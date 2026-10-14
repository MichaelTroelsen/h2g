"""`time_paired_drift`'s first window must not lock onto a musical alias.

I_Ball's original is self-similar at every multiple of its row, so a first
window searched over +/-100 holds a dozen near-equal peaks and the largest is
not the real one; the tracker then can only slide a few frames from it.
Synthetic traces here: a strictly periodic original, and a conversion whose
true offset is small but which is missing part of the first window's
attacks, so that one period later the vote is larger.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F  # noqa: E402
from test_time_paired_drift import _song, _traces  # noqa: E402

PERIOD = 60
LAG = 4


def _periodic(n_frames=6000):
    voices = []
    for k in range(3):
        base = (0, 12, 24, 36, 48)
        voices.append([p + b + 7 * k for p in range(40, n_frames, PERIOD)
                       for b in base])
    return voices


def _aliased_pair():
    th = _periodic()
    rng = random.Random(3)
    ours = []
    for fs in th:
        out = []
        for f in fs:
            # first window: drop 40% of the true-offset partners, except the
            # last period's worth, whose alias partners lie in window 1
            if f < 500 - PERIOD and rng.random() < 0.15:
                continue
            out.append(f + LAG)
        ours.append(out)
    return th, ours


def test_the_first_window_is_not_locked_one_period_away():
    th, ours = _aliased_pair()
    got = F.time_paired_drift(*_traces(th, ours))
    assert got["per_1000"] is not None, got
    assert got["lag"] == LAG, got["windows"][:3]
    assert abs(got["per_1000"]) < 0.3, got


def test_a_first_window_offset_inside_the_seed_radius_is_still_found():
    # an irregular original has no alias, so the nearest-to-zero rule must
    # not drag a real offset of 25 down to a smaller one
    th = _song()
    ours = [[f + 25 for f in fs] for fs in th]
    got = F.time_paired_drift(*_traces(th, ours))
    assert got["lag"] == 25, got["windows"][:3]
    assert abs(got["per_1000"]) < 0.3, got


def test_the_seed_radius_is_below_the_musical_period():
    assert F.TP_INIT_RADIUS < PERIOD
