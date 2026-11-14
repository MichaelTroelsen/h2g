"""A ringing rest's KEYOFF one row later, so the gate drops where the original's does.

The player's rest drops the gate on its FIRST tick (Las_Vegas_Video_Poker
`$511F DEC $54D2`, the mask `$FF -> $FE` before the shared tail writes
`wave & mask`), and a note entered with status bit 5 has no cut of its own
before it, so the note sounds its full length and the gate goes down at the
rest's row. A KEYOFF row cannot say that. Goattracker fetches the row after
the current one `gatetimer` calls before the current one ends (gplay.c:854,
:905, `tick == gatetimer` with `tick` reloaded to `tempo` one call after tick
0), and a KEYOFF takes effect AT THE FETCH (gplay.c:928, `gate = 0xfe`). With
a row of `R` calls and a record's gatetimer `g` the gate therefore drops `g`
calls BEFORE the KEYOFF row begins:

    KEYOFF on the rest's first row   gate off at   -g         calls
    KEYOFF on the rest's second row  gate off at   R - g      calls

relative to the rest's first tick. Las_Vegas voice 1, `-S4`, rows of 15 calls
and `gatetimer` 14 (`max_hard_restart`): -14 calls is 3.5 frames, and the 36
notes before a ringing rest sound 11 frames where the original sounds 15
(`gate` .9724, 144 miss frames, every one at offsets 11-14 of record
`AD$0A SR$0C`). One row later it is +1 call, the call after the rest's tick 0,
which is the frame the original's rest begins in (the call phase puts a row's
events on the call after its tick 0, `call_phase.ONSET_CALL`).

WHICH RESTS. Only a rest that `goatwriter.rest_ring` rings: the row before its
KEYOFF carries `CMD_SETSR <nonzero>`, the uncut SR of the held instrument,
because that rest was entered with the gate OPEN (the note before it had status
bit 5, a tie). A rest after a note that cut itself (the other 5 Las_Vegas notes
before a rest: gate 11 frames, rest 19, original and ours alike) has its gate
shut by the note's own end-cut, which the KEYOFF's early fetch stands in for,
and moving that KEYOFF would open the gate 4 frames too long. The SETSR
signature is read off the rows, so a pattern is only edited where every visit
of it agrees; a rest that opens a pattern and is entered ringing from some
positions and not from others gets a COPY of the pattern at the ringing ones.

WHEN IT PAYS. The new gate-off lands `R - g` calls after the rest begins, the
old one `g` before: the KEYOFF moves only where that is at least one frame
(`multiplier` calls) closer, `R - g + multiplier <= g`. A record whose
gatetimer is half the row or less (the fetch is already near the row) keeps
its row. Needs the subtune's row length in calls (`convert`'s
`group_tempos`); without it nothing is changed.

The row it moves to must be a bare rest (`$BD`, no instrument): the KEYOFF row
may carry a command (the rest's pulse reseed) and that stays where it is, so it
still runs on the rest's tick 0, and so does the `CMD_TONEPORTA 00` a rest
after a tied note is given (`ALLOW_TONEPORTA`).
"""
from typing import Callable, Dict, List, Optional, Tuple

from .goatwriter import HEADER_LEN
from .goatwriter.constants import PACKED_PATTERN_LIMIT
from .goatwriter.pulse import packed_pattern_size, pattern_rows
from .patterns import (CMD_SETSR, CMD_TONEPORTA, GT_END_PATTERN, GT_KEYOFF,
                       GT_ORDER_RESTART, GT_REPEAT, GT_REST,
                       GT_TRANSPOSE_DOWN, MAX_PATTERNS)

_RECORD_LEN = 25
_GATETIMER_AT = 7

# Test seam: False leaves every KEYOFF where it is (tests/test_rest_late_keyoff.py).
ENABLED = True
# A KEYOFF row that carries `CMD_TONEPORTA` (the tied rest's `CMD_TONEPORTA
# 00`, which the KEYOFF path never reads) moves with the rest. Measured on
# the four files that carry one at a rest that moves (-t 180 --sound):
# Confuzion gate .9950 -> .9964, Game_Killer .8879 -> .8889, Spellbound
# .9238 -> .9255 against .9251 without it, Las_Vegas unchanged -- melody, seq,
# pitch, wave, adsr and every other column equal. False (the seam) keeps those
# rows where they are.
ALLOW_TONEPORTA = True


def _walk(track: List[int], npatterns: int):
    """(position, pattern, repeat index, lap) in play order: the orderlist
    once, then from its restart position once more -- `prev_class_firstwave.
    _visits` with the position kept."""
    restart = 0
    repeat = 1
    body: List[Tuple[int, int, int]] = []
    for pos, b in enumerate(track):
        if b == GT_ORDER_RESTART:
            restart = track[pos + 1] if pos + 1 < len(track) else 0
            break
        if GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
            continue
        if GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
            repeat = b - GT_REPEAT + 1
            continue
        if b >= MAX_PATTERNS or b >= npatterns:
            repeat = 1
            continue
        body.append((pos, b, repeat))
        repeat = 1
    seq = []
    for pos, b, rep in body:
        seq += [(pos, b, i, 0) for i in range(rep)]
    for pos, b, rep in body:
        if pos >= restart:
            seq += [(pos, b, i, 1) for i in range(rep)]
    return seq


def rest_late_keyoff(blob: bytes, subtune_row_calls: Optional[List[int]],
                     multiplier: int,
                     log: Optional[Callable[[str], None]] = None) -> bytes:
    """`blob` with each ringing rest's KEYOFF moved one row later where that
    puts the gate-off a frame or more nearer the rest's first tick."""
    if not subtune_row_calls or not ENABLED:
        return bytes(blob)
    if bytes(blob[:4]) not in (b"GTS2", b"GTS5"):
        return bytes(blob)
    from .prev_class_firstwave import _layout
    tracks, instr_at, _wtbl, _tables_at, patt_at, patterns = _layout(blob)
    pos = HEADER_LEN + 1
    track_at = []
    for _ in range(len(tracks)):
        track_at.append(pos + 1)
        pos += blob[pos] + 2
    count = blob[instr_at]
    recs = instr_at + 1
    gate_of = {g: blob[recs + (g - 1) * _RECORD_LEN + _GATETIMER_AT] & 0x3F
               for g in range(1, count + 1)}

    def rows_of(b: int) -> List[Tuple[int, int, int, int]]:
        start, nrows = patterns[b]
        out = []
        for r in range(nrows):
            row = tuple(blob[start + 4 * r:start + 4 * r + 4])
            if row[0] == GT_END_PATTERN:
                break
            out.append(row)
        return out

    page = {b: rows_of(b) for b in range(len(patterns))}
    # (pattern, row) -> [(track, position, repeat index, lap, wants)]
    visits: Dict[Tuple[int, int], list] = {}
    for ti, track in enumerate(tracks):
        row_calls = (subtune_row_calls[ti // 3]
                     if ti // 3 < len(subtune_row_calls) else 0)
        live = 0
        last_row = None                 # the previous visit's last real row
        for p, b, idx, lap in _walk(track, len(patterns)):
            rows = page[b]
            for r, (note, ins, cmd, dat) in enumerate(rows):
                if (note == GT_KEYOFF and not ins
                        and (ALLOW_TONEPORTA or cmd != CMD_TONEPORTA)
                        and r + 1 < len(rows)
                        and rows[r + 1][0] == GT_REST and not rows[r + 1][1]):
                    before = rows[r - 1] if r else last_row
                    wants = False
                    if (before is not None and before[2] == CMD_SETSR
                            and before[3] and live in gate_of
                            and row_calls >= 2):
                        g = gate_of[live]
                        wants = (g >= 1 and
                                 row_calls - g + multiplier <= g)
                    visits.setdefault((b, r), []).append(
                        (ti, p, idx, lap, wants))
                if ins:
                    live = ins
            last_row = rows[-1] if rows else None
    if not any(w for v in visits.values() for *_x, w in v):
        return bytes(blob)

    out = bytearray(blob)
    moved_rows = 0
    copies = 0
    new_patterns: List[bytes] = []
    npat = len(patterns)

    def edit(rows: List[Tuple[int, int, int, int]], r: int):
        rows = list(rows)
        n, i, c, d = rows[r]
        rows[r] = (GT_REST, i, c, d)
        n2, i2, c2, d2 = rows[r + 1]
        rows[r + 1] = (GT_KEYOFF, i2, c2, d2)
        return rows

    def fits(rows) -> bool:
        return packed_pattern_size(pattern_rows(
            [x for row in rows for x in row])) <= PACKED_PATTERN_LIMIT

    # Pass one: rows after a pattern's first, which depend on the pattern
    # alone. In place, where every visit agrees.
    current = {b: list(rows) for b, rows in page.items()}
    for (b, r), vs in sorted(visits.items()):
        if r == 0 or not all(v[4] for v in vs):
            continue
        edited = edit(current[b], r)
        if fits(edited):
            current[b] = edited
            moved_rows += 1
    # Pass two: a rest that OPENS its pattern, per orderlist position.
    clone_at: Dict[Tuple[int, int], int] = {}
    for (b, r), vs in sorted(visits.items()):
        if r != 0:
            continue
        if all(v[4] for v in vs):
            edited = edit(current[b], 0)
            if fits(edited):
                current[b] = edited
                moved_rows += 1
            continue
        by_pos: Dict[Tuple[int, int], list] = {}
        for ti, p, idx, lap, w in vs:
            by_pos.setdefault((ti, p), []).append(w)
        number = None
        for (ti, p), ws in sorted(by_pos.items()):
            if not all(ws):
                continue
            if number is None:
                if npat + len(new_patterns) >= MAX_PATTERNS:
                    break
                edited = edit(current[b], 0)
                if not fits(edited):
                    break
                number = npat + len(new_patterns)
                body = [x for row in edited for x in row]
                # The END row the pattern carried is kept as it was.
                start, nrows = patterns[b]
                tail = bytes(blob[start + 4 * len(edited):start + 4 * nrows])
                new_patterns.append(bytes([nrows]) + bytes(body) + tail)
                copies += 1
            clone_at[(ti, p)] = number
            moved_rows += 1
    if not moved_rows:
        return bytes(blob)
    for b, rows in current.items():
        if rows == page[b]:
            continue
        start, _n = patterns[b]
        flat = [x for row in rows for x in row]
        out[start:start + len(flat)] = bytes(flat)
    for (ti, p), number in clone_at.items():
        out[track_at[ti] + p] = number
    out[patt_at] = (npat + len(new_patterns)) & 0xFF
    for body in new_patterns:
        out += body
    if log is not None:
        log(f"Late rest KEYOFF........: {moved_rows} ringing rest(s) "
            f"gate off one row later" + (f", {copies} pattern copy(ies)"
                                         if copies else ""))
    return bytes(out)
