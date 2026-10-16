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

**`--rest-program-stop` is the same pass restricted to the instruments whose
record selects the byte-code wave PROGRAM** (`only`). A bit-6 rest bypasses
that interpreter (`detect.wave_program_rest_bypass`), so its program stops at
the rest and the stored waveform stays at the `$08` the rest handler wrote --
and bypasses nothing else: IK+ voice 0, an arpeggio instrument, keeps stepping
across its rests (`$E388` is the arpeggio code) and re-writes the stored
waveform every frame, so parking it stops a table the original leaves
running. That is the cost `--rest-wave-silence` shows on IK+ (voice 0 `wave`
0.80 -> 0.58 against voice 1 0.40 -> 0.43, historical, v0.5.553). In this
mode a rest whose live instrument is not wholly a program instrument gets NO
command at all, instead of the `CMD_SETWAVE $08` the broader option would
leave there: the rows exist only because the pattern stage cannot name the
live instrument, and this pass is where it can.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constants import (CMD_SETAD, CMD_SETSR, CMD_SETTEMPO, CMD_SETWAVEPTR,
                        GT_KEYOFF, GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
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


def program_instruments(out, instr_at: int, written: int, gate: int,
                        arp_bit: bool = False) -> frozenset:
    """The instrument numbers (1-based) whose source record selects the
    byte-code wave program: the record's effect byte (`+7`, the third field of
    the name `NN:b5-b6-b7` every instrument is written with) has the program's
    gate bit set. An instrument that ALSO carries the arpeggio bit is left
    out -- the player's arpeggio code runs through a rest and re-writes the
    stored waveform, which is what a park would stop."""
    found = set()
    if not gate:
        return frozenset()
    for g in range(1, written + 1):
        raw = bytes(out[instr_at + 1 + (g - 1) * 25 + 9:
                        instr_at + 1 + g * 25]).split(b"\x00")[0]
        parts = raw.decode("latin-1", "replace").strip().partition(":")[2]
        fields = parts.split("-")
        if len(fields) != 3:
            continue
        try:
            b7 = int(fields[2], 16)
        except ValueError:
            continue
        if b7 & gate and not (arp_bit and b7 & 0x04):
            found.add(g)
    return frozenset(found)


def rest_park_pass(patterns: List[List[int]], tracks: List[List[int]],
                   programmed: frozenset, park: int, log=None,
                   only: Optional[frozenset] = None
                   ) -> List[List[int]]:
    """`CMD_SETWAVE $08` -> `CMD_SETWAVEPTR park` on each rest whose live
    instrument has a wavetable program (`programmed`), or is not known (a
    pattern reached holding more than one instrument, or none the walk can
    name).

    Declined, and counted: **no program** -- the live instrument has no
    wavetable pointer, so nothing can overwrite the park and `CMD_SETWAVE`
    already holds. Changed patterns are COPIES."""
    from .note_passes import _entry_instruments
    if only is None and (not park or not programmed):
        return patterns
    entry = _entry_instruments(tracks, patterns)
    out: List[List[int]] = []
    placed = stopping = unknown = cleared = 0
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
            if only is not None:
                # Program-stop mode: stop a rest whose live instrument is
                # KNOWN and is wholly a program instrument; leave every
                # other rest the plain KEYOFF an arpeggio instrument wants
                # (see the module docstring).
                if copy is None:
                    copy = list(pat)
                if park and cands and cands <= only:
                    copy[r + 2] = CMD_SETWAVEPTR
                    copy[r + 3] = park & 0xFF
                    placed += 1
                else:
                    copy[r + 2] = 0
                    copy[r + 3] = 0
                    cleared += 1
                    # `--rest-envelope-silence` beside it: the pattern stage
                    # put the SETWAVE on hold row 0 and pushed the envelope's
                    # `CMD_SETAD $00` to hold row 1 (dropping it altogether
                    # on a one-hold-row rest). This rest keeps no SETWAVE, so
                    # the AD goes back to hold row 0, where the envelope
                    # option alone has it: a rest this option does not stop
                    # is the conversion it would be without it.
                    if (pat[r] == GT_REST and r >= 4
                            and pat[r - 4] == GT_KEYOFF
                            and pat[r - 2] == CMD_SETSR and pat[r - 1] == 0):
                        copy[r + 2] = CMD_SETAD
                        nxt = r + 4
                        if (nxt + 3 < len(copy) and copy[nxt] == GT_REST
                                and copy[nxt + 2] == CMD_SETAD
                                and copy[nxt + 3] == 0):
                            copy[nxt + 2] = 0
                    # ...and a pattern opening on a rest, whose row 0 the
                    # tempo took: the envelope's SETSR went to hold row 0 and
                    # its AD to hold row 1, and the SETWAVE displaced the
                    # SETSR. Give the SETSR back; the AD stays where it is.
                    elif (pat[r] == GT_REST and r >= 4
                          and pat[r - 4] == GT_KEYOFF
                          and pat[r - 2] == CMD_SETTEMPO
                          and r + 7 < len(copy) and copy[r + 4] == GT_REST
                          and copy[r + 6] == CMD_SETAD and copy[r + 7] == 0):
                        copy[r + 2] = CMD_SETSR
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
    if log and only is not None and (placed or cleared):
        log(f"Rest program stop.......: {placed} rest(s) of a wave-program "
            f"instrument stop its program, {cleared} left a plain key-off")
    elif log and (placed or stopping):
        log(f"Rest park...............: {placed} rest(s) point the wavetable "
            f"at the parked waveform ({unknown} of an instrument not yet "
            f"named)"
            + (f", {stopping} on an instrument with no program"
               if stopping else ""))
    return out


def rest_park_plan(patterns: List[List[int]], tracks: List[List[int]],
                   wave_entries: List[Tuple[int, int]],
                   starts: Dict[int, int], log=None,
                   only: Optional[frozenset] = None
                   ) -> Tuple[List[List[int]], List[Tuple[int, int]]]:
    """(patterns, wave_entries) with the park program appended and the rests
    of looping instruments pointed at it. Unchanged where the patterns hold
    no `CMD_SETWAVE $08`, no instrument with a program, or the program would not fit
    the table."""
    if not rest_wave_rows(patterns):
        return patterns, wave_entries
    programmed = programmed_instruments(starts)
    if only is not None:
        # `--rest-program-stop`: `only` are the instruments whose record
        # selects the byte-code program. The parked program is appended
        # only if a rest actually points at it.
        only = frozenset(only) & programmed
        park = len(wave_entries) + 1
        if park + len(REST_PARK_PROGRAM) - 1 > GT_MAX_TABLELEN or park > 0xFF:
            if only and log:
                log("Rest program stop.......: no room in the wavetable for "
                    "the parked program; rests keep a plain key-off")
            park = 0
        new = rest_park_pass(patterns, tracks, programmed,
                             park if only else 0, log, only)
        used = bool(park and only) and any(
            pat[r + 2] == CMD_SETWAVEPTR and pat[r + 3] == (park & 0xFF)
            for pat in new for r in range(0, len(pat) - 3, 4)
            if pat[r] != 0xFF)
        return new, (wave_entries + list(REST_PARK_PROGRAM) if used
                     else wave_entries)
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
