"""The note rise's programs placed in the rows of duplicate instrument blocks
(`note_rise.reclaimable_holes`, `layout_pieces`, `note_rise_placed`).

Game_Killer's wavetable held 23 free rows, room for ten of the sixteen store
values. Five of its instruments carry the same five-row block, so four of
them give their rows to the programs and all sixteen go in.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import note_rise as R                    # noqa: E402
from h2g.goatwriter.constants import WAVECMD_PORTAUP         # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
BLOCK = [(0x41, 0), (0x07, 0), (0x41, 0), (0xFF, 0), (0xFF, 0)]
OTHER = [(0x81, 0), (0x08, 0x80), (0x05, 0), (0xFF, 0)]


def test_layout_without_holes_is_the_contiguous_one():
    rows, appended = R.layout_pieces([3, 2, 2, 5], [], 100)
    assert rows == [101, 104, 106, 108] and appended == 12


def test_a_piece_goes_in_the_first_hole_it_fits():
    rows, appended = R.layout_pieces([3, 2, 2, 2], [(6, 5)], 100)
    assert rows == [6, 9, 101, 103] and appended == 4


def test_placed_pieces_without_holes_equal_note_rise_entries():
    sp = lambda k: k                                     # noqa: E731
    values = {0: [1, 2, 3], 1: [1, 2]}
    entries, starts = R.note_rise_entries(values, 10, 1, 51, sp)
    placed, pstarts = R.note_rise_placed(values, 10, 1, 50, [], sp)
    assert [placed[r] for r in sorted(placed)] == entries
    assert sorted(placed) == list(range(51, 51 + len(entries)))
    assert pstarts == starts


def test_pieces_in_holes_still_jump_to_their_tail():
    sp = lambda k: k                                     # noqa: E731
    placed, starts = R.note_rise_placed({0: [1, 2]}, 10, 1, 50, [(6, 5)], sp)
    tail = len(R.tail_entries(0, 10, 2))
    assert sorted(placed)[:tail + 1] == list(range(6, 6 + tail + 1))
    for v in (1, 2):
        at = starts[(0, v)]
        assert placed[at][0] == WAVECMD_PORTAUP
        assert placed[at + 1] == (0xFF, 6)               # the tail's first row


def test_duplicate_blocks_are_shared_and_their_rows_freed():
    wave = BLOCK + BLOCK + OTHER + BLOCK
    holes, starts = R.reclaimable_holes(wave, [1, 6, 11, 15], [])
    assert holes == [(6, 5), (15, 5)] and starts == [1, 1, 11, 1]


def test_a_block_something_points_into_is_kept():
    wave = BLOCK + BLOCK + OTHER
    assert R.reclaimable_holes(wave, [1, 6, 11], [6])[0] == []     # a pointer
    assert R.reclaimable_holes(wave, [1, 6, 11], [8])[0] == []     # inside
    jumped = wave + [(0xFF, 7)]                                    # a jump in
    assert R.reclaimable_holes(jumped, [1, 6, 11], [])[0] == []


def test_a_block_that_jumps_or_does_not_stop_is_kept():
    looping = [(0x41, 0), (0x07, 0), (0xFF, 2)]
    assert R.reclaimable_holes(looping + looping, [1, 4], [])[0] == []
    open_ended = [(0x41, 0), (0x07, 0)]
    assert R.reclaimable_holes(open_ended * 2, [1, 3], [])[0] == []


@needs_corpus
def test_game_killer_takes_all_sixteen_store_values():
    import h2g.convert as C
    import songview
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, "Game_Killer.sid")
    sng = C.convert(str(CORPUS / "Game_Killer.sid"), log=lines.append, **opts)
    assert any("16 of 16 store value(s)" in m and "reused from 4 duplicate "
               "block(s)" in m for m in lines), lines
    song = songview.parse_sng(sng)
    wt = song.tables["WTBL"]
    assert len(wt) <= 255
    starts = {i.number: i.wave_ptr for i in song.instruments}
    assert len({starts[n] for n in (1, 2, 4, 8, 10)}) == 1
    assert wt[starts[1] - 1:starts[1] + 4] == BLOCK
