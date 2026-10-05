"""`time_paired_drift` is ab-9's second drift measure: it must NOT share
`drift`'s pairing (difflib on note names) or its estimator (Theil-Sen).

Synthetic traces, so the shapes are exact. Every attack carries a DIFFERENT
name on the two sides, which makes `drift` decline outright (nothing matches)
while this measure still reads the line: the proof that it is name-blind.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402


class _V:
    def __init__(self, frames, tag="n"):
        self.attacks = [f"{tag}{i}" for i in range(len(frames))]
        self.attack_frames = list(frames)


def _song(n=320, seed=7):
    """Three voices of irregular onsets over ~9000 frames (one shared clock)."""
    rng = random.Random(seed)
    voices = []
    for _ in range(3):
        t, fs = 40, []
        while len(fs) < n:
            t += rng.choice((12, 18, 24, 36, 48))
            fs.append(t)
        voices.append(fs)
    return voices


def _ours(voices, lag=0, slope=0.0):
    return [[round(f + lag + slope * f) for f in fs] for fs in voices]


def _traces(theirs, ours):
    return ([_V(f, "a") for f in theirs], [_V(f, "b") for f in ours])


def test_reads_a_straight_drift_with_every_name_different():
    th = _song()
    o, u = _traces(th, _ours(th, lag=6, slope=0.010))
    got = F.time_paired_drift(o, u)
    assert abs(got["per_1000"] - 10.0) < 0.6, got
    # `drift` has nothing to pair when no name agrees; this measure is blind to it.
    assert F.drift(o, u) == {"n": 0}


def test_sign_follows_the_side_that_runs_early():
    th = _song()
    early = F.time_paired_drift(*_traces(th, _ours(th, lag=0, slope=-0.009)))
    late = F.time_paired_drift(*_traces(th, _ours(th, lag=0, slope=0.009)))
    assert early["per_1000"] < -7 and late["per_1000"] > 7


def test_constant_lag_is_zero_drift_and_the_lag_comes_out():
    th = _song()
    got = F.time_paired_drift(*_traces(th, _ours(th, lag=17)))
    assert abs(got["per_1000"]) < 0.2, got
    assert got["lag"] == 17


def test_the_lock_follows_an_offset_larger_than_the_search_radius():
    """-9/1000 over 9000 frames is ~80 frames: five times TP_TRACK_RADIUS, so a
    lock that does not move with the last window loses the line."""
    th = _song()
    got = F.time_paired_drift(*_traces(th, _ours(th, slope=-0.0090)))
    assert abs(got["per_1000"] + 9.0) < 0.6, got
    assert got["n_windows"] >= 15


def test_unrelated_onsets_read_nothing():
    th = _song(seed=1)
    other = _song(seed=99)
    got = F.time_paired_drift(*_traces(th, other))
    assert got["per_1000"] is None


def test_too_few_attacks_read_nothing():
    got = F.time_paired_drift(*_traces([[100, 160, 220], [], []],
                                       [[100, 160, 220], [], []]))
    assert got["per_1000"] is None and got["windows"] == []


def test_a_wandering_pair_does_not_manufacture_a_rate_from_a_few_matches():
    """Half the original's attacks having no partner is chance, not music."""
    th = _song()
    ours = _ours(th, lag=3)
    rng = random.Random(5)
    ours = [[f if rng.random() < 0.3 else f + rng.randint(20, 400) for f in fs]
            for fs in ours]
    assert F.time_paired_drift(*_traces(th, ours))["per_1000"] is None


def test_a_window_offset_is_the_median_not_an_extreme():
    """A fifth of the attacks sit 3 frames early, a fifth 3 late: the window
    offset is the lag 10, where the minimum would read 7 and the maximum 13."""
    th = _song()
    ours = _ours(th, lag=10)
    ours = [[f + (-3 if i % 5 == 0 else 3 if i % 5 == 1 else 0)
             for i, f in enumerate(fs)] for fs in ours]
    got = F.time_paired_drift(*_traces(th, ours))
    assert got["lag"] == 10, got["windows"][:2]
    assert abs(got["per_1000"]) < 0.5


def test_the_window_horizon_is_honoured():
    th = _song()
    full = F.time_paired_drift(*_traces(th, _ours(th, slope=0.01)))
    short = F.time_paired_drift(*_traces(th, _ours(th, slope=0.01)), nframes=3000)
    assert short["n_windows"] < full["n_windows"]
    assert abs(short["per_1000"] - 10.0) < 1.5
