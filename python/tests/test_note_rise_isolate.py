"""The rise runs on through rest rows a pattern shares with other notes.

Game_Killer's rise (bit $02, `$0B33`) runs on through the bit-6 event after a
note exactly as Chimera's does (`detect.note_rise_rest_carries_on`), but the
rows it runs through are a rest pattern the orderlists play after other notes
too: pattern `$0B` is played four times and two follow a rise note, so each
of its rows is asked for twice in four plays and the planner called it
`mixed` and carried on 136 stores with 0 placed. Battle_of_Britain (97
carried, 58 placed) and Human_Race (18, 1) were the same. `note_rise._isolate`
gives each spelling of such a pattern a copy of its own, the orderlist byte
repointed (same length, same place), and plans again on the copies.

Crazy_Comets is the one that stays: its rest pattern is played in a repeat
(`$D4`/`$D5`, five visits), only the first of which follows the note, and an
orderlist byte cannot be unrolled in place.
"""
import pathlib
import sys

import pytest

from corpus import needs_corpus
from test_note_rise import (_agreement, _converted, needs_gt2reloc,
                            needs_siddump)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import note_rise as R                    # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402


def test_lap_positions_are_the_orderlist_byte_of_every_row_of_the_lap():
    patterns = [[0x60, 1, 0, 0, 0xBD, 0, 0, 0, 0xFF, 0, 0, 0],
                [0x61, 1, 0, 0, 0xFF, 0, 0, 0]]
    track = [0xF2, 0xD1, 0, 1, 0xFF, 0]    # transpose, repeat 2, 0, 1, restart
    rows = list(S._lap_rows(track, patterns))
    pos = list(R._lap_positions(track, patterns))
    assert len(rows) == len(pos) == 5
    assert pos == [2, 2, 2, 2, 3]
    assert [p for p, _r, _t in rows] == [0, 0, 0, 0, 1]
    # the restart's operand ends the lap
    assert list(R._lap_positions([0, 0xFF, 1, 1], patterns)) == [0, 0]


def test_visits_count_every_play_of_a_row_by_pattern_and_by_position():
    patterns = [[0x60, 1, 0, 0, 0xFF, 0, 0, 0],
                [0xBD, 0, 0, 0, 0xBD, 0, 0, 0, 0xFF, 0, 0, 0]]
    tracks = [[0xD2, 1, 0, 1, 0xFF, 0], [1, 0xFF, 0]]
    plays, pos_plays, lap_pos = R._lap_visits(tracks, patterns)
    assert plays == {(1, 0): 5, (1, 1): 5, (0, 0): 1}
    # a repeat is three visits of one position
    assert pos_plays == {(0, 1, 0): 3, (0, 1, 1): 3, (0, 2, 0): 1,
                         (0, 3, 0): 1, (0, 3, 1): 1, (1, 0, 0): 1,
                         (1, 0, 1): 1}
    assert lap_pos == {0: [1, 1, 1, 1, 1, 1, 2, 3, 3], 1: [0, 0]}


def _two_positions():
    """Pattern 1 (a rest) played at positions 0 and 1 of one voice, 2 rows."""
    patterns = [[0x60, 1, 0, 0, 0xFF, 0, 0, 0],
                [0xBD, 0, 0, 0, 0xBD, 0, 0, 0, 0xFF, 0, 0, 0]]
    tracks = [[1, 1, 0, 0xFF, 0]]
    plays = {(0, 0, 0): 1, (0, 0, 1): 1, (0, 1, 0): 1, (0, 1, 1): 1}
    return tracks, patterns, plays


def test_positions_that_spell_a_pattern_differently_get_a_copy_each():
    tracks, patterns, plays = _two_positions()
    ask = (((3, 0),), True)
    asks = {(0, 0, 1): [ask]}
    new_tracks, new_patterns, copies = R._isolate(tracks, patterns, asks,
                                                  plays, {1})
    assert copies == 1
    # the group that asks nothing stays on the pattern; the asking one moves
    assert new_tracks == [[2, 1, 0, 0xFF, 0]]
    assert new_patterns[2] == patterns[1] and new_patterns[2] is not patterns[1]
    assert new_patterns[:2] == patterns
    assert len(new_tracks[0]) == len(tracks[0])
    assert tracks == [[1, 1, 0, 0xFF, 0]]          # the arguments are not touched


def test_positions_that_spell_it_the_same_way_stay_on_one_pattern():
    tracks, patterns, plays = _two_positions()
    ask = (((3, 0),), True)
    asks = {(0, 0, 1): [ask], (0, 1, 1): [ask]}
    assert R._isolate(tracks, patterns, asks, plays, {1})[2] == 0
    assert R._isolate(tracks, patterns, {}, plays, {1})[2] == 0


def test_a_position_whose_visits_disagree_is_not_a_spelling_of_its_own_kind():
    """A row asked on one of two visits (a repeated rest pattern) is marked,
    not taken as the store; two stores for the same row differ."""
    tracks, patterns, plays = _two_positions()
    plays[(0, 0, 1)] = 2
    ask = (((3, 0),), True)
    once = {(0, 0, 1): [ask]}
    # a marker is not the store: position 0 differs from position 1 (which
    # asks nothing), so it still gets a copy -- but not the same copy as a
    # position that asks the store on every visit
    assert R._isolate(tracks, patterns, once, plays, {1})[2] == 1
    # the same store on every visit of one position is one spelling
    both = {(0, 0, 1): [ask, ask], (0, 1, 1): [ask]}
    assert R._isolate(tracks, patterns, both, plays, {1})[2] == 0
    diff = {(0, 0, 1): [ask, (((4, 0),), True)], (0, 1, 1): [ask]}
    assert R._isolate(tracks, patterns, diff, plays, {1})[2] == 1


def test_only_the_patterns_asked_about_are_copied():
    tracks, patterns, plays = _two_positions()
    asks = {(0, 0, 1): [(((3, 0),), True)]}
    assert R._isolate(tracks, patterns, asks, plays, {0})[2] == 0


def test_a_full_pattern_table_takes_no_copy():
    tracks, patterns, plays = _two_positions()
    patterns = patterns + [[0xFF, 0, 0, 0]] * (R._SONG_MAX_PATTERNS - 2)
    assert len(patterns) == R._SONG_MAX_PATTERNS
    asks = {(0, 0, 1): [(((3, 0),), True)]}
    t, p, n = R._isolate(tracks, patterns, asks, plays, {1})
    assert n == 0 and t is tracks and p is patterns


@needs_corpus
def test_three_more_files_carry_the_rise_through_their_rest_rows():
    got = {}
    for name in ("Game_Killer", "Battle_of_Britain", "Human_Race"):
        sng, lines, _ = _converted(name)
        (rise,) = [m for m in lines if "Note rise (bit $02)" in m]
        got[name] = rise
    assert "3 note(s) carried on" in got["Game_Killer"]
    assert "2 pattern copy(ies) for the rest rows" in got["Game_Killer"]
    assert "1 note(s) carried on" in got["Battle_of_Britain"]
    assert "1 pattern copy(ies) for the rest rows" in got["Battle_of_Britain"]
    assert "1 note(s) carried on" in got["Human_Race"]


@needs_corpus
@pytest.mark.parametrize("name,rows", [("Game_Killer", None),
                                       ("Battle_of_Britain", "370 store row(s)"),
                                       ("Human_Race", None)])
def test_without_the_copies_the_rest_rows_are_mixed(name, rows, monkeypatch):
    """The rest rows are `mixed` without a copy. Game_Killer and Human_Race
    then place under half of what they carry on and keep the plan without
    the continuation; Battle_of_Britain places 58 of 97 and keeps 370 rows
    where the copy takes 409."""
    monkeypatch.setattr(R, "_isolate", lambda t, p, *a: (t, p, 0))
    _sng, lines, _ = _converted(name)
    (rise,) = [m for m in lines if "Note rise (bit $02)" in m]
    assert "pattern copy" not in rise, rise
    if rows is None:
        assert "carried on" not in rise, rise
    else:
        assert rows in rise and "41 row(s) mixed" in rise, rise


@needs_corpus
def test_the_orderlists_keep_their_length_and_name_only_real_patterns():
    import songview
    for name in ("Game_Killer", "Battle_of_Britain", "Human_Race"):
        sng, _lines, _ = _converted(name)
        song = songview.parse_sng(sng)
        assert len(song.patterns) <= R._SONG_MAX_PATTERNS, name
        assert len(song.patterns) > 0


def _keep_rise(lo, hi):
    return lambda h, onset: lo <= h - onset <= hi


def _keep_fall(lo, hi):
    return lambda h, onset: lo <= onset - h <= hi


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_game_killers_whole_rise_lands_closer_on_the_originals_frames(
        tmp_path, monkeypatch):
    """-t 150, voice 0, the $0A9 record, packed through gt2reloc: the frames
    3 to $7F above the note. 435 of 765 before, 462 after (the notes' own
    stores are the same 56 of 123 in the narrow window)."""
    wide = _agreement("Game_Killer", 9, 150, 0x0A9, _keep_rise(3, 0x7F),
                      tmp_path, "wide")[0]
    assert wide[0] >= 700 and wide[1] >= 0.59 * wide[0], wide
    monkeypatch.setattr(R, "note_rise_rest_carries_on", lambda *a, **k: False)
    without = _agreement("Game_Killer", 9, 150, 0x0A9, _keep_rise(3, 0x7F),
                         tmp_path, "without")[0]
    assert without[0] == wide[0] and without[1] <= 0.58 * wide[0], (wide,
                                                                    without)
    narrow = _agreement("Game_Killer", 9, 60, 0x0A9, _keep_rise(3, 0x20),
                        tmp_path, "narrow")[0]
    assert narrow[1] >= 0.4 * narrow[0], narrow


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_battle_of_britains_rest_stores_land_on_the_originals_frames(
        tmp_path, monkeypatch):
    """-t 60 at -S2, voice 0, the $0FF record, the frames 1 to $7F below the
    note: 30 of 127 before, 52 after."""
    got = _agreement("Battle_of_Britain", 2, 60, 0x0FF, _keep_fall(1, 0x7F),
                     tmp_path, "emitted")[0]
    assert got[0] >= 120 and got[1] >= 0.38 * got[0], got
    monkeypatch.setattr(R, "note_rise_rest_carries_on", lambda *a, **k: False)
    without = _agreement("Battle_of_Britain", 2, 60, 0x0FF,
                         _keep_fall(1, 0x7F), tmp_path, "without")[0]
    assert without[0] == got[0] and without[1] <= 0.28 * got[0], (got, without)
