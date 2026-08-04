"""Regression test: Commando.sid must convert byte-for-byte identically to
the reference Commando.sng (produced by the original VB6 h2g.v1.2.exe).

Runs the conversion through the actual `h2g` CLI (subprocess), the same way a
user would, rather than calling convert() in-process -- this exercises file
I/O, argument parsing, and exit codes too, not just the conversion logic.
"""
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"


def _diff_report(actual: bytes, expected: bytes, max_shown: int = 20) -> str:
    lines = [
        f"length: actual={len(actual)} expected={len(expected)}",
    ]
    mismatches = [
        i for i in range(min(len(actual), len(expected)))
        if actual[i] != expected[i]
    ]
    lines.append(f"byte mismatches: {len(mismatches)}")
    for i in mismatches[:max_shown]:
        lines.append(f"  offset 0x{i:04X}: actual=0x{actual[i]:02X} expected=0x{expected[i]:02X}")
    if len(mismatches) > max_shown:
        lines.append(f"  ... and {len(mismatches) - max_shown} more")
    if len(actual) != len(expected):
        shorter, longer, tag = (
            (actual, expected, "expected has extra trailing bytes")
            if len(actual) < len(expected)
            else (expected, actual, "actual has extra trailing bytes")
        )
        extra = longer[len(shorter):]
        lines.append(f"{tag}: {extra[:64].hex(' ')}{' ...' if len(extra) > 64 else ''}")
    return "\n".join(lines)


def test_commando_cli_output_matches_reference(tmp_path):
    out_path = tmp_path / "Commando.sng"

    result = subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q"],
        cwd=str(PYTHON_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"h2g CLI failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    actual = out_path.read_bytes()
    expected = REFERENCE_SNG_PATH.read_bytes()

    assert actual == expected, "output .sng differs from reference:\n" + _diff_report(actual, expected)
