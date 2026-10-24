"""Hollywood or Bust record 6 (`$14`): the integer-shift floor on its vibrato swing.

The record's parameter byte `$14` is LFO table 1 (`00 01 02 01 00 81`, span 3
units) at count 4, so the original swings `3 * 4 * (interval >> 4)` =
0.75 of the semitone interval peak to peak, with a period of 6 frames. The
packed player skips the continuous effects on tick 0 of a row, and this
record plays at 3-call rows (`row_calls` 3, read off the build with a spy,
run record hollywood-or-bust-subtune-2-voice-1), so `_table_vibrato_entry`
shortens the half period 3 -> 2 and Goattracker's swing `(cmp + 2) *
(interval >> rshift)` has to be `2 * ...`; the nearest shift is 1, a swing of
1.0 interval = 1.33x the original's (1.42x measured on siddump, which reads
the interval above where the player reads the one below).

Why it stays: a note of this record is 6 frames and the packed player runs
the vibrato on 3 of them (frames 1, 3, 4 after the note; 2 and 5 are tick 0),
so a note shows three vibrato calls. In those, the only (cmp, rshift) whose
peak to peak is within 10% of the original's is a ONE-WAY RAMP (`cmp >= 4`,
`rshift` 2: +1, +2, +3 steps of a quarter interval), which is no vibrato; every
reversing shape lands at 1.33x or 0.67x. Measured, onset arm, sub 2, -t 180
(v0.5.590): `(0x80, 1)` voice-0 melody .671, `(0x80, 2)` .767, ramp `(0x84, 2)`
.675 -- see the task record for the full columns. The speed table's note-
relative entry is `interval >> shift` and nothing else (gplay.c:545-550), so a
3/8-interval step has no row; the exact shape is the wave program
(`convert(lfo_wave=True)`), which is its own trade.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.detect import detect  # noqa: E402
from h2g.goatwriter.vibrato import _table_vibrato_entry  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

HOLLYWOOD = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob/"
                 "Hollywood_or_Bust.sid")
needs_corpus = pytest.mark.skipif(not HOLLYWOOD.exists(),
                                  reason="the Hubbard corpus is not on this machine")

RECORD_BYTE = 0x14
ROW_CALLS = 3          # what the build passes for this record (spy, 2026-10-24)
WINDOW_CALLS = 3       # vibrato calls in a 6-frame note at 3-call rows
BAND = 0.10


def _gt_vibrato(cmp_value: int, calls: int) -> list:
    """Offsets (in speed units) after each of `calls` CMD_VIBRATO calls --
    gplay.c:787-796 transcribed, `vibtime` an unsigned byte."""
    vibtime = pos = 0
    out = []
    for _ in range(calls):
        if vibtime < 0x80 and vibtime > cmp_value:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        pos += -1 if vibtime & 1 else 1
        out.append(pos)
    return out


def _tv():
    sid = load_sid(str(HOLLYWOOD))
    tv = detect(sid, log=lambda m: None).table_vibrato
    assert tv is not None
    return tv


def _original_swing(tv) -> float:
    """Peak to peak in semitone intervals: span * count / 2**unit_shift."""
    index, count = RECORD_BYTE >> 4, RECORD_BYTE & 0x0F
    return tv.spans[index] * count / 2 ** tv.unit_shift


@needs_corpus
def test_the_original_swings_three_quarters_of_an_interval():
    tv = _tv()
    assert tv.spans[1] == 3 and tv.unit_shift == 4
    assert _original_swing(tv) == 0.75


@needs_corpus
def test_the_shipped_entry_is_one_interval_wide_because_of_the_rshift_rounding():
    """rc 3: half period 3 -> 2, cmp 0; the depth ratio 2 * 16 / (3 * 4) =
    2.67 has log2 1.415, which rounds to shift 1 -> (0 + 2) * (I >> 1) = 1.0 I,
    1.33x. Without the tick-0 compensation the same byte is (cmp 1, shift 2),
    exactly the original's 0.75 I -- at a period 1.5x too long."""
    tv = _tv()
    assert _table_vibrato_entry(RECORD_BYTE, tv, 1, ROW_CALLS,
                                table_span=True) == (0x80, 1)
    assert _table_vibrato_entry(RECORD_BYTE, tv, 1, 0,
                                table_span=True) == (0x81, 2)
    cmp_value, shift = _table_vibrato_entry(RECORD_BYTE, tv, 1, ROW_CALLS,
                                            table_span=True)
    assert ((cmp_value & 0x7F) + 2) / 2 ** shift / _original_swing(tv) == \
        pytest.approx(4 / 3)


@needs_corpus
def test_no_reversing_shape_in_a_note_window_is_within_ten_percent():
    """The floor: over every cmp 0..40 and shift 0..6, the shapes whose peak
    to peak over the note's three vibrato calls is within 10% of the
    original's are all monotone ramps; the closest reversing ones are 1.33x
    and 0.67x."""
    target = _original_swing(_tv())
    in_band, reversing = [], []
    for cmp_value in range(0, 41):
        offsets = [0] + _gt_vibrato(cmp_value, WINDOW_CALLS)
        steps = [b - a for a, b in zip(offsets, offsets[1:])]
        ramp = all(s > 0 for s in steps)
        for shift in range(0, 7):
            swing = (max(offsets) - min(offsets)) / 2 ** shift
            ratio = swing / target
            if abs(ratio - 1) <= BAND:
                in_band.append((cmp_value, shift, ramp))
            if not ramp:
                reversing.append(ratio)
    assert in_band, "nothing reaches the band: the floor claim is vacuous"
    assert all(ramp for _c, _s, ramp in in_band), in_band
    assert {s for _c, s, _r in in_band} == {2}
    below = max(r for r in reversing if r < 1 - BAND)
    above = min(r for r in reversing if r > 1 + BAND)
    assert below == pytest.approx(2 / 3)
    assert above == pytest.approx(4 / 3)


def test_the_gplay_transcription_is_a_triangle():
    # cmp 0: +1 0 -1 0 (period 4); cmp 1: +1 0 -1 -2 -1 0 (period 6);
    # cmp 4: +1 +2 +3 +2 +1 0 -1 ... (the ramp is the first half of a wide one)
    assert _gt_vibrato(0, 8) == [1, 0, -1, 0, 1, 0, -1, 0]
    assert _gt_vibrato(1, 6) == [1, 0, -1, -2, -1, 0]
    assert _gt_vibrato(4, 8) == [1, 2, 3, 2, 1, 0, -1, -2]
