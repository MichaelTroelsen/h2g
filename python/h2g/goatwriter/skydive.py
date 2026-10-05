"""Bit $02's skydive (detect._find_skydive) as a CMD_SETWAVEPTR program.

The block runs in the last `last_ticks` ticks of a note at least
`min_length` long, so where it starts is a property of the NOTE's length,
which a per-instrument wavetable cannot know. The row it starts on can: the
converter emits one row per tick, so the window opens `dur - last_ticks + 1`
rows after the note row, and a `CMD_SETWAVEPTR` there points the voice at a
program that does what the block does from that frame on.

What the block does (Hunter_Patrol $A2C9): on every frame whose play-entry
counter is odd it stores `savehi` into $D401 and decrements it, so the high
byte reads the note's own, then one less, two less ... down to 1. The low
byte is whatever wrote it last. Where the record's vibrato rewrites the whole
frequency every frame ($A1B4, any nonzero vibrato byte), the other frames are
back on the vibrato and the voice ALTERNATES between the two; siddump of the
original, Hunter_Patrol voice 1 frames 298-324: 6813 69DA 67A1 6AA1 66DA 6913
654C 684C ... 5BA1. Where nothing rewrites it, the fall holds between steps.

A Goattracker portamento is linear in frequency, and one high-byte step is
exactly `$0100`, so step k of the fall is `$100 * k` below the frequency the
program found -- a speed-table entry `(k, $00)`. The alternating program
spends two wavetable steps per pair of frames, `F2 k` down and `F1 k` back
up; a wavetable command runs instead of the voice's vibrato on its frame
(gplay.c:528-690, player.s mt_execwavecmd), so the vibrato is held where the
program found it for the length of the fall, which is the approximation this
makes. The holding program steps `F2 1` on each fall frame and leaves the
frame between to a no-op.

Emitted only at -S1, GTS5 (the wavetable names speed-table rows, which a GTS2
file does not store), with no outer gate, and only on a row whose every play
asks for the same program and whose command column can be taken without
losing anything; everything declined is counted in the log line.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile, find_freq_table
from .constants import (CMD_SETWAVEPTR, FORMAT_GTS5, GT_FIRST_NOTE,
                        GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        GT_WAVE_NO_NOTE, PACKED_PATTERN_LIMIT,
                        WAVE_MAX_DELAY, WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from .primitives import _note_freq
from . import arpeggio as _gw_arpeggio
from . import pulse as _gw_pulse
from . import tempo as _gw_tempo

# Commands that persist from row to row (gplay.c:404-422 keeps `command`
# across a CMD_SETWAVEPTR row), so a window row carrying the same one as the
# row before it loses nothing when the pointer takes its column.
SKYDIVE_PERSISTENT_COMMANDS = frozenset({0, 1, 2, 4})
# A Hubbard note's duration is the low five bits of its note byte.
SKYDIVE_MAX_DURATION = 0x1F
# Wavetable left side `$00`: "leave waveform unchanged" (readme.txt:787), a
# one-frame step whose `$80` right side leaves the vibrato to run.
SKYDIVE_NOOP = 0x00
# Wavetable right side `$00`: relative note +0, the note's own frequency.
SKYDIVE_NOTE_BASE = 0x00


@dataclass(frozen=True)
class SkydivePlan:
    """The finished patterns and the program block to append to the wavetable."""
    patterns: List[List[int]]
    entries: List[Tuple[int, int]]


def skydive_records(sid: SidFile, det: Detection,
                    records: int) -> Dict[int, bool]:
    """{record index: whether its fall alternates with the vibrato}.

    A record sets bit $02 and nothing that rewrites the frequency after the
    block on the same frame: the fixed octave (bit $04, Hunter_Patrol $A2F5
    writes $D400/$D401 from the note table on every frame) and the drum (bit
    $01, which steps the same `savehi`) are both excluded. It alternates
    where its vibrato byte is nonzero -- the block that rewrites the whole
    frequency every frame and is skipped on a zero byte ($A14C `BEQ $A1C3`).
    """
    vib = (det.triangle_vibrato if det.triangle_vibrato is not None
           else det.vibrato_offset)
    out: Dict[int, bool] = {}
    for i in range(records):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(sid.data):
            break
        fx = sid.data[base + 7]
        if not fx & 0x02:
            continue
        if (fx & 0x04 and det.effect_arp) or (fx & 0x01 and det.effect_drum):
            continue
        out[i] = bool(vib is not None and sid.data[base + vib])
    return out


def _high_byte(sid: SidFile, note: int) -> int:
    """The player's frequency high byte for Goattracker note index `note`."""
    table = find_freq_table(sid)
    if table is not None:
        index = note - table.shift
        if 0 <= index < table.length:
            at = sid.to_offset(table.addr) + 2 * index
            if 0 <= at and at + 1 < len(sid.data):
                return sid.data[at + 1]
    return _note_freq(note) >> 8


def skydive_writes(window: int, phase: int, high: int) -> int:
    """How many stores the block makes in a window of `window` frames.

    The first is on frame `phase` and every other frame after it; the
    `BEQ` on `savehi` stops them once the byte has reached zero, after
    `high` stores (the last one stores 1).
    """
    return min(max(0, (window - phase + 1) // 2), high)


def skydive_program(phase: int, writes: int, alternates: bool,
                    speed_index) -> List[Tuple[int, int]]:
    """The wavetable steps for one window, from the frame its row starts.

    Store k (k = 0 .. writes-1) falls on frame `phase + 2k` and is `$100 * k`
    below the note's own frequency; store 0 is that frequency, so the
    program's first movement is store 1. `speed_index(k)` names the
    speed-table row holding `(k, $00)`. Runs of frames on which nothing
    moves are one delay step each (`value + 1` frames, gplay.c:697-704).

    **An alternating program first puts the voice back on its note.** The
    block stores `savehi`, the note's own high byte, whatever the vibrato
    did to the frequency; a fall measured from where the vibrato happened
    to be sat up to two steps high (Hunter_Patrol: `$69DF` against the
    note's `$684C`, every store one high byte above the original's). So
    every frame up to store 1 is a relative-note-0 step (`$00 $00`: the
    waveform left alone, the frequency set to the note's, gplay.c:719-725),
    and the pairs that follow move from there.
    """
    frames: List[Optional[Tuple[int, int]]] = []
    last = phase + 2 * (writes - 1)
    for t in range(last + (2 if alternates else 1)):
        k, odd = divmod(t - phase, 2)
        if t >= phase and not odd and k >= 1:
            frames.append((WAVECMD_PORTADOWN,
                           speed_index(k if alternates else 1)))
        elif alternates and t > phase and odd and k >= 1:
            frames.append((WAVECMD_PORTAUP, speed_index(k)))
        elif alternates and t < phase + 2:
            frames.append((SKYDIVE_NOOP, SKYDIVE_NOTE_BASE))
        else:
            frames.append(None)
    out: List[Tuple[int, int]] = []
    run = 0
    for step in frames + [()]:
        if step is None:
            run += 1
            continue
        while run:
            n = min(run, WAVE_MAX_DELAY + 1)
            out.append((SKYDIVE_NOOP + n - 1, GT_WAVE_NO_NOTE))
            run -= n
        if step:
            out.append(step)
    out.append((GT_WAVE_JUMP, 0x00))
    return out


def _lap_rows(track: List[int], patterns: List[List[int]]):
    """(pattern, row, transpose) for every row one lap of `track` plays."""
    transpose, repeat, operand = 0, 1, False
    for b in track:
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
        pat = patterns[b]
        for _ in range(repeat):
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:
                    break
                yield b, r // 4, transpose
        repeat = 1


def skydive_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                 patterns: List[List[int]], lead: int, instr_used: int,
                 fmt: str, multiplier: int, gate_skip: Optional[int],
                 speed_table: List[tuple], wave_used: int,
                 no_test_restart: bool = False,
                 real_firstwave: tuple = (),
                 log=None) -> Optional[SkydivePlan]:
    """The rows that open a skydive window, pointed at their programs.

    Walks one lap of every orderlist in play order, the instrument column
    sticky. A note on a skydive record lasts until the next row that is not
    a bare rest -- the next event -- so its Hubbard duration is that many
    rows less one; the window opens `dur - last_ticks + 1` rows in. The
    play-entry counter's parity on that row's first frame
    (`frame_counter_base`, `fixed_arp_first_fetch`, the row length) says
    whether the first store is on its first frame or its second.

    A (pattern, row) is taken only where EVERY time the orderlists play it
    is a window opening asking for the same program, and its command column
    persists the row before's; a pattern reached under another instrument,
    or on the other parity, keeps its bytes. None where nothing is taken.
    """
    sd = det.skydive
    if sd is None:
        return None

    def say(msg: str) -> None:
        if log:
            log(f"Skydive (bit $02).......: {msg}")

    records = skydive_records(sid, det, max(instr_used - lead, 0))
    if not records:
        return None
    why = [w for w, bad in (("GTS2 stores no speed table", fmt != FORMAT_GTS5),
                            (f"-S{multiplier}", multiplier != 1),
                            ("outer gate", bool(gate_skip))) if bad]
    if why:
        say(f"{len(records)} record(s), not emitted ({', '.join(why)})")
        return None
    base = _gw_arpeggio.frame_counter_base(sid, sd.counter)
    first = _gw_arpeggio.fixed_arp_first_fetch(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if base is None or first is None or speeds is None:
        say("counter or row clock not read, not emitted")
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None                      # a split subtune shifted the numbering
    by_number = {i + lead + 1: alt for i, alt in records.items()}

    plays: Dict[tuple, int] = {}
    asks: Dict[tuple, List[tuple]] = {}
    declined = {"opens on the note row": 0, "too few stores": 0}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None:
            continue
        rows = list(_lap_rows(track, patterns))
        for p, r, _t in rows:
            plays[(p, r)] = plays.get((p, r), 0) + 1
        current = 0
        for a, (p, r, transpose) in enumerate(rows):
            note, instr = patterns[p][4 * r], patterns[p][4 * r + 1]
            if instr:
                current = instr
            if not (GT_FIRST_NOTE <= note <= GT_LAST_NOTE):
                continue
            if current not in by_number:
                continue
            end = next((e for e in range(a + 1, len(rows))
                        if patterns[rows[e][0]][4 * rows[e][1]] != GT_REST
                        or patterns[rows[e][0]][4 * rows[e][1] + 1]), None)
            if end is None:
                continue
            dur = end - a - 1
            if dur > SKYDIVE_MAX_DURATION or dur < sd.min_length:
                continue
            j0 = dur - sd.last_ticks + 1
            if j0 <= 0:
                declined["opens on the note row"] += 1
                continue
            at = a + j0
            phase = 0 if (base + first + at * frames) & 1 else 1
            high = _high_byte(sid, note - GT_FIRST_NOTE + transpose)
            writes = skydive_writes((end - at) * frames, phase, high)
            if writes < 2:
                declined["too few stores"] += 1
                continue
            wp, wr, _ = rows[at]
            pp, pr, _ = rows[at - 1]
            cell = tuple(patterns[wp][4 * wr + 2:4 * wr + 4])
            safe = (cell == tuple(patterns[pp][4 * pr + 2:4 * pr + 4])
                    and cell[0] in SKYDIVE_PERSISTENT_COMMANDS)
            # The program counts from the row's first call; the original's
            # tick frame is one frame later on a record whose attack opens
            # on the test-bit lead (`_first_frame_lead`), because the
            # converter lines the ATTACK up with the original's and this
            # window is that many frames past it.
            lag = 0 if no_test_restart or current in real_firstwave else 1
            asks.setdefault((wp, wr), []).append(
                (phase + lag, writes, by_number[current], safe))

    taken: Dict[tuple, tuple] = {}
    mixed = 0
    for key, wants in asks.items():
        if (len(wants) == plays.get(key, 0) and len(set(wants)) == 1
                and wants[0][3]):
            taken[key] = wants[0][:3]
        else:
            mixed += 1
    if not taken:
        say(f"{sum(len(w) for w in asks.values())} window(s), none taken "
            f"({mixed} row(s) mixed or occupied)")
        return None

    table = speed_table

    def speed_index(k: int) -> int:
        entry = (k, 0x00)
        if entry not in table:
            if len(table) >= GT_MAX_TABLELEN:
                raise OverflowError
            table.append(entry)
        return table.index(entry) + 1

    snapshot = list(table)
    entries: List[Tuple[int, int]] = []
    starts: Dict[tuple, int] = {}
    try:
        for want in sorted(set(taken.values())):
            starts[want] = wave_used + len(entries) + 1
            entries += skydive_program(*want, speed_index)
    except OverflowError:
        table[:] = snapshot
        say("speed table full, not emitted")
        return None
    if wave_used + len(entries) > GT_MAX_TABLELEN:
        table[:] = snapshot
        say(f"{len(entries)} wavetable step(s) past MAX_TABLELEN, not emitted")
        return None

    out = [list(pat) for pat in patterns]
    edited = 0
    for (p, r), want in sorted(taken.items()):
        trial = list(out[p])
        trial[4 * r + 2] = CMD_SETWAVEPTR
        trial[4 * r + 3] = starts[want]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            continue
        out[p] = trial
        edited += 1
    if not edited:
        table[:] = snapshot
        return None
    skipped = ", ".join(f"{n} {why}" for why, n in declined.items() if n)
    say(f"{edited} window row(s) on {len(records)} record(s) "
        f"{sorted(records)}, {len(starts)} program(s) "
        f"{sorted(starts)}, {len(entries)} wavetable step(s)"
        + (f"; {mixed} row(s) mixed or occupied" if mixed else "")
        + (f"; declined: {skipped}" if skipped else ""))
    return SkydivePlan(patterns=out, entries=entries)
