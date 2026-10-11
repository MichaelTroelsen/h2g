"""A first-choice regrid pair directly behind a 1XY-4XY is moved, not written.

`_shifted_regrid_spot` already refuses a spot that would inherit a running
slide; the first choice used to be held only to "both command cells empty", so
8 of 993 pairs (Arcade, Monty, IK, Nineteen, Rikky; measured at 6e467ff)
carried a CMD_SETTEMPO through two more rows. See `patterns._regrid_spots`.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_regrid_shift import _lengthened, _pattern, _run

SLIDE_DOWN = (2, 0x01)


def test_empty_pair_behind_a_slide_moves():
    """Row 6 is the first choice; row 5 holds a slide, so 6 would inherit it.
    Row 5 is occupied, row 7 follows an empty cell: 7 is the nearest clean."""
    n, pat, log = _run(_pattern(12, {5: SLIDE_DOWN}), 0.1)
    assert n == 1 and _lengthened(pat) == [7]
    assert "1 shifted" in log[0], log


def test_an_empty_row_between_slide_and_pair_keeps_row_6():
    n, pat, _ = _run(_pattern(12, {4: SLIDE_DOWN}), 0.1)
    assert _lengthened(pat) == [6]


def test_plain_pattern_keeps_row_6():
    n, pat, _ = _run(_pattern(12), 0.1)
    assert _lengthened(pat) == [6]
