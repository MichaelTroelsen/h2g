"""build_sng: assembling the final .sng (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from typing import (List, Optional)

from ..detect import (Detection)
from ..sidfile import (SidFile)
from .constants import (CMD_SETPULSEPTR, CMD_SETWAVEPTR, CMD_TONEPORTA,
                        DEFAULT_FORMAT, FIRSTWAVE_TESTBIT, FORMAT_GTS5,
                        FORMATS, GATETIMER_LEGATO)
from .instruments import (_build_header, _instruments_used, record_envelope,
                          _table_length_byte, _write_instruments)
from .arpeggio import (apply_tempo_duty_edits, fixed_arp_phase_split_plan,
                       fixed_arp_phases, fixed_arp_tie_rows, nibble_arp_phases,
                       nibble_gate_phases, tempo_duty_split_plan)
from .pulse import (_pulse_layout, _write_pulsetable)
from .filters import (_classic_clearing_instruments, _filter_entries,
                      _highest_instrument_referenced,
                      _ilv_clearing_instruments, _ilv_filter_entries,
                      ilv_filter_routing_plan, _write_filtertable)
from .note_passes import (_attack_hold_pass, _attack_hold_records,
                          _expanding_vibrato_counter, _expanding_vibrato_pass,
                          legato_tie_clones, legato_tie_rows, note_bit7_rows,
                          past_table_drum_plan, _tied_instrument_envelopes,
                          _vibrato_command_pass)
from .vibrato import (_classic_gate_refine, _vibrato_layout)
from .wavetable import (_wavetable_layout, _write_wavetable)
from . import arpeggio as _gw_arpeggio
from . import pulse as _gw_pulse
from . import note_passes as _gw_note_passes
def _resolve_arp_pointers(patterns: List[List[int]], arp_starts: List[int],
                          log=None) -> List[List[int]]:
    """Turn each `CMD_SETWAVEPTR` operand from an `arps` index into a table row.

    The interleaved decoder emits the 1-based index of the `(record, operand)`
    pair, because the wavetable row is not known until the table has been laid
    out and the table cannot be laid out until the patterns say which pairs
    occur. That is the same two-stage shape `steps` and the speed table already
    have, one stage later; it is resolved HERE rather than by a scan of the
    finished bytes because nothing else in this writer emits command 8, so an
    unresolved operand would be indistinguishable from a real row and would
    point the player at whatever sits there.
    (`_attack_hold_pass` is the second emitter of command 8, and it writes
    resolved rows AFTER this has run, so nothing it places is read here.)

    A pair the layout declined (`arp_starts` entry 0) has its command CLEARED.
    Leaving it is the `$E0`-`$EF` failure one table over: a byte the player
    reads whatever it was meant to mean.
    """
    if not arp_starts:
        return patterns
    out, cleared, placed = [], 0, 0
    for pattern in patterns:
        rows = list(pattern)
        for k in range(0, len(rows) - 3, 4):
            if rows[k + 2] != CMD_SETWAVEPTR:
                continue
            idx = rows[k + 3] - 1
            row = arp_starts[idx] if 0 <= idx < len(arp_starts) else 0
            if row:
                rows[k + 3] = row & 0xFF
                placed += 1
            else:
                rows[k + 2] = rows[k + 3] = 0x00
                cleared += 1
        out.append(rows)
    if log is not None and (placed or cleared):
        log(f"Interleaved arpeggios...: {placed} row(s) on "
            f"{sum(1 for r in arp_starts if r)} wavetable block(s)"
            + (f", {cleared} declined for want of table room" if cleared else ""))
    return out


def _arp_phase_distinct(sid: SidFile, det: Detection, tracks, patterns,
                        instr_used: int, effects: bool, fmt: str, table,
                        multiplier, min_notes, lead, two_stage, sfx_drum,
                        wave_program, pitch_seq, note_rows, row_calls,
                        no_test_restart, voice_two_stage, instr_voices,
                        gate_skip, real_firstwave_instruments,
                        wave_alternate=False):
    """`fixed_arp_phase_split_plan`'s `distinct`: whether a record's block
    at a residue differs from its block at its own (`_wavetable_layout`'s
    `phase_probe`, with the arguments `build_sng` lays the table out with)."""
    arp_phases = fixed_arp_phases(sid, det, tracks, patterns)
    arp_tie_rows = fixed_arp_tie_rows(sid, det, tracks, patterns)
    pitch_phases = (_gw_arpeggio.pitch_seq_phases(sid, det, tracks, patterns)
                    if pitch_seq and fmt == FORMAT_GTS5
                    and det.pitch_seq is not None else None)

    def distinct(record: int, residue: int) -> bool:
        probe = [(record, residue, False)]
        _wavetable_layout(sid, det, instr_used, effects, fmt, list(table),
                          multiplier, min_notes, lead, two_stage, sfx_drum,
                          wave_program, pitch_seq, note_rows, row_calls,
                          no_test_restart, voice_two_stage, instr_voices,
                          gate_skip, real_firstwave_instruments, None,
                          arp_phases=arp_phases, arp_tie_rows=arp_tie_rows,
                          pitch_phases=pitch_phases, phase_probe=probe,
                          wave_alternate=wave_alternate)
        return bool(probe[0][2])
    return distinct


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
              hard_restart_frames: int | None = None,
              compact_instruments: bool = False,
              pulse_plan: tuple | None = None,
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
              instr_row_calls: Optional[dict] = None,
              gate_skip: Optional[int] = None,
              wide_hard_restart: bool = False,
              max_hard_restart: bool = False,
              real_firstwave_instruments: tuple = (),
              arps: Optional[List[tuple]] = None,
              wave_alternate: bool = False,
              ilv_filter_routing: bool = False) -> bytes:
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
    lead = 0 if compact_instruments else 1
    instr_used = _instruments_used(det, log, lead)
    # The decoder's bit-7 note rows (`patterns.PatternList`), read before any
    # pass below rebinds `patterns` to a plain list. Present only where a tie
    # is spelled under `note_flag`; see `legato_tie_clones`.
    known_bit7 = getattr(patterns, "note_bit7", None)
    legato = known_bit7 is not None and _gw_note_passes.legato_tie_family(sid, det)
    decoded = getattr(patterns, "decoded", 0)
    # Before the orderlists are written, because its pattern copies repoint
    # them; its instrument bytes wait for `apply_tempo_duty_edits`, last.
    duty_split = tempo_duty_split_plan(sid, det, tracks, patterns, effects,
                                       lead, instr_used, multiplier,
                                       gate_skip, log)
    if duty_split is not None:
        tracks, patterns = duty_split.tracks, duty_split.patterns
    # The per-note fixed-arp phase, planned here for the same reason and
    # with its bytes applied last beside the tempo split's. Not on a file the
    # tempo split already edits: both would rename the same instrument
    # columns, and neither plan sees the other's bytes.
    phase_split = None
    if duty_split is None and effects and det.arp_fixed_up and det.effect_arp:
        phase_split = fixed_arp_phase_split_plan(
            sid, det, tracks, patterns, effects, lead, instr_used,
            instr_used + 1,
            distinct=_arp_phase_distinct(
                sid, det, tracks, patterns, instr_used, effects, fmt, table,
                multiplier, min_notes, lead, two_stage, sfx_drum,
                wave_program, pitch_seq, note_rows, row_calls,
                no_test_restart, voice_two_stage, instr_voices, gate_skip,
                real_firstwave_instruments, wave_alternate=wave_alternate),
            log=log)
    # Bit $10's divided phase gets the same split, in the same slot: its
    # clones are made, numbered and renamed exactly as the fixed arp's
    # (`pitch_seq_phase_split_plan`), their third slot a phase tuple where
    # the arp's is a residue. No corpus file has both clocks.
    if (phase_split is None and duty_split is None and pitch_seq
            and fmt == FORMAT_GTS5 and det.pitch_seq is not None):
        phase_split = _gw_arpeggio.pitch_seq_phase_split_plan(
            sid, det, tracks, patterns, lead, instr_used, instr_used + 1,
            distinct=_arp_phase_distinct(
                sid, det, tracks, patterns, instr_used, effects, fmt, table,
                multiplier, min_notes, lead, two_stage, sfx_drum,
                wave_program, pitch_seq, note_rows, row_calls,
                no_test_restart, voice_two_stage, instr_voices, gate_skip,
                real_firstwave_instruments, wave_alternate=wave_alternate),
            log=log)
    if phase_split is not None:
        tracks, patterns = phase_split.tracks, phase_split.patterns
    # The interleaved dialect's per-voice routing as CMD_SETFILTERCTRL
    # (`ilv_filter_routing_plan`). Here, before the orderlists are written,
    # because its pattern copies repoint them -- and so the passes below that
    # fill free command columns see its rows as taken. Not beside the tempo
    # or phase split, whose instrument edits are keyed by pattern number and
    # would miss its copies; and only where the classic reader finds no
    # table, the branch `_ilv_filter_entries` is consulted on below.
    ilv_routing = None
    if (ilv_filter_routing and filters and det.ilv_filter is not None
            and duty_split is None and phase_split is None):
        routing_base = 1 if compact_instruments else 2
        classic, _ = _filter_entries(
            sid, det, instr_used, lead, multiplier,
            _classic_clearing_instruments(sid, det, tracks, patterns,
                                          routing_base))
        if not classic:
            ilv_routing = ilv_filter_routing_plan(
                sid, det, tracks, patterns, instr_used, multiplier,
                routing_base, log)
        if ilv_routing is not None:
            tracks, patterns = ilv_routing.tracks, ilv_routing.patterns
    out.append((len(tracks) // 3) & 0xFF)

    for track in tracks:
        out.append((len(track) - 1) & 0xFF)
        out += bytes(track)

    # The filter and pulse tables are both built before the instruments,
    # because each instrument record carries the table step it starts on --
    # but both are written after them, with the other tables. A swept
    # instrument's pulse program is longer than a static one's, so that start
    # position is not a stride either.
    if filters:
        filter_entries, filter_ptrs = _filter_entries(
            sid, det, instr_used, lead, multiplier,
            _classic_clearing_instruments(
                sid, det, tracks, patterns, 1 if compact_instruments else 2))
        if not filter_entries and ilv_routing is not None:
            # The routing rides in the patterns; the table carries only the
            # sweeps (and, "shared", the one passband block).
            filter_entries, filter_ptrs = (ilv_routing.entries,
                                           ilv_routing.pointers)
        elif not filter_entries:
            # The interleaved dialect, consulted only where the classic
            # reader found nothing. The two populations are disjoint.
            filter_entries, filter_ptrs = _ilv_filter_entries(
                sid, det, instr_used, multiplier,
                _ilv_clearing_instruments(
                    sid, det, tracks, patterns,
                    1 if compact_instruments else 2))
    else:
        filter_entries, filter_ptrs = [], {}
    if pulse_plan is not None:
        # Precomputed by convert() under --pulse-phase: the phase entries had
        # to exist BEFORE the patterns were patched, because CMD_SETPULSEPTR
        # names table indices. Built by build_pulse_phase_table with this same
        # lead, so the starts line up with the records exactly as below.
        pulse_entries, pulse_starts = pulse_plan
    else:
        pulse_entries, pulse_starts = _pulse_layout(
            sid, det, instr_used, pulse, multiplier, log, lead=lead,
            usage=_gw_pulse.pulse_usage(tracks, patterns, lead))
    # Before the records, because each one carries its speed-table index -- and
    # into `table`, which the wavetable also grows and the file writes last.
    vib_ptrs = _vibrato_layout(sid, det, instr_used, vibrato, fmt, multiplier,
                               table, log, lead=lead,
                               vibrato_command=vibrato_command,
                               row_calls=row_calls, effects=effects)
    # Before the vibrato command pass, which fills only free rows and must
    # see the envelope rows as taken; the envelopes are the records' own
    # (`record_envelope`), so the pass needs nothing the records write.
    envelopes = {i + lead + 1: record_envelope(sid.data, det, i,
                                               sustain_exact, cut_release)
                 for i in range(max(instr_used - lead, 0))}
    # The ties `legato_tie_clones` will respell, fixed here so the envelope
    # pass leaves them alone: a legato clone loads its own envelope.
    legato_rows = (legato_tie_rows(
        patterns, note_bit7_rows(patterns, known_bit7, decoded))
        if legato else set())
    if legato_rows and multiplier > 1:
        # gt2reloc cannot pack a legato instrument at -S2 and above: it
        # maps the instruments (greloc.c:362-370, legato last) and THEN
        # bumps `numnohr` "for multispeed stability" (:811-815), so
        # FIRSTLEGATOINSTR (:1134) lands one past the first legato record,
        # which player.s then plays as a plain no-HR note -- a gate-off at
        # the fetch and a re-attack. Star_Paws (-S2) voice 1: siddump
        # attacks 572 -> 967 against the original's 571, every one on that
        # first clone. The editor's gplay.c:930 tests the bit itself and
        # has no such slip; the packed .sid is a deliverable, so the old
        # spelling stays.
        if log:
            log(f"Legato tie..............: {len(legato_rows)} tie row(s) "
                f"kept CMD_TONEPORTA -- -S{multiplier} packs the first "
                "legato instrument as no-HR (greloc.c:811-815)")
        legato_rows = set()
    patterns = _tied_instrument_envelopes(patterns, envelopes, tracks, log,
                                          skip=legato_rows)
    # After the layout because it needs the speed-table indices it allocated,
    # and before the records because it decides what goes in their byte 5.
    # Triangle-dialect only: it is that player's length gate this expresses,
    # and the other two engines have no gate to express (_vibrato_delay).
    if vibrato_command and vib_ptrs and det.triangle_vibrato is not None:
        vib_ptrs = _vibrato_command_pass(det, patterns, vib_ptrs, lead, log,
                                         tracks=tracks)
    # The classic engine's age-growing variant, five files: the instrument
    # entry stays the shallow first-frames level and the hold rows carry the
    # swell as `4xy` commands. Behind `vibrato_command` because commands are
    # the mechanism, and only where the routine is the age-adding one --
    # `_expanding_vibrato_counter` returns None for the 51 static-shaped
    # files, whose bytes this must not move.
    if (vibrato_command and vib_ptrs and det.vibrato_offset is not None
            and _expanding_vibrato_counter(sid, det) is not None):
        _expanding_vibrato_pass(sid, det, tracks, patterns, vib_ptrs, table,
                                lead, multiplier, row_calls,
                                instr_row_calls=instr_row_calls, log=log)
    # The fixed-interval octave's phase per instrument, from the finished
    # orderlists: a note's attack-frame residue is static, and the tick
    # entries carry the octave from the original's frame (`fixed_arp_phases`)
    # -- as does the duty shape (`fixed_arp_duty_entries`), at any rate.
    # Gated exactly as the record's own read of the +7 byte is -- `effects`.
    # The walk is in frames and does not depend on the rate: the -S1 tick
    # shape and `ticked_arp_entries` above it read the same residue.
    # The nibble dialect's counter gets the same walk (`nibble_arp_phases`):
    # its ticked records run the alternation through the noise tick from it
    # (`ticked_nibble_arp_entries`), its unticked ones start their first
    # interval on the residue's frame (`nibble_arp_entries`' `phase`), and
    # every other reader of `arp_phase` is gated on `arp_fixed`.
    arp_phases = (fixed_arp_phases(sid, det, tracks, patterns)
                  if effects and det.arp_fixed_up
                  else nibble_arp_phases(sid, det, tracks, patterns)
                  if effects and det.arp_nibble_period is not None else None)
    # The same walk kept modulo the outer gate's reload too, where the
    # nibble counter's `INC` is behind it: the attack's place in the gate's
    # cycle, from which `nibble_gate_runs` puts the original's skipped frame.
    arp_gate_phases = (nibble_gate_phases(sid, det, tracks, patterns,
                                          gate_skip)
                       if effects and not det.arp_fixed_up
                       and det.arp_nibble_period is not None and gate_skip
                       else None)
    # The duty records played under tie chains, and their one row length:
    # those lock the octave to the row (`fixed_arp_tie_row_entries`).
    arp_tie_rows = (fixed_arp_tie_rows(sid, det, tracks, patterns)
                    if effects and det.arp_fixed_up else None)
    # Bit $10's global phase, the same walk: only where the counter is
    # divided and its clock is read (`_pitch_seq_clock` -- Food_Feud), and
    # only behind the option that emits the arpeggio at all.
    pitch_phases = (_gw_arpeggio.pitch_seq_phases(sid, det, tracks, patterns)
                    if pitch_seq and fmt == FORMAT_GTS5
                    and det.pitch_seq is not None else None)
    clone_starts: List[int] = []
    phase_clone_starts: List[int] = []
    attack_holds = _attack_hold_records(sid, det, instr_used, lead, effects,
                                        two_stage)
    if attack_holds:
        # Dry run: only a record some short note will point at gets a block.
        used: set = set()
        _attack_hold_pass(patterns, {i + lead + 1: 1 for i in attack_holds},
                          det.vibrato_gate.gate, tracks, used=used)
        attack_holds = [i for i in attack_holds if i + lead + 1 in used]
    attack_hold_starts: List[int] = []
    # Before the records, because each one carries the wavetable step it
    # starts on -- and those starts are no longer a stride.
    wave_entries, wave_starts, arp_starts = _wavetable_layout(
        sid, det, instr_used, effects,
        fmt, table, multiplier,
        min_notes, lead, two_stage,
        sfx_drum, wave_program,
        pitch_seq,
        note_rows, row_calls,
        no_test_restart,
        voice_two_stage,
        instr_voices, gate_skip,
        real_firstwave_instruments, arps,
        arp_phases=arp_phases,
        arp_gate_phases=arp_gate_phases,
        arp_tie_rows=arp_tie_rows,
        pitch_phases=pitch_phases,
        clones=duty_split.clones if duty_split is not None else None,
        clone_starts=clone_starts,
        phase_clones=(phase_split.clones if phase_split is not None
                      else None),
        phase_clone_starts=phase_clone_starts, attack_holds=attack_holds,
        attack_hold_starts=attack_hold_starts,
        wave_alternate=wave_alternate, log=log)
    patterns = _resolve_arp_pointers(patterns, arp_starts, log)
    # After the arpeggio pointers are resolved (they own every CMD_SETWAVEPTR
    # operand until then) and before the pulse budget, which must see every
    # command column filled.
    if attack_holds:
        patterns = _attack_hold_pass(
            patterns,
            {i + lead + 1: start
             for i, start in zip(attack_holds, attack_hold_starts) if start},
            det.vibrato_gate.gate, tracks, log)
    # The past-table drum (`past_table_drum_plan`): a KEYOFF the decoder
    # wrote for a `$0000` note becomes a note on a variant of its record
    # whose pitched frames are silent and whose absolute ones sound. After
    # the attack-hold pass, whose notes it must not become, and before the
    # pulse budget, which must see the finished rows. Not beside the tempo
    # or phase split: both rename instrument columns after this point.
    drum_variants: List[tuple] = []
    drum_starts: List[int] = []
    if duty_split is None and phase_split is None:
        patterns, drum_variants = past_table_drum_plan(
            sid, det, patterns, tracks, wave_entries, wave_starts, lead,
            instr_used, instr_used + 1, log)
        for _record, _variant, block in drum_variants:
            drum_starts.append(len(wave_entries) + 1)
            wave_entries = wave_entries + block
    if pulse_plan is not None:
        # Last, after every pass that writes a command column: the packed
        # size is a property of the finished rows and nothing else.
        patterns = _gw_pulse.budget_pulse_phase_commands(patterns, CMD_SETPULSEPTR, log)
    vib_ptrs = _classic_gate_refine(det, vib_ptrs, wave_entries, wave_starts,
                                    multiplier, row_calls, instr_row_calls,
                                    lead, no_test_restart,
                                    real_firstwave_instruments)
    instr_at = len(out)
    _write_instruments(out, sid, det, instr_used, pulse_starts,
                       sustain_exact, no_hard_restart, filter_ptrs, vib_ptrs,
                       cut_release=cut_release,
                       lead=lead, wave_starts=wave_starts,
                       no_test_restart=no_test_restart,
                       multiplier=multiplier, row_calls=row_calls,
                       wide_hard_restart=wide_hard_restart,
                       max_hard_restart=max_hard_restart,
                       hard_restart_frames=hard_restart_frames,
                       real_firstwave_instruments=real_firstwave_instruments,
                       instr_row_calls=instr_row_calls)
    written_instr = instr_used
    if duty_split is not None:
        # Each clone is its record's finished bytes with its own wavetable
        # start -- envelope, pulse, filter, vibrato and name all the record's.
        for (record, _clone, _step), wstart in zip(duty_split.clones,
                                                   clone_starts):
            rec = instr_at + 1 + (record - 1) * 25
            clone = bytearray(out[rec:rec + 25])
            if wstart:
                clone[2] = wstart & 0xFF
            out += clone
            written_instr += 1
        out[instr_at] = written_instr
    if phase_split is not None:
        # The same for each phase clone: its record's bytes, its own block.
        for (record, _clone, _res), wstart in zip(phase_split.clones,
                                                  phase_clone_starts):
            rec = instr_at + 1 + (record - 1) * 25
            clone = bytearray(out[rec:rec + 25])
            if wstart:
                clone[2] = wstart & 0xFF
            out += clone
            written_instr += 1
        out[instr_at] = written_instr
    if drum_variants:
        # Each past-table drum variant: its record's bytes -- the pulse
        # pointer among them, so the note-on reseeds the pulse as the
        # original's does -- with its own wavetable block.
        for (record, _variant, _block), wstart in zip(drum_variants,
                                                      drum_starts):
            rec = instr_at + 1 + (record - 1) * 25
            clone = bytearray(out[rec:rec + 25])
            clone[2] = wstart & 0xFF
            out += clone
            written_instr += 1
        out[instr_at] = written_instr
    # The split clones' instrument bytes, last of everything that keys on an
    # instrument number -- and before the legato clones, which are made from
    # the instrument each tie finally plays.
    patterns = apply_tempo_duty_edits(patterns, duty_split, log)
    patterns = apply_tempo_duty_edits(patterns, phase_split, log)
    if legato_rows:
        # Each GT number's source record, for the clone's real firstwave.
        record_of = {g: g - lead - 1 for g in range(lead + 1, instr_used + 1)}
        for plan in (duty_split.clones if duty_split is not None else [],
                     phase_split.clones if phase_split is not None else [],
                     drum_variants):
            for record, number, _ in plan:
                if record in record_of:
                    record_of[number] = record_of[record]
        cloneable = {g for g, i in record_of.items()
                     if i >= 0 and out[instr_at + 1 + (g - 1) * 25 + 2]}
        still = {(p, r) for p, r in legato_rows
                 if p < len(patterns) and 4 * r + 3 < len(patterns[p])
                 and patterns[p][4 * r + 2] == CMD_TONEPORTA
                 and patterns[p][4 * r + 3] == 0}
        patterns, legato_clones, declined = legato_tie_clones(
            patterns, still, tracks, cloneable, written_instr + 1, log=log)
        for base, _number in legato_clones:
            rec = instr_at + 1 + (base - 1) * 25
            clone = bytearray(out[rec:rec + 25])
            clone[7] |= GATETIMER_LEGATO
            if clone[8] == FIRSTWAVE_TESTBIT:
                at = det.instr_start + record_of[base] * det.instr_stride + 2
                clone[8] = (sid.data[at] | 0x01) & 0xFF
            out += clone
            written_instr += 1
        out[instr_at] = written_instr
        if declined:
            # The old spelling, whole: the envelope a declined tie's new
            # instrument carries is written as it always was.
            patterns = _tied_instrument_envelopes(patterns, envelopes, tracks,
                                                  log, only=declined)
    _write_wavetable(out, sid, det, instr_used, effects, fmt, table, multiplier,
                     min_notes, lead=lead, entries=wave_entries)
    _write_pulsetable(out, pulse_entries)

    if log:
        # Instruments are written as 1..instr_used, so anything above that is a
        # reference to a slot the file does not contain. Goattracker will play
        # those rows with an undefined instrument.
        highest = _highest_instrument_referenced(patterns)
        if highest > written_instr:
            # **Say whether any orderlist reaches the pattern.** This scans
            # ALL patterns, reachable or not, and that is right for the
            # converter -- it must not emit a reference it cannot satisfy --
            # but three corpus files warn about instruments no orderlist ever
            # plays (Ricochet $20, Arcade_Classics and BMX_Kidz $32; see
            # tests/test_instrument_bound.py's played/reported split), and
            # every reader of the bare message since has had to re-derive
            # reachability by hand. `instr_voices` is `tracks.instrument_voices`
            # over the finished orderlists: only instruments a played pattern
            # names are keys, so its highest key is the music's own answer.
            reached = max((i for i in (instr_voices or {}) if i > written_instr),
                          default=0)
            where = (f"the orderlists reach ${reached:X}"
                     if reached else "none is reached by any orderlist")
            log(f"*** PATTERNS REFERENCE INSTRUMENT ${highest:X} BUT ONLY "
                f"${written_instr:X} WERE WRITTEN -- {highest - written_instr} "
                f"DANGLING; {where} ***")

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
