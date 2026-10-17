"""The classic sweep never shows its start cutoff.

Sanxion $B3DE, traced with `siddump -w` on $B55B,X: a fetch frame skips the
filter block and resets the accumulator without writing $D416, so the chip
sees `8C00` held on the strike frame and `1C00` (= start + step) on the next.
`[params][set-cutoff start]` wrote `start` on the strike call.
"""
from __future__ import annotations

import pytest

from h2g.goatwriter import (FILT_SET_CUTOFF, FILT_SET_PARAMS, FILT_STOP,
                            _classic_sweep_block)
from test_filter_absent_four import gt_filter_calls

OLD = 0x77


def _block(per_call=0x1C, m=1, calls=12, start=0x00):
    return _classic_sweep_block(0x10, 0xF4, start, per_call, m, calls)


def test_the_strike_call_leaves_the_chip_where_it_was():
    """SABOTAGE TARGET: `(m + 1)` params rows -> 1 writes `start` on the
    strike call again."""
    got = gt_filter_calls(_block(), 1, 6, cutoff=OLD)
    assert got[0] == OLD                 # the strike call: nothing written
    assert got[1] == 0x1C                # next frame: start + step, not start
    assert got[2] == 0x38


def test_the_start_value_is_never_written():
    """SABOTAGE TARGET: `cutoff + per_call * m` -> `cutoff`."""
    got = gt_filter_calls(_block(start=0x20), 1, 12, cutoff=OLD)
    assert 0x20 not in got
    assert got[1] == 0x3C


@pytest.mark.parametrize("m", [2, 3])
def test_a_multiplied_song_holds_the_whole_strike_frame(m):
    got = gt_filter_calls(_block(per_call=4, m=m, calls=40), 1, 3 * m,
                          cutoff=OLD)
    assert got[:m] == [OLD] * m          # the strike frame: m calls, no write
    assert got[m] == (4 * m) & 0xFF      # then the first stepped value


def test_the_rows_run_one_frame_fewer_than_the_gap():
    """SABOTAGE TARGET: `calls - m` -> `calls`."""
    block = _block(calls=12)
    assert sum(left for left, _ in block
               if 0 < left < FILT_SET_PARAMS) == 11
    block = _block(m=2, per_call=4, calls=12)
    assert sum(left for left, _ in block
               if 0 < left < FILT_SET_PARAMS) == 10


def test_a_short_gap_still_sweeps_and_no_length_keeps_the_single_row():
    assert sum(left for left, _ in _block(calls=1)
               if 0 < left < FILT_SET_PARAMS) == 1
    unbounded = _block(calls=None)
    assert unbounded[-2:] == [(0x7F, 0x1C), (FILT_STOP, 0)]


def test_params_precede_the_set_cutoff_row():
    block = _block()
    assert block[0][0] == FILT_SET_PARAMS | 0x10
    assert block[1][0] == FILT_SET_PARAMS | 0x10
    assert block[2][0] == FILT_SET_CUTOFF
