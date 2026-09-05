"""The calibration's reductions. The checks that render are exercised by hand
(Step 6); what is pinned here is that each number in
build/sound_calibration.json is the reduction the doc says it is."""
import numpy as np
import pytest

import sound
import sound_calibrate as C

RATE = 44100


def _sine(seconds=2.0, hz=440.0, amp=0.5):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_shift_movement_is_small_for_an_inaudible_shift():
    """48 rasterlines is 3 ms and one frame is 20 ms; the alignment absorbs
    both, so the score moves by less than a point."""
    m = C.shift_movement(_sine(), RATE, [0.003, 0.02])
    assert 0.0 <= m < 0.01


def test_noise_floor_is_the_largest_movement_seen():
    assert C.noise_floor([0.001, 0.004, 0.002]) == 0.004


def test_closeness_floor_is_the_least_agreement_a_human_called_the_same():
    pairs = [{"aud": 0.95, "loud": 0.90}, {"aud": 0.97, "loud": 0.99}]
    assert C.closeness_floor(pairs) == 0.90


def test_worse_by_is_signed_good_minus_bad():
    assert C.worse_by({"aud": 0.4}, {"aud": 0.9}) == pytest.approx(0.5)


def test_rank_in_corpus_places_a_name_among_the_rows():
    rows = [{"file": "A.sid", "aud": 0.9}, {"file": "B.sid", "aud": 0.5},
            {"file": "C.sid", "aud": 0.7}, {"file": "D.sid", "aud": None}]
    assert C.rank_in_corpus(rows, ["C"]) == {"C": (2, 3)}   # 2nd of 3 measured


def test_resolve_version_sha_matches_the_commit_subject_convention():
    """Every commit here is `vX.Y.Z: ...`; the resolver greps that prefix."""
    assert C.resolve_version_sha("0.5.446") == "be759f0"
    assert C.resolve_version_sha("9.9.999") == ""


# The three pairs as MEASURED at v0.5.459, so these are the real numbers the
# re-specification was derived from rather than invented ones.
_LV_BAD = {"aud": 0.8605, "loud": 0.9514, "loud_ratio": 0.9703}
_LV_GOOD = {"aud": 0.8727, "loud": 0.4106, "loud_ratio": 0.0743}
_HR_BAD = {"aud": 0.8929, "loud": 0.9362, "loud_ratio": 1.0373}
_HR_GOOD = {"aud": 0.8876, "loud": 0.9498, "loud_ratio": 1.0526}
_FLOOR = 0.006932023462962178


def test_loud_sees_a_regression_aud_is_blind_to():
    """Human_Race 0.5.329 -> 0.5.330, both builds healthy.

    `aud` reads -0.0053 -- the version known to be WORSE scoring BETTER -- and
    `loud` reads +0.0136, twice the noise floor and the right sign. The check
    used to read `aud` alone and called this a blind spot in the metric; one of
    its two columns was never blind.
    """
    assert C.worse_by(_HR_BAD, _HR_GOOD) < 0            # aud gets it wrong
    assert C.worse_by_loud(_HR_BAD, _HR_GOOD) > _FLOOR  # loud gets it right
    assert C.comparable(_HR_BAD, _HR_GOOD) is None      # and the pair is sound


def test_a_build_far_off_the_originals_loudness_is_excluded_not_scored():
    """Las_Vegas's *good* build renders at 0.074x the original's loudness.

    Quartered, its 60 s render is [0.201, 0.101, 0.0023, 0.0023] against the
    original's steady [0.150, 0.163, 0.169, 0.169]: the music ends around 30 s
    while the original plays on, so half the window scores our silence against
    real music. Both columns call that worse, correctly. Excluding it is the
    difference between "the metric is blind" and "this pair cannot be built
    comparably", which are different problems with different fixes.
    """
    why = C.comparable(_LV_BAD, _LV_GOOD)
    assert why is not None and "0.074" in why, why
    # ...and it is the GOOD side named, not the bad one.
    assert why.startswith("good"), why


def test_an_excluded_pair_does_not_count_as_a_pass():
    """The gate says nothing downstream may inherit an approval on these
    numbers. A pair that could not be compared has validated nothing, so it
    must not be what makes the file read PASS."""
    assert C.comparable(_LV_BAD, _LV_GOOD) is not None
    # the `passed` expression in main() is `all(b["seen"] for b in bad)`; an
    # excluded row carries seen=False, so it holds the file at FAIL.
    row_seen = (C.comparable(_LV_BAD, _LV_GOOD) is None
                and (C.worse_by(_LV_BAD, _LV_GOOD) > _FLOOR
                     or C.worse_by_loud(_LV_BAD, _LV_GOOD) > _FLOOR))
    assert row_seen is False
