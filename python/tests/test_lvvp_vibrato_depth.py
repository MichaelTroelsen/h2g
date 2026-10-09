"""Las_Vegas_Video_Poker's $6B9A vibrato depth (lvvp-6b9a-vibrato-depth).

Opened at 8586101 by lvvp-vibrato-phase: "ours swings 2 depths on $6B9A, the
original 3". Re-measured on 39b5de2 + the cycle-2 merge (figures historical;
-t 120 s, subtune 0, original at -m1, ours under presets packed at -S4;
C:/t/lvvp-6b9a-vibrato-depth/pn.py), in the original's depth unit
`u = (f(n) - f(n-1)) >> 2`, peak-to-peak over a note's first 60 frames:

    $6B9A original            2.99  (span 3.0 on 303 of 305 notes)
    $6B9A ours, gate_skip off 2.04  (span 2.0 on 280)   the 8586101 state
    $6B9A ours, shipped       3.46  (span 3.0 / 3.5 / 4.0 on 64 / 125 / 116)

The swing a note gets is `(cmp + 2) * (I >> rshift)`, `I` Goattracker's
interval from the note UP. At the shipped entry that predicts the measured
per-note peak-to-peak to a mean 0.02 depth. The 2-depth state was the missing
outer-gate stretch (`cmp + 2` = 11 calls where the half-period asks 15); the
stretch (v0.5.517) overshot it to 14 calls, 16% deep, and no integer `cmp`
gives the depth without giving up the period (the table beside
`_classic_vibrato_entry`). Nothing was changed; these pin the entry, the
swing arithmetic and the sharing so a later change to any of them is seen.
"""
import pathlib
import sys
from statistics import mean

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
from h2g.detect import detect                                 # noqa: E402
from h2g.goatwriter import _classic_vibrato_entry             # noqa: E402
from h2g.goatwriter.primitives import _note_freq              # noqa: E402
from h2g.sidfile import load_sid                              # noqa: E402

LVVP = CORPUS / "Las_Vegas_Video_Poker.sid"
VIB_BYTE = 0x1A                    # bound 3, shift 2
MULT, ROW_CALLS, GATE_SKIP = 4, 15, 4     # the preset -S4, short_row_calls, the outer gate
SHIFT, BOUND = 2, 3
# Player notes $6B9A plays (orig-note column of the trace), low to high.
NOTES = range(24, 51)


def _gt_loop(cmp_value, speed, calls):
    """gplay.c:795-801 run for `calls` calls; returns the frequency walk."""
    vibtime, freq, seen = 0, 0, [0]
    for _ in range(calls):
        if vibtime < 0x80 and vibtime > cmp_value:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        freq += -speed if vibtime & 1 else speed
        seen.append(freq)
    return seen


def _depths(entry, table):
    """Mean peak-to-peak in the original's depth units over NOTES, at call
    resolution, with Goattracker's floored table for the interval above."""
    cmp_value, rshift = entry[0] & 0x7F, entry[1]
    out = []
    for n in NOTES:
        u = (table[n] - table[n - 1]) >> SHIFT
        speed = (_note_freq(n + 1) - _note_freq(n)) >> rshift
        walk = _gt_loop(cmp_value, speed, 8 * (cmp_value + 2))
        out.append((max(walk) - min(walk)) / u)
    return out


def _player_table(sid):
    off = sid.to_offset(0x53F9)
    return [sid.data[off + 2 * n] | (sid.data[off + 2 * n + 1] << 8)
            for n in range(96)]


def test_the_entry_with_and_without_the_outer_gate_stretch():
    """$89 is the entry with the stretch off, which reproduces the 2-depth
    report exactly (not checked against 8586101's own bytes); $8C is what
    v0.5.517 emits. The
    four factors on the way: bound * mult = 12; the gate's 5/4 -> 15;
    the tick-0 compensation 14/15 -> 14; the bias 2 -> cmp 12; rshift =
    shift + round(log2(mult * 5/4)) = 4."""
    assert _classic_vibrato_entry(VIB_BYTE, MULT, ROW_CALLS) == (0x89, 4)
    assert _classic_vibrato_entry(VIB_BYTE, MULT, ROW_CALLS,
                                  gate_skip=GATE_SKIP) == (0x8C, 4)


def test_the_loop_swings_cmp_plus_two_steps():
    """The swing arithmetic the docstring uses: `(cmp + 2) * speed`, one step
    per call, for every cmp the candidate table tried."""
    for cmp_value in (9, 10, 11, 12):
        walk = _gt_loop(cmp_value, 7, 8 * (cmp_value + 2))
        assert max(walk) - min(walk) == (cmp_value + 2) * 7, cmp_value


@needs_corpus
def test_the_shipped_entry_swings_deeper_than_the_original_and_the_old_one_shallower():
    sid = load_sid(str(LVVP))
    table = _player_table(sid)
    now = mean(_depths(_classic_vibrato_entry(VIB_BYTE, MULT, ROW_CALLS,
                                              gate_skip=GATE_SKIP), table))
    old = mean(_depths(_classic_vibrato_entry(VIB_BYTE, MULT, ROW_CALLS),
                       table))
    # The original's swing is exactly `bound` depths.
    assert (VIB_BYTE >> 3) == BOUND and (VIB_BYTE & 7) == SHIFT
    assert BOUND < now, "the shipped entry no longer overswings: re-measure"
    assert 3.3 < now < 3.8, now          # 3.55 on the floored table; 3.46 traced
    assert 2.4 < old < BOUND, old        # 2.79; 2.04 traced at 1 sample per frame
    assert now > old


@needs_corpus
def test_the_two_records_share_one_vibrato_byte():
    """$6B9A (record 6) and $0AA0 (record 11) both carry $1A, so one speed
    entry serves a record 7% deep and one 2% shallow in bend."""
    sid = load_sid(str(LVVP))
    det = detect(sid, lambda *a: None)
    stride = det.instr_stride

    def record(i):
        base = det.instr_start + i * stride
        return sid.data[base:base + stride], sid.data[base + det.vibrato_offset]

    six, vib6 = record(6)
    eleven, vib11 = record(11)
    assert (six[3], six[4]) == (0x6B, 0x9A)
    assert (eleven[3], eleven[4]) == (0x0A, 0xA0)
    assert vib6 == vib11 == VIB_BYTE
