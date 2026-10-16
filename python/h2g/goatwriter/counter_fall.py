"""Bit $02's counter-started fall (detect._find_counter_fall) as per-row programs.

Mega_Apocalypse `$4DBF` is the skydive's falling high byte (`skydive.py`) with
a different gate. Where Hunter_Patrol starts it in the last ticks of a long
note and stops it at zero, this block

* starts it from a FRAME COUNT: the voice's counter (`$BC,X`, zeroed by the
  instrument start of every note whose byte does not carry bit 7, INC'd every
  frame, a BYTE) must be at or above the record's own threshold
  (`$54A7,Y`), and odd -- so the stores are on frames 1, 3, 5 ... of the
  note, whatever the global clock says;
* has no `BEQ` on savehi, so the byte runs through zero and on to `$FF`,
  `$FE` ... (measured down to `$DE` on record 9);
* does not stop with the note: the counter keeps counting through the rests
  that follow it, and it WRAPS at 256 -- the stores stop until it is back at
  the threshold (record 16: 114..255, 370..511, 626..767 of a note and the
  rests after it), savehi going on from where it was.

So a store's value is the note's own high byte minus the number of stores the
note has had, and in Goattracker terms store `n` is the note's frequency
`$100 * n` lower. A frame with no store keeps the pitch (where the record has
no vibrato) or is back on the vibrato (where it has).

**What this emits, and what it does not.**

*A record with no vibrato byte* (record 16, `$0CFC`, notes of 384 and 768
frames) is emitted: each row that holds a store gets a `CMD_SETWAVEPTR` to a
program of its own three frames -- a delay to the store's tick, an `F2` (or
`F1`, for a step of 128 high-byte units or more, the same modulo $10000) of
`$100 * size` on it, a stop -- and programs are shared by the shape of the
row, so the whole fall costs a handful of wavetable steps
(`counter_fall_entries`). `size` is how many stores the row's frame is ahead
of what the voice has been given so far, so a store the plan could not place
(a row whose command column is taken) is made up on the next one, and a
legato note, which puts the voice back on its note, starts the count over.
The rows are mostly in the rest pattern every voice shares, so the walk is
per ORDERLIST POSITION (`rest_reseed`'s): a position's rows are written only
where every visit of it agrees, and a pattern its positions want written
differently is cloned, one copy per distinct set, the positions repointed.

*A record with a vibrato byte* (record 9, `$09F9`, GT 10, the 288-frame note
whose 227 reversals open this file; record 12, GT 13) alternates the fall with
the vibrato: on every odd frame from the threshold the voice is `n * $100`
below its note, and on the even frames the vibrato block puts it back. Each
store has to be undone on the frame after it, and the size of a store is its
own count, so the exact schedule is two wavetable steps a store -- 228 for
that one note, against the 8 steps Mega_Apocalypse's wavetable had free. What
is emitted instead is the schedule at a handful of SIZES (`ALTERNATION_LEVELS`):

* a size is a three-row wavetable loop, `F2 size` (the dip), `F3 00` (the
  step back, a tie to the note: anything the swell's `4xy` left on the voice
  is dropped with it, where an `F1` would keep it forever) and a jump to the
  first; a row that opens on a dip points at the first row, a row that opens
  on the step back at the second, and the entry (the row the first dip is
  inside) at a delay and a jump;
* a wavetable command skips the pattern's continuous effect on its tick
  (gplay.c:714-715 goes to PULSEEXEC), so the loop replaces the swell's
  vibrato from the first dip on. The original keeps the vibrato on the even
  frames; the dips are the larger part of the swing from the second or third
  store on;
* every row from the entry on whose command column holds the swell's `4xy`
  (or is empty) is pointed, even where the size does not change: the swell's
  own loops pass converts every `4xy` row of a hold and would otherwise
  replace the loop. The size changes only on a row after one that ended on
  the step back (a size changed under a dip would step back by another
  amount than it fell);
* the counter's laps past the first are `counter_fall_laps`': the original
  HOLDS the lap's last dip until the vibrato gate and then stores again from
  the threshold, its count going on. A lap end with a hold program (there is
  room for two) points its rows at a short `[tie] F2 n / jump` into a still
  loop and ties back at the gate; the others keep the loop going at its last
  size, through the gap, into the next lap's dips (sizes `n` modulo 256
  folded to 1..127, the direction not kept).

Sizes are the optimal clustering in log space of the dip counts the rows are
at (`quantize_levels`), as many as the wavetable leaves the swell's loops.

**Where a store falls.** Original frame `j` of a note (its fetch frame is 0
and runs no effects) is our call `j + lag` of the note's row (`lag` is
`skydive_plan`'s: our attack is the first AUDIBLE call), so its row is
`(j + lag) // frames` and its tick the remainder. A fetch frame -- the first
frame of any event row, a rest's included -- runs no effects either, so a
store that would land on one is not made and the count does not advance
(`fall_stores`). Only -S1 is emitted: this player is not a multispeed one,
and the one file with the block packs at -S1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, CMD_VIBRATO, FORMAT_GTS5,
                        GT_FIRST_NOTE, GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST,
                        GT_WAVE_JUMP, GT_WAVE_NO_NOTE, PACKED_PATTERN_LIMIT,
                        WAVECMD_PORTADOWN, WAVECMD_PORTAUP,
                        MAX_TRACK_LEN, _SONG_MAX_PATTERNS)
from . import pulse as _gw_pulse
from . import skydive as _gw_skydive
from . import tempo as _gw_tempo

# Effect-byte bits that rewrite the frequency after the block, or skip it:
# $01 the byte-code wave program (its paths leave through `$4E63`), $10 the
# pitch sequence and $40 the fixed pitch (both rewrite $C0/$C3 from the note
# table), $80 the voice-3 drum.
COUNTER_FALL_EXCLUDED = 0x01 | 0x10 | 0x40 | 0x80
# The counter is a byte: stores need `counter & $FF >= threshold`.
COUNTER_FALL_WRAP = 0x100
# A speed row is a 16-bit step below $8000 (gplay.c:543-551), so a step of
# `$100 * size` needs size <= $7F; 128 high-byte units is $8000 either way.
COUNTER_FALL_MAX_SIZE = 0x7F
COUNTER_FALL_HALF = 0x80
# `F3 00`: tone portamento at speed 0 is a tie to the channel's note
# (gplay.c:574-583, player.s `mt_effect_3`).
WAVECMD_TIE = 0xF3


@dataclass(frozen=True)
class CounterFallPlan:
    """The finished patterns and orderlists, and the programs to append to
    the wavetable."""
    patterns: List[List[int]]
    tracks: List[List[int]]
    entries: List[Tuple[int, int]]


def counter_fall_records(sid: SidFile, det: Detection,
                         records: int) -> Dict[int, bool]:
    """{record index: whether its fall alternates with the vibrato}.

    A record sets bit $02 and none of COUNTER_FALL_EXCLUDED. It alternates
    where its vibrato byte is nonzero -- the block that rewrites the whole
    frequency on the frames between the stores.
    """
    vib = (det.triangle_vibrato if det.triangle_vibrato is not None
           else det.vibrato_offset)
    out: Dict[int, bool] = {}
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(sid.data):
            break
        fx = sid.data[base + 7]
        if not fx & 0x02 or fx & COUNTER_FALL_EXCLUDED:
            continue
        out[i] = bool(vib is not None and sid.data[base + vib])
    return out


def record_threshold(sid: SidFile, det: Detection, i: int) -> Optional[int]:
    """The frame count record `i`'s stores start from, or None off the file."""
    cf = det.counter_fall
    if cf is None:
        return None
    at = sid.to_offset(cf.threshold + i * det.instr_stride)
    return sid.data[at] if 0 <= at < len(sid.data) else None


def fall_stores(length: int, threshold: int,
                fetches: Set[int] = frozenset()) -> List[int]:
    """The frames of a note of `length` frames on which the block stores.

    Frame 0 is the fetch and runs no effect. The counter on frame `j` is `j`
    taken as a byte; the block needs it at or above `threshold` and odd. A
    frame that fetches the next EVENT of the voice (`fetches`, frames from
    the note's own) runs no effect either, so it stores nothing.
    """
    return [j for j in range(1, length)
            if j & 1 and (j % COUNTER_FALL_WRAP) >= threshold
            and j not in fetches]


def step_command(size: int) -> Optional[Tuple[int, int]]:
    """(wavetable command, speed-table high byte) for a fall of `size`
    high-byte units, or None where it is nothing or unrepresentable.

    The frequency is 16 bits, so `size` is taken modulo 256: a step of 128 or
    more high-byte units down is the same as one of 256 - size up, and 128
    itself is $8000, which a speed row reads as a note-relative one.
    """
    s = size % COUNTER_FALL_WRAP
    if s == 0 or s == COUNTER_FALL_HALF:
        return None
    if s <= COUNTER_FALL_MAX_SIZE:
        return WAVECMD_PORTADOWN, s
    return WAVECMD_PORTAUP, COUNTER_FALL_WRAP - s


def counter_fall_entries(key: Tuple[Optional[int], ...],
                         speed_index) -> List[Tuple[int, int]]:
    """The wavetable steps of one row's program: `key` is the row's calls,
    each None (nothing) or the size of the fall made on it.

    A run of calls with nothing on them is a delay (`value + 1` calls,
    gplay.c:697-704), the steps are the command entries, and the program
    stops after the last of them (`$FF 00` takes no call of its own); the
    calls after it are the row's own effects.
    """
    calls: List[Optional[Tuple[int, int]]] = []
    for size in key:
        cmd = None if size is None else step_command(size)
        calls.append(None if cmd is None else (cmd[0], speed_index(cmd[1])))
    while calls and calls[-1] is None:
        calls.pop()
    return _gw_skydive._compress(calls)


def row_falls(events, frames: int, usable) -> Dict[int, Dict[int, int]]:
    """{row offset: {tick: size}}: the fall to make on each tick, given a
    note's `events` -- (call, kind, n) sorted, kind 0 the store `n` (0-based)
    and kind -1 a legato note that puts the voice back on its own pitch --
    and `usable(row offset)`, whether that row can take a program.

    `size` is how many stores the voice is behind when the store comes: a
    store on a row that cannot take it is made up by the next that can, and
    a legato note starts the count over. Store 0 writes the note's own byte
    and moves nothing.
    """
    applied = 0
    per_row: Dict[int, Dict[int, int]] = {}
    for call, kind, n in events:
        if kind < 0:
            applied = 0
            continue
        e, tick = divmod(call, frames)
        if not usable(e):
            continue
        size = n - applied
        if size % COUNTER_FALL_WRAP == COUNTER_FALL_HALF:
            continue                 # $8000: no speed row says it
        if size % COUNTER_FALL_WRAP:
            per_row.setdefault(e, {})[tick] = size
        applied = n
    return per_row


def _visits(track: List[int], patterns: List[List[int]]):
    """(position, pattern, repeat index, transpose) for every visit of one
    lap of an orderlist, in play order (`skydive._lap_rows`' walk, with the
    orderlist position kept)."""
    transpose, repeat, operand = 0, 1, False
    for pos, b in enumerate(track):
        if operand:
            break                    # the restart's operand: the lap is over
        if b == 0xFF:
            operand = True
            continue
        if 0xE0 <= b < 0xFF:
            transpose = b - 0xF0
            continue
        if 0xD0 <= b < 0xE0:
            repeat = b - 0xD0 + 1
            continue
        if b >= len(patterns):
            continue
        for k in range(repeat):
            yield pos, b, k, transpose
        repeat = 1


def _pattern_positions(track: List[int], patterns: int):
    """(position, pattern) for every position of an orderlist that names a
    pattern -- visited or not, since a position's pattern is shared by all."""
    for pos, b in enumerate(track):
        if b == 0xFF:
            break
        if b < patterns and b < 0xD0:
            yield pos, b


@dataclass
class _Segment:
    """One note's frame counter: from a non-legato note to the next."""
    track: int
    start: int                  # lap row of the note
    end: int                    # lap row of the next non-legato note
    number: int                 # GT instrument number
    frames: int
    lag: int
    fetches: Set[int]           # frames of the segment's own event starts
    resets: List[int]           # row offsets of legato notes (back on the note)
    ok: str = ""                # why it is declined, "" when it is not


def _walk(tracks, patterns, bit7, by_number, speeds, no_test_restart,
          real_firstwave):
    """(rows, segments, visits, free, declined) for one lap of every
    orderlist.

    `rows[ti]` is the lap's rows, (pattern, row, transpose, position,
    repeat index); `segments` every note of a fall record from its fetch to
    the next non-legato note -- the span of one frame counter; `visits[(ti,
    position)]` how many times the position is played; `free[(ti, position,
    row)]` whether a pointer may replace that row's command on EVERY visit
    (the row is a bare rest and its command persists the row before's, so
    nothing but the pointer changes).
    """
    declined: Dict[str, int] = {}
    rows: Dict[int, List[tuple]] = {}
    out: List[_Segment] = []
    visits: Dict[tuple, int] = {}
    free: Dict[tuple, bool] = {}
    for ti, track in enumerate(tracks):
        lap: List[tuple] = []
        for pos, p, k, t in _visits(track, patterns):
            visits[(ti, pos)] = visits.get((ti, pos), 0) + 1
            pat = patterns[p]
            for r in range(len(pat) // 4):
                if pat[4 * r] == 0xFF:
                    break
                lap.append((p, r, t, pos, k))
        rows[ti] = lap
        for a, (p, r, _t, pos, _k) in enumerate(lap):
            cell = tuple(patterns[p][4 * r:4 * r + 4])
            prev = (tuple(patterns[lap[a - 1][0]][4 * lap[a - 1][1] + 2:
                                                  4 * lap[a - 1][1] + 4])
                    if a else None)
            ok = (cell[0] == GT_REST and cell[1] == 0 and prev is not None
                  and cell[2:] == prev
                  and cell[2] in _gw_skydive.SKYDIVE_PERSISTENT_COMMANDS)
            key = (ti, pos, r)
            free[key] = free.get(key, True) and ok
        frames = speeds.frames_for(ti // 3)
        if frames is None:
            continue
        current = 0
        seg: Optional[_Segment] = None
        first = None
        for a, (p, r, t, _pos, _k) in enumerate(lap):
            note, instr = patterns[p][4 * r], patterns[p][4 * r + 1]
            is_note = GT_FIRST_NOTE <= note <= GT_LAST_NOTE
            flags = bit7.get(p) if is_note else frozenset()
            legato = is_note and flags is not None and r in flags
            if is_note and not legato:
                if seg is not None:
                    seg.end = a
                    out.append(seg)
                    seg = None
                current = instr or current
                if flags is None:
                    declined["bit 7 of a note unknown"] = \
                        declined.get("bit 7 of a note unknown", 0) + 1
                    continue
                if current in by_number:
                    lag = 0 if no_test_restart or current in real_firstwave \
                        else 1
                    seg = _Segment(ti, a, len(lap), current, frames, lag,
                                   set(), [])
                    first = (note, t)
                continue
            if seg is None:
                if instr:
                    current = instr
                continue
            if instr and instr != seg.number:
                seg.ok = "instrument changes"
            if is_note:
                if (note, t) != first:
                    seg.ok = "legato note changes pitch"
                seg.resets.append(a - seg.start)
            if note != GT_REST:
                seg.fetches.add((a - seg.start) * frames)
        if seg is not None:
            out.append(seg)
    return rows, out, visits, free, declined


def _setup(sid: SidFile, det: Detection, tracks: List[List[int]], lead: int,
           instr_used: int, fmt: str, multiplier: int,
           gate_skip: Optional[int], bit7: Optional[dict], log):
    """(say, {GT instrument: alternates}, {GT instrument: threshold}, the
    row clock) where the fall can be read, else None -- logged once."""
    if det.counter_fall is None:
        return None

    def say(msg: str) -> None:
        if log:
            log(f"Counter fall (bit $02)..: {msg}")

    records = counter_fall_records(sid, det, max(instr_used - lead, 0))
    if not records:
        return None
    if fmt != FORMAT_GTS5 or multiplier != 1 or gate_skip:
        say(f"{len(records)} record(s), not emitted ("
            + ("GTS2 stores no speed table" if fmt != FORMAT_GTS5 else
               f"only -S1 is read, this is -S{multiplier}" if multiplier != 1
               else "outer gate") + ")")
        return None
    if bit7 is None:
        say(f"{len(records)} record(s), not emitted (bit 7 of the notes not "
            "read: it needs --tie)")
        return None
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        say("row clock not read, not emitted")
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None                      # a split subtune shifted the numbering
    by_number = {i + lead + 1: alt for i, alt in records.items()}
    thresholds = {i + lead + 1: record_threshold(sid, det, i)
                  for i in records}
    return say, by_number, thresholds, speeds


def unroll_repeats(track: List[int], positions: Set[int],
                   patterns: int) -> List[int]:
    """`track` with the `$Dx` repeat before each pattern at one of
    `positions` replaced by that many entries of the pattern, and the
    restart position moved to where it was.

    A repeat plays the same orderlist position again, so every visit of it
    gets the same rows; a fall's rows differ from one visit to the next (the
    counter has moved on), and an unrolled position is one per visit. The
    list grows by `count - 2` bytes a repeat; the caller checks the limit.
    """
    end = track.index(0xFF) if 0xFF in track else len(track)
    tokens: List[list] = []            # [old position, byte]
    pending: Optional[tuple] = None     # (token index of the $Dx, count)
    for pos in range(end):
        b = track[pos]
        tokens.append([pos, b])
        if 0xD0 <= b < 0xE0:
            pending = (len(tokens) - 1, b - 0xD0 + 1)
            continue
        if b >= 0xD0 or b >= patterns:
            continue
        if pending is not None and pos in positions and pending[1] > 1:
            tokens[pending[0]][1] = None
            tokens += [[None, b] for _ in range(pending[1] - 1)]
        pending = None
    kept = [t for t in tokens if t[1] is not None]
    restart = track[end + 1] if end + 1 < len(track) else None
    new_restart = None
    if restart is not None:
        new_restart = next((i for i, t in enumerate(kept)
                            if t[0] is not None and t[0] >= restart),
                           len(kept))
    out = [t[1] for t in kept]
    if end < len(track):
        out.append(track[end])
        if new_restart is not None:
            out.append(new_restart)
        out += track[end + 2:]
    return out


def unroll_fall_repeats(sid: SidFile, det: Detection,
                        tracks: List[List[int]], patterns: List[List[int]],
                        lead: int, instr_used: int, fmt: str,
                        multiplier: int, gate_skip: Optional[int],
                        bit7: Optional[dict], no_test_restart: bool = False,
                        real_firstwave: tuple = (), log=None
                        ) -> List[List[int]]:
    """`tracks` with every repeated position a no-vibrato fall's note runs
    over unrolled, so its visits can be written differently
    (`counter_fall_plan`). Before the orderlists are written: it changes
    their lengths. The tracks come back unchanged where there is nothing to
    unroll or the orderlist would pass `MAX_TRACK_LEN`."""
    ctx = _setup(sid, det, tracks, lead, instr_used, fmt, multiplier,
                 gate_skip, bit7, None)
    if ctx is None:
        return tracks
    _say, by_number, _thr, speeds = ctx
    rows, segs, visits, _free, _declined = _walk(
        tracks, patterns, bit7, by_number, speeds, no_test_restart,
        real_firstwave)
    want: Dict[int, Set[int]] = {}
    for s in segs:
        # A no-vibrato fall's rows differ from visit to visit; so do an
        # alternating note's PAST ITS FIRST LAP (`counter_fall_laps`: the
        # hold and the dips of lap 2 and on), which the shorter ones never
        # reach.
        if s.ok:
            continue
        if by_number[s.number]:
            length = (s.end - s.start) * s.frames
            dips = (alternation_dips(length, _thr[s.number], s.fetches)
                    if length > COUNTER_FALL_WRAP and ALTERNATION_UNROLL
                    else None)
            if dips is None or len(dips) < ALTERNATION_MIN_DIPS:
                continue
        for p, r, _t, pos, _k in rows[s.track][s.start:s.end]:
            if visits.get((s.track, pos), 1) > 1:
                want.setdefault(s.track, set()).add(pos)
    out = [list(t) for t in tracks]
    changed = refused = 0
    for ti, positions in sorted(want.items()):
        grown = unroll_repeats(tracks[ti], positions, len(patterns))
        if len(grown) >= MAX_TRACK_LEN:
            refused += 1
            continue
        out[ti] = grown
        changed += 1
    if log and (changed or refused):
        log(f"Counter fall (bit $02)..: {changed} orderlist(s) unrolled over "
            f"{sum(len(want[t]) for t in want)} repeated position(s)"
            + (f", {refused} left alone at {MAX_TRACK_LEN} bytes"
               if refused else ""))
    return out if changed else tracks


# --- The alternating record (a vibrato byte): the fall ON the vibrato -------

# A note with fewer dips (stores past the first, which moves nothing) than
# this is left to the swell. 1 takes every note with a dip: Mega_Apocalypse
# at -t 180 with presets, `aud` 0.8838 -> 0.8843 with the 4 notes of 32 dips
# or more only, 0.8825 at 6, 0.8853 at 1 (the other 50 notes are record 12's).
ALTERNATION_MIN_DIPS = 1
# How many dip sizes the alternation's loops take at most. Each is a
# three-row loop (`F2 size / F3 00 / FF`), so the wavetable pays three a
# size, and what the swell's own loops (`_expanding_vibrato_loops`, which
# run after) cannot then fit stay `4xy` rows: 10 sizes fill Mega_Apocalypse's
# table to 254 of 255 with every swell loop in, 12 lose 105 swell rows.
ALTERNATION_LEVELS = 8
# The rows the alternation may take in all (dip loops, entries, lap-end holds
# with their still loop). The swell's loops (`_expanding_vibrato_loops`, which
# fill what is left) merge onto fewer loops as the table gets short, and four
# pins hold the two ends: `test_tie_restart_mega.py` wants 42 loops or more,
# `test_counter_fall_alternation.py` wants the 7 dip sizes the first lap's
# phase needs (95 of the original's 103 lows; 6 sizes give 80). Mega_Apocalypse
# at 1172704 (historical): 29 rows with the one shared hold = 7 sizes, one
# entry, 43 loops with 18 swings merged (43 and 13 before the holds, which took
# 23 rows); a second hold (4 more rows) leaves 5-6 sizes and 42-44 loops.
ALTERNATION_ROWS = 29
# Whether a note that outlasts the counter's first lap gets the repeats it
# runs over unrolled (`unroll_fall_repeats`), so that its later laps' rows can
# differ from visit to visit.
ALTERNATION_UNROLL = True


@dataclass(frozen=True)
class AltRow:
    """One row of an alternating note's run of dips."""
    e: int              # row offset from the note's own row
    kind: str           # 'D' the row opens on a dip, 'S' on a step back,
    #                     'E' the first dip is `delay` ticks into the row
    delay: int
    n: int              # the dip size the row is at (mean of its dips)
    after_balanced: bool  # the row before ended on a step back
    fresh: bool = False  # the first row of a run after a hold (no entry)
    tied: bool = False   # an 'X' row whose program ties to the note first
    # Kinds 'X' (the row holds the lap's last dip: `n` its count, `delay` the
    # tick it is on), 'H' (a row held) and 'Q' (the row the vibrato gate
    # falls in) are `counter_fall_laps`'.


def alternation_dips(length: int, threshold: int,
                     fetches: Set[int]) -> Optional[List[int]]:
    """The frames of a note's dips -- every store of the counter's first lap
    after the first, which writes the note's own byte and moves nothing --
    or None where a fetch frame takes one (the schedule then is not the
    odd frames, and a program cannot skip one)."""
    plain = [j for j in fall_stores(length, threshold)
             if j < COUNTER_FALL_WRAP]
    real = [j for j in fall_stores(length, threshold, fetches)
            if j < COUNTER_FALL_WRAP]
    if plain != real:
        return None
    return real[1:]


def alternation_rows(dips: List[int], lag: int, frames: int,
                     mags: Optional[List[int]] = None) -> List[AltRow]:
    """The rows a note's dips and steps back fall on.

    A dip is at call `j + lag` and its step back on the next call, so from
    the first dip every call is one or the other, alternately. With an odd
    `frames` the rows alternate between opening on a dip and on a step
    back; a row that ends on a dip leaves the voice down, and the next must
    start with the step back of the SAME size (`after_balanced`).
    """
    c0 = dips[0] + lag
    last = dips[-1] + lag + 1
    out: List[AltRow] = []
    balanced = True
    for e in range(c0 // frames, last // frames + 1):
        first = e * frames
        ds = [(c - c0) // 2 + 1 if mags is None else mags[(c - c0) // 2]
              for c in range(max(first, c0), min(first + frames, last))
              if (c - c0) % 2 == 0]
        ds = [d for d in ds if d]
        if first < c0:
            kind, delay = 'E', c0 - first
        else:
            kind, delay = ('S' if (first - c0) % 2 else 'D'), 0
        n = round(sum(ds) / len(ds)) if ds else (out[-1].n if out else 1)
        out.append(AltRow(e, kind, delay, n, balanced))
        end = min(first + frames - 1, last)
        balanced = (end - c0) % 2 == 1
    return out


def quantize_levels(values: List[int], k: int) -> List[int]:
    """`k` dip sizes standing for `values`: the optimal 1-D clustering in log
    space (dynamic programming over the distinct values), each cluster
    represented by its mean, rounded."""
    import math
    counts: Dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    xs = sorted(counts)
    if len(xs) <= k:
        return xs
    logs = [math.log(x) for x in xs]
    ws = [counts[x] for x in xs]
    m = len(xs)

    def cost(i: int, j: int) -> float:
        w = sum(ws[i:j + 1])
        mean = sum(ws[t] * logs[t] for t in range(i, j + 1)) / w
        return sum(ws[t] * (logs[t] - mean) ** 2 for t in range(i, j + 1))

    best = [[float('inf')] * (k + 1) for _ in range(m + 1)]
    cut = [[0] * (k + 1) for _ in range(m + 1)]
    best[0][0] = 0.0
    for c in range(1, k + 1):
        for j in range(1, m + 1):
            for i in range(c - 1, j):
                v = best[i][c - 1] + cost(i, j - 1)
                if v < best[j][c]:
                    best[j][c], cut[j][c] = v, i
    out: List[int] = []
    j = m
    for c in range(k, 0, -1):
        i = cut[j][c]
        w = sum(ws[i:j])
        out.append(max(1, min(COUNTER_FALL_MAX_SIZE,
                              round(sum(ws[t] * xs[t] for t in range(i, j))
                                    / w))))
        j = i
    return sorted(set(out))


def nearest_level(levels: List[int], n: int) -> int:
    """Index of the level closest to `n` in log space."""
    import math
    return min(range(len(levels)),
               key=lambda i: abs(math.log(levels[i]) - math.log(max(n, 1))))


def alternation_loop(level: int, speed_index, base: int
                     ) -> List[Tuple[int, int]]:
    """One level's loop: the dip (`F2 size`), the step back (`F3 00`, a tie
    to the note: the vibrato a row's `4xy` left on the voice would otherwise
    stay in the result of every `F1`), and a jump to the first row. `base`
    is the 1-based wavetable index of its first row."""
    cmd, s = step_command(level)
    return [(cmd, speed_index(s)), (WAVECMD_TIE, 0), (GT_WAVE_JUMP, base)]


def alternation_asks(segs, rows, patterns, thresholds, own, room,
                     gates=None):
    """({(track, position): {repeat index: {row: key}}}, levels, declined,
    notes) for the alternating notes `segs`.

    A key is `('alt', 'D' | 'S', size)` -- a pointer into the size's loop at
    its dip or its step back -- or `('alt', 'E', size, delay)`, the entry: a
    delay of `delay` ticks and then the loop. Only the first row is an
    entry; the loop runs on by itself, so a row it cannot take (its command
    column is used) costs nothing. A row is pointed (`SETWAVEPTR` takes a
    swell's `4xy` or an empty column) so that the swell's own pass, which
    converts every `4xy` row of a hold, leaves the loop alone, and so that
    the size can follow the note's own dip count -- but only on a row after
    one that ended on a step back: a size changed under a dip would step
    back by another amount than it fell.

    With `gates` ({GT instrument: the vibrato gate}) a note that outlasts
    the counter's first lap gets the rest of its laps (`counter_fall_laps`):
    `('alt', 'X', count, tick, tied)` the program that dips to the lap's
    last count and holds, `('alt', 'H')` a row held and `('alt', 'Q')` the row
    the vibrato gate falls in -- as many programs as `ALTERNATION_HOLD_ROWS`
    pays for, the most used first, the rest of the lap ends left to the loop.
    """
    from . import counter_fall_laps as _laps
    declined: Dict[str, int] = {}
    live = []
    for s in segs:
        dips = alternation_dips((s.end - s.start) * s.frames,
                                thresholds[s.number], s.fetches)
        if dips is None:
            declined["a fetch frame on a store"] =                 declined.get("a fetch frame on a store", 0) + 1
            continue
        if len(dips) < ALTERNATION_MIN_DIPS:
            declined["too few dips"] = declined.get("too few dips", 0) + 1
            continue
        live.append(s)
    if not live:
        return {}, [], declined, 0

    def usable_for(s):
        lap = rows[s.track]

        def usable(e: int) -> bool:
            if s.start + e >= s.end:
                return False
            p, r, _t, _pos, _rep = lap[s.start + e]
            cmd = (patterns[p][4 * r + 2], patterns[p][4 * r + 3])
            return ((cmd[0] == CMD_VIBRATO or cmd == (0, 0))
                    and e * s.frames >= own[s.number])
        return usable

    def plan(holds):
        out = []
        for s in live:
            ars = _laps.alternation_note_rows(
                (s.end - s.start) * s.frames, thresholds[s.number],
                None if gates is None else gates.get(s.number), s.fetches,
                s.lag, s.frames, usable_for(s), s.end - s.start, holds)
            out.append((s, ars))
        return out

    # The holds: every one that could be made, the most used first, as far
    # as the rows they may take go.
    funded: Set[tuple] = set()
    if gates:
        uses: Dict[tuple, int] = {}
        for _s, ars in plan(None):
            for ar in ars:
                if ar.kind == 'X':
                    k = (ar.n, ar.delay, ar.tied)
                    uses[k] = uses.get(k, 0) + 1
        spent = _laps.STILL_ROWS
        for key in sorted(uses, key=lambda k: (-uses[k],
                                               _laps.hold_rows(*k), k)):
            cost = _laps.hold_rows(*key)
            if spent + cost <= _laps.ALTERNATION_HOLD_ROWS:
                spent += cost
                funded.add(key)
    plans = plan(funded)

    def build(k: int):
        levels = quantize_levels([ar.n for _s, ars in plans for ar in ars
                                  if ar.kind in ('E', 'D', 'S')], k)
        asks: Dict[tuple, Dict[int, Dict[int, tuple]]] = {}
        used: Set[int] = set()
        entries: Set[tuple] = set()
        holds_used: Set[tuple] = set()
        for s, ars in plans:
            lap = rows[s.track]
            usable = usable_for(s)
            cur: Optional[int] = None
            for ar in ars:
                if s.start + ar.e >= s.end:
                    break
                p, r, _t, pos, rep = lap[s.start + ar.e]
                if not usable(ar.e):
                    continue
                if ar.kind in ('X', 'H', 'Q'):
                    cur = None
                    key = (('alt', 'X', ar.n, ar.delay, ar.tied)
                           if ar.kind == 'X' else ('alt', ar.kind))
                    if ar.kind == 'X':
                        holds_used.add((ar.n, ar.delay, ar.tied))
                    asks.setdefault((s.track, pos), {}).setdefault(
                        rep, {})[r] = key
                    continue
                want = levels[nearest_level(levels, ar.n)]
                if ar.fresh and cur is None:
                    cur = want
                    key = ('alt', ar.kind, cur)
                elif cur is None:
                    delay = (ar.delay if ar.kind == 'E'
                             else 0 if ar.kind == 'D' else 1)
                    if delay >= s.frames:
                        continue
                    cur = want
                    key = (('alt', 'D', cur) if not delay
                           else ('alt', 'E', cur, delay))
                else:
                    if ar.after_balanced:
                        cur = want
                    key = ('alt', ar.kind, cur)
                used.add(cur)
                if key[1] == 'E':
                    entries.add(key)
                asks.setdefault((s.track, pos), {}).setdefault(
                    rep, {})[r] = key
        cost = (3 * len(used) + 2 * len(entries)
                + (_laps.STILL_ROWS + sum(_laps.hold_rows(*h)
                                          for h in holds_used)
                   if holds_used else 0))
        return asks, sorted(used), cost

    cap = min(room, ALTERNATION_ROWS)
    k = ALTERNATION_LEVELS
    while True:
        asks, used, cost = build(k)
        if cost <= cap or k <= 1:
            break
        k -= 1
    if cost > cap and funded:
        # The holds do not fit with even one size: the loops alone.
        funded = set()
        plans = plan(funded)
        k = ALTERNATION_LEVELS
        while True:
            asks, used, cost = build(k)
            if cost <= cap or k <= 1:
                break
            k -= 1
    if cost > room:
        declined["wavetable full"] = len(live)
        return {}, [], declined, 0
    return asks, used, declined, len(live)


def counter_fall_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                      patterns: List[List[int]], lead: int, instr_used: int,
                      fmt: str, multiplier: int, gate_skip: Optional[int],
                      speed_table: List[tuple], wave_used: int,
                      bit7: Optional[dict] = None,
                      no_test_restart: bool = False,
                      real_firstwave: tuple = (),
                      log=None, wave_entries: Optional[List[tuple]] = None,
                      wave_starts: Optional[List[int]] = None
                      ) -> Optional[CounterFallPlan]:
    """The rows that hold a store of a fall, pointed at their programs, or
    None where nothing is taken.

    Walks one lap of every orderlist in play order. A row of an orderlist
    POSITION is taken only where every visit of the position asks for the
    same program and its command column persists the row before's; a row
    that is not taken leaves its store to the next one that is (`size`
    counts from what the voice has been given). Everything declined is
    counted in the log line.
    """
    ctx = _setup(sid, det, tracks, lead, instr_used, fmt, multiplier,
                 gate_skip, bit7, log)
    if ctx is None:
        return None
    say, by_number, thresholds, speeds = ctx
    if wave_entries is None or wave_starts is None:
        say("wavetable not given, not emitted")
        return None
    rows, segs, visits, free, declined = _walk(
        tracks, patterns, bit7, by_number, speeds, no_test_restart,
        real_firstwave)
    hold = [s for s in segs if not by_number[s.number]]
    alternating = [s for s in segs if by_number[s.number]]
    stores_alt = sum(len(fall_stores((s.end - s.start) * s.frames,
                                     thresholds[s.number], s.fetches))
                     for s in alternating)
    for s in hold:
        if s.ok:
            declined[s.ok] = declined.get(s.ok, 0) + 1
    hold = [s for s in hold if not s.ok]
    # The instrument's own program must be over before a row points away
    # from it.
    own: Dict[int, Optional[int]] = {}
    for s in hold + [a for a in alternating if not a.ok]:
        if s.number not in own:
            start = (wave_starts[s.number - 1]
                     if s.number - 1 < len(wave_starts) else 0)
            calls = (_gw_skydive.instrument_calls(wave_entries, start)
                     if start else [])
            own[s.number] = None if calls is None else len(calls)
    kept = []
    for s in hold:
        if own[s.number] is None:
            declined["instrument program loops"] = \
                declined.get("instrument program loops", 0) + 1
        else:
            kept.append(s)
    hold = kept

    # Per segment: the stores as (call, n), the legato resets as calls.
    instances = []
    for s in hold:
        length = (s.end - s.start) * s.frames
        js = fall_stores(length, thresholds[s.number], s.fetches)
        events = [(j + s.lag, 0, n) for n, j in enumerate(js)]
        events += [(off * s.frames, -1, 0) for off in s.resets]
        instances.append((s, sorted(events)))

    def asks_for(avail: Set[tuple]) -> Dict[tuple, Dict[int, Dict[int, tuple]]]:
        """{(track, position): {repeat index: {row: key}}} -- what each
        visit of a position wants written, given the rows still free."""
        asks: Dict[tuple, Dict[int, Dict[int, tuple]]] = {}
        for s, events in instances:
            lap = rows[s.track]

            def usable(e: int, s=s, lap=lap) -> bool:
                if e >= s.end - s.start or e * s.frames < own[s.number]:
                    return False
                _p, r, _t, pos, _k = lap[s.start + e]
                return (s.track, pos, r) in avail
            for e, ticks in row_falls(events, s.frames, usable).items():
                p, r, _t, pos, k = lap[s.start + e]
                asks.setdefault((s.track, pos), {}).setdefault(k, {})[r] = \
                    tuple(ticks.get(t) for t in range(s.frames))
        return asks

    def solve(eligible: Set[tuple]):
        """({(track, position, row): key}, rows mixed) at the fixpoint: a
        row that is dropped leaves its store to the next, which changes
        that one's size."""
        avail = set(eligible)
        taken: Dict[tuple, tuple] = {}
        mixed = 0
        for _ in range(len(eligible) + 1):
            asks = asks_for(avail)
            taken, wanted = {}, 0
            for (ti, pos), by_visit in asks.items():
                every = {r for rr in by_visit.values() for r in rr}
                for r in every:
                    wanted += 1
                    got = [by_visit.get(k, {}).get(r)
                           for k in range(visits[(ti, pos)])]
                    if None not in got and len(set(got)) == 1:
                        taken[(ti, pos, r)] = got[0]
            mixed = wanted - len(taken)
            if set(taken) == avail or not asks:
                break
            avail = set(taken)
        return taken, mixed

    def fit(taken: Dict[tuple, tuple]):
        """(program keys that fit, those that do not): the wavetable's room,
        the commonest shapes first, and the speed table's."""
        uses: Dict[tuple, int] = {}
        for key in taken.values():
            uses[key] = uses.get(key, 0) + 1
        room = GT_MAX_TABLELEN - wave_used
        speed_room = GT_MAX_TABLELEN - len(speed_table)
        have = {h for h, _lo in speed_table}
        new_speeds: Set[int] = set()
        good, bad = [], []
        for key in sorted(uses, key=lambda k: (-uses[k], k)):
            sizes = {step_command(v)[1] for v in key
                     if v is not None and step_command(v) is not None}
            cost = len(counter_fall_entries(key, lambda h: 1))
            extra = sizes - have - new_speeds
            if cost > room or len(new_speeds) + len(extra) > speed_room:
                bad.append(key)
                continue
            room -= cost
            new_speeds |= extra
            good.append(key)
        return good, bad

    eligible = {key for key, ok in free.items() if ok}
    mixed = 0
    good: List[tuple] = []
    keys_taken: Dict[tuple, tuple] = {}
    while True:
        keys_taken, mixed = solve(eligible)
        if not keys_taken:
            break
        good, bad = fit(keys_taken)
        if not bad:
            break
        # A shape that does not fit leaves its rows out, and the stores
        # after them are sized without it: solve again without those rows.
        eligible -= {k for k, v in keys_taken.items() if v in bad}
    # The alternating notes: what the hold programs leave of the table.
    alt_ready = []
    alt_taken: Dict[tuple, tuple] = {}
    alt_levels: List[int] = []
    alt_declined: Dict[str, int] = {}
    alt_notes = 0
    for a in alternating:
        why = a.ok or ("instrument program loops"
                       if own.get(a.number) is None else "")
        if why:
            alt_declined[why] = alt_declined.get(why, 0) + 1
        else:
            alt_ready.append(a)
    if alt_ready:
        room = (GT_MAX_TABLELEN - wave_used
                - sum(len(counter_fall_entries(k, lambda h: 1))
                      for k in good))
        vg = det.vibrato_gate
        gates = ({n: vg.gate_for(n - lead - 1) for n in by_number}
                 if vg is not None and vg.form == "counter" else None)
        asks, alt_levels, more, alt_notes = alternation_asks(
            alt_ready, rows, patterns, thresholds, own, room, gates)
        for why, n in more.items():
            alt_declined[why] = alt_declined.get(why, 0) + n
        disagree = 0
        for (ti, pos), by_visit in asks.items():
            every = {r for rr in by_visit.values() for r in rr}
            for r in every:
                got = [by_visit.get(k, {}).get(r)
                       for k in range(visits[(ti, pos)])]
                if None not in got and len(set(got)) == 1:
                    alt_taken[(ti, pos, r)] = got[0]
                else:
                    disagree += 1
        if disagree:
            alt_declined["rows the visits disagree on"] = disagree
    if not keys_taken and not alt_taken:
        say(f"{len(hold)} note(s) on {len(set(s.number for s in hold))} "
            f"record(s), no row taken ({mixed} mixed or occupied)"
            + (f"; {len(alternating)} alternating note(s), {stores_alt} "
               f"store(s), not emitted" if alternating else ""))
        return None

    table = speed_table
    snapshot = list(table)

    def speed_index(high: int) -> int:
        entry = (high, 0x00)
        if entry not in table:
            table.append(entry)
        return table.index(entry) + 1

    programs: Dict[tuple, int] = {}
    entries: List[Tuple[int, int]] = []
    holds_made = sorted({k for k in alt_taken.values() if k[1] == 'X'})
    blocks = [(key, counter_fall_entries(key, speed_index)) for key in good]
    if holds_made:
        # The lap-end holds' rows are paid for here: longest first, a program
        # ends in a stop, so one that is the TAIL of a program already laid
        # (`[wait][F2][stop]` inside `[F2][wait][F2][stop]`) is that tail,
        # with no rows of its own. Only this plan's own rows are looked in:
        # the table's others may be dropped after. Without a hold the
        # programs are laid in order, one each, as they always were.
        blocks.sort(key=lambda kb: -len(kb[1]))
    for key, block in blocks:
        at = (next((i for i in range(len(entries) - len(block) + 1)
                    if entries[i:i + len(block)] == block), None)
              if holds_made else None)
        if at is None:
            programs[key] = wave_used + len(entries) + 1
            entries += block
        else:
            programs[key] = wave_used + at + 1
    # One three-row loop a dip size; a dip row points at its first row, a
    # step-back row at its second, and the entry is a delay and a jump.
    loop_at: Dict[int, int] = {}
    for q in alt_levels:
        loop_at[q] = wave_used + len(entries) + 1
        entries += alternation_loop(q, speed_index, loop_at[q])
        programs[('alt', 'D', q)] = loop_at[q]
        programs[('alt', 'S', q)] = loop_at[q] + 1
    for key in sorted({k for k in alt_taken.values() if k[1] == 'E'}):
        programs[key] = wave_used + len(entries) + 1
        entries += [(_gw_skydive.SKYDIVE_NOOP + key[3] - 1, GT_WAVE_NO_NOTE),
                    (GT_WAVE_JUMP, loop_at[key[2]])]
    # The holds (`counter_fall_laps`): the still loop every held row points
    # into, and a program a lap end.
    if holds_made:
        from . import counter_fall_laps as _laps
        base = wave_used + len(entries) + 1
        entries += _laps.still_loop(speed_index, base)
        programs[('alt', 'Q')], programs[('alt', 'H')] = base, base + 1
        for key in holds_made:
            programs[key] = wave_used + len(entries) + 1
            entries += _laps.hold_program(key[2], key[3], speed_index,
                                          base + 1, key[4])
    keys_taken = {**keys_taken, **alt_taken}

    # pattern -> {writes: [(track, position), ...]}, then one copy per
    # distinct set (`rest_reseed`): the pattern keeps the largest group.
    wants: Dict[tuple, Dict[int, tuple]] = {}
    for (ti, pos, r), key in keys_taken.items():
        wants.setdefault((ti, pos), {})[r] = key
    groups: Dict[int, Dict[frozenset, list]] = {}
    for ti, track in enumerate(tracks):
        for pos, b in _pattern_positions(track, len(patterns)):
            groups.setdefault(b, {}).setdefault(
                frozenset(wants.get((ti, pos), {}).items()), []).append(
                    (ti, pos))
    groups = {b: g for b, g in groups.items() if any(g)}
    out = [list(pat) for pat in patterns]
    new_tracks = [list(t) for t in tracks]
    written = clones = full = skipped = alt_written = 0

    def patched(b: int, want: frozenset) -> Optional[List[int]]:
        trial = list(patterns[b])
        for r, key in want:
            trial[4 * r + 2], trial[4 * r + 3] = CMD_SETWAVEPTR, programs[key]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            return None
        return trial

    for b in sorted(groups):
        by_want = groups[b]
        # The pattern keeps the positions that want nothing, or else the
        # largest group; every other group gets a copy of its own.
        stays = (frozenset() if frozenset() in by_want else
                 max(by_want, key=lambda w: (len(by_want[w]), repr(sorted(w)))))
        for want in sorted((w for w in by_want if w),
                           key=lambda w: (w != stays, repr(sorted(w)))):
            trial = patched(b, want)
            if trial is None:
                skipped += len(want) * len(by_want[want])
                continue
            if want == stays:
                out[b] = trial
            else:
                if len(out) >= _SONG_MAX_PATTERNS:
                    full += len(want) * len(by_want[want])
                    continue
                out.append(trial)
                clones += 1
                for ti, pos in by_want[want]:
                    new_tracks[ti][pos] = len(out) - 1
            written += len(want) * len(by_want[want])
            alt_written += (sum(1 for _r, k in want if k[0] == 'alt')
                            * len(by_want[want]))
    if not written:
        table[:] = snapshot
        return None
    numbers = sorted({s.number for s in hold})
    notes = ", ".join(f"{n} {why}" for why, n in declined.items() if n)
    say(f"{written - alt_written} row(s) over the orderlists on "
        f"instrument(s) {numbers}, "
        f"{len(programs)} program(s), {len(entries)} wavetable step(s) at "
        f"{wave_used + 1}, {clones} pattern copy(ies) ({len(hold)} note(s))"
        + (f"; {mixed} row(s) mixed or occupied" if mixed else "")
        + (f"; {skipped} row(s) past the packed pattern limit"
           if skipped else "")
        + (f"; {full} row(s) left alone: pattern table full" if full else "")
        + (f"; declined: {notes}" if notes else "")
        + (f"; {len(alternating)} alternating note(s) on instrument(s) "
           f"{sorted({a.number for a in alternating})}, {stores_alt} "
           f"store(s)" if alternating else "")
        + ((f", {alt_notes} emitted on {len(alt_levels)} dip size(s) "
            f"{alt_levels}, {alt_written} row(s)") if alt_written
           else (", not emitted" if alternating else ""))
        + (f", {len(holds_made)} lap-end hold program(s) "
           f"{[(k[2], k[3], k[4]) for k in holds_made]}"
           if holds_made else "")
        + (f" ({', '.join(f'{n} {why}' for why, n in alt_declined.items() if n)})"
           if any(alt_declined.values()) else ""))
    return CounterFallPlan(patterns=out, tracks=new_tracks, entries=entries)
