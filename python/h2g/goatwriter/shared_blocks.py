"""Identical instrument blocks stored once, so a pass that appends has room.

Every record's wavetable block is its own `WAVE_ENTRIES_PER_INSTR` rows, and
records whose programs are the same ones carry the same rows several times:
Thrust's table is 255 rows of 255 with the five-row program `41 00 / 01 00 /
41 00 / FF 00 / FF 00` seven times (instruments 3, 7, 10, 13, 21, 22 and 23)
and the six-row drum program `41 00 / 01 80 / 81 00 / 04 80 / 40 00 / FF 00`
three times (instruments 1, 2 and 8): 42 rows of copies. Nothing appended after
the layout (the bit-$01 drum's long sweep, `drum_long`) can then be placed at
all -- `drum_long_plan` returns None on a full table -- and the original's
`$0908` kick, whose pitch falls a high byte a frame, plays flat.

`note_rise` and `skydive` already take these rows, but only by laying their own
program over them in place. A sweep chain has to be contiguous and the copies
are not, so here the copies are REMOVED: the records are repointed at the first
copy (`note_rise.reclaimable_holes`, which decides what is a copy: a block that
ends in a stop, jumps nowhere but 0, is named by no pointer and entered by no
jump from elsewhere) and the table is renumbered without them by
`dead_blocks.plan_dead_blocks`, the pass that already does this for the records
no pattern names. Every holder of a row number is remapped by the caller.

Taken by the caller only when a plan found no room without it, so a file whose
plan fits is not touched.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .dead_blocks import plan_dead_blocks
from .note_rise import reclaimable_holes


@dataclass(frozen=True)
class SharedBlocks:
    """`entries` the table without the copies, `row_map` old row -> new row,
    `starts` the records' starts (index = `wave_starts`'), `rows` how many
    rows went and `shared` the records now pointing at another's block."""
    entries: List[Tuple[int, int]]
    row_map: Dict[int, int]
    starts: List[int]
    rows: int
    shared: Tuple[int, ...]


def plan_shared_blocks(entries: List[Tuple[int, int]],
                       wave_starts: List[int], lead: int,
                       block_starts: Iterable[int],
                       operands: Iterable[int] = (),
                       protect: int = 0) -> Optional[SharedBlocks]:
    """The table with each duplicate record block removed, or None.

    `block_starts` are the first rows of every block no record owns (the
    arpeggio, clone, tie, attack-hold, cut and drum starts) and `operands` the
    patterns' `CMD_SETWAVEPTR` operands: rows something else points at, which
    keep their block. `protect` is the last row never touched (the leading
    placeholders and the EOR library).
    """
    held = [p for p in block_starts if p]
    landing = [p for p in operands if p]
    holes, starts_to = reclaimable_holes(entries, wave_starts, held + landing)
    if not holes:
        return None
    copies = [k - lead for k, (a, b) in enumerate(zip(wave_starts, starts_to))
              if k >= lead and a != b]
    plan = plan_dead_blocks(entries, wave_starts, lead, copies, held,
                            landing, protect=protect)
    if plan is None:
        return None
    gone = {lead + i for i in plan.dropped}
    new_starts = []
    for k, (own, first) in enumerate(zip(wave_starts, starts_to)):
        row = first if k in gone else own
        new_starts.append(plan.row_map[row] if row else 0)
    return SharedBlocks(plan.entries, plan.row_map, new_starts, plan.rows,
                        tuple(sorted(gone)))
