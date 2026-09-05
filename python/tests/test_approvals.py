"""Whether a build inherits a human approval. Pure logic on fixture records;
the render/trace plumbing is exercised by hand in Task 5 step 6."""
import json

import pytest

import approvals as AP

CAL = {"noise_floor": 0.005, "closeness_floor": 0.90}


def _structure(**kw):
    s = {"attacks": 100, "orig_attacks": 100, "approved_attacks": 100,
         "melody": 0.95, "approved_melody": 0.95,
         "sequence": 0.95, "approved_sequence": 0.95, "length_delta": None}
    s.update(kw)
    return s


def _vs(aud=0.90, loud=0.90):
    return {"aud": aud, "loud": loud}


def test_the_same_bytes_are_exact():
    got = AP.inherit(_vs(), _vs(), {"aud": 1.0, "loud": 1.0}, _structure(), CAL,
                     same_sha=True)
    assert got["status"] == "exact" and got["failed"] == []


def test_a_build_no_farther_from_the_original_and_close_to_the_approved_inherits():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.92, 0.91), {"aud": 0.96, "loud": 0.95},
                     _structure(), CAL)
    assert got["status"] == "inherited" and got["failed"] == []


def test_farther_from_the_original_than_the_noise_floor_is_stale():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.88, 0.90), {"aud": 0.97, "loud": 0.97},
                     _structure(), CAL)
    assert got["status"] == "stale"
    assert "aud_vs_orig" in got["failed"]


def test_within_the_noise_floor_is_not_farther():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.897, 0.90), {"aud": 0.97, "loud": 0.97},
                     _structure(), CAL)
    assert got["status"] == "inherited"


def test_not_close_enough_to_the_approved_render_is_stale():
    """Scoring as well as the approved build is not enough: it has to SOUND
    like what the person said yes to."""
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.95, 0.95), {"aud": 0.80, "loud": 0.97},
                     _structure(), CAL)
    assert got["status"] == "stale" and "aud_vs_approved" in got["failed"]


def test_a_structural_regression_the_listener_could_hear_is_stale():
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(attacks=80), CAL)
    assert got["status"] == "stale" and "attacks" in got["failed"]
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(melody=0.90), CAL)
    assert "melody" in got["failed"]
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(length_delta=7.0), CAL)
    assert "length" in got["failed"]


def test_attacks_may_move_closer_to_the_originals_count():
    """Fewer attacks is not a regression when the original has fewer: the
    two-sided guard from presets.fidelity_better, not ours-against-ours."""
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(attacks=97, approved_attacks=100, orig_attacks=96), CAL)
    assert "attacks" not in got["failed"]


def test_no_calibration_means_no_inheritance():
    got = AP.inherit(_vs(), _vs(0.99, 0.99), {"aud": 0.99, "loud": 0.99},
                     _structure(), None)
    assert got["status"] == "uncalibrated"


def test_listener_should_check_names_the_criterion_nearest_its_bound():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.899, 0.95), {"aud": 0.91, "loud": 0.99},
                     _structure(), CAL)
    assert got["status"] == "inherited"
    assert got["listener_should_check"] in ("aud_vs_approved", "aud_vs_orig")


def test_inheritance_never_creates_an_approval(tmp_path, monkeypatch):
    """A tune with no human verdict is not assessed at all."""
    monkeypatch.setattr(AP, "ROOT", tmp_path)
    (tmp_path / "approved.json").write_text(json.dumps({"tunes": {}}), encoding="utf-8")
    assert AP.approved_tunes() == {}


def test_the_record_shape_is_stable():
    rec = AP.record("Tune", "abc", "abc",
                    AP.inherit(_vs(), _vs(), {"aud": 1.0, "loud": 1.0}, _structure(), CAL,
                               same_sha=True), previous=None, version="0.5.447")
    assert set(rec) == {"approved_sha", "current_sha", "status", "since",
                        "builds_inherited", "evidence", "failed", "listener_should_check"}
    assert rec["since"] == "0.5.447" and rec["builds_inherited"] == 0


def _fake_convert_at(tmp_path, sha, stem, sng_bytes, packed_name="packed.sid"):
    """Stand in for `sound_calibrate.convert_at`, reproducing what it really
    does: write the intermediate `.sng` beside the workdir and RETURN THE
    PACKED `.sid`. The return value is deliberately not the .sng -- that is
    the whole point of the tests below."""
    def convert_at(version, sid, workdir, gt2reloc, multiplier):
        (tmp_path / f"{stem}.{sha}.sng").write_bytes(sng_bytes)
        packed = tmp_path / packed_name
        packed.write_bytes(b"this is a packed .sid, not a .sng")
        return packed
    return convert_at


def test_recovery_reads_the_sng_convert_at_leaves_not_the_sid_it_returns(tmp_path, monkeypatch):
    """**The plan's Step 5 prescribes this wrongly.** It says convert_at
    "reproduces it, and its sha must equal sng_sha256" -- but convert_at
    returns `F.pack_sid(...)`, a packed .sid. Hashing the RETURN VALUE can
    never match an sng_sha256, so a literal implementation recovers nothing,
    always. This test fails if anyone re-writes it that way."""
    import hashlib
    import sound_calibrate as SC
    sng = b"SNG-BYTES-THE-LISTENER-HEARD"
    want = hashlib.sha256(sng).hexdigest()
    monkeypatch.setattr(SC, "resolve_version_sha", lambda v: "cafe123")
    got = AP.recover_approved_sng(
        "Tune", tmp_path / "Tune.sid", "0.5.400", want, tmp_path, "gt2reloc.exe", 1,
        convert_at=_fake_convert_at(tmp_path, "cafe123", "Tune", sng))
    assert got == sng
    # And the packed .sid it returned is NOT what was recovered.
    assert hashlib.sha256((tmp_path / "packed.sid").read_bytes()).hexdigest() != want


def test_a_sha_that_does_not_match_is_not_recovered(tmp_path, monkeypatch):
    """`approved.json`'s version is then PROVENANCE ONLY -- the build cannot be
    recovered and the tune is stale, which is Step 5's own rule."""
    import sound_calibrate as SC
    monkeypatch.setattr(SC, "resolve_version_sha", lambda v: "cafe123")
    got = AP.recover_approved_sng(
        "Tune", tmp_path / "Tune.sid", "0.5.400", "0" * 64, tmp_path, "gt2reloc.exe", 1,
        convert_at=_fake_convert_at(tmp_path, "cafe123", "Tune", b"different bytes"))
    assert got is None


def test_an_unresolvable_version_recovers_nothing(tmp_path, monkeypatch):
    import sound_calibrate as SC
    monkeypatch.setattr(SC, "resolve_version_sha", lambda v: "")
    called = []
    def convert_at(*a, **k):
        called.append(a)
        return None
    got = AP.recover_approved_sng("T", tmp_path / "T.sid", "9.9.9", "0" * 64,
                                  tmp_path, "g", 1, convert_at=convert_at)
    assert got is None and called == []      # it does not even try


def test_builds_inherited_counts_up_only_while_the_sha_keeps_moving():
    first = AP.record("T", "a", "b", {"status": "inherited", "failed": [],
                                      "listener_should_check": None, "evidence": {}},
                      previous=None, version="1")
    same = AP.record("T", "a", "b", {"status": "inherited", "failed": [],
                                     "listener_should_check": None, "evidence": {}},
                     previous=first, version="2")
    moved = AP.record("T", "a", "c", {"status": "inherited", "failed": [],
                                      "listener_should_check": None, "evidence": {}},
                      previous=same, version="3")
    assert (first["builds_inherited"], same["builds_inherited"], moved["builds_inherited"]) == (1, 1, 2)
    assert moved["since"] == "1"
