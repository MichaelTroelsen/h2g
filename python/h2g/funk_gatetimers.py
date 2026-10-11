"""Give each subtune's instruments the gatetimer of the row THAT subtune plays.

A 2-call row (`goatwriter.constants.CMD_FUNKTEMPO`) bounds an instrument's
gatetimer to 1: the packed player's counter on such a row never reaches 2
(player.s:1090-1098), so a gatetimer of 2 stalls the voice. The writer
(`goatwriter.instruments._write_instruments`) charges that bound per
instrument, as the MINIMUM row over the subtunes the instrument is played in
(`tracks.instrument_row_calls`) -- right as a safety bound, and a cost for an
instrument that is also played in a longer subtune, whose gate-off then
starts one tick earlier than its own rows would allow.

Two things go wrong, and both are fixed here, on the FINISHED bytes (the
house style of `instrument_drop`: every pass that writes or renumbers an
instrument column has run, so this cannot disagree with any of them):

* **A record the attribution never saw.** The clone passes (legato, tie,
  phase, duty, drum variants) append records after `instrument_row_calls` has
  been taken, and a record with no entry there is bounded by the file-wide
  `short_row_calls` -- 2 as soon as one subtune is a funk subtune. Such a
  record that only longer subtunes play is raised to the gatetimer its own
  shortest row allows.
* **A record played in both.** The funk subtune's rows cannot share a record
  with the longer ones, so the record is split: the original keeps the
  record number and is raised to the longer subtunes' gatetimer, and a CLONE
  with the old (low) gatetimer takes the funk subtunes' explicit uses of it.
  A pattern only funk subtunes play is respelled in place; one a longer
  subtune plays as well is copied and the funk orderlists repointed.

**Instrument 1 is never split.** Every voice starts on it without any
pattern naming it (`gplay.c:62`, `player.s:621`), so a funk voice opening on
rests runs under the record and no pattern column can move it; a record with
an implicit use in a funk subtune keeps its low gatetimer for everyone.

Nothing is touched unless the file has a funk subtune AND a longer one, and
a record whose gatetimer is not exactly what the funk row would have given it
(`ticks_for(2)`) is left alone: the value was set for a reason this pass does
not know.
"""
from typing import Callable, Dict, List, Optional, Set

from .goatwriter import GT_TEMPO_INSTRUMENT, HEADER_LEN
from .goatwriter.constants import FUNK_ROW_CALLS
from .instrument_drop import _GATETIMER_AT, _GATETIMER_MASK, _RECORD_LEN, _layout
from .patterns import GT_ORDER_RESTART, MAX_PATTERNS

# Records that fit once the tempo record (63) is kept free for.
_MAX_RECORDS = GT_TEMPO_INSTRUMENT - 1


def _pattern_entries(order: bytes):
    """(index, pattern number) for each pattern an orderlist names; the
    restart position after `$FF` and the repeat/transpose bytes are not."""
    operand = False
    for i, b in enumerate(order):
        if operand:
            operand = False
        elif b == GT_ORDER_RESTART:
            operand = True
        elif b < MAX_PATTERNS:
            yield i, b


def split_funk_gatetimers(blob: bytes, rows: List[int],
                          ticks_for: Callable[[int], int],
                          log: Optional[Callable[[str], None]] = None
                          ) -> bytes:
    """`blob` with each record's gatetimer matched to the rows that play it.

    `rows[s]` is subtune `s`'s row in play calls (`convert`'s `group_tempos`);
    `ticks_for(row)` is the gatetimer ticks the writer gives a record whose
    shortest row is `row`. Returned unchanged where the file has no funk
    subtune, no longer one, or the subtunes do not line up with `rows`.
    """
    funk = {s for s, r in enumerate(rows) if r == FUNK_ROW_CALLS}
    if not funk or len(funk) == len(rows):
        return bytes(blob)
    try:
        instr_at, tables_at, patt_at, pats = _layout(blob)
    except ValueError:
        return bytes(blob)
    subtunes = blob[HEADER_LEN]
    if subtunes != len(rows):
        return bytes(blob)
    pos = HEADER_LEN + 1
    tracks = []                     # (absolute offset, bytes) per orderlist
    for _ in range(subtunes * 3):
        n = blob[pos]
        tracks.append((pos + 1, bytes(blob[pos + 1:pos + n + 2])))
        pos += n + 2
    count = blob[instr_at]
    recs = instr_at + 1

    played: Dict[int, Set[int]] = {}        # pattern -> subtunes playing it
    explicit: Dict[int, Set[int]] = {}      # record -> subtunes naming it
    implicit: Dict[int, Set[int]] = {}      # record -> subtunes opening on it
    for ti, (_off, order) in enumerate(tracks):
        s = ti // 3
        first = True
        for _i, p in _pattern_entries(order):
            played.setdefault(p, set()).add(s)
            if p >= len(pats):
                first = False
                continue
            start, nrows = pats[p]
            if first and not blob[start + 1]:
                implicit.setdefault(1, set()).add(s)
            first = False
            for r in range(nrows):
                k = blob[start + r * 4 + 1]
                if k:
                    explicit.setdefault(k, set()).add(s)

    funk_ticks = ticks_for(FUNK_ROW_CALLS)
    out = bytearray(blob)
    raised: List[int] = []
    split: List[int] = []
    for k in range(1, count + 1):
        users = explicit.get(k, set()) | implicit.get(k, set())
        if not users:
            continue
        at = recs + (k - 1) * _RECORD_LEN + _GATETIMER_AT
        cur = blob[at] & _GATETIMER_MASK
        if cur != funk_ticks:
            continue
        longer = users - funk
        if not longer:
            continue
        target = ticks_for(min(rows[s] for s in longer))
        if target == cur:
            continue
        if not users & funk:
            raised.append(k)
        elif not implicit.get(k, set()) & funk:
            split.append(k)

    # The clone numbers and the patterns the funk subtunes need respelled.
    new_patterns: List[bytes] = []
    clone_of = {k: count + 1 + i for i, k in enumerate(split)}
    repoint: Dict[int, int] = {}            # funk pattern -> its copy
    respell: Set[int] = set()
    if split:
        for p, ss in played.items():
            if not ss & funk or p >= len(pats):
                continue
            start, nrows = pats[p]
            if not any(blob[start + r * 4 + 1] in clone_of
                       for r in range(nrows)):
                continue
            if ss <= funk:
                respell.add(p)
            else:
                repoint[p] = len(pats) + len(repoint)
        if (count + len(split) > _MAX_RECORDS
                or len(pats) + len(repoint) > MAX_PATTERNS):
            if log:
                log(f"Funk gatetimers.........: declined, {len(split)} "
                    f"record(s) to split would need {count + len(split)} "
                    f"instruments and {len(pats) + len(repoint)} patterns")
            split, clone_of, repoint, respell = [], {}, {}, set()

    if not (raised or split):
        return bytes(blob)

    # The clones carry the OLD gatetimer; the original record is raised.
    clones = bytearray()
    for k in split:
        rec = recs + (k - 1) * _RECORD_LEN
        clones += blob[rec:rec + _RECORD_LEN]
    for k in raised + split:
        at = recs + (k - 1) * _RECORD_LEN + _GATETIMER_AT
        longer = (explicit.get(k, set()) | implicit.get(k, set())) - funk
        target = ticks_for(min(rows[s] for s in longer))
        out[at] = (out[at] & ~_GATETIMER_MASK & 0xFF) | (target & _GATETIMER_MASK)

    def respelled(p: int) -> bytes:
        start, nrows = pats[p]
        body = bytearray(blob[start:start + nrows * 4])
        for r in range(nrows):
            k = body[r * 4 + 1]
            if k in clone_of:
                body[r * 4 + 1] = clone_of[k]
        return bytes(body)

    for p in respell:
        start, nrows = pats[p]
        out[start:start + nrows * 4] = respelled(p)
    copies = sorted(repoint.items(), key=lambda kv: kv[1])
    for p, _n in copies:
        new_patterns.append(bytes([pats[p][1]]) + respelled(p))
    for ti, (off, order) in enumerate(tracks):
        if ti // 3 not in funk:
            continue
        for i, p in _pattern_entries(order):
            if p in repoint:
                out[off + i] = repoint[p]

    # Reassemble: records grow (before the tables), patterns grow (at the end).
    res = bytearray(out[:instr_at])
    res.append(count + len(split))
    res += out[recs:tables_at]
    res += clones
    res += out[tables_at:patt_at]
    res.append(len(pats) + len(copies))
    res += out[patt_at + 1:]
    for body in new_patterns:
        res += body
    if log:
        parts = []
        if raised:
            parts.append(f"{len(raised)} record(s) no funk subtune plays "
                         "raised to their own rows' gatetimer: "
                         + ", ".join(f"${k:02X}" for k in raised))
        if split:
            parts.append(f"{len(split)} record(s) played in both a "
                         f"{FUNK_ROW_CALLS}-call subtune and a longer one "
                         "split ("
                         + ", ".join(f"${k:02X}->${clone_of[k]:02X}"
                                     for k in split)
                         + f"), {len(respell)} pattern(s) respelled and "
                         f"{len(copies)} copied")
        log("Funk gatetimers.........: " + "; ".join(parts))
    return bytes(res)
