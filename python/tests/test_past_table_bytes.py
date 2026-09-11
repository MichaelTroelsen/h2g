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
instruction -- is emitted as a KEYOFF. These tests pin the static reading on
Sanxion, the six entries it reaches, both halves of the rule, and that
Commando (whose cell is written by `$515A STA $54F8,X`) does not qualify.
"""
import pathlib
import sys
from dataclasses import replace

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import patterns  # noqa: E402
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
