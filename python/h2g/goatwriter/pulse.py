"""Pulse programs, the triangle walk, phase sims and the pulse-table layout (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import re
from bisect import (bisect_right)
from contextlib import contextmanager
from dataclasses import (dataclass)
from fractions import (Fraction)
from functools import lru_cache
from typing import (Dict, List, Mapping, Optional, Set, Tuple)

from ..detect import (Detection, pulse_tri_offset, _TRI_COUNTER, _TRI_DIR,
                      _TRI_IDX)
from ..search import (search_file)
from ..sidfile import (SidFile)
from .constants import (CMD_SETTEMPO, GT_FIRST_NOTE, GT_LAST_NOTE, GT_MAX_PULSE_SPEED,
                        GT_MAX_PULSE_TICKS, GT_REST, _PACK_FIRSTNOTE, _PACK_FX,
                        _PACK_FXONLY, PACKED_PATTERN_LIMIT, PULSE_RESEED_GATE,
                        SPEED_GATE, SPEED_GATE_IMM, TEMPO_FASTEST_STEADY,
                        _TRI_INSTR_CELL)
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


# A triangle step above this per CALL is spelled as one set-width row per
# call (`_ramp_rows`) instead of being clamped to `GT_MAX_PULSE_SPEED`: the
# clamp slows the sweep by raw/127, and 134 is where that passes 5%
# (a step of 128 sweeps 0.8% slow, which no column can see). Measured with
# `_tri_table_speed` over the corpus under presets: Commando records 0, 6
# and 22, Gerry_the_Germ 17 and 59, Zoids 0 and 14, Gremlins 54 and 56.
SPELLED_SPEED_MIN = GT_MAX_PULSE_SPEED + 7


def _setrow(width: int) -> tuple:
    """A pulse-table "set width" row (left `$8x`, right the low byte)."""
    return ((0x80 | (width >> 8)) & 0xFF, width & 0xFF)


def _ramp_rows(at: int, ticks: int, direction: int,
               speed: int) -> List[tuple]:
    """`ticks` calls of a sweep from width `at`, `direction` +1 or -1, at
    `speed` a call -- the rows that play them.

    A modulation row carries a SIGNED byte (readme.txt:887-889,
    gplay.c:889-899), so `GT_MAX_PULSE_SPEED` is the most one call can move
    the width, and the player's `$E0` steps reach 224. Above it the sweep is
    SPELLED: one set-width row per call, each the width the sweep has on that
    call. A set row spends the call it is read on setting the width and does
    not modulate it (gplay.c:874-879; player.s `mt_setpulse` jumps to
    `mt_nextpulsestep` past `mt_pulsemod`), so a row per call plays exactly
    the widths a modulation row of `speed` would, with no clamp -- at the
    price of one table row a call instead of one a leg."""
    if ticks <= 0:
        return []
    if speed <= GT_MAX_PULSE_SPEED:
        spd = speed if direction > 0 else (0x100 - speed) & 0xFF
        return [(t, spd) for t in _split_ticks(ticks)]
    return [_setrow((at + direction * speed * k) & 0xFFF)
            for k in range(1, ticks + 1)]


# A triangle record that holds a width this many original FRAMES or more is
# laid as a held stair (`_stair_legs`) where the table has room, instead of a
# continuous slew at the mean rate (`_pulse_layout`'s trial pass). Frames, not
# our calls: at -S9 every delay-1 step is 10 calls, and a stair there holds
# one frame -- what the slew already shows the SID (Game_Killer's pulse_phase
# fell 0.786 -> 0.714 under a 8-CALL threshold).
STAIR_MIN_FRAMES = 8

# Whether `_pulse_layout` may spend table rows on stairs at all. OFF for a
# compilation and for its appended players (`convert` sets it): their pulse
# tables are MERGED into one of 255 rows, and rows spent on a stair cost the
# ladder its `pulse_phase` level (5_Title_Tunes' players 1-4 then append
# without sweeps -- tests/test_instrument_cap_append_ladder.py).
STAIR_ENABLED = True


@contextmanager
def stair_enabled(on: bool):
    global STAIR_ENABLED
    before, STAIR_ENABLED = STAIR_ENABLED, on
    try:
        yield
    finally:
        STAIR_ENABLED = before


def _stair_rows(at: int, count: int, direction: int, step: int,
                calls: int) -> List[tuple]:
    """`count` lattice steps from width `at`: per step one set-width row (it
    spends its own call, gplay.c:874-879) and a speed-0 hold row for the
    other `calls - 1`, so each width sounds `calls` calls like the player's
    own `delay` ticks."""
    rows: List[tuple] = []
    for k in range(1, count + 1):
        rows.append(_setrow((at + direction * step * k) & 0xFFF))
        rows += [(t, 0) for t in _split_ticks(calls - 1)]
    return rows


def _stair_legs(width: int, step: int, calls: int, first_top: int,
                bottom: int, top: int) -> tuple[List[tuple], int]:
    """`_lattice_legs` as a held stair: the same lattice, the same turns, but
    every width is HELD `calls` calls and stepped by the player's own `step`
    -- a slew at the mean rate moves the width every call where the player
    moves it once a `delay` (Last_V8's record 1: rate $79, step 96 every 26
    ticks, 2 a call at -S2)."""
    entries = [_setrow(width)]
    entries += [(t, 0) for t in _split_ticks(calls - 1)]
    first = _nearest_ticks((first_top - width) & 0xFFF, step)
    entries += _stair_rows(width, first, +1, step, calls)
    at = (width + first * step) & 0xFFF
    down = max(1, _nearest_ticks((at - bottom) & 0xFFF, step))
    low = (at - down * step) & 0xFFF
    if first_top == top:
        loop = len(entries)
        entries += _stair_rows(at, down, -1, step, calls)
        entries += _stair_rows(low, down, +1, step, calls)
        return entries, loop
    entries += _stair_rows(at, down, -1, step, calls)
    at = low
    up = max(1, _nearest_ticks((top - at) & 0xFFF, step))
    loop = len(entries)
    entries += _stair_rows(at, up, +1, step, calls)
    entries += _stair_rows((at + up * step) & 0xFFF, up, -1, step, calls)
    return entries, loop


def _pulse_triangle(width: int, low: int, high: int, speed: int,
                    step: Optional[int] = None) -> tuple[List[tuple], int]:
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

    **With `step` (the triangle engine's own per-tick step), the legs turn
    where the player turns** (`_tri_turns`): on the first width of the
    record's step lattice whose high nibble EQUALS the bound -- the first
    width at or past `high << 8` going up, the first at or below
    `(low << 8) + $FF` going down -- not on the bound itself. Without it
    every triangle record descended a whole nibble too far: Game_Killer's
    record 2 ran 808..DF6 (1518) where the player runs 8E0..E20 (1344), and
    111 of 111 triangle records under presets turned off the player's
    widths. Each leg is the tick count whose arrival is NEAREST the
    player's turn width at the emitted speed, measured from where the
    previous leg actually stopped; where the speed divides the step (every
    `-S1` delay-1 step up to 127) that is the turn width exactly. Without
    `step` the old edges stand. The per-record-bounds engine now passes its
    rate as the step (`_pulse_program`), so only a caller with no rate to
    give gets them. RETRACTED: "that engine was not measured here" -- it
    was, on 484 records (`PulseBoundsSim` and this are one arithmetic).
    """
    lo_v, hi_v = low << 8, high << 8
    turns = _tri_turns(width, step, low, high) if step else None
    if turns is not None:
        return _lattice_legs(width, speed, *turns)
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


def _tri_turns(width: int, step: int, low: int,
               high: int) -> Optional[tuple[int, int, int]]:
    """(first top, bottom, top): the widths the triangle engine turns on
    from `width` going up -- its first turn, the turn after it, and the top
    of the cycle it then repeats -- or None if a nibble is never reached.

    Read off `PulsePhaseSim.advance`, the routine's own arithmetic, so the
    two cannot disagree: a 12-bit add and a turn on EQUALITY of the high
    nibble after the step (`ADC #$00 / AND #$0F / CMP #$0E / BNE`, Commando
    $5275-$527C). A step is at most $F0, so no nibble is skipped, and the
    turn lands on the first lattice point inside the bound's nibble:
    Game_Killer's record 2 ($9C0, step $E0) climbs $AA0 ... $D40, $E20 and
    turns; descends $D40 ... $9C0, $8E0 and turns; and from $8E0 reaches
    $E20 again -- a cycle 8E0..E20, 1344 a leg, where the bounds alone say
    800..E00. The first top differs from the cycle's only where the record
    opens inside the top nibble with a step that stays in it (Devils_Galop's
    record 9, $E00 step $80: $E80, then 880..E00 for ever after)."""
    sim = PulsePhaseSim(width, step, 1, low, high)
    out = []
    for want in (-1, +1, -1):
        for _ in range(0x1000 // step + 2):
            sim.advance(1)
            if sim.direction == want:
                break
        else:
            return None
        out.append(sim.width)
    return out[0], out[1], out[2]


def _nearest_ticks(distance: int, speed: int) -> int:
    """The tick count whose arrival at `speed` is nearest `distance`, half
    up (never Python's round-half-even, which would depend on parity)."""
    return (2 * distance + speed) // (2 * speed)


def _lattice_legs(width: int, speed: int, first_top: int, bottom: int,
                  top: int) -> tuple[List[tuple], int]:
    """`_pulse_triangle`'s entries for the player's lattice turns: a set to
    the record's width, the first ascent, then the loop. Every leg's tick
    count is measured from where the previous leg ACTUALLY stopped, so the
    rounding never accumulates; the loop is one down leg and one up leg of
    the same count, so it returns exactly to where it started. Where the
    first top is not the cycle's (`_tri_turns`), the first descent is laid
    before the loop and the loop opens on the ascent instead. A `speed`
    above the modulation byte is a spelled step (`_ramp_rows`): every leg is
    then one set row a call, and a lattice leg is exact."""
    entries = [_setrow(width)]
    first = _nearest_ticks((first_top - width) & 0xFFF, speed)
    if first:
        entries += _ramp_rows(width, first, +1, speed)
    at = (width + first * speed) & 0xFFF
    down = max(1, _nearest_ticks((at - bottom) & 0xFFF, speed))
    low = (at - down * speed) & 0xFFF
    if first_top == top:
        loop = len(entries)
        entries += _ramp_rows(at, down, -1, speed)
        entries += _ramp_rows(low, down, +1, speed)
        return entries, loop
    entries += _ramp_rows(at, down, -1, speed)
    at = low
    up = max(1, _nearest_ticks((top - at) & 0xFFF, speed))
    loop = len(entries)
    entries += _ramp_rows(at, up, +1, speed)
    entries += _ramp_rows((at + up * speed) & 0xFFF, up, -1, speed)
    return entries, loop


def _pulse_triangle_wrapped(width: int, low: int, high: int,
                            speed: int,
                            step: Optional[int] = None,
                            ) -> tuple[List[tuple], int]:
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
    * Without `step`, each leg turns a fraction of a step early rather
      than a fraction late.

    **With `step` (the record's rate, the player's whole per-frame step),
    the legs turn where the player turns** (`_tri_turns`, as in
    `_pulse_triangle`): on the first width of the step lattice whose high
    nibble EQUALS the bound, which is the sweep's own arithmetic
    (`PulseBoundsSim.advance` and `PulsePhaseSim.advance` are the same
    add, mask and equality test). The modular distances above are then
    measured to those widths. The `high == low` case needs no special
    reading: the sim turns at once where the step stays inside the nibble
    and runs the full $1000 where it leaves it, as the player does.
    """
    turns = _tri_turns(width, step, low, high) if step else None
    if turns is not None:
        return _lattice_legs(width, speed, *turns)
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
                   multiplier: int,
                   tick_ratios: Optional[Mapping[int, Fraction]] = None,
                   stair: bool = False, spell: bool = False,
                   ) -> tuple[List[tuple], int | None]:
    """The pulse-table entries for instrument `i`, and where a jump loops back.

    `spell` lays a per-record-bounds sweep whose rate is over
    `SPELLED_SPEED_MIN` a call as set rows (`_ramp_rows`) instead of
    clamping it to `GT_MAX_PULSE_SPEED`; it is off here and `_pulse_layout`
    turns it on record by record where the table has the rows.

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

    * the player turns around when the high nibble *equals* a bound, on the
      first width of its step lattice inside that nibble, and the legs turn
      there too (`_tri_turns`, `_lattice_legs`) -- to the nearest tick at the
      emitted speed, which is the width exactly only where the speed divides
      the rate. RETRACTED: "the tick count here is the span divided by the
      speed, which turns around a fraction of a step early" -- it aimed at
      the bound itself, up to a whole nibble from the player's turn
      (Saboteur_II's record 10: 1533 against the player's 1344).
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
            program = _pulse_tri_program(
                sid, det, i, multiplier,
                tick_ratio=(tick_ratios or {}).get(i), stair=stair)
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
    raw = max(1, round(rate / multiplier))
    speed = min(GT_MAX_PULSE_SPEED, raw)
    width = ((data[base + 1] & 0x0F) << 8) | data[base]
    if (spell and raw >= SPELLED_SPEED_MIN
            and _tri_turns(width, rate, low, high) is not None):
        # Only the lattice legs spell (`_lattice_legs`); a record whose
        # nibble is never reached keeps the clamped fallback legs.
        speed = raw
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
        return _pulse_triangle_wrapped(width, low, high, speed, rate)
    return _pulse_triangle(width, low, high, speed, rate)


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
                       multiplier: int,
                       tick_ratio: Optional[Fraction] = None,
                       stair: bool = False,
                       ) -> tuple[List[tuple], int] | None:
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
    * **A modulation row cannot carry a step above 127, so the triangle
      engine SPELLS one** (`_ramp_rows`, `_tri_table_speed`). A Goattracker
      pulse speed is a signed byte (readme.txt:887-889, gplay.c:889-899), so
      the most one row moves the width is 127 per *call*, and `rate & $E0`
      reaches 224. A set-width row spends its call setting the width and does
      not modulate it (gplay.c:874-879), so one set row per call plays the
      widths a faster row would have: a step the clamp would slow by more than
      5% (`SPELLED_SPEED_MIN`) is laid as set rows, at the price of a table
      row a call. RETRACTED: "A step above 127 cannot be expressed at all ...
      sweeps ~1.8x slow" -- true of a modulation row, which is what this
      engine emitted for Commando's records 0 and 6, Zoids' 0 and 14 and
      Gerry_the_Germ's 17 until the change that spelled them. The bounds
      engine (`_pulse_program`) spells too, record by record where the
      table has the rows (`_pulse_layout`'s `spell` trial; a record that
      would push another out keeps its clamp): 194 of its records on 19
      corpus files have a rate over 134 a call (census at 1172704,
      `pulse._bounds_record`, first 64 slots, all at `-S1`), 12 of them
      PLAYED on 8 files, and all 12 fit (tables of 98-224 rows).
    * The player turns around when the high nibble *equals* a bound, on the
      first width of its step lattice inside that nibble, and the legs here
      turn there too (`_pulse_triangle`'s `step`, `_tri_turns`) -- to the
      nearest tick at the emitted speed, which is the width exactly only
      where the speed divides the step. RETRACTED: "the tick count here
      turns a fraction of a step early instead" -- it turned on the bound
      itself, a whole nibble below the player's bottom turn: Game_Killer's
      legs spanned 1518 against the player's 1344.
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
    gate = outer_gate_skip(sid)
    speed = _tri_table_speed(step, delay, multiplier, gate, tick_ratio)
    width = ((data[rec + 1] & 0x0F) << 8) | data[rec]
    if stair and tick_ratio is None:
        # Calls the player holds a width for: `delay` ticks of our calls.
        calls = round(delay / _tri_call_speed_ratio(multiplier, gate))
        frames = delay if not gate else Fraction(delay * (gate + 1), gate)
        if frames >= STAIR_MIN_FRAMES:
            turns = _tri_turns(width, step, det.pulse_tri_lo, det.pulse_tri_hi)
            if turns is not None:
                return _stair_legs(width, step, calls, *turns)
    return _pulse_triangle(width, det.pulse_tri_lo, det.pulse_tri_hi, speed,
                           step)


def _tri_speed(step: int, delay: int, multiplier: int,
               gate_skip: Optional[int],
               tick_ratio: Optional[Fraction] = None) -> int:
    """`_tri_call_speed` clamped to what a modulation row can carry
    (`GT_MAX_PULSE_SPEED`). The program builders use `_tri_table_speed`,
    which spells a step the clamp would slow by more than 5%; this is the
    clamped figure, for what still needs one.

    The GT pulse speed (per CALL) of a triangle sweep stepping `step`
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

    **WHAT THIS EXPOSED, FIXED SINCE: the audible leg was a separate
    defect.** `_pulse_triangle` turned on the bound itself, while the player
    turns on the first lattice point whose high nibble EQUALS the bound --
    Game_Killer sweeps 8E0..E20 (1344 a leg) where our table spanned 1518.
    At /9 the two errors cancelled (leg 6.81 frames against the original's
    6.62); at /10 the rate is right and the leg read 7.33. The legs now turn
    on the player's lattice (`_tri_turns`; table 8E4..E22, 61 ticks of 22):
    measured packed at 6e467ff + that change, 120 s, Game_Killer 7.34 ->
    6.81 frames a leg (original 6.62), Ninja 16 -> 15 (14.66), One_Man 6.6
    -> 6.0 (6.1), Human_Race 24 -> 22 (22).

    **A gate the TRACK reloads (Rasputin's `$FE nn`) is `tick_ratio`.**
    `outer_gate_skip` returns None for it -- R is 2, 3, 5, 10, 60, 120, 6, 2
    along one lap of subtune 0 -- and a pulse program is one per RECORD, so
    the sweep cannot follow R. The original's rate does: 128 * R / (R + 1) a
    frame, measured per section at 310 s on voice 0 (all sweep frames, holds
    counted) 85.3, 96.0, 105.1, 114.6, 125.7, 127.5 for R 2, 3, 5, 10, 60,
    120. `track_set_tick_ratios` gives each record the clock it sounds at,
    averaged over the time it sounds: record 0 x1.057, speed 64 -> 61, packed
    ramp 128.0 -> 122.0 a frame against the 121.0 the original's per-section
    rates weigh to (record 0 sounds 3.1, 2.8, 12.3, 10.6, 14.0 and 58.1 s
    under those R). One speed per record runs 43% fast at R = 2 and 4% slow
    at R = 120, so the notes it serves badly sound a clone with the program
    of their own clock class (`tri_clock`): packed, the complete legs read
    86.0, 96.0, 106.0 and 122.0 a frame at R = 2, 3, 5 and 60 against the
    original's 82.3, 92.2, 105.3 and 121.3.

    **Read over ALL sweep frames, record 0 shows 115.2 against the 122
    emitted, and that is not lost travel** (`tri-turn-frame-dilution`,
    9a0a452). `player.s` steps on every call, turns included
    (`mt_nextpulsestep` resolves the jump on the previous entry's last
    step), so travel is 61 a call. Record 0's legs are 23 calls, odd at
    mult 2, so once per 23-frame cycle a -61 and a +61 share a frame and
    net 0; the steady mean is 22 * 122 / 23 = 116.8. Record 11's 14-call
    legs do not fold. Evening the legs would cost a 61-step of band to
    remove a fold the SID never hears.

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
    return min(GT_MAX_PULSE_SPEED,
               _tri_call_speed(step, delay, multiplier, gate_skip, tick_ratio))


def _tri_call_speed_ratio(multiplier: int,
                          gate_skip: Optional[int]) -> Fraction:
    """Original ticks per one of OUR play calls (`_tri_call_speed`'s divisor
    without the delay): the reciprocal of calls per tick."""
    if not gate_skip:
        return Fraction(1, max(1, multiplier))
    return Fraction(gate_skip, max(1, multiplier) * (gate_skip + 1))


def _tri_call_speed(step: int, delay: int, multiplier: int,
                    gate_skip: Optional[int],
                    tick_ratio: Optional[Fraction] = None) -> int:
    """How far a triangle sweep stepping `step` every `delay` ticks moves the
    width in one of OUR play calls, rounded and at least 1 -- `_tri_speed`
    before its clamp (see there for the clock)."""
    if not gate_skip:
        if tick_ratio is not None:
            calls = max(1, multiplier) * tick_ratio
            return max(1, round(step / (delay * calls)))
        return max(1, round(step / (delay * max(1, multiplier))))
    calls = Fraction(max(1, multiplier) * (gate_skip + 1), gate_skip)
    return max(1, round(step / (delay * calls)))


def _tri_table_speed(step: int, delay: int, multiplier: int,
                     gate_skip: Optional[int],
                     tick_ratio: Optional[Fraction] = None) -> int:
    """The per-call speed a triangle program is LAID at: `_tri_speed`, except
    that a step the clamp would slow by more than 5% (`SPELLED_SPEED_MIN`)
    keeps its true speed, and `_ramp_rows` spells it as set rows. Only a
    delay-1 step on a one-call tick gets there (`$E0` and `$C0`, 224 and 192
    a call at `-S1`), so the speed is the step itself and the lattice stays
    exact. `$E0` steps at `-S1` used to sweep at 127 against 224, 1.8x slow:
    Commando's records 0 and 6, Zoids' 0 and 14, Gerry_the_Germ's 17."""
    raw = _tri_call_speed(step, delay, multiplier, gate_skip, tick_ratio)
    return raw if raw >= SPELLED_SPEED_MIN else min(GT_MAX_PULSE_SPEED, raw)


def _tri_step_delay(det: Detection, rate: int) -> tuple[int, int]:
    """(step, frames between steps) of a triangle rate byte, in the file's
    own MASK DIALECT: `rate & $E0` every `(rate & $1F) + 1` frames in the
    absolute-address player (Commando), `rate & $F0` every `(rate & $0F) + 1`
    in the zero-page per-voice one (Samantha Fox, Spellbound). Detection
    reads the masks off the routine (`Detection.pulse_tri_step_mask`); every
    reader of the rate byte goes through here, so none can keep the other
    dialect's split."""
    # The command-table spelling halves the step (`AND #$F0 / LSR`,
    # `Detection.pulse_tri_step_shift`).
    return ((rate & det.pulse_tri_step_mask) >> det.pulse_tri_step_shift,
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


# Rows either side of a note over which `ClockNote.around` averages the row
# clock: wide enough to span the fractional-row compensation (a few rows) and
# a pattern or two, narrow enough to stay inside one of Rasputin's sections
# (the shortest, R = 3, is 256 rows).
CLOCK_WINDOW_ROWS = 24


@dataclass(frozen=True)
class ClockNote:
    """One note row of the finished patterns, with the clock it sounds at.

    `key` is (track index, orderlist position, row in the pattern): a repeated
    orderlist entry, or a second lap, yields the same key again. `calls` and
    `ticks` are the working calls and the original ticks the note is held for
    (to the voice's next note); `around` is the same ratio taken over
    `CLOCK_WINDOW_ROWS` rows either side of the note's middle -- the section's
    clock, free of the few-row noise the compensation commands put in a short
    note's own span."""
    record: int
    key: Tuple[int, int, int]
    calls: int
    ticks: int
    around: Fraction


def _clock_notes(sid: SidFile, det: Detection, tracks: List[List[int]],
                 patterns: List[List[int]], lead: int, multiplier: int
                 ) -> Optional[Tuple[SongSpeeds, List[List[ClockNote]]]]:
    """Every note of every subtune's finished patterns with its clock (the
    walk `track_set_tick_ratios` sums), or None where `speeds` cannot be read
    or the groups do not fit the subtunes. A subtune whose rows are shorter
    than the tempo floor yields no notes."""
    speeds = _gw_tempo.find_song_speeds(sid, det)
    groups = len(tracks) // 3
    if speeds is None or not 0 < groups <= max(sid.subtunes, 1):
        return None
    per_group: List[List[ClockNote]] = []
    for g in range(groups):
        frames = speeds.frames_for(g)
        notes_g: List[ClockNote] = []
        per_group.append(notes_g)
        if not frames or frames * multiplier < TEMPO_FASTEST_STEADY:
            continue
        plays = []                       # per voice: ([(pattern, row, pos)], rows)
        events = []                      # (row, voice, T): every CMD_SETTEMPO
        for v in range(3):
            row, repeat, operand = 0, 1, False
            voice = []
            for pos, b in enumerate(tracks[3 * g + v]):
                if operand:              # $FF's restart position
                    operand = False
                    continue
                if b == 0xFF:            # patterns.GT_ORDER_RESTART
                    operand = True
                    continue
                if 0xE0 <= b < 0xFF:     # a transpose, no row of its own
                    continue
                if 0xD0 <= b < 0xE0:     # patterns.GT_REPEAT: the NEXT entry
                    repeat = b - 0xD0 + 1
                    continue
                if b >= len(patterns):
                    continue
                pat = patterns[b]
                n = 0
                while 4 * n < len(pat) and pat[4 * n] != 0xFF:
                    n += 1
                for _ in range(repeat):
                    for k in range(n):
                        if (pat[4 * k + 2] == CMD_SETTEMPO
                                and TEMPO_FASTEST_STEADY <= pat[4 * k + 3]
                                < 0x80):
                            events.append((row + k, v, pat[4 * k + 3]))
                    voice.append((b, row, pos))
                    row += n
                repeat = 1
            plays.append((voice, row))
        # The row clock: a tempo command sets the length of its own row and
        # every later one, the voice serviced last winning a shared row. Rows
        # before the first command run the subtune's opening length.
        events.sort()
        rows_at = [e[0] for e in events]
        clock = [e[2] for e in events]
        opening = frames * multiplier
        starts = [0]                     # calls up to each event's row
        for k in range(1, len(events)):
            before = clock[k - 1] if k else opening
            starts.append(starts[-1] + (rows_at[k] - rows_at[k - 1]) * before)

        def calls_to(row: int) -> int:
            k = bisect_right(rows_at, row) - 1
            if k < 0:
                return row * opening
            return (starts[k] + (row - rows_at[k]) * clock[k]
                    + rows_at[0] * opening)

        for v in range(3):
            voice, total = plays[v]
            notes = []                   # (row, record, key)
            current = 1
            for b, row0, pos in voice:
                pat = patterns[b]
                for k in range(len(pat) // 4):
                    r = 4 * k
                    if pat[r] == 0xFF:
                        break
                    if pat[r + 1]:
                        current = pat[r + 1]
                    if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                        notes.append((row0 + k, current - lead - 1,
                                      (3 * g + v, pos, k)))
            for n, (at, rec, key) in enumerate(notes):
                end = notes[n + 1][0] if n + 1 < len(notes) else total
                end = max(end, at + 1)
                mid = (at + end) // 2
                lo = max(0, mid - CLOCK_WINDOW_ROWS)
                hi = min(max(total, end), mid + CLOCK_WINDOW_ROWS + 1)
                around = Fraction(calls_to(hi) - calls_to(lo),
                                  max(hi - lo, 1) * frames)
                notes_g.append(ClockNote(
                    rec, key, calls_to(end) - calls_to(at),
                    (end - at) * frames, around))
    return speeds, per_group


def track_set_tick_ratios(sid: SidFile, det: Detection,
                          tracks: List[List[int]],
                          patterns: List[List[int]], lead: int,
                          multiplier: int, log=None) -> Dict[int, Fraction]:
    """{record index: our calls per original TICK / `multiplier`} for a player
    whose outer gate reloads from the TRACK (`det.track_fe_command`: Rasputin's
    `$FE nn`), or {} where `outer_gate_skip` already answers.

    `_tri_speed` divides a triangle sweep's per-tick step by our calls per
    tick, `multiplier * (O + 1) / O` under an outer gate of reload O. Here O is
    not one number: `$FE nn` moves it mid-song (Rasputin subtune 0 runs 2, 3,
    5, 10, 60, 120, 6, 2) and a pulse program is one per RECORD, so the
    nearest a record can come is the clock it SOUNDS at, averaged over the
    time it sounds -- the program the record itself keeps, with a clone per
    far clock class on top (`tri_clock.tri_clock_plan`). The original's sweep covers 128 * R / (R + 1) width a
    frame in a section of reload R, so the one speed that matches the mean
    travel per frame sounded is step / (delay * c), `c` being the calls per
    tick summed over the record's notes -- `sum(calls) / sum(ticks)`, a
    time-weighted harmonic mean of the per-section clocks.

    The calls are read off the FINISHED patterns, the way
    `tempo_duty_split_plan` reads them but through every `CMD_SETTEMPO`, not
    only row 0's: `patterns._compensate_fractional_rows` spends what the
    rounded change dropped in tempo commands further down, and summing them
    gives each section its exact mean (Rasputin's 5.995, 5.328, 4.799,
    4.398, 4.065, 4.032, 4.665 and 5.984 calls a row at `-S2`, which are
    2 * 2 * (R + 1) / R for its R); a row's own T alone reads R = 10, 60 and
    120 as the same 4. A note is weighted by the rows it is held (to the
    voice's next note), and a row of `frames` working calls is `frames`
    ticks.

    One subtune's clock, the one the packed file's `-S` factor serves
    (`pack_subtune`); the other subtunes' notes only where that one never
    sounds the record. No entry for a record the walk never meets, for a row
    clock that cannot be read, or where `frames * multiplier` is under the
    tempo floor (`TEMPO_FASTEST_STEADY` clamps T up there, which would read as
    a gate). The phase table (`_phase_sweep_params`, `--pulse-phase`) is not
    given it: Rasputin does not ship that option.
    """
    if (not getattr(det, "track_fe_command", False)
            or outer_gate_skip(sid) is not None or multiplier < 1):
        return {}
    walked = _clock_notes(sid, det, tracks, patterns, lead, multiplier)
    if walked is None:
        return {}
    speeds, notes_by_group = walked
    groups = len(notes_by_group)
    per_group: List[Dict[int, List[int]]] = []
    for notes_g in notes_by_group:
        acc: Dict[int, List[int]] = {}
        per_group.append(acc)
        for note in notes_g:
            slot = acc.setdefault(note.record, [0, 0])
            slot[0] += note.calls
            slot[1] += note.ticks
    pack = _gw_tempo.pack_subtune(speeds, sid.start_song)
    out: Dict[int, Fraction] = {}
    recs = {r for acc in per_group for r in acc if r >= 0}
    for rec in sorted(recs):
        slots = ([per_group[pack].get(rec)] if pack < groups else [])
        if not slots or slots[0] is None:
            slots = [acc[rec] for acc in per_group if rec in acc]
        calls = sum(s[0] for s in slots)
        ticks = sum(s[1] for s in slots)
        if ticks:
            out[rec] = max(Fraction(1), Fraction(calls, ticks * multiplier))
    if log and out:
        log("Pulse sweep clock......: "
            + ", ".join(f"record {r} x{float(x):.3f}"
                        for r, x in sorted(out.items()))
            + f" of -S{multiplier}'s calls a tick (outer gate reloaded by "
            "the track)")
    return out


def _pulse_layout(sid: SidFile, det: Detection, instr_used: int,
                  pulse: bool, multiplier: int,
                  log=None, lead: int = 1,
                  usage: Optional[List[int]] = None,
                  tick_ratios: Optional[Mapping[int, Fraction]] = None
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
    programs = [_pulse_program(sid, det, i, pulse, multiplier, tick_ratios)
                for i in range(nrec)]
    statics = [_pulse_program(sid, det, i, False, multiplier)[0]
               for i in range(nrec)]
    entries, starts, dropped, silent, shared = _lay_out_pulse(
        programs, statics, lead, share=False)
    if not dropped and pulse and STAIR_ENABLED:
        # A slow triangle step laid as a held stair costs rows, so it is
        # tried record by record against the table that already fits, and a
        # record whose stair would push anything out keeps its slew.
        for i in range(nrec):
            alt = _pulse_program(sid, det, i, pulse, multiplier,
                                 tick_ratios, stair=True)
            if alt == programs[i]:
                continue
            trial = programs[:i] + [alt] + programs[i + 1:]
            t_entries, t_starts, t_dropped, _, _ = _lay_out_pulse(
                trial, statics, lead, share=False)
            if not t_dropped:
                programs = trial
                entries, starts = t_entries, t_starts
    if not dropped and pulse and det.pulse_bounds >= 0:
        # A per-record-bounds step over `SPELLED_SPEED_MIN` a call laid as
        # set rows costs a row a call, so it is tried record by record
        # against the table that already fits and a record whose rows would
        # push anything out keeps its clamp.
        for i in range(nrec):
            alt = _pulse_program(sid, det, i, pulse, multiplier,
                                 tick_ratios, spell=True)
            if alt == programs[i]:
                continue
            trial = programs[:i] + [alt] + programs[i + 1:]
            t_entries, t_starts, t_dropped, _, _ = _lay_out_pulse(
                trial, statics, lead, share=False)
            if not t_dropped:
                programs = trial
                entries, starts = t_entries, t_starts
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

# A planned phase is `(width, direction)`: the width the note opens on, and
# +1 / -1 for the way the sweep carries on from it. A HOLD is the third
# thing a phase can say: a record that two voices step in opposite
# directions on the same tick (`patterns._triangle_hold`) does not carry on
# anywhere, it reads one width on every step -- so its direction is `HOLD`
# plus the number of steps from the opening width to the width it holds
# (`hold_direction`, `hold_steps`; an integer, so a phase still sorts and
# keys a table like any other). Devils_Galop's instrument 10 opens voice 1
# on $F00 and holds $E80, one step down, voice 0 on $F00 and holds $F00.
HOLD = 8


# A hold can also say how long the opening width stays on the pulse register
# before the held one replaces it (`hold_wait`, in original TICKS): the original
# writes the opening width on the fetch tick and the held one after the
# fetching voice's FIRST step, which its delay counter puts one or more
# ticks later (`patterns._triangle_hold`). The wait is `HOLD_WAIT` times the
# direction's quotient, steps the remainder (-6..23, `is_hold`'s `> 1` being
# the low edge).
HOLD_WAIT = 32


# A hold can also END while its note still sounds: the partner that kept the
# record still leaves (it fetches a note of another record, a rest), and the
# voice sweeps on from where the hold left it
# (`patterns._hold_resume`). The direction then carries the hold's length and
# the phase the sweep resumes on, above `HOLD_THEN` so the low bits stay the
# hold's own: `n` original ticks of the held width, then the sweep from
# `(w2, d2)`. Still one integer, so a phase sorts and keys a table like any
# other.
HOLD_THEN = 1 << 16


def hold_direction(steps: int, wait: int = 0,
                   then: Optional[tuple] = None) -> int:
    assert -HOLD < steps < HOLD_WAIT - HOLD and wait >= 0, (steps, wait)
    assert HOLD_WAIT * (wait + 1) <= HOLD_THEN, wait
    base = HOLD + steps + HOLD_WAIT * wait
    if then is None:
        return base
    n, w2, d2 = then
    assert n >= 1 and 0 <= w2 < 0x1000 and d2 in (+1, -1), then
    return base + HOLD_THEN * (1 + ((((n << 12) | w2) << 1) | (d2 < 0)))


def is_hold(direction: int) -> bool:
    return direction > 1


def hold_steps(direction: int) -> int:
    return direction % HOLD_WAIT - HOLD


def hold_wait(direction: int) -> int:
    return direction % HOLD_THEN // HOLD_WAIT


def hold_then(direction: int) -> Optional[tuple]:
    """`(n, w2, d2)` of a hold that ends (`hold_direction`'s `then`), or None."""
    code = direction // HOLD_THEN
    if not code:
        return None
    code -= 1
    return code >> 13, (code >> 1) & 0xFFF, -1 if code & 1 else +1


def resume_phase(direction: int) -> Optional[tuple]:
    """The `(width, direction)` phase a hold that ends sweeps on from."""
    then = hold_then(direction)
    return None if then is None else (then[1], then[2])


def hold_rest(direction: int, multiplier: int) -> list:
    """The rest row(s) a hold spends between its opening width and the held
    one: `multiplier` play calls a tick, the fetch call having written the
    opening width already."""
    calls = (multiplier - 1) + hold_wait(direction) * multiplier
    return [(calls, 0)] if calls else []


def _rest_rows(calls: int) -> list:
    """`calls` play calls of nothing (a modulation row of speed 0)."""
    return [(t, 0) for t in _split_ticks(calls)] if calls > 0 else []


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
    # record, shared by every voice sweeping it, which is why the walk
    # runs the three voices in lockstep, `patterns._walk_triangle_group`).
    # `PulseBoundsSim` answers both the other way. RETRACTED: "shared by
    # every voice sounding it, which is the "two voices" decline in the
    # walk" -- the walk no longer declines a record two voices share.
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
    triangle walk's lockstep (one width stepped by every voice sweeping
    it) does not apply, and the state carries across an instrument change
    on one voice. `PER_VOICE` says so. (Written when the triangle walk
    still DECLINED a shared record: "so the triangle walk's "two voices"
    decline does not apply" -- RETRACTED with that decline.)

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
    """(width, GT speed, lo_v, hi_v, wrap, step) of record `i`'s sweep for
    the phase table, whichever engine the file carries, or None where it does
    not sweep. `wrap` says whether distances cross $FFF at every width (the
    bounds engine) or only where the equality turn says so (the triangle
    engine); `step` is the sweep's own per-play step -- the triangle's
    packed step, the bounds engine's whole rate byte -- which is the lattice
    both engines turn on (`_phase_cycle`, `_leg_ramps`). RETRACTED: "`wrap`
    says whether distances cross $FFF (the bounds engine) or clamp (the
    triangle engine)" -- the triangle's sweep crosses $FFF too, from any
    phase outside its band. RETRACTED: "`step` ... None for the bounds
    engine" -- its records aimed the phase table at `lo_v`/`hi_v` while
    `_pulse_program` already turned on the lattice.

    `lo_v`/`hi_v` are the BOUNDS, for both engines. Neither engine's loop
    turns on them: `_phase_block` and its helpers replace them with the
    lattice cycle the phases walk (`_phase_cycle`), keyed on `step`.

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
        speed = _tri_table_speed(step, delay, multiplier, outer_gate_skip(sid))
        return (width, speed, det.pulse_tri_lo << 8, det.pulse_tri_hi << 8,
                False, step)
    rec = _bounds_record(sid, det, i)
    if rec is None:
        return None
    width, rate, lo, hi = rec
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / max(1, multiplier))))
    return width, speed, lo << 8, hi << 8, True, rate


def _leg_ramps(w: int, d: int, lo_v: int, hi_v: int, wrap: bool,
               step: Optional[int]) -> tuple[int, int]:
    """(out, back): how far a phase (w, d)'s entry piece ramps in its own
    direction, then back the other way, before it joins the loop at the
    head of the other leg -- in width units, aimed at `hi_v` going up and
    `lo_v` going down.

    Without a `step` the bounds engine's distance is modulo $1000 at every
    width (`_pulse_triangle_wrapped`), and it never comes back; every
    shipped record now has one (`_phase_sweep_params`). With it, BOTH
    engines' is the distance their sweep actually TRAVELS, on its own step
    lattice, to the first width whose high nibble EQUALS the bound it is
    heading for (`PulsePhaseSim.advance`, the routine's `CMP #$0E / BNE`),
    measured to the same edge the in-band ramp has always aimed at: arrival
    less its overshoot past `hi_v` going up, arrival plus its height above
    `lo_v` going down. Inside the band that is `hi_v - w` and `w - lo_v`,
    exactly what the old clamp gave. Outside it the sweep runs on and wraps
    where the clamp laid an empty ramp: Human_Race's instrument 2 at ($080,
    down), step $80, descends $080 $000 $F80 ... to nibble 8 ($880 of
    travel); Devils_Galop's instrument 10 at ($F00, up) climbs through $FFF
    to nibble E ($F00); and a phase ON the low nibble whose first step
    leaves it (Commando's instrument 7 at ($800, down), step $E0: $720 ...)
    runs a whole $1000 lap.

    `back` is non-zero in one case: a phase going up whose own nibble is
    already the bound, so its first step turns it (Devils_Galop's and
    Monty_on_the_Run's ($E00, up), step $80: $E80, turn, $E00 ...). There is
    no edge ahead to aim at, so the piece climbs that one step and comes
    back down to `hi_v`, which the sweep passes on its way down, and joins
    the down leg there -- arriving ON the bound, so a record carrying such a
    phase still chains (`_union_kind`). The clamp turned it at once, and the
    attack read a step down.

    RETRACTED: "The triangle engine's distances are clamped at zero, as they
    always were here (its sim stores an at-bound value a step PAST the bound,
    and a clamp is what keeps that phase's ramp empty)" -- with the equality
    turn the sim stores no such value (it turns ON the step that reaches the
    nibble), and the clamp emptied the ramps of the phases outside the band.

    **`lo_v` / `hi_v` are the loop's EDGES, which with a `step` are the
    cycle's turns, not its bounds** (`_phase_cycle`): the sweep turns on the
    first width of its step lattice inside the bound's nibble, so
    Game_Killer's record 3 loops $8E0..$E20 where the bounds say
    $800..$E00. The bounds engine's records carry a step too (their rate),
    and walk the same arithmetic (`PulseBoundsSim.advance`) with the
    distances taken modulo $1000 where the nibble is below the other's;
    only a call with no `step` gets its bounds and the modular results
    above. Aimed at a lattice edge the arrival can sit on either
    side of it, so the overshoot is SIGNED: an arrival short of the edge
    climbs on to it, one past it comes back to it (the old `back`), and
    the same holds going down -- a phase ON the low nibble whose first step
    stays in it steps down, turns, and comes back up to the edge, as
    ($E00, up) steps up and comes back. Measured to the edge for the shared
    loop to continue from.
    """
    if not step:
        if wrap:
            return ((hi_v - w) & 0xFFF if d > 0 else (w - lo_v) & 0xFFF), 0
        return (max(0, hi_v - w) if d > 0 else max(0, w - lo_v)), 0
    bound = (hi_v if d > 0 else lo_v) >> 8
    x, travel = w, 0
    for _ in range(0x1000 // step + 2):
        x = (x + step * d) & 0xFFF
        travel += step
        if x >> 8 == bound:
            break
    else:                            # never reaches the nibble: no turn
        if wrap:
            return ((hi_v - w) & 0xFFF if d > 0 else (w - lo_v) & 0xFFF), 0
        return (max(0, hi_v - w) if d > 0 else max(0, w - lo_v)), 0
    # `over` is SIGNED: x and the edge are both in the bound's nibble, and
    # the edge is the bound itself only for the old callers. Aimed at a
    # lattice turn (`_phase_cycle`) the arrival can sit on either side of it.
    if d < 0:
        over = ((x - lo_v + 0x800) & 0xFFF) - 0x800
        net = travel + over
        return (net, 0) if net > 0 else (travel, -over)
    over = ((x - hi_v + 0x800) & 0xFFF) - 0x800
    net = travel - over
    return (net, 0) if net > 0 else (travel, over)


@lru_cache(maxsize=None)
def _phase_turns(w: int, d: int, step: int, lo: int, hi: int):
    """The widths a sweep entered at phase (w, d) turns on, successively --
    four turns, read off `PulsePhaseSim.advance` -- or None if a nibble is
    never reached. The first is the phase's own first turn; from the second
    on the sweep is in the cycle the record then repeats (see
    `_phase_cycle`)."""
    sim = PulsePhaseSim(w, step, 1, lo, hi, PulseVoiceCell(d, 0))
    out, going = [], d
    for _ in range(4):
        for _ in range(0x1000 // step + 2):
            sim.advance(1)
            if sim.direction == -going:
                break
        else:
            return None
        out.append(sim.width)
        going = -going
    return tuple(out)


def _phase_cycle(want_set: set, lo_v: int, hi_v: int,
                 step: Optional[int]) -> tuple[int, int]:
    """(bottom, top): the widths the loop of a triangle record's phase block
    turns on -- the cycle most of its phases end up repeating, as the
    sweep itself runs it (`_phase_turns`) -- or (lo_v, hi_v) for a call
    with no `step` and for a set that reaches no turn. The bounds engine's
    records pass their rate as `step` and are read the same way.

    The sweep turns on the first width of its step lattice whose high
    nibble EQUALS the bound, so the cycle is NOT bound to bound:
    Game_Killer's record 3 (step $E0) runs $8E0..$E20, 1344 a leg, where
    the bounds say $800..$E00; a step of $80 runs $880..$E00. Every phase
    of a record sits on the one lattice its seed's sweep walks, bar the few
    that entered through a 12-bit wrap (a step that does not divide $1000
    shifts the lattice on every lap: Commando's record 7 runs $840..$E60,
    not the $8E0..$E20 its seed's own walk does), so the cycle is the one
    most phases reach, ties to the lowest bottom. A phase on another cycle
    (`_minority_cycles`) runs a private loop on its own: RETRACTED "keeps its
    own turn in its entry piece and joins this loop from there" -- that loop
    turns on the dominant cycle's widths, so the piece played the seed's
    first leg and the dominant cycle after it."""
    if not step:
        return lo_v, hi_v
    tally: Dict[tuple, int] = {}
    for (w, d) in want_set:
        t = _phase_turns(w, d, step, lo_v >> 8, hi_v >> 8)
        if t is None:
            continue
        cyc = (t[2], t[3]) if d < 0 else (t[1], t[2])
        tally[cyc] = tally.get(cyc, 0) + 1
    if not tally:
        return lo_v, hi_v
    return min(tally, key=lambda c: (-tally[c], c))


def _minority_cycles(want_set: set, cycle: tuple[int, int],
                     step: Optional[int]) -> Dict[tuple, tuple[int, int]]:
    """{phase: (bottom, top)} for the moving phases of `want_set` whose own
    sweep repeats ANOTHER cycle than `cycle` (the dominant one,
    `_phase_cycle`'s answer): the phases `_phase_block` lays a private
    loop for. Empty with no `step` (the bounds without a lattice), and for
    a hold, which moves nowhere.

    A sweep that never wraps keeps its lattice for good: Human_Race's
    records 18 and 23 (step $E0) seed at ($800, up), which cycles
    $8E0..$E20 and always will, while 17 of 18 (18 of 19) phases entered
    through a 12-bit wrap and settle on $840..$E60. One loop cannot turn on
    both, so the shared loop is the dominant cycle's and these phases run
    their own (`_phase_turns` reads the cycle off the sim, as `_phase_cycle`
    does)."""
    if not step:
        return {}
    out: Dict[tuple, tuple[int, int]] = {}
    for (w, d) in want_set:
        if is_hold(d):
            continue
        t = _phase_turns(w, d, step, cycle[0] >> 8, cycle[1] >> 8)
        if t is None:
            continue
        cyc = (t[2], t[3]) if d < 0 else (t[1], t[2])
        if cyc != cycle:
            out[(w, d)] = cyc
    return out


def _chained_phases(want_set: set, speed: int, lo_v: int, hi_v: int,
                    wrap: bool = False, step: Optional[int] = None) -> set:
    """The phases `_phase_block(share=True)` lays ON its chained legs: those
    inside [lo, hi] on the speed lattice measured from `lo`, and only where
    the band itself is a whole number of steps -- and only where the sweep
    from the phase really runs the rest of that leg (`_leg_ramps` is the
    in-band distance and no way back). A phase ON a bound heading out of
    the band is on the lattice and on no leg: Human_Race's instrument 2 at
    ($800, down), step $80, steps to $780 and laps $1000 before it turns,
    where the chained down leg ends on it and turns at once. A HOLD
    (`is_hold`, `patterns._triangle_hold`) is on no leg either: it is a
    set row, the held width and a stop.

    `lo_v`/`hi_v` are the loop's edges (`_phase_cycle` for the triangle
    engine): the lattice is measured from the cycle's bottom, and the legs
    run to its top."""
    lo_v, hi_v = _phase_cycle(want_set, lo_v, hi_v, step)
    if not (lo_v < hi_v and (hi_v - lo_v) % speed == 0):
        return set()
    own = _minority_cycles(want_set, (lo_v, hi_v), step)
    return {(w, d) for (w, d) in want_set
            if not is_hold(d) and (w, d) not in own and lo_v <= w <= hi_v
            and (w - lo_v) % speed == 0
            and _leg_ramps(w, d, lo_v, hi_v, wrap, step)
            == ((hi_v - w if d > 0 else w - lo_v), 0)}


def _union_kind(want_set: set, speed: int, lo_v: int, hi_v: int,
                wrap: bool, step: Optional[int] = None):
    """Which union of `_lay_pulse_phase_table`'s shared pass a phase-tracked
    record may join: "chained" where every phase enters the loop exactly ON
    the bound its leg starts from, "plain" where it chains no phase at all,
    None otherwise.

    The distinction is what keeps a union lossless. A chained leg's set rows
    SET the width (that is how a phase is entered mid-leg), so they are
    no-ops only for a trajectory already on the lattice. A chained phase is
    on it by construction; an unchained phase's piece ramps toward its bound
    and jumps into the loop at a head, and it is on the lattice from there
    only if it ARRIVED on the bound. In a record's own block a piece that
    arrives off the bound runs a plain loop when the record chains nothing,
    so a union with a record that does chain would snap it onto the other
    record's lattice at the first set row it passes. Measured on
    5_Title_Tunes' first table (record 3 "plain", 6 "chained", same speed
    and bounds; be0aeb1 + this change with this function returning one kind
    for every record): the union ships under `prefer_short` and plays 22 of
    56 entry points, and record 3's own pointer, off the per-phase widths
    within 3200 calls. Records of one kind share a loop whose widths are
    the ones their own blocks played, so every entry plays what it played."""
    lo_v, hi_v = _phase_cycle(want_set, lo_v, hi_v, step)

    def lands(w: int, d: int) -> bool:   # `_phase_block`'s ramps, `_leg_ramps`
        out, back = _leg_ramps(w, d, lo_v, hi_v, wrap, step)
        n = out // speed * speed - back // speed * speed
        return (w + n * d) & 0xFFF == (hi_v if d > 0 else lo_v)
    # A hold is a set row, the held width and a stop, whatever the lattice:
    # it lands on nothing and chains nothing, so it takes no part in the
    # kind -- the phases that move decide it.
    # A phase on another cycle (`_minority_cycles`) runs its own private
    # loop and never joins this one, so it neither has to land on this
    # loop's bound nor blocks the chain.
    own = _minority_cycles(want_set, (lo_v, hi_v), step)
    moving = {(w, d) for (w, d) in want_set
              if not is_hold(d) and (w, d) not in own}
    if all(lands(w, d) for (w, d) in moving):
        return "chained"
    return (None if _chained_phases(want_set, speed, lo_v, hi_v, wrap, step)
            else "plain")


def _phase_block(base: int, num: int, want_set: set, width: int, speed: int,
                 lo_v: int, hi_v: int, wrap: bool,
                 step: Optional[int] = None,
                 share: bool = False, attack: bool = False,
                 multiplier: int = 1, resume: bool = False) -> tuple:
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
    where the band itself is a whole number of steps; any other phase (one
    outside the band, say, whose piece wraps -- `_leg_ramps`) keeps its own
    piece, which jumps into the chained legs at their heads as it jumped
    into the plain ones -- and so a record is chained only where every such
    piece ARRIVES on its bound (`_union_kind`'s "chained"; see the gate
    below). A row is never a jump's target if it is a jump
    itself (the two players follow one jump per call, gplay.c:865-869 before
    the step and player.s `mt_nextpulsestep` after it).

    **The loop and legs turn on the sweep's lattice** (`_phase_cycle`; a
    `step` says so, and both engines hand one in). The player turns on
    the first width of its step lattice whose high nibble EQUALS the bound,
    so the loop is bottom..top of THAT cycle -- Game_Killer's record 3 runs
    $8E0..$E20, 1344 a leg, where the bounds say $800..$E00 and this loop
    spanned 1518 -- the chained legs run between the same two widths, and an
    entry piece ramps to the edge of the cycle its phase joins. Every
    tick count is the one whose arrival is NEAREST the sweep's
    distance at the emitted speed (`_nearest_ticks`), where a call with no
    `step` takes the whole ticks below it. Census under forced `pulse_phase`
    (turns of the first three legs of every shipped index entry, against
    `PulsePhaseSim`): 1851 of 4503 within half a speed before, 4647 of 4704
    after, 1701 exact before and 4151 after (the rest are speeds that do
    not divide the step, and the clamped speeds of $E0 steps at `-S1`).
    RETRACTED: "the loop's span only: bound to bound" -- true of the bounds
    engine's phase table too, until its records were handed their rate as
    the step.

    **A phase on another cycle than the loop's runs a loop of its own**
    (`_minority_cycles`; task `phase-seed-minority-lattice`). Human_Race's
    records 18 and 23 seed at ($800, up), a sweep that never wraps and so
    cycles $8E0..$E20 for ever, where 17 of 18 phases cycle $840..$E60: the
    seed's piece ramps to ITS cycle's edge (`_leg_ramps` aimed there) and
    jumps into a two-leg loop on that cycle, laid the first time a piece
    needs it and shared by every phase of that cycle. It is on no chained
    leg and never lands on the shared loop, so `_chained_phases` and
    `_union_kind` read the other phases only: both records are "chained"
    (kind None before) and the shipped table is 197 rows where it took 245.

    **A hold that ENDS (`resume`; `hold_then`, `patterns._hold_resume`).** The
    partner that kept the record still can leave inside the note, and the
    voice then sweeps on alone from the width the hold left (Monty_on_the_Run's
    instrument 11 on voice 0 reads $F00 for 135 ticks and then climbs). Its
    entry is `set w / rest / set held / rest / jump`: the opening width and
    the wait as any hold, then the held width for `n` ticks less the set
    row's own call, then a jump (no call) to the entry of the phase `(w2,
    d2)` the sweep resumes on, whose set row plays on the call after the
    `n` ticks. The jump may lie ahead, so it is filled in once every entry is
    placed. Four to five rows an entry that nothing shares (the length is in
    the key), and one more entry for `(w2, d2)`, which
    `build_pulse_phase_table` adds to the record's phases for the layout
    that asks for `resume` and ships only if it is no worse by `_score`.
    Without `resume` the same direction is a plain hold, as before.

    **A `speed` above the modulation byte (`SPELLED_SPEED_MIN`; Commando's
    `$E0` steps at `-S1`, 224 a call) is laid as set rows** (`_ramp_rows`):
    the loop, the chained legs and every entry piece become one set row a
    call, at the widths the sweep has. The lattice arithmetic above then
    runs at the true speed, so the legs are exact where the clamp's were
    1.8x slow; the cost is a row a call, so the shared layout (`share=True`,
    one chain a leg) is what fits such a record once the per-phase one does
    not. Under presets (the table `convert` asks for) Commando's goes 129
    -> 185 rows and ships shared, Zoids' 85 -> 155, and Gerry_the_Germ's
    241 -> 149 shared (its per-phase layout no longer fits and would degrade
    one record).
    """
    # The triangle engine's loop turns where the sweep does (`_phase_cycle`),
    # not on its bounds, and every leg is the tick count nearest the
    # sweep's own distance (`_nearest_ticks`) where a call with no `step`
    # takes the whole ticks below it. Everything below -- `_leg_ramps`, the chained
    # legs, `_union_kind` -- reads these edges, and re-deriving them from
    # an edge returns the same edge.
    lo_v, hi_v = _phase_cycle(want_set, lo_v, hi_v, step)

    def dist(a: int, b: int) -> int:
        # The loop's span only: an entry piece's ramps are `_leg_ramps`, which
        # says why the triangle's no longer clamps.
        return (a - b) & 0xFFF if wrap else max(0, a - b)

    def whole(distance: int) -> int:
        return _nearest_ticks(distance, speed) if step else distance // speed

    def ramp(at: int, ticks: int, d: int) -> List[tuple]:
        return _ramp_rows(at, ticks, d, speed)

    setrow = _setrow

    # Chained only where EVERY phase lands on its bound -- `_union_kind`'s
    # "chained", the precondition the pass-through argument above rests
    # on. An unchained piece that arrives OFF its bound runs into a
    # chained leg's set rows and is snapped onto the lattice there, where
    # the plain loop of its per-phase block carried it on: Human_Race's
    # record 2 under the lockstep triangle walk opens a note at ($080,
    # down) beside 24 lattice phases, and from that entry the shared block
    # played $080 $0C0 $880 ... against the per-phase block's $080 $0C0
    # $100 ... (tests/test_pulse_phase_union.py). Such a record lays the
    # plain loop instead -- its per-phase block, rows and all. (Both of
    # those plays were wrong: the sweep descends $080 $000 $F80 ..., which
    # the piece now ramps (`_leg_ramps`), and a ramp of $880 at that record's
    # speed $40 arrives ON $800, so the phase no longer blocks the chain.)
    chained = (_chained_phases(want_set, speed, lo_v, hi_v, wrap, step)
               if share and _union_kind(want_set, speed, lo_v, hi_v, wrap,
                                        step) == "chained" else set())

    phase_index: dict = {}
    block: List[tuple] = []
    if chained:
        def leg(points: List[int], start: int, end: int, d: int):
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
                rows += ramp(c, abs(t - c) // speed - 1, d)
                at[t] = len(rows)
                rows.append(setrow(t))
                c = t
            if head is None:
                head = len(rows)
            rows += ramp(c, abs(end - c) // speed, d)
            return rows, at, head

        ups = sorted(w for (w, d) in chained if d > 0)
        downs = sorted((w for (w, d) in chained if d < 0), reverse=True)
        up_rows, up_at, up_h = leg(ups, lo_v, hi_v, +1)
        down_rows, down_at, down_h = leg(downs, hi_v, lo_v, -1)
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
        span_ticks = max(1, whole(dist(hi_v, lo_v)))
        down_head = base + 1
        down = ramp(hi_v, span_ticks, -1)
        up_head = down_head + len(down) + 1
        block = down + [(0xFF, up_head)]
        block += ramp(lo_v, span_ticks, +1)
        block += [(0xFF, down_head)]

    # A phase on another cycle than the loop's (`_minority_cycles`) joins
    # a loop of its OWN, laid once per cycle the first time a piece needs
    # it: the shared loop's turns are not its turns, and the piece's last
    # jump into it would play the dominant cycle from there on.
    own = _minority_cycles(want_set, (lo_v, hi_v), step)
    private: dict = {}

    def private_loop(cycle: tuple) -> tuple:
        if cycle not in private:
            b, t = cycle
            ticks = max(1, whole(dist(t, b)))
            d_head = base + len(block) + 1
            rows = ramp(t, ticks, -1)
            u_head = d_head + len(rows) + 1
            rows = rows + [(0xFF, u_head)] + ramp(b, ticks, +1)
            rows += [(0xFF, d_head)]
            block.extend(rows)
            private[cycle] = (d_head, u_head)
        return private[cycle]

    tails: dict = {}
    fixups: list = []
    for (w, direction) in sorted(want_set):
        if (w, direction) in chained:
            continue
        mine = own.get((w, direction))
        if mine is not None:
            loop_heads = private_loop(mine)
        at = base + len(block) + 1
        piece = [setrow(w)]
        if is_hold(direction):
            then = hold_then(direction) if resume else None
            if then is not None and (then[1], then[2]) in want_set:
                # A hold that ENDS (`patterns._hold_resume`): the partner
                # leaves after `n` ticks of the held width and the voice
                # sweeps on from `(w2, d2)`, an entry of this same record.
                # `w`, the wait, `held`, `n` ticks of it less the set row's
                # own call, and a jump (no call) to that entry, whose first
                # row is a set row on the next call. Never shared: the
                # length is part of the key. The jump target may lie ahead
                # of this row, so it is filled in below.
                n, w2, d2 = then
                held = (w + hold_steps(direction) * (step or 0)) & 0xFFF
                first = (multiplier - 1) + hold_wait(direction) * multiplier
                after = n * multiplier - 1
                if held == w:
                    rows = piece + _rest_rows(first + 1 + after)
                else:
                    rows = (piece + _rest_rows(first) + [setrow(held)]
                            + _rest_rows(after))
                phase_index[(num, w, direction)] = at
                fixups.append((len(block) + len(rows), (num, w2, d2)))
                block += rows + [(0xFF, 0)]
                continue
            # A hold (`patterns._triangle_hold`): the voice opens on `w`
            # and reads `held` on every step after it, for as long as its
            # partner keeps the record still. Where it opens on the width
            # it holds -- or under the shared layout, which is the one
            # that is short of rows -- its entry is a set row and a stop
            # (`FF 00`, as the table's first rows), one pair per width
            # held however many openings name it. Under the shared layout
            # an opening off the held width therefore plays the held width
            # on its attack frame, a step or two from the original's, where
            # the per-phase layout spends four rows to play it: `w`, one
            # tick of nothing that keeps the attack frame on it (the
            # original's fetch tick writes the width and sweeps from the
            # next tick), then `held`, then the stop.
            held = (w + hold_steps(direction) * (step or 0)) & 0xFFF
            if held == w or share:
                if held not in tails:
                    tails[held] = base + len(block) + 1
                    block += [setrow(held), (0xFF, 0)]
                if attack and held != w:
                    # `attack` (`_lay_attack_or_plain`, only where the
                    # table has the rows): the opening off the held width
                    # keeps the attack frame on the opening width as the
                    # per-phase layout does -- `w`, one tick of nothing --
                    # and then jumps (a jump costs no call, gplay.c's
                    # pulse-table jump) to the shared `set held / FF 00`
                    # pair: 3 rows an opening plus 2 a held width, where the
                    # per-phase form takes 4 an opening and 2 more.
                    phase_index[(num, w, direction)] = base + len(block) + 1
                    block += (piece + hold_rest(direction, multiplier)
                              + [(0xFF, tails[held])])
                else:
                    phase_index[(num, w, direction)] = tails[held]
            else:
                phase_index[(num, w, direction)] = at
                block += (piece + hold_rest(direction, multiplier)
                          + [setrow(held), (0xFF, 0)])
            continue
        if mine is None:
            out, back = _leg_ramps(w, direction, lo_v, hi_v, wrap, step)
            heads = (down_head, up_head)
        else:
            out, back = _leg_ramps(w, direction, mine[0], mine[1], wrap, step)
            heads = loop_heads
        n_out = whole(out)
        piece += ramp(w, n_out, direction)
        piece += ramp((w + direction * n_out * speed) & 0xFFF, whole(back),
                      -direction)
        piece += [(0xFF, heads[0] if direction > 0 else heads[1])]
        phase_index[(num, w, direction)] = at
        block += piece
    for row, key in fixups:
        block[row] = (0xFF, phase_index[key])
    return block, phase_index


def build_pulse_phase_table(sid: SidFile, det: Detection, instr_used: int,
                            pulse: bool, multiplier: int,
                            phases: dict, log=None,
                            lead: int = 1,
                            prefer_short: bool = False,
                            usage: Optional[List[int]] = None
                            ) -> tuple | None:
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
    layout plays the same widths. The shared pass also lays ONE block over
    the union of the phase sets of records with the same sweep, where that
    makes it better by (silent, dropped, rows) (`_lay_pulse_phase_table`,
    `_union_kind`). Measured under forced `pulse_phase` at be0aeb1 + that
    change, every index entry and tracked start played for 3200 calls
    against the unlimited per-phase layout: Gremlins keeps 20 swept (10
    still degrades), Human_Race keeps 23 (20 still degrades), and
    Master_of_Magic / Phantoms / Battle_of_Britain ship 172 -> 103,
    200 -> 59, 225 -> 147 rows.

    **One order everywhere: `_score` = (silent, dropped, rows).** The
    shared-vs-per-phase choice, the reserve and the unions all rank by it
    (the first used (dropped, silent) until v0.5.542), and the reserve is
    tried whenever the chosen layout degrades any record, shipped where it
    is strictly better by it. Under presets no corpus file moves; forced
    `pulse_phase` moves Gremlins (252 -> 253 rows, record 10 swept too).

    **Where the chosen layout still leaves a record on pointer 0, both are
    laid again with every later record's static width RESERVED** before a
    record may spend rows on movement (`_lay_pulse_phase_pass`'s `reserve`),
    and the reserved one ships if it silences fewer. Measured under forced
    `pulse_phase` at 8586101: Last_V8 (and its C128 version) went 14
    degraded / 12 on pointer 0 in 254 (255) rows to 1 / 0 in 223 (224):
    instrument 7 keeps its phases, and 9 alone degrades -- its shared block
    asks 47 rows where 32 are left. The 12 were records 22-33, which the
    shipped song prunes; what is audible is instrument 7, whose voice-0
    onset widths went 0.66 -> 0.84 same-bucket against the original over
    180 s. The reserve is exact (tests/test_pulse_phase_reserve.py sweeps
    every limit), and no file whose layout leaves every record a width
    moves.

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

    **`usage` (`pulse_usage`) weighs the layouts by NOTES SOUNDED.** Every
    comparison below ranks layouts by (silent, dropped, rows); with `usage`
    the first two count the note rows of the records concerned, not the
    records. A record nobody plays costs nothing on pointer 0 or on a static
    width: Last_V8's 12 pointer-0 records at 8586101 sounded 0 notes between
    them, and counted as 12 they outweighed a record that sounds. Without
    `usage` every record weighs 1, the count it always was.
    """
    ends = {num: {resume_phase(d) for (_, d) in ws
                  if is_hold(d) and hold_then(d) is not None}
            for num, ws in phases.items()}
    if prefer_short or not any(ends.values()):
        return _build_pulse_phase_table(sid, det, instr_used, pulse,
                                        multiplier, phases, log, lead,
                                        prefer_short, usage)[0]
    # A hold that ends (`hold_then`) asks rows: the hold's own, and the entry
    # of the sweep it hands over to. Laid both ways, it ships only if it is
    # no worse by `_score` -- a table that is full sheds a record for it, and
    # then the holds stay holds for the rest of their notes. Not on a
    # compilation (`prefer_short`): the appended players need those rows.
    plain_log: list = []
    plain, plain_t = _build_pulse_phase_table(
        sid, det, instr_used, pulse, multiplier, phases, plain_log.append,
        lead, prefer_short, usage)
    end_phases = {num: set(ws) | ends[num] for num, ws in phases.items()}
    end_log: list = []
    ended, ended_t = _build_pulse_phase_table(
        sid, det, instr_used, pulse, multiplier, end_phases, end_log.append,
        lead, prefer_short, usage, resume=True)
    best, best_log = plain, plain_log
    if (ended is not None and ended_t is not None
            and (plain is None or (_score(ended_t) <= _score(plain_t)
                                   and ended[0] != plain[0]))):
        best, best_log = ended, end_log
    if log:
        for line in best_log:
            log(line)
    return best


def _build_pulse_phase_table(sid: SidFile, det: Detection, instr_used: int,
                             pulse: bool, multiplier: int,
                             phases: dict, log=None,
                             lead: int = 1,
                             prefer_short: bool = False,
                             usage: Optional[List[int]] = None,
                             resume: bool = False) -> tuple:
    """`build_pulse_phase_table`'s one pass: ((entries, starts, index) or
    None, the chosen layout tuple), `resume` laying a hold that ends as the
    hold and the sweep it hands over to (`_phase_block`'s `resume`)."""
    ukw = {} if usage is None else {"usage": usage}
    ukw.update({"resume": True} if resume else {})
    first_log: list = []
    first = _lay_pulse_phase_table(sid, det, instr_used, pulse, multiplier,
                                   phases, first_log.append, lead, False,
                                   **ukw)
    chosen, chosen_log = first, first_log
    if prefer_short and not (first[3] or first[4]):
        short_log: list = []
        short = _lay_pulse_phase_table(sid, det, instr_used, pulse,
                                       multiplier, phases, short_log.append,
                                       lead, True, **ukw)
        if _score(short) <= _score(first) \
                and len(short[0]) < len(first[0]):
            chosen, chosen_log = short, short_log
            short_log.insert(0, (
                f"Pulse phase.............: shared ramps -- {len(short[0])} "
                f"table row(s) where one ramp per phase took {len(first[0])}; "
                "the further players appended after this subtune share the "
                "table"))
    elif first[3] or first[4]:
        shared_log: list = []
        shared = _lay_attack_or_plain(sid, det, instr_used, pulse,
                                      multiplier, phases, shared_log.append,
                                      lead, **ukw)
        # One order everywhere (`_score`): pointer 0 first, then degraded.
        if _score(shared) < _score(first):
            chosen, chosen_log = shared, shared_log
            shared_log.insert(0, (
                f"Pulse phase.............: shared ramps -- {len(shared[0])} "
                f"table row(s) place {shared[6]} of {shared[5]} phase-tracked "
                f"record(s), where one ramp per phase placed {first[6]} and "
                f"degraded {first[3]} record(s), {first[4]} to pointer 0"))
    if chosen[3] or chosen[4]:
        # A record degraded (on pointer 0 or a static width): the blocks laid
        # ahead of it took the
        # rows its static width needed. Lay both layouts again holding back
        # every later record's static first (`reserve`), and ship the one
        # that silences fewest, then degrades fewest, then is shortest.
        trials = []
        for share in (False, True):
            trial_log: list = []
            if share:
                trial = _lay_attack_or_plain(sid, det, instr_used, pulse,
                                             multiplier, phases,
                                             trial_log.append, lead,
                                             reserve=True, **ukw)
            else:
                trial = _lay_pulse_phase_table(sid, det, instr_used, pulse,
                                               multiplier, phases,
                                               trial_log.append, lead, share,
                                               reserve=True, **ukw)
            trials.append(((*_score(trial), len(trial[0])),
                           share, trial, trial_log))
        (rank, share, trial, trial_log) = min(trials, key=lambda t: t[:2])
        if rank[:2] < _score(chosen):
            trial_log.insert(0, (
                f"Pulse phase.............: statics reserved -- "
                f"{'shared ramps, ' if share else ''}{len(trial[0])} table "
                f"row(s) place {trial[6]} of {trial[5]} phase-tracked "
                f"record(s) and degrade {trial[3]} record(s), {trial[4]} to "
                f"pointer 0, where the layout without the reserve degraded "
                f"{chosen[3]}, {chosen[4]} to pointer 0"))
            chosen, chosen_log = trial, trial_log
    if log:
        for line in chosen_log:
            log(line)
    entries, starts, index, _, _, attempted, placed = chosen[:7]
    if attempted and not placed:
        # Nothing survived: every record that had a phase plan degraded to a
        # static width. Let the caller revert the whole expansion, as before
        # this fallback existed.
        return None, chosen
    return (entries, starts, index), chosen


def _union_groups(sid: SidFile, det: Detection, instr_used: int,
                  multiplier: int, phases: dict, lead: int) -> dict:
    """The sweep groups `_lay_pulse_phase_table`'s shared pass may lay as
    one union block: {(speed, lo_v, hi_v, wrap, step, kind, cycle): {num: want_set}}, only
    groups of two or more records, in allocation order of their first
    member. `want_set` is the record's planned phases plus its own (width,
    up), exactly the set the pass lays for it alone."""
    groups: dict = {}
    for j in range(max(instr_used - lead, 0)):
        want = phases.get(j + 1 + lead)
        params = _phase_sweep_params(sid, det, j, multiplier) if want else None
        if params is None:
            continue
        want_set = set(want) | {(params[0], +1)}
        kind = _union_kind(want_set, *params[1:])
        if kind is not None:
            # The cycle the loop turns on (`_phase_cycle`) is part of the
            # sweep: records of one step on different lattices lay different
            # loops, and one shared loop would play one of them off.
            cycle = _phase_cycle(want_set, params[2], params[3], params[5])
            groups.setdefault(params[1:] + (kind, cycle), {})[j + 1 + lead] = want_set
    return {k: v for k, v in groups.items() if len(v) > 1}


def _cost(t: tuple) -> tuple:
    """(dropped, silent) of a layout as the comparisons weigh them: note rows
    sounded where the pass was given `usage`, records otherwise (an older
    seven-field layout carries only the counts)."""
    return (t[7], t[8]) if len(t) > 7 else (t[3], t[4])


def _score(t: tuple) -> tuple:
    """(silent, dropped) of a layout: THE order every layout comparison uses
    (`build_pulse_phase_table`, `_lay_pulse_phase_table`) -- records on
    pointer 0 first, since a record with no width at all is worse than one on
    a static width, then degraded records. Weighed as `_cost` weighs."""
    dropped, silent = _cost(t)
    return silent, dropped


def _lay_attack_or_plain(sid: SidFile, det: Detection, instr_used: int,
                         pulse: bool, multiplier: int, phases: dict, log,
                         lead: int, reserve: bool = False,
                         usage: Optional[List[int]] = None,
                         resume: bool = False) -> tuple:
    """The SHARED layout (`_lay_pulse_phase_table(share=True)`), with a hold
    that opens off its held width playing the opening width on its attack
    frame (`_phase_block`'s `attack`) wherever the table has the rows for it:
    laid both ways, the attack form ships only if it is no worse by `_score`
    -- it asks 3 rows an opening where the plain shared form asks none, so a
    table that is full sheds a record for it, and then the plain form ships.
    A song that plans no hold lays one layout, as before."""
    ukw = {} if usage is None else {"usage": usage}

    def lay(attack: bool, lg) -> tuple:
        return _lay_pulse_phase_table(sid, det, instr_used, pulse,
                                      multiplier, phases, lg, lead, True,
                                      reserve=reserve, **ukw,
                                      **({"attack": True} if attack else {}),
                                      **({"resume": True} if resume else {}))
    plain_log: list = []
    plain = lay(False, plain_log.append)
    best, best_log = plain, plain_log
    if any(is_hold(d) for ws in phases.values() for (_, d) in ws):
        att_log: list = []
        att = lay(True, att_log.append)
        if att[0] != plain[0] and _score(att) <= _score(plain):
            best, best_log = att, att_log
    if log:
        for line in best_log:
            log(line)
    return best


def _lay_pulse_phase_table(sid: SidFile, det: Detection, instr_used: int,
                           pulse: bool, multiplier: int, phases: dict, log,
                           lead: int, share: bool,
                           reserve: bool = False,
                           usage: Optional[List[int]] = None,
                           attack: bool = False,
                           resume: bool = False) -> tuple:
    """One layout of `build_pulse_phase_table`: (entries, starts, index,
    dropped, silent, attempted, placed, dropped_notes, silent_notes). `share` picks `_phase_block`'s
    shared-ramp layout for every phase-tracked record, and may lay ONE
    block over the union of the phase sets of records sharing a sweep
    (`_union_groups`, `_lay_pulse_phase_pass`'s `unions`).

    **A union is adopted group by group, only where it makes the layout
    better by (silent, dropped, rows).** A union costs no more rows than
    its members' own blocks, but it lays them all at the group's FIRST
    member, so the rows a later member used to take at its own turn are
    taken before the records in between -- and a table that was full moves
    its shortfall onto one of those. Measured on Gremlins under forced
    `pulse_phase` at be0aeb1: both of its unions together keep records 10
    and 20 swept and put record 22 -- 1344 note rows, the file's most
    played -- on pointer 0, no width at all, where the per-record layout
    had degraded 10 and 20 to static widths and given 22 its block. So
    pointer 0 is counted first: no union is taken that silences a record
    the layout without it did not. With no group adopted the pass is the
    per-record shared layout, byte for byte. `reserve` is passed to every
    pass (`_lay_pulse_phase_pass`). "Better" counts the notes the records
    sound where `usage` is given (`_cost`)."""
    if not share:
        return _lay_pulse_phase_pass(sid, det, instr_used, pulse, multiplier,
                                     phases, log, lead, False, {}, reserve,
                                     usage, attack, resume)

    def score(t: tuple) -> tuple:
        return (*_score(t), len(t[0]))
    best_log: list = []
    best = _lay_pulse_phase_pass(sid, det, instr_used, pulse, multiplier,
                                 phases, best_log.append, lead, True, {},
                                 reserve, usage, attack, resume)
    chosen: dict = {}
    # A group that did not pay on its own may pay on top of one adopted
    # after it (Human_Race: {1,2} alone loses 477 notes against 437, but
    # with {18,23} laid it loses 264), so the groups still out are tried
    # again until a whole sweep adopts none.
    pending = _union_groups(sid, det, instr_used, multiplier, phases, lead)
    adopted = True
    while adopted and pending:
        adopted = False
        for key, members in list(pending.items()):
            trial_unions = dict(chosen)
            trial_unions[key] = members
            trial_log: list = []
            trial = _lay_pulse_phase_pass(sid, det, instr_used, pulse,
                                          multiplier, phases,
                                          trial_log.append, lead, True,
                                          trial_unions, reserve, usage,
                                          attack, resume)
            if score(trial) < score(best):
                best, best_log, chosen = trial, trial_log, trial_unions
                del pending[key]
                adopted = True
    if log:
        for line in best_log:
            log(line)
    return best


# **WHAT GREMLINS 10 IS SHORT OF, MEASURED, and why skipping the records
# `drop_unnamed_instruments` removes does not buy it.** Under forced
# `pulse_phase` at 8586101 (v0.5.511), Gremlins' shared pass with BOTH union
# groups ((3, 7) and (6, 20)) and no table limit takes 258 rows: 3 past
# `GT_MAX_TABLELEN`, so the last block laid -- record 22's, 1344 note rows,
# the file's most played -- goes to pointer 0, and the pass that ships
# instead takes (6, 20) alone and leaves 10 (280 note rows) on a static
# width. The 11 records the drop removes ($0E, $17-$20) cost the shared pass
# NO rows: each is a standalone `XX 00 / FF 00` pair that `reuse` already
# points at an earlier named record's copy (14 at record 5's, 23-32 at 16's).
# A pass that laid nothing for them was built and measured
# (C:/t/pulse-phase-union-blocks/r3/skip_probe.patch): 254 rows either way
# with no union, 252 with (6, 20), 255 with both. On the whole forced corpus it
# moved only Last_V8 and its C128 version, and there it was a LOSS hidden
# by this pass's counts: their 12 pointer-0 records at 8586101, before the
# statics reserve (22-33), sound 0 notes, so `silent` counted records
# nobody hears, and the layout it preferred kept 7 and 9 swept by putting
# 16 (4 notes) and 17 (64) on pointer 0. So it was not shipped. Since the
# reserve (`build_pulse_phase_table`'s "statics reserved" rescue) the
# shipped Last_V8 table has NO pointer-0 record -- 223 rows (224 on the
# C128 version), 2, 7 and 8 swept, 9 alone degraded -- so the skip as
# built, still (2, 2) silent/degraded, would not be adopted at all, and
# laid under the reserve it keeps the same records swept and saves only
# 12 rows (211 / 212). Every record still holding rows sounds
# notes; the 3 rows exist only as a trade -- laying record 9's sweep (179
# notes, `88 00 / 05 2B`) or record 15's (156 notes, `82 00 / 7F 01 ...`) as
# its static width fits both unions with 22 kept (255 / 253 rows), and
# which record should lose its sweep is a listening question.
# tests/test_pulse_phase_shortfall.py pins all of this. SUPERSEDED for
# Gremlins by the triangle's wrap ramps (`_leg_ramps`): record 10's 12
# phases outside the band ramp through the wrap, its block grows from 92 to
# 113 rows, it degrades in every layout, and both unions now fit with 22
# kept -- 168 rows, 3, 6, 7 and 20 swept (presets, forced `pulse_phase`,
# 075a175 + that change). The figures above are the clamp's table, and the
# test re-lays it with the ramps clamped to keep pinning them.
def _lay_pulse_phase_pass(sid: SidFile, det: Detection, instr_used: int,
                          pulse: bool, multiplier: int, phases: dict, log,
                          lead: int, share: bool, unions: dict,
                          reserve: bool = False,
                          usage: Optional[List[int]] = None,
                          attack: bool = False,
                          resume: bool = False) -> tuple:
    """One layout pass: (entries, starts, index, dropped, silent, attempted,
    placed, dropped_notes, silent_notes). The last two weigh each degraded
    record by the note rows it sounds (`usage`, `pulse_usage`; 1 a record
    without it). `unions` is the subset of `_union_groups` laid as one block
    each (see `group_left` below); empty, every phase-tracked record lays
    its own. `reserve` holds back every later record's static width first
    (`held_back` below)."""
    entries: List[tuple] = [(0x80, 0x00), (0xFF, 0x00)]
    starts = [1] * lead
    index: dict = {}
    dropped = silent = 0
    dropped_w = silent_w = 0
    attempted = placed = 0

    def hold_kw(want_set: set) -> dict:
        # What a HOLD's rows need (`_phase_block`): said only for a record
        # that plans one, so the others lay exactly as they did.
        if not any(is_hold(d) for (_, d) in want_set):
            return {}
        kw = {"attack": attack, "multiplier": multiplier}
        if resume:
            kw["resume"] = True
        return kw

    def weight(i: int) -> int:
        if usage is None:
            return 1
        return usage[i] if i < len(usage) else 0
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

    # Under `share`, phase-tracked records whose sweeps agree on (speed, lo,
    # hi, wrap, step) AND on `_union_kind` -- one group of `unions` -- share ONE
    # `_phase_block` laid over the union of their phase sets, and each
    # record's start and index entries point into it. A table row plays the
    # same whichever instrument's pointer reaches it, and the block's
    # lattice -- its chained legs, its loop, and (through `step`) the ramps
    # of its phases outside the band -- is set by those five alone
    # (`_phase_block` reads `width` for nothing), so one loop serves where
    # each record carried its own; `_union_kind` says why the kind must
    # agree too. The union is laid at the group's first record; if it does
    # not fit there, that record lays its own block and the next member
    # tries the union of what is left. `group_left` is each group's members
    # not yet laid, {num: want_set}; `laid` a group's union, once placed, as
    # {(width, direction): row}.
    group_left: dict = {k: dict(v) for k, v in unions.items()} if share else {}
    laid: dict = {}

    nrec = max(instr_used - lead, 0)
    # Under `reserve`, the rows every record after `i` needs for its static
    # width -- the fallback any degraded record takes -- are held back before
    # record `i` may spend rows on a sweep, a phase block or a union. A
    # standalone static already in `seen`, or the same rows as an earlier
    # pending one, costs nothing (`reuse`); a record a union block laid now
    # would cover (`skip`), or one an already-laid union covers, costs
    # nothing either. So while the statics alone fit, a record can lose its
    # movement to the records ahead of it but never its width:
    # `_lay_out_pulse`'s `reserve_for`, over every record.
    statics = ([_pulse_program(sid, det, j, False, multiplier)
                for j in range(nrec)] if reserve else [])

    def held_back(i: int, skip=(), laying=None) -> int:
        # `laying` is the (program, loop) record `i` is about to lay: a later
        # static with the same standalone rows will reuse it, so it is not
        # held a second time (Phantoms_of_the_Asteroid's shared table at a
        # 59-row limit degraded 5 records that fit without this).
        if not reserve:
            return 0
        rows, pending = 0, set()
        if laying is not None and share and standalone(*laying):
            pending.add(tuple(laying[0]))
        for j in range(i + 1, nrec):
            n = j + 1 + lead
            if n in skip or any(n in unions[k] for k in laid):
                continue
            program, loop = statics[j]
            if share and standalone(program, loop):
                if tuple(program) in seen or tuple(program) in pending:
                    continue
                pending.add(tuple(program))
            rows += len(program) + (loop is not None)
        return rows

    for i in range(nrec):
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
            if (len(entries) + len(block) + held_back(i, laying=(program, loop))
                    > _gw_constants.GT_MAX_TABLELEN):
                # Out of table: keep the instrument, lose only its movement.
                program, loop = _pulse_program(sid, det, i, False, multiplier)
                dropped += 1
                dropped_w += weight(i)
                if reuse(program, loop):
                    continue
                start = len(entries) + 1
                block = program if loop is None else program + [(0xFF, start + loop)]
            if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
                starts.append(0)
                silent += 1
                silent_w += weight(i)
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
        key = next((k for k, m in group_left.items() if num in m), None)
        if key is not None:
            union_rows = laid.get(key)
            if union_rows is None and len(group_left[key]) > 1:
                # The first record of a sweep group still to be laid: ONE
                # block over the union of its own and every later member's
                # phases. Too big, and this record tries its own block below;
                # the next member tries the union of what is left.
                union = set().union(*group_left[key].values())
                block, u_index = _phase_block(len(entries), 0, union,
                                              *params, share=True,
                                              **hold_kw(union))
                if (len(entries) + len(block)
                        + held_back(i, skip=group_left[key])
                        <= _gw_constants.GT_MAX_TABLELEN):
                    union_rows = {(w, d): at for (_, w, d), at in u_index.items()}
                    laid[key] = union_rows
                    entries += block
            group_left[key].pop(num, None)
            if union_rows is not None:
                index.update({(num, w, d): union_rows[(w, d)]
                              for (w, d) in want_set})
                placed += 1
                starts.append(union_rows[(width, +1)])
                continue
        block, phase_index = _phase_block(len(entries), num, want_set,
                                          *params, share=share,
                                          **hold_kw(want_set))

        if (len(entries) + len(block) + held_back(i)
                > _gw_constants.GT_MAX_TABLELEN):
            # The sweep's own phase set will not fit: fall back exactly as
            # _pulse_layout does for a non-sweeping instrument -- a static
            # width first (no phase entries for this instrument, so its
            # notes open on the record's own resting width), then pointer 0.
            if log:
                log(f"*** PULSE PHASE NEEDS {len(block)} TABLE ROWS FOR "
                    f"INSTRUMENT {num}, FALLING BACK TO A STATIC WIDTH ***")
            program, loop = _pulse_program(sid, det, i, False, multiplier)
            dropped += 1
            dropped_w += weight(i)
            if reuse(program, loop):
                continue
            start = len(entries) + 1
            block = program if loop is None else program + [(0xFF, start + loop)]
            if len(entries) + len(block) > _gw_constants.GT_MAX_TABLELEN:
                starts.append(0)
                silent += 1
                silent_w += weight(i)
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
    return (entries, starts, index, dropped, silent, attempted, placed,
            dropped_w, silent_w)


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
