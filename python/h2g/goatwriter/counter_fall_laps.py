"""The alternating fall past the counter's first lap (`counter_fall`'s second half).

The voice's frame counter `$BC,X` is a BYTE. At frame 255 of a note it
wraps, and for the alternating record (Mega_Apocalypse GT 10, `$09F9`,
threshold 31, vibrato gate 19) what the original does from there is a
SECOND LAP of the same shape, whose stores carry on counting from where the
first left off:

* frame 255 (counter 255) is the lap's last store: the voice is `n` units
  of `$100` under its note, `n` the number of stores the note has had, and
  nothing writes the frequency again until the counter is back at the
  vibrato gate -- the voice HOLDS the dip, 20 frames on record 9
  (`DE20` x 20 at the 288-frame note at frame 3745, the byte
  `$4E - 112`);
* from the gate (counter 19) the vibrato writes again, from the note;
* from the threshold (counter 31) the odd frames store again, `n` going on
  (113, 114 ...), and `n` taken modulo 256 is the dip -- a count past 127 is
  a dip UP (`$4E - 225` is `$6D`, above the note).

The first lap's loops (`counter_fall.alternation_*`) kept alternating at
their last size through all of that. What this module adds:

* **A hold at each lap end** (`alternation_note_rows`, kinds `X`, `H`, `Q`):
  the row holding the lap's last dip points at a short program, `[tie]
  [F2 n]` and a jump into a *still loop* (`F2 0` on every call, which skips
  the row's continuous effect: the swell's `4xy` left the channel's
  command at vibrato, and a stopped program would let it run); every row
  after it, to the vibrato gate, points at the still loop; the row the gate
  falls in (or the first after it) ties back to the note and falls into the
  same loop. `n` is exact (the program is `F2 n mod 256`, `F1 256 - n` past
  127): the held frames match the original's high byte.
* **The next lap's dips** (kind `D`/`S` of a fresh run): the stores go on
  from the threshold. A size is `n` modulo 256 folded to 1..127; its
  DIRECTION is not kept (a dip up is emitted as a dip down of the same
  size, the loops being down-loops only), so the sizes are right and the
  frequency high byte is not on those frames.

Programs are 2-3 rows a distinct `(n, tick)` and the wavetable has no room
for many: `ALTERNATION_HOLD_ROWS` is what the holds may take, the most used
first. A hold that is not taken leaves its lap end as before: the loop
carries on at its last size through the hold and the next lap.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, List, Optional, Set, Tuple

from . import skydive as _gw_skydive
from .constants import GT_WAVE_JUMP, WAVECMD_PORTADOWN, WAVECMD_PORTAUP
from .counter_fall import (COUNTER_FALL_HALF, COUNTER_FALL_MAX_SIZE,
                           COUNTER_FALL_WRAP, WAVECMD_TIE, AltRow,
                           alternation_rows, fall_stores, step_command)

# The wavetable rows the holds may take, the still loop's included (R0 tie,
# R1 `F2 0`, R2 jump to R1: three) and the programs, 2-4 rows each, the most
# used first. 6 is the still loop and the program every note shares: the
# 288-frame note's hold, the first lap's end of the 576- and 1920-frame notes.
# The second lap's end (count 225, tick 2, tied: 4 rows) is 10 in all; it
# costs the dip sizes two of their seven, which the first lap's phase pin
# (`counter_fall.ALTERNATION_ROWS`) does not allow. The other 7 lap ends are
# single ones. 9 is those 6 and the FINAL hold of a note a drum silences
# (`counter_fall.drum_stops`: count 245, tick 2, 3 rows).
ALTERNATION_HOLD_ROWS = 9
# The still loop: a tie to the note, then `F2 0` forever.
STILL_ROWS = 3
# Whether the laps past the first get their DIPS (a fresh run after a hold, or
# the loop carried through a hold that is not made). Off, only the first lap's
# loop and the holds are emitted. Measured at 1172704 (historical): on, the
# 576-frame note reverses 480 times (the original's 480; 288 off) and the
# swell's pass converts 1151 rows on 39 loops with nothing to merge, which
# fails three pins on how many loops it keeps
# (`tests/test_tie_restart_mega.py`, `tests/test_expanding_vibrato_split.py`);
# off it converts 1418 rows on 44 loops, 17 swings merged, as before.
ALTERNATION_LATER_LAPS = False
# Whether a note a drum silences (`counter_fall.drum_stops`) ends in a hold:
# the voice stays on the last dip's pitch to the note's end, as the original
# does once the counter can no longer reach the threshold.
ALTERNATION_FINAL_HOLD = True


def fall_size(count: int) -> int:
    """The dip, in high-byte units, a store whose running count is `count`
    makes: the count modulo 256 folded to 1..127 (0 is no dip, and a size
    of 128 is `$8000`, which no speed row says: 127)."""
    s = count % COUNTER_FALL_WRAP
    if s == 0:
        return 0
    if s > COUNTER_FALL_HALF:
        s = COUNTER_FALL_WRAP - s
    return min(s, COUNTER_FALL_MAX_SIZE)


def tie_first(delay: int, tied: bool) -> bool:
    """Whether a hold on tick `delay` ties to the note on the call before
    its dip: where that call is a step back (an odd tick), or where `tied`
    says the voice is not known to be on its note (no dip loop before the
    row: the swell's offset is on it) and there IS a call before the dip."""
    return bool(delay % 2 or (tied and delay >= 2))


def hold_program(count: int, delay: int, speed_index: Callable[[int], int],
                 still_at: int, tied: bool = False
                 ) -> List[Tuple[int, int]]:
    """The wavetable rows of the program that dips to `count` (mod 256) on
    the call `delay` ticks into its row and holds: the calls before it are
    nothing (the voice is on its note) or, where the call before the dip is
    a step back (or `tied`, see `tie_first`), a tie; the last row jumps to
    `still_at` (1-based)."""
    calls: List[Optional[Tuple[int, int]]] = []
    if tie_first(delay, tied):
        calls = [None] * (delay - 1) + [(WAVECMD_TIE, 0)]
    else:
        calls = [None] * delay
    cmd = step_command(count)
    if cmd is not None:
        calls.append((cmd[0], speed_index(cmd[1])))
    while calls and calls[-1] is None:
        calls.pop()
    rows = _gw_skydive._compress(calls)
    rows[-1] = (GT_WAVE_JUMP, still_at)
    return rows


def still_loop(speed_index: Callable[[int], int], base: int
               ) -> List[Tuple[int, int]]:
    """R0 tie to the note, R1 `F2 0` (a portamento of nothing: a wavetable
    command on every call, which skips the row's continuous effect), R2 a
    jump to R1. `base` is the 1-based index of R0."""
    cmd, zero = WAVECMD_PORTADOWN, speed_index(0)
    return [(WAVECMD_TIE, 0), (cmd, zero), (GT_WAVE_JUMP, base + 1)]


def hold_rows(count: int, delay: int, tied: bool = False) -> int:
    """How many rows `hold_program` takes."""
    return len(hold_program(count, delay, lambda h: 1, 1, tied))


def alternation_note_rows(length: int, threshold: int, gate: Optional[int],
                          fetches: Set[int], lag: int, frames: int,
                          usable: Callable[[int], bool],
                          rows_in_note: int,
                          holds: Optional[Set[Tuple[int, int, bool]]] = None,
                          stop: Optional[int] = None
                          ) -> Optional[List[AltRow]]:
    """The rows of one alternating note over ALL its counter laps, or None
    where a fetch frame lands on a store of the first lap (as
    `counter_fall.alternation_dips`).

    A lap's stores are the odd frames from the threshold to 255 (counter
    taken as a byte); the first lap's first store moves nothing. A lap that
    ends on frame 255 of a note that goes on holds, if `holds` (a set of
    `(count mod 256, tick, tied)`; None = every one) has its program and
    `usable`
    says its row can take one; otherwise its loop carries on through the
    hold -- `fillers` of the same size stand for the dips the original does
    not make, so the next lap's dips follow on the right parity.

    Rows: the first lap's as `alternation_rows`; a later run's from its
    first whole row (every row of it `fresh`: whichever of them is the
    first the table can take is the entry, with no delay of its own); a hold's `X` row (count in `n`, tick in
    `delay`), `H` rows through to the gate, `Q` the row the gate falls in
    (or the first after it).

    A `stop` (the frame a drum zeroes the counter on: `length` is already cut
    there) makes the last open run end in a hold of its own, `X` then `H` rows
    to the note's end and no `Q`: the original's pitch stays where the last
    store left it. The row of the last store is used where it can take a
    program, else the one two rows before it (the same call parity: the loop
    alternates on every call, and a row is an odd number of them).
    """
    plain = fall_stores(length, threshold)
    real = fall_stores(length, threshold, fetches)
    bad = sorted(set(plain) - set(real))
    if bad and bad[0] < COUNTER_FALL_WRAP:
        return None
    limit = None if not bad else bad[0] // COUNTER_FALL_WRAP \
        * COUNTER_FALL_WRAP
    laps: Dict[int, List[Tuple[int, int]]] = {}
    for n, j in enumerate(real):
        if limit is None or j < limit:
            laps.setdefault(j // COUNTER_FALL_WRAP, []).append((j, n))

    if gate is None or not 0 <= gate < threshold:
        # No vibrato gate read for the record: the first lap only, as
        # before -- what the original does past it is not known here.
        laps = {0: laps[0]} if 0 in laps else {}

    out: List[AltRow] = []
    run: List[Tuple[int, int]] = []        # (j, count) of the open run
    first_run = True

    def close(hold_at: Optional[tuple]) -> None:
        nonlocal run, first_run
        dips = [j for j, _n in run]
        mags = [fall_size(n) for _j, n in run]
        ars = alternation_rows(dips, lag, frames, mags)
        if not first_run:
            if ars and ars[0].kind == 'E':
                ars = ars[1:]
            ars = [replace(a, fresh=True) for a in ars]
        if hold_at is not None:
            count, e_x, tick, e_exit, tied = hold_at[:5]
            ars = [a for a in ars if a.e < e_x]
            ars.append(AltRow(e_x, 'X', tick, count, True, tied=tied,
                              final=len(hold_at) > 5))
            ars += [AltRow(e, 'H', 0, 0, True)
                    for e in range(e_x + 1, min(e_exit, rows_in_note))]
            if e_exit < rows_in_note:
                ars.append(AltRow(e_exit, 'Q', 0, 0, True))
        out.extend(ars)
        run = []
        first_run = False

    for lap in sorted(laps):
        items = laps[lap][1:] if lap == 0 else laps[lap]
        if not items:
            continue
        if run:
            # No hold at the last lap end: the loop carries on, and the
            # dips it makes through the gap are fillers of the last size.
            last_j, last_n = run[-1]
            for j in range(last_j + 2, items[0][0], 2):
                run.append((j, last_n))
        run.extend(items)
        last_j, last_n = items[-1]
        hold_at = None
        if (gate is not None and 0 <= gate < threshold
                and last_j == lap * COUNTER_FALL_WRAP + COUNTER_FALL_WRAP - 1
                and length > (lap + 1) * COUNTER_FALL_WRAP):
            count = last_n % COUNTER_FALL_WRAP
            c_last = last_j + lag
            e_x, tick = divmod(c_last, frames)
            c_res = (lap + 1) * COUNTER_FALL_WRAP + gate + lag
            e_exit = -(-c_res // frames)
            # (the gate's call is after the dip's, so e_exit > e_x always)
            # A lap past the first, with no dips in it before the hold (the
            # later laps are off), leaves the voice wherever the swell has it.
            tied = bool(lap > 0 and not ALTERNATION_LATER_LAPS
                        and tie_first(tick, True) and not tick % 2)
            if (count != COUNTER_FALL_HALF
                    and (holds is None or (count, tick, tied) in holds)
                    and usable(e_x)):
                hold_at = (count, e_x, tick, e_exit, tied)
        if hold_at is not None:
            close(hold_at)
    if run and stop is not None and ALTERNATION_FINAL_HOLD:
        last_j, last_n = run[-1]
        count = last_n % COUNTER_FALL_WRAP
        e_x, tick = divmod(last_j + lag, frames)
        if not usable(e_x) and e_x >= 2:
            e_x -= 2
        if (count != COUNTER_FALL_HALF and usable(e_x)
                and (holds is None or (count, tick, False) in holds)):
            close((count, e_x, tick, rows_in_note, False, True))
    if run:
        close(None)
    if not ALTERNATION_LATER_LAPS:
        first_end = (COUNTER_FALL_WRAP - 1 + lag) // frames
        out = [a for a in out if a.kind in 'XHQ'
               or (not a.fresh and a.e <= first_end)]
    return out
