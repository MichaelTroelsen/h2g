"""Classic, triangle and table vibrato entries and layout (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import math
from typing import (List, Optional)

from ..detect import (Detection, TRIANGLE_VIBRATO_GATE,
                      TRIANGLE_VIBRATO_MAX_SHIFT, TRIANGLE_VIBRATO_PERIOD,
                      VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                      VIBRATO_SHIFT_MASK)
from ..sidfile import (SidFile)
from .constants import (FIXED_ARP_PARITY_MASK, FORMAT_GTS5, GT_MAX_VIB_SHIFT,
                        GT_WAVE_FIRST_CMD, GT_WAVE_JUMP, GT_WAVE_LAST_CMD,
                        GT_WAVE_LAST_DELAY, GT_WAVE_NO_NOTE,
                        SPEED_NOTE_RELATIVE, VIBRATO_CMP_BIAS, VIBRATO_DELAY)
from .primitives import (_counter_gate_call, _rate_shift)
from . import constants as _gw_constants
from . import primitives as _gw_primitives
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
      `speed = depth / (2 * multiplier)`, i.e. `shift + 1 + log2(multiplier)`.

      **The code does NOT emit that: it emits**

          rshift = shift + _rate_shift(multiplier)

      **without the `+ 1`, so the swing is TWICE the derivation above.**
      The `+ 1` was dropped at v0.5.369 (3ec87b1, "the vibrato depth doubles,
      paid for with vibdelay instead of melody"), because the derived depth
      measured too shallow against the originals; halving `rshift` on its
      own renamed attacks, which is what the classic engine's `vibdelay`
      pays for. Read from this paragraph alone, the depth factor is 1.3125
      where the code's is 0.65625 -- exactly 2x and on the wrong side of 1
      -- so trust the code line, not the derivation, for what is emitted.

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
    # Zero means "do not compensate", and so does 1 -- the same convention as
    # `patterns._scaled_step`, which since the CMD_FUNKTEMPO 2-call row
    # (goatwriter.constants.CMD_FUNKTEMPO) counts 2 as a row: one call of two
    # runs effects.
    if row_calls >= 2:
        half = half * (row_calls - 1) / row_calls
    # bound 1 at -S1 asks for a half-period of one frame; Goattracker's
    # shortest is two calls (cmp 0), which is what the clamp gives.
    cmp_value = min(0x7F, max(0, round(half) - VIBRATO_CMP_BIAS))
    rshift = min(shift + _rate_shift(multiplier), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _effect_calls(entries: Optional[List[tuple]], ptr: int, calls: int,
                  row_calls: int = 0) -> int:
    """How many of a note's calls 1..`calls - 1` run continuous effects.

    That is the count `vibdelay` is spent against, and two things withhold a
    call from it (player.s `mt_wavedone`, gplay.c TICKNEFFECTS):

    * **tick 0.** `REALTIMEOPTIMIZATION` is on in every pack (gt2reloc.c:55)
      and skips continuous effects whenever the channel counter is 0 -- the
      first call of every row, `row_calls` apart from the note's own call 0.
      The `row_calls >= 2` convention of `_classic_vibrato_entry` applies:
      a 2-call CMD_FUNKTEMPO row withholds every second call; 0 and 1
      withhold nothing.
    * **a wavetable step that writes a frequency.** A step whose right column
      is not $80 (editor encoding; greloc inverts the high bit) takes the
      `mt_wavefreq` / `goto PULSEEXEC` path, and so does a wavetable command
      ($F0-$FE); only a delay tick, a no-note step or a finished program
      falls through to the effects. The note's own call 0 runs no wavetable
      at all (`mt_newnoteinit` ends in `jmp mt_loadregs`), so step 1 is on
      call 1. Pandora's `41/00 41/00 41/00 FF/00` withholds calls 1-3.

    `entries` is the finished wavetable and `ptr` the record's 1-based
    pointer into it; None or 0 is "no program", which withholds nothing.
    """
    return len(_effect_call_list(entries, ptr, calls, row_calls))


def _effect_call_list(entries: Optional[List[tuple]], ptr: int, calls: int,
                      row_calls: int = 0) -> List[int]:
    """The calls among 1..`calls - 1` that run continuous effects, in order
    -- `_effect_calls`' list, for a caller that needs to know WHERE they are.
    """
    out: List[int] = []
    wavetime = 0
    for c in range(1, calls):
        effects = True
        if entries and 0 < ptr <= len(entries):
            wave, note = entries[ptr - 1]
            if wave <= GT_WAVE_LAST_DELAY and wavetime != wave:
                wavetime += 1                   # a delay tick: effects run
            else:
                wavetime = 0
                ptr += 1
                if ptr <= len(entries) and entries[ptr - 1][0] == GT_WAVE_JUMP:
                    ptr = entries[ptr - 1][1]
                if (GT_WAVE_FIRST_CMD <= wave <= GT_WAVE_LAST_CMD
                        or note != GT_WAVE_NO_NOTE):
                    effects = False
        if row_calls >= 2 and c % row_calls == 0:
            effects = False
        if effects:
            out.append(c)
    return out


def _classic_gate_delay(det: Detection, multiplier: int, row_calls: int = 0,
                        entries: Optional[List[tuple]] = None,
                        ptr: int = 0, attack_call: int = 1,
                        record: Optional[int] = None) -> Optional[int]:
    """`vibdelay` the classic loop's own gate asks for, or None.

    detect._find_vibrato_gate reads the compare in front of the store. Its
    operand is a count of the PLAYER's frames and `vibdelay` counts our
    calls, so the target is `gate x multiplier` calls after the note:

    * "counter" (dialect A): frames since the note fetch; the store is
      skipped while the age is below the operand, so the oscillator is
      silent for exactly that many frames and runs from frame `gate` -- a
      delay, which is what `vibdelay` is. It is spent one per effect call
      (`_effect_calls`) and greloc stores it less one (greloc.c:780), so the
      oscillator first runs on effect call number `vibdelay`: the delay is
      the effect calls before the target, plus one. Without the wavetable
      this is the tick-0 count alone, an upper bound; `build_sng` refines it
      per record once the wavetable is laid out (`_classic_gate_refine`).

      **The target is counted from the call the attack is SEEN on**, which
      is what the original's gate is counted from (its fetch frame). With
      the default test-bit firstwave that is call 1, not the init call:
      Pandora's trace shows `0DD1/09` on the init frame and the note's own
      `/41` a frame later, where siddump names the attack. So the target is
      call `gate x multiplier + attack_call`, `attack_call` 1 for
      FIRSTWAVE_TESTBIT and 0 for a record writing its real waveform
      (`--no-test-restart`, `real_firstwave_instruments`). Measured
      (C:/t/classic-vibrato-gate/fb, first move after the attack): Food_Feud
      536 notes at frame 9 against the original's 398 at 9 and 99 at 10;
      ACE_II 374 at 4, 58 at 5 against 317 and 93; Star_Paws 308 at 15
      against 13 at 15. Counting from the init call instead put a third of
      Food_Feud's notes a frame early (176 at 8).
    * "duration" (dialect B): the note's stored length; a note shorter than
      the operand never vibrates, and one that qualifies vibrates from its
      first frames. That is a THRESHOLD, not a delay, and it returns None
      here: a delay of the operand's length was tried (the triangle engine's
      approximation) and moved the wrong notes -- Sanxion (gate 3, -S1)
      `vib` 0.887 -> 0.872, away from 1, its 53 late-onset notes pushed from
      frame 4 to frame 6 where the original has 2 notes starting at 6, and
      Tarzan (gate 3) flat (C:/t/classic-vibrato-gate/fb, 2026-09-30).
      The reading stays on Detection for the per-note form
      (`_vibrato_command_pass`'s shape) that can say "only notes this long".

    None -- keep the frame-1 floor -- where nothing was read: no compare
    (Sigma_Seven, whose load is dead), or an operand detect leaves UNREAD
    (0, 240, 254: Ricochet, Skate_or_Die_intro, Thundercats). Those are not a
    gate of 0 and not a default, and must not become either until the
    players are disassembled past the compare.

    **Per record where the player rewrites the operand** (detect's
    VIBRATO_GATE_STORE_SHAPE: Thundercats, Mega_Apocalypse, Star_Paws, and
    the held Arcade_Classics, BMX_Kidz, Ricochet, Skate_or_Die_intro): the
    gate is `vg.gate_for(record)`, record `i` counted from instr_start, and
    None without a record. **A per-record gate of 0 is a gate of 1**: the
    age the compare sees was never below 1 in the trace, so `CMP #0` and
    `CMP #1` skip the same frames -- on Star_Paws record 10 (gate 0) every
    compare passes and the lowest age among them is 1, the same first age
    as record 4 (gate 1) (C:/t/selfmod-vibrato-gate/runtime_trace.txt).
    No static operand is 0 (detect reads it as UNREAD), so this reaches
    only the stored table.
    """
    target = _counter_gate_call(det, multiplier, attack_call, record)
    if target is None:
        return None
    # **Nearest effect call, not the next one.** vibdelay can only start the
    # oscillator ON an effect call, and a program that holds the frequency
    # over the target (a wavetable step, a tick 0) leaves no call there. The
    # next one can be two frames late: Pygmies_Revenge's `21/00 02/80 41/00`
    # at -S1 withholds calls 4 (tick 0) and 5 (the `41/00`), so "first effect
    # call at or after 4" is call 6, where call 3 is one early. Ties go late,
    # so the oscillator never starts further before the original's than
    # after it.
    calls = _effect_call_list(entries, ptr, target + 0x100, row_calls)
    before = [c for c in calls if c < target]
    after = next((c for c in calls if c >= target), None)
    delay = len(before) + 1
    if before and (after is None or target - before[-1] < after - target):
        delay = len(before)
    return min(0xFF, max(1, delay))


def _classic_gate_refine(det: Detection, vib_ptrs: dict,
                         entries: List[tuple], wave_starts: List[int],
                         multiplier: int, row_calls: int,
                         instr_row_calls: Optional[dict] = None,
                         lead: int = 1, no_test_restart: bool = False,
                         real_firstwave_instruments: tuple = ()) -> dict:
    """`vib_ptrs` with each record's counter-gate delay taken against its own
    wavetable program -- the half `_vibrato_layout` cannot know, because the
    wavetable is laid out after it. Unchanged where no counter gate was read.

    No frame-1 floor here: the target is frame `gate`, which is past frame 0
    by construction for every operand read (3..19 static; 1 and up from a
    per-instrument table, its 0 read as 1), so the floor's reason --
    keep the oscillator off the attack frame -- is already met, and applying
    it on top would postpone a record whose program withholds the calls.
    """
    mult = max(1, multiplier)
    vg = det.vibrato_gate
    if (vg is None or vg.form != "counter" or not vib_ptrs
            or (vg.gate is None and vg.table is None)):
        return vib_ptrs
    out = {}
    for i, (idx, delay) in vib_ptrs.items():
        ptr = (wave_starts[i + lead]
               if wave_starts is not None and i + lead < len(wave_starts) else 0)
        # Goattracker number, as `_write_instruments` keys it (i + lead + 1).
        own = (instr_row_calls or {}).get(i + lead + 1, row_calls)
        # Same test as `_write_instruments`' firstwave byte.
        real = no_test_restart or (i + lead + 1) in real_firstwave_instruments
        got = _classic_gate_delay(det, mult, own, entries, ptr,
                                  attack_call=0 if real else 1, record=i)
        out[i] = (idx, delay if got is None else max(1, got))
    return out


def _vibrato_delay(det: Detection, multiplier: int,
                   commanded: bool = False, row_calls: int = 0,
                   record: Optional[int] = None) -> int:
    """Goattracker `vibdelay` for this player's vibrato, in play calls.

    `vibdelay` is a countdown, not a flag: gplay.c:769-776 is a fallthrough
    from `CMD_DONOTHING`, breaking while `vibdelay > 1` and decrementing once
    per call, so the oscillator first runs on the `vibdelay`-th call after the
    note. 1 means "from the first call" and 0 means "never".

    The LFO-table player gates nothing, so it keeps `VIBRATO_DELAY`. **The
    classic players do gate** -- this sentence said they did not until the
    gate was read (detect._find_vibrato_gate): 54 of the 55 corpus files the
    classic split resolves in carry a compare after the centring subtraction,
    in two forms, and `_classic_gate_delay` says which one a delay can
    express. **The global-triangle player does gate, but not with a
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
            floor = max(VIBRATO_DELAY, multiplier + 1)
            gate = _classic_gate_delay(det, multiplier, row_calls,
                                       record=record)
            return floor if gate is None else min(0xFF, max(floor, gate))
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
    if not byte or byte >= TRIANGLE_VIBRATO_MAX_SHIFT:
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
                    row_calls: int = 0, effects: bool = False) -> dict:
    """{instrument index: (speed-table index, vibdelay)} for `--vibrato`.

    **A fixed-interval arpeggio record gets no vibrato where its mask is a
    duty cycle.** The player's octave block writes the frequency from the
    note table on every call, after the vibrato has moved it, so an
    arpeggiating note never sounds a vibrato in the original: MEASURED at
    v0.5.489 on a 30 s siddump, 0 frames off the base or octave pitch in
    3278 arp-note frames (Zoids) and 1581 (Master_of_Magic). Goattracker
    runs the instrument vibrato and `CMD_VIBRATO` on every call the
    wavetable does not write a note on (gplay.c, a note entry `goto
    PULSEEXEC`s past TICKNEFFECTS and zeroes `vibtime`; a delay entry `goto
    TICKNEFFECTS`). The parity mask's shapes write a note on every call and
    silence it that way; `fixed_arp_duty_entries` holds its runs on delay
    entries, and with the vibrato left in the first cut put 600 vibrato
    frames on Zoids' arp notes against the original's 0 (`bend` 0.91 ->
    8.13). So such a record is skipped here, which also keeps it out of
    `_vibrato_command_pass` and `_expanding_vibrato_pass`, both of which
    read this dict. Gated on `effects` like every other read of the +7
    byte, and on the duty mask, so the parity files' bytes do not move.

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
    delay = _vibrato_delay(det, mult, commanded=vibrato_command,
                           row_calls=row_calls)
    # A gate the player stores per instrument (detect.VibratoGate.table) is
    # a delay per record; every other file has one delay for all of them.
    per_record = (det.vibrato_gate is not None
                  and det.vibrato_gate.table is not None)
    data = sid.data
    duty_mask = (_gw_primitives.fixed_arp_mask(sid, det)
                 if effects and det.arp_fixed_up and det.effect_arp else None)
    if duty_mask is not None and duty_mask[0] == FIXED_ARP_PARITY_MASK:
        duty_mask = None
    out: dict = {}
    overwritten = 0
    for i in range(max(instr_used - lead, 0)):
        base = det.instr_start + i * det.instr_stride + offset
        if base >= len(data):
            continue
        effect = det.instr_start + i * det.instr_stride + 7
        if (duty_mask is not None and effect < len(data)
                and data[effect] & 0x04):
            overwritten += 1
            continue
        entry = entry_of(data[base])
        if entry is None:
            continue
        if entry not in speed_table:
            if len(speed_table) >= _gw_constants.GT_MAX_TABLELEN:
                continue
            speed_table.append(entry)
        out[i] = (speed_table.index(entry) + 1,
                  _vibrato_delay(det, mult, commanded=vibrato_command,
                                 row_calls=row_calls, record=i)
                  if per_record else delay)
    if log and out:
        log(f"Instrument vibrato......: {len(out)} of "
            f"{max(instr_used - lead, 0)} record(s), "
            f"{len({v[0] for v in out.values()})} speed-table entry(ies) "
            f"({engine})"
            + (f", {overwritten} arpeggio record(s) the octave block "
               f"overwrites" if overwritten else ""))
    return out
