"""`startup_lag` does not read an opening original attack ours has no counterpart for.

Pygmies_Revenge's original voice 1 strikes at frame 3 and then at 18, 34, 42 ...
Ours strikes at 23, 39, 47 ...: the opening strike has no attack of ours. The
first-attack difference read 21 where the other two voices (orig 1026 and 514,
ours 1031 and 519) and the voice's own real notes all say 5 (6 once ours is
anchored on its pitched frame). At 21, `wave` read .736 and `adsr` .744; at 6,
.912 and .984 (measured at 841cf3d, -t 180 under presets.json).

The estimator stays a defined signal rather than a fit, so the cases it must
NOT fire on are tested as hard as the one it must: a voice that is simply
aligned (Nineteen, Sanxion), voices that disagree (Chimera), too few attacks.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _v(*attacks):
    return fidelity.Voice(attack_frames=list(attacks))


def _empty():
    return fidelity.Voice()


# Pygmies_Revenge as siddump read it (attack frames, first six per voice).
PYG_ORIG = [_v(1026, 1122, 1250, 1538, 1634, 1762),
            _v(3, 18, 34, 42, 50, 58),
            _v(514, 530, 546, 562, 578, 610)]
PYG_OURS = [_v(1031, 1127, 1255, 1543, 1639, 1767),
            _v(23, 39, 47, 55, 63, 87),
            _v(519, 535, 551, 567, 583, 615)]


# --- the case it exists for --------------------------------------------------

def test_pygmies_revenge_voice_one_opening_attack_is_unmatched():
    assert fidelity.unmatched_openings(PYG_ORIG, PYG_OURS) == {1}


def test_pygmies_revenge_lag_reads_the_real_notes_not_the_stray_opening():
    # 23 - 18: the second original attack stands in for the first.
    assert fidelity.startup_lag(PYG_ORIG, PYG_OURS) == (5, 5)


def test_the_stray_opening_is_the_whole_difference():
    """Remove the unmatched strike by hand and the old formula agrees."""
    orig = [PYG_ORIG[0], _v(18, 34, 42, 50, 58), PYG_ORIG[2]]
    assert fidelity.unmatched_openings(orig, PYG_OURS) == set()
    assert fidelity.startup_lag(orig, PYG_OURS) == (5, 5)


def test_the_originals_attack_list_is_not_modified():
    orig = [_v(*v.attack_frames) for v in PYG_ORIG]
    fidelity.startup_lag(orig, PYG_OURS)
    assert [v.attack_frames for v in orig] == [v.attack_frames for v in PYG_ORIG]


# --- what it must not fire on -------------------------------------------------

def test_a_voice_aligned_at_its_own_lag_is_not_unmatched():
    """Nineteen: voice 1 orig [2,8,20,26,44], ours [8,14,26,32,50] is a clean
    +6 on every note; voices 0 and 2 start at ~583 and read +1. Landing near
    the second attack once is chance, so a RUN is demanded (it read 6 -> 0
    when one attack was enough)."""
    orig = [_v(583, 589, 595, 601, 607), _v(2, 8, 20, 26, 44), _v(584, 590, 596, 602, 608)]
    ours = [_v(584, 590, 596, 602, 608), _v(8, 14, 26, 32, 50), _v(585, 591, 597, 603, 609)]
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (6, 6)


def test_a_voice_that_fits_both_readings_is_left_as_it_stands():
    """Sanxion: voice 1 strikes every 6 frames, so ours [8,14,20,26] fits the
    original shifted +5 AND the original minus its first strike shifted +0.
    Both readings fit, which is no evidence for the second."""
    orig = [_v(784, 832, 863, 881, 899), _v(3, 9, 15, 21, 27, 33), _v(584, 590, 596, 602, 608)]
    ours = [_v(784, 832, 862, 880, 898), _v(8, 14, 20, 26, 32, 38), _v(586, 592, 598, 604, 610)]
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (5, 5)


def test_voices_that_disagree_have_no_consensus_to_skip_to():
    """Chimera-shaped: the other voices' offsets (6 and 20) differ by more
    than the tolerance, so there is no latency to test voice 1's notes
    against, even though they would fit the skipped reading at the smaller."""
    orig = [_v(2, 884, 902, 911, 920), _v(3, 18, 34, 42, 50, 58), _v(434, 443, 461, 470, 488)]
    ours = [_v(8, 890, 908, 917, 926), _v(23, 39, 47, 55, 63, 87), _v(454, 463, 481, 490, 508)]
    # voice 0 offset 6, voice 2 offset 20: no consensus for voice 1.
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (6, 6)    # voice 0's, as before


def test_a_late_voice_is_still_reported_as_a_lag():
    """Our voice 1 starting late, with no attack landing on a second original
    attack, is a defect the lag must keep reporting (clamped, raw kept)."""
    orig = [_v(2, 30, 60, 90, 120), _v(3, 20, 40, 60, 80), _v(2, 30, 60, 90, 120)]
    ours = [_v(8, 36, 66, 96, 126), _v(448, 470, 490, 510, 530), _v(8, 36, 66, 96, 126)]
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (6, 6)    # min over voices, as before
    ours = [_v(448, 470), _v(448, 470, 490, 510, 530), _v(448, 470)]
    assert fidelity.startup_lag(orig, ours) == (25, 446)  # clamped, raw reported


def test_too_few_attacks_for_a_run_is_not_evidence():
    orig = [_v(1026, 1122), _v(3, 18, 34), _v(514, 530)]
    ours = [_v(1031, 1127), _v(23, 39), _v(519, 535)]
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (20, 20)    # 23 - 3, unmoved


def test_a_voice_already_at_the_consensus_offset_is_not_moved():
    """Two original strikes two frames apart, then the run: the first strike's
    offset (7) is within tolerance of the consensus (5), so it is not an
    UNMATCHED opening -- it is merely a different latency to within a frame or
    two, and the first-attack estimate already reads it."""
    orig = [_v(100, 130, 160, 190, 220), _v(3, 5, 20, 36, 44, 52), _v(101, 131, 161, 191, 221)]
    ours = [_v(105, 135, 165, 195, 225), _v(10, 25, 41, 49, 57), _v(106, 136, 166, 196, 226)]
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (7, 7)    # 10 - 3, as before


# --- the real files ---------------------------------------------------------

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

SECONDS = 30


def _traces(name, tmp_path):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    m = doc["songs"].get(name, {}).get("multiplier", 1)
    sub, our_sub, _ = fidelity.resolve_pair(CORPUS / name, "auto")
    sng, _ = fidelity.legalise_restarts(
        convert(str(CORPUS / name), log=lambda x: None, **opts))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None and packed.exists()
    return (fidelity.run_siddump(CORPUS / name, SECONDS, sub),
            fidelity.run_siddump(packed, SECONDS, our_sub, calls=m))


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_pygmies_revenge_reads_a_lag_within_two_frames_of_five(tmp_path):
    orig, ours = _traces("Pygmies_Revenge.sid", tmp_path)
    assert min(orig[1].attack_frames) < 10                  # the stray opening
    assert fidelity.unmatched_openings(orig, ours) == {1}
    lag, raw = fidelity.startup_lag(orig, ours)
    assert lag == raw and abs(lag - 5) <= 2, (lag, raw)


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name,lag", [("Nineteen.sid", 6), ("Sanxion.sid", 5)])
def test_aligned_voices_keep_their_lag(name, lag, tmp_path):
    """The two files a single-attack version of the test moved (to 0 and -1)."""
    orig, ours = _traces(name, tmp_path)
    assert fidelity.unmatched_openings(orig, ours) == set()
    assert fidelity.startup_lag(orig, ours) == (lag, lag)
