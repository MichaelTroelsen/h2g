"""Tracing a conversion at the rate it was packed for.

A tune packed with `gt2reloc -S2` is called 100.25 times a second on hardware:
the packed file's *init* address is a ten-byte stub that writes `0x4cc7/2` to
timer A and falls through into the player, and the play address is the player
itself (greloc.c:140, :1616, :1636). Stock siddump calls the play routine
`seconds * 50` times whatever the PSID speed field says (siddump.c:309/325),
so all 33 of those songs were traced at half speed -- and, because siddump's
option switch has no `default:` case, a stock binary handed `-m2` drops it
without a word and returns a dump that looks entirely normal and is half the
tune.

That silent path is what these tests exist for. The capability probe is the
only thing standing between "this build cannot do it" and a plausible wrong
number.
"""
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                               # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RT = pathlib.Path(fidelity.SIDDUMP_RT)
STOCK = os.environ.get(
    "H2G_SIDDUMP_STOCK",
    r"C:\Users\mit\claude\c64server\SIDM2\tools\siddump.exe")

needs_rt = pytest.mark.skipif(
    not RT.exists(),
    reason="tools/siddump-rt not built (see its README)")


def test_a_binary_without_m_is_not_taken_at_its_word(tmp_path):
    """An exe that cannot be run at all supports nothing."""
    fidelity.supports_calls_per_frame.cache_clear()
    assert not fidelity.supports_calls_per_frame(str(tmp_path / "nothing.exe"))


def test_tracing_faster_than_50hz_refuses_a_binary_that_cannot(tmp_path):
    """The failure mode is a plausible dump, so it has to be an exception.

    Refusing is the whole point: the alternative is a trace of half the tune
    that no column of the report can distinguish from a bad conversion.
    """
    fake = tmp_path / "nothing.exe"
    with pytest.raises(RuntimeError, match="does not support -m"):
        fidelity.run_siddump(REPO_ROOT / "Commando.sid", 1, 0, str(fake), calls=2)


def test_one_call_per_frame_never_needs_the_patched_build(tmp_path):
    """Everything at multiplier 1 still runs on a stock siddump."""
    fake = tmp_path / "nothing.exe"
    # No -m argument is added, so this gets as far as trying to run the exe
    # rather than refusing on the capability check.
    with pytest.raises((OSError, subprocess.SubprocessError)):
        fidelity.run_siddump(REPO_ROOT / "Commando.sid", 1, 0, str(fake), calls=1)


@needs_rt
def test_the_built_tool_advertises_m(tmp_path):
    fidelity.supports_calls_per_frame.cache_clear()
    assert fidelity.supports_calls_per_frame(str(RT))


@needs_rt
@pytest.mark.skipif(not pathlib.Path(STOCK).exists(),
                    reason="stock siddump not available to compare against")
def test_m1_is_byte_identical_to_stock_siddump():
    """The patch is inert at the default, or every number here moved at once."""
    sid = str(REPO_ROOT / "Commando.sid")
    args = ["-a0", "-t5"]
    a = subprocess.run([str(RT), sid] + args, capture_output=True, text=True,
                       timeout=180, stdin=subprocess.DEVNULL).stdout
    b = subprocess.run([STOCK, sid] + args, capture_output=True, text=True,
                       timeout=180, stdin=subprocess.DEVNULL).stdout
    c = subprocess.run([str(RT), sid] + args + ["-m1"], capture_output=True,
                       text=True, timeout=180, stdin=subprocess.DEVNULL).stdout
    assert a == b
    assert c == b


@needs_rt
def test_two_calls_a_frame_plays_twice_as_much_tune():
    """Same frame count, twice the music -- which is what the option means."""
    sid = REPO_ROOT / "Commando.sid"
    one = fidelity.run_siddump(sid, 10, 0, str(RT), calls=1)
    two = fidelity.run_siddump(sid, 10, 0, str(RT), calls=2)
    n1 = sum(len(v.attacks) for v in one)
    n2 = sum(len(v.attacks) for v in two)
    assert n1 > 0
    # Not exactly 2x: a note's attack is a gate edge, and a tune played twice
    # as fast in a fixed window reaches further into music with its own note
    # density. The claim is only that the frame axis did not change while
    # substantially more of the tune fitted inside it.
    assert n2 > n1 * 1.5
    assert len(one[0].attack_frames) == 0 or max(
        v.attack_frames[-1] for v in one if v.attack_frames) <= 10 * 50
    assert max(v.attack_frames[-1] for v in two if v.attack_frames) <= 10 * 50
