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
