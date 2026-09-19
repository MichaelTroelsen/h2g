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


def test_preset_misses_are_counted_at_the_end_of_the_run(
        tmp_path, monkeypatch, capsys):
    # warnings.warn in _preset_opts deduplicates per call site, so a run that
    # misses on every name prints one warning; listen.py's own count is what
    # says HOW MANY fell through, and says it loudly when it was all of them.
    corpus = tmp_path / "corpus"
    for n in ("Unknown_A.sid", "Unknown_B.sid"):
        _make_sid(corpus / n)
    outdir = tmp_path / "build" / "listen"
    presets = _presets(tmp_path, {"SomeOtherTune.sid": {"max_rows": 40}})
    _stage_stub_env(monkeypatch, tmp_path)
    rc = L.main([
        str(corpus), "--files", "Unknown_A.sid", "Unknown_B.sid",
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(tmp_path / "work"), "-t", "1",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "2 of 2 staged tune(s) not in presets.json" in err
    assert "Unknown_A.sid, Unknown_B.sid" in err
    assert "EVERY staged name missed" in err


def test_a_partial_preset_miss_is_counted_but_not_shouted(
        tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus"
    for n in ("Known.sid", "Unknown.sid"):
        _make_sid(corpus / n)
    outdir = tmp_path / "build" / "listen"
    presets = _presets(tmp_path, {"Known.sid": {"max_rows": 40}})
    _stage_stub_env(monkeypatch, tmp_path)
    rc = L.main([
        str(corpus), "--files", "Known.sid", "Unknown.sid",
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(tmp_path / "work"), "-t", "1",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "1 of 2 staged tune(s) not in presets.json" in err
    assert "Unknown.sid" in err.split("staged tune(s) not in")[1]
    assert "EVERY staged name missed" not in err


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


# --- the trace of our side runs at the rate it was packed for ---------------
#
# `pack_sid(..., multiplier)` is gt2reloc's -S: the packed player wants that
# many calls per frame. siddump ignores the CIA stub the flag prepends, so the
# trace of our side has to be told the same number again as siddump-rt's -m.
# listen.py packed at -S{multiplier} and traced with `calls` left at its
# default of 1 until v0.5.486, so on a -S3 file our side was dumped at a third
# of its speed for the whole window and every derived staging note compared
# 180 s of the original against 60 s of ours. Measured on Saboteur_II: ties
# 1631 against the original's 8046 with `calls` defaulted, 7386 with it
# passed; attacks 920 against 2566, then 2564 -- and a "No legato" note that
# exists only at the wrong rate.


def _stage_one(monkeypatch, tmp_path, songs):
    corpus = tmp_path / "corpus"
    _make_sid(corpus / "Tune.sid")
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"
    presets = _presets(tmp_path, songs)
    _stage_stub_env(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(L, "run_siddump",
                        lambda *a, **k: calls.append((a, k)) or [])
    rc = L.main([str(corpus), "--files", "Tune.sid", "-o", str(outdir),
                "--presets", presets, "--workdir", str(workdir), "-t", "1",
                "--traces-only"])
    assert rc == 0
    assert len(calls) == 2, calls
    return calls


def test_our_side_is_traced_at_the_multiplier_it_was_packed_at(
        tmp_path, monkeypatch):
    (orig_a, orig_k), (ours_a, ours_k) = _stage_one(
        monkeypatch, tmp_path, {"Tune.sid": {"multiplier": 3}})
    # The original is the corpus file, traced at one call per frame: the
    # multiplier belongs to our side only.
    assert Path(orig_a[0]).name == "Tune.sid"
    assert orig_k.get("calls", 1) == 1
    # Ours is the packed .sid, traced at the rate gt2reloc packed it for.
    assert Path(ours_a[0]).name == "Tune.h2g.sid"
    assert ours_k["calls"] == 3


def test_a_single_speed_file_is_traced_at_one_call_per_frame(
        tmp_path, monkeypatch):
    """`-m1` is not `-m` omitted: run_siddump appends the flag only above 1,
    so a file without a multiplier must arrive as exactly 1 and never as a
    None that `calls > 1` would raise on."""
    (_, orig_k), (_, ours_k) = _stage_one(
        monkeypatch, tmp_path, {"Tune.sid": {}})
    assert orig_k.get("calls", 1) == 1
    assert ours_k["calls"] == 1


# --- render_window: a row's own traced window can outrun `-t` --------------
#
# fidelity_queue_and_listen_read_window_seconds: fidelity.traced_window(row)
# is the canonical reader; render_window only honours its two genuine
# widen/shorten signals (window_seconds, original_ends), never its bare
# `seconds` fallback -- see render_window's docstring for why. Pinned with a
# real corpus shape: Rock_Tells_the_Tale (build/fidelity.json, v0.5.489)
# carries window_seconds 382 against a 180 s run with no original_ends.


def test_render_window_follows_a_widened_window():
    row = {"file": "Rock_Tells_the_Tale.sid", "seconds": 180, "window_seconds": 382}
    assert L.render_window(row, 30) == 382


def test_render_window_follows_a_shortened_window():
    row = {"file": "Action_Biker.sid", "seconds": 180, "window_seconds": 61,
           "original_ends": 61}
    assert L.render_window(row, 30) == 61


def test_render_window_ignores_the_bare_seconds_fallback():
    """A row with no widen/shorten signal at all -- just the run's own `-t`
    echoed into `seconds` -- must not override an explicit `-t` on THIS
    invocation of listen.py."""
    row = {"file": "Ordinary.sid", "seconds": 180}
    assert L.render_window(row, 30) == 30


def test_render_window_falls_back_for_a_bare_row():
    """`--files`/`--all` without a matching fidelity row stage `{"file": f}`
    -- no seconds key at all -- and must render at the requested `-t`
    exactly as before this change."""
    assert L.render_window({"file": "Unknown.sid"}, 30) == 30


def test_our_side_renders_for_the_traced_window_when_it_widened(
        tmp_path, monkeypatch):
    """End to end: main() must pass the row's traced window, not `-t`, to
    both the renderer and the siddump trace, and note it in LISTENING.md."""
    corpus = tmp_path / "corpus"
    _make_sid(corpus / "Tune.sid")
    outdir = tmp_path / "build" / "listen"
    workdir = tmp_path / "work"
    presets = _presets(tmp_path, {"Tune.sid": {}})
    received_opts, written_wavs = _stage_stub_env(monkeypatch, tmp_path)
    seconds_seen = []

    def fake_render(src, out, seconds, sub, mute=()):
        seconds_seen.append(seconds)
        Path(out).write_bytes(b"RIFFWAVE")
        return True
    monkeypatch.setattr(
        L, "pick_renderer",
        lambda sid, args, probe_dir=None: L.Choice(fake_render, "", "fake"))

    dump_calls = []
    monkeypatch.setattr(
        L, "run_siddump",
        lambda *a, **k: dump_calls.append(a[1]) or [])

    fidelity_json = tmp_path / "fidelity.json"
    fidelity_json.write_text(json.dumps([
        {"file": "Tune.sid", "seconds": 30, "window_seconds": 90}]),
        encoding="utf-8")

    rc = L.main([
        str(corpus), "--from-json", str(fidelity_json),
        "--files", "Tune.sid",
        "-o", str(outdir), "--presets", presets,
        "--workdir", str(workdir), "-t", "30",
    ])
    assert rc == 0
    assert seconds_seen == [90, 90]           # original then ours
    assert dump_calls == [90, 90]
    text = (outdir / "LISTENING.md").read_text(encoding="utf-8")
    assert "Rendered for **90 s**, not the requested `-t 30`" in text


# --- render_sidplayfp pins the power-on delay -----------------------------
#
# sidplayfp's `--delay=<num>` ("Simulate C64 power on delay as number of CPU
# cycles. If greater than 8191 the delay will be random. This is the
# default." -- sidplayfp.txt) was NOT passed through v0.5.491, so every render
# of the same bytes started the C64 a random number of cycles into its own
# timeline. Measured on Devils_Galop the day the flag landed: two flagless
# 60 s renders differed by 88 bytes, aligned 4 hops apart and read 0.0186 on
# `sound_calibrate.rerender_movements` (the 0.0183 re-render floor
# docs/SOUND-CALIBRATION.md adopted at v0.5.491, which hid Human_Race,
# Rasputin and Spellbound); the same two under `--delay=0` are the same
# length and read 0.0000. The two tests below are what keeps the flag on the
# command line: a renderer refactor that drops it changes no test's
# behaviour and no cache key, only the floor under every score.


def _captured_sidplayfp_argv(monkeypatch, tmp_path):
    """Run `render_sidplayfp` with subprocess.run replaced and return argv."""
    seen = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        Path(argv[-2][2:]).write_bytes(b"\0" * (L.EMPTY_WAV + 1))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(L.subprocess, "run", fake_run)
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID")
    ok = L.render_sidplayfp(sid, tmp_path / "out.wav", 7, 2,
                            exe=str(tmp_path / "sidplayfp.exe"))
    assert ok and len(seen) == 1
    return seen[0]


def test_render_sidplayfp_passes_a_fixed_power_on_delay(monkeypatch, tmp_path):
    """SABOTAGE TARGET: drop the `--delay=` element from the command line in
    `render_sidplayfp` and this fails on the `delay` lookup."""
    argv = _captured_sidplayfp_argv(monkeypatch, tmp_path)
    delay = [a for a in argv if a.startswith("--delay=")]
    assert delay == [f"--delay={L.SIDPLAYFP_POWER_ON_DELAY}"], argv
    # the rest of the line is unchanged: format, fade-off, 1-based subtune
    assert argv[1:6] == ["-t7", "-f44100", "-p16", "-m", "-fo0"]
    assert "-o3" in argv and argv[-1].endswith("Tune.sid")


def test_sidplayfp_power_on_delay_is_inside_the_fixed_range():
    """SABOTAGE TARGET: set `SIDPLAYFP_POWER_ON_DELAY` to 8192 -- sidplayfp
    documents any value above 8191 as "random", i.e. the flag's absence --
    and this fails. Measured: `--delay=8191` renders twice to the same
    samples (max 3 LSB of dither apart), `--delay=8192` to samples 21739
    apart, on Devils_Galop's first 3 s."""
    d = L.SIDPLAYFP_POWER_ON_DELAY
    assert isinstance(d, int) and not isinstance(d, bool)
    assert 0 <= d <= 8191, "above 8191 sidplayfp draws the delay at random"
