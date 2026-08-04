"""Output format selection (--format gts2 | gts5).

GoatTracker 2.77 accepts both (src/gsong.c:189 for GTS3/4/5, :249 for GTS2),
but its *legacy* GTS2 import path contains a buffer overrun that the modern
path does not -- see goatwriter.FORMAT_GTS5 for the analysis. These tests pin
the structural difference between the two.
"""
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"

GT_MAX_TABLES = 4       # MAX_TABLES in gcommon.h
GTS2_TABLES = 3         # the GTS2 loader reads MAX_TABLES-1


def _run(out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _parse(blob, ntables):
    """Walk a .sng the way gsong.c's loader does, for a given table count."""
    magic = blob[:4]
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    tracks = []
    for _ in range(subtunes):
        for _c in range(3):
            length = blob[pos]; pos += 1
            tracks.append(blob[pos:pos + length + 1]); pos += length + 1
    ninstr = blob[pos]; pos += 1
    instr = []
    for _ in range(ninstr):
        instr.append(blob[pos:pos + 9]); pos += 9 + 16
    tables = []
    for _ in range(ntables):
        tlen = blob[pos]; pos += 1
        tables.append((blob[pos:pos + tlen], blob[pos + tlen:pos + 2 * tlen]))
        pos += 2 * tlen
    npatt = blob[pos]; pos += 1
    patterns = []
    for _ in range(npatt):
        rows = blob[pos]; pos += 1
        patterns.append(blob[pos:pos + rows * 4]); pos += rows * 4
    assert pos == len(blob), f"trailing data: parsed {pos} of {len(blob)}"
    return dict(magic=magic, subtunes=subtunes, tracks=tracks, instr=instr,
                tables=tables, patterns=patterns)


def test_default_is_gts2_and_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()
    assert out.read_bytes()[:4] == b"GTS2"


def test_gts5_magic_and_fourth_table(tmp_path):
    out = tmp_path / "g5.sng"
    assert _run(out, "--format", "gts5").returncode == 0
    s = _parse(out.read_bytes(), GT_MAX_TABLES)
    assert s["magic"] == b"GTS5"
    assert len(s["tables"]) == GT_MAX_TABLES
    # The added table is the speed table, and it is empty: every instrument this
    # writer emits carries ptr[STBL] == 0.
    ltable, rtable = s["tables"][3]
    assert len(ltable) == 0 and len(rtable) == 0
    for b in s["instr"]:
        assert b[5] == 0, "ptr[STBL] must be 0 while the speed table is empty"


def test_gts5_differs_from_gts2_only_by_magic_and_speed_table(tmp_path):
    g2, g5 = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(g2).returncode == 0
    assert _run(g5, "--format", "gts5").returncode == 0
    b2, b5 = g2.read_bytes(), g5.read_bytes()

    assert len(b5) == len(b2) + 1, "GTS5 adds exactly one byte (empty 4th table)"

    a = _parse(b2, GTS2_TABLES)
    b = _parse(b5, GT_MAX_TABLES)
    assert a["subtunes"] == b["subtunes"]
    assert a["tracks"] == b["tracks"]
    assert a["instr"] == b["instr"]
    assert a["patterns"] == b["patterns"]
    assert a["tables"][:3] == b["tables"][:3]


def test_gts5_composes_with_other_options(tmp_path):
    out = tmp_path / "c.sng"
    r = _run(out, "--format", "gts5", "--max-rows", "128", "--terminate-patterns")
    assert r.returncode == 0, r.stderr
    s = _parse(out.read_bytes(), GT_MAX_TABLES)
    assert s["magic"] == b"GTS5"
    # pattern[MAX_PATT][MAX_PATTROWS*4+4] -- 516 bytes, i.e. 128 data rows plus
    # one slot for the ENDPATT sentinel. --terminate-patterns fills that slot,
    # so 129 rows is the legal maximum, not an overflow.
    assert max(len(p) for p in s["patterns"]) <= 128 * 4 + 4


@pytest.mark.parametrize("bad", ["gts3", "GTS2", "sng", ""])
def test_unknown_format_rejected(tmp_path, bad):
    out = tmp_path / "x.sng"
    assert _run(out, "--format", bad).returncode != 0
    assert not out.exists()
