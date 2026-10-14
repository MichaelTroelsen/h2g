"""Bit $02's window-less skydive (detect._find_note_rise) as per-row programs.

Game_Killer $0B33 is Hunter_Patrol's skydive block (`skydive.py`) without the
ticks-left window, and with `INC` where Hunter_Patrol has `DEC`: on every
tick whose play-entry counter is odd it stores `savehi` into $D401 and steps
it, from the note's first effect tick to its last, for every note at least
`min_length` long. The fetch sets `savehi` to the note's own high byte
($0918), so each note's run starts over -- a tie landing included, since the
classic fetch writes it for every note it reads.

Where the record's vibrato rewrites the whole frequency every tick, the
ticks between are back on it and the voice ALTERNATES between the two.
siddump of Game_Killer, voice 0 from its attack at frame 641 (the record's
vibrato is 3426/34ED/35B4/367B, steps of $C7 on the global counter's
triangle):

    3426 35B4 347B 347B 367B 35B4 34ED 3626 3426 37ED 35B4 387B 367B 367B
    39B4 34ED 3A26 3426 3BED 35B4 3C7B 367B 3DB4 3DB4 34ED 3E26 ...

-- the vibrato on one tick, `$34`, `$35`, `$36` ... over its low byte on the
next, `$44` by the note's end; the doubled frames are the outer gate's skip.
Battle_of_Britain $82CC is the same block with `DEC` (`9C40 9E8E 9C40 9C40
9B8E A0DC 9A2A A32A 99DC ...` from frame 960).

**Where it goes.** A row of two ticks holds exactly one store: store k is on
the original's tick `phase + 2k` from the fetch (`phase` from the counter
value the player's fetch tick reads, `frame_counter_base` and
`fixed_arp_first_fetch`), and on ours `store_lag` ticks later. So each
store's row takes a `CMD_SETWAVEPTR` to a short program, by the half of the
row the store falls in:

* first tick: `F1`/`F2` by `$100 * k` on the row's first call, then a jump
  into a shared tail that puts the voice back on its note (a delay whose last
  call is relative note 0, gplay.c:719-725) on the second tick's first call
  and again on the row's last call, so the next row's store is measured from
  the note;
* second tick: the note on the first tick's last call, the step on the
  second tick's first call, and a shared tail putting it back on the row's
  last call.

**Rows of three ticks** (Crazy_Comets $5509, Chimera $C661, both at -S1:
siddump of Crazy_Comets voice 0 from its attack at frame 481 reads `5C 5F 5C
61 5B 5E 5A 5C 59 5F 58 ...`, the stores `5C 5B 5A 59 ...` on every second
frame and the vibrato between) walk across the row, because a store is every
second tick and a row is three: a row holds one store on tick 0, 1 or 2, or
two on ticks 0 and 2, and the rows alternate one and two (the store ticks are
the counter's odd values, so which rows hold two follows the parity of the
row's index in the lap -- `a * frames` in the plan). Each row's program is
keyed on the ticks it stores on: the same steps, a note before each and on
the call after it, and for two stores both in one program (`row_calls_of`).
A row of three has a gap of `2 * tick_calls - 2` calls to its last call, so
it is placed only to 8 calls a tick (`delays_fit`).

The step is a jump -- one call, not a rate -- so it is not divided by the
multiplier. The row's vibrato command persists across a pointer row (gplay.c
tick 0 leaves `command` alone for $8; player.s `mt_tick0_8`), and the delays
and the calls after each program's stop run it.

A per-instrument program cannot hold it: every call of a 360-call note is a
step or part of a delay of at most 16, and Game_Killer's wavetable has 23
entries left. Two or three entries a store value fit where five hundred do
not; where even that does not fit, fewer values are spread over the range and
each store takes the nearest. Where there is more than one kind of row (three
ticks to a row have four) a spread value repeats in every kind, so the lowest
values are kept exact instead and the stores above them are left to the
vibrato. `reserve` entries are held back from either for the past-table
split, which runs later on the finished song (`convert._assemble` builds
again with what it came up short).

**What this approximates.** The original stores the note's high byte plus k
over the vibrato's LOW byte, so its low byte wanders by up to the vibrato's
depth where ours is the note's; and between stores the vibrato restarts from
the note on every row, where the original's runs on its global triangle.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..detect import Detection, note_rise_rest_carries_on
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, CMD_TONEPORTA, FORMAT_GTS5,
                        GT_FIRST_NOTE, GT_KEYOFF, GT_LAST_NOTE,
                        GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        PACKED_PATTERN_LIMIT, WAVE_MAX_DELAY,
                        WAVECMD_BASE, WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from .primitives import _gate_calls
from . import arpeggio as _gw_arpeggio
from . import pulse as _gw_pulse
from . import skydive as _gw_skydive
from . import tempo as _gw_tempo

# A Hubbard note's duration is the low five bits of its note byte.
NOTE_RISE_MAX_DURATION = 0x1F
# Ticks per row this emitter places. A store is every second tick, so a row
# of two holds exactly one; a row of three alternates one store (on any of its
# three ticks) with two (its first and its last), by the parity of the row.
NOTE_RISE_ROW_TICKS = (2, 3)
# A speed row is a 16-bit step below $8000 (gplay.c:543-551 reads one at or
# above it as note-relative), so a jump of `$100 * k` needs k <= $7F.
NOTE_RISE_MAX_STEP = 0x7F
# Right side $00 on a delay's last call: relative note 0, the voice on its
# note (gplay.c:719-725, player.s `mt_wavefreq`).
NOTE_RISE_NOTE_BASE = 0x00


def store_lag(multiplier: int, tick_calls: int, test_lead: bool) -> int:
    """How many of our ticks a store lands after the original's, 0 or 1.

    The harness lines our attack frame up with the original's fetch frame,
    and our attack frame is the first frame holding the note's first audible
    call: call 1 where the record opens on the test-bit lead (call 0, the
    note init, writes the test bit), call 0 where the instrument writes its
    real waveform. A row's tick 0 is call `1 % multiplier` of its frame
    (`skydive.skydive_row_offset`), so frames end on the calls congruent to
    `multiplier - 1 - that` and our attack frame ends on the first such call
    at or after the audible one; the original's tick n is then our call
    `end + n * multiplier`, in our tick `(end + n * multiplier) //
    tick_calls`. Measured on the packed files traced per call: Battle_of_
    Britain (-S2, lead) ends its attack frame on call 2, one tick late --
    `skydive_plan`'s `lag` at -S1, one frame -- and Game_Killer (-S9, ticks of
    10 calls) on call 3, none.
    """
    m = max(1, multiplier)
    end_mod = (m - 1 - _gw_skydive.skydive_row_offset(m)) % m
    audible = 1 if test_lead else 0
    end = audible + (end_mod - audible) % m
    return end // max(1, tick_calls)


def store_phase(base: int, first: int, row: int, frames: int) -> int:
    """The original's tick, from a note's fetch tick, of its first store: 1
    or 2.

    The counter reads `base + first + row * frames` on the fetch tick of lap
    row `row` and steps once a passing call; the fetch tick runs no effect
    (Game_Killer $097B JMP $0B89), so store 0 is the first odd value after it.
    A row of two ticks leaves the parity alone; a row of three flips it with
    the row's own, which is what makes the rows alternate one store and two.
    """
    return 1 if (base + first + row * frames + 1) & 1 else 2


def store_rows(phase: int, lag: int, frames: int, length: int,
               kcap: int, skips=()) -> Dict[int, List[Tuple[int, int]]]:
    """{row of the note: [(store k, its tick in the row)]} for store k = 1 ..
    `kcap - 1`, store k being on the original's tick `phase + 2k` and ours
    `lag` ticks later, up to the note's last tick (`length` rows of `frames`
    ticks). Store 0 is the note's own byte and is not emitted.

    `skips` are ticks that run no effect (the fetch tick of an event that
    continues the note, `continuation`): a store due on one is not executed,
    the byte is not stepped, and the next store is the one that would have
    been, so every k after it is one store later."""
    stores: Dict[int, List[Tuple[int, int]]] = {}
    k = -1
    tick = phase - 2
    while True:
        tick += 2
        if tick >= length * frames:
            break                        # past the note's last tick
        if tick in skips:
            continue
        k += 1
        if k < 1:
            continue
        if k >= kcap:
            break
        j, half = divmod(tick + lag, frames)
        if j >= length:
            break
        stores.setdefault(j, []).append((k, half))
    return stores


def continuation(rows: List[tuple], patterns: List[List[int]], a: int,
                 length: int, min_length: int) -> List[Tuple[int, int]]:
    """[(row of the note where an event starts, its rows)] for the events
    after a note of `length` rows at lap row `a` that the rise runs through.

    The rise tests the current event's duration, not the note's, and a
    status byte with bit 6 (no operand, no note) leaves the voice, its
    instrument and the byte being stepped alone: Chimera $C2FF `DEC $C640`
    for the gate mask, then the instrument's record rewritten with the gate
    off, and $C656 -- the stepped byte -- untouched. So the rise carries on
    through the release for as long as each such event is `min_length` rows
    or more (Chimera's notes of 22 rows rise on for another 21, to $40; the
    third event, 3 rows, ends it). Our spelling of that event is a KEYOFF
    with no instrument, whose rows run to the next row with a note or an
    instrument.
    """
    out: List[Tuple[int, int]] = []
    end = a + length
    while end < len(rows):
        p, r, _t = rows[end]
        if (patterns[p][4 * r] != GT_KEYOFF or patterns[p][4 * r + 1]):
            break
        nxt = next((e for e in range(end + 1, len(rows))
                    if patterns[rows[e][0]][4 * rows[e][1]] != GT_REST
                    or patterns[rows[e][0]][4 * rows[e][1] + 1]), None)
        if nxt is None:
            break
        dur = nxt - end - 1
        if not min_length <= dur <= NOTE_RISE_MAX_DURATION:
            break
        out.append((end - a, nxt - end))
        end = nxt
    return out


def store_values(kmax: int, room: int) -> List[int]:
    """The store values given a program of their own, at most `room` of them.

    Every k in 1..kmax where they fit; otherwise `room` values spread evenly
    over the range from 1 to kmax, so the sweep still starts and ends where
    the block's does.
    """
    if kmax < 1 or room < 1:
        return []
    if room >= kmax:
        return list(range(1, kmax + 1))
    if room == 1:
        return [kmax]
    return sorted({round(1 + j * (kmax - 1) / (room - 1)) for j in range(room)})


def nearest_value(k: int, values: List[int]) -> int:
    """The value whose program store k takes (the lower one on a tie)."""
    return min(values, key=lambda v: (abs(v - k), v))


def _ticks(half) -> Tuple[int, ...]:
    return (half,) if isinstance(half, int) else tuple(half)


def row_calls_of(hs: Tuple[int, ...], tick_calls: int,
                 row_ticks: int = 2) -> Tuple[Dict[int, str], int]:
    """({call in the row: 'step' | 'note'}, the call of the last store).

    A store is on its tick's first call. The voice is put back on its note
    (a delay whose last call is relative note 0, gplay.c:719-725) on the call
    before each store, so the step is measured from the note; on the first
    call of the tick after each store, where the original is back on its
    vibrato; and on the row's last call, so the next row's store is measured
    from the note too -- unless that call is itself a store.
    """
    t = tick_calls
    calls: Dict[int, str] = {h * t: "step" for h in hs}
    for h in hs:
        if h * t >= 1:
            calls.setdefault(h * t - 1, "note")
        if h < row_ticks - 1:
            calls.setdefault((h + 1) * t, "note")
    calls.setdefault(row_ticks * t - 1, "note")
    return calls, max(h * t for h in hs)


def tail_entries(half: int, tick_calls: int, row_ticks: int = 2
                 ) -> List[tuple]:
    """The steps every program whose last store is on tick `half` jumps into
    after its step; none where the step is the row's last call.

    Entered on the call after the step: the note on the first call of the
    tick after it (a delay of `tick_calls - 1`: the last of `tick_calls`
    calls) where there is one, and on the row's last call. Then a stop.
    """
    calls, last = row_calls_of((half,), tick_calls, row_ticks)
    out: List[tuple] = []
    at = last + 1
    for c in sorted(c for c in calls if c > last):
        out.append((c - at, NOTE_RISE_NOTE_BASE))
        at = c + 1
    return out + [(GT_WAVE_JUMP, 0x00)] if out else []


def program_entries(half, tick_calls: int, cmd: int, speed, tail: int,
                    row_ticks: int = 2) -> List[tuple]:
    """One store value's program: (the note before it,) the step, the jump.

    `half` is the tick of the row's store, or the ticks of its two stores;
    `speed` its speed-table index, or theirs in the same order. The notes
    between two stores are part of the program; everything after the last
    is the shared tail at `tail` (where there is none the program stops).
    """
    hs = _ticks(half)
    speeds = _ticks(speed)
    calls, last = row_calls_of(hs, tick_calls, row_ticks)
    steps = {h * tick_calls: sp for h, sp in zip(hs, speeds)}
    out: List[tuple] = []
    at = 0
    for c in sorted(c for c in calls if c <= last):
        if c in steps:
            assert c == at, (hs, tick_calls)
            out.append((cmd, steps[c]))
        else:
            out.append((c - at, NOTE_RISE_NOTE_BASE))
        at = c + 1
    has_tail = bool(tail_entries(hs[-1], tick_calls, row_ticks))
    return out + [(GT_WAVE_JUMP, (tail & 0xFF) if has_tail else 0x00)]


def delays_fit(row_ticks: int, tick_calls: int) -> bool:
    """Whether every delay a row's programs need is at most `WAVE_MAX_DELAY`
    (a wavetable delay is $00-$0F). A row of two ticks of up to 16 calls
    always fits; a row of three has a gap of `2 * tick_calls - 2` calls
    between a store and the last call, so it fits only to 8 calls a tick."""
    for h in range(row_ticks):
        for hs in ((h,), (h, h + 2)):
            if hs[-1] >= row_ticks:
                continue
            progs = (program_entries(hs, tick_calls, WAVECMD_PORTAUP,
                                     (1,) * len(hs), 1, row_ticks)
                     + tail_entries(hs[-1], tick_calls, row_ticks))
            if any(left > WAVE_MAX_DELAY for left, _r in progs
                   if left < WAVECMD_BASE):
                return False
    return True


def program_cost(half: int, tick_calls: int,
                 row_ticks: int = 2) -> Tuple[int, int]:
    """(entries a value, entries of the shared tail) for `half`."""
    return (len(program_entries(half, tick_calls, WAVECMD_PORTAUP, 1, 1,
                                row_ticks)),
            len(tail_entries(half, tick_calls, row_ticks)))


def note_rise_entries(values: dict, tick_calls: int, step: int, start: int,
                      speed_index, row_ticks: int = 2
                      ) -> Tuple[List[tuple], dict]:
    """(wavetable entries, {(ticks, value): its program's start}).

    `values` maps the tick of a row's store (an int), or the ticks of its
    two stores (a tuple), to the values programmed for it -- an int each, or
    a tuple of two. Per tick a row ends on, its shared tail and then its
    programs (`program_entries`), laid out from `start` (1-based).
    """
    cmd = WAVECMD_PORTAUP if step > 0 else WAVECMD_PORTADOWN
    entries: List[tuple] = []
    starts = {}
    for last in sorted({_ticks(h)[-1] for h in values}):
        tail = start + len(entries)
        entries += tail_entries(last, tick_calls, row_ticks)
        for half in sorted((h for h in values if _ticks(h)[-1] == last),
                           key=_ticks):
            for v in values[half]:
                starts[(half, v)] = start + len(entries)
                sp = tuple(speed_index(x) for x in _ticks(v))
                entries += program_entries(half, tick_calls, cmd,
                                           sp[0] if len(sp) == 1 else sp,
                                           tail, row_ticks)
    return entries, starts


def _rise_pieces(values: dict, tick_calls: int, row_ticks: int):
    """[(key, size)] in layout order: per tick a row ends on, its shared
    tail (key `last`) and then its programs (key `(half, value)`). A tail of
    no entries is left out. The same order `note_rise_entries` lays out."""
    pieces: List[tuple] = []
    for last in sorted({_ticks(h)[-1] for h in values}):
        n = len(tail_entries(last, tick_calls, row_ticks))
        if n:
            pieces.append((last, n))
        for half in sorted((h for h in values if _ticks(h)[-1] == last),
                           key=_ticks):
            for v in values[half]:
                pieces.append(((half, v), len(program_entries(
                    half, tick_calls, WAVECMD_PORTAUP,
                    (1,) * len(_ticks(half)), 1, row_ticks))))
    return pieces


def layout_pieces(sizes: List[int], holes: List[Tuple[int, int]],
                  wave_len: int) -> Tuple[List[int], int]:
    """([first row of each piece], rows appended past `wave_len`).

    Each piece goes into the first hole (first row, rows) it fits, else onto
    the end. Every piece is a run of delays ending in a jump, so it works
    wherever it stands. With no holes this is the contiguous layout."""
    free = [list(h) for h in holes]
    at = wave_len + 1
    rows: List[int] = []
    for size in sizes:
        for h in free:
            if h[1] >= size:
                rows.append(h[0])
                h[0] += size
                h[1] -= size
                break
        else:
            rows.append(at)
            at += size
    return rows, at - 1 - wave_len


def note_rise_placed(values: dict, tick_calls: int, step: int, wave_len: int,
                     holes: List[Tuple[int, int]], speed_index,
                     row_ticks: int = 2
                     ) -> Tuple[Dict[int, tuple], dict]:
    """({row: wavetable entry}, {(ticks, value): its program's start}), the
    pieces of `note_rise_entries` placed by `layout_pieces`: in `holes`
    where they fit, else from `wave_len + 1` on."""
    cmd = WAVECMD_PORTAUP if step > 0 else WAVECMD_PORTADOWN
    pieces = _rise_pieces(values, tick_calls, row_ticks)
    rows, _ = layout_pieces([n for _k, n in pieces], holes, wave_len)
    at = dict(zip([k for k, _n in pieces], rows))
    placed: Dict[int, tuple] = {}
    starts = {}
    for last in sorted({_ticks(h)[-1] for h in values}):
        tail = at.get(last, 0)
        for i, e in enumerate(tail_entries(last, tick_calls, row_ticks)):
            placed[tail + i] = e
        for half in sorted((h for h in values if _ticks(h)[-1] == last),
                           key=_ticks):
            for v in values[half]:
                starts[(half, v)] = at[(half, v)]
                sp = tuple(speed_index(x) for x in _ticks(v))
                for i, e in enumerate(program_entries(
                        half, tick_calls, cmd,
                        sp[0] if len(sp) == 1 else sp, tail, row_ticks)):
                    placed[at[(half, v)] + i] = e
    return placed, starts


def reclaimable_holes(wave_entries: List[tuple], wave_starts: List[int],
                      pointers: List[int]
                      ) -> Tuple[List[Tuple[int, int]], List[int]]:
    """([(first row, rows)] of unused duplicate blocks, the starts to use).

    Every instrument's record is its own block, and several records carry
    the same one (Game_Killer: instruments 1, 2, 4, 8 and 10 are all `41 00 /
    07 00 / 41 00 / FF 00 / FF 00`). A block that ends in a stop, jumps
    nowhere but 0 (so it does not care where it stands), is named by no
    pointer and entered by no jump from elsewhere is the same program as the
    first block with its entries; its records are repointed there and its
    rows are free. `pointers` is every other row anything points at.
    """
    size = len(wave_entries)
    named = {p for p in pointers if p}
    bounds = sorted({s for s in wave_starts if s} | named | {size + 1})
    jump_to = [t for left, t in wave_entries if left == GT_WAVE_JUMP and t]
    canon: Dict[tuple, int] = {}
    move: Dict[int, int] = {}
    holes: List[Tuple[int, int]] = []
    for s in sorted({s for s in wave_starts if s}):
        e = next(b for b in bounds if b > s)
        block = tuple(wave_entries[s - 1:e - 1])
        if (not block or block[-1] != (GT_WAVE_JUMP, 0x00)
                or any(left == GT_WAVE_JUMP and t for left, t in block)):
            continue
        if block not in canon:
            canon[block] = s
        elif (not any(s <= p < e for p in named)
              and not any(s <= t < e for t in jump_to)):
            move[s] = canon[block]
            holes.append((s, len(block)))
    return holes, [move.get(x, x) for x in wave_starts]


def _note_rows(tracks: List[List[int]], patterns: List[List[int]],
               numbers: set):
    """Every note an instrument in `numbers` plays, one lap of each orderlist
    in play order, the instrument column sticky:
    (instrument, track, rows of the lap, lap row, rows long, note)."""
    for ti, track in enumerate(tracks):
        rows = list(_gw_skydive._lap_rows(track, patterns))
        current = 0
        for a, (p, r, transpose) in enumerate(rows):
            note, instr = patterns[p][4 * r], patterns[p][4 * r + 1]
            if instr:
                current = instr
            if not (GT_FIRST_NOTE <= note <= GT_LAST_NOTE):
                continue
            if current not in numbers:
                continue
            end = next((e for e in range(a + 1, len(rows))
                        if patterns[rows[e][0]][4 * rows[e][1]] != GT_REST
                        or patterns[rows[e][0]][4 * rows[e][1] + 1]), None)
            if end is None:
                continue
            yield (current, ti, rows, a, end - a,
                   note - GT_FIRST_NOTE + transpose)


def _rise_plan_once(sid: SidFile, det: Detection, tracks: List[List[int]],
                    patterns: List[List[int]], lead: int, instr_used: int,
                    fmt: str, multiplier: int, gate_skip: Optional[int],
                    row_calls: int, speed_table: List[tuple], wave_used: int,
                    no_test_restart: bool = False, real_firstwave: tuple = (),
                    log=None, reserve: int = 0,
                    wave_entries: Optional[List[tuple]] = None,
                    wave_starts: Optional[List[int]] = None,
                    wave_pointers: Optional[List[int]] = None,
                    extend: bool = True, info: Optional[dict] = None
                    ) -> Optional[_gw_skydive.SkydivePlan]:
    """The rows holding a store of every long note on a bit-$02 record, each
    pointed at its store's program, or None where nothing is taken.

    Taken only where the subtune's row is two or three ticks of
    `row_calls / frames` calls, the record's vibrato rewrites the frequency
    every tick (the alternating reading, `skydive_records`), and -- per
    (pattern, row) -- every time the orderlists play the row it asks for the
    same store or stores on the same ticks and its command column persists
    the row before's (`skydive_plan`'s rule). Everything declined is counted
    in the log line. `reserve` wavetable entries are left free for a later
    pass (`past_table_wave.retarget_mixed_steps`). Where the programs do not
    all fit, the rows of duplicate instrument blocks (`reclaimable_holes`)
    are used too, given `wave_entries`, `wave_starts` and `wave_pointers`
    (every other row anything points at): the plan then carries the
    wavetable to use (`base`) and the instrument starts (`starts`).
    """
    nr = det.note_rise
    if nr is None:
        return None
    extend = extend and note_rise_rest_carries_on(sid, det)

    def say(msg: str) -> None:
        if log:
            log(f"Note rise (bit $02).....: {msg}")

    records = _gw_skydive.skydive_records(sid, det, max(instr_used - lead, 0))
    alternating = {i + lead + 1 for i, alt in records.items() if alt}
    if not records:
        return None
    if fmt != FORMAT_GTS5:
        say(f"{len(records)} record(s), not emitted (GTS2 stores no speed "
            f"table)")
        return None
    if not alternating:
        say(f"{len(records)} record(s), none with a vibrato between the "
            f"stores, not emitted")
        return None
    base = _gw_arpeggio.frame_counter_base(sid, nr.counter)
    first = _gw_arpeggio.fixed_arp_first_fetch(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if base is None or first is None or speeds is None:
        say("counter or row clock not read, not emitted")
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None                      # a split subtune shifted the numbering
    tick_calls = _gate_calls(max(1, multiplier), gate_skip)
    if not 1 <= tick_calls <= WAVE_MAX_DELAY + 1:
        say(f"a tick of {tick_calls} calls, not emitted")
        return None

    plays: Dict[tuple, int] = {}
    for track in tracks:
        for p, r, _t in _gw_skydive._lap_rows(track, patterns):
            plays[(p, r)] = plays.get((p, r), 0) + 1
    asks: Dict[tuple, List[tuple]] = {}
    askers: Dict[tuple, set] = {}
    runs: List[Tuple[List[tuple], int]] = []   # per continued note: its rows
    kbase = 0           # the highest store the notes' own events ask for
    carried_on: List[tuple] = []        # ((pattern, row), (k, tick)) past a note
    declined: Dict[str, int] = {}

    def decline(why: str) -> None:
        declined[why] = declined.get(why, 0) + 1

    for number, ti, rows, a, length, note in _note_rows(tracks, patterns,
                                                        alternating):
        dur = length - 1
        if dur > NOTE_RISE_MAX_DURATION or dur < nr.min_length:
            continue                     # the block's own length test: none
        frames = speeds.frames_for(ti // 3)
        if (frames not in NOTE_RISE_ROW_TICKS
                or frames * tick_calls != row_calls):
            decline("rows not two or three ticks")
            continue
        if not delays_fit(frames, tick_calls):
            decline("a delay past $0F")
            continue
        phase = store_phase(base, first, a, frames)
        lag = store_lag(multiplier, tick_calls,
                        not (no_test_restart or number in real_firstwave))
        high = _gw_skydive._high_byte(sid, note)
        # The `BEQ` on savehi: a rising byte stops once it wraps to zero, a
        # falling one after it stores 1.
        cap = (0x100 - high) if nr.step > 0 else high
        kcap = min(cap, NOTE_RISE_MAX_STEP + 1)
        stores = store_rows(phase, lag, frames, length, kcap)
        kbase = max([kbase] + [k for v in stores.values() for k, _h in v])
        more = (continuation(rows, patterns, a, length, nr.min_length)
                if extend else [])
        if more:
            stores = store_rows(phase, lag, frames,
                                length + sum(n for _s, n in more), kcap,
                                {s * frames for s, _n in more})
        seq: List[tuple] = []
        lp, lr, _ = rows[a + length - 1]
        carried = patterns[lp][4 * lr + 2] in (0, 4)
        for j, got in stores.items():
            wp, wr, _ = rows[a + j]
            pp, pr, _ = rows[a + j - 1]
            cell = tuple(patterns[wp][4 * wr + 2:4 * wr + 4])
            before = tuple(patterns[pp][4 * pr + 2:4 * pr + 4])
            safe = (cell == before
                    and cell[0] in _gw_skydive.SKYDIVE_PERSISTENT_COMMANDS)
            # The rows of a continuing event: the KEYOFF that opens it carries
            # the tie's `CMD_TONEPORTA 00` (patterns.py, the `pending_tie`
            # row), which on a row with no note only pins the voice to its
            # last note -- and would pin it against the step -- and its hold
            # rows carry no command at all. A pointer in either leaves the
            # note's own vibrato (or nothing) running on through the release,
            # as the original's does; a slide the note had does not carry on,
            # so the row before the event must be one of those.
            if (not safe and j >= length and carried
                    and cell in ((0, 0x00), (CMD_TONEPORTA, 0x00))):
                safe = True
            asks.setdefault((wp, wr), []).append((tuple(got), safe))
            askers.setdefault((wp, wr), set()).add(number)
            seq.append((wp, wr))
            if j >= length:
                carried_on.extend(((wp, wr), kh) for kh in got)
        if more:
            runs.append((seq, frames))

    taken: Dict[tuple, tuple] = {}
    mixed = 0
    for key, wants in asks.items():
        if (len(wants) == plays.get(key, 0) and len(set(wants)) == 1
                and wants[0][1]):
            taken[key] = wants[0][0]
        else:
            mixed += 1
    if not taken:
        say(f"{sum(len(w) for w in asks.values())} store row(s), none taken"
            + (f" ({mixed} mixed or occupied)" if mixed else "")
            + ("; declined: " + ", ".join(f"{n} {w}"
                                           for w, n in declined.items())
               if declined else ""))
        return None

    def ticks_of(ask: tuple):
        hs = tuple(h for _k, h in ask)
        return hs[0] if len(hs) == 1 else hs

    def programs_for(chosen: List[int], rows: Dict[tuple, tuple]
                     ) -> Dict[object, List[object]]:
        """{ticks: [the values programmed for it]} for `rows`."""
        out: Dict[object, set] = {}
        for ask in rows.values():
            vs = tuple(nearest_value(k, chosen) for k, _h in ask)
            out.setdefault(ticks_of(ask), set()).add(
                vs[0] if len(vs) == 1 else vs)
        return {h: sorted(vs, key=_ticks) for h, vs in out.items()}

    def clipped(top: int) -> Dict[tuple, tuple]:
        """`taken` with the stores above `top` left out, and the rows that
        had nothing else."""
        cut = {key: tuple(x for x in ask if x[0] <= top)
               for key, ask in taken.items()}
        # A store on a row's last tick has no tail to put the voice back on
        # its note: the next row's program does that, or the next note. Where
        # a continued note's stores above `top` are left out, neither comes,
        # so its last kept store is the last one with a tail (the voice would
        # otherwise stay risen to the end of the release).
        for seq, fr in runs:
            if not any(x[0] > top for key in seq for x in taken.get(key, ())):
                continue
            for key in reversed(seq):
                ask = cut.get(key, ())
                while ask and not tail_entries(ask[-1][1], tick_calls, fr):
                    ask = ask[:-1]
                if key in cut:
                    cut[key] = ask
                if ask:
                    break
        return {key: ask for key, ask in cut.items() if ask}

    kmax = max(k for ask in taken.values() for k, _h in ask)
    snapshot = list(speed_table)
    room = GT_MAX_TABLELEN - len(speed_table)
    limit = GT_MAX_TABLELEN - max(0, reserve)
    # Where the values do not all fit: one kind of row (Game_Killer's, a store
    # on every row's one tick) takes fewer values spread over the range and
    # each store the nearest, as before. Several kinds (a row of three ticks
    # has four) repeat each spread value in every kind, so there the lowest
    # values are kept exact and the stores above them are left to the vibrato.
    kinds = {ticks_of(ask) for ask in taken.values()}
    def fitting(holes: List[Tuple[int, int]]):
        """Every (values, rows) whose programs fit, most values first."""
        for count in range(min(kmax, room), 0, -1):
            if count < kmax and len(kinds) > 1:
                trial_values, trial_rows = (list(range(1, count + 1)),
                                            clipped(count))
            else:
                trial_values, trial_rows = store_values(kmax, count), taken
            if not trial_rows:
                continue
            sizes = [n for _k, n in _rise_pieces(
                programs_for(trial_values, trial_rows), tick_calls, frames)]
            if (wave_used + layout_pieces(sizes, holes, wave_used)[1]
                    <= limit):
                yield trial_values, trial_rows

    def speed_index(k: int) -> int:
        entry = (k, 0x00)
        if entry not in speed_table:
            speed_table.append(entry)
        return speed_table.index(entry) + 1

    def attempt(chosen: List[int], rows: Dict[tuple, tuple],
                holes: List[Tuple[int, int]]) -> Optional[dict]:
        """Everything the plan emits for `chosen` values, or None where the
        speed table is full or no pattern can take its rows. Leaves
        `speed_table` as it found it; the speed table it wants is in the
        result."""
        speed_table[:] = snapshot
        values = programs_for(chosen, rows)
        base_table: Optional[List[tuple]] = None
        placed: Dict[int, tuple] = {}
        if holes:
            placed, starts = note_rise_placed(values, tick_calls, nr.step,
                                              wave_used, holes, speed_index,
                                              frames)
            base_table = list(wave_entries)
            entries: List[tuple] = []
            for row in sorted(placed):
                if row <= wave_used:
                    base_table[row - 1] = placed[row]
                else:
                    assert row == wave_used + len(entries) + 1, row
                    entries.append(placed[row])
        else:
            entries, starts = note_rise_entries(values, tick_calls, nr.step,
                                                wave_used + 1, speed_index,
                                                frames)
        speeds = list(speed_table)
        speed_table[:] = snapshot
        if len(speeds) > GT_MAX_TABLELEN:
            return None
        out = [list(pat) for pat in patterns]
        edited = stores = over = cut = 0
        numbers: set = set()
        for p in sorted({p for p, _r in rows}):
            def fill(pool: List[int]) -> Optional[List[int]]:
                trial = list(out[p])
                for (tp, r), ask in rows.items():
                    if tp == p:
                        vs = tuple(nearest_value(k, pool) for k, _h in ask)
                        at = starts.get((ticks_of(ask),
                                         vs[0] if len(vs) == 1 else vs))
                        if at is None:
                            return None   # no program of that value here
                        trial[4 * r + 2] = CMD_SETWAVEPTR
                        trial[4 * r + 3] = at
                return trial

            def too_big(trial: Optional[List[int]]) -> bool:
                return trial is None or (_gw_pulse.packed_pattern_size(
                    _gw_pulse.pattern_rows(trial)) > PACKED_PATTERN_LIMIT)

            trial = fill(chosen)
            # A command/data pair costs two bytes wherever it changes, and
            # every store of a long note asks for a value of its own: a
            # pattern past the limit takes every other value (then every
            # third ...) from the programs there are, before it is given up.
            # Only where the duplicate blocks made room for the values: a
            # file that fits without them is laid out as it was.
            thin = 1
            while holes and too_big(trial) and thin < len(chosen):
                thin += 1
                trial = fill(chosen[::thin] + [chosen[-1]])
            kept = [key for key in rows if key[0] == p]
            if too_big(trial):
                # First-fit in row order, as `pulse.budget_pulse_phase_commands`:
                # the pack charges a command only where it changes from the row
                # before, so which pointers fit depends on which were kept
                # before them. A pattern that does not take every row keeps the
                # rest on the vibrato rather than losing the lot (Human_Race's
                # patterns $50 and $53 pack to 262 with all 112 rows, 6 bytes
                # over greloc's 256).
                trial, kept = list(out[p]), []
                for (tp, r), ask in sorted(rows.items()):
                    if tp != p:
                        continue
                    vs = tuple(nearest_value(k, chosen) for k, _h in ask)
                    at = starts.get((ticks_of(ask),
                                     vs[0] if len(vs) == 1 else vs))
                    if at is None:
                        continue
                    cell = trial[4 * r + 2:4 * r + 4]
                    trial[4 * r + 2] = CMD_SETWAVEPTR
                    trial[4 * r + 3] = at
                    if too_big(trial):
                        trial[4 * r + 2:4 * r + 4] = cell
                        cut += 1
                        continue
                    kept.append((tp, r))
                if not kept:
                    over += 1
                    continue
            edited += len(kept)
            stores += sum(len(rows[key]) for key in kept)
            numbers |= set().union(*(askers[key] for key in kept))
            out[p] = trial
        if not edited:
            return None
        return dict(chosen=chosen, rows=rows, holes=holes, out=out,
                    edited=edited, over=over, cut=cut, numbers=numbers,
                    entries=entries, base=base_table, placed=placed,
                    speeds=speeds, score=(stores, len(chosen)))

    best: Optional[dict] = None
    for values_, rows_ in fitting([]):
        best = attempt(values_, rows_, [])
        break
    # Where they do not all go in, the rows of duplicate instrument blocks
    # are free too (`reclaimable_holes`). Every count of values that fits
    # with them is tried -- more values mean more distinct operands, and a
    # pattern past the packed limit loses all its rows -- and they are used
    # only where that keeps more stores, or the same with more values, so a
    # file that fits is laid out as before.
    new_starts: Optional[List[int]] = None
    perfect = (best is not None and len(best["chosen"]) == kmax
               and best["over"] == 0)
    if (not perfect and wave_entries is not None and wave_starts is not None
            and len(wave_entries) == wave_used):
        named = list(wave_pointers or []) + [
            pat[4 * r + 3] for pat in patterns for r in range(len(pat) // 4)
            if pat[4 * r + 2] == CMD_SETWAVEPTR]
        free, starts_to = reclaimable_holes(wave_entries, wave_starts, named)
        if free:
            for values_, rows_ in fitting(free):
                got = attempt(values_, rows_, free)
                if got is not None and (best is None
                                        or got["score"] > best["score"]):
                    best, new_starts = got, starts_to
    if best is None:
        say(f"{len(taken)} store row(s), no wavetable room or no pattern "
            f"within the packed limit, not emitted")
        return None
    chosen, rows, holes = best["chosen"], best["rows"], best["holes"]
    out, edited, numbers = best["out"], best["edited"], best["numbers"]
    entries, base_table, placed = best["entries"], best["base"], best["placed"]
    speed_table[:] = best["speeds"]
    if best["over"]:
        declined["pattern past the packed limit"] = best["over"]
    if best["cut"]:
        declined["row past the packed limit"] = best["cut"]
    dropped_stores = sum(len(a) for a in taken.values()) - sum(
        len(a) for a in rows.values())
    taken = rows
    halves = sorted({h for ask in taken.values() for _k, h in ask})
    names = ("first", "second", "third", "fourth")
    how = ("" if len(chosen) == kmax else
           f" ({dropped_stores} store(s) above left to the vibrato)"
           if dropped_stores else " (nearest)")
    say(f"{edited} store row(s) on instrument(s) {sorted(numbers)}, "
        f"{len(chosen)} of {kmax} store value(s){how}, "
        f"{'+' if nr.step > 0 else '-'}$100 a step on the rows' "
        f"{'/'.join(names[h] for h in halves)} tick, "
        f"{tick_calls} calls a tick, {len(entries)} wavetable step(s) at "
        f"{wave_used + 1}"
        + (f" and {sum(1 for r in placed if r <= wave_used)} reused from "
           f"{len(holes)} duplicate block(s)" if holes else "")
        + (f"; {mixed} row(s) mixed or occupied" if mixed else "")
        + (f"; {len(runs)} note(s) carried on through the rest after them"
           if runs else "")
        + ("; declined: " + ", ".join(f"{n} {w}" for w, n in declined.items())
           if declined else ""))
    if info is not None:
        info.update(chosen=chosen, kbase=kbase, edited=edited,
                    cut=best["cut"], over=best["over"], continued=bool(runs),
                    carried=len(carried_on),
                    placed=sum(1 for key, kh in carried_on
                               if kh in rows.get(key, ())))
    return _gw_skydive.SkydivePlan(patterns=out, entries=entries,
                                   base=base_table, starts=new_starts)


def _extension_pays(ext: dict, base: dict) -> bool:
    """Whether the plan that carries notes on through the rest after them
    (`ext`) keeps everything the plan without it (`base`) does -- every value
    the notes' own events ask for exact, no more rows cut or patterns lost
    to the packed limit, no fewer rows edited -- and places at least half of
    the stores it carries on.

    The last is what keeps a file whose rests are mostly shared rows from
    moving for a handful of stores: Crazy_Comets asks for 256 and places
    10-16 (its rests are played after other notes too, so `mixed`), Human_Race
    18 and 1, Game_Killer 136 and 0; Chimera asks for 192 and places 114.
    """
    chosen, kbase = ext["chosen"], ext["kbase"]
    return (len(chosen) >= kbase and chosen[:kbase] == list(range(1, kbase + 1))
            and ext["over"] <= base["over"] and ext["cut"] <= base["cut"]
            and ext["edited"] >= base["edited"]
            and 2 * ext["placed"] >= ext["carried"])


def note_rise_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                   patterns: List[List[int]], lead: int, instr_used: int,
                   fmt: str, multiplier: int, gate_skip: Optional[int],
                   row_calls: int, speed_table: List[tuple], wave_used: int,
                   no_test_restart: bool = False, real_firstwave: tuple = (),
                   log=None, reserve: int = 0,
                   wave_entries: Optional[List[tuple]] = None,
                   wave_starts: Optional[List[int]] = None,
                   wave_pointers: Optional[List[int]] = None
                   ) -> Optional[_gw_skydive.SkydivePlan]:
    """`_rise_plan_once`, with the rise carried on through the rest after a note
    (`continuation`) where that costs the notes' own stores nothing.

    The continued stores raise the highest value asked for, and a table
    that cannot hold them all spreads or clips what it can: so the plan is
    taken twice, with them and without, and the longer one is kept only
    where every value the notes' own events ask for is still exact (Battle
    of Britain: one continued note had the other stores' values spread over
    52 and took its two $0FF voices from 98% and 99% to 59% on the stores),
    no pattern rows were cut that were not cut before, no row is lost, and
    half of what it carries on is placed (`_extension_pays`). Everything
    else -- the speed table, the log -- is the kept plan's. A file the
    continuation does not touch is planned once, as it was.
    """
    def run(extend: bool):
        table = list(speed_table)
        lines: List[str] = []
        info: dict = {}
        plan = _rise_plan_once(
            sid, det, tracks, patterns, lead, instr_used, fmt, multiplier,
            gate_skip, row_calls, table, wave_used, no_test_restart,
            real_firstwave, lines.append, reserve, wave_entries, wave_starts,
            wave_pointers, extend, info)
        return plan, table, lines, info

    kept = run(True)
    if kept[0] is None:
        # nothing taken with the continuation: never worse than without it
        kept = run(False)
    elif kept[3].get("continued"):
        base = run(False)
        if base[0] is None or not _extension_pays(kept[3], base[3]):
            kept = base
    plan, table, lines, _info = kept
    speed_table[:] = table
    if log:
        for line in lines:
            log(line)
    return plan
