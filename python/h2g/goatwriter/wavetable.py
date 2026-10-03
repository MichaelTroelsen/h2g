"""Wavetable entries, drum entries and the wavetable layout (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from collections import (Counter)
from typing import (List, Optional)

from ..detect import (Detection)
from ..sidfile import (SidFile)
from .constants import (DEFAULT_FORMAT, DRUM_DEEPEN_MARGIN,
                        DRUM_MAX_SWEEP_STEPS, _drum_speed,
                        EFFECT_PITCH_SEQ_MASK, EFFECT_SFX_DRUM_MASK,
                        FIXED_ARP_PARITY_MASK, FORMAT_GTS5, NOISE_TICK_FRAMES,
                        RISE_SHIFT, SPEED_NOTE_RELATIVE,
                        WAVE_ENTRIES_PER_INSTR, WAVE_JUMP, WAVE_MAX_DELAY,
                        WAVE_NOISE_GATEOFF, WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from .instruments import (_table_length_byte)
from .primitives import (_arp_relative, _first_frame_lead, _gate_calls,
                         _note_freq, _rate_shift, _wave_hold_byte)
from .arpeggio import (fixed_arp_duty_entries, gateoff_nibble_arp_budget_pair,
                       gateoff_nibble_arp_entries, _half_cycle,
                       nibble_arp_counter_test, nibble_arp_entries,
                       nibble_arp_first_half, nibble_arp_half_calls,
                       nibble_arp_half_cycle, nibble_arp_up,
                       _nibble_gate_shape, unticked_arp_octave_entry)
from .attack import (_counter_gate_restore_call, _fixed_attack_note,
                     _note_alternate_note, _two_stage_entries,
                     _two_stage_frames, _two_stage_pitch_seq_entries,
                     _voice_two_stage_entries, _wave_alternate_entries)
from .drums import (_arp_block, _arp_offsets, _sfx_drum_entries)
from .notes import (_drum_steps_safe, _pitch_seq_entries, _pitch_seq_notes,
                    _pitch_seq_phase_notes, _pitch_seq_phased_entries)
from .wave_program import (_wave_program_entries)
from . import constants as _gw_constants
from . import primitives as _gw_primitives
from . import tempo as _gw_tempo
from . import arpeggio as _gw_arpeggio
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
                       gate_skip: Optional[int] = None,
                       arp_phase: Optional[int] = None,
                       arp_mask: Optional[tuple] = None,
                       arp_step_calls: Optional[int] = None,
                       hold_attack: bool = False,
                       pitch_phase: Optional[tuple] = None,
                       arp_tie_row: Optional[int] = None,
                       wave_alternate: bool = False,
                       log=None,
                       arp_gate_phase: Optional[int] = None) -> tuple:
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
    # The direction, where the nibble block picks it per record (only
    # Formula_1_Simulator's opcode-spelled block does): None elsewhere.
    arp_up = (nibble_arp_up(sid, det, arp_note)
              if effects and not arp_fixed else None)

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
                        multiplier, budget, written=no_test_restart,
                        frames_per_step=det.pitch_seq.frames_per_step,
                        phases=pitch_phase,
                        phase_notes=(None if not pitch_phase else
                                     _pitch_seq_phase_notes(sid, det, i)))
                    if both is not None:
                        return both
                    if log:
                        log(f"Two-stage + pitch-seq.: record {i} "
                            f"(effect ${arp_style:02X}) does not fit its "
                            f"{budget}-entry budget; it keeps the attack "
                            f"waveform and LOSES its arpeggio")
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
            # The other four `atkpitch` rows -- Knucklebusters, Deep_Strike,
            # Sanxion and Food_Feud -- could not reach this code through
            # v0.5.486: all four have `det.wave_program < 0`, and that array
            # was where `_fixed_attack_note` read the note index. It now reads
            # the handler's own operand (`det.fixed_pitch_index`), which all
            # four carry; Food Feud's voice 3 went from 36 ties to 1351
            # against the original's 1396 on that change alone.
            # A counter vibrato gate keeps the fixed pitch to frame `gate`
            # (`_counter_gate_restore_call`); gated on `effects` like every
            # other read of the record's effect and vibrato bytes.
            two = _two_stage_entries(wave, data[at], frames, multiplier,
                                     attack_note=(
                                         None if arp_style & EFFECT_SFX_DRUM_MASK
                                         else _fixed_attack_note(sid, det, i)),
                                     budget=budget,
                                     written=no_test_restart,
                                     hold_attack=hold_attack,
                                     start=start,
                                     restore_call=(
                                         _counter_gate_restore_call(
                                             sid, det, i, multiplier,
                                             no_test_restart)
                                         if effects else None))
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
        # The player's phase, where `pitch_seq_phases` could carry it for this
        # instrument; otherwise the modal rotation below, as before.
        if pitch_phase and start is not None and wave & 0xF0:
            phase_notes = _pitch_seq_phase_notes(sid, det, i)
            if phase_notes is not None:
                phased = _pitch_seq_phased_entries(phase_notes, pitch_phase,
                                                   wave, multiplier, start,
                                                   budget)
                if phased is not None:
                    return phased
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
        # Bust, Chicken Song; re-counted by a forced-on corpus byte-hash at
        # v0.5.494 + uncommitted tree, 1dde44a, it moves exactly those 2 of
        # 89 converting files) -- is emitted ONLY under the per-song
        # `wave_alternate` option, default off. The emission is the player's
        # own derivation, read off `detect.WAVE_ALT_NOISE_SHAPE`:
        # `AND #$07 / ORA #$80`, noise keeping the voice's control bits.
        elif wave_alternate and det.wave_alternate_noise:
            alt_byte = (wave & 0x07) | 0x80
        # MEASURED AT 1dde44a + uncommitted tree, -t 180, under presets
        # (`fidelity.measure`, `_preset_opts`), option off -> on:
        #
        #   Chicken_Song      wave 88.3 -> 83.5%   noise 2556 -> 3780
        #                     (orig 4188)          melody 61.5 / seq 62.2 /
        #                     pitch 77.4 / onset 69.2% / attacks 2006 (orig
        #                     2000) / vib 0.30 -- all EXACTLY unmoved
        #   Hollywood_or_Bust melody 60.5 -> 49.0%  seq 58.8 -> 47.2%
        #                     pitch 85.2 -> 83.6%   wave 83.3 -> 72.2%
        #                     vib 0.27 -> 0.13      noise 0 -> 2998 (orig 4500)
        #                     nrun - -> 100%        attacks 3254 (orig 3255)
        #
        # Two populations, so one switch for the corpus is wrong either way:
        # unconditionally it ships Hollywood's -11.5pp of melody. The earlier
        # table here (0aa0d5c, a 60 s window: Chicken_Song `wave 84.1 ->
        # 77.0%  noise 0 -> 545 (orig 654)`) is superseded, not contradicted --
        # the Chicken_Song baseline has since gained noise of its own.
        #
        # **The search does not adopt it on either file** (presets.py's
        # `wave_alternate` entry in EXCLUDED_FROM_ALWAYS has the run).
        # Chicken_Song's candidate moves the noise PITCH onto the original's
        # (ours 14148 -> 5614 against 5611), but the search's per-frame
        # `onset_frame_agreement` falls 0.808 -> 0.769 and `gave_back` vetoes
        # it; the report's per-instrument `onset` column does not move. So the
        # adoption is a hand-recorded, listening one.
        # H2G-CONVERSION-METHOD.md section 7.iiii still carries the 0aa0d5c
        # numbers -- outside this task's declared paths.
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
    # A ticked fixed-interval record at -S1 whose phase is known: the octave
    # alternation is carried on the tick entries' right side as well as the
    # tails', so it starts on the original's frame rather than after the tick.
    phased = False
    if tick:
        # **DROPPING THIS GATE BIT IS REFUSED, and the reason is measured over
        # the population it reaches -- 33 of the 89 corpus songs at f0fd20c.**
        # Action Biker's drum opens THREE gated frames where its original opens
        # one (`09 | 81 81 81 80 ...` against `40 | 81 80 80 80 ...`), and
        # forcing these noise entries to a bare `$80` is the obvious repair.
        # A/B'd at -t 60 over all 33 reached files, it fails twice over:
        #
        #   * it does not fix the motivating defect. Action_Biker's
        #     `noise_run_agreement` stays 0.0, `noise_run_matched` 0 of 1 and
        #     `our_noise_frames` 682 against the original's 744 -- IDENTICAL in
        #     both arms. The run LENGTH is what is wrong there (62 runs of 11
        #     frames against the original's 12) and the leading gate bit is not
        #     what sets it.
        #   * and it costs melody on seven files, up to **-31.8pp**:
        #     One_Man_and_his_Droid 100.0 -> 68.2, Spellbound 95.4 -> 72.7,
        #     Phantoms_of_the_Asteroid 100.0 -> 92.9, Proteus 89.4 -> 81.8,
        #     Game_Killer 100.0 -> 97.4, Chimera 99.1 -> 98.5, Warhawk
        #     89.5 -> 89.3; Deep_Strike also loses a little `gate`.
        #
        # It DOES improve `gate` broadly (21 files better and nothing else
        # worse -- Commando 42.7 -> 57.6, Crazy_Comets 58.7 -> 77.4, Warhawk
        # 88.5 -> 95.3), and `nrun` and `wave` move on NOT ONE of the 33. So
        # the trade is a real gate gain against a real melody loss, and this
        # repo does not pay melody for register agreement -- the same rule
        # `fidelity_better`'s note-keeping guard enforces.
        #
        # **THE OLD REASON FOR REFUSING IT WAS WRONG AND IS RETRACTED.** The
        # standing note (v0.5.445) said "ACE_II IS THE LEAD: its original wants
        # 0 leading gated frames, the change gives it 0, and it got WORSE -- so
        # the OR controls something beyond the leading count". ACE_II is **not
        # in the reach**: its conversion is byte-identical with and without this
        # bit, so the change gave it nothing and cannot have made it worse. Its
        # per-offset gate agreement against the original is identical to the
        # digit in both arms on all three voices. Whatever moved ACE_II in that
        # earlier A/B, it was not this expression -- so do not go looking for a
        # second thing the OR controls; on this evidence it controls the leading
        # gated frames and nothing else.
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
        # **The noise tick was holding the base note, and the original does
        # not.** The drum block writes $D404 and the octave block then writes
        # the frequency, every frame, tick included: Commando's original reads
        # `b U b U` from the frame after the attack on every octave onset
        # (`bUbUbUbUbUbU` x32 on voice 0), and this shape put the first octave
        # on entry 4, after both tick entries -- `0 0 0 0 1 0 1` against the
        # original's `0 1 0 1`, a swing that is wrong on EVERY frame of every
        # note. The phase is the note's attack-frame parity
        # (`fixed_arp_phases`); with it known, each tick entry is one frame --
        # a delay could not alternate -- and carries the octave where the
        # frame is odd. Only where the extra entries fit; otherwise the
        # unphased shape stands, as it does for every record the phase is not
        # known for. -S1 only: above it the tick is a delay of calls and the
        # shape is `ticked_arp_entries`', which carries the phase itself
        # (until v0.5.489 the loop below ran per call above -S1, SUMMARY
        # item 4 of the-seven-file-adc-0c-family).
        # `arp_phase` is the counter's residue on the attack frame since
        # v0.5.489 (`fixed_arp_phases`): for the parity mask, 0 puts the
        # first octave on offset 1 and 1 on offset 2. A duty mask never
        # reaches this shape -- `fixed_arp_duty_entries` below takes it.
        if (arp and arp_fixed and arp_phase is not None and multiplier == 1
                and (arp_mask is None or arp_mask[0] == FIXED_ARP_PARITY_MASK)
                and len(frame0) + extra + 5 <= budget):
            tl, tr = [noise] * (extra + 1), [0x00] * (extra + 1)
            phased = True
            arp_phase = 1 + (arp_phase & 1)
        tick = len(frame0) + len(tl) + 4 <= budget
    if tick:
        off = len(tl) + len(frame0) - 1
        # Two `tail` entries, mirroring the untimed shape's entries 1-2: the
        # arpeggio loops over the second of them and the entry after it, so
        # collapsing them to one puts the stop where the arpeggio's own
        # entries belong and the loop is never reached.
        left = frame0 + tl + [tail, tail, 0xFF, 0xFF]
        right = frame0_r + tr + [0x00, 0x00, 0x00, 0x00]
        if phased:
            # Entry k plays on frame k + 1 - len(frame0) after the attack
            # siddump names: with the lead, entry 0 is the record's waveform
            # on the frame the attack is read from (the test-bit frame before
            # it is silent to the trace); without it (`written`), the
            # instrument's firstwave owns frame 0 and entry 0 is frame 1. The
            # octave sits on every second frame from `arp_phase`, tails
            # included, and the two-entry loop keeps the parity.
            for k in range(len(frame0), len(frame0) + len(tl) + 2):
                if (k + 1 - len(frame0) - arp_phase) % 2 == 0:
                    right[k] = _arp_relative(arp_fixed, arp_note, arp_up)

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
        # A fixed-interval block dividing its counter by a DUTY mask ($02,
        # $04, $07) is a square wave in frames, not the one-call alternation
        # every shape below emits; `fixed_arp_duty_entries` unrolls it from
        # the record's phase (0, the reset value, where no phase could be
        # walked). Gated on `effects` like every other read of the +7 byte,
        # and on the mask NOT being Commando's `$01`, whose files keep their
        # bytes exactly: the corpus byte-hash at v0.5.489 named the nine
        # mask != $01 files and nothing else.
        # **The counter steps once a call that passes the outer gate**, and
        # that call is (O + 1) / O of the original's frames where the player
        # has one (`_gate_calls`, the rule `_voice_two_stage_entries` already
        # obeys): Game_Killer's step is 10 of our calls at its -S9, not 9,
        # or the duty runs a call a step ahead of the rows it was walked
        # against. No other duty file has a `SongSpeeds.skip`, and at -S1
        # the rounding leaves the step one call.
        if (effects and arp_fixed and arp_mask is not None
                and arp_mask[0] != FIXED_ARP_PARITY_MASK):
            duty = fixed_arp_duty_entries(
                wave, tail, arp_mask[0], arp_mask[1],
                0 if arp_phase is None else arp_phase,
                _arp_relative(arp_fixed, arp_note, arp_up),
                # A `tempo_duty_split` clone's own step; the record's otherwise.
                (arp_step_calls if arp_step_calls is not None
                 else _gate_calls(multiplier, gate_skip)), base_entry,
                budget, written=no_test_restart,
                tick=((WAVE_NOISE_GATEOFF | (wave & 0x01),
                       _noise_tick_frames(sid, det)) if tick else None),
                # A record played under tie chains locks its octave to the
                # row (`fixed_arp_tie_rows`); never a clone's own step.
                tie_row=arp_tie_row if arp_step_calls is None else None)
            if duty is not None:
                return duty
        # $13CD: alternate between the note and the note minus the high
        # nibble, one frame each. Readme p.794: right side $60-$7F is a
        # negative relative note, so $80-N is -N semitones.
        hold = _wave_hold_byte(multiplier, wave)
        # **The nibble dialect's half is the RECORD's, not a frame**
        # (`detect.nibble_arp_period`): the block masks its counter with `#$02`
        # (`#$04` in Proteus and Formula_1_Simulator) where the nibble is an
        # octave and `#$01` otherwise, and the counter steps on calls that
        # pass the outer gate. Measured on the originals at 60 s: Warhawk's
        # `$090E`/`$080C` and International_Karate's `$0A08`/`$0F0B` alternate
        # in runs of 2 and 3 frames, their other records in 1s and 2s -- where
        # every shape here held a half for exactly one frame. None (the old
        # one-frame half) for the fixed dialect and for Mozart.
        arp_half = (nibble_arp_half_calls(sid, det, arp_note, multiplier,
                                          gate_skip)
                    if effects and not arp_fixed else None)
        # Where the gated half is not a whole number of calls the rounded
        # one is a rate error (`nibble_arp_half_cycle`): loop its halves.
        arp_cycle = (nibble_arp_half_cycle(sid, det, arp_note, multiplier,
                                           gate_skip)
                     if effects and not arp_fixed else None)
        if arp_cycle is not None:
            arp_half = arp_cycle
        # A ticked record above -S1 gets its own shape: the tick once, then
        # a two-frame loop of `m` calls a half (`ticked_arp_entries`). Until
        # v0.5.489 it fell to the per-call loop below, which toggled the
        # octave `m` times a frame -- measured at 312 samples a frame on the
        # packed Last_V8 (75 of 399 frames carrying both notes, split at
        # the half frame), invisible to siddump. The phase is applied only
        # under the parity mask, exactly as the -S1 tick shape gates it: a
        # duty record only reaches here when `fixed_arp_duty_entries`
        # declined its budget, and its residue is not a parity.
        # The nibble dialect's ticked record, its phase walked
        # (`nibble_arp_phases`): the alternation runs through the tick, as
        # the original's does (`ticked_nibble_arp_entries`). Above -S1 only,
        # as `ticked_arp_entries` is; a half of one frame is `multiplier`
        # calls where `nibble_arp_half_calls` reads None.
        per = det.arp_nibble_period
        test = (nibble_arp_counter_test(sid, per)
                if per is not None else None)
        # Where the outer gate's skipped frame lands on a fixed counter
        # residue, the original's own frame runs (`nibble_gate_runs`): the
        # long half on the half the original stretches, every boundary on a
        # frame. Both phased shapes below take them in place of the evenly
        # spread halves; None keeps those.
        gate_shape = (_nibble_gate_shape(sid, det, arp_note, multiplier,
                                         gate_skip, arp_gate_phase)
                      if effects and not arp_fixed and arp_phase is not None
                      else None)
        if (tick and effects and not arp_fixed and multiplier > 1
                and arp_phase is not None and test is not None):
            mask = per.half(arp_note)
            half = arp_half if arp_half is not None else multiplier
            first_up, steps = nibble_arp_first_half(arp_phase, mask, test[1])
            first_calls = max(1, round(steps * (sum(_half_cycle(half))
                                                / len(_half_cycle(half)))
                                       / mask))
            if gate_shape is not None:
                first_up, first_calls, half = gate_shape
            shaped = _gw_arpeggio.ticked_nibble_arp_entries(
                frame0, frame0_r,
                sum(1 if b > WAVE_MAX_DELAY else b + 1 for b in tl),
                noise, tail, _arp_relative(arp_fixed, arp_note, arp_up), half,
                first_up, first_calls,
                base_entry,
                budget)
            if shaped is not None:
                return shaped
        if tick and (hold is not None or arp_half is not None):
            shaped = _gw_arpeggio.ticked_arp_entries(
                frame0, frame0_r, tl, tr, noise, tail,
                _arp_relative(arp_fixed, arp_note, arp_up), multiplier, base_entry,
                budget,
                arp_phase=(arp_phase if arp_fixed and arp_phase is not None
                           and (arp_mask is None
                                or arp_mask[0] == FIXED_ARP_PARITY_MASK)
                           else None),
                half_calls=arp_half)
            if shaped is not None:
                return shaped
        if arp_half is not None and not tick and tail == wave:
            rel = _arp_relative(arp_fixed, arp_note, arp_up)
            # The walked residue places the first interval frame, as it does
            # for the ticked record above (`nibble_arp_first_half`); the run
            # is in counter steps, converted at the half's own call rate.
            # Where the attack's frame and that run make exactly one half on
            # the base note, the unphased shape already plays it, and keeps
            # its bytes. Over `budget` the unphased shape stands.
            if arp_phase is not None and test is not None:
                mask = per.half(arp_note)
                first_up, steps = nibble_arp_first_half(arp_phase, mask,
                                                        test[1])
                cyc = _half_cycle(arp_half)
                first_calls = max(1, round(steps * (sum(cyc) / len(cyc))
                                           / mask))
                halves = arp_half
                if gate_shape is not None:
                    first_up, first_calls, halves = gate_shape
                frame0, frame0_r = _first_frame_lead(
                    wave, multiplier, force=True, written=no_test_restart)
                lead_calls = 0 if no_test_restart else max(1, multiplier)
                if not (isinstance(halves, int) and not first_up
                        and lead_calls + first_calls == halves):
                    shaped = nibble_arp_entries(
                        wave, rel, halves, base_entry, budget,
                        phase=(frame0, frame0_r, first_up, first_calls))
                    if shaped is not None:
                        return shaped
            shaped = nibble_arp_entries(wave, rel, arp_half, base_entry, budget)
            if shaped is not None:
                return shaped
        # The gate-off tail cannot loop through the attack, so it has its own
        # shape (`gateoff_nibble_arp_entries`); until then it fell to the
        # per-call loop below and toggled every play call above -S1.
        if arp_half is not None and not tick and tail != wave:
            shaped = gateoff_nibble_arp_entries(
                wave, tail, _arp_relative(arp_fixed, arp_note, arp_up),
                arp_half, base_entry, budget)
            if shaped is None:
                pair = gateoff_nibble_arp_budget_pair(arp_half)
                shaped = gateoff_nibble_arp_entries(
                    wave, tail, _arp_relative(arp_fixed, arp_note, arp_up),
                    pair, base_entry, budget)
                if shaped is not None and log:
                    cyc = _half_cycle(arp_half)
                    log(f"Gate-off nibble arpeggio: record {i} halves "
                        f"{cyc} do not fit its {budget}-entry budget; it "
                        f"alternates {pair} calls instead")
            if shaped is not None:
                return shaped
        if hold is None or tail != wave or tick:
            # -S1: a call is a frame, so the plain two-entry loop is already
            # at the player's rate. A ticked record lands here too: at -S1,
            # where a call is a frame; above it only where
            # `ticked_arp_entries` found no room, since the multiplier shape
            # below loops back to entry 0, which would replay the noise tick
            # once per arpeggio cycle.
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
                if not phased:
                    # **The unticked -S1 shape hard-coded offset 2 until
                    # v0.5.490.** Entry k plays on frame k after the attack
                    # (k + 1 where `written`: the firstwave owns frame 0, as
                    # the tick shape's empty lead reads it), and the loop
                    # over entries 1-2 keeps parity, so the octave goes on
                    # whichever of the two shares the parity of the first
                    # octave-up offset -- `1 + (residue & 1)`, exactly as the
                    # tick shape above and `ticked_arp_entries` read the
                    # residue. Parity mask only, the residue known, -S1 only
                    # (above it the loop is per call and the phase is the
                    # ticked shape's); everything else keeps entry 2. The
                    # corpus byte-hash at v0.5.490 moved exactly the
                    # residue-0 files: Geoff_Capes_Strongman_Challenge,
                    # Gremlins and Hunter_Patrol.
                    octave_entry = 2 + off
                    if (not tick and multiplier == 1 and arp_fixed
                            and arp_phase is not None
                            and (arp_mask is None
                                 or arp_mask[0] == FIXED_ARP_PARITY_MASK)):
                        octave_entry = unticked_arp_octave_entry(
                            arp_phase, written=no_test_restart)
                    right[octave_entry] = _arp_relative(arp_fixed, arp_note, arp_up)
                right[3 + off] = second
            else:
                # `effects` off means "reproduce the VB6 original", and the
                # fixture encodes its shape: the arpeggio on entry 3 with the
                # jump returning to entry 2. Correcting the phase here broke 26
                # byte-exactness tests -- the same leak, with the same count, as
                # `arp_fixed_up` before it was gated.
                left[3 + off] = tail
                right[3 + off] = _arp_relative(arp_fixed, arp_note, arp_up)
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
            left[2], right[2] = tail, _arp_relative(arp_fixed, arp_note, arp_up)
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
        speeds = _gw_tempo.find_song_speeds(sid, det if det.can_convert else None)
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
        if len(speed_table) >= _gw_constants.GT_MAX_TABLELEN:
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
        if len(speed_table) >= _gw_constants.GT_MAX_TABLELEN:
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


def _loop_of(left: List[int], right: List[int], start: int) -> Optional[tuple]:
    """(loop start, jump index) of a block whose first jump loops back into
    it, both as indices into the block; None for a block that stops."""
    j = next((k for k, b in enumerate(left) if b == WAVE_JUMP), None)
    if j is None:
        return None
    t = right[j] - start
    if not 0 <= t < j:
        return None
    return t, j


def _shared_loop_block(block: tuple, start: int, entries: List[tuple],
                       record_start: int) -> tuple:
    """A phase clone's block with its loop replaced by a jump into its
    record's, where the two loops are the same cycle entered at different
    points -- which a residue is, for every shape that unrolls the counter's
    cycle (the duty loop, the parity shapes' two-entry loop). Checked, not
    assumed: the clone's loop entries must equal a rotation of the record's
    exactly, jumps aside; otherwise the block is returned whole.

    The jump costs no call (gplay.c reads a `$FF` on the entry after the one
    it executes), so the prefix followed by a jump to the record's entry `x`
    plays the record's loop from `x`, wraps at the record's own jump, and
    sounds what the clone's own loop would have. Game_Killer's -S9 duty
    blocks are 10-16 entries, and without this two of its eight clones did
    not fit the 255-entry table."""
    left, right = block
    mine = _loop_of(left, right, start)
    if mine is None:
        return block
    rl, rr = [], []
    k = record_start - 1
    while k < len(entries):
        rl.append(entries[k][0])
        rr.append(entries[k][1])
        if entries[k][0] == WAVE_JUMP:
            break
        k += 1
    theirs = _loop_of(rl, rr, record_start)
    if theirs is None:
        return block
    a, j = mine
    b, jr = theirs
    loop = list(zip(left[a:j], right[a:j]))
    ring = list(zip(rl[b:jr], rr[b:jr]))
    if len(loop) != len(ring) or WAVE_JUMP in left[a:j]:
        return block
    for x in range(len(ring)):
        if ring[x:] + ring[:x] == loop:
            return (left[:a] + [WAVE_JUMP],
                    right[:a] + [(record_start + b + x) & 0xFF])
    return block


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
                      real_firstwave_instruments: tuple = (),
                      arps: Optional[List[tuple]] = None,
                      arp_phases: Optional[dict] = None,
                      arp_gate_phases: Optional[dict] = None,
                      arp_tie_rows: Optional[dict] = None,
                      pitch_phases: Optional[dict] = None,
                      clones: Optional[List[tuple]] = None,
                      clone_starts: Optional[list] = None,
                      phase_clones: Optional[List[tuple]] = None,
                      phase_clone_starts: Optional[list] = None,
                      phase_probe: Optional[List[tuple]] = None,
                      attack_holds: Optional[List[int]] = None,
                      attack_hold_starts: Optional[list] = None,
                      wave_alternate: bool = False,
                      log=None) -> tuple:
    """(entries, starts, arp_starts) for the whole wavetable, laid out in order.

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

    `arps` (the interleaved engine's `$83`, see patterns.ILV_ARP) appends one
    block per distinct `(record, operand)` pair AFTER every instrument's, so no
    instrument's start moves and a file with no arpeggios lays out byte for
    byte as before. `arp_starts` is parallel to `arps`; a pair the table has no
    room for gets **no entry at all** rather than a truncated one, and
    `build_sng` clears the command that pointed at it -- a wavetable row is
    executed whatever happens to be in it, so a short block is worse than none.
    """
    entries: List[tuple] = []
    starts: List[int] = []
    for _ in range(lead):
        starts.append(len(entries) + 1)
        entries += [(0x09, 0x00), (0xFF, 0x00),
                    (0x00, 0x00), (0x00, 0x00), (0x00, 0x00)]
    n = max(instr_used - lead, 0)
    # The fixed-interval block's counter mask, read once for the file: a duty
    # mask ($02, $04, $07) sends every arpeggio record to
    # `fixed_arp_duty_entries`, the parity mask ($01) keeps the shapes below.
    # Gated on `effects` exactly as each record's read of the +7 byte is.
    arp_mask = (_gw_primitives.fixed_arp_mask(sid, det)
                if effects and det.arp_fixed_up else None)
    def record_entries(i: int, start: int, budget: int,
                       step: Optional[int] = None,
                       hold_attack: bool = False,
                       phase=None) -> tuple:
        # `phase` is a phase clone's residue: an int is the fixed arp's
        # (`arp_phase`), a tuple bit $10's phase cells (`pitch_phase`,
        # `pitch_seq_phase_split_plan`).
        pitch = phase if isinstance(phase, tuple) else None
        if pitch is not None:
            phase = None
        # Must agree with _write_instruments' own per-instrument decision, or
        # the wavetable's own first entry and the instrument record's
        # firstwave byte disagree about who writes frame 0 -- exactly the
        # mismatch that made real_firstwave_instruments alone (without this)
        # cost ACE_II melody 100% -> 88% instead of fixing it: the record's
        # byte writes the real waveform on frame 0 AND the wavetable's entry 0
        # still assumed a testbit lead-in and wrote its own, one frame later.
        gt_number = i + lead + 1
        instrument_written = no_test_restart or gt_number in real_firstwave_instruments
        return _wavetable_entries(sid, det, i, effects, fmt, speed_table,
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
                                  gate_skip=gate_skip,
                                  arp_phase=(phase if phase is not None
                                             else None if arp_phases is None
                                             else arp_phases.get(gt_number)),
                                  arp_mask=arp_mask,
                                  arp_step_calls=step,
                                  hold_attack=hold_attack,
                                  pitch_phase=(pitch if pitch is not None
                                               else None if pitch_phases is None
                                               else pitch_phases.get(
                                                   gt_number)),
                                  arp_tie_row=(None if arp_tie_rows is None
                                               else arp_tie_rows.get(
                                                   gt_number)),
                                  wave_alternate=wave_alternate,
                                  log=log,
                                  arp_gate_phase=(
                                      None if arp_gate_phases is None
                                      or phase is not None
                                      else arp_gate_phases.get(gt_number)))

    if phase_probe is not None:
        # `fixed_arp_phase_split_plan`'s question, asked before the table is
        # laid out: does (record, residue) emit anything but the record's own
        # block? Both at one start and the whole table's room, so only the
        # phase differs. Answered into `phase_probe`'s third slot.
        for k, (record, residue, _) in enumerate(phase_probe):
            i = record - lead - 1
            phase_probe[k] = (record, residue, 0 <= i < n and (
                record_entries(i, 1, _gw_constants.GT_MAX_TABLELEN, phase=residue)
                != record_entries(i, 1, _gw_constants.GT_MAX_TABLELEN)))
        return entries, starts, []
    for i in range(n):
        start = len(entries) + 1
        reserved = (n - i - 1) * WAVE_ENTRIES_PER_INSTR
        budget = max(WAVE_ENTRIES_PER_INSTR,
                     _gw_constants.GT_MAX_TABLELEN - len(entries) - reserved)
        left, right = record_entries(i, start, budget)
        starts.append(start)
        entries += list(zip(left, right))

    arp_starts: List[int] = []
    for record, operand in (arps or []):
        offsets = _arp_offsets(operand)
        start = len(entries) + 1
        block = None
        if offsets is not None and 0 <= record < len(starts) - lead:
            src = starts[record + lead] - 1
            block = _arp_block(entries[src:], offsets, multiplier, start)
        if block is None or start - 1 + len(block[0]) > _gw_constants.GT_MAX_TABLELEN:
            arp_starts.append(0)
            continue
        arp_starts.append(start)
        entries += list(zip(*block))
    # `tempo_duty_split_plan`'s clones, last, so no record's start moves: the
    # record's own entries at the clone's step. One that does not fit gets
    # start 0 and the caller points the clone at its record's block.
    for record, _clone, step in (clones or []):
        i = record - lead - 1
        start = len(entries) + 1
        block = None
        if 0 <= i < n and len(entries) < _gw_constants.GT_MAX_TABLELEN:
            block = record_entries(i, start, _gw_constants.GT_MAX_TABLELEN - len(entries),
                                   step)
        if block is None or start - 1 + len(block[0]) > _gw_constants.GT_MAX_TABLELEN:
            if clone_starts is not None:
                clone_starts.append(0)
            continue
        if clone_starts is not None:
            clone_starts.append(start)
        entries += list(zip(*block))
    # `fixed_arp_phase_split_plan`'s clones, after the tempo clones and for
    # the same reason: the record's own entries at the clone's residue. One
    # that does not fit, or whose block is the record's, gets start 0 and
    # the caller points it at its record's block.
    for record, _clone, residue in (phase_clones or []):
        i = record - lead - 1
        start = len(entries) + 1
        block = None
        if 0 <= i < n and len(entries) < _gw_constants.GT_MAX_TABLELEN:
            room = _gw_constants.GT_MAX_TABLELEN - len(entries)
            block = record_entries(i, start, room, phase=residue)
            if block == record_entries(i, start, room):
                block = None
            elif block is not None:
                # Its loop is the record's entered elsewhere, mostly: share it.
                block = _shared_loop_block(block, start, entries,
                                           starts[i + lead])
        if block is None or start - 1 + len(block[0]) > _gw_constants.GT_MAX_TABLELEN:
            if phase_clone_starts is not None:
                phase_clone_starts.append(0)
            if log:
                kind = ("pitch phase split" if isinstance(residue, tuple)
                        else "arp phase split")
                log(f"{kind}: clone of {record:02X} at residue "
                    f"{residue} has no block of its own")
            continue
        if phase_clone_starts is not None:
            phase_clone_starts.append(start)
        entries += list(zip(*block))
    # `_attack_hold_records`' second programs, after everything else for the
    # same reason: the record's own block with the fixed attack pitch held
    # (`hold_attack`), which `_attack_hold_pass` points the notes the
    # player's vibrato gate skips at. A record whose held block is the same
    # as its own (no fixed pitch reached it) gets start 0 and no entries.
    for i in (attack_holds or []):
        start = len(entries) + 1
        block = None
        if 0 <= i < n and len(entries) < _gw_constants.GT_MAX_TABLELEN:
            room = _gw_constants.GT_MAX_TABLELEN - len(entries)
            block = record_entries(i, start, room, hold_attack=True)
            if block == record_entries(i, start, room):
                block = None
        if block is None or start - 1 + len(block[0]) > _gw_constants.GT_MAX_TABLELEN:
            if attack_hold_starts is not None:
                attack_hold_starts.append(0)
            continue
        if attack_hold_starts is not None:
            attack_hold_starts.append(start)
        entries += list(zip(*block))
    return entries, starts, arp_starts


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
        entries, _, _ = _wavetable_layout(sid, det, instr_used, effects, fmt,
                                          table, multiplier, min_notes, lead)
    out.append(_table_length_byte(len(entries), "wave"))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)
