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

**A looping program can be stepped silently instead of stopped: the twin
(`--rest-park-twin`).** The original's rest does NOT stop a pitch loop of the
record (I_Ball's instrument 3: base note, base note, +24 semitones, period 3):
the player keeps stepping it with the voice at wave `$08`, ADSR `$0000`, so its
frequency register keeps reversing across the rest, and the stop program
freezes it where the park lands. A rest whose live instrument is a single
KNOWN instrument with a LOOPING program is then pointed at a copy of the
loop body, its waveform column made `$E8` (silent, gplay.c:527: the voice
reads `$08`, below siddump's note threshold, so no tie is brought back), its
delay entries and its note column kept, closed by its own `FF <first row>`.
Under `--rest-envelope-silence` the copy opens on one `CMD_SETSR $00` row that
runs once (the `FF` jumps past it) and the AD stays on the rest's hold row. A
loop with a command row, or one that opens on a delay (a delay entry compares
against a `wavetime` the old table leaves wherever it was, gplay.c:697-704),
keeps the stop program. Twins are keyed by body, so instruments that share a
loop share the rows, and only those a rest points at are appended. Measured
(I_Ball, `-t 180`, v0.5.685, historical): the stop program costs vib 1.0056 ->
.9438, the twin .9943.

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
                        GT_WAVE_NO_NOTE, WAVECMD_BASE)

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

# The park with the bit-6 rest's other half (`--rest-wave-silence` beside
# `--rest-envelope-silence`): the original's rest handler writes the stored
# waveform `$08` AND zeroes SR and AD on ONE call (Thundercats `$EE38`:
# `STA $D406,Y / STA $D405,Y / LDA #$08 / JMP`, Auf_Wiedersehen_Monty
# `$E543`), so the three writes land on the same frame. Pattern rows carry
# one command each and a row is `tempo + 1` calls, so the pattern spelling
# lands them 3 rows apart; a wavetable program runs one row per CALL
# (gplay.c:520-540, a `$Fx` command row executes `CMD_SETSR`/`CMD_SETAD` from
# the table, gplay.c:545-585), which at `-S3` is the same frame.
REST_PARK_ENV_PROGRAM: Tuple[Tuple[int, int], ...] = (
    (WAVECMD_BASE | CMD_SETSR, 0x00),
    (WAVE_SILENT_BASE | REST_SILENT_WAVE, GT_WAVE_NO_NOTE),
    (GT_WAVE_JUMP, 0x00),
)

# The same program with the AD as a THIRD row: SR on the row's own call, the
# park on the next, the AD on the one after -- one call behind the park
# instead of a whole pattern row (the hold-row AD, 4 frames at IK_plus). Used
# only for a rest whose live instrument has NO vibrato pointer: a `$Fx` row
# on a tick-N call skips that call's tick-N effects (gplay.c:711-712, `goto
# PULSEEXEC`) and the instrument's vibrato is one of them, so the second
# command row costs a vibrato step. SR alone in the program is the call-0
# row, whose tick-N effects are skipped anyway (`optimizerealtime`,
# gplay.c:731). Measured 2026-11-16 (`vibrato_instruments`; the tests'
# header has the figures).
REST_PARK_ENV_FULL_PROGRAM: Tuple[Tuple[int, int], ...] = (
    (WAVECMD_BASE | CMD_SETSR, 0x00),
    (WAVE_SILENT_BASE | REST_SILENT_WAVE, GT_WAVE_NO_NOTE),
    (WAVECMD_BASE | CMD_SETAD, 0x00),
    (GT_WAVE_JUMP, 0x00),
)

# A delay entry of 0 holds ONE call (gplay.c:697-704, a delay entry is current
# for `value + 1` calls) and writes nothing. Placed in front of the park it
# lets the park land one call later; see `lagged_instruments`.
REST_PARK_DELAY: Tuple[int, int] = (0x00, GT_WAVE_NO_NOTE)

# (rows, index of the row the closing `FF` jumps back to)
TwinBody = Tuple[Tuple[Tuple[int, int], ...], int]


def twin_loops(entries: List[Tuple[int, int]], starts: Dict[int, int]
               ) -> Dict[int, TwinBody]:
    """Instrument number -> silent twin of its program's LOOP, for every
    instrument whose program loops (see "the twin" in the module docstring).

    `entries` is the 1-based wavetable as (left, right) rows, `starts` the
    instrument's first row (0 = no program). The program is WALKED from its
    start the way the player runs it, following each `FF <target>`; the loop
    is the cycle the walk first closes (an instrument's own tail, or a tail
    shared with other instruments that its `FF` jumps into). A walk that
    reaches a stop (`FF 00`), leaves the table or sits on an `FF` row it
    already followed is not a loop.

    The twin of the cycle: every waveform entry (left `$10`-`$EF`) becomes
    `$E8`; delays (left `$00`-`$0F`, which still write their note column when
    they expire) and the note column are kept. A cycle that BEGINS on a delay
    is declined (a delay entry compares against a `wavetime` the old table
    leaves wherever it was, gplay.c:697-704, and Shockway_Rider's twin of such
    a loop stepped a note pitch onto its hard-restart frame: runs.jsonl
    `rest-park-silent-stepping-twin-i-ball`), as is a cycle with a command row
    (`$F0`-`$FE`): a command executed under a rest is an effect the original
    did not run there."""
    out: Dict[int, TwinBody] = {}
    n = len(entries)
    for g, s in starts.items():
        if not s or s > n:
            continue
        path: List[int] = []
        at: Dict[int, int] = {}
        followed = set()
        pos, cycle = s, None
        while 1 <= pos <= n:
            if pos in at:
                cycle = at[pos]
                break
            left, right = entries[pos - 1]
            if left == GT_WAVE_JUMP:
                if not right or pos in followed:
                    break
                followed.add(pos)
                pos = right
                continue
            at[pos] = len(path)
            path.append(pos)
            pos += 1
        if cycle is None:
            continue
        body = [entries[p - 1] for p in path[cycle:]]
        if any(0xF0 <= left <= 0xFE for left, _ in body):
            continue
        rows = [(WAVE_SILENT_BASE | REST_SILENT_WAVE, note)
                if 0x10 <= left < 0xF0 else (left, note)
                for left, note in body]
        if rows[0][0] <= 0x0F:
            continue
        out[g] = (tuple(rows), 0)
    return out


def twin_layout(loops: Dict[int, TwinBody], used, base: int,
                prefix: Tuple[Tuple[int, int], ...] = ()
                ) -> Tuple[Dict[int, int], List[Tuple[int, int]]]:
    """(pointer by instrument, rows to append) for the instruments in `used`,
    the first appended row being 1-based row `base`. Instruments that share a
    body share its rows; the pointer is the first row of `prefix` (the
    commands run once, before the loop: `--rest-envelope-silence`'s SR) or of
    the body, never a delay or an `FF`, and the closing `FF` jumps past the
    prefix."""
    placed: Dict[TwinBody, int] = {}
    rows: List[Tuple[int, int]] = []
    ptr: Dict[int, int] = {}
    for g in sorted(used):
        key = loops[g]
        body, lead = key
        if key not in placed:
            placed[key] = base + len(rows)
            rows.extend(prefix)
            rows.extend(body)
            rows.append((GT_WAVE_JUMP, placed[key] + len(prefix) + lead))
        ptr[g] = placed[key]
    return ptr, rows


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


def lagged_instruments(out, instr_at: int, written: int) -> frozenset:
    """The instrument numbers (1-based) whose note-init call writes a
    TEST-BIT firstwave (`$09`, or `$x8` from `named_testbit_firstwave`; the
    record's `+8`): the program's first wavetable row then runs on call 2, a
    call after the row grid, while the original's first opcode runs on the
    row's own frame.

    The original's rest arrives on the frame after the program's last opcode,
    counted from the attack: Bangkok_Knights `$0AA9`, 12 frames, the rest on
    attack + 12. A park at tick 0 of our rest row is attack + 11 for such an
    instrument. Measured 2026-10-16 over the 78 parked notes of that
    instrument: 60 one frame early, 10 two, 8 on time; with the delay row
    (`REST_PARK_DELAY`) 60 on time, 10 one early, 8 one late (the original's
    own rest alternates between attack + 12 and + 13). IK+, I_Ball and
    Trans-Atlantic read the same (-1 on 180 of 193, 19 of 22 and 14 of 14
    before; 0 on those same counts afterwards).

    **What the delay does NOT do.** SETWAVEPTR switches the pointer on the
    rest row's own call, so the delay row runs IN PLACE of the program's
    step on that call: the park lands on the original's frame but the step
    one frame before it (Bangkok `$0AA9` `+11`, the `$BB` opcode) is still
    lost, as it was without the delay. Restoring it needs the pointer the
    program holds at the rest, which the pattern stage does not know.

    Only the test-bit family is claimed: it is what the four measured files
    carry; a record with another firstwave is left on the plain park,
    unmeasured."""
    found = set()
    for g in range(1, written + 1):
        fw = out[instr_at + 1 + (g - 1) * 25 + 8]
        if fw & 0x08 and fw < 0xFE:
            found.add(g)
    return frozenset(found)


def vibrato_instruments(out, instr_at: int, written: int) -> frozenset:
    """The instrument numbers (1-based) whose record carries a vibrato table
    pointer (`+5`, gplay.c:353 `cptr->cmddata = iptr->ptr[STBL]`)."""
    return frozenset(g for g in range(1, written + 1)
                     if out[instr_at + 1 + (g - 1) * 25 + 5])


def _hold_sr_to_ad(copy: List[int], r: int, full: bool = False) -> None:
    """The park program zeroes SR itself; the rest's first hold row then
    carries the AD half instead of a second SETSR. Where the program holds
    the AD too (`full`) the hold row carries nothing."""
    n1 = r + 4
    if (n1 + 3 < len(copy) and copy[n1] == GT_REST
            and copy[n1 + 2] == CMD_SETSR and copy[n1 + 3] == 0):
        copy[n1 + 2] = 0 if full else CMD_SETAD


def rest_park_pass(patterns: List[List[int]], tracks: List[List[int]],
                   programmed: frozenset, park: int, log=None,
                   only: Optional[frozenset] = None,
                   late_park: int = 0, lagged: frozenset = frozenset(),
                   envelope: bool = False,
                   vib: Optional[frozenset] = None, free_park: int = 0,
                   twins: Optional[Dict[int, int]] = None,
                   stats: Optional[dict] = None) -> List[List[int]]:
    """`CMD_SETWAVE $08` -> `CMD_SETWAVEPTR park` on each rest whose live
    instrument has a wavetable program (`programmed`), or is not known (a
    pattern reached holding more than one instrument, or none the walk can
    name).

    Declined, and counted: **no program** -- the live instrument has no
    wavetable pointer, so nothing can overwrite the park and `CMD_SETWAVE`
    already holds. Changed patterns are COPIES.

    `free_park` (with `vib`, the instruments carrying a vibrato pointer): the
    pointer of the program that also holds the AD, taken by a rest whose live
    instruments are all KNOWN and none has vibrato; every other rest takes
    `park` (see `REST_PARK_ENV_FULL_PROGRAM`). Only the non-`only` path uses
    it: `--rest-program-stop` keeps the two-row program.

    `twins` (instrument -> pointer, see `twin_loops`): a rest whose live
    instrument is that ONE instrument points at its silent stepping twin
    instead of the stop program. `stats`, when given, collects `twin` (the
    instruments that took one), `plain` (rests on `park`) and `full` (rests
    on `free_park`)."""
    from .note_passes import _entry_instruments
    if only is None and (not (park or free_park or twins) or not programmed):
        return patterns
    entry = _entry_instruments(tracks, patterns)
    out: List[List[int]] = []
    placed = stopping = unknown = cleared = nfull = twinned = 0
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
                    # A test-bit instrument's program runs a call behind
                    # the row grid: park through the one-call delay.
                    to = late_park if late_park and cands <= lagged else park
                    copy[r + 2] = CMD_SETWAVEPTR
                    copy[r + 3] = to & 0xFF
                    placed += 1
                    if envelope:
                        _hold_sr_to_ad(copy, r)
                else:
                    copy[r + 2] = 0
                    copy[r + 3] = 0
                    cleared += 1
                    # `--rest-envelope-silence` beside it: the pattern stage
                    # spelt the rest as KEYOFF + `CMD_SETWAVE $08` on row 0,
                    # `CMD_SETSR $00` on hold row 0 and `CMD_SETAD $00` on
                    # hold row 1 (the SETSR alone on a rest with one hold
                    # row, nothing on a rest with none). This rest keeps no
                    # SETWAVE, so it goes back to the envelope option's own
                    # spelling -- SETSR on row 0, AD on hold row 0: a rest
                    # this option does not stop is the conversion it would be
                    # without it.
                    if pat[r] == GT_KEYOFF:
                        # `envelope`: the envelope option is on, so even a
                        # rest with no hold row (its SETSR dropped for the
                        # SETWAVE) gets the SETSR back on row 0.
                        if envelope:
                            copy[r + 2], copy[r + 3] = CMD_SETSR, 0
                        n1 = r + 4
                        if (n1 + 3 < len(copy) and copy[n1] == GT_REST
                                and copy[n1 + 2] == CMD_SETSR
                                and copy[n1 + 3] == 0):
                            copy[r + 2], copy[r + 3] = CMD_SETSR, 0
                            copy[n1 + 2] = CMD_SETAD
                            n2 = n1 + 4
                            if (n2 + 3 < len(copy) and copy[n2] == GT_REST
                                    and copy[n2 + 2] == CMD_SETAD
                                    and copy[n2 + 3] == 0):
                                copy[n2 + 2] = 0
                    # ...and a pattern opening on a rest, whose row 0 the
                    # tempo took: the SETWAVE moved to hold row 0 (the
                    # SETSR to hold row 1, the AD to hold row 2). Without
                    # the SETWAVE the envelope option alone has SETSR on
                    # hold row 0 and AD on hold row 1: give the SETSR this
                    # row back and shift the AD up.
                    elif (pat[r] == GT_REST and r >= 4
                          and pat[r - 4] == GT_KEYOFF
                          and pat[r - 2] == CMD_SETTEMPO):
                        n1 = r + 4
                        if (n1 + 3 < len(copy) and copy[n1] == GT_REST
                                and copy[n1 + 2] == CMD_SETSR
                                and copy[n1 + 3] == 0):
                            copy[r + 2] = CMD_SETSR
                            copy[n1 + 2] = CMD_SETAD
                            n2 = n1 + 4
                            if (n2 + 3 < len(copy) and copy[n2] == GT_REST
                                    and copy[n2 + 2] == CMD_SETAD
                                    and copy[n2 + 3] == 0):
                                copy[n2 + 2] = 0
                continue
            if cands and not (cands & programmed):
                stopping += 1
                continue
            if len(cands) != 1:
                unknown += 1
            full = bool(free_park and vib is not None and cands
                        and not (cands & vib))
            to = free_park if full else park
            g = next(iter(cands)) if len(cands) == 1 else 0
            if twins and g in twins:
                to, full = twins[g], False
                twinned += 1
                if stats is not None:
                    stats.setdefault("twin", set()).add(g)
            elif not to:
                continue
            elif stats is not None:
                key = "full" if full else "plain"
                stats[key] = stats.get(key, 0) + 1
            if copy is None:
                copy = list(pat)
            copy[r + 2] = CMD_SETWAVEPTR
            copy[r + 3] = to & 0xFF
            placed += 1
            nfull += full
            if envelope:
                _hold_sr_to_ad(copy, r, full)
        out.append(pat if copy is None else copy)
    if log and only is not None and (placed or cleared):
        log(f"Rest program stop.......: {placed} rest(s) of a wave-program "
            f"instrument stop its program, {cleared} left a plain key-off")
    elif log and (placed or stopping):
        log(f"Rest park...............: {placed} rest(s) point the wavetable "
            f"at the parked waveform ({unknown} of an instrument not yet "
            f"named)" + (f", {nfull} with the AD in the program" if nfull else "")
            + (f", {twinned} of them at a silent stepping twin of the "
               f"instrument's loop" if twinned else "")
            + (f", {stopping} on an instrument with no program"
               if stopping else ""))
    return out


def _plan_with_twins(patterns, tracks, wave_entries, loops, programmed, log,
                     envelope, vib):
    """`rest_park_plan`'s non-`only` path with silent stepping twins, or None
    where no rest takes one or the layout does not fit (the caller then plans
    without twins). The layout is [park program][full program][twins]: a
    sentinel run of `rest_park_pass` counts which of the three the rests
    point at, and only those are appended."""
    split = bool(envelope and vib is not None)
    if split:
        base, full = REST_PARK_ENV_PROGRAM, REST_PARK_ENV_FULL_PROGRAM
    else:
        base = REST_PARK_ENV_PROGRAM if envelope else REST_PARK_PROGRAM
        full = ()
    stats: dict = {}
    rest_park_pass(patterns, tracks, programmed, 1, None, envelope=envelope,
                   vib=vib, free_park=1 if split else 0,
                   twins={g: 1 for g in loops}, stats=stats)
    used = stats.get("twin", set())
    if not used:
        return None
    at = len(wave_entries) + 1
    park = free = 0
    rows: List[Tuple[int, int]] = []
    if stats.get("plain"):
        park = at + len(rows)
        rows += list(base)
    if stats.get("full"):
        free = at + len(rows)
        rows += list(full)
    prefix = ((WAVECMD_BASE | CMD_SETSR, 0x00),) if envelope else ()
    ptr, twin_rows = twin_layout(loops, used, at + len(rows), prefix)
    rows += twin_rows
    if (at + len(rows) - 1 > GT_MAX_TABLELEN
            or any(p > 0xFF for p in (park, free, *ptr.values()))):
        if log:
            log("Rest park...............: no room in the wavetable for the "
                "silent stepping twins; rests keep the stop program")
        return None
    new = rest_park_pass(patterns, tracks, programmed, park, log,
                         envelope=envelope, vib=vib, free_park=free,
                         twins=ptr)
    return new, wave_entries + rows


def rest_park_plan(patterns: List[List[int]], tracks: List[List[int]],
                   wave_entries: List[Tuple[int, int]],
                   starts: Dict[int, int], log=None,
                   only: Optional[frozenset] = None,
                   lagged: frozenset = frozenset(),
                   envelope: bool = False,
                   vib: Optional[frozenset] = None, twin: bool = False
                   ) -> Tuple[List[List[int]], List[Tuple[int, int]]]:
    """(patterns, wave_entries) with the park program appended and the rests
    of looping instruments pointed at it. Unchanged where the patterns hold
    no `CMD_SETWAVE $08`, no instrument with a program, or the program would not fit
    the table.

    `twin` (`--rest-park-twin`): a rest on ONE instrument whose program loops
    points at a silent stepping copy of that loop instead of the stop program
    (`twin_loops`), after SR zeroed once where `envelope` is on. Falls back to
    the stop program for every rest when the twins do not fit the table."""
    if not rest_wave_rows(patterns):
        return patterns, wave_entries
    programmed = programmed_instruments(starts)
    if only is not None:
        # `--rest-program-stop`: `only` are the instruments whose record
        # selects the byte-code program. The parked program is appended
        # only if a rest actually points at it.
        only = frozenset(only) & programmed
        lagged = frozenset(lagged) & only
        # The delayed entry sits one row before the plain park and falls
        # through into it: [delay, E8 80, FF 00], the plain pointer one row
        # in. Without a lagged rest the delay row is not written at all.
        base_prog = REST_PARK_ENV_PROGRAM if envelope else REST_PARK_PROGRAM
        late = len(wave_entries) + 1 if lagged else 0
        park = len(wave_entries) + 1 + (1 if lagged else 0)
        rows = len(base_prog) + (1 if lagged else 0)
        if (park + len(base_prog) - 1 > GT_MAX_TABLELEN
                or late + rows - 1 > GT_MAX_TABLELEN or park > 0xFF):
            if only and log:
                log("Rest program stop.......: no room in the wavetable for "
                    "the parked program; rests keep a plain key-off")
            park = late = 0
        # Quiet while the layout is still undecided: one log line, not two.
        new = rest_park_pass(patterns, tracks, programmed,
                             park if only else 0, None, only, late, lagged,
                             envelope)

        def _points(to):
            return bool(to and only) and any(
                pat[r + 2] == CMD_SETWAVEPTR and pat[r + 3] == (to & 0xFF)
                for pat in new for r in range(0, len(pat) - 3, 4)
                if pat[r] != 0xFF)
        if late and not _points(late):
            # No rest took the delayed entry: the plain layout, as before.
            park = len(wave_entries) + 1
            late = 0
            new = rest_park_pass(patterns, tracks, programmed, park, None,
                                 only, envelope=envelope)
        used = _points(park) or _points(late)
        new = rest_park_pass(patterns, tracks, programmed,
                             park if only else 0, log, only, late, lagged,
                             envelope)
        if not used:
            return new, wave_entries
        prog = list(base_prog)
        if late:
            prog = [REST_PARK_DELAY] + prog
        return new, wave_entries + prog
    if not programmed:
        return patterns, wave_entries
    loops = twin_loops(wave_entries, starts) if twin else {}
    if loops:
        planned = _plan_with_twins(patterns, tracks, wave_entries, loops,
                                   programmed, log, envelope, vib)
        if planned is not None:
            return planned
    if envelope and vib is not None:
        # `vib`: the instruments with a vibrato pointer. A rest that cannot be
        # on one takes the full program (the AD on the park's frame), the
        # others the two-row program and the hold-row AD; only the programs a
        # rest points at are appended, the full one after the other.
        base, full = REST_PARK_ENV_PROGRAM, REST_PARK_ENV_FULL_PROGRAM
        p0 = len(wave_entries) + 1
        f0 = p0 + len(base)
        if (f0 + len(full) - 1 <= GT_MAX_TABLELEN and f0 <= 0xFF):
            new = rest_park_pass(patterns, tracks, programmed, p0, None,
                                 envelope=True, vib=vib, free_park=f0)

            def _pts(to):
                return any(pat[r + 2] == CMD_SETWAVEPTR
                           and pat[r + 3] == (to & 0xFF)
                           for pat in new for r in range(0, len(pat) - 3, 4)
                           if pat[r] != 0xFF)
            up, uf = _pts(p0), _pts(f0)
            if not (up or uf):
                return patterns, wave_entries
            if up and uf:
                new = rest_park_pass(patterns, tracks, programmed, p0, log,
                                     envelope=True, vib=vib, free_park=f0)
                return new, wave_entries + list(base) + list(full)
            if uf:
                new = rest_park_pass(patterns, tracks, programmed, 0, log,
                                     envelope=True, vib=vib, free_park=p0)
                return new, wave_entries + list(full)
            new = rest_park_pass(patterns, tracks, programmed, p0, log,
                                 envelope=True)
            return new, wave_entries + list(base)
    # `envelope`: the rests also zero SR and AD (`--rest-envelope-silence`),
    # which the program then does on the same call as the park.
    program = REST_PARK_ENV_PROGRAM if envelope else REST_PARK_PROGRAM
    park = len(wave_entries) + 1
    if park + len(program) - 1 > GT_MAX_TABLELEN or park > 0xFF:
        if log:
            log("Rest park...............: no room in the wavetable for the "
                "parked program; rests keep CMD_SETWAVE")
        return patterns, wave_entries
    new = rest_park_pass(patterns, tracks, programmed, park, log,
                         envelope=envelope)
    if new is patterns or all(a is b for a, b in zip(new, patterns)):
        return patterns, wave_entries
    return new, wave_entries + list(program)
