"""The LFO-table vibrato entry corrected for the packed player's tick-0 skip.

player.s runs no continuous effect on tick 0 of a row (REALTIMEOPTIMIZATION),
so a row of `row_calls` calls steps the oscillator on `row_calls - 1` of them.
`_table_vibrato_entry` scales its half-period by (rc - 1) / rc, the way
`_classic_vibrato_entry` does; 0 and 1 mean "do not compensate".
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from h2g.detect import Detection, TableVibrato
from h2g.goatwriter import (FORMAT_GTS5, SPEED_NOTE_RELATIVE,
                            VIBRATO_CMP_BIAS, _table_vibrato_entry,
                            _vibrato_layout)

SHAPES = ((4, 1), (6, 2), (8, 2), (10, 3))
TV = TableVibrato(5, 4, SHAPES)


def _cmp(byte, mult, rc):
    left, _ = _table_vibrato_entry(byte, TV, mult, rc)
    return left & 0x7F


@pytest.mark.parametrize("rc", [0, 1])
def test_no_or_one_call_is_the_uncorrected_entry(rc):
    for byte in (0x01, 0x12, 0x24, 0x33):
        for mult in (1, 2, 4):
            assert (_table_vibrato_entry(byte, TV, mult, rc)
                    == _table_vibrato_entry(byte, TV, mult))


@pytest.mark.parametrize("mult,rc", [(1, 2), (2, 2), (2, 3), (4, 4), (4, 2)])
def test_the_half_period_is_scaled_by_rows_less_tick_zero(mult, rc):
    for index, (length, _) in enumerate(SHAPES):
        want = max(1, round(length * mult / 2.0 * (rc - 1) / rc))
        assert _cmp((index << 4) | 1, mult, rc) == max(
            0, want - VIBRATO_CMP_BIAS)


def test_the_period_in_frames_is_the_tables_length_once_tick_zero_is_skipped():
    # 2*(cmp+2) stepped calls; only (rc-1)/rc of calls step, so real calls =
    # 2*(cmp+2) * rc/(rc-1), and frames = that / mult.
    for mult, rc in ((2, 3), (4, 4), (4, 2)):
        for index, (length, _) in enumerate(SHAPES):
            cmp_value = _cmp((index << 4) | 1, mult, rc)
            frames = 2 * (cmp_value + VIBRATO_CMP_BIAS) * rc / (rc - 1) / mult
            assert abs(frames - length) <= rc / (rc - 1) / mult + 1e-9


def test_the_shift_reads_the_cmp_actually_emitted():
    a = _table_vibrato_entry(0x13, TV, 2, 0)
    b = _table_vibrato_entry(0x13, TV, 2, 3)
    assert a[0] & SPEED_NOTE_RELATIVE and b[0] & SPEED_NOTE_RELATIVE
    assert b[0] & 0x7F <= a[0] & 0x7F
    assert b[1] <= a[1]


def test_a_silent_byte_stays_silent_whatever_the_row():
    assert _table_vibrato_entry(0x00, TV, 2, 3) is None
    assert _table_vibrato_entry(0x90, TV, 2, 3) is None


class _Sid:
    data = bytes([0, 0, 0x41, 0, 0, 0x01, 0, 0])


def test_the_layout_hands_the_table_engine_its_row_calls():
    det = Detection(instr_start=0, instr_stride=8, table_vibrato=TV)
    for rc in (0, 3):
        table = []
        _vibrato_layout(_Sid(), det, 2, True, FORMAT_GTS5, 2, table,
                        row_calls=rc)
        assert table == [_table_vibrato_entry(0x01, TV, 2, rc)]
