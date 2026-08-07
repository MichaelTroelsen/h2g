"""Timing a conversion against the original, which no score does.

`melody` is a difflib ratio over a note sequence inside a fixed window, so it
answers "the same notes in the same order" and not "at the same speed". The
two come apart in a specific, asymmetric way: a conversion playing too *fast*
reaches further into the tune than the window holds and difflib is charged for
the surplus, while one playing too *slow* returns a prefix. In v0.5.99 that
made `melody` prefer 50Hz for 17 files whose measured error at 100Hz was
between 1% and 33%, and the report called it "a factor of two out".

So `pace` measures the thing directly, and these tests pin the two ways it can
be read wrong: an estimator that a few long gaps can drag (which is why the
median and not the fit is the number reported), and the difference between a
row of the wrong length and material we never play.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                               # noqa: E402
from fidelity import Voice, matched_gaps, pace                # noqa: E402


def voice(notes, frames):
    return Voice(attacks=list(notes), attack_frames=list(frames))


def trace(*voices):
    return fidelity.Trace(list(voices), fidelity.FilterState())


def test_matched_gaps_pairs_notes_difflib_agrees_on():
    a = voice(["C-4", "D-4", "E-4"], [0, 10, 20])
    b = voice(["C-4", "D-4", "E-4"], [0, 5, 10])
    assert matched_gaps(a, b) == [(10, 5), (10, 5)]


def test_matched_gaps_survives_a_note_only_one_side_plays():
    """The gap spans the dropped note rather than vanishing with it."""
    a = voice(["C-4", "D-4", "E-4"], [0, 10, 20])
    b = voice(["C-4", "E-4"], [0, 20])
    assert matched_gaps(a, b) == [(20, 20)]


def test_short_gaps_are_not_timed():
    """Chord onsets and same-row retriggers quantise to noise."""
    a = voice(["C-4", "E-4"], [0, 2])
    b = voice(["C-4", "E-4"], [0, 1])
    assert matched_gaps(a, b) == []
    assert matched_gaps(a, b, floor=2) == [(2, 1)]


def test_a_row_of_the_right_length_reads_1_0():
    a = voice([f"C-{i%8}" for i in range(12)], [8 * i for i in range(12)])
    got = pace(trace(a, voice([], []), voice([], [])),
               trace(a, voice([], []), voice([], [])))
    assert got["median"] == pytest.approx(1.0)
    assert got["spread"] == pytest.approx(0.0)


def test_a_row_two_thirds_too_short_reads_two_thirds_and_tight():
    """Tarzan's shape: every gap compressed by the same factor."""
    names = [f"C-{i%8}" for i in range(12)]
    a = voice(names, [6 * i for i in range(12)])
    b = voice(names, [4 * i for i in range(12)])
    got = pace(trace(a, voice([], []), voice([], [])),
               trace(b, voice([], []), voice([], [])))
    assert got["median"] == pytest.approx(2 / 3)
    assert got["spread"] == pytest.approx(0.0)


def test_one_dropped_section_does_not_read_as_a_short_row():
    """The median's robustness, stated as the property it buys.

    Every surviving gap is played at its right length and the loss is one
    long jump. The row length *is* right, and that is what gets reported --
    a single omission moves neither the median nor the quartiles.
    """
    names = [f"C-{i%8}" for i in range(12)]
    a = voice(names, [8 * i for i in range(12)])
    ours = [8 * i for i in range(12)]
    ours[6:] = [f - 40 for f in ours[6:]]        # five rows' worth never played
    b = voice(names, ours)
    got = pace(trace(a, voice([], []), voice([], [])),
               trace(b, voice([], []), voice([], [])))
    assert got["median"] == pytest.approx(1.0)
    assert got["spread"] == pytest.approx(0.0)


def test_an_alternating_gate_reads_as_spread():
    """ACE II's shape: the player runs 5 frames then 6, and we run a flat 4.

    No single row length describes this, so the number `--pace` prints is an
    average and has to say so.
    """
    names = [f"C-{i%8}" for i in range(13)]
    at, bt, ta, tb = [0], [0], 0, 0
    for k in range(12):
        ta += 5 if k % 2 else 6
        tb += 4
        at.append(ta)
        bt.append(tb)
    got = pace(trace(voice(names, at), voice([], []), voice([], [])),
               trace(voice(names, bt), voice([], []), voice([], [])))
    assert 0.72 < got["median"] < 0.81
    assert got["spread"] > 0.12


def test_the_reported_ratio_is_the_median_not_the_fit():
    """One resting voice must not decide the file's tempo.

    Eleven gaps compressed to 3/4 and one very long gap stretched: the
    least-squares fit follows the long one because it is weighted by its own
    length, the median does not. Reporting the fit here would say the
    conversion plays *slower* than the original when eleven twelfths of it
    plays faster.
    """
    names = [f"C-{i%8}" for i in range(13)]
    at, bt, ta, tb = [0], [0], 0, 0
    for _ in range(11):
        ta += 8
        tb += 6
        at.append(ta)
        bt.append(tb)
    at.append(ta + 400)
    bt.append(tb + 800)
    got = pace(trace(voice(names, at), voice([], []), voice([], [])),
               trace(voice(names, bt), voice([], []), voice([], [])))
    assert got["median"] == pytest.approx(0.75)
    # The fit says the conversion plays *slower* than the original when eleven
    # twelfths of it plays faster. That disagreement is why the median leads.
    assert got["slope"] > 1.0


def test_too_little_shared_material_is_not_timed():
    a = voice(["C-4", "D-4"], [0, 10])
    b = voice(["C-4", "D-4"], [0, 10])
    got = pace(trace(a, voice([], []), voice([], [])),
               trace(b, voice([], []), voice([], [])))
    assert "median" not in got and got["n"] < 6
