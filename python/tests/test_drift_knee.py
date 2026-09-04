"""`drift` must say when the offset is TWO rates rather than one.

`mad` separates *drifting* from *wandering*. It cannot separate one rate from
two: an offset that runs at one slope for half the window and another for the
rest stays close to a line, so its `mad` is small and the fit is accepted --
while the single number reported describes neither half. Rasputin is the corpus
case, reversing sign (-8.16 early, +41.16 late) at `mad` 5.8.

Built on synthetic traces so the shapes are exact and the test cannot go quiet
if the corpus moves under it. The corpus figures live in `drift`'s own comment.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402


class _V:
    """The two fields `matched_onsets` and `drift` read off a Voice."""

    def __init__(self, frames):
        self.attacks = [f"n{i}" for i in range(len(frames))]
        self.attack_frames = list(frames)


def _traces(theirs, ours):
    """One voice carrying the given onset frames; the other two silent."""
    empty = _V([])
    return ([_V(theirs), empty, empty], [_V(ours), empty, empty])


def _straight(n=40, step=50, slope=0.0):
    theirs = [100 + step * i for i in range(n)]
    ours = [int(t + slope * t) for t in theirs]
    return theirs, ours


def _kneed(n=40, step=50, early=0.0, late=0.05):
    """One slope for the first half of the window, another for the second."""
    theirs = [100 + step * i for i in range(n)]
    mid = theirs[n // 2]
    ours = []
    for t in theirs:
        off = early * t if t <= mid else early * mid + late * (t - mid)
        ours.append(int(t + off))
    return theirs, ours


def test_a_straight_offset_reports_no_knee():
    a, b = _traces(*_straight(slope=0.01))
    d = F.drift(a, b)
    assert d.get("per_1000") is not None, "the straight case must still fit"
    assert "knee" not in d, d.get("knee")
    assert d["knee_per_1000"] < F.DRIFT_KNEE_PER_1000


def test_a_kneed_offset_is_reported():
    a, b = _traces(*_kneed(early=0.0, late=0.05))
    d = F.drift(a, b)
    assert d.get("per_1000") is not None, "a knee must not refuse the fit"
    assert "knee" in d, d
    assert d["knee_per_1000"] >= F.DRIFT_KNEE_PER_1000
    # and it must name BOTH halves, not just say 'knee'
    assert "half_early_per_1000" in d and "half_late_per_1000" in d
    assert d["half_late_per_1000"] > d["half_early_per_1000"]


def test_the_knee_survives_a_small_mad_which_is_the_whole_point():
    """If `mad` caught these, the new branch would be redundant."""
    a, b = _traces(*_kneed(early=0.0, late=0.05))
    d = F.drift(a, b)
    assert "unfitted" not in d, "the scatter gate must NOT be what fires here"
    assert d["mad"] <= F.DRIFT_MAX_SCATTER * d["span"]


def test_a_sign_reversal_is_reported_rasputins_shape():
    a, b = _traces(*_kneed(early=-0.01, late=0.04))
    d = F.drift(a, b)
    assert "knee" in d
    assert d["half_early_per_1000"] < 0 < d["half_late_per_1000"]


def test_halves_and_whole_use_the_SAME_estimator():
    """The first census of this got the wrong answer by using a different rule.

    A half fitted under a different estimator than the whole makes the
    difference between them an artefact of the tooling. Fitting the WHOLE
    window through the half-estimator must reproduce `per_1000` exactly.
    """
    a, b = _traces(*_straight(slope=0.01))
    d = F.drift(a, b)
    pairs = sorted(F.matched_onsets(a[0], b[0]))
    assert F._theil_sen_per_1000(pairs) == d["per_1000"]


def test_too_few_pairs_reports_no_halves_rather_than_guessing():
    a, b = _traces(*_straight(n=F.MIN_DRIFT_HALF * 2 - 1, slope=0.01))
    d = F.drift(a, b)
    if d.get("per_1000") is not None:
        assert "knee" not in d
        assert "half_early_per_1000" not in d
