"""Per-song option presets (--presets).

The output-shaping options are opt-in and the right setting is not the same for
every tune, so presets.py searches the combinations per song and records the
winner. This covers the consuming half: a stored entry must be applied, and an
explicit flag must still beat it.
"""
import json
import pathlib
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
