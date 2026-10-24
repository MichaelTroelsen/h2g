"""A pattern's last event is measured THROUGH event-less successor patterns.

Bump_Set_Spike's GT 13 (`$0A0A`, a drum-only record) is selected on the last
row of pattern 3, whose successor is a one-row hold pattern that holds no event
of its own. `median_played_durations` read that as "no resolvable successor"
and dropped the note, so the record had no known length and kept the pitch
bound alone: 24 `CMD_PORTADOWN` steps, 31 wavetable entries on a table that is
255 of 255. The note lasts two rows (the last row, the hold row) and the
original holds `0DD0` for all of them -- traced at 240 s the six notes read
`0DD0` on every frame to the next note, with no sweep. Figures are historical
(v0.5.541, presets).

The walk goes on over the event-less pattern's own successors, each by its
share of the ways the orderlist leaves it; a walk that revisits a pattern or
runs out of orderlist contributes nothing, so a note it cannot place stays
unknown, as before.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import h2g.convert  # noqa: E402,F401  (import order: patterns <-> goatwriter cycle)
from h2g.goatwriter.constants import WAVECMD_PORTADOWN  # noqa: E402
from h2g.patterns import median_played_durations  # noqa: E402

END = [0xFF, 0, 0, 0]
HOLD = [0xBD, 0, 0, 0]
REPEAT2 = 0xD1


def _pat(*events):
    """events: (instrument, rows) -- each a note then rows-1 hold rows."""
    out = []
    for instr, rows in events:
        out += [0x60, instr, 0, 0] + HOLD * (rows - 1)
    return out + END


def _hold(rows):
    """A pattern with no event at all: `rows` hold rows."""
    return HOLD * rows + END


def test_last_event_runs_through_an_event_less_pattern():
    # Pattern 0 ends on a 1-row note of instrument 2; pattern 1 is one hold
    # row; pattern 2 opens on a note. 1 + 1 + 0.
    pats = [_pat((3, 3), (2, 1)), _hold(1), _pat((3, 2))]
    assert median_played_durations([[0, 1, 2]], pats)[2] == 2


def test_it_runs_through_a_chain_of_them():
    pats = [_pat((3, 3), (2, 1)), _hold(1), _hold(3), _pat((3, 2))]
    assert median_played_durations([[0, 1, 2, 3]], pats)[2] == 1 + 1 + 3


def test_an_event_less_pattern_adds_its_rows_up_to_the_end_marker():
    # Rows after the ENDPATT row are never played.
    pats = [_pat((2, 1)), _hold(2) + HOLD * 5, _pat((3, 2))]
    assert median_played_durations([[0, 1, 2]], pats)[2] == 1 + 2


def test_the_next_events_leading_hold_rows_still_count():
    nxt = HOLD * 2 + _pat((3, 2))
    pats = [_pat((2, 1)), _hold(1), nxt]
    assert median_played_durations([[0, 1, 2]], pats)[2] == 1 + 1 + 2


def test_an_orderlist_that_ends_in_an_event_less_pattern_stays_unknown():
    pats = [_pat((3, 3), (2, 1)), _hold(1)]
    assert 2 not in median_played_durations([[0, 1]], pats)


def test_a_cycle_of_event_less_patterns_stays_unknown():
    # Pattern 1 restarts onto itself: nothing ever reaches an event.
    pats = [_pat((3, 3), (2, 1)), _hold(1)]
    assert 2 not in median_played_durations([[0, 1, 0xFF, 1]], pats)


def test_a_repeated_event_less_pattern_stays_unknown():
    # [REPEAT x2, 1] plays the hold pattern twice: every play holds the note,
    # so the gap is 1 + 2 + the successor's lead, and the successor table only
    # has an edge from the pattern to itself and one onward. Reading a share
    # off that would say 2 (the onward edge alone) -- wrong -- so it is left
    # unknown, as before.
    pats = [_pat((3, 3), (2, 1)), _hold(1), _pat((3, 2))]
    assert 2 not in median_played_durations([[0, REPEAT2, 1, 2]], pats)
    # ... while the same pattern played once is measured.
    assert median_played_durations([[0, 1, 2]], pats)[2] == 2


def test_a_cycle_through_two_event_less_patterns_stays_unknown():
    pats = [_pat((3, 3), (2, 1)), _hold(1), _hold(1)]
    assert 2 not in median_played_durations([[0, 1, 2, 0xFF, 1]], pats)


def test_branches_are_weighted_by_how_often_the_orderlists_take_them():
    short = _pat((3, 2))                       # gap 1 + 1 + 0 = 2
    long = HOLD * 2 + _pat((3, 2))             # gap 1 + 1 + 2 = 4
    pats = [_pat((3, 3), (2, 1)), _hold(1), short, long]
    # Three voices reach pattern 1; two leave to the short one, one to the
    # long one: the median is the short gap ...
    two_short = [[0, 1, 2], [0, 1, 2], [0, 1, 3]]
    assert median_played_durations(two_short, pats)[2] == 2
    # ... and with the proportions swapped it is the long one.
    two_long = [[0, 1, 2], [0, 1, 3], [0, 1, 3]]
    assert median_played_durations(two_long, pats)[2] == 4


def test_a_successor_with_an_event_is_measured_as_before():
    # The existing rule (test_pattern_last_event) is untouched.
    pats = [_pat((3, 3), (2, 1)), _pat((3, 2))]
    assert median_played_durations([[0, 1]], pats) == {3: 3, 2: 1}


def _converted(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng[0] if isinstance(sng, tuple) else sng


def _block(song, number):
    """(entries up to its stop, CMD_PORTADOWN entries) of an instrument."""
    wt = song.tables["WTBL"]
    k = song.instruments[number - 1].wave_ptr - 1
    start = k
    steps = 0
    while wt[k][0] != 0xFF:
        steps += wt[k][0] == WAVECMD_PORTADOWN
        k += 1
    return k - start + 1, steps


@needs_corpus
def test_bump_set_spike_gt13_has_no_sweep_and_gives_its_entries_back():
    import songview
    song = songview.parse_sng(_converted("Bump_Set_Spike"))
    ad, sr = song.instruments[12].ad, song.instruments[12].sr
    assert (ad, sr) == (0x0A, 0x0A)
    length, steps = _block(song, 13)
    assert steps == 0, "the original holds the frequency for the whole note"
    assert length <= 6, length
    # It was 24 steps and 31 entries on a table that is full.
    assert len(song.tables["WTBL"]) < 255
