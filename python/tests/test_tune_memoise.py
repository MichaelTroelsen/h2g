"""`tune_by_fidelity` scores a conversion once per distinct set of bytes.

The 127-combination walk converts, packs with gt2reloc and traces with siddump
for every combination, though most toggles are inert on most files and so most
combinations produce a conversion identical to one already scored. A score is a
function of the packed bytes, which are a function of the converted ones, so a
combination whose bytes equal an earlier one's can only score as it did.
`play()` memoises on the bytes `pack_sid` receives.

Driven by stubs, so the properties hold whatever the corpus contains: what is
counted is `pack_sid` calls per distinct blob, and what is checked for
outcome-preservation is that same-length, different-byte blobs are NOT merged.
"""
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fidelity as F                                   # noqa: E402
import presets as P                                    # noqa: E402


def _run(monkeypatch, tmp_path, blob_for, melody_for, pack_ok=lambda b: True):
    """Run `tune_by_fidelity` over stubs. Returns (result, packed blobs)."""
    packed_blobs: list[bytes] = []
    cur: list[str] = []
    voices = [F.Voice(), F.Voice(), F.Voice()]

    def fake_pack(blob, *a, **k):
        packed_blobs.append(blob)
        if not pack_ok(blob):
            return None
        return tmp_path / ("p_" + blob.decode())

    def fake_dump(path, *a, **k):
        cur.append(Path(path).name)
        return voices

    def fake_compare(a, b):
        name = cur[-1]
        if not name.startswith("p_"):
            return {"melody": 0.5, "sequence": 0.5}
        return {"melody": melody_for(name[2:].encode()), "sequence": 0.5}

    stubs = {
        "make_workdir": lambda *a, **k: (tmp_path, False),
        "resolve_pair": lambda *a, **k: (0, 0, False),
        "calibration": lambda d: 0,
        "run_siddump": fake_dump,
        "pack_sid": fake_pack,
        "legalise_restarts": lambda b: (b, 0),
        "compare": fake_compare,
        "wave_compare": lambda *a, **k: {"our_noise_frames": 0,
                                         "orig_noise_frames": 0},
        "startup_lag": lambda a, b: (0, 0),
        "pitch_motion_compare": lambda *a, **k: {"reversal_ratio": 1.0},
        "onset_agreement": lambda *a, **k: {"onset_frame_agreement": 0.5},
        "sound_run_agreement": lambda *a, **k: {"sound_run_agreement": 0.5},
        "gate_compare": lambda *a, **k: {"gate": 0.5},
        "pulse_compare": lambda *a, **k: {"pulse_phase": None},
    }
    for k, v in stubs.items():
        monkeypatch.setattr(F, k, v)

    def fake_convert(path, log=None, **opts):
        return blob_for({k for k, v in opts.items() if v is True})

    monkeypatch.setattr(P, "convert", fake_convert)
    monkeypatch.setattr(P, "find_freq_table", lambda s: None)
    monkeypatch.setattr(P, "load_sid", lambda s: None)
    monkeypatch.setattr(P, "_noise_pitch", lambda *a, **k: None)
    monkeypatch.setattr(shutil, "copyfile", lambda a, b: None)
    got = P.tune_by_fidelity(tmp_path / "x.sid", {}, 1, "siddump", "gt2reloc", 10)
    return got, packed_blobs


def test_identical_bytes_are_packed_and_traced_once(monkeypatch, tmp_path):
    """Only `sfx_drum` changes the bytes: two distinct blobs in the whole walk.

    `default` is packed twice -- once by the subtune probe, which is not a
    scored candidate, once as the reference -- and `sfx` once, however many
    combinations convert to it."""
    got, packed = _run(
        monkeypatch, tmp_path,
        blob_for=lambda on: b"sfx" if "sfx_drum" in on else b"default",
        melody_for=lambda b: 0.5)
    assert Counter(packed) == {b"default": 2, b"sfx": 1}, Counter(packed)
    assert got == {}


def test_a_refusal_is_memoised_too(monkeypatch, tmp_path):
    """A blob gt2reloc refuses is refused again by the same bytes."""
    got, packed = _run(
        monkeypatch, tmp_path,
        blob_for=lambda on: b"bad" if "wave_program" in on else b"default",
        melody_for=lambda b: 0.5,
        pack_ok=lambda b: b != b"bad")
    assert Counter(packed)[b"bad"] == 1
    assert got == {}


def test_same_length_different_bytes_are_not_merged(monkeypatch, tmp_path):
    """The outcome is what the walk would have chosen: blobs of equal length
    and different content keep their own scores, so the better one wins."""
    def blob_for(on):
        if "sfx_drum" in on and "wave_program" not in on:
            return b"aaab"
        if "wave_program" in on and "sfx_drum" not in on:
            return b"aaac"
        return b"aaaa"
    melody = {b"aaaa": 0.50, b"aaab": 0.90, b"aaac": 0.10}
    got, packed = _run(monkeypatch, tmp_path, blob_for, lambda b: melody[b])
    assert got == {"sfx_drum": True}
    assert Counter(packed) == {b"aaaa": 2, b"aaab": 1, b"aaac": 1}


def test_every_combination_sharing_one_blob_costs_one_pack(monkeypatch, tmp_path):
    """The whole walk collapses to the probe plus the reference."""
    got, packed = _run(
        monkeypatch, tmp_path,
        blob_for=lambda on: b"x",
        melody_for=lambda b: 0.5)
    assert len(packed) == 2
    assert got == {}
