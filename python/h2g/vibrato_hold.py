"""The classic vibrato as a frame-held wavetable program, for multispeed songs.

The classic `$78/$07` player moves a voice's frequency ONCE A FRAME: its counter
steps between 0 and `bound` and the voice sits at `note + (ctr - bound/2) *
depth` for the whole frame (Thanatos voice 0: `3A8C 3B5E 3A8C 39BA`, one value
per frame, +-$D2). The instrument vibrato Goattracker runs
(`goatwriter.vibrato._classic_vibrato_entry`) steps on EVERY play call, so at
`-S4` it is a four-times-finer ramp of a quarter of the depth per call
(`$37` a call against `$D2` a frame): the same period and the same swing, a
different waveform. Sampled once a frame it reads 0.75 direction changes a frame
against the original's 0.38, and the rendered sound shows it -- substituting the
original's pitch registers into our player lifts Thanatos' `aud` by 0.0102
(C:/t/thanatos-aud-ceiling).

Goattracker has one place that steps the vibrato once instead of continuously:
a WAVETABLE COMMAND row. `$F4 nn` (gplay.c:618-641) runs one `CMD_VIBRATO` step
of speed-table entry `nn` and the program moves on. So the held vibrato is a
wavetable program that steps on the frame lattice and waits in between:

    F4 nn        one step, full depth (interval >> shift: no division by the
                 call rate, the step is a frame's)
    delay m - 2  `m - 1` calls (a delay row `d` holds `d + 1` calls), `m` = the
                 song's calls a frame
    FF <row>     back to the F4 row

with the speed entry `($80 | (bound - 2), shift)`: `cmp + 2` = `bound` steps a
half-period, the player's own (`VIBRATO_CMP_BIAS`), and `vibtime` starting at 0
walks `+ - - + + - - +` from the note -- the counter's path, a step a frame.
Nothing is divided by the multiplier here, so none of
`_classic_vibrato_entry`'s `_rate_shift` rounding (non-power-of-two multipliers)
or tick-0 compensation applies to a record this pass takes.

The instrument's own program (waveform, delay, waveform, ... , stop) keeps its
rows; the vibrato steps are merged into it on the call timeline at the same
lattice (the program's own events are whole frames apart). A step that lands on
a row of the program is put one call later. A waveform row that selects its
note with relative `+0` re-sets the note's frequency AND `vibtime`
(gplay.c:722-723), which would restart the swing at every waveform change; the
original's does not, so those rows say "no note" (`$80`) instead -- except a row
that OPENS the gate, an attack, which keeps its "+0" (Zoolook's `40 / 11`: the
program re-gates and must sound the note, not the last swing position; taking
that row off "+0" renamed 9 attacks on voice 0, melody 100% -> 95%).

**An odd bound is mirrored, and the lift for it is built but off.** The
player's swing is `-(b-1)/2 .. +(b+1)/2` depths around the note and
Goattracker's walk of `cmp = b - 2` is `-(b+1)/2 .. +(b-1)/2` (simulated over
`vibtime`, tests/test_vibrato_hold.py). A one-off `$F1` portamento up of one
depth (the same note-relative speed) on the call the vibrato starts puts the
swing on the player's side (`LIFT_ODD_BOUND`). Measured both ways over the 22
files it changes (-t 180 --sound, forced on; figures historical): Samantha_Fox,
whose records are bound 3, `tiefr` 74% -> 91% and `tie` 1.22x -> 1.02x; but
`aud` -0.015 summed (Zoolook .9209 -> .9154, Flash_Gordon .9286 -> .9249,
Thanatos .9482 -> .9457), and `bend` 1.18 -> 1.35 on Food_Feud. `aud` is the
column this module is for, so the lift ships off.

Taken only where the song's vibrato is this engine with none of the stretches
(`gate_skip`, `dwell`, `depth_extra`), the song is multispeed, the record's
bound is at least 2 (a one-frame half-period cannot be a held step: `cmp`
bottoms out at 0), its program is a straight line that ends in a stop and has no
pitch command of its own, and no pattern points the wavetable into it. A song
whose patterns command a vibrato of their own (`CMD_VIBRATO nn`, nn != 0:
Ricochet, Skate_or_Die_intro) is left whole, since the two would add. Everything
else keeps the per-call entry, byte for byte.

What is NOT carried: the original's counter is free-running (its phase at a
note is whatever the voice's history left, `goatwriter.vibrato`, "Phase"), ours
restarts at every note -- the second note of Thanatos' voice 0 swings down
first where ours swings up. A note that the duration-gate pass damped with
`CMD_VIBRATO 0` still steps (the command cannot stop a wavetable command row;
Deep_Strike carries 266 of them). And the depth is the interval ABOVE the note
shifted, the player's the one below: about +6% (`depth` 1.04-1.08 on every
file this takes).
"""
from typing import Callable, Dict, List, Optional, Tuple

from .detect import (Detection, VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     VIBRATO_SHIFT_MASK)
from .goatwriter import call_phase as _gw_call_phase
from .goatwriter import tempo as _gw_tempo
from .goatwriter.constants import (CMD_SETWAVEPTR, CMD_VIBRATO,
                                   GT_MAX_TABLELEN,
                                   GT_WAVE_FIRST_CMD, GT_WAVE_JUMP,
                                   GT_WAVE_LAST_CMD, GT_WAVE_LAST_DELAY,
                                   GT_WAVE_NO_NOTE, SPEED_NOTE_RELATIVE,
                                   VIBRATO_CMP_BIAS)
from .instrument_drop import _RECORD_LEN, _layout
from .sidfile import SidFile
from .unison_vibrato import _vibrato_byte

_WAVECMD_VIBRATO = GT_WAVE_FIRST_CMD + 4        # $F0 + CMD_VIBRATO
_WAVECMD_PORTAUP = GT_WAVE_FIRST_CMD + 1        # $F0 + CMD_PORTAUP
_STBL_AT, _VIBDELAY_AT, _WAVE_AT, _NAME_AT = 5, 6, 2, 9
_PLAIN_WAVE_LAST = 0xEF         # $10-$EF: waveform (with or without the gate)
LIFT_ODD_BOUND = False


def _read_tables(blob: bytes, tables_at: int, patt_at: int) -> List[List[Tuple[int, int]]]:
    pos = tables_at
    tables = []
    for _ in range(4):
        n = blob[pos]
        tables.append(list(zip(blob[pos + 1:pos + 1 + n],
                               blob[pos + 1 + n:pos + 1 + 2 * n])))
        pos += 1 + 2 * n
    assert pos == patt_at
    return tables


def _program(rows: List[Tuple[int, int]], start: int
             ) -> Optional[Tuple[Dict[int, Tuple[int, int]], int, int]]:
    """({call: row}, calls to the stop, last row index) of the straight-line
    program at 1-based `start`, or None where it loops, jumps out of the
    table or is not a plain sequence of waveform / command / delay rows."""
    events: Dict[int, Tuple[int, int]] = {}
    t, at = 0, start
    while True:
        if not 1 <= at <= len(rows):
            return None
        left, right = rows[at - 1]
        if left == GT_WAVE_JUMP:
            return (events, t, at) if right == 0 else None
        if left == 0:
            return None
        if left <= GT_WAVE_LAST_DELAY:
            t += left + 1
        else:
            events[t] = (left, right)
            t += 1
        at += 1


class _Unsupported(Exception):
    """A program the merge cannot lay out (a one-call gap with no waveform to
    repeat as a no-op)."""


def _held_rows(events: Dict[int, Tuple[int, int]], end_t: int, step_row,
               first: int, calls: int, first_row: int,
               centre_row: Optional[Tuple[int, int]] = None
               ) -> List[Tuple[int, int]]:
    """The rows of the merged program: `events` kept, a vibrato step on every
    lattice call from `first`, then the steady loop. `first_row` is the 1-based
    table index the first row will have (the loop's jump target).

    A wait of one call has no delay row (`d` holds `d + 1` calls, and `d` 0 is
    no delay), so it is the program's last waveform written again with "no
    note": the same value on the same voice, a no-op."""
    merged = dict(events)
    if centre_row is not None:
        u = first
        while u in merged:
            u += 1
        merged[u] = centre_row
    for t in range(first, end_t + calls, calls):
        u = t
        while u in merged:
            u += 1
        if u < t + calls:
            merged[u] = step_row
    last = max(merged) if merged else -1
    loop_t = first
    while loop_t <= last:
        loop_t += calls
    rows: List[Tuple[int, int]] = []
    wave: List[Optional[int]] = [None]

    def wait(gap: int):
        while gap > 0:
            if gap == 1:
                if wave[0] is None:
                    raise _Unsupported()
                rows.append((wave[0], GT_WAVE_NO_NOTE))
                return
            take = min(gap, GT_WAVE_LAST_DELAY + 1)
            if gap - take == 1:
                take -= 1
            rows.append((take - 1, GT_WAVE_NO_NOTE))
            gap -= take

    cur = 0
    for t in sorted(merged):
        wait(t - cur)
        row = merged[t]
        rows.append(row)
        if GT_WAVE_LAST_DELAY < row[0] <= _PLAIN_WAVE_LAST:
            wave[0] = row[0]
        cur = t + 1
    wait(loop_t - cur)
    loop_row = first_row + len(rows)
    rows.append(step_row)
    wait(calls - 1)
    rows.append((GT_WAVE_JUMP, loop_row))
    return rows


def effective_gate_skip(sid: SidFile) -> Optional[int]:
    """The outer gate's reload as `_vibrato_layout` receives it: only for a
    player `call_phase.entry_gate` accepts (Thanatos' gate reloads 4 but is
    not one, and its update runs every call)."""
    return (_gw_tempo.outer_gate_skip(sid)
            if _gw_call_phase.entry_gate(sid, dispatch=True) else None)


def hold_classic_vibrato(blob: bytes, sid: SidFile, det: Detection,
                         multiplier: int,
                         log: Optional[Callable[[str], None]] = None) -> bytes:
    """`blob` with each classic vibrato record's per-call entry replaced by a
    frame-held wavetable program (see the module docstring)."""
    if (multiplier < 2 or det.vibrato_offset is None
            or det.triangle_vibrato is not None
            or det.table_vibrato is not None or det.vibrato_dwell
            or det.vibrato_shift_extra or effective_gate_skip(sid)):
        return blob
    try:
        instr_at, tables_at, patt_at, pats = _layout(blob)
    except ValueError:
        return blob
    if bytes(blob[:4]) != b"GTS5":
        return blob
    wtbl, ptbl, ftbl, stbl = _read_tables(blob, tables_at, patt_at)
    count = blob[instr_at]
    recs = [bytearray(blob[instr_at + 1 + i * _RECORD_LEN:
                           instr_at + 1 + (i + 1) * _RECORD_LEN])
            for i in range(count)]
    # Wavetable pointers the patterns command: a record whose block one of
    # them enters keeps its per-call vibrato.
    pointed = set()
    for start, nrows in pats:
        for r in range(nrows):
            if blob[start + r * 4 + 2] == CMD_SETWAVEPTR:
                pointed.add(blob[start + r * 4 + 3])
    for start, nrows in pats:
        for r in range(nrows):
            if (blob[start + r * 4 + 2] == CMD_VIBRATO
                    and blob[start + r * 4 + 3]):
                return blob
    made: Dict[Tuple[int, int], int] = {}
    taken = 0
    for rec in recs:
        wptr, vptr = rec[_WAVE_AT], rec[_STBL_AT]
        byte = _vibrato_byte(bytes(rec[_NAME_AT:_RECORD_LEN]))
        if not wptr or not vptr or not byte or vptr > len(stbl):
            continue
        bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
        shift = byte & VIBRATO_SHIFT_MASK
        if bound < 2 or stbl[vptr - 1][0] < SPEED_NOTE_RELATIVE:
            continue
        key = (wptr, byte)
        if key not in made:
            prog = _program(wtbl, wptr)
            if prog is None:
                made[key] = 0
                continue
            events, end_t, last_row = prog
            if any(_WAVECMD_PORTAUP <= left <= _WAVECMD_VIBRATO
                   for left, _right in events.values()):
                made[key] = 0
                continue
            if any(wptr <= p <= last_row for p in pointed):
                made[key] = 0
                continue
            entry = (SPEED_NOTE_RELATIVE | (bound - VIBRATO_CMP_BIAS), shift)
            if entry not in stbl:
                stbl.append(entry)
            step = (_WAVECMD_VIBRATO, stbl.index(entry) + 1)
            centre = None
            if bound & 1 and LIFT_ODD_BOUND:
                # An odd bound is lopsided in the player (`-(b-1)/2 .. +(b+1)/2`
                # depths) and mirrored in ours (`-(b+1)/2 .. +(b-1)/2`): one
                # depth up, once, on the call the vibrato starts, puts the
                # swing on the player's side of the note.
                lift = (SPEED_NOTE_RELATIVE, shift)
                if lift not in stbl:
                    stbl.append(lift)
                centre = (_WAVECMD_PORTAUP, stbl.index(lift) + 1)
            # The record's own delay, in calls, rounded to the frame lattice
            # (the classic engine starts on the first call of frame 1 at the
            # earliest: `multiplier + 1`).
            delay = max(rec[_VIBDELAY_AT], 1)
            first = max(multiplier,
                        multiplier * round((delay - 1) / multiplier))
            kept = {}
            gate = None
            for t in sorted(events):
                left, right = events[t]
                if GT_WAVE_LAST_DELAY < left <= _PLAIN_WAVE_LAST:
                    # A row that opens the gate is an attack: it re-bases the
                    # pitch on the note (the program's own re-gate, Zoolook's
                    # `40 / 11`), so it keeps its "+0".
                    rising = bool(left & 1) and gate is not True
                    gate = bool(left & 1)
                    if t > 0 and right == 0 and not rising:
                        right = GT_WAVE_NO_NOTE
                kept[t] = (left, right)
            try:
                rows = _held_rows(kept, end_t, step, first, multiplier,
                                  len(wtbl) + 1, centre)
            except _Unsupported:
                made[key] = 0
                continue
            if len(wtbl) + len(rows) > GT_MAX_TABLELEN:
                made[key] = 0
                continue
            made[key] = len(wtbl) + 1
            wtbl.extend(rows)
        if made[key]:
            rec[_WAVE_AT] = made[key]
            rec[_STBL_AT] = 0
            rec[_VIBDELAY_AT] = 0
            taken += 1
    if not taken:
        return blob
    out = bytearray(blob[:instr_at + 1])
    for rec in recs:
        out += rec
    for table in (wtbl, ptbl, ftbl, stbl):
        out += bytes([len(table)])
        out += bytes(left for left, _right in table)
        out += bytes(right for _left, right in table)
    out += blob[patt_at:]
    if log:
        log(f"Frame-held vibrato......: {taken} record(s) as a wavetable "
            f"program stepping every {multiplier} calls "
            f"({len(set(v for v in made.values() if v))} program(s))")
    return bytes(out)
