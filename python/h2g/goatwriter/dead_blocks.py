"""Drop the wavetable blocks of the records no pattern names.

`instrument_drop.drop_unnamed_instruments` removes, from the finished file,
every instrument record no pattern row names -- and leaves the record's
wavetable block where it was, because by then removing it would repoint every
other record (its docstring says so). Under `prune` the dead records are many:
Last_V8's song as written plays 18 of its 33 records and the wavetable keeps
all 33 blocks, 60 rows of them the same five-row drum program repeated. The
rows are not free to anything that runs before the drop -- the skydive, rise
and fall passes size their programs against a table the dead blocks fill.

So the blocks go earlier, here, at the one moment the build can do it without
a second pair of eyes on every consumer: after the layout and the passes that
read it record by record (`_free_gate_calls`, `past_table_drum_plan`), before
the passes that append programs and so ask how much room is left. Everything
that holds a row number at that moment is a short list: the records' starts,
the arpeggio/clone/tie/attack-hold/drum starts, the `CMD_SETWAVEPTR` operands
of the patterns, the jumps inside the table itself.

**A block is dropped only if nothing reaches it.** The reach is a walk from
every kept pointer (`$FF` jumps and `$F8` pointer commands followed), so a dead
record whose rows another program jumps into, or whose start is also a kept
record's (`_entered_record_block`, the EOR library), keeps them. Rows the
layout leaves between kept blocks (the padding up to
`WAVE_ENTRIES_PER_INSTR`) are not touched: only a dead record's own rows move,
which is what keeps a file with no dead record byte for byte what it was.

The dropped records' own pointer becomes 0. They are not written for long: the
finished-bytes drop removes them, and `build_sng` checks (`named_after`) that no
later pass named one of them, rebuilding without the drop where one did.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .constants import CMD_SETWAVEPTR, GT_WAVE_JUMP, WAVECMD_BASE

# `$F0 + CMD_SETWAVEPTR`: the wavetable's own pointer command, its right
# side the row it moves the pointer to.
WAVE_SETPTR = WAVECMD_BASE + CMD_SETWAVEPTR


@dataclass(frozen=True)
class DeadBlocks:
    """What dropping the dead blocks does.

    `row_map` takes each kept row (1-based) to its new row; `dropped` is the
    set of records (0-based, `wave_starts` index) whose block went and `rows`
    how many rows that freed.
    """
    entries: List[Tuple[int, int]]
    row_map: Dict[int, int]
    dropped: Tuple[int, ...]
    rows: int


def _targets(entry: Tuple[int, int]) -> Optional[int]:
    """The row an entry sends the pointer to, or None."""
    left, right = entry
    if left in (GT_WAVE_JUMP, WAVE_SETPTR) and right:
        return right
    return None


def reached_rows(entries: List[Tuple[int, int]], roots: Iterable[int]
                 ) -> Set[int]:
    """Every row (1-based) the table can execute from `roots`: a row falls
    through to the next, a `$FF` jump goes only to its target (0 stops), and
    the `$F8` pointer command does both, as the cautious reading of a command
    that may or may not take."""
    size = len(entries)
    seen: Set[int] = set()
    todo = [r for r in roots if r]
    while todo:
        row = todo.pop()
        if row in seen or not 1 <= row <= size:
            continue
        seen.add(row)
        left, right = entries[row - 1]
        if left != GT_WAVE_JUMP:
            todo.append(row + 1)
        if _targets(entries[row - 1]) is not None:
            todo.append(right)
    return seen


def plan_dead_blocks(entries: List[Tuple[int, int]], wave_starts: List[int],
                     lead: int, dead: Iterable[int],
                     block_starts: Iterable[int],
                     operands: Iterable[int] = (), protect: int = 0
                     ) -> Optional[DeadBlocks]:
    """The table without the dead records' blocks, or None where none goes.

    `dead` is the 0-based records (`wave_starts[lead + i]`) no pattern names,
    `block_starts` the first row of every other block (the arpeggio, clone,
    tie, attack-hold and drum starts: they bound a record's block and are
    kept), `operands` the patterns' `CMD_SETWAVEPTR` operands (rows that may
    land anywhere, inside a dead block too, which then stays), `protect` the last row of the blocks that are never touched (the leading
    placeholders, the EOR library and its stop program). None as well where
    some kept entry names a row the table does not have: a rewrite would have
    to guess.
    """
    size = len(entries)
    dead = {d for d in dead if 0 <= d < len(wave_starts) - lead}
    held = {p for p in block_starts if p}
    landing = {p for p in operands if p}
    kept_starts = {s for k, s in enumerate(wave_starts)
                   if s and (k < lead or (k - lead) not in dead)}
    roots = kept_starts | held | landing | set(range(1, protect + 1))
    reached = reached_rows(entries, roots)
    every = sorted({s for s in wave_starts if s} | held | {size + 1})
    gone: Set[int] = set()
    dropped: List[int] = []
    for i in sorted(dead):
        s = wave_starts[lead + i]
        if not s or s <= protect or s in kept_starts or s in held:
            continue
        e = next(b for b in every if b > s)
        block = range(s, e)
        if any(r in reached for r in block):
            continue
        gone.update(block)
        dropped.append(i)
    if not gone:
        return None
    row_map: Dict[int, int] = {}
    kept: List[Tuple[int, int]] = []
    for row in range(1, size + 1):
        if row not in gone:
            kept.append(entries[row - 1])
            row_map[row] = len(kept)
    rewritten = []
    for entry in kept:
        target = _targets(entry)
        if target is not None:
            if target not in row_map:
                return None
            entry = (entry[0], row_map[target])
        rewritten.append(entry)
    return DeadBlocks(rewritten, row_map, tuple(dropped), len(gone))


def remap_rows(rows: List[int], row_map: Dict[int, int]) -> None:
    """`rows` in place: each non-zero row through `row_map`."""
    for k, row in enumerate(rows):
        if row:
            rows[k] = row_map[row]


def setwaveptr_operands(patterns: List[List[int]]) -> List[int]:
    """Every non-zero `CMD_SETWAVEPTR` operand in `patterns`."""
    return [pat[4 * r + 3] for pat in patterns if pat
            for r in range(len(pat) // 4)
            if pat[4 * r + 2] == CMD_SETWAVEPTR and pat[4 * r + 3]]


def remap_setwaveptr(patterns: List[List[int]], row_map: Dict[int, int]
                     ) -> None:
    """The `CMD_SETWAVEPTR` operands of `patterns`, in place, through
    `row_map`."""
    for pat in patterns:
        if not pat:
            continue
        for r in range(len(pat) // 4):
            if pat[4 * r + 2] == CMD_SETWAVEPTR and pat[4 * r + 3]:
                pat[4 * r + 3] = row_map[pat[4 * r + 3]]


def named_records(patterns: List[List[int]]) -> Set[int]:
    """Every non-zero instrument column value in `patterns` (GT numbers)."""
    return {pat[4 * r + 1] for pat in patterns if pat
            for r in range(len(pat) // 4) if pat[4 * r + 1]}


def dead_records(patterns: List[List[int]], instr_used: int, lead: int
                 ) -> List[int]:
    """The 0-based records no pattern row names. GT instrument 1 is never one:
    both players start every voice on it without a pattern naming it
    (`instrument_drop`'s own rule)."""
    named = named_records(patterns)
    return [i for i in range(max(instr_used - lead, 0))
            if i + lead + 1 not in named and i + lead + 1 != 1]
