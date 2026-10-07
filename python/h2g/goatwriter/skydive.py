"""Bit $02's skydive (detect._find_skydive) as a CMD_SETWAVEPTR program.

The block runs in the last `last_ticks` ticks of a note at least
`min_length` long, so where it starts is a property of the NOTE's length,
which a per-instrument wavetable cannot know. The row it starts on can: the
converter emits one row per tick, so the window opens `dur - last_ticks + 1`
rows after the note row, and a `CMD_SETWAVEPTR` there points the voice at a
program that does what the block does from that frame on. Where that is not
a row after the note (`dur < last_ticks`), the pointer goes on the note row
itself and its program carries the instrument's own wave program
(`skydive_note_row_program`).

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

Emitted only in GTS5 (the wavetable names speed-table rows, which a GTS2
file does not store), with no outer gate, and only on a row whose every play
asks for the same program and whose command column can be taken without
losing anything; everything declined is counted in the log line. Above -S1
every frame of the program is `multiplier` calls and every speed is divided
by it (`skydive_speed`, `skydive_program`), and the program's first frame is
short by the call the row's tick 0 starts into (`skydive_row_offset`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile, find_freq_table
from .constants import (CMD_SETWAVEPTR, FORMAT_GTS5, GT_FIRST_NOTE,
                        GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        GT_WAVE_FIRST_CMD, GT_WAVE_LAST_DELAY,
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
# Commands whose tick 0 on a NOTE row only sets the continuous effect
# (gplay.c:404-422; player.s `mt_tick0_12`, `mt_tick0_34`): portamento up and
# down, vibrato. Toneporta is not one -- on a note row it skips the note
# init the program needs (gplay.c:354, player.s `cmp #TONEPORTA`).
SKYDIVE_NOTE_ROW_STATE_COMMANDS = frozenset({1, 2, 4})
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


def skydive_speed(k: int, multiplier: int = 1) -> Optional[Tuple[int, int]]:
    """Store k's speed-table entry `(hi, lo)`, per PLAY CALL at -S{multiplier}.

    The block moves the frequency `$100 * k` in one of the original's frames
    and a wavetable step runs once per call, so a frame of the fall is
    `multiplier` steps of `$100 * k / multiplier` each -- the rate divided
    where it is encoded (CLAUDE.md, "a rate read out of a player is per
    frame"). None where that is not a whole number of frequency units, or
    reaches `$8000`, which gplay.c:543-551 and player.s `mt_setspeedparam`
    (`bmi mt_calculatedspeed`) read as a note-relative speed instead.
    """
    per_call, rem = divmod(k * 0x100, max(1, multiplier))
    if rem or not 0 <= per_call < 0x8000:
        return None
    return per_call >> 8, per_call & 0xFF


def skydive_program(phase: int, writes: int, alternates: bool,
                    speed_index, multiplier: int = 1) -> List[Tuple[int, int]]:
    """The wavetable steps for one window, from the frame its row starts
    (`skydive_calls`, one entry per call, runs of still calls a delay)."""
    return _compress(skydive_calls(phase, writes, alternates, speed_index,
                                   multiplier))


def skydive_calls(phase: int, writes: int, alternates: bool, speed_index,
                  multiplier: int = 1, first_calls: Optional[int] = None
                  ) -> List[Optional[Tuple[int, int]]]:
    """The window's program call by call, None where nothing is written.

    Store k (k = 0 .. writes-1) falls on frame `phase + 2k` and is `$100 * k`
    below the note's own frequency; store 0 is that frequency, so the
    program's first movement is store 1. `speed_index(k)` names the
    speed-table row holding store k's per-call step (`skydive_speed`).
    Runs of frames on which nothing moves are one delay step each (`value +
    1` calls, gplay.c:697-704).

    **One frame is `multiplier` play calls**, and every step above is
    written once per call of its frame: a fall frame is `multiplier` `F2`
    steps of `1/multiplier` of the frame's movement each, a frame on the note
    `multiplier` relative-note-0 steps, a run of still frames a delay of
    `run * multiplier` calls -- except frame 0, which has only the calls of
    its frame from the row's tick 0 on (`skydive_row_offset`): one at -S2;
    `first_calls` overrides that where the program starts later than the
    row's tick 0 (`skydive_note_row_program`).
    Neither a fall frame's second call nor a note
    frame's can be a delay: a delay call runs the row's continuous command
    (gplay.c:699-702 `goto TICKNEFFECTS`, player.s `inc mt_chnwavetime /
    bne mt_wavedone`), the very vibrato a wavetable command holds off.

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
    m = max(1, multiplier)
    first = m - skydive_row_offset(m) if first_calls is None else first_calls
    calls: List[Optional[Tuple[int, int]]] = []
    for t, step in enumerate(frames):
        calls += [step] * (first if t == 0 else m)
    return calls


def _compress(calls: List[Optional[Tuple[int, int]]]) -> List[Tuple[int, int]]:
    """Per-call steps as wavetable entries: each run of calls on which
    nothing is written is one delay entry per `WAVE_MAX_DELAY + 1` calls
    (`value + 1` calls, gplay.c:697-704), and the program stops."""
    out: List[Tuple[int, int]] = []
    run = 0
    for step in calls + [()]:
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


def skydive_row_offset(multiplier: int = 1) -> int:
    """How many calls of its frame are already played when a row's tick 0 runs.

    The packed player's first call is the song init and nothing else
    (player.s:573-620: `mt_initsongnum` resets the channels, sets each
    `mt_chncounter` to 1 and leaves through `mt_loadregswaveonly`), so row
    0's tick 0 is call 1, and with every row `frames * multiplier` calls
    long every row's tick 0 is call `1 mod multiplier` of its frame. At -S1
    that is 0; at -S2 the row's first call is the LAST call of its frame,
    the one siddump samples, and the frame the program counts as 0 has one
    call where every later frame has two. Measured on Master_of_Magic voice
    0 at -m1 (one line per call): the window's first relative-note-0 step is
    call 11013, odd, and with frame 0 given two calls the whole fall read
    one call late at -m2 -- `$67D3 $67D3 $6753` where the original stores
    `$674C`, then is back on `$684C`.
    """
    return 1 % max(1, multiplier)


def instrument_calls(entries: List[Tuple[int, int]],
                     start: int) -> Optional[List[Optional[Tuple[int, int]]]]:
    """An instrument's wave program from `start` (1-based) call by call,
    None where the call writes nothing; None for the whole where it loops.

    Read like gplay.c WAVEEXEC (:515-725): a delay `$0n` is n calls that run
    the continuous effects and a last one that applies the right side; `$00`
    applies it at once; a right side of `$80` writes no frequency, so a step
    with neither a waveform nor a frequency is a still call; `$FF 00` stops
    and takes no call of its own (:707-712 jumps on the advance). A loop
    (`$FF` to a non-zero row) never ends, so nothing can follow it.
    """
    out: List[Optional[Tuple[int, int]]] = []
    at = start
    while 1 <= at <= len(entries):
        left, right = entries[at - 1]
        if left == GT_WAVE_JUMP:
            return out if right == 0 else None
        if left <= GT_WAVE_LAST_DELAY:
            out += [None] * left
            out.append((SKYDIVE_NOOP, right) if right != GT_WAVE_NO_NOTE
                       else None)
        else:
            out.append((left, right))
        at += 1
    return None


def _merge_instrument(instr: List[Optional[Tuple[int, int]]],
                      sky: List[Optional[Tuple[int, int]]],
                      alternates: bool) -> Optional[List[Optional[tuple]]]:
    """The instrument's own calls and the window's in one program, or None.

    A note row's `CMD_SETWAVEPTR` replaces the instrument's wave pointer
    (gplay.c:367 then :436, player.s `mt_newnoteinit` then `mt_tick0_8`), so
    the program has to carry what the instrument's own program did on those
    calls. Call by call:

    * the window writes nothing: the instrument's step, unless it is a
      command, or sets a frequency other than the note's, or sets the note
      while the fall is under it (the holding program, between stores);
    * the window puts the voice on its note: the instrument's waveform with
      relative note 0, unless the instrument's step is a command or names
      another note;
    * the window steps the fall: the fall, where the instrument's step
      changes nothing the fall would lose -- no waveform other than the one
      already latched, no command, no note but the note's own.

    Anything else is a conflict and the window is declined.
    """
    out: List[Optional[tuple]] = []
    wave: Optional[int] = None
    fallen = False
    for c in range(max(len(instr), len(sky))):
        i = instr[c] if c < len(instr) else None
        s = sky[c] if c < len(sky) else None
        if i is None:
            step = s
        else:
            left, right = i
            if left >= GT_WAVE_FIRST_CMD:
                return None
            if s is None:
                if right != GT_WAVE_NO_NOTE and (right != SKYDIVE_NOTE_BASE
                                                 or fallen):
                    return None
                step = i
            elif s[0] == SKYDIVE_NOOP:
                if right not in (SKYDIVE_NOTE_BASE, GT_WAVE_NO_NOTE):
                    return None
                step = (left, SKYDIVE_NOTE_BASE)
            else:
                if left != SKYDIVE_NOOP and left != wave:
                    return None
                if right not in (SKYDIVE_NOTE_BASE, GT_WAVE_NO_NOTE):
                    return None
                step = s
        if step is not None:
            if SKYDIVE_NOOP < step[0] < GT_WAVE_FIRST_CMD:
                wave = step[0]
            if step[0] == WAVECMD_PORTADOWN:
                fallen = True
            elif step[0] == WAVECMD_PORTAUP and alternates:
                fallen = False
            elif step[0] < GT_WAVE_FIRST_CMD and step[1] == SKYDIVE_NOTE_BASE:
                fallen = False
        out.append(step)
    return out


def skydive_note_row_program(instr: List[Optional[Tuple[int, int]]],
                             phase: int, writes: int, alternates: bool,
                             speed_index, multiplier: int = 1
                             ) -> Optional[List[Tuple[int, int]]]:
    """The program for a window that opens on the note row, or None
    (`skydive_note_row_calls`, runs of still calls a delay)."""
    merged = skydive_note_row_calls(instr, phase, writes, alternates,
                                    speed_index, multiplier)
    return None if merged is None else _compress(merged)


def skydive_note_row_calls(instr: List[Optional[Tuple[int, int]]],
                           phase: int, writes: int, alternates: bool,
                           speed_index, multiplier: int = 1
                           ) -> Optional[List[Optional[Tuple[int, int]]]]:
    """A note-row window's program call by call, the instrument's own
    program merged in (`_merge_instrument`); None where they conflict.

    `phase` is the row frame of store 0. A note row's tick 0 is the note
    init and runs no wavetable (gplay.c:510-514 `goto NEXTCHN`, player.s
    `mt_newnoteinit` leaving through `mt_loadregswaveonly`), so the program's
    first call is the row's second; at -S1 that is the row's frame 1. Above
    it, the init is the last call of the row's frame 0 (`skydive_row_offset`)
    and the program still starts on frame 1, unless the frame has calls left
    after the init (-S3 and up), which are the program's frame 0.
    """
    m = max(1, multiplier)
    rest = m - skydive_row_offset(m) - 1
    frame0, first = (0, rest) if rest > 0 else (1, m)
    if phase < frame0:
        return None
    sky = skydive_calls(phase - frame0, writes, alternates, speed_index, m,
                        first_calls=first)
    return _merge_instrument(instr, sky, alternates)


def note_row_column_free(cmd: int, ends_on_note: bool) -> bool:
    """Whether a note row's command column may take the pointer.

    An empty one, or one whose command only sets the continuous effect: that
    is lost without trace where the program leaves the effect no call of the
    note (checked once the program is built, `note_cover` in
    `skydive_plan`) and the next event is a note, whose init resets it
    (gplay.c:351, player.s `mt_newnoteinit` `sta mt_chnfx,x`) -- a tied one
    included, since both reset before the toneporta test. Never toneporta on
    the row itself: that is the tie, which skips the note init the program
    replaces.
    """
    return cmd == 0 or (cmd in SKYDIVE_NOTE_ROW_STATE_COMMANDS
                        and ends_on_note)


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
                 log=None, wave_entries: Optional[List[tuple]] = None,
                 wave_starts: Optional[List[int]] = None
                 ) -> Optional[SkydivePlan]:
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

    **A note shorter than `last_ticks` opens its window on the note row
    itself** (`dur - last_ticks + 1 <= 0`: the ticks-left counter is below
    LAST from the fetch on). The player skips every effect on the fetch frame
    (Zoids `$116A JMP $137C`), so its first store is on the note's frame 1
    or 2. There the pointer takes the note row's command column -- only an
    empty one (`$0` is the instrument's vibrato, which the note init loads
    anyway: gplay.c:351-353, player.s `mt_newnoteinit`) -- and its program
    replaces the instrument's own, so it carries that program's calls
    (`instrument_calls`, `_merge_instrument`). Only with `wave_entries` and
    `wave_starts`; without them these windows are declined, as they were.
    Their programs go after the row windows' and each is placed only if it
    fits; the row windows' are all or nothing, as before.
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
    note_asks: Dict[tuple, List[tuple]] = {}
    note_cover: Dict[tuple, int] = {}
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
            lag = 0 if no_test_restart or current in real_firstwave else 1
            if j0 <= 0:
                if wave_entries is None or wave_starts is None:
                    declined["opens on the note row"] += 1
                    continue
                # Frame 0 is the fetch, which runs no effect; the first
                # store is on the first odd-counter frame after it.
                phase = 1 if (base + first + a * frames + 1) & 1 else 2
                high = _high_byte(sid, note - GT_FIRST_NOTE + transpose)
                writes = skydive_writes((end - a) * frames, phase, high)
                if writes < 2:
                    declined["too few stores"] += 1
                    continue
                cmd = patterns[p][4 * r + 2]
                ends_on_note = (GT_FIRST_NOTE
                                <= patterns[rows[end][0]][4 * rows[end][1]]
                                <= GT_LAST_NOTE)
                note_asks.setdefault((p, r), []).append(
                    (phase + lag, writes, current,
                     note_row_column_free(cmd, ends_on_note)))
                if cmd:
                    calls = (end - a) * frames * max(1, multiplier) - 1
                    note_cover[(p, r)] = max(note_cover.get((p, r), 0),
                                             calls)
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
            # window is that many frames past it (`lag`, above).
            asks.setdefault((wp, wr), []).append(
                (phase + lag, writes, by_number[current], safe))

    def take(table_of_asks):
        got: Dict[tuple, tuple] = {}
        bad = 0
        for key, wants in table_of_asks.items():
            if (len(wants) == plays.get(key, 0) and len(set(wants)) == 1
                    and wants[0][3]):
                got[key] = wants[0][:3]
            else:
                bad += 1
        return got, bad

    taken, mixed = take(asks)
    note_taken, note_mixed = take(note_asks)
    if not taken and not note_taken:
        say(f"{sum(len(w) for w in asks.values())} window(s), none taken "
            f"({mixed} row(s) mixed or occupied)"
            + (f"; {sum(len(w) for w in note_asks.values())} on the note "
               f"row, none taken ({note_mixed} row(s) mixed or occupied)"
               if note_asks else ""))
        return None

    table = speed_table

    def speed_index(k: int) -> int:
        entry = skydive_speed(k, multiplier)
        if entry is None:
            raise OverflowError
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
            entries += skydive_program(*want, speed_index, multiplier)
    except OverflowError:
        table[:] = snapshot
        say(f"speed table full or a step not a whole per-call rate at "
            f"-S{multiplier}, not emitted")
        return None
    if wave_used + len(entries) > GT_MAX_TABLELEN:
        table[:] = snapshot
        say(f"{len(entries)} wavetable step(s) past MAX_TABLELEN, not emitted")
        return None

    # The note-row windows' programs, each placed where it fits.
    note_starts: Dict[tuple, int] = {}
    note_declined = {"instrument program loops": 0,
                     "instrument program conflicts": 0,
                     "speed table": 0, "wavetable full": 0}
    instr_of: Dict[int, Optional[list]] = {}
    shape: Dict[tuple, Optional[list]] = {}
    for want in sorted(set(note_taken.values())):
        phase, writes, number = want
        if number not in instr_of:
            start = (wave_starts[number - 1]
                     if number - 1 < len(wave_starts) else 0)
            instr_of[number] = (instrument_calls(wave_entries, start)
                                if start else [])
        if instr_of[number] is None:
            note_declined["instrument program loops"] += 1
            shape[want] = None
            continue
        # The shape alone first (no speed row is registered for it): which
        # calls write, and how many the program has.
        shape[want] = skydive_note_row_calls(instr_of[number], phase, writes,
                                             by_number[number],
                                             lambda k: 0, multiplier)
        if shape[want] is None:
            note_declined["instrument program conflicts"] += 1
    uncovered = 0
    for key in list(note_taken):
        calls = shape.get(note_taken[key])
        if calls is None:
            del note_taken[key]
        elif key in note_cover and (None in calls
                                    or len(calls) < note_cover[key]):
            del note_taken[key]
            uncovered += 1
    if uncovered:
        note_declined["a command the program leaves a call"] = uncovered
    for want in sorted(set(note_taken.values())):
        phase, writes, number = want
        before = list(table)
        try:
            prog = skydive_note_row_program(instr_of[number], phase, writes,
                                            by_number[number], speed_index,
                                            multiplier)
        except OverflowError:
            table[:] = before
            note_declined["speed table"] += 1
            continue
        if wave_used + len(entries) + len(prog) > GT_MAX_TABLELEN:
            table[:] = before
            note_declined["wavetable full"] += 1
            continue
        note_starts[want] = wave_used + len(entries) + 1
        entries += prog

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
    note_edited = 0
    for (p, r), want in sorted(note_taken.items()):
        if want not in note_starts:
            continue
        trial = list(out[p])
        trial[4 * r + 2] = CMD_SETWAVEPTR
        trial[4 * r + 3] = note_starts[want]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            continue
        out[p] = trial
        note_edited += 1
    if not edited and not note_edited:
        table[:] = snapshot
        return None
    skipped = ", ".join(f"{n} {why}" for why, n in declined.items() if n)
    note_skipped = ", ".join(f"{n} {why}" for why, n in note_declined.items()
                             if n)
    say(f"{edited} window row(s) on {len(records)} record(s) "
        f"{sorted(records)}, {len(starts)} program(s) "
        f"{sorted(starts)}, {len(entries)} wavetable step(s)"
        + (f"; {mixed} row(s) mixed or occupied" if mixed else "")
        + (f"; declined: {skipped}" if skipped else "")
        + (f"; on the note row: {note_edited} row(s), {len(note_starts)} "
           f"program(s) {sorted(note_starts)}"
           + (f", {note_mixed} row(s) mixed or occupied"
              if note_mixed else "")
           + (f", declined: {note_skipped}" if note_skipped else "")
           if note_asks else ""))
    return SkydivePlan(patterns=out, entries=entries)
