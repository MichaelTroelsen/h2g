"""Cutting an over-long subtune into consecutive subtunes, in phase.

Goattracker starts *every* voice at orderlist position 0 when a subtune
begins, while the C64 player lets each voice loop its own orderlist
independently. So a cut restarts the short voices, and unless it lands on a
whole number of their loops everything after the seam plays with the
accompaniment offset against the melody.

That is why the cut is not simply "the largest prefix that fits". Monty on the
Run's subtune 11 is the motivating case: a 27530-row voice against two 97-row
voices carrying notes. A greedy rule takes the largest prefix under 254 bytes
and lands mid-figure; the aligned rule takes 251 entries -- 19691 rows,
exactly 203 loops -- and the seam is clean.

Where the short voices are silent there is no phase to preserve and any cut is
exact. That is Gremlins' subtune 23.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import (GT_ORDER_RESTART, MAX_TRACK_LEN, _unpack_repeats,
                          split_subtune)

# Pattern 1 is 4 rows and silent; pattern 2 is 4 rows and sounds a note.
QUIET = [0xBD, 0x00, 0x00, 0x00] * 4
LOUD = [0x70, 0x01, 0x00, 0x00] * 4
PATTERNS = [QUIET, QUIET, LOUD]

TAIL = [GT_ORDER_RESTART, 0x00]


def _long(n):
    """A long voice of n single-pattern entries, each 4 rows."""
    return [0x01] * n + TAIL


def test_two_long_voices_are_refused():
    # Each would need its own cut and the cuts would have to coincide.
    # Knucklebusters is the corpus case: three voices of 21349, 15939 and
    # 19501 rows looping independently.
    group = [_long(300), _long(300), [0x01] + TAIL]
    assert split_subtune(group, PATTERNS, False) is None


def test_a_silent_neighbour_imposes_no_constraint():
    # Silence has no phase, so the cut is free -- Gremlins subtune 23.
    group = [[0x01] + TAIL, [0x01] + TAIL, _long(300)]
    parts = split_subtune(group, PATTERNS, False)
    assert parts is not None
    assert len(parts) == 2
    assert all(len(t) < MAX_TRACK_LEN for voices in parts for t in voices)


def test_every_entry_survives_the_cut():
    group = [[0x01] + TAIL, [0x01] + TAIL, _long(300)]
    parts = split_subtune(group, PATTERNS, False)
    rebuilt = []
    for k, voices in enumerate(parts):
        body = _unpack_repeats(voices[2])[:-2]
        if k and body and 0xE0 <= body[0] < 0xFF:
            body = body[1:]                 # restated transpose, not music
        rebuilt += body
    assert rebuilt == [0x01] * 300


def test_a_sounding_neighbour_forces_an_aligned_cut():
    # The neighbour plays 2 patterns = 8 rows and loops. Every entry of the
    # long voice is 4 rows, so only even entry counts land on a loop boundary.
    neighbour = [0x02, 0x02] + TAIL          # 8 rows, sounding
    group = [neighbour, _long(300), [0x01] + TAIL]
    parts = split_subtune(group, PATTERNS, False)
    assert parts is not None
    first = _unpack_repeats(parts[0][1])[:-2]
    assert len(first) * 4 % 8 == 0, "cut must fall on a whole neighbour loop"


def test_an_impossible_alignment_is_refused_rather_than_forced():
    # The neighbour's loop is longer than anything that fits, so no aligned
    # cut exists. Refusing leaves the caller to drop the subtune, which is
    # better than emitting one that plays out of phase.
    neighbour = [0x02] * 400 + TAIL
    group = [neighbour, _long(300), [0x01] + TAIL]
    assert split_subtune(group, PATTERNS, False) is None


def test_a_group_that_needs_no_cut_is_not_this_function_s_job():
    # reindex_tracks only calls this for a group over the limit, so "nothing
    # to do" is reported as None and the caller keeps the group untouched.
    group = [[0x01] + TAIL, _long(10), [0x01] + TAIL]
    assert split_subtune(group, PATTERNS, False) is None


def test_the_transpose_in_effect_is_restated_after_a_cut():
    # Goattracker resets a voice's transpose to 0 at the start of a subtune
    # (gplay.c:222), so a cut after a transpose must restate it or the
    # remainder plays at the wrong pitch.
    body = [0x01] * 100 + [0xF7] + [0x01] * 200
    group = [[0x01] + TAIL, body + TAIL, [0x01] + TAIL]
    parts = split_subtune(group, PATTERNS, False)
    assert parts is not None and len(parts) >= 2
    second = _unpack_repeats(parts[1][1])
    assert second[0] == 0xF7, "continuation must restate the transpose"
