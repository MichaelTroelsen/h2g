"""build_sng: assembling the final .sng (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import copy
from typing import (List, Optional)

from ..detect import (Detection)
from ..sidfile import (SidFile)
from .constants import (CMD_SETPULSEPTR, CMD_SETWAVEPTR, CMD_TONEPORTA,
                        DEFAULT_FORMAT, EFFECT_PITCH_SEQ_MASK,
                        FIRSTWAVE_TESTBIT, FORMAT_GTS5, GT_WAVE_FIRST_CMD,
                        GT_WAVE_JUMP, GT_WAVE_LAST_CMD, GT_WAVE_LAST_DELAY,
                        GT_WAVE_NO_NOTE, WAVE_SILENT_BASE,
                        FORMATS, GATETIMER_LEGATO, GT_MAX_FILT,
                        GT_MAX_INSTRUMENTS, WAVE_ENTRIES_PER_INSTR)
from .instruments import (_build_header, _instruments_used, record_envelope,
                          _table_length_byte, _write_instruments)
from .arpeggio import (apply_tempo_duty_edits, fixed_arp_phase_split_plan,
                       fixed_arp_phases, fixed_arp_tie_rows, GatePhase,
                       nibble_arp_phases,
                       nibble_gate_phases, tempo_duty_split_plan)
from .pulse import (_pulse_layout, _write_pulsetable)
from .filters import (_classic_clearing_instruments, _filter_entries,
                      classic_sweep_calls,
                      _highest_instrument_referenced,
                      _ilv_clearing_instruments, _ilv_filter_entries,
                      free_running_start, ilv_filter_routing_plan,
                      sfx_bandpass_plan, _write_filtertable)
from .note_passes import (_attack_hold_pass, _attack_hold_records,
                          _cut_durations, _cut_note_pass, _duration_gate_pass,
                          _expanding_vibrato_counter, _expanding_vibrato_pass,
                          legato_tie_clones, legato_tie_rows, note_bit7_rows,
                          past_table_drum_plan, _tied_instrument_envelopes,
                          _vibrato_command_pass)
from .vibrato import (_classic_gate_refine, _free_gate_calls,
                      _vibrato_layout)
from .wavetable import (_wavetable_layout, _write_wavetable)
from .primitives import _record_row_calls
from . import arpeggio as _gw_arpeggio
from . import drum_fall as _gw_drum_fall
from . import lfo_wave as _gw_lfo_wave
from . import call_phase as _gw_call_phase
from . import tempo as _gw_tempo
from . import pulse as _gw_pulse
from . import note_passes as _gw_note_passes
from . import rest_reseed as _gw_rest_reseed
from . import rest_park as _gw_rest_park
from . import sfx_rest_click as _gw_sfx_rest_click
from . import rest_ring as _gw_rest_ring
from . import filters as _gw_filters
from . import classic_filter_stop as _gw_classic_filter_stop
from . import skydive as _gw_skydive
from . import note_rise as _gw_note_rise
from . import wave_eor as _gw_wave_eor
from . import dead_blocks as _gw_dead_blocks
from . import counter_fall as _gw_counter_fall
from . import rise_stair as _gw_rise_stair
from . import tri_clock as _gw_tri_clock
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
                        wave_alternate=False, instr_row_calls=None,
                        phases: Optional[tuple] = None,
                        eor_phases: Optional[dict] = None):
    """`fixed_arp_phase_split_plan`'s `distinct`: whether a record's block
    at a residue differs from its block at its own (`_wavetable_layout`'s
    `phase_probe`, with the arguments `build_sng` lays the table out with).
    `phases` is (arp_phases, arp_tie_rows, pitch_phases, arp_gate_phases)
    to probe with as given -- the ones the table was laid out with -- in
    place of the fixed-arp walk over `tracks`/`patterns`; with the nibble
    gate's phases among them, `distinct(record, its own residue)` says
    whether the record's block depends on the gate phase at all (a probe
    lays its residue out with none)."""
    arp_gate_phases = None
    if phases is not None:
        arp_phases, arp_tie_rows, pitch_phases, arp_gate_phases = phases
    else:
        arp_phases = fixed_arp_phases(sid, det, tracks, patterns)
        arp_tie_rows = fixed_arp_tie_rows(sid, det, tracks, patterns)
        pitch_phases = (_gw_arpeggio.pitch_seq_phases(sid, det, tracks,
                                                      patterns)
                        if pitch_seq and fmt == FORMAT_GTS5
                        and det.pitch_seq is not None else None)
    cache: dict = {}

    def distinct(record: int, residue: int) -> bool:
        if (record, residue) in cache:
            return cache[(record, residue)]
        probe = [(record, residue, False)]
        _wavetable_layout(sid, det, instr_used, effects, fmt, list(table),
                          multiplier, min_notes, lead, two_stage, sfx_drum,
                          wave_program, pitch_seq, note_rows, row_calls,
                          no_test_restart, voice_two_stage, instr_voices,
                          gate_skip, real_firstwave_instruments, None,
                          arp_phases=arp_phases, arp_tie_rows=arp_tie_rows,
                          pitch_phases=pitch_phases, phase_probe=probe,
                          arp_gate_phases=arp_gate_phases,
                          wave_alternate=wave_alternate,
                          instr_row_calls=instr_row_calls,
                          eor_phases=eor_phases)
        cache[(record, residue)] = bool(probe[0][2])
        return cache[(record, residue)]

    blocks: dict = {}

    def block(record: int, residue):
        """The block (record, residue) lays out, as a hashable: two residues
        of one record with the same value are the same bytes. Probed with the
        same arguments as `distinct`."""
        if (record, residue) not in blocks:
            probe = {(record, residue): None}
            _wavetable_layout(sid, det, instr_used, effects, fmt, list(table),
                              multiplier, min_notes, lead, two_stage,
                              sfx_drum, wave_program, pitch_seq, note_rows,
                              row_calls, no_test_restart, voice_two_stage,
                              instr_voices, gate_skip,
                              real_firstwave_instruments, None,
                              arp_phases=arp_phases,
                              arp_tie_rows=arp_tie_rows,
                              pitch_phases=pitch_phases,
                              phase_block_probe=probe,
                              arp_gate_phases=arp_gate_phases,
                              wave_alternate=wave_alternate,
                              instr_row_calls=instr_row_calls,
                              eor_phases=eor_phases)
            blocks[(record, residue)] = probe[(record, residue)]
        return blocks[(record, residue)]
    distinct.block = block
    return distinct


def _record_numbers(lead: int, instr_used: int, duty_split, phase_split,
                    drum_variants) -> dict:
    """{instrument GT number: source record index} -- every record, and each
    clone the splits and the drum variants append, as its record."""
    record_of = {g: g - lead - 1 for g in range(lead + 1, instr_used + 1)}
    for plan in (duty_split.clones if duty_split is not None else [],
                 phase_split.clones if phase_split is not None else [],
                 drum_variants):
        for record, number, _ in plan:
            if record in record_of:
                record_of[number] = record_of[record]
    return record_of


def _tie_phase_verdicts(sid: SidFile, det: Detection, rows: set,
                        tracks: List[List[int]], patterns: List[List[int]],
                        record_of: dict, lead: int, arp_phases, arp_tie_rows,
                        pitch_phases, arp_gate_phases, phase_clones,
                        distinct, gate_skip=None) -> dict:
    """{(pattern, row): (why, record GT number, residue)} for every tie row
    in `rows` a legato clone of the instrument it plays would put out of
    phase. `why` is one of the four reasons `_phase_locked_ties` logs;
    `residue` is the one counter residue an "arpeggio phase" row is played
    on (`arp_row_residues`), or a `GatePhase` for a "gated arpeggio phase"
    row played on one gate residue (`nibble_gate_row_residues`, which needs
    `gate_skip`), else None -- a row played on several has no one block to
    restart on. The rules are `_phase_locked_ties`'."""
    if not rows or not (arp_phases or arp_tie_rows or pitch_phases
                        or arp_gate_phases):
        return {}
    entry = _gw_note_passes._entry_instruments(tracks, patterns)
    residues = (_gw_arpeggio.arp_row_residues(sid, det, tracks, patterns)
                if arp_phases else None) or {}
    seen = sorted(set().union(*residues.values())) if residues else []
    clone_residue = {clone: res for _rec, clone, res in phase_clones}
    gate_rows: dict = {}
    period = None
    if arp_gate_phases and gate_skip:
        gate_rows = _gw_arpeggio.nibble_gate_row_residues(
            sid, det, tracks, patterns, gate_skip) or {}
        per = det.arp_nibble_period
        if per is not None:
            period = _gw_arpeggio.fixed_arp_period(
                max(per.on_interval, per.otherwise))
    kept: dict = {}
    for pn in sorted({p for p, _r in rows}):
        pat = patterns[pn]
        held = entry.get(pn, set())
        live = next(iter(held)) if len(held) == 1 else 0
        for r in range(len(pat) // 4):
            if pat[4 * r + 1]:
                live = pat[4 * r + 1]
            if (pn, r) not in rows or not live:
                continue
            i = record_of.get(live)
            if i is None or i < 0:
                continue
            g = i + lead + 1                 # the source record's number
            fx = det.instr_start + i * det.instr_stride + 7
            fx = sid.data[fx] if 0 <= fx < len(sid.data) else 0
            mine = (arp_phases or {}).get(g)
            if arp_tie_rows and g in arp_tie_rows:
                kept[(pn, r)] = ("row-locked arpeggio", g, None)
            elif (pitch_phases and g in pitch_phases
                  and fx & EFFECT_PITCH_SEQ_MASK):
                kept[(pn, r)] = ("pitch-sequence phase", g, None)
            elif (arp_gate_phases and g in arp_gate_phases
                  and mine is not None and distinct(g, mine)):
                # Its block at its own residue differs from the one laid
                # out: the gate's phase is in it. A row played on ONE gate
                # residue (`GatePhase`, the counter modulo lcm(P, O)) is
                # free where that is the residue of the block it restarts,
                # else restarts the block laid out for it.
                got = gate_rows.get((pn, r))
                cur = clone_residue.get(live)
                landing = None
                if (got and None not in got and len(got) == 1 and period
                        and (cur is None or isinstance(cur, GatePhase))):
                    x = next(iter(got))
                    here = GatePhase(x, period)
                    if x == (arp_gate_phases[g] if cur is None
                             else cur.residue):
                        continue         # a fresh attack lands on the block
                    if cur is None and not distinct(g, here):
                        continue         # the block no residue changes
                    landing = here
                kept[(pn, r)] = ("gated arpeggio phase", g, landing)
            elif (mine is not None
                  and any(distinct(g, x) for x in seen)):
                own = clone_residue.get(live, mine)
                got = residues.get((pn, r))
                if not got or not all(
                        x == own or not (distinct(g, x) or distinct(g, own))
                        for x in got):
                    kept[(pn, r)] = ("arpeggio phase", g,
                                     next(iter(got)) if got and len(got) == 1
                                     else None)
    return kept


def _tie_block_source(g: int, x: int, mine: Optional[int], distinct,
                      phase_clones) -> Optional[str]:
    """Where a block laid out for record `g` at counter residue `x` already
    exists: "clone" (a phase clone of that record and residue), "record"
    (the record's own block, which `x` does not change: `x` is the residue
    it was laid out at, or `distinct` says the two are the same), else None
    -- the block a tie landing there needs is one nobody laid out."""
    if any(rec == g and res == x for rec, _c, res in phase_clones):
        return "clone"
    if mine is not None and (x == mine or not distinct(g, x)):
        return "record"
    return None


# The verdicts whose row lands on one residue, so on a block that can be laid
# for it (`_tie_blocks_wanted`, `_phase_locked_ties`' respell).
_TIE_BLOCK_KINDS = ("arpeggio phase", "gated arpeggio phase")


def _block_residue_of(g: int, x, arp_phases, arp_gate_phases):
    """The residue record `g`'s own block was laid out at, in the kind of
    residue `x` is: the counter's (`arp_phases`), or a `GatePhase` of the
    record's gate residue."""
    if isinstance(x, GatePhase):
        own = (arp_gate_phases or {}).get(g)
        return None if own is None else GatePhase(own, x.period)
    return (arp_phases or {}).get(g)


def _tie_blocks_wanted(verdicts: dict, arp_phases, distinct,
                       phase_clones, arp_gate_phases=None) -> List[tuple]:
    """The (record GT number, residue) blocks the "arpeggio phase" and
    one-residue "gated arpeggio phase" verdicts in `verdicts` need laid out:
    one per pair, in sorted order, none for a pair `_tie_block_source` finds
    already laid out."""
    wanted = set()
    for why, g, x in verdicts.values():
        if (why in _TIE_BLOCK_KINDS and x is not None
                and _tie_block_source(
                    g, x, _block_residue_of(g, x, arp_phases,
                                            arp_gate_phases),
                    distinct, phase_clones) is None):
            wanted.add((g, x))
    return sorted(wanted, key=lambda t: (
        t[0], isinstance(t[1], GatePhase),
        (t[1].residue, t[1].period) if isinstance(t[1], GatePhase)
        else (t[1], 0)))


def _phase_locked_ties(sid: SidFile, det: Detection, rows: set,
                       tracks: List[List[int]], patterns: List[List[int]],
                       record_of: dict, lead: int, arp_phases, arp_tie_rows,
                       pitch_phases, arp_gate_phases, phase_clones,
                       distinct, log=None, block_start=None,
                       respelled=None, gate_skip=None) -> set:
    """The tie rows a legato clone would put out of phase: kept on
    `CMD_TONEPORTA 00`, which runs the wavetable on through the tie.

    A clone restarts its record's block (gplay.c:363 `ptr[WTBL] =
    iptr->ptr[WTBL]`), and a block that carries an arpeggio carries the
    counter's residue on a fresh attack -- the record's majority
    (`arp_phases`), or a phase clone's own (`phase_clones`). The counter is
    global in the original (Commando `$5365 LDA $5525 / AND #$01`), so the
    tie's landing does not restart it there, and the octave after a
    restarted block is right only where the tie lands on that same residue,
    or on one whose block `distinct` says is identical. Each row is checked
    on every place it is played (`arp_row_residues`). Kept outright: a
    record whose block is the row-locked tie-chain shape (`arp_tie_rows`,
    built for a tie that does NOT restart it), and one whose block carries
    bit $10's phase (`EFFECT_PITCH_SEQ_MASK`) or the nibble gate's
    (`distinct` at its own residue), which no residue walk here models. A
    record no residue changes (`distinct` False everywhere) is free to
    restart.

    A row of the "arpeggio phase" kind played on ONE residue is not kept
    where `block_start(record, residue)` names a wavetable start for it (a
    phase clone's, the record's own, or a block `_tie_blocks_wanted` had
    laid out): the clone restarts THAT block, which is the fresh attack the
    original's restart is at that residue. Those rows go into `respelled`
    as {(pattern, row): start}."""
    verdicts = _tie_phase_verdicts(
        sid, det, rows, tracks, patterns, record_of, lead, arp_phases,
        arp_tie_rows, pitch_phases, arp_gate_phases, phase_clones, distinct,
        gate_skip)
    kept = {k: v[0] for k, v in verdicts.items()}
    if block_start is not None and respelled is not None:
        for key, (why, g, x) in verdicts.items():
            if why in _TIE_BLOCK_KINDS and x is not None:
                start = block_start(g, x)
                if start:
                    respelled[key] = start
                    del kept[key]
    if log is not None and kept:
        why: dict = {}
        for w in kept.values():
            why[w] = why.get(w, 0) + 1
        log(f"Legato tie..............: {len(kept)} tie row(s) kept "
            f"CMD_TONEPORTA, the clone's restart out of phase ("
            + "; ".join(f"{c} {w}" for w, c in sorted(why.items())) + ")")
    return set(kept)


def _block_is_steady(entries: List[tuple], start: int,
                     firstwave: int) -> bool:
    """Whether a record's wavetable block, run again from `start` (1-based)
    on a note already sounding it, changes nothing: one waveform from the
    firstwave on (`firstwave` is the byte the note starts with; $FE/$FF
    only set the gate, gplay.c:356), no command entry ($F0-$FE), and every
    note column the pattern's note (+0) or "keep" ($80) -- delays ($01-$0F)
    and "no change" ($00) between. Walked to the first jump; a loop back
    into the block runs only what was walked."""
    waves = set()
    if 0x10 <= firstwave < WAVE_SILENT_BASE:
        waves.add(firstwave)
    j = start - 1
    while 0 <= j < len(entries):
        left, right = entries[j]
        if left == GT_WAVE_JUMP:
            break
        if GT_WAVE_FIRST_CMD <= left <= GT_WAVE_LAST_CMD:
            return False
        if left > GT_WAVE_LAST_DELAY:
            waves.add(left if left < WAVE_SILENT_BASE else left & 0x0F)
        if right not in (0x00, GT_WAVE_NO_NOTE) or len(waves) > 1:
            return False
        j += 1
    return True


def _pulse_sweeps(entries: List[tuple], start: int) -> bool:
    """Whether a pulse program run from `start` (1-based) moves the width:
    any modulation entry (left $01-$7F, gplay.c:870-893) with a nonzero
    speed before its first jump."""
    j = start - 1
    while start and 0 <= j < len(entries):
        left, right = entries[j]
        if left == 0xFF:
            break
        if 0x01 <= left < 0x80 and right:
            return True
        j += 1
    return False


class _RetryDeadBlocks(Exception):
    """`_build_sng`: a pass named a record whose wavetable block
    `dead_blocks` had dropped; rebuild without dropping any."""


class _RetrySplit(Exception):
    """`_build_sng`: some `entry_instrument_split` copy settles only rows
    whose restart is silent; rebuild splitting just `.args[0]`."""


def _heard_splits(heard: set, split_rows: set, copies: dict,
                  tracks: List[List[int]], patterns: List[List[int]]) -> set:
    """The source patterns of `entry_instrument_split`'s `copies` worth their
    copy under the classic restart family: those holding a `_restart_heard`
    row among the rows the split was made for (`split_rows`, before the
    first named instrument), or whose predecessor ends on a heard row (the
    successor case). A copy whose rows are all quiet buys nothing -- they
    keep CMD_TONEPORTA with or without it -- and costs a pattern."""
    sources = set(copies.values())
    succ = _gw_note_passes._pattern_successors(tracks, len(patterns))
    keep: set = set()
    for pn, r in heard:
        sp = copies.get(pn, pn)
        if (sp, r) not in split_rows:
            continue
        if sp in sources and r < _gw_note_passes._first_named_row(patterns[pn]):
            keep.add(sp)
        if 4 * r + 4 >= len(patterns[pn]) or patterns[pn][4 * r + 4] == 0xFF:
            keep |= {copies.get(q, q) for q in succ.get(pn, ())} & sources
    return keep


def _restart_heard(rows: set, tracks: List[List[int]],
                   patterns: List[List[int]], record_of: dict, out,
                   instr_at: int, wave_entries: List[tuple],
                   pulse_entries: List[tuple], firstwave_of, kind: str,
                   pulse_restart: bool = False) -> set:
    """The tie rows whose instrument restart the original makes AUDIBLE --
    the ones to respell. The classic start re-writes waveform, pulse, AD
    and SR and restarts the effects (`CLASSIC_TIE_START_SHAPES`); on a tie
    into the record the channel already holds, with a block that writes one
    waveform at the pattern's note (`_block_is_steady`), every one of those
    writes is the value already there -- in the "record" dialect the pulse
    too (the live value), in the "voice" dialect wherever the record's
    program does not sweep (`_pulse_sweeps`) -- and the restart is silent.
    There `CMD_TONEPORTA 00` already says it, and a clone would cost what
    any Goattracker note costs: player.s runs no pulse step on the note's
    init call, so a held sweep would stall a frame per tie (Ninja voice 1,
    $3A8 held two frames at 5174 where the old spelling sweeps on). A tie
    into another record, or onto a block or sweep the restart replays, is
    heard. An unsettled held instrument counts as another record.

    The pulse reason counts only with `pulse_restart` (convert()'s
    `tie_pulse_restart`): respelling those ties costs pitch on the files
    that reach it (convert()'s docstring), so it is per song."""
    entry = _gw_note_passes._entry_instruments(tracks, patterns)
    heard = set()
    for pn in sorted({p for p, _r in rows}):
        pat = patterns[pn]
        held = entry.get(pn, set())
        live = next(iter(held)) if len(held) == 1 else 0
        for r in range(len(pat) // 4):
            before = live
            if pat[4 * r + 1]:
                live = pat[4 * r + 1]
            if (pn, r) not in rows:
                continue
            if not live or not before or record_of.get(before) != record_of.get(live):
                heard.add((pn, r))
                continue
            rec = instr_at + 1 + (live - 1) * 25
            if not _block_is_steady(wave_entries, out[rec + 2],
                                    firstwave_of(live)):
                heard.add((pn, r))
            elif (kind == "voice" and pulse_restart
                  and _pulse_sweeps(pulse_entries, out[rec + 3])):
                heard.add((pn, r))
    return heard


def _build_sng(sid: SidFile, det: Detection, tracks: List[List[int]],
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
              subtune_row_calls: tuple = (),
              voice_two_stage: bool = False,
              instr_voices: Optional[dict] = None,
              instr_row_calls: Optional[dict] = None,
              note_pitches: Optional[dict] = None,
              note_spans: Optional[dict] = None,
              gate_skip: Optional[int] = None,
              wide_hard_restart: bool = False,
              max_hard_restart: bool = False,
              real_firstwave_instruments: tuple = (),
              arps: Optional[List[tuple]] = None,
              wave_alternate: bool = False,
              ilv_filter_routing: bool = False,
              gate_off_firstwave_instruments: tuple = (),
              gatetimer_trim: int = 0,
              tie_restart: bool = False,
              tie_pulse_restart: bool = False,
              wave_reserve: int = 0,
              sfx_drum_bandpass: bool = False,
              drum_fall: bool = False,
              named_firstwave: bool = False,
              pitch_tie_phase: bool = False,
              rest_program_stop: bool = False,
              drop_dead_blocks: bool = False,
              vibrato_onset: bool = False,
              lfo_wave: bool = False,
              master_volume: bool = False,
              _split_only: Optional[frozenset] = None) -> bytes:
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
    ghosts = getattr(patterns, "ghosts", ())
    # The classic players with no legato marker restart the instrument on
    # EVERY tie landing (`classic_tie_restart_family`), so every tie row is
    # one -- behind `tie_restart`, because Commando is one of them.
    restart_kind = (_gw_note_passes.classic_tie_restart_family(sid, det)
                    if tie_restart and not legato else None)
    def _entry_split_rows(tks: List[List[int]],
                          pats: List[List[int]]) -> set:
        """The rows `entry_instrument_split` is handed (see its call
        below for why these): the legato tie rows, behind the -S2 decoy
        where one is needed, and the free-note respell's rows."""
        early_bit7 = (note_bit7_rows(pats, known_bit7, decoded, ghosts)
                      if legato else
                      {p: frozenset() for p in range(len(pats))})
        rows = legato_tie_rows(pats, early_bit7)
        if (rows and multiplier > 1
                and _gw_note_passes.legato_slip_decoy(
                    pats, tks, instr_used, instr_used + 1) is None):
            rows = set()
        # The free-note respell below walks the same way and declines the
        # same "entered with two instruments" rows, so its rows are split
        # for too -- under its own gates, and not behind the -S2 decoy: a
        # free-note variant is no legato record, so gt2reloc has no slip to
        # hand it. Only rows that could play a record with an attack to
        # skip (`free_note_split_rows`): any other declines regardless.
        if (legato and two_stage and effects
                and _gw_note_passes.free_note_skips_two_stage(sid, det)):
            # A record with no attack takes a pulse-only variant where the
            # player's counter is read only behind the attack bits, so its
            # rows are worth a split too (entry settled -> held == base).
            pulse_ok = (_gw_note_passes.free_note_attack_bits(sid, det)
                        is not None)
            skippable = {g for g in range(lead + 1, instr_used + 1)
                         if pulse_ok
                         or _gw_note_passes.free_note_record_has_attack(
                             sid, det, g - lead - 1)}
            rows = rows | _gw_note_passes.free_note_split_rows(
                pats, _gw_note_passes.free_note_rows(pats, early_bit7),
                tks, skippable)
        return rows

    def _phase_split_displaces_passes(tks: List[List[int]],
                                      pats: List[List[int]]) -> bool:
        """True where a phase split would switch off a pass that has work
        here. The entry-instrument split and the free-note respell both
        stand down beside any phase split (their pattern copies and their
        record-keyed rows cannot share the plan's renamed instrument
        columns), so a file on which either would change a byte keeps the
        record's majority phase rather than lose them: Star_Paws's
        entry split, Lightforce's, Shockway_Rider's and Saboteur_II's
        free notes (task pitch-seq-room-aware-phase-clones)."""
        if (legato or restart_kind) and duty_split is None:
            rows = _entry_split_rows(tks, pats)
            if rows and _gw_note_passes.entry_split_has_work(
                    tks, pats, rows):
                return True
        if (legato and two_stage and effects and duty_split is None
                and _gw_note_passes.free_note_skips_two_stage(sid, det)):
            # What the pass would hand to a variant: every record gets a
            # start, whether or not its real one could be entered (that
            # needs the finished wavetable) and whether or not the pulse
            # counter is readable (`free_note_attack_bits`) -- this asks
            # whether the pass is RELEVANT to the file, so it over-counts.
            # The rows the pass declines for what they follow
            # (`free_note_variants`) stay declined: Trans-Atlantic's.
            starts, only = {}, set()
            for g in range(lead + 1, instr_used + 1):
                starts[g] = 1
                if not _gw_note_passes.free_note_record_has_attack(
                        sid, det, g - lead - 1):
                    only.add(g)
            bit7 = note_bit7_rows(pats, known_bit7, decoded, ghosts)
            if _gw_note_passes.free_note_has_work(
                    pats, _gw_note_passes.free_note_rows(pats, bit7), tks,
                    starts, instr_used + 1, only):
                return True
        return False

    # The note lengths the byte-code program's cut-note test reads
    # (`_wave_program_entries` `spans`): only where an instrument writes a
    # real firstwave, because only there does the next note's init call put
    # the previous note's last pitch on the chip for a frame.
    stale_spans = (note_spans if (no_test_restart
                                  or real_firstwave_instruments) else None)
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
                real_firstwave_instruments, wave_alternate=wave_alternate,
                instr_row_calls=instr_row_calls),
            log=log)
    # Bit $10's divided phase gets the same split, in the same slot: its
    # clones are made, numbered and renamed exactly as the fixed arp's
    # (`pitch_seq_phase_split_plan`), their third slot a phase tuple where
    # the arp's is a residue. No corpus file has both clocks.
    if (phase_split is None and duty_split is None and pitch_seq
            and fmt == FORMAT_GTS5 and det.pitch_seq is not None):
        pitch_distinct = _arp_phase_distinct(
            sid, det, tracks, patterns, instr_used, effects, fmt, table,
            multiplier, min_notes, lead, two_stage, sfx_drum,
            wave_program, pitch_seq, note_rows, row_calls,
            no_test_restart, voice_two_stage, instr_voices, gate_skip,
            real_firstwave_instruments, wave_alternate=wave_alternate,
            instr_row_calls=instr_row_calls)
        # The outer-gated flat clocks' clones are room-aware: a dry layout
        # of the plan names the clones the wavetable has no block for (they
        # would be numbered, copied and renamed to play the record's own
        # block, moving bytes and no sound), and the plan is made again
        # without them. A clone that takes no entries moves no other's
        # start, so once is enough. Food_Feud's and Mega_Apocalypse's
        # plans are made once, as they always were.
        room_aware = _gw_arpeggio.pitch_seq_outer_gated(sid, det)
        no_room: set = set()
        for _pass in range(2 if room_aware else 1):
            held: List[str] = []
            phase_split = _gw_arpeggio.pitch_seq_phase_split_plan(
                sid, det, tracks, patterns, lead, instr_used,
                instr_used + 1,
                displaces=_phase_split_displaces_passes,
                distinct=(lambda rec, res: (rec, res) not in no_room
                          and pitch_distinct(rec, res)),
                log=held.append if log else None)
            if phase_split is None or not room_aware or _pass:
                for line in held:
                    log(line)
                break
            dry_starts: List[int] = []
            _wavetable_layout(
                sid, det, instr_used, effects, fmt, list(table),
                multiplier, min_notes, lead, two_stage, sfx_drum,
                wave_program, pitch_seq, note_rows, row_calls,
                no_test_restart, voice_two_stage, instr_voices,
                gate_skip, real_firstwave_instruments, arps,
                arp_phases=(fixed_arp_phases(sid, det, tracks, patterns)
                            if effects and det.arp_fixed_up else None),
                arp_tie_rows=(fixed_arp_tie_rows(sid, det, tracks, patterns)
                              if effects and det.arp_fixed_up else None),
                pitch_phases=_gw_arpeggio.pitch_seq_phases(
                    sid, det, tracks, patterns),
                phase_clones=phase_split.clones,
                phase_clone_starts=dry_starts,
                wave_alternate=wave_alternate,
                instr_row_calls=instr_row_calls,
                hold_travel=not (no_test_restart
                                 or real_firstwave_instruments
                                 or gate_off_firstwave_instruments),
                note_pitches=note_pitches, note_spans=stale_spans)
            failed = {(rec, res) for (rec, _c, res), at
                      in zip(phase_split.clones, dry_starts) if not at}
            if not failed:
                for line in held:
                    log(line)
                break
            if log:
                log(f"pitch phase split: {len(failed)} clone(s) the "
                    "wavetable has no room for stay on their record: "
                    + ", ".join(f"{rec:02X} {res}"
                                for rec, res in sorted(failed)))
            no_room |= failed
            phase_split = None
    # The gated nibble counter's residue gets it too, in the same slot
    # (`nibble_gate_phase_split_plan`): each clone's third slot a
    # `GatePhase`, its block laid out at that residue's counter phase and
    # gate phase both. `distinct` probes with the phases the table is laid
    # out with, so a residue whose block is the record's gets no clone --
    # and nor does one the table has no room for: a dry layout of the plan
    # names the clones that would get start 0 (their notes would play the
    # record's block under another number, moving bytes and no sound), and
    # the plan is made again without them. A clone that takes no entries
    # moves no other's start, so once is enough.
    if (phase_split is None and duty_split is None and effects
            and not det.arp_fixed_up and det.effect_arp
            and det.arp_nibble_period is not None and gate_skip):
        gate_majority = nibble_gate_phases(sid, det, tracks, patterns,
                                           gate_skip)
        if gate_majority:
            probe_phases = (
                nibble_arp_phases(sid, det, tracks, patterns), None,
                (_gw_arpeggio.pitch_seq_phases(sid, det, tracks, patterns)
                 if pitch_seq and fmt == FORMAT_GTS5
                 and det.pitch_seq is not None else None),
                gate_majority)
            gate_distinct = _arp_phase_distinct(
                sid, det, tracks, patterns, instr_used, effects, fmt,
                table, multiplier, min_notes, lead, two_stage, sfx_drum,
                wave_program, pitch_seq, note_rows, row_calls,
                no_test_restart, voice_two_stage, instr_voices,
                gate_skip, real_firstwave_instruments,
                wave_alternate=wave_alternate,
                instr_row_calls=instr_row_calls, phases=probe_phases)
            no_room: set = set()
            for _pass in range(2):
                phase_split = _gw_arpeggio.nibble_gate_phase_split_plan(
                    sid, det, tracks, patterns, effects, lead, instr_used,
                    instr_used + 1, gate_skip,
                    distinct=(lambda rec, res: (rec, res) not in no_room
                              and gate_distinct(rec, res)),
                    log=log if _pass else None,
                    block_of=gate_distinct.block)
                if phase_split is None:
                    break
                dry_starts: List[int] = []
                _wavetable_layout(
                    sid, det, instr_used, effects, fmt, list(table),
                    multiplier, min_notes, lead, two_stage, sfx_drum,
                    wave_program, pitch_seq, note_rows, row_calls,
                    no_test_restart, voice_two_stage, instr_voices,
                    gate_skip, real_firstwave_instruments, arps,
                    arp_phases=probe_phases[0],
                    arp_gate_phases=gate_majority,
                    pitch_phases=probe_phases[2],
                    phase_clones=phase_split.clones,
                    phase_clone_starts=dry_starts,
                    wave_alternate=wave_alternate,
                    instr_row_calls=instr_row_calls,
                    hold_travel=not (no_test_restart
                                     or real_firstwave_instruments
                                     or gate_off_firstwave_instruments),
                    note_pitches=note_pitches, note_spans=stale_spans)
                failed = {(rec, res) for (rec, _c, res), at
                          in zip(phase_split.clones, dry_starts) if not at}
                if not failed:
                    if not _pass and log:
                        # The plan stands: say what it is.
                        _gw_arpeggio.nibble_gate_phase_split_plan(
                            sid, det, tracks, patterns, effects, lead,
                            instr_used, instr_used + 1, gate_skip,
                            distinct=gate_distinct, log=log,
                            block_of=gate_distinct.block)
                    break
                if log:
                    log(f"gate phase split: {len(failed)} clone(s) the "
                        "wavetable has no room for stay on their record: "
                        + ", ".join(f"{rec:02X} r{res.residue}"
                                    for rec, res in sorted(failed)))
                no_room |= failed
                phase_split = None
    # Bit $02's EOR toggle (Rasputin, `wave_eor.wave_eor_split_plan`): the
    # phase is the voice's event parity and the period the note's tick, so a
    # record's notes split evenly between two blocks and each gets the one
    # its counter reads. In the phase split's slot, which no other plan
    # takes on such a file, and BESIDE the tempo split, which Rasputin's
    # duty arpeggios already make: its clones are numbered after that
    # split's (they are written after them), its clones' records are left
    # alone, and a pattern this plan copies gets that plan's edits too.
    eor_phases = None
    if phase_split is None and effects and det.wave_eor is not None:
        aliases = ({c: r for r, c, _s in duty_split.clones}
                   if duty_split is not None else {})
        walked = _gw_wave_eor.wave_eor_note_residues(
            sid, det, tracks, patterns, instr_used, lead, aliases)
        if walked is not None:
            eor_phases = walked[0]
            phase_split = _gw_wave_eor.wave_eor_split_plan(
                sid, det, tracks, patterns, instr_used, lead,
                instr_used + 1 + (len(duty_split.clones)
                                  if duty_split is not None else 0),
                distinct=_arp_phase_distinct(
                    sid, det, tracks, patterns, instr_used, effects, fmt,
                    table, multiplier, min_notes, lead, two_stage, sfx_drum,
                    wave_program, pitch_seq, note_rows, row_calls,
                    no_test_restart, voice_two_stage, instr_voices,
                    gate_skip, real_firstwave_instruments,
                    wave_alternate=wave_alternate,
                    instr_row_calls=instr_row_calls,
                    eor_phases=eor_phases),
                aliases=aliases,
                exclude=frozenset(aliases) | frozenset(aliases.values()),
                log=log)
            if phase_split is not None and duty_split is not None:
                duty_split.edits = _gw_wave_eor.carry_split_edits(
                    tracks, phase_split.tracks, duty_split.edits)
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
    # A pattern entered holding two instruments gets a copy per instrument
    # (`entry_instrument_split`), so the clone respells below can settle the
    # rows before its first named instrument instead of declining them.
    # Here, because its copies repoint the orderlists; not beside the tempo
    # or phase split, whose instrument edits are keyed by pattern number.
    # The candidate rows are the ones the respells below are handed, under
    # the same gates; a copy's bit-7 rows are its source's (`bit7_rows`).
    split_copies: dict = {}
    split_rows: set = set()
    if ((legato or restart_kind) and duty_split is None
            and phase_split is None):
        split_rows = _entry_split_rows(tracks, patterns)
        tracks, patterns, split_copies = (
            _gw_note_passes.entry_instrument_split(
                tracks, patterns, split_rows, log=log, only=_split_only))

    def bit7_rows(pats: List[List[int]]) -> dict:
        return _gw_note_passes.split_bit7_rows(
            note_bit7_rows(pats, known_bit7, decoded, ghosts), split_copies)
    # Bit $10's phase on the legato ties (`pitch_seq_tie_plan`): a tie
    # restarts no phase cell in the original, but the clone it is respelled
    # on restarts its record's block, which carries ONE phase. The plan
    # copies patterns (and writes repeats out) so each tie row is fetched in
    # one state, and tags the rows whose state is not the record's own; the
    # blocks are laid out below and the clones pointed at them. Here, before
    # the orderlists are written, for the same reason the entry split is;
    # under the legato clones' own gates (the -S2 decoy included), and not
    # beside a split whose edits are keyed by pattern number.
    tie_tags: dict = {}
    if (pitch_tie_phase and legato and pitch_seq and fmt == FORMAT_GTS5
            and det.pitch_seq is not None and duty_split is None
            and phase_split is None and ilv_routing is None):
        tie_rows = legato_tie_rows(patterns, bit7_rows(patterns))
        if (tie_rows and multiplier > 1
                and _gw_note_passes.legato_slip_decoy(
                    patterns, tracks, instr_used, instr_used + 1) is None):
            tie_rows = set()
        own_phases = _gw_arpeggio.pitch_seq_phases(sid, det, tracks, patterns)
        tie_plan = (_gw_arpeggio.pitch_seq_tie_plan(
            sid, det, tracks, patterns, tie_rows, lead, instr_used,
            own_phases, log=log) if tie_rows and own_phases else None)
        if tie_plan is not None:
            tracks, patterns = tie_plan.tracks, tie_plan.patterns
            split_copies.update(tie_plan.copies)
            tie_tags = tie_plan.tags
    # The counter-started fall's notes run over repeated orderlist positions
    # (a long rest is `$D5 00`), whose visits it has to write differently:
    # unrolled here, before the orderlists are written, since it changes
    # their lengths (`counter_fall_plan` writes the rows, further down).
    if effects and det.counter_fall is not None:
        tracks = _gw_counter_fall.unroll_fall_repeats(
            sid, det, tracks, patterns, lead, instr_used, fmt, multiplier,
            gate_skip,
            bit7_rows(patterns) if known_bit7 is not None else None,
            no_test_restart=no_test_restart,
            real_firstwave=tuple(real_firstwave_instruments), log=log)
    out.append((len(tracks) // 3) & 0xFF)

    # Where each orderlist's bytes start, for a late pass that repoints a
    # position at a pattern copy (`rest_reseed`): same length, same place.
    track_at: List[int] = []
    for track in tracks:
        out.append((len(track) - 1) & 0xFF)
        track_at.append(len(out))
        out += bytes(track)

    # The filter and pulse tables are both built before the instruments,
    # because each instrument record carries the table step it starts on --
    # but both are written after them, with the other tables. A swept
    # instrument's pulse program is longer than a static one's, so that start
    # position is not a stride either.
    classic_clearing: set = set()
    sweep_lengths: dict = {}
    stop_sites: dict = {}
    if filters:
        classic_clearing = _classic_clearing_instruments(
            sid, det, tracks, patterns, 1 if compact_instruments else 2)
        filter_entries, filter_ptrs = _filter_entries(
            sid, det, instr_used, lead, multiplier, classic_clearing)
        if filter_ptrs:
            # The classic sweep lasts the voice's note, not $7F calls: sized
            # from the orderlists once the records that filter are known.
            # Where the voice moves to an unfiltered record the sweep is
            # stopped by an `A 00` (`classic_filter_stop`), so those gaps
            # no longer bound the length.
            sweep_lengths, stop_sites, stop_stats = (
                _gw_classic_filter_stop.classic_filter_stops(
                    tracks, patterns, set(filter_ptrs), lead + 1,
                    row_calls, instr_row_calls))
            if log and stop_stats["wanted"]:
                log("Classic filter stop.....: "
                    + ", ".join(f"{n} {k}" for k, n in stop_stats.items()))
            filter_entries, filter_ptrs = _filter_entries(
                sid, det, instr_used, lead, multiplier, classic_clearing,
                sweep_calls=sweep_lengths)
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
        tri_plan = None
    else:
        # A triangle sweep's speed is divided by our calls per original tick,
        # which a track-set outer gate (Rasputin's `$FE nn`) moves mid-song:
        # each record gets the clock it sounds at (`track_set_tick_ratios`),
        # and the notes it serves badly get a clone per clock class, spelled
        # by the last pass of all (`tri_clock_clones`).
        tick_ratios = (_gw_pulse.track_set_tick_ratios(
            sid, det, tracks, patterns, lead, multiplier, log)
            if pulse else None)
        pulse_entries, pulse_starts = _pulse_layout(
            sid, det, instr_used, pulse, multiplier, log, lead=lead,
            usage=_gw_pulse.pulse_usage(tracks, patterns, lead),
            tick_ratios=tick_ratios)
        tri_plan = (_gw_tri_clock.tri_clock_plan(
            sid, det, tracks, patterns, lead, multiplier, tick_ratios, log)
            if tick_ratios else None)
    # The LFO-table vibrato as wave programs (`lfo_wave`): which records get
    # one, at which walk index. Set on `det` so every layout -- the probes
    # and the real one -- lays the same block out, and cleared otherwise so
    # a second build under other options sees none. A record that gets a
    # program gets no Goattracker vibrato: the two would both move it.
    det.lfo_wave_phases = (_gw_lfo_wave.usable_phases(
        sid, det, _gw_lfo_wave.lfo_phases(sid, det, tracks, patterns, lead,
                                          multiplier),
        lead, multiplier, list(table))
        if lfo_wave and vibrato and fmt == FORMAT_GTS5 and no_test_restart
        else {})
    if det.lfo_wave_phases and log:
        log("LFO wave programs.......: "
            + ", ".join(f"{gt:02X} from index {x}"
                        for gt, x in sorted(det.lfo_wave_phases.items())))
    # Before the records, because each one carries its speed-table index -- and
    # into `table`, which the wavetable also grows and the file writes last.
    vib_ptrs = _vibrato_layout(sid, det, instr_used, vibrato, fmt, multiplier,
                               table, log, lead=lead,
                               skip=frozenset(gt - lead - 1 for gt in
                                              det.lfo_wave_phases),
                               vibrato_command=vibrato_command,
                               row_calls=row_calls, effects=effects,
                               gate_skip=(_gw_tempo.outer_gate_skip(sid)
                                          if _gw_call_phase.entry_gate(
                                              sid, dispatch=True)
                                          else None),
                               instr_row_calls=instr_row_calls,
                               table_span=True)
    # Before the vibrato command pass, which fills only free rows and must
    # see the envelope rows as taken; the envelopes are the records' own
    # (`record_envelope`), so the pass needs nothing the records write.
    envelopes = {i + lead + 1: record_envelope(sid.data, det, i,
                                               sustain_exact, cut_release)
                 for i in range(max(instr_used - lead, 0))}
    # The ties `legato_tie_clones` will respell, fixed here so the envelope
    # pass leaves them alone: a legato clone loads its own envelope.
    legato_rows = (legato_tie_rows(patterns, bit7_rows(patterns))
        if legato else legato_tie_rows(
            patterns, {p: frozenset() for p in range(len(patterns))})
        if restart_kind else set())
    if (legato_rows and multiplier > 1
            and _gw_note_passes.legato_slip_decoy(
                patterns, tracks, instr_used, instr_used + 1) is None):
        # gt2reloc cannot pack a legato instrument at -S2 and above: it
        # maps the instruments (greloc.c:362-370, legato last) and THEN
        # bumps `numnohr` "for multispeed stability" (:811-815), so
        # FIRSTLEGATOINSTR (:1134) lands one past the first legato record,
        # which player.s then plays as a plain no-HR note -- a gate-off at
        # the fetch and a re-attack. Star_Paws (-S2) voice 1: siddump
        # attacks 572 -> 967 against the original's 571, every one on that
        # first clone. The editor's gplay.c:930 tests the bit itself and
        # has no such slip. The clones go ahead only behind a decoy record
        # for the slip to land on (`legato_slip_decoy`, below); with no row
        # to name one on, the old spelling stays.
        if log:
            log(f"Legato tie..............: {len(legato_rows)} tie row(s) "
                f"kept CMD_TONEPORTA -- -S{multiplier} packs the first "
                "legato instrument as no-HR (greloc.c:811-815)")
        legato_rows = set()
    patterns = _tied_instrument_envelopes(patterns, envelopes, tracks, log,
                                          skip=legato_rows)
    if cut_release and det.envelope_cut:
        # The markers `_build_raw_pattern` left at a rest's KEYOFF and last
        # hold row; the rest rings at the record's own release in between.
        patterns, tracks = _gw_rest_ring.rest_ring_pass(
            patterns,
            {i + lead + 1: record_envelope(sid.data, det, i, sustain_exact,
                                           False)
             for i in range(max(instr_used - lead, 0))},
            envelopes, tracks, log,
            # The note rise claims the rows through a rest itself, after
            # this pass; on its files the ring keeps its older reach.
            chains=not (effects and det.note_rise is not None))
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
        # A pattern some positions want the swell on and others do not is
        # copied per set of rows wanted first; same-length orderlists, so the
        # bytes already written are written over (`expanding_vibrato_split`).
        tracks, patterns, vib_copies = _gw_note_passes.expanding_vibrato_split(
            sid, det, tracks, patterns, vib_ptrs, table, lead, multiplier,
            row_calls, instr_row_calls=instr_row_calls, log=log)
        if vib_copies:
            split_copies.update(vib_copies)
            for at, track in zip(track_at, tracks):
                out[at:at + len(track)] = bytes(track)
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
    # Bit $10's global phase, the same walk: only where its clock is read
    # (`_pitch_seq_any_clock` -- Food_Feud's divided one, and the undivided
    # ones of Mega_Apocalypse and the classic outer-gated players), and only
    # behind the option that emits the arpeggio at all.
    pitch_phases = (_gw_arpeggio.pitch_seq_phases(sid, det, tracks, patterns)
                    if pitch_seq and fmt == FORMAT_GTS5
                    and det.pitch_seq is not None else None)
    clone_starts: List[int] = []
    phase_clone_starts: List[int] = []
    # [first, last, stop] wavetable rows of bit $02's EOR cycles and the
    # program that ends them, where the layout laid them out.
    eor_span: List[int] = []
    eor_lib_out: List[object] = []
    # The blocks the phase-mismatched tie rows need (`_tie_blocks_wanted`):
    # a legato clone of a record restarts the block it points at, and a tie
    # landing on a residue no block was laid for would restart the wrong
    # one. Planned on the patterns as the legato pass will see them (the
    # phase clones' names applied), laid out beside the phase clones.
    tie_blocks: List[tuple] = []
    tie_block_starts: List[int] = []
    if restart_kind and legato_rows:
        plan_clones = phase_split.clones if phase_split is not None else []
        plan_distinct = _arp_phase_distinct(
            sid, det, tracks, patterns, instr_used, effects, fmt, table,
            multiplier, min_notes, lead, two_stage, sfx_drum, wave_program,
            pitch_seq, note_rows, row_calls, no_test_restart,
            voice_two_stage, instr_voices, gate_skip,
            real_firstwave_instruments, wave_alternate=wave_alternate,
            instr_row_calls=instr_row_calls,
            phases=(arp_phases, arp_tie_rows, pitch_phases, arp_gate_phases),
            eor_phases=eor_phases)
        tie_blocks = _tie_blocks_wanted(
            _tie_phase_verdicts(
                sid, det, legato_rows, tracks,
                apply_tempo_duty_edits(patterns, phase_split),
                _record_numbers(lead, instr_used, duty_split, phase_split,
                                []),
                lead, arp_phases, arp_tie_rows, pitch_phases,
                arp_gate_phases, plan_clones, plan_distinct, gate_skip),
            arp_phases, plan_distinct, plan_clones, arp_gate_phases)
    if tie_tags:
        # One block per (record, phase tuple) a tagged tie lands on.
        tie_blocks = sorted(set(tie_tags.values()))
    attack_holds = _attack_hold_records(sid, det, instr_used, lead, effects,
                                        two_stage)
    if attack_holds:
        # Dry run: only a record some short note will point at gets a block.
        used: set = set()
        _attack_hold_pass(patterns, {i + lead + 1: 1 for i in attack_holds},
                          det.vibrato_gate.gate, tracks, used=used)
        attack_holds = [i for i in attack_holds if i + lead + 1 in used]
    attack_hold_starts: List[int] = []
    # A record whose first slide frame a played note can end on
    # (`_cut_share`) keeps the frame for the notes that do not
    # (`keep_slide`) and gets a second program, declining it, for the ones
    # that do -- only if the pass can point every one of them.
    cut_records: List[int] = []
    cut_starts: List[int] = []
    cut_targets: dict = {}
    if stale_spans and wave_program:
        frames_of = {gt: None for gt in stale_spans}
        _wavetable_layout(
            sid, det, instr_used, effects, fmt, table, multiplier,
            min_notes, lead, two_stage, sfx_drum, wave_program, pitch_seq,
            note_rows, row_calls, no_test_restart, voice_two_stage,
            instr_voices, gate_skip, real_firstwave_instruments, None,
            wave_alternate=wave_alternate, instr_row_calls=instr_row_calls,
            note_pitches=note_pitches, note_spans=stale_spans,
            cut_probe=frames_of)
        durations = {}
        for gt, frames in frames_of.items():
            if frames:
                got = _cut_durations(
                    stale_spans[gt], frames,
                    _record_row_calls(instr_row_calls, gt, row_calls))
                if got:
                    durations[gt] = got
        if durations:
            stats: dict = {}
            _cut_note_pass(patterns, {gt: (1, d) for gt, d in
                                      durations.items()}, tracks,
                           stats=stats)
            for gt, d in sorted(durations.items()):
                st = stats.get(gt, {"placed": 0, "missed": 0})
                if st["placed"] and not st["missed"]:
                    cut_records.append(gt - lead - 1)
                    cut_targets[gt] = d
                elif log:
                    log(f"Cut-note programs.....: {gt:02X} stays whole "
                        f"({st['placed']} pointed, {st['missed']} missed)")
    # The LFO programs at each note's own phase where the record's modal one
    # misses it (`lfo_wave.lfo_phase_pointers`): pointer rows through the
    # `arps` route, so before the layout that appends their blocks.
    if det.lfo_wave_phases:
        if arps is None:
            arps = []
        patterns = _gw_lfo_wave.lfo_phase_pointers(
            sid, det, tracks, patterns, lead, multiplier, arps, log)
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
        phase_clone_starts=phase_clone_starts, tie_blocks=tie_blocks,
        tie_block_starts=tie_block_starts, attack_holds=attack_holds,
        attack_hold_starts=attack_hold_starts,
        cut_records=cut_records, cut_starts=cut_starts,
        wave_alternate=wave_alternate, log=log,
        instr_row_calls=instr_row_calls,
        # The byte-code program's `$85` travel at -S1 (`_wave_program_entries`
        # `hold_travel`): only where every note opens on the test bit, so the
        # tail's pitch the next note's init call inherits is never heard.
        hold_travel=not (no_test_restart or real_firstwave_instruments
                         or gate_off_firstwave_instruments),
        eor_phases=eor_phases, note_pitches=note_pitches,
        note_spans=stale_spans,
        eor_span=eor_span, eor_library_out=eor_lib_out)
    # The sfx drum's one-frame bandpass, written into the filter programs of the
    # drum records. After the wavetable layout, because where the noise lands
    # is read off the laid-out block (`sfx_drum_hit_lattice`); the table is
    # rebuilt rather than patched so the replaced blocks leave no dead rows.
    # Only over the classic reader's own table: the interleaved dialect's is
    # not a per-record sweep to put a loop around.
    if (sfx_drum_bandpass and sfx_drum and filters and filter_entries
            and filter_ptrs and ilv_routing is None
            and fmt == FORMAT_GTS5):
        blips = sfx_bandpass_plan(sid, det, filter_ptrs, wave_entries,
                                  wave_starts, lead, multiplier)
        if blips:
            rebuilt, rebuilt_ptrs = _filter_entries(
                sid, det, instr_used, lead, multiplier, classic_clearing,
                sfx_blips=blips, sweep_calls=sweep_lengths)
            if set(rebuilt_ptrs) == set(filter_ptrs):
                if log:
                    log(f"Sfx drum bandpass.......: {len(blips)} drum "
                        f"record(s) carry the one-frame bandpass; filter "
                        f"table {len(filter_entries)} -> {len(rebuilt)} "
                        f"of {GT_MAX_FILT} rows")
                filter_entries, filter_ptrs = rebuilt, rebuilt_ptrs
    # A counter-gated record whose plain program holds the frequency over
    # its gate's call gives the re-pitching steps back to the effects
    # (`_free_gate_calls`), before anything copies a record's block and
    # before `_classic_gate_refine` counts the calls it frees.
    if effects and vib_ptrs:
        blocks = [(i, wave_starts[i + lead])
                  for i in range(max(instr_used - lead, 0))
                  if i + lead < len(wave_starts)]
        for plan, starts in (
                (duty_split.clones if duty_split is not None else [],
                 clone_starts),
                (phase_split.clones if phase_split is not None else [],
                 phase_clone_starts)):
            blocks += [(record - lead - 1, start)
                       for (record, _c, _x), start in zip(plan, starts)
                       if start]
        blocks += [(record - lead - 1, start)
                   for (record, _x), start in zip(tie_blocks,
                                                  tie_block_starts) if start]
        # The records the swell pass commanded hold rows for, as it asks.
        swelling = (set(_gw_note_passes._expanding_vibrato_records(
                        sid, det, vib_ptrs, table))
                    if (vibrato_command and det.vibrato_offset is not None
                        and _expanding_vibrato_counter(sid, det) is not None)
                    else set())
        wave_entries, _freed = _free_gate_calls(
            det, vib_ptrs, wave_entries, blocks, multiplier, row_calls,
            instr_row_calls, lead, no_test_restart,
            real_firstwave_instruments, swelling=swelling, log=log,
            duration_onset=vibrato_onset)
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
    if cut_records:
        patterns = _cut_note_pass(
            patterns,
            {i + lead + 1: (start, cut_targets[i + lead + 1])
             for i, start in zip(cut_records, cut_starts) if start},
            tracks, log, stats={})
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
    # The blocks of the records no pattern names (`dead_blocks`): the finished
    # file drops those records, and their rows are room the programs below
    # are sized against. Only behind `drop_dead_blocks` (the option that
    # drops the records), after every pass that reads the table record by
    # record and before the ones that append to it.
    dead_dropped: frozenset = frozenset()
    if drop_dead_blocks:
        dead = _gw_dead_blocks.dead_records(patterns, instr_used, lead)
        library_end = (eor_span[2] + len(_gw_wave_eor.EOR_STOP_PROGRAM) - 1
                       if eor_span else 0)
        plan = _gw_dead_blocks.plan_dead_blocks(
            wave_entries, wave_starts, lead, dead,
            list(arp_starts) + clone_starts + phase_clone_starts
            + tie_block_starts + attack_hold_starts + cut_starts
            + drum_starts,
            _gw_dead_blocks.setwaveptr_operands(patterns),
            protect=max(lead * WAVE_ENTRIES_PER_INSTR, library_end))
        if plan is not None:
            row_map = plan.row_map
            for i in plan.dropped:
                wave_starts[lead + i] = 0
            for rows in (wave_starts, arp_starts, clone_starts,
                         phase_clone_starts, tie_block_starts,
                         attack_hold_starts, cut_starts, drum_starts,
                         eor_span):
                _gw_dead_blocks.remap_rows(rows, row_map)
            _gw_dead_blocks.remap_setwaveptr(patterns, row_map)
            if log:
                log(f"Dead wavetable blocks...: {len(plan.dropped)} record(s) "
                    f"no pattern names, {plan.rows} of {len(wave_entries)} "
                    f"rows freed")
            wave_entries = plan.entries
            dead_dropped = frozenset(i + lead + 1 for i in plan.dropped)
    # Bit $02's skydive (`skydive_plan`): a CMD_SETWAVEPTR on the row each
    # long note's window opens, into a program appended to the wavetable.
    # After every block whose start the records carry, so its own starts are
    # known, and before the passes that fill free command columns, which
    # must see its rows as taken. Gated on `effects` like every read of +7.
    if effects and det.skydive is not None:
        sky = _gw_skydive.skydive_plan(sid, det, tracks, patterns, lead,
                                       instr_used, fmt, multiplier,
                                       gate_skip, table, len(wave_entries),
                                       no_test_restart,
                                       tuple(real_firstwave_instruments),
                                       log=log, wave_entries=wave_entries,
                                       wave_starts=wave_starts,
                                       wave_pointers=[
                                           r for r in (
                                               list(arp_starts)
                                               + clone_starts
                                               + phase_clone_starts
                                               + tie_block_starts
                                               + attack_hold_starts
                                               + cut_starts
                                               + drum_starts) if r])
        if sky is not None:
            patterns = sky.patterns
            if sky.base is not None:
                # The plan shared the identical programs at the table's end
                # to make room (`compact_wave_tail`): the instruments' starts
                # moved with them.
                wave_entries = sky.base
                wave_starts[:] = sky.starts
            wave_entries = wave_entries + sky.entries
    # Bit $01's 16-bit drum fall (`drum_fall_plan`, Tarzan; the `drum_fall`
    # option): a CMD_SETWAVEPTR on the row after each drum note, into a
    # gate-off head and one shared chain appended past every block whose
    # start is known. Its rows are taken before the passes that fill free
    # command columns.
    if drum_fall and effects and det.drum_fall_step:
        dfall = _gw_drum_fall.drum_fall_plan(sid, det, tracks, patterns, lead,
                                             instr_used, fmt, multiplier,
                                             gate_skip, table,
                                             len(wave_entries), log=log)
        if dfall is not None:
            patterns = dfall.patterns
            wave_entries = wave_entries + dfall.entries
    # The same block without its window (`note_rise_plan`): a store on every
    # other tick of the whole note, one or two a row of two or three ticks,
    # each row pointed at a short program appended past every block whose
    # start is known. Its rows are taken before the passes that fill free
    # command columns.
    if effects and det.note_rise is not None:
        rise = _gw_note_rise.note_rise_plan(
            sid, det, tracks, patterns, lead, instr_used, fmt, multiplier,
            gate_skip, row_calls, table, len(wave_entries), no_test_restart,
            tuple(real_firstwave_instruments), log=log, reserve=wave_reserve,
            wave_entries=wave_entries, wave_starts=wave_starts,
            wave_pointers=[r for r in (
                list(arp_starts) + clone_starts + phase_clone_starts
                + tie_block_starts + attack_hold_starts + cut_starts
                + drum_starts) if r],
            subtune_row_calls=subtune_row_calls)
        if rise is not None:
            patterns = rise.patterns
            if rise.tracks is not None:
                # Its pattern copies repoint orderlist positions: same
                # length, same place, so the bytes already written are
                # written over (as the counter-started fall's).
                tracks = rise.tracks
                for at, track in zip(track_at, tracks):
                    out[at:at + len(track)] = bytes(track)
            if rise.base is not None:
                # Duplicate instrument blocks gave their rows to the
                # programs: the records now share the first copy.
                wave_entries = rise.base
                wave_starts[:] = rise.starts
            wave_entries = wave_entries + rise.entries
    # The counter-started fall (`counter_fall_plan`): the same stepping byte
    # gated by a frame count the note's fetch zeroes. Its rows are taken
    # before the passes that fill free command columns, and it needs the
    # decoder's bit-7 note rows, which say where that count carries on.
    if effects and det.counter_fall is not None:
        fall = _gw_counter_fall.counter_fall_plan(
            sid, det, tracks, patterns, lead, instr_used, fmt, multiplier,
            gate_skip, table, len(wave_entries),
            bit7=(bit7_rows(patterns) if known_bit7 is not None else None),
            no_test_restart=no_test_restart,
            real_firstwave=tuple(real_firstwave_instruments), log=log,
            wave_entries=wave_entries, wave_starts=wave_starts)
        if fall is not None:
            patterns = fall.patterns
            wave_entries = wave_entries + fall.entries
            # Its pattern copies repoint orderlist positions: same length,
            # same place, so the bytes already written are written over.
            tracks = fall.tracks
            for at, track in zip(track_at, tracks):
                out[at:at + len(track)] = bytes(track)
    # The swell's hold rows onto wavetable loops that step the triangle on
    # every call, tick 0 included (`_expanding_vibrato_loops`). After the
    # skydive for the same reason it is after the drums -- its loops are
    # appended past every block whose start is already known -- and before
    # the passes that fill free columns, since it may take one. Not beside
    # the tempo or phase split, whose clones carry programs of their own.
    if (vibrato_command and vib_ptrs and fmt == FORMAT_GTS5
            and duty_split is None and phase_split is None
            and det.vibrato_offset is not None
            and _expanding_vibrato_counter(sid, det) is not None):
        tracks, patterns, vib_copies = _gw_note_passes.expanding_vibrato_split(
            sid, det, tracks, patterns, vib_ptrs, table, lead, multiplier,
            row_calls, instr_row_calls=instr_row_calls, loops=True,
            wave_entries=wave_entries, wave_starts=wave_starts,
            no_test_restart=no_test_restart,
            real_firstwave_instruments=tuple(real_firstwave_instruments),
            log=log)
        if vib_copies:
            split_copies.update(vib_copies)
            for at, track in zip(track_at, tracks):
                out[at:at + len(track)] = bytes(track)
        wave_entries, _looped = _gw_note_passes._expanding_vibrato_loops(
            sid, det, tracks, patterns, vib_ptrs, table, lead, multiplier,
            row_calls, wave_entries, wave_starts,
            instr_row_calls=instr_row_calls,
            no_test_restart=no_test_restart,
            real_firstwave_instruments=tuple(real_firstwave_instruments),
            log=log)
    # The classic vibrato's DURATION gate, per event (`_duration_gate_pass`).
    # After the passes that own a command column for a short note
    # (the attack hold, the skydive, the drum fall, the cut), so it takes
    # only the columns they left free, and before the budget.
    if vibrato_command and vib_ptrs:
        _duration_gate_pass(det, patterns, vib_ptrs, lead, log, tracks=tracks)
    # The zero-page triangle player reseeds its pulse on a REST event as on
    # a note (`rest_reseed`). After every pass that fills a command column,
    # so it takes only columns nobody else wanted, and before the budget,
    # which must see its commands. Not where `pulse_plan` already owns
    # CMD_SETPULSEPTR: that walk is the other dialect's and never meets
    # this one (`pulse_phase_sims` returns {} here).
    reseeded = 0
    if pulse and pulse_plan is None:
        patterns, tracks, reseeded = _gw_rest_reseed.rest_pulse_reseeds(
            sid, det, tracks, patterns, pulse_starts, instr_used, lead,
            multiplier, log)
        for at, track in zip(track_at, tracks):
            out[at:at + len(track)] = bytes(track)
    # A free-running filter sweep's accumulator starts at the file's byte, not
    # at Goattracker's 0 (`free_running_start`). After every pass that fills a
    # command column, so it only takes row 0 where nobody else did.
    if (filters and filter_entries and filter_ptrs and det.filter is not None
            and det.filter.free_running and det.filter.cutoff):
        patterns, tracks, _placed, _skipped = free_running_start(
            tracks, patterns, det.filter.cutoff, log)
        for at, track in zip(track_at, tracks):
            out[at:at + len(track)] = bytes(track)
    if pulse_plan is not None or reseeded:
        # Last, after every pass that writes a command column: the packed
        # size is a property of the finished rows and nothing else.
        patterns = _gw_pulse.budget_pulse_phase_commands(patterns, CMD_SETPULSEPTR, log)
    vib_ptrs = _classic_gate_refine(det, vib_ptrs, wave_entries, wave_starts,
                                    multiplier, row_calls, instr_row_calls,
                                    lead, no_test_restart,
                                    real_firstwave_instruments,
                                    duration_onset=vibrato_onset)
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
                       instr_row_calls=instr_row_calls,
                       gate_off_firstwave_instruments=tuple(
                           gate_off_firstwave_instruments),
                       gatetimer_trim=gatetimer_trim,
                       gate_clear_firstwave=effects,
                       named_firstwave=named_firstwave)
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
    # (base, number) for every record appended below that plays its base's
    # own wavetable program -- the decoy, the legato clones, the free-note
    # variants -- for the rise stair at the end (`rise_stair_plan`).
    stair_aliases: List[tuple] = []
    if legato_rows:
        # Each GT number's source record, for the clone's real firstwave.
        record_of = _record_numbers(lead, instr_used, duty_split, phase_split,
                                    drum_variants)
        cloneable = {g for g, i in record_of.items()
                     if i >= 0 and out[instr_at + 1 + (g - 1) * 25 + 2]}
        still = {(p, r) for p, r in legato_rows
                 if p < len(patterns) and 4 * r + 3 < len(patterns[p])
                 and patterns[p][4 * r + 2] == CMD_TONEPORTA
                 and patterns[p][4 * r + 3] == 0}
        # The classic restart family respells only the ties whose restart is
        # heard (`_restart_heard`), and of those not the ones a restarted
        # block would put out of the arpeggio counter's phase
        # (`_phase_locked_ties`): both keep the old spelling, which runs the
        # program on, and get the envelope pass a declined tie gets.
        def clone_firstwave(g: int, start: Optional[int] = None) -> int:
            # The record's own waveform with the gate where the record's is
            # the test bit: the original re-stores its waveform at the
            # landing and resets no oscillator. In the classic restart
            # family, and in the `note_flag` family (`legato`: Trans-Atlantic
            # voice 2 played $41 on the old pitch $7C10 at frame 6494 where
            # the original moves waveform and pitch together), where the
            # clone's first wavetable entry writes the waveform, 0
            # instead -- "no change" (gplay.c:355 `if (iptr->firstwave)`,
            # player.s `beq mt_skipwave`): the init call writes no pitch
            # (player.s `jmp mt_loadregswaveonly`), so a gate an effect had
            # closed would open there on the OLD note's frequency, a frame
            # before the new one lands (Chimera voice 1, D0A6 at 8647 ahead
            # of 1A15), where the original writes both on its fetch frame.
            # A gate-off firstwave (`gate_off_firstwave_instruments`, gate
            # bit clear) on a held note would drop the gate for a frame the
            # original never drops, so it is treated as the testbit is.
            fw = out[instr_at + 1 + (g - 1) * 25 + 8]
            i = record_of.get(g)
            if ((fw != FIRSTWAVE_TESTBIT and fw & 0x01)
                    or i is None or i < 0):
                return fw
            if start is None:
                start = out[instr_at + 1 + (g - 1) * 25 + 2]
            if ((restart_kind or legato) and 0 < start <= len(wave_entries)
                    and GT_WAVE_LAST_DELAY < wave_entries[start - 1][0]
                    < GT_WAVE_FIRST_CMD):
                return 0
            return (sid.data[det.instr_start + i * det.instr_stride + 2]
                    | 0x01) & 0xFF

        phase_kept: set = set()
        retarget: dict = {}
        if restart_kind:
            heard = _restart_heard(still, tracks, patterns, record_of, out,
                                   instr_at, wave_entries, pulse_entries,
                                   clone_firstwave, restart_kind,
                                   pulse_restart=tie_pulse_restart)
            if _split_only is None and split_copies:
                keep = _heard_splits(heard, split_rows, split_copies,
                                     tracks, patterns)
                if keep != set(split_copies.values()):
                    raise _RetrySplit(frozenset(keep))
            quiet = still - heard
            if log and quiet:
                log(f"Legato tie..............: {len(quiet)} tie row(s) kept "
                    "CMD_TONEPORTA, the restart writing what the voice "
                    "already holds")
            phase_kept |= quiet
            still = heard
            live_clones = phase_split.clones if phase_split is not None else []
            tie_distinct = _arp_phase_distinct(
                sid, det, tracks, patterns, instr_used, effects, fmt,
                table, multiplier, min_notes, lead, two_stage, sfx_drum,
                wave_program, pitch_seq, note_rows, row_calls,
                no_test_restart, voice_two_stage, instr_voices,
                gate_skip, real_firstwave_instruments,
                wave_alternate=wave_alternate,
                instr_row_calls=instr_row_calls,
                phases=(arp_phases, arp_tie_rows, pitch_phases,
                        arp_gate_phases),
                eor_phases=eor_phases)
            laid = dict(zip(tie_blocks, tie_block_starts))
            clone_start = {(rec, res): at for (rec, _c, res), at
                           in zip(live_clones, phase_clone_starts)}

            def block_start(g: int, x: int) -> int:
                # The wavetable start of record `g`'s block at residue `x`:
                # where it was laid out, 0 where it could not be.
                source = _tie_block_source(
                    g, x, _block_residue_of(g, x, arp_phases, arp_gate_phases),
                    tie_distinct, live_clones)
                own = wave_starts[g - 1] if 0 < g <= len(wave_starts) else 0
                if source == "clone":
                    return clone_start.get((g, x)) or own
                if source == "record":
                    return own
                return laid.get((g, x), 0)

            phase_kept |= _phase_locked_ties(
                sid, det, still, tracks, patterns, record_of, lead,
                arp_phases, arp_tie_rows, pitch_phases, arp_gate_phases,
                live_clones, tie_distinct, log, block_start=block_start,
                respelled=retarget, gate_skip=gate_skip)
            still -= phase_kept
        if tie_tags:
            # The pitch-sequence ties (`pitch_seq_tie_plan`): each tagged
            # row restarts the block of the phase it lands on, where the
            # block was laid out and is not the record's own. The record
            # the row lands on is re-read here, the passes since having
            # renamed columns.
            laid = dict(zip(tie_blocks, tie_block_starts))
            entry_held = _gw_note_passes._entry_instruments(tracks, patterns)
            for pn in sorted({p for p, _r in tie_tags}):
                if pn >= len(patterns):
                    continue
                pat = patterns[pn]
                held = entry_held.get(pn, set())
                live = next(iter(held)) if len(held) == 1 else 0
                for r in range(len(pat) // 4):
                    if pat[4 * r] == 0xFF:
                        break
                    if pat[4 * r + 1]:
                        live = pat[4 * r + 1]
                    tag = tie_tags.get((pn, r))
                    if tag is None or (pn, r) not in still:
                        continue
                    g, tup = tag
                    start = laid.get((g, tup), 0)
                    own_start = (wave_starts[g - 1]
                                 if 0 < g <= len(wave_starts) else 0)
                    if (start and start != own_start
                            and record_of.get(live) == record_of.get(g)):
                        retarget[(pn, r)] = start
        # In the "record" dialect a tie into the instrument the channel
        # already holds moves no pulse (the fetch writes the record's live,
        # swept value), so that tie's clone keeps the running pulse program:
        # pulse pointer 0 (gplay.c `if (iptr->ptr[PTBL])`). A tie that
        # changes record starts the new record's, as a fresh note does.
        hold_pulse = (
            (lambda base, held: bool(held)
             and record_of.get(held) == record_of.get(base))
            if restart_kind == "record" else None)
        kinds: dict = {}
        phased: dict = {}
        # At -S2 and above the first legato number is the decoy's, which
        # gt2reloc's slip turns into a no-HR record (see the decline above);
        # the clones are numbered after it.
        slip = 1 if multiplier > 1 else 0
        # The clones (and the decoy, written_instr + 1) stay below every
        # dangling reference, which a clone numbered onto it would satisfy
        # (`clone_number_ceiling`).
        ceiling = _gw_note_passes.clone_number_ceiling(patterns, written_instr)
        before = patterns
        patterns, legato_clones, declined = legato_tie_clones(
            patterns, still, tracks, cloneable, written_instr + 1 + slip,
            last_number=ceiling, log=log,
            **({"row_kind": lambda pn, r: retarget.get((pn, r)),
                "phased": phased} if retarget else {}),
            **({"kind": hold_pulse, "kinds": kinds} if hold_pulse else {}))
        if log and retarget:
            moved = sum(1 for key in retarget if key not in declined)
            if moved:
                log(f"Legato tie..............: {moved} tie row(s) restart "
                    "the block of the residue they land on "
                    f"({len(tie_blocks)} block(s) laid out for them)")
        if log and declined and ceiling < GT_MAX_INSTRUMENTS:
            log(f"Legato tie..............: clone numbers stop at {ceiling}, "
                f"below dangling instrument ${ceiling + 1:X}")
        decoy = (_gw_note_passes.legato_slip_decoy(
            patterns, tracks, written_instr, written_instr + 1)
            if slip and legato_clones else None)
        if slip and legato_clones and decoy is None:
            # The cloning re-latched the rows the early check found; keep
            # the old spelling for every tie rather than pack a slipped clone.
            if log:
                log(f"Legato tie..............: no decoy row after cloning -- "
                    f"{len(still)} tie row(s) kept CMD_TONEPORTA at "
                    f"-S{multiplier} (greloc.c:811-815)")
            patterns, legato_clones, declined = before, [], set(still)
        declined = declined | phase_kept
        if decoy is not None:
            dp, dr, held = decoy
            patterns[dp][4 * dr + 1] = written_instr + 1
            rec = instr_at + 1 + (held - 1) * 25
            pad = bytearray(out[rec:rec + 25])
            pad[7] |= GATETIMER_LEGATO
            out += pad
            written_instr += 1
            stair_aliases.append((held, written_instr))
            if log:
                log(f"Legato tie..............: decoy legato record "
                    f"{written_instr} (instrument {held}'s, latched on "
                    f"pattern {dp:02X} row {dr}) takes gt2reloc's -S"
                    f"{multiplier} slip (greloc.c:811-815)")
        for base, number in legato_clones:
            rec = instr_at + 1 + (base - 1) * 25
            clone = bytearray(out[rec:rec + 25])
            clone[7] |= GATETIMER_LEGATO
            if number in phased:
                clone[2] = phased[number] & 0xFF
            clone[8] = clone_firstwave(base, phased.get(number))
            if kinds.get(number):
                clone[3] = 0
            out += clone
            written_instr += 1
        stair_aliases.extend(legato_clones)
        out[instr_at] = written_instr
        if declined:
            # The old spelling, whole: the envelope a declined tie's new
            # instrument carries is written as it always was.
            # A kept tie can follow a stretch the cloning left latched on a
            # clone of the same instrument (no note between to re-latch):
            # that is the instrument's own envelope, not a change to write.
            # Byte-inert on the note_flag family at 6e467ff; Bump_Set_Spike
            # pattern $1F row 36 under `tie_restart` is the case.
            patterns = _tied_instrument_envelopes(
                patterns, envelopes, tracks, log, only=declined,
                alias={c: b for b, c in legato_clones})
    # A flagged note that re-attacks skips the two-stage attack and the
    # pulse reseed (`free_note_skips_two_stage`): each such row plays a
    # variant of its record that starts on the second stage with pulse
    # pointer 0. After the legato clones, whose rows it must not take
    # (`free_note_rows` leaves every CMD_TONEPORTA row alone) and whose
    # numbers come first; not beside the tempo or phase split, whose
    # renamed columns hold no record of their own here.
    if (legato and two_stage and effects and duty_split is None
            and phase_split is None
            and _gw_note_passes.free_note_skips_two_stage(sid, det)):
        # A record with no attack (`free_note_record_has_attack`) loses only
        # its pulse reseed and envelope write on a flagged note: its variant
        # keeps the wavetable start and drops the pulse pointer -- where the
        # player's counter is read only behind the two attack bits
        # (`free_note_attack_bits`). One whose pointer is already 0 needs
        # none: its full start IS the free note. A record with an attack the
        # wavetable walk cannot enter past keeps the full start.
        pulse_ok = _gw_note_passes.free_note_attack_bits(sid, det) is not None
        free_starts, pulse_only, no_variant = {}, set(), {}
        for g in range(lead + 1, instr_used + 1):
            rec = instr_at + 1 + (g - 1) * 25
            wstart = _gw_note_passes.free_note_wave_start(
                sid, det, g - lead - 1, wave_entries, out[rec + 2])
            if wstart:
                free_starts[g] = wstart
            elif not pulse_ok:
                continue
            elif _gw_note_passes.free_note_record_has_attack(
                    sid, det, g - lead - 1):
                no_variant[g] = "attack the wavetable cannot skip"
            elif not out[rec + 3]:
                no_variant[g] = "full start already keeps the pulse"
            else:
                free_starts[g] = out[rec + 2]
                pulse_only.add(g)
        free_rows = _gw_note_passes.free_note_rows(patterns,
                                                   bit7_rows(patterns))
        # A legato clone (or the decoy) of a record carries its pulse
        # pointer: a channel holding it runs that record's own program.
        same_pulse = {
            number: base for base, number in stair_aliases
            if base != number and number <= written_instr
            and out[instr_at + 1 + (number - 1) * 25 + 3]
            == out[instr_at + 1 + (base - 1) * 25 + 3]}
        patterns, free_variants, _kept = _gw_note_passes.free_note_variants(
            patterns, free_rows, tracks, free_starts, written_instr + 1,
            last_number=_gw_note_passes.clone_number_ceiling(
                patterns, written_instr), log=log,
            pulse_only=pulse_only, no_variant=no_variant,
            same_pulse=same_pulse)
        for base, _number in free_variants:
            rec = instr_at + 1 + (base - 1) * 25
            clone = bytearray(out[rec:rec + 25])
            clone[2] = free_starts[base] & 0xFF
            clone[3] = 0
            out += clone
            written_instr += 1
        stair_aliases.extend(free_variants)
        out[instr_at] = written_instr
    # The last tick of a toggling note holds the state the last toggle left,
    # where the wavetable's cycles would toggle once more
    # (`wave_eor.eor_stop_pass`). After every pass that names an instrument,
    # so the numbers it reads are the finished ones.
    if eor_span and (tuple(wave_entries[eor_span[2] - 1:eor_span[2] + 1])
                     == _gw_wave_eor.EOR_STOP_PROGRAM):
        rings = _gw_wave_eor.eor_ring_instruments(
            wave_entries,
            {g: out[instr_at + 1 + (g - 1) * 25 + 2]
             for g in range(1, written_instr + 1)
             if out[instr_at + 1 + (g - 1) * 25 + 2]},
            (eor_span[0], eor_span[1]))
        patterns = _gw_wave_eor.eor_stop_pass(patterns, tracks, rings,
                                              eor_span[2], log)
        # The gate's skip once in R calls, where R has no ring of its own
        # (`wave_eor.eor_skip_detours`): a `CMD_SETWAVEPTR` on the skip row
        # puts the R = 0 ring back on the original's frames. After the stop
        # pass, whose last-row commands it must see as taken, and after every
        # pass that names an instrument or copies a pattern.
        if eor_lib_out:
            eor_alias = {
                g: i + lead + 1 for g, i in _record_numbers(
                    lead, instr_used, duty_split, phase_split,
                    drum_variants).items()}
            for base, number in stair_aliases:
                eor_alias[number] = eor_alias.get(base, base)
            eor_starts = {g: out[instr_at + 1 + (g - 1) * 25 + 2]
                          for g in range(1, written_instr + 1)
                          if out[instr_at + 1 + (g - 1) * 25 + 2]}
            patterns, tracks = _gw_wave_eor.eor_skip_detours(
                sid, det, tracks, patterns, instr_used, lead, eor_alias,
                wave_entries, eor_starts,
                {g: out[instr_at + 1 + (g - 1) * 25 + 8]
                 for g in range(1, written_instr + 1)},
                eor_lib_out[0], multiplier, log)
            for at, track in zip(track_at, tracks):
                out[at:at + len(track)] = bytes(track)
    # A swept record's notes at a clock its program misses sound a clone of
    # it with the program of their clock class. Here, after every pass that
    # appends or renames an instrument -- the clone is made from the finished
    # record, and numbered after the last one -- and before the tables are
    # written, which it extends.
    if tri_plan is not None:
        tracks, patterns, written_instr, tri_clones = (
            _gw_tri_clock.tri_clock_clones(
                sid, det, tri_plan, tracks, patterns, out, instr_at,
                written_instr, pulse_entries, pulse_starts, lead,
                multiplier, log))
        stair_aliases.extend(tri_clones)
        for at, track in zip(track_at, tracks):
            out[at:at + len(track)] = bytes(track)
    # The bit-$80 drum's hit on a rest of its record (`sfx_rest_click`): the
    # player fires it unmasked one frame into the rest, a gate edge our KEYOFF
    # masks. After every pass that names an instrument (the clone is made from
    # the finished record and numbered after the last one), before the rest
    # park, whose `CMD_SETWAVE` rows it may have taken.
    if sfx_drum and fmt == FORMAT_GTS5:
        patterns, wave_entries, written_instr = (
            _gw_sfx_rest_click.sfx_rest_click_plan(
                det, tracks, patterns, out, instr_at, written_instr,
                wave_entries, multiplier, log))
    # `--rest-wave-silence`'s parked waveform under a LOOPING wavetable
    # (`rest_park`): the rest's `CMD_SETWAVE $08` is overwritten by the next
    # call's WAVEEXEC, so such a rest points at a parked program appended
    # here instead. Inert where no pattern holds a `CMD_SETWAVE $08` row.
    # After every pass that names an instrument or appends a block (it reads
    # the finished starts), before the table is written.
    # `--rest-program-stop` is the same pass restricted to the instruments
    # whose record selects the byte-code program -- the only ones a bit-6 rest
    # stops (`detect.wave_program_rest_bypass`). The record's effect byte is
    # the third field of the name `_write_instruments` gives each instrument.
    program_only = None
    if rest_program_stop:
        program_only = _gw_rest_park.program_instruments(
            out, instr_at, written_instr, det.wave_program_gate,
            det.effect_arp)
    patterns, wave_entries = _gw_rest_park.rest_park_plan(
        patterns, tracks, wave_entries,
        {g: out[instr_at + 1 + (g - 1) * 25 + 2]
         for g in range(1, written_instr + 1)}, log,
        **({} if program_only is None else {
            "only": program_only,
            "lagged": _gw_rest_park.lagged_instruments(
                out, instr_at, written_instr)}))
    if dead_dropped:
        # A record dropped as unnamed, named after all by a pass that ran
        # later: its pointer is 0 and it would play nothing. Never ship that.
        revived = dead_dropped & _gw_dead_blocks.named_records(patterns)
        if revived:
            raise _RetryDeadBlocks(frozenset(revived))
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
    # Bit $02's rise under the arpeggio as a pattern-side stair: a note per
    # semitone on a zero-speed toneportamento (`rise_stair_plan`). LAST of
    # every pattern pass, so nothing that walks note rows -- the phase
    # walks, the tie respells, the decoy search -- reads a step as a note,
    # and before the speed table, which gains its zero-speed row here.
    # Gated on `effects` like every read of +7.
    if effects and ((det.effect_rise and det.effect_arp)
                    or det.effect_fall is not None):
        stair_records = {g: g - lead - 1 for g in range(lead + 1, instr_used + 1)}
        for plan in (duty_split.clones if duty_split is not None else [],
                     phase_split.clones if phase_split is not None else []):
            for record, number, _x in plan:
                if record in stair_records:
                    stair_records[number] = stair_records[record]
        for base, number in stair_aliases:
            if base in stair_records:
                stair_records[number] = stair_records[base]
        stair = _gw_rise_stair.rise_stair_plan(sid, det, tracks, patterns,
                                               stair_records, fmt, table,
                                               log=log)
        if stair is not None:
            # Its copies repoint orderlist positions: same length, same
            # place, as `rest_reseed`'s do.
            patterns, tracks = stair
            for at, track in zip(track_at, tracks):
                out[at:at + len(track)] = bytes(track)
    # A free-running filter sweep holds for one call on every event its
    # driving voice fetches, and a tie or a KEYOFF is an event that loads no
    # instrument, so nothing holds it (`free_running_fetch_holds`). Last of
    # the passes that fill a command column, so it takes only columns nobody
    # else wanted; the instrument records are final here, clones included.
    # The original's hold is a frame without a step, which is `multiplier`
    # calls: the instrument's block opens with that many params rows
    # (`_free_running_block`'s `hold_calls`), so the one pointer jump covers
    # the whole frame at any -S.
    if (filters and filter_entries and filter_ptrs and det.filter is not None
            and det.filter.free_running):
        hold_voice = _gw_filters.free_running_fetch_hold_voice(sid)
        if hold_voice is not None:
            ptr_of = {g: out[instr_at + 1 + (g - 1) * 25 + 4]
                      for g in range(1, written_instr + 1)}
            patterns, tracks, _held = _gw_filters.free_running_fetch_holds(
                tracks, patterns, ptr_of, hold_voice, log=log)
            for at, track in zip(track_at, tracks):
                out[at:at + len(track)] = bytes(track)
    # The classic sweep's stops, `A 00` on the note where a sweeping voice
    # moves to an unfiltered record. After every pass that fills a command
    # column, like the fetch holds above: it takes only what nobody wanted.
    if stop_sites and filter_ptrs:
        patterns, tracks, _stopped = _gw_classic_filter_stop.apply_stops(
            tracks, patterns, stop_sites, log=log)
        for at, track in zip(track_at, tracks):
            out[at:at + len(track)] = bytes(track)
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

    # One D0v per subtune, LAST: after `apply_tempos` (convert.py) and every
    # pass above, so no tempo can have been skipped for it
    # (`patterns.apply_master_volume`).
    if master_volume and det.master_volume is not None:
        from ..patterns import apply_master_volume
        patterns = [list(p) for p in patterns]
        apply_master_volume(patterns, tracks, det.master_volume, log)

    out.append(len(patterns) & 0xFF)
    for pattern in patterns:
        out.append((len(pattern) // 4) & 0xFF)
        out += bytes(pattern)

    return bytes(out)


def build_sng(sid, det, tracks, patterns, *args, **kw):
    """`_build_sng`; under `drop_dead_blocks` a build in which a later pass
    named a record whose block was dropped is redone without the drop."""
    if not kw.get("drop_dead_blocks") or args:
        return _build_sng_split(sid, det, tracks, patterns, *args, **kw)
    log = kw.get("log")
    spare = (copy.deepcopy(tracks), copy.deepcopy(patterns))
    lines: list = []
    try:
        out = _build_sng_split(sid, det, tracks, patterns,
                               **dict(kw, log=lines.append))
    except _RetryDeadBlocks as retry:
        if log is not None:
            log("Dead wavetable blocks...: record(s) "
                + ", ".join(f"${g:02X}" for g in sorted(retry.args[0]))
                + " named after the drop, built again without it")
        return _build_sng_split(sid, det, spare[0], spare[1],
                                **dict(kw, drop_dead_blocks=False))
    if log is not None:
        for line in lines:
            log(line)
    return out


def _build_sng_split(sid, det, tracks, patterns, *args, **kw):
    """`_build_sng`; under `tie_restart` a build whose entry-instrument split
    copied a pattern only for quiet restarts (`_heard_splits`) is redone
    without those copies."""
    if not kw.get("tie_restart") or args:
        return _build_sng(sid, det, tracks, patterns, *args, **kw)
    log = kw.get("log")
    spare = (copy.deepcopy(tracks), copy.deepcopy(patterns))
    lines: list = []
    first = dict(kw, log=lines.append)
    try:
        out = _build_sng(sid, det, tracks, patterns, **first)
    except _RetrySplit as retry:
        second = dict(kw, _split_only=retry.args[0])
        return _build_sng(sid, det, spare[0], spare[1], **second)
    if log is not None:
        for line in lines:
            log(line)
    return out
