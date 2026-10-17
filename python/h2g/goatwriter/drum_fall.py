"""Bit $01's 16-bit drum fall (detect._find_drum_fall16) as per-row programs.

Tarzan `$57EA`: from the first frame of a note's SECOND tick the voice's
frequency falls `det.drum_fall_step` ($0080) a frame, with the gate masked
off, until the note ends or the high byte reaches zero. Where it starts is a
tick boundary, and the tick is a pattern ROW here (one row per tick), so it
is placed by row rather than by a per-instrument wavetable delay: Tarzan's
subtunes tick at 1-5 frames (the start offset of the fall measured on the
original: 3 in subtunes 0/1/8, 2 in 5, 5 in 6 and 10), which no single
delay in an instrument's table can say.

What is emitted, on the row after each qualifying note row (`drum_fall_plan`):
a `CMD_SETWAVEPTR` into a short head -- the record's waveform with the gate
bit cleared and the frequency kept (the player's `gatemask = $FE`, on the
fall's first frame), then one `F2` of two steps (the decrement the head could
not carry, and the next) -- which jumps into one shared chain of `F2 step`
entries ending in a stop. A wavetable command runs on every play call but a
new note's first (player.s `mt_waveexec`; tick 0 without a new note
included, unlike a pattern portamento under gt2reloc's default realtime
optimization), so the fall is the player's frame for frame from its second
frame on, and its first frame is one step high. The head enters the chain
`calls - 2` entries before its stop, `calls` being how far the player's own
`LDA freqhi / BEQ out` lets the LOWEST pitch this row is played at fall
(`fall_steps`): a Goattracker portamento has no such floor and would wrap
through $0000 into a squeal. A shorter note is cut off by its next note,
which reloads the instrument's table. Heads are shared by (waveform, calls).

Declined, and counted in the log line: a note whose next row is not free
(a note, or a command already there), a note of one row (its fall starts on
frame 1, inside the note's own row), a tie (`CMD_TONEPORTA`), a row whose
instrument the pattern does not name, a record whose fall a later block
overwrites (`drum_fall_records`), and GTS2 (no speed table).
The rate is per play call: `step // multiplier` on each of the frame's
`multiplier` calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, CMD_TONEPORTA, FORMAT_GTS5,
                        GT_FIRST_NOTE, GT_KEYOFF, GT_LAST_NOTE,
                        GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        GT_WAVE_NO_NOTE,
                        WAVECMD_PORTADOWN)
from .counter_fall import _visits
from .primitives import _note_freq

# Effect bits whose blocks run after the fall and rewrite the frequency
# shadows or the waveform cell every frame (Tarzan: $02 the waveform
# alternation $581F, $08 the note alternation $5857, $40 the fixed pitch /
# re-assert $589D), or that this dialect does not read ($10, $80).
DRUM_FALL_EXCLUDED = 0x02 | 0x08 | 0x10 | 0x40 | 0x80
# The block stops once the high byte is zero: it subtracts while hi != 0.
DRUM_FALL_FLOOR = 0x100
# Longest note a row is assumed to hold, in frames per row, for the chain
# length only: an over-long chain costs table rows, never pitch.
DRUM_FALL_ROW_FRAMES = 8


@dataclass
class DrumFallPlan:
    patterns: List[List[int]]
    entries: List[Tuple[int, int]]
    placed: int
    declined: Dict[str, int]


def drum_fall_records(sid: SidFile, det: Detection, records: int) -> Set[int]:
    """0-based records whose fall reaches the chip: bit $01 set, no later
    block rewriting the shadows, and no vibrato byte (the vibrato block
    writes the frequency before the fall subtracts from it)."""
    out: Set[int] = set()
    if not det.drum_fall_step:
        return out
    data = sid.data
    vib = det.vibrato_offset
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(data):
            break
        fx = data[base + 7]
        if not fx & 0x01 or fx & DRUM_FALL_EXCLUDED:
            continue
        if vib is not None and data[base + vib]:
            continue
        out.add(i)
    return out


def fall_steps(freq: int, step: int) -> int:
    """Frames the player falls from `freq` before its high byte is zero."""
    if freq < DRUM_FALL_FLOOR or step <= 0:
        return 0
    return (freq - DRUM_FALL_FLOOR) // step + 1


def drum_fall_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                   patterns: List[List[int]], lead: int, instr_used: int,
                   fmt: str, multiplier: int, gate_skip: Optional[int],
                   speed_table: List[tuple], wave_used: int,
                   log=None) -> Optional[DrumFallPlan]:
    if not det.drum_fall_step:
        return None
    records = drum_fall_records(sid, det, max(instr_used - lead, 0))
    if not records:
        return None
    # **No outer-gate divisor**, unlike `_drum_speed`'s Warhawk block: this
    # player's skip ($555B `DEC $59F6 / BPL`, reload `#$0B`) only holds the
    # TICK counter `$59DE` for a frame and then runs every voice's effects as
    # on any other frame ($5573), the fall included, so it falls on every
    # frame and the rate is the player's per frame over `multiplier` calls.
    if fmt != FORMAT_GTS5:
        if log:
            log("Drum fall...............: not emitted (GTS2 stores no "
                "speed table)")
        return None
    numbers = {i + lead + 1 for i in records}
    m = max(1, multiplier)
    step = max(1, det.drum_fall_step // m)

    # The lowest transpose each pattern is played at.
    low: Dict[int, int] = {}
    for track in tracks:
        for _pos, p, _k, trans in _visits(track, patterns):
            low[p] = min(low.get(p, trans), trans)

    declined: Dict[str, int] = {}

    def no(why: str) -> None:
        declined[why] = declined.get(why, 0) + 1

    data = sid.data
    gate_off = {i + lead + 1: data[det.instr_start + i * det.instr_stride + 2]
                & 0xFE for i in records}
    asks: List[Tuple[int, int, int, int]] = []   # (pattern, row, wave, calls)
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
            nxt = rows[r + 1] if r + 1 < len(rows) else None
            if nxt is None or nxt[0] not in (GT_REST, GT_KEYOFF) or nxt[1]:
                no("one row")
                continue
            if nxt[2] or nxt[3]:
                no("command column taken")
                continue
            end = r + 1
            while end < len(rows) and rows[end][0] in (GT_REST, GT_KEYOFF):
                end += 1
            n = note - GT_FIRST_NOTE + low[p]
            k = fall_steps(_note_freq(n), det.drum_fall_step) * m
            k = min(k, (end - r) * DRUM_FALL_ROW_FRAMES * m)
            if k < 2:
                no("no fall at this pitch")
                continue
            asks.append((p, r + 1, gate_off[cur], k))
    if not asks:
        if log and declined:
            log(f"Drum fall...............: 0 rows ({declined})")
        return None

    def speed(value: int) -> Optional[int]:
        entry = ((value >> 8) & 0xFF, value & 0xFF)
        if entry not in speed_table:
            if len(speed_table) >= GT_MAX_TABLELEN:
                return None
            speed_table.append(entry)
        return speed_table.index(entry) + 1

    one, two = speed(step), speed(2 * step)
    if one is None or two is None:
        return None
    # The program a row points at is a HEAD, `(wave & $FE, $80)` -- the
    # gate off, on the fall's first call, with the frequency kept -- then
    # one `F2` of two steps (the first call's decrement, which the head
    # could not carry, and the second's), then a jump into a shared chain of
    # single steps `calls - 2` entries before its stop. A gate-off KEYOFF on
    # the row would have been cheaper and was measured two frames early
    # (Tarzan voice 3, subtune 0: gate off from frame 1 of every hit where
    # the player holds it to frame 3); why the packed player applies it
    # there was not traced.
    heads = sorted({(w, k) for _p, _r, w, k in asks})
    chain = max(k for _w, k in heads) - 2
    room = GT_MAX_TABLELEN - wave_used - 3 * len(heads) - 1
    if room < 0:
        if log:
            log("Drum fall...............: no wavetable room")
        return None
    chain = min(chain, room)
    first = wave_used + 1                           # 1-based row of entry 0
    stop = first + chain                            # the chain's stop row
    entries: List[Tuple[int, int]] = (
        [(WAVECMD_PORTADOWN, one)] * chain + [(GT_WAVE_JUMP, 0x00)])
    at_head: Dict[Tuple[int, int], int] = {}
    for w, k in heads:
        at_head[(w, k)] = first + len(entries)
        entries += [(w, GT_WAVE_NO_NOTE), (WAVECMD_PORTADOWN, two),
                    (GT_WAVE_JUMP, stop - min(k - 2, chain))]

    out = [list(pat) for pat in patterns]
    for p, row, w, k in asks:
        at = row * 4
        out[p][at + 2] = CMD_SETWAVEPTR
        out[p][at + 3] = at_head[(w, k)]
    if log:
        log(f"Drum fall...............: {len(asks)} row(s), {len(heads)} "
            f"head(s) into a {chain}-step chain of ${step:04X} a call"
            + (f"; declined {declined}" if declined else ""))
    return DrumFallPlan(out, entries, len(asks), declined)
