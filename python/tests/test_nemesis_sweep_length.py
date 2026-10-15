"""A record that mostly ends on an unfiltered follower sweeps its stops' travel.

`_best_sweep_length` picked the length minimising the absolute error over a
record's gaps, which is their weighted median. Nemesis_the_Warlock's record 2
(the filter sweep, +2 a frame, reset at every fetch at $E0D1) is struck 105
times in one pass and 91 of them end on an unfiltered record: gaps of 32
calls x 54, 64 x 34, 96 x 4, 128 x 13. The median is 32, the conversion swept
32 calls (33 changes) a strike where the player's ran 128, 95, 64 and 32
frames by the bar, and `cutoff_sweep` read 0.500 (travel 2.28M of 4.56M).
For a stop-majority record the length is now the smallest one whose total
travel matches the player's (57 calls; `cutoff_sweep` 0.887, travel 4.05M).

The gate on the original side is the voice's NEXT NOTE's instrument: `$E500,X`
changes at the fetch and the filter block at `$E3AD` is only reached for a
record whose status byte (`$E648`) carries bit 5, so the sweep ends where the
voice's next note is an unfiltered record. That is per occurrence; the
program is global, so one length per record is a compromise
(`classic-filter-stop-on-unfiltered-follower` is the per-occurrence repair).

Measured at 4833cff, presets, -t 180, the 23 files of the classic-sweep
movers: only Nemesis_the_Warlock moves (0.500 -> 0.887); Deep_Strike (0.893)
and Thundercats (1.085) are byte-identical. Four global rules tried first
(balance everywhere; the stops' mean; a half-weighted shortfall; balance with
the sweep capped at the next filtered strike on any voice) each moved Sanxion
(1.100 -> 1.19..1.36) and Dragons_Lair_Part_II (0.835 -> 0.62..0.75) away
from 1, so the rule is held to a stop majority.
"""
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.goatwriter import _best_sweep_length

REPO = Path(__file__).resolve().parents[2]

# Nemesis' record 2, in calls (4 per pattern row): (gap, next record unfiltered)
NEMESIS = ([(32, True)] * 54 + [(64, True)] * 32 + [(64, False)] * 2
           + [(96, True)] * 4 + [(128, False)] * 12 + [(128, True)])


def test_nemesis_record_2_is_swept_to_the_total_the_player_makes():
    """SABOTAGE TARGET: drop the stop-majority branch and this is the median,
    32 (cutoff_sweep 0.500)."""
    assert _best_sweep_length(NEMESIS) == 57


def test_that_length_is_where_the_shortfall_crosses_zero():
    """SABOTAGE TARGET: `<= 0` -> `< 0` (or `lo = mid + 1` on the wrong side)
    moves it off the smallest crossing length."""
    def shortfall(length):
        return sum((g - length) if stop else max(g - length, 0)
                   for g, stop in NEMESIS)
    got = _best_sweep_length(NEMESIS)
    assert shortfall(got) <= 0 < shortfall(got - 1)


def test_the_branch_needs_a_stop_majority():
    """SABOTAGE TARGET: `2 * stops <= len(gaps)` -> `<`: an even split would
    leave the median."""
    skewed = [(32, True)] * 4 + [(64, False)] * 2 + [(128, False)] * 2
    assert sum(1 for _, s in skewed if s) * 2 == len(skewed)
    assert _best_sweep_length(skewed) == 32      # the median, unchanged
    # and Sanxion's shape (29% stops, median 6) keeps its 6
    sanxion = ([(6, False)] * 436 + [(6, True)] * 221 + [(12, False)] * 110
               + [(12, True)] * 3)
    assert _best_sweep_length(sanxion) == 6


def test_all_stops_is_the_mean_of_the_gaps():
    assert _best_sweep_length([(10, True), (30, True)]) == 20
    assert _best_sweep_length([(7, True)]) == 7


def test_a_short_filtered_gap_is_not_travel_to_credit_against_the_stops():
    """SABOTAGE TARGET: drop the `max(.., 0)` on the filtered gaps and a gap
    the sweep already outlasts (the next strike restarts it, so it overshoots
    nothing) is counted as travel ours made too much, pulling 100 down to 78."""
    assert _best_sweep_length([(100, True)] * 3 + [(10, False)]) == 100


def test_a_record_with_no_stops_is_the_longest_gap_as_before():
    assert _best_sweep_length([(96, False), (128, False), (64, False)]) == 128


@needs_corpus
def test_nemesis_sweeps_128_calls_in_the_conversion():
    """At the seam, under the shipped presets: record 2's modulation rows.
    128 (a $7F row and a 1) since `classic_filter_stop` stops the sweep on the
    unfiltered followers, so the stop-majority travel match (57) is not
    needed: the length is the longest gap."""
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    blob = convert(str(CORPUS / "Nemesis_the_Warlock.sid"), log=lambda m: None,
                   **F._preset_opts(doc, "Nemesis_the_Warlock.sid"))
    ftbl = parse_sng(blob).tables["FTBL"]
    assert ((127, 2) in ftbl and (1, 2) in ftbl
            and (57, 2) not in ftbl and (32, 2) not in ftbl), ftbl
