"""The skydive's programs laid over the rows of duplicate instrument blocks
(`skydive.coalesce_holes`, `take_from_runs`, `reusable_runs` through
`skydive_plan`; the holes are `note_rise.reclaimable_holes`').

Gremlins and Hunter_Patrol had room for the held programs but not for the
vibrato-carrying ones the plan tries next: their wavetables end at 247 and 242
of 255. Both carry duplicate five-row instrument blocks (Hunter_Patrol 20 of
them, 100 free rows), and the rows are a run wherever the blocks lie side by
side. A program goes there only after the table's end refused it, so a file
that fits (Master_of_Magic, One_Man_and_his_Droid, Zoids) keeps its bytes.

Why not the single padding rows: the second `FF 00` of a five-row block is
unreachable, but it is a run of ONE row, and a program is two rows at the
least (a step and its stop) -- `test_a_program_is_never_shorter_than_two_rows`.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter import counter_fall as CF                # noqa: E402
from h2g.goatwriter.constants import CMD_SETWAVEPTR          # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
MARK = "row(s) laid over the rows of duplicate instrument blocks"


def test_touching_blocks_are_one_run():
    assert S.coalesce_holes([(11, 5), (6, 5), (23, 5)]) == [(6, 10), (23, 5)]
    assert S.coalesce_holes([(6, 5), (11, 5), (16, 5)]) == [(6, 15)]
    assert S.coalesce_holes([]) == []


def test_a_program_takes_the_smallest_run_it_fits():
    free = [[6, 15], [23, 5], [40, 8]]
    assert S.take_from_runs(free, 5) == 23           # the exact fit, not 6
    assert free == [[6, 15], [28, 0], [40, 8]]
    assert S.take_from_runs(free, 6) == 40           # 8 over 15
    assert S.take_from_runs(free, 9) == 6
    assert S.take_from_runs(free, 7) is None         # 6 left in [15, 6]
    assert free[0] == [15, 6]


def test_the_lower_run_wins_a_tie():
    free = [[30, 5], [10, 5]]
    assert S.take_from_runs(free, 5) == 10


def test_a_program_is_never_shorter_than_two_rows():
    """A program ends in its stop, so one row of it is a step at the least.
    The padding rows of a block are single, so none of them can hold one."""
    one = lambda k: 1                                    # noqa: E731
    assert len(CF.counter_fall_entries((3,), one)) == 2
    assert S._compress([(0xF2, 1)]) == [(0xF2, 1), (0xFF, 0)]
    assert len(S._compress([])) <= 1


def _convert(name, **kw):
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, name + ".sid")
    lines = []
    sng = C.convert(str(CORPUS / (name + ".sid")), log=lines.append, **opts)
    return sng, lines


def _walk(wt, start):
    """The rows a wavetable pointer runs through: until a jump (the jump row
    included), or the end of the table."""
    rows, r = [], start
    while 1 <= r <= len(wt) and r not in rows:
        rows.append(r)
        if wt[r - 1][0] == 0xFF:
            break
        r += 1
    return rows


@needs_corpus
@pytest.mark.parametrize("name", ["Hunter_Patrol", "Gremlins"])
def test_carried_programs_go_over_duplicate_blocks_and_nothing_else_moves(
        name, monkeypatch):
    import songview
    if name == "Hunter_Patrol":
        # The rows its dead blocks free (`goatwriter.dead_blocks`, 85 of 182)
        # hold the carried programs on their own, so no duplicate block is
        # laid over; this test is about the table without them.
        from h2g.goatwriter import dead_blocks
        monkeypatch.setattr(dead_blocks, "plan_dead_blocks",
                            lambda *a, **k: None)
    sng, lines = _convert(name)
    sky = [m for m in lines if m.startswith("Skydive (bit")]
    assert any(MARK in m and "carrying the vibrato" in m for m in sky), sky

    # The same conversion with no carried program has no reason to touch a
    # duplicate block: every instrument's own program must read the same.
    with S.vibrato_carry(False):
        held_sng, held_lines = _convert(name)
    assert not any(MARK in m for m in held_lines)
    song, held = songview.parse_sng(sng), songview.parse_sng(held_sng)
    wt, held_wt = song.tables["WTBL"], held.tables["WTBL"]
    assert len(wt) <= 255
    for a, b in zip(song.instruments, held.instruments):
        if not a.wave_ptr:
            assert not b.wave_ptr
            continue
        mine = [wt[r - 1] for r in _walk(wt, a.wave_ptr)]
        theirs = [held_wt[r - 1] for r in _walk(held_wt, b.wave_ptr)]
        assert mine == theirs, (a.number, mine, theirs)

    # Every pointer a pattern sets that is not a record's own runs to a
    # jump through rows that no record owns.
    starts = {i.wave_ptr for i in song.instruments if i.wave_ptr}
    owned = {r for s in starts for r in _walk(wt, s)}
    pointed = {pat[4 * r + 3] for pat in song.patterns
               for r in range(len(pat) // 4)
               if pat[4 * r + 2] == CMD_SETWAVEPTR} - starts
    assert pointed, "no program of its own was laid anywhere"
    programs = [[wt[r - 1] for r in _walk(wt, s)] for s in starts]
    for ptr in pointed:
        run = _walk(wt, ptr)
        assert wt[run[-1] - 1][0] == 0xFF, ptr
        assert not set(run) & owned, (ptr, run)
        # a stale copy of a block would read as some record's program
        assert [wt[r - 1] for r in run] not in programs, (ptr, run)


@needs_corpus
@pytest.mark.parametrize("name", ["Master_of_Magic", "One_Man_and_his_Droid",
                                  "Zoids"])
def test_a_file_the_table_end_fits_is_not_laid_over_blocks(name):
    # Last_V8 is not here: its window at the cell pitch is a
    # second program laid as the tail of the first (test_skydive_cell_pitch.py),
    # and the 3 rows the table's end has left do not take its lead.
    _sng, lines = _convert(name)
    assert not any(MARK in m for m in lines
                   if m.startswith("Skydive (bit")), lines
