"""The outer gate every reader takes is the one the PSID play address enters.

Bump_Set_Spike carries two `RTS`-form gates back to back, the NTSC
compensator's first and the PAL one the play address names:

    B006  LDA $02A6 / BNE $B016           ; PAL -> skip the NTSC gate
    B00B  DEC $B4F5 / BPL $B016 / LDA #$05 / STA $B4F5 / RTS     (NTSC)
    B016  DEC $B4F4 / BPL $B021 / LDA #$09 / STA $B4F4 / RTS     (play, PAL)

`_find_outer_gate` and `nibble_gate_byte` took the first `search` hit, the
NTSC gate's reload 5 (the per-subtune table behind the PAL one, `$B4F0`, says
9 and 3), so the row came out 3 x 6/5 = 18/5 frames where the original's is
3 x 10/9 = 10/3: `-S5` for a tune that wants `-S3`. At 60 s through the packed
file the onsets were 3/214, 2/257 and 1/197 exact on the three voices, the
offset growing with every row (-1195 frames by the end of the dump); with the
play entry's gate read, 219/219, 278/278 and 214/214.

The reading is `tempo.outer_gate_match`; `call_phase.entry_gate` takes the same
one, so the startup-row model and the tempo can never disagree about which
gate is "the" gate.
"""
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import arpeggio, call_phase, tempo       # noqa: E402
from h2g.goatwriter.constants import (OUTER_GATE,            # noqa: E402
                                      OUTER_GATE_RTS)
from h2g.sidfile import HLEN, SidFile, load_sid              # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _rts_gate(cell: int, reload: int) -> bytes:
    """`DEC cell / BPL +6 / LDA #reload / STA cell / RTS` (11 bytes)."""
    lo, hi = cell & 0xFF, cell >> 8
    return bytes([0xCE, lo, hi, 0x10, 0x06, 0xA9, reload, 0x8D, lo, hi, 0x60])


def _two_gates(play: int) -> SidFile:
    """NTSC-style gate at $1000 (reload 5), the PAL one at $100B (reload 9),
    a `JMP $100B` at $1030 and an `NOP` at $1040."""
    image = bytearray(0x100)
    image[0x00:0x0B] = _rts_gate(0x1090, 5)
    image[0x0B:0x16] = _rts_gate(0x1091, 9)
    image[0x30:0x33] = bytes([0x4C, 0x0B, 0x10])
    image[0x40] = 0xEA
    return SidFile(path="synthetic", data=bytes(HLEN - 1) + bytes(image),
                   name="", author="", released="", load_addr=0x1000,
                   subtunes=1, play_addr=play)


# --- which gate is read -------------------------------------------------------

@pytest.mark.parametrize("play,reload,gate_at", [
    (0x100B, 9, 0x0B),        # the play address IS the second gate
    (0x1030, 9, 0x0B),        # a jump table in front of it is followed
    (0x1000, 5, 0x00),        # the first gate IS the entry: unchanged
    (0x1040, 5, 0x00),        # entry is no gate: the first match, as before
])
def test_the_gate_the_play_routine_enters_is_the_one_read(play, reload, gate_at):
    sid = _two_gates(play)
    m = tempo.outer_gate_match(sid)
    assert m is not None and m.re is OUTER_GATE_RTS
    assert m.start() == HLEN - 1 + gate_at
    assert tempo.outer_gate_skip(sid, 0) == reload
    assert tempo._find_outer_gate(sid, 1) == ((reload,), None)


@pytest.mark.parametrize("play,want", [(0x100B, True), (0x1030, True),
                                       (0x1000, True), (0x1040, False)])
def test_entry_gate_agrees_with_the_tempo_reading(play, want):
    # entry_gate must be the gate _find_outer_gate reads: with the entry on
    # the second gate, it is (it used to be False -- the first match sat at
    # $1000, not at the entry).
    assert call_phase.entry_gate(_two_gates(play)) is want


def test_nibble_gate_byte_reads_the_same_gate():
    # The cell is the entered gate's, not the first one's. Seed the image
    # bytes so the two cells differ.
    sid = _two_gates(0x100B)
    data = bytearray(sid.data)
    data[HLEN - 1 + 0x90] = 7              # $1090, the first gate's cell
    data[HLEN - 1 + 0x91] = 2              # $1091, the entered gate's cell
    # one store and one DEC per cell, as nibble_gate_byte requires
    sid = SidFile(path=sid.path, data=bytes(data), name="", author="",
                  released="", load_addr=0x1000, subtunes=1, play_addr=0x100B)
    assert arpeggio.nibble_gate_byte(sid) == 2


def test_a_file_with_no_gate_is_untouched():
    sid = SidFile(path="synthetic", data=bytes(HLEN - 1) + bytes(0x40),
                  name="", author="", released="", load_addr=0x1000,
                  subtunes=1, play_addr=0x1000)
    assert tempo.outer_gate_match(sid) is None
    assert tempo.outer_gate_skip(sid, 0) is None


def test_play_entry_lives_in_tempo_and_call_phase_re_exports_it():
    assert call_phase.play_entry is tempo.play_entry
    assert call_phase.PLAY_ENTRY_JMPS == tempo.PLAY_ENTRY_JMPS


# --- the corpus ---------------------------------------------------------------

@needs_corpus
def test_only_bump_set_spike_changes_which_gate_is_read():
    """Over the whole corpus, `outer_gate_match` is the old first `search`
    hit for every file but Bump_Set_Spike."""
    moved = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        old = OUTER_GATE.search(sid.data) or OUTER_GATE_RTS.search(sid.data)
        new = tempo.outer_gate_match(sid)
        if (old is None) != (new is None) or (
                old is not None and old.start() != new.start()):
            moved.append(path.name)
    assert moved == ["Bump_Set_Spike.sid"]


@needs_corpus
def test_bump_set_spike_reads_the_pal_gate():
    sid = load_sid(str(CORPUS / "Bump_Set_Spike.sid"))
    at = tempo.play_entry(sid)
    assert at == sid.to_offset(0xB016) == tempo.outer_gate_match(sid).start()
    # DEC $B4F4 -- the PAL gate's cell, not the NTSC one's $B4F5.
    assert tempo.outer_gate_match(sid).group(1) == bytes([0xF4, 0xB4])
    # The per-subtune table behind the PAL gate's immediate: 9 and 3.
    assert tempo._find_outer_gate(sid, sid.subtunes) == ((9, 3), 0xB4F0)
    assert tempo.outer_gate_skip(sid, 0) == 9
    assert arpeggio.nibble_gate_byte(sid) == sid.data[sid.to_offset(0xB4F4)]
    assert call_phase.entry_gate(sid)


@needs_corpus
def test_bump_set_spike_rows_and_the_pack_factor():
    sid, det = (lambda s: _detect_tables(s, lambda *_: None))(
        load_sid(str(CORPUS / "Bump_Set_Spike.sid")))
    speeds = tempo.find_song_speeds(sid, det)
    assert speeds.skip == (9, 3)
    # inner gate 3 and 2 frames x (skip + 1) / skip
    assert [tempo.effective_frames(speeds, s, True) for s in range(2)] \
        == [Fraction(10, 3), Fraction(8, 3)]
    # one factor serves both subtunes' denominators; it was -S5 (18/5, 12/5)
    assert tempo.file_multiplier(sid, speeds, True) == 3


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_bump_set_spike_onsets_land_on_the_originals_frames(tmp_path):
    """Frame against frame, every onset on every voice, over 60 s. The pack
    factor is the one the converter derives (`file_multiplier`), not the
    shipped presets.json's `multiplier`, which `presets.py` records."""
    name = "Bump_Set_Spike.sid"
    sid, det = _detect_tables(load_sid(str(CORPUS / name)), lambda *_: None)
    m = tempo.file_multiplier(sid, tempo.find_song_speeds(sid, det), True)
    assert m == 3
    import json
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / name), log=lambda x: None,
                  **fidelity._preset_opts(doc, name))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / name, 60, 0, calls=1)
    ours = fidelity.run_siddump(packed, 60, 0, calls=m)
    lag, raw = fidelity.startup_lag(orig, ours)
    for a, b in zip(orig, ours):
        assert len(a.attack_frames) > 200
        assert len(a.attack_frames) == len(b.attack_frames)
        assert [x - lag for x in b.attack_frames] == a.attack_frames
