"""Drop the instrument records no pattern names, from a finished `.sng`.

The writer emits one instrument per player record (plus, in the inherited
layout, the "Clear Voice" placeholder at 1) and then appends the clones the
tempo-duty, fixed-arp-phase, attack-hold and past-table-drum passes make. A
record no pattern row's instrument column ever names is a slot the song
cannot reach: Knucklebusters' record 27 (GT 28 under --compact-instruments)
carries $00 $00, pulse width $000 and an EMPTY wavetable block, and is named
0 times. Under presets.json, 71 of the 89 corpus files that convert carry
at least one such slot (measured on the v0.5.494 working tree, 2026-10-02).

This runs on the FINISHED bytes, after every pass that writes or renumbers
an instrument column, so it cannot disagree with any of them: it reads the
instrument column of every pattern (reachable or not -- an unreachable
pattern naming a record keeps it, the conservative reading of "named in no
pattern"), keeps the named records in their order, and renumbers every
column through the same map. The clones are records like any other here.

**Instrument 1 is always kept.** Both players start every voice on it
without any pattern naming it -- `gplay.c:62` `chn[c].instr = 1` and
`player.s:621` `sta mt_chninstr,x ;Reset instrument` -- so a note played
before the first instrument column sounds instrument 1, and greloc keeps it
for the same reason (`greloc.c:274-275`, "Instrument 1 is always used").
Dropping it would move that note onto whatever became the new instrument 1.

The packed `.sid` does not change: greloc.c:291 already maps away every
instrument no reachable pattern names. What changes is the `.sng` a person
opens -- no dead slots, and instrument numbers that count only what plays.

The tables are left exactly as written. A dropped record's wavetable,
pulse and filter blocks stay where they are, unreferenced: removing them
would repoint every surviving record's pointers and every CMD_SET*PTR
operand, which is a different change with a different blast radius.

Instrument numbers above the record count (a dangling reference, which the
writer already logs) are shifted down by the number dropped, so they stay
dangling rather than silently landing on a real record.
"""
from typing import Callable, List, Optional, Tuple

from .goatwriter import HEADER_LEN

_RECORD_LEN = 25


def _layout(blob: bytes) -> Tuple[int, int, int, List[Tuple[int, int]]]:
    """(instrument count offset, tables offset, pattern count offset,
    [(first row offset, rows)] per pattern) for a `.sng` built by build_sng.
    """
    magic = bytes(blob[:4])
    if magic not in (b"GTS2", b"GTS5"):
        raise ValueError(f"not a Goattracker song: magic {magic!r}")
    pos = HEADER_LEN
    subtunes = blob[pos]
    pos += 1
    for _ in range(subtunes * 3):
        pos += blob[pos] + 2
    instr_at = pos
    tables_at = instr_at + 1 + blob[instr_at] * _RECORD_LEN
    pos = tables_at
    for _ in range(4 if magic == b"GTS5" else 3):
        pos += 1 + 2 * blob[pos]
    patt_at = pos
    pos += 1
    patterns = []
    for _ in range(blob[patt_at]):
        rows = blob[pos]
        patterns.append((pos + 1, rows))
        pos += 1 + rows * 4
    if pos != len(blob):
        raise ValueError(f".sng layout read ends at {pos}, file is {len(blob)}")
    return instr_at, tables_at, patt_at, patterns


def named_instruments(blob: bytes) -> set:
    """Every non-zero instrument column value in every pattern."""
    _, _, _, patterns = _layout(blob)
    return {blob[start + r * 4 + 1]
            for start, rows in patterns for r in range(rows)
            if blob[start + r * 4 + 1]}


def drop_unnamed_instruments(blob: bytes,
                             log: Optional[Callable[[str], None]] = None
                             ) -> bytes:
    """`blob` without the instrument records no pattern names (1 is kept)."""
    instr_at, tables_at, patt_at, patterns = _layout(blob)
    count = blob[instr_at]
    named = {blob[start + r * 4 + 1]
             for start, rows in patterns for r in range(rows)}
    keep = [k for k in range(1, count + 1) if k == 1 or k in named]
    if len(keep) == count:
        return bytes(blob)
    dropped = count - len(keep)
    remap = {old: new for new, old in enumerate(keep, 1)}
    recs = instr_at + 1
    out = bytearray(blob[:instr_at])
    out.append(len(keep))
    for k in keep:
        out += blob[recs + (k - 1) * _RECORD_LEN:recs + k * _RECORD_LEN]
    out += blob[tables_at:patt_at + 1]
    for start, rows in patterns:
        out.append(rows)
        body = bytearray(blob[start:start + rows * 4])
        for r in range(rows):
            ins = body[r * 4 + 1]
            if ins:
                body[r * 4 + 1] = remap[ins] if ins <= count else ins - dropped
        out += body
    if log:
        gone = [k for k in range(1, count + 1) if k not in remap]
        log(f"Dropped {dropped} instrument(s) no pattern names: "
            + ", ".join(f"${k:02X}" for k in gone))
    return bytes(out)
