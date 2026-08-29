"""The `-S` factor is chosen from the subtune the file STARTS on.

A packed `.sid` has ONE call rate and its subtunes disagree about what they
want. Until v0.5.410 the rate came from subtune 0, on `derived_group_tempos`'
stated reasoning that subtune 0 is "the canonical tune, and what a packed .sid
plays by default". The second half is false: what a packed `.sid` plays by
default is the PSID header's `startSong`, which is exactly why
`fidelity.resolve_subtune` exists.

Censused at v0.5.409, twelve corpus files have SOME subtune wanting a higher
multiplier than subtune 0; only two have a *start* subtune that does, and those
two are the whole of the change's reach:

    Kings_of_the_Beach_ingame  start 4   8/3 frames   -S1 -> -S3
    Knucklebusters             start 1   7/3 frames   -S1 -> -S3

The tests that matter here are the last two. A rate written into the `.sng` and
a rate the packer uses must be THE SAME NUMBER, and this repo has shipped them
disagreeing: CLAUDE.md records Las Vegas converting to silence and Samantha Fox
playing three times too fast, both with `melody` still reading 100%, because a
detection change moved the row and one of the five derivation sites did not
move with it. There are five, they are in three files, and nothing but a test
across them can see that they agree.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                     # noqa: E402

import fidelity                                             # noqa: E402
import presets                                              # noqa: E402
from h2g.convert import _derived_multiplier, _detect_tables  # noqa: E402
from h2g.goatwriter import (SongSpeeds, find_song_speeds,    # noqa: E402
                            pack_subtune, recommended_multiplier)
from h2g.sidfile import load_sid                            # noqa: E402

# start_song is 1-based; these are the two files the rule reaches.
MOVED = {"Kings_of_the_Beach_ingame.sid": (4, 3),
         "Knucklebusters.sid": (1, 3)}


def _speeds(frames):
    return SongSpeeds(frames=frames, reload_addr=0x1000, table_addr=None)


def test_start_song_is_one_based():
    """The header counts from 1 and the tables from 0."""
    sp = _speeds((3, 2, 4))
    assert pack_subtune(sp, 1) == 0
    assert pack_subtune(sp, 3) == 2


def test_an_out_of_range_start_song_falls_back_to_zero():
    """A header over-declares routinely -- CLAUDE.md's three bounds exist for
    it -- so a startSong past the speeds table must not index off the end."""
    assert pack_subtune(_speeds((3, 2)), 9) == 0


def test_no_speeds_still_answers():
    assert pack_subtune(None, 4) == 3


def test_the_rule_only_matters_where_the_subtunes_disagree():
    """Subtune 0's value is kept wherever the start subtune wants the same."""
    sp = _speeds((3, 3, 3))
    assert recommended_multiplier(sp, pack_subtune(sp, 2), True) == \
        recommended_multiplier(sp, 0, True)


@needs_corpus
def test_the_two_files_pack_for_the_subtune_they_open_on():
    for name, (start, want) in MOVED.items():
        sid = load_sid(str(CORPUS / name))
        assert sid.start_song - 1 == start, name
        sid2, det = _detect_tables(sid, lambda m: None)
        speeds = find_song_speeds(sid2, det)
        # The defect: subtune 0 asks for less than the subtune that plays.
        assert recommended_multiplier(speeds, 0, True) < want, name
        assert recommended_multiplier(
            speeds, pack_subtune(speeds, sid.start_song), True) == want, name


@needs_corpus
def test_every_derivation_site_agrees_on_the_pack_factor():
    """The invariant a listener cannot hear until the file is silent.

    `presets.pack_multiplier` writes the number into presets.json, the
    converter scales every per-call rate by its own, and
    `fidelity._skip_gate_multiplier` re-derives a third for the trace. Two of
    the three disagreeing is a `.sng` written for one rate and packed at
    another.
    """
    for name, (_start, want) in MOVED.items():
        path = CORPUS / name
        sid = load_sid(str(path))
        _sid2, det = _detect_tables(sid, lambda m: None)
        assert presets.pack_multiplier(path) == want, f"presets {name}"
        assert fidelity._skip_gate_multiplier(path) == want, f"fidelity {name}"
        assert _derived_multiplier(sid, det, True) == want, f"convert {name}"
