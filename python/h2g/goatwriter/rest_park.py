"""`--rest-wave-silence` under a wavetable program: a parked twin to point at.

The option parks `$08` (test bit, no waveform, silence) in the voice on a
bit-6 rest with `CMD_SETWAVE $08` (gplay.c:433, `cptr->wave = data`). That
write survives only where the instrument's wavetable has STOPPED: `$FF 00`
zeroes `ptr[WTBL]` (gplay.c:709-711) and WAVEEXEC is guarded on that
pointer. A table still RUNNING -- a loop, or a program longer than the note --
executes WAVEEXEC on every call and its next waveform entry rewrites
`cptr->wave` (gplay.c:525, `if (wave < WAVESILENT) cptr->wave = wave`), so
the voice reads `$40` (pulse, gate off) across the rest. siddump names a note
on every voice whose waveform register is `$10` or more (siddump.c:449), so
each step of an arpeggio that keeps stepping prints as a tie, where the
original, parked at `$08` with ADSR `$0000`, prints a bare frequency and no
tie. Measured at 5fdcf5a (`runs.jsonl`, `our-silent-ties-surplus`): Nineteen
voice 0 carries 1447 such ties and Shockway_Rider's 1726.

The repair is a pointer, not a waveform: `CMD_SETWAVEPTR` (gplay.c:436-445)
to a two-row program of this file's own,

    E8 80      wave $08 (`wave & 0xf` of a "silent" entry, gplay.c:527), no note
    FF 00      stop

so the table runs once, on the SAME call (a KEYOFF row sets no `newnote`, so
WAVEEXEC follows the tick-0 effects, gplay.c:513), writes `$08` and ZEROES the
pointer. Nothing is left to overwrite it; the state is the one a stopped table
leaves after `CMD_SETWAVE`. One shared program serves every instrument: 2
wavetable rows in all, not a twin per instrument, because nothing in it
depends on the instrument. The pointer may not name an `$FF` row itself
(gplay.c:442-445 stops the song on a jump target); `E8` is a plain step.

**The next note restores everything.** A note row reloads `ptr[WTBL]` from the
instrument the channel holds (gplay.c:367, `cptr->ptr[WTBL] =
iptr->ptr[WTBL]`), and `instr 00` keeps the current instrument (gplay.c:914),
so a note after the rest, with or without an instrument column, restarts the
right table. The one row that does not is `CMD_TONEPORTA`, which skips the
branch (gplay.c:354) and so keeps the parked pointer; `CMD_SETWAVE` has the
same exposure, and `tests/test_rest_park.py` counts it on the corpus.

Only a rest whose live instrument HAS a wavetable program, or is not known, is
rewritten. A rest on an instrument with no program keeps `CMD_SETWAVE`, which
is sufficient there and is what it was before this pass; and a conversion with
no `CMD_SETWAVE $08` row (the option off, which is every shipped preset)
comes back unchanged, byte for byte, with no rows appended.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constants import (CMD_SETWAVEPTR, GT_MAX_TABLELEN, GT_WAVE_JUMP,
                        GT_WAVE_NO_NOTE)

# gcommon.h CMD_SETWAVE; `patterns.CMD_SETWAVE`. Local, as `goatwriter` does
# not import `patterns` (patterns imports it).
CMD_SETWAVE = 7
# patterns.REST_SILENT_WAVE.
REST_SILENT_WAVE = 0x08
# WAVESILENT ($E0) + the waveform nibble: gplay.c:527 writes `wave & 0xf`.
WAVE_SILENT_BASE = 0xE0

REST_PARK_PROGRAM: Tuple[Tuple[int, int], Tuple[int, int]] = (
    (WAVE_SILENT_BASE | REST_SILENT_WAVE, GT_WAVE_NO_NOTE),
    (GT_WAVE_JUMP, 0x00),
)


def rest_wave_rows(patterns: List[List[int]]) -> int:
    """How many `CMD_SETWAVE $08` rows the patterns hold."""
    n = 0
    for pat in patterns:
        for r in range(0, len(pat) - 3, 4):
            if pat[r] == 0xFF:
                break
            if pat[r + 2] == CMD_SETWAVE and pat[r + 3] == REST_SILENT_WAVE:
                n += 1
    return n


def programmed_instruments(starts: Dict[int, int]) -> frozenset:
    """The instrument numbers (keys of `starts`: number -> 1-based wavetable
    row, 0 = no program) that have a wavetable program at all.

    NOT only the programs that loop. A program that merely runs long is
    still running when a short note's rest arrives, and its next waveform
    entry overwrites the park exactly as a loop's does: Shockway_Rider, 180 s,
    presets plus `--rest-wave-silence`, 216 silent ties with the loops
    alone pointed and 189 with every instrument that has a program (Nineteen
    243 either way)."""
    return frozenset(n for n, s in starts.items() if s)


def rest_park_pass(patterns: List[List[int]], tracks: List[List[int]],
                   programmed: frozenset, park: int, log=None
                   ) -> List[List[int]]:
    """`CMD_SETWAVE $08` -> `CMD_SETWAVEPTR park` on each rest whose live
    instrument has a wavetable program (`programmed`), or is not known (a
    pattern reached holding more than one instrument, or none the walk can
    name).

    Declined, and counted: **no program** -- the live instrument has no
    wavetable pointer, so nothing can overwrite the park and `CMD_SETWAVE`
    already holds. Changed patterns are COPIES."""
    from .note_passes import _entry_instruments
    if not park or not programmed:
        return patterns
    entry = _entry_instruments(tracks, patterns)
    out: List[List[int]] = []
    placed = stopping = unknown = 0
    for number, pat in enumerate(patterns):
        cands = set(entry.get(number, ()))
        copy: Optional[List[int]] = None
        for r in range(0, len(pat) - 3, 4):
            if pat[r] == 0xFF:
                break
            if pat[r + 1]:
                cands = {pat[r + 1]}
            if pat[r + 2] != CMD_SETWAVE or pat[r + 3] != REST_SILENT_WAVE:
                continue
            if cands and not (cands & programmed):
                stopping += 1
                continue
            if len(cands) != 1:
                unknown += 1
            if copy is None:
                copy = list(pat)
            copy[r + 2] = CMD_SETWAVEPTR
            copy[r + 3] = park & 0xFF
            placed += 1
        out.append(pat if copy is None else copy)
    if log and (placed or stopping):
        log(f"Rest park...............: {placed} rest(s) point the wavetable "
            f"at the parked waveform ({unknown} of an instrument not yet "
            f"named)"
            + (f", {stopping} on an instrument with no program"
               if stopping else ""))
    return out


def rest_park_plan(patterns: List[List[int]], tracks: List[List[int]],
                   wave_entries: List[Tuple[int, int]],
                   starts: Dict[int, int], log=None
                   ) -> Tuple[List[List[int]], List[Tuple[int, int]]]:
    """(patterns, wave_entries) with the park program appended and the rests
    of looping instruments pointed at it. Unchanged where the patterns hold
    no `CMD_SETWAVE $08`, no instrument with a program, or the program would not fit
    the table."""
    if not rest_wave_rows(patterns):
        return patterns, wave_entries
    programmed = programmed_instruments(starts)
    if not programmed:
        return patterns, wave_entries
    park = len(wave_entries) + 1
    if park + len(REST_PARK_PROGRAM) - 1 > GT_MAX_TABLELEN or park > 0xFF:
        if log:
            log("Rest park...............: no room in the wavetable for the "
                "parked program; rests keep CMD_SETWAVE")
        return patterns, wave_entries
    new = rest_park_pass(patterns, tracks, programmed, park, log)
    if new is patterns or all(a is b for a, b in zip(new, patterns)):
        return patterns, wave_entries
    return new, wave_entries + list(REST_PARK_PROGRAM)
