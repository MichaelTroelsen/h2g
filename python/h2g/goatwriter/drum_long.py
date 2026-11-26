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

**-S1** (Geoff_Capes_Strongman_Challenge, rows of 3 calls): the same plan with
two differences. The decline is not the record's MEDIAN but its own program's
sweep -- the `CMD_PORTADOWN` entries `_drum_entries` laid, two at most on the
five-entry layout (`own_sweep`) -- against what THIS note leaves the player
room for (`(L - 2) * row_calls - 1` frames: a four-row note is Commando's five
steps, an eight-row one runs to the high byte's floor); Geoff's records are
played at four rows and eight, so every note after the first two steps went
unswept. And the head opens on the noise the row's first call lands in: the
row after the drum note starts `row_calls - 1` frames after the attack's
visible frame (the init call writes only `$D404`), the noise tick runs
`_noise_tick_frames` frames from the one after it, so the first `tick -
(row_calls - 2)` calls of the head are still the noise. `drum_fall_loop` is
not planned at -S1.

Not calibrated for rows that are not a whole number of frames, and off by
default per song for that reason: forced on (v0.5.674, `-t 180`, presets,
`--sound`) Crazy_Comets (-S1, rows of 2.75 frames) reads depth .767 -> .673,
travel .991 -> 1.084, aud .9251 -> .9240; Human_Race aud .9193 -> .9185;
Chimera tie .756 -> .745. Geoff_Capes is the file it was built for.
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
from .constants import DRUM_MAX_SWEEP_STEPS
from .primitives import _gate_calls, _note_freq
from .wavetable import (_drum_speed, _drum_speed_index, _drum_tick_noise,
                        _noise_tick_frames)

GT_END_PATTERN = 0xFF
# Where a record's own program stops reading for `own_sweep`.
OWN_SWEEP_WINDOW = 24
# The arpeggio block runs after the drum and rewrites the frequency.
DRUM_LONG_EXCLUDED = DRUM_FALL_EXCLUDED | 0x04
MIN_UNITS = 3
# The jump into the chain costs no call, and the row's own first call already
# runs the head's first entry: one more hold lands the first decrement on the
# frame's last call + 1, where the player's second sweeping frame begins.
HOLD_EXTRA = 1
# A note's fall is carried on the loop only where it is at least this many
# QUARTERS of what the record's own program holds (`_long_fall`): 6 is one and
# a half times. A fall a few calls past the cap is not worth replacing the
# program's own noise tick and sweep. Measured at 1c9d17c, `drum_fall_loop`
# forced: Battle_of_Britain's 22-call falls (1.4x the 16-call cap) cost its
# drum a noise frame (onset 100% -> 92%, wave 100% -> 99%); Formula_1_Simulator's
# six 28-call falls (1.75x) are measured gains.
LONG_FALL_QUARTERS = 6


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


def own_sweep(entries: List[tuple], start: int) -> int:
    """`CMD_PORTADOWN` steps the record's own wavetable program (laid by
    `_drum_entries`) takes from wavetable row `start`, 1-based, until its stop
    or jump; 0 where the program is unknown."""
    if not entries or start < 1:
        return 0
    n = 0
    for left, _right in entries[start - 1:start - 1 + OWN_SWEEP_WINDOW]:
        if left == WAVECMD_PORTADOWN:
            n += 1
        elif left == GT_END_PATTERN or left == GT_WAVE_JUMP:
            break
    return n


def drum_long_plan(sid: SidFile, det: Detection, tracks, patterns, lead: int,
                   instr_used: int, fmt: str, multiplier: int,
                   gate_skip: Optional[int], speed_table: List[tuple],
                   wave_used: int, row_calls: int,
                   note_rows: Optional[dict], log=None,
                   plain: bool = True, loop: bool = False,
                   wave_entries: Optional[List[tuple]] = None,
                   wave_starts: Optional[List[int]] = None,
                   play_groups: Optional[dict] = None
                   ) -> Optional[DrumLongPlan]:
    # -S1 needs the record's own program (`own_sweep`), so it is planned only
    # where the caller hands the table over, and without the loop half.
    if (not det.effect_drum or fmt != FORMAT_GTS5 or not note_rows
            or multiplier < 1
            or (multiplier < 2 and (wave_entries is None
                                    or wave_starts is None))):
        return None
    if multiplier < 2:
        loop = False
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
    noise = {i + lead + 1: _drum_tick_noise(
        data[det.instr_start + i * det.instr_stride + 2], multiplier)
        for i in records}
    # -S1: how many of the head's calls are still the noise tick, per record
    # (its own subtunes' speed gate, as the table's tick is sized).
    lead_noise: Dict[int, int] = {}
    own: Dict[int, int] = {}
    if multiplier < 2:
        for g in numbers:
            tick = _noise_tick_frames(sid, det, (play_groups or {}).get(g))
            lead_noise[gate_off[g]] = max(
                0, min(tick - (row_calls - 2), m + HOLD_EXTRA - 1))
            own[g] = (own_sweep(wave_entries, wave_starts[g - 1])
                      if 0 < g <= len(wave_starts) else 0)
    asks: List[Tuple[int, int, int, int]] = []   # (pattern, row, wave, steps)
    # (pattern, head row, stop row or None, calls, wave): a note the record's
    # own program cannot carry the whole fall of (`_long_fall`).
    loops: List[Tuple[int, int, Optional[int], int, int]] = []
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
            med = note_rows.get(cur)
            if (loop and med is not None and med >= MIN_UNITS
                    and end - r >= MIN_UNITS):
                # A record whose own program carries a sweep: only a note
                # that outlasts `_drum_max_steps`' cap needs more
                # (`_long_fall`). It may run off its pattern: the fall is
                # bound by the pitch, and the stop row only by the rows.
                ask = _long_fall(rows, r, end, note, low[p], row_calls, m,
                                 step, gate_skip, no)
                if ask is not None:
                    loops.append((p,) + ask + (gate_off[cur],))
                continue
            if not plain:
                continue
            if end >= len(rows) or rows[end][0] == GT_END_PATTERN:
                no("length runs off the pattern")
                continue
            length = end - r
            if length < MIN_UNITS:
                no("shorter than three rows")
                continue
            if multiplier >= 2:
                if med is None or med >= MIN_UNITS or length <= med:
                    no("the record's own program already sweeps")
                    continue
            elif med is None:
                no("record's length unmeasured")
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
            if multiplier < 2 and calls <= own.get(cur, 0):
                no("the record's own program already sweeps")
                continue
            asks.append((p, r + 1, gate_off[cur], calls))
    if not asks and not loops:
        if log and declined:
            log(f"Drum long sweep.........: 0 rows ({declined})")
        return None
    noise_of = {gate_off[g]: noise[g] for g in numbers if g in noise}
    entries: List[Tuple[int, int]] = []
    first = wave_used + 1
    at_head: Dict[Tuple[int, int], int] = {}
    chain = 0
    if asks:
        heads = sorted({(w, k) for _p, _r, w, k in asks})
        chain = max(k for _w, k in heads)
        room = (GT_MAX_TABLELEN - wave_used
                - (m + 1 + HOLD_EXTRA) * len(heads) - 1)
        if room < 0:
            return None
        chain = min(chain, room)
        stop = first + chain
        entries = ([(WAVECMD_PORTADOWN, index)] * chain
                   + [(GT_WAVE_JUMP, 0x00)])
        for w, k in heads:
            at_head[(w, k)] = first + len(entries)
            ln = lead_noise.get(w, 0)
            entries += [(noise_of.get(w, w), GT_WAVE_NO_NOTE)] * ln
            entries += [(w, GT_WAVE_NO_NOTE)] * (m + HOLD_EXTRA - ln)
            entries += [(GT_WAVE_JUMP, stop - min(k, chain))]
    out = [list(pat) for pat in patterns]
    for p, row, w, k in asks:
        at = row * 4
        out[p][at + 2] = CMD_SETWAVEPTR
        out[p][at + 3] = at_head[(w, k)]
    placed_loops = 0
    if loops:
        # One shared two-entry loop (a PORTADOWN that jumps back to itself:
        # a step a call for as long as the voice runs it), a head per
        # waveform that holds the gate-off waveform and falls into it, and a
        # stop per waveform: a held entry, then the table's end. The fall's
        # LENGTH is the row the stop is written on, not the table: a chain
        # of the whole fall is `calls` entries, 216 on Formula_1_Simulator
        # against the 56 its 199-entry table has left.
        waves = sorted({lw for *_x, lw in loops})
        need = 2 + (m + HOLD_EXTRA + 1 + 2) * len(waves)
        if wave_used + len(entries) + need <= GT_MAX_TABLELEN:
            loop_at = first + len(entries)
            entries += [(WAVECMD_PORTADOWN, index),
                        (GT_WAVE_JUMP, loop_at)]
            heads_l: Dict[int, int] = {}
            stops_l: Dict[int, int] = {}
            for w in waves:
                heads_l[w] = first + len(entries)
                entries += [(w, GT_WAVE_NO_NOTE)] * (m + HOLD_EXTRA)
                entries += [(GT_WAVE_JUMP, loop_at)]
                stops_l[w] = first + len(entries)
                entries += [(w, GT_WAVE_NO_NOTE), (GT_WAVE_JUMP, 0x00)]
            for p, head_row, stop_row, _calls, w in loops:
                at = head_row * 4
                out[p][at + 2] = CMD_SETWAVEPTR
                out[p][at + 3] = heads_l[w]
                if stop_row is not None:
                    at = stop_row * 4
                    out[p][at + 2] = CMD_SETWAVEPTR
                    out[p][at + 3] = stops_l[w]
                placed_loops += 1
        else:
            no("no wavetable room for the long fall's loop")
    if not asks and not placed_loops:
        if log and declined:
            log(f"Drum long sweep.........: 0 rows ({declined})")
        return None
    if log:
        log(f"Drum long sweep.........: {len(asks)} row(s) into a "
            f"{chain}-step chain of ${step:04X} a call, {placed_loops} "
            f"long fall(s) on a loop"
            + (f"; declined {declined}" if declined else ""))
    return DrumLongPlan(out, entries, len(asks) + placed_loops, declined)


def _long_fall(rows, r: int, end: int, note: int, low: int, row_calls: int,
               m: int, step: int, gate_skip: Optional[int], no):
    """(head row, stop row or None, calls) for a drum note whose fall is
    longer than the record's own program can carry, else None.

    The player sweeps while the frequency high byte is non-zero and the note
    lasts (`_drum_entries`), so the fall is the smaller of the two bounds.
    `_drum_max_steps` caps the record's program at `DRUM_MAX_SWEEP_STEPS`
    player frames; past that the table room is gone, not the fall
    (Formula_1_Simulator's record 10: E-6 `$57AC` falls to `$01AC` over 115
    frames in the original and over 8 in ours).
    """
    if step <= 0 or r + 1 >= len(rows):
        return None
    head = r + 1
    if rows[head][2] or rows[head][3]:
        no("command column taken")
        return None
    freq = _note_freq(note - GT_FIRST_NOTE + low)
    if freq < DRUM_FALL_FLOOR:
        no("no fall at this pitch")
        return None
    pitch_calls = (freq - DRUM_FALL_FLOOR) // step
    note_calls = (end - r - 2) * row_calls - m
    calls = min(pitch_calls, note_calls)
    own = DRUM_MAX_SWEEP_STEPS * _gate_calls(m, gate_skip)
    if calls * 4 < LONG_FALL_QUARTERS * own:
        no("the record's own program already sweeps")
        return None
    stop = head + (m + HOLD_EXTRA + calls) // row_calls
    if stop < end:
        if rows[stop][2] or rows[stop][3]:
            no("command column taken")
            return None
        return head, stop, calls
    if end >= len(rows) or rows[end][0] == GT_END_PATTERN:
        no("stop row runs off the pattern")
        return None
    # The next note's own program replaces the loop.
    return head, None, calls
