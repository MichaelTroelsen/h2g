"""Pattern-slicing length (--max-rows).

94 is the original VB6 tool's slice length and the default; 128 is
Goattracker's real MAX_PATTROWS since v2.32 (src/gcommon.h). Raising it
produces fewer, longer patterns and shorter orderlists.

These tests parse the emitted .sng rather than just comparing sizes, so a
structurally broken file fails here instead of in Goattracker.
"""
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"

GT_MAX_PATTROWS = 128  # gcommon.h
GT_MAX_PATT = 208
GT_MAX_SONGLEN = 254


def _run(out_path, *extra):
    result = subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )
    return result


def _parse_sng(blob: bytes) -> dict:
    """Walk a .sng exactly as Goattracker's gsong.c loader does."""
    assert blob[:4] == b"GTS2", "bad magic"
    pos = 4 + 32 * 3                      # name / author / released

    subtunes = blob[pos]; pos += 1
    tracks = []
    for _ in range(subtunes):
        for _chn in range(3):             # MAX_CHN
            length = blob[pos]; pos += 1
            loadsize = length + 1         # loader reads length+1 bytes
            tracks.append(blob[pos:pos + loadsize])
            pos += loadsize

    instr_count = blob[pos]; pos += 1
    pos += instr_count * (9 + 16)         # 9 data bytes + 16-byte name

    tables = []
    for _ in range(3):                    # wave, pulse, filter
        tlen = blob[pos]; pos += 1
        tables.append((blob[pos:pos + tlen], blob[pos + tlen:pos + 2 * tlen]))
        pos += 2 * tlen

    patt_count = blob[pos]; pos += 1
    patterns = []
    for _ in range(patt_count):
        rows = blob[pos]; pos += 1
        patterns.append(blob[pos:pos + rows * 4])
        pos += rows * 4

    assert pos == len(blob), f"trailing data: parsed {pos} of {len(blob)} bytes"
    return {"subtunes": subtunes, "tracks": tracks, "instruments": instr_count,
            "tables": tables, "patterns": patterns,
            "rows": [len(p) // 4 for p in patterns]}


def test_default_is_94_and_still_byte_exact(tmp_path):
    """Omitting --max-rows must not change the fixture output."""
    out = tmp_path / "default.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_explicit_94_matches_default(tmp_path):
    out = tmp_path / "r94.sng"
    assert _run(out, "--max-rows", "94").returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_128_rows_is_structurally_valid_and_more_compact(tmp_path):
    out94, out128 = tmp_path / "r94.sng", tmp_path / "r128.sng"
    assert _run(out94, "--max-rows", "94").returncode == 0
    assert _run(out128, "--max-rows", "128").returncode == 0

    a, b = _parse_sng(out94.read_bytes()), _parse_sng(out128.read_bytes())

    # Raising the slice length must not change the song's shape.
    assert a["subtunes"] == b["subtunes"]
    assert a["instruments"] == b["instruments"]

    # Fewer patterns, and every one within Goattracker's limits.
    assert len(b["patterns"]) < len(a["patterns"])
    assert max(b["rows"]) <= GT_MAX_PATTROWS
    assert len(b["patterns"]) <= GT_MAX_PATT
    for t in b["tracks"]:
        assert len(t) <= GT_MAX_SONGLEN

    # Shorter orderlists: slicing a pattern into N pieces costs N entries.
    assert sum(len(t) for t in b["tracks"]) <= sum(len(t) for t in a["tracks"])


def test_94_output_respects_its_own_limit(tmp_path):
    out = tmp_path / "r94.sng"
    assert _run(out, "--max-rows", "94").returncode == 0
    assert max(_parse_sng(out.read_bytes())["rows"]) <= 94


@pytest.mark.parametrize("bad", ["0", "129", "-1"])
def test_out_of_range_is_rejected(tmp_path, bad):
    result = _run(tmp_path / "bad.sng", "--max-rows", bad)
    assert result.returncode != 0
    assert not (tmp_path / "bad.sng").exists()
