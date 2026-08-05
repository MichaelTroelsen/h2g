"""Orderlist REPEAT packing (--pack-repeats).

Goattracker can say "play the next pattern n+1 times" in two bytes
(`$D0`-`$DF`, gplay.c:983), so a run of L identical consecutive patterns costs
ceil(L/16)*2 instead of L. This is the only option that shortens an
*orderlist* -- dedup renumbers entries without removing any and pruning
removes patterns, not positions -- so it is the only one that can rescue a
tune from the 254-byte orderlist limit.

The risk is not that it fails to shrink: it is that a repeat command is
positional. Goattracker parses one orderlist step as
[transpose][repeat][pattern], so a repeat placed after another repeat makes
the second byte be read as the step's *pattern number*. These tests therefore
reconstruct what each orderlist plays, following gplay.c, and assert it is
unchanged.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import (GT_MAX_REPEAT_RUN, GT_MIN_REPEAT_RUN, GT_REPEAT,
                          pack_repeats)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"

REPEAT, TRANSDOWN, TRANSUP, LOOPSONG = 0xD0, 0xE0, 0xF0, 0xFF


def _run(out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _play(order, limit=10000):
    """Pattern numbers an orderlist plays, in order, following gplay.c:977-992.

    One step reads an optional transpose, then an optional repeat, then the
    pattern -- and while a repeat is counting down the pointer does not
    advance, so the same byte is read again as the next step's pattern.
    """
    out, ptr, trans, repeat = [], 0, 0, 0
    while ptr < len(order) and len(out) < limit:
        if order[ptr] == LOOPSONG:
            break
        if TRANSDOWN <= order[ptr] < LOOPSONG:
            trans = order[ptr] - TRANSUP
            ptr += 1
            if ptr >= len(order):
                break
        if REPEAT <= order[ptr] < TRANSDOWN:
            repeat = order[ptr] - REPEAT
            ptr += 1
            if ptr >= len(order):
                break
        out.append((trans, order[ptr]))
        if repeat:
            repeat -= 1
        else:
            ptr += 1
    return out


def _roundtrip(track):
    """Pack a track and assert it plays identically. Returns the packed form."""
    packed = pack_repeats(track)
    assert _play(packed) == _play(track), f"{track} -> {packed}"
    return packed


# --- the construct ---------------------------------------------------------

def test_short_runs_are_left_alone():
    # A run of 2 costs 2 bytes either way, so emitting a command buys nothing.
    assert GT_MIN_REPEAT_RUN == 3
    assert _roundtrip([0x05, 0x05, 0xFF, 0x00]) == [0x05, 0x05, 0xFF, 0x00]


def test_a_run_becomes_one_command_and_one_pattern():
    assert _roundtrip([0x05] * 3 + [0xFF, 0x00]) == [GT_REPEAT + 2, 0x05, 0xFF, 0x00]


def test_a_full_group_is_sixteen_plays():
    assert GT_MAX_REPEAT_RUN == 16
    assert _roundtrip([0x05] * 16 + [0xFF, 0x00]) == [0xDF, 0x05, 0xFF, 0x00]


def test_a_leftover_below_the_threshold_is_written_out():
    # 17 packs to $DF,P,P (3 bytes), not two groups (4).
    assert _roundtrip([0x05] * 17 + [0xFF, 0x00]) == [0xDF, 0x05, 0x05, 0xFF, 0x00]


def test_long_runs_split_into_full_groups():
    # 35 = 16 + 16 + 3; the last group still clears the threshold, so all
    # three pack -- 6 bytes for 35 plays.
    assert _roundtrip([0x05] * 35 + [0xFF, 0x00]) == \
        [0xDF, 0x05, 0xDF, 0x05, GT_REPEAT + 2, 0x05, 0xFF, 0x00]


def test_distinct_patterns_are_untouched():
    track = [0x01, 0x02, 0x03, 0xFF, 0x00]
    assert _roundtrip(track) == track


# --- the positional hazards ------------------------------------------------

def test_a_run_after_a_stray_repeat_keeps_its_first_element_literal():
    # $D4 here is not ours: version 0/1/3 orderlists can carry Hubbard pattern
    # numbers in $D0-$FD, which reindex_tracks passes through untouched and
    # Goattracker then reads as a repeat. Packing straight after it would put
    # two repeats in a row and the second would be read as a pattern number.
    packed = _roundtrip([0xD4, 0x1F, 0x1F, 0x1F, 0x1F, 0xFF, 0x00])
    assert packed[:2] == [0xD4, 0x1F]
    assert not (REPEAT <= packed[2] < TRANSDOWN and REPEAT <= packed[1] < TRANSDOWN)


def test_packing_after_a_transpose_is_allowed():
    # [transpose][repeat][pattern] is exactly the order gplay.c reads.
    assert _roundtrip([0xF7] + [0x05] * 4 + [0xFF, 0x00]) == \
        [0xF7, GT_REPEAT + 3, 0x05, 0xFF, 0x00]


def test_the_restart_operand_is_never_treated_as_a_pattern():
    # $FF's operand is a position, not a pattern -- a run of them must not be
    # collapsed, and the pair must stay adjacent.
    track = [0x05, 0x05, 0x05, 0xFF, 0x05]
    assert _roundtrip(track)[-2:] == [0xFF, 0x05]


def test_a_repeat_is_never_the_last_byte():
    for length in range(1, 40):
        packed = pack_repeats([0x07] * length)
        assert not (REPEAT <= packed[-1] < TRANSDOWN), length


def test_every_run_length_round_trips():
    for length in range(1, 100):
        _roundtrip([0x02, 0x03] + [0x07] * length + [0x04, 0xFF, 0x00])


# --- end to end ------------------------------------------------------------

def test_default_is_off_and_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_packing_shortens_the_file(tmp_path):
    plain, packed = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(plain).returncode == 0
    assert _run(packed, "--pack-repeats").returncode == 0
    assert len(packed.read_bytes()) < len(plain.read_bytes())


def test_composes_with_the_other_options(tmp_path):
    out = tmp_path / "c.sng"
    r = _run(out, "--pack-repeats", "--prune-patterns", "--dedup-patterns",
             "--max-rows", "128", "--format", "gts5")
    assert r.returncode == 0, r.stderr
