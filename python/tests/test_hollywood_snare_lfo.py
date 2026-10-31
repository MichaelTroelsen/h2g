"""Hollywood or Bust: the snare's top note, its noise alternation, the LFO lead.

Three readings of the command-table player (Hollywood or Bust, Chicken Song),
each measured on the original with siddump (sub 2, PAL; run record
hollywood-snare-and-lfo-vibrato):

* **The snare plays A-7, a note the note column cannot hold.** Record 10's
  pattern note is `$5D`, entry 93 (`$EA30`); the decoder clamped it to G#7
  (`$DD0E`), a semitone low on 124 of 375 hits. The command-table decoder
  now records such rows (`top_rows`) as the classic one does, and
  `past_table_wave` plays the entry from the wavetable.
* **Bit $02's derived noise carries bit $04's arpeggio.** `$0774` alternates
  the waveform with `(wave & 7) | $80` on the global counter's odd frames,
  and `$0792`'s nibble arpeggio tests the SAME counter (`AND #mask / BNE`):
  at mask $01 the note lowered by the nibble sounds on the record's own
  waveform's frames. Record 9 (`$D6`, nibble 13) reads `0C4E/11 1A13/81` in
  the original; `convert(wave_alternate=True)` emitted the noise and dropped
  the arpeggio (`1A15` every frame), which is what cost the option its melody.
* **The LFO vibrato as a per-frame program** (`convert(lfo_wave=True)`,
  goatwriter.lfo_wave): record 6 (`$14`, table 1 `00 01 02 01 00 81`, count
  4) reads `684C 66D8 684C 69C0 6B34 69C0` from each onset; Goattracker's
  vibrato under the plain program's note steps held it but for one frame.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g import patterns as P  # noqa: E402
from h2g.detect import _wave_alt_arp, detect  # noqa: E402
from h2g.goatwriter import lfo_wave as L  # noqa: E402
from h2g.goatwriter.appending import _parse_song  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR, WAVECMD_PORTADOWN,  # noqa: E402
                                      WAVECMD_PORTAUP)
from h2g.goatwriter.wavetable import _wavetable_entries  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
HOLLYWOOD = CORPUS / "Hollywood_or_Bust.sid"
CHICKEN = CORPUS / "Chicken_Song.sid"
needs_corpus = pytest.mark.skipif(not HOLLYWOOD.exists(),
                                  reason="the Hubbard corpus is not on this machine")


def _load(path):
    sid = load_sid(str(path))
    return sid, detect(sid, log=lambda m: None)


def _convert(path, **over):
    import fidelity as F
    from h2g.convert import convert
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    lines: list = []
    opts = {**F._preset_opts(doc, path.name), **over}
    return convert(str(path), log=lines.append, **opts), lines


# --- the top note -----------------------------------------------------------

def _cmd_events(stream: bytes, **kw):
    # offset 2: the duration table (one entry, 6 frames); the pattern at 3.
    data = bytes([0, 0, 6]) + stream
    top: dict = {}
    # 6 frames a row: one row per note.
    events = P._build_raw_pattern_cmdtable(data, 3, 2, (1,), 0, 6,
                                           top_rows=top, **kw)
    return events, top, data


def test_the_cmdtable_decoder_records_an_entry_above_92_and_clamps_it():
    # status $00 (duration 0, a note follows): notes $5D, $5C, $5F, $30.
    events, top, _ = _cmd_events(bytes([0, 0x5D, 0, 0x5C, 0, 0x5F, 0, 0x30,
                                        0xFF]))
    notes = [events[k] for k in range(0, len(events) - 4, 4) if events[k]]
    assert notes == [0xBC, 0xBC, 0xBC, 0x90]
    assert top == {0: 1, 2: 3}           # rows of the 1st and 3rd notes


def test_asking_for_the_record_moves_no_byte():
    events, _top, data = _cmd_events(bytes([0, 0x5F, 0, 0x30, 0xFF]))
    assert events == P._build_raw_pattern_cmdtable(data, 3, 2, (1,), 0, 6)


@needs_corpus
def test_hollywood_plays_the_snares_a7_from_a_pinned_program():
    blob, lines = _convert(HOLLYWOOD)
    song = _parse_song(blob)
    wave = song.tables[0]
    pointed = 0
    for pat in song.patterns:
        for k in range(0, len(pat) - 3, 4):
            nt, _ins, cmd, data = pat[k:k + 4]
            if nt == 0xBC and cmd & 0x0F == CMD_SETWAVEPTR:
                assert wave[data - 1][1] == 0x80 | 93     # entry 93, A-7
                pointed += 1
    assert pointed == 1
    assert any("Past-table wave split" in m and "1 note row(s)" in m
               for m in lines)


# --- the derived noise and its arpeggio -------------------------------------

@needs_corpus
def test_the_arpeggio_shape_is_read_in_both_derived_files_only():
    for path, want in ((HOLLYWOOD, True), (CHICKEN, True),
                       (CORPUS / "W_A_R.sid", False),
                       (CORPUS / "Commando.sid", False)):
        assert _load(path)[1].wave_alternate_arp is want, path.name


@needs_corpus
def test_the_two_counter_loads_must_name_one_cell():
    sid, _det = _load(HOLLYWOOD)
    data = bytearray(sid.data)
    # The arpeggio's own `LDA $09A2 / AND #mask / BNE` -- repoint it.
    off = sid.to_offset(0x07AE)
    assert data[off:off + 4] == bytes.fromhex("AD A2 09 29")
    assert _wave_alt_arp(bytes(data), "AD A0 09")
    data[off + 1] = 0xA3
    assert not _wave_alt_arp(bytes(data), "AD A0 09")


@needs_corpus
def test_record_9s_lowered_note_rides_its_own_waveform():
    """`0C4E/11 1A13/81`: the note minus 13 on the record's own waveform,
    the note itself on the noise -- the derived pair with bit $04 riding."""
    sid, det = _load(HOLLYWOOD)
    on = _wavetable_entries(sid, det, 9, True, "gts5", [], 1, start=6,
                            budget=12, wave_alternate=True,
                            no_test_restart=True)
    assert on == ([0x11, 0x81, 0xFF], [0x80 - 13, 0x00, 6])
    # Record 10's nibble is 0: nothing to ride, the pair is the note's.
    on = _wavetable_entries(sid, det, 10, True, "gts5", [], 1, start=6,
                            budget=12, wave_alternate=True,
                            no_test_restart=True)
    assert on == ([0x15, 0x85, 0xFF], [0x00, 0x00, 6])


@needs_corpus
def test_the_wave_alternate_option_still_moves_only_the_two_files():
    for path, moves in ((HOLLYWOOD, True), (CORPUS / "W_A_R.sid", False)):
        off, _ = _convert(path, wave_alternate=False)
        on, _ = _convert(path, wave_alternate=True)
        assert (on != off) is moves, path.name


# --- the LFO program ---------------------------------------------------------

@needs_corpus
def test_the_walk_reads_the_table_as_the_player_does():
    sid, det = _load(HOLLYWOOD)
    tv = det.table_vibrato
    assert tv.index_cell == 0x09B1 and det.cmd_instr_cell == 0x097D
    assert tv.bases == (0x09D3, 0x09D8, 0x09DF, 0x09E8)
    # Table 1 from index 4: `00 81`, then `$FF` resets to 0 and reads again.
    values, at = L._walk_reads(sid, tv.bases[1], 4, 8)
    assert values == [0, -1, 0, 1, 2, 1, 0, -1]
    assert at == [4, 5, 0, 1, 2, 3, 4, 5]


@needs_corpus
def test_which_records_qualify():
    sid, det = _load(HOLLYWOOD)
    got = [i for i in range(det.instr_used + 1)
           if L.lfo_record(sid, det, i, 1) is not None]
    # 5 and 11 count 3 (no power of two); 14 and 18 set effect bit $01;
    # 20 is a drum record ($33).
    assert got == [0, 6, 12]
    assert L.lfo_record(sid, det, 6, 1) == (0x09D8, 4, 2)
    assert L.lfo_record(sid, det, 6, 2) is None          # -S1 only


@needs_corpus
def test_record_6s_program_from_index_4():
    """Note, then the jump into the cycle at index 5 (frame 1 moves from
    the note to -1, the cycle's own step there), then the six steps."""
    sid, det = _load(HOLLYWOOD)
    st: list = []
    got = L.lfo_wave_entries(sid, det, 6, 4, 0x41, st, 6, 40)
    U, D = WAVECMD_PORTAUP, WAVECMD_PORTADOWN
    assert got == ([0x41, 0xFF, U, U, U, D, D, D, 0xFF],
                   [0x00, 8 + 5, 1, 1, 1, 1, 1, 1, 8])
    assert st == [(0x80, 2)]         # (interval above) >> 2: count 4 / 16
    # Positions it plays from the note: 0 -1 0 1 2 1, the original's.
    left, right = got
    pos, row, out = 0, 7, [0]
    for _ in range(5):
        if left[row - 6] == 0xFF:
            row = right[row - 6]
        pos += 1 if left[row - 6] == U else -1
        out.append(pos)
        row += 1
    assert out == [0, -1, 0, 1, 2, 1]


@needs_corpus
def test_a_program_that_does_not_fit_is_declined_and_adds_no_speed_row():
    sid, det = _load(HOLLYWOOD)
    st: list = []
    assert L.lfo_wave_entries(sid, det, 6, 4, 0x41, st, 6, 8) is None
    assert st == []


@needs_corpus
def test_the_walk_puts_the_lead_on_index_4():
    """Measured: every onset of record 6 in sub 2 but the 3-frame pairs
    opens on index 4 (`0 -1 0 1 2 1`)."""
    # The programs are laid out under no_test_restart only (build_sng), and
    # the preset's aligned_firstwave overrides it: measured with it off.
    blob, lines = _convert(HOLLYWOOD, lfo_wave=True, aligned_firstwave=False)
    msg = next(m for m in lines if m.startswith("LFO wave programs"))
    gt = {int(tok.split()[0], 16): int(tok.split()[-1])
          for tok in msg.split(": ", 1)[1].split(", ")}
    # Records 0, 6 and 12 under compact numbering; the lead is record 6.
    assert gt == {0x01: 2, 0x07: 4, 0x0D: 8}
    assert any("LFO wave phases" in m for m in lines)


@needs_corpus
def test_a_program_record_gets_no_goattracker_vibrato():
    from h2g.goatwriter.vibrato import _vibrato_layout
    sid, det = _load(HOLLYWOOD)
    full = _vibrato_layout(sid, det, det.instr_used + 2, True, "gts5", 1, [])
    skip = _vibrato_layout(sid, det, det.instr_used + 2, True, "gts5", 1, [],
                           skip=frozenset({0, 6, 12}))
    assert {0, 6, 12} <= set(full)
    assert set(full) - set(skip) == {0, 6, 12}


@needs_corpus
def test_a_shared_row_under_two_records_gets_no_pointer():
    """One pattern row cannot say two programs: a pattern two tracks play
    under different instruments keeps the instrument's own on every visit."""
    sid, det = _load(HOLLYWOOD)
    det.frames_per_row = 3
    lead = 1
    lfo_gt, other_gt = 6 + lead + 1, 1 + lead + 1      # record 6, record 1
    det.lfo_wave_phases = {lfo_gt: 4}       # voice 0's image index
    note = [0x60 + 40, 0, 0, 0]
    shared = bytes(note + [0xBD, 0, 0, 0] + [0xFF, 0, 0, 0])
    lat_lfo = bytes([0x60 + 30, lfo_gt, 0, 0, 0xFF, 0, 0, 0])
    lat_other = bytes([0x60 + 30, other_gt, 0, 0, 0xFF, 0, 0, 0])
    patterns = [list(shared), list(lat_lfo), list(lat_other)]
    tracks = [[1, 0, 0xFF, 0], [2, 0, 0xFF, 0], [0xFF, 0]]
    arps: list = []
    out = L.lfo_phase_pointers(sid, det, tracks, patterns, lead, 1, arps)
    assert out[0][:4] == note and arps == []
    # ... and played under the LFO record alone, it is pointed.
    tracks = [[1, 0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    out = L.lfo_phase_pointers(sid, det, tracks, patterns, lead, 1, arps)
    assert out[0][2] == CMD_SETWAVEPTR and len(arps) == 1
    assert isinstance(arps[0][1], L.LfoPhase) and arps[0][0] == 6


@needs_corpus
def test_off_by_default_and_inert_on_commando():
    off, _ = _convert(HOLLYWOOD)
    assert off == _convert(HOLLYWOOD, lfo_wave=False)[0]
    # Inert under the preset's aligned_firstwave (it overrides the
    # no_test_restart the programs need); live without it.
    assert off == _convert(HOLLYWOOD, lfo_wave=True)[0]
    ntr, _ = _convert(HOLLYWOOD, aligned_firstwave=False)
    assert ntr != _convert(HOLLYWOOD, lfo_wave=True,
                           aligned_firstwave=False)[0]
    com = CORPUS / "Commando.sid"
    assert _convert(com, lfo_wave=True)[0] == _convert(com)[0]


def test_it_is_per_song_and_not_searched():
    import presets
    assert "lfo_wave" in presets.EXCLUDED_FROM_ALWAYS
    assert "lfo_wave" in presets.CARRIED_PER_SONG
    assert "lfo_wave" not in presets.FIDELITY_TOGGLES
    assert "lfo_wave" not in presets.FIXED


@needs_corpus
def test_frame_1_moves_from_the_note_where_the_index_opens_off_zero():
    """Record 0 from index 2 (table 2, value 2 there): frame 0 is the note
    itself, so frame 1 moves +1 to the next index's value, 1 -- a lead step
    the cycle does not hold -- and the walk is on the cycle from index 4."""
    sid, det = _load(HOLLYWOOD)
    st: list = []
    got = L.lfo_wave_entries(sid, det, 0, 2, 0x41, st, 6, 40)
    U, D = WAVECMD_PORTAUP, WAVECMD_PORTADOWN
    assert got == ([0x41, U, 0xFF, U, U, U, D, D, D, D, U, 0xFF],
                   [0x00, 1, 9 + 4, 1, 1, 1, 1, 1, 1, 1, 1, 9])
