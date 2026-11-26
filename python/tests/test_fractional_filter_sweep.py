"""A filter step that does not divide by the multiplier runs as an exact loop.

Dragons_Lair_Part_II's record 0x12 steps the cutoff 2 a frame and the song
packs at -S3: 2/3 a call. `_filter_step_per_call` rounds that to 1, which
steps 3 a frame, 1.5x the player's rate, and every sweep overshot the
original's (`cutoff_frame` 10%, `cutoff_sweep` 1.44x at -t 180). A record
whose every gap ends on a strike or a placed stop (`SweepLengths.free`) needs
no length, so its block is the exact pattern of whole steps with a jump back.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from h2g.goatwriter import (FILT_SET_PARAMS, FILT_STOP, _classic_sweep_block,
                            _fractional_period_rows, _fractional_sweep_applies)
from test_filter_absent_four import gt_filter_calls

OLD = 0x77


@pytest.mark.parametrize("step,m,rows", [
    (2, 3, [(1, 0), (2, 1)]),            # 0, +1, +1
    (1, 3, [(2, 0), (1, 1)]),            # 0, 0, +1
    (0xFE, 3, [(2, 0xFF), (1, 0)]),      # -2 a frame (floor): -1, -1, 0
    (3, 2, [(1, 1), (1, 2)]),            # 1.5 a call: +1, +2
])
def test_the_period_is_the_exact_pattern(step, m, rows):
    """SABOTAGE TARGET: `_fractional_period_rows` returning one row of the
    rounded per-call step (the pre-change behaviour)."""
    got = _fractional_period_rows(step, m)
    assert got == rows
    signed = step - 256 if step >= 0x80 else step
    total = sum(n * (v - 256 if v >= 0x80 else v) for n, v in got)
    assert total == signed                  # one period is one frame's travel


@pytest.mark.parametrize("step,m,applies", [
    (2, 3, True),        # 0.667 rounded to 1: 50% off
    (1, 3, True),        # 0.333 -> 1: 200%
    (0xFE, 3, True),
    (3, 2, True),        # 1.5 -> 2: 33%
    (16, 3, False),      # 5.33 -> 5: 6%
    (15, 3, False),      # whole
    (4, 2, False),       # whole
    (2, 1, False),       # -S1: nothing to divide
    (0, 3, False),
])
def test_only_a_rounding_worth_a_loop_gets_one(step, m, applies):
    assert _fractional_sweep_applies(step, m) is applies


def _block(step, m, loop_at=1, calls=300, per_call=1, start=0x00):
    return _classic_sweep_block(0x10, 0xF2, start, per_call, m, calls,
                                step, loop_at=loop_at)


def _frames(entries, m, nframes, cutoff=OLD):
    calls = gt_filter_calls(entries, 1, m * nframes, cutoff=cutoff)
    return [calls[m * f + m - 1] for f in range(nframes)]


@pytest.mark.parametrize("step,m", [(2, 3), (1, 3), (3, 2), (0xFE, 3)])
def test_the_chip_moves_one_frames_step_every_frame(step, m):
    """SABOTAGE TARGET: dropping the `loop_at` branch of `_classic_sweep_block`
    steps `per_call * m` (3 a frame for a 2) and the deltas differ."""
    signed = step - 256 if step >= 0x80 else step
    frames = _frames(_block(step, m), m, 40)
    deltas = {(b - a) & 0xFF for a, b in zip(frames[2:], frames[3:])}
    assert deltas == {signed & 0xFF}


def test_the_block_jumps_back_to_its_first_modulation_row():
    block = _block(2, 3, loop_at=9)
    assert block[-1][0] == FILT_STOP
    assert block[-1][1] == 9 + 4 + 1        # params x (m+1), the set row
    assert block[:4] == [(FILT_SET_PARAMS | 0x10, 0xF2)] * 4


def test_a_block_without_a_loop_site_keeps_the_rounded_rate():
    """A record that is not `free` still has a length and the old rows."""
    unlooped = _classic_sweep_block(0x10, 0xF2, 0, 1, 3, 12, 2, loop_at=None)
    assert FILT_STOP not in [left for left, right in unlooped if right]
    old = _classic_sweep_block(0x10, 0xF2, 0, 1, 3, 12)
    assert unlooped == old


def test_a_step_that_divides_evenly_is_untouched():
    looped = _classic_sweep_block(0x10, 0xF2, 0, 5, 3, 12, 15, loop_at=1)
    assert looped == _classic_sweep_block(0x10, 0xF2, 0, 5, 3, 12)


CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"


@pytest.mark.skipif(not (CORPUS / "Dragons_Lair_Part_II.sid").exists(),
                    reason="corpus not present")
def test_dragons_lair_ii_record_0x12_sweeps_two_a_frame():
    """The real file: the instrument carrying record 0x12's filter pointer
    sweeps 0x02 a frame on the chip, not 0x03."""
    import fidelity as F
    import songview as S
    from h2g.convert import convert

    doc = json.loads(PRESETS.read_text())
    opts = F._preset_opts(doc, "Dragons_Lair_Part_II.sid")
    song = S.parse_sng(convert(str(CORPUS / "Dragons_Lair_Part_II.sid"),
                               log=lambda m: None, **opts))
    entries = song.tables["FTBL"]
    assert any(left == FILT_STOP and right for left, right in entries), \
        "no looped filter program was written"
    seen = set()
    for ins in song.instruments:
        if not ins.filt_ptr:
            continue
        calls = gt_filter_calls(entries, ins.filt_ptr, 3 * 30, cutoff=0)
        frames = [calls[3 * f + 2] for f in range(30)]
        seen.add(frozenset((b - a) & 0xFF
                           for a, b in zip(frames[3:], frames[4:])))
    # 2 a frame is what record 0x12 does; the 3 a frame it used to
    assert frozenset({2}) in seen
