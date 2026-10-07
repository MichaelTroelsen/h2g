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

The step is a jump -- one call, not a rate -- so it is not divided by the
multiplier. The row's vibrato command persists across a pointer row (gplay.c
tick 0 leaves `command` alone for $8; player.s `mt_tick0_8`), and the delays
and the calls after each program's stop run it.

A per-instrument program cannot hold it: every call of a 360-call note is a
step or part of a delay of at most 16, and Game_Killer's wavetable has 23
entries left. Two or three entries a store value fit where five hundred do
not; where even that does not fit, fewer values are spread over the range and
each store takes the nearest.

**What this approximates.** The original stores the note's high byte plus k
over the vibrato's LOW byte, so its low byte wanders by up to the vibrato's
depth where ours is the note's; and between stores the vibrato restarts from
the note on every row, where the original's runs on its global triangle.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, FORMAT_GTS5, GT_FIRST_NOTE,
                        GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        PACKED_PATTERN_LIMIT, WAVE_MAX_DELAY,
                        WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from .primitives import _gate_calls
from . import arpeggio as _gw_arpeggio
from . import pulse as _gw_pulse
from . import skydive as _gw_skydive
from . import tempo as _gw_tempo

# A Hubbard note's duration is the low five bits of its note byte.
NOTE_RISE_MAX_DURATION = 0x1F
# Ticks per row this emitter places: exactly one store a row.
NOTE_RISE_ROW_TICKS = 2
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


def tail_entries(half: int, tick_calls: int) -> List[tuple]:
    """The steps every program of `half` jumps into after its step.

    Entered on the call after the step. First half: the note on the second
    tick's first call (a delay of `tick_calls - 1`: the last of `tick_calls`
    calls), and again on the row's last call where the tick has more than
    one. Second half: the note on the row's last call. Then a stop.
    """
    t = tick_calls
    if half == 0:
        out = [(t - 1, NOTE_RISE_NOTE_BASE)]
        if t >= 2:
            out.append((t - 2, NOTE_RISE_NOTE_BASE))
    else:
        out = [(t - 2, NOTE_RISE_NOTE_BASE)]
    return out + [(GT_WAVE_JUMP, 0x00)]


def program_entries(half: int, tick_calls: int, cmd: int, speed: int,
                    tail: int) -> List[tuple]:
    """One store value's program: (the note before it,) the step, the jump."""
    head = [] if half == 0 else [(tick_calls - 1, NOTE_RISE_NOTE_BASE)]
    return head + [(cmd, speed), (GT_WAVE_JUMP, tail & 0xFF)]


def program_cost(half: int, tick_calls: int) -> Tuple[int, int]:
    """(entries a value, entries of the shared tail) for `half`."""
    return ((2 if half == 0 else 3),
            len(tail_entries(half, tick_calls)))


def note_rise_entries(values: Dict[int, List[int]], tick_calls: int,
                      step: int, start: int,
                      speed_index) -> Tuple[List[tuple], dict]:
    """(wavetable entries, {(half, value): its program's start}).

    Per half used, its shared tail and then one program a value (`program_
    entries`), laid out from `start` (1-based).
    """
    cmd = WAVECMD_PORTAUP if step > 0 else WAVECMD_PORTADOWN
    entries: List[tuple] = []
    starts = {}
    for half in sorted(values):
        tail = start + len(entries)
        entries += tail_entries(half, tick_calls)
        for v in values[half]:
            starts[(half, v)] = start + len(entries)
            entries += program_entries(half, tick_calls, cmd, speed_index(v),
                                       tail)
    return entries, starts


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


def note_rise_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                   patterns: List[List[int]], lead: int, instr_used: int,
                   fmt: str, multiplier: int, gate_skip: Optional[int],
                   row_calls: int, speed_table: List[tuple], wave_used: int,
                   no_test_restart: bool = False, real_firstwave: tuple = (),
                   log=None) -> Optional[_gw_skydive.SkydivePlan]:
    """The rows holding a store of every long note on a bit-$02 record, each
    pointed at its store's program, or None where nothing is taken.

    Taken only where the subtune's row is two ticks of `row_calls / 2`
    calls, the record's vibrato rewrites the frequency every tick (the
    alternating reading, `skydive_records`), and -- per (pattern, row) --
    every time the orderlists play the row it asks for the same store in the
    same half and its command column persists the row before's
    (`skydive_plan`'s rule). Everything declined is counted in the log line.
    """
    nr = det.note_rise
    if nr is None:
        return None

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
    declined: Dict[str, int] = {}

    def decline(why: str) -> None:
        declined[why] = declined.get(why, 0) + 1

    for number, ti, rows, a, length, note in _note_rows(tracks, patterns,
                                                        alternating):
        dur = length - 1
        if dur > NOTE_RISE_MAX_DURATION or dur < nr.min_length:
            continue                     # the block's own length test: none
        frames = speeds.frames_for(ti // 3)
        if frames != NOTE_RISE_ROW_TICKS or frames * tick_calls != row_calls:
            decline("rows not two ticks")
            continue
        # The counter reads `base + first + a * frames` on row a's fetch
        # tick and steps once a passing call; the fetch tick runs no effect
        # (Game_Killer $097B JMP $0B89), so store 0 is the first odd value
        # after it.
        phase = 1 if (base + first + a * frames + 1) & 1 else 2
        lag = store_lag(multiplier, tick_calls,
                        not (no_test_restart or number in real_firstwave))
        if (phase + lag) % 2 and tick_calls < 2:
            decline("a one-call tick with the store on the second")
            continue
        high = _gw_skydive._high_byte(sid, note)
        # The `BEQ` on savehi: a rising byte stops once it wraps to zero, a
        # falling one after it stores 1.
        cap = (0x100 - high) if nr.step > 0 else high
        for k in range(1, min(cap, NOTE_RISE_MAX_STEP + 1)):
            tick = phase + 2 * k
            if tick >= length * frames:
                break                    # past the note's last tick
            j, half = divmod(tick + lag, frames)
            if j >= length:
                break
            wp, wr, _ = rows[a + j]
            pp, pr, _ = rows[a + j - 1]
            cell = tuple(patterns[wp][4 * wr + 2:4 * wr + 4])
            safe = (cell == tuple(patterns[pp][4 * pr + 2:4 * pr + 4])
                    and cell[0] in _gw_skydive.SKYDIVE_PERSISTENT_COMMANDS)
            asks.setdefault((wp, wr), []).append((k, half, safe))
            askers.setdefault((wp, wr), set()).add(number)

    taken: Dict[tuple, tuple] = {}
    mixed = 0
    for key, wants in asks.items():
        if (len(wants) == plays.get(key, 0) and len(set(wants)) == 1
                and wants[0][2]):
            taken[key] = wants[0][:2]
        else:
            mixed += 1
    if not taken:
        say(f"{sum(len(w) for w in asks.values())} store row(s), none taken"
            + (f" ({mixed} mixed or occupied)" if mixed else "")
            + ("; declined: " + ", ".join(f"{n} {w}"
                                           for w, n in declined.items())
               if declined else ""))
        return None

    halves = sorted({h for _k, h in taken.values()})
    kmax = max(k for k, _h in taken.values())
    per_value = sum(program_cost(h, tick_calls)[0] for h in halves)
    tails = sum(program_cost(h, tick_calls)[1] for h in halves)
    room = (GT_MAX_TABLELEN - wave_used - tails) // per_value
    snapshot = list(speed_table)
    chosen = store_values(kmax, min(room, GT_MAX_TABLELEN - len(speed_table)))
    if not chosen:
        say(f"{len(taken)} store row(s), no wavetable room, not emitted")
        return None
    values = {h: chosen for h in halves}

    def speed_index(k: int) -> int:
        entry = (k, 0x00)
        if entry not in speed_table:
            speed_table.append(entry)
        return speed_table.index(entry) + 1

    entries, starts = note_rise_entries(values, tick_calls, nr.step,
                                        wave_used + 1, speed_index)
    if len(speed_table) > GT_MAX_TABLELEN:
        speed_table[:] = snapshot
        say("speed table full, not emitted")
        return None

    out = [list(pat) for pat in patterns]
    edited = 0
    numbers: set = set()
    for p in sorted({p for p, _r in taken}):
        trial = list(out[p])
        for (tp, r), (k, half) in taken.items():
            if tp == p:
                trial[4 * r + 2] = CMD_SETWAVEPTR
                trial[4 * r + 3] = starts[(half, nearest_value(k, chosen))]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            decline("pattern past the packed limit")
            continue
        edited += sum(1 for tp, _r in taken if tp == p)
        numbers |= set().union(*(askers[key] for key in taken if key[0] == p))
        out[p] = trial
    if not edited:
        speed_table[:] = snapshot
        say("every pattern past the packed limit, not emitted")
        return None
    say(f"{edited} store row(s) on instrument(s) {sorted(numbers)}, "
        f"{len(chosen)} of {kmax} store value(s)"
        f"{'' if len(chosen) == kmax else ' (nearest)'}, "
        f"{'+' if nr.step > 0 else '-'}$100 a step on the rows' "
        f"{'/'.join(('first', 'second')[h] for h in halves)} tick, "
        f"{tick_calls} calls a tick, {len(entries)} wavetable step(s) at "
        f"{wave_used + 1}"
        + (f"; {mixed} row(s) mixed or occupied" if mixed else "")
        + ("; declined: " + ", ".join(f"{n} {w}" for w, n in declined.items())
           if declined else ""))
    return _gw_skydive.SkydivePlan(patterns=out, entries=entries)
