"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import List, Optional, Tuple

from .detect import (Detection, EFFECT_BIT40_MASK, FILTER_ENABLE_BIT,
                     decode_wave_program,
                     TRIANGLE_VIBRATO_GATE, TRIANGLE_VIBRATO_MAX_SHIFT,
                     TRIANGLE_VIBRATO_PEAK, TRIANGLE_VIBRATO_PERIOD,
                     VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     VIBRATO_SHIFT_MASK)
from .sidfile import GT_FREQ0, SidFile, find_freq_table

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
# Effect-byte bits whose routine writes the envelope registers on every
# frame, so the note-end cut (detect.ENVELOPE_CUT_SHAPES) is immediately
# overwritten and the record's release *is* audible after all. Bit $01
# alone: over the 143 unambiguous instruments of the 33 files that have the
# cut routine, `effect & $01 == 0` predicts the cut with 98.6% accuracy, no
# false negatives and 2 false positives. `& $07` scores 86.0%, `== 0` 78.3%.
#
# The same rule looked like 59.8% when first tested, because that test ran
# over all 95 files -- in the 62 with no cut routine nothing is cut whatever
# the effect byte says, so they contributed only false positives. A
# discriminator is only meaningful on the population the behaviour occurs
# in, and that mistake is why v0.5.200 shipped the cut for every record.
EFFECT_PER_FRAME = 0x01

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
# How long the gate is closed before each note, in *frames*. It is the low
# six bits of the instrument's gatetimer: Goattracker fetches the next note
# that many calls early and holds the gate off for them (gplay.c:905), which
# is this writer's only release between two adjacent notes.
#
# It was 2 **calls**, which is 2 frames at `-S1` and two thirds of one at
# `-S3`, against the players' own releases -- 3.3 frames on average, from the
# gate census. Measured in frames it is `frames * multiplier` calls, the same
# conversion every other rate in this file makes.
#
# **2 because 1 is worse and 3 buys nothing**, on the bytes rather than on a
# derived row: raising it to 3 changes 3 of 83 corpus files (Chicken Song,
# Mr Meaner, Rock Tells the Tale) and moves no dimension of the report, and
# 4 and 6 change exactly the same three. Lowering it to 1 changes 15 and
# costs 1.2pp of mean gate. So the constant is nearly inert, and the reason
# is that the two bounds below decide almost everywhere -- the floor for the
# single-speed files, the row for the multispeed ones.
#
# The lever is the row bound. Swept over the corpus: `row // 3` costs 1.7pp
# of gate for nothing, `2 * row // 3` and `row - 1` buy 1.6pp and 3.3pp and
# take Saboteur II's melody from 98% to 67% and 62%. `row // 2` is not a
# corpus optimum -- it is the last value before that single file breaks.
#
# `--wide-hard-restart` offers `2 * row // 3` per song, which is what a
# ceiling set by one file asks for. v0.5.276 declined to offer it, on the
# ground that a sixth `--fidelity` toggle "would double a four-hour search";
# that cost was never timed and is 8 minutes (v0.5.301), so the refusal had
# no basis and the option is searched per song like the other five.
HARD_RESTART_FRAMES = 2


def _hard_restart_ticks(multiplier: int, row_calls: int,
                        wide: bool = False, full: bool = False) -> int:
    """Calls to hold the gate off before a note, bounded by the row.

    **gplay.c:334 stops the song outright** when the gatetimer exceeds the
    channel's tick, so this can never reach the row length -- and the failure
    is total, not graceful: swept past the bound, Commando drops from 716
    attacks to 3 and Sanxion from 956 to 1. `row_calls` is the *shortest* row
    the file writes (convert passes `short_row_calls`), because a pattern
    shared between two tempos is short in the faster one.

    **At most half the row**, which is a claim about the music rather than
    about the player: a note that spends more of its slot released than
    sounding is not the note. Bounded only by `row_calls - 1` -- the
    player's own limit -- Saboteur II gets 6 calls of an 8-call row and
    melody falls 98% -> 62% with `retrig` 1.00 -> 0.81, while every other
    file that moved gained. Half of its row is 4, and the same sweep that
    found the collapse shows the gain surviving it.

    **`wide` raises that bound to `2 * row // 3`**, worth 1.6pp of mean gate
    over the corpus in v0.5.276's sweep and the value at which Saboteur II
    starts to break (melody 98% -> 67%). Half the row is the *safe* bound and
    two thirds is the *better* one everywhere else, which is a per-song
    question rather than a constant -- so it rides `--wide-hard-restart` and
    `fidelity_better` decides it, with `keeps_notes` as the guard that is
    meant to refuse it on files of Saboteur II's shape. At v0.5.302 it did
    exactly that: 9 of the 19 files it reaches took it and Saboteur II did
    not.

    **`full` goes to `row_calls - 1`, the player's own limit**, 3.3pp of mean
    gate in the same sweep and 98% -> 62% on the same file. It is offered on
    the strength of `keeps_notes` having demonstrably refused the gentler
    value where it hurts -- a guard that has caught the case once is evidence,
    where at v0.5.276 it was a hope. `full` outranks `wide`; see the comment
    at the branch.

    **Floored at 2**, the value this writer wrote for its whole life, so no
    single-speed file moves: Commando's row is 3 calls, half of which is 1,
    and dropping to 1 would rewrite every `-S1` conversion in the corpus to
    fix a defect the multispeed files have.

    Falls back to that constant where the row is unknown, which is what a
    caller building instruments without a tempo pass has.
    """
    want = max(1, HARD_RESTART_FRAMES * max(1, multiplier))
    if not row_calls or row_calls <= 1:
        return min(want, 2)
    # Ordered, not exclusive: the search tries every combination of its
    # toggles, so `full` and `wide` can arrive together and the wider of the
    # two has to win rather than the later-tested one. A song selecting both
    # has `wide` removed by `presets.prune_inert`, which drops any flag whose
    # removal leaves the bytes identical.
    if full:
        bound = row_calls - 1
    elif wide:
        bound = 2 * row_calls // 3
    else:
        bound = row_calls // 2
    ticks = min(want, max(1, bound))
    ticks = max(ticks, min(2, row_calls - 1))
    return min(ticks, row_calls - 1)

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

# Frames of noise the drum block writes before the voice's own waveform,
# measured off the original's trace rather than assumed: 349 of Commando's
# note onsets hold noise for exactly this many frames and then switch.
#
# **It is not 2 everywhere, and this is known to be wrong for more notes than it
# is right for.** Across every drum-flagged note in the corpus, a *pitched*
# record gets a run of 1 on 1548 notes and 2 on 934; Monty gives 1 where
# Commando gives 2 from a byte-identical routine, so the difference is in the
# surrounding order and not in any record byte. A record whose waveform carries
# no waveform bits gets noise for the whole note instead -- Hubbard's own
# comment, "ctrlreg 0 is always noise" -- and that half `_drum_entries` already
# emits correctly. Flipping this to 1 would suit the majority and break the one
# file whose drum a listener validated. See H2G-CONVERSION-METHOD.md 7.ggg.
NOISE_TICK_FRAMES = 2


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


def _pitch_seq_notes(sid: SidFile, det: Detection,
                     i: int) -> Optional[List[int]]:
    """Right-side note bytes for effect bit $10's arpeggio, or None.

    One entry per step of the player's cycle, in the order a wavetable should
    play them. Split out of `_pitch_seq_entries` so the composed block that
    carries bit $04's attack waveform as well (`_two_stage_pitch_seq_entries`)
    derives its steps from the same place rather than from a second copy of the
    rotation rule -- there is one rule and it is measured, see below.

    Gated **per record**, on this record's own effect byte: `det.pitch_seq` says
    only that the player reads the bit.
    """
    seq = det.pitch_seq
    if seq is None:
        return None
    data = sid.data
    rec = det.instr_start + i * det.instr_stride
    if rec + 7 >= len(data) or not data[rec + 7] & EFFECT_PITCH_SEQ_MASK:
        return None
    at = seq.index + i * det.instr_stride
    if at >= len(data):
        return None
    idx = data[at]
    pair = seq.pairs + 2 * idx
    if seq.base >= len(data) or pair + 1 >= len(data):
        return None
    steps = [data[seq.base]] + [data[pair], data[pair + 1]]
    steps = steps[:max(2, seq.steps)]
    if not any(steps):
        return None
    # **Rotated so the most common step follows the attack.** The player's phase
    # is global, so which step a note begins on is unknowable here; a wavetable
    # always starts at its first entry. Emitting the sequence as written puts
    # Trans-Atlantic's `+24` one frame into every note, where the player's
    # `(0, 24, 0)` gives 0 on two phases of three -- measured, that cost 4.2
    # points of mean melody across 26 files and took Chain Reaction and Zoolook
    # from 100% to 78%. Leading with the modal step is the likeliest value under
    # a uniform unknown phase, not a fit to the metric.
    modal = Counter(steps).most_common(1)[0][0]
    # Index 1, not index 0: entry 0 is the attack frame and must sound the
    # pattern's own note, so the modal step goes on the frame after it.
    turn = (steps.index(modal) - 1) % len(steps)
    steps = steps[turn:] + steps[:turn]
    return [_arp_relative(1, step) if step < 0x80
            else (0x80 - (0x100 - step)) & 0xFF for step in steps]


def _pitch_seq_entries(sid: SidFile, det: Detection, i: int,
                       wave: int, multiplier: int = 1) -> Optional[tuple]:
    """Wavetable entries for effect bit $10's arpeggio, or None.

    `detect.PitchSeq` reads the mechanism: `note = played note + seq[phase]` on a
    global three-step counter, in 34 of 95 corpus files. A wavetable says that
    directly -- one entry per step, the waveform held and the right side naming a
    relative note -- and loops for as long as the note is held, as the player's
    counter does.

    **The step is a rate, so it is divided by `multiplier` at the point it is
    encoded** -- which here means multiplied, because the quantity emitted is a
    number of table entries rather than a period: the player's phase counter
    advances once per *frame* of a 50 Hz original, a Goattracker wavetable steps
    once per *play call*, and one frame is `multiplier` calls, so each step holds
    `multiplier` entries. Without it a `-S3` file arpeggiates three times too
    fast. `_two_stage_pitch_seq_entries` has scaled its own copy of this cycle
    since it was written and flagged this path as not doing so ("consistent with
    this function only at multiplier 1"); the two now agree at every `-S`.

    Two honest limits. The player's phase is **global**, so it does not restart
    with the note; a wavetable always does, and the emitted arpeggio can sit up
    to `steps - 1` frames out of phase. On three frames that is inaudible. And a
    sequence of all zeroes is *no* arpeggio -- the instrument simply plays its
    note -- so it emits nothing rather than three identical entries.

    A record whose own `+2` waveform is zero is declined: every entry here puts
    `wave` on the left, and `$00`-`$0F` on a wavetable's left side is a *delay*,
    not a waveform, so such a block would say something else entirely. Bit $04
    gives such a record a waveform to hold -- see
    `_two_stage_pitch_seq_entries`, which is why that path does not repeat this
    guard.
    """
    if not wave & 0xF0:
        return None
    notes = _pitch_seq_notes(sid, det, i)
    if notes is None:
        return None
    # Spelled out rather than delayed: a delay entry's right side is applied
    # only on its last call (gplay.c:697-723), and the note this step names has
    # to be current from the first call of the frame it covers. The same reason
    # `_two_stage_pitch_seq_entries` spells every frame of its cycle out.
    hold = max(1, multiplier)
    if hold > 1:
        # **The attack frame's last write is entry 0 once a step is a frame
        # long, so the step that leaves the note alone has to move there.**
        # The packed player runs the wavetable from the note's *second* call
        # (player.s:908-911), so entry k covers calls `k*hold+1 .. (k+1)*hold`.
        # At `hold == 1` entry 0 lands on frame 1 and frame 0 is the firstwave,
        # which writes no note -- so the attack keeps the pattern's own pitch
        # whatever entry 0 says, and `_pitch_seq_notes` puts the modal (almost
        # always zero) step at index 1. At `hold >= 2` entry 0 covers frame 0
        # instead, and a transposing step there renames every note siddump
        # reads: Shockway_Rider's melody 98.6% -> 83.6%, its voice 2 dropping
        # from an exact 4-pitch match to five wrong pitches. Rotating one
        # further -- the modal step to index 0 -- is the *same* rule applied at
        # the multiplier, not a second one, and restores Shockway_Rider to
        # 98.6% and Star_Paws to 96.6% while keeping the scaled rate. It also
        # makes the option free where it was not: Chain_Reaction (-S3) forced
        # to `--pitch-seq` reads melody 77.6% unscaled, 78.6% scaled and
        # **99.8%** scaled-and-rotated, which is its score with the option off,
        # at 1039 reversals against 772. See H2G-CONVERSION-METHOD.md 7.ttt.
        notes = notes[1:] + notes[:1]
    left = [wave] * (len(notes) * hold)
    right = [n for n in notes for _ in range(hold)]
    return left, right


def _freq_table_note(sid: SidFile, index: int) -> Optional[int]:
    """Wavetable right-side byte for note `index` of the player's own table.

    Two mechanisms hand a wavetable an *absolute* pitch out of the player's
    frequency table -- bit $40's fixed attack (`_fixed_attack_note`) and bit
    $08's alternate note (`_note_alternate_note`) -- and both do it the same
    way: `sidfile.find_freq_table` locates the table the player indexes, the
    16-bit frequency at `2 * index` is read out of it, and the nearest of
    Goattracker's 96 notes names it. One helper rather than two copies,
    because it is a rule about the player and not about either caller
    (CLAUDE.md).

    Returns None where the byte cannot be a note. The player's table has a
    definite length and an index past it is reading something else; a zero
    frequency is the same. Neither is guessed at.
    """
    table = find_freq_table(sid)
    if table is None:
        return None
    if not 0 <= index < table.length:
        return None
    at = sid.to_offset(table.addr) + 2 * index
    if at + 1 >= len(sid.data):
        return None
    freq = sid.data[at] | (sid.data[at + 1] << 8)
    if not freq:
        return None
    note = min(range(96), key=lambda n: abs(_note_freq(n) - freq))
    return (WAVE_NOTE_ABS + note) & 0xFF


def _fixed_attack_note(sid: SidFile, det: Detection, i: int) -> Optional[int]:
    """Absolute-note byte for effect bit $40's fixed attack pitch, or None.

    The derivation, which took two wrong turns worth recording. The routine is

        LDA counter,X / BEQ + / DEC counter,X / LDA $116B,Y / JMP fetch
        + LDA gate,Y / BNE out / LDA note,X
        fetch  ASL / TAY / LDA table,Y / STA freqlo,X
                           LDA table+1,Y / STA freqhi,X

    and three things had to be pinned before it could be emitted:

    * **What the two cells are.** They feed `$D400`/`$D401` directly
      (`LDA freqhi,X / STA $D401,Y`), so they are the voice frequency.
    * **What the table is.** `sidfile.find_freq_table` locates it
      independently and returns the same address the routine indexes -- so the
      pitch is a *note*, not an arbitrary value.
    * **What indexes it.** `$116B,Y` read with `Y` as the instrument *number*
      gives 129 on Trans-Atlantic's record 1, which maps to `$1A03` and is not
      the pitch the trace shows. `Y` is the record **offset**: index × stride.
      At that offset the byte is `$34` = 52, and `freqtable[52]` is `$15EB` --
      exactly the frequency the original sounds on 226 of 226 frames.

    And the table it indexes is `det.wave_program`, the same array the `$08`
    interpreter reads as a *pointer low byte*. One cell, two meanings, chosen by
    the effect bit -- as with `$01` (drum or wave program) and `$80` (drum or
    program). Which is why this is gated on `det.effect_bit40`: read as a
    pointer it is not a note, and the `$08` records here hold 176, 201 and 178,
    i.e. `$3E00`, `$FF34` and `$3C00`, nonsense as pitches.

    Returns None where the byte cannot be a note -- the player's table has a
    definite length and an index past it is reading something else, which is a
    reading this function will not guess at.
    """
    if not det.effect_bit40 or det.wave_program < 0:
        return None
    # **Per record, not per file.** `det.effect_bit40` says the player reads the
    # bit; only this record's own effect byte says whether it is set. Checking
    # the file alone applied the pitch to Thundercats' drum, whose record does
    # not carry $40 -- 99 frames at a pitch the original never sounds there, and
    # melody 77% -> 72%.
    rec7 = det.instr_start + i * det.instr_stride + 7
    if rec7 >= len(sid.data) or not sid.data[rec7] & EFFECT_BIT40_MASK:
        return None
    off = det.wave_program + i * det.instr_stride
    if off >= len(sid.data):
        return None
    return _freq_table_note(sid, sid.data[off])


def _note_alternate_note(sid: SidFile, det: Detection,
                         i: int) -> Optional[int]:
    """Absolute-note byte for effect bit $08's alternate note, or None.

    `detect._find_note_alternate` reads the block (Flash Gordon `$139A`, 21
    corpus files, 80 records): the voice's pitch alternates every frame
    between the note the pattern played and a fixed note *number* held in a
    parallel per-instrument array, on the same per-voice counter bit $02's
    waveform alternation uses. The array is indexed by `i * instr_stride`
    like every other effect table in this family, and the byte in it is an
    index into the player's own frequency table -- so what a wavetable can say
    is the nearest absolute note.

    **Per record, not per file**, the rule bit $40 had to learn the hard way:
    `det.note_alternate` says the player reads the bit, and only this record's
    own effect byte says it is set.
    """
    if det.note_alternate < 0 or det.instr_start < 0:
        return None
    rec7 = det.instr_start + i * det.instr_stride + 7
    if rec7 >= len(sid.data) or not sid.data[rec7] & EFFECT_NOTE_ALT_MASK:
        return None
    off = det.note_alternate + i * det.instr_stride
    if off >= len(sid.data):
        return None
    return _freq_table_note(sid, sid.data[off])


def _first_frame_entry(wave: int, written: bool = False) -> bool:
    """Whether the note's first frame gets an entry of the record's own `+2`.

    **The player writes the record's `+2` waveform on the note's first frame
    and reaches the effect block only from the second** -- the same rule
    `_drum_entries` was corrected to in v0.5.172, which never propagated to the
    other two emitters. Measured on Trans-Atlantic, modal waveform class over
    frames 0..7 from each onset with identical note counts on both sides:

        GT 3 (`+7 $08`, the wave program, 43 onsets a side)
          ORIGINAL  tri   noise tri   pulse noise noise noise noise
          OURS      noise tri   pulse noise noise noise noise noise
        GT 5 (`+7 $24`, the two-stage attack, 24 onsets a side)
          ORIGINAL  pulse noise pulse pulse pulse pulse pulse pulse
          OURS      noise pulse pulse pulse pulse pulse pulse pulse

    Both are the original shifted one frame left, and both originals' frame 0
    is exactly `+2`'s class -- `$11` tri for GT 3, `$41` pulse for GT 5.

    **A `+2` of `$00` is the exception, and it is what makes this a function.**
    That record has no waveform and no gate on its first frame, so siddump sees
    no gate edge there and calls the *second* frame the onset: Trans-Atlantic's
    GT 4 (`+2 $00`, a five-frame `$11` attack) profiles as five frames of `tri`
    from offset 0 in the original, already aligned with what we emit. Adding an
    entry for its silent frame would move a block that is right. A wavetable
    cannot write `$00` as a waveform either ($00-$0F are delays), so there is
    nothing faithful to put there.

    **`written` is `--no-test-restart`, and it removes the entry entirely.**
    That option writes the record's own waveform into the instrument's
    `firstwave`, and the *packed* player -- unlike the editor's `gplay.c`,
    which executes the wavetable on the same call -- jumps straight to
    `mt_loadregs` after a new note's init (`player.s:908-911`), so the
    wavetable's first entry lands on the note's *second* call. `firstwave` has
    already put the record's waveform on frame 0; an entry here repeats it and
    pushes the whole effect one frame late. IK+ measured `tri tri noi tri`
    against the original's `tri noi tri pul` on three instruments, and the
    same shift on its two-stage records.
    """
    return not written and bool(wave & 0xF0)


def _first_frame_lead(wave: int, multiplier: int = 1,
                      force: bool = False, written: bool = False) -> tuple:
    """The entries that hold the record's `+2` waveform for the note's frame 0.

    `(left, right)`, empty where the record has no waveform to put there
    (`_first_frame_entry`) -- unless `force`, which keeps the entry whatever
    `+2` holds.

    **`written` beats `force`.** It is `--no-test-restart`, which puts the
    record's waveform in the instrument's `firstwave` -- and the packed player
    writes that on the note's first call without executing the wavetable at
    all (`player.s:908-911`), so frame 0 is already the record's waveform and
    an entry here is a duplicate that delays the effect by a frame. `force`
    says "this caller has always emitted the entry"; `written` says "the frame
    is already accounted for", and the second is about the file rather than
    about the caller's history.

    **`force` is for a caller that already emitted this entry unconditionally**,
    where dropping it would be a change of its own rather than the absence of
    an addition. `_drum_entries` is that caller: it has always opened on the
    record's waveform, including the records whose `+2` selects none, where the
    byte lands in the wavetable's `$00`-`$0F` delay range and holds the frame
    without writing it. Faithful for neither reading -- the player *writes*
    `$00` there and a delay does not -- but making the lead a whole frame and
    silently deleting it for those records are two changes, and only the first
    is measured here.

    **One frame is `multiplier` play calls, not one call.** A wavetable steps
    once per call, so at `-S2` a single entry covers only half of frame 0 and
    whatever follows finishes the frame -- and siddump samples the registers at
    the end of a frame, so frame 0 reads as the *effect* rather than as the
    waveform. That is the whole defect at one remove: the same emitters that
    put the effect on frame 0 outright were also, on every multispeed file,
    putting it there through an under-long lead.

    A delay entry is current for `value + 1` calls (gplay.c:697-704), so one
    extra entry covers any `-S` the corpus uses. Its right side is `$80` for
    the reason `_drum_entries` gives: a delay's right side *is* read, on its
    final call, and anything else would drag the note.

    Shared by `_drum_entries` and `_two_stage_entries` rather than written out
    in each -- this rule was prose in one function's docstring for 45 versions
    while two siblings in the same file contradicted it (CLAUDE.md).
    `_two_stage_pitch_seq_entries` spells its lead out instead, because that
    block needs a note on the right side of every call and a delay would
    supply one only on its last.
    """
    if written or not (force or _first_frame_entry(wave)):
        return [], []
    left, right = [wave], [0x00]
    rest = max(1, multiplier) - 1              # ...the entry above is one call
    if rest == 1:
        left.append(wave)
        right.append(0x00)
    elif rest > 1:
        left.append(min(rest - 1, WAVE_MAX_DELAY))
        right.append(0x80)
    return left, right


def _two_stage_frames(frames: int, effect: int) -> int:
    """How many frames bit $04's attack actually lasts, from its table byte.

    **A record that also sets bit `$40` sounds half of them**, and the byte on
    its own does not say so -- which is why H2G-CONVERSION-METHOD.md carried
    "the relationship between that byte and the shared `$0FAA,X` counter is not
    established" as an open question. It is a halving, measured across the
    corpus rather than reasoned:

        frames byte 2, effect $44   ->  1 frame   Sigma Seven $0FFD (124 onsets)
                                                  Ricochet $0CE8 (77)
                                                  Skate or Die $08D9 (300), $0AD8 (26)
        frames byte 4, effect $44   ->  2 frames  Trans-Atlantic $0A99 (150)
                                                  Sanxion $1909 (81), Pandora $0D99 (31)
                                                  Auf Wiedersehen Monty $0AF9 (10)
                                                  Knucklebusters $0AAD (4)
        frames byte 2, effect $04   ->  2 frames  Sigma Seven $2B9D (61)

    527 onsets on the first line alone and not one counter-example there; the
    `frames = 4` line is what rules out "always one frame", which the first line
    alone cannot distinguish from a halving.

    The mechanism this implies -- and it is an implication, not a reading of the
    6502 -- is that `$40`'s handler decrements the same per-voice attack counter
    `$04`'s does, so with both live it counts down twice per frame. That would
    make the halving exact rather than approximate, which is what the two
    measured points show.

    **One counter-example, recorded rather than smoothed over.** Lightforce's
    `$1FF9` is `$44` with a frames byte of 4 and measures 0 attack frames over
    15 onsets. Not explained. It is one record against nine.

    A halved byte never reaches zero here: `_two_stage_entries` declines a
    record whose frames are <= 0, and this returns at least 1 so such a record
    keeps an attack rather than silently losing the block.
    """
    if effect & EFFECT_FIXED_PITCH_MASK:
        return max(1, frames // 2)
    return frames


def _wave_alternate_entries(wave: int, alt: int, multiplier: int = 1,
                            start: Optional[int] = None,
                            budget: int = WAVE_ENTRIES_PER_INSTR,
                            written: bool = False,
                            alt_first: bool = False,
                            alt_note: Optional[int] = None) -> Optional[tuple]:
    """Bit $02's every-other-frame waveform, or None where it says nothing.

    `detect._find_wave_alternate` reads the block: the voice's waveform
    alternates each frame between the record's own `+2` and a second
    per-instrument table, chosen by the low bit of a per-voice frame counter.
    In 20 of the 21 corpus files carrying it the alternate is `$81` -- noise
    with the gate on -- so what it sounds is a noise frame every other frame
    under the note.

    **The phase is not free, and it is not guessed.** The note's first frame is
    spent by the init path writing the record's waveform (section 7.www), and
    the alternation runs from the second: W_A_R's instrument `$0900` reads
    `tri tri noi tri` on all 205 of its onsets, one shape with no distribution
    at all. So the shape is the frame-0 lead, then the pair, looping -- which
    is what a wavetable can hold. Contrast bit `$10`'s arpeggio (section
    7.ttt), whose global counter gives a note no reproducible starting phase.

    Each half lasts one *frame*, which is `multiplier` play calls, bought with
    a delay entry beside it exactly as `_first_frame_lead` does. The loop
    target is the first of the pair, so the lead is passed once per note and
    the alternation is continuous after it.

    **`alt_note` is effect bit $08, which is the same alternation applied to
    the note** -- a second block on the same counter and the same phase test,
    24 bytes after this one in Flash Gordon (`detect._find_note_alternate`).
    All 80 corpus records that set bit $08 also set bit $02, so the two are
    one shape and not two: the alternate half gets the alternate waveform
    *and* the alternate pitch, and the record's own half keeps its own of
    both. Passed as an absolute note byte (`_note_alternate_note`), None where
    the record does not set the bit or the index is not a note.

    The right side of the record's own half is `$00`, which is what puts the
    played note *back*: `gt2reloc` inverts bit 7 of every non-command right
    byte (`greloc.c:1339-1341`), so a `.sng` `$00` reaches the packed player
    as `$80` and writes `adc mt_chnnote,x / and #$7f` -- the note's own pitch
    -- on every call it is current for. `$80` would be no write at all, and
    the alternate pitch would simply stay. See `_hold_wave_program_entry`,
    where reading those two bytes the other way round made the whole
    `program` bucket of `VIBRATO.md` read zero.
    """
    if (alt <= WAVE_MAX_DELAY
            or (alt == wave and alt_note is None)
            or not (wave & 0xF0)):
        # An alternate in the delay range is not a waveform; an alternate
        # equal to `+2` alternates with itself; and a record with no waveform
        # of its own has nothing to alternate *from*. That last is a real
        # under-read rather than the one `_sfx_drum_entries` used to make: a
        # bit-$80 record with no waveform is the drum *alone* and is now
        # encoded (v0.5.253), where an alternation genuinely needs two.
        #
        # **`alt == wave` is a statement about the waveform only, so it stops
        # being a refusal the moment `alt_note` is present.** Bit $08 rides
        # this pair (see the docstring), and when the record's `+2` and its
        # alternate name the same waveform the *pitch* is the whole of what
        # the player alternates: same counter, same `AND #$01 / BEQ`, one half
        # sounding the pattern's note and the other the record's own index
        # into the player's frequency table. Declining there emitted a flat
        # note where the player sounds two.
        #
        # Corpus-wide this reaches **one record**: Dragons_Lair_Part_II's 24
        # (`+2 $81`, alternate `$81`, effect `$0A`, note index `$20` -> `$A0`),
        # the only record in any file where `alt == wave`, bit $08 is set, the
        # index resolves to a note, and the record is inside `det.instr_used`.
        # The other eleven bit-$08 records that resolve a note and reach no
        # alternation -- for any of these three reasons, or because the record
        # does not set bit $02 at all -- sit *past* `instr_used`: dead table
        # cells, the same shape the note-frequency census found. Neither of
        # the other two clauses fires on a single in-use record, so there is
        # no evidence to widen either of them on.
        # This one is played: 3 rows of GT pattern 39, reached by subtune 7
        # voice 1.
        #
        # **No column of `FIDELITY.md` can adjudicate this**, and that is
        # structural rather than a gap in the effort. The change moves a noise
        # instrument's *pitch*, and `nrun` compares run lengths while `melody`
        # reads the attack frame -- CLAUDE.md's own "no report column sees a
        # noise frame's pitch". The file is doubly unadjudicable: its traced
        # subtune is not the music our subtune 0 plays (15% on the diagonal,
        # 60% at o9), and this record only sounds in subtune 7, which nothing
        # traces. What is checked is the reach -- a corpus byte-hash names
        # this one file -- and `tests/test_note_alternate.py`.
        return None
    if start is None:
        return None
    lead, lead_r = _first_frame_lead(wave, multiplier, written=written)

    def half(w: int, note: int = WAVE_NOTE_BASE) -> tuple:
        # **`$00` re-asserts the played note and `$80` writes nothing.** This
        # comment had those two the wrong way round from v0.5.130 until the
        # `alt_note` work, on a reading of `player.s:976-977` alone: the
        # measurement it cited ("Hollywood or Bust's melody 58% -> 25% with
        # `$80` against 47% with `$00`") is right, and so is the byte, but the
        # reason is `greloc.c:1339-1341` -- `gt2reloc` packs every non-command
        # right byte as `b ^ $80`, so a `.sng` `$00` reaches the packed
        # player's `bne` as `$80`, takes the `bmi` path and writes
        # `adc mt_chnnote,x / and #$7f`, the note's own pitch. `$80` becomes
        # packed `$00` and makes no write at all. Same conclusion, and the
        # difference matters the moment an entry beside this one sets an
        # absolute pitch, as `alt_note` does: `$00` is what takes it back off.
        # `_hold_wave_program_entry` is where this was measured.
        left, right = [w], [note]
        rest = max(1, multiplier) - 1          # ...the entry above is one call
        if rest == 1:
            left.append(w)
            right.append(note)
        elif rest > 1:
            # The delay carries this half's own note, so one block keeps one
            # convention -- and with `alt_note` that is no longer merely
            # tidiness. A delay entry's right side is read on its *last* call
            # (gplay.c:697-723), which is the last call of the frame and the
            # one siddump samples: `$00` there would put the played note back
            # a call after the alternate was set, and the alternation would
            # measure as flat. Recorded when it was only tidiness: `$80` and
            # `$00` are equivalent on a delay entry, traced on W_A_R both ways
            # with 0 of 1500 frames differing on all three voices; they are
            # *not* on a waveform entry (see `half`'s first line).
            left.append(min(rest - 1, WAVE_MAX_DELAY))
            right.append(note)
        return left, right

    # **Which of the pair the note's second frame gets is read off the
    # branch, not assumed.** Both dialects test the counter with
    # `AND #$01 / BEQ`, and in both the note's frame 1 takes the
    # *fall-through* -- the tabled dialect's is the record's own waveform
    # (W_A_R measures `tri tri noi tri`) and the derived dialect's is the
    # noise (Hollywood or Bust measures `tri noi tri noi`). Same rule, opposite
    # output, which is why this is a parameter rather than a constant.
    # The alternate note travels with the alternate *waveform*: one counter,
    # one branch, one phase -- the player's two blocks read the same cell with
    # the same `AND #$01 / BEQ`, so the frame that sounds the alternate
    # waveform is the frame that sounds the alternate pitch.
    own_note = WAVE_NOTE_BASE
    alt_r = own_note if alt_note is None else alt_note
    first, second = (alt, wave) if alt_first else (wave, alt)
    first_r, second_r = ((alt_r, own_note) if alt_first
                         else (own_note, alt_r))
    a_l, a_r = half(first, first_r)
    b_l, b_r = half(second, second_r)
    left = lead + a_l + b_l
    right = lead_r + a_r + b_r
    if len(left) + 1 > budget:
        return None
    return left + [0xFF], right + [(start + len(lead)) & 0xFF]


def _two_stage_entries(wave: int, attack: int, frames: int,
                       multiplier: int = 1,
                       attack_note: Optional[int] = None,
                       budget: int = WAVE_ENTRIES_PER_INSTR,
                       written: bool = False) -> tuple:
    """Wavetable entries for the two-stage waveform, or None if it says nothing.

    The dialect `detect._find_two_stage` reads, in 44 corpus files: effect bit
    $04 is not an arpeggio but an *attack waveform*, held for a per-instrument
    number of frames and then dropped to the record's own +2. Detection has
    located both arrays since it was written and nothing consumed them, so
    every one of those files played the second stage from its first frame.

    What that costs is not subtle. Trans-Atlantic's GT 2 is `$81` noise for 4
    frames before its pulse -- 226 notes of drum the conversion played as a
    pulse -- and its GT 4 has **no waveform of its own at all** (`+2` is `$00`),
    so the attack is the only waveform it ever has and the instrument was
    silent for all 70 of its notes.

    A record whose `+2` is zero has **no** second stage: the player writes
    `$00` there, which selects no waveform and stops the sound outright. That
    used to be emitted as the attack waveform released, on the grounds that a
    wavetable cannot say `$00` -- `$00`-`$0F` are delays. It can: `$18` is the
    test bit with a waveform selected, and the test bit holds the oscillator at
    zero, so it is silent in both players (`_wave_byte`). Trans-Atlantic's
    `$0AF8` is the one corpus record that reaches this: the original sounds
    five frames and stops, and the released attack kept sounding for the whole
    slot -- 11 frames on a twelve-frame note, and 23 on a twenty-four.

    `frames` is a per-frame count and the table steps per *call*, so it is
    scaled by `multiplier`; and a delay entry holds for `value + 1` calls, with
    entry 0 itself being one, exactly as `_wave_hold_byte` sets out.
    """
    if attack == 0 or frames <= 0:
        return None
    calls = max(1, frames) * max(1, multiplier)
    second = _wave_byte(wave & 0xFE) if not wave & 0xF0 else wave & 0xFE
    # `attack_note` is effect bit $40: the attack does not play the pattern's
    # note at all, it plays a fixed pitch out of the player's own note table
    # (detect._find_effect_bit40). Without it the attack sounded at whatever the
    # pattern asked for, and since these attacks are mostly noise -- whose pitch
    # is the rate its shift register clocks -- that is the difference between a
    # snare and a thud. Trans-Atlantic's GT 2 sounded its noise at frequency
    # high bytes 3-13 where the original sounds every one of 226 at $15EB.
    left, right = [attack], [attack_note if attack_note is not None else 0x00]
    extra = calls - 1             # entry 0 is already one call
    if attack_note is not None:
        # **The remaining calls are spelled out rather than folded into a
        # delay.** The reason recorded here was corrected once and is corrected
        # again: it read "the rest of the attack returns to the played note",
        # then was rewritten to "`$00` is no frequency write at all", citing
        # `player.s:976-977`. That second reading is the PACKED byte's, and
        # this is a `.sng` byte -- `gt2reloc` inverts bit 7 of every
        # non-command right byte (`greloc.c:1340-1341`), so a `.sng` `$00`
        # arrives as packed `$80` and DOES write: `adc mt_chnnote / and #$7f`,
        # the played note. The original wording was nearer the truth than its
        # correction.
        #
        # What actually separates the two forms is the other end. A delay's
        # right side is read on its FINAL call, so folding these into one
        # delay would re-assert the played note once at the end of the attack
        # instead of on every call of it -- and on a fixed-attack-pitch record
        # that is the difference between holding the pitch and dropping back.
        # Spelled out, every call carries the same byte and the shape is
        # explicit.
        #
        # THIS IS THE THIRD COMMENT IN THIS FILE ABOUT THAT ONE BYTE. The
        # other two (`WAVE_NOTE_BASE`'s definition and
        # `_wave_alternate_entries.half()`) were each corrected by a separate
        # change that did not know about this one, which is how a superseded
        # reading survived beside two correct ones. When this byte's meaning is
        # restated, grep the file for `greloc.c` and `976-977` and fix every
        # site, or the next reader will find the wrong one first.
        #
        # Holding is what the player does. One_on_One's GT 2 (`$44`, frames
        # byte 4 -> 2), 372 onsets and no distribution on any offset: the
        # played note on frame 0, then `$4310` on frames 1, 2 **and** 3 --
        # one frame past the attack waveform, which drops back to the
        # record's own `+2` on frame 3. So the fixed pitch outlives the stage
        # it belongs to, and a form that ended it early would be the wrong
        # one.
        left += [attack] * extra
        right += [0x00] * extra
    elif extra == 1:
        left.append(attack)       # no delay encodes one call; rewrite instead
        right.append(0x00)
    elif extra > 1:
        left.append(min(extra - 1, WAVE_MAX_DELAY))
        right.append(0x80)
    left += [second | (wave & 0x01), 0xFF]
    right += [0x00, 0x00]
    # The note's first frame is the record's own waveform; the attack starts on
    # the second. See `_first_frame_entry`. One frame is `multiplier` calls, the
    # same conversion `calls` above makes -- and the entries are dropped whole
    # rather than the block truncated where the 255-entry table has no room for
    # them, which is the degradation every other emitter here already makes.
    lead, lead_r = _first_frame_lead(wave, multiplier, written=written)
    if lead and len(left) + len(lead) <= budget:
        left[:0] = lead
        right[:0] = lead_r
    return left, right


def _gate_calls(calls: int, gate_skip: Optional[int]) -> int:
    """The player's own working calls expressed in ours.

    A player with an outer counter above its gate does nothing at all on one
    call in `O + 1` (`_find_outer_gate`), and Goattracker's player has no such
    counter -- so a duration of `n` of the original's *working* calls occupies
    `n * (O + 1) / O` of ours. The same correction `SongSpeeds.exact_row`
    makes to a row length, made to a table entry. `gate_skip` is None where
    the player has no counter, and None without `--skip-gate`, where the rows
    were not corrected either.
    """
    if not gate_skip:
        return calls
    return int(round(calls * (gate_skip + 1) / gate_skip))


def _voice_two_stage_entries(wave: int, alt: int, threshold: int,
                             multiplier: int = 1,
                             budget: int = WAVE_ENTRIES_PER_INSTR,
                             written: bool = False,
                             gate_skip: Optional[int] = None
                             ) -> Optional[tuple]:
    """Bit $02's attack where its parameters are per voice, or None.

    The same *shape* as `_two_stage_entries` -- an attack waveform, then the
    record's own -- so it delegates rather than re-emitting one; what is new is
    where the two parameters come from. `detect._find_voice_two_stage` reads
    them out of two static three-byte tables the player indexes by voice, so
    the caller has already resolved which voice this instrument is played on
    (`tracks.instrument_voices`) and passes that voice's pair.

    **`threshold - 1`, and the `- 1` is measured rather than reasoned.** The
    player compares a per-note frame counter against the threshold, and the
    counter is zeroed and then incremented on the note's *first* call, which
    is the one call that never reaches the effect block -- the note-start path
    jumps straight past it (Ninja `$C95C`). So the second call reads 1, not 0,
    and the attack ends `threshold - 1` calls later. Traced three ways on
    Ninja's voice 3, whose pair is `$15`/4: the file as it ships sounds the
    alternate for four displayed frames of which one is a skipped gate call,
    a copy patched to `threshold = 1` sounds it for none at all, and a copy
    with the alternate's table load redirected to the counter prints the
    counter itself into `$D404`. The first of those alone reads as `threshold`
    frames and is the wrong reading; it took the second to separate them.

    **Then corrected for the gate the player skips calls on.** Those three
    active calls occupy four *displayed* frames on Ninja, whose outer counter
    (`$C806`, `DEC / BPL / reload 3 / RTS`) does nothing on one call in four,
    and our player has no such counter -- see `_gate_calls`. Measured against
    the uncorrected form on the one file that carries this: `slides` 947 ->
    1026 of the original's 1338, `bend` 0.67x -> 0.75x and `vib` 0.59x ->
    0.79x, with `onset`, `melody` and `wave` unmoved. Both readings give 4 for
    a threshold of 4, which is every threshold this corpus actually reaches --
    they part company at Ninja's third voice, whose 6 is `_gate_calls(5) = 7`
    against a bare `threshold` of 6, and no instrument is played there. So the
    ratios above are what chose the correction; the arithmetic is what makes
    it a reading rather than a coincidence.
    """
    return _two_stage_entries(wave, alt, _gate_calls(threshold - 1, gate_skip),
                              multiplier, budget=budget, written=written)


def _two_stage_pitch_seq_entries(wave: int, attack: int, frames: int,
                                 notes: List[int], start: int,
                                 multiplier: int = 1,
                                 budget: int = WAVE_ENTRIES_PER_INSTR,
                                 written: bool = False) -> Optional[tuple]:
    """One block carrying bit $04's attack waveform *and* bit $10's arpeggio.

    The two bits are **sequential, independent tests on the same effect byte**,
    not exclusive branches. Read off Trans-Atlantic's player, whose record byte
    +7 is copied to the scratch cell `$0EFB` once and then tested five times in
    a row -- `$08` at $0B44, `$04` at $0B9C, `$10` at $0BB8, `$20` at $0BEB and
    `$40` (as `BIT`/`BVC`) at $0C05:

        0B9C  LDA $0EFB / AND #$04 / BEQ $0BB7   ; bit $04: the *waveform*
        0BA3  LDA $0FAA,X / BEQ +                ;   attack counter still running?
        0BA8  DEC $0FAA,X / LDA $116C,Y          ;   yes: the attack waveform
        0BB1 +LDA $10DB,Y                        ;   no:  the record's own +2
        0BB4  STA $0D5E,X                        ;   -> the voice's waveform cell
        0BB7  CLC
        0BB8  LDA $0EFB / AND #$10 / BEQ $0BEB   ; bit $10: the *note*
        ...   LDY $107C / LDA note,X / ADC seq,Y ;   played note + this step
        0BDC  LDA $0C8C,Y / STA $0EE5,X          ;   -> the voice's frequency
              LDA $0C8D,Y / STA $0EB5,X

    Nothing between $0BB7 and $0BB8 can skip the second test, so a record whose
    effect byte is `$14` gets both: the attack's waveform and, on the same
    frames, the arpeggio's note. Trans-Atlantic's record 3 (`0AF8`) is the one
    such record any corpus file plays with both options on, and the original's
    trace shows exactly that -- five frames of `$11` from the note's onset with
    the frequency stepping `+24, 0, 0, +24, 0` through them, and the arpeggio
    continuing after the waveform goes to `$00`.

    So the arpeggio runs across *both* stages, and the block loops on the
    sustain stage rather than stopping there, because the player keeps writing
    the frequency for as long as the note is held. Every frame gets its own
    entry: a delay entry cannot carry a note that changes on the frames it
    covers (gplay.c:697-723 applies the right side only on the delay's last
    call), which is the cost of the mechanism and not a choice.

    The rate is scaled the way `_two_stage_entries` scales `frames`: the
    player's phase counter advances once per frame of a single-speed original,
    and the wavetable steps once per *play call*, so each step holds
    `multiplier` entries. `_pitch_seq_entries` **now does the same** -- it did
    not for as long as this function has existed, and this docstring flagged the
    divergence rather than fixing it ("consistent with this function only at
    multiplier 1"). It also over-counted the reach: the flag said correcting the
    standalone path "would move three shipped multispeed files", and it moves
    **two** (Shockway_Rider and Star_Paws). Flash_Gordon, Mr_Meaner and
    Thundercats are multispeed with `--pitch-seq` on and emit nothing from that
    path at all: every record that reaches it has bit $10 *clear* (28 of them
    across the three), so their bit-$10 records were taken by an earlier branch
    -- this block among them. Count what an option reaches before sizing a
    change to it. Note what the scaling costs to check: no trace in the repo can
    adjudicate it, because
    siddump samples once per frame whatever the call rate, so on Thundercats at
    -S3 the scaled and unscaled blocks emit different bytes and score the
    identical 1308 reversals. The scaling is shipped because it is what the
    player says, not because a column moved.

    Returns None where the block will not fit the record's budget, so the
    caller falls back to the plain two-stage shape rather than emitting a
    truncated arpeggio.
    """
    if attack == 0 or frames <= 0 or not notes:
        return None
    # **The attack frame sounds the pattern's own note.** Entry 0 is applied on
    # the note's first call, and that is the frame `melody` and a listener alike
    # read the note's identity from. The player's phase is global, so whichever
    # step really falls there is unknowable and any step we choose is a guess --
    # but a step of zero is the one guess that cannot *rename* the note, so the
    # cycle is rotated to open on one where it has one (`seq[0]` is the byte
    # nothing writes, so it nearly always does). Measured on Thundercats, whose
    # sequence opens `+3`: without this the reversals come out exact, 1308
    # against the original's 1308, and melody falls 77.3% -> 65.7% on unchanged
    # note counts -- 148 notes named three semitones sharp. The same trap as
    # section 7.qqq's `$40` pitch on frame 0, and it is invisible on
    # Trans-Atlantic, whose rotation already opens on zero and whose bytes this
    # rule leaves untouched.
    #
    # A rotation is the freedom `_pitch_seq_notes` already exercises for the
    # same reason, so this narrows a choice rather than contradicting one; it is
    # applied here only, leaving the eight files that ship the standalone path
    # byte for byte as they are.
    if WAVE_NOTE_BASE in notes:
        turn = notes.index(WAVE_NOTE_BASE)
        notes = notes[turn:] + notes[:turn]
    hold = max(1, multiplier)
    calls = max(1, frames) * hold
    # Same rule as `_two_stage_entries`, and this is the path that reaches the
    # record it was written for: a `+2` selecting no waveform is silence, not
    # the attack released. Trans-Atlantic's `$0AF8` carries `$14`, so with
    # `--pitch-seq` on -- which its preset has -- it comes here.
    second = _wave_byte(wave & 0xFE) if not wave & 0xF0 else wave & 0xFE
    tail = second | (wave & 0x01)
    loop = len(notes) * hold
    # The note's first frame is the record's own waveform (`_first_frame_entry`)
    # and the attack -- with the arpeggio that runs across it -- starts on the
    # second. Trans-Atlantic's GT 4, the one corpus record this path reaches, has
    # `+2 $00` and so takes no such entry; the branch is here because the other
    # files carrying both bits do have a waveform. It is one *frame*, so `hold`
    # calls -- spelled out rather than delayed, because this block spells every
    # other frame out for the same reason (a delay entry's right side is read
    # only on its last call, and the note base has to be current from the first).
    lead = hold if _first_frame_entry(wave, written) else 0
    if lead + calls + loop + 1 > budget:
        return None
    left: List[int] = [wave] * lead
    right: List[int] = [WAVE_NOTE_BASE] * lead
    for c in range(calls + loop):
        left.append(attack if c < calls else tail)
        right.append(notes[(c // hold) % len(notes)])
    # The jump targets the sustain stage, not the block: the attack runs once
    # per note, and so does the first-frame entry before it -- which is why the
    # target carries `lead`. `calls` is an exact multiple of `hold`, so the phase
    # the loop re-enters on is the phase it left; the cycle stays continuous
    # across the jump, as the player's free-running counter does.
    left.append(0xFF)
    right.append(start + lead + calls)
    return left, right


SFX_DRUM_FRAMES = 2          # frames of noise per hit, measured off the trace
WAVE_NOTE_BASE = 0x00        # right side: **writes the pattern's own note**. This is a
#                              `.sng` byte and `gt2reloc` inverts bit 7 of every
#                              non-command right byte on the way in (greloc.c:1340-1341,
#                              `insertbyte(rtable[c][d] ^ 0x80)`), so $00 reaches the
#                              packed player as $80 and takes the `bmi` at
#                              `mt_wavefreq` -- `adc mt_chnnote / and #$7f`. The comment
#                              here used to read "no frequency write (player.s:976-977
#                              `bne`)", which is true of the *packed* byte $00 and so of
#                              the `.sng` byte $80. See v0.5.336 and CLAUDE.md.
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
                      multiplier: int = 1,
                      second_note: Optional[int] = None) -> tuple:
    """Entries for the bit-$80 drum: a noise hit every `period` frames.

    `detect._find_sfx_drum` reads what this plays -- noise at a fixed frequency
    high byte, on a per-voice counter, while an instrument carrying bit $80 is
    held. It is the drum of seven corpus files and was left unwritten while it
    was believed to be the game's own sound effect (§7).

    The shape is a loop, because the player's is: two frames of noise at the
    drum's pitch, the instrument's own waveform and note back again, a delay
    covering the rest of the period, and a jump to the top. That is five
    entries, which is exactly `WAVE_ENTRIES_PER_INSTR`.

The burst is **two** frames in the trace where the counter test (`CMP #$01`)
    implies one, which is still measured rather than derived.

    **The second frame's pitch is effect bit $40, found in v0.5.204.** This
    docstring used to record `$15EB` as "a fixed frequency from somewhere this
    reader has not found", and both frames were written at the drum's own high
    byte for want of anything better. It is the player's note table indexed by
    the instrument's own byte -- `freqtable[52]` on Trans-Atlantic's record 1 --
    and `_fixed_attack_note` derives it. Passed as `second_note`, the two frames
    now carry the two pitches the trace shows:

        +1  noise at the drum's high byte   ($38xx; low byte left as it was)
        +2  noise at freqtable[index]       ($15EB, exactly)

    That profile is identical on all 226 notes of that instrument, so it is the
    shape and not a sample.
    """
    if pitch_hi <= 0 or period <= 0:
        return None
    m = max(1, multiplier)
    # **A record whose +2 selects no waveform is the drum on its own**, and it
    # goes through `_wave_byte` for the reason every other such byte does:
    # `$01`-`$0F` are *delays* in a wavetable, and the `$E0`-`$EF` encoding is
    # what writes them to $D404 as the control bits they are (readme.txt
    # 3.4.1, gplay.c:527). Written literally the entry set no waveform at all
    # -- Bangkok Knights' GT 9 inherited noise from whatever played before and
    # its delay entry applied a relative note, 40 frames at `freqtbl[0]` =
    # $0117 where the drum belongs at $49E5 -- and this function declined the
    # record rather than encode it, which silenced the drum instead.
    #
    # Nineteen is what that cost. Records 0 and 4 share ADSR $0B06 and effect
    # $A0; 0 carries `+2 $41` and is the pulse bass with the drum over it,
    # 4 carries `+2 $01` and is the **drum alone** -- 151 of the original's
    # 267 attacks on voice 3 in 60 s, every one of them named C#6 at the drum's
    # own $482D. Declining record 4 emitted `01/00 01/00 01/00 FF/00`: three
    # one-call delays and a stop, no waveform and no drum. `$E1` writes the
    # $01 the player holds between hits, and because $01 is below $10
    # siddump's keyoff-keyon test fires on the `$81` that follows it, so the
    # ticks are named as notes on our side exactly as they are on the
    # original's.
    held = _wave_byte((wave & 0xFE) | 0x01)
    note = _sfx_note_byte(pitch_hi)
    noise = WAVE_NOISE_GATEOFF | 0x01

    def hold(left: list, right: list, calls: int) -> None:
        """Append entries covering `calls` calls of the instrument's own note.

        One explicit entry is one call; a delay entry is current for `value + 1`
        (gplay.c:697-704), and `$00` is not a delay -- `$01`-`$0F` are -- so a
        remainder of exactly one call is spelled out rather than encoded.
        """
        if calls <= 0:
            return
        left.append(held)
        right.append(0x00)                   # relative 0: the played note
        rest = calls - 1
        if rest == 1:
            left.append(held)
            right.append(0x00)
        elif rest > 1:
            left.append(min(rest - 1, WAVE_MAX_DELAY))
            right.append(WAVE_NOTE_KEEP)

    if second_note is None:
        # **The hit is on the note's second frame, and every `period` after.**
        # Bangkok Knights $8488, and the same block byte for byte in Mega
        # Apocalypse, Star Paws and Thundercats:
        #
        #     848D  LDA $8936 / CMP #$01 / BEQ fire     ; counter == 1 -> hit
        #     8499  CMP #$06 / BCC out                  ; == period -> wrap
        #     84A4  fire: LDA #$48 / STA $D40F / LDA #$81 / STA $D412
        #
        # and the counter is **zeroed at note start** -- `LDA #$00 / STA
        # $8934,X` at $80CE, in the block that clears this voice's other
        # per-note cells -- then `INC $8934,X` once a frame at $84D2. So it is
        # note-locked, the phase is reproducible, and a wavetable can hold it.
        #
        # **This docstring used to say the opposite**, that the counter was
        # "per voice and free-running", and put the noise at the *end* of the
        # cycle for that reason. The measurement it cited is real and was
        # misread: opening on the noise at **frame 0** puts the drum's pitch on
        # the note's own attack frame, where siddump names the note, and
        # Trans-Atlantic's melody duly fell 94.7% -> 50.4%. That is an argument
        # against frame 0, not against frame 1 -- the same collapse
        # `--no-test-restart` produces on Star Paws by the same route. Measured
        # on the original, all four files sound noise at offset 1 on 100% of
        # onsets, and Bangkok's 226 of 232 read `noi` at 1 and 7 -- one frame
        # each, not the two the second-note dialect shows.
        left: List[int] = []
        right: List[int] = []
        hold(left, right, m)                 # frame 0: the record's own note
        loop = len(left)
        left.append(noise)
        right.append(note)
        rest = m - 1                         # ...the hit lasts one frame
        if rest == 1:
            left.append(noise)
            right.append(note)
        elif rest > 1:
            left.append(min(rest - 1, WAVE_MAX_DELAY))
            right.append(WAVE_NOTE_KEEP)
        hold(left, right, (period - 1) * m)
        return left, right, loop

    # With the $40 pitch: a prologue that runs once, then a loop that does not.
    # The burst at offsets +1..+2 carries two pitches, the drum's and $40's; the
    # ticks after it carry one, because $40's counter has run out. Offsets are
    # the trace's, on every note of Trans-Atlantic's instrument 0A99.
    left = [held, noise, noise]
    right = [0x00, note, second_note]
    hold(left, right, (period - SFX_DRUM_FRAMES) * m)
    loop = len(left)
    left.append(noise)
    right.append(note)
    hold(left, right, (period - 1) * m)
    return left, right, loop


# Goattracker's "inaudible waveform" range: $E0-$EF sets the waveform to
# $00-$0F (readme.txt:3.4.1, gplay.c:527). A player waveform below $10 -- gate
# alone, or nothing at all -- cannot be written literally, because $01-$0F are
# *delays*. This is the encoding for it, and the reason a wave program can carry
# `slide $01` at all.
WAVE_SILENT_BASE = 0xE0
# gcommon.h:60. $F0-$FE are Goattracker's wavetable commands and $FF is the
# jump, so no byte from $F0 up can be a waveform.
WAVECMD_BASE = 0xF0
# $D404 bit 3. With it set the oscillator is held in reset and outputs nothing
# whatever the four select bits say -- which is why `FIRSTWAVE_TESTBIT` ($09)
# is a silent frame. `$18` is that bit with triangle selected, and it is the
# **only** way to reach silence from a wavetable in the packed player: see
# `_wave_byte` for why `$E0` is not.
WAVE_TEST_BIT = 0x08
WAVE_SILENT_TESTBIT = 0x18


def _wave_byte(wave: int) -> int:
    """Wavetable left byte that sets the player's waveform `wave`.

    **Two ranges cannot be written literally**, and both go through the
    `$E0`-`$EF` encoding (readme.txt 3.4.1, gplay.c:527), which writes
    `$00`-`$0F` to `$D404` -- control bits, no waveform selected:

    * below `$10`, because `$01`-`$0F` are *delays*. This is what lets a wave
      program carry `slide $01` at all.
    * `$F0` and above, because `WAVECMD` is `$F0` (gcommon.h:60) -- that range
      is Goattracker's commands and `$FF` is the **jump**. Writing such a byte
      literally does not select a waveform, it rewrites the table: Wiz's
      record 1 carries the opcode `set $FF, 250` and emitted `FF/DE`, a jump to
      row 222 of a 112-row table, which `gt2reloc` refuses with exit code 0 and
      no message (§ 7.nnnn). Three corpus files carry opcodes in that range and
      two of them ship with `--wave-program` selected.

    Dropping the four select bits is faithful rather than merely legal. `$FF`
    is all four waveforms *and* the test bit: the test bit holds the oscillator
    in reset and the four select bits AND to silence on a real chip, so what
    the player sounds there is nothing. `$E0 | (wave & $0F)` keeps gate, ring,
    sync and test exactly and drops a nibble that produces no output.

    **Except for `$E0` itself, which the packed player never writes.**
    `gplay.c:527` is the editor; `gt2reloc` re-encodes the range on the way out
    (`greloc.c:1270-1271`): `$E0`-`$EF` becomes its low nibble, and then `+$10`
    is added back **only if the song uses a wavetable delay at all**
    (`nowavedelay`, set from the used rows at `greloc.c:829`). A song without
    one therefore ships `$E0` as a literal `$00`, and the player it is built
    with reads a zero byte as *no wave change* (`player.s:944`, the
    `NOWAVEDELAY != 0` branch) -- so the entry writes nothing and the previous
    waveform keeps sounding. Every other value in the range survives, because
    `$01`-`$0F` are stored as themselves.
    Traced, not reasoned: Skate or Die intro's GT 7 ends its wave program on
    `slide $00`, its packed table carries that entry as `00`, and its trace
    holds the `$80` before it for the rest of the note where the original goes
    silent. Nineteen's `$E1`, in a song that does use delays, comes out as
    `$11` in the packed file and writes the `$01` it means (§ 7.zzzz).
    So a waveform of `$00` is emitted as `$18` instead -- triangle with the
    **test bit**, which the packed player does write and which sounds nothing,
    because the test bit holds the oscillator at zero. `$F0` takes the same
    route for the same reason.
    """
    if 0x10 <= wave < WAVECMD_BASE:
        return wave
    if not wave & 0x0F:
        return WAVE_SILENT_TESTBIT
    return WAVE_SILENT_BASE | (wave & 0x0F)


def _speed_index(speed_table: List[tuple], entry: tuple) -> int:
    """1-based speed-table index for `entry`, appending it, or 0 if full."""
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _hold_wave_program_entry(left: List[int], right: List[int],
                             wave: int, multiplier: int) -> None:
    """Extend the entry just appended to cover a whole frame at `-S{m}`.

    One opcode of the byte-code program is one of the player's frames, and a
    frame is `multiplier` play calls. `_wave_hold_byte` is the shared encoding
    of that -- a repeat of the waveform at `-S2`, where no delay value exists
    for a single extra call, and a delay of `m - 2` above it.

    **Right side `$80`, and `$00` was the defect this fixed.** `gt2reloc`
    inverts bit 7 of every non-command wavetable right byte on the way in --
    `insertbyte(rtable[c][d] ^ 0x80)`, greloc.c:1339-1341 -- so the packed
    player's `lda mt_notetbl-2,y / bne mt_wavefreq` (player.s:974-977) is
    testing the *inverted* byte. A `.sng` `$80` becomes packed `$00` and makes
    no frequency write at all; a `.sng` `$00` becomes packed `$80`, takes the
    `bmi` path at `mt_wavefreq` and writes `adc mt_chnnote,x / and #$7f` --
    the note's own pitch, every hold call.

    That is what made the `program` bucket of `VIBRATO.md` read zero. At `-S2`
    an opcode is entry + hold, so the opcode's absolute pitch was written on
    the frame's first call and overwritten by the base note on its second;
    siddump samples the register once a frame and saw a flat pitch. Ricochet's
    `$09F9` measured 184 reversals in the original and 0 here, with the
    waveforms `11 81 41 41 80 80 80` landing exactly right beside them.

    See `_wave_program_entries` for the same byte on the opcode entries.
    """
    hold = _wave_hold_byte(multiplier, _wave_byte(wave))
    if hold is not None:
        left.append(hold)
        right.append(WAVE_NOTE_KEEP)


def _wave_program_travels(multiplier: int, fmt: str, running: int) -> bool:
    """Whether a slide's accumulated travel can be carried at this call rate.

    A `< $80` opcode is one of the player's *frames*, and a frame is
    `multiplier` play calls. Above `-S1` the opcode's waveform entry does not
    need all of them, so the spare call can hold a `CMD_PORTADOWN` and the
    travel reaches the chip inside the same frame the player spends on it. At
    `-S1` there is no spare call and a second entry would make the program run
    at half the player's rate -- the trade v0.5.203 measured and refused, and
    the reason this is gated rather than unconditional.
    """
    return fmt == FORMAT_GTS5 and multiplier >= 2 and bool(running & 0xFFFF)


def _wave_program_travel_entry(left: List[int], right: List[int],
                               running: int, speed_table: List[tuple],
                               fmt: str, multiplier: int) -> bool:
    """Append the portamento carrying `running`, the slides' summed operands.

    The player subtracts each `< $80` opcode's 16-bit operand from a frequency
    **accumulator** that note-start loaded with the note's own frequency, so
    after k slides the voice sounds `note - sum(operands)`. The waveform entry
    beside this one writes the note (`WAVE_NOTE_BASE`); this entry takes it the
    rest of the way.

    **The sum, not the step.** Written per opcode as the running total rather
    than as that opcode's own delta so the entry is correct without depending
    on what the previous entries left in `cptr->freq` -- a `>= $80` opcode
    between two slides writes `$D401` directly and never touches the
    accumulator, so a delta chain would drift by exactly that opcode's absolute
    pitch. Each entry re-derives the whole offset from the note.

    One entry is one subtraction: `gplay.c:557-573` and `player.s:1531-1547`
    both execute the command, advance the pointer and skip the note write on
    the same call -- the packed player routes it through `mt_execwavetickn`,
    which sets `mt_effectjump+1` and falls into `mt_effect_12` *without*
    writing `mt_chnfx,x`, so it is a one-shot and not a standing effect. Same
    shape as the drum sweep's `[WAVECMD_PORTADOWN] * steps` chain.

    A sum at or above `$8000` is a net *rise* (the player's subtraction is
    modular 16-bit) and takes `CMD_PORTAUP` with the two's complement, which
    also keeps the speed's high byte below `$80` -- at or above it the players
    read the entry as note-relative and take the low byte as a shift
    (`gplay.c:548-552`, `player.s:1027`), which is a different quantity
    entirely.
    """
    if not _wave_program_travels(multiplier, fmt, running):
        return False
    s = running & 0xFFFF
    if s < 0x8000:
        cmd, speed = WAVECMD_PORTADOWN, s
    else:
        cmd, speed = WAVECMD_PORTAUP, 0x10000 - s
    if not 0 < speed < 0x8000:
        return False
    index = _speed_index(speed_table, ((speed >> 8) & 0xFF, speed & 0xFF))
    if not index:
        return False
    left.append(cmd)
    right.append(index)
    return True


def _wave_program_entries(sid: SidFile, det: Detection, i: int,
                          speed_table: List[tuple], fmt: str,
                          multiplier: int, budget: int,
                          written: bool = False) -> Optional[tuple]:
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
    * `< $80` with a nonzero operand is two **above `-S1`**: the waveform on
      the note's own pitch, then a portamento carrying the running sum of the
      operands (`_wave_program_travel_entry`). The pair still costs one frame,
      because a frame is `multiplier` calls and the waveform entry does not
      need them all. At `-S1` there is no spare call and the travel is dropped,
      which is what v0.5.203 measured and chose.
    * `$85` holds, which is the program's end. The interpreter does **not**
      loop back: on `$85` it jumps straight to the per-frame writer without
      advancing the program index, and the index is zeroed only by note start
      (ACE II `$E36C-$E370` against `$E0F7 STA $EBC7,X` on the note-fetch
      path). So the block stops there, restoring the stored waveform on the
      accumulator's pitch, as the player does.

    **One opcode is one frame, and one frame is `multiplier` play calls.** The
    player advances one opcode per frame; a wavetable advances one entry per
    *call*, so each opcode gets a hold entry after it (`_wave_hold_byte`, the
    same rule as `_first_frame_lead`) and the program runs at the player's
    rate at every `-S`. Until v0.5.234 the function simply refused a multiplier
    above 1, which is what kept the largest group of the onset census
    unrendered: 7 of the 9 files whose `$01` records the original opens on
    noise and we held flat -- Kings of the Beach, Ricochet, Saboteur II,
    Shockway Rider, Star Paws, Thundercats -- carry a wave program and pack at
    `-S2`, `-S3` or `-S5`, so the option was selectable, measured, and inert.

    The cost is a table roughly twice as long. Nothing starves for it: the
    caller's budget already reserves five entries for every later record and
    this loop already stops on it, so an over-long program loses its trailing
    opcodes rather than another instrument's block.

    **The hold entry's right side is `$80`, not `$00`.** It was `$00` from
    v0.5.234, on a reading of `player.s:974-977` that had not accounted for
    `greloc.c:1339-1341` inverting bit 7 of the right column as it packs. The
    two bytes mean the opposite of what that reading said: `$80` makes no
    frequency write, `$00` re-asserts the pattern's own note, and the hold was
    therefore undoing the absolute pitch of every `>= $80` opcode one call
    after it was set. See `_hold_wave_program_entry`.
    """
    if fmt != FORMAT_GTS5:
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

    # **The note's first frame is the record's own waveform**, and the program
    # runs from the second (`_first_frame_entry`): Trans-Atlantic's GT 3 opens
    # `tri` -- its `+2`, `$11` -- and only then the program's `$81` noise. Opened
    # on the program, every frame it emits ran one early and that first frame was
    # lost. Counted in the budget below like any other entry, so a record too
    # long for the table loses a trailing opcode rather than this.
    # `_first_frame_lead` rather than a lead written out here: the rule has two
    # halves and this function only ever had the first. Its one-entry seed was
    # one *call* where frame 0 is `multiplier` of them -- the same defect
    # v0.5.220 fixed in `_drum_entries` and v0.5.226 in the plain tick block,
    # latent here only because the multiplier gate above made it unreachable.
    lead_l, lead_r = _first_frame_lead(data[rec + 2], multiplier,
                                       written=written)
    left: List[int] = list(lead_l)
    right: List[int] = list(lead_r)
    seed = len(left)
    # **The two opcode kinds write different cells, and the hold reverts to the
    # one the `< $80` opcodes own.** IK+ `$E348`: a `>= $80` opcode stores to
    # `$E5E7,X` -- the cell the per-frame writer copies to `$D404` -- while a
    # `< $80` opcode stores to `$E58F,X`, the voice's *stored* waveform. On
    # `$85` the interpreter jumps to `$E44C`, which is
    # `LDA $E58F,X / AND gate,X / STA $E5E7,X`: the voice goes back to the last
    # `< $80` opcode's waveform, not to the record's `+2`. Its `$08D8` is the
    # proof -- program `81 11 40 80 80 80 80 80`, and the original reads
    # `11 81 11 40 80 80 80 80 80 40 40 40`, three frames of the `$40` that
    # opcode 2 stored, where we wrote the record's `$11` released.
    # Seeded with `+2` because that is what the note-start code puts in the
    # cell, so a program of nothing but `>= $80` opcodes restores what it
    # always did.
    persist = data[rec + 2]
    # What one opcode costs: its own entry, plus the hold that makes it last a
    # whole frame above -S1. The guard below has to count both, or a program
    # that fills the table overruns the budget by one entry and takes it from
    # the five every later record is reserved -- the one property that makes
    # the variable-length layout safe (`_wavetable_layout`).
    per_opcode = 1 + (_wave_hold_byte(multiplier) is not None)
    # The slides' running total, in the units the player's accumulator counts
    # in. Zero for a program of nothing but `>= $80` opcodes, which is what
    # makes those records byte-identical to before the travel was emitted.
    running = 0
    # Whether the frequency Goattracker is holding right now IS that
    # accumulator. False after a `>= $80` opcode, which writes an absolute
    # pitch over it, and false at `-S1`, where no portamento is emitted at all
    # and the entries stay exactly the bytes they were before the travel
    # existed. See the slide branch: it decides between re-anchoring on the
    # note and stepping on from where the last one left off.
    carried = False
    # What the block after the loop needs: the restore entry, the stop, and --
    # wherever the call rate lets a slide's travel be emitted at all -- the
    # portamento that puts the restore on the accumulator's pitch. Reserved
    # whatever this opcode does, because the closing travel is decided by the
    # sum of *every* slide and a `set` can be the last opcode a full budget
    # admits.
    tail = 2 + (1 if _wave_program_travels(multiplier, fmt, 1) else 0)
    for kind, wave, arg in decode_wave_program(data, at):
        if kind == "hold":
            break
        if kind == "set":
            if len(left) + per_opcode + tail > budget:
                break
            left.append(_wave_byte(wave))
            right.append(_sfx_note_byte(arg))
            _hold_wave_program_entry(left, right, wave, multiplier)
            carried = False     # an absolute pitch, not the accumulator
            continue
        # **One entry, even when the operand is non-zero** (v0.5.203). A
        # portamento needs a command entry of its own, and a wavetable spends a
        # call on it, so a two-entry slide makes the program one frame longer
        # than the player's -- which runs the whole thing late and truncates
        # what follows. On Trans-Atlantic's snare the two slides cost 2 of 11
        # frames and cut the closing noise burst from 8 frames to 6. The
        # frame count is what the ear hears in a percussion transient; two
        # frames of pitch movement under a released waveform is not, so the
        # waveform keeps its frame and the movement is dropped.
        #
        # **But the frame it lands on is the note's own pitch, not the last
        # `set` opcode's.** The two opcode kinds do not write the same cells,
        # and this one does not go through `$D401` at all. Saboteur II $F36B,
        # Shockway Rider $F05A -- the same routine byte for byte:
        #
        #     F36B  9D 5D F5   STA $F55D,X   ; waveform -> the STORED cell
        #     F36F  38 BD 8F F5 F1 F8 9D 8F F5    ; freq LO acc -= operand
        #     F379  BD 7B F5 F1 F8 9D 7B F5       ; freq HI acc -= borrow
        #     F386  4C 5F F4   JMP $F45F
        #     ...
        #     F45F  AC 50 F5   LDY $F550
        #     F462  BD 5D F5 3D 66 F5 99 04 D4    ; stored waveform & gate
        #     F46B  BD 7B F5 99 01 D4             ; the ACCUMULATOR -> $D401
        #     F471  BD 8F F5 99 00 D4             ; ...and $D400
        #
        # The accumulator is loaded with the note's frequency at note start and
        # a `>= $80` opcode never touches it -- that one writes `$D401`
        # directly and exits by another path ($F477). So the first `< $80`
        # opcode of a program **abandons the absolute pitch and returns to the
        # note**, minus the running sum of the operands, and every later one
        # continues from there. Exact on both files and on four different base
        # notes: Saboteur's $1739 - $0180 = $15B9 and $49B8 - $0180 = $4838,
        # Shockway's $1168 - $01C0 = $0FA8 and $14AF - $01C0 = $12EF.
        #
        # `WAVE_NOTE_KEEP` here held whatever the last `set` put in `$D401`,
        # which is an absolute pitch with nothing to do with the note -- on
        # Saboteur's $0888 it froze the program at $20DC where the original
        # descends from $15B9, and on a *high* note it was an octave and a half
        # below where the player goes. `WAVE_NOTE_BASE` says "back to the
        # note", which is exact whenever the running sum is zero and the right
        # side of the truth otherwise. The sum itself is still dropped: it is a
        # linear frequency subtraction and a wavetable's right column names
        # notes, so its size in semitones depends on the note it is played at
        # (Saboteur's first slide is -1.16 st under $1739 and -0.36 st under
        # $49B8) and no single byte can carry both.
        #
        # **The travel itself is carried where there is a call to carry it in**
        # -- `_wave_program_travel_entry`, a `CMD_PORTADOWN` on the spare call
        # of the frame at `-S2` and above. The paragraph above is what remains
        # true at `-S1`, where the opcode's one call is already spent on its
        # waveform. So `WAVE_NOTE_BASE` is no longer the whole answer, it is
        # the entry the portamento starts from, and the sum is dropped only
        # where the call rate leaves nowhere to put it.
        #
        # **The step, not the sum, wherever the last entry left the frequency
        # on the accumulator.** Both are exact in the player's terms and they
        # differ in *when inside the frame* the pitch is right. Re-anchoring
        # (`WAVE_NOTE_BASE` + a portamento of the whole running sum) writes the
        # bare note on the frame's first call and corrects it on the second, so
        # a trace sampling once a frame can read the note -- ACE II's `$EB0A`
        # sat at `0EA3` for the whole slide that way while the calls underneath
        # it stepped correctly. `WAVE_NOTE_KEEP` plus this opcode's own operand
        # never writes the note at all, so the frequency only ever moves the
        # way the player moves it. The anchor is still needed for the first
        # slide of a program and for the one after any `>= $80` opcode, because
        # those leave an absolute pitch in the register that has nothing to do
        # with the accumulator.
        delta = arg & 0xFFFF if carried else (running + arg) & 0xFFFF
        travel = int(_wave_program_travels(multiplier, fmt, delta))
        cost = 1 + travel + (_wave_hold_byte(multiplier - travel) is not None)
        if len(left) + cost + tail > budget:
            break
        left.append(_wave_byte(wave))
        right.append(WAVE_NOTE_KEEP if carried else WAVE_NOTE_BASE)
        # `moved` rather than `travel`: a full speed table refuses the index,
        # and the hold has to cover the call the portamento did not take.
        moved = int(_wave_program_travel_entry(left, right, delta, speed_table,
                                               fmt, multiplier))
        _hold_wave_program_entry(left, right, wave, multiplier - moved)
        running = (running + arg) & 0xFFFF
        # The frequency now matches the accumulator only if this entry actually
        # said so: a step it could not encode (a full speed table) leaves it a
        # step behind, and the next slide re-anchors instead of compounding the
        # error. `delta == 0` needs no portamento to be right either way.
        carried = bool(travel and moved) or (not delta and bool(
            _wave_program_travels(multiplier, fmt, 1)))
        persist = wave              # a `< $80` opcode owns the stored cell
    # `seed` alone is not a program: a record whose interpreter holds on its
    # first opcode has nothing to say here and falls through to the shapes
    # below, exactly as it did before the seed entry existed.
    if len(left) <= seed:
        return None
    # **Restore the record's own waveform before stopping** (v0.5.203). The
    # docstring above used to say Goattracker keeps the last waveform "as the
    # player does"; the player does not. Its note-end routine writes the
    # *stored* waveform with the gate cleared -- `LDA $54F8,X / AND #$FE /
    # STA $D404,Y`, the same routine as the envelope cut (detect
    # .ENVELOPE_CUT_SHAPES) -- so a program that ends on noise stops sounding
    # noise when the note ends. Holding it instead let the noise run into the
    # gap: Trans-Atlantic's snare had runs of 30, 54 and 78 frames where the
    # original's are 8.
    #
    # **What is restored is the stored cell, not the record's `+2`** -- see
    # `persist` above. Where the program's last `< $80` opcode selects no
    # waveform (Skate or Die intro and Arcade Classics both end on `slide
    # $00`) that restore is silence, which is what the original sounds for the
    # rest of the note; `_wave_byte` is what makes it reach the packed player.
    #
    # **And the hold writes a pitch too** -- `WAVE_NOTE_KEEP` here was the same
    # defect v0.5.341 fixed one loop above, left in the one emitter that is not
    # in the loop. `$85` does not stop the interpreter, it *jumps* to the
    # per-frame writer ($F45F on Saboteur II / Shockway Rider -- the listing
    # above), and that path ends `LDA $F57B,X / STA $D401,Y` and
    # `LDA $F58F,X / STA $D400,Y`: the frequency **accumulator**, which is the
    # note's own frequency minus the running sum of the `slide` operands. It
    # is **not** whatever the last `set` opcode put in
    # `$D401` -- that one writes the register directly and exits by another
    # path, so its absolute pitch has nothing to do with where the hold sits.
    # Traced on Nineteen's `$0797` (record 6, program `set $81 $30 / slide $11
    # $0400 / slide $40 $0E40 / set $80 $30 $15 $20 $10 $20 / hold`): over a
    # 19-frame note the original reads
    # `17A1 0961 3061 1561 2061 1061 2061 0961 0961 ...` -- base note `$1BA1`,
    # then the two slides, then the five absolute pitches, then **back to
    # `$0961` = `$1BA1 - $0400 - $0E40`** for the whole tail. Ours held `20DC`,
    # the last `set`'s pitch, an octave and a half above it.
    # `WAVE_NOTE_BASE` is exact whenever the running sum is zero (a program of
    # nothing but `set` opcodes, which is most of them) and the right side of
    # the truth otherwise -- the identical argument the slide entries carry.
    # The sum is carried here by the same portamento the slide entries take
    # (`_wave_program_travel_entry`), and dropped at `-S1` for the same reason
    # it is dropped there. It is the *whole* running sum, because the hold
    # writes where the accumulator ended up and not where the last slide moved
    # it -- the entry re-derives the offset from the note, so a `>= $80` opcode
    # after the last slide changes nothing about it. Nothing follows the stop,
    # so the pitch this leaves stands for the rest of the note, which is what
    # the interpreter's `$85` does.
    left.append(_wave_byte(persist & ~WAVE_GATE_BIT & 0xFF))
    right.append(WAVE_NOTE_KEEP if carried else WAVE_NOTE_BASE)
    if not carried:
        _wave_program_travel_entry(left, right, running, speed_table,
                                   fmt, multiplier)
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
# The same gate with an *immediate* reload -- `BPL +5` rather than `+6`,
# because `LDA #imm` is two bytes where `LDA abs` is three:
#
#     C83D  DEC $CC46 / BPL +5 / LDA #$02 / STA $CC46      (Ninja)
#     C84E  LDA $CC46 / CMP #$02 / BNE skip    ; work on the reload frame
#
# 35 corpus files carry this shape and 33 of them already read a gate through
# the absolute spelling, so it is consulted **only where that one found
# nothing** -- the rule `find_relocation` and `INSTRUMENT_INDEX_SHAPE` follow.
# What the other 33 count is not established, and a wrong tempo is worse than
# the old constant.
SPEED_GATE_IMM = re.compile(rb"\xce(..)\x10\x05\xa9(.)\x8d(..)", re.DOTALL)
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
# **And it has a second spelling, unread until v0.5.248.** At the PSID *play*
# address the same counter ends in `RTS` -- "on the underflow call, do nothing
# at all" -- rather than jumping past the gate, and its branch is `BPL +6`
# instead of `+8` because it steps over one byte and not three:
#
#     1012  DEC $15AE / BPL $101D / LDA #$07 / STA $15AE / RTS   (Warhawk)
#
# Nine corpus files open their play routine this way -- Warhawk, Proteus,
# International Karate, Bump Set Spike, Game Killer, Thrust, Mozart, Ninja
# and Formula 1 Simulator -- and **none of them carries the `JMP` form as
# well**, so there is no question of which one applies. `SPEED_GATE`'s own
# comment names this idiom, but as the prescaler variant of three files,
# excluded because "no steady Goattracker tempo can express it": it also
# sits above a normal gate here, where it multiplies rather than replaces,
# and `_skip_gate_multiplier` is what expresses such a row when the
# denominator is small enough.
OUTER_GATE_RTS = re.compile(rb"\xce(..)\x10\x06\xa9(.)\x8d(..)\x60", re.DOTALL)

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


def _gate_hits(sid: SidFile):
    """(match offset, reload address) for every speed-gate shape in the file.

    The immediate-reload spelling is a *fallback*: it is consulted only where
    the absolute one matched nothing, because 33 of the 35 corpus files
    carrying it also carry the absolute form, and reading both would hand two
    candidates to a chooser with no way to tell them apart. It rescues Ninja
    and Mega Apocalypse, whose players have only this one.

    For that spelling the "reload address" is the address of the *immediate's
    own operand byte*, which is what makes `_speeds_for_reload` work
    unchanged: a per-subtune table is written into that operand by the init
    (`LDA table,X / STA <the immediate>`, the self-modifying idiom
    `_find_outer_gate` reads for the same reason), and where no init writes it
    the byte sitting there is the value.
    """
    data = sid.data
    hits = []
    for m in SPEED_GATE.finditer(data):
        ctr, rel, ctr2 = m.group(1), m.group(2), m.group(3)
        if ctr != ctr2:
            continue
        hits.append((m.start(), rel[0] | rel[1] << 8))
    if hits:
        return hits
    base = sid.load_addr - sid.to_offset(sid.load_addr)
    for m in SPEED_GATE_IMM.finditer(data):
        if m.group(1) != m.group(3):
            continue
        hits.append((m.start(), m.start() + 6 + base))
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


# Any `LDA table,X` -- used only to find *other* per-subtune tables read the
# same way, near the one `_find_outer_gate` has already found.
_ABS_X_LOAD = re.compile(rb"\xbd(..)", re.DOTALL)

# How far either side of a found `LDA table,X` to look for a second one, when
# bounding that table's real length (see `_adjacent_table_bound`). Generous
# enough to span the handful of instructions between two loads in the same
# init loop (Knucklebusters and W_A_R's are 6 bytes apart); the corpus has
# no closer false match at this width or twice it (checked at 32/64/128).
_ADJACENT_TABLE_WINDOW = 32


def _adjacent_table_bound(sid: SidFile, bd_pos: int,
                          table_addr: int) -> Optional[int]:
    """Distance to the nearest *other* per-subtune table read the same way.

    `_speeds_for_reload`'s table can be over-read when a file's header
    over-counts its subtunes, and it guards against that with
    MAX_SANE_SPEED_RELOAD -- a magnitude bound that works because the bytes
    past a frames table's real end are usually code. That bound is wrong for
    the outer gate's own values: 16 corpus files carry a genuine skip
    reload above it (Ricochet's 127 is `outer_gate_skip`'s own worked
    example of "almost no skip, and correct for a reason"), so nulling
    anything over MAX_SANE_SPEED_RELOAD here would falsely null real data on
    16 files to fix one.

    What actually bounds Knucklebusters' table is structural, not a value:
    its init reads three 8-byte per-subtune tables back to back (`LDA
    $0978,X`, `LDA $0968,X`, `LDA $0970,X`), so $0970's table is exactly 8
    bytes before $0978's begins -- and a header that claims 11 subtunes
    reads 3 bytes into the next table, at values ($02) too small for any
    magnitude guard to catch. W_A_R (also a Warhawk-engine file) carries the
    identical shape at $E90F/$E917. Searching nearby code for another `LDA
    table,X` whose address sits just past this one's finds that boundary
    directly, for both.
    """
    lo = max(0, bd_pos - _ADJACENT_TABLE_WINDOW)
    hi = min(len(sid.data), bd_pos + _ADJACENT_TABLE_WINDOW)
    best = None
    for m in _ABS_X_LOAD.finditer(sid.data, lo, hi):
        addr = m.group(1)[0] | (m.group(1)[1] << 8)
        if addr <= table_addr:
            continue
        gap = addr - table_addr
        if best is None or gap < best:
            best = gap
    return best


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
    m = OUTER_GATE.search(sid.data) or OUTER_GATE_RTS.search(sid.data)
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
                n = max(subtunes, 1)
                bound = _adjacent_table_bound(sid, i - 3, table)
                if bound is not None and bound < n:
                    n = bound
                vals = sid.data[off:off + n]
                return tuple(v or None for v in vals), table
        i = sid.data.find(store, i + 1)
    return (sid.data[imm_off] or None,) * max(subtunes, 1), None


def outer_gate_skip(sid: SidFile, subtune: int = 0) -> Optional[int]:
    """The reload of the counter above the player's gate, or None.

    `find_song_speeds` already carries this as `SongSpeeds.skip`, but only for
    a player whose *inner* speed gate it also found -- and the two are
    independent readings. Anything that needs the counter alone should ask
    here rather than through a `SongSpeeds` that may be None for a reason
    having nothing to do with the counter.

    **The file this was written for no longer needs it.** Ninja had the outer
    counter and no readable inner gate until v0.5.267 read its immediate
    reload spelling (`SPEED_GATE_IMM`), and `find_song_speeds` answers for it
    now. The separation still holds -- a player can have either counter
    without the other -- so this stays, with its justification re-stated
    rather than its example.
    """
    vals, _ = _find_outer_gate(sid, max(sid.subtunes, 1))
    if 0 <= subtune < len(vals):
        return vals[subtune]
    return None


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
    for pos, rel_addr in _gate_hits(sid):
        speeds = _speeds_for_reload(sid, rel_addr)
        if speeds is not None:
            candidates.append((pos, speeds))
    if not candidates:
        # **No inner gate is a reading, not a refusal -- if there is an outer
        # one.** The two counters are independent (`outer_gate_skip` says so
        # in as many words), and a player with only the outer one advances its
        # pattern exactly once per working call: the row *is* one tick, and
        # the skip is the whole of the timing.
        #
        # Mozart is the one corpus file shaped that way, and returning None
        # for it cost a factor of two. Its play entry point at $0829 is the
        # gate itself, in the inverted spelling `OUTER_GATE_RTS` matches:
        #
        #     0829  DEC $0C33
        #     082C  BPL $0834        ; >= 0 -> do the update
        #     082E  LDA #$02 / STA $0C33
        #     0833  RTS              ; underflow -> reload and skip this call
        #
        # Two updates every three calls, so a tick is 1.5 frames. Its waits
        # are 3 and 7, giving 4 and 8 updates, and the original's note gaps
        # are 6 and 12 frames exactly. With no speeds the tempo fell back to
        # the constant 3 at `-S1` -- 3 frames a row against the player's 1.5,
        # which `drift` reported as **+1000.0 per 1000 with a scatter of
        # 0.0**, a conversion running at precisely half speed. As `frames=1`
        # with `skip=2` the row is 3/2 frames, which packs exactly as tempo 3
        # at `-S2`.
        #
        # Scoped by construction to a file that has an outer gate and no inner
        # one: 10 corpus files lack the inner gate and 9 of them lack both, so
        # they are untouched and keep the fallback constant.
        skip, skip_table = _find_outer_gate(sid, max(sid.subtunes, 1))
        if skip and skip[0]:
            n = max(sid.subtunes, 1)
            return SongSpeeds((1,) * n, -1, None,
                              skip=skip, skip_table_addr=skip_table)
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
#
# v0.5.313 raised it 6 -> 10, and the reason is not the size of q but **how
# badly the row rounds without it**. This comment used to say the rows beyond
# six "are within ~1.3% of a whole number anyway, so they round", which is
# true of most of them and false of exactly the three shapes a cap of 10
# reaches:
#
#     16/7   = 2.286  ->  2   12.5% out   Warhawk, Proteus
#     20/9   = 2.222  ->  2   10.0%       Game Killer
#     33/10  = 3.300  ->  3    9.1%       Delta Mix-E-Load, IK, Kentilla
#     -------------------------------------------------------------------
#     81/20  = 4.050  ->  4    1.2%       After 8, Rikky
#     113/28 = 4.036  ->  4    0.9%       Pandora
#     109/36 = 3.028  ->  3    0.9%       Sanxion, Sigma Seven
#     339/112= 3.027  ->  3    0.9%       IK+, I Ball, Nineteen, ...
#     384/127= 3.024  ->  3    0.8%       BMX Kidz, Wiz, Skate or Die, ...
#
# A 7.5x gap between the worst rounder and the best non-rounder, with nothing
# in between -- so the cap is a property of the corpus rather than a number to
# tune. Ten calls a frame is about three quarters of a PAL frame's 19656
# cycles, which is heavy; 127 would be 6350 Hz, which is not a call rate at
# all. The six files it reaches all gain: `drift` -> 0.00 on every one, `wave`
# +16.1pp mean, `gate` +30pp, and `retrig` toward 1.00. See section 8.
MAX_ROW_DENOMINATOR = 10


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


def orderlist_tempo_values(sid: SidFile, det: Detection,
                           reloads: List[dict],
                           tempo: int | str | None = None,
                           skip_gate: bool = False) -> List[dict]:
    """Each orderlist tempo command's operand, as a CMD_SETTEMPO value.

    One map per track, keyed by orderlist position, exactly as
    `tracks.convert_tracks` filled them. The track index says which subtune a
    map belongs to (three tracks each, in order), because the operand is only
    half of the answer -- the other half is that subtune's own row length.

    **The operand is the OUTER counter's reload, not a row length.** Rasputin
    `$C012` is

        DEC $C53A / BPL work / LDA $C539 / STA $C53A / JMP exit

    -- the shape § 7.rrrr calls the outer gate, spelled with a *cell* reload
    where `OUTER_GATE` expects an immediate, which is why `find_song_speeds`
    reports no `skip` for this file. It works on `R` calls in every `R + 1`,
    so a row of `frames` working calls lasts `frames * (R + 1) / R` real
    frames: exactly `SongSpeeds.exact_row`'s factor, with `R` changing
    mid-song. The inner gate, and so `frames`, is `$C062` and does not move.

    Read as a row length instead, Rasputin's `$FE 78` would be 121 frames a
    row against its neighbours' 3 -- ten seconds on a pattern the same list
    plays at speed twenty entries earlier. That implausibility is what sent
    this back to the disassembler; the ratio form gives 2.017 frames against
    2.033, which is the accelerando it sounds like.

    Rounded, because the product rarely lands on a whole number of calls and
    Goattracker has no fractional tempo: 2.667 frames at `-S2` is 5.33 calls
    and is written as 5. The alternative to a rounded change is the *absent*
    one, which is what this file had -- every row 4 calls where the truth
    ranges from 4.03 to 6.
    """
    speeds = find_song_speeds(sid, det)
    mult = 1
    if tempo == "auto" and det.frames_per_row <= 1:
        mult = recommended_multiplier(speeds, 0, skip_gate)
    out: List[dict] = []
    for ti, m in enumerate(reloads):
        # `frames_for`, not `effective_frames`: the outer counter's factor is
        # what the operand *is*, so taking a correction for it out of the file
        # image as well would apply it twice.
        base = None if speeds is None else speeds.frames_for(ti // 3)
        if base is None:
            base = TEMPO_FASTEST_STEADY
        out.append({at: min(max(int(round(base * (r + 1) / r * mult)),
                                TEMPO_FASTEST_STEADY), 0x7F)
                    for at, r in m.items() if r})
    return out


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
                       no_test_restart: bool = False,
                       cut_release: bool = False,
                       multiplier: int = 1,
                       row_calls: int = 0,
                       wide_hard_restart: bool = False,
                       max_hard_restart: bool = False,
                       real_firstwave_instruments: tuple = ()) -> int:
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
        if (cut_release and det.envelope_cut
                and not data[base + 7] & EFFECT_PER_FRAME):
            # This player ends an untied note by writing 0 to both envelope
            # registers (detect.ENVELOPE_CUT_SHAPES), so the note stops dead
            # and the release nibble in the record is never heard. Copying it
            # into a Goattracker instrument makes it audible, and Goattracker
            # gates off on the same frame the player does -- so the note rings
            # through a gap that should be silence. Measured on Commando, the
            # original's release is 0 on all 7 instruments at every note end
            # while ours carries B, A, F, 9, B, 4 and F.
            #
            # The sustain is left alone: it governs the note while it plays,
            # which is not what the cut destroys.
            #
            # **Per instrument, not per file** (v0.5.201). An instrument
            # whose effect routine runs every frame re-writes the envelope
            # after the cut, so its release survives and is heard. On
            # Commando only records 0, 2, 6 and 8 are cut; the ones
            # carrying the drum bit hold their value across the whole gap,
            # and zeroing their release destroyed the drums -- reported by
            # a listener, and visible in the trace all along. See
            # EFFECT_PER_FRAME.
            sr &= 0xF0
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
        gatetimer = ((0x80 if no_hard_restart else 0)
                     | (_hard_restart_ticks(multiplier, row_calls,
                                            wide_hard_restart,
                                            max_hard_restart) & 0x3F))
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
        #
        # `--no-test-restart` makes this decision for every instrument in the
        # file at once, and that is too blunt: on ACE_II it recovers the drum
        # (voice 2, instrument 1 alone) from melody 100% -> 37% back to 99.6%,
        # but the SAME flag also breaks voice 1 (100% -> 14%, a different
        # mechanism entirely -- see the wavetable-entries `written=` plumbing,
        # not this byte). `real_firstwave_instruments` isolates just the
        # firstwave half of the trade, by GT instrument NUMBER (1-based,
        # matching what a pattern row's instrument column and songview.py
        # both show -- `gt_number = i + lead + 1`), so a per-song preset entry
        # can name the one instrument that needs it without forcing every
        # other instrument in the file through the same byte. Isolated and
        # measured on ACE_II (v0.5.357+): reverting only this byte for the
        # rest of the file, while instrument 1 keeps the real-waveform byte,
        # holds voice 0 and voice 2 at their un-flagged fidelity while voice 2
        # gains the fix -- confirming the corruption lives in this byte alone
        # for that instrument, not in `no_test_restart`'s other effects.
        gt_number = i + lead + 1
        use_real_firstwave = no_test_restart or gt_number in real_firstwave_instruments
        out += bytes([ad, sr, wave_ptr, pulse_ptr, filt_ptr, stbl_ptr,
                      vib_delay, gatetimer,
                      ((data[base + 2] | 0x01) & 0xFF) if use_real_firstwave
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


def _classic_vibrato_entry(byte: int, multiplier: int,
                           row_calls: int = 0) -> Optional[tuple]:
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

    * **The packed player does not run the vibrato on tick 0 of a row.**
      `player.s:982-987` is `REALTIMEOPTIMIZATION`, default-on in `gt2reloc`
      (`-R0` turns it off): `lda mt_chncounter,x / beq mt_done`, commented "No
      continuous effects on tick0", and `mt_chnvibtime` is only touched below
      that branch. So a row of `row_calls` calls advances the counter on
      `row_calls - 1` of them and a half-period encoded at face value lasts
      `row_calls / (row_calls - 1)` calls of real time. This is the *same*
      dropped call `patterns._scaled_step` already compensates for the
      portamento, in the other direction -- there the step is scaled **up**,
      here the comparison threshold is scaled **down**:

          cmp = bound * multiplier * (row_calls - 1) / row_calls - BIAS

      Powerplay Hockey is the file that made this measurable: it is the first
      corpus file whose classic-vibrato instruments emit *anything* (its
      instrument table was wrong until § 7.iiiii), and all three read
      0.648/0.669/0.656 of the original's reversal count against a predicted
      `(3 - 1) / 3 = 0.667` at its `row_calls` of 3. **Confirmed by turning
      the proposed cause off rather than by argument**, which is the check
      § 7.ppppp exists to demand: packing the same `.sng` with `-R0` takes the
      file's `vib` **0.658 -> 1.015** with `melody` unmoved at 0.993, and over
      all 55 files carrying this engine it takes mean `|log2(vib)|`
      **0.476 -> 0.411**. Compensating here instead reaches 0.428 -- the
      emitter reproduces removing the cause, on the rate axis, to within 0.017.

      `-R0` is not itself the fix, and this run reproduces why: it takes the
      median slide ratio **0.994 -> 1.118** over the same 55, because
      `patterns._scaled_step` already compensates the same dropped call for
      the portamento and disabling the skip double-corrects it (the corpus
      figure recorded in CLAUDE.md, re-measured on this population).

      **What it costs, measured rather than predicted.** Goattracker
      *integrates* a step, so the excursion is `(cmp + 2) * speed`:
      shortening `cmp` shortens the swing by the same
      `(row_calls - 1) / row_calls`. `bend` sees exactly that and moves the
      wrong way -- mean `|log2(bend)|` **1.221 -> 1.264** (closer on 11 of 48,
      further on 25) where `-R0`, which fixes the rate without paying for it,
      reaches 1.079. **Everything else is flat**: `melody`, `sequence`,
      `wave`, `adsr`, `onset`, `gate` and the attack counts are identical on
      all 55 files, so what moves here is pitch oscillation and nothing else.

      The obvious repair is to take the depth back in `rshift`, and it was
      built and measured before being rejected. `rshift` is an integer shift
      and the factor wanted at `row_calls == 3` is `log2(3/2) = 0.585`, so the
      nearest whole shift over-corrects: decrementing it lands `bend` at 1.096
      -- close to `-R0`'s 1.079, as intended -- and costs **melody on
      Powerplay 0.993 -> 0.922 and Sigma Seven 0.990 -> 0.972**, the swing
      being deep enough to rename attacks. `vib` is identical either way
      (0.4282), which is the signature of a change to depth alone. So `rshift`
      stays where v0.5.129 left it, for a second reason now: not only did its
      two old errors cancel, there is no integer that pays this one back
      without a melody regression on the file the correction was derived from.

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
    half = bound * multiplier
    # `row_calls` is what `build_sng` receives, which `convert` passes as
    # `short_row_calls` -- the file's *shortest* row, not `_scaled_step`'s
    # longest. Exact on the 44 of these 55 files that write one row length,
    # and an over-correction on the 11 that vary, worst at Warhawk (8 against
    # 40) -- which is one of the files whose `vib` moves away from 1 here. The
    # quantity actually wanted is the mean row over the calls the vibrato
    # runs for; neither end is that, and reaching it means a new argument
    # through `convert`.
    # Zero means "do not compensate", and so does anything under 3 -- the same
    # convention and the same reason as `patterns._scaled_step`: below that the
    # value is funktempo rather than a row length, and `row_calls - 1` stops
    # being a call count worth dividing by.
    if row_calls >= 3:
        half = half * (row_calls - 1) / row_calls
    # bound 1 at -S1 asks for a half-period of one frame; Goattracker's
    # shortest is two calls (cmp 0), which is what the clamp gives.
    cmp_value = min(0x7F, max(0, round(half) - VIBRATO_CMP_BIAS))
    rshift = min(shift + _rate_shift(multiplier), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _vibrato_delay(det: Detection, multiplier: int,
                   commanded: bool = False) -> int:
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

    **This is the fallback, not the mechanism, since v0.5.199** -- see
    `_vibrato_command_pass`, which expresses the gate per note and reaches both
    halves. What stays here is the approximation for the notes it cannot reach,
    and the gate it uses depends on which of the two is running:

    * On its own, `TRIANGLE_VIBRATO_GATE` (8), even in the five files whose
      player compares against something else. A delay is doing two jobs at once
      -- suppressing short notes and postponing long ones -- and the file's own
      threshold is the right number only for the first. Substituting it here
      drops corpus agreement from 85.5% to **78.9%**, more than doubling the
      spurious vibratos (207 to 417): a lower threshold gives up the
      suppression without buying a correct onset.
    * Behind the command pass, **no delay at all** (v0.5.294). v0.5.198
      compared the file's own threshold against the constant 8 here -- two
      ways of delaying -- and chose between them at 92.1% against 90.3%.
      Neither is right. The commands already write CMD_VIBRATO on the notes
      that qualify and a suppressing 0 on the rest, so any delay postpones the
      notes they just enabled: Chimera's GT 6 has eight commanded-on notes, no
      uncommanded ones, and traced zero reversals against the original's 98,
      because the oscillator's half-period is `cmp + 2` = 4 calls and the delay
      was 8. Measured over the 25 files of this dialect, `vib` moves on 20 and
      **19 of them closer to 1.0**, median distance in log space 0.795 ->
      0.668, with no other column moving.

    The constant is therefore right as a plain delay and has no role behind
    the commands, which is why `commanded` is a parameter and not a
    convenience.

    v0.5.198 measured that last sentence rather than asserting it, across the
    25 corpus files this gate reaches, over 2487 notes of instruments whose
    only pitch movement is the vibrato (no drum or arpeggio bit). The original
    moves 435 of them. Two axes, and they oppose each other:

        gate   moves/still agrees   still notes we wobble   onset late (median)
           1                65.9%              826 of 2052                   +0
           8                85.5%                      207                  +10
          12                88.6%                      114                  +15

    So `vibdelay 1` catches 413 of the 435 but wobbles 40% of the notes that
    should be still, and 8 catches 282 and is 10 frames late on them. The
    pervasive spurious wobble is the more audible error, which is what makes 8
    the closer -- not that it scores highest. **12 scores highest and is not
    shipped**: the moves/still axis cannot see the 5 extra frames of lateness
    it costs, it plateaus at 14 because it saturates rather than peaks, and
    late onset is the defect a listener actually reported. Do not raise this
    constant on the strength of that column alone. 8 is also the player's own
    threshold, so it is the one value here that is read rather than fitted.

    Getting both halves needs the gate expressed per *note*, which means a
    pattern-level vibrato command on qualifying notes with `vibdelay 1`. That
    is what `_vibrato_command_pass` does, and this function stopped fighting
    it in v0.5.294 -- the sentence had been here since v0.5.199 while the code
    below still delayed.
    """
    if det.triangle_vibrato is None:
        # **The classic engine delays past frame 0; the LFO table does not.**
        # Halving `rshift` doubles the swing, and on its own that renames the
        # attack -- siddump names a note from the frequency on the frame the
        # gate rises, and a swing near a semitone has already moved it by then.
        # That route was refuted twice (v0.5.129, v0.5.367) at a cost of
        # melody 0.986 -> 0.299 on One_on_One_Jordan_vs_Bird alone. Delaying
        # the oscillator until frame 0 is over removes the CAUSE: the attack
        # keeps the note's own pitch, so the deeper swing is free. `multiplier`
        # calls are frame 0, so `multiplier + 1` is its first call of frame 1.
        #
        # Scoped to the classic engine because that is the population the
        # depth deficit was measured on, and because the LFO table's entry is
        # documented as starting ON the note
        # (tests/test_table_vibrato.py::test_the_entry_is_note_relative_and_starts_on_the_note).
        if det.vibrato_offset is not None:
            return max(VIBRATO_DELAY, multiplier + 1)
        return VIBRATO_DELAY
    if commanded:
        # **The commands express the gate; the delay must not express it
        # again.** `_vibrato_command_pass` writes CMD_VIBRATO on the notes
        # that qualify and a suppressing 0 on the rest -- on Chimera 264
        # enables against 1864 suppressions, and its GT 6 has *no*
        # uncommanded note at all. Leaving `vibdelay` at the threshold then
        # postpones the enabled notes too: the oscillator's half-period here
        # is `cmp + 2` = 4 calls, so 8 calls of delay costs a note its whole
        # first swing, and that instrument traces zero reversals against the
        # original's 98.
        #
        # This is what the docstring above has always said the design needs
        # ("with `vibdelay 1`"). The 92.1%-against-90.3% measurement it cites
        # compared the file's own threshold against the constant 8 -- two
        # ways of delaying -- and never asked what not delaying scores.
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
                    lead: int = 1, vibrato_command: bool = False,
                    row_calls: int = 0) -> dict:
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

    `row_calls` is passed only to the classic engine. The packed player's
    tick-0 effect skip (see _classic_vibrato_entry) applies to *every* vibrato
    it runs, so the LFO-table and global-triangle entries carry the same error
    -- they are left uncorrected because neither was measured, not because
    they are exempt, and both are a two-line change once a population to
    measure them on is chosen.

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
        entry_of = lambda b: _classic_vibrato_entry(b, mult, row_calls)
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
    delay = _vibrato_delay(det, mult, commanded=vibrato_command)
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


EFFECT_NOTE_ALT_MASK = 0x08     # bit $08's two-note alternation (7.hhhh's
#                                 other half); the pulse-width accumulator in
#                                 the disjoint dialect `det.pulse_lo_base`
#                                 reads the same bit
EFFECT_PITCH_SEQ_MASK = 0x10    # the effect byte's bit-$10 arpeggio
# Bit $40: a fixed attack pitch out of the player's own note table. It also
# halves bit $04's attack -- see `_two_stage_frames`, which is where the
# measurement behind that is recorded.
EFFECT_FIXED_PITCH_MASK = 0x40
# Bit $80: the sfx drum. Named here because bit $40's pitch is only emitted
# from the two-stage block on a record that does *not* set it -- see the call
# site, and section 7.qqq for why the two cannot share a frame.
EFFECT_SFX_DRUM_MASK = 0x80
WAVE_GATE_BIT = 0x01            # $D404 bit 0
CMD_VIBRATO = 0x04              # gcommon.h:8
GT_FIRST_NOTE = 0x60            # gcommon.h:48 FIRSTNOTE
GT_LAST_NOTE = 0xBC             # gcommon.h:49 LASTNOTE
GT_REST = 0xBD                  # gcommon.h:50 REST -- "no new note", not a stop


def _vibrato_command_pass(det: Detection, patterns: List[List[int]],
                          vib_ptrs: dict, lead: int, log=None) -> dict:
    """Move the global-triangle dialect's vibrato from the instrument to the
    pattern rows, which is the only way to express its per-note length gate.

    The player gates vibrato on the note's own stored duration and nothing
    else (§ 7.aaa, and _vibrato_delay for the disassembly):

        BD EF 14  LDA $14EF,X / AND #$1F / CMP #$08 / BCC out

    A Goattracker *instrument* cannot say that, because `vibdelay` is per
    instrument, so v0.5.198 measured the two ways of approximating it with one
    number and shipped the less-bad one: `vibdelay 8` suppresses short notes
    correctly and starts long ones 10 frames late. This is the exact form
    instead, and it works because of where gplay.c puts the delay countdown:

        case CMD_DONOTHING:
        if ((!cptr->cmddata) || (!cptr->vibdelay)) break;
        if (cptr->vibdelay > 1) { cptr->vibdelay--; break; }
        case CMD_VIBRATO:                      // <-- fallthrough target
        ...oscillate...

    The countdown lives *inside* `case CMD_DONOTHING`. A row carrying
    `CMD_VIBRATO` enters at the second label and never sees it, so a commanded
    vibrato runs from the note's first call whatever `vibdelay` holds. Set the
    instrument's `ptr[STBL]` to 0 and an *uncommanded* note takes the
    `!cmddata` break and gets nothing at all. Between them: vibrato on exactly
    the notes the player vibrates, starting where the player starts it.

    Three properties of the row stream make this a pass rather than a rewrite:

    * **The gate needs no unit conversion.** `_build_raw_pattern` emits `wait`
      hold rows after each note and `wait = b1 & 0x1F` is the identical
      expression to the player's `AND #$1F`, so a note occupies `wait + 1`
      rows and `wait >= 8` is exactly `rows > TRIANGLE_VIBRATO_GATE`. Nothing
      here depends on frames per row, on the tempo, or on the multiplier --
      which is why this is the one rate-like quantity in the file that is *not*
      scaled (contrast build_speed_table, _drum_speed, _wave_hold_byte).
    * **Hold rows already carry the note row's command** (`events += [GT_NO_NOTE,
      0x00, cmd1, cmd2]`), and an empty row would otherwise reset `cmddata`
      back to the instrument's zeroed pointer and stop the oscillation
      mid-note, so the command has to be on every row of the note -- and
      writing it there matches what the decoder does with a portamento.
    * **`$BD` is "no new note", not a rest.** gplay.c:925 only assigns
      `newnote` for `<= LASTNOTE`, so a `$BD` row continues the note and is
      safe to treat as part of its block.

    **A short note is damped explicitly, and the instrument keeps its pointer.**
    `$04 00` gives `cmddata = 0`, which still enters `case CMD_VIBRATO` but with
    `cmpvalue` and `speed` both 0, so it adds nothing to the frequency -- a
    suppression that costs no extra state and, unlike zeroing `ptr[STBL]`,
    applies per note. Keeping the pointer then means a note this pass *cannot*
    reach falls back to the v0.5.198 approximation rather than losing its
    vibrato outright. Measured over the 25 files and 2487 notes of § 7.kkk,
    the three combinations separate cleanly:

        variant                    agree   miss  invent   onset (median)
        instrument vibdelay 8      85.5%    153     207              +10
        command, ptr[STBL] = 0     88.9%    212      63               +0
        command, pointer kept      85.6%    152     207               +0

    Zeroing the pointer removes 144 spurious vibratos -- notes lasting more
    than 8 *calls* whose player duration is under 8 *frames*, which a delay
    cannot distinguish and this gate can -- but costs 60 notes that qualify and
    could not be commanded. Damping short notes explicitly gets both, which is
    what this function does.

    **The threshold is the file's own `CMP`, not TRIANGLE_VIBRATO_GATE.** Those
    three rows were all measured against the assumed 8, and on Commando that
    damped 695 of 705 notes and vibrated 10 -- the constant was read from one
    player and 5 of the 25 compare against something else (Commando 6, then 5,
    4, 4, 2; detect._find_triangle_gate). With its own 6 the file vibrates 50
    notes and scores 100.0% where the instrument delay scored 97.8%, and the
    arithmetic is checkable rather than fitted: `wait >= 6` selects the 24- and
    30-frame notes, of which GT 1 has 27 + 4 = 31, exactly the 31 notes the
    original is measured to vibrate. Corpus-wide, with the right threshold:

        delay, gate 8 (v0.5.198)   85.5%   miss 153   invent 207   onset +10
        delay, per-file gate       78.9%   miss 109   invent 417   onset +10
        command + damp             92.1%   miss 129   invent  68   onset  +0

    -- better on *both* axes than either delay, which no single `vibdelay` could
    manage, and better on 6 files than the middle row is on any. The second row
    is the warning: the per-file gate is an improvement here and a regression as
    a plain delay. See `_vibrato_delay`.

    Skipped, and counted rather than silently dropped: a note whose command
    column is already spoken for (a portamento or a tempo change -- one column
    per row, and the slide is the more audible of the two), and a *qualifying*
    note whose live instrument is not known because no row has named one yet in
    this pattern. A short note needs no index to damp, so an unnamed instrument
    does not stop it.
    """
    gate = det.triangle_gate or TRIANGLE_VIBRATO_GATE
    by_slot = {rec + 1 + lead: idx for rec, (idx, _delay) in vib_ptrs.items()}
    placed = damped = busy = unknown = 0
    for pat in patterns:
        live = 0
        i = 0
        while i + 3 < len(pat):
            note, instr = pat[i], pat[i + 1]
            if instr:
                live = instr
            if not GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                i += 4
                continue
            end = i + 4
            while (end + 3 < len(pat) and pat[end] == GT_REST
                   and pat[end + 1] == 0):
                end += 4
            index = 0
            if (end - i) // 4 > gate:
                index = by_slot.get(live, -1)
            if index < 0:
                unknown += 1
            else:
                # Only the free rows, so a portamento or a tempo change keeps
                # the column -- and a note whose *own* row is taken still gets
                # the vibrato on the rest of its block rather than none at all.
                # A tie emits CMD_TONEPORTA on the landing row (patterns.py),
                # and the original starts oscillating a frame or two into that
                # note, so filling from the next row is also what it does.
                for row in range(i, end, 4):
                    if pat[row + 2] == 0:
                        pat[row + 2] = CMD_VIBRATO
                        pat[row + 3] = index
                if pat[i + 2] != CMD_VIBRATO:
                    busy += 1
                elif index:
                    placed += 1
                else:
                    damped += 1
            i = end
    if log and (placed or damped):
        log(f"Vibrato command.........: {placed} note(s) vibrated, "
            f"{damped} damped by length"
            + (f", {busy} with the column in use" if busy else "")
            + (f", {unknown} on an unnamed instrument" if unknown else ""))
    return vib_ptrs


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
                       wave_program: bool = False,
                       pitch_seq: bool = False,
                       note_rows: Optional[dict] = None,
                       row_calls: int = 0,
                       no_test_restart: bool = False,
                       voice_two_stage: bool = False,
                       voice: Optional[int] = None,
                       gate_skip: Optional[int] = None) -> tuple:
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
        if drum and arp:
            # **A record setting both bits owes the noise tick as well.** The
            # drum block does not branch around the arpeggio: International
            # Karate $B15F is Warhawk $1366 byte for byte, and every one of its
            # exits -- the bit test, both guard loads and the `STA $D404,Y` at
            # the end -- lands on the `NOP` at $B19B, one byte before the
            # arpeggio's own `LDA effect / AND #$04` at $B19C. The two run in
            # sequence for such a record, the drum writing $D404 (noise while
            # the duration counter is still large) and the arpeggio then
            # overwriting the frequency it swept.
            #
            # Five slots cannot hold the drum's *sweep* beside the arpeggio's
            # pair, which is why the shape below keeps the arpeggio -- but the
            # tick is two entries and the variable-length wavetable has room
            # for them. `drum` stays true so the tail keeps its gate-off bit;
            # only the tick is added, by the same route a sustaining record
            # already takes.
            #
            # Measured on the original rather than argued from the bit: IK's
            # three both-bits records open `pul noi noi pul`, `saw noi noi saw`
            # and `pul noi noi pul` where we held the base waveform for all
            # four frames, and its missing noise frames (437 against 828) are
            # exactly this tick.
            tick = True
    if arp_note == 0:
        arp_note = 0x74

    # The byte-code wave program is the whole instrument where it applies: the
    # player's interpreter writes $D404 and $D401 itself and returns, so no
    # other shape in this function is reached for such a record.
    if wave_program and speed_table is not None:
        prog = _wave_program_entries(sid, det, i, speed_table, fmt,
                                     multiplier, budget,
                                     written=no_test_restart)
        if prog is not None:
            return prog

    # The bit-$80 drum, read before everything else because it is the whole
    # note: the player skips its own waveform and frequency writes on the frame
    # it fires (`BNE` past them), so nothing else in this function applies to
    # the instrument. Loops for as long as the note is held, as the player's
    # per-voice counter does.
    if (sfx_drum and det.sfx_pitch >= 0 and (arp_style & 0x80)
            and fmt == FORMAT_GTS5):
        # The $40 pitch fires once per *note* -- its counter runs out -- so it
        # goes in a prologue the loop's jump skips. Passed into a single looping
        # block it landed on every tick: exact on Trans-Atlantic, whose bursts
        # happen to line up, and 281 frames against the original's 35 on
        # Pandora. See H2G-CONVERSION-METHOD.md section 7.rrr.
        hit = _sfx_drum_entries(wave, det.sfx_pitch, det.sfx_period, multiplier,
                                second_note=_fixed_attack_note(sid, det, i))
        if hit is not None:
            left, right, loop = hit
            jump = len(left) + 1
            if start is not None and jump <= budget:
                # The jump targets the *loop*, not the block: a prologue before
                # it must not repeat. `loop` is 0 for the plain shape, which is
                # the whole block looping as before.
                return left + [0xFF], right + [start + loop]

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
            frames = _two_stage_frames(data[fr], arp_style)
            # A record setting bit $10 as well gets **both**: in the player the
            # two are sequential tests on one effect byte, $04 choosing the
            # waveform and $10 the note, and neither can skip the other. Gated
            # per record on both bits -- `arp_style` is this record's own +7,
            # and `_pitch_seq_notes` re-checks $10 on it -- because a
            # file-level flag says only that the player reads the bit, which is
            # the mistake `_fixed_attack_note` made against Thundercats' drum.
            if (pitch_seq and fmt == FORMAT_GTS5 and start is not None
                    and (arp_style & EFFECT_PITCH_SEQ_MASK)):
                notes = _pitch_seq_notes(sid, det, i)
                if notes is not None:
                    both = _two_stage_pitch_seq_entries(
                        wave, data[at], frames, notes, start,
                        multiplier, budget, written=no_test_restart)
                    if both is not None:
                        return both
            # Effect bit $40's fixed attack pitch, and the gate on it is bit
            # $80 rather than the bit itself.
            #
            # § 7.qqq measured the balloon song's three-bit drum -- $04, $80
            # and $40 interleaved by frame, the played note at offset 0, $80's
            # pitch at offset 1 and $40's at offset 2 -- and concluded that
            # `_fixed_attack_note` must never be passed here, because on that
            # record frame 1 belongs to $80 and melody falls 85% -> 39%. That
            # is a profile of a record carrying **all three** bits. Measured on
            # a `$44` record -- One_on_One's GT 2, 372 onsets, no distribution
            # at all on any offset:
            #
            #   offset 0   wf $43 (the record's own +2)   the PLAYED note
            #   offset 1   wf $81 (the attack)            $4310  <- fixed
            #   offset 2   wf $81                         $4310
            #   offset 3   wf $43                         $4310
            #   offset 4   wf $42 (gate off)              the next note
            #
            # With no $80 in the record nothing else claims frame 1, and the
            # fixed pitch starts there -- exactly where `_two_stage_entries`
            # puts it, since the frame-0 lead writes no note. So the gate is
            # the *drum* bit, per record: `arp_style` is this record's own +7,
            # the same per-record rule `_fixed_attack_note` itself applies to
            # $40 after Thundercats.
            #
            # **`VIBRATO.md`'s `atkpitch` bucket cannot move on this, and it
            # is not a defect in the emission.** That census names a row's
            # cause from the record's effect bits, so a `$44` record with no
            # other pitch-moving bit this player reads is filed under `$40`
            # whatever is actually moving its pitch -- and in the two rows
            # holding 543 of the bucket's 569 reversals it is something else
            # entirely. One_on_One's `$06A6` walks the pitch over offsets
            # 3-7 of every note (`$1920 $19e2 $1aa4`), and Knucklebusters'
            # `$0AAD` runs a plain 4-5 frame vibrato (`$0f14`..`$0ff0`, 22
            # reversals in one 84-frame note). Worse, `pitch_motion` skips
            # frames `a-1..a+1` and this effect is a *step to a constant*, so
            # even a perfect emission contributes ~0 reversals: wiring it
            # leaves the vibrato census on all nine affected files
            # byte-identical. What it does move is One_on_One's `slides`,
            # 4325 -> 4139 against the original's 2809, with every other
            # column on all nine files unchanged.
            #
            # The other four `atkpitch` rows cannot reach this code at all:
            # Knucklebusters, Deep_Strike, Sanxion and Food_Feud all have
            # `det.wave_program < 0`, and that array is where the note index
            # lives, so `_fixed_attack_note` returns None for every record in
            # them. Locating it is `detect.py` work, not this call site's.
            two = _two_stage_entries(wave, data[at], frames, multiplier,
                                     attack_note=(
                                         None if arp_style & EFFECT_SFX_DRUM_MASK
                                         else _fixed_attack_note(sid, det, i)),
                                     budget=budget,
                                     written=no_test_restart)
            if two is not None:
                return two

    # The same attack with per-voice parameters (Ninja). Gated on `effects`
    # like every other reading of +7 -- with the flag off this function still
    # reproduces the VB6 original byte for byte, and the first version of this
    # block broke that. Gated too on the record's own bit $02 *and* on the
    # instrument having been resolved to a voice:
    # the player's tables are indexed by voice and a Goattracker wavetable is
    # per instrument, so an instrument played on two voices has two different
    # right answers and gets neither. `voice` is None for exactly that case --
    # see `tracks.instrument_voices` and `_record_voice`.
    if (voice_two_stage and effects and voice is not None
            and det.voice_two_stage_alt >= 0 and (arp_style & 0x02)):
        alt = data[det.voice_two_stage_alt + voice]
        threshold = data[det.voice_two_stage_frames + voice]
        pair = _voice_two_stage_entries(wave, alt, threshold, multiplier,
                                        budget=budget,
                                        written=no_test_restart,
                                        gate_skip=gate_skip)
        if pair is not None:
            return pair

    # Bit $01's alternating waveform where its table is per voice (Ninja).
    # Placed after the per-voice two-stage block because the player runs the
    # two in that order and the later write wins: bit $01's block is at
    # `$CADD` and bit $02's at `$CAFD`, both storing to `$D404`, so a record
    # setting both sounds $02's. No corpus record sets both.
    #
    # Gated on `effects`, on the record's own bit $01, and on the instrument
    # having been resolved to a voice -- `_record_voice`, the same rule the
    # block above uses, because the table is indexed by voice and a
    # Goattracker wavetable is not.
    if (effects and (arp_style & 0x01) and voice is not None
            and det.voice_wave_alternate >= 0):
        # `alt_first`: the branch runs the opposite way from W_A_R's dialect
        # (detect.VOICE_WAVE_ALT_SHAPE), so the note's second call sounds the
        # alternate rather than the record's own. Read off the branch and
        # measured on voice 1, whose onset frame is `41` and whose next frame
        # is `81`.
        pair = _wave_alternate_entries(
            wave, data[det.voice_wave_alternate + voice], multiplier, start,
            budget, written=no_test_restart, alt_first=True)
        if pair is not None:
            return pair

    # Effect bit $10's arpeggio, after the two-stage block because a record
    # setting both ($14 here) gets its waveform from that one -- and because a
    # record with no waveform of its own reaches this and is declined. That is
    # still an under-read: `_sfx_drum_entries` stopped making it in v0.5.253
    # by routing the held byte through `_wave_byte`, and the same encoding is
    # available here.
    if pitch_seq and fmt == FORMAT_GTS5:
        arpseq = _pitch_seq_entries(sid, det, i, wave, multiplier)
        if arpseq is not None:
            left, right = arpseq
            if start is not None and len(left) + 1 <= budget:
                return left + [0xFF], right + [start]

    # Effect bit $02's alternating waveform, after the two-stage block for the
    # reason the player gives: a record setting both gets its waveform from
    # $04's handler, which runs later and overwrites this one's cell on every
    # frame -- while its counter runs with the attack waveform, and afterwards
    # with the record's own `+2`. No corpus record sets both in any case.
    # Gated on `effects` like every other reading of +7, and on the routine
    # being present rather than on the bit alone: bit $02 is the *rise* in
    # Warhawk's dialect, and no file has both blocks.
    if effects and (arp_style & 0x02):
        alt_byte, alt_first = None, False
        if det.wave_alternate >= 0:
            a = det.wave_alternate + i * det.instr_stride
            if a < len(data):
                alt_byte = data[a]
        # `det.wave_alternate_noise` -- the derived dialect (Hollywood or
        # Bust, Chicken Song) -- is deliberately NOT emitted here. It is
        # decoded and measured: Chicken_Song gains (wave 77 -> 84%, noise
        # 490 -> 919, nrun 0 -> 100%, onset 57 -> 86%, melody unmoved) and
        # Hollywood_or_Bust loses **11 points of melody** for the same
        # register gains. Two files, one each way, and no per-song switch
        # short of a sixth `--fidelity` toggle -- which doubles a search
        # already running 31 combinations a song. See
        # H2G-CONVERSION-METHOD.md section 7.iiii.
        #
        # **Those figures were taken against a baseline that no longer
        # exists**, and the "noise 490" half of it was never this dialect's:
        # the 490 came from bit $01 emitting a drum on Chicken Song, which
        # `detect._find_effect_routines` stopped doing once the block was
        # required to contain the noise constant `LDA #$80` -- Chicken Song's
        # writes a per-voice table byte to $D404 instead. Its baseline is now
        # **0 noise frames**, and all 654 the original makes are on the two
        # records that carry bit $02 (ADSR $0A07 and $0900), which is this
        # dialect and nothing else. So the trade above still has to be
        # re-measured before it is quoted; what it says today is that the one
        # mechanism that would put noise in this file is the one held back.
        if alt_byte is not None:
            # **Effect bit $08 rides the same pair.** It is the same counter
            # and the same phase test 24 bytes further on, alternating the
            # *note* where this block alternates the waveform, and all 80
            # corpus records that set it also set $02 -- so it is one shape
            # and not a second emitter. `_note_alternate_note` returns None
            # for a record that does not set the bit, which leaves every other
            # file's bytes exactly as they were.
            alt = _wave_alternate_entries(
                wave, alt_byte, multiplier, start, budget,
                written=no_test_restart, alt_first=alt_first,
                alt_note=_note_alternate_note(sid, det, i))
            if alt is not None:
                return alt

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
        # **The tick's length is the player's speed gate less one, not the
        # constant**, exactly as it is in `_drum_entries` -- the same rule
        # about the same block, and this emitter had been reading it from a
        # hardcoded 2 while the other derived it. The corpus says which: the
        # five files whose noise runs regressed when the tick first reached a
        # both-bits record (Warhawk, Formula_1_Simulator, Spellbound, Proteus,
        # Last_V8) are exactly the five whose gate derives 1, and IK -- where
        # the original measures two frames of noise -- derives 2.
        extra = _noise_tick_frames(sid, det) * max(1, multiplier) - 1
        tl, tr = [noise], [0x00]
        if extra == 1:
            tl.append(noise)
            tr.append(0x00)
        elif extra > 1:
            # A delay is current for value + 1 calls, and its right side is
            # read on the last of them, so $80 keeps it from moving the note.
            tl.append(min(extra - 1, WAVE_MAX_DELAY))
            tr.append(0x80)
        # **And the lead is a frame, not a call** -- `_first_frame_lead`, the
        # third emitter to need it and the third to have been written without
        # it. At `-S2` a single entry covers half of frame 0 and the noise
        # finishes the frame, so siddump (which samples at end of frame) reads
        # the tick where the player has the record's own waveform: Warhawk's
        # five ticked instruments all measured `noi pul pul pul` against the
        # original's `pul noi pul pul`, while its two drum-only ones -- which
        # take `_drum_entries`, where the lead was fixed in v0.5.220 -- matched.
        # `force=True` for the same reason that caller gives: this block has
        # always emitted entry 0, so gating it on `_first_frame_entry` would be
        # a second, unmeasured change.
        # (named apart from this function's `lead` parameter, which is the
        # instrument-number offset the wavetable pointers are built from)
        frame0, frame0_r = _first_frame_lead(wave, multiplier, force=True,
                                             written=no_test_restart)
        # **The tick is an addition, so it has to fit.** This block ignored
        # `budget` entirely: with the frame-0 lead two entries above -S1 and the
        # tick's own delay a third, it emits 7 or 8 where the caller has
        # reserved 5, and the layout's "nobody starves" guarantee is the
        # caller's arithmetic rather than a property the emitters held up. 122
        # of the corpus's records are in that case, and it only bites where a
        # table is nearly full: W_A_R at `--two-stage --pitch-seq` overran 255
        # by one and `gt2reloc` refused the file. Where there is no room the
        # record keeps the five-entry shape below -- the tick is what is lost,
        # not the table.
        tick = len(frame0) + len(tl) + 4 <= budget
    if tick:
        off = len(tl) + len(frame0) - 1
        # Two `tail` entries, mirroring the untimed shape's entries 1-2: the
        # arpeggio loops over the second of them and the entry after it, so
        # collapsing them to one puts the stop where the arpeggio's own
        # entries belong and the loop is never reached.
        left = frame0 + tl + [tail, tail, 0xFF, 0xFF]
        right = frame0_r + tr + [0x00, 0x00, 0x00, 0x00]

    # A record that sets both bits gets both blocks in the player -- the drum
    # sets the waveform, the arpeggio then overwrites the frequency it swept
    # ($13F4 runs after $139F). Five entries cannot hold the drum's *sweep*
    # beside the arpeggio's pair, so such a record keeps the arpeggio and takes
    # the shape above: the record's waveform on frame 0, the noise tick, then
    # the gate-off tail the arpeggio alternates over. 62 of the 291 drum
    # records this gate keeps are in that case.
    if drum and effects and not arp:
        # min_played_notes is keyed by Goattracker instrument number, and this
        # function's `i` is the 0-based record index: instrument 1 is the
        # hardcoded Clear Voice, so record i is instrument i + 2.
        lowest = None if min_notes is None else min_notes.get(i + 1 + lead)
        typical = (None if note_rows is None
                   else note_rows.get(i + 1 + lead))
        # The tick length is the player's speed gate less one, not a constant:
        # `lengthleft` decrements once per duration unit, so the drum's "first
        # vbl" test stays true for `frames` frames and the note's own first
        # frame is spent by the init path. See `_noise_tick_frames`.
        #
        # Two attempts to measure this came back flat, and both were the
        # *metric*: an attack-anchored reading asks what the waveform is at
        # `a + k`, and that anchor moves when the run's length changes.
        # Measured position-independently (`fidelity.noise_run_agreement`) the
        # derived length takes the corpus from 19 of 74 drum instruments
        # matching the original's run to 43.
        return _drum_entries(wave, fmt, speed_table, multiplier, lowest,
                             sustain=data[base + 4] >> 4, budget=budget,
                             tick_frames=_noise_tick_frames(sid, det),
                             note_rows=typical, row_calls=row_calls,
                             written=no_test_restart)

    if drum and not tick:
        if effects:
            # The arpeggio keeps entries 2-4, so all the drum can say here is
            # where it starts: the voice's own waveform, gate released. With
            # `effects` on a both-bits record no longer reaches this: it is
            # ticked above, and the tick block has already written entries
            # 1-2 and both tails. Only the `effects`-off shape -- which
            # reproduces the VB6 original and knows nothing of either
            # routine -- is left here.
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
    second = (base_entry + 1 + off) & 0xFF
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
            # The alternation belongs on the *third* call, not the fourth.
            # The player's own trace is `note note arp note arp ...` -- Commando
            # GT 2 reads `1D46 1D46 3A8C 1D46 3A8C` from each onset -- so the
            # arpeggio note goes on entry 2 and the jump returns to entry 1,
            # giving base, base, arp, base, arp. Carrying it on entry 3 with the
            # jump to entry 2 delayed the first swing by one call, and with the
            # `$09` first-frame waveform ahead of it the measured onset landed on
            # frame 3 or later where the player's is frame 1-2 -- 15 of the 24
            # corpus files with an arpeggio routine. The rate and the interval
            # were always right; only the phase was late.
            if effects:
                right[2 + off] = _arp_relative(arp_fixed, arp_note)
                right[3 + off] = second
            else:
                # `effects` off means "reproduce the VB6 original", and the
                # fixture encodes its shape: the arpeggio on entry 3 with the
                # jump returning to entry 2. Correcting the phase here broke 26
                # byte-exactness tests -- the same leak, with the same count, as
                # `arp_fixed_up` before it was gated.
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
                  budget: int = WAVE_ENTRIES_PER_INSTR,
                  tick_frames: int = NOISE_TICK_FRAMES,
                  note_rows: Optional[int] = None,
                  row_calls: int = 0,
                  written: bool = False) -> tuple:
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

    Emitted here: attack, the gate-off waveform, the sweep, stop. The step size
    is literal (see _drum_speed, which divides the player's per-frame step by
    the -S multiplier); the depth is bounded by three things, and the block
    itself supplies two of them -- what cannot wrap (`_drum_max_steps`, its
    `LDA freqhi,X / BEQ out`), how long the note lasts
    (`_drum_duration_steps`, its `LDA remaining,X / BEQ out`), and what the
    wavetable can hold.

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

    A step past the first is written only where `_drum_steps_safe` can prove it
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
    # **The waveform holds for a whole frame, which is `multiplier` calls.**
    # This entry was one call at every -S value until v0.5.220, so on a
    # multispeed file the noise below finished frame 0 and siddump -- which
    # samples at end of frame -- read the drum's tick where the player has the
    # record's waveform. It is the same defect v0.5.218 fixed in the other two
    # emitters, arriving by the other route: not the effect placed on frame 0,
    # but the waveform too short to keep it off. 20 of the 23 instruments still
    # reading a frame early after v0.5.218 were on `-S2` files, against 3 on the
    # 45 single-speed ones.
    lead, lead_r = _first_frame_lead(wave, multiplier, force=True,
                                     written=written)
    left = lead + [WAVE_NOISE_GATEOFF | (wave & 0x01)]
    right = lead_r + [0x00]
    # Two frames is `2 * multiplier` calls, of which the entry above is one.
    # A delay entry is current for `value + 1` calls (see _wave_hold_byte), so
    # one more entry covers the rest at every -S value the corpus uses; its
    # right side is $80 because a delay's right side IS read, on its final
    # call, and anything else would drag the note.
    extra = tick_frames * max(1, multiplier) - 1
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
    # **And the base shape has to fit too.** Above `-S1` this is six entries --
    # the frame-0 lead is two and the tick's delay a third -- against the five
    # the caller reserves for every later record, on 75 corpus records. Only the
    # *sweep* below was ever checked. Where there is no room the multiplier
    # padding goes first: it is the smaller loss (the lead reverts to the one
    # call it was before v0.5.220) and it keeps the tick, which is the thing a
    # listener hears.
    while len(left) > budget and len(lead) > 1:
        del left[1], right[1]
        lead = lead[:-1]
    # Then the tick's own hold, which sits directly after the noise entry --
    # index `len(lead) + 1`, and only where the tick has one to give up. The
    # caller's floor is `WAVE_ENTRIES_PER_INSTR`, so trimming the lead alone
    # already fits every budget the layout hands out and this is the guard for
    # a caller that asks for less.
    if len(left) > budget and len(left) > len(lead) + 3:
        del left[len(lead) + 1], right[len(lead) + 1]
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
        # ... and no deeper than a note of this record's own typical length
        # gives the player frames to sweep in. The pitch bound above says how
        # far a chain *may* fall; this says how far the original's own block
        # gets to before the note ends. Only ever a reduction, so a record
        # whose notes are long enough -- or one with no measured note at
        # all -- is written exactly as it was.
        held = _drum_duration_steps(note_rows, row_calls, multiplier)
        if held is not None:
            steps = min(steps, held)
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
#
# It is a corpus-wide stand-in for the per-record number `_drum_duration_steps`
# now derives, and the two are both applied: whichever is smaller wins.
DRUM_MAX_SWEEP_STEPS = 8


def _drum_duration_steps(note_rows: Optional[int], row_calls: int,
                         multiplier: int = 1) -> Optional[int]:
    """Sweep steps a note of `note_rows` rows leaves the player room for.

    Read off the block in `_drum_entries`, in the units its two guards count
    in. `R` is the note's remaining length and it decrements once per duration
    *unit*, not per frame (`_noise_tick_frames`), so with `W = R`'s reload
    value the block spends:

    * `R == W`, one whole unit, on the `BCC` noise branch -- which writes the
      frequency without decrementing it, and is why the sweep begins at the
      unit boundary rather than at the note's first frame;
    * `R` from `W - 1` down to `1`, `W - 1` units, sweeping once per frame;
    * `R == 0`, the last unit, back out through `LDA remaining,X / BEQ out`
      with the frequency frozen where the sweep left it.

    A converted row is one unit and an event lasts `wait + 1` of them
    (`_build_raw_pattern`), so `note_rows` rows is `W + 1` and the sweep
    runs `(note_rows - 2) * frames_per_row` frames. The first of those
    frames writes the frequency it was already at -- `LDA freqhi / DEC / STA`
    stores the value it loaded -- so one fewer than that many *decrements*
    reach the chip, and a `CMD_PORTADOWN` entry is exactly one decrement.

    `row_calls` is the row in play calls (`tempo_command_value`), i.e.
    `frames_per_row * multiplier`, and the step size is already `1/multiplier`
    of a frame's (`_drum_speed`) -- so the whole thing is counted in calls and
    the single frame comes off as `multiplier` calls. Done that way rather
    than by recovering `frames_per_row` first because a row is not always a
    whole number of frames: W_A_R packs 9 calls at `-S4`, and flooring 9/4 to
    2 would lose an eighth of every sweep. What is kept right is the *travel*,
    not the count.

    Checked against the original: Commando's gate is 3 frames a unit and its
    instrument 13 is played at four rows, giving `(4 - 2) * 3 - 1 = 5` -- and
    a 240 s siddump of subtune 0 has 106 sweeps of exactly 5 steps
    (`0DD0 -> 08D0`). The other 12 are `0DD0 -> 01D0`, longer notes stopped by
    the player's *other* guard, `LDA freqhi,X / BEQ out`, which is the bound
    `_drum_max_steps` already expresses.

    Returns None where nothing is known, so an unmeasured record keeps
    whatever the pitch bound alone gave it.
    """
    if note_rows is None or row_calls <= 0:
        return None
    return max(0, (note_rows - 2) * row_calls - max(1, multiplier))



def _noise_tick_frames(sid: SidFile, det: Detection) -> int:
    """Frames of noise this player's drum block writes, from its speed gate.

    **It is the speed gate less one, and that is a mechanism rather than a fit.**
    The drum's "is this the note's first vbl" test compares `(duration & $1F) - 1`
    against the note's remaining length, and `lengthleft` decrements once per
    duration *unit* -- not per frame. So the test stays true for as many frames
    as a unit lasts, and the note's own first frame is spent by the init path
    writing the record's waveform to `$D404` after the drum routine has run. What
    reaches the chip is therefore `frames - 1` frames of noise.

    Measured across the 25 corpus files with a drum routine and a pitched record,
    it is exact on 22:

        gate 2 -> run 1   12 files (Monty, Last_V8, Warhawk, Phantoms, ...)
        gate 3 -> run 2   10 files (Commando, Crazy_Comets, Zoids, ...)

    The three exceptions are the noise-throughout class -- a record whose
    waveform carries no waveform bits, which Hubbard's own comment covers
    ("ctrlreg 0 is always noise") -- and one file where no gate is found at all,
    which keeps `NOISE_TICK_FRAMES`.

    This is what the hardcoded 2 was standing in for. It was one frame too long
    for the twelve files whose gate is 2. See H2G-CONVERSION-METHOD.md 7.ggg.

    **Which subtune's gate, though.** This took the mode over every subtune,
    on the reasoning that one odd subtune must not retime a table the whole
    song shares. Commando is what that gets wrong: its gates are
    `(3, 4, 3, 3, 1, None, 1, ...)` -- four songs and fourteen one-frame sound
    effects, so the effects outvote the music and the mode is 1 where the
    original measures a two-frame tick on all five of its pitched drum records
    (371 runs of 2 against nothing else). The subtune to read is the one the
    file itself starts on, `resolve_subtune`'s rule and for its reason: it is
    the subtune a player selects when the user selects none, and therefore the
    one that is the tune.

    Settled by measuring the original rather than by argument. Tracing each of
    the 35 corpus files whose player has the drum routine and taking the modal
    noise-run length over the ADSR pairs of its drum-flagged *pitched* records:

        startSong exact on 27, the mode on 24, of the 28 files whose run is
        short (1-3 frames); startSong is right everywhere the mode is and on
        Commando, Delta and Phantoms_of_the_Asteroid besides.

    The seven files neither derivation fits measure 12-18 frames -- the
    noise-throughout class §7.ggg already documents -- and Sanxion is the one
    genuine miss: it measures 1 where both derivations say 2.
    """
    try:
        speeds = find_song_speeds(sid, det if det.can_convert else None)
    except Exception:                                  # noqa: BLE001
        return NOISE_TICK_FRAMES
    raw = speeds.frames if (speeds and speeds.frames) else ()
    # A subtune whose reload exceeds MAX_SANE_SPEED_RELOAD reports None (see
    # SongSpeeds.frames), and a file where that subtune is unreadable -- or
    # every subtune's is -- must not let None reach Counter/`- 1`.
    idx = max(0, getattr(sid, "start_song", 1) - 1)
    gate = raw[idx] if idx < len(raw) else None
    if gate is None:
        frames = tuple(f for f in raw if f is not None)
        if not frames:
            return NOISE_TICK_FRAMES
        gate = Counter(frames).most_common(1)[0][0]
    return max(1, gate - 1)


def _drum_max_steps(min_note: Optional[int], multiplier: int = 1) -> int:
    """Deepest sweep this record can take without wrapping, in wavetable steps.

    This is the block's *first* exit -- `LDA freqhi,X / BEQ out`, the frequency
    reaching zero (section 7.ii) -- and the deepest a Goattracker
    `CMD_PORTADOWN` chain can go without underflowing is exactly the distance
    from the *lowest note the record is played at* down to zero. Falling that
    far from any higher note lands short of silence but still travels most of
    the way, which is the shape a tom has anyway.

    **It is not on its own the musical target**, though this said for three
    versions that "the safety bound and the musical target turn out to be the
    same number". They coincide only where the note lasts long enough for the
    frequency to reach zero before the block's *other* exit -- `LDA
    remaining,X / BEQ out`, the note ending -- fires. Commando's instrument 13
    has room for thirteen steps here and its original takes five, because its
    note is four rows long. `_drum_duration_steps` is that second guard, and
    both are applied.

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


def _record_voice(instr_voices: Optional[dict], instr: int) -> Optional[int]:
    """The voice `instr` is mostly played on, or None if no pattern names it.

    A per-voice effect has no single right answer for an instrument two voices
    share, and the first version of this refused those outright -- emit
    nothing rather than pick. **Measured, picking is better.** Ninja's GT 12
    is played on voices 1 and 3; refusing it left `onset` at 60% and taking
    its busier voice puts it at 80%, with `melody`, `seq`, `noise` and every
    other dimension unmoved and `wave` inside a point. The reason the choice
    is cheap here is visible in the tables it indexes: the alternates for
    those two voices are `$11` and `$15`, triangle either way, so the wrong
    half of the guess is wrong about the ring bit and right about the
    waveform.

    Weighted by rows *and* by how often the orderlists play the pattern
    holding them (`tracks.instrument_voices`), so "mostly" is about how much
    of the tune sounds that way rather than about how the patterns were
    written. None only where nothing names the instrument at all.
    """
    if not instr_voices:
        return None
    per = instr_voices.get(instr)
    if not per:
        return None
    return max(per, key=per.get)


def _wavetable_layout(sid: SidFile, det: Detection, instr_used: int,
                      effects: bool, fmt: str, speed_table: List[tuple],
                      multiplier: int, min_notes: Optional[dict],
                      lead: int, two_stage: bool = False,
                      sfx_drum: bool = False,
                      wave_program: bool = False, pitch_seq: bool = False,
                      note_rows: Optional[dict] = None,
                      row_calls: int = 0,
                      no_test_restart: bool = False,
                      voice_two_stage: bool = False,
                      instr_voices: Optional[dict] = None,
                      gate_skip: Optional[int] = None,
                      real_firstwave_instruments: tuple = ()) -> tuple:
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
        # Must agree with _write_instruments' own per-instrument decision, or
        # the wavetable's own first entry and the instrument record's
        # firstwave byte disagree about who writes frame 0 -- exactly the
        # mismatch that made real_firstwave_instruments alone (without this)
        # cost ACE_II melody 100% -> 88% instead of fixing it: the record's
        # byte writes the real waveform on frame 0 AND the wavetable's entry 0
        # still assumed a testbit lead-in and wrote its own, one frame later.
        gt_number = i + lead + 1
        instrument_written = no_test_restart or gt_number in real_firstwave_instruments
        left, right = _wavetable_entries(sid, det, i, effects, fmt, speed_table,
                                         multiplier, min_notes, lead,
                                         start=start, budget=budget,
                                         two_stage=two_stage,
                                         sfx_drum=sfx_drum,
                                         wave_program=wave_program,
                                         pitch_seq=pitch_seq,
                                         note_rows=note_rows,
                                         row_calls=row_calls,
                                         no_test_restart=instrument_written,
                                         voice_two_stage=voice_two_stage,
                                         voice=_record_voice(instr_voices,
                                                             gt_number),
                                         gate_skip=gate_skip)
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


def _pulse_triangle(width: int, low: int, high: int,
                    speed: int) -> tuple[List[tuple], int]:
    """A triangle between two high nibbles, opening at the record's own width.

    Shared by the two engines that sweep the whole 12-bit width -- the
    per-record bounds array (`_pulse_program`) and the fixed-bound triangle
    (`_pulse_tri_program`) -- because the shape is the same and only where the
    bounds come from differs.

    **It opens at the record's width, not at a bound.** The player reseeds its
    accumulator from record +0/+1 at each note and sweeps from there, so the
    width the record names is the duty cycle every attack is heard on. Starting
    at the low bound instead put Trans-Atlantic's lead on `$D00` where the
    player opens on `$880`, and shrank its band from the original's 1728 to 508:
    the sweep was the right shape in the wrong place. `_pulse_tri_program` was
    given the record's width in v0.5.174 for this reason and this path was not,
    which is why the two now share one function.

    The descent is measured from where the ascent actually stopped rather than
    from the bound, so truncation cannot walk the band into a 12-bit wrap --
    Goattracker masks the width to `$FFF` (gplay.c:891) where the player clamps.
    """
    lo_v, hi_v = low << 8, high << 8
    # Clamped to the top only. A record's width may legitimately sit *below* the
    # low bound -- Trans-Atlantic's GT 1 opens on $880 with bounds $D00/$F00 --
    # and the player does not clamp it: it sweeps up from there until a bound
    # turns it, so its band is $880-$F40 rather than the $D00-$F00 the bounds
    # alone describe. Clamping up into the band cost that instrument two thirds
    # of its travel and left the first version of this fix changing nothing.
    width = min(width, hi_v)
    entries = [((0x80 | (width >> 8)) & 0xFF, width & 0xFF)]
    first = (hi_v - width) // speed
    if first:
        entries += [(t, speed) for t in _split_ticks(first)]
    ticks = _split_ticks(max(1, (width + first * speed - lo_v) // speed))
    loop = len(entries)
    entries += [(t, (0x100 - speed) & 0xFF) for t in ticks]
    entries += [(t, speed) for t in ticks]
    return entries, loop


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
    width = ((data[base + 1] & 0x0F) << 8) | data[base]
    return _pulse_triangle(width, low, high, speed)


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
    width = ((data[rec + 1] & 0x0F) << 8) | data[rec]
    return _pulse_triangle(width, det.pulse_tri_lo, det.pulse_tri_hi, speed)


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


def _filter_step_per_call(step: int, multiplier: int) -> int:
    """The player's per-FRAME cutoff step as a per-CALL one, signed.

    The filter table's right side is "speed, signed 8-bit" and Goattracker
    applies it once per play CALL (readme 3.4.3); the player adds its record
    byte once per FRAME. They coincide only at `-S1`, and above it the sweep
    runs `multiplier` times too far -- ACE II's original steps the cutoff by
    768 a frame and ours stepped 2304, which is 768x3 at its `-S3`, measured
    as `cut` 2.39x over 30 s.

    This is the rule CLAUDE.md already states -- a rate read out of the player
    is per frame and every table applies it per call -- and the list of
    emitters that obey it (`build_speed_table`, `_drum_speed`,
    `_rise_speed_index`, `_wave_hold_byte`, the pulse programs,
    `_wave_program_entries`) did not include this one.

    Rounded to NEAREST rather than truncated, and floored at a magnitude of 1
    so a sweep never becomes static: `3 // 4` is 0, and a filter that stops
    moving is a worse error than one moving slightly too fast, because it is
    inaudible as a sweep at all rather than merely mistimed.
    """
    if not step:
        return 0
    signed = step - 256 if step >= 0x80 else step
    scaled = round(signed / multiplier)
    if scaled == 0:                       # never round a live sweep to nothing
        scaled = 1 if signed > 0 else -1
    scaled = max(-128, min(127, scaled))
    return scaled & 0xFF


def _filter_entries(sid: SidFile, det: Detection, instr_used: int,
                    lead: int = 1, multiplier: int = 1):
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
        per_call = _filter_step_per_call(step, multiplier)
        if per_call:
            block.append((FILT_MODULATE, per_call))
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
              wave_program: bool = False,
              vibrato_command: bool = False,
              cut_release: bool = False,
              pitch_seq: bool = False,
              note_rows: Optional[dict] = None,
              row_calls: int = 0,
              voice_two_stage: bool = False,
              instr_voices: Optional[dict] = None,
              gate_skip: Optional[int] = None,
              wide_hard_restart: bool = False,
              max_hard_restart: bool = False,
              real_firstwave_instruments: tuple = ()) -> bytes:
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
                                                      lead, multiplier)
    else:
        filter_entries, filter_ptrs = [], {}
    pulse_entries, pulse_starts = _pulse_layout(sid, det, instr_used, pulse,
                                                multiplier, log, lead=lead)
    # Before the records, because each one carries its speed-table index -- and
    # into `table`, which the wavetable also grows and the file writes last.
    vib_ptrs = _vibrato_layout(sid, det, instr_used, vibrato, fmt, multiplier,
                               table, log, lead=lead,
                               vibrato_command=vibrato_command,
                               row_calls=row_calls)
    # After the layout because it needs the speed-table indices it allocated,
    # and before the records because it decides what goes in their byte 5.
    # Triangle-dialect only: it is that player's length gate this expresses,
    # and the other two engines have no gate to express (_vibrato_delay).
    if vibrato_command and vib_ptrs and det.triangle_vibrato is not None:
        vib_ptrs = _vibrato_command_pass(det, patterns, vib_ptrs, lead, log)
    # Before the records, because each one carries the wavetable step it
    # starts on -- and those starts are no longer a stride.
    wave_entries, wave_starts = _wavetable_layout(sid, det, instr_used, effects,
                                                  fmt, table, multiplier,
                                                  min_notes, lead, two_stage,
                                                  sfx_drum, wave_program,
                                                  pitch_seq,
                                                  note_rows, row_calls,
                                                  no_test_restart,
                                                  voice_two_stage,
                                                  instr_voices, gate_skip,
                                                  real_firstwave_instruments)
    _write_instruments(out, sid, det, instr_used, pulse_starts,
                       sustain_exact, no_hard_restart, filter_ptrs, vib_ptrs,
                       cut_release=cut_release,
                       lead=lead, wave_starts=wave_starts,
                       no_test_restart=no_test_restart,
                       multiplier=multiplier, row_calls=row_calls,
                       wide_hard_restart=wide_hard_restart,
                       max_hard_restart=max_hard_restart,
                       real_firstwave_instruments=real_firstwave_instruments)
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
