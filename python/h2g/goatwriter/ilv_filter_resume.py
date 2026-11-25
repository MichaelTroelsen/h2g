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

from .constants import CMD_TONEPORTA, GT_FIRST_NOTE, GT_LAST_NOTE
from .note_passes import clone_number_ceiling, note_bit7_rows

# Switched off by `tests/test_ilv_filter_resume.py`, which proves the plan is
# what moves the bytes.
RESUME_ENABLED = True

_RESUME_RECORD_BYTES = 25      # one instrument record of the .sng
_RESUME_FILTER_PTR = 4         # its filter pointer


def resume_plan(patterns: List[List[int]], skip_known: Optional[dict],
                skip_decoded: int, skip_ghosts: tuple, out: bytearray,
                instr_at: int, written: int, log=None
                ) -> Tuple[List[List[int]], int, List[Tuple[int, int]]]:
    """(patterns, written, [(instrument, clone)]) with every `$84` note on a
    filtered instrument renamed to a filter-less clone of it.

    `out` ends with the last instrument record (`written` of them, the table
    at `instr_at`); the clones' records are appended to it. `patterns` are
    edited in place -- a row flagged in a pattern is flagged wherever that
    pattern plays, because the flag is the note's own. Unchanged where the
    plan finds nothing to rename, or where a pass's copy cannot be
    attributed (`note_bit7_rows` says None)."""
    if not RESUME_ENABLED or not skip_known:
        return patterns, written, []
    rows = note_bit7_rows(patterns, skip_known, skip_decoded, skip_ghosts)
    filtered = {g for g in range(1, written + 1)
                if out[instr_at + 1 + (g - 1) * _RESUME_RECORD_BYTES + _RESUME_FILTER_PTR]}
    if not filtered:
        return patterns, written, []
    wanted: Dict[int, List[Tuple[int, int]]] = {}
    for pn, flags in rows.items():
        if not flags or pn >= len(patterns):
            continue
        pat = patterns[pn]
        for r in sorted(flags):
            k = 4 * r
            if k + 3 >= len(pat) or pat[k] == 0xFF:
                break
            ins = pat[k + 1]
            if (ins in filtered and GT_FIRST_NOTE <= pat[k] <= GT_LAST_NOTE
                    and pat[k + 2] != CMD_TONEPORTA):
                wanted.setdefault(ins, []).append((pn, r))
    if not wanted:
        return patterns, written, []
    ceiling = clone_number_ceiling(patterns, written)
    clones: List[Tuple[int, int]] = []
    number = written
    for g in sorted(wanted):
        if number + 1 > ceiling:
            if log:
                log(f"ILV filter resume.......: no instrument number left "
                    f"for instrument {g}'s clone ({len(wanted[g])} note(s) "
                    "keep restarting the sweep)")
            continue
        number += 1
        rec = instr_at + 1 + (g - 1) * _RESUME_RECORD_BYTES
        clone = bytearray(out[rec:rec + _RESUME_RECORD_BYTES])
        clone[_RESUME_FILTER_PTR] = 0
        out += clone
        clones.append((g, number))
        for pn, r in wanted[g]:
            patterns[pn][4 * r + 1] = number
    if clones:
        out[instr_at] = number
        if log:
            log(f"ILV filter resume.......: "
                f"{sum(len(wanted[g]) for g, _n in clones)} note row(s) keep "
                f"their sweep running on {len(clones)} filter-less clone(s) "
                + ", ".join(f"{g}->{n}" for g, n in clones))
    return patterns, number, clones
