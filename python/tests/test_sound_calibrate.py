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


# --------------------------------------------------------------------------
# `render_doc` -- the function that writes the VERDICT.
#
# Everything above pins a reduction. This pins the DOCUMENT, and it is the
# more consequential half: `docs/SOUND-CALIBRATION.md` is a committed artefact
# whose first line says PASS or FAIL, and the FAIL sentence is what stops
# anything downstream inheriting an approval on numbers that did not pass. It
# had no test -- a corpus census of every artefact builder found it and
# `survey.build_subtune_census` as the only two committed artefacts with an
# untested builder.
#
# Pinned on a FIXTURE rather than on a real calibration run, deliberately:
# `render_doc` is pure (`dict -> str`), so a fixture reaches every verdict
# branch including the ones a passing corpus never produces. A test that
# rendered a real run would exercise the PASS branch only and would go quiet
# on the day it mattered.
# --------------------------------------------------------------------------


def _out(**kw):
    """A minimal calibration result. Every branch below varies one key."""
    out = {
        "version": "0.5.460", "head": "826dec8", "seconds": 60,
        "pass": True, "noise_floor": 0.0051, "closeness_floor": 0.9,
        "checks": {
            "identity": {"Commando": {"aud": 1.0, "loud": 1.0,
                                      "loud_ratio": 1.0}},
            "shift": {"movements": [0.001, 0.002]},
            "inaudible": [{"file": "ACE_II", "versions": ["a", "b"],
                           "aud": 0.97, "loud": 0.96}],
            "known_bad": [],
            "approved_rank": {"Commando": {"rank": 2, "of": 89,
                                           "upper_half": True}},
        },
    }
    out.update(kw)
    return out


def _bad(**kw):
    row = {"file": "Last_V8", "versions": ["bad", "good"],
           "bad": 0.80, "good": 0.90, "worse_by": 0.10,
           "worse_by_loud": 0.10, "seen": True}
    row.update(kw)
    return row


def test_a_failing_calibration_says_FAIL_and_forbids_inheritance():
    """The sentence this whole document exists to be able to print."""
    doc = C.render_doc(_out(**{"pass": False}))
    assert "**FAIL**" in doc
    assert "nothing downstream may inherit an approval on these numbers" in doc
    assert "**PASS**" not in doc


def test_a_passing_calibration_says_PASS_and_nothing_about_inheritance():
    doc = C.render_doc(_out(**{"pass": True}))
    assert "**PASS**" in doc
    assert "**FAIL**" not in doc
    assert "may inherit an approval" not in doc


def test_both_floors_are_printed_with_their_values():
    """The doc's own claim is that these two are measured and typed nowhere."""
    doc = C.render_doc(_out(noise_floor=0.0051, closeness_floor=0.9))
    assert "0.0051" in doc and "0.9" in doc
    assert "noise floor" in doc and "closeness floor" in doc


def test_a_blind_spot_is_ANNOUNCED_rather_than_left_looking_like_a_pass():
    """`seen: False` means the metric could not see a known regression.

    The row must say so in words. A blind spot rendered as a blank or a dash
    is the failure this column exists to prevent -- the doc is read by someone
    deciding whether to trust `aud`, and an unseen regression that looks like
    an empty cell reads as "nothing to report".
    """
    doc = C.render_doc(_out(checks=dict(_out()["checks"],
                                        known_bad=[_bad(seen=False)])))
    assert "NO -- a blind spot; name it in the Dimension" in doc


def test_a_regression_only_loud_sees_is_named_as_such():
    """`worse_by <= 0` with `seen` true means `aud` missed it and `loud` did not."""
    doc = C.render_doc(_out(checks=dict(
        _out()["checks"],
        known_bad=[_bad(worse_by=-0.02, worse_by_loud=0.08)])))
    assert "`aud` does not see it" in doc
    assert "+0.0800" in doc


def test_an_incomparable_pair_is_EXCLUDED_rather_than_scored():
    """A pair whose loudness ratio leaves the band is not a miss.

    Scoring it would charge the metric for a comparison it was right to
    refuse, which is how two of the three known_bad pairs came to look like
    failures before `comparable` existed.
    """
    doc = C.render_doc(_out(checks=dict(
        _out()["checks"],
        known_bad=[_bad(incomparable="loud ratio 4.10 outside (0.5, 2.0)")])))
    assert "EXCLUDED -- loud ratio 4.10 outside (0.5, 2.0)" in doc


def test_an_errored_pair_reports_its_error_instead_of_a_number():
    doc = C.render_doc(_out(checks=dict(
        _out()["checks"],
        known_bad=[{"file": "Wiz", "error": "will not convert"}])))
    assert "will not convert" in doc


def test_an_approved_tune_below_the_median_gets_the_caveat_not_a_bare_no():
    """`upper_half` false must not read as a verdict on the tune.

    The doc picks neither side; it says to check the file with `--sound` and
    the approval note. A bare "no" would read as the calibration failing that
    tune.
    """
    doc = C.render_doc(_out(checks=dict(
        _out()["checks"],
        approved_rank={"Thrust": {"rank": 80, "of": 89, "upper_half": False}})))
    assert "this doc picks neither" in doc


def test_the_document_has_all_five_sections_and_ends_with_a_newline():
    doc = C.render_doc(_out())
    for heading in ("## 1. Identity", "## 2. Inaudible shift",
                    "## 3. A change a listener called inaudible",
                    "## 4. Known-bad builds",
                    "## 5. Where the approved tunes sit"):
        assert heading in doc, heading
    assert doc.startswith("# Sound calibration")
    assert doc.endswith("\n")
