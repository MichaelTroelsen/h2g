"""The free-running cutoff's fetch hold is `multiplier` calls, not one.

The original holds on a note-FETCH frame: no step for a whole frame, which is
`multiplier` play calls. Each filter-table params row is one call
(gplay.c:265-270), so the block opens with `multiplier` params rows when the
player is one `free_running_fetch_hold_voice` reads, and a
`CMD_SETFILTERPTR` to its first row holds that many calls. Until now the pass
was gated to `multiplier == 1`.
"""
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import h2g.goatwriter.filters as gwf                          # noqa: E402
from h2g.goatwriter import (FILT_MODULATE, FILT_SET_PARAMS,   # noqa: E402
                            _free_running_block)
from test_filter_absent_four import gt_filter_calls           # noqa: E402


def _hold_gaps(block, held_calls, start=0x40):
    """(cutoff before, cutoff after each of 20 calls) for a jump to the
    block's first row made while the sweep runs on the modulation row."""
    mod_row = 1 + max(1, held_calls)
    run = gt_filter_calls(block, mod_row, 30, cutoff=start)
    cutoff = run[-1]
    return cutoff, gt_filter_calls(block, 1, 20, cutoff=cutoff)


@pytest.mark.parametrize("m", [1, 2, 3, 4])
def test_a_pointer_jump_holds_exactly_multiplier_calls(m):
    """SABOTAGE TARGET: emit one params row whatever `hold_calls` says and
    the hold is one call at every m > 1."""
    block = _free_running_block(0x10, 0xF4, 2, 1, hold_calls=m)
    cutoff, got = _hold_gaps(block, m)
    assert got[:m] == [cutoff] * m                   # m calls, no step
    assert got[m] == (cutoff + 2) & 0xFF             # then the sweep resumes
    assert got[m + 1] == (cutoff + 4) & 0xFF


@pytest.mark.parametrize("m", [1, 3])
def test_the_loop_returns_to_the_modulation_row(m):
    """SABOTAGE TARGET: leave the jump at `at + 1` and, at m > 1, it lands on
    a params row and the sweep pauses m calls every $7F."""
    block = _free_running_block(0x10, 0xF4, 2, 1, hold_calls=m)
    assert block[:m] == [(FILT_SET_PARAMS | 0x10, 0xF4)] * m
    assert block[m] == (FILT_MODULATE, 2) and block[m + 1][1] == 1 + m
    got = gt_filter_calls(block, 1, 600, cutoff=0x00)
    steps = [(b - a) & 0xFF for a, b in zip(got[m:], got[m + 1:])]
    assert set(steps) == {2}


def test_the_default_and_a_static_block_are_unchanged():
    assert _free_running_block(0x10, 0xF4, 2, 5) == \
        _free_running_block(0x10, 0xF4, 2, 5, hold_calls=1) == [
            (FILT_SET_PARAMS | 0x10, 0xF4), (FILT_MODULATE, 2), (0xFF, 6)]
    assert _free_running_block(0x10, 0xF4, 0, 1, hold_calls=4) == [
        (FILT_SET_PARAMS | 0x10, 0xF4), (0xFF, 0x00)]


def _fake():
    data = bytearray(64)
    data[8], data[9] = 0xF4, 0x02      # resctl, step
    data[20] = 0x20                    # status: filter enabled
    filt = SimpleNamespace(offset=8, status=20, passband=0x10, cutoff=8,
                           free_running=True, clamp=False)
    det = SimpleNamespace(filter=filt, instr_stride=100, sfx_period=0)
    return SimpleNamespace(data=bytes(data)), det


@pytest.mark.parametrize("m", [1, 3])
def test_the_table_builder_widens_only_a_player_the_hold_reads(m, monkeypatch):
    """A synthetic multispeed free-running record through the table builder:
    the head is `m` params rows where the fetch skip is read, one row where
    it is not (After_8, Rikky and Mr_Meaner must not move)."""
    sid, det = _fake()
    monkeypatch.setattr(gwf, "free_running_fetch_hold_voice", lambda s: 0)
    entries, ptrs = gwf._filter_entries(sid, det, 2, multiplier=m)
    assert ptrs == {0: 1}
    assert entries[:m] == [(FILT_SET_PARAMS | 0x10, 0xF4)] * m
    assert entries[m][0] == FILT_MODULATE
    monkeypatch.setattr(gwf, "free_running_fetch_hold_voice", lambda s: None)
    entries, _ = gwf._filter_entries(sid, det, 2, multiplier=m)
    assert [e[0] for e in entries].count(FILT_SET_PARAMS | 0x10) == 1
