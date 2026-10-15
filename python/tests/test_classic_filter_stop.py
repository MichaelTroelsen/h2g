"""The classic filter sweep stops where the sweeping voice moves to an
unfiltered record: `A 00` on that note.

The player sweeps a voice's cutoff only while the voice's record filters; an
unfiltered record's instrument loads no filter pointer, so Goattracker's one
global program kept running past the note that ended the original's sweep, and
`classic_sweep_calls` could only size ONE length per record as a compromise
(`_best_sweep_length`). `CMD_SETFILTERPTR` with data 0 stops the program where
it stands (gplay.c:459, player.s `mt_tick0_a`), so a placed stop frees the
length to be the record's longest gap.

Measured at f28b063 (presets, -t 180, `cutoff_sweep` ours/original travel,
before -> after): Nemesis_the_Warlock 0.887 -> 1.019, Dragons_Lair_Part_II
0.835 -> 0.915, Deep_Strike 0.893 -> 1.085, Knucklebusters 1.272 -> 1.268;
away from 1: Sanxion 1.100 -> 1.162 (its original sweeps 5 frames whatever
the gap, which nothing here reads), Lightforce 1.147 -> 1.150, Food_Feud
1.101 -> 1.103, Nineteen 0.451 -> 0.449.
"""
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.goatwriter import (CMD_SETFILTERPTR, apply_stops, classic_filter_stops,
                            classic_sweep_calls, _stop_row)

REPO = Path(__file__).resolve().parents[2]
NOTE, REST, END = 0x60, 0xBD, 0xFF


def _pattern(rows):
    flat = []
    for note, ins, cmd, dat in rows:
        flat += [note, ins, cmd, dat]
    return flat + [END, 0, 0, 0]


def _voice(*rows):
    return [_pattern(rows)], [[0, END, 0]]


# --- where a stop goes -----------------------------------------------------------

def test_a_free_note_row_takes_the_stop():
    pattern = _pattern([(NOTE, 4, 0, 0), (REST, 0, 0, 0)])
    assert _stop_row(pattern, 0) == 0


def test_an_occupied_note_row_passes_the_stop_to_the_next_free_row():
    """SABOTAGE TARGET: dropping the `cmd == 0` test writes over a command."""
    pattern = _pattern([(NOTE, 4, 8, 3), (REST, 0, 0, 0), (REST, 0, 0, 0)])
    assert _stop_row(pattern, 0) == 1


def test_a_running_command_takes_no_stop():
    """A slide or vibrato started on the note row (or on the way) is a running
    command a one-shot is not put under."""
    assert _stop_row(_pattern([(NOTE, 4, 1, 9), (REST, 0, 0, 0)]), 0) is None
    assert _stop_row(_pattern([(NOTE, 4, 8, 3), (REST, 0, 4, 9),
                               (REST, 0, 0, 0)]), 0) is None


def test_the_stop_does_not_run_into_the_next_note():
    pattern = _pattern([(NOTE, 4, 8, 3), (NOTE, 4, 0, 0)])
    assert _stop_row(pattern, 0) is None


# --- the plan --------------------------------------------------------------------

def _plan(rows, filtered=frozenset({2})):
    patterns, tracks = _voice(*rows)
    return classic_filter_stops(tracks, patterns, set(filtered), 1, 4)


def test_a_stop_is_owed_where_a_filtered_record_gives_way_to_an_unfiltered_one():
    lengths, sites, stats = _plan([(NOTE, 3, 0, 0), (REST, 0, 0, 0),
                                   (REST, 0, 0, 0), (NOTE, 4, 0, 0),
                                   (REST, 0, 0, 0)])
    assert sites == {(0, 0): frozenset({3})}
    assert (stats["wanted"], stats["placed"]) == (1, 1)


def test_a_filtered_follower_is_owed_no_stop():
    """SABOTAGE TARGET: `nxt not in filtered` -> `True` stops a program the
    next filtered record is about to replace anyway."""
    _l, sites, stats = _plan([(NOTE, 3, 0, 0), (REST, 0, 0, 0),
                              (NOTE, 3, 0, 0), (REST, 0, 0, 0)])
    assert sites == {} and stats["wanted"] == 0


def test_an_unfiltered_note_after_an_unfiltered_note_is_owed_none():
    """The sweeping voice is the one whose last record filtered."""
    _l, sites, _s = _plan([(NOTE, 4, 0, 0), (REST, 0, 0, 0),
                           (NOTE, 4, 0, 0), (REST, 0, 0, 0)])
    assert sites == {}


def test_a_placed_stop_frees_the_length_from_the_stopping_gap():
    """SABOTAGE TARGET: leaving the placed stop's gap marked as a stop gives
    back the old compromise (the stopping gap's 8, not the filtered 16)."""
    rows = [(NOTE, 3, 0, 0)] + [(REST, 0, 0, 0)] * 1 + [(NOTE, 4, 0, 0)]
    rows += [(NOTE, 3, 0, 0)] + [(REST, 0, 0, 0)] * 3 + [(NOTE, 3, 0, 0),
                                                         (REST, 0, 0, 0)]
    lengths, _sites, _stats = _plan(rows)
    old = classic_sweep_calls(*reversed(_voice(*rows)), {2}, 1, 4)
    assert old == {2: 8}                # 2 stops-bounded and 1 free: median-ish
    assert lengths == {2: 16}           # the longest gap, now the stop is made


def test_a_stop_with_no_free_column_keeps_its_gap_a_stop():
    lengths, sites, stats = _plan([(NOTE, 3, 0, 0), (NOTE, 4, 8, 1)])
    assert sites == {} and stats["no column"] == 1
    assert lengths == {2: 4}


def test_a_pattern_played_twice_with_one_follower_needs_both_plays_to_agree():
    # pattern 0: filtered note then an unfiltered note; pattern 1: the same
    # first note, but the voice then plays the filtered record again
    p0 = _pattern([(NOTE, 3, 0, 0), (NOTE, 4, 0, 0)])
    p1 = _pattern([(NOTE, 3, 0, 0), (NOTE, 3, 0, 0)])
    tracks = [[0, 1, END, 0]]
    _l, sites, stats = classic_filter_stops(tracks, [p0, p1], {2}, 1, 4)
    assert sites == {(0, 0): frozenset({1})}      # only p0's follower is owed
    # the same pattern played twice: both plays want row 1
    _l, sites, stats = classic_filter_stops([[0xD1, 0, END, 0]], [p0], {2},
                                            1, 4)
    assert sites == {(0, 1): frozenset({1})}
    assert (stats["wanted"], stats["placed"]) == (2, 2)
    # a pattern that starts on an unfiltered note: only its second play
    # follows a filtered one, so the plays disagree and no stop is written
    q = _pattern([(NOTE, 4, 0, 0), (NOTE, 3, 0, 0)])
    _l, sites, stats = classic_filter_stops([[0xD1, 0, END, 0]], [q], {2},
                                            1, 4)
    assert sites == {} and (stats["wanted"], stats["disagree"]) == (1, 1)


# --- the write -------------------------------------------------------------------

def test_the_stop_is_a_setfilterptr_to_zero():
    """SABOTAGE TARGET: a nonzero data byte points the program at a row."""
    patterns, tracks = _voice((NOTE, 3, 0, 0), (REST, 0, 0, 0),
                              (NOTE, 4, 0, 0), (REST, 0, 0, 0))
    _l, sites, _s = classic_filter_stops(tracks, patterns, {2}, 1, 4)
    new_patterns, new_tracks, written = apply_stops(tracks, patterns, sites)
    assert written == 1
    row = new_patterns[0][4 * 2:4 * 3]
    assert row[2:] == [CMD_SETFILTERPTR, 0] and CMD_SETFILTERPTR == 0x0A
    assert new_tracks == tracks         # the one position keeps its pattern
    assert patterns[0][4 * 2 + 2] == 0  # the input is not edited in place


def test_a_pattern_wanted_differently_at_two_positions_is_copied():
    """SABOTAGE TARGET: editing the shared pattern puts the stop on a play
    that is not followed by an unfiltered note."""
    p0 = _pattern([(NOTE, 3, 0, 0), (REST, 0, 0, 0)])
    p1 = _pattern([(NOTE, 4, 0, 0)])
    p2 = _pattern([(NOTE, 3, 0, 0)])
    tracks = [[0, 1, END, 0], [0, 2, END, 0]]
    _l, sites, _s = classic_filter_stops(tracks, [p0, p1, p2], {2}, 1, 4)
    assert sites == {(0, 1): frozenset({0})}      # the unfiltered p1 follows
    # a pattern every position of which wants the stop is edited in place
    pats, trs, written = apply_stops([[0, 0, END, 0]], [p0, p1, p2],
                                     {(0, 0): frozenset({0}),
                                      (0, 1): frozenset({0})})
    assert written == 1 and len(pats) == 3 and pats[0][2:4] == [
        CMD_SETFILTERPTR, 0]
    # a stop wanted at only one of two positions of the pattern: a copy
    pats, trs, written = apply_stops(tracks, [p0, p1, p2],
                                     {(0, 0): frozenset({0})})
    assert len(pats) == 4 and trs == [[3, 1, END, 0], [0, 2, END, 0]]
    assert pats[0] == p0 and pats[3][2:4] == [CMD_SETFILTERPTR, 0]


def test_a_column_another_pass_filled_is_left_alone():
    patterns, tracks = _voice((NOTE, 3, 0, 0), (REST, 0, 8, 5))
    _p, _t, written = apply_stops(tracks, patterns, {(0, 0): frozenset({1})})
    assert written == 0


# --- the corpus --------------------------------------------------------------------

def _convert(stem, log=None):
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    return convert(str(CORPUS / f"{stem}.sid"), log=log or (lambda m: None),
                   **F._preset_opts(doc, f"{stem}.sid"))


@needs_corpus
def test_nemesis_carries_the_stops_and_sweeps_its_longest_gap():
    """At the seam, under the shipped presets: Nemesis' record 2 sweeps 128
    calls (the longest of its gaps) and its unfiltered followers stop it."""
    from songview import parse_sng
    song = parse_sng(_convert("Nemesis_the_Warlock"))
    ftbl = song.tables["FTBL"]
    assert any(left == 127 for left, _ in ftbl), ftbl
    stops = [(p, r) for p, pat in enumerate(song.patterns)
             for r in range(len(pat) // 4)
             if pat[4 * r + 2:4 * r + 4] == [CMD_SETFILTERPTR, 0]]
    assert len(stops) >= 4, stops


@needs_corpus
def test_sanxions_stops_are_all_placed_and_none_dropped():
    lines = []
    _convert("Sanxion", lines.append)
    said = [m for m in lines if m.startswith("Classic filter stop")]
    assert any("223 placed" in m for m in said), said
    assert not any("DROPPED" in m for m in said), said


def test_commando_is_untouched():
    ref = (REPO / "Commando.sng").read_bytes()
    assert convert(str(REPO / "Commando.sid"), log=lambda m: None,
                   filters=True) == ref
