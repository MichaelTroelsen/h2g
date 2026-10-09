"""Bit $02's chromatic rise under the arpeggio, as a pattern-side stair.

A record setting the rise (bit $02) AND the nibble arpeggio (bit $04) runs
both blocks every working frame, rise first (Warhawk $13A2 then $13CD,
Spellbound $E2FF then $E326):

    LDA effect / AND #$02 / BEQ out
    LDA counter / AND #$03 / BNE out     ; one step in four
    INC note,X                           ; the voice's note index
    LDA note,X / ASL / TAY / LDA freqtbl,Y ... STA $D400/$D401

and the arpeggio then reads the note index the rise has just raised, so the
pair CLIMBS together: Spellbound $11 (effect $56) plays `+0 +0 -5 +0 -4 +1
-4 +1 -3 +2 ...`, a semitone every four counter steps, +60 by the end of
its 281 frames. The wavetable cannot carry it (`goatwriter/wavetable.py`,
the EMITTER LIMIT note beside the rise branch): a note entry sets the
frequency from the PATTERN note, so no portamento survives the arpeggio's
next entry, and unrolled the stair is four entries a semitone.

**The climb goes on the pattern side, one note per semitone, spelled so
that it moves nothing but the note.** A row with a note and `CMD_TONEPORTA`
skips the note init (player.s `mt_newnoteinit`: `cmp #TONEPORTA / beq
mt_nonewnoteinit`, ahead of the wave pointer load; gplay.c:354) and the
gate-off at the fetch (player.s `mt_normalnote` `beq mt_rest`, gplay.c:928)
but still stores the note (`sta mt_chnnote,x`, gplay.c:350), so the
instrument's program runs on and its next note entry is relative to the new
note (player.s `mt_wavefreq` `adc mt_chnnote,x`, gplay.c:719-720). Speed
`$00` would be the tie, which ALSO pulls the frequency to the note on every
call the program does not set one (player.s `mt_effect_3_found`, gplay.c:810
`!cptr->cmddata`) -- the arpeggio's hold calls, so the low half would sound
the base note. A speed-table row of `$0000` instead: the toneportamento
then moves the frequency by zero (player.s `mt_effect_3_up`/`_down` add or
subtract `mt_temp1/2`; gplay.c:827/837 `freq +=/-= speed`), and only the
program's own note entries are heard. GTS5 only: a GTS2 file stores no
speed table, and its loader reads the column as the speed itself, where 0
is the tie (gsong.c:315-317, gtable.c:862 `if (!data) return -1`).

**Where the steps fall.** The counter steps once a working frame (the call
that passes the outer gate; `fixed_arp_counter_base`), so on the k-th working
frame after a note's fetch it reads `base + first + a * frames + k`, where
`a` is the note's row in the lap and `frames` the subtune's row in working
frames -- the clock `fixed_arp_phases` walks. A step lands on every frame
where that is a multiple of four, EXCEPT a frame on which the voice fetches
an event: the fetch tick runs no effect (Spellbound $E086 `JMP $E367`), so
Spellbound's 128-row note, which re-fetches a gate-off event every 32 rows
on a step frame, climbs 60 semitones where 63 steps' worth of frames pass.
A step `o` working frames into a row goes on that row (early by `o`) or on
the next (late by `frames - o`), whichever is nearer, the earlier on a tie.

A step goes in where every play of its orderlist position -- one lap and
the restart's -- asks for the same note, and a pattern the positions
disagree on is copied (`rise_stair_plan`). The step is written absolute
(the note's own plus the steps so far), so a step that cannot be placed
costs only the rows until the next one. A climb stops at Goattracker's top
pattern note (`GT_LAST_NOTE`): Thrust's `$17` notes stop at +35 of the
original's 48 and 52.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..detect import Detection, _effect_byte_address
from ..search import search_file
from ..sidfile import SidFile
from .constants import (CMD_TONEPORTA, FIXED_ARP_RESET_WINDOW, FORMAT_GTS5,
                        GT_FIRST_NOTE, GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST,
                        PACKED_PATTERN_LIMIT, _SONG_MAX_PATTERNS)
from . import arpeggio as _gw_arpeggio
from . import pulse as _gw_pulse
from . import tempo as _gw_tempo

# `LDA counter / AND #$03 / BNE out`: one rise in four counter steps.
RISE_STEP_MASK = 0x03
# The speed-table row a step's toneportamento names: a speed of zero.
RISE_STAIR_SPEED = (0x00, 0x00)
# The rise block, both spellings of its increment (`detect._find_effect_
# routines`): `INC abs,X` (`FE`, Warhawk) and `INC zp,X` (`F6`, Spellbound).
RISE_BLOCK_INCREMENTS = ("FE", "F6")


@dataclass(frozen=True)
class RiseBlock:
    """The rise block's file offset and the counter it divides."""
    at: int
    counter: int
    zp: bool


def rise_block(sid: SidFile, det: Detection) -> Optional[RiseBlock]:
    """The rise block and its counter, or None.

    The same search `detect._find_effect_routines` makes, with the counter
    read off the block's second load, and only where the arpeggio block
    (`{effect} 29 04 F0 ?? {effect} 4A 4A 4A 4A 8D ?? ?? A0 02 C9 0C F0 02
    A0 01 8C ?? ??`, Warhawk $13CD) divides the SAME counter -- the stair is
    in the counter's phase only if the alternation is too.
    """
    found = _effect_byte_address(sid, det)
    if not found:
        return None
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    any_load = "A5 ??" if zp else "AD ?? ??"
    width = 2 if zp else 3
    data = sid.data
    for inc in RISE_BLOCK_INCREMENTS:
        at = search_file(data,
                         f"{load} 29 02 F0 ?? {any_load} 29 03 D0 ?? {inc}")
        if at < 1:
            continue
        op = at + width + 4 + 1
        counter = data[op] if zp else data[op] | data[op + 1] << 8
        ctr_load = (f"A5 {counter:02X}" if zp
                    else f"AD {counter & 0xFF:02X} {counter >> 8:02X}")
        arp = search_file(data, f"{load} 29 04 F0 ?? {load} 4A 4A 4A 4A 8D "
                          f"?? ?? A0 02 C9 0C F0 02 A0 01 8C ?? ?? "
                          f"{ctr_load} 29")
        if arp < 1:
            return None
        return RiseBlock(at=at, counter=counter, zp=zp)
    return None


def rise_counter_base(sid: SidFile, block: RiseBlock) -> Optional[int]:
    """What the counter reads on working frame `k`, less `k`.

    `frame_counter_base` for an absolute counter. A zero-page one has the
    same two shapes in `INC zp` / `LDA #0 / STA zp` (Spellbound $E01B
    `INC $C1` ... $E024 `LDA #$00 / STA $C1`, the new-song reset): base 0
    where the reset follows the increment, None where it does not -- a
    zero-page byte is not in the file image to read a start from.
    """
    if not block.zp:
        return _gw_arpeggio.frame_counter_base(sid, block.counter)
    data = sid.data
    inc = search_file(data, f"E6 {block.counter:02X}")
    if inc < 1:
        return None
    reset = data.find(bytes([0xA9, 0x00, 0x85, block.counter]), inc,
                      inc + FIXED_ARP_RESET_WINDOW)
    return 0 if reset >= 0 else None


def rise_arp_records(sid: SidFile, det: Detection, records: int) -> List[int]:
    """The records whose program is the arpeggio's AND that rise.

    Bits $02 and $04 both set, with a nonzero interval nibble: a zero nibble
    is not emitted as an arpeggio at all (`_wavetable_entries`, `arp_note ==
    0`), so its program has no note entry for a stair to move. A drum bit
    beside them is fine -- that record keeps the arpeggio shape and only
    gains the noise tick.
    """
    out = []
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(sid.data):
            break
        fx = sid.data[base + 7]
        if fx & 0x06 == 0x06 and fx >> 4:
            out.append(i)
    return out


def stair_steps(counter: int, span: int,
                fetches: frozenset) -> List[Tuple[int, int]]:
    """[(working frame from the fetch, semitones climbed after it)].

    `counter` is what the counter reads on the note's fetch frame, `span`
    the note's length in working frames, `fetches` the working frames
    (from the note's) on which the voice fetches a later event of the same
    note -- a gate-off, say -- and so runs no effect.
    """
    out = []
    k = 0
    for w in range(1, span):
        if (counter + w) & RISE_STEP_MASK or w in fetches:
            continue
        k += 1
        out.append((w, k))
    return out


def step_rows(w: int, frames: int) -> List[int]:
    """The rows (from the note's) a step on working frame `w` may go on,
    nearest first: its own where it starts the row, else its own (early by
    the offset) and the next (late by the rest), the earlier on a tie."""
    j, o = divmod(w, frames)
    if o == 0:
        return [j, j + 1]
    return [j, j + 1] if o <= frames - o else [j + 1, j]


def zero_speed_index(speed_table: List[tuple]) -> Optional[int]:
    """The 1-based speed-table row holding `RISE_STAIR_SPEED`, appended
    where none does; None where the table is full."""
    if RISE_STAIR_SPEED in speed_table:
        return speed_table.index(RISE_STAIR_SPEED) + 1
    if len(speed_table) >= GT_MAX_TABLELEN:
        return None
    speed_table.append(RISE_STAIR_SPEED)
    return len(speed_table)


def _played_rows(track: List[int], count: int, patterns: List[List[int]]):
    """(visit, position, pattern, row, transpose) for every row a voice
    plays: one lap, then the restart's lap once more -- the walk
    `rest_reseed._rest_reseed_plan` and `_lapped_tracks` make, so a position
    the loop replays in another counter phase is asked twice. `visit`
    numbers each play of a position (a repeat is that many visits)."""
    end = track.index(0xFF) if 0xFF in track else len(track)
    restart = track[end + 1] if end + 1 < len(track) else None
    laps = [range(0, end)]
    if restart is not None and restart < end:
        laps.append(range(restart, end))
    transpose = 0
    visit = 0
    for lap in laps:
        repeat = 1
        for pos in lap:
            b = track[pos]
            if 0xE0 <= b < 0xFF:
                transpose = b - 0xF0
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b >= count:
                repeat = 1
                continue
            pat = patterns[b]
            for _ in range(repeat):
                visit += 1
                for k in range(0, len(pat) - 3, 4):
                    if pat[k] == 0xFF:
                        break
                    yield visit, pos, b, k // 4, transpose
            repeat = 1


def rise_stair_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                    patterns: List[List[int]], record_of: Dict[int, int],
                    fmt: str, speed_table: List[tuple],
                    log=None) -> Optional[Tuple[List[List[int]],
                                                List[List[int]]]]:
    """(patterns, tracks) with every rise+arp note's stair written in, or
    None where nothing is.

    `record_of` maps each Goattracker instrument number that plays a
    record's own arpeggio program -- the record's, and its clones' -- to
    the 0-based record. A step goes in the pattern every play of an
    orderlist position agrees on; where two positions playing one pattern
    want different steps (or one wants none: the pattern is also played
    outside the note), each other want gets a copy of the pattern, numbered
    past the table up to `_SONG_MAX_PATTERNS`, and its positions are
    repointed -- same orderlist length, so the caller rewrites the bytes in
    place. Everything declined is counted in the log line.
    """
    def say(msg: str) -> None:
        if log:
            log(f"Rise stair (bit $02)....: {msg}")

    if not (det.effect_rise and det.effect_arp) or det.arp_fixed_up:
        return None
    rising = set(rise_arp_records(sid, det, det.instr_used))
    numbers = {g for g, rec in record_of.items() if rec in rising}
    if not numbers:
        return None
    if fmt != FORMAT_GTS5:
        say(f"{len(rising)} record(s), not emitted (GTS2 stores no speed "
            "table)")
        return None
    block = rise_block(sid, det)
    base = rise_counter_base(sid, block) if block is not None else None
    first = _gw_arpeggio.fixed_arp_first_fetch(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if block is None or base is None or first is None or speeds is None:
        say("counter or row clock not read, not emitted")
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None                      # a split subtune shifted the numbering

    declined: Dict[str, int] = {}
    notes = 0
    top = 0
    played: set = set()
    plan: Dict[Tuple[int, int], frozenset] = {}

    def decline(why: str, n: int = 1) -> None:
        declined[why] = declined.get(why, 0) + n

    def declines() -> str:
        return ("; declined: " + ", ".join(f"{n} {w}"
                                           for w, n in declined.items())
                if declined else "")

    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        rows = list(_played_rows(track, len(patterns), patterns))
        wants: Dict[int, Dict[int, int]] = {}
        where: Dict[int, int] = {}
        for vis, pos, _p, _r, _t in rows:
            wants.setdefault(vis, {})
            where[vis] = pos
        current = 0
        for a, (_vis, _pos, p, r, transpose) in enumerate(rows):
            note, instr = patterns[p][4 * r], patterns[p][4 * r + 1]
            if instr:
                current = instr
            if not (GT_FIRST_NOTE <= note <= GT_LAST_NOTE):
                continue
            if current not in numbers:
                continue
            if not frames:
                decline("subtune clock not read")
                continue
            record = record_of[current]
            end = len(rows)
            for e in range(a + 1, len(rows)):
                ep, er = rows[e][2], rows[e][3]
                en, ei = patterns[ep][4 * er], patterns[ep][4 * er + 1]
                if (GT_FIRST_NOTE <= en <= GT_LAST_NOTE
                        or (ei and record_of.get(ei) != record)):
                    end = e
                    break
            fetches = frozenset(
                (e - a) * frames for e in range(a + 1, end)
                if patterns[rows[e][2]][4 * rows[e][3]] != GT_REST)
            counter = base + first + a * frames
            absolute = note + transpose
            notes += 1
            want: Dict[int, int] = {}
            for w, k in stair_steps(counter, (end - a) * frames, fetches):
                if absolute + k > GT_LAST_NOTE:
                    decline("past the top note")
                    break
                for j in step_rows(w, frames):
                    if not 1 <= j < end - a:
                        continue
                    sp, sr, st = rows[a + j][2:]
                    cell = patterns[sp][4 * sr:4 * sr + 4]
                    if cell[0] != GT_REST or any(cell[1:]):
                        continue
                    if not GT_FIRST_NOTE <= absolute + k - st <= GT_LAST_NOTE:
                        continue
                    want[j] = max(want.get(j, 0), k)
                    break
                else:
                    decline("no free row")
            for j, k in want.items():
                vis, _pos, _sp, sr, st = rows[a + j]
                wants[vis][sr] = absolute + k - st
                top = max(top, k)
            if want:
                played.add(current)
        for vis, want in wants.items():
            key = (ti, where[vis])
            got = frozenset(want.items())
            if key in plan and plan[key] != got:
                decline("disagreeing visit", len(plan[key] ^ got))
                got = plan[key] & got
            plan[key] = got

    groups: Dict[int, Dict[frozenset, list]] = {}
    for (ti, pos), want in plan.items():
        groups.setdefault(tracks[ti][pos], {}).setdefault(want, []).append(
            (ti, pos))
    if not any(w for by_want in groups.values() for w in by_want):
        if notes:
            say(f"{notes} note(s), no step row taken{declines()}")
        return None
    snapshot = list(speed_table)
    index = zero_speed_index(speed_table)
    if index is None:
        say("speed table full, not emitted")
        return None

    def patched(b: int, want: frozenset) -> Optional[List[int]]:
        rows_ = list(patterns[b])
        for row, value in want:
            rows_[4 * row] = value
            rows_[4 * row + 2] = CMD_TONEPORTA
            rows_[4 * row + 3] = index
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(rows_))
                > PACKED_PATTERN_LIMIT):
            return None
        return rows_

    out_patterns = [list(pat) for pat in patterns]
    out_tracks = [list(t) for t in tracks]
    written = copies = 0
    for b in sorted(groups):
        by_want = groups[b]
        wanted = [w for w in by_want if w]
        if not wanted:
            continue
        # The pattern keeps the positions that want nothing, or else the
        # largest group; every other group gets a copy of its own.
        if frozenset() in by_want:
            stays = frozenset()
        else:
            stays = max(wanted, key=lambda w: (len(by_want[w]), sorted(w)))
            rows_ = patched(b, stays)
            if rows_ is None:
                decline("pattern past the packed limit", len(stays))
            else:
                out_patterns[b] = rows_
                written += len(stays)
        for want in sorted((w for w in wanted if w != stays), key=sorted):
            if len(out_patterns) >= _SONG_MAX_PATTERNS:
                decline("pattern table full", len(want))
                continue
            rows_ = patched(b, want)
            if rows_ is None:
                decline("pattern past the packed limit", len(want))
                continue
            out_patterns.append(rows_)
            copies += 1
            for ti, pos in by_want[want]:
                out_tracks[ti][pos] = len(out_patterns) - 1
            written += len(want)
    if not written:
        speed_table[:] = snapshot
        say(f"{notes} note(s), every step row declined{declines()}")
        return None
    say(f"{written} step row(s) over {notes} note(s) on instrument(s) "
        f"{sorted(played)}, up to +{top} semitone(s), {copies} pattern "
        f"cop(ies), CMD_TONEPORTA {index:02X} (speed $0000){declines()}")
    return out_patterns, out_tracks


