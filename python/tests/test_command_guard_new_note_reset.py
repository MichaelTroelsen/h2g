"""The regrid guards that read the row before's command column know that a
new note zeroes the running effect first.

gplay.c `if (cptr->newnote) { ... cptr->command = 0; ...}` runs before the
tick-0 command switch, and player.s `mt_newnoteinit` does `sta mt_chnfx,x
;Reset effect`. So a note row whose own command is one-shot (or empty)
leaves no 1XY-4XY running, and a `CMD_SETTEMPO` written over a note row's
1XY/2XY leaves no slide on that row.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import CMD_SETTEMPO  # noqa: F401  (import order: goatwriter first)
from h2g.patterns import (_inherits_continuous_effect, _new_note_row,
                          _slide_covered_regrid_spot)

NOTE = 0x70
REST = 0xBD
SETAD = 5
ONE_SHOT = (REST, SETAD, 9)


def _pattern(rows, cells, fill=(REST, 0, 0)):
    """cells: {row: (note, cmd, data)}; every other row is `fill`."""
    out = []
    for r in range(rows):
        note, cmd, data = cells.get(r, fill)
        out += [note, 1, cmd, data]
    return out + [0xFF, 0, 0, 0]


def test_new_note_row_is_the_note_range_only():
    pat = _pattern(5, {0: (0x60, 0, 0), 1: (0xBC, 0, 0), 2: (0xBD, 0, 0),
                       3: (0xBE, 0, 0), 4: (0xBF, 0, 0)})
    assert [_new_note_row(pat, k) for k in range(5)] == [
        True, True, False, False, False]


def test_a_slide_runs_through_rest_rows_with_one_shot_commands():
    pat = _pattern(8, {1: (REST, 1, 4)}, ONE_SHOT)
    assert _inherits_continuous_effect(pat, 6)


def test_a_note_row_with_a_one_shot_command_ends_the_slide():
    pat = _pattern(8, {1: (REST, 1, 4), 3: (NOTE, SETAD, 9)}, ONE_SHOT)
    assert not _inherits_continuous_effect(pat, 6)


def test_a_note_row_starting_a_slide_of_its_own_still_reaches_the_row():
    pat = _pattern(8, {1: (REST, 1, 4), 3: (NOTE, 2, 9)}, ONE_SHOT)
    assert _inherits_continuous_effect(pat, 6)


def test_the_candidate_row_being_a_note_inherits_nothing():
    pat = _pattern(8, {1: (REST, 1, 4), 6: (NOTE, 0, 0)}, ONE_SHOT)
    assert not _inherits_continuous_effect(pat, 6)


def test_a_run_with_no_command_or_note_back_to_the_start_is_still_unknown():
    assert _inherits_continuous_effect(_pattern(8, {}, ONE_SHOT), 5)


def _run(rows, note_at=()):
    cells = {r: (REST, 1, 2) for r in range(1, rows)}
    for r in note_at:
        cells[r] = (NOTE, 1, 2)
    return _pattern(rows, cells)


def test_a_slide_run_of_rests_covers_the_pair():
    assert _slide_covered_regrid_spot(_run(12), 6, 12) == 6


def test_a_note_on_the_first_pair_row_is_not_covered():
    pat = _run(12, note_at=(6,))
    assert _slide_covered_regrid_spot(pat, 6, 12) != 6


def test_a_note_on_the_second_pair_row_is_not_covered():
    pat = _run(12, note_at=(7,))
    assert _slide_covered_regrid_spot(pat, 6, 12) != 6


def test_a_note_on_the_row_before_the_pair_does_not_decline_it():
    pat = _run(12, note_at=(5,))
    assert _slide_covered_regrid_spot(pat, 6, 12) == 6
