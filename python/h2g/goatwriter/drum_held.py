"""The drum's noise held a second frame by the outer gate's skipped call.

Traced at -m1, a bit-$01 drum note of a player whose outer gate withholds one
call in `skip + 1` and whose speed gate fetches a row every other call has
one of two noise lengths, and **which one is a function of the frame the row
was fetched on and nothing else** (`tests/test_drum_wave_outer_gate_phase.py`
for Warhawk and Proteus; Spellbound here, 180 s, voices 0 and 2, every note):

    call f      the row is fetched; the wave is the attack ($41)
    call f + 1  the drum block writes $80 (noise), once
    call f + 2  the block would store the gate-off mask ($40) ... unless this
                is the call the outer gate withholds: the play routine
                returns at its first instruction and the chip keeps $80

so the noise is two frames where `f + 2` is the withheld call and one frame
elsewhere. Spellbound's play routine `$E012` (`DEC $C2 / BPL / LDA #$0A /
STA $C2 / RTS`) withholds every 11th call: 58 of 58 voice-0 and 128 of 128
voice-2 noise-instrument notes follow the rule, 0 exceptions.

An instrument's wavetable cannot say it -- all the 28 pattern cells of
Spellbound's drum rows see every start residue -- but **the residue of a
note is static**. Both counters start at the file's own bytes (the outer
counter is a zero-page cell the init's fill loop clears), so the call every
row fetch lands on is the simulation `drum_unit.fetch_frames` already runs.
This pass runs it over the start subtune's orderlists, takes the notes whose
`f + 2` is a withheld call, and gives each a `CMD_SETWAVEPTR` on its own row
into a copy of the record's program with the noise frame twice (`A B C D`
then a jump back to the record's own `C`). Programs that are identical from
the noise on (Spellbound's 3, 5 and 6) share one copy.

A program whose tail LOOPS (Spellbound records 2, 8-13, 15, 23-25: a pitch
alternation behind the noise) cannot take the extra frame as rows: the loop is
phased by the call grid already, and a second `C D` put it one frame late on
every held note (pitch 17.8 -> 20.4 mismatched frames a note). The original
holds the noise on the call the plain program's first tail row stands on
(`40:80`, one call), so the variant puts the noise THERE, `A B C D N jump`,
and the loop behind it keeps its phase -- only where that row and the one
after it are plain waveform rows, since a delay behind the noise would hold it
for the whole delay (Proteus records 11 and 12).

**Speed gate 3** (Bump_Set_Spike, International_Karate, Thrust): the noise is `gate - 1`
frames and `gate` where `f + 2` or `f + 3` is withheld (`is_held`). The
programs are `overlay_key`'s, not the copies above: a program that stops gets
the extra frame put IN (a sweep laid behind the noise starts a frame later on
a held note), a looping one keeps its timeline and has the noise written over
the rows that start in the held window. A note whose row a split renames
takes the clone's program (`edits`, `extra_starts`).

A pattern cell serves every orderlist position that plays it at every clock
phase, so a pattern whose positions disagree about a row is COPIED, one copy
per distinct spelling (the largest group stays on the pattern where nothing
else plays it; a position outside the walked lap, or in another subtune, keeps
the pattern unspelled). The start subtune only; one lap, so a repeat count
whose visits disagree votes by majority.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from . import tempo as _gw_tempo
from .arpeggio import _abs_writers, _countdown
from .constants import (CMD_SETWAVEPTR, CMD_TONEPORTA, GT_FIRST_NOTE,
                        GT_LAST_NOTE, GT_MAX_TABLELEN, GT_WAVE_JUMP,
                        OUTER_GATE_RTS, OUTER_GATE_RTS_ZP, SPEED_GATE)
from .counter_fall import _pattern_positions, _visits
from .drum_unit import clock_cells, fetch_frames

GT_END_PATTERN = 0xFF
# Patterns left for the passes after this one (the pre-note-wave copy, the
# master volume) and rows left for none: the plan is dropped, not squeezed.
PATTERN_RESERVE = 6
# The speed gates whose held noise has been measured: 2 (the module's
# docstring) and 3 (Bump_Set_Spike, International_Karate, Thrust -- the
# noise is `gate - 1` frames and `gate` where the unit holds a withheld call).
HELD_GATES = (2, 3)
OVERLAY = "overlay"
# `A B C D` (attack, delay, noise, delay), the noise again with the gate
# closed and its delay, and the jump to the row after the record's own D.
VARIANT_ROWS = 7
# `A B C D`, the noise replacing the tail's first row, and the jump behind it.
LOOP_VARIANT_ROWS = 6
# `LDX #n / LDA #$00 / STA zp,X / DEX / BPL`: the init's zero-page clear.
ZERO_FILL = re.compile(rb"\xa2(.)\xa9\x00\x95(.)\xca\x10\xfb", re.DOTALL)
_ZP_WRITERS = (0x85, 0x86, 0x84, 0xC6, 0xE6, 0x06, 0x46, 0x26, 0x66)
_ZP_INDEXED = (0x95, 0x94, 0x96, 0x16, 0x56, 0x36, 0x76, 0xD6, 0xF6)
# How far below a zero-page cell an indexed store of the init may start and
# still reach it: the fill loop is the one allowed to.
_INDEXED_REACH = 3


class DrumHeldPlan:
    def __init__(self, patterns, tracks, entries, flagged, keys, copies,
                 declined, sources):
        self.patterns = patterns
        self.tracks = tracks
        self.entries = entries
        self.flagged = flagged
        self.keys = keys
        self.copies = copies
        self.declined = declined
        # {copy: the pattern it copies}, for the per-pattern state a pass
        # computed before this one (`legato_rows`).
        self.sources = sources


def _zp_outer_start(sid: SidFile) -> Optional[Tuple[int, int]]:
    """(skip, first value) of a zero-page outer counter, or None.

    The `OUTER_GATE_RTS_ZP` spelling at the play entry. The cell is not in
    the image, so its first value is what the init leaves there: nothing may
    write it but the gate's own `DEC` and reload `STA`, and an init that
    clears a zero-page range containing it (`ZERO_FILL`) leaves 0.
    """
    at = _gw_tempo.play_entry(sid)
    if at is None:
        return None
    m = OUTER_GATE_RTS_ZP.match(sid.data, at)
    if m is None or m.group(1) != m.group(3):
        return None
    cell = m.group(1)[0]
    data = sid.data
    named = sum(data.count(bytes([op, cell])) for op in _ZP_WRITERS)
    if named != 2:                       # the gate's DEC and its reload STA
        return None
    for op in _ZP_INDEXED:
        for base in range(max(cell - _INDEXED_REACH, 0), cell + 1):
            if data.count(bytes([op, base])) and not any(
                    f.group(2)[0] == base and base <= cell <= base
                    + f.group(1)[0] for f in ZERO_FILL.finditer(data)):
                return None
    for f in ZERO_FILL.finditer(data):
        if f.group(2)[0] <= cell <= f.group(2)[0] + f.group(1)[0]:
            return m.group(2)[0], 0
    return None


def _abs_outer_start(sid: SidFile) -> Optional[Tuple[int, int]]:
    """(skip, first value) of an absolute outer counter in the `RTS`
    spelling at the play entry (Warhawk `$1012`), or None. The cell is in the
    image, so its first value is the file's byte; only the gate's own `DEC`
    and reload `STA` may write it."""
    at = _gw_tempo.play_entry(sid)
    if at is None:
        return None
    m = OUTER_GATE_RTS.match(sid.data, at)
    if m is None or m.group(1) != m.group(3):
        return None
    if _abs_writers(sid.data, m.group(1)) != 2:
        return None
    off = sid.to_offset(m.group(1)[0] | m.group(1)[1] << 8)
    if not 0 <= off < len(sid.data):
        return None
    return m.group(2)[0], sid.data[off]


def held_clock(sid: SidFile, det: Detection,
               gates: Tuple[int, ...] = HELD_GATES
               ) -> Optional[Tuple[int, int, int, int]]:
    """(gate, skip, outer start, inner start) of the start subtune, or None.

    Only a speed gate in `gates` (`HELD_GATES`): the noise runs from the call
    after the fetch to the call before the next fetch, so a unit that holds a
    withheld call is one frame longer than `gate` and its noise one longer
    than `gate - 1` (module docstring; the gate-3 files are measured in
    `tests/test_drum_held_gate3.py`).
    """
    try:
        speeds = _gw_tempo.find_song_speeds(sid, det if det.can_convert
                                            else None)
    except Exception:                                   # noqa: BLE001
        return None
    if speeds is None:
        return None
    idx = max(0, getattr(sid, "start_song", 1) - 1)
    gate = speeds.frames_for(idx)
    skip = speeds.skip_for(idx)
    if gate not in gates or not skip:
        return None
    cells = clock_cells(sid)
    if cells is not None:
        return gate, skip, cells[0], cells[1]
    outer = _zp_outer_start(sid) or _abs_outer_start(sid)
    if outer is None or outer[0] != skip:
        return None
    reload_addr = speeds.reload_addr
    data = sid.data
    for g in SPEED_GATE.finditer(data):
        if g.group(1) != g.group(3):
            continue
        if (g.group(2)[0] | g.group(2)[1] << 8) != reload_addr:
            continue
        if _abs_writers(data, g.group(1)) != 2:
            return None
        at = sid.to_offset(g.group(1)[0] | g.group(1)[1] << 8)
        if not 0 <= at < len(data):
            return None
        return gate, skip, outer[1], data[at]
    return None


def withheld_calls(outer: int, skip: int, upto: int) -> Set[int]:
    """The play calls (1, 2, ...) the outer gate does nothing on."""
    out: Set[int] = set()
    for call in range(1, upto + 1):
        outer, under = _countdown(outer, skip)
        if under:
            out.add(call)
    return out


def is_held(f: int, gate: int, withheld: Set[int]) -> bool:
    """The row fetched on call `f` has its noise held a frame: the call after
    the fetch writes it (not a withheld one), and a call the fetch's unit
    spends before the next fetch -- `f + 2` .. `f + gate` -- is withheld, so
    the chip keeps the noise through it instead of taking the gate-off mask.
    At gate 2 that is `f + 2` alone, the module's rule."""
    return (f + 1) not in withheld and any(
        (f + k) in withheld for k in range(2, gate + 1))


def held_rows(sid: SidFile, det: Detection, tracks, patterns
              ) -> Optional[Dict[tuple, bool]]:
    """`{(track, position, visit, row in pattern): noise is held}` for every
    row of one lap of the start subtune, or None where the clock is not
    readable. `row_index` is the voice's row grid (`arpeggio._walk_note_rows`).
    """
    idx = max(0, getattr(sid, "start_song", 1) - 1)
    # The first subtune's orderlists lead the list however many of the
    # PSID's later subtunes were dropped; any other start needs the numbering
    # to be the PSID's (`drum_unit.drum_first_units`).
    if 3 * idx + 3 > len(tracks) or (
            idx and len(tracks) != 3 * max(sid.subtunes, 1)):
        return None
    clock = held_clock(sid, det)
    if clock is None:
        return None
    gate, skip, outer0, inner0 = clock
    out: Dict[tuple, bool] = {}
    total = 0
    for ti in range(3 * idx, 3 * idx + 3):
        total = max(total, sum(
            len(patterns[p]) // 4 for _pos, p, _k, _t in
            _visits(tracks[ti], patterns)))
    fetched = fetch_frames(outer0, inner0, gate, skip, total + 2)
    if len(fetched) < total + 2:
        return None
    withheld = withheld_calls(outer0, skip, fetched[-1] + 3)
    for ti in range(3 * idx, 3 * idx + 3):
        row = 0
        for pos, p, k, _t in _visits(tracks[ti], patterns):
            pat = patterns[p]
            for r in range(0, len(pat), 4):
                if pat[r] == GT_END_PATTERN:
                    break
                out[(ti, pos, k, r)] = is_held(fetched[row], gate, withheld)
                row += 1
    return out


def _shape(entries: List[tuple], start: int):
    """(key, row of C) of the program at wavetable row `start`, or None.

    `A B C D ...`: a pitched attack wave and its delay, then a noise wave and
    its delay -- the shape `_wave_alternate_entries` lays for a drum whose
    noise is the frame after the attack -- ending in a jump within a block's
    reach, which is the program's tail. Two programs with the same key are
    identical from the noise on.
    """
    i = start - 1
    if start < 1 or i + 3 >= len(entries):
        return None
    a, b, c, d = entries[i:i + 4]
    if not (0x10 <= a[0] < 0x80 and 1 <= b[0] <= 0x0F
            and 0x80 <= c[0] < 0xE0 and 1 <= d[0] <= 0x0F):
        return None
    tail = []
    for e in entries[i + 2:i + 2 + 24]:
        tail.append(e)
        if e[0] == GT_WAVE_JUMP:
            if len(tail) < 3 or tail[2][0] == GT_WAVE_JUMP:
                return None
            # A looping tail is taken only where its first row is a plain
            # waveform row, the one call the held noise replaces.
            if e[1] != 0 and not (len(tail) >= 5
                                  and 0x10 <= tail[2][0] < 0xE0
                                  and 0x10 <= tail[3][0] < 0xE0):
                return None
            return (a, b, tuple(tail)), start + 2
    return None


def _drum_records(sid: SidFile, det: Detection, records: int) -> Set[int]:
    out: Set[int] = set()
    data = sid.data
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(data):
            break
        if data[base + 7] & 0x01:
            out.add(i)
    return out


def is_loop(key: tuple) -> bool:
    """The program's tail ends in a jump back into itself (`FF:xx`, xx != 0)
    rather than a stop (`FF:00`). An overlay key (gate 3) carries it."""
    if key[0] == OVERLAY:
        return key[3]
    return key[2][-1][1] != 0


def overlay_key(entries: List[tuple], start: int, gate: int,
                multiplier: int) -> Optional[tuple]:
    """`(OVERLAY, 0, rows, loops)`: the program at wavetable row `start` with
    its noise held a frame longer, or None. For a speed gate above 2.

    The plain program writes noise from its first noise row (`C`, call `n0`)
    to the first waveform row that is not noise (`n1`) -- `(gate - 1) *
    multiplier` calls where the record is the `A B C D` shape, whatever its
    own rows make of it otherwise. A held note keeps the chip on noise, gate
    closed, one frame (`multiplier` calls) longer. Two ways to say it, by what
    stands behind the noise:

    * **A program that stops** (`FF:00`, no command rows behind the noise):
      the frame goes IN, after the plain noise, and the rows behind it follow
      -- `A B C D`, one frame of closed noise, a jump to the pulse row.
    * **A program that loops** (a pitch alternation phased by the call grid, a
      pitch dither): the timeline must not move, so the plain program is
      unrolled up to the window's end, `n0 + gate * multiplier - 1`, with every
      waveform row that STARTS in `[n1, end]` written as noise instead (its
      right byte kept, so its pitch writes stay), the delay that crosses the
      end cut there with the record's own waveform written back on the next
      call, and a jump to the row behind. The window is whole frames, so the
      sample at a frame's end sees it whatever the note's call phase.

    None where the unrolled run meets a command row or a stop, where the plain
    noise already reaches the end, where the row after the window is a delay
    (it would keep the noise on) or a command row, and for a stop program
    with a sweep (command rows) behind the noise: Bump_Set_Spike's record 1
    (`F2:07` x 6) takes the frame IN and pitch_cents falls .8811 -> .8644, the
    noise written over the pulse row with the waveform put back a call later
    .8727, so it is left alone (the original's sweep starts a frame after its
    noise ends, held or not, and ours is already matched to it by being a
    frame early and slower).
    """
    i = start - 1
    if start < 1 or i + 3 >= len(entries):
        return None
    a, b, c, d = entries[i:i + 4]
    if not (0x10 <= a[0] < 0x80 and 1 <= b[0] <= 0x0F
            and 0x80 <= c[0] < 0xE0 and 1 <= d[0] <= 0x0F):
        return None
    tail = []
    for e in entries[i + 2:i + 2 + 24]:
        tail.append(e)
        if e[0] == GT_WAVE_JUMP:
            if len(tail) < 3 or tail[2][0] == GT_WAVE_JUMP:
                return None
            # A looping tail is taken only where its first row is a plain
            # waveform row, the one call the held noise replaces.
            if e[1] != 0 and not (len(tail) >= 5
                                  and 0x10 <= tail[2][0] < 0xE0
                                  and 0x10 <= tail[3][0] < 0xE0):
                return None
            return (a, b, tuple(tail)), start + 2
    return None


def _drum_records(sid: SidFile, det: Detection, records: int) -> Set[int]:
    out: Set[int] = set()
    data = sid.data
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(data):
            break
        if data[base + 7] & 0x01:
            out.add(i)
    return out


def is_loop(key: tuple) -> bool:
    """The program's tail ends in a jump back into itself (`FF:xx`, xx != 0)
    rather than a stop (`FF:00`). An overlay key (gate 3) carries it."""
    if key[0] == OVERLAY:
        return key[3]
    return key[2][-1][1] != 0


def overlay_key(entries: List[tuple], start: int, gate: int,
                multiplier: int) -> Optional[tuple]:
    """`(OVERLAY, start, rows, loops)` of the program at wavetable row `start`
    with its noise held to `gate` frames, or None. For a speed gate above 2.

    The plain program writes its noise for `(gate - 1) * multiplier` calls
    from the first noise row (`C`, call `n0`) -- or whatever the record's own
    rows make of it -- and then a waveform row that is not noise. A held note
    keeps the chip on noise, gate closed, to call `n0 + gate * multiplier - 1`:
    whole frames, so the sample the traces take at each frame's end sees it
    whatever the call phase of the note. **The rows after the noise are NOT
    moved**: the program's own timeline goes on exactly where it was (a second
    `C D` put Bump_Set_Spike's pitch 0.881 -> 0.833 at gate 3, and a pitch
    loop behind the noise is phased by the call grid, `variant`), so the
    variant is the plain program unrolled up to the window's end with every
    waveform row that STARTS inside `[first non-noise row, end]` written as
    noise instead (its right byte kept, so its pitch writes stay), the delay
    that crosses the end cut there with the record's own waveform written back
    on the next call, and a jump to the row behind.

    None where the straight run to the window's end meets a jump, a stop or a
    command row, where the plain noise already reaches the end, or where the
    row after the window is a delay (it would keep the noise on).
    """
    i = start - 1
    if start < 1 or i + 3 >= len(entries):
        return None
    a, b, c, d = entries[i:i + 4]
    if not (0x10 <= a[0] < 0x80 and 1 <= b[0] <= 0x0F
            and 0x80 <= c[0] < 0xE0 and 1 <= d[0] <= 0x0F):
        return None
    m = max(1, multiplier)
    span: List[tuple] = []          # (row index, first call, calls)
    call, pos, hops, stopped = 0, i, 0, False
    end = n1 = None
    while len(span) < 40:
        if end is not None and call > end:
            break
        if pos >= len(entries):
            return None
        left, right = entries[pos]
        if left == GT_WAVE_JUMP:
            # A jump costs no call: the row it lands on is the next call's.
            if right == 0:
                stopped = True
                break
            pos = right - 1
            hops += 1
            if hops > 8:
                return None
            continue
        if left == 0 or left >= 0xF0:
            return None
        n = left + 1 if left <= 0x0F else 1
        if pos == i + 2:
            end = call + gate * m - 1
        if (n1 is None and pos >= i + 2 and 0x10 <= left
                and not left & 0x80):
            n1 = call
        span.append((pos, call, n))
        call += n
        pos += 1
    else:
        return None
    if n1 is None or end is None or n1 > end:
        return None
    closed = c[0] & 0xFE
    loops = True
    for e in entries[i + 2:i + 2 + 24]:
        if e[0] == GT_WAVE_JUMP:
            loops = e[1] != 0
            break
    if not loops:
        # A program that stops (the drum's pitch sweep is laid behind the
        # noise as a run of command rows): its tail is timed from the end of
        # the noise, which the original holds a frame -- Bump_Set_Spike's
        # sweep starts a frame later on a held note -- so the frame goes IN,
        # and the rows behind it follow it.
        head = [entries[p] for p, first, _n in span if first < n1]
        at = next(p for p, first, _n in span if first == n1)
        for e in entries[at:at + 24]:
            if e[0] == GT_WAVE_JUMP:
                break
            if e[0] >= 0xF0:
                # A sweep (command rows) behind the noise: the original's
                # starts a frame later on a held note and ours, which sweeps
                # a call early and slower, is matched to it better where it
                # is NOT moved (Bump_Set_Spike record 1: pitch_cents
                # .8811 -> .8644 with the frame put in, -> .8727 with the
                # noise written over the pulse row and the waveform written
                # back a call later). Declined.
                return None
        if m <= 1:
            frame = [(closed, 0x80)]
        elif m == 2:
            frame = [(closed, 0x80), (closed, 0x80)]
        else:
            frame = [(closed, 0x80), (m - 2, 0x80)]
        return (OVERLAY, 0, tuple(head + frame + [(GT_WAVE_JUMP, at + 1)]),
                False)
    reg = None
    out: List[tuple] = []
    for p, first, n in span:
        left, right = entries[p]
        if 0x10 <= left < 0xF0:
            reg = left
            out.append((closed, right) if n1 <= first <= end
                       else (left, right))
        else:
            out.append((left, right))
    if stopped:
        # The program ends inside the window: the noise runs on to its end
        # and the record's waveform goes back where the plain program leaves
        # it.
        k = end - call + 1
        if k > 0:
            out.append((closed, 0x80) if k == 1 else (k - 1, 0x80))
        out.append((reg, 0x80))
        out.append((GT_WAVE_JUMP, 0))
    else:
        p, first, n = span[-1]
        left, right = entries[p]
        last_call = first + n - 1
        nxt = entries[pos] if pos < len(entries) else None
        if nxt is None:
            return None
        if last_call > end:
            # A delay crosses the end: noise to the end, the record's own
            # waveform on the call after, then what is left of the delay.
            if not 1 <= left <= 0x0F:
                return None
            out.pop()
            head = end - first + 1
            out.append((closed, 0x80) if head == 1 else (head - 1, 0x80))
            rest = last_call - end
            if rest == 1:
                out.append((reg, right))
            else:
                out.append((reg, 0x80))
                out.append((reg, right) if rest == 2 else (rest - 2, right))
        else:
            after = nxt
            if after[0] == GT_WAVE_JUMP and after[1]:
                after = entries[after[1] - 1]
            if 1 <= after[0] <= 0x0F:
                return None                   # a delay would keep the noise
            if 0xF0 <= after[0] < GT_WAVE_JUMP:
                return None                   # a sweep: see the stop path
            if after[0] == GT_WAVE_JUMP:
                # The program's end: the chip would keep the noise, so the
                # record's waveform is written back on the next call.
                out.append((reg, 0x80))
        out.append(nxt if nxt[0] == GT_WAVE_JUMP else (GT_WAVE_JUMP, pos + 1))
    return (OVERLAY, 0, tuple(out), True)


def variant_rows(key: tuple, gate: int = 2, multiplier: int = 1) -> int:
    if key[0] == OVERLAY:
        return len(key[2])
    return LOOP_VARIANT_ROWS if is_loop(key) else VARIANT_ROWS


def variant(key: tuple, c_row: int, wave_entries: List[tuple],
            gate: int = 2, multiplier: int = 1) -> List[tuple]:
    if key[0] == OVERLAY:
        return list(key[2])
    a, b, tail = key
    noise, delay = wave_entries[c_row - 1], wave_entries[c_row]
    if is_loop(key):
        # `tail` starts at the noise, so `tail[2]` is the row behind the
        # record's own delay (one call, `40:80`): the call a held noise lands
        # on. The loop behind it is phased by the call grid already and must
        # not move, so the noise REPLACES that row, keeping its pitch byte,
        # rather than lengthening the program (a second `C D` put the pitch
        # loop one frame late on every held note).
        return [a, b, noise, delay, (noise[0] & 0xFE, tail[2][1]),
                (GT_WAVE_JUMP, c_row + 3)]
    # The second noise frame has the gate CLOSED, as the original's
    # ($80): the first keeps the record's own (the deliberate $81 of
    # `_drum_tick_noise`), so the gate still closes where the plain
    # program closes it and only the waveform runs on.
    return [a, b, noise, delay, (noise[0] & 0xFE, noise[1]), delay,
            (GT_WAVE_JUMP, c_row + 2)]


def literal_runs(sid: SidFile, det: Detection, ti: int, track: List[int],
                 patterns, lead: int = 0) -> Set[int]:
    """Indices of `track` (one UNPACKED orderlist of the start subtune) that
    sit in a run of one pattern whose plays disagree about which note rows
    the outer gate holds.

    The plays of a repeat count share one pattern cell, so `drum_held_plan`
    cannot spell them apart and declines every row the plays disagree on
    (`visits disagree`: Proteus 130 of its notes, Spellbound 107, International
    Karate 592, Bump_Set_Spike 60). A run the orderlist writes step by step
    has one position a play, so each is spelled for its own clock residue.
    `patterns.pack_repeats(literal=...)` takes this set; the clock is
    `held_rows`' and the rows are the ones a drum record plays (`lead` is
    `build_sng`'s: GT instrument `g` is record `g - lead - 1`), the only ones
    the spelling is about -- a run whose plays differ on no drum row stays a
    repeat count, so a file the plan has nothing to say about keeps its bytes
    (Warhawk). Empty where the plan would not run at all (another subtune, a
    clock the file does not let us read).
    """
    idx = max(0, getattr(sid, "start_song", 1) - 1)
    if not 3 * idx <= ti < 3 * idx + 3:
        return set()
    clock = held_clock(sid, det)
    if clock is None:
        return set()
    gate, skip, outer0, inner0 = clock
    total = sum(len(patterns[p]) // 4 for _pos, p, _k, _t in
                _visits(track, patterns))
    fetched = fetch_frames(outer0, inner0, gate, skip, total + 2)
    if len(fetched) < total + 2:
        return set()
    withheld = withheld_calls(outer0, skip, fetched[-1] + 3)
    drums = {i + lead + 1 for i in _drum_records(
        sid, det, max(0, (len(sid.data) - det.instr_start) // max(
            det.instr_stride, 1)))}
    held_at: Dict[int, Tuple[int, ...]] = {}
    row = 0
    cur = 0
    for pos, p, _k, _t in _visits(track, patterns):
        pat = patterns[p]
        flags: List[int] = []
        for r in range(0, len(pat), 4):
            if pat[r] == GT_END_PATTERN:
                break
            if pat[r + 1]:
                cur = pat[r + 1]
            if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE and cur in drums:
                flags.append(int(is_held(fetched[row], gate, withheld)))
            row += 1
        held_at[pos] = tuple(flags)
    out: Set[int] = set()
    i = 0
    while i < len(track):
        j = i + 1
        while j < len(track) and track[j] == track[i]:
            j += 1
        if (j - i > 1 and track[i] < len(patterns)
                and len({held_at.get(k) for k in range(i, j)}) > 1):
            out.update(range(i, j))
        i = j
    return out


def drum_held_plan(sid: SidFile, det: Detection, tracks, patterns, lead: int,
                   instr_used: int, wave_entries: List[tuple],
                   wave_starts: List[int], log=None, reserve: int = 0,
                   multiplier: int = 1, edits: Optional[dict] = None,
                   extra_starts: Optional[Dict[int, int]] = None
                   ) -> Optional[DrumHeldPlan]:
    """`edits` is `{pattern: {row: (old, new)}}`, the instrument bytes the
    tempo-duty and phase splits write into the patterns LAST, and
    `extra_starts` `{clone number: wavetable start}` of the clones they add.
    A note whose row they rename plays the clone's program, not its record's:
    at a gate above 2 the held program is the clone's (a gate-2 file keeps
    the record's, as it always has)."""
    if not det.effect_drum or det.instr_start is None:
        return None
    held = held_rows(sid, det, tracks, patterns)
    if not held:
        if log:
            log("Drum held noise.........: 0 rows (the start subtune's "
                "clock is not readable)")
        return None
    from ..patterns import MAX_PATTERNS
    declined: Dict[str, int] = {}
    gate = held_clock(sid, det)[0]

    def no(why: str, n: int = 1) -> None:
        declined[why] = declined.get(why, 0) + n

    # Instrument number -> program key, for the drum records of the right shape.
    keys: List[tuple] = []
    key_of: Dict[int, int] = {}
    c_of: Dict[int, int] = {}
    for i in sorted(_drum_records(sid, det, max(instr_used - lead, 0))):
        g = i + lead + 1
        start = wave_starts[g - 1] if 0 < g <= len(wave_starts) else 0
        if gate == 2:
            shaped = _shape(wave_entries, start) if start else None
        else:
            ov = (overlay_key(wave_entries, start, gate, multiplier)
                  if start else None)
            shaped = None if ov is None else (ov, 0)
        if shaped is None:
            continue
        if shaped[0] not in keys:
            keys.append(shaped[0])
            c_of[len(keys)] = shaped[1]
        key_of[g] = keys.index(shaped[0]) + 1
    if gate != 2 and extra_starts:
        # A split's clone of a drum record: its own program (the record's
        # rows in the other phase), held the same way.
        for clone, start in sorted(extra_starts.items()):
            if clone in key_of or not start:
                continue
            ov = overlay_key(wave_entries, start, gate, multiplier)
            if ov is None:
                continue
            if ov not in keys:
                keys.append(ov)
                c_of[len(keys)] = 0
            key_of[clone] = keys.index(ov) + 1
    if not key_of:
        if log:
            log("Drum held noise.........: 0 rows (no drum record has the "
                "attack/noise program shape)")
        return None
    idx = max(0, getattr(sid, "start_song", 1) - 1)
    walked = range(3 * idx, 3 * idx + 3)

    # Per walked position and pattern row: the instrument key it asks for on
    # every visit (0 where it asks for none).
    asks: Dict[tuple, Dict[int, List[int]]] = {}
    for ti in walked:
        cur = 0
        for pos, p, k, _t in _visits(tracks[ti], patterns):
            pat = patterns[p]
            for r in range(0, len(pat), 4):
                if pat[r] == GT_END_PATTERN:
                    break
                if pat[r + 1]:
                    cur = pat[r + 1]
                    if gate != 2 and edits:
                        edit = edits.get(p, {}).get(r // 4)
                        if edit is not None and edit[0] == cur:
                            cur = edit[1]
                if not GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                    continue
                if pat[r + 2] == CMD_TONEPORTA:
                    continue
                cell_free = not pat[r + 2] and not pat[r + 3]
                # The top note reads past the frequency table: its row is
                # pinned to its own program by the past-table split, which
                # needs the command column (`top_note_wave`). A looping
                # record's top-note row is left to it.
                if (pat[r] == GT_LAST_NOTE and cur in key_of
                        and is_loop(keys[key_of[cur] - 1])):
                    cell_free = False
                cell = asks.setdefault((ti, pos), {}).setdefault(r, [])
                if (cell_free and held.get((ti, pos, k, r)) and cur in key_of):
                    cell.append(key_of[cur])
                else:
                    cell.append(0)
                    if held.get((ti, pos, k, r)) and cur in key_of:
                        no("command column taken")
    if not any(any(vs) for rows in asks.values() for vs in rows.values()):
        if log:
            log("Drum held noise.........: 0 rows (no note row is held)")
        return None

    def vote(vs: List[int]) -> int:
        top, n = Counter(vs).most_common(1)[0]
        return top if top and n * 2 > len(vs) else 0

    spell: Dict[tuple, Dict[int, int]] = {
        pp: {r: vote(vs) for r, vs in rows.items()}
        for pp, rows in asks.items()}
    for pp, rows in asks.items():
        for r, vs in rows.items():
            if any(vs) and not spell[pp][r]:
                # Visits of one orderlist position share its pattern cell:
                # a repeat count whose plays land on different clock
                # residues cannot be spelled for the minority (the orderlist
                # is laid before this pass and has no room to unroll).
                no("visits disagree", sum(1 for v in vs if v))
    walked_pos = {(ti, pos) for (ti, pos) in spell}
    outside: Set[int] = set()
    for ti, track in enumerate(tracks):
        for pos, p in _pattern_positions(track, len(patterns)):
            if (ti, pos) not in walked_pos:
                outside.add(p)

    gain: Counter = Counter(g for rows in spell.values()
                            for g in rows.values() if g)
    room = GT_MAX_TABLELEN - len(wave_entries) - reserve
    chosen: List[int] = []
    if gate == 2:
        for key, n in sorted(gain.items(), key=lambda kv: (-kv[1], kv[0])):
            size = variant_rows(keys[key - 1], gate, multiplier)
            if n and room >= size:
                chosen.append(key)
                room -= size
    else:
        # The overlay programs are seven to nine rows each and a table may
        # have room for two: the best SET, not the best first (the biggest
        # program can strand two smaller ones that hold more notes).
        best: Dict[int, Tuple[int, List[int]]] = {0: (0, [])}
        for key, n in sorted(gain.items()):
            size = variant_rows(keys[key - 1], gate, multiplier)
            for used, (score, picks) in sorted(best.items(), reverse=True):
                if used + size <= room and n:
                    got = best.get(used + size)
                    if got is None or score + n > got[0]:
                        best[used + size] = (score + n, picks + [key])
        top = max(best.values(), key=lambda v: (v[0], -len(v[1])))
        chosen = list(top[1])
        room -= sum(variant_rows(keys[k - 1], gate, multiplier)
                    for k in chosen)
    if not chosen:
        no("no wavetable room")
        return None

    while chosen:
        plan = _group(spell, tracks, set(chosen), outside)
        if len(patterns) + plan[2] <= MAX_PATTERNS - PATTERN_RESERVE:
            break
        chosen.remove(min(chosen, key=lambda k: (gain[k], -k)))
    else:
        no("no pattern room")
        return None
    out_patterns, out_tracks, copies, flagged, sources = _apply(
        plan, patterns, tracks, wave_entries, chosen, keys, gate, multiplier)
    entries: List[tuple] = []
    for key in chosen:
        entries += variant(keys[key - 1], c_of[key], wave_entries, gate,
                           multiplier)
    if log:
        log(f"Drum held noise.........: {flagged} note row(s) play a "
            f"two-frame noise program ({len(chosen)} of {len(keys)} "
            f"program(s), {len(entries)} wavetable row(s) after {len(wave_entries)}); {copies} pattern "
            f"cop(ies)" + (f"; declined {declined}" if declined else ""))
    return DrumHeldPlan(out_patterns, out_tracks, entries, flagged, chosen,
                        copies, declined, sources)


def _group(spell, tracks, chosen: Set[int], outside: Set[int]):
    """(groups per pattern, ..., copies): positions that agree on every note
    row of a pattern share a spelling; only rows asking for a CHOSEN
    program count as asking."""
    by_pat: Dict[int, List[tuple]] = {}
    for (ti, pos) in sorted(spell):
        by_pat.setdefault(tracks[ti][pos], []).append((ti, pos))
    plan: Dict[int, list] = {}
    copies = 0
    for p, members in by_pat.items():
        vecs = []
        for pp in members:
            vec = {r: (g if g in chosen else 0)
                   for r, g in spell[pp].items()}
            vecs.append((pp, vec))
        vecs.sort(key=lambda x: (-sum(1 for g in x[1].values() if g), x[0]))
        groups: List[Tuple[Dict[int, int], List[tuple]]] = []
        for pp, vec in vecs:
            for gv, gm in groups:
                if all(gv.get(r, g) == g for r, g in vec.items()):
                    gv.update(vec)
                    gm.append(pp)
                    break
            else:
                groups.append((dict(vec), [pp]))
        flagged = [(gv, gm) for gv, gm in groups if any(gv.values())]
        zero = [(gv, gm) for gv, gm in groups if not any(gv.values())]
        if not flagged:
            continue
        in_place = not zero and p not in outside
        plan[p] = [(gv, gm, in_place and i == 0)
                   for i, (gv, gm) in enumerate(flagged)]
        copies += len(flagged) - (1 if in_place else 0)
    return plan, by_pat, copies


def _apply(plan, patterns, tracks, wave_entries, chosen, keys, gate=2,
           multiplier=1):
    groups, _by_pat, _copies = plan
    out_p = [list(p) for p in patterns]
    out_t = [list(t) for t in tracks]
    # Pointers: each chosen program's copy, in the order `entries` lays them.
    ptr_of: Dict[int, int] = {}
    at = len(wave_entries) + 1
    for key in chosen:
        ptr_of[key] = at
        at += variant_rows(keys[key - 1], gate, multiplier)
    flagged = 0
    copies = 0
    sources: Dict[int, int] = {}
    for p in sorted(groups):
        for gv, gm, in_place in groups[p]:
            if in_place:
                target = p
            else:
                out_p.append(list(patterns[p]))
                target = len(out_p) - 1
                sources[target] = p
                copies += 1
                for ti, pos in gm:
                    out_t[ti][pos] = target
            for r, g in gv.items():
                if g:
                    out_p[target][r + 2] = CMD_SETWAVEPTR
                    out_p[target][r + 3] = ptr_of[g]
                    flagged += 1
    return out_p, out_t, copies, flagged, sources
