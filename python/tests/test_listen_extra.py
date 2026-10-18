"""EXTRA_PAGES: a page for a different subtune of a corpus file ("Delta_13").

The page converts and renders its SOURCE file with the source's presets at the
listed subtune, and abpage resolves the page name to the same source, so the
sha it expects is the sha listen.py staged (no stale-audio flag).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abpage as A  # noqa: E402
import extra_pages as E  # noqa: E402
import listen as L  # noqa: E402
import h2g.convert as C  # noqa: E402


def _fake_convert(calls):
    def fake(path, log=None, **opts):
        calls.append((Path(path).name, opts))
        return b"SNG:" + Path(path).name.encode() + repr(sorted(opts.items())).encode()
    return fake


def _setup(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "Tune.sid").write_bytes(b"PSID" + b"\x00" * 200)
    presets = tmp_path / "presets.json"
    presets.write_text(json.dumps({"always": {}, "songs": {
        "Tune.sid": {"max_rows": 77}}}), encoding="utf-8")
    monkeypatch.setitem(E.EXTRA_PAGES, "Tune_2", {"source": "Tune.sid", "subtune": 5})
    calls = []
    monkeypatch.setattr(L, "convert", _fake_convert(calls))
    monkeypatch.setattr(C, "convert", _fake_convert(calls))
    monkeypatch.setattr(L, "legalise_restarts", lambda blob: (blob, 0))
    packed = tmp_path / "packed.sid"
    packed.write_bytes(b"PACKEDSID")
    monkeypatch.setattr(L, "pack_sid", lambda *a, **k: packed)
    renders = []

    def fake_render(src, out, seconds, sub, mute=()):
        Path(out).write_bytes(b"RIFFWAVE")
        renders.append((Path(src).name, sub))
        return True

    monkeypatch.setattr(L, "pick_renderer",
                        lambda sid, args, probe_dir=None: L.Choice(fake_render, "", "fake"))
    monkeypatch.setattr(L, "run_siddump", lambda *a, **k: [])
    monkeypatch.setattr(L, "trace_json", lambda *a, **k: {})
    monkeypatch.setattr(L, "listen_notes", lambda *a, **k: ["stub"])
    return corpus, presets, calls, renders


def _stage(tmp_path, corpus, presets, *extra):
    outdir = tmp_path / "out"
    rc = L.main([str(corpus), "--files", *extra, "-o", str(outdir),
                 "--presets", str(presets), "--workdir", str(tmp_path / "w"),
                 "-t", "1"])
    assert rc == 0
    return outdir


def test_delta_13_is_registered_as_index_12_of_delta():
    assert E.extra_for("Delta_13") == {"source": "Delta.sid", "subtune": 12}
    assert E.extra_for("Delta_13.sid") is E.EXTRA_PAGES["Delta_13"]
    assert E.extra_for("Delta.sid") is None


def test_all_stages_the_extra_page_beside_its_source(tmp_path):
    p = tmp_path / "presets.json"
    p.write_text(json.dumps({"always": {}, "songs": {"Delta.sid": {}}}), encoding="utf-8")
    got = L.select_names([], True, str(p))
    assert got == ["Delta.sid", "Delta_13"]


def test_the_extra_page_uses_its_sources_presets_and_subtune(tmp_path, monkeypatch, capsys):
    corpus, presets, calls, renders = _setup(tmp_path, monkeypatch)
    outdir = _stage(tmp_path, corpus, presets, "Tune_2")
    assert calls[0][0] == "Tune.sid"
    assert calls[0][1]["max_rows"] == 77
    assert renders == [("Tune.sid", 5), ("Tune_2.h2g.sid", 5)]
    assert (outdir / "Tune_2.h2g.sng").exists()
    assert (outdir / "Tune_2.original.wav").exists()
    assert not (outdir / "Tune.h2g.sng").exists()
    assert "not in presets.json" not in capsys.readouterr().err


def test_abpage_sha_for_the_extra_page_equals_the_staged_sng_and_is_not_stale(
        tmp_path, monkeypatch):
    corpus, presets, calls, _ = _setup(tmp_path, monkeypatch)
    outdir = _stage(tmp_path, corpus, presets, "Tune_2")
    monkeypatch.setattr(A, "LISTEN", outdir)
    monkeypatch.setattr(A, "ROOT", presets.parent)
    monkeypatch.setattr(A, "find_sid", lambda n: corpus / n)
    shas = A.conversion_shas()
    staged = hashlib.sha256((outdir / "Tune_2.h2g.sng").read_bytes()).hexdigest()
    assert shas["Tune_2"] == staged
    assert A.audio_provenance("Tune_2", shas)[0] == "current"
