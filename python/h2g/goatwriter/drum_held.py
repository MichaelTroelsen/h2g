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


def held_clock(sid: SidFile, det: Detection
               ) -> Optional[Tuple[int, int, int, int]]:
    """(gate, skip, outer start, inner start) of the start subtune, or None.

    Only a speed gate of two calls: the fetch call is followed by exactly one
    call the drum block can write on, and that is the rule's whole shape.
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
    if gate != 2 or not skip:
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
                out[(ti, pos, k, r)] = (fetched[row] + 2) in withheld
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
    rather than a stop (`FF:00`)."""
    return key[2][-1][1] != 0


def variant_rows(key: tuple) -> int:
    return LOOP_VARIANT_ROWS if is_loop(key) else VARIANT_ROWS


def variant(key: tuple, c_row: int, wave_entries: List[tuple]) -> List[tuple]:
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


def drum_held_plan(sid: SidFile, det: Detection, tracks, patterns, lead: int,
                   instr_used: int, wave_entries: List[tuple],
                   wave_starts: List[int], log=None, reserve: int = 0
                   ) -> Optional[DrumHeldPlan]:
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

    def no(why: str, n: int = 1) -> None:
        declined[why] = declined.get(why, 0) + n

    # Instrument number -> program key, for the drum records of the right shape.
    keys: List[tuple] = []
    key_of: Dict[int, int] = {}
    c_of: Dict[int, int] = {}
    for i in sorted(_drum_records(sid, det, max(instr_used - lead, 0))):
        g = i + lead + 1
        start = wave_starts[g - 1] if 0 < g <= len(wave_starts) else 0
        shaped = _shape(wave_entries, start) if start else None
        if shaped is None:
            continue
        if shaped[0] not in keys:
            keys.append(shaped[0])
            c_of[len(keys)] = shaped[1]
        key_of[g] = keys.index(shaped[0]) + 1
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
    for key, n in sorted(gain.items(), key=lambda kv: (-kv[1], kv[0])):
        size = variant_rows(keys[key - 1])
        if n and room >= size:
            chosen.append(key)
            room -= size
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
        plan, patterns, tracks, wave_entries, chosen, keys)
    entries: List[tuple] = []
    for key in chosen:
        entries += variant(keys[key - 1], c_of[key], wave_entries)
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


def _apply(plan, patterns, tracks, wave_entries, chosen, keys):
    groups, _by_pat, _copies = plan
    out_p = [list(p) for p in patterns]
    out_t = [list(t) for t in tracks]
    # Pointers: each chosen program's copy, in the order `entries` lays them.
    ptr_of: Dict[int, int] = {}
    at = len(wave_entries) + 1
    for key in chosen:
        ptr_of[key] = at
        at += variant_rows(keys[key - 1])
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
