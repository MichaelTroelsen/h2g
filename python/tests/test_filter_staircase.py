"""A per-frame filter step that is not a whole number per call is a staircase.

Thanatos steps its cutoff by 3 a frame and holds the value the rest of the
frame; at `-S4` that is 0.75 a call, which `_filter_step_per_call` rounds to
+1, so ours swept 4 a frame (`cut` 1.12x, `cfrm` 65%, v0.5.676 at `-t 180`).
`_clamped_block` writes a one-call row of the whole step and a row holding
the other `m - 1` calls, for a step that does not divide by the multiplier.
Measured on Thanatos alone (the only file with the clamp spelling, and so the
only one whose bytes move): `cut` 1.12x -> 0.92x, `cfrm` 65% -> 86%.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import detect
from h2g.goatwriter import (FILT_SET_CUTOFF, FILT_SET_PARAMS, FILT_STOP,
                            GT_MAX_FILT, _clamp_frames, _clamped_block,
                            _filter_entries, _filter_step_per_call)
from h2g.goatwriter.filters import STAIRCASE_MAX_FRAMES
from h2g.sidfile import load_sid
from test_filter_absent_four import gt_filter_calls


def _frames(step, start, m, frames, cutoff=0x55):
    """The cutoff at the END of each frame, strike on the first call of
    frame 0, the sampling siddump does."""
    per_call = _filter_step_per_call(step, m)
    block = _clamped_block(0x10, 0xF4, start, step, per_call, m)
    got = gt_filter_calls(block, 1, m * frames, cutoff=cutoff)
    return block, [got[m * k + m - 1] for k in range(frames)]


@pytest.mark.parametrize("start,step,m", [(0x20, 3, 4), (0x20, 3, 2),
                                          (0x10, 5, 4), (0x20, 7, 3)])
def test_the_chip_sees_the_players_value_each_frame(start, step, m):
    """SABOTAGE TARGET: short-circuit the staircase branch in
    `_clamped_block` and the per-call rounding sweeps `round(step / m) * m`
    a frame, which is 4 for 3 at `-S4`."""
    n = min(_clamp_frames(start, step), STAIRCASE_MAX_FRAMES)
    block, seen = _frames(step, start, m, n + 3)
    assert seen[0] == 0x55                    # the strike frame writes none
    want = [(start + step * k) & 0xFF for k in range(1, n + 1)]
    assert seen[1:n + 1] == want
    assert seen[n + 1:] == [want[-1]] * 2     # then it holds
    assert block[0] == (FILT_SET_PARAMS | 0x10, 0xF4)
    assert block[-1] == (FILT_STOP, 0x00)
    assert len(block) <= GT_MAX_FILT


def test_a_step_that_divides_keeps_the_per_call_rows():
    """The exact case is untouched: 4 a frame at `-S4` is +1 a call."""
    block = _clamped_block(0x10, 0xF4, 0x20, 4, _filter_step_per_call(4, 4), 4)
    assert block[:2] == [(FILT_SET_PARAMS | 0x10, 0xF4),
                         (FILT_SET_CUTOFF, 0x20)]
    assert all(left != 1 for left, _ in block[2:-1])


def test_single_speed_never_stairs():
    block = _clamped_block(0x10, 0xF4, 0x20, 3, 3, 1)
    assert block[:2] == [(FILT_SET_PARAMS | 0x10, 0xF4),
                         (FILT_SET_CUTOFF, 0x20)]


@needs_corpus
def test_thanatos_sweeps_three_a_frame_at_s4():
    sid = load_sid(str(CORPUS / "Thanatos.sid"))
    det = detect(sid, lambda m: None)
    entries, pointers = _filter_entries(sid, det, 8, 1, 4)
    assert pointers and len(entries) <= GT_MAX_FILT
    ptr = min(pointers.values())
    got = gt_filter_calls(entries, ptr, 4 * 12, cutoff=0x37)
    frame_end = [got[4 * k + 3] for k in range(12)]
    assert frame_end[0] == 0x37
    assert [b - a for a, b in zip(frame_end[1:], frame_end[2:])] == [3] * 10
    assert frame_end[1] == 0x23
