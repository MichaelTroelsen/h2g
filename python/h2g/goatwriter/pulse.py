"""Pulse programs, the triangle walk, phase sims and the pulse-table layout (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import re
from dataclasses import (dataclass)
from fractions import (Fraction)
from typing import (List, Optional, Set, Tuple)

from ..detect import (Detection, pulse_tri_offset, _TRI_COUNTER, _TRI_DIR,
                      _TRI_IDX)
from ..search import (search_file)
from ..sidfile import (SidFile)
from .constants import (GT_FIRST_NOTE, GT_LAST_NOTE, GT_MAX_PULSE_SPEED,
                        GT_MAX_PULSE_TICKS, GT_REST, _PACK_FIRSTNOTE, _PACK_FX,
                        _PACK_FXONLY, PACKED_PATTERN_LIMIT, PULSE_RESEED_GATE,
                        SPEED_GATE, SPEED_GATE_IMM, _TRI_INSTR_CELL)
from .instruments import (_table_length_byte)
from .tempo import (outer_gate_skip, SongSpeeds)
from . import constants as _gw_constants
from . import tempo as _gw_tempo
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

    **This function has no note-to-note memory, and that is a real
    approximation for `_pulse_tri_program`'s callers.** Every entries list it
    returns starts a fresh sweep from `width`; nothing here carries a phase
    between two notes that reuse the same record. That matches Goattracker,
    which reloads the pulse pointer at every note trigger (gplay.c:375-379),
    but not the player, whose 12-bit accumulator free-runs across notes and
    is never reseeded. So the RATE this function encodes carries over
    correctly and the BAND does not, whenever notes are short against the
    sweep period -- measured on 5_Title_Tunes, our per-voice band comes out
    449/771/899 against the player's 1536/1536/1408, and voice 2 proves the
    mechanism exactly: 186 notes, 186 reset jumps of 899, and a band of 899,
    all the same number (`_pulse_tri_program`'s docstring has the full
    measurement and why the fix is declined; corrected there at v0.5.379
    after standing as the opposite claim for 45 versions). One residual is
    still open: per-note excursion is not exactly gap x speed (predicted
    256/512/1024 against the 449/771/899 measured), so the turn-around
    arithmetic is unaccounted for.
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


def _pulse_triangle_wrapped(width: int, low: int, high: int,
                            speed: int) -> tuple[List[tuple], int]:
    """`_pulse_triangle` for a bounds byte whose high nibble is <= its low one.

    Same shape, same opening at the record's own width, same loop back to the
    descent -- but every distance is taken modulo $1000, because that is what
    the player does. Its sweep never clamps and never compares magnitudes: it
    adds or subtracts the rate into a 12-bit accumulator (`ADC #$00 / AND
    #$0F` on the high byte) and flips direction when the high nibble EQUALS
    the bound it is heading for. So with `high` below `low` the ascent from
    the seed runs up through $Fxx, wraps to $0xx, and continues until the
    nibble reads `high`; the descent then runs back down through the wrap
    until it reads `low`. Goattracker's pulse arithmetic wraps the same way
    -- `cptr->pulse &= 0xfff` in gplay.c:893/899, and the packed player
    carries into a high byte the SID only reads four bits of -- so a leg that
    crosses $FFF needs no special encoding, only the right tick count.

    Measured on Kings of the Beach ingame, instrument 4 (rate $84, bounds $02,
    seed $080, all three voices): the original climbs $080 -> $FF8 in 30
    frames of +132 and wraps to $07C; a note there never lasts longer, so the
    first leg is the whole audible sweep. At -S3 that is 90 calls of +44.

    Two approximations, both stated:

    * `high == low` is a band of one nibble: the player reaches it and then
      alternates one step down, one step up, forever. The modular descent
      distance is then ~0 and `max(1, ...)` gives exactly that one-tick
      jitter -- except when the ascent ended just past a wrap, where the
      player's first descent runs a full $1000 before settling into the
      jitter, and this leg does not. Nine corpus records read `$00`, all on
      instrument 18 or above.
    * As in `_pulse_triangle`, each leg turns a fraction of a step early
      rather than a fraction late.
    """
    lo_v, hi_v = low << 8, high << 8
    entries = [((0x80 | (width >> 8)) & 0xFF, width & 0xFF)]
    first = ((hi_v - width) & 0xFFF) // speed
    if first:
        entries += [(t, speed) for t in _split_ticks(first)]
    top = (width + first * speed) & 0xFFF
    ticks = _split_ticks(max(1, ((top - lo_v) & 0xFFF) // speed))
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
    # rate 0 is the player's own "do not sweep", and keeps the static width.
    if rate == 0:
        return static, None
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / multiplier)))
    width = ((data[base + 1] & 0x0F) << 8) | data[base]
    # high <= low used to keep the static width too, on the reasoning that it
    # "leaves no band to travel". It does not: the player only ever tests the
    # high nibble for EQUALITY with a bound after the step (`ADC #$00 / AND
    # #$0F / CMP #high`, Kings of the Beach $928D-$9294), so a band whose top
    # is below its bottom is a band that crosses $FFF. Kings of the Beach
    # ingame's instrument 4 is the measured case -- rate $84, bounds $02, seed
    # $080 -- and siddump shows every note climbing $080, $104, ... $FF8 and
    # wrapping to $07C, 30 steps of +132 on all three voices, where this
    # branch had it frozen at $080: 1 pulse change per voice against the
    # original's 342. 25 corpus records have this shape, on 15 files.
    if high <= low:
        return _pulse_triangle_wrapped(width, low, high, speed)
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
    routine, stepped by `rate & $E0` every `(rate & $1F) + 1` TICKS -- a tick
    is a call past the outer gate, see `_tri_speed` for why that is not a
    frame on Game_Killer, Ninja, Samantha_Fox or Spellbound. 24 corpus
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
      an instrument is triggered (gplay.c:375-379, player.s:859-866). So the
      original's phase at any given note is arbitrary and ours is always the
      record's own width. The RATE carries over. **THE BAND DOES NOT** --
      this line said it did until v0.5.379, and it is the sentence that would
      stop the next reader looking. Measured on 5_Title_Tunes at `-t 60`: our
      per-voice band is 449 / 771 / 899 against the original's 1536 / 1536 /
      1408, where the bounds here describe 1536. Voice 2 proves the mechanism
      with three identical numbers -- 186 notes, 186 reset jumps of 899, and a
      band of 899. Our sweep climbs part of the way up and is snapped back to
      the record's width at the next note; the player keeps climbing. Crossing
      the band at speed 32 needs 48 frames and this file's notes are 8 and 16
      frames long, so we can only ever cover a fraction of it.

      **It is fixable in principle and not worth fixing, which is why this
      stays an approximation.** An instrument whose pulse pointer is 0 leaves
      the channel pointer AND the step timer untouched, so a program started
      once free-runs exactly as the player's accumulator does (player.s:859-866
      `lda mt_inspulseptr-1,y / beq mt_skippulse`, its own comment "if
      nonzero"; gplay.c:375-379 guards the same block with `if
      (iptr->ptr[PTBL])`). `_pulse_layout` already uses pointer 0 as its
      table-overflow fallback. Two things stop it being a general repair.
      Goattracker's pulse state is per CHANNEL where the player's accumulator
      is per RECORD and shared across voices, so the two are equivalent only
      where ONE sweeping instrument owns a voice; and one instrument per record
      means pointer 0 alone never STARTS the program, so it needs a
      starter/continuer pair costing two slots against a ceiling this writer
      already drops instruments past. Censused over the whole corpus at
      v0.5.378: **2 of 72 voices** across the 24 files carrying this engine
      qualify -- 5_Title_Tunes voice 2 and Human_Race voice 0 -- holding 2881
      of the engine population's 67619 original pulse-width changes, 4.26% of
      it and 0.76% of the corpus. Every other voice either plays two or more
      instruments (each owning its own table, so the pointer resets regardless)
      or is dominated by an instrument that does not sweep. Same family as the
      effect-bit-`$10` case in CLAUDE.md, where a globally-counted mechanism
      could not go in a per-note table and the honest answer was to say so.
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
    step, delay = _tri_step_delay(det, data[rec + 6])
    if step == 0:                    # rate 0, or a rate that is delay-only
        return None
    speed = _tri_speed(step, delay, multiplier, outer_gate_skip(sid))
    width = ((data[rec + 1] & 0x0F) << 8) | data[rec]
    return _pulse_triangle(width, det.pulse_tri_lo, det.pulse_tri_hi, speed)


def _tri_speed(step: int, delay: int, multiplier: int,
               gate_skip: Optional[int]) -> int:
    """The GT pulse speed (per CALL) of a triangle sweep stepping `step`
    every `delay` of the original's TICKS -- shared by `_pulse_tri_program`
    and `_phase_sweep_params`, so a note with no CMD_SETPULSEPTR sweeps at
    the rate of one that has one.

    **A tick is a play call that passes the player's outer gate, not a
    frame**, and our calls per tick are `multiplier * (O + 1) / O` where the
    player has an outer counter of reload O (`outer_gate_skip`), plain
    `multiplier` where it has none. This used to divide by `multiplier`
    alone, on the strength of convert.py's v0.5.460 "THE SWEEP STEPS PER
    FRAME" bullet; that is right only for a player with no outer gate, and
    the same ratio `_gate_calls` already applies to every wavetable
    duration (convert.py: "the row correction and the table correction are
    the same ratio applied to different quantities") had never reached the
    pulse table.

    Measured (forced A/B, presets, packed and traced at -m{multiplier}
    against the original at -m1, 120 s, width travel per frame inside a
    sweep leg, turn frames excluded): Game_Killer (-S9, O=9) original
    200.3, /9 225.0, /10 198.0; Ninja (-S1, O=3) original 94.5, /1 127.0,
    /(4/3) 96.0; Samantha_Fox_Strip_Poker (-S4, O=4) original 25.1, /4 32.0,
    /5 24.0. Spellbound (-S5, O=10) holds one frame in 11, the gate's
    signature. The control, One_Man_and_his_Droid (-S2, no outer gate):
    original 218.4, /2 224.0, undivided 254.0 -- so the division itself
    stays, only its clock changes. Undivided, Game_Killer's speed clamps at
    127 a call against the original's ~22.

    **WHAT THIS EXPOSES, NOT FIXES: the audible leg is a separate defect.**
    `_pulse_triangle` turns on the bound itself, while the player turns on
    the first lattice point whose high nibble EQUALS the bound -- Game_Killer
    sweeps 8E0..E20 (1344 a leg) where our table spans ~1500. At /9 the two
    errors cancelled (leg 6.81 frames against the original's 6.62); at /10
    the rate is right and the leg reads 7.33. A probe giving the legs the
    player's lattice span on top of this divisor put Game_Killer at 6.82,
    Ninja at 15 (original 14.66, /1 shipped 12) and One_Man at 6.0 (6.1,
    shipped 6.58). Rasputin's gate is not read at all: its R comes from
    the track's `$FE nn` (`outer_gate_skip` returns None), so it keeps
    `multiplier` -- shipped 128 a frame against the original's 101.

    **So the `pul` COUNT overshoots by (O+1)/O by construction, and that is
    not a pulse defect.** The gate skips the WHOLE play routine one frame in
    O+1 (Samantha Fox `$7006 DEC $EA / BPL / LDA #$04 / STA $EA / RTS`), so
    the original's width holds on that frame and moves O frames in O+1 by
    a full step; this speed spreads the same travel over every call, the
    way the GT tempo already spreads the gated ticks (5 calls a tick at
    `-S4`). Measured at 81da71d (presets, 92 s window, subtune 9, frames
    paired at the harness's startup lag): Samantha Fox's pulse changes are
    3509/3509/3676 against ours 4385/4384/4594 (x1.250); EVERY frame where
    ours moves and the original does not -- 876/876/918, exactly the
    excess -- falls on one frame phase mod 5, the gate's, and none on a
    note-fetch frame; the original never moves where ours holds. Spellbound
    (O=10) reads x1.094 the same way, its excess on one phase mod 11. The
    fetch frame is NOT the cause: the player opens the note on the record's
    exact width and steps from the next frame, our set entry plus one
    call's speed does the same, and both sides count that frame once.
    Copying the hold would need the note's tick phase mod O per note (four
    variants of every sweeping record's table at O=4) to reproduce a stutter
    the tempo deliberately evens out everywhere else; read `pspan` and the
    per-frame travel instead. `tests/test_pulse_tri_gate_hold.py` pins it.
    """
    if not gate_skip:
        return min(GT_MAX_PULSE_SPEED,
                   max(1, round(step / (delay * max(1, multiplier)))))
    calls = Fraction(max(1, multiplier) * (gate_skip + 1), gate_skip)
    return min(GT_MAX_PULSE_SPEED, max(1, round(step / (delay * calls))))


def _tri_step_delay(det: Detection, rate: int) -> tuple[int, int]:
    """(step, frames between steps) of a triangle rate byte, in the file's
    own MASK DIALECT: `rate & $E0` every `(rate & $1F) + 1` frames in the
    absolute-address player (Commando), `rate & $F0` every `(rate & $0F) + 1`
    in the zero-page per-voice one (Samantha Fox, Spellbound). Detection
    reads the masks off the routine (`Detection.pulse_tri_step_mask`); every
    reader of the rate byte goes through here, so none can keep the other
    dialect's split."""
    return (rate & det.pulse_tri_step_mask,
            (rate & det.pulse_tri_delay_mask) + 1)


# REFUTED as a remaining defect (measured on the uncommitted tree after
# 1dde44a, Knucklebusters under presets.json): "prefer dropping a program's
# SWEEP while keeping its set over dropping a later program whole". The
# static fallback below plus `_pulse_layout`'s usage pass with its static-pair
# reservation already do exactly that. The table is 255/255; GT26 (record 25,
# 8 notes sounded, all in subtune 2) keeps its set at pointer 249 and loses
# only its sweep; the one record at pointer 0 is GT29, which sounds nothing.
# GT26's block is 7 entries + its jump, and the played records ahead of it in
# usage order end at entry 248 -- one short -- so no reordering among played
# records buys the sweep, and evicting GT27's unplayed sweep (placed after
# GT26 had already failed) frees nothing GT26 could use. What would buy it is
# a cheaper encoding: GT26's loop body (entries 3-6) is GT14's entry for
# entry, so a jump into GT14's loop costs 4 entries, not 8 -- which
# `_lay_out_pulse` now does (loop-tail sharing, below), so GT26 keeps its
# sweep and the static-fallback description in this paragraph is historical.
# The usage pass was not what saved GT26's set on this file: with it removed the bytes
# move but GT26 is still the one played record short of its sweep and GT29
# the one at pointer 0 -- the static fallback is. Pinned by
# tests/test_pulse_layout_knucklebusters.py.
def _lay_out_pulse(programs: List[tuple], statics: List[List[tuple]],
                   lead: int, share: bool,
                   order: Optional[List[int]] = None,
                   reserve_for: Optional[Set[int]] = None
                   ) -> tuple[List[tuple], List[int], int, int, int]:
    """One pass over the records' programs into a table of GT_MAX_TABLELEN.

    Returns (entries, starts, dropped, silent, shared). With `share`, a
    program identical to one already in the table -- same entries, same
    loop index -- is not written again: its record points at the block that
    is already there. A block whose LOOP BODY is already in the table (same
    entries after its loop index, whatever precedes them) is written as its
    own prefix plus `(0xFF, <that body's absolute index>)`, or not at all
    when the prefix is empty -- the body's closing jump already returns to
    the body's own start, so the sound is the same and the cost is the
    prefix and one entry. Only with `share`, so a table that fits unshared is
    byte-for-byte what it always was; a block that fell back to its static
    pair registers no body. The block's `(0xFF, start + loop)` jump encodes an
    ABSOLUTE table index, so a block is emitted once at one start and every
    sharer names that start; the key is (entries, loop), not the finished
    block, because the finished block differs by the start it was written at.

    `order` is the sequence of record indices to allocate in, defaulting to
    index order. Whatever the order, `starts` is by record index: it is the
    ALLOCATION that is reordered, never which record owns which pointer.

    `reserve_for` names the records that must at least get their static
    pair: a sweep block is placed only if the table left after it still
    holds two entries for every such record not yet allocated (distinct
    statics, since identical ones share), so a record that is played can
    lose its sweep to the records ahead of it but never its width.
    """
    entries: List[tuple] = [(0x80, 0x00), (0xFF, 0x00)]
    by_rec = [0] * len(programs)
    placed: dict = {}                  # (program, loop) -> 1-based start
    bodies: dict = {}                  # loop body -> 1-based index of its first entry
    dropped = silent = shared = 0
    order = list(range(len(programs))) if order is None else list(order)
    for n, i in enumerate(order):
        (program, loop), static = programs[i], statics[i]
        key = (tuple(program), loop)
        if share and key in placed:
            by_rec[i] = placed[key]
            shared += 1
            continue
        start = len(entries) + 1
        block = program if loop is None else program + [(0xFF, start + loop)]
        tail_shared = False
        if share and loop is not None:
            body = tuple(program[loop:])
            at = bodies.get(body)
            if at is not None:
                # The loop body is already in the table: write only this
                # block's own prefix, then jump into that body. The body's
                # own closing jump returns to ITS start, which is the same
                # place this block's loop would have returned to.
                if loop == 0:            # nothing before the body: point at it
                    by_rec[i] = at
                    placed[key] = at
                    shared += 1
                    continue
                block = program[:loop] + [(0xFF, at)]
                tail_shared = True
        reserve = 0
        if reserve_for:
            pending = {tuple(statics[j]) for j in order[n + 1:]
                       if j in reserve_for
                       and (tuple(programs[j][0]), programs[j][1]) not in placed
                       and (tuple(statics[j]), None) not in placed}
            reserve = 2 * len(pending)
        if len(entries) + len(block) + reserve > _gw_constants.GT_MAX_TABLELEN:
            # Out of table: keep the instrument, lose only its movement.
            dropped += 1
            key = (tuple(static), None)
            if share and key in placed:
                by_rec[i] = placed[key]
                shared += 1
                continue
            block = static
            tail_shared = False
        if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
            # Not even the static pair fits. Pointer 0 leaves the pulse width
            # alone (readme.txt:714) -- the record must still get one, or every
            # instrument after it reads another instrument's program.
            by_rec[i] = 0
            silent += 1
            continue
        placed[key] = start
        by_rec[i] = start
        if tail_shared:
            shared += 1
        elif loop is not None and block is not static:
            bodies.setdefault(tuple(program[loop:]), start + loop)
        entries += block
    # The empty Clear Voice, if present, keeps entry 1.
    return entries, [1] * lead + by_rec, dropped, silent, shared


def pulse_usage(tracks: List[List[int]], patterns: List[List[int]],
                lead: int) -> List[int]:
    """Note rows each instrument record SOUNDS, walked in play order -- one
    count per record index, orderlist repeats honoured.

    The quantity is sounding, not naming: every new note reloads the channel's
    pulse pointer from whatever instrument the channel currently holds
    (gplay.c:375-377, player.s:859-866), `instr 00` keeps that instrument
    (gplay.c:914), and a channel holds instrument 1 before any row names one
    (gplay.c:62, gplay.c:223, player.s:619-621) -- so under `compact_instruments`
    record 0 sounds unnamed. The walk is `fixed_arp_phases`'s. A record that
    reads 0 here never has its pointer loaded, so whatever the pulse table
    holds for it is inaudible.
    """
    counts: dict = {}
    for track in tracks:
        current, repeat, operand = 1, 1, False
        for b in track:
            if operand:                  # $FF's restart position
                operand = False
                continue
            if b == 0xFF:                # patterns.GT_ORDER_RESTART
                operand = True
                continue
            if 0xE0 <= b < 0xFF:         # a transpose, no row of its own
                continue
            if 0xD0 <= b < 0xE0:         # patterns.GT_REPEAT: the NEXT entry
                repeat = b - 0xD0 + 1
                continue
            if b >= len(patterns):
                continue
            pat = patterns[b]
            for _ in range(repeat):
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:   # ENDPATT, patterns.GT_END_PATTERN
                        break
                    if pat[r + 1]:
                        current = pat[r + 1]
                    if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                        rec = current - lead - 1
                        counts[rec] = counts.get(rec, 0) + 1
            repeat = 1
    n = max((k for k in counts if k >= 0), default=-1) + 1
    return [counts.get(i, 0) for i in range(n)]


def _pulse_layout(sid: SidFile, det: Detection, instr_used: int,
                  pulse: bool, multiplier: int,
                  log=None, lead: int = 1,
                  usage: Optional[List[int]] = None
                  ) -> tuple[List[tuple], List[int]]:
    """The whole pulse table, plus each instrument's 1-based start entry.

    Entries were a fixed two per instrument until the sweep gave some of them
    four or more, so the start positions are returned rather than computed from
    a stride -- `_write_instruments` writes them into the records.

    One block per record, as always, while every record's own block fits.
    When one does not, the table is laid out again with identical programs
    SHARED -- a record whose (entries, loop) another record already placed
    points at that block instead of getting a second copy -- and only then
    does a record lose its sweep to the static pair. Sharing is a rescue and
    keeps the rescue's ordering: it never touches a file whose table was
    already whole, because an unshared block that fits is exactly what the
    fixture and every measured conversion encode.

    When sharing still leaves a record short, a third and last pass
    allocates in DESCENDING `usage` (`pulse_usage`: note rows the record
    sounds, walked in play order; ties keep index order) with a static pair
    reserved for every record that sounds at all, so what the table cannot
    hold is lost by the records the song plays least -- and a record that
    sounds nothing may lose even its width, which nothing can hear -- rather
    than by whichever records happen to sit at the end of the instrument
    table. Measured at v0.5.486, once sharing had landed: the corpus's one
    record left with no width at all (Knucklebusters GT29) sounded zero
    notes, so the SILENT branch was no longer an audible loss; the STATIC
    fallback still was, since Rock_Tells_the_Tale dropped GT16's sweep
    (sounding 352 notes) while keeping GT3's (sounding 1). Descending usage
    ALONE, without the reservation, silenced three of Rock's played records
    (GT11, GT13, GT14) to buy GT16 its sweep -- the reservation is what
    makes the order safe. Without `usage` -- the tests' bare calls -- the
    two index-order passes stand exactly as they were.
    """
    nrec = max(instr_used - lead, 0)
    programs = [_pulse_program(sid, det, i, pulse, multiplier)
                for i in range(nrec)]
    statics = [_pulse_program(sid, det, i, False, multiplier)[0]
               for i in range(nrec)]
    entries, starts, dropped, silent, shared = _lay_out_pulse(
        programs, statics, lead, share=False)
    if dropped:
        entries, starts, dropped, silent, shared = _lay_out_pulse(
            programs, statics, lead, share=True)
    unheard = 0
    if dropped and usage is not None:
        use = [usage[i] if i < len(usage) else 0 for i in range(nrec)]
        order = sorted(range(nrec), key=lambda i: -use[i])  # stable on ties
        entries, starts, dropped, silent, shared = _lay_out_pulse(
            programs, statics, lead, share=True, order=order,
            reserve_for={i for i in range(nrec) if use[i]})
        unheard = sum(1 for u in use if u == 0)
    if log and shared:
        log(f"*** PULSE TABLE FULL -- {shared} INSTRUMENT(S) SHARE A BLOCK "
            f"IDENTICAL TO AN EARLIER ONE, OR TO ITS LOOP ***")
    if log and dropped:
        # `dropped` also counts the records that then lost even the static
        # pair (`silent`, always a subset of it); only the rest kept a width.
        log(f"*** PULSE TABLE FULL -- {dropped - silent} INSTRUMENT(S) KEEP A STATIC "
            f"WIDTH INSTEAD OF THEIR SWEEP"
            + (f", {silent} SET NO WIDTH AT ALL ***" if silent else " ***"))
        if usage is not None:
            log(f"*** PULSE TABLE FULL -- ALLOCATED BY NOTES SOUNDED, "
                f"{unheard} INSTRUMENT(S) SOUND NONE ***")
    return entries, starts


# --------------------------------------------------------------------------
# Pulse PHASE: which duty cycle a note OPENS on.
#
# The triangle engine's accumulator free-runs: it lives in the instrument
# record's own width bytes, is stepped every `delay` TICKS of the original
# (play calls past its outer gate) while the record sounds, in the direction
# the sounding VOICE's cell holds, turns where the high nibble reaches a
# bound, and is never reseeded at a note -- so the original's notes open all
# over the sweep, while
# Goattracker reloads the pulse pointer from the instrument and opens every
# note on the record's width. `pspan` reads 5_Title_Tunes at 0.47x and
# `pphase` at 0.25x for exactly this.
#
# The model below was validated against the original's own trace before any
# of this was built: it predicts 848 of 848 note-onset widths on all three of
# 5_Title_Tunes' sweeping voices exactly, and 96.9% of all 6000 traced frames
# once the initial state is known. Two details are load-bearing and both were
# read out of the trace rather than assumed: THE SWEEP DOES NOT RUN ON THE
# NOTE-FETCH CALL (the width holds three frames around an attack against the
# delay's two everywhere else), and THE REFLECTION STORES THE AT-BOUND VALUE
# (the store-at-bound simulation matches 96.9% of frames; the skip-at-bound
# reading of the 6502 -- whose top-bound exit is a JMP with two bytes left on
# the stack -- matches 9.5%, so the observable behaviour wins over the
# disassembly).
#
# The repair is CMD_SETPULSEPTR on the note row: the phase is deterministic,
# so it is computed at emit time by walking the orderlist (patterns.
# collect/apply, which own the clone discipline), and the pulse table gains
# one ENTRY POINT per distinct (width, direction) a note opens on -- a set,
# a ramp to the bound, and a jump into a shared alternating loop. Tick 0
# commands run AFTER the new-note init (player.s:903-906), so the command
# beats the instrument's own pointer load.
#
# **The command has a packed cost, and it is what refused Rasputin at -S2.**
# greloc.c's `packpattern()` charges two bytes for every row whose command or
# data differs from the row before, and returns -1 past 256 bytes a pattern
# ("PATTERN xx IS TOO COMPLEX", to a console nobody sees). CMD_SETPULSEPTR on
# nearly every note row of a 127-row pattern is 105 changes on top of the
# notes: four of Rasputin's expanded patterns pack to 264-270 (v0.5.480),
# confirmed by stripping the command from only those four and packing. The
# `multiplier == 1` gate in convert.py kept it off that file until the gate
# was lifted; what keeps the file packing now is `budget_pulse_phase_commands`
# below, run LAST in `build_sng` on the finished rows -- the arithmetic is
# `packed_pattern_size`, with `tests/test_table_validation.packed_pattern_size`
# as its second reader -- dropping, first-fit, the commands that would take a
# pattern across the limit.
# --------------------------------------------------------------------------

class PulseVoiceCell:
    """The triangle sweep's per-VOICE state: its direction (+1 up, -1 down)
    and its delay counter. The player keeps both in `dir,X` / `counter,X`
    (detect._TRI_DIR / _TRI_COUNTER) while the width lives in the record, so
    every record one voice sweeps shares one of these -- see PulsePhaseSim."""

    __slots__ = ("direction", "counter")

    def __init__(self, direction: int = +1, counter: int = 0) -> None:
        self.direction, self.counter = direction, counter


class PulsePhaseSim:
    """The triangle accumulator, exactly as validated against the trace.

    One per sweeping record. `advance(ticks, skip_first)` runs the sweep for
    that many ORIGINAL TICKS -- `skip_first` on the tick that fetches a note,
    which the player spends in the fetch rather than the sweep. `phase()` is
    the (width, direction) a note starting NOW opens on.

    **Width per RECORD, direction and delay counter per VOICE.** The routine
    adds to `record+0/+1,Y` but turns on `dir,X` and counts on
    `counter,X` (One_Man `$1265`/`$150A,X`/`$1507,X`, Game_Killer
    `$0A6B`/`$0C78,X`/`$0C75,X`, Rasputin `$C293`/`$C530,X`/`$C52D,X`), so
    the two per-voice cells live in a `PulseVoiceCell` that every record a
    voice sweeps shares: a record entered after another on the same voice
    continues in that voice's direction and mid-count. `cell` binds one; the
    default is a private cell starting up at a zero count, the state the
    model had before the cells were read. `patterns.collect_pulse_phases`
    binds each voice's records to one cell seeded from the file image
    (`triangle_start`).

    **THE CLOCK IS THE ORIGINAL'S TICK, not a play call and not a frame**
    (read at 1dde44a off the three multispeed carriers' disassembly, then
    measured): a tick is a play call that passes the player's OUTER gate,
    and a row is `SongSpeeds.frames_for` ticks whatever our tempo or
    multiplier. One_Man has no outer gate (2 calls a tick at `-S2`, tempo
    4); Game_Killer's `$0826 DEC $0C8C / BPL / LDA #$09 / STA $0C8C / RTS`
    skips one frame in ten (10 calls a tick at `-S9`, tempo 20); Rasputin's
    `$C012 DEC $C53A / BPL / LDA $C539 / STA $C53A / JMP $C3C5` skips by an
    `R` its orderlist's `$FE nn` moves mid-song (3 calls a tick at `-S2`,
    tempo 6). RETRACTED: "Units are PLAYER CALLS throughout, which is what
    makes the model multiplier-free: the original steps its sweep once per
    play call whatever the call rate" -- true only where a call is a tick,
    which is the `-S1` files with no outer gate this sim was validated on
    (5_Title_Tunes). Paired by note against the originals' traces, exact
    width at the attack frame, shipped model -> tick clock with voice cells:
    Game_Killer 245/563 -> 563/563, Rasputin and One_Man_and_his_Droid as
    `tests/test_pulse_phase.py` pins them. (The GT-side table speed is a
    separate question and keeps `_pulse_tri_program`'s formula.)

    **RETRACTED as a measurement (04fdcb5 + the uncommitted tree):** "On
    Game_Killer (`-S9`) the walk's planned onset buckets agree with the
    original's 63% / 61% over the first 100 / 200 sweeping notes on the CALL
    clock against 19% / 21% on the frame clock". That pairing slipped one
    note; paired by note the plan reads 0.135 (calls) and 0.215 (frames) at
    the attack, chance ~0.14, so the call clock is the walk's default, not a
    finding, and "the `DEC counter,X / BPL` sits inside the multispeed core"
    is unsupported. The plan does reach the packed output (200/200 notes on
    their planned width plus the frame's ramp ticks): the loss was in this
    sim's model, not in the table -- the call clock and a direction cloned
    into each record, the two things the tick clock and `PulseVoiceCell`
    replace. On those first 200 notes the plan now opens on the original's
    exact width 200 times
    (`tests/test_pulse_phase.py::test_game_killers_plan_opens_on_the_originals_width_on_the_tick_clock`,
    and `::test_game_killers_planned_phases_reach_the_packed_output`).
    `PulseBoundsSim` measures the other way (frame clock, Saboteur_II).
    """

    # What `patterns.collect_pulse_phases` asks a sim about itself: whether
    # a note reseeds the accumulator (never, here -- the sweep free-runs
    # across notes) and whether the accumulator is per voice (no -- per
    # record, shared by every voice sounding it, which is the "two voices"
    # decline in the walk). `PulseBoundsSim` answers both the other way.
    RESEEDS = False
    PER_VOICE = False

    def __init__(self, width: int, step: int, delay: int,
                 lo: int, hi: int, cell: Optional[PulseVoiceCell] = None) -> None:
        self.width, self.step, self.delay = width, step, delay
        self.lo, self.hi = lo, hi
        # A private cell unless one is bound: up, and a zero count -- the
        # first active tick fires immediately, since the player's
        # DEC-then-BPL counter goes negative on its first decrement.
        self.cell = cell if cell is not None else PulseVoiceCell()

    @property
    def direction(self) -> int:
        return self.cell.direction

    @direction.setter
    def direction(self, value: int) -> None:
        self.cell.direction = value

    @property
    def _dcnt(self) -> int:
        return self.cell.counter

    @_dcnt.setter
    def _dcnt(self, value: int) -> None:
        self.cell.counter = value

    def phase(self) -> tuple:
        return (self.width, self.direction)

    def advance(self, ticks: int, skip_first: bool = False) -> None:
        cell = self.cell
        for k in range(ticks):
            if skip_first and k == 0:
                continue
            cell.counter -= 1
            if cell.counter >= 0:
                continue
            cell.counter = self.delay - 1
            # The routine's own arithmetic: 12 bits (`ADC #$00 / AND #$0F`
            # on the high byte) and a turn on EQUALITY of the high nibble
            # after the step (`CMP #$0E / BNE`, `CMP #$08 / BNE`). Inside
            # the band that is the magnitude test this sim used to make,
            # since no step reaches $100; outside it the width runs on and
            # wraps. Commando's record 6 ($800, rate $E0) opens note 279 at
            # $800 on a voice whose cell is descending, and the original
            # goes $720, $640, ... round through $FFF where a magnitude test
            # turned it at once.
            if cell.direction > 0:
                self.width = (self.width + self.step) & 0xFFF
                if self.width >> 8 == self.hi:
                    cell.direction = -1
            else:
                self.width = (self.width - self.step) & 0xFFF
                if self.width >> 8 == self.lo:
                    cell.direction = +1

    def clone(self, cell: Optional[PulseVoiceCell] = None) -> "PulsePhaseSim":
        """This record's width, bound to `cell` -- or, without one, to a
        private copy of this sim's own cell."""
        if cell is None:
            cell = PulseVoiceCell(self.cell.direction, self.cell.counter)
        return PulsePhaseSim(self.width, self.step, self.delay, self.lo,
                             self.hi, cell)


class PulseBoundsSim:
    """The per-record-bounds engine's accumulator (`_pulse_program`'s), as
    validated against the trace -- the triangle sim's sibling, for the files
    `pulse_phase_sims` returns nothing on.

    Read out of Saboteur_II's routine ($F297-$F2F0; Food_Feud carries the
    same bytes at $92EF) and then confirmed frame for frame on both ORIGINALS
    at `-t 180` before anything was emitted: every sweep step the trace can
    classify is reproduced (25626/25626 on Saboteur_II, 25298/25298 on
    Food_Feud) and every attack's onset width -- the frame `pphase` reads --
    is predicted (1314/1314 and 1554/1554), the 56 + 29 attacks that do NOT
    reseed included. Three things differ from `PulsePhaseSim`, and the third
    is the one that matters:

    * **One step every call, no delay counter.** The rate byte is the whole
      step (`LDA $F56E / CLC / ADC acc`), where the triangle engine packs a
      step and a frames-between-steps into one byte.
    * **The bounds are the record's own two nibbles, the turn is on EQUALITY
      of the high nibble after the step, and the at-bound value is stored**
      (`PHA` before the `CMP`, `PLA` into `$D403` after). Equality, not
      magnitude, so a band whose top nibble is below its bottom crosses `$FFF`
      -- `_pulse_triangle_wrapped`'s case -- and the 12-bit mask here is the
      routine's `AND #$0F`.
    * **THE ACCUMULATOR IS RESEEDED AT EVERY NOTE WHOSE NOTE BYTE HAS BIT 7
      CLEAR** (`$F162 LDA $F59A / BMI skip`: the note-start path writes the
      record's +0/+1 straight into `$D402/$D403` and zeroes the direction
      cell). Only a bit-7 note free-runs through the accumulator the previous
      note left. That is the opposite of the triangle engine, whose
      accumulator is never reseeded, and it is why the bounds engine's notes
      open on the record width almost everywhere and on a free-running phase
      only at bit-7 notes -- Saboteur_II voice 0's [4, 5, 6, 9] buckets are
      exactly its 56 bit-7 attacks in 180 s, and the other three buckets are
      record widths. `reseed()` is that path; `advance(calls, skip_first)` is
      the sweep with the fetch call skipped, the triangle sim's convention,
      because the fetch path (`$F1A2 ... JMP $F45F`) never reaches the sweep.

    And one more the walk needs, read off the sweep routine itself
    (`$F2AC LDA $F572,X` / `$F2B5 ADC $F59C,X` / `$F2B9 LDA $F59F,X`, X the
    voice from `$F185 LDX $F56B`): **THE ACCUMULATOR IS PER VOICE**, not per
    record. A record sounding on two voices does not share it, so the
    triangle walk's "two voices" decline does not apply, and the state
    carries across an instrument change on one voice. `PER_VOICE` says so.

    **The walk drives this sim through `free_rows`.** The decoder carries
    the note byte's bit 7 out beside `exits_tied` (`_build_raw_pattern`'s
    `free_rows`, per output pattern on `TrackIndex.free_rows`, extended to
    the later passes' copies by `patterns.inherit_free_rows`);
    `patterns.collect_pulse_phases` calls `reseed()` on every note row
    without the bit and plans a `CMD_SETPULSEPTR` only for a row with it;
    convert.py's gate admits `det.pulse_bounds >= 0` and hands the walk
    `pulse_bounds_sims` where `pulse_phase_sims` returns nothing --
    restricted by `pulse_reseed_gated` to the players carrying Saboteur_II's
    own `LDA note / BMI` spelling of the reseed test, the only one the rule
    was validated on. `build_pulse_phase_table` serves the records.
    """

    RESEEDS = True
    PER_VOICE = True

    def __init__(self, width: int, rate: int, lo: int, hi: int) -> None:
        self.seed, self.rate = width, rate
        self.lo, self.hi = lo, hi
        self.width = width
        self.direction = +1

    def phase(self) -> tuple:
        return (self.width, self.direction)

    def reseed(self) -> None:
        """The note-start path: record width, direction up."""
        self.width, self.direction = self.seed, +1

    def advance(self, calls: int, skip_first: bool = False) -> None:
        if self.rate == 0:
            return
        for k in range(calls):
            if skip_first and k == 0:
                continue
            if self.direction > 0:
                self.width = (self.width + self.rate) & 0xFFF
                if (self.width >> 8) == self.hi:
                    self.direction = -1
            else:
                self.width = (self.width - self.rate) & 0xFFF
                if (self.width >> 8) == self.lo:
                    self.direction = +1

    def clone(self) -> "PulseBoundsSim":
        c = PulseBoundsSim(self.seed, self.rate, self.lo, self.hi)
        c.width, c.direction = self.width, self.direction
        return c


def _bounds_record(sid: SidFile, det: Detection, i: int):
    """(seed width, rate, lo nibble, hi nibble) of record `i` under the
    per-record-bounds engine, or None where the record does not sweep or
    the bytes are off the end of the file. `_pulse_program`'s reads, shared
    so the sim and the phase table cannot disagree about a record."""
    if det.pulse_bounds < 0:
        return None
    d = sid.data
    rec = det.instr_start + i * det.instr_stride
    bounds_at = det.pulse_bounds + i * det.instr_stride
    rate_at = rec + det.pulse_rate_field
    if rec + 1 >= len(d) or bounds_at >= len(d) or rate_at >= len(d):
        return None
    rate = d[rate_at]
    if rate == 0:
        return None
    width = ((d[rec + 1] & 0x0F) << 8) | d[rec]
    return width, rate, d[bounds_at] & 0x0F, d[bounds_at] >> 4


def pulse_reseed_gated(sid: SidFile) -> bool:
    """Whether this player reseeds its pulse accumulator behind Saboteur_II's
    `LDA note / BMI` test -- the population `PulseBoundsSim.reseed()` is a
    reading of. convert.py hands the walk the bounds sims only here."""
    return search_file(sid.data, PULSE_RESEED_GATE) > 0


def pulse_bounds_sims(sid: SidFile, det: Detection, lead: int = 1) -> dict:
    """{pattern instrument byte: PulseBoundsSim} for the records that sweep
    under the per-record-bounds engine -- `pulse_phase_sims`'s shape for the
    other engine. Empty where the file does not carry it. A record reader
    only: whether the walk may be handed these at all is
    `pulse_reseed_gated`'s question, asked in convert.py."""
    if det.pulse_bounds < 0:
        return {}
    out: dict = {}
    for i in range(det.instr_used):
        rec = _bounds_record(sid, det, i)
        if rec is None:
            continue
        width, rate, lo, hi = rec
        out[i + 1 + lead] = PulseBoundsSim(width, rate, lo, hi)
    return out


def pulse_phase_sims(sid: SidFile, det: Detection,
                     lead: int = 1) -> dict:
    """{pattern instrument byte: PulsePhaseSim} for the records that sweep.

    The gates are `_pulse_tri_program`'s own: the engine present, the record's
    rate byte carrying a step, and the effect-bit-$08 gate honoured only where
    the player tests it. The instrument byte is the record index plus `lead`,
    the same 1-based numbering `_pulse_layout` writes.
    """
    if det.pulse_tri_hi < 0:
        return {}
    # The zero-page dialect reseeds its per-voice accumulator at every note
    # fetch, so there is no free-running phase for a walk to plan: a pulse
    # program restarting with the note already is the player. PulsePhaseSim
    # models the other dialect (RESEEDS = False, PER_VOICE = False) and
    # would plan commands this player never needs.
    if det.pulse_tri_per_voice:
        return {}
    d = sid.data
    out: dict = {}
    for i in range(det.instr_used):
        rec = det.instr_start + i * det.instr_stride
        if rec + 7 >= len(d):
            break
        if det.pulse_tri_gated and d[rec + 7] & 0x08:
            continue
        step, delay = _tri_step_delay(det, d[rec + 6])
        if step == 0:
            continue
        width = ((d[rec + 1] & 0x0F) << 8) | d[rec]
        # Instrument numbers are 1-based and offset by the layout's lead:
        # record 0 is instrument 1 under --compact-instruments (lead 0) and
        # instrument 2 in the inherited layout (lead 1). _instruments_used
        # documents the convention; getting this wrong points every command
        # at a neighbouring record's table.
        out[i + 1 + lead] = PulsePhaseSim(width, step, delay,
                                          det.pulse_tri_lo, det.pulse_tri_hi)
    return out


@dataclass(frozen=True)
class TriangleStart:
    """The triangle engine's state at the first play call, read off the
    player -- what `patterns.collect_pulse_phases` seeds the walk with.

    * `cells` -- (direction, counter) per voice X from the image's `dir,X`
      and `counter,X` (detect._TRI_DIR / _TRI_COUNTER). Nothing but the
      sweep itself writes either, so every subtune starts from these bytes.
      Game_Killer's `$0C78` reads 01 00 00: its voice 0 starts DOWN, which a
      sim seeded up on every record cannot follow.
    * `instruments` -- the instrument byte (record + 1 + lead) each voice
      sweeps until its first fetch: the cell the sweep's own `LDY idx` is
      filled from (`LDA instr,X / ASL / ASL / ASL / TAY / STY idx`).
    * `counter` -- the image byte of the speed gate's counter, which no init
      writes (only the gate's own reload stores to it), so `prefetch` can
      count the ticks the player sweeps before its first fetch.

    REPLACES `patterns.PULSE_PHASE_PREROLL = 7`, a fit: "seven calls
    reproduces every one of 5_Title_Tunes voice 3's 188 measured onsets".
    Its player's counter reads 3 against a reload of 3, so the first fetch
    is the FOURTH tick and three ticks sweep before it -- seven up from a
    zero count was the mirror image of three down from the image's
    (descending, count 1) on that one voice, and on any other cell state
    the two disagree.
    """
    cells: Tuple[Tuple[int, int], ...]
    instruments: Tuple[int, ...]
    counter: int

    def prefetch(self, frames: int) -> int:
        """Ticks the player sweeps before its first fetch, for a subtune of
        `frames` ticks a row (reload + 1). The gate fetches on the tick its
        counter reads the reload (`LDA counter / CMP reload / BNE`); the
        first DEC starts from the image byte. 5_Title_Tunes: counter 3,
        reload 3 -> 2, 1, 0, then -1 reloads to 3 and fetches: 3."""
        reload, c = frames - 1, self.counter
        for n in range(0x100):
            c = (c - 1) & 0xFF
            if c & 0x80:
                c = reload
            if c == reload:
                return n
        return 0


def _speed_counter(sid: SidFile, speeds: Optional["SongSpeeds"]) -> Optional[int]:
    """The image byte of the speed gate's counter, where it is the whole
    story: the gate `find_song_speeds` read (absolute or immediate reload),
    no store to the counter but the gate's own, and the fetch tested as
    `LDA counter / CMP reload` (or `CMP #imm`) right after it. None
    otherwise -- the zero-page spelling included, which no file the walk
    reaches carries."""
    if speeds is None or speeds.reload_addr < 0:
        return None
    d = sid.data
    for rx, imm in ((SPEED_GATE, False), (SPEED_GATE_IMM, True)):
        for m in rx.finditer(d):
            if m.group(1) != m.group(3):
                continue
            rel = (sid.to_address(m.start() + 6) if imm
                   else m.group(2)[0] | m.group(2)[1] << 8)
            if rel != speeds.reload_addr:
                continue
            ctr = m.group(1)
            if d.count(b"\x8d" + ctr) != 1:
                return None
            tail = d[m.end():m.end() + 32]
            test = (b"\xad" + ctr + b"\xc9" + bytes([d[m.start() + 6]]) if imm
                    else b"\xad" + ctr + b"\xcd" + m.group(2))
            if test not in tail:
                return None
            at = sid.to_offset(ctr[0] | ctr[1] << 8)
            return d[at] if 0 <= at < len(d) else None
    return None


def triangle_start(sid: SidFile, det: Detection,
                   lead: int = 1) -> Optional[TriangleStart]:
    """`TriangleStart` for the triangle engine's player, or None where any
    part of it cannot be read -- and then the walk is not run, since a
    start state guessed is a phase guessed on every note after it."""
    if det.pulse_tri_hi < 0 or det.pulse_tri_per_voice or det.instr_stride != 8:
        return None
    off = pulse_tri_offset(sid, det)
    if off < 3 or sid.data[off + _TRI_IDX - 1] != 0xAC:      # LDY idx
        return None
    d = sid.data

    def word(at: int) -> bytes:
        return bytes(d[at:at + 2])

    def image(addr: int) -> Optional[bytes]:
        at = sid.to_offset(addr)
        return bytes(d[at:at + 3]) if 0 <= at and at + 3 <= len(d) else None

    ctr_op, dir_op = word(off + _TRI_COUNTER), word(off + _TRI_DIR)
    # The premise: no store to either cell but the sweep's own.
    if d.count(b"\x9d" + ctr_op) != 1 or d.count(b"\x9d" + dir_op) != 0:
        return None
    cells = [m.group(1) for m in re.finditer(
        _TRI_INSTR_CELL + re.escape(word(off + _TRI_IDX)), d, re.DOTALL)]
    if len(set(cells)) != 1:
        return None
    ctr = image(ctr_op[0] | ctr_op[1] << 8)
    drn = image(dir_op[0] | dir_op[1] << 8)
    ins = image(cells[0][0] | cells[0][1] << 8)
    counter = _speed_counter(sid, _gw_tempo.find_song_speeds(sid, det))
    if ctr is None or drn is None or ins is None or counter is None:
        return None
    # A counter byte past $80 goes negative on its first DEC, which a signed
    # count reaches by starting below zero.
    return TriangleStart(
        cells=tuple((-1 if drn[x] else +1, c if c <= 0x80 else c - 0x100)
                    for x, c in enumerate(ctr)),
        instruments=tuple(i + 1 + lead for i in ins),
        counter=counter)


def _phase_sweep_params(sid: SidFile, det: Detection, i: int,
                        multiplier: int) -> tuple | None:
    """(width, GT speed, lo_v, hi_v, wrap) of record `i`'s sweep for the
    phase table, whichever engine the file carries, or None where it does not
    sweep. `wrap` says whether distances cross $FFF (the bounds engine) or
    clamp (the triangle engine).

    The two engines reach the same table shape from different record bytes:
    the triangle's step and delay are packed into +6 and its bounds are the
    routine's constants; the bounds engine's rate is the whole
    `pulse_rate_field` byte and its bounds are the record's own nibbles.
    Each speed is the one that engine's static program already emits
    (`_pulse_tri_program`, `_pulse_program`), so a note that gets no command
    sweeps at the same rate as one that does.
    """
    d = sid.data
    if det.pulse_tri_hi >= 0:
        rec = det.instr_start + i * det.instr_stride
        if rec + 7 >= len(d):
            return None
        step, delay = _tri_step_delay(det, d[rec + 6])
        width = ((d[rec + 1] & 0x0F) << 8) | d[rec]
        speed = _tri_speed(step, delay, multiplier, outer_gate_skip(sid))
        return width, speed, det.pulse_tri_lo << 8, det.pulse_tri_hi << 8, False
    rec = _bounds_record(sid, det, i)
    if rec is None:
        return None
    width, rate, lo, hi = rec
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / max(1, multiplier))))
    return width, speed, lo << 8, hi << 8, True


def _phase_block(base: int, num: int, want_set: set, width: int, speed: int,
                 lo_v: int, hi_v: int, wrap: bool,
                 share: bool = False) -> tuple:
    """(rows, phase_index) for one sweeping record whose block opens after
    table row `base`: the alternating loop plus one entry point per phase in
    `want_set`, `phase_index` mapping (num, width, direction) to the 1-based
    row a CMD_SETPULSEPTR names. `width` is the record's own (unused here
    beyond the caller's pointer; kept so the params tuple unpacks whole).

    **Per-phase ramps (`share=False`, the layout every fitting file ships).**
    A down leg and an up leg jump to each other; every phase is a set-width
    row, its own ramp to the bound it is heading for, and a jump into the
    loop -- three rows a phase, more where `_split_ticks` spells a long ramp
    as several. Last_V8's instrument 7 has 42 phases and asked for 130 rows.

    **Shared ramps (`share=True`, `build_pulse_phase_table`'s rescue).** The
    phases a sweep plans sit on its own lattice -- the sim steps the width by
    a whole step, and the four overflowing records' phases are 4 speed steps
    apart -- so every up phase lies ON the up leg and every down phase ON
    the down leg. Each leg is then laid out as one chain: a ramp segment up
    to the next phase width, that phase's set-width row, the next segment.
    A set-width row costs the player one call holding the width it sets
    (gplay.c:874-879 sets and advances with no modulation that call;
    player.s `mt_setpulse` jumps to `mt_nextpulsestep` past `mt_pulsemod`),
    so the segment before it is laid ONE TICK SHORT: arriving at
    `w - speed`, the set row's call takes the width to `w`, exactly the step
    a modulation tick would have taken. The pass-through therefore plays the
    same widths on the same calls as the plain leg, and a note entering at a
    phase's set row plays what its own piece played: set `w`, then the leg
    from `w`. A phase AT the leg's start bound has its set row before the
    leg's head, and the jump from the other leg names the head, so the
    pass-through does not pay that row's held call. Only phases inside
    [lo, hi] on the speed lattice measured from `lo` are chained, and only
    where the band itself is a whole number of steps; any other phase (the
    triangle sim's at-bound value a step PAST the bound, say) keeps its own
    piece, which jumps into the chained legs at their heads as it jumped
    into the plain ones. A row is never a jump's target if it is a jump
    itself (the two players follow one jump per call, gplay.c:865-869 before
    the step and player.s `mt_nextpulsestep` after it).
    """
    def dist(a: int, b: int) -> int:
        # The triangle engine's distances are clamped at zero, as they always
        # were here (its sim stores an at-bound value a step PAST the bound,
        # and a clamp is what keeps that phase's ramp empty). The bounds
        # engine's are taken modulo $1000, because its sweep crosses $FFF
        # rather than clamping (`_pulse_triangle_wrapped`).
        return (a - b) & 0xFFF if wrap else max(0, a - b)
    up_spd, down_spd = speed, (0x100 - speed) & 0xFF

    def ramp(ticks: int, spd: int) -> List[tuple]:
        return [(t, spd) for t in _split_ticks(ticks)] if ticks > 0 else []

    def setrow(w: int) -> tuple:
        return ((0x80 | (w >> 8)) & 0xFF, w & 0xFF)

    chainable = (share and lo_v < hi_v and (hi_v - lo_v) % speed == 0)
    chained = {(w, d) for (w, d) in want_set
               if chainable and lo_v <= w <= hi_v and (w - lo_v) % speed == 0}

    phase_index: dict = {}
    block: List[tuple] = []
    if chained:
        def leg(points: List[int], start: int, end: int, spd: int):
            """One chained leg from `start` to `end` through `points`:
            (rows, {width: row offset}, head offset)."""
            rows: List[tuple] = []
            at: dict = {}
            head = None
            c = start
            for t in points:
                if t == start:
                    at[t] = len(rows)
                    rows.append(setrow(t))
                    continue
                if head is None:
                    head = len(rows)
                rows += ramp(abs(t - c) // speed - 1, spd)
                at[t] = len(rows)
                rows.append(setrow(t))
                c = t
            if head is None:
                head = len(rows)
            rows += ramp(abs(end - c) // speed, spd)
            return rows, at, head

        ups = sorted(w for (w, d) in chained if d > 0)
        downs = sorted((w for (w, d) in chained if d < 0), reverse=True)
        up_rows, up_at, up_h = leg(ups, lo_v, hi_v, up_spd)
        down_rows, down_at, down_h = leg(downs, hi_v, lo_v, down_spd)
        up0 = base + 1
        down0 = up0 + len(up_rows) + 1
        up_head, down_head = up0 + up_h, down0 + down_h
        block = up_rows + [(0xFF, down_head)] + down_rows + [(0xFF, up_head)]
        for w, off in up_at.items():
            phase_index[(num, w, +1)] = up0 + off
        for w, off in down_at.items():
            phase_index[(num, w, -1)] = down0 + off
    else:
        # The shared alternating loop: a down leg and an up leg, each jumping
        # to the other. Every phase entry ramps to its bound and joins here.
        span_ticks = max(1, dist(hi_v, lo_v) // speed)
        down_head = base + 1
        down = [(t, down_spd) for t in _split_ticks(span_ticks)]
        up_head = down_head + len(down) + 1
        block = down + [(0xFF, up_head)]
        block += [(t, up_spd) for t in _split_ticks(span_ticks)]
        block += [(0xFF, down_head)]

    for (w, direction) in sorted(want_set):
        if (w, direction) in chained:
            continue
        at = base + len(block) + 1
        piece = [setrow(w)]
        if direction > 0:
            piece += ramp(dist(hi_v, w) // speed, up_spd)
            piece += [(0xFF, down_head)]
        else:
            piece += ramp(dist(w, lo_v) // speed, down_spd)
            piece += [(0xFF, up_head)]
        phase_index[(num, w, direction)] = at
        block += piece
    return block, phase_index


def build_pulse_phase_table(sid: SidFile, det: Detection, instr_used: int,
                            pulse: bool, multiplier: int,
                            phases: dict, log=None,
                            lead: int = 1,
                            prefer_short: bool = False) -> tuple | None:
    """The whole pulse table with phase entry points, or None if NOTHING
    survives the table budget.

    `phases` is {instrument byte: set of (width, direction)} from the
    orderlist walk. Serves both sweeping engines through
    `_phase_sweep_params` (see `PulseBoundsSim` for how the bounds engine's
    walk differs). Returns (entries, starts, index) where `index` maps
    (instrument byte, width, direction) to the 1-based table entry a
    CMD_SETPULSEPTR must name. Non-sweeping instruments keep exactly the
    block `_pulse_layout` gives them; a sweeping record's own start pointer
    becomes its (record width, up) phase entry, so a note that gets no
    command -- a yielded row 0, a skipped occupied column -- still lands
    inside the same machinery rather than on a second copy of the sweep.

    A record whose planned phase set will not fit falls back to a static
    width first (`dropped`) -- exactly `_pulse_layout`'s own fallback for a
    table this full -- then to pointer 0 if even that will not fit
    (`silent`), rather than failing the whole file: `apply_pulse_phase`
    already tolerates a missing `index` entry (it just emits no command,
    so the note opens on the record's own width), so a partial table is
    always playable. `index` only holds instruments that KEPT a phase
    entry; the caller can ship a table with some records degraded. Only
    when every sweeping record that had a plan is degraded -- nothing
    survived -- does this return None, so the caller can still revert as
    it did before this fallback existed.

    **Before degrading anything, the table is laid out a second time with
    SHARED RAMPS** (`_phase_block(share=True)`), and that layout ships when
    it degrades fewer records. It is a rescue, consulted only where the
    per-phase layout dropped something, so a file whose table fits keeps
    its bytes. Measured at 04fdcb5 + this session's tree: one record's phase
    set cost 130 rows (Last_V8 instrument 7) because every phase carried its
    own ramp to the bound; shared, the four overflowing files (Last_V8 and
    its C128 version, Master_of_Magic, Phantoms_of_the_Asteroid) place every
    phase-tracked record and drop none. `_phase_block` says why the shared
    layout plays the same widths.

    **`prefer_short`: the table is shared with songs appended after this
    one.** On a compilation (`convert._append_players`) the pulse table
    subtune 0 leaves is the budget every appended player's sweeps must fit
    in, so there the shared layout ships whenever it degrades no more
    records AND is shorter, even where the per-phase one fits. Measured on
    5_Title_Tunes: subtune 0's table 214 -> 167 rows, no record dropped
    either way, its siddump register table identical for 180 s (9001
    rows); the 47 rows let players 1-4 append with their sweeps (pulse 248
    of 255) where they appended without any. Nothing else passes it, so
    every other file keeps its bytes.
    """
    first_log: list = []
    first = _lay_pulse_phase_table(sid, det, instr_used, pulse, multiplier,
                                   phases, first_log.append, lead, False)
    chosen, chosen_log = first, first_log
    if prefer_short and not (first[3] or first[4]):
        short_log: list = []
        short = _lay_pulse_phase_table(sid, det, instr_used, pulse,
                                       multiplier, phases, short_log.append,
                                       lead, True)
        if (short[3], short[4]) <= (first[3], first[4]) \
                and len(short[0]) < len(first[0]):
            chosen, chosen_log = short, short_log
            short_log.insert(0, (
                f"Pulse phase.............: shared ramps -- {len(short[0])} "
                f"table row(s) where one ramp per phase took {len(first[0])}; "
                "the further players appended after this subtune share the "
                "table"))
    elif first[3] or first[4]:
        shared_log: list = []
        shared = _lay_pulse_phase_table(sid, det, instr_used, pulse,
                                        multiplier, phases, shared_log.append,
                                        lead, True)
        # `dropped` counts every degraded record and `silent` the subset
        # that reached pointer 0, so the pair compares in that order.
        if (shared[3], shared[4]) < (first[3], first[4]):
            chosen, chosen_log = shared, shared_log
            shared_log.insert(0, (
                f"Pulse phase.............: shared ramps -- {len(shared[0])} "
                f"table row(s) place {shared[6]} of {shared[5]} phase-tracked "
                f"record(s), where one ramp per phase placed {first[6]} and "
                f"degraded {first[3]} record(s), {first[4]} to pointer 0"))
    if log:
        for line in chosen_log:
            log(line)
    entries, starts, index, _, _, attempted, placed = chosen
    if attempted and not placed:
        # Nothing survived: every record that had a phase plan degraded to a
        # static width. Let the caller revert the whole expansion, as before
        # this fallback existed.
        return None
    return entries, starts, index


def _lay_pulse_phase_table(sid: SidFile, det: Detection, instr_used: int,
                           pulse: bool, multiplier: int, phases: dict, log,
                           lead: int, share: bool) -> tuple:
    """One layout pass of `build_pulse_phase_table`: (entries, starts,
    index, dropped, silent, attempted, placed). `share` picks
    `_phase_block`'s shared-ramp layout for every phase-tracked record."""
    entries: List[tuple] = [(0x80, 0x00), (0xFF, 0x00)]
    starts = [1] * lead
    index: dict = {}
    dropped = silent = 0
    attempted = placed = 0
    # Under `share`, a non-phase block that names no row of its own -- no
    # loop, and no jump but `FF 00`, the stop -- plays the same from any
    # copy, so a second record with the same rows takes the first one's
    # pointer instead of a copy. Last_V8 carries 16 records whose block is
    # `80 00 / FF 00`; the shared-ramp layout needs 30 rows past 255 there
    # without this and fits with it. Off in the per-phase pass, so a file
    # whose table fits keeps its bytes.
    seen: dict = {}

    def standalone(program: list, loop) -> bool:
        return loop is None and all(l != 0xFF or r == 0 for l, r in program)

    def reuse(program: list, loop) -> bool:
        at = seen.get(tuple(program)) if share and standalone(program, loop) else None
        if at is None:
            return False
        starts.append(at)
        return True

    def remember(program: list, loop, start: int) -> None:
        if share and standalone(program, loop):
            seen.setdefault(tuple(program), start)

    for i in range(max(instr_used - lead, 0)):
        num = i + 1 + lead
        want = phases.get(num)
        params = _phase_sweep_params(sid, det, i, multiplier) if want else None
        if not want or params is None:
            # Not phase-tracked (no plan, or a record that does not sweep
            # under either engine): the ordinary --pulse-phase block.
            program, loop = _pulse_program(sid, det, i, pulse, multiplier)
            if reuse(program, loop):
                continue
            start = len(entries) + 1
            block = program if loop is None else program + [(0xFF, start + loop)]
            if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
                # Out of table: keep the instrument, lose only its movement.
                program, loop = _pulse_program(sid, det, i, False, multiplier)
                dropped += 1
                if reuse(program, loop):
                    continue
                start = len(entries) + 1
                block = program if loop is None else program + [(0xFF, start + loop)]
            if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
                starts.append(0)
                silent += 1
                continue
            remember(program, loop, start)
            starts.append(start)
            entries += block
            continue

        attempted += 1
        width = params[0]
        # One entry point per distinct phase, the record's own resting width
        # included so the instrument pointer has somewhere to stand. Built
        # into a local index first so a table-full below can discard just
        # this record without touching what an earlier record already placed.
        want_set = set(want) | {(width, +1)}
        block, phase_index = _phase_block(len(entries), num, want_set,
                                          *params, share=share)

        if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
            # The sweep's own phase set will not fit: fall back exactly as
            # _pulse_layout does for a non-sweeping instrument -- a static
            # width first (no phase entries for this instrument, so its
            # notes open on the record's own resting width), then pointer 0.
            if log:
                log(f"*** PULSE PHASE NEEDS {len(block)} TABLE ROWS FOR "
                    f"INSTRUMENT {num}, FALLING BACK TO A STATIC WIDTH ***")
            program, loop = _pulse_program(sid, det, i, False, multiplier)
            dropped += 1
            if reuse(program, loop):
                continue
            start = len(entries) + 1
            block = program if loop is None else program + [(0xFF, start + loop)]
            if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
                starts.append(0)
                silent += 1
                continue
            remember(program, loop, start)
            starts.append(start)
            entries += block
            continue

        index.update(phase_index)
        placed += 1
        starts.append(phase_index[(num, width, +1)])
        entries += block

    if log and dropped:
        log(f"*** PULSE TABLE FULL UNDER --pulse-phase -- {dropped} "
            f"INSTRUMENT(S) LOSE THEIR PHASE ENTRIES"
            + (f", {silent} SET NO WIDTH AT ALL ***" if silent else " ***"))
    return entries, starts, index, dropped, silent, attempted, placed


def packed_pattern_size(rows) -> int:
    """Bytes `packpattern` emits for `rows` of (note, instr, cmd, data)
    -- its size arithmetic exactly, before the endmark.

    Three rules decide it: a repeated instrument byte costs nothing, a
    command/data pair costs two bytes only where it CHANGES from the previous
    row (one where the command is 0), and a run of bare rests after the first
    row collapses to one byte per 64. Table remaps are size-neutral. Not
    replicated, and both only ever make the real pack SMALLER than this: a
    song with no command anywhere starts `command` at 0 rather than -1 (the
    first row's `FX+0` is then free), and `CMD_SETMASTERVOL` above `$0F` is
    erased when no author info is packed.
    """
    temp1, instr = [], 0
    for c, (n, i, cmd, dat) in enumerate(rows):
        if c and i and i == instr:
            temp1.append((n, 0, cmd, dat))
        else:
            temp1.append((n, i, cmd, dat))
            if i:
                instr = i
    b, command, databyte = [], -1, -1
    for n, i, cmd, dat in temp1:
        if i:
            b.append(i)
        if n == GT_REST:
            if cmd != command or dat != databyte:
                command, databyte = cmd, dat
                b.append(_PACK_FXONLY + cmd)
                if cmd:
                    b.append(dat)
            else:
                b.append(GT_REST)
        else:
            if cmd != command or dat != databyte:
                command, databyte = cmd, dat
                b.append(_PACK_FX + cmd)
                if cmd:
                    b.append(dat)
            b.append(n)
    size, c = 0, 0
    while c < len(b):
        packok = c != 0
        if b[c] < _PACK_FX:
            size += 1
            c += 1
            packok = False
        if c < len(b) and _PACK_FXONLY <= b[c] < _PACK_FIRSTNOTE:
            fxnum = b[c] - _PACK_FXONLY
            size += 2 if fxnum else 1
            c += 2 if fxnum else 1
            continue
        if c < len(b) and b[c] < _PACK_FXONLY:
            fxnum = b[c] - _PACK_FX
            size += 2 if fxnum else 1
            c += 2 if fxnum else 1
            packok = False
        if c >= len(b):
            break
        if b[c] != GT_REST:
            packok = False
        if not packok:
            size += 1
            c += 1
        else:
            d = c
            while d < len(b) and b[d] == GT_REST and d - c < 64:
                d += 1
            d -= c
            size += 1
            c += d if d > 1 else 1
    return size


def pattern_rows(pattern: List[int]) -> list:
    """A flat pattern as (note, instr, cmd, data) rows up to its ENDPATT --
    `pattlen` in gsong.c:1328, the row count `packpattern` is handed."""
    out = []
    for k in range(0, len(pattern) - 3, 4):
        if pattern[k] == 0xFF:      # ENDPATT, patterns.GT_END_PATTERN
            break
        out.append(tuple(pattern[k:k + 4]))
    return out


def budget_pulse_phase_commands(patterns: List[List[int]], command: int,
                                log=None,
                                limit: int = PACKED_PATTERN_LIMIT) -> List[List[int]]:
    """Every pattern that packs past `limit`, with its `command` rows re-placed
    first-fit in row order and the rest dropped; the others returned as they
    are.

    Runs on the FINISHED rows, after `_vibrato_command_pass`, because that is
    the only place the size is knowable: Rasputin's four phase clones pack to
    217 when `apply_pulse_phase` writes them and to 264-270 once the vibrato
    pass has put `CMD_VIBRATO` on 53-68 more of their rows (v0.5.480). A
    budget taken on the plan therefore drops nothing and the file is still
    refused -- measured before this was moved here.

    Row order rather than any smarter choice, on purpose: the pack charges a
    change from the PREVIOUS row, so which commands fit depends on which were
    kept before them, and the first-fit walk is the one whose result a reader
    can reproduce by hand. A note whose command is dropped keeps the
    instrument's own pointer, the record's (width, up) entry that
    `build_pulse_phase_table` gives every sweeping record -- exactly what
    every note got before the option. A pattern still past the limit with
    every `command` stripped is not this pass's to fix, and is left as is;
    `tests/test_pattern_budget.py` walks the corpus's finished bytes for it.
    Changed patterns are COPIES: the caller's list may be shared with the
    orderlist stages that built it.
    """
    out: List[List[int]] = []
    dropped = over = 0
    for pattern in patterns:
        rows = pattern_rows(pattern)
        if packed_pattern_size(rows) <= limit:
            out.append(pattern)
            continue
        wanted = [(k, r[3]) for k, r in enumerate(rows) if r[2] == command]
        if not wanted:
            out.append(pattern)
            continue
        over += 1
        base = [(n, i, 0, 0) if c == command else (n, i, c, d)
                for (n, i, c, d) in rows]
        for k, e in wanted:
            trial = list(base)
            trial[k] = (base[k][0], base[k][1], command, e)
            if packed_pattern_size(trial) > limit:
                dropped += 1
                continue
            base = trial
        copy = list(pattern)
        for k, (n, i, c, d) in enumerate(base):
            copy[4 * k + 2], copy[4 * k + 3] = c, d
        out.append(copy)
    if log and over:
        log(f"Pulse phase.............: {dropped} CMD_SETPULSEPTR dropped from "
            f"{over} pattern(s) that would pack past {limit} bytes "
            "(greloc.c packpattern)")
    return out


def _write_pulsetable(out: bytearray, entries: List[tuple]) -> None:
    out.append(_table_length_byte(len(entries), "pulse"))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)
