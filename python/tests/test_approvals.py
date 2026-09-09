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
    does: write the intermediate `.sng`, pack a `.sid`, and RETURN BOTH as a
    `Converted` pair.

    IT RETURNS THE REAL `sound_calibrate.Converted`, NOT A LOOK-ALIKE. A fake
    shaped by hand would pin the fake's convention rather than the module's, and
    that is precisely the defect this pair replaced: the previous fake wrote the
    `.sng` to a path it invented and returned only the packed `.sid`, so both
    it and `recover_approved_sng` agreed on a convention that appeared in no
    signature. Importing the real type means a change to that type breaks these
    tests, which is the whole point of having them.
    """
    import sound_calibrate as SC

    def convert_at(version, sid, workdir, gt2reloc, multiplier):
        out = tmp_path / f"{stem}.{sha}.sng"
        out.write_bytes(sng_bytes)
        packed = tmp_path / packed_name
        packed.write_bytes(b"this is a packed .sid, not a .sng")
        return SC.Converted(sng=out, sid=packed)
    return convert_at


def test_convert_at_returns_the_sng_it_writes_beside_the_packed_sid():
    """The contract this pair exists for: BOTH artefacts come back named, so no
    caller has to rebuild `workdir / f"{stem}.{sha}.sng"` out of parts."""
    import sound_calibrate as SC
    assert SC.Converted._fields == ("sng", "sid")


def test_recover_reads_the_returned_sng_and_not_a_rebuilt_path(tmp_path):
    """SABOTAGE-SHAPED: the fake writes its `.sng` to a name the old
    reconstruction would NOT have produced. Under the old code -- which built
    `workdir / f"{stem}.{sha}.sng"` itself -- this recovers nothing; under the
    returned pair it recovers the bytes."""
    import hashlib
    import sound_calibrate as SC
    sng = b"the approved bytes"
    odd = tmp_path / "not-the-conventional-name.sng"

    def convert_at(version, sid, workdir, gt2reloc, multiplier):
        odd.write_bytes(sng)
        packed = tmp_path / "packed.sid"
        packed.write_bytes(b"packed")
        return SC.Converted(sng=odd, sid=packed)

    got = AP.recover_approved_sng(
        "Tune", tmp_path / "Tune.sid", "0.5.1",
        hashlib.sha256(sng).hexdigest(), tmp_path, "gt2reloc", 1,
        convert_at=convert_at)
    assert got == sng, "recover must read the path convert_at RETURNED"


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


# --------------------------------------------------- the real packing path
#
# These exist because 15 green tests did not notice that the first real
# assessment died on `FileNotFoundError: <workdir>/cur/a.sng`. Every one of
# them injected a fake `convert_at` and none reached the packer at all, so the
# suite was green on both sides of a defect that made the tool unusable.
#
# The half that matters is the FIRST test: it calls the REAL
# `fidelity.pack_sid`, not a stand-in. It needs no gt2reloc, because pack_sid
# writes its `.sng` BEFORE it shells out -- so a missing directory fails at the
# write, which is exactly the defect's own failure mode.

def test_pack_sid_really_does_not_create_its_own_directory(tmp_path):
    """The contract `pack_into` exists to satisfy, pinned on the REAL function.

    If pack_sid ever starts creating its own directory this fails, and that is
    the point: `pack_into`'s mkdir would then be dead code, and a later reader
    should be told rather than left guessing why it is there.
    """
    import fidelity as F
    missing = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError):
        F.pack_sid(b"\x00" * 32, missing, "gt2reloc-not-invoked", 1)


def test_pack_into_creates_the_directory_the_packer_writes_into(tmp_path):
    """The regression itself: `pack_into` on a missing directory must NOT raise
    FileNotFoundError. gt2reloc may refuse these bytes and return None -- that
    is fine and is not what is under test; the assertion is that we got far
    enough to ask it."""
    import approvals as AP
    called = {}

    def fake_pack_sid(sng, workdir, exe, multiplier=1, pulse_skip=False):
        # Asserts the caller's guarantee at the moment pack_sid would rely on
        # it, rather than after the fact.
        called["dir_existed"] = workdir.is_dir()
        (workdir / "a.sng").write_bytes(sng)      # what the real one does first
        return workdir / "b.sid"

    # A REAL .sng, because pack_into legalises before packing and the legaliser
    # parses the format -- 32 zero bytes is not a fixture, it is a different
    # test failing for a different reason (IndexError inside legalise_restarts).
    sng = (AP.ROOT / "Commando.sng").read_bytes()
    real = AP.F.pack_sid
    AP.F.pack_sid = fake_pack_sid
    try:
        got = AP.pack_into(sng, tmp_path, "cur", "gt2reloc", 1)
    finally:
        AP.F.pack_sid = real
    assert called["dir_existed"], "pack_into must create <workdir>/<tag> BEFORE packing"
    assert got == tmp_path / "cur" / "b.sid"
    assert (tmp_path / "cur" / "a.sng").exists()


def test_pack_into_is_reachable_without_running_an_assessment(tmp_path):
    """It is module-level ON PURPOSE. As a closure inside `assess` the only way
    to exercise it was to run a whole assessment, which is why the defect
    shipped past a green suite."""
    import approvals as AP
    assert callable(getattr(AP, "pack_into", None))
