"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import List, Optional, Set, Tuple
from ..detect import (Detection, EFFECT_BIT40_MASK, FILTER_ENABLE_BIT,
                     PITCH_SEQ_AT_PHASE, PITCH_SEQ_SHAPES,
                     NibbleArpPeriod, NIBBLE_ARP_PERIOD_OPCODE_SHAPE,
                     _effect_byte_address, decode_wave_program,
                     TRIANGLE_VIBRATO_GATE, TRIANGLE_VIBRATO_MAX_SHIFT,
                     TRIANGLE_VIBRATO_PEAK, TRIANGLE_VIBRATO_PERIOD,
                     VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     VIBRATO_SHIFT_MASK, _TRI_COUNTER, _TRI_DIR, _TRI_IDX,
                     pulse_tri_offset)
from ..search import search_file
from ..sidfile import GT_FREQ0, SidFile, find_freq_table

# The package re-exports EVERY name the single-file goatwriter.py held,
# private ones included, so `from h2g.goatwriter import X` and
# `goatwriter.X` keep working unchanged. Patch a function in tests on its
# DEFINING module (goatwriter.<module>.X): a patch on this facade reaches
# no caller (tests/test_goatwriter_package.py enforces it).
from .constants import (_ABS_X_LOAD, _ADJACENT_TABLE_WINDOW, ARP_HEAD_FRAMES,
                        ARP_MAX_STEPS, BEQ, BNE, CMD_SETAD, CMD_SETFILTERCTRL,
                        CMD_SETFILTERPTR, CMD_SETPULSEPTR, CMD_SETSR,
                        CMD_SETTEMPO, CMD_SETWAVEPTR, CMD_TONEPORTA,
                        CMD_VIBRATO, DEFAULT_FORMAT, DRUM_DEEPEN_MARGIN,
                        DRUM_MAX_SWEEP_STEPS, DRUM_SPEED, _drum_speed,
                        DRUM_SPEED_PER_FRAME, EFFECT_FIXED_PITCH_MASK,
                        EFFECT_NOTE_ALT_MASK, EFFECT_PER_FRAME,
                        EFFECT_PITCH_SEQ_MASK, EFFECT_SFX_DRUM_MASK,
                        EXPANDING_VIBRATO_COUNTER_AT, EXPANDING_VIBRATO_SHAPES,
                        EXPANDING_VIBRATO_TABLE_AT, FIELD_LEN, FILT_MODULATE,
                        FILT_SET_CUTOFF, FILT_SET_PARAMS, FILT_STOP,
                        FIRSTWAVE_GATE_ONLY, FIRSTWAVE_TESTBIT,
                        FIXED_ARP_GATED_INC, FIXED_ARP_PARITY_MASK,
                        FIXED_ARP_RESET_WINDOW, FIXED_ARP_SPLIT_FACTOR,
                        FIXED_ARP_TIE_SHARE, FORMAT_GTS2, FORMAT_GTS5, FORMATS,
                        GATETIMER_LEGATO, GT_DEFAULT_TEMPO_CALLS,
                        GT_FIRST_NOTE, GT_KEYOFF, GT_LAST_NOTE, GT_MAX_FILT,
                        GT_MAX_INSTR, GT_MAX_INSTRUMENTS, GT_MAX_PULSE_SPEED,
                        GT_MAX_PULSE_TICKS, GT_MAX_SONGS, GT_MAX_TABLELEN,
                        GT_MAX_VIB_SHIFT, GT_MIN_TEMPO, GT_REST,
                        GT_TABLES_GTS2, GT_TABLES_GTS5, GT_TEMPO_INSTRUMENT,
                        GT_WAVE_FIRST_CMD, GT_WAVE_JUMP, GT_WAVE_LAST_CMD,
                        GT_WAVE_LAST_DELAY, GT_WAVE_NO_NOTE,
                        HARD_RESTART_FRAMES, HEADER_LEN, ILV_EMPTY_UNION,
                        ILV_FILTER_ROUTING, _JUMP, LEGATO_TIE_FLAG_STORE_SHAPE,
                        LEGATO_TIE_GATE_SHAPE, MAX_INSTRUMENTS,
                        MAX_REPRESENTABLE_INSTRUMENTS, MAX_ROW_DENOMINATOR,
                        MAX_SANE_SPEED_RELOAD, _NAME_AT,
                        NIBBLE_GATE_MAX_HALVES, NOISE_TICK_FRAMES,
                        _ORDERLIST_REPEAT, _ORDERLIST_TRANSPOSE, OUTER_GATE,
                        OUTER_GATE_PAL, OUTER_GATE_RTS, OUTER_GATE_RTS_ZP,
                        _PACK_FIRSTNOTE, _PACK_FX, _PACK_FXONLY,
                        PACKED_PATTERN_LIMIT, PAL_NTSC_ENTRY,
                        PAL_NTSC_FLAG_LDX, PAL_NTSC_WINDOW, _POINTER_COMMANDS,
                        PULSE_ENTRIES_PER_INSTR, PULSE_RESEED_GATE,
                        _RECORD_LEN, RISE_SHIFT, SFX_DRUM_FRAMES,
                        _SONG_MAX_PATTERNS, SONG_START_ROW, _SPEED_COMMANDS,
                        SPEED_GATE, SPEED_GATE_IMM, SPEED_GATE_ZP,
                        SPEED_NOTE_RELATIVE, SPEED_RELOAD_STORE,
                        SPEED_TABLE_LOAD, _TABLE_NAMES, TEMPO_DUTY_MAX_CLONE,
                        TEMPO_FASTEST_STEADY, _TRI_INSTR_CELL,
                        VIBRATO_CMP_BIAS, VIBRATO_DELAY,
                        WAVE_ENTRIES_PER_INSTR, WAVE_GATE_BIT, WAVE_JUMP,
                        WAVE_MAX_DELAY, WAVE_NOISE_GATEOFF, WAVE_NOTE_ABS,
                        WAVE_NOTE_BASE, WAVE_NOTE_KEEP, _WAVE_POINTER_COMMANDS,
                        WAVE_SILENT_BASE, WAVE_SILENT_TESTBIT,
                        _WAVE_SPEED_COMMANDS, WAVE_TEST_BIT, WAVECMD_BASE,
                        WAVECMD_PORTADOWN, WAVECMD_PORTAUP, _X_RELOADERS)  # noqa: F401
from .hard_restart import (_hard_restart_ticks)  # noqa: F401
from .instruments import (_build_header, _field_bytes, _instruments_used,
                          _padded_name_bytes, record_envelope,
                          _table_length_byte, _write_instruments)  # noqa: F401
from .appending import (append_song, _latched_after, _parse_song,
                        _pattern_plays, _pin_start_instruments, _place_region,
                        _regions, _run_end, _Song, _table_entries, _write_song)  # noqa: F401
from .primitives import (_arp_relative, _counter_gate_call, _first_frame_entry,
                         _first_frame_lead, _fixed_arp_block, fixed_arp_mask,
                         _fixed_pitch_yield_field, _freq_table_note,
                         _gate_calls, _note_freq, _rate_shift, _sfx_note_byte,
                         _speed_index, _wave_byte, _wave_hold_byte)  # noqa: F401
from .tempo import (_adjacent_table_bound, derived_group_tempos,
                    effective_frames, file_multiplier, _find_outer_gate,
                    find_song_speeds, _gate_hits, orderlist_tempo_values,
                    outer_gate_skip, pack_subtune, _pal_ntsc_indexed,
                    recommended_multiplier, SongSpeeds, _speeds_for_reload,
                    tempo_command_value)  # noqa: F401
from .arpeggio import (apply_tempo_duty_edits, ArpPhaseSplit, _countdown,
                       _expand_repeats, _fixed_arp_counter,
                       fixed_arp_counter_base, fixed_arp_counter_gated,
                       fixed_arp_duty_entries, fixed_arp_first_fetch,
                       fixed_arp_note_residues, fixed_arp_period,
                       fixed_arp_phase_split_plan, fixed_arp_phases,
                       fixed_arp_tie_row_entries, fixed_arp_tie_rows,
                       fixed_arp_up, gateoff_nibble_arp_budget_pair,
                       gateoff_nibble_arp_entries, _half_cycle, _hold_run,
                       nibble_arp_counter_gated, nibble_arp_counter_test,
                       nibble_arp_entries, nibble_arp_first_half,
                       nibble_arp_half_calls, nibble_arp_half_cycle,
                       nibble_arp_phases, nibble_arp_up, nibble_gate_byte,
                       nibble_gate_frames, nibble_gate_phases,
                       nibble_gate_runs, _nibble_gate_shape, _note_phase_split,
                       _orderlist_occurrences, _phase_divergent_repeats,
                       _pitch_seq_advance, _pitch_seq_calls, _pitch_seq_clock,
                       _pitch_seq_fetched, _pitch_seq_frames_after,
                       pitch_seq_note_phases, pitch_seq_phase_split_plan,
                       pitch_seq_phases, PitchSeqClock, _refined_majority,
                       _share, tempo_duty_split_plan, TempoDutySplit,
                       ticked_arp_entries, ticked_nibble_arp_entries,
                       unticked_arp_octave_entry, _walk_note_rows)  # noqa: F401
from .attack import (_counter_gate_restore_call, _fixed_attack_note,
                     _fixed_hold_entries, _note_alternate_note,
                     _two_stage_entries, _two_stage_frames,
                     _two_stage_pitch_seq_entries, _voice_two_stage_entries,
                     _wave_alternate_entries, _wave_block_calls)  # noqa: F401
from .pulse import (_bounds_record, budget_pulse_phase_commands,
                    build_pulse_phase_table, _lay_out_pulse,
                    _lay_pulse_phase_table, packed_pattern_size, pattern_rows,
                    _phase_block, _phase_sweep_params, pulse_bounds_sims,
                    _pulse_layout, _pulse_lo_program, pulse_phase_sims,
                    _pulse_program, pulse_reseed_gated, _pulse_tri_program,
                    _pulse_triangle, _pulse_triangle_wrapped, pulse_usage,
                    PulseBoundsSim, PulsePhaseSim, PulseVoiceCell,
                    _speed_counter, _split_ticks, _tri_speed, _tri_step_delay,
                    triangle_start, TriangleStart, _write_pulsetable)  # noqa: F401
from .filters import (_classic_clearing_instruments, _filter_entries,
                      _filter_step_per_call, _highest_instrument_referenced,
                      _ilv_clearing_instruments, _ilv_filter_entries,
                      _ilv_filter_passband, ilv_filter_routing_plan,
                      _ilv_programs, _ilv_routed_records, _ilv_routing_walk,
                      _ilv_voice_rows, IlvRouting,
                      _instruments_named_per_voice, _write_filtertable)  # noqa: F401
from .note_passes import (_attack_hold_pass, _attack_hold_records,
                          _entry_instruments, _expanding_vibrato_counter,
                          _expanding_vibrato_level, _expanding_vibrato_pass,
                          _expanding_vibrato_step, _held_to_attack,
                          _lapped_tracks, legato_tie_clones, legato_tie_family,
                          legato_tie_rows, note_bit7_rows,
                          _orderlist_min_transpose, _past_table_drum_block,
                          past_table_drum_plan, _player_interval,
                          _predecessor_tails, _successor_heads,
                          _tied_instrument_envelopes, _vibrato_command_pass)  # noqa: F401
from .vibrato import (_classic_gate_delay, _classic_gate_refine,
                      _classic_vibrato_entry, _effect_call_list, _effect_calls,
                      _table_vibrato_entry, _triangle_vibrato_entry,
                      _vibrato_delay, _vibrato_layout)  # noqa: F401
from .drums import (_arp_block, _arp_offsets, _sfx_drum_entries)  # noqa: F401
from .notes import (_drum_steps_safe, _phase_note, _pitch_seq_entries,
                    _pitch_seq_note_byte, _pitch_seq_notes,
                    _pitch_seq_phase_notes, _pitch_seq_phased_entries,
                    _pitch_seq_steps)  # noqa: F401
from .wave_program import (_hold_wave_program_entry, _wave_program_entries,
                           _wave_program_travel_entry, _wave_program_travels)  # noqa: F401
from .wavetable import (_drum_duration_steps, _drum_entries, _drum_max_steps,
                        _drum_speed_index, _loop_of, _noise_tick_frames,
                        _record_voice, _rise_speed_index, _shared_loop_block,
                        _wavetable_entries, _wavetable_layout,
                        _write_wavetable)  # noqa: F401
from .build import (_arp_phase_distinct, build_sng, _resolve_arp_pointers)  # noqa: F401
