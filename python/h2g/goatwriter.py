"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import List, Optional, Tuple

from .detect import (Detection, FILTER_ENABLE_BIT, decode_wave_program,
                     TRIANGLE_VIBRATO_GATE, TRIANGLE_VIBRATO_MAX_SHIFT,
                     TRIANGLE_VIBRATO_PEAK, TRIANGLE_VIBRATO_PERIOD,
                     VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     VIBRATO_SHIFT_MASK)
from .sidfile import GT_FREQ0, SidFile

HEADER_LEN = 0x64
FIELD_LEN = 0x20

# Output format. Both are accepted by GoatTracker 2.77 (src/gsong.c:189,249).
#
# GTS2 is the 3-table format the original VB6 tool wrote, and what the
# byte-exact Commando fixture encodes -- hence the default.
#
# GTS5 is the modern 4-table format. Prefer it for anything you intend to open
# in GoatTracker: the GTS2 *import* path contains a buffer overrun that GTS5
# avoids entirely. gsong.c:306 runs
#     for (d = 0; d < length; d++)  switch (pattern[c][d*4+2]) ...
# where `length` is already rows*4 *bytes*, but `d` indexes rows -- so it walks
# 4x too far, up to pattern[c][1503] in a row of MAX_PATTROWS*4+4 == 516 bytes,
# writing into following patterns wherever it finds command $1/$2/$3/$4/$0E.
# Those are exactly the portamento commands this converter emits. The GTS3/4/5
# loader has no such conversion loop.
FORMAT_GTS2 = "gts2"
FORMAT_GTS5 = "gts5"
FORMATS = (FORMAT_GTS2, FORMAT_GTS5)
DEFAULT_FORMAT = FORMAT_GTS2

# MAX_TABLES in gcommon.h is 4 (WTBL, PTBL, FTBL, STBL). The GTS2 loader reads
# MAX_TABLES-1 and derives the speed table by converting instrument bytes;
# GTS3+ stores all four.
GT_TABLES_GTS2 = 3
GT_TABLES_GTS5 = 4

# Goattracker limits, from goattracker2 src/gcommon.h.
GT_MAX_INSTR = 64      # MAX_INSTR
GT_MAX_TABLELEN = 255  # MAX_TABLELEN -- ltable/rtable are this many bytes each

# Wave/pulse table entries emitted per instrument.
WAVE_ENTRIES_PER_INSTR = 5
PULSE_ENTRIES_PER_INSTR = 2
# A pulse-table left side is a tick count only in 01-7F; 80 and above are read
# as "set pulse width" and FF as a jump (readme.txt:887-891). The right side is
# a signed 8-bit speed (gplay.c:888-900), so a positive step tops out at 7F too.
GT_MAX_PULSE_TICKS = 0x7F
GT_MAX_PULSE_SPEED = 0x7F

# The binding constraint is NOT MAX_INSTR. Each instrument costs 5 wavetable
# entries, and the wavetable's stored length is a single byte bounded by
# MAX_TABLELEN, so at most 255//5 == 51 instruments can be represented at all.
# Raising the clamp to GT_MAX_INSTR (64) would need 320 entries: the length byte
# would wrap and Goattracker would read a truncated table over the following
# section. Keep this at or below MAX_REPRESENTABLE_INSTRUMENTS.
MAX_REPRESENTABLE_INSTRUMENTS = GT_MAX_TABLELEN // WAVE_ENTRIES_PER_INSTR  # 51

# 50 is what the original VB6 tool used, and what the byte-exact Commando
# fixture encodes. It is one below the representable maximum; leave it alone
# unless you are deliberately changing output.
MAX_INSTRUMENTS = 50

assert MAX_INSTRUMENTS <= MAX_REPRESENTABLE_INSTRUMENTS

# Wavetable left-side encodings, readme.txt:790-792. $F0-$FE execute a pattern
# command with the right side as its parameter; $F0 + CMD_PORTAUP (1) is a
# portamento up, and $FF is a jump whose right side is the target position.
WAVECMD_PORTAUP = 0xF1
WAVECMD_PORTADOWN = 0xF2

# Waveform value $80 is noise with the gate bit clear -- literally the `LDA
# #$80 / STA $D404,Y` the drum block ends on. A gated-off voice keeps its last
# waveform latched, so this is also what the voice shows until its next note.
WAVE_NOISE_GATEOFF = 0x80
# Speed-table left side with bit $80 set selects a realtime-calculated,
# note-relative speed; the right side is then a shift applied to the semitone
# interval at the current note (readme.txt:171-174, gplay.c:539-547). Shift 2
# is a quarter semitone per frame == one semitone per four frames.
SPEED_NOTE_RELATIVE = 0x80
RISE_SHIFT = 2

# A note-relative speed is the semitone interval shifted right by the table's
# right byte; past 15 the interval is gone whatever the note, so a shift beyond
# this is a vibrato with no depth rather than a very small one.
GT_MAX_VIB_SHIFT = 0x0F
# gplay.c:769-772 counts the delay down and only acts at 1, so 1 is "start on
# the note". None of the players this reads has a delay before the vibrato.
VIBRATO_DELAY = 0x01

# An absolute speed-table entry is (hi, lo) of a frequency step applied once
# per *play call* (gplay.c:562, inside the per-call TICKNEFFECTS at :748/758).
# The drum block decrements the frequency HIGH byte once per *frame*
# ($1387-$138D: `LDA counter / DEC counter / STA $D401,Y`), which is exactly
# 256 units per frame.
#
# Those two units are the same only at `gt2reloc -S1`. Under -S2 a call is
# half a frame, so a step written as 256 travels 512 units per frame -- twice
# the player's -- and under -S3, three times. `_drum_speed` divides the
# per-frame step by the multiplier the file will be packed at, which is what
# makes the emitted sweep the player's sweep at any -S value.
#
# siddump ignores the PSID speed field (siddump.c:309/325), so no number in
# FIDELITY.md can move on this; RetroDebugger can see it.
DRUM_SPEED_PER_FRAME = 0x0100


def _drum_speed(multiplier: int = 1) -> tuple:
    """`DRUM_SPEED_PER_FRAME` as a per-call (hi, lo) step at `-S{multiplier}`.

    Floor rather than round, and never zero: a step of zero is a sweep that
    does not move, which is further from the player than one 1/256th slow.
    """
    step = max(1, DRUM_SPEED_PER_FRAME // max(1, multiplier))
    return (step >> 8) & 0xFF, step & 0xFF


# The multiplier-1 value, kept as a name because the wavetable tests and the
# method doc both quote it.
DRUM_SPEED = _drum_speed(1)


# Units of headroom required above the exact no-underflow bound before a second
# sweep step is written. _note_freq floors a formula where Goattracker's own
# table rounds, so the two can disagree by a unit or two; 32 is far more than
# that, and costs no corpus coverage (184 of 192 drum instruments still deepen).
DRUM_DEEPEN_MARGIN = 32

# Record byte +8, the waveform Goattracker writes on a note's first frame.
#
# `$09` is testbit plus gate -- Goattracker's own editor default and what this
# tool has always written. The testbit holds the oscillator's phase accumulator
# and the noise LFSR at zero, so the frame it occupies is *silent*, and it
# occupies one on every note. Hubbard's players spend 4273 such frames across
# 12 of the 83 corpus files; ours spent 9179 across 79.
#
# `$FF` is the alternative gplay.c:355-363 offers: a firstwave of `$FE` or above
# is read as a gate value and assigned straight to `cptr->gate`, leaving
# `cptr->wave` alone. So `$FF` opens the gate -- the note still attacks -- and
# the frame keeps whatever waveform was already there instead of going quiet.
# Anything below `$FE` is written to the waveform and forces the gate on.
FIRSTWAVE_TESTBIT = 0x09
FIRSTWAVE_GATE_ONLY = 0xFF


def _note_freq(note: int) -> int:
    """Goattracker's `freqtbl` value for note index `note`, floored.

    gplay.c:9-21 tabulates `GT_FREQ0 * 2**(n/12)` rounded. Flooring the formula
    rather than transcribing the table keeps this *under* the real value, which
    is the safe direction for a bound that decides whether a sweep can wrap.
    """
    if note < 0:
        return 0
    return int(GT_FREQ0 * (2.0 ** (note / 12.0)))


def _drum_steps_safe(steps: int, min_note: Optional[int],
                     multiplier: int = 1) -> bool:
    """Can `steps` unconditional sweep steps never underflow this instrument?

    `CMD_PORTADOWN` is `cptr->freq -= speed` on an unsigned 16-bit value with
    no clamp anywhere (gplay.c:557-572), so a sweep deeper than the distance
    from the note to zero wraps to a very high frequency and screeches -- which
    is why section 7.oo reverted an unbounded jump-to-self loop after it did
    exactly that on Commando. The player itself cannot: its own `LDA freqhi,X /
    BEQ out` freezes at zero.

    Goattracker's lowest note is only 279 (`GT_FREQ0`), so *no* step count above
    one is safe for every note the format can express -- section 7.oo's reason
    for stopping at one. It is safe for every note an instrument is actually
    *played* at, though, and that is a property this converter can read off the
    finished patterns (`patterns.min_played_notes`). A missing bound means
    "unknown", so it declines rather than assuming.
    """
    if min_note is None:
        return False
    hi, lo = _drum_speed(multiplier)
    step = (hi << 8) | lo
    return _note_freq(min_note) - steps * step >= DRUM_DEEPEN_MARGIN


# A wavetable left side of $01-$0F is a delay: the entry holds whatever
# waveform is already set for that many play calls before advancing
# (gcommon.h:56-57 WAVEDELAY/WAVELASTDELAY, executed at gplay.c:698-704).
WAVE_MAX_DELAY = 0x0F


def _wave_hold_byte(multiplier: int = 1, wave: int = 0) -> Optional[int]:
    """Entry-1 byte that makes the attack last one frame, or None at -S1.

    **A delay entry holds for `value + 1` play calls, not `value`.**
    gplay.c:697-704 advances only on the call where `wavetime == value`,
    having incremented it on each of the `value` calls before, so the entry
    is current for `value + 1` calls in total. Entry 0 is itself one call, so
    a frame of `m` calls needs `m - 1` more from entry 1, which is a delay of
    `m - 2`.

    Until v0.5.130 this returned `m - 1` and the attack ran for `m + 1` calls
    -- 1.5 frames at -S2, where 22 of the corpus's 37 multispeed files sit.
    The reading came from gcommon.h's `WAVEDELAY .. WAVELASTDELAY` range
    rather than from the loop that consumes it.

    One extra call has no delay encoding: 0 is not a delay value and `$00` in
    a wavetable is the editor's empty marker. At -S2 the attack waveform is
    written again instead -- the same one call, an unambiguous byte, and a
    no-op wherever `tail == wave` already put it there.
    """
    extra = max(1, multiplier) - 1
    if extra <= 0:
        return None
    if extra == 1:
        return wave
    return min(extra - 1, WAVE_MAX_DELAY)


def _two_stage_entries(wave: int, attack: int, frames: int,
                       multiplier: int = 1) -> tuple:
    """Wavetable entries for the two-stage waveform, or None if it says nothing.

    The dialect `detect._find_two_stage` reads, in 34 corpus files: effect bit
    $04 is not an arpeggio but an *attack waveform*, held for a per-instrument
    number of frames and then dropped to the record's own +2. Detection has
    located both arrays since it was written and nothing consumed them, so
    every one of those files played the second stage from its first frame.

    What that costs is not subtle. Trans-Atlantic's GT 2 is `$81` noise for 4
    frames before its pulse -- 226 notes of drum the conversion played as a
    pulse -- and its GT 4 has **no waveform of its own at all** (`+2` is `$00`),
    so the attack is the only waveform it ever has and the instrument was
    silent for all 70 of its notes.

    A record whose `+2` is zero gets the attack waveform with the gate cleared
    as its second stage. The player writes `$00` there, which is "no waveform
    selected" and stops the sound outright; a Goattracker wavetable cannot say
    that -- `$00`-`$0F` are delays, not waveforms -- so the nearest it has is
    the same waveform released.

    `frames` is a per-frame count and the table steps per *call*, so it is
    scaled by `multiplier`; and a delay entry holds for `value + 1` calls, with
    entry 0 itself being one, exactly as `_wave_hold_byte` sets out.
    """
    if attack == 0 or frames <= 0:
        return None
    calls = max(1, frames) * max(1, multiplier)
    second = (wave & 0xFE) or (attack & 0xFE)
    left, right = [attack], [0x00]
    extra = calls - 1             # entry 0 is already one call
    if extra == 1:
        left.append(attack)       # no delay encodes one call; rewrite instead
        right.append(0x00)
    elif extra > 1:
        left.append(min(extra - 1, WAVE_MAX_DELAY))
        right.append(0x80)
    left += [second | (wave & 0x01), 0xFF]
    right += [0x00, 0x00]
    return left, right


SFX_DRUM_FRAMES = 2          # frames of noise per hit, measured off the trace
WAVE_NOTE_KEEP = 0x80        # right side: leave the frequency alone
WAVE_NOTE_ABS = 0x80         # ...and $80 + index is an absolute note


def _sfx_note_byte(pitch_hi: int) -> int:
    """Wavetable right-side byte for a frequency whose high byte is `pitch_hi`.

    The player writes `$D401` directly and keeps the note's low byte, which a
    wavetable cannot do -- its right side names a note, not a register. The
    nearest absolute note is what it can say: `$3800` lands on index 68
    (`$375C`) and `$4800` on 73 (`$49E5`), both inside a quarter-tone. For
    noise that is not an approximation anyone can hear -- the pitch sets how
    fast the shift register clocks, and a quarter-tone changes the colour of a
    drum by nothing.
    """
    target = pitch_hi << 8
    idx = min(range(96), key=lambda n: abs(_note_freq(n) - target))
    return (WAVE_NOTE_ABS + idx) & 0xFF


def _sfx_drum_entries(wave: int, pitch_hi: int, period: int,
                      multiplier: int = 1) -> tuple:
    """Entries for the bit-$80 drum: a noise hit every `period` frames.

    `detect._find_sfx_drum` reads what this plays -- noise at a fixed frequency
    high byte, on a per-voice counter, while an instrument carrying bit $80 is
    held. It is the drum of seven corpus files and was left unwritten while it
    was believed to be the game's own sound effect (§7).

    The shape is a loop, because the player's is: two frames of noise at the
    drum's pitch, the instrument's own waveform and note back again, a delay
    covering the rest of the period, and a jump to the top. That is five
    entries, which is exactly `WAVE_ENTRIES_PER_INSTR`.

    Two things here are measured rather than derived, and both are marked in
    §7 as open. The burst is **two** frames in the trace where the counter
    test (`CMP #$01`) implies one; and the second frame's frequency is a fixed
    `$15EB` from somewhere this reader has not found, so both frames are
    written at the pitch that *is* read. The alternative -- emitting one frame,
    or the note's own pitch -- is further from the trace, not closer.
    """
    if pitch_hi <= 0 or period <= 0:
        return None
    # A record whose +2 is $00 has no waveform to come back to, and `$01` --
    # what `(wave & 0xFE) | 0x01` yields -- is a *delay* in a wavetable, not a
    # waveform ($01-$0F, readme.txt:3.4.1). Emitting it left the instrument
    # setting no waveform at all: it inherited noise from whatever played
    # before and its delay entry applied a relative note, so Bangkok Knights'
    # GT 9 sounded 40 frames at `freqtbl[0]` = $0117 where the drum belongs at
    # $49E5. readme.txt warns about a delay in the first step for this reason.
    # No waveform means no drum here -- an under-read, not an invention.
    if not wave & 0xF0:
        return None
    m = max(1, multiplier)
    # **The note comes first, and that is not cosmetic.** The player's counter
    # is per voice and free-running, so a hit falls wherever it falls relative
    # to a note start; a wavetable always begins at the note. Opening on the
    # noise therefore puts the drum's pitch on the note's own first frame,
    # where the played note never sounds at all -- measured, it took
    # Trans-Atlantic's melody from 94.7% to 50.4%. Opening on the note and
    # hitting later in the loop keeps both.
    left = [(wave & 0xFE) | 0x01]
    right = [0x00]                           # relative 0: the played note
    # Hold there for the rest of the period. A delay entry is current for
    # `value + 1` calls (gplay.c:697-704), so the value is one less than the
    # calls wanted -- and the count is in calls, not frames.
    rest = (period - SFX_DRUM_FRAMES) * m - 1
    if rest == 1:
        left.append((wave & 0xFE) | 0x01)
        right.append(0x00)
    elif rest > 1:
        left.append(min(rest - 1, WAVE_MAX_DELAY))
        right.append(WAVE_NOTE_KEEP)
    note = _sfx_note_byte(pitch_hi)
    left += [WAVE_NOISE_GATEOFF | 0x01] * SFX_DRUM_FRAMES
    right += [note] * SFX_DRUM_FRAMES
    return left, right


# Goattracker's "inaudible waveform" range: $E0-$EF sets the waveform to
# $00-$0F (readme.txt:3.4.1, gplay.c:527). A player waveform below $10 -- gate
# alone, or nothing at all -- cannot be written literally, because $01-$0F are
# *delays*. This is the encoding for it, and the reason a wave program can carry
# `slide $01` at all.
WAVE_SILENT_BASE = 0xE0


def _wave_byte(wave: int) -> int:
    """Wavetable left byte that sets the player's waveform `wave`."""
    return wave if wave >= 0x10 else WAVE_SILENT_BASE | (wave & 0x0F)


def _speed_index(speed_table: List[tuple], entry: tuple) -> int:
    """1-based speed-table index for `entry`, appending it, or 0 if full."""
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _wave_program_entries(sid: SidFile, det: Detection, i: int,
                          speed_table: List[tuple], fmt: str,
                          multiplier: int, budget: int) -> Optional[tuple]:
    """Wavetable entries for the byte-code wave program, or None.

    The interpreter `detect.find_wave_program` reads, in 29 corpus files -- the
    most widespread instrument mechanism this converter has left unemitted, and
    the one carrying Trans-Atlantic's snare (`81 30`, noise at `$30xx`, 43 onsets
    a listener reported missing).

    Each opcode becomes entries:

    * `>= $80` -- waveform plus an absolute frequency high byte -- is one entry:
      the waveform, with the nearest absolute note on the right. The player
      writes `$D401` directly and a wavetable names notes, so the pitch is
      quantised to a semitone; for the noise these opcodes mostly carry, that is
      inaudible (see `_sfx_note_byte`).
    * `< $80` with a zero operand is also one entry: a waveform change and no
      pitch movement, which is most of what GT 11-13 do.
    * `< $80` with a nonzero operand is two: the waveform, then a portamento
      whose speed-table entry is the operand itself. The player *subtracts* it,
      so an operand above `$8000` is a rise and takes `CMD_PORTAUP` with the
      two's complement -- which also keeps the high byte below `$80`, where a
      speed-table entry would otherwise read as note-relative
      (`SPEED_NOTE_RELATIVE`).
    * `$85` holds, which is the program's end; the block stops there and
      Goattracker keeps the last waveform, as the player does.

    **Multiplier 1 only.** The player advances one opcode per frame and a
    wavetable advances one entry per *call*, so at `-S2` the whole program would
    run twice as fast. Slowing it needs a delay entry per opcode, which roughly
    doubles a budget that already reaches 131 entries on Kings of the Beach.
    Restricting it is an under-read; guessing the rate is not.
    """
    if fmt != FORMAT_GTS5 or max(1, multiplier) != 1:
        return None
    if det.wave_program < 0 or not det.wave_program_gate:
        return None
    data = sid.data
    rec = det.instr_start + i * det.instr_stride
    off = det.wave_program + i * det.instr_stride
    if max(rec + 7, off + 1) >= len(data):
        return None
    if not data[rec + 7] & det.wave_program_gate:
        return None
    at = sid.to_offset(data[off] | (data[off + 1] << 8))
    if at < 0:
        return None

    left: List[int] = []
    right: List[int] = []
    for kind, wave, arg in decode_wave_program(data, at):
        if kind == "hold":
            break
        need = 2 if (kind == "slide" and arg) else 1
        if len(left) + need + 1 > budget:      # ...and the stop
            break
        if kind == "set":
            left.append(_wave_byte(wave))
            right.append(_sfx_note_byte(arg))
            continue
        step = arg if arg < 0x8000 else 0x10000 - arg
        cmd = WAVECMD_PORTADOWN if arg < 0x8000 else WAVECMD_PORTAUP
        if not arg:
            left.append(_wave_byte(wave))
            right.append(WAVE_NOTE_KEEP)
            continue
        idx = _speed_index(speed_table, ((step >> 8) & 0xFF, step & 0xFF))
        if not idx:
            break
        left += [_wave_byte(wave), cmd]
        right += [WAVE_NOTE_KEEP, idx]
    if not left:
        return None
    left.append(0xFF)
    right.append(0x00)
    return left, right


def _rate_shift(multiplier: int = 1) -> int:
    """Extra right-shift that turns a per-frame rate into a per-call one.

    Only the note-relative speed entries take their rate as a shift, so this
    is exact for 1 and 2 and rounds for 3 (log2(3) = 1.58 -> 2, a division by
    four where three is wanted). See _rise_speed_index.
    """
    m = max(1, multiplier)
    return max(0, round(math.log2(m)))


# --- Tempo -----------------------------------------------------------------
#
# This converter emits exactly one pattern row per Hubbard player tick (see
# patterns.py: an event with wait W occupies W+1 rows). So a row must last one
# player tick -- and a tick is reload+1 frames, not one frame: see the speed
# gate below (find_song_speeds).
#
# Goattracker makes a row last `tempo+1` calls of the play routine (gplay.c:325
# reloads tick from tempo, :322 advances the row when it hits 0). The startup
# default is 6 calls per row, and it scales with the speed multiplier
# (`6*multiplier-1`, gplay.c:212) -- so raising the multiplier alone never
# changes the row rate, it only subdivides each call.
#
# The one lever stored *in the file* is the last instrument's Attack/Decay:
#
#     if ((instr[MAX_INSTR-1].ad >= 2) && (!(instr[MAX_INSTR-1].ptr[WTBL])))
#         cptr->tempo = instr[MAX_INSTR-1].ad - 1;          gplay.c:221
#
# That override does NOT scale with the multiplier, so it sets calls-per-row
# absolutely: instr[63].ad == A gives A calls per row, hence A/multiplier frames
# per row. Goattracker rejects A < 2 (values 0 and 1 select funktempo instead),
# so the fastest expressible row is 2 calls -- i.e. one frame per row requires
# speed multiplier 2. That is exactly the "2x" needed to make a converted tune
# play at the right speed.
GT_TEMPO_INSTRUMENT = 63          # MAX_INSTR-1 -- the old route, see below
GT_DEFAULT_TEMPO_CALLS = 6        # Goattracker's startup default

# CMD_SETTEMPO (gcommon.h: 15). gplay.c:494 takes the low 7 bits, decrements
# them when >= 3, and assigns the result to all three channels when the value
# is under $80. gplay.c:325 then makes a row last `tempo + 1` play-routine
# calls -- but only for `tempo >= 2`; 0 and 1 are *funktempo*, which alternates
# two tick lengths out of funktable[] rather than holding a steady rate.
#
# So the fastest steady row the format can express is tempo 2, i.e. three
# calls, reached by a command value of 2 or 3.
CMD_SETTEMPO = 15
GT_MIN_TEMPO = 2                  # below this is funktempo, not a rate
TEMPO_FASTEST_STEADY = 3          # value -> tempo 2 -> 3 calls per row

# The superseded route: instrument 63's attack/decay (gplay.c:221). It was
# wrong twice over. `ad = 2` yields tempo 1, which is funktempo -- the
# alternating 9/6 tick pattern, not the steady 2 calls/row it was documented
# as -- and reaching instrument 63 meant declaring 63 instruments, ~1.2 KB of
# inert padding that gt2reloc strips when packing to .sid, leaving the packed
# tune silent. A CMD_SETTEMPO in the pattern data survives relocation, shows up
# in the editor, and costs nothing.


# --- The player's own song speed -------------------------------------------
#
# The classic players do NOT advance the sequencer every frame. Commando $5052:
#
#     5054  CE 13 55  DEC $5513     ; master speed counter, every call
#     5057  10 06     BPL $505F
#     5059  AD 17 55  LDA $5517     ; reload value
#     505C  8D 13 55  STA $5513
#     ...
#     5066  AD 13 55  LDA $5513
#     5069  CD 17 55  CMP $5517     ; equal only on the reload frame
#     506C  D0 15     BNE $5083     ; other frames skip the sequencer
#     ...
#     5078  DE F2 54  DEC $54F2,X   ; the per-voice duration DEC (wait+1 rows)
#
# so a duration *unit* -- what one converted pattern row represents -- lasts
# reload+1 frames, not one. The reload value is per subtune where init loads it
# from a table (Commando $5F0F: TAX / LDA $5514,X / STA $5517 -> speeds 2,3,2
# for its three tunes), and a static data byte in the players whose init never
# writes it (Zoids: $146F holds 2, one speed for every subtune). The digi
# engine carries the same gate (Off the Cuff: table at $183F, value 1).
#
# The DEC/BPL/LDA/STA 10-byte sequence with matching counter operands is the
# fingerprint; it matches 85 of the 95 corpus files, and everywhere it was
# checked per voice against siddump of the original (Commando, Thing on a
# Spring, Crazy Comets, IK+, Zoids, After 8, Pandora, Nemesis, Off the Cuff)
# the original's attack gaps are exactly reload+1 times the decoded rows.
#
# What it deliberately does not match: the *prescaler* variant (Mozart, Ninja,
# Mega Apocalypse), `DEC / BPL past-an-RTS / LDA #imm / STA / RTS`, which runs
# the whole player only v of every v+1 calls -- an effective rate of (v+1)/v
# frames per call that no steady Goattracker tempo can express -- and the
# command-table dialect, whose row length comes from its duration table's
# common factor instead (patterns.cmdtable_frames_per_row).
SPEED_GATE = re.compile(rb"\xce(..)\x10\x06\xad(..)\x8d(..)", re.DOTALL)
SPEED_TABLE_LOAD = b"\xbd"       # LDA abs,X -- X is the subtune number
SPEED_RELOAD_STORE = b"\x8d"     # STA abs

# The gate is not the only thing counting frames. Immediately above it sits a
# second counter of the same shape but with an *immediate* reload, and on the
# frame it underflows the gate's DEC is jumped over entirely:
#
#     DEC outer / BPL +8 / LDA #O / STA outer / JMP past-the-gate
#     DEC gate  / BPL +6 / LDA reload / STA gate
#
# So the gate is decremented on O of every O+1 frames, and a row that should
# last `frames` frames lasts `frames * (O+1)/O`. That factor is why
# find_song_speeds reads low on a large minority of the corpus -- measured
# against 15 files whose row length was timed independently, the corrected
# number is within 5% on all 15 and within 1% on 10 (see whats-next.md 7b).
OUTER_GATE = re.compile(rb"\xce(..)\x10\x08\xa9(.)\x8d(..)\x4c(..)", re.DOTALL)

# A reload byte above this is not a song speed. Real corpus values are 0-8
# (f = 1..9); per-subtune tables are read past their end for files whose
# header over-counts subtunes (Commando claims 19), and the bytes that follow
# are code whose values (0x70+) would otherwise become absurd tempos.
MAX_SANE_SPEED_RELOAD = 15


@dataclass(frozen=True)
class SongSpeeds:
    """Frames per duration unit, per subtune, read from the player.

    `frames[s]` is reload+1 for subtune `s`, or None where the table byte is
    not a sane speed (over-counted subtunes read past the real table).
    """
    frames: Tuple[Optional[int], ...]
    reload_addr: int
    table_addr: Optional[int]    # None = static reload byte, one speed for all
    # Reload of the outer counter that skips the gate, per subtune. Empty when
    # the player has no such counter -- which is most of the corpus.
    skip: Tuple[Optional[int], ...] = ()
    skip_table_addr: Optional[int] = None

    def frames_for(self, subtune: int) -> Optional[int]:
        if 0 <= subtune < len(self.frames):
            return self.frames[subtune]
        return None

    def skip_for(self, subtune: int) -> Optional[int]:
        if 0 <= subtune < len(self.skip):
            return self.skip[subtune]
        return None

    def exact_row(self, subtune: int = 0):
        """The corrected row as an exact Fraction of frames, or None.

        `(reload + 1) * (O + 1) / O` is rational, and a row of p/q frames is
        expressible exactly by packing at `-Sq` with a tempo of p: a row lasts
        tempo/multiplier frames. That is what MAX_ROW_DENOMINATOR bounds --
        the multiplier is a real call rate on real hardware, and q of 127
        would ask the player to run 6350 times a second.
        """
        f = self.frames_for(subtune)
        o = self.skip_for(subtune)
        if f is None:
            return None
        return Fraction(f * (o + 1), o) if o else Fraction(f)

    def encodable_frames(self, subtune: int = 0) -> Optional[int]:
        """`true_frames` when Goattracker can express it exactly, else None.

        A row is a whole number of play calls, so a corrected row of 2.67 --
        the player skipping one frame in four -- has no tempo. Rounding it
        would trade a known 25% error for an unknown one, and the honest
        encoding of a fractional row is §8's re-gridding, not a round(). Only
        the whole-number cases are returned, which on this corpus is six
        files against forty-two fractional ones.
        """
        t = self.true_frames(subtune)
        if t is None:
            return None
        return int(round(t)) if abs(t - round(t)) < 0.02 else None

    def true_frames(self, subtune: int = 0) -> Optional[float]:
        """Frames per duration unit *including* the outer counter's skips.

        Non-integer by nature: a gate of 2 frames skipping one frame in four
        gives rows of 3, 3 and 2 frames, an average of 2.67. Nothing in
        Goattracker can express that, which is why this is reported rather
        than encoded -- `frames_for` is still what the writer uses. See
        whats-next.md 7b and 8.
        """
        f = self.frames_for(subtune)
        o = self.skip_for(subtune)
        if f is None:
            return None
        if not o:
            return float(f)
        return f * (o + 1) / o

    @property
    def source(self) -> str:
        if self.table_addr is not None:
            return f"per-subtune table at ${self.table_addr:04X}"
        return f"static reload byte at ${self.reload_addr:04X}"


def _gate_hits(data: bytes):
    """(match offset, reload address) for every speed-gate shape in the file."""
    hits = []
    for m in SPEED_GATE.finditer(data):
        ctr, rel, ctr2 = m.group(1), m.group(2), m.group(3)
        if ctr != ctr2:
            continue
        hits.append((m.start(), rel[0] | rel[1] << 8))
    return hits


def _speeds_for_reload(sid: SidFile, rel_addr: int) -> Optional[SongSpeeds]:
    """SongSpeeds for one gate, from its init table or its static byte."""
    data = sid.data
    rel_bytes = bytes([rel_addr & 0xFF, rel_addr >> 8])
    load = re.escape(SPEED_TABLE_LOAD) + b"(..)" + \
        re.escape(SPEED_RELOAD_STORE + rel_bytes)
    n = max(sid.subtunes, 1)
    for m in re.finditer(load, data, re.DOTALL):
        t = m.group(1)
        table_addr = t[0] | t[1] << 8
        off = sid.to_offset(table_addr)
        if not 0 <= off < len(data):
            continue
        vals = data[off:off + n]
        frames = tuple(v + 1 if v <= MAX_SANE_SPEED_RELOAD else None
                       for v in vals)
        if frames and frames[0] is not None:
            return SongSpeeds(frames, rel_addr, table_addr)
    off = sid.to_offset(rel_addr)
    if 0 <= off < len(data) and data[off] <= MAX_SANE_SPEED_RELOAD:
        return SongSpeeds((data[off] + 1,) * n, rel_addr, None)
    return None


def _find_outer_gate(sid: SidFile, subtunes: int):
    """(per-subtune reloads, table address) for the counter above the gate.

    The reload is an *immediate*, so the byte sitting in the file image is
    whatever the last init left there -- Tarzan's reads 11 while its subtune 0
    actually runs 2. Where the init writes that operand from a table
    (`LDA table,X / STA <the immediate's own address>`, the same self-modifying
    idiom the players use elsewhere) the table is the answer and the image byte
    is a decoy. v0.5.102 read the image byte and concluded the value was a
    per-player constant; it is per subtune in 32 of the 51 files that have it.
    """
    m = OUTER_GATE.search(sid.data)
    if not m:
        return (), None
    ctr = m.group(1)[0] | (m.group(1)[1] << 8)
    if ctr != (m.group(3)[0] | (m.group(3)[1] << 8)):
        return (), None                     # decrements one cell, reloads another
    imm_off = m.start() + 6
    imm_addr = sid.load_addr + imm_off - sid.to_offset(sid.load_addr)
    store = bytes([0x8D, imm_addr & 0xFF, imm_addr >> 8])
    i = sid.data.find(store)
    while i >= 0:
        if i >= 3 and sid.data[i - 3] == SPEED_TABLE_LOAD[0]:
            table = sid.data[i - 2] | (sid.data[i - 1] << 8)
            off = sid.to_offset(table)
            if 0 <= off < len(sid.data):
                vals = sid.data[off:off + max(subtunes, 1)]
                return tuple(v or None for v in vals), table
        i = sid.data.find(store, i + 1)
    return (sid.data[imm_off] or None,) * max(subtunes, 1), None


def find_song_speeds(sid: SidFile,
                     det: Detection | None = None) -> Optional[SongSpeeds]:
    """The tune's frames-per-duration-unit, or None where it cannot be read.

    A file can hold several gate shapes (5 Title Tunes carries five separate
    players; One on One's sample data happens to contain the byte sequence).
    With a detection to hand, the gate nearest the detected instrument table is
    the detected player's own. Without one, agreement across all hits is
    required -- disagreeing hits mean the wrong one may be chosen, and a wrong
    tempo is worse than the old constant.
    """
    candidates = []
    for pos, rel_addr in _gate_hits(sid.data):
        speeds = _speeds_for_reload(sid, rel_addr)
        if speeds is not None:
            candidates.append((pos, speeds))
    if not candidates:
        return None
    skip, skip_table = _find_outer_gate(sid, max(sid.subtunes, 1))
    candidates = [(pos, replace(sp, skip=skip, skip_table_addr=skip_table))
                  for pos, sp in candidates]
    if len(candidates) == 1:
        return candidates[0][1]
    if det is not None and det.instr_start >= 0:
        return min(candidates, key=lambda c: abs(c[0] - det.instr_start))[1]
    first = candidates[0][1]
    if all(c[1].frames == first.frames for c in candidates):
        return first
    return None


# How far the -S factor may be raised to make a fractional row exact.
#
# The bound is playability, not fidelity. Six calls a frame is ~300 a second
# and about 9k cycles of a PAL frame's 19656 at 1.5k a call -- heavy but
# real. Ten would be three quarters of the frame and twenty impossible, and
# the rows those would buy are within ~1.3% of a whole number anyway (3.02,
# 3.03, 4.04), so they round.
#
# v0.5.121 capped this at 4 because -S5 appeared to regress three files. It
# did not: siddump samples once per frame whatever the call rate, so tracing
# a multiplier-5 file at -m5 discards four calls in five along with the gate
# edges inside them (v0.5.124). Measured at equal sampling with
# `fidelity.py --equal-calls`, nothing regresses and three files gain --
# Kings_of_the_Beach_intro, the supposed worst case at 96% -> 61%, is 96% at
# -S5.
MAX_ROW_DENOMINATOR = 6


def effective_frames(speeds: Optional[SongSpeeds], subtune: int = 0,
                     skip_gate: bool = False):
    """Frames per unit as the tempo should encode it.

    Without `skip_gate` this is the speed gate's own reload+1, which is what
    every version before v0.5.119 used. With it, the counter above the gate is
    taken into account wherever the corrected row is a whole number -- see
    SongSpeeds.encodable_frames and whats-next.md §7b.
    """
    if speeds is None:
        return None
    if skip_gate:
        got = speeds.encodable_frames(subtune)
        if got is not None:
            return got
        exact = speeds.exact_row(subtune)
        if exact is not None and exact.denominator <= MAX_ROW_DENOMINATOR:
            return exact
    return speeds.frames_for(subtune)


def recommended_multiplier(speeds: Optional[SongSpeeds],
                           subtune: int = 0, skip_gate: bool = False) -> int:
    """gt2reloc -S value under which this tune's tempo is expressible.

    A row must last `frames` player calls scaled by the multiplier, and
    Goattracker's fastest steady row is three calls (values 2 and 3 both give
    tempo 2; below that is funktempo). So frames >= 3 works at 1x, frames == 2
    needs the play routine called twice per frame, and frames == 1 three
    times. greloc.c:1595 arms a CIA stub for exactly this.
    """
    f = effective_frames(speeds, subtune, skip_gate)
    if f is None:
        return 1
    q = getattr(f, "denominator", 1)
    if q > 1:
        # A row of p/q frames is exact at -Sq, and stays exact at any multiple
        # of q -- so clear the denominator first, then raise it further if the
        # row is still too short to express.
        return q * max(1, -(-(GT_MIN_TEMPO + 1) // int(f * q // 1 or 1)) if
                       f * q < GT_MIN_TEMPO + 1 else 1)
    if f >= GT_MIN_TEMPO + 1:
        return 1
    return -(-(GT_MIN_TEMPO + 1) // int(f))


def tempo_command_value(sid: SidFile, subtune: int = 0,
                        speeds: Optional[SongSpeeds] = None,
                        multiplier: int = 1, skip_gate: bool = False) -> int:
    """CMD_SETTEMPO value for this subtune: its player's frames per unit.

    One converted row is one duration unit, and the player's speed gate says a
    unit lasts `frames` frames -- so a row must last `frames` play calls, and
    the command value for any count >= 3 *is* the count (gplay.c:494
    decrements values >= 3, :325 makes a row last tempo+1 calls).

    `multiplier` is the gt2reloc -S factor the caller intends to pack with:
    at 50*m Hz a row of the same real length needs frames*m calls. Where the
    speed cannot be read (no gate shape, a prescaler player, an over-counted
    subtune) the old constant stands, scaled the same way, so a file keeps one
    consistent timebase.
    """
    if speeds is None:
        speeds = find_song_speeds(sid)
    f = effective_frames(speeds, subtune, skip_gate)
    if f is None:
        # The old constant, scaled to the caller's timebase: 3 calls at 1x is
        # 3*m calls at m-times the call rate.
        return min(TEMPO_FASTEST_STEADY * multiplier, 0x7F)
    # The floor is not only the funktempo boundary: every instrument this
    # writer emits carries gatetimer 2 (_write_instruments), and gplay.c:334
    # stops the song outright when gatetimer exceeds the channel's tick. A
    # command value of 3 lands as effective tempo 2 -- exactly at that
    # boundary -- so nothing below 3 may ever be emitted here.
    return min(max(int(f * multiplier), TEMPO_FASTEST_STEADY), 0x7F)


def derived_group_tempos(sid: SidFile, det: Detection, groups: int,
                         skip_gate: bool = False) -> Tuple[List[int], int, str]:
    """Per-subtune CMD_SETTEMPO values, the -S multiplier, and a source note.

    `groups` is how many 3-track groups the caller has, which equals the
    header subtune numbering as long as no subtune has been split (the caller
    checks that). The multiplier is chosen from subtune 0 -- the canonical
    tune, and what a packed .sid plays by default -- and every subtune's value
    is scaled by it, so the whole file shares one timebase.
    """
    speeds = find_song_speeds(sid, det)
    mult = recommended_multiplier(speeds, 0, skip_gate)
    values = [tempo_command_value(sid, s, speeds, mult, skip_gate)
              for s in range(groups)]
    note = speeds.source if speeds is not None else \
        "no speed gate found, keeping the constant"
    return values, mult, note


def _table_length_byte(entries: int, what: str) -> int:
    """Length byte for a wave/pulse table, refusing to silently wrap.

    The original masked with & 0xFF, which turns an over-long table into a
    plausible-looking short one -- Goattracker then reads the remainder as
    whatever section follows. Fail loudly instead.
    """
    if not 0 <= entries <= GT_MAX_TABLELEN:
        raise ValueError(
            f"{what} table needs {entries} entries, exceeding Goattracker's "
            f"MAX_TABLELEN ({GT_MAX_TABLELEN})"
        )
    return entries


def _padded_name_bytes(name: str, width: int = 16) -> bytes:
    raw = name.encode("latin-1", errors="replace")[:width]
    return raw + bytes(width - len(raw))


def _field_bytes(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")[:FIELD_LEN]
    return raw.ljust(FIELD_LEN, b"\x00")


def _build_header(sid: SidFile, fmt: str = DEFAULT_FORMAT) -> bytearray:
    header = bytearray(HEADER_LEN)
    header[0:4] = b"GTS2" if fmt == FORMAT_GTS2 else b"GTS5"
    header[0x04:0x04 + FIELD_LEN] = _field_bytes(sid.name)
    header[0x24:0x24 + FIELD_LEN] = _field_bytes(sid.author)
    header[0x44:0x44 + FIELD_LEN] = _field_bytes(sid.released)
    return header


def _instruments_used(det: Detection, log=None, lead: int = 1) -> int:
    """How many instrument slots the file will carry, `lead` placeholders included.

    `lead` is 1 for the inherited layout, whose instrument 1 is a hardcoded
    empty "Clear Voice" so the player's record 0 becomes instrument 2, and 0
    for --compact-instruments, which puts record 0 at instrument 1. Goattracker
    reserves no slot of its own: its format stores instruments from 1 and
    treats 0 as "no change" in a pattern column (readme:613, 1386), so the
    placeholder is the VB6 original's convention, not the format's.
    """
    available = det.instr_used + lead
    instr_used = min(available, MAX_INSTRUMENTS)
    if log and available > instr_used:
        # The count itself is bounded at the records (see detect's
        # `_bound_instruments`); what remains here is Goattracker's own
        # ceiling, which the wavetable's one-byte length imposes.
        log(f"*** INSTRUMENT TABLE HAS {available} ENTRIES, ONLY {instr_used} FIT "
            f"(GOATTRACKER WAVETABLE LIMIT) -- {available - instr_used} DROPPED ***")
    return instr_used


def _write_instruments(out: bytearray, sid: SidFile, det: Detection,
                       instr_used: int, pulse_starts: List[int],
                       sustain_exact: bool = False,
                       no_hard_restart: bool = False,
                       filter_ptrs: dict | None = None,
                       vib_ptrs: dict | None = None,
                       lead: int = 1,
                       wave_starts: Optional[List[int]] = None,
                       no_test_restart: bool = False) -> int:
    out.append(instr_used)
    first = FIRSTWAVE_GATE_ONLY if no_test_restart else FIRSTWAVE_TESTBIT

    if lead:
        # Instrument 1: always the empty "Clear Voice" slot.
        out += bytes([0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00, 0x02, first])
        out += _padded_name_bytes("Clear Voice")

    # The digi engine's records are 16 bytes rather than 8. The fields read
    # here -- pulse +0/+1, waveform +2, attack/decay +3, sustain/release +4 --
    # sit at the same offsets in both layouts, so only the stride differs.
    wtable_start = lead * WAVE_ENTRIES_PER_INSTR + 1
    data = sid.data
    n = max(instr_used - lead, 0)  # number of real (non-empty) instruments

    for i in range(n):
        base = det.instr_start + i * det.instr_stride
        ad = data[base + 3]
        sr = data[base + 4]
        if not sustain_exact and sr >= 0xF0:
            # Inherited from the VB6 original (h2g.frm:578-579), whose comment
            # reads "&SSSXRRRR (S=Sustain, R=Release, X=Cut this bit out)".
            # There is no X bit: SID register 6 is SSSS RRRR, four bits of
            # sustain and four of release (6581 datasheet). Clearing $10 lowers
            # a sustain of F to E on every instrument that asked for full
            # sustain -- the level the note holds at for its whole duration.
            # Kept as the default only because the byte-exact Commando fixture
            # encodes it; --sustain-exact reads the register as the SID does.
            sr &= 0xEF
        # From the laid-out table, not from the index: a record before this
        # one may be longer than WAVE_ENTRIES_PER_INSTR (a deep drum sweep),
        # and then the arithmetic is simply wrong. Falls back to the stride
        # for callers that pass no layout.
        wave_ptr = ((wave_starts[i + lead]
                     if wave_starts is not None and i + lead < len(wave_starts)
                     else i * 5 + wtable_start) & 0xFF)
        # Not a stride: a swept instrument's pulse program is longer than a
        # static one's, so the start positions come from the built table.
        pulse_ptr = (pulse_starts[i + lead]
                     if i + lead < len(pulse_starts) else 0) & 0xFF
        # gatetimer bit $80 is Goattracker's "no hard restart" flag
        # (gsong.c:381). Without it, gplay.c:930-937 writes `adparam` -- the
        # editor's HR value, default $0F00 (goattrk2.c:49), baked into the
        # packed player as ADPARAM/SRPARAM (greloc.c:1138) -- into $D405/$D406
        # for one frame before every note. Hubbard's players never do that:
        # $0F00 appears in none of the corpus originals and is the most common
        # ADSR value in every conversion without this flag.
        gatetimer = 0x82 if no_hard_restart else 0x02
        filt_ptr = (filter_ptrs or {}).get(i, 0x00)
        # Bytes 5 and 6 are ptr[STBL] and vibdelay in a GTS5 file
        # (gsong.c:224-225) and the same pair the other way round, packed, in a
        # GTS2 one (gsong.c:284-285) -- which is why they stay 0,0 unless
        # _vibrato_layout produced something, and it only does for GTS5.
        stbl_ptr, vib_delay = (vib_ptrs or {}).get(i, (0x00, 0x00))
        # The player's own first frame is the record's waveform with the gate
        # on -- Commando's noise record traces `81 80 80 80 80` -- so that is
        # what `--no-test-restart` writes here. Anything below $FE is assigned
        # to the waveform and forces the gate on (gplay.c:355-363), which is
        # both halves of what a note needs: a real attack and no silent frame.
        out += bytes([ad, sr, wave_ptr, pulse_ptr, filt_ptr, stbl_ptr,
                      vib_delay, gatetimer,
                      ((data[base + 2] | 0x01) & 0xFF) if no_test_restart
                      else FIRSTWAVE_TESTBIT])

        b5, b6, b7 = data[base + 5], data[base + 6], data[base + 7]
        name = f"{i + 2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"
        out += _padded_name_bytes(name)

    return instr_used


# What Goattracker's vibrato actually does, simulated from gplay.c:795-801
# rather than read off the constants:
#
#     if ((vibtime < 0x80) && (vibtime > cmpvalue)) vibtime ^= 0xff;
#     vibtime += 0x02;
#     if (vibtime & 0x01) freq -= speed; else freq += speed;
#
# `vibtime` walks the even values up to `cmpvalue`, flips to the odd half by
# XOR, walks that down, and flips back. Counting the calls in each phase for
# cmpvalue 0..16, odd and even alike:
#
#     peak-to-peak = (cmpvalue + 2) * speed
#     full period  = 2 * (cmpvalue + 2) calls
#
# so an amplitude (half the peak-to-peak) of `(cmpvalue + 2) / 2 * speed`, and
# a HALF period of `cmpvalue + 2` calls. The +2 matters at the small values
# both engines produce: cmpvalue 2 oscillates twice as fast as cmpvalue 6, not
# three times.
VIBRATO_CMP_BIAS = 2


def _classic_vibrato_entry(byte: int, multiplier: int) -> Optional[tuple]:
    """Speed-table entry for one instrument byte in the $78/$07 format.

    The mapping is close to literal because both sides express the depth the
    same way. The player computes `(freq(note) - freq(note-1)) >> shift` and
    oscillates a counter between 0 and `bound`; Goattracker's note-relative
    speed (`ltable >= $80`) computes the interval at the current note shifted
    right by `rtable`, and flips direction when its own counter passes
    `ltable & $7f`. So:

        entry = ($80 | cmp, rshift)

    with the two derived from the half-period and the excursion, both taken
    from the *simulated* gplay.c semantics (see VIBRATO_CMP_BIAS) rather than
    from its constants:

    * **Period.** The player's counter steps by one per frame between 0 and
      `bound` (Warhawk $11FE-$121E: `DEC ctr,X / BNE out` walking down,
      `INC ctr,X / LDA bound,X / CMP ctr,X / BCS out` walking up), so its
      half-period is `bound` frames. Goattracker's is `cmp + 2` *calls*, which
      is `(cmp + 2) / multiplier` frames. Hence

          cmp = bound * multiplier - VIBRATO_CMP_BIAS

    * **Excursion.** The player's apply loop only ever subtracts
      (Warhawk $1245: `LDA ctr,X / LSR / TAY / DEY / BMI out / freq -= depth`),
      so the note is the top of the swing and `(bound >> 1) * depth` is a
      **peak-to-peak**, not an amplitude. Goattracker's peak-to-peak is
      `(cmp + 2) * speed`. Equating the two, with `cmp + 2 = bound *
      multiplier` from the period, cancels `bound` and leaves
      `speed = depth / (2 * multiplier)`, i.e.

          rshift = shift + 1 + log2(multiplier)

    * `multiplier` is in both because Goattracker's counter advances per play
      call and the player's per frame -- the same per-frame/per-call division
      every other rate in this file takes (see _drum_speed).

    Until v0.5.129 `cmp` was `2 * bound * multiplier`, from reading
    Goattracker's half-period as `cmp / 2` calls instead of `cmp + 2`. That
    made the emitted oscillation run at close to **half** the player's rate for
    all 56 files carrying this format. `rshift` is unchanged by the correction
    and that is not a coincidence: the old derivation equated the player's
    peak-to-peak with a Goattracker *amplitude*, and the two errors -- a period
    twice too long and an excursion convention off by two -- cancelled in the
    shift exactly. Only `cmp` was ever wrong.

    Two deliberate approximations besides, neither hidden: the player applies
    its counter as a *position* (an absolute offset from the note) where
    Goattracker integrates a step, which is the same triangle reached
    differently; and Goattracker takes the interval *above* the note where the
    player takes the one below, about 6% of a semitone.
    """
    bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
    if not byte or not bound:
        # The player's own test: `LDA record+5,Y / BNE` at Warhawk $11EA. A
        # bound of zero is an oscillation with no excursion, which is the same
        # silence reached one step later.
        return None
    shift = byte & VIBRATO_SHIFT_MASK
    # bound 1 at -S1 asks for a half-period of one frame; Goattracker's
    # shortest is two calls (cmp 0), which is what the clamp gives.
    cmp_value = min(0x7F, max(0, bound * multiplier - VIBRATO_CMP_BIAS))
    rshift = min(shift + 1 + _rate_shift(multiplier), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _vibrato_delay(det: Detection, multiplier: int) -> int:
    """Goattracker `vibdelay` for this player's vibrato, in play calls.

    `vibdelay` is a countdown, not a flag: gplay.c:769-776 is a fallthrough
    from `CMD_DONOTHING`, breaking while `vibdelay > 1` and decrementing once
    per call, so the oscillator first runs on the `vibdelay`-th call after the
    note. 1 means "from the first call" and 0 means "never".

    The classic and LFO-table players gate nothing, so they keep
    `VIBRATO_DELAY`. **The global-triangle player does gate, but not with a
    delay** -- and the difference is worth stating precisely, because a delay
    is what it looks like:

        BD EF 14  LDA $14EF,X    ; the note's raw pattern status byte
        29 1F     AND #$1F       ; ...its duration field
        C9 08     CMP #$08
        90 1C     BCC out        ; duration < 8 -> no vibrato on this note

    `$14EF,X` is written once per note (`LDA ($FD),Y / STA $14EF,X` at $10A2)
    and never incremented or decremented anywhere in the player, so this is a
    *per-note length threshold* decided before the note sounds, not a counter
    running during it. Nothing in a Goattracker instrument can express "only
    notes at least this long", because `vibdelay` is per instrument.

    What `vibdelay` reproduces exactly is the half that matters here: a note
    shorter than the delay **ends before the oscillator ever starts**, so
    setting the delay to the threshold suppresses vibrato on exactly the notes
    the player suppresses it on. The threshold is 8 of the player's frames and
    `vibdelay` counts our calls, so it scales by `multiplier` like every other
    rate in this file (see _drum_speed).

    The half it does not reproduce: on a note long enough to qualify, the
    player oscillates from its first frame where this starts at frame 8. So
    long notes are under-vibratoed at the head. That is the opposite error from
    applying the effect to every note regardless of length, and much the
    smaller one -- before this, a corpus where most notes are shorter than the
    threshold got vibrato on all of them.
    """
    if det.triangle_vibrato is None:
        return VIBRATO_DELAY
    return min(0xFF, max(1, TRIANGLE_VIBRATO_GATE * multiplier))


def _triangle_vibrato_entry(byte: int, multiplier: int) -> Optional[tuple]:
    """Speed-table entry for the global-triangle dialect's shift-count byte.

    The player (detect._find_triangle_vibrato, 25 corpus files) does

        frequency = note + phase x (interval_at_note >> (byte + 1))

    with `phase` the folded triangle `0,1,2,3,3,2,1,0` off a counter stepped
    once per play call. Both halves of the mapping come from *simulating*
    gplay.c:795-801 rather than reading its constants, which is the discipline
    § 7.ll exists to enforce. Simulated, Goattracker's oscillator obeys two
    exact laws:

        period       = 2 * cmp + 4   play calls
        peak-to-peak = (cmp + 2)     * speed

    (the first restates the documented `cmp + 2` half-period, which is what
    makes the simulation trustworthy rather than novel.)

    * **Period.** The player's counter steps once per *frame* and eight steps
      make a cycle, so its half-period is `TRIANGLE_VIBRATO_PERIOD / 2` = 4
      frames. Goattracker's is `cmp + 2` *calls*, i.e. `(cmp + 2) / multiplier`
      frames. Hence

          cmp = (PERIOD / 2) * multiplier - VIBRATO_CMP_BIAS

      which is the classic mapping's own formula at a fixed bound of 4 -- this
      dialect simply has no per-instrument period to read.

    * **Excursion.** The player's phase runs `0..PEAK`, so its peak-to-peak is
      `PEAK * (interval >> (byte + 1))`; it is one-sided, the note sitting at
      the bottom of the swing rather than the middle, exactly as the classic
      player's is one-sided the other way. Equating peak-to-peak with
      `(cmp + 2) * speed = PERIOD/2 * multiplier * speed` and
      `speed = interval >> rshift`:

          rshift = byte + 1 + log2(multiplier) + log2((PERIOD / 2) / PEAK)

      `log2(4/3)` is 0.415, and `round(k + 0.415) == k` for any integer k, so
      the emitted shift is `byte + 1 + log2(multiplier)` -- coincidentally the
      classic mapping's expression, reached from different quantities.

    **The residual is a systematic 33% overshoot in depth, and it is the
    format's, not a slip.** Goattracker's note-relative speed can only be
    `interval >> k`, a power of two; the player wants three of them. 4/3 is
    the nearest expressible ratio and it is 1.33x too deep. Correcting it
    would need the absolute speed form, which does not track pitch the way
    this player does, so the depth is traded for the pitch-tracking.
    """
    if not byte or byte > TRIANGLE_VIBRATO_MAX_SHIFT:
        # The player's own `BEQ past`, and its own way of switching a record
        # off: a shift this large leaves nothing of the 16-bit interval. No
        # player in the family masks the byte -- Last_V8 stores 81.
        return None
    half = TRIANGLE_VIBRATO_PERIOD // 2
    cmp_value = min(0x7F, max(0, half * multiplier - VIBRATO_CMP_BIAS))
    rshift = min(byte + 1 + _rate_shift(multiplier), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _table_vibrato_entry(byte: int, tv, multiplier: int) -> Optional[tuple]:
    """Speed-table entry for one instrument byte in the LFO-table format.

    The command-table engine's vibrato is a table walked one entry per frame,
    the offset in frame `i` being `table[i] * count * (interval >> unit)` with
    `count` the parameter byte's low nibble and the table its high one; see
    detect._find_table_vibrato for the routine. All four tables in both corpus
    files are triangles, which is the only reason a fixed triangle can stand
    in for them at all -- an arbitrary shape could not be approximated, and
    this returns None for a table that is not one (peak or length unreadable).

    The table's LENGTH is the whole period in frames, against Goattracker's
    `2 * (cmp + 2)` calls, so matching the period gives

        cmp = length * multiplier / 2 - 2

    and matching the excursion equates the two amplitudes,

        (cmp + 2) / 2 * (interval >> rshift)
            == peak * count * (interval >> unit)

    which the interval cancels out of entirely, leaving

        rshift = log2((cmp + 2) * 2**unit / (2 * peak * count))

    rounded to the nearest integer -- Goattracker's depth is a shift, so only
    powers of two are reachable and the rounding is in log space, where the
    error is multiplicative and symmetric. Hollywood or Bust's seven vibrato
    records ask for ratios of 4, 4, 3, 5.33, 4, 8 and 4 -- five land on a
    power of two exactly and two round, the worst of them by a third.

    Both numbers come from the *simulated* gplay.c semantics (see
    VIBRATO_CMP_BIAS), not from the reading _classic_vibrato_entry above was
    built on. A `cmp` of 0 is a legal entry, not an empty one: `$80` still
    selects the note-relative speed and `cmpvalue & 0x7f` is then 0, which is
    the fastest oscillation Goattracker has -- 4 calls -- and exactly what the
    shortest of the four tables asks for.

    One approximation the classic mapping has and this does not: the player
    takes the interval *above* the note here (`freq(note+1) - freq(note)`),
    which is the one Goattracker computes. What remains is the shape: the
    player's table is a position sequence sampled per frame where Goattracker
    integrates a step per call, so the two triangles agree in period and
    excursion and differ in how they get there whenever the table is not
    symmetric -- table 1 (`0 1 2 1 0 -1`) spends four of its six frames above
    zero.
    """
    count = byte & 0x0F
    index = (byte & 0xF0) >> 4
    if not byte or not count or index >= len(tv.shapes):
        # The player's own test is on the whole byte (`LDA record+5,Y / BNE`
        # at Hollywood or Bust $05D1); a count of zero multiplies the unit by
        # nothing, which is the same silence reached one step later.
        return None
    length, peak = tv.shapes[index]
    if not length or not peak:
        return None
    half = max(1, round(length * multiplier / 2.0))
    cmp_value = min(0x7F, max(0, half - VIBRATO_CMP_BIAS))
    ratio = ((cmp_value + VIBRATO_CMP_BIAS) * (1 << tv.unit_shift)
             / (2.0 * peak * count))
    rshift = min(max(round(math.log2(ratio)), 0), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _vibrato_layout(sid: SidFile, det: Detection, instr_used: int,
                    vibrato: bool, fmt: str, multiplier: int,
                    speed_table: List[tuple], log=None,
                    lead: int = 1) -> dict:
    """{instrument index: (speed-table index, vibdelay)} for `--vibrato`.

    Goattracker runs a per-instrument vibrato with no pattern command at all:
    on every new note `gplay.c:352-354` loads `cptr->vibdelay = iptr->vibdelay`
    and `cptr->cmddata = iptr->ptr[STBL]`, and a channel whose command is
    CMD_DONOTHING falls through into CMD_VIBRATO once the delay expires
    (gplay.c:769-780). Those are instrument-record bytes 5 and 6, and this
    writer has always written `0x00, 0x00` there -- which is why no file it has
    ever produced vibrates, and why a third of the corpus moves the pitch not
    at all where the original does.

    Two player engines reach this, and they share no byte format: the classic
    $78-bound/$07-shift pair (56 corpus files, _classic_vibrato_entry) and the
    command-table engine's LFO table (2 files, _table_vibrato_entry). Both end
    at the same place -- a note-relative speed-table entry and a vibdelay --
    and the derivation of each is in its own function.

    GTS5 only. A GTS2 file stores no speed table -- its loader packs the
    vibrato into a single instrument byte and calls makespeedtable itself
    (gsong.c:285), and it reads bytes 5 and 6 the other way round
    (vibdelay first, gsong.c:284) -- so the same numbers would need a
    different encoding, and the byte-exact fixture is a GTS2 file.
    """
    if not vibrato or fmt != FORMAT_GTS5:
        return {}
    mult = max(1, multiplier)
    if det.vibrato_offset is not None:
        offset = det.vibrato_offset
        entry_of = lambda b: _classic_vibrato_entry(b, mult)
        engine = "bound/shift"
    elif det.table_vibrato is not None:
        offset = det.table_vibrato.offset
        entry_of = lambda b: _table_vibrato_entry(b, det.table_vibrato, mult)
        engine = "LFO table"
    elif det.triangle_vibrato is not None:
        offset = det.triangle_vibrato
        entry_of = lambda b: _triangle_vibrato_entry(b, mult)
        engine = "global triangle"
    else:
        return {}
    delay = _vibrato_delay(det, mult)
    data = sid.data
    out: dict = {}
    for i in range(max(instr_used - lead, 0)):
        base = det.instr_start + i * det.instr_stride + offset
        if base >= len(data):
            continue
        entry = entry_of(data[base])
        if entry is None:
            continue
        if entry not in speed_table:
            if len(speed_table) >= GT_MAX_TABLELEN:
                continue
            speed_table.append(entry)
        out[i] = (speed_table.index(entry) + 1, delay)
    if log and out:
        log(f"Instrument vibrato......: {len(out)} of "
            f"{max(instr_used - lead, 0)} record(s), "
            f"{len({v[0] for v in out.values()})} speed-table entry(ies) "
            f"({engine})")
    return out


def _arp_relative(arp_fixed: int, arp_note: int) -> int:
    """The wavetable right-side byte for the arpeggio's alternate note.

    Readme p.794: `$00-$5F` is a relative note up, `$60-$7F` a negative one,
    so `$80 - N` is N semitones down. The two dialects go opposite ways -- the
    nibble form's `SBC` lowers the note, the fixed form's `ADC` raises it -- so
    the sign is a property of the routine, not of the record.
    """
    if arp_fixed:
        return arp_note & 0x5F
    return (0x80 - arp_note) & 0xFF


def _wavetable_entries(sid: SidFile, det: Detection, i: int, effects: bool,
                       fmt: str, speed_table: List[tuple],
                       multiplier: int = 1,
                       min_notes: Optional[dict] = None,
                       lead: int = 1,
                       start: Optional[int] = None,
                       budget: int = WAVE_ENTRIES_PER_INSTR,
                       two_stage: bool = False,
                       sfx_drum: bool = False,
                       wave_program: bool = False) -> tuple:
    """The five (left, right) wavetable entries for instrument `i`.

    With `effects` false this reproduces the VB6 original exactly, fabricating
    a drum and an arpeggio from bits $01 and $04 of every instrument record in
    every file. With it on, each bit is read only where detection found the
    routine that reads it (det.effect_drum / det.effect_arp / det.effect_rise),
    because +7 is not a shared format: see detect._find_effect_routines and the
    census in H2G-CONVERSION-METHOD.md section 7. Corpus-wide that gate is the
    larger half of this function's error -- 159 of 450 records setting the drum
    bit and 544 of 683 setting the arpeggio bit are in a player with no such
    routine, and the original invents the effect for all of them.

    Where the drum routine *is* present the shape is also deepened; see
    _drum_entries.
    """
    data = sid.data
    base = det.instr_start + i * det.instr_stride
    arp_style = data[base + 7]
    wave = data[base + 2]

    # The fixed-interval dialect takes no interval from the record: its
    # routine adds a hardcoded octave (detect.arp_fixed_up), so the nibble
    # carries no information and the "zero nibble means no arpeggio" rule
    # below must not apply to it.
    # Gated on `effects` like every other read of the +7 byte: with the flag
    # off this function reproduces the VB6 original exactly, and the original
    # knew nothing of either dialect.
    arp_fixed = det.arp_fixed_up if effects else 0
    arp_note = arp_fixed or ((arp_style & 0xF0) >> 4)
    # The original substitutes $74 -- a +12 relative note, an octave-up
    # arpeggio -- whenever the high nibble is zero. The player does no such
    # thing: the nibble is written into the operand of the `SBC` at $13F4
    # ($13DB `STA $13F5`), so a nibble of zero subtracts zero and both halves
    # of the alternation play the same note. Half of every arpeggio instrument
    # in the corpus (315 of 660 records) has nibble zero, so the substitution
    # invents an octave arpeggio for all of them.
    drum = (arp_style & 1) == 1
    arp = (arp_style & 4) == 4
    tick = False
    if effects:
        if not det.effect_drum:
            drum = False
        elif drum and (data[base + 4] >> 4):
            # A record whose envelope sustains is not percussive, and the drum
            # shape is wrong for it in *both* its parts -- not just the pitch
            # sweep. Its second entry releases the gate, so a held tone drops
            # into its release on frame 2 and can never sustain at all. A
            # listener caught the sweep first ("out of tune") and then this,
            # once the sweep was gone ("still not correct"): the record was
            # still getting the drum's gate-off. Suppressing only half of the
            # treatment was the bug. See _drum_entries for the sustain rule.
            #
            # It owes the noise tick even so. The drum block's opening two
            # frames of noise are not part of the percussive treatment -- the
            # player writes them for any record carrying the bit -- and
            # dropping the whole block dropped those too, which is why
            # instrmap.py reports four of Commando's instruments opening on
            # noise in the original and on a pitched waveform here.
            drum = False
            tick = True
        if not det.effect_arp or arp_note == 0:
            arp = False
    if arp_note == 0:
        arp_note = 0x74

    # The byte-code wave program is the whole instrument where it applies: the
    # player's interpreter writes $D404 and $D401 itself and returns, so no
    # other shape in this function is reached for such a record.
    if wave_program and speed_table is not None:
        prog = _wave_program_entries(sid, det, i, speed_table, fmt,
                                     multiplier, budget)
        if prog is not None:
            return prog

    # The bit-$80 drum, read before everything else because it is the whole
    # note: the player skips its own waveform and frequency writes on the frame
    # it fires (`BNE` past them), so nothing else in this function applies to
    # the instrument. Loops for as long as the note is held, as the player's
    # per-voice counter does.
    if (sfx_drum and det.sfx_pitch >= 0 and (arp_style & 0x80)
            and fmt == FORMAT_GTS5):
        hit = _sfx_drum_entries(wave, det.sfx_pitch, det.sfx_period, multiplier)
        if hit is not None:
            left, right = hit
            jump = len(left) + 1
            if start is not None and jump <= budget:
                return left + [0xFF], right + [start]

    # Read before the drum and arpeggio shapes because in this dialect bit $04
    # is neither: `_find_two_stage` only reports a player whose $04 handler is
    # the attack-waveform block, and such a player sets neither effect_drum nor
    # effect_arp, so the two can never both apply to one record. Gated on
    # `effects` like every other reading of +7 -- with the flag off this
    # function still reproduces the VB6 original byte for byte.
    if (two_stage and det.effect_two_stage and (arp_style & 0x04)
            and det.two_stage_wave >= 0):
        at = det.two_stage_wave + i * det.instr_stride
        fr = det.two_stage_frames + i * det.instr_stride
        if max(at, fr) < len(data):
            two = _two_stage_entries(wave, data[at], data[fr], multiplier)
            if two is not None:
                return two

    arp_set_keybit = 0 if drum else 1
    tail = (wave & 0xFE) | arp_set_keybit

    left = [wave, 0x00, tail, 0xFF, 0xFF]
    right = [0x00, 0x00, 0x00, 0x00, 0x00]

    # The tick goes at entries 1-2, not 0-1: the player writes the note's own
    # waveform on the note's first frame and the drum block's noise only from
    # the second. Traced on Commando's original, voice 0 reads
    # `15 80 80 14 14` from each onset -- own waveform, two frames of noise,
    # then the gate-off waveform. Putting the noise at entry 0 makes it two
    # frames early and drops that opening frame entirely.
    #
    # `off` is how far that pushes everything after it, so the arpeggio's and
    # the rise's jump targets still name the entry they mean. Variable-length
    # wavetables (v0.5.163) are what make the extra entries affordable.
    off = 0
    if tick:
        noise = WAVE_NOISE_GATEOFF | (wave & 0x01)
        extra = NOISE_TICK_FRAMES * max(1, multiplier) - 1
        tl, tr = [noise], [0x00]
        if extra == 1:
            tl.append(noise)
            tr.append(0x00)
        elif extra > 1:
            # A delay is current for value + 1 calls, and its right side is
            # read on the last of them, so $80 keeps it from moving the note.
            tl.append(min(extra - 1, WAVE_MAX_DELAY))
            tr.append(0x80)
        off = len(tl)
        # Two `tail` entries, mirroring the untimed shape's entries 1-2: the
        # arpeggio loops over the second of them and the entry after it, so
        # collapsing them to one puts the stop where the arpeggio's own
        # entries belong and the loop is never reached.
        left = [wave] + tl + [tail, tail, 0xFF, 0xFF]
        right = [0x00] + tr + [0x00, 0x00, 0x00, 0x00]

    # A record that sets both bits gets both blocks in the player -- the drum
    # sets the waveform, the arpeggio then overwrites the frequency it swept
    # ($13F4 runs after $139F). Five entries cannot hold both, so the arpeggio
    # keeps the pair it needs and such a record stays on the original's shape.
    # 62 of the 291 drum records this gate keeps are in that case.
    if drum and effects and not arp:
        # min_played_notes is keyed by Goattracker instrument number, and this
        # function's `i` is the 0-based record index: instrument 1 is the
        # hardcoded Clear Voice, so record i is instrument i + 2.
        lowest = None if min_notes is None else min_notes.get(i + 1 + lead)
        return _drum_entries(wave, fmt, speed_table, multiplier, lowest,
                             sustain=data[base + 4] >> 4, budget=budget)

    if drum:
        if effects:
            # The arpeggio keeps entries 2-4, so all the drum can say here is
            # where it starts: the voice's own waveform, gate released. The
            # leading noise tick the original wrote is not in the player at
            # all, and on the corpus it scores at chance.
            left[1] = (wave & 0xFE) or WAVE_NOISE_GATEOFF
        else:
            left[1] = 0x80 | arp_set_keybit
            right[1] = (0x80 - arp_note) & 0xFF
    elif not tick:
        # A ticked record already owns entry 1, and its tails sit at 3-4.
        left[1] = tail

    # The instrument's own entries are 1-based indices i*5+6 .. i*5+10, so its
    # third is i*5+8 -- the loop target for both the arpeggio and the rise.
    # The arpeggio and the rise both jump back to entries of their own block,
    # so the targets are this instrument's real start -- not arithmetic on its
    # index, which stops being true the moment any earlier record is longer
    # than WAVE_ENTRIES_PER_INSTR.
    base_entry = start if start is not None         else (lead + i) * WAVE_ENTRIES_PER_INSTR + 1
    first = base_entry & 0xFF
    third = (base_entry + 2 + off) & 0xFF

    if arp:
        # $13CD: alternate between the note and the note minus the high
        # nibble, one frame each. Readme p.794: right side $60-$7F is a
        # negative relative note, so $80-N is -N semitones.
        hold = _wave_hold_byte(multiplier, wave)
        if hold is None or tail != wave or tick:
            # -S1: a call is a frame, so the plain two-entry loop is already
            # at the player's rate. A ticked record is forced onto this shape
            # too: the multiplier shape below loops back to entry 0, which
            # would replay the noise tick once per arpeggio cycle.
            left[3 + off] = tail
            right[3 + off] = _arp_relative(arp_fixed, arp_note)
            right[4 + off] = third
        else:
            # At -S{m} each half must last m calls, which needs a hold entry
            # beside each -- five slots for attack + 2x(note, hold) + jump,
            # one too many. The jump target buys the slot back: it loops to
            # entry 0 rather than to `third`, so the attack entry doubles as
            # the first call of the note half. That is only sound because the
            # attack byte and `tail` differ at most in the gate bit and are
            # equal in all 45 corpus records reaching this branch -- re-entering
            # entry 0 rewrites the same waveform. `tail != wave` above keeps
            # anything else on the -S1 shape rather than emitting a retrigger
            # once per arpeggio cycle.
            #
            # A hold entry's right side is read on its final call
            # (gplay.c:705-717 falls through to the note code), so entry 3
            # carries $80 -- "no note change" -- or it would drag the
            # arpeggio note back to the base note one call early.
            left[1], right[1] = hold, 0x00
            left[2], right[2] = tail, _arp_relative(arp_fixed, arp_note)
            left[3], right[3] = hold, 0x80
            right[4] = first
    elif effects and det.effect_rise and (arp_style & 2) == 2:
        index = _rise_speed_index(fmt, speed_table, multiplier)
        if index:
            left[2 + off] = WAVECMD_PORTAUP
            right[2 + off] = index
            right[3 + off] = third

    # The attack entry holds for one play call, which is one frame only at
    # -S1; under -S{m} it needs m. A delay entry ($01-$0F, held for N calls --
    # gcommon.h:56-57, gplay.c:698-704) buys those calls without spending a
    # waveform slot, and entry 1 is where it fits: in the plain and arpeggio
    # shapes entry 1 merely repeats entry 2's `tail`, and in the arpeggio's
    # case the loop runs over entries 2 and 3, so entry 1 is passed once.
    #
    # The rise shape is the exception -- its entry 2 is a command, so entry 1
    # is the only place the tail waveform is written, and the delay may take it
    # only where the tail *is* the attack byte and writing it changes nothing.
    hold = _wave_hold_byte(multiplier, wave)
    if hold is not None and not arp and not drum and not tick and (
            left[2] == tail or tail == wave):
        left[1] = hold

    return left, right


def _drum_entries(wave: int, fmt: str, speed_table: List[tuple],
                  multiplier: int = 1, min_note: Optional[int] = None,
                  sustain: int = 0,
                  budget: int = WAVE_ENTRIES_PER_INSTR) -> tuple:
    """The five wavetable entries for a record whose player really has a drum.

    Warhawk `$1366`, read out of the 6502 rather than inferred from the bit:

        1366  LDA effect / AND #$01 / BEQ out
        136D  LDA $15B1,X / BEQ out       ; per-voice drum counter, still running?
        1372  LDA $1576,X / BEQ out       ; drum length, set?
        1377  LDA $1579,X / AND #$1F / SEC / SBC #$01 / CMP $1576,X
        1385  BCC $1397                   ; R still large -> EARLY in the note
        1387  LDA $15B1,X / DEC $15B1,X / STA $D401,Y  ; freq HI -= 1 per frame
        1390  LDA $157C,X / AND #$FE / BNE $139F       ; the voice's own waveform
        1397  LDA $15B1,X / STA $D401,Y / LDA #$80     ; ... or noise
        139F  STA $D404,Y

    So the drum is the voice's own waveform with the gate released and the
    frequency falling one high byte per frame -- and noise at the *start* (the
    BCC branch, taken while the remaining-duration counter is still large),
    or throughout, when the waveform masked to `& $FE` is zero.

    **The branch direction was recorded backwards until v0.5.90.** `A` is
    `W - 1` (the note's original duration less one) and `M` is the counter
    still counting down from `W`, so `BCC` -- taken on `A < M` -- fires while
    the counter is large, which is the beginning of the note, not its end. The
    sweep then runs for the rest of it: `W - 1` steps per note against the one
    this writes -- confirmed in VICE at v0.5.91, where Bump_Set_Spike's voice-2
    frequency-high shadow walks `0D 0C 0B 0A 09 08 07`, one per play call. The
    single step here is an under-render, and `bend` reports it as an overshoot
    only because siddump names the player's 256-unit steps as notes rather than
    bends. See H2G-CONVERSION-METHOD.md section 7.ii. H2G's version was a single noise tick *first* and then the waveform,
    with no sweep at all.

    Emitted here: attack, the gate-off waveform, one or two steps of the
    sweep, stop. The step size is literal (see _drum_speed, which divides the
    player's per-frame step by the -S multiplier); the depth is bounded by what
    the wavetable can hold and by what cannot wrap.

    **Why two and not `W - 1`.** A wavetable command entry executes exactly
    once and then `ptr[WTBL]` advances unconditionally (gplay.c:715-724): the
    delay branch is the `wave <= WAVELASTDELAY` *else* of the command branch,
    so a command cannot be held or repeated, and N steps means N entries. This
    layout gives each instrument exactly WAVE_ENTRIES_PER_INSTR of them
    (`wave_ptr = i * 5 + ...`), of which the drum shape needs an attack, a
    gate-off waveform and a stop -- leaving room for two. Depth past that is
    not a floor problem but a *layout* one, and lifting it means variable-length
    wavetables against a 255-entry budget: see H2G-CONVERSION-METHOD.md section
    7.oo.

    The second step is written only where `_drum_steps_safe` can prove it
    cannot wrap for any note the instrument is played at -- 184 of the corpus's
    192 drum instruments, across 40 files. The eight it declines are Last_V8's,
    whose unattributable rows reach Goattracker's lowest note. The `wave`
    metric cannot see any of this: it compares waveform class, and the class
    does not change while the frequency falls.

    All five entries are in use either way, so unlike the plain shape this one
    has no slot for a delay: its attack entry lasts one play call at every -S
    value, and only the sweep *rate* is scaled by the multiplier.

    **The noise ending is deliberately not written.** Emitting it as a fourth
    entry costs 2.4 points of corpus wave agreement (60.5% -> 58.1%) and takes
    noise frames from 5680 to 10666 against the original's 11641: in
    Goattracker a gated-off voice keeps its last waveform latched until the
    next note, so a noise entry at the end of the table stands for the whole
    rest of the note, while the player stops writing $D404 the moment its
    counter runs out. Measured on the corpus, not argued.

    A record that also sets the rise bit loses the rise here; it needs the same
    slots. 4 files have the rise routine at all.
    """
    # The note opens on noise, for two frames, and then takes the voice's own
    # waveform. That is the `BCC` branch at Warhawk $1385 -> $1397: it fires
    # while the remaining-duration counter is still large, i.e. at the START of
    # the note, a direction section 7.ii corrected in v0.5.90 -- and the tick
    # is measurable, not inferred. Tracing Commando's original and taking the
    # length of the noise run at each onset splits cleanly in two: ADSR $0A09
    # holds noise for 11 frames (a real noise instrument), while five other
    # records hold it for exactly 2 and then switch to a pitched waveform --
    # 349 note onsets in that file alone. See instrmap.py.
    #
    # h2g removed this tick, on the stated grounds that "there is no such tick
    # in the player", judged by the corpus `wave` metric landing on a noise
    # frame about as often as noise occurs. The trace says otherwise, and the
    # VB6 original emitted it.
    # Entry 0 is the note's own waveform, and the tick follows it. The player
    # writes the waveform on the note's first frame and reaches the drum
    # block's noise only from the second -- Commando's original reads
    # `15 80 80 14 14` from each onset, visible in the siddump instrmap.py
    # publishes. Putting the noise at entry 0 (as this did) ran it two frames
    # early and dropped that opening frame.
    #
    # The noise keeps the record's own gate bit, where this used to clear it.
    # The player does clear it, but our first-frame waveform is $09 -- gate
    # *plus testbit*, and the testbit silences the oscillator -- so an entry 0
    # that also clears the gate leaves the envelope untriggered and the
    # instrument silent. Measured on Commando GT 13: 0 onsets against the
    # original's 14 with $80, and exactly 14 with $81.
    left = [wave, WAVE_NOISE_GATEOFF | (wave & 0x01)]
    right = [0x00, 0x00]
    # Two frames is `2 * multiplier` calls, of which the entry above is one.
    # A delay entry is current for `value + 1` calls (see _wave_hold_byte), so
    # one more entry covers the rest at every -S value the corpus uses; its
    # right side is $80 because a delay's right side IS read, on its final
    # call, and anything else would drag the note.
    extra = NOISE_TICK_FRAMES * max(1, multiplier) - 1
    if extra == 1:
        left.append(WAVE_NOISE_GATEOFF | (wave & 0x01))
        right.append(0x00)
    elif extra > 1:
        left.append(min(extra - 1, WAVE_MAX_DELAY))
        right.append(0x80)
    left.append((wave & 0xFE) or WAVE_NOISE_GATEOFF)
    right.append(0x00)
    left.append(0xFF)
    right.append(0x00)
    while len(left) < WAVE_ENTRIES_PER_INSTR:
        left.append(0xFF)
        right.append(0x00)
    index = _drum_speed_index(fmt, speed_table, multiplier)
    # The sweep goes only on a record whose envelope actually decays. The
    # player's own gate is a single cross-voice cell written at note-start
    # (section 7.ii), which no per-instrument wavetable can encode, so *some*
    # approximation is forced -- and "every record carrying the bit" is a bad
    # one. A sustain of 0 falls to silence: a hit, where a downward sweep is
    # the whoop of a tom or a kick. A record that sustains is a held tone, and
    # sweeping it does not decorate the note, it detunes it for the note's
    # whole length and then holds the wrong pitch. Found by ear: a listener
    # picked out one sustaining record (Commando's, sustain 4) as "out of
    # tune", and suppressing its sweep as "much better". 60 of the corpus's
    # 284 drum-flagged records sustain; the other 224 keep the sweep.
    if index and not sustain:
        # `budget` is how many entries this record may occupy in total; the
        # caller shrinks it when the 255-entry table is running out. Below the
        # fixed five it changes nothing, so a file with room behaves as it did.
        want = _drum_max_steps(min_note, multiplier)
        prefix = left[:-1] if left[-1] == 0xFF else list(left)
        # strip the padding the tick block added, keeping the tick itself
        while len(prefix) > 1 and prefix[-1] == 0xFF:
            prefix.pop()
        pre_r = right[:len(prefix)]
        room = max(0, budget - len(prefix) - 1)     # ... and the stop
        # No `max(1, ...)`: the tick's own four entries plus a stop already
        # fill WAVE_ENTRIES_PER_INSTR exactly, so forcing a step through would
        # push this record to six and, on a table close to full, past the
        # 255-row limit. A drum with no room loses its sweep, not its shape.
        steps = min(want, room) if want else min(
            room, 2 if _drum_steps_safe(2, min_note, multiplier) else 1)
        left = prefix + [WAVECMD_PORTADOWN] * steps + [0xFF]
        right = pre_r + [index] * steps + [0x00]
        while len(left) < WAVE_ENTRIES_PER_INSTR:
            left.append(0xFF)
            right.append(0x00)
    return left, right


# Steps the player itself can take: it sweeps once per frame for `W - 1`
# frames, and section 7.ii measured W across the corpus at 2-9 ticks. So eight
# is the deepest sweep any note is actually held long enough to receive, and a
# chain longer than that is not fidelity -- it is table space spent on frames
# the note has already finished. Before this cap the safe bound alone produced
# a 136-step chain and drove three files to the 255-row table ceiling.
DRUM_MAX_SWEEP_STEPS = 8

# Frames of noise the drum block writes before the voice's own waveform,
# measured off the original's trace rather than assumed: 349 of Commando's
# note onsets hold noise for exactly this many frames and then switch.
NOISE_TICK_FRAMES = 2


def _drum_max_steps(min_note: Optional[int], multiplier: int = 1) -> int:
    """Deepest sweep this record can take without wrapping, in wavetable steps.

    The safety bound and the musical target turn out to be the same number.
    The player sweeps until its own guard freezes the frequency at zero
    (section 7.ii), so "as deep as it can go" is what faithfulness asks for;
    and the deepest a Goattracker `CMD_PORTADOWN` chain can go without
    underflowing is exactly the distance from the *lowest note the record is
    played at* down to zero. Falling that far from any higher note lands short
    of silence but still travels most of the way -- which is the shape a tom
    has anyway.

    Returns 0 where no bound is known, so an unknown record keeps the shallow
    two-step form rather than guessing deep.
    """
    if min_note is None:
        return 0
    hi, lo = _drum_speed(multiplier)
    step = (hi << 8) | lo
    if step <= 0:
        return 0
    room = _note_freq(min_note) - DRUM_DEEPEN_MARGIN
    return max(0, min(room // step, DRUM_MAX_SWEEP_STEPS * max(1, multiplier)))


def _drum_speed_index(fmt: str, speed_table: List[tuple],
                      multiplier: int = 1) -> int:
    """1-based speed-table index for the drum's downward sweep, or 0.

    Zero for a GTS2 file for the same reason as _rise_speed_index: it stores no
    speed table, so an index written here would name whatever entry the
    loader's own reconstruction happened to put at that position.
    """
    if fmt != FORMAT_GTS5:
        return 0
    entry = _drum_speed(multiplier)
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _rise_speed_index(fmt: str, speed_table: List[tuple],
                      multiplier: int = 1) -> int:
    """1-based speed-table index for the effect byte's chromatic rise, or 0.

    Effect bit $02 makes the player raise the note by one semitone every four
    frames, for as long as the note is held: `$13A2 LDA effect / AND #$02`,
    then `LDA $15BF / AND #$03 / BNE` -- the global frame counter, so it acts
    only on every fourth frame -- then `INC $157F,X`, the voice's note index,
    and a rewrite of $D400/$D401 from the frequency table. 252 instrument
    records across 59 corpus files set it, and H2G read none of them.

    Goattracker cannot step a note from the wavetable without spending one
    entry per semitone, which the fixed five-entry-per-instrument layout has
    no room for. It *can* glide at a note-relative rate: readme.txt:171 says a
    speed-table left side with bit $80 set selects a realtime-calculated
    speed, and gplay.c:539-547 then computes it as the semitone interval at
    the current note shifted right by the table's right byte. A shift of 2 is
    a quarter of a semitone per frame -- the player's rate exactly, as a
    continuous glide rather than four-frame steps. That approximation is
    deliberate and is the only part of this mapping that is not literal.

    "Per frame" holds only at -S1: the shift is applied once per play call, so
    each doubling of the call rate needs one more shift to keep the same rate
    per frame. The multipliers this converter emits are 2 and 3 (ceil(3/f),
    f in 1..2), and 3 is not a power of two -- shift 4 divides by four where
    three is wanted, which is the closest either neighbouring shift gets.
    Recorded rather than hidden: at -S3 the rise glides 3/4 of the player's
    rate, where before this it glided three times it.

    Returns 0 for a GTS2 file, which has no stored speed table: its loader
    builds one from instrument vibrato bytes and *pattern* command columns
    only (gsong.c:285, :311-321) and reads the wavetable verbatim, so an index
    written here would name whatever entry happened to land at that position.
    """
    if fmt != FORMAT_GTS5:
        return 0
    entry = (SPEED_NOTE_RELATIVE, RISE_SHIFT + _rate_shift(multiplier))
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _wavetable_layout(sid: SidFile, det: Detection, instr_used: int,
                      effects: bool, fmt: str, speed_table: List[tuple],
                      multiplier: int, min_notes: Optional[dict],
                      lead: int, two_stage: bool = False,
                      sfx_drum: bool = False,
                      wave_program: bool = False) -> tuple:
    """(entries, starts) for the whole wavetable, laid out sequentially.

    Every instrument used to own exactly `WAVE_ENTRIES_PER_INSTR` entries at
    `index * 5 + 1`, which is why the drum sweep could never be more than two
    steps deep (section 7.tt): three of the five go to the attack, the gate-off
    waveform and the stop. Laying the table out sequentially and *recording*
    each start -- the shape `_pulse_layout` already uses, and for the same
    reason -- lets a record be longer than five when it has something to say.

    Two properties hold it together:

    * **Nothing shrinks.** Every block is padded back up to
      `WAVE_ENTRIES_PER_INSTR`, so a file where no record grows lays out byte
      for byte as it always did. That is what makes the change verifiable
      rather than merely plausible.
    * **Nobody starves.** Each record's budget is what remains after reserving
      the five entries every *later* record is owed, so a deep sweep early in
      the table can never push a later instrument out of it.
    """
    entries: List[tuple] = []
    starts: List[int] = []
    for _ in range(lead):
        starts.append(len(entries) + 1)
        entries += [(0x09, 0x00), (0xFF, 0x00),
                    (0x00, 0x00), (0x00, 0x00), (0x00, 0x00)]
    n = max(instr_used - lead, 0)
    for i in range(n):
        start = len(entries) + 1
        reserved = (n - i - 1) * WAVE_ENTRIES_PER_INSTR
        budget = max(WAVE_ENTRIES_PER_INSTR,
                     GT_MAX_TABLELEN - len(entries) - reserved)
        left, right = _wavetable_entries(sid, det, i, effects, fmt, speed_table,
                                         multiplier, min_notes, lead,
                                         start=start, budget=budget,
                                         two_stage=two_stage,
                                         sfx_drum=sfx_drum,
                                         wave_program=wave_program)
        starts.append(start)
        entries += list(zip(left, right))
    return entries, starts


def _write_wavetable(out: bytearray, sid: SidFile, det: Detection,
                     instr_used: int, effects: bool = False,
                     fmt: str = DEFAULT_FORMAT,
                     speed_table: List[tuple] | None = None,
                     multiplier: int = 1,
                     min_notes: Optional[dict] = None,
                     lead: int = 1,
                     entries: Optional[List[tuple]] = None) -> None:
    if entries is None:
        table = speed_table if speed_table is not None else []
        entries, _ = _wavetable_layout(sid, det, instr_used, effects, fmt,
                                       table, multiplier, min_notes, lead)
    out.append(_table_length_byte(len(entries), "wave"))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)


def _split_ticks(ticks: int) -> List[int]:
    """`ticks` as steps of at most GT_MAX_PULSE_TICKS, longest first.

    A pulse-table left side is a tick count in 01-7F -- 80 and above mean "set
    pulse width" instead -- so a leg longer than 127 calls has to be spelled as
    consecutive steps carrying the same speed. gplay.c:902 advances to the next
    entry when a step's counter reaches zero and the modulation simply
    continues, so N steps of the same speed and a single step of their total
    are the same sweep.
    """
    full, rest = divmod(ticks, GT_MAX_PULSE_TICKS)
    steps = [GT_MAX_PULSE_TICKS] * full
    if rest:
        steps.append(rest)
    return steps or [1]


def _pulse_program(sid: SidFile, det: Detection, i: int, pulse: bool,
                   multiplier: int) -> tuple[List[tuple], int | None]:
    """The pulse-table entries for instrument `i`, and where a jump loops back.

    Without `pulse`, or where the player has no sweep, this is what H2G has
    always written: one "set pulse width" from record bytes +0/+1, then stop.
    That is correct for the 328 corpus records whose sweep rate is zero and
    wrong for the 414 that sweep, which came out with a duty cycle frozen at
    its starting value -- audible as a flat, static timbre under notes that are
    otherwise right, and invisible to every metric in the repo (`wave` compares
    the waveform *class*, so pulse is pulse whatever its width).

    The player's sweep is a triangle: add `rate` to a 12-bit accumulator each
    frame, flip direction when the high nibble reaches either bound. In a
    Goattracker pulse table that is a "set" to the lower bound, an ascending
    step, a descending step, and a jump -- readme.txt:887-891 for the encoding
    and gplay.c:872-902 for the execution.

    Two places this is an approximation, both stated rather than hidden:

    * the player turns around when the high nibble *equals* a bound, so a rate
      that does not divide the span exactly overshoots by up to one step before
      flipping; the tick count here is the span divided by the speed, which
      turns around a fraction of a step early instead.
    * `multiplier` is the gt2reloc -S factor. Goattracker steps the pulse table
      once per play *call* (gplay.c:872, inside the per-call block) where the
      player steps once per *frame*, so at -S2 an unscaled speed would sweep at
      twice the player's rate. Dividing rounds, and an odd rate at -S2 cannot
      be expressed exactly; the tick count is recomputed from the speed that
      was actually emitted so the sweep still covers the right span.
    """
    data = sid.data
    base = det.instr_start + i * det.instr_stride
    static = [((data[base + 1] | 0x80) & 0xFF, data[base]), (0xFF, 0x00)]
    if not pulse:
        return static, None
    if det.pulse_bounds < 0:
        # Two engines share the instrument record, and which one a record uses
        # is the record's own effect bit $08. Ask the accumulate one first: it
        # returns None unless the bit is set, so the order is what routes them.
        if det.pulse_lo_base >= 0:
            program = _pulse_lo_program(sid, det, i, multiplier)
            if program is not None:
                return program
        if det.pulse_tri_hi >= 0:
            program = _pulse_tri_program(sid, det, i, multiplier)
            if program is not None:
                return program
        return static, None
    bounds_at = det.pulse_bounds + i * det.instr_stride
    rate_at = base + det.pulse_rate_field
    if bounds_at >= len(data) or rate_at >= len(data):
        return static, None
    rate = data[rate_at]
    bounds = data[bounds_at]
    low, high = bounds & 0x0F, bounds >> 4
    # rate 0 is the player's own "do not sweep"; high <= low leaves it no band
    # to travel, and what it does then depends on 12-bit wrap-around. Both keep
    # the static width -- an under-read never invents movement.
    if rate == 0 or high <= low:
        return static, None
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / multiplier)))
    steps = _split_ticks(max(1, ((high - low) << 8) // speed))
    entries = [((0x80 | low) & 0xFF, 0x00)]
    entries += [(t, speed) for t in steps]
    entries += [(t, (0x100 - speed) & 0xFF) for t in steps]
    return entries, 1


def _pulse_lo_program(sid: SidFile, det: Detection, i: int,
                      multiplier: int) -> tuple[List[tuple], int | None] | None:
    """The accumulate engine's entries, or None if this record does not use it.

    The other pulse engine, selected per *instrument* by effect-byte bit $08 and
    mutually exclusive with the sweep: 34 corpus files sweep, 21 accumulate, and
    none do both. It adds record +6 to the width's low byte every frame and
    writes only $D402, never $D403 -- so the duty cycle races around one
    256-wide band while the high nibble stays where the note put it.

    In a Goattracker pulse table that is a set to the seeded width, one
    ascending leg long enough to cross the low byte, and a jump back to the
    *set* rather than to the leg. Jumping to the set is what pins the high
    nibble: Goattracker's modulation carries into it (gplay.c:888-900) and the
    player never does, so a leg allowed to run on would climb out of the band
    the player stays inside.

    The approximation, stated rather than hidden: the player's accumulator wraps
    mod 256 and carries its phase into the next cycle, so a rate that does not
    divide 256 exactly starts each cycle a little further along. Restarting at
    the seed keeps the period and the band right and loses that drift. It also
    restarts with the note, which is correct here -- $D402/$D403 are reseeded at
    every note fetch (see `_find_pulse_lo`), so the engine has no state to carry
    across a note anyway.
    """
    data = sid.data
    rec = det.pulse_lo_base + i * det.instr_stride
    if rec + 7 >= len(data):
        return None
    # The player gates the block on the instrument's own bit $08. A record
    # without it keeps the static width, which is exactly what it plays.
    if not data[rec + 7] & 0x08:
        return None
    rate = data[rec + 6]
    if rate == 0:
        return None
    lo, hi = data[rec], data[rec + 1]
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / multiplier)))
    entries = [((0x80 | (hi & 0x0F)) & 0xFF, lo)]
    entries += [(t, speed) for t in _split_ticks(max(1, 0x100 // speed))]
    return entries, 0


def _pulse_tri_program(sid: SidFile, det: Detection, i: int,
                       multiplier: int) -> tuple[List[tuple], int] | None:
    """The triangle engine's entries, or None if this record does not sweep.

    The third pulse engine (`_find_pulse_tri`), and the one Commando's lead
    uses: a triangle across the 12-bit width between two nibbles fixed in the
    routine, stepped by `rate & $E0` every `(rate & $1F) + 1` frames. 24 corpus
    files carry it; before this it fell through to the static width, so an
    instrument whose whole character is a moving duty cycle came out frozen.
    Commando's GT 1 covers six 256-wide buckets in the original and sat on one.

    In a Goattracker pulse table: a set to the record's own width, an ascent to
    the upper bound, then a descent and an ascent that alternate forever. The
    first leg exists because the record starts mid-band -- `$AC0` of `$800`
    to `$E00` in Commando -- and starting the program at a bound instead would
    put every note's attack on a duty cycle the player never opens on.

    Three approximations, stated rather than hidden:

    * **The player's sweep free-runs and this one cannot.** The width lives in
      the instrument record, shared by every voice sounding it, and nothing
      reseeds it at note start; Goattracker reloads the pulse pointer whenever
      an instrument is triggered (gplay.c:375-379). So the original's phase at
      any given note is arbitrary and ours is always the record's own width.
      The band and the rate carry over; the phase cannot.
    * **A step above 127 cannot be expressed at all.** A Goattracker pulse
      speed is a signed byte (readme.txt:887-889, gplay.c:889-899), so the most
      the width can move is 127 per *call*. `rate & $E0` reaches 224, and at
      `-S1` a step that large is emitted at 127 and sweeps ~1.8x slow. The span
      stays right because the tick count is recomputed from the speed actually
      emitted -- the same trade the other two engines make.
    * The player turns around when the high nibble *equals* a bound, so a step
      that does not divide the span overshoots by up to one step; the tick
      count here turns a fraction of a step early instead.
    """
    data = sid.data
    rec = det.instr_start + i * det.instr_stride
    if rec + 7 >= len(data):
        return None
    # In 19 of the 24 files this engine is the else-branch of an effect-bit-$08
    # test and the accumulate engine is the then-branch; in the other five
    # there is no test and every record sweeps. Honouring the gate only where
    # it exists is what keeps those two readings apart.
    if det.pulse_tri_gated and data[rec + 7] & 0x08:
        return None
    step = data[rec + 6] & 0xE0
    if step == 0:                    # rate 0, or a rate that is delay-only
        return None
    delay = (data[rec + 6] & 0x1F) + 1
    speed = min(GT_MAX_PULSE_SPEED,
                max(1, round(step / (delay * max(1, multiplier)))))
    low, high = det.pulse_tri_lo << 8, det.pulse_tri_hi << 8
    width = min(max(((data[rec + 1] & 0x0F) << 8) | data[rec], low), high)
    entries = [((0x80 | (width >> 8)) & 0xFF, width & 0xFF)]
    first = (high - width) // speed
    if first:
        entries += [(t, speed) for t in _split_ticks(first)]
    # Measured from where the ascent actually stopped rather than from the
    # bound, so truncation cannot walk the band down into a 12-bit wrap --
    # Goattracker masks the width to $FFF (gplay.c:891) where the player clamps.
    ticks = _split_ticks(max(1, (width + first * speed - low) // speed))
    loop = len(entries)
    entries += [(t, (0x100 - speed) & 0xFF) for t in ticks]
    entries += [(t, speed) for t in ticks]
    return entries, loop


def _pulse_layout(sid: SidFile, det: Detection, instr_used: int,
                  pulse: bool, multiplier: int,
                  log=None, lead: int = 1) -> tuple[List[tuple], List[int]]:
    """The whole pulse table, plus each instrument's 1-based start entry.

    Entries were a fixed two per instrument until the sweep gave some of them
    four or more, so the start positions are returned rather than computed from
    a stride -- `_write_instruments` writes them into the records.
    """
    entries: List[tuple] = [(0x80, 0x00), (0xFF, 0x00)]
    starts = [1] * lead                # the empty Clear Voice, if present
    dropped = silent = 0
    for i in range(max(instr_used - lead, 0)):
        program, loop = _pulse_program(sid, det, i, pulse, multiplier)
        start = len(entries) + 1
        block = program if loop is None else program + [(0xFF, start + loop)]
        if len(entries) + len(block) > GT_MAX_TABLELEN:
            # Out of table: keep the instrument, lose only its movement.
            block, _ = _pulse_program(sid, det, i, False, multiplier)
            dropped += 1
        if len(entries) + len(block) > GT_MAX_TABLELEN:
            # Not even the static pair fits. Pointer 0 leaves the pulse width
            # alone (readme.txt:714) -- the record must still get one, or every
            # instrument after it reads another instrument's program.
            starts.append(0)
            silent += 1
            continue
        starts.append(start)
        entries += block
    if log and dropped:
        log(f"*** PULSE TABLE FULL -- {dropped} INSTRUMENT(S) KEEP A STATIC "
            f"WIDTH INSTEAD OF THEIR SWEEP"
            + (f", {silent} SET NO WIDTH AT ALL ***" if silent else " ***"))
    return entries, starts


def _write_pulsetable(out: bytearray, entries: List[tuple]) -> None:
    out.append(_table_length_byte(len(entries), "pulse"))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)


# Goattracker's filter table is bounded by MAX_FILT, not MAX_TABLELEN
# (gcommon.h:26), and it is the only table with a limit that low -- which is
# why entries are spent only on instruments whose routing byte actually routes
# a channel, rather than one block per instrument as wave and pulse do.
GT_MAX_FILT = 64

# Goattracker filter-table left side (readme.txt:905-913):
FILT_SET_CUTOFF = 0x00   # right side is the cutoff
FILT_SET_PARAMS = 0x80   # | passband; right side is resonance/routing
FILT_STOP = 0xFF
# "For N ticks, change cutoff by the signed right side." $7F is the longest a
# single step can run, and the sweep is meant to last the note, so one maximal
# step is the closest a static table gets to a per-frame accumulation.
FILT_MODULATE = 0x7F


def _filter_entries(sid: SidFile, det: Detection, instr_used: int,
                    lead: int = 1):
    """(entries, pointers) for the filter table, or ([], {}) when unreadable.

    The player adds a per-instrument step to a per-voice cutoff accumulator
    every frame and writes the result to $D416; Goattracker's filter table
    expresses exactly that as "set params, set cutoff, modulate". What it
    cannot express is the accumulator being *per voice* -- Goattracker has one
    filter and one cutoff for the whole tune, as the SID chip does, so two
    voices sweeping at once come out as whichever instrument was struck last.
    That is the chip's limit, not the format's: the original has the same
    single filter and the same last-writer-wins race.
    """
    filt = det.filter
    if filt is None:
        return [], {}
    data = sid.data
    entries: List[tuple] = []
    pointers: dict = {}
    for i in range(max(instr_used - 1, 0)):
        base = filt.offset + i * det.instr_stride
        if base + 1 >= len(data):
            break
        status = filt.status + i * det.instr_stride
        if status >= len(data):
            break
        # The player's own switch, not ours: it runs the whole filter block
        # only for an instrument whose status byte has bit $20 set. Reading the
        # array without this test gives a plausible resonance byte for every
        # instrument in every file that merely *contains* the routine.
        if not data[status] & FILTER_ENABLE_BIT:
            continue
        resctl, step = data[base], data[base + 1]
        if not resctl & 0x0F:
            continue  # routes no voice through the filter: nothing to hear
        block = [(FILT_SET_PARAMS | filt.passband, resctl),
                 (FILT_SET_CUTOFF, filt.cutoff)]
        if step:
            block.append((FILT_MODULATE, step))
        block.append((FILT_STOP, 0x00))
        if len(entries) + len(block) > GT_MAX_FILT:
            break
        pointers[i] = len(entries) + 1  # table steps are 1-based
        entries += block
    return entries, pointers


def _write_filtertable(out: bytearray, entries: List[tuple]) -> None:
    if not entries:
        out += bytes([0x02, 0x11, 0xFF, 0x22, 0x01])  # empty filter table
        return
    out.append(len(entries))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)


def _highest_instrument_referenced(patterns: List[List[int]]) -> int:
    """Largest instrument number any pattern row selects (column 1 of 4)."""
    highest = 0
    for pattern in patterns:
        for k in range(1, len(pattern), 4):
            if pattern[k] > highest:
                highest = pattern[k]
    return highest


def build_sng(sid: SidFile, det: Detection, tracks: List[List[int]],
              patterns: List[List[int]], log=None,
              fmt: str = DEFAULT_FORMAT,
              speed_table: List[tuple] | None = None,
              effects: bool = False, pulse: bool = False,
              multiplier: int = 1,
              sustain_exact: bool = False,
              no_hard_restart: bool = False,
              filters: bool = False,
              vibrato: bool = False,
              min_notes: Optional[dict] = None,
              compact_instruments: bool = False,
              no_test_restart: bool = False,
              two_stage: bool = False,
              sfx_drum: bool = False,
              wave_program: bool = False) -> bytes:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {fmt!r}")
    # _write_wavetable may append the note-relative entry the chromatic rise
    # needs, and the table is written after it, so give it a list to grow.
    table = list(speed_table or [])
    out = bytearray()
    out += _build_header(sid, fmt)
    # Derived from the tracks actually emitted, not sid.subtunes: convert_tracks
    # trims subtunes the track table cannot back, and the count byte must agree
    # with the number of tracks that follow or the file is unreadable. Identical
    # to sid.subtunes whenever nothing was trimmed.
    out.append((len(tracks) // 3) & 0xFF)

    for track in tracks:
        out.append((len(track) - 1) & 0xFF)
        out += bytes(track)

    lead = 0 if compact_instruments else 1
    instr_used = _instruments_used(det, log, lead)
    # The filter and pulse tables are both built before the instruments,
    # because each instrument record carries the table step it starts on --
    # but both are written after them, with the other tables. A swept
    # instrument's pulse program is longer than a static one's, so that start
    # position is not a stride either.
    if filters:
        filter_entries, filter_ptrs = _filter_entries(sid, det, instr_used,
                                                      lead)
    else:
        filter_entries, filter_ptrs = [], {}
    pulse_entries, pulse_starts = _pulse_layout(sid, det, instr_used, pulse,
                                                multiplier, log, lead=lead)
    # Before the records, because each one carries its speed-table index -- and
    # into `table`, which the wavetable also grows and the file writes last.
    vib_ptrs = _vibrato_layout(sid, det, instr_used, vibrato, fmt, multiplier,
                               table, log, lead=lead)
    # Before the records, because each one carries the wavetable step it
    # starts on -- and those starts are no longer a stride.
    wave_entries, wave_starts = _wavetable_layout(sid, det, instr_used, effects,
                                                  fmt, table, multiplier,
                                                  min_notes, lead, two_stage,
                                                  sfx_drum, wave_program)
    _write_instruments(out, sid, det, instr_used, pulse_starts,
                       sustain_exact, no_hard_restart, filter_ptrs, vib_ptrs,
                       lead=lead, wave_starts=wave_starts,
                       no_test_restart=no_test_restart)
    _write_wavetable(out, sid, det, instr_used, effects, fmt, table, multiplier,
                     min_notes, lead=lead, entries=wave_entries)
    _write_pulsetable(out, pulse_entries)

    if log:
        # Instruments are written as 1..instr_used, so anything above that is a
        # reference to a slot the file does not contain. Goattracker will play
        # those rows with an undefined instrument.
        highest = _highest_instrument_referenced(patterns)
        if highest > instr_used:
            log(f"*** PATTERNS REFERENCE INSTRUMENT ${highest:X} BUT ONLY "
                f"${instr_used:X} WERE WRITTEN -- {highest - instr_used} DANGLING ***")

    _write_filtertable(out, filter_entries)
    if fmt == FORMAT_GTS5:
        # Fourth table (STBL), stored only in GTS3+. A GTS2 file has none: its
        # loader builds one while reading, both from each instrument's vibrato
        # byte and from every portamento command's data column
        # (gsong.c:285, :311-321).
        #
        # So the same conversion that is correct in a GTS2 file is inert in a
        # GTS5 one unless the table is written out here -- gplay.c:740 reads a
        # portamento's speed from `ltable[STBL][cmddata-1]`, and against an
        # empty table that is zero, i.e. no pitch movement at all. See
        # patterns.build_speed_table.
        out.append(_table_length_byte(len(table), "speed"))
        out += bytes(left for left, _ in table)
        out += bytes(right for _, right in table)

    out.append(len(patterns) & 0xFF)
    for pattern in patterns:
        out.append((len(pattern) // 4) & 0xFF)
        out += bytes(pattern)

    return bytes(out)
