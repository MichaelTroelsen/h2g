"""A classic filter sweep restarts on EVERY event its voice fetches, not only
on a new note.

**THE PLAYER RESETS A VOICE'S CUTOFF ACCUMULATOR AT THE TOP OF ITS FETCH, FOR
A REST AND A TIE AS WELL AS A NOTE.** Knucklebusters $0562..$0578 (the start
song, records 19/20): the fetch path stores `LDA #$00 / STA $09A4,X`
(`cutoff,X`) before it tests whether the entry names a note, and skips the
effects section that frame, so the frame holds and the next one writes
`start + step`. The start song's pattern 73 plays note, KEYOFF, note: the
original sweeps 9 frames, holds the one fetch frame at the KEYOFF, and sweeps
again from `$1C00`; ours knew only the note's strike, so its one program ran
straight on through the 8-bit wrap and led the original by 28 steps for the
rest of the 28-frame gap (cutoff credit .44 -> .19 on frames 12-19, 0 after).

The restart is a `CMD_SETFILTERPTR` to the live instrument's own block on
the KEYOFF row: the block opens with `multiplier + 1` params rows, which is
the strike frame's hold (`filters._classic_sweep_block`), then the first
swept value. `filters.free_running_fetch_holds` places the same pointer for
the free-running player's one-call hold; this reuses its planner for every
voice, on the event's own row only (`back=0`: a restart three rows early is
three rows of the wrong cutoff).

**IT SPENDS PATTERN SLOTS AHEAD OF `pitch_lead`.** A position whose visits want
different restarts gets a pattern copy, and `convert` runs `lead_ties` on the
finished bytes. Auf_Wiedersehen_Monty goes 154 -> 206 patterns under
`pitch_lead_tie` (no shipped preset sets it); three restart copies in front
of those 52 reach the 208 cap and four row-0 drums stay unled
(`tests/test_pitch_lead.py` isolates the option from this pass).
"""
from __future__ import annotations

from .filters import _filter_step_per_call, free_running_fetch_holds

# Read at call time, so a test can short-circuit it.
ENABLED = True
# A restart re-runs the record's own sweep, so it is only right where that
# sweep is: the rounded per-call step times the multiplier must reproduce the
# player's per-frame step to within this share of it. Dragons_Lair_Part_II's
# record 22 steps 1 a frame and ours 1 a CALL (3 a frame at -S3), `cut`
# 1.44x already; the one restart it takes re-runs that triple-speed sweep and
# takes `cut` to 1.50x (measured at 0205e7d, -t 180). Knucklebusters' $1C
# against 9 x 3 is 4% off.
SLOPE_TOLERANCE = 0.25
# A tie fetches too (the reset sits above the tie test), but its own row's
# command column is its `CMD_TONEPORTA`, so at `back=0` a restart can never
# be placed there: with ties counted the files that move moved no
# differently (byte-hash, 2026-11-26). False leaves them out of the counts.
TIES = False


def classic_fetch_restarts(tracks, patterns, ptr_of: dict, log=None) -> tuple:
    """(patterns, tracks, written): a restart pointer on every KEYOFF (and,
    where `TIES`, tie) of every voice whose live instrument carries a filter block."""
    return free_running_fetch_holds(tracks, patterns, ptr_of, voice=None,
                                    back=0, log=log, ties=TIES)


def slope_true(step: int, multiplier: int) -> bool:
    """True where `filters._filter_step_per_call` carries the player's
    per-frame step to within `SLOPE_TOLERANCE` of it (a static record, step
    0, is trivially true)."""
    signed = step - 256 if step >= 0x80 else step
    if not signed:
        return True
    p = _filter_step_per_call(step, multiplier)
    p = p - 256 if p >= 0x80 else p
    return abs(signed - p * max(1, multiplier)) <= SLOPE_TOLERANCE * abs(signed)


def untrue_slope_pointers(sid, det, filter_ptrs: dict, multiplier: int) -> set:
    """The filter-table pointers whose record's sweep runs a wrong slope
    (`slope_true`); a restart is not written for an instrument that holds
    one."""
    filt = det.filter
    bad = set()
    for record, ptr in filter_ptrs.items():
        at = filt.offset + record * det.instr_stride + 1
        if at < len(sid.data) and not slope_true(sid.data[at], multiplier):
            bad.add(ptr)
    return bad
