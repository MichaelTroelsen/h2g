"""Bit $01's 8-bit drum sweep on the notes longer than the record's median.

The player's drum block (Monty `$82DE`, Warhawk `$1366`) subtracts one from the
frequency HIGH byte every call while the note's remaining-unit counter R sits
in `1 .. W-1` (W = `dur & $1F`), so a note of L = W + 1 units sweeps for
`L - 2` units, after the first unit's noise, and a note of two units not at
all. A Goattracker wavetable is per INSTRUMENT: `_drum_entries` writes ONE
sweep depth per record, from the MEDIAN note length
(`median_played_durations`). Monty's record 1 is played at four units (G-5,
440 plays) and two (G-6, G-7, 880 plays), whose median is two: no sweep at all,
and the four-unit note's three-frame `3426 -> 3126` fall never reaches the chip.

What is emitted, on the row after each drum note of three or more rows whose RECORD's
median note is shorter than three (`drum_long_plan`: its own program has
no sweep to extend): a `CMD_SETWAVEPTR` into a head -- the record's
waveform with the gate bit cleared, held for the `multiplier` calls of the
player's first sweeping frame (it stores the value it loaded: no change) --
then a jump into one shared chain of `CMD_PORTADOWN` steps ending in a stop,
entered `(L - 2) * row_calls - multiplier` entries before the stop.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, CMD_TONEPORTA, FORMAT_GTS5,
                        GT_FIRST_NOTE, GT_KEYOFF, GT_LAST_NOTE,
                        GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        GT_WAVE_NO_NOTE, WAVECMD_PORTADOWN)
from .counter_fall import _visits
from .drum_fall import DRUM_FALL_EXCLUDED, DRUM_FALL_FLOOR
from .primitives import _note_freq
from .wavetable import _drum_speed, _drum_speed_index

GT_END_PATTERN = 0xFF
# The arpeggio block runs after the drum and rewrites the frequency.
DRUM_LONG_EXCLUDED = DRUM_FALL_EXCLUDED | 0x04
MIN_UNITS = 3
# The jump into the chain costs no call, and the row's own first call already
# runs the head's first entry: one more hold lands the first decrement on the
# frame's last call + 1, where the player's second sweeping frame begins.
HOLD_EXTRA = 1


class DrumLongPlan:
    def __init__(self, patterns, entries, placed, declined):
        self.patterns = patterns
        self.entries = entries
        self.placed = placed
        self.declined = declined


def drum_long_records(sid: SidFile, det: Detection, records: int) -> Set[int]:
    out: Set[int] = set()
    data = sid.data
    vib = det.vibrato_offset
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(data):
            break
        fx = data[base + 7]
        if not fx & 0x01 or fx & DRUM_LONG_EXCLUDED:
            continue
        if vib is not None and data[base + vib]:
            continue
        out.add(i)
    return out


def drum_long_plan(sid: SidFile, det: Detection, tracks, patterns, lead: int,
                   instr_used: int, fmt: str, multiplier: int,
                   gate_skip: Optional[int], speed_table: List[tuple],
                   wave_used: int, row_calls: int,
                   note_rows: Optional[dict], log=None
                   ) -> Optional[DrumLongPlan]:
    # Calibrated at -S2 and above only: HOLD_EXTRA is a call, and at -S1 a call
    # is a whole frame -- Crazy_Comets (-S1, rows of 2.75 frames) lost 12 noise
    # frames to a head entered a frame early.
    if (not det.effect_drum or fmt != FORMAT_GTS5 or not note_rows
            or multiplier < 2):
        return None
    records = drum_long_records(sid, det, max(instr_used - lead, 0))
    if not records:
        return None
    numbers = {i + lead + 1 for i in records}
    m = max(1, multiplier)
    index = _drum_speed_index(fmt, speed_table, multiplier, gate_skip)
    if not index:
        return None
    hi, lo = _drum_speed(multiplier, gate_skip)
    step = (hi << 8) | lo
    low: Dict[int, int] = {}
    for track in tracks:
        for _pos, p, _k, trans in _visits(track, patterns):
            low[p] = min(low.get(p, trans), trans)
    declined: Dict[str, int] = {}

    def no(why: str) -> None:
        declined[why] = declined.get(why, 0) + 1

    data = sid.data
    gate_off = {i + lead + 1: (data[det.instr_start + i * det.instr_stride + 2]
                               & 0xFE) or 0x80 for i in records}
    asks: List[Tuple[int, int, int, int]] = []   # (pattern, row, wave, steps)
    for p, pat in enumerate(patterns):
        if p not in low:
            continue
        rows = [pat[r:r + 4] for r in range(0, len(pat) - 3, 4)]
        cur = 0
        for r, (note, ins, cmd, _dat) in enumerate(rows):
            if ins:
                cur = ins
            if not GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                continue
            if cur not in numbers:
                continue
            if not ins and r == 0:
                no("instrument not named")
                continue
            if cmd == CMD_TONEPORTA:
                no("tie")
                continue
            end = r + 1
            while (end < len(rows) and rows[end][0] in (GT_REST, GT_KEYOFF)
                   and not rows[end][1]):
                end += 1
            if end >= len(rows) or rows[end][0] == GT_END_PATTERN:
                no("length runs off the pattern")
                continue
            length = end - r
            if length < MIN_UNITS:
                no("shorter than three rows")
                continue
            med = note_rows.get(cur)
            if med is None or med >= MIN_UNITS or length <= med:
                no("the record's own program already sweeps")
                continue
            nxt = rows[r + 1]
            if nxt[2] or nxt[3]:
                no("command column taken")
                continue
            n = note - GT_FIRST_NOTE + low[p]
            freq = _note_freq(n)
            if freq < DRUM_FALL_FLOOR:
                no("no fall at this pitch")
                continue
            calls = (length - 2) * row_calls - m
            calls = min(calls, ((freq - DRUM_FALL_FLOOR) // 0x100 + 1) * m)
            if calls < 1:
                no("no fall at this pitch")
                continue
            asks.append((p, r + 1, gate_off[cur], calls))
    if not asks:
        if log and declined:
            log(f"Drum long sweep.........: 0 rows ({declined})")
        return None
    heads = sorted({(w, k) for _p, _r, w, k in asks})
    chain = max(k for _w, k in heads)
    room = GT_MAX_TABLELEN - wave_used - (m + 1 + HOLD_EXTRA) * len(heads) - 1
    if room < 0:
        return None
    chain = min(chain, room)
    first = wave_used + 1
    stop = first + chain
    entries: List[Tuple[int, int]] = (
        [(WAVECMD_PORTADOWN, index)] * chain + [(GT_WAVE_JUMP, 0x00)])
    at_head: Dict[Tuple[int, int], int] = {}
    for w, k in heads:
        at_head[(w, k)] = first + len(entries)
        entries += [(w, GT_WAVE_NO_NOTE)] * (m + HOLD_EXTRA)
        entries += [(GT_WAVE_JUMP, stop - min(k, chain))]
    out = [list(pat) for pat in patterns]
    for p, row, w, k in asks:
        at = row * 4
        out[p][at + 2] = CMD_SETWAVEPTR
        out[p][at + 3] = at_head[(w, k)]
    if log:
        log(f"Drum long sweep.........: {len(asks)} row(s), {len(heads)} "
            f"head(s) into a {chain}-step chain of ${step:04X} a call"
            + (f"; declined {declined}" if declined else ""))
    return DrumLongPlan(out, entries, len(asks), declined)
