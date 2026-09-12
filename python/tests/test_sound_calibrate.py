"""The calibration's pure reductions, and `render_doc`, the document builder.

Nothing here calls `sound.render_cached` or `main` -- the five checks' own
audio rendering is exercised only by running `sound_calibrate.py` for real,
still by hand. `convert_at` WAS in that list and no longer is: the last test
in this file calls it for real with only its two OS boundaries faked, and the
sentence that excluded it survived the test that contradicted it for as long
as it took to read the file. What this file pins is: each
reduction function (`shift_movement`, `shift_movements`, `noise_floor`,
`closeness_floor`, `worse_by`, `worse_by_loud`, `comparable`,
`known_bad_passed`, `rank_in_corpus`, `resolve_version_sha`) against fixed
numbers, `score_pair` and `CHECK_WINDOW_S` -- the prefix checks 2-4 are
scored over -- against a synthetic pair whose defect has a known share of
each window, AND
`render_doc` -- the function that turns a calibration result into
`docs/SOUND-CALIBRATION.md` -- against every verdict branch, on a
hand-built fixture rather than a real run."""
import ast
import pathlib

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


# --------------------------------------------------------------------------
# CHECK_WINDOW_S: checks 2-4 score a fixed prefix of the aligned render.
#
# `aud` and `loud` are means over frames, so a defect of fixed length reads
# smaller the longer the render it is averaged into -- W_A_R's ~40 s event
# read +0.168 at 60 s and +0.066 at 180 s (50a6178, historical). The pair
# below is that shape made synthetic: 180 s of one tone, the "bad" build a
# different tone in 20-60 s and the "good" build identical to the original.
# The whole-window margin is then EXACTLY the prefix margin diluted by
# 180/60, which is what the 3x assertion pins.
# --------------------------------------------------------------------------
_LOW_RATE = 16000          # 180 s at 44.1 kHz is a 1 GB feature pass; 16 kHz keeps
                           # F_MAX (8 kHz) inside Nyquist and the test under a few s


def _tone(seconds, hz, rate=_LOW_RATE, amp=0.5):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _write(path, samples, rate=_LOW_RATE):
    import wave
    pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _fixed_defect_pair(tmp_path, total_s=180.0, t0=20.0, t1=60.0):
    """(orig, bad, good) WAV paths: bad differs from orig only in [t0, t1)."""
    orig = _tone(total_s, 440.0)
    bad = orig.copy()
    i0, i1 = int(t0 * _LOW_RATE), int(t1 * _LOW_RATE)
    bad[i0:i1] = _tone(total_s, 880.0)[i0:i1]
    paths = {}
    for name, x in (("orig", orig), ("bad", bad), ("good", orig)):
        paths[name] = tmp_path / f"{name}.wav"
        _write(paths[name], x)
    return paths


def _renders_from(paths, monkeypatch):
    """`score_pair` renders through `sound.render_cached`; hand it the WAVs
    by the .sid's stem instead, and count what it asked for."""
    calls = []

    def fake(sid, seconds, sub, tag, *a, **k):
        calls.append((sid.stem, seconds, tag))
        return paths[sid.stem]
    monkeypatch.setattr(C.sound, "render_cached", fake)
    return calls


def test_check_window_is_sixty_seconds():
    assert C.CHECK_WINDOW_S == 60


def test_a_fixed_defect_reads_three_times_larger_on_the_prefix_than_on_the_whole(
        tmp_path, monkeypatch):
    """SABOTAGE TARGET: drop the `window_s` slice from `sound.compare_features`
    (or stop `score_pair` passing CHECK_WINDOW_S) and the prefix margin equals
    the whole margin, so the 3x ratio below reads 1x and this fails.

    The defect occupies 40 s. Averaged over the 60 s prefix it is 2/3 of the
    frames; over 180 s, 2/9. The ratio of the two `worse_by` margins is
    therefore 180/60 = 3, to within the frame rounding at the window edges.
    """
    paths = _fixed_defect_pair(tmp_path)
    calls = _renders_from(paths, monkeypatch)
    bad_prefix, bad_whole = C.score_pair(tmp_path / "orig.sid", tmp_path / "bad.sid", 180, 0)
    good_prefix, good_whole = C.score_pair(tmp_path / "orig.sid", tmp_path / "good.sid", 180, 0)
    m_prefix = C.worse_by(bad_prefix, good_prefix)
    m_whole = C.worse_by(bad_whole, good_whole)
    assert good_prefix["aud"] == pytest.approx(1.0, abs=1e-9)
    assert m_whole > 0.05, f"the whole-window margin must see the defect at all: {m_whole}"
    assert m_prefix / m_whole == pytest.approx(3.0, rel=0.03), (
        f"prefix {m_prefix:.4f} / whole {m_whole:.4f} = {m_prefix / m_whole:.3f}x; "
        f"a 40 s defect in a {C.CHECK_WINDOW_S} s prefix of a 180 s render is 3x "
        f"its whole-window share -- if this reads 1x, the prefix is not being cut")
    # the prefix is scored, not re-rendered: one render per side per pair
    assert [c[1] for c in calls] == [180] * 4
    # and the frames the prefix scored are CHECK_WINDOW_S worth, not the whole
    assert bad_prefix["sound_frames"] == int(C.CHECK_WINDOW_S / (sound.HOP / _LOW_RATE))
    assert bad_whole["sound_frames"] > 2.9 * bad_prefix["sound_frames"]


def test_score_pair_names_a_failed_render_on_both_windows(monkeypatch):
    monkeypatch.setattr(C.sound, "render_cached",
                        lambda sid, *a, **k: None if sid.stem == "U" else sid)
    got = C.score_pair(pathlib.Path("O.sid"), pathlib.Path("U.sid"), 1, 0)
    assert got == ({"sound_failed": "ours"}, {"sound_failed": "ours"})


def test_shift_movement_over_a_window_is_the_windowed_movement():
    """`shift_movements` scores several windows from one feature pass and
    `shift_movement(window_s=w)` is its single-window face; the floor for
    checks 3 and 4 is the one measured over CHECK_WINDOW_S, so the two must
    agree on it."""
    s = _sine(4.0)
    both = C.shift_movements(s, RATE, [0.003, 0.02], [1.0, None])
    assert both[0] == C.shift_movement(s, RATE, [0.003, 0.02], window_s=1.0)
    assert both[1] == C.shift_movement(s, RATE, [0.003, 0.02])
    assert all(0.0 <= m < 0.01 for m in both)


def test_main_scores_checks_2_to_4_through_the_windowed_paths_only():
    """A guard on the wiring `main` is hand-run through: it must reach the
    scoring only via `shift_movements` (handed CHECK_WINDOW_S) and
    `score_pair`, never `sound.compare_sids`/`compare_wavs`/`compare_features`
    directly, since those default to the whole window. Check 1 is the one
    exception and calls `compare_features` on identical features, where a
    window changes nothing."""
    text = pathlib.Path(C.__file__).read_text(encoding="utf-8")
    main = next(n for n in ast.walk(ast.parse(text))
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]

    def name(c):
        return c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None)
    names = [name(c) for c in calls]
    assert "compare_sids" not in names and "compare_wavs" not in names
    assert names.count("score_pair") >= 2, "checks 3 and 4 both go through score_pair"
    shift = [c for c in calls if name(c) == "shift_movements"]
    assert shift, "check 2 goes through shift_movements"
    assert any(isinstance(n, ast.Name) and n.id == "CHECK_WINDOW_S"
               for c in shift for n in ast.walk(c)), (
        "check 2's floor must be measured over CHECK_WINDOW_S")
    pair_src = ast.get_source_segment(text, next(
        n for n in ast.walk(ast.parse(text))
        if isinstance(n, ast.FunctionDef) and n.name == "score_pair"))
    assert "CHECK_WINDOW_S" in pair_src


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


# --------------------------------------------------------------------------
# `convert_at`'s OWN return statement -- exercised for real.
#
# Every existing caller of `convert_at` (approvals.assess, approvals.
# recover_approved_sng, and this module's own checks 3/4) is tested only
# through a hand-written stand-in for the whole function -- see
# `test_approvals.py`'s `_fake_convert_at` and the tests that inject a bare
# lambda. That pins each CALLER's handling of a `Converted`/`None` result;
# none of it ever calls the real `convert_at`, so `return None if packed is
# None else Converted(sng=out, sid=packed)` reverting to the old bare
# `return packed` moves nothing in the suite -- MEASURED at c2cb76a, 0 failed.
#
# `approvals.pack_into` was made testable by finding the point where the REAL
# function fails without its external dependency: `pack_sid` writes its
# `.sng` in-process, before it shells out to gt2reloc, so a missing directory
# raises with no binary involved. `convert_at` has no equivalent single
# early-failure point -- its own "write the .sng" step IS a subprocess call
# (a historical `python -m h2g`), not an in-process write, so there is no
# moment before that call where a directory or file-system defect alone can
# stand in for the whole external dependency the way `pack_sid`'s pre-write
# does.
#
# What convert_at DOES have is exactly two OS boundaries: `subprocess.run`
# (used for `git archive` and for the historical `python -m h2g` invocation)
# and `fidelity.pack_sid` (which shells out to gt2reloc). Faking only those
# two -- never `convert_at` itself -- lets every other line of the real
# function run for real: `Path.mkdir`, a real (empty) tar's `extractall`,
# `fidelity.legalise_restarts` on a real `.sng` (Commando.sng, already used
# as a real-format fixture in test_approvals.py), the `tree_presets` OSError
# fallback, and -- the line this exists to guard -- the final `Converted`
# construction. No git history, no historical interpreter, and no gt2reloc
# binary are needed.
# --------------------------------------------------------------------------
def test_convert_at_returns_a_converted_pair_not_the_bare_packed_path(tmp_path, monkeypatch):
    """SABOTAGE TARGET: reverting `convert_at`'s
    `return None if packed is None else Converted(sng=out, sid=packed)` to the
    old `return packed` must fail this test -- `got.sng` would then raise
    AttributeError on a bare `Path`.
    """
    import io
    import tarfile
    import types
    from pathlib import Path

    sha = "deadbee1"
    monkeypatch.setattr(C, "resolve_version_sha", lambda version: sha)

    # The bytes the historical `python -m h2g` call would have written --
    # a REAL .sng, because legalise_restarts (called on it for real below)
    # parses the format at a fixed offset.
    sng_bytes = (C.ROOT / "Commando.sng").read_bytes()

    # A real, empty tar -- what `git archive` on any tree ultimately is,
    # bytes-for-bytes something tarfile.extractall can really consume.
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w"):
        pass
    archive_bytes = tar_buf.getvalue()

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            return types.SimpleNamespace(stdout=archive_bytes)
        # the historical `python -m h2g ... -o <out> ...` invocation
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_bytes(sng_bytes)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(C.subprocess, "run", fake_run)

    packed_path = tmp_path / "packed.sid"

    def fake_pack_sid(*a, **k):
        packed_path.write_bytes(b"stand-in packed .sid, gt2reloc never ran")
        return packed_path

    monkeypatch.setattr(C.F, "pack_sid", fake_pack_sid)

    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"never read by any of the fakes above")

    got = C.convert_at("9.9.998", sid, tmp_path, "gt2reloc-not-invoked", 1)

    assert isinstance(got, C.Converted), (
        f"convert_at must return a Converted pair, got {got!r}")
    assert got.sng == tmp_path / f"Tune.{sha}.sng"
    assert got.sng.read_bytes() == sng_bytes
    assert got.sid == packed_path


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
    """An excluded pair is not what makes the file read PASS -- it is not
    counted at all.

    THE SECOND HALF OF THIS COMMENT USED TO SAY "so it holds the file at FAIL",
    which was true of the old criterion and is FALSE of the current one. The
    user decided (see `.claude/tasks/decisions.jsonl`) that an incomparable
    pair is REPORTED, not counted, so it neither passes nor fails the suite --
    `known_bad_passed` filters it out entirely. The assertion below is
    unchanged and still right: an excluded row is not `seen`.
    """
    assert C.comparable(_LV_BAD, _LV_GOOD) is not None
    row_seen = (C.comparable(_LV_BAD, _LV_GOOD) is None
                and (C.worse_by(_LV_BAD, _LV_GOOD) > _FLOOR
                     or C.worse_by_loud(_LV_BAD, _LV_GOOD) > _FLOOR))
    assert row_seen is False
    # ...and being unseen no longer sinks a suite that has a comparable pair.
    assert C.known_bad_passed([{"incomparable": "not a comparable render",
                                "seen": False},
                               {"incomparable": None, "seen": True}]) is True


def test_a_suite_of_only_excluded_pairs_FAILS_rather_than_passing_vacuously():
    """The guard the whole change turns on.

    `all()` over an empty sequence is True, so filtering excluded pairs OUT
    without also requiring one to remain would report PASS the moment every
    pair is excluded -- validating nothing, and reading identically to a real
    pass. That is the same shape as a census reporting "0 disagreements" over
    rows it never examined, which this repo has shipped more than once.

    Both endpoints are pinned, because only the pair distinguishes the guard
    from its absence.
    """
    assert C.known_bad_passed([]) is False
    assert C.known_bad_passed([{"incomparable": "multiplier change",
                                "seen": False}]) is False
    assert C.known_bad_passed([{"incomparable": "a", "seen": False},
                               {"incomparable": "b", "seen": False}]) is False
    # one comparable, seen -> the suite has validated something
    assert C.known_bad_passed([{"incomparable": None, "seen": True}]) is True


def test_a_comparable_pair_that_is_not_seen_still_FAILS():
    """Excluding the incomparable must not weaken the real criterion: a pair
    that CAN be compared and whose regression the metric MISSED is exactly the
    blind spot this file exists to catch, and it still holds the suite at
    FAIL."""
    assert C.known_bad_passed([{"incomparable": None, "seen": False}]) is False
    assert C.known_bad_passed([{"incomparable": None, "seen": True},
                               {"incomparable": None, "seen": False}]) is False


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
        "check_window_s": 60,
        "whole": {"noise_floor": 0.0052, "closeness_floor": 0.89},
        "checks": {
            "identity": {"Commando": {"aud": 1.0, "loud": 1.0,
                                      "loud_ratio": 1.0}},
            "shift": {"movements": [0.001, 0.002],
                      "whole": {"movements": [0.0015, 0.0025]}},
            "inaudible": [{"file": "ACE_II", "versions": ["a", "b"],
                           "aud": 0.97, "loud": 0.96,
                           "whole": {"aud": 0.96, "loud": 0.95}}],
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


def test_the_header_names_why_the_window_was_chosen_not_just_which():
    """The doc must say the window matches what approvals.py compares at,
    not merely state the number -- that's the whole point of this task."""
    doc = C.render_doc(_out(seconds=180))
    assert "approvals.py" in doc
    assert "180 s" in doc
    assert "different quantity" in doc


def test_the_header_says_checks_2_to_4_are_scored_over_the_prefix_and_shows_both_floors():
    """A reader of the doc applies the floors somewhere -- approvals.py over
    the whole window -- so the doc must say which window each floor is about
    and print the whole-window pair beside the prefix pair, never one that
    reads as the other."""
    doc = C.render_doc(_out(seconds=180, check_window_s=60,
                            whole={"noise_floor": 0.0033, "closeness_floor": 0.955}))
    assert "first 60 s of the aligned 180 s render" in doc
    assert "CHECK_WINDOW_S" in doc
    assert "0.0033" in doc and "0.9550" in doc
    assert "`approvals.py` applies the floors over the whole window" in doc
    # and the per-row whole figures are in the tables
    doc = C.render_doc(_out(checks=dict(
        _out()["checks"], known_bad=[_bad(whole={"worse_by": 0.033})])))
    assert "| +0.100 | +0.033 |" in doc
    assert "| 0.9700 | 0.9600 | 0.9600 | 0.9500 |" in doc


def test_a_result_without_a_check_window_still_renders():
    """Older JSON (pre-CHECK_WINDOW_S) has neither key; the doc must not
    invent a window for it."""
    out = _out()
    del out["check_window_s"], out["whole"]
    out["checks"]["shift"].pop("whole")
    out["checks"]["inaudible"][0].pop("whole")
    doc = C.render_doc(out)
    assert "CHECK_WINDOW_S" not in doc
    assert "| 0.9700 | 0.9600 | - | - |" in doc


def test_the_document_has_all_five_sections_and_ends_with_a_newline():
    doc = C.render_doc(_out())
    for heading in ("## 1. Identity", "## 2. Inaudible shift",
                    "## 3. A change a listener called inaudible",
                    "## 4. Known-bad builds",
                    "## 5. Where the approved tunes sit"):
        assert heading in doc, heading
    assert doc.startswith("# Sound calibration")
    assert doc.endswith("\n")


# --------------------------------------------------------------------------
# The header docstring is a claim about this file's own contents, and twice
# in one week it was false while the suite stayed green: 9ec29bf (a docstring
# that asserted its own absence) and the `convert_at` sentence above, which
# said "Nothing here calls ... convert_at" for as long as the test that called
# it took to read. Prose about a file is not checked by running the file, so
# this test reads the docstring's exclusion list and greps the file's CODE for
# a call to each excluded name. It keys on the two spellings the repo has
# used -- "Nothing here calls `a`, `b` or `c`" and "`x` is not exercised" --
# and nothing else, so it cannot be satisfied by rewording the claim into a
# shape it does not read.

def _docstring_exclusions(text):
    import re
    doc = ast.get_docstring(ast.parse(text)) or ""
    names = set()
    for m in re.finditer(r"Nothing here calls ((?:`[^`]+`(?:,\s*|\s+or\s+)?)+)", doc):
        names.update(re.findall(r"`([^`]+)`", m.group(1)))
    for m in re.finditer(r"`([^`]+)` is not exercised", doc):
        names.add(m.group(1))
    return {n.rsplit(".", 1)[-1] for n in names}


def _called_names(text):
    tree = ast.parse(text)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def test_the_header_docstrings_exclusion_list_is_true_of_the_code_below_it():
    """SABOTAGE TARGETS: (1) add `C.main()` anywhere in this file -- the guard
    names `main`; (2) put `convert_at` back into the docstring's "Nothing here
    calls" list -- the guard names it, because the test above calls it."""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    excluded = _docstring_exclusions(text)
    assert excluded, ("the header docstring no longer carries a 'Nothing here calls' "
                      "list; either it moved or this guard's regex no longer reads it")
    called = _called_names(text)
    lies = sorted(excluded & called)
    assert not lies, (
        f"the header docstring says nothing here calls {lies}, but the code below "
        f"it does -- fix the sentence, not the test")
