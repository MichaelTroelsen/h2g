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

**Early classes: the duration-gated update** (Zoolook; `_duration_gate`,
`EARLY_VERIFIED`). Its swing is gated on the note's LENGTH (`$4263 LDA $44C7,X /
AND #$1F / CMP #$03 / BCC`), not its age, so the first update after the fetch
frame already shows it: `first` = 1, where the age gate's is 4 (`note_phases`
carries it per note, `classify` reads the offsets from it). Frame 1 is ahead of
the note's second pattern row (a row of 10-11 frames is call 30-32 at -S3), so the
chain a second row starts cannot carry the phase: a class is the note's own
INSTRUMENT, a copy of the record whose program is the record's events, the
swing's offset on frame 1 (a `$F1`/`$F2` of up to two depths, `A`) and a jump
into a shared EXPLICIT triangle -- `bound` ups and `bound` downs of one depth,
a frame each and a delay row between (`early_loop`), entered at the row of the
note's phase (`cycle_rotation`, no `vibtime`, so no free calls to find). A
record whose program has a row after frame 1 (Zoolook's byte `$1A` record, which re-gates
at call 15) and a note whose next fetch is a tie (`EARLY_SKIP_TIED`) keep the
record's own vibrato. Needs a gap of `m - 1 >= 2` calls between steps: -S3 and
up.

Two corrections the dialect needed, measured against siddump of Zoolook
(`fidelity.py -t 180`, v0.5.685; historical, C:/t/listen-r2-zoolook):

* **The new-song call is no update** (`note_phases` counted frame 0 of the
  voices' history). A file whose initial instrument carries a vibrato byte
  stepped the counter once too often: every note of Zoolook's first 4621
  frames sat one step ahead (5306 of 6118 direction signs agreed over 568
  notes), and with the call left out 6118 of 6118. The age-gated pass reads it
  too: Saboteur_II (`vibrato_phase` is in its preset) moves, `tiefr` 83.7 ->
  84.4%, `travel` .776 -> .790, `bend` .805 -> .821, `cents` +0.1 pp, `aud`
  +0.0001, `wave` -0.0001; ACE_II and Trans-Atlantic are unchanged byte for
  byte, and forced on IK_plus it reads `cents` 92.5 -> 94.0%, `travel` .977
  -> .997, `aud` +0.0002, `loud` -0.0003.
* **A class costs an instrument, and the 62 are shared** with the
  previous-class firstwave clones (`prev_class_firstwave`, second build), which
  are made most-used first up to the same limit: Zoolook's 62 are full without
  this pass (23 clones) and with three classes it makes 20 (seven: 16). `EARLY_MAX_CLONES`
  is the sweep (its comment).

Measured, Zoolook `-t 180 --presets --sound`, `vibrato_phase` forced, three
classes (v0.5.685; historical): `tiefr` 85.1 -> 90.7%, `cents` 93.7 -> 96.1%,
`tie` 0.864 -> 0.924, `depth` 0.61 -> 0.66, `travel` 0.63 -> 0.71, `bend`
0.667 -> 0.682, `aud` 0.9067 -> 0.9097, `loud` 0.9694 -> 0.9703; `wave` 99.43
-> 99.35% (the displaced firstwave clones). 223 of the 568 vibrating notes are
taken (the rest are tied, in a repeat whose plays name different classes, or
of the records left out).

**At -S1** (`multiplier == 1`; Trans-Atlantic_Balloon_Challenge, whose clock
`_clock_cells` reads: outer 109, inner 2, three frames a row, the outer gate
skipping one call in 113) the packed player runs one call a frame, a wavetable
command row takes the whole call, and the zero-speed steps of the multispeed
design have no free calls to sit on (the row is three calls, the swing starts
on the fifth). The class is then `(record, j, A)`: `j` the row of an explicit
cycle (`bound` `$F1` ups, `bound` `$F2` downs, one depth each, no `vibtime`)
the chain jumps into (`cycle_rotation`), `A` the move on frame 4 as before.
Two things follow from the call being the program's:

* a program that loops past its note starves the pattern effect of whatever
  follows: Trans-Atlantic voice 0's tied notes slide on their rest rows, and
  an endless program held 11897 where the original slid 10000 -> 11380 (the
  held-vibrato probe, `vibrato_hold` forced at -S1: `cents` .973 -> .885,
  voices 0 and 1 `$0879`, 817 and 784 of 1249 frames over 50 cents). A next
  NOTE row that is no tie restarts the wavetable and ends the program by
  itself (stopping it on the row before cost a short note its last three
  frames: travel .64 against .79 without); where a pitch command sits on or
  between the note's rows and that next note, the program is stopped,
  `CMD_SETWAVEPTR 0`, on the row before it, which must be a free row two or
  more after the note's, and a note that needs the stop and cannot have it
  keeps the record's per-call vibrato;
* a note with a pitch command on any of its rows is left out (`note_phases(
  slides=True)`), and the record-level held program (`vibrato_hold`) stays
  multispeed-only for the same reason.

Not recovered: a tied note's slide and vibrato cannot both run on one call at
-S1, so the original's vibrato under a slide stays unsounded.
"""
from fractions import Fraction
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

# The pass at -S1 (module docstring, "At -S1"). `ALLOW_S1` False restores the
# `multiplier > 1` gate; `STOP_AT_FETCH` False leaves a note's program running
# past its note (tests/test_vibrato_phase_s1.py pins both).
ALLOW_S1 = True
STOP_AT_FETCH = True
# The age at which the classic update starts to write the swing: `$E289
# LDA $E587,X / CMP #$04 / BCC` in ACE_II. The update runs from frame 1.
FIRST_ACTIVE = 4
# A duration-gated update (Zoolook, `_duration_gate`) writes from frame 1: the
# fetch frame (0) runs none of the update, the next one steps and shows.
EARLY_FIRST_ACTIVE = 1
# The duration-gated files the counter model has been read against a trace of
# the original on, by PSID title. 23 corpus files carry the dialect
# (`_duration_gate`) and the pass reads the clock and counter of three of them
# (Chain_Reaction, Thanatos, Zoolook); the model agrees with the traced
# direction sequence on every frame of Zoolook's 568 vibrating notes (6118 of
# 6118 steps) and NOT on Chain_Reaction's first 4621 frames (record `$0B`:
# 2008 of 2793 steps, every note one step ahead, as Zoolook's were before the
# new-song call stopped counting; its first fetch is call 2 where Zoolook's is
# call 1, so its start-up runs another call that is no update). The pass is
# keyed to what has been read; `vibrato_phase` forced on Chain_Reaction with
# the gate open reads `aud` -0.0044, `cents` -0.74 pp, `tiefr` +2.1 pp.
EARLY_VERIFIED = frozenset({"Zoolook"})
# An early class is one instrument, and the 62 instruments are shared with every
# pass that clones a record after this one (`prev_class_firstwave` is built on
# the same limit): each class displaces the least-used of its variants. Swept
# on Zoolook, `-t 180 --presets --sound`, `vibrato_phase` forced
# (C:/t/listen-r2-zoolook, v0.5.685; historical): 2 classes `aud` +0.0000, 3
# `aud` +0.0031 `loud` +0.0009 `tiefr` 85.1 -> 90.7%, 4 (the fourth is
# `(10, 0, -1)`) `aud` +0.0001 `loud` -0.0004, 5 and 7 flat on `aud` with
# `wave` -0.0013 / -0.0018. The cap is that sweep, not a derivation.
EARLY_MAX_CLONES = 3
# A note whose next fetch is a tie (a pitch command) goes on past that fetch,
# where the original's update stalls one frame and the shared loop does not:
# its first segment is exact and the rest is a frame off. Left to the record's
# own vibrato (Zoolook's `$28A8`: 3 notes of 85 frames each).
EARLY_SKIP_TIED = True
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


def _duration_gate(sid: SidFile, det: Detection) -> bool:
    """Whether the update writes its swing from the FIRST update after a fetch
    and only gates it on the note's length (Zoolook `$4263`: `LDA $44C7,X /
    AND #$1F / CMP #$03 / BCC`): the dialect `VibratoGate.form == "duration"`
    names. There is no age to wait for, so the swing shows from frame 1."""
    gate = det.vibrato_gate
    if gate is None or gate.form != "duration" or gate.gate is None:
        return False
    site = _find_vibrato_site(sid, det)
    if site is None:
        return False
    window = bytes(sid.data[site[1]:site[1] + 0x140])
    shape = bytes([0x29, 0x1F, 0xC9, gate.gate, 0x90])    # AND #$1F / CMP / BCC
    at = window.find(shape)
    return at >= 3 and window[at - 3] == 0xBD      # LDA abs,X


def first_active(sid: SidFile, det: Detection) -> Optional[int]:
    """The frame, counted from a note's fetch, on which the original's update
    first writes its swing: `FIRST_ACTIVE` behind an age gate,
    `EARLY_FIRST_ACTIVE` behind a duration gate of a file `EARLY_VERIFIED`
    names, None where neither is read."""
    if _age_gate(sid, det):
        return FIRST_ACTIVE
    if sid.name in EARLY_VERIFIED and _duration_gate(sid, det):
        return EARLY_FIRST_ACTIVE
    return None


def note_phases(blob: bytes, sid: SidFile, det: Detection,
                slides: bool = False) -> list:
    """Every vibrating note of the first lap, with the original's triangle:
    `{place, record, byte, bound, shift, life, frame, offsets}` where `place`
    is `(track, orderlist index, play, row)` and `offsets[j]` (j = 1 .. life
    - 1) the swing, in depths about the note, on frame `j` after the fetch.
    Empty where the clock, the counter or the age gate is not read.

    `slides` leaves out a note any of whose rows, up to the next fetch, carries
    a pitch command: a wavetable command row takes the whole play call, so at
    -S1 a program that steps every call starves a pattern slide (Trans-Atlantic
    voice 0's `$0879` notes slide on their rest rows)."""
    cells_at = _uv.counter_cells(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    clock = _clock_cells(sid, 0)
    swing_from = first_active(sid, det)
    if (cells_at is None or speeds is None or clock is None
            or swing_from is None or blob[HEADER_LEN] != 1
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
        for f in range(1, f_first):
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
            if slides and any(lane[r][3] in _PITCH_COMMANDS
                              for r in range(idx, end_row)):
                continue
            life = frames[end_row] - f0
            tie_next = lane[end_row][3] in _PITCH_COMMANDS
            if life < swing_from + 2:
                continue
            bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
            offs = {j: after[f0 + j][0] - (bound >> 1) for j in range(1, life)}
            out.append(dict(place=place, record=rec, byte=byte, bound=bound,
                            shift=byte & VIBRATO_SHIFT_MASK, life=life,
                            frame=f0, offsets=offs, first=swing_from,
                            tie_next=tie_next))
    return out


def cycle_rotation(bound: int, dirs: List[int]) -> Optional[int]:
    """The least `j` in 0 .. 2 * bound - 1 whose step of the explicit cycle
    (`bound` ups, then `bound` downs: the player's triangle) starts `dirs`
    when entered at row `j`, or None."""
    cyc = [1] * bound + [-1] * bound
    for j in range(2 * bound):
        if all(cyc[(j + i) % (2 * bound)] == d for i, d in enumerate(dirs)):
            return j
    return None


def classify(note: dict, explicit: bool = False) -> Optional[Tuple[int, int]]:
    """`(n, A)` for a note: the null count whose direction sequence matches
    the original's from frame 5 on, and the offset it is at on frame 4.

    `explicit` (-S1, `phase_classic_vibrato`): `n` is instead the row of the
    explicit up/down cycle the note's program jumps into (`cycle_rotation`),
    which takes no null steps to set the phase."""
    offs, bound, life = note["offsets"], note["bound"], note["life"]
    first = note.get("first", FIRST_ACTIVE)
    if first not in offs:
        return None
    dirs = [offs[j] - offs[j - 1] for j in range(first + 1, life)
            if j in offs and j - 1 in offs][:2 * bound]
    if any(x not in (-1, 1) for x in dirs):
        return None
    n = (cycle_rotation(bound, dirs) if explicit
         else rotation(bound, dirs))
    return None if n is None else (n, offs[first])


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


def early_frame_rows(calls: int) -> int:
    """Rows one frame of the explicit loop takes: the step and the delay that
    holds the other `calls - 1` calls."""
    gap: List[tuple] = []
    _wait(gap, [None], calls - 1)
    return 1 + len(gap)


def early_loop(bound: int, calls: int, first_row: int) -> List[tuple]:
    """The shared explicit triangle of an early class (`early_rows`): `bound`
    ups and `bound` downs of one depth, a frame each, no `vibtime`, closing in
    the jump to `first_row`. A class jumps into it at the row of its phase."""
    rows: List[tuple] = []
    for i in range(2 * bound):
        rows.append(((_SYM_UP if i < bound else _SYM_DOWN), 1))
        _wait(rows, [None], calls - 1)
    rows.append((GT_WAVE_JUMP, first_row))
    return rows


def early_after(kept: Dict[int, tuple], end_t: int, bound: int, rot: int,
                calls: int, first: int) -> int:
    """The loop phase a class enters at: its rotation `rot` advanced past the
    frames the class program unrolls itself (none while the record's program
    has no row after frame `first`)."""
    return rot % (2 * bound)


def early_rows(kept: Dict[int, tuple], end_t: int, bound: int, rot: int,
               calls: int, first: int, move: Optional[tuple]) -> List[tuple]:
    """An early class's program, WITHOUT the closing jump into the shared loop:
    the record's events with `move` (the swing's offset on frame `first`, a
    `$F1`/`$F2` of up to two depths) on frame `first`'s first call, an event
    that falls on it one call after, up to the first call of frame `first + 1`
    where the loop's step on the original's phase takes over. `_Unsupported`
    where a record's row falls after that (merging it would move the
    swing the loop carries)."""
    t_a = first * calls
    t_l = t_a + calls
    if any(t >= t_l for t in kept):
        raise _Unsupported()
    tl = {t: row for t, row in kept.items() if t < t_a}
    if move is not None:
        tl[t_a] = move
    for t, row in sorted((t, r) for t, r in kept.items() if t_a <= t < t_l):
        u = t
        while u in tl:
            u += 1
        if u >= t_l:
            raise _Unsupported()
        tl[u] = row
    return _lay_out(tl, 0, t_l, None)


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


def _quiet_to_note(rows: Optional[list]) -> Optional[bool]:
    """Whether the rows reach their first NOTE with no pitch command on or
    before it (True), meet one (False), or hold no note (None)."""
    if rows is None:
        return None
    for n, _k, c in rows:
        if c in _PITCH_COMMANDS:
            return False
        if GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
            return True
    return None


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
    if (m < (1 if ALLOW_S1 else 2) or det.vibrato_offset is None
            or det.triangle_vibrato is not None
            or det.table_vibrato is not None or det.vibrato_dwell
            or det.vibrato_shift_extra or effective_gate_skip(sid)):
        return blob
    try:
        instr_at, tables_at, patt_at, pats = _layout(blob)
    except ValueError:
        return blob
    if bytes(blob[:4]) != b"GTS5":
        return blob
    notes = note_phases(blob, sid, det, slides=(m == 1))
    if not notes:
        return blob
    first = notes[0]["first"]
    # A duration-gated update (`_duration_gate`) shows its swing from frame 1,
    # before the note's second pattern row: the class is the instrument itself
    # (`early_rows`), not a chain a second row starts. Its rows need a gap of
    # `m - 1` calls between two steps, and one call is no delay row.
    early = first == EARLY_FIRST_ACTIVE
    if early and m < 3:
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
    t_a = first * m
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
        kept_ev = _kept_events(events)
        if m == 1 and (end_t > t_l or any(t >= t_l for t in kept_ev)):
            # The explicit cycle is a bare loop: an event after frame 4
            # would have to be merged into it.
            continue
        taken[k] = dict(kept=kept_ev, end_t=end_t, bound=bound,
                        shift=shift, byte=byte, wptr=wptr)

    # Every class, its weight in frames and its notes.
    classes: Dict[tuple, dict] = {}
    for note in notes:
        k = note["record"]
        if early and EARLY_SKIP_TIED and note.get("tie_next"):
            continue
        cls = (classify(note, explicit=(m == 1 or early))
               if k in taken else None)
        if cls is None or note["byte"] != taken[k]["byte"]:
            continue
        key = (k, cls[0], cls[1])
        c = classes.setdefault(key, dict(weight=0, notes=[]))
        c["weight"] += (note["life"] if note["frame"] < WEIGHT_WINDOW
                        else note["life"] * LATE_WEIGHT)
        c["notes"].append(note["place"])

    # The second pattern row's first call: the program time `CMD_SETWAVEPTR`
    # on it takes effect at (`t_row`), the row clock in calls.
    t_row = None
    if not early:
        speeds = _gw_tempo.find_song_speeds(sid, det)
        row_len = speeds.exact_row(0) if speeds is not None else None
        if (m == 1 and speeds is not None and speeds.frames_for(0)
                and row_len is not None and row_len.denominator != 1):
            # At -S1 our row is the whole number of calls the tempo says; the
            # outer gate's rare skipped call is the original's, which the
            # re-grid (`regrid_phase`) takes up, so the corrected row's
            # fraction is no part of where OUR second pattern row falls.
            row_len = Fraction(speeds.frames_for(0))
        if row_len is None or (row_len * m).denominator != 1:
            return blob
        # The note's call 0 runs no wavetable row: program time is the call
        # - 1.
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
        if early:
            return (n, a), 0
        if m == 1:
            return 0, 0
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
        if early:
            return early_rows(info["kept"], info["end_t"], info["bound"],
                              n, m, first, moves.get(a))
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

    def entry_row(key):
        """The row of the shared loop a class's chain jumps to: its cycle
        rotation at -S1, the loop's first row otherwise."""
        if early:
            return early_entry(key[0], key[1])
        return key[1] if m == 1 else 0

    def loop_key(info):
        if early:
            return ((), 0, info["bound"], info["shift"])
        tail = tuple(sorted((t - t_l, row) for t, row in info["kept"].items()
                            if t >= t_l))
        return (tail, max(0, info["end_t"] - t_l), info["bound"], info["shift"])

    def loop_rows_for(lkey, first_row):
        tail, end, bnd, _s = lkey
        if early:
            return early_loop(bnd, m, first_row)
        if m == 1:
            return ([(_SYM_UP, 1)] * bnd + [(_SYM_DOWN, 1)] * bnd
                    + [(GT_WAVE_JUMP, first_row)])
        return _held_rows(dict(tail), end, (_SYM_STEP, 0), 0, m, first_row)

    def early_entry(k, j):
        """The row of the shared loop a class's program jumps to: the frame
        after its unrolled steps (`early_rows`), `early_frame_rows` rows a
        frame."""
        info = taken[k]
        return (early_after(info["kept"], info["end_t"], info["bound"], j, m,
                            first) * early_frame_rows(m))

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
            pending[key] = chain_spec(key) + [(GT_WAVE_JUMP,
                                               ("L", None, entry_row(key)))]
        except _Unsupported:
            continue
    loops: Dict[tuple, int] = {}
    programs: Dict[tuple, List[dict]] = {}
    bases: Dict[tuple, int] = {}                # (record, nulls) -> stem row
    stems: Dict[tuple, int] = {}                # stem rows -> first row
    made: Dict[tuple, int] = {}                 # class -> chain's 1-based row
    new_records: List[tuple] = []               # ((record, nulls), bytearray)
    while (pending and count + len(bases) < _MAX_RECORDS
           and (not early or len(bases) < EARLY_MAX_CLONES)):
        best = None
        for key, rows in pending.items():
            info = taken[key[0]]
            nb, _n2 = split(key)
            lkey = loop_key(info)
            shared = share(rows[:-1] + [(GT_WAVE_JUMP,
                                         ("L", lkey, entry_row(key)))], lkey)
            extra = 0
            if lkey not in loops:
                try:
                    extra = len(loop_rows_for(lkey, 1))
                except _Unsupported:
                    continue
            if not early and (key[0], nb) not in bases:
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
        if not early and (key[0], nb) not in bases:
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
                right = (loops[lkey] + right[2]
                         if right[0] == "L" else right[1])
            rows_c.append((left, right))
        wtbl.extend(concrete(rows_c, info))
        programs.setdefault(lkey, []).append(dict(rows=shared, at=at))
        made[key] = at
        if early:
            # The class is its own instrument: the record, started at the
            # class's program.
            rec = bytearray(recs[key[0] - 1])
            rec[_WAVE_AT] = at
            rec[_STBL_AT] = 0
            rec[_VIBDELAY_AT] = 0
            bases[(key[0], nb)] = at
            new_records.append(((key[0], nb), rec))
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
    stop_rows: Dict[Tuple[int, int], Dict[int, int]] = {}
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
            stops: Dict[int, int] = {}
            for r, val in (maps[0] or {}).items():
                nxt = rows[r + 1] if r + 1 < len(rows) else None
                if early:
                    mapping[r] = val
                elif (nxt is not None and nxt[2] == 0
                        and not GT_FIRST_NOTE <= nxt[0] <= GT_LAST_NOTE):
                    if m == 1 and STOP_AT_FETCH:
                        # At -S1 the program steps on every call and so
                        # starves the pattern effect of whatever follows (a
                        # tie's slide, a slide on a rest row). A next NOTE
                        # row that is no tie restarts the wavetable and ends
                        # the program by itself; where a pitch command is in
                        # the way the program is stopped, `CMD_SETWAVEPTR 0`,
                        # on the row before that note, which must be free.
                        note_at = next((q for q in range(r + 1, len(rows))
                                        if GT_FIRST_NOTE <= rows[q][0]
                                        <= GT_LAST_NOTE), None)
                        if note_at is None:
                            # The note runs to the pattern's end: what
                            # follows is the pattern again (a repeat) and
                            # the next entry; both must reach a note
                            # with no pitch command on the way.
                            follow = [entries[e + 1][4]
                                      if e + 1 < len(entries) else None]
                            if repeat > 1:
                                follow.append(rows)
                            if any(_quiet_to_note(f) is not True
                                   for f in follow):
                                lost["next row"] += 1
                                continue
                        elif any(rows[q][2] in _PITCH_COMMANDS
                                 for q in range(r + 1, note_at + 1)):
                            stop = note_at - 1
                            if (stop < r + 2 or rows[stop][2]
                                    or stop in stops.values()
                                    or stop in {x + 1 for x in mapping}):
                                lost["next row"] += 1
                                continue
                            stops[r] = stop
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
            stop_rows[(ti, i)] = stops
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
            if not early:
                body[(r + 1) * 4 + 2] = CMD_SETWAVEPTR
                body[(r + 1) * 4 + 3] = chain
        for stop in stop_rows.get(_t[:2], {}).values():
            body[stop * 4 + 2] = CMD_SETWAVEPTR
            body[stop * 4 + 3] = 0
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
            f"({named} notes in their classes {sorted(made)}, lost to "
            + ", ".join(f"{k} {v}" for k, v in lost.items()) + "), "
            f"{len(new_patterns)} pattern(s) copied, wavetable "
            f"{len(wtbl)}/{GT_MAX_TABLELEN} rows")
    return bytes(res)
