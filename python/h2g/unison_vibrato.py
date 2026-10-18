"""Two voices playing one note with one vibrato, a fraction of a cycle apart.

The classic `$78/$07` vibrato keeps its counter and direction PER VOICE and
nothing resets them at a note (`goatwriter.vibrato._classic_vibrato_entry`,
"Phase"). So a voice's phase at a note is whatever the voice's history left,
and two voices that double a melody on the same record carry a fixed offset
between them for as long as both run the update on the same calls. That is a
chorus: the two pitches sit a fraction of a semitone apart and the beat
between them roams. Goattracker restarts `vibtime` at every note
(gplay.c:723), so both voices of a doubled note start in phase and stay
equal -- the chorus is gone.

International_Karate (`$AE00` player) is the case that was heard (user,
2026-10-18: "at 0:08 the two voices should be slightly off each other"). Its
update, after the split at `$AFE8`:

    AFF7  BD FF B2  LDA $B2FF,X   ; direction
    AFFA  10 0A     BPL up
    AFFC  DE DD B2  DEC $B2DD,X   ; counter, walking down
    AFFF  D0 19     BNE out
    B001  FE FF B2  INC $B2FF,X   ; at 0: turn up
    B004  10 14     BPL out
    B006  FE DD B2  INC $B2DD,X   ; up
    B009  BD FC B2  LDA $B2FC,X   ; the bound
    B00C  DD DD B2  CMP $B2DD,X
    B00F  B0 09     BCS out
    B011  9D DD B2  STA $B2DD,X   ; past it: clamp,
    B014  DE FF B2  DEC $B2FF,X   ; turn down,
    B017  DE DD B2  DEC $B2DD,X   ; and step back

Nothing else in the player stores `$B2DD`/`$B2FF` (the init at `$BE90` does
not), so the image's bytes are the start state: counters 02 01 04,
directions FF 00 FF. The note-fetch call leaves through `JMP $B1E2` before
the update (`$AF98`), so the counter holds on a fetch. Voices 1 and 3 double
the melody on record 6 (vibrato byte `$2B`, bound 5) from frame 425 to 1270,
and over all 1271 frames there voice 3's counter is two updates behind
voice 1's (siddump-rt -w over 200 s).

**What is emitted.** The phase itself cannot be carried (each note's
absolute phase is scattered), but the OFFSET between two voices can: the
lagging voice's note takes a clone of its record whose `vibdelay` is longer
by the offset, so its oscillation is the leading voice's delayed by that
many calls. The offset is read off the original's own update, simulated per
voice over the finished rows (`frames` passing calls a row, a step on every
call whose record has a vibrato byte except the fetch), from the image's
counters. The calls are the offset's share of Goattracker's own period for
the entry (`_gt_period`), so the delay is a phase of the oscillator that
plays it. The cost is the delay itself: the lagging voice holds the note
for those calls before its vibrato starts.

A note is doubled when another voice fetches the same note (after
transposes) on the same row, on a record with the same vibrato byte, and
neither row carries a pitch command (a tie, a slide or `CMD_VIBRATO` makes
`vibdelay` moot). Patterns the lagging voice plays are copied with the clone
named on its rows, every note row of the copy naming its instrument
explicitly, and the base record restored on the first free row after the
last clone so a later `instr 00` note keeps the base. One lap of each
orderlist; a repeated entry is copied only where every repeat agrees.
"""
from typing import Callable, Dict, List, Optional, Tuple

from .detect import (Detection, VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     _find_vibrato_site)
from .goatwriter import GT_TEMPO_INSTRUMENT, HEADER_LEN
from .goatwriter.constants import (CMD_TONEPORTA, CMD_VIBRATO, GT_FIRST_NOTE,
                                   GT_LAST_NOTE)
from .goatwriter import tempo as _gw_tempo
from .instrument_drop import _RECORD_LEN, _layout
from .patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,
                       GT_TRANSPOSE_DOWN, GT_TRANSPOSE_UP, MAX_PATTERNS)
from .sidfile import SidFile

_MAX_RECORDS = GT_TEMPO_INSTRUMENT - 1
_STBL_AT = 5            # record byte: speed-table pointer (1-based)
_VIBDELAY_AT = 6        # record byte: vibdelay
_NAME_AT = 9
# Row commands that replace the instrument vibrato on a note: portamento up
# and down, tone portamento (tie or slide), and an explicit vibrato.
_PITCH_COMMANDS = (0x01, 0x02, CMD_TONEPORTA, CMD_VIBRATO)


def counter_cells(sid: SidFile, det: Detection) -> Optional[Tuple[int, int]]:
    """(counter, direction) base addresses of the classic update, or None.

    Read where the update follows the split directly -- `LDA dir,X / BPL /
    DEC ctr,X ... INC dir,X / BPL / INC ctr,X / LDA bound,X / CMP ctr,X /
    BCS / STA ctr,X / DEC dir,X / DEC ctr,X` (the clamp-then-step-back top,
    period `2 * bound`), all absolute,X. Any other spelling is None: the
    simulation below is this update's, and only this one's.
    """
    if (det.vibrato_offset is None or det.triangle_vibrato is not None
            or det.table_vibrato is not None or det.vibrato_dwell
            or det.track_voices != 3):
        return None
    site = _find_vibrato_site(sid, det)
    if site is None:
        return None
    d = sid.data
    at = site[1] + 15                      # past `48 29 78 ... 8D ?? ??`
    if d[site[1] + 9] != 0x68 or d[site[1] + 12] != 0x8D:
        return None                        # not the all-absolute split
    b = d[at:at + 35]
    if len(b) < 35:
        return None

    def w(i):
        return b[i] | b[i + 1] << 8

    if not (b[0] == 0xBD and b[3] == 0x10 and b[5] == 0xDE
            and b[8] == 0xD0 and b[10] == 0xFE and b[13] == 0x10
            and b[15] == 0xFE and b[18] == 0xBD and b[21] == 0xDD
            and b[24] == 0xB0 and b[26] == 0x9D and b[29] == 0xDE
            and b[32] == 0xDE):
        return None
    dirc, ctr = w(1), w(6)
    if not (w(11) == dirc and w(16) == ctr and w(22) == ctr
            and w(27) == ctr and w(30) == dirc and w(33) == ctr):
        return None
    if _other_writer(d, ctr, dirc, {at + i for i in (5, 10, 15, 26, 29, 32)}):
        return None
    return ctr, dirc


# Absolute-operand writes: STA abs / abs,X / abs,Y, STX abs, STY abs, and
# INC / DEC abs and abs,X.
_ABS_WRITES = (0x8D, 0x9D, 0x99, 0x8E, 0x8C, 0xEE, 0xFE, 0xCE, 0xDE)
_INDEXED = (0x9D, 0x99, 0xFE, 0xDE)
_X_STEPS = (0xCA, 0xE8)                         # DEX INX
_Y_STEPS = (0x88, 0xC8)                         # DEY INY
_BRANCHES = (0x10, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0)


def _loop_tail(d: bytes, i: int, op: int) -> bool:
    """The store at `i` is in a loop's body: within 16 bytes after it an
    index step is followed by a branch backward over the store (`STA base,X
    / DEX / BPL`, or several stores before the step)."""
    steps = _Y_STEPS if op == 0x99 else _X_STEPS
    for j in range(i + 3, min(len(d) - 2, i + 19)):
        if d[j] in steps and d[j + 1] in _BRANCHES:
            rel = d[j + 2] - 0x100 if d[j + 2] & 0x80 else d[j + 2]
            if j + 3 + rel <= i:
                return True
    return False
_LOAD_INDEX = (0xA2, 0xA0)                      # LDX # / LDY #
# How far above its base an indexed clear loop with no `LDX #`/`LDY #` in
# sight may reach.
_CLEAR_REACH = 0x80


def _other_writer(d: bytes, ctr: int, dirc: int, own: set) -> bool:
    """True where a byte triple outside the update spells a write that can
    land on a counter or direction cell -- an init-time clear, which makes
    the image's bytes the wrong start state (Shockway_Rider, Spellbound;
    tests/test_classic_vibrato_census.py INIT_CLEARS; the other two are zero
    page, which `counter_cells` does not read). Two shapes: a write whose
    operand IS a voice's cell, and an indexed write in a loop (a DEX/DEY/
    INX/INY within 4 bytes after it) whose base sits below a cell by no more
    than the loop's `LDX #`/`LDY #` start within 16 bytes before it. A byte
    search over code and data alike: a hit in data only declines."""
    cells = [c + v for c in (ctr, dirc) for v in range(3)]
    for i in range(len(d) - 2):
        op = d[i]
        if op not in _ABS_WRITES or i in own:
            continue
        a = d[i + 1] | d[i + 2] << 8
        if a in cells:
            return True
        if op not in _INDEXED or not _loop_tail(d, i, op):
            continue
        reach = _CLEAR_REACH
        for j in range(i - 2, max(-1, i - 17), -1):
            if d[j] in _LOAD_INDEX:
                reach = d[j + 1]
                break
        if any(a < c <= a + reach for c in cells):
            return True
    return False


def step(pos: int, dirc: int, bound: int) -> Tuple[int, int]:
    """One update of the counter, byte for byte (see the module docstring)."""
    if dirc & 0x80:
        pos = (pos - 1) & 0xFF
        if pos:
            return pos, dirc
        dirc = (dirc + 1) & 0xFF
        if not dirc & 0x80:
            return pos, dirc
    pos = (pos + 1) & 0xFF
    if bound >= pos:
        return pos, dirc
    return (bound - 1) & 0xFF, (dirc - 1) & 0xFF


def lag(ahead: Tuple[int, int], behind: Tuple[int, int],
        bound: int) -> Optional[int]:
    """Updates `behind` takes to reach `ahead`'s state, or None (not on the
    cycle within one period)."""
    s = behind
    for k in range(2 * bound + 1):
        if s == ahead:
            return k
        s = step(s[0], s[1], bound)
    return None


def _gt_period(cmp_value: int) -> int:
    """Goattracker's vibrato period in calls for compare value `cmp_value`
    (gplay.c:795-801), read off its steady state."""
    vt, dirs = 0, []
    for _ in range(4096):
        if vt < 0x80 and vt > cmp_value:
            vt ^= 0xFF
        vt = (vt + 2) & 0xFF
        dirs.append(vt & 1)
    tail = dirs[2048:]
    for p in range(2, 1024):
        if all(tail[i] == tail[i + p] for i in range(len(tail) - p)):
            return p
    return 0


def _vibrato_byte(name: bytes) -> Optional[int]:
    """The record's +5 byte from the writer's `NN:b5-b6-b7` name."""
    text = name.split(b"\x00")[0].decode("latin-1", "replace").strip()
    head, _, tail = text.partition(":")
    parts = tail.split("-")
    if len(head) != 2 or len(parts) != 3:
        return None
    try:
        return int(parts[0], 16)
    except ValueError:
        return None


def _rows(order: bytes, pats, blob: bytes):
    """Per orderlist entry: (index, pattern, repeats, transpose, rows) with
    rows a list of (note, instr, command) -- one lap."""
    out = []
    trans, repeat, operand = 0, 1, False
    for i, b in enumerate(order):
        if operand:
            operand = False
            continue
        if b == GT_ORDER_RESTART:
            operand = True
            continue
        if GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
            trans = b - GT_TRANSPOSE_UP
            continue
        if GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
            repeat = b - GT_REPEAT + 1
            continue
        if b >= len(pats):
            repeat = 1
            continue
        start, nrows = pats[b]
        rows = []
        for r in range(nrows):
            n, k, c = blob[start + r * 4], blob[start + r * 4 + 1], blob[start + r * 4 + 2]
            if n == GT_END_PATTERN:
                break
            rows.append((n, k, c))
        out.append((i, b, repeat, trans, rows))
        repeat = 1
    return out


def doubled_note_delays(blob: bytes, sid: SidFile, det: Detection
                        ) -> Dict[Tuple[int, int, int], Tuple[int, int]]:
    """{(track, orderlist index, play, row): (record, updates)} -- each
    doubled note a voice should start late, with the record it plays and the
    lag in the original's updates. Empty where the update is not read."""
    cells = counter_cells(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if cells is None or speeds is None:
        return {}
    try:
        instr_at, _tables_at, _patt_at, pats = _layout(blob)
    except ValueError:
        return {}
    count = blob[instr_at]
    recs = instr_at + 1
    vbyte = {0: None}
    for k in range(1, count + 1):
        at = recs + (k - 1) * _RECORD_LEN
        vbyte[k] = _vibrato_byte(bytes(blob[at + _NAME_AT:at + _RECORD_LEN]))
    init = det.init_instrument
    d = sid.data

    def record_byte(rec):
        off = det.instr_start + rec * det.instr_stride + det.vibrato_offset
        return d[off] if 0 <= off < len(d) else None

    ctr, dirc = cells
    try:
        start = [(d[sid.to_offset(ctr + v)], d[sid.to_offset(dirc + v)])
                 for v in range(3)]
    except Exception:                       # noqa: BLE001 -- unreadable cells
        return {}
    subtunes = blob[HEADER_LEN]
    pos = HEADER_LEN + 1
    orders = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        orders.append(bytes(blob[pos + 1:pos + n + 2]))
        pos += n + 2
    out: Dict[tuple, Tuple[int, int]] = {}
    for s in range(subtunes):
        frames = speeds.frames_for(s)
        if not frames:
            continue
        # Per voice, per row: (note or None, instr, command, place) and the
        # counter state on the fetch call.
        lanes, trails, firsts = [], [], []
        for v in range(3):
            ti = s * 3 + v
            first = (init if init is not None and init >= 0 else
                     (det.initial_instruments[v]
                      if v < len(det.initial_instruments) else None))
            cur_byte = record_byte(first) if first is not None else None
            firsts.append(cur_byte)
            cur = 0
            state = start[v]
            lane = []
            trail = []                  # per update: the bound stepped, or -1
            for i, p, repeat, trans, rows in _rows(orders[ti], pats, blob):
                for play in range(repeat):
                    for r, (n, k, c) in enumerate(rows):
                        if k:
                            cur = k
                            cur_byte = vbyte.get(k)
                        note = n if GT_FIRST_NOTE <= n <= GT_LAST_NOTE else None
                        lane.append((None if note is None else note + trans,
                                     cur, c, (ti, i, play, r), state, cur_byte,
                                     len(trail)))
                        for j in range(frames):
                            if (note is not None and j == 0) or not cur_byte:
                                trail.append(-1)  # the fetch skips the update
                                continue
                            bound = ((cur_byte & VIBRATO_BOUND_MASK)
                                     >> VIBRATO_BOUND_SHIFT)
                            state = step(state[0], state[1], bound)
                            trail.append(bound)
            lanes.append(lane)
            trails.append(trail)
        # Per pair, the first update on which the two voices did not step
        # alike. Only a pair still in lockstep at a doubled note is trusted:
        # its offset is then the image's, whatever this walk mis-reads about
        # the rows (a rest that is a fetch, a pre-roll), because both voices
        # mis-read it alike.
        split = {}
        for a in range(3):
            for b in range(a + 1, 3):
                ta, tb = trails[a], trails[b]
                u = next((u for u in range(min(len(ta), len(tb)))
                          if ta[u] != tb[u]), min(len(ta), len(tb)))
                if firsts[a] != firsts[b]:
                    # The calls before the first fetch run the update on the
                    # record the player starts each voice on, which the rows
                    # do not show (Thrust: records 23, 26, 21, vibrato bytes
                    # $00, $30, $11 -- voices 2 and 3 step on the first call
                    # and voice 1 does not).
                    u = -1
                split[(a, b)] = split[(b, a)] = u
        for row in range(min(len(lane) for lane in lanes) if lanes else 0):
            cells_here = [lanes[v][row] for v in range(3)]
            groups: Dict[tuple, List[int]] = {}
            for v, (note, cur, c, _pl, _st, byte, _u) in enumerate(cells_here):
                if (note is None or not byte or c in _PITCH_COMMANDS
                        or not cur or vbyte.get(cur) != byte):
                    continue
                groups.setdefault((note, byte), []).append(v)
            for (_note, byte), vs in groups.items():
                if len(vs) < 2:
                    continue
                bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
                if bound < 1:
                    continue
                best = None
                for ref in vs:
                    lags = {}
                    for v in vs:
                        if v == ref:
                            continue
                        k = lag(cells_here[ref][4], cells_here[v][4], bound)
                        if k is None or split[(ref, v)] < cells_here[v][6]:
                            break
                        lags[v] = k
                    else:
                        cost = max(lags.values())
                        if best is None or cost < best[0]:
                            best = (cost, lags)
                if best is None:
                    continue
                for v, k in best[1].items():
                    if k:
                        out[cells_here[v][3]] = (cells_here[v][1], k)
    return out




def _respell(body: bytearray, nrows: int, mapping: Dict[int, tuple]
             ) -> Optional[bytearray]:
    """`body` with each mapped row naming its clone key, every later note row
    that named nothing naming the base it played under, and the base restored
    on the first free row after a clone, before the next note. None where a
    clone would still be in effect when the pattern ends."""
    out = bytearray(body)
    eff = None                  # the instrument in effect in the ORIGINAL
    live = None                 # in the copy: None = same as eff, else a key
    for r in range(nrows):
        n, k = out[r * 4], out[r * 4 + 1]
        if n == GT_END_PATTERN:
            break
        note = GT_FIRST_NOTE <= n <= GT_LAST_NOTE
        if r in mapping:
            eff = mapping[r][0]     # the clone number goes in after
            live = mapping[r]
            continue
        if k:
            eff = k
            live = None
            continue
        if live is not None:
            # A note that named nothing names its base; a free row before
            # the next note restores the base for whatever follows.
            out[r * 4 + 1] = eff
            live = None
    if live is not None:
        return None
    return out


def chorus_doubled_notes(blob: bytes, sid: SidFile, det: Detection,
                         log: Optional[Callable[[str], None]] = None) -> bytes:
    """`blob` with each doubled note's lagging voice started late by the
    original's offset (module docstring). Unchanged where nothing is
    doubled out of phase, or the clones and copies would not fit."""
    delays = doubled_note_delays(blob, sid, det)
    if not delays:
        return bytes(blob)
    instr_at, tables_at, patt_at, pats = _layout(blob)
    count = blob[instr_at]
    recs = instr_at + 1
    # The speed table: the fourth table in GTS5 (wave, pulse, filter, speed).
    if bytes(blob[:4]) != b"GTS5":
        return bytes(blob)
    pos = tables_at
    for _ in range(3):
        pos += 1 + 2 * blob[pos]
    n_stbl = blob[pos]
    stbl_left = blob[pos + 1:pos + 1 + n_stbl]

    def record(k):
        at = recs + (k - 1) * _RECORD_LEN
        return bytes(blob[at:at + _RECORD_LEN])

    def calls(k, updates):
        rec = record(k)
        ptr, delay = rec[_STBL_AT], rec[_VIBDELAY_AT]
        byte = _vibrato_byte(rec[_NAME_AT:])
        if not ptr or not delay or ptr > n_stbl or not byte:
            return None
        bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
        period = _gt_period(stbl_left[ptr - 1] & 0x7F)
        if not period or not bound:
            return None
        return round(updates * period / (2 * bound))

    want: Dict[Tuple[int, int, int], Dict[int, tuple]] = {}
    for (ti, i, play, r), (k, updates) in delays.items():
        extra = calls(k, updates)
        if extra:
            want.setdefault((ti, i, play), {})[r] = (k, extra)

    subtunes = blob[HEADER_LEN]
    pos = HEADER_LEN + 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        tracks.append((pos + 1, bytes(blob[pos + 1:pos + n + 2])))
        pos += n + 2
    # Per orderlist entry the copy it takes; an entry whose repeats disagree,
    # or whose copy would leave a clone in effect past its end, is left alone.
    plans = []                              # (orderlist offset, pattern, mapping, body)
    for ti, (off, order) in enumerate(tracks):
        for i, p, repeat, _trans, _r in _rows(order, pats, blob):
            maps = [want.get((ti, i, play)) for play in range(repeat)]
            if not maps[0] or any(m != maps[0] for m in maps):
                continue
            start, nrows = pats[p]
            body = _respell(bytearray(blob[start:start + nrows * 4]), nrows,
                            maps[0])
            if body is None:
                continue
            plans.append((off + i, p, maps[0], body, nrows))
    keys = sorted({key for _o, _p, m, _b, _n in plans for key in m.values()})
    if not plans:
        return bytes(blob)
    clone_of = {key: count + 1 + j for j, key in enumerate(keys)}
    bodies: Dict[bytes, int] = {}
    new_patterns: List[bytes] = []
    repoint: Dict[int, int] = {}
    for at, _p, mapping, body, nrows in plans:
        for r, key in mapping.items():
            body[r * 4 + 1] = clone_of[key]
        raw = bytes([nrows]) + bytes(body)
        if raw not in bodies:
            bodies[raw] = len(pats) + len(new_patterns)
            new_patterns.append(raw)
        repoint[at] = bodies[raw]
    if (count + len(keys) > _MAX_RECORDS
            or len(pats) + len(new_patterns) > MAX_PATTERNS):
        if log:
            log(f"Doubled-note vibrato....: declined, {len(keys)} clone(s) and "
                f"{len(new_patterns)} pattern copies would need "
                f"{count + len(keys)} instruments and "
                f"{len(pats) + len(new_patterns)} patterns")
        return bytes(blob)
    out = bytearray(blob)
    for at, p in repoint.items():
        out[at] = p
    clones = bytearray()
    for k, extra in keys:
        rec = bytearray(record(k))
        rec[_VIBDELAY_AT] = min(0xFF, rec[_VIBDELAY_AT] + extra)
        clones += rec
    res = bytearray(out[:instr_at])
    res.append(count + len(keys))
    res += out[recs:tables_at]
    res += clones
    res += out[tables_at:patt_at]
    res.append(len(pats) + len(new_patterns))
    res += out[patt_at + 1:]
    for raw in new_patterns:
        res += raw
    if log:
        notes = sum(len(m) for _a, _p, m, _b, _n in plans)
        log("Doubled-note vibrato....: "
            f"{notes} doubled note row(s) started late on the lagging voice ("
            + ", ".join(f"${k:02X}+{extra}->${clone_of[(k, extra)]:02X}"
                        for k, extra in keys)
            + f" calls of vibdelay); {len(new_patterns)} pattern(s) copied")
    return bytes(res)
