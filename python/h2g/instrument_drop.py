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

The wavetable is left as written HERE. A dropped record's wavetable block
goes earlier than this pass: `goatwriter.dead_blocks` drops the blocks of
the records no pattern names inside the build, behind the same option, so
that the passes sized against the table's room see the room. On bytes that
come from the writer without it (appended players, a hand-fed `.sng`) the
block stays unreferenced here. The PULSE and FILTER tables are pruned: the rows only a
dropped record reaches are removed and every pointer renumbered (the kept
records' bytes 3 and 4, CMD_SETPULSEPTR / CMD_SETFILTERPTR operands in the
patterns and in wavetable $F9 / $FA rows, table jumps) -- `_drop_dead_blocks`.
A wavetable row of a dropped block that names a pulse block keeps it, and a
row no record at all reaches is left as written. The packed `.sid` is
unchanged either way: greloc marks only the rows execution enters
(`tableused`, greloc.c:902-925).

Instrument numbers above the record count (a dangling reference, which the
writer already logs) are shifted down by the number dropped, so they stay
dangling rather than silently landing on a real record.

`add_startup_tempo`, the other finished-bytes pass here, runs after the drop
and does the opposite on purpose: it adds instrument 63, which no pattern
names, for gt2reloc's startup row (`goatwriter.call_phase`).
"""
from typing import Callable, List, Optional, Tuple

from .goatwriter import (GT_FIRST_NOTE, GT_LAST_NOTE, GT_TEMPO_INSTRUMENT,
                         HEADER_LEN)
from .patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,
                       GT_TRANSPOSE_DOWN)

_RECORD_LEN = 25
# A record's gatetimer byte, and the bits of it the packed player compares
# against its counter (greloc.c:787 writes `gatetimer & 0x3f`).
_GATETIMER_AT = 7
_GATETIMER_MASK = 0x3F
_STARTUP_TEMPO_NAME = "Startup tempo"
# Record bytes 3 and 4 (songview Instrument.pulse_ptr / filt_ptr), the pattern
# commands and the wavetable command rows (gplay.c:529, WAVECMD..WAVELASTCMD,
# the command being the row's low nibble) that name a pulse / filter row.
_PULSE_AT, _FILTER_AT = 3, 4
_CMD_SETPULSEPTR, _CMD_SETFILTERPTR = 0x09, 0x0A
_WAVE_FIRST_CMD, _WAVE_LAST_CMD = 0xF0, 0xFE
_TABLE_JUMP = 0xFF
_TABLE_NAMES = ("WTBL", "PTBL", "FTBL", "STBL")


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


def _reach(rows: List[Tuple[int, int]], roots) -> set:
    """The 1-based rows of a pulse or filter table that execution can enter
    from `roots`: a row falls through to the next unless it is a jump
    (left $FF, right the target, 0 = stop)."""
    seen: set = set()
    todo = list(roots)
    while todo:
        r = todo.pop()
        if r in seen or not 1 <= r <= len(rows):
            continue
        seen.add(r)
        left, right = rows[r - 1]
        if left == _TABLE_JUMP:
            if right:
                todo.append(right)
        else:
            todo.append(r + 1)
    return seen


def _drop_dead_blocks(blob: bytes, instr_at: int, tables_at: int, patt_at: int,
                      patterns: List[Tuple[int, int]], keep: List[int],
                      log: Optional[Callable[[str], None]]):
    """(table bytes, pulse map, filter map) with the pulse and filter rows
    ONLY a dropped record reaches removed, or None where there are none.

    A row is dead when it is reachable from some record of the file as
    written but not from a kept record, a pattern's CMD_SETPULSEPTR /
    CMD_SETFILTERPTR, or a wavetable $F9 / $FA command row (every wavetable
    row counts, reachable or not: the wavetable is not pruned here, and a row
    that names a pulse block keeps it). Rows no record reaches at all are
    left as written, as before. The maps renumber a pointer past the removed
    rows (a removed target, only possible from a row nothing executes, lands
    on the next kept row)."""
    count = blob[instr_at]
    recs = instr_at + 1
    pos = tables_at
    raw = []
    for _ in range(len(_TABLE_NAMES) if blob[:4] == b"GTS5" else 3):
        n = blob[pos]
        raw.append((pos, [(blob[pos + 1 + i], blob[pos + 1 + n + i])
                          for i in range(n)]))
        pos += 1 + 2 * n
    wave, pulse, filt = raw[0][1], raw[1][1], raw[2][1]
    cmd_p, cmd_f = set(), set()
    for start, rows in patterns:
        for r in range(rows):
            cmd, data = blob[start + r * 4 + 2], blob[start + r * 4 + 3]
            if data and cmd == _CMD_SETPULSEPTR:
                cmd_p.add(data)
            elif data and cmd == _CMD_SETFILTERPTR:
                cmd_f.add(data)
    for left, right in wave:
        if right and _WAVE_FIRST_CMD <= left <= _WAVE_LAST_CMD:
            if left & 0xF == _CMD_SETPULSEPTR:
                cmd_p.add(right)
            elif left & 0xF == _CMD_SETFILTERPTR:
                cmd_f.add(right)

    def pointers(at: int, which: List[int]) -> set:
        return {blob[recs + (k - 1) * _RECORD_LEN + at] for k in which} - {0}

    removed = []
    for at, rows, extra in ((_PULSE_AT, pulse, cmd_p),
                            (_FILTER_AT, filt, cmd_f)):
        everyone = _reach(rows, pointers(at, list(range(1, count + 1))) | extra)
        kept = _reach(rows, pointers(at, keep) | extra)
        removed.append(everyone - kept)
    if not removed[0] and not removed[1]:
        return None

    def mapper(rows: List[Tuple[int, int]], gone: set):
        before = [0]
        for r in range(1, len(rows) + 1):
            before.append(before[-1] + (r in gone))

        def m(x: int) -> int:
            if x == 0:
                return 0
            if x <= len(rows):
                return x - before[x - 1]
            return x - len(gone)
        return m

    maps = [mapper(pulse, removed[0]), mapper(filt, removed[1])]
    out = bytearray()
    wave_out = []
    for left, right in wave:
        if right and _WAVE_FIRST_CMD <= left <= _WAVE_LAST_CMD:
            if left & 0xF == _CMD_SETPULSEPTR:
                right = maps[0](right)
            elif left & 0xF == _CMD_SETFILTERPTR:
                right = maps[1](right)
        wave_out.append((left, right))
    out.append(len(wave_out))
    out += bytes(left for left, _ in wave_out)
    out += bytes(right for _, right in wave_out)
    for (_, rows), gone, m in ((raw[1], removed[0], maps[0]),
                               (raw[2], removed[1], maps[1])):
        live = [(left, m(right) if left == _TABLE_JUMP else right)
                for r, (left, right) in enumerate(rows, 1) if r not in gone]
        out.append(len(live))
        out += bytes(left for left, _ in live)
        out += bytes(right for _, right in live)
    out += blob[raw[2][0] + 1 + 2 * len(filt):patt_at]
    if log:
        log(f"Dropped {len(removed[0])} pulse and {len(removed[1])} filter "
            f"table row(s) only a dropped instrument reaches")
    return bytes(out), maps[0], maps[1]


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
    tables = _drop_dead_blocks(blob, instr_at, tables_at, patt_at, patterns,
                               keep, log)
    if tables is None:
        out += blob[tables_at:patt_at + 1]
    else:
        out += tables[0]
        # The kept records' pulse / filter pointers, renumbered.
        for n in range(len(keep)):
            for at, m in ((_PULSE_AT, tables[1]), (_FILTER_AT, tables[2])):
                p = recs + n * _RECORD_LEN + at
                out[p] = m(out[p])
        out.append(blob[patt_at])
    pmaps = tables[1:] if tables is not None else None
    for start, rows in patterns:
        out.append(rows)
        body = bytearray(blob[start:start + rows * 4])
        for r in range(rows):
            ins = body[r * 4 + 1]
            if ins:
                body[r * 4 + 1] = remap[ins] if ins <= count else ins - dropped
            if pmaps is not None and body[r * 4 + 3]:
                if body[r * 4 + 2] == _CMD_SETPULSEPTR:
                    body[r * 4 + 3] = pmaps[0](body[r * 4 + 3])
                elif body[r * 4 + 2] == _CMD_SETFILTERPTR:
                    body[r * 4 + 3] = pmaps[1](body[r * 4 + 3])
        out += body
    if log:
        gone = [k for k in range(1, count + 1) if k not in remap]
        log(f"Dropped {dropped} instrument(s) no pattern names: "
            + ", ".join(f"${k:02X}" for k in gone))
    return bytes(out)


def onset_rows(blob: bytes, subtune: int, horizon: int
               ) -> Optional[frozenset]:
    """The rows, counted from the song's start, on which some voice of
    `subtune` carries a note, over the first `horizon` rows -- or None where
    the orderlists do not read.

    The rows are the song's clock (every voice's row `j` starts together), so
    this is the set of rows that have something to put on a frame:
    `call_phase.startup_phase` scores a JMP-form gate over exactly these. A
    pattern ends at its `GT_END_PATTERN` row, which takes no time; an
    orderlist's `RST` is followed, its repeat bytes expanded, its transposes
    ignored (a transposed note is still a note).
    """
    try:
        _, _, _, patterns = _layout(blob)
    except ValueError:
        return None
    pos = HEADER_LEN
    subtunes = blob[pos]
    pos += 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        tracks.append(blob[pos + 1:pos + n + 2])
        pos += n + 2
    if not 0 <= subtune < subtunes:
        return None
    rows = set()
    for voice in range(3):
        order = tracks[subtune * 3 + voice]
        row, at, repeat, steps = 0, 0, 1, 0
        while row < horizon and at < len(order) and steps < 4 * horizon + 64:
            steps += 1
            b = order[at]
            if b == GT_ORDER_RESTART:
                if at + 1 >= len(order) or order[at + 1] >= len(order):
                    break
                at = order[at + 1]
            elif b >= GT_TRANSPOSE_DOWN:
                at += 1
            elif b >= GT_REPEAT:
                repeat = b - GT_REPEAT + 1
                at += 1
            else:
                if b >= len(patterns):
                    return None
                start, count = patterns[b]
                for _ in range(repeat):
                    for r in range(count):
                        note = blob[start + r * 4]
                        if note == GT_END_PATTERN:
                            break
                        if GT_FIRST_NOTE <= note <= GT_LAST_NOTE and row < horizon:
                            rows.add(row)
                        row += 1
                repeat = 1
                at += 1
    return frozenset(rows)


def add_startup_tempo(blob: bytes, tempo: int,
                      log: Optional[Callable[[str], None]] = None) -> bytes:
    """`blob` carrying instrument 63 with attack/decay `tempo` and nothing else.

    gt2reloc reads that record as the packed song's startup row,
    DEFAULTTEMPO `tempo - 1` (greloc.c:1140-1141: `ad >= 2` and no wavetable
    pointer), and `goatwriter.call_phase` says why a song wants one. Records
    below 63 are padded with empty ones, because a `.sng` stores instruments
    1..N contiguously; no pattern names them, so the packed file carries none
    of them (greloc.c:291), and neither does it carry 63 itself -- only the
    one define.

    **Last, on the finished bytes, after `drop_unnamed_instruments`**, which
    would drop every one of these records: none is named by a pattern, which
    is the point of them.

    Returned unchanged (and logged) where the record cannot be added without
    changing what the song plays: the file already uses instrument 63; a
    pattern names an instrument above the written count, which the padding
    would turn from a dangling reference into an empty record; or some
    record's gatetimer is not reached by the startup row's counter (it counts
    `tempo - 1` down to 0, and row 0's note is fetched only where it equals
    the gatetimer of the instrument the voice starts on -- player.s
    `mt_gatetimer`; the superseded `--tempo` route went silent exactly so).
    """
    instr_at, tables_at, _patt_at, patterns = _layout(blob)
    count = blob[instr_at]
    named = {blob[start + r * 4 + 1]
             for start, rows in patterns for r in range(rows)}
    recs = instr_at + 1
    gatetimers = [blob[recs + k * _RECORD_LEN + _GATETIMER_AT] & _GATETIMER_MASK
                  for k in range(count)]
    why = (f"the song already has {count} instruments" if count >= GT_TEMPO_INSTRUMENT
           else f"a pattern names instrument ${max(named):02X} above the "
                f"{count} written" if named and max(named) > count
           else f"a gatetimer of {max(gatetimers)} is not reached in a "
                f"{tempo}-call startup row" if gatetimers and max(gatetimers) > tempo - 1
           else None)
    if why is not None:
        if log:
            log(f"Startup call phase......: declined, {why}")
        return bytes(blob)
    record = bytes([tempo & 0xFF]) + bytes(8)
    record += _STARTUP_TEMPO_NAME.encode("latin-1").ljust(_RECORD_LEN - 9, b"\x00")
    out = bytearray(blob[:instr_at])
    out.append(GT_TEMPO_INSTRUMENT)
    out += blob[recs:tables_at]
    out += bytes(_RECORD_LEN) * (GT_TEMPO_INSTRUMENT - 1 - count)
    out += record
    out += blob[tables_at:]
    return bytes(out)
