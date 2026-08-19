"""A per-subtune tempo may not reach a subtune that wants another one.

Patterns are global and orderlists are per subtune, and `CMD_SETTEMPO` under
$80 sets all three channels (gplay.c:494) -- so a value written for subtune j
is executed by every subtune that plays the same pattern, on any voice. These
tests pin the cases in both directions: a clone where the values differ, and
no clone at all where they do not (which is what keeps the byte-exact fixture
and the other 71 corpus files still).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g.patterns import (CMD_SETTEMPO, GT_END_PATTERN, GT_ORDER_RESTART,  # noqa: E402
                          MAX_PATTERNS, apply_tempos)

REST = 0xBD


def row(note=REST, instr=0, cmd=0, dat=0):
    return [note, instr, cmd, dat]


def pattern(rows=2):
    return [b for _ in range(rows) for b in row()] + [GT_END_PATTERN, 0, 0, 0]


def track(*patterns_):
    return list(patterns_) + [GT_ORDER_RESTART, 0]


def tempo_of(patt):
    return patt[3] if patt[2] == CMD_SETTEMPO else None


def test_two_subtunes_sharing_a_pattern_with_different_tempos_clone_it():
    """Human_Race's shape: subtune 1 enters voice 0 on the pattern subtune 0
    enters *voice 2* on, and the two want different rows."""
    patterns = [pattern(), pattern()]
    tracks = [track(1), track(1), track(0),      # subtune 0, voice 2 plays p0
              track(0), track(0), track(0)]      # subtune 1 enters on p0
    written = apply_tempos(patterns, tracks, [4, 3])

    assert written == 2
    assert len(patterns) == 3, "the shared entry pattern was not cloned"
    assert tempo_of(patterns[0]) is None, "the shared pattern still carries one"
    assert tempo_of(patterns[1]) == 4
    assert tempo_of(patterns[2]) == 3
    # Only subtune 1's *entry* reference moved; nothing else was rewritten.
    assert tracks[3][0] == 2
    assert tracks[4] == track(0) and tracks[5] == track(0)


def test_the_same_tempo_on_both_sides_is_left_alone():
    """The harmless case, and the one that must not grow the file: every other
    corpus conversion and the byte-exact fixture depend on it."""
    patterns = [pattern(), pattern()]
    tracks = [track(1), track(1), track(0),
              track(0), track(0), track(0)]
    written = apply_tempos(patterns, tracks, [4, 4])

    assert written == 2
    assert len(patterns) == 2, "cloned a pattern that carried no conflict"
    assert tempo_of(patterns[0]) == 4 and tempo_of(patterns[1]) == 4


def test_a_pattern_another_subtune_plays_mid_song_counts_too():
    """The leak is not only about entry rows: a subtune that reaches the
    pattern later would change tempo partway through."""
    patterns = [pattern(), pattern(), pattern()]
    tracks = [track(0), track(2), track(2),
              track(1, 0), track(2), track(2)]   # subtune 1 reaches p0 second
    apply_tempos(patterns, tracks, [4, 6])

    assert len(patterns) == 4
    assert tempo_of(patterns[0]) is None
    assert tempo_of(patterns[3]) == 4
    assert tempo_of(patterns[1]) == 6


def test_the_write_is_dropped_rather_than_made_wrong_at_the_ceiling():
    patterns = [pattern() for _ in range(MAX_PATTERNS)]
    tracks = [track(1), track(1), track(0),
              track(0), track(0), track(0)]
    written = apply_tempos(patterns, tracks, [4, 3])

    assert len(patterns) == MAX_PATTERNS, "grew past Goattracker's ceiling"
    assert written == 1, "the conflicting write should be dropped, not wrong"
    assert tempo_of(patterns[0]) is None
    assert tempo_of(patterns[1]) == 4


def test_an_occupied_command_column_still_declines():
    patterns = [pattern(), pattern()]
    patterns[1][2] = 3                            # CMD_TONEPORTA on row 0
    tracks = [track(1), track(1), track(1),
              track(0), track(0), track(0)]
    written = apply_tempos(patterns, tracks, [4, 4])

    assert written == 1
    assert tempo_of(patterns[1]) is None


def test_it_refuses_a_value_list_that_does_not_match_the_tracks():
    patterns = [pattern()]
    tracks = [track(0), track(0), track(0)]
    try:
        apply_tempos(patterns, tracks, [4, 3])
    except ValueError:
        return
    raise AssertionError("two values for one subtune should not be accepted")
