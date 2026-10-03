"""A note byte past the frequency table sounds whatever cell it lands on, and
one of those cells is silence.

The classic players' note fetch is `ASL / TAY / LDA freqtbl,Y` with no bound
(patterns.py, the clamp's own census: 24 corpus files index past their 96-entry
table). Commando's `$68` lands on a per-voice stored-waveform cell and sounds
B-5. Sanxion's `$60` lands on `$B50D`/`$B50E` -- `$00 $00` in the file, named
by no instruction -- and the original writes frequency `$0000` with the gate
on: a drum whose pulse frames are DC, `0000 C-0` in siddump on voice 2, 150
frames of it in 180 s. The clamp turned that into GT index 92, a G#7 pulse,
on six pattern entries.

`patterns.past_table_rests` is the rule: a past-table byte whose landing cell
is a constant `$0000` -- zero in the file AND unnamed by any absolute-operand
instruction -- is decoded as a KEYOFF, and `goatwriter.past_table_drum_plan`
re-emits it as a note on a variant instrument wherever the instrument's wave
program sounds an absolute-pitch frame (Sanxion's noise drum; see
test_sanxion_six_entries_rest_where_the_clamp_sounded_g_sharp_7). These tests
pin the static reading on
Sanxion, the six entries it reaches, both halves of the rule, and that
Commando (whose cell is written by `$515A STA $54F8,X`) does not qualify.
"""
import pathlib
import sys
from dataclasses import replace

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import songview  # noqa: E402
from h2g import goatwriter as gw  # noqa: E402
from h2g import patterns  # noqa: E402
from h2g.convert import convert  # noqa: E402
from h2g.detect import detect  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"
SANXION = CORPUS / "Sanxion.sid"

# Sanxion's table and the cell its `$60` reads. Read out of the file by
# `find_freq_table`, and re-read here so the numbers in the docstring are
# checked rather than quoted.
SANXION_TABLE = 0xB44D
SANXION_CELL = 0xB50D          # SANXION_TABLE + 2 * 96
# Table entry (hex) -> the row its `$60` event lands on, in the decoded
# stream before slicing. Six entries, one row each.
SANXION_SIX = {0x1: 20, 0x3: 20, 0x4: 20, 0x6: 20, 0x7: 20, 0x8: 20}
G_SHARP_7 = patterns.GT_FIRSTNOTE + 92
# The GT instrument the six drum rows play (record 0 under
# --compact-instruments), its wave program as converted, and the variant's:
# the two `$41` frames the note pitches -- at `$0000` in the original, DC --
# become `$09` (`$E9` in the table: test bit, gate kept), and the absolute
# B-5 noise frame the original sounds stays.
SANXION_DRUM_RECORD = 1
SANXION_RECORD_WAVE = [(0x41, 0x00), (0x81, 0xC7), (0x41, 0x00), (0xFF, 0x00)]
SANXION_VARIANT_WAVE = [(0xE9, 0x00), (0x81, 0xC7), (0xE9, 0x00), (0xFF, 0x00)]
PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"


def _preset_opts(name):
    import json
    import fidelity as F
    return F._preset_opts(json.loads(PRESETS.read_text(encoding="utf-8")),
                          name)


def _sanxion():
    sid = load_sid(str(SANXION))
    return sid, detect(sid, log=lambda m: None)


@needs_corpus
def test_sanxion_byte_60_lands_on_two_zero_bytes_nothing_names():
    sid, det = _sanxion()
    ft = det.freq_table
    assert ft is not None
    assert (ft.addr, ft.length) == (SANXION_TABLE, 96)
    cell = sid.to_offset(SANXION_CELL)
    assert sid.data[cell:cell + 2] == b"\x00\x00"
    # The cell -- and a per-voice `base,X` reaching it with X up to 2 -- is
    # named by no absolute-operand instruction in the file.
    assert patterns._absolute_references(sid.data, SANXION_CELL - 2,
                                         SANXION_CELL + 1) == 0
    assert patterns.past_table_rests(sid, det) == frozenset({96})


@needs_corpus
def test_sanxion_six_entries_rest_where_the_clamp_sounded_g_sharp_7():
    """The six drum entries' `01 60` at row 20 -- and what the CONVERSION
    finally emits there.

    The decoder still writes a KEYOFF carrying the record's number: that is
    the shape `goatwriter.past_table_drum_plan` keys on, and the decode-level
    half below pins it. But the KEYOFF is no longer what the file says.
    RETRACTED as the emitted row (found wrong at e362bd6, re-measured in
    C:/t/sanxion-noise-drum): the original's `$60` is a note-on at frequency
    `$0000` whose record-0 wave program `41 / 81 at absolute B-5 / 41 / stop`
    sounds a noise frame at `41B8` on siddump's third voice -- 41 in 100 s,
    first at frame 645 -- and the KEYOFF sounded none. The emitted row is a
    note on a VARIANT of record 0 whose pitched frames are test-bit silence
    (`$09`: test bit, gate kept as the original's `$41` keeps it) and whose
    absolute frame is kept, with the record's own pulse pointer so the
    note-on reseeds the pulse as the original's does.
    """
    sid, det = _sanxion()
    hits = {}
    for i in range(det.pattern_used):
        ev = patterns.decode_entry(sid, det, i)
        assert ev is not None, i
        rows = [k // 4 for k in range(0, len(ev), 4)
                if ev[k] == patterns.GT_KEYOFF]
        if rows:
            assert len(rows) == 1, (i, rows)
            hits[i] = rows[0]
    assert hits == SANXION_SIX
    # ...and on the same rows, the same decoder with the rule switched off
    # is the clamp: index 92, the screech. That is what the rule replaces.
    data = sid.data
    for i, row in SANXION_SIX.items():
        step = i * det.table_stride
        addr = sid.to_offset(data[det.pattern_hi + step] * 256
                             + data[det.pattern_lo + step])
        kw = dict(note_flag=det.note_flag, status_bit6=det.status_bit6,
                  instr_mask=patterns._instrument_mask(det.instr_stride))
        ev = patterns._build_raw_pattern(data, addr, rest_notes=frozenset(),
                                         **kw)
        assert ev[4 * row] == G_SHARP_7, (i, row, ev[4 * row:4 * row + 4])
        ev = patterns._build_raw_pattern(data, addr,
                                         rest_notes=frozenset({96}), **kw)
        assert ev[4 * row] == patterns.GT_KEYOFF, (i, row)
    # What the file emits under presets.json: no KEYOFF carrying a record's
    # number survives, and six rows are a note on the variant -- one per
    # drum entry, each at row 20 of its pattern.
    song = songview.parse_sng(convert(str(SANXION), log=lambda m: None,
                                      **_preset_opts("Sanxion.sid")))
    wave = song.tables["WTBL"]
    # Found by its wave block, not by position: the variant was the last
    # instrument until the legato-tie clones (`goatwriter.legato_tie_clones`)
    # started appending after it -- Sanxion carries two.
    found = [k for k, ins in enumerate(song.instruments, 1)
             if wave[ins.wave_ptr - 1:ins.wave_ptr + 3] == SANXION_VARIANT_WAVE]
    assert len(found) == 1, found
    variant = found[0]
    record = song.instruments[SANXION_DRUM_RECORD - 1]
    drum = song.instruments[variant - 1]
    assert wave[record.wave_ptr - 1:record.wave_ptr + 3] == SANXION_RECORD_WAVE
    assert wave[drum.wave_ptr - 1:drum.wave_ptr + 3] == SANXION_VARIANT_WAVE
    # Everything but the wave pointer is the record's: envelope, pulse
    # pointer (the reseed), filter, vibrato, gate timer, firstwave.
    assert (replace(drum, number=0, wave_ptr=0)
            == replace(record, number=0, wave_ptr=0))
    rows, keyoffs = [], 0
    for pat in song.patterns:
        for k in range(0, len(pat) - 3, 4):
            if pat[k] == patterns.GT_KEYOFF and pat[k + 1]:
                keyoffs += 1
            if pat[k + 1] == variant:
                rows.append(k // 4)
                assert pat[k] == patterns.GT_FIRSTNOTE, k // 4
                # The record is named again on the voice's next note, so
                # the variant's number does not latch past the drum.
                nxt = next(j for j in range(k + 4, len(pat), 4)
                           if pat[j + 1] or pat[j] <= patterns.GT_LASTNOTE)
                assert pat[nxt + 1] == SANXION_DRUM_RECORD
    assert keyoffs == 0
    assert rows == [20] * len(SANXION_SIX)


@needs_corpus
def test_the_rule_needs_both_halves():
    # Half one: the cell must be zero in the file. One byte of it set, and
    # the original would sound a pitch there, so the byte is a note again
    # and the clamp is the right answer for it.
    sid, det = _sanxion()
    cell = sid.to_offset(SANXION_CELL)
    patched = bytearray(sid.data)
    patched[cell + 1] = 0x07
    assert 96 not in patterns.past_table_rests(
        replace(sid, data=bytes(patched)), det)
    # Half two: nothing may name the cell. An `STA $B50D` anywhere in the
    # file -- here written over the last three bytes, where nothing this
    # reading depends on lives -- makes it a variable, not a constant.
    patched = bytearray(sid.data)
    patched[-3:] = bytes((0x8D, SANXION_CELL & 0xFF, SANXION_CELL >> 8))
    assert 96 not in patterns.past_table_rests(
        replace(sid, data=bytes(patched)), det)
    # A per-voice store two bytes below the cell reaches it with X=2 and is
    # refused on the same grounds.
    patched = bytearray(sid.data)
    patched[-3:] = bytes((0x9D, (SANXION_CELL - 2) & 0xFF,
                          (SANXION_CELL - 2) >> 8))
    assert 96 not in patterns.past_table_rests(
        replace(sid, data=bytes(patched)), det)


def test_commando_byte_68_is_a_note_not_a_rest():
    # The fixture file, so this runs wherever the repo does. Commando's `$68`
    # lands on the per-voice stored-waveform cells `$54F8`/`$54F9`, which
    # `$515A STA $54F8,X` writes -- the reading in the clamp's own comment.
    # Whatever the cell holds at load time, it is named, so it is not a
    # constant and the byte is not a rest. The byte-exact fixture
    # (test_commando.py) is what this keeps green.
    sid = load_sid(str(COMMANDO))
    det = detect(sid, log=lambda m: None)
    assert det.freq_table is not None
    assert patterns._absolute_references(sid.data, 0x54F8 - 2, 0x54F8 + 1) > 0
    assert patterns.past_table_rests(sid, det) == frozenset()


def test_the_default_is_the_clamp():
    # `_build_raw_pattern` with no `rest_notes` is the historical decoder: a
    # `$60` clamps to index 92. A two-event pattern: `01 60` then `FF`.
    ev = patterns._build_raw_pattern(bytes((0, 0, 0x01, 0x60, 0xFF)), 2)
    assert ev[0] == G_SHARP_7
    ev = patterns._build_raw_pattern(bytes((0, 0, 0x01, 0x60, 0xFF)), 2,
                                     rest_notes=frozenset({0x60}))
    assert ev[0] == patterns.GT_KEYOFF


@needs_corpus
def test_reach_is_four_files_decoded_and_one_played():
    # Where the rule reaches, corpus-wide, at the DECODE level: every entry
    # of every classic-dialect file. Four files carry a qualifying byte in
    # some table entry; in three of them the entry is one no orderlist
    # plays (pruned, or a phantom), so the corpus byte-hash under
    # presets.json at v0.5.482 named exactly one file moved: Sanxion. The
    # set is pinned so a change in reach is a change someone has to explain.
    hit = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, log=lambda m: None)
        except Exception:  # noqa: BLE001 -- the six non-Hubbard files
            continue
        if det.freq_table is None or det.pattern_dialect != "classic":
            continue
        if not patterns.past_table_rests(sid, det):
            continue
        for i in range(max(det.pattern_used, 0)):
            ev = patterns.decode_entry(sid, det, i)
            if ev and any(ev[k] == patterns.GT_KEYOFF
                          for k in range(0, len(ev), 4)):
                hit.add(path.name)
                break
    assert hit == {"BMX_Kidz.sid", "Kings_of_the_Beach_ingame.sid",
                   "Ricochet.sid", "Sanxion.sid"}


# ---------------------------------------------------------------------------
# The past-table drum: `goatwriter.past_table_drum_plan` re-emits the KEYOFF
# above as a note on a variant of its record, wherever the record's wave
# program sounds an absolute-pitch frame (`_past_table_drum_block`).
# ---------------------------------------------------------------------------

def test_the_variant_silences_the_pitched_frames_and_keeps_the_absolute():
    table = SANXION_RECORD_WAVE + [(0x11, 0x00)]
    assert gw._past_table_drum_block(table, 1) == SANXION_VARIANT_WAVE
    # A gate-off frame keeps its gate bit off: `$40` -> `$08` (`$E8`).
    assert gw._past_table_drum_block(
        [(0x40, 0x00), (0x81, 0xC7), (0xFF, 0x00)], 1) == [
            (0xE8, 0x00), (0x81, 0xC7), (0xFF, 0x00)]
    # `$80` keeps the last pitch written: after the absolute frame it is
    # still B-5 and audible, so it stays; a command passes through.
    assert gw._past_table_drum_block(
        [(0x41, 0x00), (0x81, 0xC7), (0x41, 0x80), (0xF1, 0x02),
         (0xFF, 0x00)], 1) == [
            (0xE9, 0x00), (0x81, 0xC7), (0x41, 0x80), (0xF1, 0x02),
            (0xFF, 0x00)]


def test_the_variant_declines_what_it_cannot_say():
    # No absolute frame: the variant would be silence, which the KEYOFF is.
    assert gw._past_table_drum_block([(0x41, 0x00), (0xFF, 0x00)], 1) is None
    # A delay that writes the note's pitch under an audible waveform would
    # need that waveform changed, which only a waveform byte can do.
    assert gw._past_table_drum_block(
        [(0x81, 0xC7), (0x03, 0x00), (0xFF, 0x00)], 1) is None
    # A loop is walked once only, so it is refused.
    assert gw._past_table_drum_block(
        [(0x41, 0x00), (0x81, 0xC7), (0xFF, 0x01)], 1) is None
    # Nothing stops it within the table.
    assert gw._past_table_drum_block([(0x41, 0x00), (0x81, 0xC7)], 1) is None


@needs_corpus
def test_the_plan_names_the_record_again_before_the_next_note():
    # The variant's number latches for the voice (gplay.c:912-913), so the
    # next note must name the record again; one that does not gets it
    # written in, and a drum with no row left to do it keeps the KEYOFF.
    sid, det = _sanxion()
    wave = SANXION_RECORD_WAVE
    end = [0xFF, 0, 0, 0]
    pats = [
        [0x70, 1, 0, 0, patterns.GT_KEYOFF, 1, 0, 0, 0xBD, 0, 0, 0,
         0x72, 0, 0, 0] + end,
        [0x70, 1, 0, 0, patterns.GT_KEYOFF, 1, 0, 0, 0xBD, 0, 0, 0] + end,
    ]
    out, variants = gw.past_table_drum_plan(
        sid, det, pats, [[0, 1, 0xFF, 0]], list(wave), [1], 0, 1, 2)
    assert variants == [(1, 2, SANXION_VARIANT_WAVE)]
    assert out[0][4:8] == [patterns.GT_FIRSTNOTE, 2, 0, 0]
    assert out[0][12:14] == [0x72, 1]
    assert out[1] is pats[1]
    # A transpose below zero lifts the note so it stays a real one.
    out, _ = gw.past_table_drum_plan(
        sid, det, pats, [[0xEC, 0, 0xFF, 0]], list(wave), [1], 0, 1, 2)
    assert out[0][4] == patterns.GT_FIRSTNOTE + 4
    # A file with no past-table rest byte is returned untouched.
    cell = sid.to_offset(SANXION_CELL)
    patched = bytearray(sid.data)
    patched[cell + 1] = 0x07
    sid0 = replace(sid, data=bytes(patched))
    assert patterns.past_table_rests(sid0, det) == frozenset()
    assert gw.past_table_drum_plan(
        sid0, det, pats, [[0, 1, 0xFF, 0]], list(wave), [1], 0, 1, 2) == (
            pats, [])


@needs_corpus
def test_only_a_past_table_rest_writes_a_keyoff_with_an_instrument(
        monkeypatch):
    # The plan keys on the shape "KEYOFF carrying an instrument number". It
    # is the rule's alone: with `past_table_rests` stood down, no entry of
    # any classic-dialect file decodes to it under the presets' grammar --
    # `rest_keyoff`, the bit-6 rest, writes `00` there.
    grammar = dict(GRAMMAR, rest_keyoff=True, rest_instrument=True)
    real = patterns.past_table_rests
    with_rule, without = set(), set()
    for path, sid, det in _classic_corpus():
        for i in range(max(det.pattern_used, 0)):
            for fn, seen in ((real, with_rule),
                             (lambda s, d: frozenset(), without)):
                monkeypatch.setattr(patterns, "past_table_rests", fn)
                ev = patterns.decode_entry(sid, det, i, **grammar)
                if ev and any(ev[k] == patterns.GT_KEYOFF and ev[k + 1]
                              for k in range(0, len(ev) - 3, 4)):
                    seen.add(path.name)
    assert without == set()
    assert "Sanxion.sid" in with_rule


# ---------------------------------------------------------------------------
# The other half of the same reading: a past-table byte on a constant cell
# that is NOT zero sounds that cell's pitch, and `patterns.past_table_notes`
# re-reads it as the nearest entry of the player's own table.
#
# In Proteus, Warhawk and Thing_on_a_Spring the byte `$60` lands exactly on
# the player's per-voice offset table `00 07 0E`, which follows the frequency
# table and is read by `LDA offsets,X` and written by nothing. The original
# sounds `$0700` there -- siddump at -m1 over 180 s shows `0700 G#2` at 48 /
# 29 / 114 gate-on edges (Proteus v3, Warhawk v3, Thing v2) -- 23 cents above
# entry 32, G#2. The clamp made every one of them G#7. Measured at 50a6178
# under presets.json at -t 180, G#2 against the clamp: melody 87->88 / 89->90
# / 93->98 %, sequence 77->89 / 81->90 / 94->98 %, and `our_noise_pitch`
# moved toward the original on all three (Warhawk 12604 -> 10599 against
# 10590). The corpus byte-hash under presets named exactly the three;
# Commando.sng did not move.
# ---------------------------------------------------------------------------

THREE = {
    # file: (table address, cell `$60` lands on = table + 2 * 96)
    "Proteus.sid": (0x0CA3, 0x0D63),
    "Warhawk.sid": (0x14AC, 0x156C),
    "Thing_on_a_Spring.sid": (0xC3A9, 0xC469),
}
G_SHARP_2 = patterns.GT_FIRSTNOTE + 32
# Table entry (hex) -> rows its `$60` events land on, decoded under the
# presets' grammar (slides + status_bit6, the always block). Warhawk under
# the DEFAULT grammar also moves entries 32-34, but those are a two-byte
# slide operand mis-read as a note -- `slides` reads it correctly and they
# vanish, which is why the grammar is pinned here.
THREE_ROWS = {
    "Proteus.sid": {0x15: [8, 24], 0x18: [8, 24], 0x1A: [8, 24]},
    "Warhawk.sid": {0x15: [8, 24], 0x18: [8, 24], 0x1A: [8, 24]},
    "Thing_on_a_Spring.sid": {0x1B: [3, 12, 21, 27, 36, 45]},
}
GRAMMAR = dict(slides=True, status_bit6=True)


def _load(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, log=lambda m: None)


@needs_corpus
@pytest.mark.parametrize("name", sorted(THREE))
def test_byte_60_lands_on_the_offset_table_a_load_names(name):
    sid, det = _load(name)
    table, cell = THREE[name]
    ft = det.freq_table
    assert (ft.addr, ft.length) == (table, 96)
    off = sid.to_offset(cell)
    assert sid.data[off:off + 3] == b"\x00\x07\x0e"
    # A LOAD names the cell (the player's `LDA offsets,X`), so the rest
    # rule's predicate refuses it -- correctly, it is not a rest...
    assert patterns._absolute_references(sid.data, cell - 2, cell + 1) > 0
    assert 96 not in patterns.past_table_rests(sid, det)
    # ...and no WRITER names it, so it is a constant, and the constant is
    # `$0700`: nearest the player's own entry 32.
    assert patterns._absolute_writers(sid.data, cell - 2, cell + 1) == 0
    assert patterns.past_table_notes(sid, det)[0x60] == 32


@needs_corpus
@pytest.mark.parametrize("name", sorted(THREE))
def test_the_three_sound_g_sharp_2_where_the_clamp_sounded_g_sharp_7(
        name, monkeypatch):
    sid, det = _load(name)
    real = patterns.past_table_notes
    hits = {}
    for i in range(det.pattern_used):
        monkeypatch.setattr(patterns, "past_table_notes", real)
        on = patterns.decode_entry(sid, det, i, **GRAMMAR)
        monkeypatch.setattr(patterns, "past_table_notes", lambda s, d: {})
        off = patterns.decode_entry(sid, det, i, **GRAMMAR)
        assert (on is None) == (off is None), i
        if on is None:
            continue
        assert len(on) == len(off), i
        rows = [k // 4 for k in range(0, len(on), 4) if on[k] != off[k]]
        for k in range(0, len(on), 4):
            if on[k] != off[k]:
                # The note column is the only thing that moves, and it
                # moves from the clamp's G#7 to G#2 -- never anywhere else.
                assert (off[k], on[k]) == (G_SHARP_7, G_SHARP_2), (i, k // 4)
                assert on[k + 1:k + 4] == off[k + 1:k + 4], (i, k // 4)
        if rows:
            hits[i] = rows
    assert hits == THREE_ROWS[name]


@needs_corpus
def test_a_constant_note_needs_no_writer_and_a_zero_cell_is_a_rest_first():
    sid, det = _load("Proteus.sid")
    _, cell = THREE["Proteus.sid"]
    # An `STA $0D63` anywhere in the file makes the cell a variable and the
    # byte goes back to the clamp.
    patched = bytearray(sid.data)
    patched[-3:] = bytes((0x8D, cell & 0xFF, cell >> 8))
    assert 0x60 not in patterns.past_table_notes(
        replace(sid, data=bytes(patched)), det)
    # So does a per-voice `STA $0D61,X`, which reaches the cell with X=2.
    patched = bytearray(sid.data)
    patched[-3:] = bytes((0x9D, (cell - 2) & 0xFF, (cell - 2) >> 8))
    assert 0x60 not in patterns.past_table_notes(
        replace(sid, data=bytes(patched)), det)
    # A read-modify-write is a writer too: `INC $0D63`.
    patched = bytearray(sid.data)
    patched[-3:] = bytes((0xEE, cell & 0xFF, cell >> 8))
    assert 0x60 not in patterns.past_table_notes(
        replace(sid, data=bytes(patched)), det)
    # A second LOAD changes nothing: `LDA $0D63` is how the player reads it.
    patched = bytearray(sid.data)
    patched[-3:] = bytes((0xAD, cell & 0xFF, cell >> 8))
    assert patterns.past_table_notes(
        replace(sid, data=bytes(patched)), det)[0x60] == 32
    # Zero the cell and it is the rest rule's case, not this one -- and
    # since a load still names it, it is neither: back to the clamp.
    patched = bytearray(sid.data)
    patched[sid.to_offset(cell) + 1] = 0
    sid0 = replace(sid, data=bytes(patched))
    assert 0x60 not in patterns.past_table_notes(sid0, det)
    assert 96 not in patterns.past_table_rests(sid0, det)


def test_the_rest_wins_over_the_note_and_the_default_is_still_the_clamp():
    # A two-event pattern, `01 60` then `FF`, as in test_the_default_is_the_clamp.
    raw = bytes((0, 0, 0x01, 0x60, 0xFF))
    assert patterns._build_raw_pattern(raw, 2)[0] == G_SHARP_7
    assert patterns._build_raw_pattern(
        raw, 2, const_notes={0x60: 32})[0] == G_SHARP_2
    # The mapped entry takes the ordinary path: `note_base` applies to it.
    assert patterns._build_raw_pattern(
        raw, 2, const_notes={0x60: 32}, note_base=-1)[0] == G_SHARP_2 - 1
    # `rest_notes` is consulted first: a byte in both is a rest.
    assert patterns._build_raw_pattern(
        raw, 2, rest_notes=frozenset({0x60}),
        const_notes={0x60: 32})[0] == patterns.GT_KEYOFF


def test_commando_byte_68_is_not_a_constant_either():
    # Commando's `$68` cell `$54F8` is written by `$515A STA $54F8,X`, so it
    # fails the writer test exactly as it fails the rest rule's -- the
    # byte-exact fixture stays green (test_commando.py). Its `$60` DOES map
    # (the same `00 07 0E` offset table follows its 96-entry table) and no
    # Commando pattern carries a `$60`, which the fixture also pins.
    sid = load_sid(str(COMMANDO))
    det = detect(sid, log=lambda m: None)
    assert patterns._absolute_writers(sid.data, 0x54F8 - 2, 0x54F8 + 1) > 0
    notes = patterns.past_table_notes(sid, det)
    assert 0x68 not in notes
    assert notes[0x60] == 32


@needs_corpus
def test_note_reach_is_four_files_decoded_and_three_played(monkeypatch):
    # Where the constant-note rule reaches at the DECODE level under the
    # presets' grammar (slides + status_bit6), over every classic-dialect
    # corpus file: four. Ricochet's entries are ones no orderlist plays
    # (prune drops them), so the corpus byte-hash under presets.json at
    # 50a6178 named exactly Proteus, Thing_on_a_Spring and Warhawk. Pinned
    # so a change in reach is a change someone has to explain.
    real = patterns.past_table_notes
    hit = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, log=lambda m: None)
        except Exception:  # noqa: BLE001 -- the six non-Hubbard files
            continue
        if det.freq_table is None or det.pattern_dialect != "classic":
            continue
        if not real(sid, det):
            continue
        for i in range(max(det.pattern_used, 0)):
            monkeypatch.setattr(patterns, "past_table_notes", real)
            on = patterns.decode_entry(sid, det, i, **GRAMMAR)
            monkeypatch.setattr(patterns, "past_table_notes",
                                lambda s, d: {})
            off = patterns.decode_entry(sid, det, i, **GRAMMAR)
            if on is not None and on != off:
                hit.add(path.name)
                break
    assert hit == {"Proteus.sid", "Ricochet.sid", "Thing_on_a_Spring.sid",
                   "Warhawk.sid"}


# ---------------------------------------------------------------------------
# The third reading of the same fetch, and the one that comes BEFORE the other
# two: the `ASL` is eight bits wide. `ASL / TAY / LDA freqtbl,Y` has no `ROL`
# after the shift, so bit 7 of the note byte leaves through the carry and a
# byte at or above `$80` indexes the table from the top again --
# `((byte << 1) & $FF) >> 1`, the low seven bits (`patterns._wrap_note`). The
# clamp turned every such byte into G#7.
#
# Mega_Apocalypse is the measured case. Its note fetch at `$4B74` is
# `INY / LDA ($FA),Y / STA $5001 / AND #$7F / CLC / ADC $5222,X / STA $B9,X /
# ASL / TAY / LDA $4E89,Y`: the raw byte is kept as a flag, the low seven bits
# are transposed and shifted. `detect`'s `note_flag` spellings anchor the
# store as `9D` abs,X and this one is `95` zero page, so the flag went
# unread and the whole byte reached the clamp. Pattern entry 25 is `BF 09 4A
# 1F CA FF` -- a D-6 (`$4A` = 74) and then `$CA`, the same D-6 with bit 7
# set, a legato continuation; entry 39 is `BF 10 32 1F B2 FF`, D-4 and `$B2`.
# The player reads entries 74 and 50 (and 62 where the orderlist transposes
# +12); the clamp read 92 for all three.
#
# Measured at d2160e0 (snapshots differing only in patterns.py, presets.json
# options, -t 180, subtune 0, -m1, startup lag 7): the one occurrence inside
# the window is voice 0 at t=77 s, 192 frames, where the original holds
# `$4E20` (entry 74, D-6, with its own wide vibrato around it), the clamp
# played `$DD0E` (G#7) and the wrap plays `$4E28` (D-6). Attacks 407 -> 407
# on that voice, `melody` unchanged to full precision -- the row is a tie
# (`3 00`), so it is not an attack and no attack-keyed column can see it;
# the frames can. The corpus byte-hash named exactly Mega_Apocalypse
# (3 bytes, every one `$BC` -> a D); Commando.sng did not move.
# ---------------------------------------------------------------------------

MEGA = CORPUS / "Mega_Apocalypse.sid"
MEGA_FETCH = 0x4B74
MEGA_FETCH_BYTES = bytes.fromhex(
    "c8 b1 fa 8d 01 50 29 7f 18 7d 22 52 95 b9 0a a8 b9")
MEGA_TABLE = 0x4E89
# SID pattern-table entry -> (raw bytes, row the wrapped byte lands on,
# raw byte, entry the player reads, that entry's frequency in the file).
MEGA_TWO = {
    25: (bytes.fromhex("bf 09 4a 1f ca ff"), 32, 0xCA, 74, 0x4E20),
    39: (bytes.fromhex("bf 10 32 1f b2 ff"), 32, 0xB2, 50, 0x1388),
}


def test_the_wrap_is_the_eight_bit_shift_and_it_comes_first():
    # The arithmetic, on the bytes the docstring names.
    assert patterns._wrap_note(0xB2) == 50
    assert patterns._wrap_note(0xCA) == 74
    assert patterns._wrap_note(0xE0) == 96
    # ...and it is the identity below $80: a `$68` still reads 104, so the
    # Commando reading (and the fixture) is untouched.
    assert patterns._wrap_note(0x68) == 104
    assert all(patterns._wrap_note(b) == b for b in range(0x80))
    # Through the decoder: `01 B2` then `FF`, as in test_the_default_is_the_clamp.
    raw = bytes((0, 0, 0x01, 0xB2, 0xFF))
    assert patterns._build_raw_pattern(raw, 2)[0] == patterns.GT_FIRSTNOTE + 50
    raw = bytes((0, 0, 0x01, 0xCA, 0xFF))
    assert patterns._build_raw_pattern(raw, 2)[0] == patterns.GT_FIRSTNOTE + 74
    # `note_flag` masks the same bit the shift drops, so it changes nothing.
    assert (patterns._build_raw_pattern(raw, 2, note_flag=True)
            == patterns._build_raw_pattern(raw, 2, note_flag=False))
    # A wrapped byte that lands PAST the table is the other two readings'
    # case, keyed on the wrapped value: `$E0` is `$60` to them.
    raw = bytes((0, 0, 0x01, 0xE0, 0xFF))
    assert patterns._build_raw_pattern(raw, 2)[0] == G_SHARP_7
    assert patterns._build_raw_pattern(
        raw, 2, rest_notes=frozenset({0x60}))[0] == patterns.GT_KEYOFF
    assert patterns._build_raw_pattern(
        raw, 2, const_notes={0x60: 32})[0] == G_SHARP_2
    # A real entry 92-95 still clamps: the wrap is not a second clamp.
    raw = bytes((0, 0, 0x01, 0x5F, 0xFF))
    assert patterns._build_raw_pattern(raw, 2)[0] == G_SHARP_7


@needs_corpus
def test_mega_apocalypse_masks_transposes_and_shifts_its_note_byte():
    sid = load_sid(str(MEGA))
    det = detect(sid, log=lambda m: None)
    assert det.pattern_dialect == "classic"
    off = sid.to_offset(MEGA_FETCH)
    assert sid.data[off:off + len(MEGA_FETCH_BYTES)] == MEGA_FETCH_BYTES
    ft = det.freq_table
    assert (ft.addr, ft.length) == (MEGA_TABLE, 96)
    base = sid.to_offset(MEGA_TABLE)
    data = sid.data
    for i, (raw, row, byte, entry, freq) in MEGA_TWO.items():
        step = i * det.table_stride
        addr = sid.to_offset(data[det.pattern_hi + step] * 256
                             + data[det.pattern_lo + step])
        assert data[addr:addr + len(raw)] == raw, i
        assert raw[4] == byte
        assert patterns._wrap_note(byte) == entry
        assert data[base + 2 * entry] | (data[base + 2 * entry + 1] << 8) == freq
        ev = patterns.decode_entry(sid, det, i, **GRAMMAR)
        assert ev[4 * row] == patterns.GT_FIRSTNOTE + entry, (i, row)
        # The note before it is the same entry, read from a byte below $80:
        # the flagged byte is a legato continuation of it, so the wrap and
        # the note it follows agree, which is what the trace shows.
        assert ev[0] == patterns.GT_FIRSTNOTE + entry, i


@needs_corpus
def test_mega_apocalypse_without_the_wrap_is_the_clamp(monkeypatch):
    # The same rows with the wrap stood down (identity) read G#7: what the
    # clamp emitted, and what removing the `& 0xFF` from `_wrap_note` would
    # restore -- `(b << 1) >> 1` is `b` again.
    sid = load_sid(str(MEGA))
    det = detect(sid, log=lambda m: None)
    on = {i: patterns.decode_entry(sid, det, i, **GRAMMAR) for i in MEGA_TWO}
    monkeypatch.setattr(patterns, "_wrap_note", lambda b: b)
    off = {i: patterns.decode_entry(sid, det, i, **GRAMMAR) for i in MEGA_TWO}
    for i, (_, row, _, entry, _) in MEGA_TWO.items():
        assert len(on[i]) == len(off[i]), i
        assert off[i][4 * row] == G_SHARP_7, i
        assert on[i][4 * row] == patterns.GT_FIRSTNOTE + entry, i
        # The note column on that one row is all that moves.
        assert [k for k in range(0, len(on[i]), 4)
                if on[i][k:k + 4] != off[i][k:k + 4]] == [4 * row], i
        assert on[i][4 * row + 1:4 * row + 4] == off[i][4 * row + 1:4 * row + 4]


def _classic_corpus():
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, log=lambda m: None)
        except Exception:  # noqa: BLE001 -- the six non-Hubbard files
            continue
        if det.pattern_dialect != "classic":
            continue
        yield path, sid, det


@needs_corpus
def test_every_classic_table_is_read_through_an_eight_bit_shift():
    # "Every 8-bit ASL player" is a claim about the corpus, so it is checked
    # against the corpus: every classic-dialect file whose table was found
    # carries `ASL / TAY / LDA tbl,Y` or `ASL / TAX / LDA tbl,X` at that
    # table's address. A 16-bit index would need a `ROL` after the shift and
    # a different lookup shape, and none has one.
    missing = []
    seen = 0
    for path, sid, det in _classic_corpus():
        ft = det.freq_table
        if ft is None:
            continue
        seen += 1
        lo, hi = ft.addr & 0xFF, ft.addr >> 8
        tay = bytes((0x0A, 0xA8, 0xB9, lo, hi))
        tax = bytes((0x0A, 0xAA, 0xBD, lo, hi))
        if sid.data.find(tay) < 0 and sid.data.find(tax) < 0:
            missing.append(path.name)
    assert missing == []
    assert seen >= 70, seen           # 73 of 79 classic files at d2160e0


@needs_corpus
def test_wrap_reach_is_three_files_decoded_and_one_played(monkeypatch):
    # Where the wrap reaches at the DECODE level under the presets' grammar,
    # over every classic-dialect corpus file: three. Commodore_64_Music_
    # Examples' and Confuzion's are a `$83` (entry 3) in entries no orderlist
    # plays, so the corpus byte-hash under presets.json at d2160e0 named
    # exactly Mega_Apocalypse. Pinned so a change in reach is a change
    # someone has to explain.
    real = patterns._wrap_note
    hit = set()
    for path, sid, det in _classic_corpus():
        for i in range(max(det.pattern_used, 0)):
            monkeypatch.setattr(patterns, "_wrap_note", real)
            on = patterns.decode_entry(sid, det, i, **GRAMMAR)
            monkeypatch.setattr(patterns, "_wrap_note", lambda b: b)
            off = patterns.decode_entry(sid, det, i, **GRAMMAR)
            if on is not None and on != off:
                hit.add(path.name)
                break
    assert hit == {"Commodore_64_Music_Examples.sid", "Confuzion.sid",
                   "Mega_Apocalypse.sid"}
