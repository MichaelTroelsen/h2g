"""The rule that decides a tune ended inside the traced window.

`original_ended` can only ever *shorten* a comparison, and a shorter
comparison removes our surplus notes -- so every column it touches improves by
construction. That makes the interesting tests the ones where it must decline:
a tune with a long rest in the middle, and a tune that simply plays to the end.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fidelity import Voice, original_ended  # noqa: E402


def trace(*per_voice: list[int]):
    voices = []
    for frames in per_voice:
        v = Voice()
        v.attack_frames = list(frames)
        v.attacks = ["C-4"] * len(frames)
        voices.append(v)
    while len(voices) < 3:
        voices.append(Voice())
    return voices


def test_a_tune_that_stops_early_shortens_the_window():
    # Geoff Capes' shape: attacks every ~12 frames to frame 768, then nothing
    # for the remaining 44 seconds of a 60 s window.
    ended = original_ended(trace(list(range(0, 769, 12))), 60)
    assert ended == 768 // 50 + 2


def test_a_tune_that_plays_to_the_end_is_left_alone():
    assert original_ended(trace(list(range(0, 3000, 12))), 60) is None


def test_a_long_rest_in_the_middle_is_not_an_ending():
    """A rest is not an ending -- the tail is measured against the tune's own
    largest gap, not against a fixed fraction of the window."""
    frames = list(range(0, 500, 10)) + list(range(2000, 2400, 10))
    # 600 frames of trailing silence, against an internal gap of 1500.
    assert original_ended(trace(frames), 60) is None


def test_the_tail_must_beat_five_seconds_outright():
    """Twice the largest gap is not enough on a tune whose gaps are tiny."""
    frames = list(range(0, 2800, 4))          # dense, largest gap 4 frames
    assert original_ended(trace(frames), 60) is None
    # ... and the same tune stopping a long way earlier does trigger.
    assert original_ended(trace(list(range(0, 1000, 4))), 60) == 1000 // 50 + 1


def test_a_window_with_no_attacks_is_not_an_ending():
    assert original_ended(trace([]), 60) is None


def test_it_never_shortens_below_five_seconds():
    """A five-second window is its own hazard (BMX_Kidz opens with thirteen
    seconds of rest), so a tune that stops almost immediately keeps the full
    window rather than being scored over a fragment."""
    assert original_ended(trace([0, 10, 20]), 60) is None


def test_it_never_lengthens_the_window():
    for seconds in (10, 60):
        got = original_ended(trace(list(range(0, 200, 10))), seconds)
        assert got is None or got <= seconds
