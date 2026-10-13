"""A pattern's LAST event is measured against the orderlist's next pattern.

Chimera's record 8 ($BF05) is played only as the final row of 6-row groups,
so every one of its notes is a pattern's last event; the old rule dropped
them all as "unknown", the instrument had no known note length and kept the
drum's $80 noise on its gate-off row, where the original holds $10 (the
duration guard at $C4DA).
"""
import h2g.convert  # noqa: F401  (import order: patterns <-> goatwriter cycle)
from h2g.patterns import median_played_durations

END = [0xFF, 0, 0, 0]


def _pat(*events):
    """events: (instrument, rows) -- each a note then rows-1 hold rows."""
    out = []
    for instr, rows in events:
        out += [0x60, instr, 0, 0] + [0xBD, 0, 0, 0] * (rows - 1)
    return out + END


def test_last_event_measures_to_the_successors_first_event():
    # Pattern 0 ends on a 1-row note of instrument 2; pattern 1 opens on a
    # note, so the gap is exactly 1.
    pats = [_pat((3, 3), (2, 1)), _pat((3, 2))]
    assert median_played_durations([[0, 1]], pats) == {3: 3, 2: 1}


def test_last_event_adds_the_successors_leading_hold_rows():
    nxt = [0xBD, 0, 0, 0] * 2 + _pat((3, 2))     # opens on two hold rows
    pats = [_pat((3, 3), (2, 1)), nxt]
    assert median_played_durations([[0, 1]], pats)[2] == 3


def test_last_event_with_no_successor_stays_unknown():
    assert 2 not in median_played_durations([[0]], [_pat((3, 3), (2, 1))])


def test_last_event_follows_a_restart_and_a_repeat():
    pats = [_pat((3, 3), (2, 1))]
    assert median_played_durations([[0, 0xFF, 0]], pats)[2] == 1
    # a REPEAT plays the pattern again straight away
    assert median_played_durations([[0xD1, 0, 0xFF, 0]], pats)[2] == 1


def test_a_repeat_counts_the_pattern_as_its_own_successor():
    # [REPEAT x2, 0, 1]: pattern 0 plays twice -- into itself (gap 1), then
    # into pattern 1, which opens on three hold rows (gap 4). The median of
    # {1, 4} is the lower one; ignoring the repeat leaves only the 4.
    nxt = [0xBD, 0, 0, 0] * 3 + _pat((3, 2))
    pats = [_pat((3, 3), (2, 1)), nxt]
    assert median_played_durations([[0xD1, 0, 1]], pats)[2] == 1
