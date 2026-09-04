"""Per-song option presets (--presets).

The output-shaping options are opt-in and the right setting is not the same for
every tune, so presets.py searches the combinations per song and records the
winner. This covers the consuming half: a stored entry must be applied, and an
explicit flag must still beat it.
"""
import json
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID = REPO_ROOT / "Commando.sid"
REFERENCE = REPO_ROOT / "Commando.sng"


def _write(tmp_path, entry, always=None):
    doc = {"always": always or {}, "songs": {"Commando.sid": entry}}
    path = tmp_path / "p.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _run(tmp_path, *extra):
    out = tmp_path / "o.sng"
    r = subprocess.run(
        [sys.executable, "-m", "h2g", str(SID), "-o", str(out), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True)
    return r, out


def test_an_empty_preset_matches_the_defaults(tmp_path):
    path = _write(tmp_path, {})
    r, out = _run(tmp_path, "--presets", str(path))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == REFERENCE.read_bytes()


def test_a_song_with_no_entry_converts_at_the_defaults(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"songs": {"Other.sid": {"max_rows": 128}}}), encoding="utf-8")
    r, out = _run(tmp_path, "--presets", str(path))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == REFERENCE.read_bytes()


def test_stored_options_are_applied(tmp_path):
    path = _write(tmp_path, {"max_rows": 128, "pack": True, "dedup": True})
    r, out = _run(tmp_path, "--presets", str(path))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() != REFERENCE.read_bytes()


def test_an_explicit_flag_beats_the_preset(tmp_path):
    # The preset says 128; the command line says 94, which is what the
    # byte-exact fixture encodes.
    path = _write(tmp_path, {"max_rows": 128})
    r, out = _run(tmp_path, "--presets", str(path), "--max-rows", "94")
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == REFERENCE.read_bytes()


def test_the_always_block_is_applied(tmp_path):
    # gts5 differs from gts2 by the magic and one extra empty table.
    path = _write(tmp_path, {}, always={"format": "gts5"})
    r, out = _run(tmp_path, "--presets", str(path))
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:4] == b"GTS5"


def test_an_equals_form_flag_beats_the_always_block(tmp_path):
    # Argparse accepts `--format=gts5` as a single token; the explicit-flag
    # detection used to test raw argv membership and miss it, letting the
    # preset silently override what the user typed.
    path = _write(tmp_path, {}, always={"format": "gts2"})
    r, out = _run(tmp_path, "--presets", str(path), "--format=gts5")
    assert r.returncode == 0, r.stderr
    assert out.read_bytes()[:4] == b"GTS5"


def test_an_equals_form_flag_beats_the_song_entry(tmp_path):
    # Same defect on the per-song side: an explicit `--max-rows=94` must beat
    # the stored 128 and reproduce the byte-exact fixture.
    path = _write(tmp_path, {"max_rows": 128})
    r, out = _run(tmp_path, "--presets", str(path), "--max-rows=94")
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == REFERENCE.read_bytes()


def test_a_missing_file_is_a_clean_error(tmp_path):
    r, _ = _run(tmp_path, "--presets", str(tmp_path / "nope.json"))
    assert r.returncode != 0
    assert "presets" in r.stderr.lower()


def test_malformed_json_is_a_clean_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    r, _ = _run(tmp_path, "--presets", str(path))
    assert r.returncode != 0
    assert "json" in r.stderr.lower()


# --- the artefact must describe the conversion it recorded -----------------

def test_every_fixed_option_reaches_the_always_block(tmp_path):
    """`presets.py` CONVERTS with FIXED and used to write the `always` block
    key by key, so an option added to FIXED moved every recorded `bytes` and
    `rows` while never reaching the block `fidelity._preset_opts` reads --
    an artefact describing a conversion its own options cannot reproduce.
    `silent_park` did exactly that.

    Third instance of one shape this session: a generated half and a
    hand-written half that can disagree (the report's header vs its rows, the
    not-converted dash count, and this).
    """
    import presets
    want = {presets._ALWAYS_NAME.get(k, k) for k in presets.FIXED
            if k not in presets.EXCLUDED_FROM_ALWAYS}
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    missing = want - set(doc.get("always") or {})
    assert not missing, (
        f"in FIXED but not in presets.json's always block: {sorted(missing)} "
        "-- regenerate presets.json")


def test_the_carry_forward_keeps_options_no_search_can_re_derive():
    """A regeneration without --fidelity cannot re-derive a per-song setting,
    so it carries what the artefact already records. It used to carry only
    FIDELITY_TOGGLES -- a BOOLEAN walk -- which silently dropped
    5_Title_Tunes' hand-measured `hard_restart_frames: 4` on every
    regeneration, returning its gate to 50%. Observed, not hypothesised.
    """
    import presets
    for key in presets.FIDELITY_TOGGLES:
        assert key in presets.CARRIED_PER_SONG, key
    # the int the boolean search cannot express
    assert "hard_restart_frames" in presets.CARRIED_PER_SONG
    # and it is keyed on EXCLUDED_FROM_ALWAYS, so a future per-song option
    # joins by being declared rather than by being remembered here
    for key in presets.EXCLUDED_FROM_ALWAYS:
        assert key in presets.CARRIED_PER_SONG, key


def test_the_rest_envelope_adoption_survived_regeneration():
    """v0.5.367 measured `rest_envelope_silence` into five songs' entries and
    a presets.py regeneration silently DELETED all five by v0.5.370 -- the
    carry-forward then only knew FIDELITY_TOGGLES. The option spent 25
    versions looking unreachable when it was reachable and had been reached;
    the plan even carried a task saying '0 of 83 songs carry it'.

    Restored at this head for the four non-approved songs of the five (ACE_II
    stays out: it is human-approved and its recorded sha matches the no-flag
    conversion). This test is the alarm if any future regeneration drops them
    again -- with both keys in CARRIED_PER_SONG it should be impossible, and
    impossible things are what the suite is for.
    """
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    carrying = {n for n, e in doc["songs"].items()
                if e.get("rest_envelope_silence")}
    assert carrying >= {"Auf_Wiedersehen_Monty.sid", "BMX_Kidz.sid",
                        "Shockway_Rider.sid", "Thundercats.sid"}, (
        f"the measured rest-envelope adoption was lost again: {carrying}")


def test_the_frame_count_is_searched_as_values_not_as_another_toggle():
    """An int cannot join the boolean product without multiplying it.

    Seven toggles is 127 combinations a song; a four-valued axis would make it
    508. The values are searched in a second pass over the boolean winner
    instead, so the cost is `len(HARD_RESTART_SEARCH)` extra conversions per
    song rather than four times as many.
    """
    import presets as P

    assert "hard_restart_frames" not in P.FIDELITY_TOGGLES, (
        "an int in the boolean product would be coerced to True/False")
    assert P.HARD_RESTART_SEARCH, "the pass needs values to try"
    assert all(isinstance(v, int) and v > 0 for v in P.HARD_RESTART_SEARCH)
    assert 2 not in P.HARD_RESTART_SEARCH, (
        "2 is HARD_RESTART_FRAMES, the reference the pass measures against")


def test_the_frame_count_survives_a_regeneration():
    """It is in CARRIED_PER_SONG, so a plain run keeps a measured value.

    This is the guard the option needed before it was searchable at all: a
    regeneration deleted 5_Title_Tunes' hand-measured 4 once already.
    """
    import presets as P

    assert "hard_restart_frames" in P.CARRIED_PER_SONG


def test_an_inert_frame_count_is_dropped(tmp_path, monkeypatch):
    """A value whose removal changes not one byte was never what a
    measurement preferred -- the same rule `prune_inert` applies to flags,
    in the same currency."""
    import presets as P

    monkeypatch.setattr(P, "convert",
                        lambda path, log=None, **opts: b"identical")
    assert P._inert_frames(tmp_path / "x.sid", {},
                           {"hard_restart_frames": 4}) is True


def test_a_frame_count_that_moves_bytes_is_kept(tmp_path, monkeypatch):
    import presets as P

    def fake(path, log=None, **opts):
        return b"with" if opts.get("hard_restart_frames") else b"without"

    monkeypatch.setattr(P, "convert", fake)
    assert P._inert_frames(tmp_path / "x.sid", {},
                           {"hard_restart_frames": 4}) is False


def test_a_conversion_that_raises_is_not_called_inert(tmp_path, monkeypatch):
    """Cannot prove it inert is not the same as proved inert -- dropping a
    measured value because the check crashed would be the worse error."""
    import presets as P

    def boom(path, log=None, **opts):
        raise ValueError("nope")

    monkeypatch.setattr(P, "convert", boom)
    assert P._inert_frames(tmp_path / "x.sid", {},
                           {"hard_restart_frames": 4}) is False


def test_a_fidelity_search_carries_what_it_cannot_re_derive():
    """The carry-forward used to apply only on the NO-SEARCH path.

    `presets.py` carried previous per-song settings under an `elif`, so a
    SUCCESSFUL `--fidelity` run dropped every per-song decision outside
    FIDELITY_TOGGLES -- it carried only when the search had raised. Measured
    over the corpus before the fix: 19 lost. `regrid` on all 12 files carrying
    it, `rest_envelope_silence` on 4, `real_firstwave_instruments` on 2 (one of
    them human-approved) and `pulse_phase` on 1.

    FOURTH sighting of a regeneration deleting a measured decision:
    hard_restart_frames at v0.5.389, five rest_envelope_silence entries lost
    for 25 versions, real_firstwave_instruments at v0.5.398, and this. The
    three earlier fixes each widened WHAT is carried; none noticed the carry
    was skipped on the path that re-decides the most. So this pins the RULE --
    carry anything the run cannot re-derive -- rather than any one option.
    """
    import presets as P

    derivable = set(P.FIDELITY_TOGGLES) | {"hard_restart_frames"}
    must_survive = [k for k in P.CARRIED_PER_SONG if k not in derivable]
    assert must_survive, (
        "nothing left to carry -- either the search grew or CARRIED_PER_SONG "
        "shrank; check which before deleting this test")
    for k in ("regrid", "rest_envelope_silence", "real_firstwave_instruments",
              "pulse_phase"):
        assert k in must_survive, f"{k} would be dropped by a --fidelity run"


def test_the_frame_count_is_derivable_and_so_is_not_blindly_carried():
    """`hard_restart_frames` became searchable, so a `--fidelity` run must be
    free to overwrite a carried value -- otherwise the first hand measurement
    would be permanent and the search could never correct it."""
    import presets as P

    assert "hard_restart_frames" in P.CARRIED_PER_SONG, (
        "still carried on a plain run, where nothing re-derives it")
    assert P.HARD_RESTART_SEARCH and P.HARD_RESTART_ENABLERS, (
        "and derivable on a --fidelity run, which is why it is excluded there")



# --------------------------------------------------------------------------
# A regeneration must be able to carry a measured NO, not only a measured YES.
# --------------------------------------------------------------------------

def test_carried_entry_keeps_an_explicit_false():
    """The whole point: `regrid: false` is a DECISION and must survive.

    Until v0.5.413 the carry tested `entry.get(k)`, so an explicit false was
    silently dropped and "measured and rejected" was byte-identical to "never
    tried" for all sixteen CARRIED_PER_SONG options. That matters most for the
    options `fidelity_better` cannot select at all -- `--regrid` is hand-adopted
    on twelve files, so the artefact is the only record of any decision about
    it, and it could only ever record the yeses.
    """
    import presets
    assert presets.carried_entry({"regrid": False}) == {"regrid": False}


def test_carried_entry_still_keeps_a_true_and_still_ignores_absent():
    import presets
    assert presets.carried_entry({"regrid": True}) == {"regrid": True}
    assert presets.carried_entry({"max_rows": 94}) == {}


def test_carried_entry_carries_a_false_beside_a_true():
    """Membership, not truthiness -- and the two must not interfere."""
    import presets
    got = presets.carried_entry({"regrid": False, "two_stage": True,
                                 "max_rows": 94})
    assert got == {"regrid": False, "two_stage": True}


def test_every_carried_key_is_a_membership_test_not_a_truthiness_one():
    """Pins the property for the whole set rather than for one key.

    A future option joins CARRIED_PER_SONG by being declared, so a test naming
    only `regrid` would not notice the next one being added under the old rule.
    """
    import presets
    falsey = {k: False for k in presets.CARRIED_PER_SONG}
    assert presets.carried_entry(falsey) == falsey


def test_the_only_pruned_combination_is_wide_under_max():
    """The prune is narrow by construction and nothing else is skipped.

    A combination may be dropped from the walk ONLY when a combination still
    visited produces the same bytes. Anything wider silently changes what the
    search selects, because `fidelity_better` is not a total order.
    """
    import itertools
    import presets as P
    combos = [dict(zip(P.FIDELITY_TOGGLES, f))
              for f in itertools.product((False, True),
                                         repeat=len(P.FIDELITY_TOGGLES))
              if any(f)]
    skipped = [c for c in combos if P._redundant_combination(c)]
    assert skipped, "the prune must actually skip something"
    for extra in skipped:
        assert extra["max_hard_restart"] and extra["wide_hard_restart"]
        # Every skipped combination has a surviving twin -- the same flags with
        # the width cleared -- which is what makes the skip lossless.
        twin = {**extra, "wide_hard_restart": False}
        assert not P._redundant_combination(twin), extra
    assert len(combos) == 127
    assert len(skipped) == 32, len(skipped)


def test_no_combination_without_max_is_pruned():
    """The converse guard.

    `wide_hard_restart` moves the bytes on 36 of 83 corpus files when
    `max_hard_restart` is off, so pruning it there would delete a live axis --
    the v0.5.426 defect `_redundant_combination`'s docstring cites.
    """
    import itertools
    import presets as P
    for f in itertools.product((False, True),
                               repeat=len(P.FIDELITY_TOGGLES)):
        extra = dict(zip(P.FIDELITY_TOGGLES, f))
        if not extra["max_hard_restart"]:
            assert not P._redundant_combination(extra), extra


# --------------------------------------------------------------------------
# A fresh -o path has nothing to carry FROM, and that must not be silent.
# --------------------------------------------------------------------------

def test_a_nonexistent_output_path_warns_nothing_was_carried(tmp_path, capsys):
    """f0fd20c: a search written to a fresh `-o` path (`C:/t/hr1_candidate.json`)
    produced a diff against the shipped presets.json that read as 23 destroyed
    measurements -- regrid x12, rest_envelope_silence x4,
    real_firstwave_instruments x2, pulse_phase x1, force_park x1. None was
    destroyed; none was ever carried, because there was nothing at the output
    path to carry FROM. `kept` was silently 0 either way (a real file with
    nothing carryable, or no file at all), so the old code said nothing.

    This is the plain structural pass (no --fidelity) -- the same silence the
    task's own repro used, and the cheaper one to run in a test.
    """
    import presets as P

    sid_dir = tmp_path / "sids"
    sid_dir.mkdir()
    shutil.copy(SID, sid_dir / SID.name)
    out = tmp_path / "fresh.json"  # never written -- no previous file exists
    assert not out.exists()

    rc = P.main([str(sid_dir), "-o", str(out)])
    assert rc == 0

    stderr = capsys.readouterr().err
    assert "no previous file" in stderr, stderr
    assert "0 were carried" in stderr, stderr
    # The old, silent behaviour: no "carried N ... forward" line at all,
    # because kept was 0. Confirm the warning replaces that silence rather
    # than an actual carry count being misreported.
    assert "carried " not in stderr.split("no previous file")[0], stderr


def test_an_existing_previous_file_still_prints_its_carried_count(tmp_path, capsys):
    """The counterpart: -o pointing at a REAL previous file with a carryable
    per-song setting must still print the ordinary `carried N ... forward`
    line, and must NOT also print the new fresh-path warning -- the two are
    mutually exclusive on purpose (one says how many, the other says why it
    could not say how many).
    """
    import presets as P

    sid_dir = tmp_path / "sids"
    sid_dir.mkdir()
    shutil.copy(SID, sid_dir / SID.name)

    out = tmp_path / "existing.json"
    out.write_text(json.dumps({
        "always": {}, "songs": {SID.name: {"regrid": True}},
    }), encoding="utf-8")

    rc = P.main([str(sid_dir), "-o", str(out)])
    assert rc == 0

    stderr = capsys.readouterr().err
    assert "carried 1 --fidelity setting(s) forward" in stderr, stderr
    assert "no previous file" not in stderr, stderr


def test_pulse_phase_is_carried_but_not_searched():
    """The decision recorded at 64c795b, pinned in both directions.

    `pulse_phase` must stay OUT of `FIDELITY_TOGGLES` and IN
    `CARRIED_PER_SONG`. Measured with the real search machinery: with
    `FIDELITY_TOGGLES` set to `("pulse_phase",)` it is selected on 0 of the 6
    files it reaches, and with the shipped seven plus it, 0 of 6 again --
    because nothing in the criterion's nine-element state reads $D402/$D403.

    Membership is what makes the search authoritative: `main()` carries a
    previous entry across a `--fidelity` run only `if k not in
    FIDELITY_TOGGLES`. So promoting it would replace the four hand-recorded
    adoptions with a measured no, which is the failure this file's `regrid`
    entry and `carried_entry` between them record four times. Cost is not the
    reason and must not be cited as one: seven toggles over those six files is
    161.0 s and eight is 159.8 s.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    import presets
    assert "pulse_phase" not in presets.FIDELITY_TOGGLES
    assert "pulse_phase" in presets.EXCLUDED_FROM_ALWAYS
    assert "pulse_phase" in presets.CARRIED_PER_SONG


def test_a_carried_hand_measurement_survives_a_fidelity_run():
    """`carried_entry` keeps the keys the search cannot re-derive.

    This is the mechanism the four `pulse_phase` adoptions rest on -- and the
    one that has silently failed four times (hard_restart_frames at v0.5.389,
    rest_envelope_silence, real_firstwave_instruments at v0.5.398, and the
    whole non-searchable set on the `--fidelity` path). Asserted on membership
    rather than truthiness, because an explicit `False` is a recorded REFUSAL
    and dropping it makes "measured and rejected" identical to "never tried".
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    import presets
    entry = {"max_rows": 94, "pulse_phase": True, "regrid": False,
             "two_stage": True, "bytes": 123}
    got = presets.carried_entry(entry)
    assert got["pulse_phase"] is True
    assert got["regrid"] is False, "an explicit refusal must survive too"
    assert "bytes" not in got, "derived fields are not carried"


def _state(melody=1.0, seq=1.0, attacks=100, noise=(0, 0, 0, 0), osc=None,
           onset=None, hold=None, gate=None, orig_attacks=100, pphase=None):
    """A `tune_by_fidelity` state tuple, in the order `play()` builds it."""
    return (melody, seq, attacks, noise, osc, onset, hold, gate,
            orig_attacks, pphase)


def test_a_pulse_phase_gain_is_enough_to_accept():
    """The TENTH element, and the first thing in this criterion that reads
    $D402/$D403.

    Elements 0-8 are melody, sequence, our attacks, the noise 4-tuple,
    `reversal_ratio`, `onset_frame_agreement`, `sound_run_agreement`, `gate`
    and the original's attack count -- and the note beside `pulse_phase` in
    `FIXED` records, measured at 64c795b, that not one of them touches the
    pulse registers, which is why the search took that option on 0 of the 6
    files it reaches. `pulse_phase` is ours-over-theirs with 1.0 right, so a
    move toward 1 is a gain and `_closer` judges it in log space like every
    other ratio here.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    import presets
    ref = _state(pphase=0.20)
    cand = _state(pphase=0.90)
    assert presets.fidelity_better(cand, ref), \
        "a pulse phase moving toward the original's is an acceptance"
    assert not presets.fidelity_better(ref, cand), \
        "and moving away from it is not"


def test_the_pulse_term_is_acceptance_only_and_keeps_notes_still_vetoes():
    """Never a veto, for the reason the oscillation and noise-pitch clauses
    give: a setting that changes WHICH notes sound changes the attack frames
    the phase is sampled at, so a term whose sample the setting resizes must
    not be the thing that rejects it. And `keeps_notes` outranks it -- the
    anti-gaming guard that has protected every term here since the first.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    import presets
    # a big phase gain bought with a melody collapse is still refused
    cand = _state(melody=0.40, pphase=0.99)
    ref = _state(melody=1.00, pphase=0.10)
    assert not presets.fidelity_better(cand, ref), "keeps_notes outranks it"
    # and a phase LOSS alone never rejects a candidate winning on melody
    cand2 = _state(melody=1.00, pphase=0.10)
    ref2 = _state(melody=0.50, pphase=0.99)
    assert presets.fidelity_better(cand2, ref2), "acceptance only, not a veto"


def test_a_nine_element_state_still_works():
    """An older saved state has no tenth element, and an absent dimension must
    not recommend anything -- the same convention `osc`, `opens`, `holds` and
    `gates` use. Without this the term would raise IndexError on any state
    built before it existed.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    import presets
    old_ref = _state()[:9]
    old_cand = _state(melody=1.0)[:9]
    assert presets.fidelity_better(old_cand, old_ref) is False


def test_a_sharded_fidelity_run_refuses_rather_than_dropping_carried_settings(
        tmp_path):
    """`--shard` bypassed carry-forward, and the merged file looked complete.

    MEASURED at v0.5.457: six shards each written to a fresh `-o`, then
    `--merge`, LOST 30 per-song decisions -- all 13 `--regrid` adoptions, 4
    `rest_envelope_silence`, 4 `pulse_phase`, 2 `real_firstwave_instruments`,
    `force_park` and `initial_instrument` -- to gain the one setting the run
    was launched for. The carry reads the OUTPUT file, and a shard's output
    does not exist yet, so `carried` was empty and the branch that exists to
    preserve non-searchable settings had nothing to preserve.

    This is the FIFTH sighting of a regeneration deleting a measured decision,
    and the comment above that branch already enumerates four and states the
    rule -- "carry anything the run cannot RE-DERIVE, on every path". The shard
    path is the one it missed.

    Refused rather than warned: `--merge` cannot tell afterwards, because a
    dropped setting and a setting that was never measured are the same absence.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    out = tmp_path / "shard.json"          # deliberately does not exist
    r = subprocess.run(
        [sys.executable, str(PYTHON_ROOT / "presets.py"), str(tmp_path),
         "--fidelity", "--shard", "0/6", "-o", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout[-400:] + r.stderr[-400:]
    assert "no readable carry source" in r.stderr
    # It must name the way out, not merely complain.
    assert "--carry-from" in r.stderr and "--no-carry" in r.stderr


def test_no_carry_still_lets_a_sharded_run_through(tmp_path):
    """The refusal is about a SILENT drop, not about sharding. Someone who
    means to re-decide from nothing says so and is allowed to.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    out = tmp_path / "shard.json"
    r = subprocess.run(
        [sys.executable, str(PYTHON_ROOT / "presets.py"), str(tmp_path),
         "--fidelity", "--shard", "0/6", "--no-carry", "-o", str(out)],
        capture_output=True, text=True)
    assert r.returncode != 2 or "no readable carry source" not in r.stderr


def test_carry_from_is_read_instead_of_the_output_file(tmp_path):
    """The fix, not just the guard: a shard writing a fresh file must be able
    to carry from the shipped presets.
    """
    sys.path.insert(0, str(PYTHON_ROOT))
    src = tmp_path / "shipped.json"
    src.write_text(json.dumps({
        "always": {}, "songs": {"Commando.sid": {"regrid": True}}}),
        encoding="utf-8")
    out = tmp_path / "shard.json"
    r = subprocess.run(
        [sys.executable, str(PYTHON_ROOT / "presets.py"), str(tmp_path),
         "--fidelity", "--shard", "0/6", "--carry-from", str(src),
         "-o", str(out)],
        capture_output=True, text=True)
    assert "no readable carry source" not in r.stderr, r.stderr[-400:]
