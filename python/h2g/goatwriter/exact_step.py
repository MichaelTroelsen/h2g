"""A classic filter sweep that keeps the player's per-FRAME step at a multiplier
that does not divide it.

The goattracker filter table steps once per play CALL and the classic player
adds its record byte once per FRAME, so at `-S3` a step of -19 a frame is
-6.33 a call. `filters._filter_step_per_call` rounds that to one whole speed,
-6, and the sweep then runs 5% slow for every frame of its length: Knucklebusters
record 1 sweeps 48 frames and ends 0x3000 off the original's cutoff.

**It is applied only where it measured better** (`wanted`): the multiplier must
not divide the step, every strike of the record must land on one call phase
(`phase_free`: the sweep-to-next-note gaps `classic_filter_stop` already walks
are whole frames), and the rounded step must have drifted `DRIFT_FLOOR` steps
by the end of the sweep. Measured at a3792d2, -t 180, presets: Knucklebusters_1
cfrm 33% -> 80%, Knucklebusters_3 68% -> 77%; forced on the start song's
28-call records 19/20 it takes that subtune's cfrm .773 -> .677 (60 s), and on
Lightforce's 21-frame records 15/16 it pushes `cut` 1.046 -> 1.098.
"""
from __future__ import annotations

from typing import List

from .constants import FILT_MODULATE

# A window is as many frames as the 64-row filter table affords (two rows a
# window). Candidates, truest first; `filters._filter_entries` takes the
# first that fits.
EXACT_STEP_WINDOWS = (2, 3, 4, 6, 8, 12, 16, 24)

# Off, the classic sweep runs `_filter_step_per_call`'s one rounded speed, as
# before. Read at call time, so a test can short-circuit it.
EXACT_FRAME_STEP = True
PHASE_GATE = True

# A record is worth the extra table rows once the rounded per-call step has
# drifted this many cutoff steps (high-byte units) off the player's by the end
# of its sweep: `CUTOFF_FRAME_SPAN` / 0x100, the distance at which `cfrm`
# stops giving credit. A shorter sweep is within the rounding's own noise.
DRIFT_FLOOR = 32


def fractional(step: int, multiplier: int) -> bool:
    """True where the multiplier does not divide the signed per-frame step."""
    signed = step - 256 if step >= 0x80 else step
    return multiplier > 1 and bool(signed % multiplier)


def phase_free(sweep_calls, record: int, multiplier: int) -> bool:
    """True where every strike of `record` falls on one call phase.

    A strike's call phase within a frame is its distance in calls from the
    last one, mod `multiplier`; a record whose every sweep-to-next-note gap is
    a whole number of frames strikes at one phase, and the exact per-frame
    step is then right on every strike.
    """
    if not PHASE_GATE:
        return True
    gaps = getattr(sweep_calls, "gaps", {}).get(record)
    m = max(1, multiplier)
    return bool(gaps) and all(g % m == 0 for g in gaps)


def wanted(sweep_calls, record: int, step: int, multiplier: int,
           per_call: int) -> bool:
    """True where `record`'s sweep is built with the exact per-frame step.

    The multiplier does not divide the step (`fractional`), every strike of
    the record sits on one call phase (`phase_free`), and the rounded
    per-call step `per_call` would drift `DRIFT_FLOOR` steps or more off the
    player's over the sweep's length."""
    if not (fractional(step, multiplier)
            and phase_free(sweep_calls, record, multiplier)):
        return False
    calls = (sweep_calls or {}).get(record) or 0
    signed = step - 256 if step >= 0x80 else step
    p = per_call - 256 if per_call >= 0x80 else per_call
    return abs(signed - p * multiplier) * (calls / multiplier) >= DRIFT_FLOOR


def exact_step_rows(step: int, multiplier: int, calls: int,
                    window_frames: int) -> List[tuple]:
    """Modulation rows (time, speed) running `calls` calls at `step` a FRAME.

    **ONE ROUNDED PER-CALL SPEED IS A DIFFERENT SWEEP, NOT A SLIGHTLY SLOW
    ONE.** Every frame the error is the same sign: Knucklebusters' record 1
    steps the cutoff by -19 a frame at `-S3`, ours -6 a call = -18, so a
    48-frame sweep ends 48 steps (0x3000) off the original's and `cfrm`, which
    forgives 0x200 and scores nothing past 0x2200, reads 0.33 with every sweep
    entered on the right frame.

    Here the frame's total is kept. The sweep is cut into windows of
    `window_frames` whole frames (as even as the length allows). A window
    travels `frames * step` exactly, `extra` of its calls at the dearer
    per-call speed and the rest at the cheaper, the dearer ones split half at
    each end: the cutoff is on the player's line at every window edge and
    within `extra * (1 - extra / span) / 2` steps of it between them (one
    sided, that peak would double). Neighbouring windows' dearer ends are one
    row, so a window costs two rows. A leftover part-frame runs the rounded
    speed.
    """
    signed = step - 256 if step >= 0x80 else step
    m = max(1, multiplier)
    frames, rest = divmod(calls, m)
    windows = max(1, -(-frames // max(1, window_frames))) if frames else 0
    rows: List[tuple] = []

    def emit(n: int, speed: int) -> None:
        while n > 0:
            if rows and rows[-1][1] == speed and rows[-1][0] < FILT_MODULATE:
                take = min(n, FILT_MODULATE - rows[-1][0])
                rows[-1] = (rows[-1][0] + take, speed)
            else:
                take = min(n, FILT_MODULATE)
                rows.append((take, speed))
            n -= take

    for w in range(windows):
        f = (frames * (w + 1)) // windows - (frames * w) // windows
        span = f * m
        total = f * signed
        low = total // span                 # floor, also for a negative step
        extra = total - low * span
        first = extra // 2
        emit(first, (low + 1) & 0xFF)
        emit(span - extra, low & 0xFF)
        emit(extra - first, (low + 1) & 0xFF)
    if rest:
        emit(rest, round(signed / m) & 0xFF)
    return rows
