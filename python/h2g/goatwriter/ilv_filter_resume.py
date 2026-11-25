"""A running filter sweep carries on through the interleaved player's `$84` notes.

**THE PLAYER RESTARTS A RECORD'S FILTER PROGRAM ON EVERY FILTERED NOTE, EXCEPT
THE ONES A `$84` PRECEDES.** The note-start loader reads the record's
filter-enable bit and then a flag:

    1321  AD 86 1A  LDA $1A86
    1324  D0 63     BNE $1389        ; skip the whole program load

and `$84` is the command that sets that flag (`$11E7 LDA #$01 / STA $1A86`;
the fetch pass zeroes it again at `$1152`, so it belongs to the one event that
follows). The skipped load is the program index (`$1A83`), the start cutoff
(`$1A74`/`$1A71`), the step, the two limits, the direction and the record's
resonance. So a `$84` note leaves the sweep running from wherever the last
filtered note's program had taken it -- Lion_Heart's record 4 sweeps a
triangle between `$1D00` and `$7200` at a constant 928 a frame and is restarted
(to `$4E00`) by 148 of its 184 notes; the other 36 follow a `$84` and the
cutoff just keeps moving. Goattracker restarts a filter table on every note
that names an instrument with a filter pointer (gplay.c:386-391), so
before this pass those 36 notes jumped the cutoff back to the start.

**Measured, not assumed.** Redirecting the `$84` handler's store
(`STA $1A86` at `$11EA`) to `$0200` in a copy of Lion_Heart makes the original
restart on every note; scored against our conversion that copy reads `cfrm`
.884 and `cut` 1.015, and the real original reads .7985 and 1.068. The
difference between the two originals is these 36 notes. See
docs/OPTIONS.md `--ilv-filter-resume`.

**A sweep that runs on has to HOLD where the player's does.** The note start
ends in `$13CA JMP $17B7`, past the block that steps the sweep (`$15F9`), so
on each frame a note starts the cutoff stays put: Radio_ACE steps `$0295` on
five frames of six and holds on the sixth (its trace repeats the value on
frames 2318, 2324, 2330, ...). A table that runs on through the `$84` notes
without it overshoots by a step in six -- Radio_ACE's `cut` 1.133 -> 1.285
with the clones alone. `filters.ilv_hold_period` reads the period (one wait
for every filtered note) and the sweep is emitted as periods of stepping calls
and one hold (`filters._ilv_hold_sweep`).

**`$87 nn mm` notes start their program at `nn`, not at the record's start.**
It writes the cutoff cell at the command (`$11B0-$11BC`) and sets `$1A63`,
which makes the note-start loader skip the two start loads and keep the rest
(`$1335 LDA $1A63 / BNE $1346`: step, limits, direction and resonance still
come from the record). Such a note names a clone whose filter pointer is a
three-row block of its own -- the record's params row, `set cutoff nn`, and a
jump into the record's sweep at the period whose cutoff is nearest `nn`.
Radio_ACE has seven distinct values.

**Goattracker cannot say it per note.** A filter pointer belongs to the
instrument, and an instrument with pointer 0 leaves the running table alone
(gplay.c:386 `if (iptr->ptr[FTBL])`). So each such note names a CLONE of its
instrument -- the finished record's bytes with the filter pointer cleared --
and every other column of the record (wave, pulse, vibrato, envelope) is the
record's own, which is what the original still loads on those notes.

The rows come from the decoder (`patterns._build_raw_pattern_ilv`'s
`skip_rows`, carried to the finished patterns as `patterns.SkipList`) and are
attributed to a pass's copies by note column the way `note_bit7_rows` does,
a copy whose notes two differently flagged patterns share staying as it was.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constants import (CMD_TONEPORTA, FILT_SET_CUTOFF, FILT_STOP,
                        GT_FIRST_NOTE, GT_LAST_NOTE, GT_MAX_FILT)
from .note_passes import clone_number_ceiling, note_bit7_rows

# Switched off by `tests/test_ilv_filter_resume.py`, which proves the plan is
# what moves the bytes.
RESUME_ENABLED = True
# Likewise for the `$87` clones (`tests/test_ilv_filter_hold.py`).
START_CLONES_ENABLED = True

_RESUME_RECORD_BYTES = 25      # one instrument record of the .sng
_RESUME_FILTER_PTR = 4         # its filter pointer


def resume_plan(patterns: List[List[int]], skip_known: Optional[dict],
                skip_decoded: int, skip_ghosts: tuple, out: bytearray,
                instr_at: int, written: int, log=None,
                filter_entries: Optional[list] = None,
                anchors: Optional[dict] = None
                ) -> Tuple[List[List[int]], int, List[Tuple[int, int]]]:
    """(patterns, written, [(instrument, clone)]) with every `$84` note on a
    filtered instrument renamed to a filter-less clone of it, and every `$87`
    note to a clone whose filter block starts at its own cutoff.

    `out` ends with the last instrument record (`written` of them, the table
    at `instr_at`); the clones' records are appended to it. `patterns` are
    edited in place -- a row flagged in a pattern is flagged wherever that
    pattern plays, because the flag is the note's own. Unchanged where the
    plan finds nothing to rename, or where a pass's copy cannot be
    attributed (`note_bit7_rows` says None).

    The `$87` clones need `filter_entries` (appended to in place) and
    `anchors`, `{filter pointer: [(row offset, high byte)]}` from
    `filters.ilv_hold_anchors`: the rows of the record's sweep a clone can
    jump into. Without them a `$87` note keeps restarting at the record's
    start."""
    if not RESUME_ENABLED or not skip_known:
        return patterns, written, []
    rows = note_bit7_rows(patterns, skip_known, skip_decoded, skip_ghosts)
    filtered = {g: out[instr_at + 1 + (g - 1) * _RESUME_RECORD_BYTES
                       + _RESUME_FILTER_PTR]
                for g in range(1, written + 1)}
    filtered = {g: ptr for g, ptr in filtered.items() if ptr}
    if not filtered:
        return patterns, written, []
    wanted: Dict[int, List[Tuple[int, int]]] = {}
    started: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for pn, flags in rows.items():
        if not flags or pn >= len(patterns):
            continue
        pat = patterns[pn]
        for item in sorted(flags, key=lambda f: f[0] if isinstance(f, tuple)
                           else f):
            r, hi = item if isinstance(item, tuple) else (item, None)
            k = 4 * r
            if k + 3 >= len(pat) or pat[k] == 0xFF:
                break
            ins = pat[k + 1]
            if (ins in filtered and GT_FIRST_NOTE <= pat[k] <= GT_LAST_NOTE
                    and pat[k + 2] != CMD_TONEPORTA):
                if hi is None:
                    wanted.setdefault(ins, []).append((pn, r))
                elif (START_CLONES_ENABLED and anchors
                      and filter_entries is not None):
                    started.setdefault((ins, hi), []).append((pn, r))
    # A `$87` clone needs a block it can copy: the record's own first two
    # rows, params then set-cutoff, and the sweep's anchors.
    usable = {}
    for g, ptr in filtered.items():
        if (filter_entries is not None and anchors and ptr in anchors
                and ptr + 1 < len(filter_entries)
                and filter_entries[ptr - 1][0] & 0x80
                and filter_entries[ptr][0] == FILT_SET_CUTOFF):
            usable[g] = ptr
    started = {key: v for key, v in started.items() if key[0] in usable}
    if not wanted and not started:
        return patterns, written, []
    ceiling = clone_number_ceiling(patterns, written)
    clones: List[Tuple[int, int]] = []
    number = written

    def clone_of(g: int, ptr: int) -> None:
        rec = instr_at + 1 + (g - 1) * _RESUME_RECORD_BYTES
        c = bytearray(out[rec:rec + _RESUME_RECORD_BYTES])
        c[_RESUME_FILTER_PTR] = ptr
        out.extend(c)

    for g in sorted(wanted):
        if number + 1 > ceiling:
            if log:
                log(f"ILV filter resume.......: no instrument number left "
                    f"for instrument {g}'s clone ({len(wanted[g])} note(s) "
                    "keep restarting the sweep)")
            continue
        number += 1
        clone_of(g, 0)
        clones.append((g, number))
        for pn, r in wanted[g]:
            patterns[pn][4 * r + 1] = number
    kept_starts = 0
    for g in sorted({key[0] for key in started}):
        ptr = usable[g]
        counts = {hi: len(v) for (gg, hi), v in started.items() if gg == g}
        room = (GT_MAX_FILT - len(filter_entries)) // 3
        keep = sorted(sorted(counts, key=lambda h: (-counts[h], h))[:room])
        ladder = anchors[ptr]
        for hi in keep:
            if number + 1 > ceiling:
                break
            offset = min(ladder, key=lambda a: (abs(a[1] - hi), a[0]))[0]
            number += 1
            filter_entries.extend([filter_entries[ptr - 1],
                                   (FILT_SET_CUTOFF, hi),
                                   (FILT_STOP, ptr + 2 + offset)])
            clone_of(g, len(filter_entries) - 2)
            clones.append((g, number))
            # Every value the room could not give a block of its own takes
            # the nearest one's.
            for other, rowsets in sorted(started.items()):
                if other[0] != g:
                    continue
                nearest = min(keep, key=lambda h: (abs(h - other[1]), h))
                if nearest == hi:
                    for pn, r in rowsets:
                        patterns[pn][4 * r + 1] = number
                    kept_starts += len(rowsets)
    if clones:
        out[instr_at] = number
        if log:
            log(f"ILV filter resume.......: "
                f"{sum(len(v) for v in wanted.values())} note row(s) keep "
                f"their sweep running on filter-less clone(s), "
                f"{kept_starts} start on a `$87` cutoff of their own; "
                + ", ".join(f"{g}->{n}" for g, n in clones))
    return patterns, number, clones
