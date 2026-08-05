"""Orderlist compaction by pattern merging.

Slicing splits long patterns and nothing puts short ones back together, so an
orderlist can carry more entries than the music needs. Merging two consecutive
patterns into one costs a pattern-table slot and saves an orderlist byte --
enough to rescue the three subtunes that otherwise exceed Goattracker's
254-byte limit (Gremlins 23, Knucklebusters 0, Monty on the Run 11).

The hazard is the interaction with REPEAT packing. A run of one repeated
pattern packs to two bytes; merging its pairs first would make them distinct
and cost far more. Knucklebusters' middle voice is exactly that case -- 261
bytes packing to 56 -- so merging is costed against the packed result, not
applied blindly before it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import (GT_END_PATTERN, MAX_PATTERNS, MAX_TRACK_LEN,
                          _merge_pass, _merged_pattern, compact_orderlist,
                          reindex_tracks)

ROW = [0x60, 0x01, 0x00, 0x00]          # one sounding row
END = [GT_END_PATTERN, 0x00, 0x00, 0x00]


def _pat(rows, terminated=False):
    return ROW * rows + (END if terminated else [])


# --- building a merged pattern ---------------------------------------------

def test_merging_drops_the_first_pattern_s_end_marker():
    # Goattracker rescans the note column for ENDPATT rather than trusting the
    # stored length, so an interior one would cut the merged pattern in half
    # and the second part would never play.
    pats = [_pat(2, terminated=True), _pat(3)]
    idx = _merged_pattern(0, 1, pats, max_rows=128, cache={})
    assert pats[idx] == ROW * 5
    assert GT_END_PATTERN not in pats[idx][:-4]


def test_the_second_pattern_s_end_marker_is_kept():
    pats = [_pat(2), _pat(3, terminated=True)]
    idx = _merged_pattern(0, 1, pats, max_rows=128, cache={})
    assert pats[idx] == ROW * 5 + END


def test_a_merge_that_would_exceed_the_pattern_length_is_refused():
    pats = [_pat(70), _pat(70)]
    assert _merged_pattern(0, 1, pats, max_rows=128, cache={}) is None
    assert len(pats) == 2                  # nothing appended


def test_a_full_pattern_table_refuses_further_merges():
    pats = [_pat(1) for _ in range(MAX_PATTERNS)]
    assert _merged_pattern(0, 1, pats, max_rows=128, cache={}) is None


def test_the_same_pair_reuses_one_merged_pattern():
    pats, cache = [_pat(1), _pat(1)], {}
    a = _merged_pattern(0, 1, pats, 128, cache)
    b = _merged_pattern(0, 1, pats, 128, cache)
    assert a == b and len(pats) == 3


# --- which neighbours may merge --------------------------------------------

def test_identical_neighbours_are_never_merged():
    # That is REPEAT packing's job, and it does it in two bytes however long
    # the run is.
    pats = [_pat(1), _pat(1)]
    assert _merge_pass([0, 0, 0, 0], pats, 128, {}) == [0, 0, 0, 0]
    assert len(pats) == 2


def test_a_transpose_between_two_patterns_blocks_the_merge():
    # The transpose applies to the second pattern alone; merging would apply
    # it to both.
    pats = [_pat(1), _pat(1)]
    assert _merge_pass([0, 0xF7, 1], pats, 128, {}) == [0, 0xF7, 1]


def test_the_restart_operand_is_never_merged():
    # The byte after $FF is a position, not a pattern.
    pats = [_pat(1), _pat(1)]
    out = _merge_pass([0, 1, 0xFF, 0x01], pats, 128, {})
    assert out[-2:] == [0xFF, 0x01]


def test_distinct_neighbours_merge():
    pats = [_pat(1), _pat(2)]
    out = _merge_pass([0, 1], pats, 128, {})
    assert out == [2] and pats[2] == ROW * 3


# --- costing against packing ------------------------------------------------

def test_a_track_that_already_fits_is_untouched():
    pats = [_pat(1) for _ in range(4)]
    track = [0, 1, 2, 3, 0xFF, 0x00]
    assert compact_orderlist(track, pats, 128, pack=True) == \
        compact_orderlist(track, pats, 128, pack=True)
    assert len(pats) == 4                  # nothing was created


def test_a_run_of_one_pattern_is_left_to_packing():
    # 300 entries of the same pattern: packing gets it to a handful of bytes,
    # and merging must not intervene and make them distinct.
    pats = [_pat(1)]
    track = [0] * 300 + [0xFF, 0x00]
    out = compact_orderlist(track, pats, 128, pack=True)
    assert len(out) < 50
    assert len(pats) == 1


def test_merging_shortens_an_over_long_run_of_distinct_patterns():
    # Alternating patterns defeat packing entirely, so merging is the only
    # lever -- and merged pairs then become a run packing *can* collapse.
    pats = [_pat(1), _pat(1)]
    track = [0, 1] * 150 + [0xFF, 0x00]
    assert len(track) >= MAX_TRACK_LEN
    out = compact_orderlist(track, pats, 128, pack=True)
    assert len(out) < MAX_TRACK_LEN


def test_merging_is_only_attempted_for_over_long_tracks():
    # reindex_tracks passes `patterns` only so merging is possible; a track
    # that already fits must come back byte for byte, or the fixture moves.
    index = [[i] for i in range(8)]
    pats = [_pat(1) for _ in range(8)]
    tracks = [[0, 1, 2, 0xFF, 0x00]] * 3
    out = reindex_tracks(tracks, index, pack=True, patterns=pats, max_rows=128)
    assert out == [[0, 1, 2, 0xFF, 0x00]] * 3
    assert len(pats) == 8
