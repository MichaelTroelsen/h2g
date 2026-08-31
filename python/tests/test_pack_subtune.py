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


def _speeds_for(path):
    """(sid, det, speeds) for a corpus file, or None if detection declines."""
    try:
        sid = load_sid(str(path))
        sid2, det = _detect_tables(sid, lambda m: None)
        return sid, det, find_song_speeds(sid2, det)
    except Exception:                                            # noqa: BLE001
        return None


@needs_corpus
def test_no_corpus_file_packs_for_a_subtune_it_does_not_start_on():
    """The rule of v0.5.410, asserted over the whole corpus rather than the
    two files it moved.

    `pack_subtune` must return the subtune `fidelity.resolve_subtune` names --
    the header's `startSong`, what a packed .sid plays by default -- except
    where that index is past the speeds table, which a header over-declares
    routinely and where the documented fallback is 0.

    The two existing corpus tests above pin the files the rule CHANGED. This
    pins that it did not quietly change anyone else, which is the half a
    regression would land in: every file it must leave alone.
    """
    seen = agreed = 0
    for path in sorted(CORPUS.glob("*.sid")):
        got = _speeds_for(path)
        if got is None:
            continue
        sid, _det, speeds = got
        seen += 1
        want = fidelity.resolve_subtune(path, "auto")
        ps = pack_subtune(speeds, sid.start_song)
        if speeds is not None and want >= len(speeds.frames):
            assert ps == 0, f"{path.name}: over-declared start must fall back to 0"
        else:
            assert ps == want, f"{path.name}: packs s{ps}, starts on s{want}"
        agreed += 1
    assert seen > 50, "corpus present but almost nothing parsed -- vacuous"
    assert agreed == seen


@needs_corpus
def test_every_derivation_site_agrees_on_every_corpus_file():
    """The Las Vegas invariant, widened from two files to all of them.

    `test_every_derivation_site_agrees_on_the_pack_factor` above checks the
    three sites against a hard-coded expectation for the two files the rule
    moved. The failure that shipped silence was a site NOT moving with a
    detection change, and that can land on any file -- so the three are checked
    against EACH OTHER here, on every tune, with no expected value to go stale.

    Computed from the files, never read from presets.json: the artefact is
    regenerated after a conversion-changing commit rather than during one, so
    asserting against it would fail for the one reason this test is not about.
    """
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        got = _speeds_for(path)
        if got is None:
            continue
        sid, det, _speeds = got
        try:
            a = presets.pack_multiplier(path)
            b = fidelity._skip_gate_multiplier(path)
            c = _derived_multiplier(sid, det, True)
        except Exception:                                        # noqa: BLE001
            continue
        assert a == b == c, f"{path.name}: presets {a}, fidelity {b}, convert {c}"
        checked += 1
    assert checked > 50, f"only {checked} files compared -- vacuous"
