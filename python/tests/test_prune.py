"""Unreferenced-pattern removal (--prune-patterns).

The pattern table's size is inferred from the gap between the SID's pattern
LO and HI address tables, so it counts entries the song may never play. Those
are decoded and written anyway, which is pure weight -- and can push a tune
past Goattracker's 208-pattern limit for music it does not contain.

Pruning cannot change playback (a pattern no orderlist names is unreachable),
but it does renumber the survivors, so these tests assert the reconstructed
row stream is identical with and without it -- the same invariant test_dedup
uses.
"""
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"
# Repo-local, and has exactly one pattern no track references.
UNUSED_SID_PATH = REPO_ROOT / "arkiv" / "Bump_Set_Spike.sid"

REPEAT, LOOPSONG = 0xD0, 0xFF


def _run(sid, out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(sid), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _parse(blob, ntables=3):
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    tracks = []
    for _ in range(subtunes * 3):
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
    """Each track expanded into what it would actually play.

    Commands and dangling references are kept as markers rather than dropped,
    so a prune that changed an orderlist's shape could not hide behind them.
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
                rows.append(("LOOP",))
                continue
            if b >= REPEAT:
                rows.append(("CMD", b))
                continue
            rows.append(song["patterns"][b] if b < len(song["patterns"])
                        else ("DANGLING", b))
        out.append(rows)
    return out


# --- referenced_patterns: the orderlist walk ------------------------------

def test_referenced_patterns_skips_commands_and_restart_operand():
    from h2g.patterns import referenced_patterns
    # $D0/$E5/$F2 are repeat/transpose commands (no operand); $FF is followed
    # by a restart position, here 3 -- a small number that must NOT be read as
    # a pattern reference.
    assert referenced_patterns([[1, 0xD0, 2, 0xE5, 0xF2, 5, 0xFF, 3]]) == {1, 2, 5}


def test_referenced_patterns_unions_all_tracks():
    from h2g.patterns import referenced_patterns
    assert referenced_patterns([[1, 2], [2, 7], []]) == {1, 2, 7}


# --- end to end ------------------------------------------------------------

def test_default_is_off_and_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(SID_PATH, out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_noop_when_every_pattern_is_played(tmp_path):
    # Commando's tracks reference all 45 patterns its table holds, so pruning
    # has nothing to remove and must not perturb the bytes.
    out = tmp_path / "p.sng"
    assert _run(SID_PATH, out, "--prune-patterns").returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_prune_removes_unreferenced_patterns(tmp_path):
    plain, pruned = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(UNUSED_SID_PATH, plain).returncode == 0
    assert _run(UNUSED_SID_PATH, pruned, "--prune-patterns").returncode == 0
    a, b = _parse(plain.read_bytes()), _parse(pruned.read_bytes())
    assert len(b["patterns"]) < len(a["patterns"]), "nothing pruned"
    assert len(pruned.read_bytes()) < len(plain.read_bytes())


def test_prune_preserves_the_music(tmp_path):
    plain, pruned = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(UNUSED_SID_PATH, plain).returncode == 0
    assert _run(UNUSED_SID_PATH, pruned, "--prune-patterns").returncode == 0
    a, b = _parse(plain.read_bytes()), _parse(pruned.read_bytes())

    assert a["subtunes"] == b["subtunes"]
    assert a["instr"] == b["instr"]
    # Pruning renumbers orderlist entries but never adds or removes any.
    assert [len(t) for t in a["tracks"]] == [len(t) for t in b["tracks"]]
    assert _row_stream(a) == _row_stream(b)


def test_every_surviving_pattern_is_referenced(tmp_path):
    from h2g.patterns import referenced_patterns
    out = tmp_path / "b.sng"
    assert _run(UNUSED_SID_PATH, out, "--prune-patterns").returncode == 0
    song = _parse(out.read_bytes())
    used = referenced_patterns(song["tracks"])
    assert set(range(len(song["patterns"]))) <= used, "an unplayed pattern survived"


def test_composes_with_other_options(tmp_path):
    out = tmp_path / "c.sng"
    r = _run(UNUSED_SID_PATH, out, "--prune-patterns", "--dedup-patterns",
             "--max-rows", "128", "--terminate-patterns", "--format", "gts5")
    assert r.returncode == 0, r.stderr
    song = _parse(out.read_bytes(), ntables=4)
    assert len(set(song["patterns"])) == len(song["patterns"])
    assert max(len(p) for p in song["patterns"]) <= 128 * 4 + 4
