"""Explicit pattern termination (--terminate-patterns).

Goattracker does not trust a pattern's stored length: countpatternlengths()
(gsong.c) rescans the note column for ENDPATT and overwrites pattlen. Its own
saver therefore always emits pattlen+1 rows -- data plus one ENDPATT row
(gsong.c:116-118).

H2G's sliced patterns omit that terminator on every slice but the last, so
their length is whatever clearpattern() left behind:

    memset(pattern[p], 0, MAX_PATTROWS*4);
    for (c = 0; c < defaultpatternlength; c++) pattern[p][c*4] = REST;
    for (c = defaultpatternlength; c <= MAX_PATTROWS; c++) pattern[p][c*4] = ENDPATT;

with defaultpatternlength defaulting to 64. Slicing at 94 works only because
94 > 64. These tests pin the fix and model the loader to show what it prevents.
"""
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"

ENDPATT = 0xFF
REST = 0xBD
GT_MAX_PATTROWS = 128


def _run(out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _patterns(blob: bytes) -> list[bytes]:
    """Extract the pattern section, walking the file as gsong.c's loader does."""
    assert blob[:4] == b"GTS2"
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    for _ in range(subtunes):
        for _chn in range(3):
            pos += 1 + blob[pos] + 1          # length byte, then length+1 bytes
    pos += 1 + blob[pos] * (9 + 16)           # instrument count, then records
    for _ in range(3):                        # wave, pulse, filter tables
        tlen = blob[pos]; pos += 1 + 2 * tlen
    count = blob[pos]; pos += 1
    out = []
    for _ in range(count):
        rows = blob[pos]; pos += 1
        out.append(blob[pos:pos + rows * 4]); pos += rows * 4
    assert pos == len(blob), f"trailing data: parsed {pos} of {len(blob)}"
    return out


def _loaded_length(pattern: bytes, default_pattern_length: int = 64) -> int:
    """What Goattracker would compute as this pattern's length.

    Models clearpattern() + countpatternlengths(): the loader's pre-fill is
    visible wherever the loaded pattern does not reach.
    """
    rows = [pattern[i * 4] for i in range(len(pattern) // 4)]
    for d in range(GT_MAX_PATTROWS + 1):
        note = rows[d] if d < len(rows) else (
            REST if d < default_pattern_length else ENDPATT)
        if note == ENDPATT:
            return d
    return GT_MAX_PATTROWS


def test_off_by_default_output_unchanged(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_every_pattern_ends_with_endpatt(tmp_path):
    out = tmp_path / "t.sng"
    assert _run(out, "--terminate-patterns").returncode == 0
    pats = _patterns(out.read_bytes())
    assert pats, "no patterns emitted"
    for i, p in enumerate(pats):
        assert len(p) >= 4, f"pattern {i} is empty"
        assert p[-4] == ENDPATT, f"pattern {i} does not end with ENDPATT"


def test_unterminated_patterns_break_under_a_larger_loader_default(tmp_path):
    """The concrete failure --terminate-patterns prevents.

    With defaultpatternlength raised above the slice length, an unterminated
    slice inherits REST rows from the pre-fill and reports the wrong length.
    A terminated slice is immune because it carries its own sentinel.
    """
    plain, term = tmp_path / "p.sng", tmp_path / "t.sng"
    assert _run(plain).returncode == 0
    assert _run(term, "--terminate-patterns").returncode == 0

    plain_pats, term_pats = _patterns(plain.read_bytes()), _patterns(term.read_bytes())

    # Sanity: the fixture really does contain sliced (94-row) patterns.
    sliced = [i for i, p in enumerate(plain_pats) if len(p) // 4 == 94]
    assert sliced, "fixture has no full-length slices to exercise"

    # At the stock default (64) both agree -- which is why this has gone unnoticed.
    for i in sliced:
        assert _loaded_length(plain_pats[i], 64) == 94

    # At 100, the unterminated slices silently grow; the terminated ones do not.
    assert any(_loaded_length(plain_pats[i], 100) != 94 for i in sliced), \
        "expected unterminated slices to mis-report under a larger loader default"
    for i in sliced:
        assert _loaded_length(term_pats[i], 100) == 94


def test_terminated_patterns_stay_within_goattracker_limits(tmp_path):
    """Termination adds a row; at max-rows 128 that is exactly the array bound."""
    out = tmp_path / "t128.sng"
    assert _run(out, "--terminate-patterns", "--max-rows", "128").returncode == 0
    for p in _patterns(out.read_bytes()):
        rows = len(p) // 4
        assert rows <= GT_MAX_PATTROWS + 1, f"{rows} rows exceeds the pattern array"
        assert _loaded_length(p) <= GT_MAX_PATTROWS
