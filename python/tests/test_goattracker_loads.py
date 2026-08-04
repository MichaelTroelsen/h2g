"""Validate our .sng output against GoatTracker's *real* loader.

Every other test in this suite checks our output against our own understanding
of the format. This one hands the file to GoatTracker's own code and asks
whether it accepts it.

`sngspli2` is GoatTracker's song splitter. It is the only GoatTracker tool that
builds without SDL (`sngspli2.o` + `bme_end.o`), so it is the one piece of the
real toolchain usable in an automated test. It calls the same `loadsong()` in
gsong.c that the editor uses, so a file it loads is a file GoatTracker loads.

Build it with:
    cd goattracker2-sf/src
    make -f makefile.win CFLAGS="-Ibme -Iasm -I<sdl-headers> -O3" \\
        ../win32/sngspli2.exe

Point the tests at it with H2G_SNGSPLI2=<path to sngspli2.exe>; they skip when
it is absent, so the suite still runs on a machine without GoatTracker.

NOT covered: whether the song *sounds* right. That needs gt2reloc (blocked, see
the module docstring note below) plus a SID register trace.
"""
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG = REPO_ROOT / "Commando.sng"

# sngspli2 splits patterns into [length] rows. Anything shorter than our own
# pattern length multiplies orderlist entries and trips GoatTracker's 254-byte
# orderlist limit -- a property of the split request, not of our file. 128 is
# MAX_PATTROWS, so no pattern is ever split and no orderlist grows.
NO_SPLIT_LENGTH = "128"

_SEARCH = [
    r"C:\Users\mit\Downloads\goattracker2-sf-v1.1\goattracker2-sf-v1.1\win32\sngspli2.exe",
    "/usr/local/bin/sngspli2",
]


def _find_sngspli2():
    env = os.environ.get("H2G_SNGSPLI2")
    if env and pathlib.Path(env).exists():
        return env
    found = shutil.which("sngspli2")
    if found:
        return found
    for cand in _SEARCH:
        if pathlib.Path(cand).exists():
            return cand
    return None


SNGSPLI2 = _find_sngspli2()
requires_gt = pytest.mark.skipif(
    SNGSPLI2 is None,
    reason="GoatTracker's sngspli2 not found; set H2G_SNGSPLI2 to enable",
)


def _convert(out_path, *extra):
    result = subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )
    assert result.returncode == 0, f"conversion failed:\n{result.stderr}"
    return out_path


def _load_in_goattracker(sng_path, tmp_path):
    """Run a .sng through GoatTracker's loader. Returns its stdout."""
    dest = tmp_path / "gt_out.sng"          # source and dest may not be equal
    result = subprocess.run(
        [SNGSPLI2, str(sng_path), str(dest), NO_SPLIT_LENGTH],
        capture_output=True, text=True,
    )
    return result.stdout + result.stderr


def _assert_accepted(output, label):
    # loadsong() failing prints this specific string (sngspli2.c).
    assert "Couldn't load source song" not in output, (
        f"GoatTracker REJECTED {label}:\n{output}")
    assert "ERROR" not in output, f"GoatTracker errored on {label}:\n{output}"
    assert "Processing complete" in output, (
        f"GoatTracker did not complete on {label}:\n{output}")


@requires_gt
def test_reference_fixture_loads(tmp_path):
    """The committed Commando.sng must be loadable by GoatTracker itself.

    This is the strongest single claim in the suite: the fixture reproduces the
    2005 VB6 tool byte-for-byte AND is accepted by GoatTracker's real loader.
    """
    _assert_accepted(_load_in_goattracker(REFERENCE_SNG, tmp_path), "Commando.sng")


@requires_gt
@pytest.mark.parametrize("label,flags", [
    ("default", ()),
    ("max-rows 128", ("--max-rows", "128")),
    ("terminate-patterns", ("--terminate-patterns",)),
    ("128 + terminate", ("--max-rows", "128", "--terminate-patterns")),
])
def test_converted_output_loads(tmp_path, label, flags):
    """Every output mode must produce a file GoatTracker accepts."""
    sng = _convert(tmp_path / f"out_{abs(hash(label))}.sng", *flags)
    _assert_accepted(_load_in_goattracker(sng, tmp_path), label)


@requires_gt
def test_goattracker_reports_expected_song_size(tmp_path):
    """Sanity-check that GoatTracker sees real content, not an empty song.

    A structurally valid but musically empty file would still 'load', so assert
    the reported pattern data is substantial.
    """
    output = _load_in_goattracker(REFERENCE_SNG, tmp_path)
    # Table: "Before <songdata> <patterns> <patt.tbl> <total>"
    before = [ln for ln in output.splitlines() if ln.strip().startswith("Before")]
    assert before, f"no size table in output:\n{output}"
    fields = before[0].split()
    songdata, patterns = int(fields[1]), int(fields[2])
    assert songdata > 100, f"songdata implausibly small: {songdata}"
    assert patterns > 1000, f"pattern data implausibly small: {patterns}"
