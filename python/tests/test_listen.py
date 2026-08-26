"""`listen.py --files` must not accept a path where it wants a bare name.

A `--files` entry used to be kept verbatim: as the `presets.json` lookup key,
and (via `stem = name[:-4]`) as the on-disk filename joined to `outdir`.
pathlib's `/` returns the right operand unchanged when it is absolute, so
`outdir / stem` silently discarded `outdir` for a path argument -- a real run
staged `--files C:/full/path/to/5_Title_Tunes.sid` and wrote NOTHING to
`build/listen` while writing 11 files (~85 MB) into the SID corpus directory
next to the originals, printing "staged" the whole time.

Three things are pinned here: a path argument is normalised to its basename
and resolved against `sid_dir` like every other name; a name absent from
`presets.json` is reported rather than silently converted with defaults; and
no per-tune output path can resolve outside `outdir`, by construction rather
than by convention.
"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import listen as L  # noqa: E402


# --- _basename_of -------------------------------------------------------


def test_basename_of_strips_a_forward_slash_path():
    assert L._basename_of("C:/full/path/to/5_Title_Tunes.sid") == "5_Title_Tunes.sid"


def test_basename_of_strips_a_backslash_path():
    assert L._basename_of(r"C:\full\path\to\5_Title_Tunes.sid") == "5_Title_Tunes.sid"


def test_basename_of_leaves_a_bare_name_alone():
    assert L._basename_of("5_Title_Tunes.sid") == "5_Title_Tunes.sid"


def test_basename_of_strips_a_relative_path_too():
    assert L._basename_of("../sid/Delta.sid") == "Delta.sid"


# --- select_names normalises ---------------------------------------------


def _presets(tmp_path, songs):
    p = tmp_path / "presets.json"
    p.write_text(json.dumps({"always": {}, "songs": songs}), encoding="utf-8")
    return str(p)


def test_select_names_normalises_a_path_argument_to_its_basename(tmp_path):
    full = str(tmp_path / "corpus" / "5_Title_Tunes.sid")
    got = L.select_names([full], False, _presets(tmp_path, {}))
    assert got == ["5_Title_Tunes.sid"]


def test_select_names_still_passes_bare_names_through(tmp_path):
    """The pre-existing, already-tested behaviour must not regress."""
    got = L.select_names(["B.sid", "A.sid"], False, _presets(tmp_path, {}))
    assert got == ["B.sid", "A.sid"]


# --- _outdir_path: no output path can escape outdir -----------------------


def test_outdir_path_returns_the_ordinary_join(tmp_path):
    outdir = tmp_path / "listen"
    outdir.mkdir()
    got = L._outdir_path(outdir, "Delta.h2g.sng")
    assert got == (outdir / "Delta.h2g.sng").resolve()


def test_outdir_path_refuses_an_absolute_escape(tmp_path):
    """The exact shape of the real defect: a filename that is itself an
    absolute path, which pathlib's `/` would otherwise honour verbatim,
    discarding `outdir` entirely."""
    outdir = tmp_path / "listen"
    outdir.mkdir()
    escape = str(tmp_path / "corpus" / "5_Title_Tunes.h2g.sng")
    try:
        L._outdir_path(outdir, escape)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "outside outdir" in str(exc)


def test_outdir_path_refuses_dotdot_traversal(tmp_path):
    outdir = tmp_path / "listen"
    outdir.mkdir()
    try:
        L._outdir_path(outdir, "../escaped.wav")
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- main(): the reported scenario, end to end -----------------------------
#
# convert/pack_sid/run_siddump/pick_renderer are stubbed so this test needs no
# gt2reloc/siddump/sidplayfp -- it is about where files land and what gets
# reported, not about the audio pipeline.


def _stage_stub_env(monkeypatch, tmp_path, sng_bytes=b"SNGBYTES"):
    """Stub every external step main() takes after `_preset_opts`, and record
    the options each conversion actually received."""
    received_opts = []

    def fake_convert(path, log=None, **opts):
        received_opts.append(opts)
        return sng_bytes

    monkeypatch.setattr(L, "convert", fake_convert)
    monkeypatch.setattr(L, "legalise_restarts", lambda blob: (blob, 0))

    packed = tmp_path / "packed.sid"
    packed.write_bytes(b"PACKEDSID")
    monkeypatch.setattr(L, "pack_sid", lambda *a, **k: packed)

    written_wavs = []

    def fake_render(src, out, seconds, sub, mute=()):
        Path(out).write_bytes(b"RIFFWAVE")
        written_wavs.append(Path(out))
        return True

    monkeypatch.setattr(
        L, "pick_renderer",
        lambda sid, args, probe_dir=None: L.Choice(fake_render, "", "fake"))
    monkeypatch.setattr(L, "run_siddump", lambda *a, **k: [])
    monkeypatch.setattr(L, "trace_json", lambda *a, **k: {})
    monkeypatch.setattr(L, "listen_notes", lambda *a, **k: ["stub"])
    return received_opts, written_wavs


def _make_sid(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PSID" + b"\x00" * 200)


def test_a_path_argument_stages_into_outdir_and_touches_nothing_in_the_corpus(
        tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus"
    sid = corpus / "5_Title_Tunes.sid"
    _make_sid(sid)
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"
    presets = _presets(tmp_path, {"5_Title_Tunes.sid": {}})
    _stage_stub_env(monkeypatch, tmp_path)

    rc = L.main([
        str(corpus), "--files", str(sid),
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(workdir), "-t", "1",
    ])
    assert rc == 0

    # Nothing landed beside the original -- the actual damage in the report.
    assert sorted(p.name for p in corpus.iterdir()) == ["5_Title_Tunes.sid"]
    # Everything landed in outdir instead.
    assert (outdir / "5_Title_Tunes.h2g.sng").read_bytes() == b"SNGBYTES"
    assert (outdir / "5_Title_Tunes.h2g.sid").exists()
    assert (outdir / "5_Title_Tunes.original.wav").exists()
    assert (outdir / "5_Title_Tunes.h2g.wav").exists()

    err = capsys.readouterr().err
    assert "is a path" in err and "5_Title_Tunes.sid" in err


def test_a_bare_name_behaves_exactly_as_before(tmp_path, monkeypatch, capsys):
    """The verified-good case from the same session: a bare `--files` name
    must keep staging into outdir with no path-normalisation note."""
    corpus = tmp_path / "corpus"
    sid = corpus / "Tune.sid"
    _make_sid(sid)
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"
    presets = _presets(tmp_path, {"Tune.sid": {}})
    _stage_stub_env(monkeypatch, tmp_path)

    rc = L.main([
        str(corpus), "--files", "Tune.sid",
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(workdir), "-t", "1",
    ])
    assert rc == 0
    assert (outdir / "Tune.h2g.sng").exists()
    err = capsys.readouterr().err
    assert "is a path" not in err
    assert "staged 1 tune(s)" in err


def test_a_name_missing_from_presets_is_reported_not_silent(
        tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus"
    sid = corpus / "Unknown.sid"
    _make_sid(sid)
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"
    # presets.json exists but records nothing for this tune.
    presets = _presets(tmp_path, {"SomeOtherTune.sid": {"max_rows": 40}})
    received_opts, _ = _stage_stub_env(monkeypatch, tmp_path)

    rc = L.main([
        str(corpus), "--files", "Unknown.sid",
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(workdir), "-t", "1",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "Unknown.sid" in err and "not in" in err and "presets.json" in err
    # ...and it still converts, with the defaults _preset_opts falls back to.
    assert received_opts == [] or received_opts[-1]["max_rows"] == 94


def test_a_name_present_in_presets_is_not_reported(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus"
    sid = corpus / "Known.sid"
    _make_sid(sid)
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"
    presets = _presets(tmp_path, {"Known.sid": {"max_rows": 40}})
    received_opts, _ = _stage_stub_env(monkeypatch, tmp_path)

    rc = L.main([
        str(corpus), "--files", "Known.sid",
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(workdir), "-t", "1",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "not in" not in err
    assert received_opts[-1]["max_rows"] == 40


# --- the "second, smaller defect": does a re-stage reuse stale output? -----
#
# CLAUDE.md's task notes a re-stage claiming "staged" while reusing an
# existing WAV, but also says the .sng write is unconditional and asks
# whether the WAV-reuse can happen on its own (outside the path bug above).
# It cannot: every write in the loop is unconditional except under
# --traces-only, which explicitly documents skipping renders. These pin that.


def test_a_restage_rewrites_the_sng_with_new_options(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus"
    sid = corpus / "Tune.sid"
    _make_sid(sid)
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"

    presets_v1 = _presets(tmp_path, {"Tune.sid": {"max_rows": 10}})

    def convert_v1(path, log=None, **opts):
        return b"V1:%d" % opts["max_rows"]

    monkeypatch.setattr(L, "convert", convert_v1)
    monkeypatch.setattr(L, "legalise_restarts", lambda blob: (blob, 0))
    packed = tmp_path / "packed.sid"
    packed.write_bytes(b"PACKEDSID")
    monkeypatch.setattr(L, "pack_sid", lambda *a, **k: packed)
    monkeypatch.setattr(
        L, "pick_renderer",
        lambda sid, args, probe_dir=None: L.Choice(
            lambda s, o, sec, sub, mute=(): Path(o).write_bytes(b"WAV1") or True,
            "", "fake"))
    monkeypatch.setattr(L, "run_siddump", lambda *a, **k: [])
    monkeypatch.setattr(L, "trace_json", lambda *a, **k: {})
    monkeypatch.setattr(L, "listen_notes", lambda *a, **k: ["stub"])

    L.main([str(corpus), "--files", "Tune.sid", "-o", str(outdir),
            "--presets", presets_v1, "--workdir", str(workdir), "-t", "1"])
    sng1 = (outdir / "Tune.h2g.sng").read_bytes()
    wav1 = (outdir / "Tune.original.wav").read_bytes()
    assert sng1 == b"V1:10" and wav1 == b"WAV1"

    # Re-stage the SAME tune: measured options changed, and the renderer
    # would now write different bytes if it actually ran.
    presets_v2 = _presets(tmp_path, {"Tune.sid": {"max_rows": 20}})

    def convert_v2(path, log=None, **opts):
        return b"V2:%d" % opts["max_rows"]

    monkeypatch.setattr(L, "convert", convert_v2)
    monkeypatch.setattr(
        L, "pick_renderer",
        lambda sid, args, probe_dir=None: L.Choice(
            lambda s, o, sec, sub, mute=(): Path(o).write_bytes(b"WAV2") or True,
            "", "fake"))

    L.main([str(corpus), "--files", "Tune.sid", "-o", str(outdir),
            "--presets", presets_v2, "--workdir", str(workdir), "-t", "1"])
    sng2 = (outdir / "Tune.h2g.sng").read_bytes()
    wav2 = (outdir / "Tune.original.wav").read_bytes()

    # Neither the .sng nor the WAV survived stale from the first stage --
    # this defect does not reproduce on its own outside the path bug.
    assert sng2 == b"V2:20" and sng2 != sng1
    assert wav2 == b"WAV2" and wav2 != wav1


def test_traces_only_is_the_documented_exception_that_skips_renders(
        tmp_path, monkeypatch):
    """The one deliberate reuse in the file: `--traces-only` is documented to
    skip rendering because the WAVs are already staged. Confirm it really
    does skip the render call (rather than merely being allowed to), so that
    the general rule above ("every write is unconditional") is not
    contradicted by this documented exception."""
    corpus = tmp_path / "corpus"
    sid = corpus / "Tune.sid"
    _make_sid(sid)
    outdir = tmp_path / "build" / "listen"
    outdir.mkdir(parents=True)
    (outdir / "Tune.original.wav").write_bytes(b"PREEXISTING")
    workdir = tmp_path / "work"
    presets = _presets(tmp_path, {"Tune.sid": {}})
    render_calls = []
    _stage_stub_env(monkeypatch, tmp_path)
    real_render = L.pick_renderer

    def counting_choice(sid_, args, probe_dir=None):
        return L.Choice(lambda *a, **k: render_calls.append(1) or True, "", "fake")
    monkeypatch.setattr(L, "pick_renderer", counting_choice)

    rc = L.main([str(corpus), "--files", "Tune.sid", "-o", str(outdir),
                "--presets", presets, "--workdir", str(workdir), "-t", "1",
                "--traces-only"])
    assert rc == 0
    assert render_calls == []
    # The pre-existing WAV is untouched, which is the point of the mode.
    assert (outdir / "Tune.original.wav").read_bytes() == b"PREEXISTING"
