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
(gplay.c:528-690, player.s mt_execwavecmd), so a program built only from
those holds the vibrato where the program found it for the length of the
fall. The holding program steps `F2 1` on each fall frame and leaves the
frame between to a no-op.

**Where the vibrato can be read, the program carries it** (`SkydiveVibrato`,
`skydive_targets`). The global-triangle vibrato (detect._find_triangle_
vibrato, all six files whose record vibrates) is a pure function of the
play-entry counter -- `note + fold(counter & 7) * (interval >> (byte + 1))`,
folded 0,1,2,3,3,2,1,0 -- and the counter is the very cell the skydive tests
(`triangle_counter`). So the frequency the original writes on every frame of
the window is known in advance: the vibrato on the frames between stores,
and the same vibrato's low byte under the falling high byte on the stores
(Hunter_Patrol: stores `67A1 66DA 654C 6413` carry the low bytes of
`6AA1 69DA 684C 6913`, the vibrato's own). Every frame of the program is then
one portamento command whose speed is the difference to the frame before, so
the vibrato is not held off but written into the speeds. A program of that
kind depends on the note's pitch and on the counter's phase, which a pitch
-independent held program does not, so a row asking for it is given one only
where every play of it asks for the same, and only while the wavetable and
the speed table have room: the held program is the fallback, per program.

**A TIED note's window opens on the row after the tie** (`tie_window_phase`,
`share_program_tail`). A tie (`CMD_TONEPORTA 00`) sets the ticks-left counter
like any fetch but skips the frequency and `savehi` (Zoids $10D5 `BVS
$1116`), and its command column is already taken, so the pointer goes on the
NEXT row, which a tie leaves free (the converter repeats the persistent
command on each row; one row of the pointer costs that command's tick 0,
which the program never lets run because it writes on every call). Those
programs are the tail of one another -- the pairs `F2 k / F1 k` do not depend
on the note -- so a tie window is a short lead and a wavetable jump into the
pairs of a program already placed, not another 70 rows.

Emitted only in GTS5 (the wavetable names speed-table rows, which a GTS2
file does not store), with no outer gate, and only on a row whose every play
asks for the same program and whose command column can be taken without
losing anything; everything declined is counted in the log line. Above -S1
every frame of the program is `multiplier` calls and every speed is divided
by it (`skydive_speed`, `skydive_program`), and the program's first frame is
short by the call the row's tick 0 starts into (`skydive_row_offset`).
"""
from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..detect import (Detection, TRIANGLE_VIBRATO_GATE,
                      TRIANGLE_VIBRATO_MAX_SHIFT, TRIANGLE_VIBRATO_PERIOD,
                      TRIANGLE_VIBRATO_SHAPE)
from ..search import search_file
from ..sidfile import SidFile, find_freq_table
from .constants import (CMD_FUNKTEMPO, CMD_SETTEMPO, CMD_SETWAVEPTR,
                        CMD_TONEPORTA, FORMAT_GTS5, GT_FIRST_NOTE,
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
# The commands the row AFTER a tie may be holding when the pointer takes its
# column: none, or one that only sets the continuous effect for the row. The
# tie's own toneporta then runs in its place for that one row, and the
# program writes on every call of it, so it never shows.
SKYDIVE_TIE_NEXT_COMMANDS = frozenset({0, 1, 2, 4})
# A Hubbard note's duration is the low five bits of its note byte.
SKYDIVE_MAX_DURATION = 0x1F
# Wavetable left side `$00`: "leave waveform unchanged" (readme.txt:787), a
# one-frame step whose `$80` right side leaves the vibrato to run.
SKYDIVE_NOOP = 0x00
# Wavetable right side `$00`: relative note +0, the note's own frequency.
SKYDIVE_NOTE_BASE = 0x00


# Goattracker's own frequency table (gplay.c:9-31 `freqtbllo`/`freqtblhi`, the
# first 96 entries, C-0 .. B-7): what a relative-note-0 wavetable step sets
# the voice to, and so the frequency every program here is measured from. It
# is transcribed rather than computed (`primitives._note_freq` floors the
# formula, which is off by one on most entries and by 1880 on the clamped
# last one).
GT_FREQ_TABLE = (
    0x0117, 0x0127, 0x0139, 0x014B, 0x015F, 0x0174, 0x018A, 0x01A1,
    0x01BA, 0x01D4, 0x01F0, 0x020E, 0x022D, 0x024E, 0x0271, 0x0296,
    0x02BE, 0x02E8, 0x0314, 0x0343, 0x0374, 0x03A9, 0x03E1, 0x041C,
    0x045A, 0x049C, 0x04E2, 0x052D, 0x057C, 0x05CF, 0x0628, 0x0685,
    0x06E8, 0x0752, 0x07C1, 0x0837, 0x08B4, 0x0939, 0x09C5, 0x0A5A,
    0x0AF7, 0x0B9E, 0x0C4F, 0x0D0A, 0x0DD1, 0x0EA3, 0x0F82, 0x106E,
    0x1168, 0x1271, 0x138A, 0x14B3, 0x15EE, 0x173C, 0x189E, 0x1A15,
    0x1BA2, 0x1D46, 0x1F04, 0x20DC, 0x22D0, 0x24E2, 0x2714, 0x2967,
    0x2BDD, 0x2E79, 0x313C, 0x3429, 0x3744, 0x3A8D, 0x3E08, 0x41B8,
    0x45A1, 0x49C5, 0x4E28, 0x52CD, 0x57BA, 0x5CF1, 0x6278, 0x6853,
    0x6E87, 0x751A, 0x7C10, 0x8371, 0x8B42, 0x9389, 0x9C4F, 0xA59B,
    0xAF74, 0xB9E2, 0xC4F0, 0xD0A6, 0xDD0E, 0xEA33, 0xF820, 0xFFFF,
)
# The folded triangle's peak: `fold(c & 7)` runs 0,1,2,3,3,2,1,0.
SKYDIVE_VIBRATO_PEAK = 3
# Whether a window's program may write the vibrato out. A carried program is
# pitch-specific and so bigger than the held one it replaces, and in a
# compilation every further player is appended into the SAME 255-row tables:
# `convert._append_players` runs the conversion again without them, and again
# with only the room that left, when the carried programs cost it a player.
CARRY_VIBRATO = True
# None, or the (wavetable, speed table) rows a plan's carried programs may add
# to its own held layout -- what the compilation had left over (`vibrato_carry`).
CARRY_BUDGET: Optional[Tuple[int, int]] = None


@contextlib.contextmanager
def vibrato_carry(on: bool, budget: Optional[Tuple[int, int]] = None):
    """Run a conversion with the carried-vibrato programs allowed or not,
    and held to `budget` extra (wavetable, speed table) rows if given."""
    global CARRY_VIBRATO, CARRY_BUDGET
    before = CARRY_VIBRATO, CARRY_BUDGET
    CARRY_VIBRATO, CARRY_BUDGET = on, budget
    try:
        yield
    finally:
        CARRY_VIBRATO, CARRY_BUDGET = before


# A portamento speed at or above `$8000` is note-relative (gplay.c:543-551).
SKYDIVE_MAX_SPEED = 0x7FFF


@dataclass(frozen=True)
class SkydivePlan:
    """The finished patterns and the program block to append to the wavetable.

    `base` and `starts` are set only when the plan made room by sharing the
    identical programs at the end of the table (`compact_wave_tail`) or by
    laying programs over the rows of duplicate instrument blocks
    (`note_rise.reclaimable_holes`): the wavetable to append `entries` to is
    then `base`, not the one the plan was given, and `starts` is the
    instrument starts to write over `wave_starts`.
    """
    patterns: List[List[int]]
    entries: List[Tuple[int, int]]
    base: Optional[List[Tuple[int, int]]] = None
    starts: Optional[List[int]] = None
    # Set only where the plan gave an orderlist position a pattern copy of
    # its own (`note_rise._isolate`): the orderlists to write.
    tracks: Optional[List[List[int]]] = None


def compact_wave_tail(wave_entries: List[Tuple[int, int]],
                      wave_starts: List[int],
                      pointers: List[int]
                      ) -> Optional[Tuple[List[Tuple[int, int]], List[int]]]:
    """The wavetable with the identical programs at its end shared, or None.

    Every record's program is its own block, and many records have the same
    one (Last_V8: thirteen drum records are `00 00 / 00 00 / 01 00 / FF 00 /
    FF 00`, 65 rows). A program is stateless, so two records may point at
    one copy: the tail from some record's start on is rebuilt with each
    distinct block once, in order of first appearance, and `wave_starts` is
    repointed. Returns (entries, starts) for the smallest tail that can be
    rebuilt, None where nothing is saved.

    A tail can be rebuilt only if nothing else names a row in it, because
    rows move: no entry of `pointers` (every other row anything points at --
    arpeggio, clone, drum, attack-hold, tie starts and the
    `CMD_SETWAVEPTR` operands of the patterns) at or past its first row, no
    jump from before it into it, and no jump inside it to a row but 0 (a
    jump to 0 is a stop and does not care where it stands).
    """
    starts = sorted({s for s in wave_starts if s})
    size = len(wave_entries)
    for cut in starts:
        if any(p >= cut for p in pointers):
            continue
        head = wave_entries[:cut - 1]
        if any(left == GT_WAVE_JUMP and right >= cut for left, right in head):
            continue
        tail = wave_entries[cut - 1:]
        edges = [s for s in starts if s >= cut] + [size + 1]
        blocks = {s: tuple(wave_entries[s - 1:e - 1])
                  for s, e in zip(edges, edges[1:])}
        if any(left == GT_WAVE_JUMP and right
               for block in blocks.values() for left, right in block):
            continue
        if sum(len(b) for b in blocks.values()) != len(tail):
            continue
        placed: Dict[tuple, int] = {}
        entries = list(head)
        for s in sorted(blocks):
            if blocks[s] not in placed:
                placed[blocks[s]] = len(entries) + 1
                entries += list(blocks[s])
        if len(entries) >= size:
            continue
        return entries, [placed[blocks[s]] if s >= cut else s
                         for s in wave_starts]
    return None


def coalesce_holes(holes: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """`holes` ((first row, rows) each, `note_rise.reclaimable_holes`) with
    the ones that touch merged into runs: duplicate blocks are five rows
    apiece and lie side by side, and a program is one run of rows."""
    runs: List[List[int]] = []
    for first, rows in sorted(holes):
        if runs and runs[-1][0] + runs[-1][1] == first:
            runs[-1][1] += rows
        else:
            runs.append([first, rows])
    return [(a, n) for a, n in runs]


def take_from_runs(free: List[List[int]], rows: int) -> Optional[int]:
    """The first row of the smallest run in `free` ([first, rows] lists) with
    `rows` rows or more, taken off it, or None. Smallest first so the long
    runs stay for the long programs; the lower address breaks a tie."""
    fit = [run for run in free if run[1] >= rows]
    if not fit:
        return None
    run = min(fit, key=lambda r: (r[1], r[0]))
    at = run[0]
    run[0] += rows
    run[1] -= rows
    return at


@dataclass(frozen=True)
class SkydiveVibrato:
    """What a window needs of the original's vibrato to write it out.

    `counter` is the play-entry counter's value (mod 8) on the program's
    frame 0, `base` the note's frequency in the ORIGINAL's table (what its
    vibrato oscillates around, so what the program reproduces frame for
    frame), `step` the oscillator's unit, `interval >> (byte + 1)` off the
    same table, and `anchor` Goattracker's own frequency for the note --
    where a relative-note-0 step puts the voice, so where the program starts
    and ends. It is the base itself where the original's table is not known.
    """
    counter: int
    base: int
    step: int
    anchor: Optional[int] = None
    pinned: bool = False

    @property
    def start(self) -> int:
        return self.base if self.anchor is None else self.anchor


def triangle_counter(sid: SidFile) -> Optional[int]:
    """The address of the global-triangle vibrato's oscillator counter.

    The `LDA abs` in front of the shape's `AND #$07` (One_Man_and_his_Droid
    $11A0 `AD 1C 15`). None where the file has no such vibrato.
    """
    at = search_file(sid.data, TRIANGLE_VIBRATO_SHAPE)
    if at < 3 or sid.data[at - 3] != 0xAD:
        return None
    return sid.data[at - 2] | sid.data[at - 1] << 8


def vibrato_phase(counter: int) -> int:
    """The oscillator's `fold(counter & 7)`: 0,1,2,3,3,2,1,0 (`AND #$07 /
    CMP #$04 / BCC / EOR #$07`)."""
    c = counter & 7
    return c ^ 7 if c >= 4 else c


def skydive_vibrato_shifts(sid: SidFile, det: Detection,
                           records: Dict[int, bool]) -> Dict[int, int]:
    """{record index: its vibrato shift count} for the records whose
    vibrato the window can write out.

    Only the global-triangle dialect (the others' oscillators are per
    instrument), only where its counter is the skydive's own, only where
    every note that has a window also has the vibrato (`min_length` at least
    the player's own length gate), and only for a count the player does not
    shift to nothing (`TRIANGLE_VIBRATO_MAX_SHIFT`: `interval >> (byte + 1)`
    is zero from 15 on, and a record that stores 188 or 255 there has no
    vibrato to carry).
    """
    sd = det.skydive
    if (sd is None or det.triangle_vibrato is None
            or triangle_counter(sid) != sd.counter
            or sd.min_length < (det.triangle_gate or TRIANGLE_VIBRATO_GATE)):
        return {}
    out: Dict[int, int] = {}
    for i, alternates in records.items():
        if not alternates:
            continue
        at = det.instr_start + i * det.instr_stride + det.triangle_vibrato
        if at < len(sid.data) and 0 < sid.data[at] < TRIANGLE_VIBRATO_MAX_SHIFT:
            out[i] = sid.data[at]
    return out


def _orig_freq(sid: SidFile, index: int) -> Optional[int]:
    table = find_freq_table(sid)
    if table is None or not 0 <= index < table.length:
        return None
    at = sid.to_offset(table.addr) + 2 * index
    if not 0 <= at or at + 1 >= len(sid.data):
        return None
    return sid.data[at] | sid.data[at + 1] << 8


def anchor_bias(vib: Optional[SkydiveVibrato], pinned: bool = True) -> int:
    """How far above the original's own frequency for the note the voice
    starts, where a relative-note-0 step puts it: `anchor - base`.

    The original's store is `high(note) - k`, over the low byte of the note
    in ITS table; a fall of `$100 * k` from Goattracker's note reads a high
    byte up wherever the vibrato tick that follows it carries the low byte
    over (Last_V8_C128_version, note 76: the original's $57AC against
    Goattracker's $57BA, and a tick of +$53 takes $56BA to $570D, where
    $56AC reaches only $56FF). Zero where the original's table is not known
    (`window_vibrato` then has anchor and base equal) or the interval is
    not a small one.
    """
    if vib is None or vib.anchor is None:
        return 0
    bias = vib.anchor - vib.base
    return bias if (vib.pinned and pinned) or abs(bias) < 0x100 else 0


def window_vibrato(sid: SidFile, shift: Optional[int], note: int,
                   counter: int, det: Optional[Detection] = None
                   ) -> Optional[SkydiveVibrato]:
    """The vibrato a window on Goattracker note index `note` writes, or None.

    `counter` is the play-entry counter on the program's frame 0. The unit is
    the original's own: the interval to the next note in ITS table, shifted
    `shift + 1` times (the depth loop `LSR / ROR / DEC / BPL`, which runs
    `shift + 1` times), the same index `_high_byte` reads the store from.
    None where the peak would carry the 16-bit frequency over, or the step
    is nothing.
    """
    if shift is None or not 0 <= note < len(GT_FREQ_TABLE) - 1:
        return None
    table = find_freq_table(sid)
    index = note - (table.shift if table is not None else 0)
    here, there = _orig_freq(sid, index), _orig_freq(sid, index + 1)
    if here is None or there is None or there <= here:
        here, there = GT_FREQ_TABLE[note], GT_FREQ_TABLE[note + 1]
    step = (there - here) >> (shift + 1)
    if not step or here + SKYDIVE_VIBRATO_PEAK * step > 0xFFFF:
        return None
    cell = None
    if det is not None:
        from ..patterns import player_cell_pitch
        cell = player_cell_pitch(sid, det, index)
    if cell is not None:
        # A byte past the table: the original starts the note at the
        # recorded cell pitch, so the fall is measured from THAT, however
        # far (`pinned`) the entry it was rounded to sits from it.
        return SkydiveVibrato(counter=counter & (TRIANGLE_VIBRATO_PERIOD - 1),
                              base=cell, step=step,
                              anchor=GT_FREQ_TABLE[note], pinned=True)
    return SkydiveVibrato(counter=counter & (TRIANGLE_VIBRATO_PERIOD - 1),
                          base=here, step=step, anchor=GT_FREQ_TABLE[note])


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


def skydive_speed(k: int, multiplier: int = 1,
                  bias: int = 0) -> Optional[Tuple[int, int]]:
    """Store k's speed-table entry `(hi, lo)`, per PLAY CALL at -S{multiplier}.

    The block moves the frequency `$100 * k` in one of the original's frames
    and a wavetable step runs once per call, so a frame of the fall is
    `multiplier` steps of `$100 * k / multiplier` each -- the rate divided
    where it is encoded (CLAUDE.md, "a rate read out of a player is per
    frame"). None where that is not a whole number of frequency units, or
    reaches `$8000`, which gplay.c:543-551 and player.s `mt_setspeedparam`
    (`bmi mt_calculatedspeed`) read as a note-relative speed instead.

    `bias` is added to the frame's movement before it is divided: how far
    Goattracker's frequency for the note sits above the original's own
    (`anchor_bias`), so a fall measured from Goattracker's note lands where
    the original's would.
    """
    per_call, rem = divmod(k * 0x100 + bias, max(1, multiplier))
    if rem or not 0 <= per_call < 0x8000:
        return None
    return per_call >> 8, per_call & 0xFF


def skydive_program(phase: int, writes: int, alternates: bool,
                    speed_index, multiplier: int = 1,
                    vib: Optional[SkydiveVibrato] = None,
                    speed_row=None,
                    compact: bool = False) -> List[Tuple[int, int]]:
    """The wavetable steps for one window, from the frame its row starts
    (`skydive_calls`, one entry per call, runs of still calls a delay).

    `compact` is the held alternating program at a third of the rows
    (`skydive_compact_calls`); `speed_index` then names the FRAME's step
    (`skydive_speed(k)`, not divided by the multiplier)."""
    if compact and alternates and vib is None and multiplier > 1:
        return _compress(skydive_compact_calls(phase, writes, speed_index,
                                               multiplier),
                         fold_apply=True)
    return _compress(skydive_calls(phase, writes, alternates, speed_index,
                                   multiplier, vib=vib, speed_row=speed_row))


def skydive_compact_calls(phase: int, writes: int, speed_index,
                          multiplier: int,
                          first_calls: Optional[int] = None
                          ) -> List[Optional[Tuple[int, int]]]:
    """The alternating program above -S1 in 3 rows a pair of frames, not 4.

    The program of `skydive_calls` spends a call on every call of every
    frame: a fall frame is `multiplier` `F2` steps of a share of the
    movement, a note frame `multiplier` relative-note-0 steps. The table
    space is the cost (Last_V8, -S2: 124 rows for 30 stores, with 38 free),
    and a frame's calls do not need a step each:

    * a fall frame is ONE `F2` of the frame's whole movement, on its first
      call (`skydive_speed(k)`, the -S1 rate), and the rest of its calls are
      still -- they run the instrument's vibrato, one tick each;
    * a note frame is a relative-note-0 step on its first and last call and
      still calls between, which fold into one delay entry with the last
      step (`_compress`, `fold_apply`).

    At -S2 that is `F2 k`, `(1, $00)`, `($00, $00)`: the voice is on the
    fall for the frame's two calls and on the note for the next two, and the
    last call of each frame -- the one siddump samples -- is on the fall
    after its one vibrato tick (the original's low byte there is the
    vibrato's own) and exactly on the note. The vibrato is therefore not
    held off for the fall's calls as `skydive_calls` holds it, but runs one
    tick a fall frame: a tick moves the frequency by the instrument's
    vibrato speed, far from a store's $0100.
    """
    m = max(1, multiplier)
    first = m - skydive_row_offset(m) if first_calls is None else first_calls
    last = phase + 2 * (writes - 1)
    calls: List[Optional[Tuple[int, int]]] = []
    note = (SKYDIVE_NOOP, SKYDIVE_NOTE_BASE)
    for t in range(last + 2):
        n = first if t == 0 else m
        k, odd = divmod(t - phase, 2)
        if t >= phase + 2 and not odd:
            calls += [(WAVECMD_PORTADOWN, speed_index(k))] + [None] * (n - 1)
        elif t >= phase + 2:
            calls += [note] + [None] * max(n - 2, 0) + ([note] if n > 1 else [])
        else:
            calls += [note] * n
    return calls


def skydive_targets(phase: int, writes: int, vib: SkydiveVibrato
                    ) -> List[int]:
    """The frequency the voice should read on each frame of an alternating
    window that writes out its vibrato, frame 0 to the one after the last
    store.

    The original writes `base + fold(counter) * step` every frame (the
    vibrato), and on a store frame (frame `phase + 2j`) replaces the high
    byte with the note's own less `j` -- over the vibrato's low byte, which is
    what it just wrote. Frame 0 and the last are Goattracker's note
    (`vib.start`, a relative-note-0 step) and not the original's: frame 0
    because nothing the program knows of the voice before it (the row's own
    vibrato has been running on a phase of its own), the last because the
    program ends by putting the voice back where the instrument's vibrato
    starts from (relative note 0 sets `vibtime` to zero).
    """
    last = phase + 2 * (writes - 1)
    out: List[int] = []
    for t in range(last + 2):
        if t == 0 or t == last + 1:
            out.append(vib.start)
            continue
        freq = vib.base + vibrato_phase(vib.counter + t) * vib.step
        if t >= phase and not (t - phase) & 1:
            freq = (((vib.base >> 8) - (t - phase) // 2) << 8) | (freq & 0xFF)
        out.append(freq)
    return out


def skydive_vibrato_calls(phase: int, writes: int, vib: SkydiveVibrato,
                          speed_row, multiplier: int = 1,
                          first_calls: Optional[int] = None
                          ) -> List[Optional[Tuple[int, int]]]:
    """An alternating window with its vibrato written out, call by call.

    Frame 0 and the last are relative-note-0 steps (`skydive_targets`); every
    frame between is a portamento command of the difference to the frame
    before, `F1` up or `F2` down, against the speed-table row
    `speed_row(magnitude)` names. A command runs instead of the voice's
    vibrato on its frame (gplay.c:528-690), so nothing the row's own vibrato
    does can reach the voice while the program runs.

    **A frame is `multiplier` calls** and the frame's movement is shared
    between them, `magnitude // calls` on each and the remainder one more on
    that many: only the last call of a frame is sampled, so how the movement
    divides inside it is unobservable, but it has to add up. A frame that
    moves nothing is a row of speed 0 -- not speed-table row 0, which the
    packed player reads off the byte before the table.
    """
    m = max(1, multiplier)
    first = m - skydive_row_offset(m) if first_calls is None else first_calls
    targets = skydive_targets(phase, writes, vib)
    calls: List[Optional[Tuple[int, int]]] = []
    for t, here in enumerate(targets):
        n = first if t == 0 else m
        if t == 0 or t == len(targets) - 1:
            calls += [(SKYDIVE_NOOP, SKYDIVE_NOTE_BASE)] * n
            continue
        move = here - targets[t - 1]
        whole, extra = divmod(abs(move), n)
        cmd = WAVECMD_PORTAUP if move > 0 else WAVECMD_PORTADOWN
        for c in range(n):
            calls.append((cmd, speed_row(whole + (c < extra))))
    return calls


def skydive_calls(phase: int, writes: int, alternates: bool, speed_index,
                  multiplier: int = 1, first_calls: Optional[int] = None,
                  vib: Optional[SkydiveVibrato] = None, speed_row=None
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

    **With `vib` (and `speed_row`, `skydive_vibrato_calls`) the vibrato is
    written into the program instead of held off by it**: every frame is
    a portamento command of the difference to the frame before, so the frames
    between stores carry the oscillator the original writes there.
    """
    if alternates and vib is not None and speed_row is not None:
        return skydive_vibrato_calls(phase, writes, vib, speed_row,
                                     multiplier, first_calls)
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


def _compress(calls: List[Optional[Tuple[int, int]]],
              fold_apply: bool = False) -> List[Tuple[int, int]]:
    """Per-call steps as wavetable entries: each run of calls on which
    nothing is written is one delay entry per `WAVE_MAX_DELAY + 1` calls
    (`value + 1` calls, gplay.c:697-704), and the program stops.

    **With `fold_apply`, a run of still calls that ends on a relative-note-0
    step is ONE entry** (`skydive_compact_calls`): a delay `$0n` is n calls
    that run the continuous effects and a last one that applies the right
    side (gplay.c:697-704), so `(n, $00)` is n still calls then the
    note step -- the same calls the two entries `(n - 1, $80)` and `($00,
    $00)` make, one row smaller. It is not applied by default: a program laid
    out before this must keep its bytes.
    """
    out: List[Tuple[int, int]] = []
    run = 0
    for step in calls + [()]:
        if step is None:
            run += 1
            continue
        if fold_apply and run and step == (SKYDIVE_NOOP, SKYDIVE_NOTE_BASE):
            while run > WAVE_MAX_DELAY:
                n = min(run - WAVE_MAX_DELAY, WAVE_MAX_DELAY + 1)
                out.append((SKYDIVE_NOOP + n - 1, GT_WAVE_NO_NOTE))
                run -= n
            out.append((SKYDIVE_NOOP + run, SKYDIVE_NOTE_BASE))
            run = 0
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
                             speed_index, multiplier: int = 1,
                             vib: Optional[SkydiveVibrato] = None,
                             speed_row=None
                             ) -> Optional[List[Tuple[int, int]]]:
    """The program for a window that opens on the note row, or None
    (`skydive_note_row_calls`, runs of still calls a delay)."""
    merged = skydive_note_row_calls(instr, phase, writes, alternates,
                                    speed_index, multiplier, vib, speed_row)
    return None if merged is None else _compress(merged)


def skydive_note_row_calls(instr: List[Optional[Tuple[int, int]]],
                           phase: int, writes: int, alternates: bool,
                           speed_index, multiplier: int = 1,
                           vib: Optional[SkydiveVibrato] = None,
                           speed_row=None
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

    `vib.counter` is the oscillator's phase on the ROW's frame 0; the
    program's frame 0 is `frame0` frames later.
    """
    m = max(1, multiplier)
    rest = m - skydive_row_offset(m) - 1
    frame0, first = (0, rest) if rest > 0 else (1, m)
    if phase < frame0:
        return None
    if vib is not None:
        vib = dataclasses.replace(
            vib, counter=(vib.counter + frame0) % TRIANGLE_VIBRATO_PERIOD)
    sky = skydive_calls(phase - frame0, writes, alternates, speed_index, m,
                        first_calls=first, vib=vib, speed_row=speed_row)
    return _merge_instrument(instr, sky, alternates)


def rows_off_the_frame_grid(rows, patterns: List[List[int]],
                            multiplier: int) -> bool:
    """Whether some row of a lap is not a whole number of frames long.

    `skydive_row_offset` is the residue of a row's tick 0 in its frame for a
    song whose every row is `frames * multiplier` calls: tick 0 of row r is
    call `1 + row_calls * r`, so it moves by `row_calls mod multiplier` a row
    and the program of a row after a row of 3 calls at -S2 starts on the OTHER
    call of its frame. A program counted call by call (every one here) is
    right for one residue only, so a lap that carries a tempo command which is
    not a multiple of the multiplier (`CMD_SETTEMPO`, which the fractional-row
    pass, the orderlist step tempos and the regrid compensation all write) or
    a 2-call funk row (`CMD_FUNKTEMPO`) is declined, as is every play of a
    row shared with it. None of the corpus files that emit the program above
    -S1 (Master_of_Magic, One_Man_and_his_Droid: every row `CMD_SETTEMPO 4`
    at -S2) has one; at -S1 the residue is 0 whatever the rows, so this is
    asked only above it.
    """
    if multiplier <= 1:
        return False
    for p, r, _t in rows:
        cmd, data = patterns[p][4 * r + 2], patterns[p][4 * r + 3]
        if cmd == CMD_FUNKTEMPO or (cmd == CMD_SETTEMPO
                                    and (data & 0x7F) % multiplier):
            return True
    return False


def tie_window_phase(phase: int, lag: int, frames: int) -> int:
    """The frame of store 0 counted from the row AFTER a tie (the pointer's
    row): `phase + lag` is its frame counted from the tie row's own first
    call (the note-row formula), and the next row starts `frames` later."""
    return phase + lag - frames


def _run_from(rows: Dict[int, Tuple[int, int]], at: int
              ) -> Optional[List[Tuple[int, int]]]:
    """The entries the wavetable executes from row `at` to its stop, following
    jumps, as the placed `rows` hold them; None where it leaves them, loops,
    or starts on a jump."""
    out: List[Tuple[int, int]] = []
    seen = set()
    while True:
        if at not in rows or at in seen:
            return None
        seen.add(at)
        left, right = rows[at]
        if left == GT_WAVE_JUMP:
            if right == 0:
                return out or None
            at = right
            continue
        out.append((left, right))
        at += 1


def share_program_tail(prog: List[Tuple[int, int]],
                       rows: Dict[int, Tuple[int, int]],
                       min_saving: int = 2
                       ) -> Tuple[List[Tuple[int, int]], Optional[int]]:
    """`prog` with its tail left to a program already placed: (rows still to
    place, the row to point at instead of the program's own first, or None).

    `rows` is every wavetable row the plan has placed so far. A step is
    stateless -- the portamento pairs name a speed-table row and nothing
    else -- so a program whose last entries before the stop are what row `c`
    executes to ITS stop plays the same from there on, and can end in a
    wavetable jump to `c` (a jump takes no call of its own, gplay.c:707-712,
    player.s `mt_nowavejump`). Where the whole program is what `c` executes,
    it needs no row at all and the pointer names `c`. The longest such run
    wins; a jump has to save at least `min_saving` rows (it costs one).
    Returns `(prog, None)` where nothing does.
    """
    stop = (GT_WAVE_JUMP, 0x00)
    if not prog or prog[-1] != stop:
        return prog, None
    body = prog[:-1]
    best_len, best_at = 0, 0
    for at in sorted(rows):
        run = _run_from(rows, at)
        if (run is None or len(run) > len(body) or len(run) <= best_len
                or body[len(body) - len(run):] != run):
            continue
        best_len, best_at = len(run), at
    if not best_len:
        return prog, None
    if best_len == len(body):
        return [], best_at
    if best_len - 1 < min_saving:
        return prog, None
    return body[:len(body) - best_len] + [(GT_WAVE_JUMP, best_at)], None


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


def _lap_restart(track: List[int]) -> Optional[int]:
    """The restart position `$FF n` names, None where the track has none."""
    operand = False
    for b in track:
        if operand:
            return b
        if b == 0xFF:
            operand = True
    return None


def _program_order(key):
    """Sort key for a (window, vibrato) program key, which a held row's key
    extends with the anchor bias: the vibrato is None or a dataclass, which
    do not compare. A key of four (`pinned_key`) goes after the others, for
    it is laid as the tail of one of them."""
    want, vib = key[0], key[1]
    return (len(key) > 3, want, vib is not None,
            (vib.counter, vib.base, vib.step, vib.start) if vib is not None
            else (), key[2:])


@dataclass
class _Assembly:
    """One way of laying the programs out: which are carried, where they
    start, and the speed table they left behind."""
    entries: List[Tuple[int, int]]
    starts: Dict[tuple, int]
    row_keys: Dict[tuple, tuple]
    note_starts: Dict[tuple, int]
    note_keys: Dict[tuple, tuple]
    note_declined: Dict[str, int]
    table: List[tuple]
    tie_starts: Dict[tuple, int] = dataclasses.field(default_factory=dict)
    tie_keys: Dict[tuple, tuple] = dataclasses.field(default_factory=dict)
    tie_declined: Dict[str, int] = dataclasses.field(default_factory=dict)
    tie_shared: int = 0
    # {row: entry} of the programs laid over reclaimed rows (`reuse`), which
    # `entries` does not carry: it is only what goes past the table's end.
    overlay: Dict[int, Tuple[int, int]] = dataclasses.field(
        default_factory=dict)

    @property
    def placed(self) -> int:
        """How many note-row programs and tie ROWS this layout got in. The
        tie windows are counted by row: a program carrying the vibrato is
        one row's and a held one is shared by every row that asks for it, so
        carrying one must not look like keeping both."""
        return len(self.note_starts) + sum(
            key in self.tie_starts for key in self.tie_keys.values())


def skydive_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                 patterns: List[List[int]], lead: int, instr_used: int,
                 fmt: str, multiplier: int, gate_skip: Optional[int],
                 speed_table: List[tuple], wave_used: int,
                 no_test_restart: bool = False,
                 real_firstwave: tuple = (),
                 log=None, wave_entries: Optional[List[tuple]] = None,
                 wave_starts: Optional[List[int]] = None,
                 wave_pointers: Optional[List[int]] = None
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

    **A window that can write the vibrato out asks for a program of its own
    pitch and phase** (`window_vibrato`, `skydive_vibrato_calls`), which a
    row gets only where every play of it asks for the same one; otherwise
    its held program, which does not depend on either, is the fallback. The
    programs are laid out held first, and each carried one is added only
    while the wavetable and the speed table take it without costing a note-row
    program its place (`assemble`, most-used first).

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
    wave_used_before = wave_used

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
    by_shift = {i + lead + 1: s for i, s in
                skydive_vibrato_shifts(sid, det, records).items()}

    plays: Dict[tuple, int] = {}
    asks: Dict[tuple, List[tuple]] = {}
    note_asks: Dict[tuple, List[tuple]] = {}
    note_cover: Dict[tuple, int] = {}
    tie_asks: Dict[tuple, List[tuple]] = {}
    tie_declined = {"holding program leaves a call": 0,
                    "stores before the next row": 0}
    off_grid = 0
    declined = {"opens on the note row": 0, "too few stores": 0,
                "orderlist(s) with rows that are not whole frames": 0}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None:
            continue
        rows = list(_lap_rows(track, patterns))
        restart = _lap_restart(track)
        for p, r, _t in rows:
            plays[(p, r)] = plays.get((p, r), 0) + 1
        if rows_off_the_frame_grid(rows, patterns, multiplier):
            off_grid += 1
            declined["orderlist(s) with rows that are not whole frames"] += 1
            continue
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
            if end is None and restart == 0:
                # The lap plays again from its first row, so a note running
                # off the end lasts until that lap's first event.
                end = len(rows) + next(
                    (e for e in range(a + 1)
                     if patterns[rows[e][0]][4 * rows[e][1]] != GT_REST
                     or patterns[rows[e][0]][4 * rows[e][1] + 1]), a)
            if end is None:
                continue
            dur = end - a - 1
            if dur > SKYDIVE_MAX_DURATION or dur < sd.min_length:
                continue
            j0 = dur - sd.last_ticks + 1
            lag = 0 if no_test_restart or current in real_firstwave else 1
            index = note - GT_FIRST_NOTE + transpose
            if (j0 <= 0 and wave_entries is not None
                    and wave_starts is not None
                    and patterns[p][4 * r + 2] == CMD_TONEPORTA
                    and patterns[p][4 * r + 3] == 0):
                # A tie: the window opens on the row after it.
                counter = base + first + a * frames
                phase = 1 if (counter + 1) & 1 else 2
                high = _high_byte(sid, index)
                writes = skydive_writes((end - a) * frames, phase, high)
                if writes < 2:
                    declined["too few stores"] += 1
                    continue
                start = tie_window_phase(phase, lag, frames)
                alternates = by_number[current]
                wp, wr, _ = rows[(a + 1) % len(rows)]
                free = patterns[wp][4 * wr + 2] in SKYDIVE_TIE_NEXT_COMMANDS
                if start < -1:
                    tie_declined["stores before the next row"] += 1
                    continue
                if not alternates:
                    tie_declined["holding program leaves a call"] += 1
                    continue
                at = a + 1
                tie_asks.setdefault((wp, wr), []).append(
                    (start, writes, alternates, free,
                     window_vibrato(sid, by_shift.get(current), index,
                                    base + first + at * frames - lag, det)))
                continue
            if j0 <= 0:
                if wave_entries is None or wave_starts is None:
                    declined["opens on the note row"] += 1
                    continue
                # Frame 0 is the fetch, which runs no effect; the first
                # store is on the first odd-counter frame after it.
                counter = base + first + a * frames
                phase = 1 if (counter + 1) & 1 else 2
                high = _high_byte(sid, index)
                writes = skydive_writes((end - a) * frames, phase, high)
                if writes < 2:
                    declined["too few stores"] += 1
                    continue
                cmd = patterns[p][4 * r + 2]
                ends_on_note = (GT_FIRST_NOTE
                                <= patterns[rows[end % len(rows)][0]][4 * rows[end % len(rows)][1]]
                                <= GT_LAST_NOTE)
                note_asks.setdefault((p, r), []).append(
                    (phase + lag, writes, current,
                     note_row_column_free(cmd, ends_on_note),
                     window_vibrato(sid, by_shift.get(current), index,
                                    counter - lag, det)))
                if cmd:
                    calls = (end - a) * frames * max(1, multiplier) - 1
                    note_cover[(p, r)] = max(note_cover.get((p, r), 0),
                                             calls)
                continue
            at = a + j0
            counter = base + first + at * frames
            phase = 0 if counter & 1 else 1
            high = _high_byte(sid, index)
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
                (phase + lag, writes, by_number[current], safe,
                 window_vibrato(sid, by_shift.get(current), index,
                                counter - lag, det)
                 if by_number[current] else None))

    pinned_active = [True]

    def take(table_of_asks):
        """{row: held program}, {row: the vibrato every play asks for or
        None}, and how many rows were refused."""
        got: Dict[tuple, tuple] = {}
        vibs: Dict[tuple, Optional[SkydiveVibrato]] = {}
        bad = 0
        for key, wants in table_of_asks.items():
            if (len(wants) == plays.get(key, 0)
                    and len({w[:4] for w in wants}) == 1 and wants[0][3]):
                got[key] = wants[0][:3]
                carried = {w[4] for w in wants}
                vibs[key] = carried.pop() if len(carried) == 1 else None
            else:
                bad += 1
        return got, vibs, bad

    taken, row_vib, mixed = take(asks)
    note_taken, note_vib, note_mixed = take(note_asks)
    tie_taken, tie_vib, tie_mixed = take(tie_asks)
    if not taken and not note_taken and not tie_taken:
        say(f"{sum(len(w) for w in asks.values())} window(s), none taken "
            f"({mixed} row(s) mixed or occupied)"
            + (f"; {sum(len(w) for w in note_asks.values())} on the note "
               f"row, none taken ({note_mixed} row(s) mixed or occupied)"
               if note_asks else "")
            + (f"; declined: {off_grid} orderlist(s) with rows that are "
               f"not whole frames" if off_grid else ""))
        return None

    instr_of: Dict[tuple, Optional[list]] = {}

    def assemble(carried: frozenset, compact: bool = False,
                 shared: Optional[tuple] = None, reuse: bool = False
                 ) -> Tuple[Optional[_Assembly], str]:
        """The programs laid out with the `carried` ones (program keys
        `(window, vibrato)`) written out and every other window held, on a
        copy of the speed table; the assembly or why not.

        `compact` lays the held alternating programs out in a third of the
        rows (`skydive_compact_calls`). `shared` is `(entries, starts)` of
        the wavetable with its identical tail programs shared
        (`compact_wave_tail`), the table the programs are laid out after.
        `reuse` lets a program go over the rows of the table's duplicate
        instrument blocks (`reusable_runs`) wherever it fits, before the
        table's end; without it nothing is placed there."""
        table = list(speed_table)
        base, base_starts = shared or (wave_entries, wave_starts)
        wave_used = len(base) if shared else wave_used_before
        free = ([list(run) for run in reusable_runs(shared)[0]]
                if reuse else [])
        overlay: Dict[int, Tuple[int, int]] = {}

        def place(prog: list, force: bool = False) -> Optional[int]:
            """The first row `prog` is laid at: a reclaimed run it fits,
            else the table's end (None past MAX_TABLELEN unless `force`,
            whose caller checks the end itself)."""
            at = take_from_runs(free, len(prog))
            if at is not None:
                overlay.update({at + i: e for i, e in enumerate(prog)})
                return at
            if (not force
                    and wave_used + len(entries) + len(prog)
                    > GT_MAX_TABLELEN):
                return None
            at = wave_used + len(entries) + 1
            entries.extend(prog)
            return at

        def instrument_program(number: int) -> Optional[list]:
            key = (shared is not None, number)
            if key not in instr_of:
                start = (base_starts[number - 1]
                         if number - 1 < len(base_starts) else 0)
                instr_of[key] = (instrument_calls(base, start)
                                 if start else [])
            return instr_of[key]

        def row_of(entry) -> int:
            if entry not in table:
                if len(table) >= GT_MAX_TABLELEN:
                    raise OverflowError
                table.append(entry)
            return table.index(entry) + 1

        def speed_index(k: int) -> int:
            entry = skydive_speed(k, multiplier)
            if entry is None:
                raise OverflowError
            return row_of(entry)

        def speed_frame(k: int, bias: int = 0) -> int:
            # The compact program's one step a frame: the -S1 rate.
            entry = skydive_speed(k, bias=bias)
            if entry is None:
                raise OverflowError
            return row_of(entry)

        def speed_row(magnitude: int) -> int:
            if not 0 <= magnitude <= SKYDIVE_MAX_SPEED:
                raise OverflowError
            return row_of((magnitude >> 8, magnitude & 0xFF))

        def key_of(want, vib):
            return (want, vib if (want, vib) in carried else None)

        def squeezes(want, key):
            return (compact and want[2] and key[1] is None and multiplier > 1)

        # A compact held program falls from Goattracker's note, so it is
        # keyed on how far that sits above the original's own. Windows on
        # different notes share one program (the table has no room for one
        # a note), and the program takes the largest of their biases: a fall
        # too deep by the difference to the others' is a few units of the low
        # byte, where one too shallow lets a vibrato tick carry over.
        # A window whose start is a measured cell pitch (`pinned`) is a
        # group of its own: its bias is hundreds of units, and the others
        # would take it as their largest.
        def is_pinned(pr):
            vib = row_vib.get(pr)
            return pinned_active[0] and vib is not None and vib.pinned

        group_bias: Dict[tuple, int] = {}
        for pr, want in taken.items():
            if (not is_pinned(pr)
                    and squeezes(want, key_of(want, row_vib.get(pr)))):
                group_bias[want] = max(
                    group_bias.get(want, 0),
                    anchor_bias(row_vib.get(pr), pinned_active[0]))

        def pinned_key(pr, want):
            """The key of a row whose window starts at a measured cell
            pitch, or None: the held program of its own group, entered
            `n` stores later -- the fall `n` high bytes deeper is the same
            program's store `k + n`, so it needs no speed rows of its own
            and is laid as a tail of that program (`share_program_tail`)
            with `writes - n` stores. Only where the high byte of the start
            then agrees with the cell's."""
            vib = row_vib[pr]
            gb = group_bias.get(want)
            if (gb is None
                    or not squeezes(want, key_of(want, vib))):
                return None
            n = (anchor_bias(vib) - gb + 0x80) // 0x100
            if (n < 1 or want[1] - n < 2
                    or (vib.anchor - gb - 0x100 * n) >> 8 != vib.base >> 8):
                return None
            return ((want[0], want[1] - n, want[2]), None, 0x100 * n + gb,
                    True)

        row_keys = {}
        for pr, want in taken.items():
            key = key_of(want, row_vib.get(pr))
            pk = pinned_key(pr, want) if is_pinned(pr) else None
            if pk is not None:
                row_keys[pr] = pk
            else:
                row_keys[pr] = key + (
                    group_bias.get(want, 0)
                    if squeezes(want, key) else 0,)
        entries: List[Tuple[int, int]] = []
        starts: Dict[tuple, int] = {}
        # Every row placed, by number: the tie windows' programs end in a
        # jump into the tail of one of these, or are one.
        placed_rows: Dict[int, Tuple[int, int]] = {}
        try:
            for key in sorted(set(row_keys.values()), key=_program_order):
                squeeze = (compact and key[0][2] and key[1] is None
                           and multiplier > 1)
                prog = skydive_program(
                    *key[0],
                    (lambda k, bias=key[2]: speed_frame(k, bias))
                    if squeeze else speed_index,
                    multiplier, vib=key[1], speed_row=speed_row,
                    **({"compact": True} if squeeze else {}))
                if len(key) > 3:
                    whole = prog
                    prog, point_at = share_program_tail(prog, placed_rows)
                    if point_at is None and prog == whole:
                        return None, "a cell-pitch program shares no tail"
                    if point_at is not None:
                        starts[key] = point_at
                        continue
                starts[key] = place(prog, force=True)
                placed_rows.update(
                    {starts[key] + i: e for i, e in enumerate(prog)})
        except OverflowError:
            return None, (f"speed table full or a step not a whole per-call "
                          f"rate at -S{multiplier}")
        if wave_used + len(entries) > GT_MAX_TABLELEN:
            return None, f"{len(entries)} wavetable step(s) past MAX_TABLELEN"

        # The note-row windows' programs, each placed where it fits.
        note_keys = {pr: key_of(want, note_vib.get(pr))
                     for pr, want in note_taken.items()}
        note_starts: Dict[tuple, int] = {}
        note_declined = {"instrument program loops": 0,
                         "instrument program conflicts": 0,
                         "speed table": 0, "wavetable full": 0}
        shape: Dict[tuple, Optional[list]] = {}
        for key in sorted(set(note_keys.values()), key=_program_order):
            (phase, writes, number), vib = key
            instr = instrument_program(number)
            if instr is None:
                note_declined["instrument program loops"] += 1
                shape[key] = None
                continue
            # The shape alone first (no speed row is registered for it):
            # which calls write, and how many the program has.
            shape[key] = skydive_note_row_calls(
                instr, phase, writes, by_number[number], lambda k: 0,
                multiplier, vib, lambda magnitude: 0)
            if shape[key] is None:
                note_declined["instrument program conflicts"] += 1
        uncovered = 0
        for pr in list(note_keys):
            calls = shape.get(note_keys[pr])
            if calls is None:
                del note_keys[pr]
            elif pr in note_cover and (None in calls
                                       or len(calls) < note_cover[pr]):
                del note_keys[pr]
                uncovered += 1
        if uncovered:
            note_declined["a command the program leaves a call"] = uncovered
        for key in sorted(set(note_keys.values()), key=_program_order):
            (phase, writes, number), vib = key
            before = list(table)
            try:
                prog = skydive_note_row_program(
                    instrument_program(number), phase, writes,
                    by_number[number], speed_index, multiplier, vib,
                    speed_row)
            except OverflowError:
                table[:] = before
                note_declined["speed table"] += 1
                continue
            at = place(prog)
            if at is None:
                table[:] = before
                note_declined["wavetable full"] += 1
                continue
            note_starts[key] = at
            placed_rows.update(
                {at + i: e for i, e in enumerate(prog)})

        # The tie windows' programs, each placed where it fits and sharing
        # the tail of a program already placed (`share_program_tail`).
        tie_keys = {pr: key_of(want, tie_vib.get(pr))
                    for pr, want in tie_taken.items()}
        tie_starts: Dict[tuple, int] = {}
        tie_declined_now = {"speed table": 0, "wavetable full": 0}
        tie_shared = 0
        for key in sorted(set(tie_keys.values()), key=_program_order):
            before = list(table)
            try:
                prog = skydive_program(*key[0], speed_index, multiplier,
                                       vib=key[1], speed_row=speed_row)
            except OverflowError:
                table[:] = before
                tie_declined_now["speed table"] += 1
                continue
            full = len(prog)
            prog, point_at = share_program_tail(prog, placed_rows)
            at = place(prog) if prog else wave_used + len(entries) + 1
            if at is None:
                table[:] = before
                tie_declined_now["wavetable full"] += 1
                continue
            tie_shared += full - len(prog)
            tie_starts[key] = point_at if point_at is not None else at
            placed_rows.update({at + i: e for i, e in enumerate(prog)})
        return _Assembly(entries, starts, row_keys, note_starts, note_keys,
                         note_declined, table, tie_starts, tie_keys,
                         tie_declined_now, tie_shared, overlay), ""

    # The layouts to try, the first that fits taken: as before, then the
    # held alternating programs in a third of the rows (above -S1), then the
    # identical programs at the table's end shared, then both. Everything
    # after the first is a rescue for a file that otherwise gets nothing, so
    # a file the first layout fits is untouched.
    sharing = None
    pointers: List[int] = []
    if wave_entries and wave_starts:
        pointers = list(wave_pointers or ())
        pointers += [pat[4 * r + 3] for pat in patterns
                     for r in range(len(pat) // 4)
                     if pat[4 * r + 2] == CMD_SETWAVEPTR]
        sharing = compact_wave_tail(wave_entries, wave_starts, pointers)
    reuse_cache: Dict[bool, tuple] = {}

    def reusable_runs(shared: Optional[tuple]) -> tuple:
        """(runs, starts, holes) of the table the programs are laid after
        (`shared`'s, else the one the plan was given): the rows its duplicate
        instrument blocks free (`note_rise.reclaimable_holes`) as runs of
        touching blocks, the instrument starts with those records repointed
        at the first copy, and the blocks. Empty where the plan was given no
        table or not the whole of it."""
        key = shared is not None
        if key not in reuse_cache:
            table_, starts_ = shared or (wave_entries, wave_starts)
            if (not table_ or not starts_
                    or (shared is None and len(table_) != wave_used_before)):
                reuse_cache[key] = ([], list(starts_ or ()), [])
            else:
                from .note_rise import reclaimable_holes
                holes, starts_to = reclaimable_holes(table_, starts_,
                                                     pointers)
                reuse_cache[key] = (coalesce_holes(holes), starts_to, holes)
        return reuse_cache[key]

    layouts = [(False, None)]
    if multiplier > 1:
        layouts.append((True, None))
    if sharing is not None:
        layouts.append((False, sharing))
        if multiplier > 1:
            layouts.append((True, sharing))
    held, reason = None, ""
    reuse = False
    # A window at a measured cell pitch is laid as the tail of its group's
    # program where it can be (`pinned_key`); where no layout takes that, it
    # is laid as any other window, from the entry its byte was rounded to.
    for pinned_active[0] in (True, False):
        if not pinned_active[0] and not any(
                v is not None and v.pinned for v in row_vib.values()):
            break
        reason, reuse = "", False
        for compact, shared in layouts:
            held, why_not = assemble(frozenset(), compact, shared)
            if held is not None:
                break
            reason = reason or why_not
        if held is None:
            # Nothing fits at the table's end: the rows of the duplicate
            # instrument blocks are free too, so lay out over those first.
            for compact, shared in layouts:
                if not reusable_runs(shared)[0]:
                    continue
                held, _why = assemble(frozenset(), compact, shared, True)
                if held is not None:
                    reuse = True
                    break
        if held is not None:
            break
    if held is None:
        say(f"{reason}, not emitted")
        return None
    # Carry the vibrato wherever it fits, the programs most rows share first,
    # and never at the cost of a note-row program the held layout placed.
    use: Dict[tuple, int] = {}
    for rows_of, vibs in ((taken, row_vib), (note_taken, note_vib),
                          (tie_taken, tie_vib)):
        for pr, want in rows_of.items():
            if vibs.get(pr) is not None:
                use[(want, vibs[pr])] = use.get((want, vibs[pr]), 0) + 1
    best, carried = held, frozenset()
    for key in (sorted(use, key=lambda k: (-use[k], _program_order(k)))
                if CARRY_VIBRATO else ()):
        trial, _ = assemble(carried | {key}, compact, shared, reuse)
        if ((trial is None or trial.placed < held.placed) and not reuse
                and reusable_runs(shared)[0]):
            # It does not fit at the table's end, or only at a note-row or
            # tie program's cost: the rows of the duplicate instrument blocks
            # are free too. From here every layout is over them.
            again, _ = assemble(carried | {key}, compact, shared, True)
            if again is not None and again.placed >= held.placed:
                trial, reuse = again, True
        if (trial is not None
                and trial.placed >= held.placed
                and (CARRY_BUDGET is None
                     or (len(trial.entries) - len(held.entries)
                         <= CARRY_BUDGET[0]
                         and len(trial.table) - len(held.table)
                         <= CARRY_BUDGET[1]))):
            best, carried = trial, carried | {key}
    entries, starts = best.entries, best.starts
    note_starts, note_declined = best.note_starts, best.note_declined

    out = [list(pat) for pat in patterns]
    edited = 0
    for pr, key in sorted(best.row_keys.items()):
        p, r = pr
        trial = list(out[p])
        trial[4 * r + 2] = CMD_SETWAVEPTR
        trial[4 * r + 3] = starts[key]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            continue
        out[p] = trial
        edited += 1
    note_edited = 0
    for pr, key in sorted(best.note_keys.items()):
        p, r = pr
        if key not in note_starts:
            continue
        trial = list(out[p])
        trial[4 * r + 2] = CMD_SETWAVEPTR
        trial[4 * r + 3] = note_starts[key]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            continue
        out[p] = trial
        note_edited += 1
    tie_edited = 0
    for pr, key in sorted(best.tie_keys.items()):
        p, r = pr
        if key not in best.tie_starts:
            continue
        trial = list(out[p])
        trial[4 * r + 2] = CMD_SETWAVEPTR
        trial[4 * r + 3] = best.tie_starts[key]
        if (_gw_pulse.packed_pattern_size(_gw_pulse.pattern_rows(trial))
                > PACKED_PATTERN_LIMIT):
            continue
        out[p] = trial
        tie_edited += 1
    if not edited and not note_edited and not tie_edited:
        return None
    speed_table[:] = best.table
    skipped = ", ".join(f"{n} {why}" for why, n in declined.items() if n)
    note_skipped = ", ".join(f"{n} {why}" for why, n in note_declined.items()
                             if n)
    tie_skipped = ", ".join(
        f"{n} {why}" for why, n in {**tie_declined,
                                    **best.tie_declined}.items() if n)
    say(f"{edited} window row(s) on {len(records)} record(s) "
        f"{sorted(records)}, {len(starts)} program(s) "
        f"{sorted(k[0] for k in starts)}, {len(entries)} wavetable step(s)"
        + (f", {len(carried)} carrying the vibrato on "
           f"{sum(k[1] is not None for k in best.row_keys.values())} row(s) "
           f"and {sum(k[1] is not None for k in best.note_keys.values())} "
           f"on the note row" if carried else "")
        + (f", compact (3 rows a pair of frames)" if compact else "")
        + (f", {len(wave_entries) - len(shared[0])} row(s) made by sharing "
           f"identical programs at the end of the table" if shared else "")
        + (f", {len(best.overlay)} row(s) laid over the rows of duplicate "
           f"instrument blocks" if best.overlay else "")
        + (f"; {mixed} row(s) mixed or occupied" if mixed else "")
        + (f"; declined: {skipped}" if skipped else "")
        + (f"; on the note row: {note_edited} row(s), {len(note_starts)} "
           f"program(s) {sorted(k[0] for k in note_starts)}"
           + (f", {note_mixed} row(s) mixed or occupied"
              if note_mixed else "")
           + (f", declined: {note_skipped}" if note_skipped else "")
           if note_asks else "")
        + (f"; after a tie: {tie_edited} row(s), {len(best.tie_starts)} "
           f"program(s), {best.tie_shared} row(s) saved by jumping into a "
           f"placed program's tail"
           + (f", {tie_mixed} row(s) mixed or occupied" if tie_mixed else "")
           + (f", declined: {tie_skipped}" if tie_skipped else "")
           if tie_asks or tie_skipped else ""))
    base_out, starts_out = (shared[0], shared[1]) if shared else (None, None)
    if best.overlay:
        # Programs went over duplicate blocks' rows: the table to append to
        # has them written in, and the records of the blocks they took point
        # at the first copy of the block instead.
        _runs, starts_to, holes = reusable_runs(shared)
        base_out = list(shared[0] if shared else wave_entries)
        for row, entry in best.overlay.items():
            base_out[row - 1] = entry
        taken_blocks = {first for first, n in holes
                        if any(first <= row < first + n
                               for row in best.overlay)}
        starts_out = [to if was in taken_blocks else was
                      for was, to in zip(shared[1] if shared else wave_starts,
                                         starts_to)]
    return SkydivePlan(patterns=out, entries=entries,
                       base=base_out, starts=starts_out)
