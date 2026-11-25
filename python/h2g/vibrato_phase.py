"""The classic vibrato's free-running counter phase, one instrument clone a note.

The classic `$78/$07` player steps a per-voice triangle (counter and direction)
once a frame and nothing resets it at a note (`unison_vibrato`, `goatwriter.
vibrato`, "Phase"): the swing a note shows from its first active frame is
wherever the voice's history left the triangle, so a pattern replayed later
swings the other way round. Goattracker's `vibtime` restarts at every pitch
write (player.s `mt_wavenote`, gplay.c:723), so every note of a held-vibrato
program (`vibrato_hold`) swings in ONE phase, and the same file's notes hit
the original's phase on about one note in eight. Measured on ACE_II voice 0
(60 s, 92 vibrating notes; `vibrato_hold` forced; figures historical, C:/t/
ace-ii-free-running-vibrato-phase): `depth` .52 -> 1.06, but `tiefr` .749 ->
.673 and `cents` .9575 -> .922. Substituting the ORIGINAL's offsets for those
notes in ours (a stub PSID overriding voice 0's frequency; the oracle) gives
`tiefr` .934, `cents` .981: the loss is the phase, and the whole of it.

**What the original does.** ACE_II `$E218`: counter `$E000,X`, direction
`$E02F,X`, bound `$E003,X` (the record's byte & $78 >> 3), stepped once a frame
by the update `unison_vibrato.step` carries, on every frame whose record has
a vibrato byte EXCEPT a note-fetch frame. The offset is written only from a
note's age 4 (`$E289 LDA $E587,X / CMP #$04 / BCC`): the note sounds flat on
frames 0-3 and from frame 4 sits at `(counter - bound/2)` depths about the
note. The fetch frames are the play routine's row clock, which this module
runs: `DEC outer / BPL / LDA #skip / STA outer / JMP` then the speed gate, and
a fetch where `outer != 0` and the speed counter holds its reload
(`arpeggio._pitch_seq_outer_flat_clock` reads the same shape). The first play
call is the new-song call, which runs none of it; with the cells' own bytes
that reproduces `(8 * r + 1) // 3 + 2`, the frame of row `r`'s fetch, for all
300 rows tried and the 107 voice-0 attacks of the first 60 s; and the counter
walk then reproduces the measured offsets of 59 of the first 60 vibrating
notes (the 60th is a note cut short by the next, whose window the check
mistook).

**What can be emitted.** A note's program is its record's wavetable program
(`vibrato_hold._program`) with, from frame 4:

* `n` ZERO-SPEED `$F4`s on free calls before it, each stepping `vibtime` and
  moving nothing (`mt_effect_4` clears the speed's high byte, the right byte is
  the speed): `vibtime` then walks the direction sequence `U U D.. U..` from its
  `n`-th element, and the sequence is periodic after two elements, so `n` in
  0 .. 2 * bound - 1 reaches every rotation of the original's triangle;
* one `$F1`/`$F2` (a one-step portamento of the note-relative speed, twice the
  shift for two steps) on the call of frame 4: the offset the original is
  already at when it starts to show (`A`, -2 .. 2 depths);
* then the held program's `$F4` on every frame from frame 5, in the record's
  shared loop (`vibrato_hold._held_rows`).

`n` and `A` follow from the original's offsets by one search each, and a note's
class `(record, n, A)` is the whole of what its program differs in.

**Where the room goes.** The wavetable is 255 rows and ACE_II's is 126 of them
before this pass. A class's program cannot be one instrument per class (the
record's first rows, its events and `n` nulls, are 7 - 15 rows each, 38 classes
in the first minute alone: 361 rows measured, the budget 129). So the program is
SPLIT at the pattern's second row, the first call `CMD_SETWAVEPTR` can name:

* a BASE clone of the record, one per `(record, STEM_NULLS or 0)` and shared by
  every record whose events are the same rows, runs the record's events and the
  nulls that fit before that call;
* the note's SECOND pattern row carries `CMD_SETWAVEPTR chain`, which takes the
  pointer at its tick 0 (gplay.c:437, player.s `mt_tick0_8`) -- program time
  `row calls - 1`, the note's call 0 running no wavetable row -- to the class's
  CHAIN: the rest of the nulls, the move, a jump into the record's shared loop;
* chains of one loop share their longest common row suffix that runs from the
  same call (`share`), and the classes are taken by frames covered per row.

A note of a class that is left, or whose second row is a fetch or carries a
command, keeps its record's per-call instrument vibrato, byte for byte. The
note rows of a taken class name the base clone; a clone stays the instrument
across rests (`respell`) and the next note that names nothing names the base
it played under, in a copy of its pattern where the pattern before left a
clone live. Patterns are copied once per orderlist position that needs a
distinct set of rows, as the chorus pass copies them, and only the first lap of
an orderlist is walked -- the second lap of a looping tune meets the triangle
in other phases, which no fixed pattern copy can name. ACE_II's lap is 313 s;
every fidelity figure is taken over its first 180.

Measured, ACE_II `-t 180 --presets --sound`, forced on (historical, C:/t/ace-ii-
free-running-vibrato-phase; the shipped values in brackets): `depth` 1.05
(.52), `travel` .93 (.62), `bend` .94 (.73), `tiefr` 89% (81%), `cents` 97%
(96%), `aud` .9468 (.9451); `vib` falls 1.00 -> 0.97. 412 of 602 vibrating
notes (216 of the 351 in the first 180 s) are in the original's phase; the rest
keep the per-call vibrato. The pass reads the classic update whose row clock is
two counted gates and whose swing waits for age 4: ACE_II and Saboteur_II
(Saboteur_II: `bend` .66 -> .81, `travel` .70 -> .78, nothing else beyond
+-0.001).
"""
from typing import Callable, Dict, List, Optional, Tuple

from . import unison_vibrato as _uv
from .detect import (Detection, VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     VIBRATO_SHIFT_MASK, _find_vibrato_site)
from .goatwriter import HEADER_LEN
from .goatwriter import arpeggio as _arp
from .goatwriter import tempo as _gw_tempo
from .goatwriter.constants import (CMD_SETWAVEPTR, CMD_TONEPORTA, CMD_VIBRATO,
                                   GT_FIRST_NOTE,
                                   GT_KEYOFF, GT_LAST_NOTE, GT_MAX_TABLELEN,
                                   GT_WAVE_FIRST_CMD, GT_WAVE_JUMP,
                                   GT_WAVE_LAST_DELAY, GT_WAVE_NO_NOTE,
                                   OUTER_GATE, SPEED_GATE, SPEED_NOTE_RELATIVE,
                                   VIBRATO_CMP_BIAS, WAVECMD_PORTADOWN,
                                   WAVECMD_PORTAUP)
from .instrument_drop import _RECORD_LEN, _layout
from .patterns import MAX_PATTERNS
from .sidfile import SidFile
from .vibrato_hold import (_NAME_AT, _PLAIN_WAVE_LAST, _STBL_AT, _VIBDELAY_AT,
                           _WAVE_AT, _WAVECMD_VIBRATO, _Unsupported,
                           _held_rows, _program, _read_tables,
                           _record_delay_frames, effective_gate_skip)

# The age at which the classic update starts to write the swing: `$E289
# LDA $E587,X / CMP #$04 / BCC` in ACE_II. The update runs from frame 1.
FIRST_ACTIVE = 4
CMD_PORTAUP, CMD_PORTADOWN = 1, 2           # gcommon.h
_AGE_GATE = bytes([0xC9, FIRST_ACTIVE, 0x90])     # CMP #4 / BCC
_MAX_RECORDS = 62                                  # GT_TEMPO_INSTRUMENT - 1
# Notes shorter than this (in frames, fetch to next fetch) show no swing the
# class could differ on: frame 4 is the first, frame 5 the first step.
MIN_LIFE = FIRST_ACTIVE + 2
# Which classes the wavetable's room goes to: a note's frames count in full
# while it plays in the first `WEIGHT_WINDOW` frames (180 s, the span every
# fidelity figure is taken over and the first minutes of a tune a listener
# hears) and at `LATE_WEIGHT` of that after it.
WEIGHT_WINDOW = 9000
LATE_WEIGHT = 0.25
# Zero-speed steps a base clone's own program carries before the second
# pattern row (the rest of a class's nulls run in its chain).
STEM_NULLS = 4
_PITCH_COMMANDS = (CMD_PORTAUP, CMD_PORTADOWN, CMD_TONEPORTA, CMD_VIBRATO)
# Symbolic rows (`phase_classic_vibrato`): a first byte no wavetable row has.
_SYM_NULL, _SYM_STEP, _SYM_UP, _SYM_DOWN = 0x1F4, 0x1F5, 0x1F1, 0x1F2


# --- the original's row clock ----------------------------------------------

def _clock_cells(sid: SidFile, subtune: int):
    """`(outer value, inner value, frames, skip)` at the first play call, or
    None. The two gates `DEC outer / BPL / LDA #skip / STA outer / JMP` and
    `DEC inner / BPL / LDA speed / STA inner`, the `LDA outer / BEQ` fetch
    guard and `LDA inner / CMP speed / BNE` behind them, and the cells' values
    after the init run (`_init_cells`)."""
    data = sid.data
    m = OUTER_GATE.search(data)
    if m is None or m.group(1) != m.group(3):
        return None
    g = SPEED_GATE.match(data, m.end())
    if g is None or g.group(1) != g.group(3):
        return None
    outer, inner, speed = m.group(1), g.group(1), g.group(2)
    target = sid.to_offset(m.group(4)[0] | m.group(4)[1] << 8)
    if target != g.end():
        return None
    guard = bytes([0xAD, outer[0], outer[1], 0xF0])
    at = data.find(guard, target, target + 16)
    if at < 0:
        return None
    fetch = bytes([0xAD, inner[0], inner[1], 0xCD, speed[0], speed[1], 0xD0])
    if data.find(fetch, at, at + 16) < 0:
        return None
    ran = _arp._init_cells(sid, subtune)
    if ran is None:
        return None
    _w, read = ran
    try:
        o0 = read(outer[0] | outer[1] << 8)
        i0 = read(inner[0] | inner[1] << 8)
        frames = read(speed[0] | speed[1] << 8) + 1
    except LookupError:
        return None
    return o0, i0, frames, m.group(2)[0]


def fetch_frames(cells, count: int, new_song_calls: int = 1) -> List[int]:
    """The call (= frame) of each of the first `count` row fetches. The first
    `new_song_calls` calls run none of the clock (ACE_II's `BIT $E574 / BVC`:
    the init leaves bit 6 set and the first call clears the voices)."""
    outer, inner, frames, skip = cells
    out: List[int] = []
    call = new_song_calls
    while len(out) < count:
        outer -= 1
        if outer < 0:
            outer = skip
        else:
            inner -= 1
            if inner < 0:
                inner = frames - 1
        if outer != 0 and inner == frames - 1:
            out.append(call)
        call += 1
    return out


def row_frames(cells, rows: int) -> List[int]:
    """`F[r]`: the frame row `r` starts on, for r in 0 .. rows (the last is
    the frame after the lap), a row being one fetch."""
    return fetch_frames(cells, rows + 1)


# --- the original's triangle, note by note ----------------------------------

def gt_directions(cmp_value: int, count: int) -> List[int]:
    """The sign of each `$F4` step from `vibtime` 0 (gplay.c:795-801):
    +1 adds, -1 subtracts."""
    vt, out = 0, []
    for _ in range(count):
        if vt < 0x80 and vt > cmp_value:
            vt ^= 0xFF
        vt = (vt + 2) & 0xFF
        out.append(-1 if vt & 1 else 1)
    return out


def rotation(bound: int, dirs: List[int]) -> Optional[int]:
    """The least `n` in 0 .. 2 * bound - 1 whose Goattracker direction
    sequence, from its `n`-th step, starts with `dirs`, or None."""
    g = gt_directions(bound - VIBRATO_CMP_BIAS, 4 * bound + len(dirs) + 2)
    for n in range(2 * bound):
        if g[n:n + len(dirs)] == dirs:
            return n
    return None


def _record_byte(sid: SidFile, det: Detection, rec: Optional[int]
                 ) -> Optional[int]:
    if rec is None:
        return None
    off = det.instr_start + rec * det.instr_stride + det.vibrato_offset
    return sid.data[off] if 0 <= off < len(sid.data) else None


def _age_gate(sid: SidFile, det: Detection) -> bool:
    """Whether the update's swing is written from age `FIRST_ACTIVE` on."""
    site = _find_vibrato_site(sid, det)
    if site is None:
        return False
    window = bytes(sid.data[site[1]:site[1] + 0x140])
    return window.find(_AGE_GATE) >= 3 and _age_load(window)


def _age_load(window: bytes) -> bool:
    at = window.find(_AGE_GATE)
    return at >= 3 and window[at - 3] == 0xBD      # LDA abs,X


def note_phases(blob: bytes, sid: SidFile, det: Detection) -> list:
    """Every vibrating note of the first lap, with the original's triangle:
    `{place, record, byte, bound, shift, life, frame, offsets}` where `place`
    is `(track, orderlist index, play, row)` and `offsets[j]` (j = 1 .. life
    - 1) the swing, in depths about the note, on frame `j` after the fetch.
    Empty where the clock, the counter or the age gate is not read."""
    cells_at = _uv.counter_cells(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    clock = _clock_cells(sid, 0)
    if (cells_at is None or speeds is None or clock is None
            or not _age_gate(sid, det) or blob[HEADER_LEN] != 1
            or speeds.frames_for(0) != clock[2]):
        return []
    try:
        instr_at, _tables_at, _patt_at, pats = _layout(blob)
    except ValueError:
        return []
    count = blob[instr_at]
    recs = instr_at + 1
    vbyte = {0: None}
    for k in range(1, count + 1):
        at = recs + (k - 1) * _RECORD_LEN
        vbyte[k] = _uv._vibrato_byte(bytes(blob[at + _NAME_AT:at + _RECORD_LEN]))
    d = sid.data
    try:
        start = [(d[sid.to_offset(cells_at[0] + v)],
                  d[sid.to_offset(cells_at[1] + v)]) for v in range(3)]
    except Exception:                       # noqa: BLE001 -- unreadable cells
        return []
    pos = HEADER_LEN + 1
    orders = []
    for _ in range(3):
        n = blob[pos]
        orders.append(bytes(blob[pos + 1:pos + n + 2]))
        pos += n + 2
    out: list = []
    for v in range(3):
        lane = []
        cur, cur_byte = 0, None
        first = (det.initial_instruments[v]
                 if v < len(det.initial_instruments) else det.init_instrument)
        cur_byte = _record_byte(sid, det, first)
        for i, p, repeat, _trans, rows in _uv._rows(orders[v], pats, blob):
            for play in range(repeat):
                for r, (n, k, c) in enumerate(rows):
                    if k:
                        cur, cur_byte = k, vbyte.get(k)
                    fetch = GT_FIRST_NOTE <= n <= GT_LAST_NOTE or n == GT_KEYOFF
                    lane.append((fetch, cur, cur_byte, c, (v, i, play, r), n))
        if not lane:
            continue
        frames = row_frames(clock, len(lane))
        state = start[v]
        after: Dict[int, tuple] = {}
        f_first = frames[0]
        for f in range(f_first):
            b = _record_byte(sid, det, first)
            if b:
                bound = (b & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
                state = _uv.step(state[0], state[1], bound)
        notes = []
        for idx, (fetch, cur_, byte, c, place, nbyte) in enumerate(lane):
            f0, f1 = frames[idx], frames[idx + 1]
            for f in range(f0, f1):
                if (fetch and f == f0) or not byte:
                    after[f] = state
                    continue
                bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
                state = _uv.step(state[0], state[1], bound)
                after[f] = state
            if (fetch and byte and c not in _PITCH_COMMANDS and cur_
                    and GT_FIRST_NOTE <= nbyte <= GT_LAST_NOTE):
                notes.append((idx, cur_, byte, place, f0))
        fetch_rows = [i for i, e in enumerate(lane) if e[0]]
        nxt = {a: b for a, b in zip(fetch_rows, fetch_rows[1:])}
        for idx, rec, byte, place, f0 in notes:
            end_row = nxt.get(idx)
            if end_row is None:
                continue
            life = frames[end_row] - f0
            if life < MIN_LIFE:
                continue
            bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
            offs = {j: after[f0 + j][0] - (bound >> 1) for j in range(1, life)}
            out.append(dict(place=place, record=rec, byte=byte, bound=bound,
                            shift=byte & VIBRATO_SHIFT_MASK, life=life,
                            frame=f0, offsets=offs))
    return out


def classify(note: dict) -> Optional[Tuple[int, int]]:
    """`(n, A)` for a note: the null count whose direction sequence matches
    the original's from frame 5 on, and the offset it is at on frame 4."""
    offs, bound, life = note["offsets"], note["bound"], note["life"]
    if FIRST_ACTIVE not in offs:
        return None
    dirs = [offs[j] - offs[j - 1] for j in range(FIRST_ACTIVE + 1, life)
            if j in offs and j - 1 in offs][:2 * bound]
    if any(x not in (-1, 1) for x in dirs):
        return None
    n = rotation(bound, dirs)
    return None if n is None else (n, offs[FIRST_ACTIVE])


# --- emitting a class ---------------------------------------------------------

def _wait(rows: List[tuple], wave: List[Optional[int]], gap: int) -> None:
    """`vibrato_hold._held_rows.wait`: `gap` calls of nothing, as delay rows
    (a delay row `d` holds `d + 1` calls), a one-call gap as the last waveform
    written again with no note."""
    while gap > 0:
        if gap == 1:
            if wave[0] is None:
                raise _Unsupported()
            rows.append((wave[0], GT_WAVE_NO_NOTE))
            return
        take = min(gap, GT_WAVE_LAST_DELAY + 1)
        if gap - take == 1:
            take -= 1
        rows.append((take - 1, GT_WAVE_NO_NOTE))
        gap -= take


def _lay_out(tl: Dict[int, tuple], start: int, end: int,
             wave0: Optional[int]) -> List[tuple]:
    """The rows that put the calls `tl` (call -> row) on the timeline from call
    `start`, delays between, to call `end`; `wave0` the waveform a one-call
    gap repeats."""
    rows: List[tuple] = []
    wave: List[Optional[int]] = [wave0]
    cur = start
    for t in sorted(tl):
        _wait(rows, wave, t - cur)
        row = tl[t]
        rows.append(row)
        if GT_WAVE_LAST_DELAY < row[0] <= _PLAIN_WAVE_LAST:
            wave[0] = row[0]
        cur = t + 1
    _wait(rows, wave, end - cur)
    return rows


def _last_wave(kept: Dict[int, tuple], before: int) -> Optional[int]:
    w = None
    for t in sorted(kept):
        if t < before and GT_WAVE_LAST_DELAY < kept[t][0] <= _PLAIN_WAVE_LAST:
            w = kept[t][0]
    return w


def free_calls(kept: Dict[int, tuple], lo: int, hi: int) -> List[int]:
    return [t for t in range(max(lo, 1), hi) if t not in kept]


def stem_rows(kept: Dict[int, tuple], nb: int, t_row: int,
              null_row: tuple) -> List[tuple]:
    """A base clone's own program up to the call the second pattern row
    reaches (`t_row`): the record's events before it and `nb` zero-speed steps
    on the latest free calls (`_Unsupported` where they do not fit)."""
    tl = {t: row for t, row in kept.items() if t < t_row}
    free = free_calls(tl, 1, t_row)
    if nb > len(free):
        raise _Unsupported()
    for t in (free[len(free) - nb:] if nb else []):
        tl[t] = null_row
    return _lay_out(tl, 0, t_row, None)


def chain_rows(kept: Dict[int, tuple], n: int, a_move: int, calls: int,
               t_row: int, null_row: tuple, move_rows: Dict[int, tuple]
               ) -> List[tuple]:
    """The rows `CMD_SETWAVEPTR` on the second pattern row starts, running
    from call `t_row` to the first call of the shared loop (`calls *
    (FIRST_ACTIVE + 1)`), WITHOUT the closing jump: the record's events in
    the span, `n` zero-speed steps on the latest free calls before frame 4,
    and on frame 4's first call the move of `a_move` depths. An event that
    falls on the move goes one call after it. `_Unsupported` where the span
    does not hold it."""
    t_a = FIRST_ACTIVE * calls
    t_l = t_a + calls
    tl = {t: row for t, row in kept.items() if t_row <= t < t_a}
    if a_move:
        tl[t_a] = move_rows[a_move]
    for t, row in sorted((t, r) for t, r in kept.items() if t_a <= t < t_l):
        u = t
        while u in tl:
            u += 1
        if u >= t_l:
            raise _Unsupported()
        tl[u] = row
    free = [t for t in range(t_row, t_a) if t not in tl]
    if n > len(free):
        raise _Unsupported()
    for t in (free[len(free) - n:] if n else []):
        tl[t] = null_row
    return _lay_out(tl, t_row, t_l, _last_wave(kept, t_row))


def simulate(rows: List[tuple], stbl: List[tuple], start: int, calls: int,
             shift: int, switch: Optional[Tuple[int, int]] = None
             ) -> List[int]:
    """The swing, in depths about the note, after each of `calls` play calls of
    the program at 1-based row `start` (a test's reading of what a class
    emits): gplay.c's wavetable loop -- a delay row `d` holds `d + 1` calls,
    `$FF` jumps for free -- and its `$F4` (`CMD_VIBRATO`, `vibtime` from 0) and
    `$F1`/`$F2` rows. A note-relative entry `(0x80 | cmp, r)` moves
    `1 << (shift - r)` depths, a plain `(cmp, 0)` entry none. `switch` is
    `(call, row)`: the pointer is set to `row` on that call before its row is
    read, as a `CMD_SETWAVEPTR` on a pattern row's tick 0 does."""
    ptr, wavetime, vt, pos, out = start, 0, 0, 0, []
    for call in range(calls):
        if switch is not None and call == switch[0]:
            ptr, wavetime = switch[1], 0       # `CMD_SETWAVEPTR`, tick 0
        left, right = rows[ptr - 1]
        if left <= GT_WAVE_LAST_DELAY:
            if left != wavetime:
                wavetime += 1
                out.append(pos)
                continue
        elif left >= GT_WAVE_FIRST_CMD and left != GT_WAVE_JUMP:
            cmd = left - GT_WAVE_FIRST_CMD
            lft, rgt = stbl[right - 1]
            move = (1 << max(0, shift - rgt)) if lft >= SPEED_NOTE_RELATIVE else 0
            if cmd == 4:
                cmp_value = lft & 0x7F
                if vt < 0x80 and vt > cmp_value:
                    vt ^= 0xFF
                vt = (vt + 2) & 0xFF
                pos += -move if vt & 1 else move
            elif cmd == 1:
                pos += move
            elif cmd == 2:
                pos -= move
        wavetime = 0
        ptr += 1
        if rows[ptr - 1][0] == GT_WAVE_JUMP:
            ptr = rows[ptr - 1][1]
        out.append(pos)
    return out


def _kept_events(events: Dict[int, tuple]) -> Dict[int, tuple]:
    """`vibrato_hold`'s reading of a program's own rows: a waveform row that
    is not the attack re-bases the pitch on no note."""
    kept: Dict[int, tuple] = {}
    gate = None
    for t in sorted(events):
        left, right = events[t]
        if GT_WAVE_LAST_DELAY < left <= _PLAIN_WAVE_LAST:
            rising = bool(left & 1) and gate is not True
            gate = bool(left & 1)
            if t > 0 and right == 0 and not rising:
                right = GT_WAVE_NO_NOTE
        kept[t] = (left, right)
    return kept


def respell(body: bytearray, nrows: int, mapping: Dict[int, tuple],
            name_first: Optional[int] = None
            ) -> Tuple[bytearray, Optional[int]]:
    """`(body, live)`: `body` with every NOTE row that follows a mapped row
    and names no instrument naming the base it played under -- and nothing
    else (the caller writes the mapped rows). `unison_vibrato._respell` also
    names the base on the first row after a clone, a rest, which is wrong
    here: the packed player re-reads the current instrument's vibrato
    parameter at the tick 0 of every row with no command (player.s
    `mt_tick0_0`), and with a vibrato delay of 0 runs it at once, so the base
    record's per-call vibrato would start on top of the clone's program. A
    clone therefore stays the current instrument across rests.

    `name_first` is the base instrument the pattern's first note plays under
    when the pattern before it left a clone live: the first note row that
    names nothing names it. `live` is the base a clone still in effect at the
    pattern's end wants restored on the next pattern's first note, or None."""
    out = bytearray(body)
    eff = name_first
    live = name_first is not None
    for r in range(nrows):
        n, k = out[r * 4], out[r * 4 + 1]
        if n == 0xFF:               # patterns.GT_END_PATTERN
            break
        if r in mapping:
            eff = mapping[r][0]
            live = True
            continue
        if k:
            eff, live = k, False
            continue
        if live and GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
            out[r * 4 + 1] = eff
            live = False
    return out, (eff if live else None)


def _entry(stbl: List[tuple], entry: tuple) -> int:
    """The 1-based speed-table row of `entry`, added where absent."""
    if entry not in stbl:
        stbl.append(entry)
    return stbl.index(entry) + 1


def phase_classic_vibrato(blob: bytes, sid: SidFile, det: Detection,
                          multiplier: int,
                          log: Optional[Callable[[str], None]] = None
                          ) -> bytes:
    """`blob` with each vibrating note of the first lap that the wavetable has
    room for started in the original's triangle phase (module docstring).
    Unchanged where the player's clock, counter or age gate is not read, a
    pattern commands a vibrato of its own, or nothing fits."""
    m = multiplier
    if (m < 2 or det.vibrato_offset is None or det.triangle_vibrato is not None
            or det.table_vibrato is not None or det.vibrato_dwell
            or det.vibrato_shift_extra or effective_gate_skip(sid)):
        return blob
    try:
        instr_at, tables_at, patt_at, pats = _layout(blob)
    except ValueError:
        return blob
    if bytes(blob[:4]) != b"GTS5":
        return blob
    notes = note_phases(blob, sid, det)
    if not notes:
        return blob
    wtbl, ptbl, ftbl, stbl = _read_tables(blob, tables_at, patt_at)
    count = blob[instr_at]
    recs_at = instr_at + 1
    recs = [bytearray(blob[recs_at + i * _RECORD_LEN:
                           recs_at + (i + 1) * _RECORD_LEN])
            for i in range(count)]
    pointed = set()
    for start, nrows in pats:
        for r in range(nrows):
            if blob[start + r * 4 + 2] == CMD_SETWAVEPTR:
                pointed.add(blob[start + r * 4 + 3])
            if (blob[start + r * 4 + 2] == CMD_VIBRATO
                    and blob[start + r * 4 + 3]):
                return blob
    t_a = FIRST_ACTIVE * m
    t_l = t_a + m

    # The records whose program a class can start from.
    taken: Dict[int, dict] = {}
    for k in {n["record"] for n in notes}:
        rec = recs[k - 1]
        wptr, vptr = rec[_WAVE_AT], rec[_STBL_AT]
        byte = _uv._vibrato_byte(bytes(rec[_NAME_AT:_RECORD_LEN]))
        if not wptr or not vptr or not byte or vptr > len(stbl):
            continue
        bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
        shift = byte & VIBRATO_SHIFT_MASK
        if bound < 2 or stbl[vptr - 1][0] < SPEED_NOTE_RELATIVE:
            continue
        prog = _program(wtbl, wptr)
        if prog is None:
            continue
        events, end_t, last_row = prog
        if any(WAVECMD_PORTAUP <= left <= _WAVECMD_VIBRATO
               for left, _right in events.values()):
            continue
        if any(wptr <= p <= last_row for p in pointed):
            continue
        if _record_delay_frames(sid, det, rec) is not None:
            continue
        taken[k] = dict(kept=_kept_events(events), end_t=end_t, bound=bound,
                        shift=shift, byte=byte, wptr=wptr)

    # Every class, its weight in frames and its notes.
    classes: Dict[tuple, dict] = {}
    for note in notes:
        k = note["record"]
        cls = classify(note) if k in taken else None
        if cls is None or note["byte"] != taken[k]["byte"]:
            continue
        key = (k, cls[0], cls[1])
        c = classes.setdefault(key, dict(weight=0, notes=[]))
        c["weight"] += (note["life"] if note["frame"] < WEIGHT_WINDOW
                        else note["life"] * LATE_WEIGHT)
        c["notes"].append(note["place"])

    # The second pattern row's first call: the program time `CMD_SETWAVEPTR`
    # on it takes effect at (`t_row`), the row clock in calls.
    speeds = _gw_tempo.find_song_speeds(sid, det)
    row_len = speeds.exact_row(0) if speeds is not None else None
    if row_len is None or (row_len * m).denominator != 1:
        return blob
    # The note's call 0 runs no wavetable row: program time is the call - 1.
    t_row = int(row_len * m) - 1
    if not 1 < t_row < t_a:
        return blob

    # Programs are built from symbolic rows (a first byte above $FF: the null
    # step, a move, the held step) so that two classes' rows can be compared
    # before any speed-table entry exists; `concrete` writes the entries.
    def split(key):
        """(nulls in the base clone, nulls in the chain) of a class: the base
        clone runs the record's events with `nb` nulls (0 or `STEM_NULLS`)
        and the chain the rest."""
        k, n, a = key
        info = taken[k]
        cap = len(free_calls(info["kept"], t_row, t_a))
        if n <= cap:
            return 0, n
        nb = min(STEM_NULLS, len(free_calls(
            {t: 0 for t in info["kept"] if t < t_row}, 1, t_row)))
        if nb and 0 <= n - nb <= cap:
            return nb, n - nb
        raise _Unsupported()

    def chain_spec(key):
        k, n, a = key
        info = taken[k]
        _nb, n2 = split(key)
        moves: Dict[int, tuple] = {}
        if a:
            if abs(a) > 2 or (abs(a) == 2 and info["shift"] < 1):
                raise _Unsupported()
            moves[a] = ((_SYM_UP if a > 0 else _SYM_DOWN), abs(a))
        return chain_rows(info["kept"], n2, a, m, t_row, (_SYM_NULL, 0), moves)

    def concrete(rows, info):
        out = []
        for left, right in rows:
            if left == _SYM_NULL:
                out.append((_WAVECMD_VIBRATO, _entry(
                    stbl, (info["bound"] - VIBRATO_CMP_BIAS, 0))))
            elif left == _SYM_STEP:
                out.append((_WAVECMD_VIBRATO, _entry(
                    stbl, (SPEED_NOTE_RELATIVE
                           | (info["bound"] - VIBRATO_CMP_BIAS),
                           info["shift"]))))
            elif left in (_SYM_UP, _SYM_DOWN):
                ent = _entry(stbl, (SPEED_NOTE_RELATIVE,
                                    info["shift"] - (right - 1)))
                out.append(((WAVECMD_PORTAUP if left == _SYM_UP
                             else WAVECMD_PORTADOWN), ent))
            else:
                out.append((left, right))
        return out

    def loop_key(info):
        tail = tuple(sorted((t - t_l, row) for t, row in info["kept"].items()
                            if t >= t_l))
        return (tail, max(0, info["end_t"] - t_l), info["bound"], info["shift"])

    def loop_rows_for(lkey, first_row):
        tail, end, _b, _s = lkey
        return _held_rows(dict(tail), end, (_SYM_STEP, 0), 0, m, first_row)

    def calls_of(row):
        return row[0] + 1 if row[0] <= GT_WAVE_LAST_DELAY else 1

    def share(rows, lkey):
        """`rows` (symbolic, closing in the jump to the loop) with its longest
        suffix that an allocated chain of the same loop runs from the same
        call replaced by a jump into it."""
        best = rows
        for prog in programs.get(lkey, ()):
            prows = prog["rows"]
            for i in range(1, len(rows) - 1):
                t_x = sum(calls_of(r) for r in rows[:i])
                for j in range(len(prows) - 1):
                    if prows[j:] == rows[i:] and (
                            sum(calls_of(r) for r in prows[:j]) == t_x):
                        cand = rows[:i] + [(GT_WAVE_JUMP,
                                            ("A", prog["at"] + j))]
                        if len(cand) < len(best):
                            best = cand
                        break
        return best

    pending: Dict[tuple, List[tuple]] = {}
    for key in classes:
        try:
            split(key)
            pending[key] = chain_spec(key) + [(GT_WAVE_JUMP, ("L", None))]
        except _Unsupported:
            continue
    loops: Dict[tuple, int] = {}
    programs: Dict[tuple, List[dict]] = {}
    bases: Dict[tuple, int] = {}                # (record, nulls) -> stem row
    stems: Dict[tuple, int] = {}                # stem rows -> first row
    made: Dict[tuple, int] = {}                 # class -> chain's 1-based row
    new_records: List[tuple] = []               # ((record, nulls), bytearray)
    while pending and count + len(bases) < _MAX_RECORDS:
        best = None
        for key, rows in pending.items():
            info = taken[key[0]]
            nb, _n2 = split(key)
            lkey = loop_key(info)
            shared = share(rows[:-1] + [(GT_WAVE_JUMP, ("L", lkey))], lkey)
            extra = 0
            if lkey not in loops:
                try:
                    extra = len(loop_rows_for(lkey, 1))
                except _Unsupported:
                    continue
            if (key[0], nb) not in bases:
                try:
                    stem = stem_rows(info["kept"], nb, t_row, (_SYM_NULL, 0))
                except _Unsupported:
                    continue
                if (tuple(stem), info["bound"] if nb else None) not in stems:
                    extra += len(stem) + 1
            cost = len(shared) + extra
            if len(wtbl) + cost > GT_MAX_TABLELEN:
                continue
            score = (classes[key]["weight"] / cost, -cost, key)
            if best is None or score > best[0]:
                best = (score, key, shared, lkey, nb)
        if best is None:
            break
        _score, key, shared, lkey, nb = best
        info = taken[key[0]]
        del pending[key]
        if lkey not in loops:
            loops[lkey] = len(wtbl) + 1
            wtbl.extend(concrete(loop_rows_for(lkey, len(wtbl) + 1), info))
        if (key[0], nb) not in bases:
            stem = stem_rows(info["kept"], nb, t_row, (_SYM_NULL, 0))
            skey = (tuple(stem), info["bound"] if nb else None)
            if skey not in stems:
                # The jump closing a stem is never reached (the second row's
                # `CMD_SETWAVEPTR` takes the pointer first), so any loop will
                # do and two records with the same events share the rows.
                stems[skey] = len(wtbl) + 1
                wtbl.extend(concrete(stem, info))
                wtbl.append((GT_WAVE_JUMP, min(loops.values())))
            bases[(key[0], nb)] = stems[skey]
            rec = bytearray(recs[key[0] - 1])
            rec[_WAVE_AT] = bases[(key[0], nb)]
            rec[_STBL_AT] = 0
            rec[_VIBDELAY_AT] = 0
            new_records.append(((key[0], nb), rec))
        at = len(wtbl) + 1
        rows_c = []
        for left, right in shared:
            if left == GT_WAVE_JUMP and isinstance(right, tuple):
                right = loops[lkey] if right[0] == "L" else right[1]
            rows_c.append((left, right))
        wtbl.extend(concrete(rows_c, info))
        programs.setdefault(lkey, []).append(dict(rows=shared, at=at))
        made[key] = at
    if not made:
        return blob

    # Which row of which orderlist position names which base clone, and
    # which chain the row after it starts. A note whose next row is missing,
    # is a fetch or carries a command is left as it was.
    want: Dict[Tuple[int, int, int], Dict[int, tuple]] = {}
    for key in made:
        nb, _n2 = split(key)
        for (ti, i, play, r) in classes[key]["notes"]:
            want.setdefault((ti, i, play), {})[r] = (key[0], nb, made[key])
    subtunes = blob[HEADER_LEN]
    pos = HEADER_LEN + 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        tracks.append((pos + 1, bytes(blob[pos + 1:pos + n + 2])))
        pos += n + 2
    first_named: Dict[int, bool] = {}
    for p, (start, nrows) in enumerate(pats):
        first_named[p] = False
        for r in range(nrows):
            n = blob[start + r * 4]
            if n == 0xFF:
                break
            if GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
                first_named[p] = bool(blob[start + r * 4 + 1])
                break
    plans = []
    forced: Dict[Tuple[int, int], int] = {}
    lost = {"repeat": 0, "next row": 0, "live at the end": 0}
    for ti, (off, order) in enumerate(tracks):
        entries = _uv._rows(order, pats, blob)
        for e, (i, p, repeat, _trans, rows) in enumerate(entries):
            maps = [want.get((ti, i, play)) for play in range(repeat)]
            if maps[0] and any(mp != maps[0] for mp in maps):
                lost["repeat"] += len(maps[0])
                maps = [None] * repeat
            if not maps[0] and (ti, e) not in forced:
                continue
            mapping = {}
            for r, val in (maps[0] or {}).items():
                nxt = rows[r + 1] if r + 1 < len(rows) else None
                if (nxt is not None and nxt[2] == 0
                        and not GT_FIRST_NOTE <= nxt[0] <= GT_LAST_NOTE):
                    mapping[r] = val
                else:
                    lost["next row"] += 1
            if not mapping and (ti, e) not in forced:
                continue
            start, nrows = pats[p]
            body, live = respell(bytearray(blob[start:start + nrows * 4]),
                                 nrows, mapping, forced.get((ti, e)))
            if live is not None:
                # A clone is still the current instrument at the pattern's
                # end: safe where the next entry's first note names its own,
                # else that note is named after it, in a copy of its pattern.
                nxt_e = e + 1
                if (repeat > 1 or nxt_e >= len(entries)):
                    lost["live at the end"] += len(mapping)
                    continue
                if not first_named.get(entries[nxt_e][1], False):
                    forced[(ti, nxt_e)] = live
            plans.append((off + i, p, mapping, body, nrows, (ti, i, repeat)))
    if not plans:
        return blob
    keys = sorted({(k, nb) for _o, _p, mp, _b, _n, _t in plans
                   for (k, nb, _a) in mp.values()})
    clone_of = {key: count + 1 + j for j, key in enumerate(keys)}
    rec_of = dict(new_records)
    bodies: Dict[bytes, int] = {}
    new_patterns: List[bytes] = []
    repoint: Dict[int, int] = {}
    for at, _p, mapping, body, nrows, _t in plans:
        for r, (k, nb, chain) in mapping.items():
            body[r * 4 + 1] = clone_of[(k, nb)]
            body[(r + 1) * 4 + 2] = CMD_SETWAVEPTR
            body[(r + 1) * 4 + 3] = chain
        raw = bytes([nrows]) + bytes(body)
        if raw not in bodies:
            bodies[raw] = len(pats) + len(new_patterns)
            new_patterns.append(raw)
        repoint[at] = bodies[raw]
    if (count + len(keys) > _MAX_RECORDS
            or len(pats) + len(new_patterns) > MAX_PATTERNS):
        if log:
            log(f"Phased vibrato..........: declined, {len(keys)} clone(s) and "
                f"{len(new_patterns)} pattern copies would need "
                f"{count + len(keys)} instruments and "
                f"{len(pats) + len(new_patterns)} patterns")
        return blob
    out = bytearray(blob)
    for at, p in repoint.items():
        out[at] = p
    res = bytearray(out[:instr_at])
    res.append(count + len(keys))
    res += out[recs_at:recs_at + count * _RECORD_LEN]
    for key in keys:
        res += rec_of[key]
    for table in (wtbl, ptbl, ftbl, stbl):
        res += bytes([len(table)])
        res += bytes(left for left, _right in table)
        res += bytes(right for _left, right in table)
    res.append(len(pats) + len(new_patterns))
    res += out[patt_at + 1:]
    for raw in new_patterns:
        res += raw
    if log:
        frame_of = {n["place"]: n["frame"] for n in notes}
        covered = [(ti, i, play, r) for _o, _p, mp, _b, _n, (ti, i, rep)
                   in plans for r in mp for play in range(rep)]
        early = sum(1 for pl in covered if frame_of.get(pl, 1 << 30)
                    < WEIGHT_WINDOW)
        total = sum(1 for n in notes if n["frame"] < WEIGHT_WINDOW)
        named = sum(len(classes[k]["notes"]) for k in made)
        log(f"Phased vibrato..........: {len(covered)} of {len(notes)} "
            f"vibrating note(s) ({early} of {total} in the first "
            f"{WEIGHT_WINDOW} frames) started in the original's phase by "
            f"{len(keys)} clone(s) and {len(made)} wavetable chain(s) "
            f"({named} notes in their classes, lost to "
            + ", ".join(f"{k} {v}" for k, v in lost.items()) + "), "
            f"{len(new_patterns)} pattern(s) copied, wavetable "
            f"{len(wtbl)}/{GT_MAX_TABLELEN} rows")
    return bytes(res)
