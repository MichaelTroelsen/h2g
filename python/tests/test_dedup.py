"""Pattern de-duplication (--dedup-patterns).

Sharing one Goattracker pattern between byte-identical slices. The risk is not
that it fails to shrink the file -- it is that it changes what the song plays,
so these tests reconstruct each track's full row stream and assert it is
identical with and without dedup.
"""
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"

REPEAT, LOOPSONG = 0xD0, 0xFF


def _run(out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _parse(blob, ntables=3):
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    tracks = []
    for _ in range(subtunes):
        for _c in range(3):
            length = blob[pos]; pos += 1
            tracks.append(list(blob[pos:pos + length + 1])); pos += length + 1
    ninstr = blob[pos]; pos += 1
    instr = blob[pos:pos + ninstr * 25]; pos += ninstr * 25
    for _ in range(ntables):
        tlen = blob[pos]; pos += 1; pos += 2 * tlen
    npatt = blob[pos]; pos += 1
    patterns = []
    for _ in range(npatt):
        rows = blob[pos]; pos += 1
        patterns.append(bytes(blob[pos:pos + rows * 4])); pos += rows * 4
    assert pos == len(blob), f"parsed {pos} of {len(blob)}"
    return dict(subtunes=subtunes, tracks=tracks, instr=instr, patterns=patterns)


def _row_stream(song):
    """Each track expanded into the actual bytes it would play.

    This is the invariant dedup must preserve: pattern *numbers* may change,
    pattern *content in playback order* may not.
    """
    out = []
    for t in song["tracks"]:
        rows = []
        expect_operand = False
        for b in t:
            if expect_operand:
                expect_operand = False
                continue
            if b == LOOPSONG:
                expect_operand = True
                continue
            if b >= REPEAT:
                continue
            rows.append(song["patterns"][b])
        out.append(rows)
    return out


def test_default_is_off_and_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_dedup_reduces_pattern_count(tmp_path):
    plain, dedup = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(plain).returncode == 0
    assert _run(dedup, "--dedup-patterns").returncode == 0
    a, b = _parse(plain.read_bytes()), _parse(dedup.read_bytes())
    assert len(b["patterns"]) < len(a["patterns"]), "no duplicates removed"
    assert len(dedup.read_bytes()) < len(plain.read_bytes())


def test_dedup_preserves_the_music(tmp_path):
    plain, dedup = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(plain).returncode == 0
    assert _run(dedup, "--dedup-patterns").returncode == 0
    a, b = _parse(plain.read_bytes()), _parse(dedup.read_bytes())

    assert a["subtunes"] == b["subtunes"]
    assert a["instr"] == b["instr"]
    # Same number of orderlist entries -- dedup renumbers, never removes.
    assert [len(t) for t in a["tracks"]] == [len(t) for t in b["tracks"]]
    # And the same pattern content in the same playback order.
    assert _row_stream(a) == _row_stream(b)


def test_deduped_patterns_are_all_distinct(tmp_path):
    out = tmp_path / "b.sng"
    assert _run(out, "--dedup-patterns").returncode == 0
    pats = _parse(out.read_bytes())["patterns"]
    assert len(set(pats)) == len(pats), "duplicates survived de-duplication"


def test_composes_with_other_options(tmp_path):
    out = tmp_path / "c.sng"
    r = _run(out, "--dedup-patterns", "--max-rows", "128",
             "--terminate-patterns", "--format", "gts5")
    assert r.returncode == 0, r.stderr
    song = _parse(out.read_bytes(), ntables=4)
    assert len(set(song["patterns"])) == len(song["patterns"])
    assert max(len(p) for p in song["patterns"]) <= 128 * 4 + 4
