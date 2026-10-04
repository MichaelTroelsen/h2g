"""presets.tune_by_fidelity and instrmap.report trace the (original, ours)
pair `fidelity.resolve_pair` returns, not one index for both sides.

C64ME pins s1/o0 and Dragons_Lair_Part_II s0/o9 (`fidelity.SUBTUNE_COUNTERPART`).
Both callers used `resolve_subtune`, scoring C64ME's s0 against our s0.
"""
from pathlib import Path

import pytest

import fidelity as F
import instrmap
import presets


class _Stop(Exception):
    pass


PINS = [("Commodore_64_Music_Examples.sid", 1, 0),
        ("Dragons_Lair_Part_II.sid", 0, 9)]


def _stub_common(monkeypatch, calls):
    def fake_run(path, seconds, sub, siddump, *a, **k):
        calls.append((Path(path).name, sub))
        return []
    monkeypatch.setattr(F, "run_siddump", fake_run)
    monkeypatch.setattr(F, "legalise_restarts", lambda b: (b, None))
    monkeypatch.setattr(F, "pack_sid", lambda *a, **k: Path("packed.sid"))


def _stub_presets(monkeypatch):
    monkeypatch.setattr(presets, "load_sid", lambda p: object())
    monkeypatch.setattr(presets, "find_freq_table", lambda s: None)
    monkeypatch.setattr(presets, "convert", lambda *a, **k: b"")
    monkeypatch.setattr(F, "compare",
                        lambda o, d: {"melody": None, "sequence": None})


@pytest.mark.parametrize("name,orig,ours", PINS)
def test_tune_by_fidelity_traces_the_pinned_pair(monkeypatch, tmp_path,
                                                 name, orig, ours):
    sid = tmp_path / name
    sid.write_bytes(b"x")
    calls: list = []
    _stub_common(monkeypatch, calls)
    _stub_presets(monkeypatch)
    assert presets.tune_by_fidelity(sid, {}, 1, "sd", "gt", 1) == {}
    assert calls[0] == ("o.sid", orig)
    ours_calls = [s for n, s in calls if n == "packed.sid"]
    assert ours_calls and set(ours_calls) == {ours}   # pinned: no re-search


def test_tune_by_fidelity_unpinned_keeps_the_diagonal(monkeypatch, tmp_path):
    sid = tmp_path / "Whatever.sid"
    sid.write_bytes(b"x")
    calls: list = []
    _stub_common(monkeypatch, calls)
    _stub_presets(monkeypatch)
    monkeypatch.setattr(F, "resolve_subtune", lambda s, r: 2)
    presets.tune_by_fidelity(sid, {}, 1, "sd", "gt", 1)
    assert calls[0] == ("o.sid", 2)
    assert {s for n, s in calls if n == "packed.sid"} == {2, 1, 3}


@pytest.mark.parametrize("name,orig,ours", PINS)
def test_instrmap_report_traces_the_pinned_pair(monkeypatch, tmp_path,
                                                name, orig, ours):
    sid = tmp_path / name
    sid.write_bytes(b"x")
    calls: list = []

    def fake_run(path, seconds, sub, siddump, *a, **k):
        calls.append((Path(path).name, sub))
        if Path(path).name == "packed.sid":
            raise _Stop
        return []
    monkeypatch.setattr(F, "run_siddump", fake_run)
    monkeypatch.setattr(F, "convert", lambda *a, **k: b"")
    monkeypatch.setattr(F, "legalise_restarts", lambda b: (b, None))
    monkeypatch.setattr(F, "pack_sid", lambda *a, **k: Path("packed.sid"))
    with pytest.raises(_Stop):
        instrmap.report(sid, {}, 1, 1, tmp_path / "w", "gt", "sd")
    assert calls == [("o.sid", orig), ("packed.sid", ours)]
