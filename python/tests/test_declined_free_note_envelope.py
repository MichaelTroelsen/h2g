"""A declined free note keeps the envelope the channel holds.

A note byte with bit 7 skips the player's AD/SR write, so the chip keeps the
pair the last note that loaded one left. `free_note_variants` cannot take a
record whose attack the wavetable cannot skip, and the full start it falls
back on loaded the record's own pair: Flash_Gordon voice 2's final note
(pattern $45 row 0, 51.8 s) held $366C in the original and sounded $2C9C,
2592 `adsr` frames (v0.5.678, adsr 0.954). `declined_free_note_clones`
names a clone of the record whose AD/SR are the held pair.
"""
import json
import pathlib

from h2g.convert import convert
from h2g.goatwriter import note_passes as NP
from h2g.goatwriter.constants import (CMD_SETAD, CMD_SETSR, CMD_TONEPORTA,
                                      GT_REST)

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60
HELD, OWN = (0x36, 0x6C), (0x2C, 0x9C)
ENV = {3: HELD, 5: OWN}
TRACKS = [[0, 0xFF, 0]]


def _run(pattern, rows):
    return NP.declined_free_note_clones([pattern], rows, TRACKS, ENV, 6)


def test_the_row_names_a_clone_with_the_held_pair():
    pat = [NOTE, 3, 0, 0,
           NOTE + 1, 5, 0, 0,        # flagged, declined
           GT_REST, 0, 0, 0]
    out, clones, n = _run(pat, {(0, 1)})
    assert clones == [(5, 6, HELD)] and n == 1
    assert out[0][4:8] == [NOTE + 1, 6, 0, 0]
    assert out[0][8 + 1] == 5                     # the base is latched again


def test_a_tie_that_names_an_instrument_does_not_change_the_held_pair():
    pat = [NOTE, 3, 0, 0,
           NOTE + 1, 5, CMD_TONEPORTA, 0,    # latches 5, loads nothing
           NOTE + 2, 0, 0, 0,                # flagged: plays 5, chip holds 3's
           GT_REST, 0, 0, 0]
    out, clones, _n = _run(pat, {(0, 2)})
    assert clones == [(5, 6, HELD)]
    assert out[0][8 + 1] == 6


def test_a_setsr_row_is_part_of_the_held_pair():
    pat = [NOTE, 3, 0, 0,
           GT_REST, 0, CMD_SETSR, 0x08,
           NOTE + 2, 5, 0, 0,
           GT_REST, 0, 0, 0]
    _out, clones, _n = _run(pat, {(0, 2)})
    assert clones == [(5, 6, (0x36, 0x08))]


def test_a_row_whose_held_pair_is_its_own_needs_no_clone():
    pat = [NOTE, 5, 0, 0, NOTE + 1, 5, 0, 0, GT_REST, 0, 0, 0]
    out, clones, n = _run(pat, {(0, 1)})
    assert not clones and n == 0 and out[0] == pat


def test_an_unknown_held_pair_declines():
    pat = [NOTE + 1, 5, 0, 0, GT_REST, 0, 0, 0]      # the tune's first note
    out, clones, _n = _run(pat, {(0, 0)})
    assert not clones and out[0] == pat


def test_no_orderlists_changes_nothing():
    pat = [NOTE, 3, 0, 0, NOTE + 1, 5, 0, 0, GT_REST, 0, 0, 0]
    out, clones, _n = NP.declined_free_note_clones([pat], {(0, 1)}, None,
                                                   ENV, 6)
    assert out == [pat] and not clones


def _tie_pattern():
    return [GT_REST, 5, CMD_SETSR, OWN[1],            # `_tied_instrument_
            NOTE + 2, 5, CMD_TONEPORTA, 0,            #  envelopes`' spelling
            GT_REST, 0, CMD_SETAD, OWN[0],
            GT_REST, 0, 0, 0]


def test_a_flagged_tie_write_after_a_kept_pair_is_dropped_not_freed():
    free = [NOTE, 3, 0, 0, NOTE + 1, 5, 0, 0, GT_REST, 0, 0, 0]
    out, clones, _n = NP.declined_free_note_clones(
        [free, _tie_pattern()], {(0, 1)}, [[0, 1, 0xFF, 0]], ENV, 6,
        ties={(1, 1)})
    assert clones == [(5, 6, HELD)]
    # The tie keeps its row and the instrument latch; the writes are gone.
    assert out[1][0:4] == [GT_REST, 5, 0, 0]
    assert out[1][4:8] == [NOTE + 2, 5, CMD_TONEPORTA, 0]
    assert out[1][8:12] == [GT_REST, 0, 0, 0]


def test_a_flagged_tie_write_that_changes_nothing_is_left():
    # No declined row, no clone: the write reloads the pair the chip holds.
    pat = _tie_pattern()
    out, clones, n = NP.declined_free_note_clones(
        [[NOTE, 5, 0, 0, GT_REST, 0, 0, 0], pat], set(), [[0, 1, 0xFF, 0]],
        ENV, 6, ties={(1, 1)})
    assert not clones and not n and out[1] == pat


@needs_corpus
def test_flash_gordon_voice_2_final_note_keeps_366c():
    import fidelity
    import songview
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    lines = []
    opts = dict(fidelity._preset_opts(doc, "Flash_Gordon.sid"), pack=False)
    song = songview.parse_sng(
        convert(str(CORPUS / "Flash_Gordon.sid"), log=lines.append, **opts))
    assert any("Held envelope" in ln and "1 declined" in ln
               for ln in lines), lines
    # The clone is record 08's bytes with $366C; pattern 69's row 0 names it.
    clone = [i for i in song.instruments
             if i.name.startswith("08:") and i.adsr == "$366C"]
    assert len(clone) == 1
    row = song.patterns[69][0:4]
    assert row[1] == clone[0].number, row
    # The tie writes after it (pattern $47 rows 3 and 5) would reload $2C9C.
    assert song.patterns[71][3 * 4 + 2] == 0
    assert song.patterns[71][5 * 4 + 2] == 0
