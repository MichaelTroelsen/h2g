"""Every option convert() takes must be reachable from a preset.

This defect has shipped twice. `--slides` was emitted but never forwarded
(AUDIT.md's first verified defect), and `--filter` arrived in v0.5.72 wired
into convert() and README but into neither `presets.py`'s `always` block nor
`fidelity._preset_opts` -- so every measurement ran with the filter off and the
next artefact regeneration would have recorded the feature as doing nothing.

Both were the same cause: the option list is maintained by hand in more than
one place. `_preset_opts` now derives it from `inspect.signature(convert)`;
these tests fail if a new option escapes either the derivation or the block.
"""
import inspect
import json
from pathlib import Path

import pytest

from fidelity import (_NOT_CONVERT_OPTS, _PER_SONG_OPTS, _RENAMED_OPTS,
                      _convert_options, _preset_opts)
from h2g import __version__
from h2g.convert import convert
import presets
from presets import EXCLUDED_FROM_ALWAYS

PRESETS = Path(__file__).resolve().parents[2] / "presets.json"


def _always():
    """The shipped block, skipped only when it genuinely predates an OPTION.

    presets.json is regenerated after a conversion-changing commit, not during
    one, so between the two it legitimately predates the options it should
    carry. Asserting against a stale artefact would fail for the one reason
    this test is not about -- so there is a skip, and the skip is right.

    WHAT WAS WRONG WITH IT, measured rather than supposed. The skip used to
    fire on `__version__ not in generator`, i.e. on ANY version difference.
    CLAUDE.md requires a version bump on *every* commit, and
    `bump_version.py` rewrites `__init__.py` and `CHANGELOG.md` only -- it
    never touches presets.json. So the stamp fell behind on the very next
    commit whatever that commit did, and the guard went dark until someone
    regenerated the artefact for an unrelated reason. That is not a
    hypothetical: it is the likeliest reading of CLAUDE.md's note that this
    guard once stayed off for ten versions, and at v0.5.337 it was watched
    happening again within one commit -- `bump_version.py` runs AFTER
    `presets.py`, so the commit that regenerates presets.json disarms the
    guard it just re-armed.

    The version was only ever a PROXY for "could the option set have changed
    since this file was written". Ask that question directly instead: if every
    option `convert()` takes today is already accounted for in the artefact --
    present in `always`, or deliberately excluded, or per-song, or not a
    convert option at all -- then the artefact is not stale in any way that
    can make this test lie, and it runs no matter what version stamped it.

    A skip survives for exactly the legitimate case: an option is unaccounted
    for AND the artefact predates this version, which is the add-then-
    regenerate window. If an option is unaccounted for and the versions MATCH,
    that is the defect this test exists to catch and it fails, as it should.
    """
    if not PRESETS.exists():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    always = doc.get("always", {})
    unaccounted = [
        _RENAMED_OPTS.get(o, o) for o in _convert_options()
        if o not in _PER_SONG_OPTS and o not in _NOT_CONVERT_OPTS
        and o not in EXCLUDED_FROM_ALWAYS
        and _RENAMED_OPTS.get(o, o) not in always
    ]
    if unaccounted and __version__ not in str(doc.get("generator", "")):
        pytest.skip(
            f"presets.json predates h2g {__version__} AND is missing "
            f"{unaccounted!r} -- regenerate it. (A version difference alone no "
            f"longer skips: see this function's docstring.)")
    return always


def test_convert_options_are_exactly_its_keywords_minus_the_inputs():
    params = set(inspect.signature(convert).parameters)
    assert params - {"sid_path", "log"} == set(_convert_options())


def test_every_convert_option_is_produced_by_preset_opts():
    """The guard the two shipped defects needed."""
    doc = {"always": {}, "songs": {}}
    produced = set(_preset_opts(doc, "any.sid"))
    for opt in _convert_options():
        assert opt in produced, (
            f"convert() takes {opt!r} and _preset_opts never passes it, so a "
            f"preset run silently converts without it")


def test_preset_opts_forwards_what_the_always_block_sets():
    doc = {"always": {o: True for o in _convert_options()}, "songs": {}}
    doc["always"]["format"] = "gts5"
    doc["always"]["tempo"] = "auto"
    opts = _preset_opts(doc, "any.sid")
    for opt in _convert_options():
        if opt in _PER_SONG_OPTS or opt in ("fmt", "tempo"):
            continue
        assert opts[opt] is True, f"{opt} was set in `always` and not forwarded"


def test_preset_opts_is_accepted_by_convert_verbatim():
    """Nothing in the dict may be a keyword convert() would reject."""
    doc = {"always": {}, "songs": {}}
    params = set(inspect.signature(convert).parameters)
    assert set(_preset_opts(doc, "any.sid")) <= params


def test_the_shipped_always_block_carries_every_gated_option():
    """A gated option left out of `always` is a feature that measures as dead.

    Only options that are a no-op where their routine is absent belong here;
    the packing ones are excluded by name because convert() does not take them.
    """
    always = _always()
    for opt in _convert_options():
        if (opt in _PER_SONG_OPTS or opt in _NOT_CONVERT_OPTS
                or opt in EXCLUDED_FROM_ALWAYS):
            continue
        key = _RENAMED_OPTS.get(opt, opt)
        assert key in always, (
            f"{key!r} is a convert() option missing from presets.json's "
            f"`always` block -- regenerate presets.json, or add it to "
            f"presets.EXCLUDED_FROM_ALWAYS with the reason")


def test_every_deliberate_exclusion_is_a_real_option():
    """A stale name in the exclusion set would hide a genuinely missing one."""
    assert EXCLUDED_FROM_ALWAYS <= set(_convert_options())


# --- per-song options ------------------------------------------------------
#
# An option can be right for a few files and wrong corpus-wide, which `always`
# cannot express. `presets.py --fidelity` records those per song, and until
# v0.5.177 nothing read them: `_preset_opts` consulted `always` alone, so a
# searched setting would have been written and then ignored -- the exact shape
# in which --slides and --filter each shipped dead.

def test_a_song_entry_beats_the_always_block_in_both_directions():
    doc = {"always": {"no_test_restart": False, "pulse": True},
           "songs": {"a.sid": {"no_test_restart": True, "pulse": False}}}
    got = _preset_opts(doc, "a.sid")
    assert got["no_test_restart"] is True, "a per-song override was ignored"
    assert got["pulse"] is False, "a per-song False must switch one off too"
    other = _preset_opts(doc, "b.sid")
    assert (other["no_test_restart"], other["pulse"]) == (False, True)


def test_the_fidelity_searched_options_are_kept_out_of_always():
    """They are per song by construction: each is a corpus-wide loss and a win
    on a handful of files, so an `always` entry would be wrong either way."""
    assert set(presets.FIDELITY_TOGGLES) <= EXCLUDED_FROM_ALWAYS
    assert not set(presets.FIDELITY_TOGGLES) & set(presets.FIXED)
    assert set(presets.FIDELITY_TOGGLES) <= set(_convert_options())


def test_the_fidelity_search_cannot_be_won_by_deleting_notes():
    """Section 7.eee: the candidate this search exists for reached `wave` 99.5%
    on Commando by losing 79 notes, because a per-frame agreement rewards losing
    the events it scores. Melody alone would not catch it either -- it collapses
    consecutive repeats, so a re-struck note lost is invisible to it."""
    ref = (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800))
    assert presets.fidelity_better((0.90, 0.80, 600, (0, 0, 0x3800, 0x3800)), ref)
    # better melody, but the sequence or the notes went with it
    assert not presets.fidelity_better((0.90, 0.70, 600, (0, 0, 0x3800, 0x3800)), ref)
    assert not presets.fidelity_better((0.90, 0.80, 599, (0, 0, 0x3800, 0x3800)), ref)


def test_a_gain_inside_the_noise_is_not_recorded():
    ref = (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800))
    assert not presets.fidelity_better((0.80 + presets.FIDELITY_MARGIN / 2,
                                        0.90, 900, (0, 0, 0, 0)), ref)
    assert presets.fidelity_better((0.80 + presets.FIDELITY_MARGIN,
                                   0.75, 600, (0, 0, 0, 0)), ref)


def test_restoring_noise_the_original_has_and_we_have_none_of_is_a_win():
    """The second way to win, and the one --two-stage needs. A conversion with
    no noise at all where the original has some is missing its drums outright
    (Trans-Atlantic: 0 frames against 1089), which no agreement percentage can
    say because there is nothing on our side to disagree with. Scoring it on
    `wave` would reject it -- restoring a 1-4 frame transient moves that column
    the wrong way even when the transient is right."""
    ref = (0.80, 0.75, 600, (0, 1089, 0x3800, 0x3800))
    assert presets.fidelity_better((0.80, 0.75, 600, (928, 1089, 0x3800, 0x3800)), ref)
    # ...but not if the notes go with it
    assert not presets.fidelity_better((0.80, 0.75, 599, (928, 1089, 0x3800, 0x3800)), ref)
    # and not where the original has no noise either: that is invention
    assert not presets.fidelity_better((0.80, 0.75, 600, (928, 0, 0x3800, 0x3800)),
                                       (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800)))
    # nor where we already sound some -- the criterion is "none at all"
    assert not presets.fidelity_better((0.80, 0.75, 600, (999, 1089, 0x3800, 0x3800)),
                                       (0.80, 0.75, 600, (900, 1089, 0x3800, 0x3800)))


def test_restored_noise_has_to_be_audible():
    """The SID's noise is an LFSR clocked by the frequency register, so a noise
    frame at a low frequency makes no sound at all. Counting frames rather than
    sound selected four files whose restored drums a listener could not hear:
    the attack in this dialect carries a pitch as well as a waveform, and only
    the waveform is read, so the noise plays at the note's own $05xx."""
    ref = (0.80, 0.75, 600, (0, 1089, 0, 0x3800))
    assert presets.fidelity_better((0.80, 0.75, 600, (928, 1089, 0x3000, 0x3800)), ref)
    assert not presets.fidelity_better((0.80, 0.75, 600, (928, 1089, 0x05CE, 0x3800)), ref)


def test_restored_noise_has_to_land_closer_than_none_at_all():
    """|ours - theirs| < |0 - theirs|, not merely "more than zero". Without the
    upper bound the criterion took Sigma Seven, whose two-stage attack sounds 82
    noise frames where the original sounds 41 -- drums invented at twice the
    rate are not an improvement on drums missing."""
    ref = (0.80, 0.75, 600, (0, 41, 0x3800, 0x3800))
    assert presets.fidelity_better((0.80, 0.75, 600, (40, 41, 0x3800, 0x3800)), ref)
    assert not presets.fidelity_better((0.80, 0.75, 600, (82, 41, 0x3800, 0x3800)), ref)
    assert not presets.fidelity_better((0.80, 0.75, 600, (83, 41, 0x3800, 0x3800)), ref)


def test_a_listening_veto_names_a_real_option_and_a_real_file():
    """The search scores registers; a veto is where someone heard the result
    and it was wrong. A stale key here would silently stop vetoing."""
    for name, keys in presets.FIDELITY_VETOED.items():
        assert name.endswith(".sid"), name
        # `hard_restart_frames` joined the searchable set at
        # v0.5.406 via the frame pass, so a veto or a
        # confirmation may name it: it is a real decision
        # the search can now make, and un-make.
        assert keys <= set(presets.FIDELITY_TOGGLES) | {"hard_restart_frames"}, (name, keys)


def test_the_shipped_presets_honour_every_veto():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    for name, keys in presets.FIDELITY_VETOED.items():
        entry = (doc.get("songs") or {}).get(name, {})
        for key in keys:
            assert not entry.get(key), (
                f"{name} still carries {key}, which a listening test rejected "
                "-- regenerate presets.json")


# --- v0.5.208: the oscillation and noise-pitch criteria ----------------------

def test_a_ratio_is_compared_in_log_space():
    """2.0x and 0.5x are the same size of wrong; `abs(r - 1)` calls one twice
    the other. The margin is a fraction of the remaining gap, so a move has to
    be worth something rather than merely be a move."""
    assert presets._closer(0.61, 0.17, 1.0, 0.02), "0.17x -> 0.61x is closer"
    assert not presets._closer(0.5, 2.0, 1.0, 0.02), "same distance either side"
    assert not presets._closer(0.17, 0.61, 1.0, 0.02), "and it is directional"
    # an unmeasurable dimension cannot recommend a setting
    for a, b in ((None, 0.5), (0.5, None), (0, 0.5), (0.5, 0)):
        assert not presets._closer(a, b, 1.0, 0.02), (a, b)


def test_oscillating_nearer_the_originals_rate_is_a_win():
    """The criterion effect bit $10's arpeggio needed. It strikes no new notes
    and sounds no new register, so `plays_more` and `finds_noise` are both blind
    to it -- the balloon song goes vib 0.17x -> 0.61x with melody unchanged."""
    ref = (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800), 0.17)
    assert presets.fidelity_better(
        (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800), 0.61), ref)
    # ...and it is still guarded by the note tests, which is what rejects the
    # same setting on the seven files where it costs melody
    assert not presets.fidelity_better(
        (0.52, 0.75, 600, (0, 0, 0x3800, 0x3800), 0.93), ref)
    assert not presets.fidelity_better(
        (0.80, 0.75, 599, (0, 0, 0x3800, 0x3800), 0.61), ref)


def test_moving_the_noise_to_the_originals_pitch_is_a_win():
    """The frames can already be there and be the wrong colour: the drum
    composition changes no count and no waveform, only which pitch the burst
    sounds at. `finds_noise` cannot see that -- it needs our side to have had
    *none*."""
    ref = (0.80, 0.75, 600, (928, 1089, 0x0500, 0x3800), 1.0)
    assert presets.fidelity_better(
        (0.80, 0.75, 600, (928, 1089, 0x3000, 0x3800), 1.0), ref)
    # a move away is not a win, and neither is one inside the margin
    assert not presets.fidelity_better(
        (0.80, 0.75, 600, (928, 1089, 0x0200, 0x3800), 1.0), ref)


def test_a_state_without_the_new_terms_still_scores():
    """Four-element states predate this term. An absent dimension reads as
    unmeasurable rather than as a zero, which would recommend everything."""
    ref = (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800))
    assert presets.fidelity_better((0.90, 0.80, 600, (0, 0, 0x3800, 0x3800)), ref)
    assert not presets.fidelity_better(
        (0.80, 0.75, 600, (0, 0, 0x3800, 0x3800)), ref)


def test_the_walk_cannot_give_back_what_a_previous_winner_gained():
    """v0.5.230. The five terms are one-sided questions, so any of them
    accepts; the search then makes the winner the new reference and walks on.
    Without a no-regression clause that path runs downhill.

    IK+ is the case, with the numbers from an instrumented search: it accepted
    `--wave-program` (noise 140 -> 1170 of the original's 1517, onset 0.45 ->
    0.75, melody unchanged) and then, sixteen combinations later, replaced it
    with `--no-test-restart`, which drops the noise back to 168 and leaves
    onset at 0.45 -- winning only because 168 frames sit at a pitch nearer the
    original's than 1170 do. The better setting was measured, accepted, and
    thrown away.
    """
    base = (0.990, 0.772, 535, (140, 1517, 0x3900, 0x3800), 0.0, 0.450)
    wp = (0.990, 0.772, 535, (1170, 1517, 0x3800, 0x3800), 0.269, 0.750)
    ntr = (0.989, 0.772, 535, (168, 1517, 0x3900, 0x3800), 0.0, 0.450)
    assert presets.fidelity_better(wp, base), "the real gain is still a win"
    assert not presets.fidelity_better(ntr, wp), \
        "and cannot be replaced by something worse on noise and onset"
    # ...while a candidate that improves one term and touches nothing else is
    # still accepted, which is what keeps the clause from being a blanket veto.
    better_onset = (0.990, 0.772, 535, (1170, 1517, 0x3800, 0x3800),
                    0.269, 0.900)
    assert presets.fidelity_better(better_onset, wp)


def test_the_clause_does_not_veto_on_a_term_the_change_resizes():
    """Only `onset` and losing the noise outright are vetoes.

    The oscillation ratio and the noise *pitch* are estimated over the frames
    the setting itself creates -- IK+ sounds 140 noise frames without
    `--wave-program` and 1170 with it -- so "worse" does not mean the same
    thing on both sides. Vetoing on them rejected the candidate the clause was
    written to protect and cost seven measured settings across the corpus.
    """
    base = (0.990, 0.772, 535, (140, 1517, 0x3900, 0x3800), 0.0, 0.450)
    wp = (0.990, 0.772, 535, (1170, 1517, 0x3800, 0x3800), 0.269, 0.750)
    assert presets.fidelity_better(wp, base),         "better on noise, oscillation and onset -- a noisier pitch estimate "         "over eight times the sample must not veto it"


def test_silencing_the_drum_is_not_a_win_however_the_onset_moves():
    """The one regression a *ratio* cannot state.

    `_ratio` reads 0 noise frames as "not measurable" and `_closer` declines
    to compare it, so a candidate that silences a drum outright would slip
    past the no-regression clause while winning on some other term. It is
    named explicitly.
    """
    have = (0.990, 0.772, 535, (1170, 1517, 0x3800, 0x3800), 0.269, 0.750)
    none = (0.990, 0.772, 535, (0, 1517, 0, 0x3800), 0.269, 0.900)
    assert not presets.fidelity_better(none, have)


# --- v0.5.235: one bad combination is not a failed song ---------------------

def test_a_candidate_that_will_not_convert_is_skipped_not_fatal(tmp_path):
    """Letting the exception out of `play` abandoned the whole 31-combination
    walk and fell back to the structural defaults -- which *drops* a setting an
    earlier search had measured. W_A_R lost `two_stage` that way: 4 of its
    combinations overflow Goattracker's 255-entry wavetable at -S4, and the
    other 27 were never scored."""
    import shutil
    import fidelity as F
    import presets as P

    skipped, converted = [], []

    def fake_convert(path, log=None, **opts):
        on = tuple(sorted(k for k, v in opts.items() if v is True))
        if opts.get("two_stage"):
            raise ValueError("wave table needs 256 entries")
        converted.append(on)
        return b"blob"

    voices = [F.Voice(), F.Voice(), F.Voice()]
    stubs = {
        "make_workdir": lambda *a, **k: (tmp_path, False),
        "resolve_subtune": lambda *a, **k: 0,
        "calibration": lambda d: 0,
        "run_siddump": lambda *a, **k: voices,
        "pack_sid": lambda *a, **k: tmp_path / "p.sid",
        "legalise_restarts": lambda b: (b, 0),
        "compare": lambda a, b: {"melody": 0.5, "sequence": 0.5},
        "wave_compare": lambda *a, **k: {"our_noise_frames": 0,
                                         "orig_noise_frames": 0},
        "startup_lag": lambda a, b: (0, 0),
        "pitch_motion_compare": lambda *a, **k: {"reversal_ratio": 1.0},
        "onset_agreement": lambda *a, **k: {"onset_frame_agreement": 0.5},
    }
    saved = {k: getattr(F, k) for k in stubs}
    old_convert, old_freq, old_load = P.convert, P.find_freq_table, P.load_sid
    old_copy, old_pitch = shutil.copyfile, P._noise_pitch
    for k, v in stubs.items():
        setattr(F, k, v)
    P.convert, P.find_freq_table, P.load_sid = fake_convert, lambda s: None, lambda s: None
    shutil.copyfile = lambda a, b: None
    P._noise_pitch = lambda *a, **k: None
    try:
        got = P.tune_by_fidelity(tmp_path / "x.sid", {}, 4, "siddump", "gt2reloc",
                                 10, log=skipped.append)
    finally:
        for k, v in saved.items():
            setattr(F, k, v)
        P.convert, P.find_freq_table, P.load_sid = old_convert, old_freq, old_load
        shutil.copyfile, P._noise_pitch = old_copy, old_pitch

    # Derived from the toggle count rather than written down: with n toggles
    # the walk tries 2**n - 1 non-empty combinations and 2**(n - 1) of them
    # carry two_stage and raise. Hardcoded as 31/16/15/17 while n was 5, and
    # v0.5.302's sixth toggle broke it -- a number restating what the module
    # declares drifts from it, which is the same lesson as the vibrato
    # census's bit table (7.yyyyy).
    n = len(P.FIDELITY_TOGGLES)
    # v0.5.429 prunes the combinations that set both `max_hard_restart` and
    # `wide_hard_restart`, which are byte-identical to the same flags without
    # the width (see presets._redundant_combination). Counted from the
    # predicate rather than written down, for the same reason the toggle count
    # is: a number restating what the module declares drifts from it.
    import itertools as _it
    _combos = [dict(zip(P.FIDELITY_TOGGLES, f))
               for f in _it.product((False, True), repeat=n)
               if any(f) and not P._redundant_combination(
                   dict(zip(P.FIDELITY_TOGGLES, f)))]
    raising = sum(1 for c in _combos if c["two_stage"])
    scored = len(_combos) - raising
    assert got == {}
    # Count the lines this test is ABOUT rather than every line logged: since
    # v0.5.45x the hard-restart pre-check logs its own skip too, and a bare
    # `len(skipped)` counted that as a refused combination. Same lesson as the
    # toggle count above -- assert on the thing you mean, not on a total that
    # anything else may join.
    refused = [m for m in skipped if "will not convert" in m]
    assert len(refused) == raising
    # ...and nothing ELSE is logged except the one other line the walk may now
    # emit. Kept as a whitelist rather than dropped: the guard exists so a
    # future silent failure cannot hide inside the log, and widening it to
    # "anything goes" would retire it.
    assert all("will not convert" in m or "sub-search skipped" in m
               for m in skipped)
    # The scored candidates, the reference, the subtune probe before it, and
    # the integer pass over `hard_restart_frames` -- one conversion per value
    # in HARD_RESTART_SEARCH, run against whichever combination the boolean
    # walk selected. DERIVED from the module rather than written down, for the
    # reason above: this assertion was hardcoded at 31/16/15/17 while n was 5
    # and broke on the sixth toggle. It would break again on a fourth frame
    # value.
    #
    # The frame pass tries each value against the selection AND against each
    # bound-raiser, because `hard_restart_frames` and `--max-hard-restart` are
    # worthless apart -- neither changes a byte alone on 5_Title_Tunes and
    # together they are worth 25 points of `gate`. So the term is
    # values x (1 + enablers), derived rather than written down.
    #
    # `_inert_frames` adds two more conversions, but only when the pass
    # actually selects a value; here every candidate scores identically so
    # none is accepted, `got` is empty, and the byte check never runs.
    #
    # SINCE v0.5.45x THE PASS IS GUARDED BY A PRE-CHECK, and in this stub every
    # conversion returns the same bytes, so the grid is inert and the pass does
    # not run at all. What is counted here is therefore the PRE-CHECK's cost --
    # one reference plus one per grid point, all conversions, no packing and no
    # tracing -- in place of the pass's. Both terms are derived from the module
    # so that a fourth frame value or a third enabler moves them together.
    grid_points = len(P.HARD_RESTART_SEARCH) * (1 + len(P.HARD_RESTART_ENABLERS))
    pre_check = 1 + grid_points
    frame_pass = 0          # skipped: the stub converts identically every time
    assert len(converted) == scored + 2 + pre_check + frame_pass
    assert any("sub-search skipped" in m for m in skipped),         "the pre-check did not fire, so this is counting the wrong thing"


def test_the_search_window_is_the_window_the_report_is_published_at():
    """v0.5.195 moved `FIDELITY.md` to 60 s because at 10 s a fifth of the
    corpus contributed nothing to some columns. The *search* stayed at 10 and
    nobody re-read that finding: Sanxion's 10 s window holds 1 comparable
    instrument and **zero** noise frames against 8 and 1669 at 60 s, so the
    noise and onset criteria were blind there and it dropped `two_stage` --
    which an independent 60 s A/B scores at onset 62% -> 100%. Five files were
    decided that way. Pinned so the window cannot drift back silently."""
    import presets as P
    assert P.build_parser().get_default("seconds") == 60


def test_every_per_song_decision_in_the_artefact_survives_a_regeneration():
    """A per-song option not in CARRIED_PER_SONG is deleted by the next
    `presets.py` run, silently.

    This is the fourth sighting of that failure and the first guard against
    the general case. `hard_restart_frames` was caught in the act at
    v0.5.389; five `rest_envelope_silence` entries were gone for 25 versions;
    and the v0.5.397 regeneration deleted `real_firstwave_instruments` from
    both songs carrying it -- one of them human-approved. The earlier guards
    were each written for one named option, so each new option arrived
    unprotected.

    The question this asks is not "does the option reach `convert`" (the
    tests above) but "is the artefact the only copy of this decision, and can
    a regeneration destroy it". Any convert() option that appears per song and
    is not in the `always` block has exactly one home, and CARRIED_PER_SONG is
    what preserves it.
    """
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    options = set(inspect.signature(convert).parameters)
    always = set(doc.get("always", {}))
    # presets.py re-derives these structurally on every run, so they need no
    # carrying -- they are measurements of the FILE, not decisions about it.
    derived = {"bytes", "rows", "subtunes", "multiplier", "max_rows",
               "dedup", "prune", "pack"}

    unprotected = {}
    for name, entry in doc.get("songs", {}).items():
        for key, value in entry.items():
            if not value or key in derived or key in always:
                continue
            if key in options and key not in presets.CARRIED_PER_SONG:
                unprotected.setdefault(key, []).append(name)
    assert not unprotected, (
        "these per-song decisions would be deleted by the next presets.py "
        f"run: { {k: v[:3] for k, v in unprotected.items()} } -- add each key "
        "to presets.EXCLUDED_FROM_ALWAYS (which feeds CARRIED_PER_SONG)")
