"""End-to-end .sid -> .sng conversion (port of loadfile()'s FindEnd block)."""
from __future__ import annotations

from typing import Callable, List

from .detect import Detection, PlayerView, detect, player_view
from .goatwriter import (DEFAULT_FORMAT, FORMAT_GTS2, FORMATS, GT_MIN_TEMPO,
                         TEMPO_FASTEST_STEADY,
                         append_song, build_sng, derived_group_tempos,
                         file_multiplier, orderlist_tempo_calls,
                         orderlist_tempo_values,
                         write_funktempo,
                         outer_gate_skip, pulse_phase_sims,
                         pulse_bounds_sims, pulse_reseed_gated,
                         triangle_start,
                         build_pulse_phase_table, _instruments_used, find_song_speeds, effective_frames,
                         HEADER_LEN, startup_phase)
from .patterns import (DEFAULT_TRACK, GT_COMMAND_FLOOR, GT_DEFAULT_ROWS,
                       ConversionAbort, build_speed_table,
                       scale_portamento_data, command_floor,
                       convert_patterns, apply_tempo, apply_tempos, regrid_tempos,
                       cmdtable_frames_per_row,
                       min_played_notes, median_played_durations,
                       pattern_references, drop_unplayed_patterns,
                       referenced_patterns, reindex_tracks,
                       collect_pulse_phases, apply_pulse_phase,
                       inherit_free_rows, inherit_event_rows)
from .instrument_drop import (
    add_startup_tempo,
    drop_unnamed_instruments as drop_unnamed_instruments_from)
from .past_table_wave import pin_past_table_wave_notes
from .sidfile import SidFile, load_sid
from .stored_wave import stored_wave_copies
from .tracks import (apply_initial_instruments, convert_tracks,
                     ensure_playable_orderlists, fold_transposes,
                     silence_pre_instrument_notes,
                     instrument_row_calls, instrument_voices,
                     instrument_transposes,
                     legalise_restarts)

Logger = Callable[[str], None]


class UnsupportedSidError(Exception):
    pass


# Share of orderlist entries that may name a pattern the file does not have
# before the whole detection is judged unsound rather than merely lossy.
#
# Chosen from the corpus, not picked round: the two files whose signature match
# is a false positive sit at 89% and 100% dangling, and the worst *legitimate*
# file -- Mega Apocalypse, real music carrying many phantom subtunes -- sits at
# 46%. Anything in between separates them; 2/3 leaves a 20-point margin on the
# tunes that must keep converting and a 23-point margin on the ones that must
# not.
MAX_DANGLING_SHARE = 2 / 3


def _tables_readable(det: Detection) -> bool:
    """True if detection found tables that actually name patterns.

    `can_convert` only says all four bases were located; a player whose table
    operands are placeholders until init patches them locates bases fine and
    then reads no patterns at all.
    """
    return det.can_convert and det.pattern_used > 0


def _detect_tables(sid: SidFile, log: Logger, engine: int = 0):
    """(image, detection), re-reading the file with init's writes if needed.

    The re-read is a strict fallback: a file whose operands already name real
    tables is returned untouched, so applying init writes can rescue a file
    that reads nothing but can never disturb one that reads correctly. Only
    the winning attempt's log lines are emitted, so the output shows one
    SEARCHING block either way.
    """
    lines: List[str] = []
    det = detect(sid, lines.append, engine)
    if not _tables_readable(det):
        staged = sid.with_init_writes()
        if staged is not None:
            staged_lines: List[str] = []
            staged_det = detect(staged, staged_lines.append, engine)
            if _tables_readable(staged_det):
                for line in staged_lines:
                    log(line)
                log("Table pointers..........: written by init, re-read after applying them")
                return staged, staged_det
    for line in lines:
        log(line)
    return sid, det


def check_detection_sound(tracks, pattern_used: int, log: Logger,
                          floor: int = GT_COMMAND_FLOOR) -> None:
    """Reject a detection whose orderlists mostly name patterns that don't exist.

    A signature can match code that is not the tune's player -- One on One's
    match yields three "orderlist" pointers into nibble-packed sample data, and
    ACE 2's first orderlist byte is already a restart command. Every downstream
    guard then behaves correctly on garbage and produces a structurally valid,
    musically empty .sng: a failure that reads as a success.

    Individually bad references are normal and must not trip this (phantom
    subtunes alone account for up to 46% of a real file's references). Only the
    proportion across the whole file distinguishes the two.
    """
    if not tracks:
        log("*** NO SUBTUNE PLAYS ANY EXISTING PATTERN ***")
        raise UnsupportedSidError("NO PLAYABLE SUBTUNE, CAN'T CONVERT")

    refs = pattern_references(tracks, floor)
    dangling = [r for r in refs if r > pattern_used]
    if not refs or len(dangling) / len(refs) > MAX_DANGLING_SHARE:
        share = f"{100 * len(dangling) // len(refs)}%" if refs else "no"
        log(f"*** {share} OF ORDERLIST ENTRIES NAME PATTERNS THAT DO NOT EXIST ***")
        raise UnsupportedSidError(
            "ORDERLISTS DO NOT MATCH THE PATTERN TABLE, DETECTION IS UNSOUND")


def _derived_multiplier(sid: SidFile, det: Detection, skip_gate: bool) -> int:
    """The `gt2reloc -S` factor this tune will be packed at.

    Derived the way the PACKER derives it, which is the point: the harness
    computes the pack factor for itself (`fidelity._skip_gate_multiplier`
    re-runs `find_song_speeds` / `recommended_multiplier`), so a conversion
    that leaves its own `multiplier` at 1 does not thereby get packed at -S1 --
    it gets packed at -S{M} with every per-call rate written for -S1. Slide
    steps, drum sweeps, wavetable delays and the pulse programs are all divided
    by this number at the point they are encoded, so a wrong value here is
    silent and total.

    That is exactly what `tempo != "auto"` used to do: `multiplier` was
    assigned only on the fully-derived path, so forcing a tempo left every rate
    at the -S1 scaling while the file was still packed at its real factor. It
    read as the probe breaking rather than the hypothesis -- a forced-tempo
    A/B of Skate or Die intro measured melody 0.0%.

    Falls back to 1 on any failure, which is the same answer the caller used to
    hardcode, so a file whose speeds cannot be read is no worse off than before.
    """
    try:
        speeds = find_song_speeds(sid, det)
        return file_multiplier(sid, speeds, skip_gate)
    except Exception:                                          # noqa: BLE001
        return 1


def regrid_deficits(speeds, values: List[int], skip_gate: bool,
                    multiplier: int) -> List[float]:
    """Per subtune, the FRAMES per row `regrid_tempos` must make up, or 0.0.

    Only where `effective_frames` DECLINED the exact row and the subtune's
    tempo is that declined row -- if it was encodable, the tempo already
    carries it and compensating again would double-count.

    **UNITS.** `exact` and `eff` are frames per row; `values` are CALLS (the
    CMD_SETTEMPO value, frames * multiplier); `regrid_tempos` wants frames and
    multiplies by `multiplier` itself. Through v0.5.511 this compared `eff`
    with `values[k]` directly, which is the same number only at -S1 -- so no
    multispeed file could ever be reached, whatever `--regrid` said. Star_Paws
    is the file that found it: its subtune 0 reads 256/127 frames (a two-frame
    speed gate under `DEC $B712 / BPL / LDA #$7F / STA $B712 / JMP $B06B`,
    which freezes the speed counter one frame in 128), encoded as 2 frames =
    tempo 4 at -S2, and `2.0 != 4.0` declined it. Ours ran one frame in 128
    fast, `drift` -7.81 per 1000, 71 frames ahead by 180 s -- read on the
    8-frame drum grid of voices 2 and 3 as attacks landing "3 frames late",
    the -5 aliased by nearest-neighbour pairing.
    """
    deficits = []
    for k in range(len(values)):
        exact = speeds.exact_row(k) if speeds is not None else None
        eff = effective_frames(speeds, k, skip_gate)
        if (exact is None or eff is None
                or float(eff) * multiplier != float(values[k])):
            deficits.append(0.0)
        else:
            deficits.append(max(0.0, float(exact) - float(eff)))
    return deficits


def convert(sid_path: str, log: Logger = print,
            max_rows: int = GT_DEFAULT_ROWS,
            terminate_patterns: bool = False,
            fmt: str = DEFAULT_FORMAT,
            dedup: bool = False,
            prune: bool = False,
            pack: bool = False,
            legal_restart: bool = False,
            silent_park: bool = False,
            force_park: bool = False,
            regrid: bool = False,
            slides: bool = False,
            effects: bool = False,
            status_bit6: bool = False,
            fold_transpose: bool = False,
            skip_gate: bool = False,
            initial_instrument: bool = False,
            sustain_exact: bool = False,
            no_hard_restart: bool = False,
            wide_hard_restart: bool = False,
            max_hard_restart: bool = False,
            hard_restart_frames: int | None = None,
            no_test_restart: bool = False,
            two_stage: bool = False,
            voice_two_stage: bool = False,
            wave_alternate: bool = False,
            sfx_drum: bool = False,
            wave_program: bool = False,
            vibrato_command: bool = False,
            cut_release: bool = False,
            tie: bool = False,
            pitch_seq: bool = False,
            arpeggio: bool = False,
            filters: bool = False,
            pulse: bool = False,
            vibrato: bool = False,
            rest_instrument: bool = False,
            rest_keyoff: bool = False,
            rest_wave_silence: bool = False,
            rest_envelope_silence: bool = False,
            compact_instruments: bool = False,
            engine: int = 0,
            tempo: int | str | None = None,
            real_firstwave_instruments: tuple = (),
            pulse_phase: bool = False,
            drop_unnamed_instruments: bool = False,
            ilv_filter_routing: bool = False,
            gate_off_firstwave_instruments: tuple = (),
            tie_restart: bool = False,
            regrid_full_debt: bool = False) -> bytes:
    """Convert a .sid to .sng bytes.

    max_rows is the pattern-slicing length. It defaults to 94 (what the
    original VB6 tool used, and what the byte-exact Commando fixture encodes);
    128 is Goattracker's real MAX_PATTROWS since v2.32 and produces fewer,
    longer patterns -- which shortens orderlists and converts some tunes that
    otherwise exceed Goattracker's limits.

    prune drops every pattern no track's orderlist references. It cannot
    change playback -- an unnamed pattern is unreachable -- but it does
    renumber the ones that remain, so it is opt-in like the other
    output-changing options.

    pack collapses runs of one repeated pattern into Goattracker REPEAT
    commands. It is the only option that shortens an orderlist, and so the
    only one that can rescue a tune from the 254-byte orderlist limit.

    legal_restart rewrites the out-of-range restart position that stands in
    for Hubbard's "tune ended" marker, which Goattracker's exporter
    (greloc.c:244) refuses outright -- so without it gt2reloc silently
    produces no .sid for those tunes. The tune loops instead of ending; see
    tracks.legalise_restarts.

    terminate_patterns appends an explicit ENDPATT row to every pattern
    slice that lacks one, matching what Goattracker's own saver writes.
    Off by default: it changes the bytes, and the Commando fixture encodes
    the original tool's unterminated output.

    slides reads a pitch-slide command's second operand byte in the players
    that have one, giving the true 16-bit step instead of half of it and --
    more importantly -- keeping the rest of the pattern in step. It applies
    only where detection found that fetch (det.slide_operand), so it is a
    no-op for 54 of the 95 corpus files and for the Commando fixture. Off by
    default because it changes the bytes of the 41 files it does reach.

    effects decodes the two bits of the instrument effect byte (+7) that the
    original mis-read: bit $02's chromatic rise, which it ignored entirely,
    and bit $04's arpeggio with a zero interval nibble, for which it invented
    an octave-up arpeggio the player never plays. Both live in the wavetable.
    Off by default: the Commando fixture has six instruments in the second
    case and one in the first. See goatwriter._wavetable_entries.

    pulse writes the player's per-frame pulse-width sweep into the pulse
    table instead of freezing each instrument's duty cycle at its starting
    value. 414 records across 43 corpus files sweep; the rest have a zero rate
    and are unaffected. Off by default because it changes the bytes of those
    43 files. See goatwriter._pulse_program and detect._find_pulse_sweep.

    status_bit6 honours the player's bit-6-first status test (`BIT status /
    BVS`, detect.STATUS_BIT6_SHAPE): a $C0-$FE status byte consumes only
    itself instead of also an operand and a note the player never reads.
    Applies only where detection finds that shape (61 of 95 corpus files,
    Commando among them), so it is gated the same way slides is. Off by
    default: it changes the bytes, and the byte-exact Commando fixture
    encodes the old three-byte reading.

    compact_instruments drops the empty "Clear Voice" slot the VB6 original
    reserved at instrument 1, putting the player's record 0 there instead.
    Goattracker reserves nothing: its format stores instruments from 1 and a
    pattern column of 0 already means "no change" (readme:613, 1386), so the
    placeholder is inherited convention, not a requirement. It costs an
    instrument slot, five wavetable entries, and -- the reason it was noticed
    -- offsets every instrument number by one against the player's own
    numbering, which makes the file hard to read against the original. Off by
    default because it renumbers every instrument in every file, the byte-exact
    Commando fixture included.

    rest_instrument carries an instrument change that lands on a rest with the
    rest itself, instead of the C-0-on-instrument-1 the original tool emitted.
    Goattracker latches the instrument column whenever it is non-zero, before
    and independently of the note test (gplay.c:912-914), so a $BD row can
    carry the change and sound nothing -- where instrument 1 is the hardcoded
    Clear Voice, all-zero ADSR with the testbit set, i.e. a click and a
    retrigger. 1422 rows across 64 corpus files. Off by default because it
    changes the bytes of those files, the byte-exact Commando fixture among
    them; found by ear, and no dimension of FIDELITY.md reports it.

    rest_envelope_silence writes `CMD_SETSR $00` on a bit-6 rest, which is
    what the player does there: all 21 corpus players that silence on such a
    rest zero the voice's envelope pair in the branch itself
    (detect._find_rest_silence_envelope), so the note that was sounding stops
    dead. A Goattracker KEYOFF clears only the gate, so without this the
    record's release nibble plays out across a gap the original silences --
    ACE_II's two lead instruments carry release 9 and ring through 575 of its
    voice-1 frames where the original's ADSR reads $0000. Not the same lever
    as cut_release: that zeroes the nibble in the *instrument*, which is right
    only for the 33 players that cut at every note end. These 21 cut at the
    rest alone and their ordinary note ends do sound the release.

    fold_transpose recovers the orderlist transposes Goattracker's +14
    ceiling used to clamp away, by keeping `T mod 12` in the orderlist and
    folding the whole octaves into a copy of each pattern the step plays.
    17 corpus files carry such a transpose and five of them are audibly
    detuned by it -- up to 34 semitones. Costs one pattern-table entry per
    distinct (pattern, octaves) pair; steps whose notes have no room to rise
    are left clamped. Off by default: it changes the bytes of the files it
    reaches. See tracks.fold_transposes.

    real_firstwave_instruments names the GT instrument numbers (1-based,
    matching a pattern row's instrument column AS WRITTEN, i.e. BEFORE
    `drop_unnamed_instruments` renumbers them -- songview shows the
    post-drop number; 5_Title_Tunes' preset (1, 2, 3, 5, 6, 8) is
    (1, 2, 3, 4, 5, 7) in the opened file, record 4 being dropped;
    tests/test_firstwave_numbering_after_drop.py) whose "first frame" byte is
    the record's own waveform with the gate forced on, rather than the
    neutral testbit-only byte every instrument gets by default -- the same
    byte `no_test_restart` changes, but per instrument instead of for the
    whole file. `no_test_restart` recovered ACE_II's drum (instrument 1 on
    voice 2, melody 37% -> 99.6%) but broke voice 1 at the same time (100% ->
    14%, a different mechanism, in the wavetable-entries code this option
    does not touch) -- so a file-wide flag cannot ship the fix without the
    regression. Naming only the instrument that needs it avoids that: empty
    by default and byte-inert everywhere it names nothing. See
    goatwriter._write_instruments.

    gate_off_firstwave_instruments names GT instrument numbers the same way
    whose firstwave is the record's own waveform with the gate CLEARED
    (`waveform & $FE`; goatwriter.instruments.gate_off_firstwave) instead of
    the testbit `$09`. The init call writes only `$D404`, and `$09`'s gate
    bit opens every note one frame before the original does
    (tests/test_firstwave_gate_edge.py). Only that byte changes: the
    wavetable keeps the testbit's lead-entry layout. Where both lists name an
    instrument, or `no_test_restart` is set, the real-waveform byte wins.
    Empty by default, so byte-inert where it names nothing; a per-song,
    hand-recorded choice, because forced on every instrument it trades
    columns per song (run record gate-off-firstwave-option).

    wave_alternate emits effect bit $02's DERIVED alternate waveform
    (det.wave_alternate_noise: `AND #$07 / ORA #$80`, noise at the voice's
    own control bits) in the two players that derive it rather than table it
    -- Chicken Song and Hollywood or Bust. Per song and off by default: it
    trades Chicken Song `wave` for noise frames and costs Hollywood or Bust
    11.5 points of melody (figures beside the emission in goatwriter, and
    in presets.EXCLUDED_FROM_ALWAYS). Byte-inert on every other file.

    drop_unnamed_instruments removes, from the finished file, every
    instrument record no pattern row names, and renumbers the instrument
    columns to match; instrument 1 is always kept, because both players
    start every voice on it (gplay.c:62, player.s:621). Knucklebusters'
    record 27 -- $00 $00, pulse width $000, an empty wavetable block, named
    0 times -- is the case that asked for it. The packed .sid is unchanged
    (greloc.c:291 already drops them); the tables are left as written.
    Applied after every pass, so `real_firstwave_instruments` and the clone
    passes still number instruments as written. Off by default: the Commando
    fixture carries one such record (its instrument 13). See
    instrument_drop.

    ilv_filter_routing writes the interleaved player's per-voice filter
    routing as CMD_SETFILTERCTRL (B) commands at every row where the union of
    the voices' routed bits changes, instead of routing all three voices from
    every program's params row (`goatwriter.ILV_FILTER_ROUTING`) and the gated
    instrument clear. Needs `filters`; reaches only files with
    `det.ilv_filter` and a program with a passband. Off by default: it moves
    the bytes of the files it reaches. See goatwriter.ilv_filter_routing_plan.

    tie_restart spells a tie in the classic players WITHOUT the legato
    marker (`goatwriter.classic_tie_restart_family`: Commando, Monty on the
    Run, International Karate and 32 more) as a plain note on a legato clone
    of its instrument, the spelling `legato_tie_clones` already gives the
    marker players' unflagged ties: those players re-run the whole
    instrument start -- waveform with the gate, pulse, AD, SR, the effect
    counters -- on every fetched note, tied or not, where `CMD_TONEPORTA 00`
    skips all of it. Only a restart that is HEARD is respelled (another
    record, a block or sweep the restart replays; `build._restart_heard`):
    one that writes what the voice already holds keeps the old spelling,
    and so does one whose restarted block would leave the arpeggio
    counter's phase. Needs `tie`. Off by default: Commando is one of
    these players, and the fixture encodes the old spelling (its own ties
    all restart silently, so presets move none of its bytes either).

    regrid_full_debt makes `regrid`'s budget pay the whole debt: it counts
    every PLAY of a voice-0 pattern, packed `$D0+n` repeats included, and
    charges only the compensating rows the writer can actually place, so a
    row declined by a full command column carries its debt forward instead
    of vanishing (patterns `_regrid_order`, `_regrid_spots`). Needs `regrid`.
    Off by default because both corrections move the bytes of ten of the -S1
    files that ship `regrid` (measured at 6e467ff), whose adoptions were
    measured under the old budget; per song, hand-adopted like `regrid`.

    A COMPILATION -- several players behind an init/play dispatch
    (`detect.find_players`) -- converts subtune 0 from the first player as
    before, then appends each further player's own conversion as the next
    subtune. See `_append_players`. `sid_path` may also be an already-loaded
    `SidFile`, which is how each player's view is converted.
    """
    opts = {k: v for k, v in locals().items() if k not in ("sid_path", "log")}
    sid = sid_path if isinstance(sid_path, SidFile) else load_sid(sid_path)
    log("------------------------------------------------------SID INFO---")
    log(f"SID Name....: '{sid.name}'")
    log(f"SID Author..: '{sid.author}'")
    log(f"SID Released: '{sid.released}'")
    log(f"SID Loadaddr: ${sid.load_addr:X}")
    log(f"SID Subtunes: ${sid.subtunes:X}")
    if sid.relocation is not None:
        r = sid.relocation
        log(f"SID Relocates: ${r.src:X}-${r.src + r.length - 1:X} "
            f"-> ${r.dst:X} at init")

    log("-----------------------------------------------------SEARCHING---")
    sid, det = _detect_tables(sid, log, engine)

    log("--------------------------------------------------------STATUS---")
    if not det.can_convert:
        raise UnsupportedSidError("NO HUBBARD PLAYER DETECTED, CAN'T CONVERT")

    log("*** HUBBARD PLAYER DETECTED, CONVERTING ***")
    log("----------------------------------------------------CONVERTING---")

    raw_transposes: List[dict] | None = [] if fold_transpose else None
    # Unconditional, like the terminators they come from: `$FE nn` is a tempo
    # change the player really makes, and dropping it plays the rest of the
    # tune at the tempo its init happened to set. Only one corpus player has
    # the command at all (detect._find_track_terminators), so this is empty
    # for every other file and the pass below never runs.
    raw_tempos: List[dict] = []
    tracks = convert_tracks(sid, det, log, raw_transposes, raw_tempos)
    # These three all read orderlists that are still in Hubbard numbering, so
    # they need the dialect's command boundary rather than Goattracker's.
    floor = command_floor(det.read_track_version, det.track_fd_transpose)
    check_detection_sound(tracks, det.pattern_used, log, floor)
    # After the soundness check, which counts a reference above pattern_used as
    # dangling -- and every variant this adds is one, by construction. Before
    # `played`, so the variants are what pruning keeps rather than what it
    # drops.
    variants = (fold_transposes(sid, det, tracks, raw_transposes, log,
                                slides, status_bit6)
                if fold_transpose else [])
    # Beside fold_transposes rather than inside convert_tracks: both walk the
    # orderlists for a per-pattern fact the patterns alone cannot supply, and
    # both need this call's own `slides`/`status_bit6` -- the grammar the
    # instrument-indexed transpose's entry state is read under is the grammar
    # convert_patterns will actually decode each pattern with, not a
    # convert_tracks-time guess at every reading the player admits. See
    # tracks.instrument_transposes.
    if det.instr_transpose >= 0:
        det.instr_entry_transposes = instrument_transposes(
            sid, det, tracks, log, slides=slides, status_bit6=status_bit6)
    played = referenced_patterns(tracks, floor)
    # Decided before the patterns are built, because it sets how many rows
    # each event becomes -- and it is only ever anything but 1 for the
    # command-table dialect, so no other file's output can move.
    det.frames_per_row = cmdtable_frames_per_row(sid, det, played)
    # The pattern data column holds one byte, and a slide step is sixteen. In a
    # GTS5 file the column ends up a 1-based *index* into the speed table
    # anyway (gplay.c:740), so let the decoder write that index directly and
    # keep the steps themselves at full width here -- see patterns._step_index.
    #
    # Only where every non-zero portamento column can have come from the slide
    # branch: the classic grammar, with the two-byte fetch honoured. Without
    # the fetch the column is the old packed value and must stay one, and the
    # digi and cmdtable grammars build their columns elsewhere. A GTS2 file
    # keeps the packed value too, because its loader reads that column as the
    # value (gsong.c:311-321) and there is no stored table for an index to
    # name.
    #
    # The digi grammar qualifies on the same terms: its $82 effect is the only
    # thing that puts a non-zero value in a portamento column, and it needs no
    # separate fetch flag -- the operands are part of the command.
    slide_steps: list | None = None
    if fmt != FORMAT_GTS2 and slides and (
            (det.slide_operand and det.pattern_dialect == "classic")
            or det.pattern_dialect == "digi"
            or (det.pattern_dialect == "cmdtable" and det.cmd_slide >= 0)):
        slide_steps = []
    # The interleaved engine's `$83` semitone arpeggio (patterns.ILV_ARP).
    # A list rather than a flag because the decoder collects the distinct
    # `(record, operand)` pairs into it and emits their INDEX; the wavetable
    # row is not known until `build_sng` lays the table out. None on every
    # other dialect, so nothing else can grow a command column.
    ilv_arps: list | None = [] if (arpeggio and det.pattern_dialect == "ilv") else None
    instr_base = 1 if compact_instruments else 2
    # The bounds pulse engine's phase walk (below, beside the triangle
    # engine's) needs the note byte's bit 7 carried out of the decoder per
    # row, and the request changes the dedup key -- so it is made only
    # where that walk is going to run: the option on, the engine present
    # with its reseed test in the spelling the sim was validated on, and a
    # record that sweeps. `pulse_phase_sims` (the triangle engine) returns
    # nothing on these files, and vice versa, so the two never both apply.
    phase_lead = 0 if compact_instruments else 1
    bounds_sims = (pulse_bounds_sims(sid, det, phase_lead)
                   if pulse_phase and pulse and det.pulse_bounds >= 0
                   and det.pulse_tri_hi < 0 and pulse_reseed_gated(sid)
                   else {})
    # A note byte past the table that lands on the per-voice stored-waveform
    # cells sounds what voices 0 and 1 hold at that moment -- read by walking
    # the orderlists, which are still in Hubbard numbering here, under the
    # grammar convert_patterns decodes with. Not an option: it is what the
    # player does. Commando is held out by name (stored_wave.HELD).
    #
    # Since the pitch is the OTHER voices' state, two orderlist positions
    # naming one pattern can sound it differently; each such position gets
    # a copy numbered after fold_transposes' variants, and the orderlist
    # byte is rewritten here, after `played` -- a copy is appended like a
    # variant, never pruned, and its source stays referenced by the
    # positions that kept the majority.
    wave_notes, wave_copies = stored_wave_copies(
        sid, det, tracks, det.pattern_used + 1 + len(variants), floor, log,
        slides=slides, status_bit6=status_bit6)
    want_event_rows = bool(pulse_phase and pulse and det.pulse_tri_hi >= 0)
    new_patterns, track_index = convert_patterns(
        sid, det, log, max_rows, terminate_patterns, dedup,
        used=played if prune else None,
        slides=slides, status_bit6=status_bit6,
        variants=variants, steps=slide_steps, arps=ilv_arps,
        rest_instrument=rest_instrument,
        rest_keyoff=rest_keyoff,
        # Only the testbit family parks a waveform; the envelope-zeroing
        # four write none, and a KEYOFF already says what they do.
        rest_wave=rest_wave_silence and det.rest_silence_kind == "testbit",
        # ...but *every* one of the 21 zeroes the envelope pair, which is
        # the half a KEYOFF cannot say. See
        # detect._find_rest_silence_envelope.
        rest_envelope=rest_envelope_silence and det.rest_silence_envelope,
        instr_base=instr_base, tie=tie,
        wave_notes=wave_notes, wave_copies=wave_copies,
        # The triangle walk's fetch rows (patterns.collect_pulse_phases'
        # `event_rows`). Unlike `free_rows` the request moves no byte -- the
        # dedup key is left alone -- so it is made wherever that walk can run.
        event_rows=want_event_rows,
        free_rows=bool(bounds_sims))
    # Captured before reindexing: groups equal header subtune numbers until a
    # split inserts extra ones, and the tempo derivation is per subtune.
    subtunes_before = len(tracks) // 3
    # Resolved before reindexing because that is where the substitution has to
    # happen -- see patterns._apply_orderlist_tempos for why it cannot wait
    # until after packing.
    step_tempos = (orderlist_tempo_values(sid, det, raw_tempos, tempo, skip_gate)
                   if any(raw_tempos) else None)
    # The same changes unrounded, so the part of a row the rounding drops is
    # spent inside each segment's patterns -- see
    # patterns._compensate_fractional_rows.
    step_calls = (orderlist_tempo_calls(sid, det, raw_tempos, tempo, skip_gate)
                  if step_tempos else None)
    tracks = reindex_tracks(tracks, track_index, pack, floor, log,
                            patterns=new_patterns, max_rows=max_rows,
                            tempos=step_tempos, tempo_calls=step_calls)
    if step_tempos:
        n = sum(len(m) for m in step_tempos)
        log(f"Orderlist tempo.........: {n} mid-song tempo change(s) from the "
            "track dialect's $FE nn")
    # Unconditional, and before the restart pass: a voice whose orderlist
    # holds nothing but an end marker makes greloc.c skip its whole subtune,
    # and every subtune past the resulting count is never written to the
    # packed .sid at all. That is silent data loss, not a stylistic choice,
    # so it is not gated behind an option.
    ensure_playable_orderlists(tracks, log)
    # After reindexing, so the orderlist bytes and `new_patterns` indices are
    # both Goattracker's; before the restart pass, which reads orderlist
    # lengths this may not change but must not race.
    if initial_instrument and not det.pre_instrument_silence:
        apply_initial_instruments(tracks, new_patterns, det, log,
                                  instr_base=instr_base)
    # Unconditional, and the exact converse of the line above -- which is why
    # the two are mutually exclusive rather than merely ordered. Where the
    # player parks silence in the stored waveform until a voice's first
    # instrument, a note before then sounds NOTHING, so giving the voice an
    # instrument there is precisely the wrong repair. Not gated behind an
    # option because it is a property of the player, measured per build, not a
    # preference: see detect.PRE_INSTRUMENT_SILENCE.
    silence_pre_instrument_notes(tracks, new_patterns, det, log)
    if legal_restart:
        # After reindexing, packing, merging and splitting: those all change an
        # orderlist's length, and whether a restart position is in range is a
        # question about the finished list.
        #
        # `silent_park` hands the pattern table over so a tune that ENDED can
        # be parked on silence rather than looped from the top -- the repair
        # for the length rule, where restart-0 is only the workaround that
        # makes the file packable. It rides on `legal_restart` because it is
        # the same decision about the same byte: without that flag there is no
        # restart position to choose.
        legalise_restarts(tracks, log,
                          new_patterns if silent_park else None,
                          force_park=force_park,
                          # The silent pattern's event starts, beside the
                          # ones convert_patterns entered (only where asked).
                          event_rows=(track_index.event_rows
                                      if want_event_rows else None))
    # Every subtune dropped means the file carries no orderlist at all -- the
    # same refusal the empty-tracks case gets, for the same reason.
    if all(t == DEFAULT_TRACK for t in tracks):
        raise UnsupportedSidError(
            "EVERY SUBTUNE'S ORDERLIST EXCEEDS GOATTRACKER'S LIMIT, CAN'T CONVERT")

    # The gt2reloc -S factor this tune needs, where it is derivable. The pulse
    # table is stepped per play call, so a sweep written for one call a frame
    # runs at twice its rate under -S2; only the auto path knows the factor.
    multiplier = 1
    group_tempos = None
    # The row length in play calls, for build_speed_table's lost-call
    # compensation. The largest one the file writes, because a pattern shared
    # between two subtunes at different tempos has no single right answer and
    # under-compensating the faster one is the safe direction -- see
    # patterns.build_speed_table.
    row_calls = 0
    # The *shortest* row any subtune writes, for the drum sweep's duration
    # bound. Opposite end of the same spread as `row_calls` and for the
    # opposite reason: that one compensates a rate and wants the safe
    # over-estimate, this one turns a note's length in rows into frames the
    # sweep may occupy and wants the safe under-estimate -- a pattern shared
    # between two subtunes at different tempos is short in the faster one.
    # See goatwriter._drum_duration_steps.
    short_row_calls = 0
    if tempo != "auto":
        resolved_tempo = tempo
        # A forced tempo still gets packed at the factor the file needs, so it
        # needs the same divisor every rate table is encoded against. See
        # _derived_multiplier.
        multiplier = _derived_multiplier(sid, det, skip_gate)
        if multiplier > 1:
            log(f"Call multiplier.........: -S{multiplier} (derived; the "
                f"forced tempo {tempo} is in play calls, not frames)")
    elif det.frames_per_row > 1:
        # gplay.c:494 decrements a value >= 3 and gplay.c:325 makes a row last
        # tempo+1 calls, so for values in this range the command value *is*
        # the number of player calls per row.
        resolved_tempo = det.frames_per_row
        # Same reasoning as the forced branch above. No corpus file reaches
        # this branch today (95 of 95 take the derived path), so it is fixed
        # for the shape rather than for a measured file -- a lesson recorded
        # in one branch is not a lesson in the file.
        multiplier = _derived_multiplier(sid, det, skip_gate)
        log(f"Row length..............: {det.frames_per_row} player calls "
            "(from the note-duration table's common factor)")
    else:
        # Derived per file, per subtune, from the player's own speed gate --
        # see goatwriter.find_song_speeds. Applied here rather than through
        # resolved_tempo because the values differ between subtunes.
        resolved_tempo = None
        groups = len(tracks) // 3
        # A GTS5 file can play a 2-call row (constants.CMD_FUNKTEMPO); the
        # placeholder is resolved by write_funktempo below.
        values, mult, note = derived_group_tempos(sid, det, groups,
                                                  skip_gate,
                                                  funk=fmt != FORMAT_GTS2)
        multiplier = mult
        # A tempo command at orderlist position 0 *is* that subtune's opening
        # tempo -- the player's init loads the counter from its own table and
        # the voice's first step overwrites it before a row is played. Both
        # writes would otherwise land on row 0 of the song, one from
        # apply_tempo on voice 0's pattern and one from the orderlist pass on
        # voice 2's, and which won would come down to the order gplay services
        # the channels in. Agreeing the two is not a tie-break, it is the
        # reading: Rasputin's subtune 0 opens `$FE 02`, which is 3 frames a
        # row against the table's 2.
        # Only where the numbering still lines up: `step_tempos` is parallel
        # to the tracks as `convert_tracks` emitted them, and a split has
        # inserted groups since.
        if step_tempos and groups == subtunes_before:
            for k in range(groups):
                for v in range(3):
                    if 3 * k + v >= len(step_tempos):
                        continue
                    opening = step_tempos[3 * k + v].get(0)
                    if opening is not None:
                        values[k] = opening
        if groups != subtunes_before:
            # A split subtune shifted the numbering, so per-subtune
            # attribution is unsafe; every group gets subtune 0's timebase.
            values = [values[0]] * groups
        # Per subtune in one call, because the values have to be compared with
        # each other: a pattern two subtunes play can carry only one tempo, and
        # writing them one at a time made the later subtune's value the earlier
        # one's clock. See patterns.apply_tempos.
        written = apply_tempos(new_patterns, tracks, values, log)
        group_tempos = list(values)
        if regrid:
            # The fractional part of a row the tempo cannot express. Only
            # where `effective_frames` DECLINED the exact row -- if it was
            # encodable, the tempo already carries it and compensating again
            # would double-count. See patterns.regrid_tempos.
            deficits = regrid_deficits(find_song_speeds(sid, det), values,
                                       skip_gate, multiplier)
            if any(deficits):
                regrid_tempos(new_patterns, tracks, values, deficits,
                              multiplier, log, full_debt=regrid_full_debt)
        row_calls = max(values) if values else 0
        short_row_calls = min(values) if values else 0
        log(f"Tempo...................: CMD_SETTEMPO "
            f"{sorted(set(values))} in {written} pattern(s) ({note})")
        if mult > 1:
            log(f"*** TUNE TICKS FASTER THAN ITS ROWS CAN PLAY AT 1x -- PACK "
                f"WITH gt2reloc -S{mult} OR IT PLAYS {mult}x TOO SLOW ***")
    if resolved_tempo is not None:
        if not GT_MIN_TEMPO <= resolved_tempo <= 0x7F:
            raise ValueError(
                f"tempo must be {GT_MIN_TEMPO}..127 (Goattracker reads 0 and 1 "
                f"as funktempo, gplay.c:325), got {resolved_tempo}")
        # CMD_SETTEMPO 2 plays 3 calls (gplay.c:494 decrements only values
        # >= 3, and tempo 2 reloads the tick to 2), so a forced 2 is a 3-call
        # row to everything that reads one. Only the derived path's
        # CMD_FUNKTEMPO placeholder is a real 2-call row (write_funktempo), and
        # row_calls == 2 compensates as one (patterns._scaled_step).
        calls = max(resolved_tempo, TEMPO_FASTEST_STEADY)
        row_calls = calls
        short_row_calls = calls
        apply_tempo(new_patterns, tracks, resolved_tempo, log)
        group_tempos = [calls] * (len(tracks) // 3)

    # The outer counter's reload, where the player has one. A call it skips is
    # a call our wavetable steps anyway, so a duration read out of that player
    # in *its* working calls occupies (O + 1) / O of ours -- see
    # goatwriter._gate_calls. **Not conditional on `--skip-gate`**, which is
    # about how long a *row* lasts: a wavetable entry lasts a play call, a play
    # call is a frame at -S1 whatever the tempo says, and the mechanism it
    # encodes lasts a number of the original's frames. The two stayed separate
    # when v0.5.267 gave Ninja -- the file that used to demonstrate the
    # difference -- a readable inner gate: the row correction and the table
    # correction are the same ratio applied to different quantities.
    gate_skip = outer_gate_skip(sid)

    # Last, so it sees every command any earlier stage emitted. It rewrites the
    # data column in place, so nothing downstream may read it as a value again.
    scaled = 0
    if fmt != FORMAT_GTS2:
        speed_table = build_speed_table(new_patterns, multiplier, slide_steps,
                                        row_calls)
        # Only the derived path writes the placeholder; a forced tempo of 2
        # keeps meaning what CMD_SETTEMPO 2 means (3 calls).
        if resolved_tempo is None:
            write_funktempo(new_patterns, speed_table, log)
        # Every stored step is the divided one, so at -S2 and above the count
        # of scaled slides is the count of entries.
        scaled = len(speed_table) if multiplier > 1 else 0
    else:
        speed_table = []
        if multiplier > 1:
            # A GTS2 file has no table: the pattern column is the parameter, so
            # the count is of columns rather than of distinct steps.
            scaled = scale_portamento_data(new_patterns, multiplier)
    if log and speed_table:
        log(f"Speed table entries.....: {len(speed_table)}")
    if log and multiplier > 1:
        log(f"Per-call rates..........: {scaled} slide step(s), the drum sweep "
            f"and the rise divided by {multiplier} for the -S{multiplier} call "
            f"rate (siddump cannot see this, siddump.c:309/325)")
    # Read after every stage that can move a note or an orderlist entry, and
    # from the finished pair, because it is a *safety* bound: the drum sweep's
    # depth is chosen from the lowest pitch each instrument actually plays, and
    # a bound taken before splitting/packing/transpose-folding would describe
    # patterns that are no longer the ones being written. See
    # goatwriter._drum_steps_safe.
    # ------------------------------------------------------------------
    # Pulse phase: open each note of a free-running sweep on the duty cycle
    # the player's accumulator holds at that moment, via CMD_SETPULSEPTR.
    # The walk and the clone discipline live in patterns.py, the simulator
    # and the table in goatwriter.py; the table is built HERE, before the
    # patterns are patched, because the commands name its entry indices.
    # Multispeed files were declined until the gate below was lifted. **THE
    # REASON WAS NO LONGER "UNMEASURED":
    # THE SWEEP STEPS PER FRAME, MEASURED AT v0.5.460, three ways that agree.**
    # This comment used to say the per-call/per-frame question "has not been
    # measured, and a wrong reading there would be silent". It is measured:
    #
    # * `PULSE_TRI_SHAPE` opens `AND #$1F / DEC counter,X / BPL skip` -- a
    #   per-voice countdown reloaded from the rate byte's low five bits,
    #   sitting in the play routine's body, so its unit is one ENTRY to that
    #   routine.
    # * Of the 11 corpus files carrying this engine above `-S1`, **10 declare
    #   VBI** and only Battle_of_Britain declares CIA -- so the routine is
    #   entered once per displayed frame, and the `-S` factor is a property of
    #   what `gt2reloc` packed on OUR side. Same rule as `_measure` tracing
    #   every original at `-m1`.
    # * Pulse-width change gaps in the ORIGINALS at `-m1` come from the same
    #   alphabet on the `-S2` files as on the `-S1` controls; were those
    #   originals entered twice a frame their gaps would be halved.
    #
    # So `_pulse_tri_program`'s division by `multiplier` is the correct
    # treatment rather than a guess, and the gate was NOT protecting against a
    # wrong rate unit.
    #
    # **RETRACTED (2026-10-03): "THE SWEEP STEPS PER FRAME, MEASURED AT
    # v0.5.460, three ways that agree"**, and with it "So
    # `_pulse_tri_program`'s division by `multiplier` is the correct
    # treatment rather than a guess". Only the ENTRY half above survives
    # (VBI: the routine is entered once a displayed frame). The triangle
    # engine's counter steps once per ORIGINAL TICK -- a play call that
    # passes the player's outer gate (`goatwriter.PulsePhaseSim`, walked on
    # that clock below) -- and the GT pulse speed is divided by our calls a
    # tick, `multiplier * (O+1) / O` under an outer gate
    # (`goatwriter._tri_speed`): Game_Killer's packed ramp 225 -> 198 a
    # frame against the original's 200. The intermediate "per CALL"
    # reading was itself a pairing slip. See docs/LESSONS.md's two
    # RETRACTED sections for "THE SWEEP STEPS PER FRAME" and the 2026-10-03
    # entry after them.
    #
    # **THE `multiplier == 1` GATE THAT USED TO SIT HERE IS LIFTED (after 24b9f1d).**
    # It was kept past that measurement for a different and measured reason,
    # written down in `tests/test_pulse_phase.py`: lifting it reaches three
    # VBI multispeed files, and **Rasputin's conversion then did not PACK** --
    # gt2reloc refused it with no table error and 126 patterns against a
    # limit of 208. The cause, found at 24b9f1d, is greloc.c's `packpattern()`
    # returning -1 past 256 packed bytes a pattern: CMD_SETPULSEPTR on 785
    # note rows, plus the vibrato commands `_vibrato_command_pass` adds
    # afterwards, took four of Rasputin's 127-row clones to 264-270. The
    # repair is `goatwriter.budget_pulse_phase_commands`, run in `build_sng`
    # on the FINISHED rows (a budget on the plan here measured nothing to
    # drop -- the vibrato pass is what crosses the line), and with it the
    # file packs. Of the other two, Game_Killer gains `pulse_phase` and
    # One_Man_and_his_Droid moves bytes and no number; `tests/test_pulse_phase.py`
    # and `tests/test_pattern_budget.py` pin the lifted gate, the budget and
    # Rasputin's pack.
    #
    # **AND THE GATE WAS NOT THE ONLY THING DECLINING THESE FILES**, which was
    # not previously known: with the condition lifted, only 3 of the 10 VBI
    # carriers are reached at all. The other 7 are Devils_Galop, both Last_V8s,
    # Master_of_Magic, Monty_on_the_Run, Phantoms_of_the_Asteroid and
    # Thing_on_a_Spring.
    #
    # **THIS COMMENT USED TO SAY THEY WERE DECLINED BY `group_tempos` OR BY
    # `pulse_phase_sims` RETURNING NOTHING. THAT IS WRONG ON BOTH HALVES, FOR
    # ALL SEVEN (measured v0.5.467).** Every one of them arrives here with a
    # non-empty `group_tempos` (1 to 4) AND a non-empty `sims` (2 to 8) -- and
    # several carry MORE sims than the three that succeed, which have 1, 2 and
    # 2. Neither of the first four conditions is what refuses them. They die
    # at the two AFTER, and the converter already logs which:
    #
    # * **`collect_pulse_phases` returns no plan (3 files)** -- Devils_Galop,
    #   Monty_on_the_Run, Thing_on_a_Spring. Cause, in its own words: *"a
    #   record sounds on two voices of subtune N; the accumulator is shared
    #   and the plan declines the subtune"* (Monty on subtunes 0 and 2,
    #   Thing_on_a_Spring on 0, Devils_Galop on 1). That is the player's one
    #   pulse accumulator per record, not a table limit -- a real refusal,
    #   and correct.
    # * **`build_pulse_phase_table` used to return no table for these 4
    #   files** -- both Last_V8s, Master_of_Magic, Phantoms_of_the_Asteroid.
    #   Cause: the pulse table OVERFLOWS. *"PULSE PHASE NEEDS 130 TABLE ROWS
    #   FOR INSTRUMENT 7"* (both Last_V8s), 112 rows for instrument 14
    #   (Master_of_Magic), 70 for instrument 17 (Phantoms) -- against
    #   `GT_MAX_TABLELEN`. This one was a CAPACITY limit rather than a
    #   musical refusal (see task
    #   pulse-phase-table-has-no-exhaustion-instrumentation): the function
    #   now falls a record whose phase set will not fit back to a static
    #   width, then to pointer 0, and only returns None where NOTHING
    #   survives -- so these four now ship a partial table (logged as
    #   dropped/silent counts) instead of losing the whole expansion,
    #   PROVIDED at least one sweeping record's phase plan still fits.
    #
    # So the two causes are unequal: a shared accumulator is the player and
    # stays a real refusal; a full table is our encoding and now degrades
    # gracefully instead of failing outright.
    #
    # **RETRACTED (the lockstep triangle walk): "That is the player's one
    # pulse accumulator per record, not a table limit -- a real refusal,
    # and correct" and "a shared accumulator is the player and stays a real
    # refusal".** The accumulator is shared, but the walk can follow it:
    # rows are synchronous across a group's voices, so
    # `patterns._walk_triangle_group` steps every voice's record tick by
    # tick in the player's order (X = 2, 1, 0) and a record two voices sweep
    # is stepped by both. No subtune or voice is declined for sharing any
    # more. Under forced `pulse_phase` the six files it declined move --
    # Chimera, Devils_Galop, Human_Race, Monty_on_the_Run, Ninja,
    # Thing_on_a_Spring -- and nothing else (tests/test_triangle_lockstep.py
    # has their widths against the originals); under shipped presets none
    # does, since none of the six ships the flag.
    #
    # 5_Title_Tunes, the measured case for the emission itself, is -S1.
    # ------------------------------------------------------------------
    # **THE GATE ADMITS BOTH SWEEPING ENGINES.** `det.pulse_tri_hi >= 0` is
    # the triangle engine, whose walk this comment block is about;
    # `det.pulse_bounds >= 0` is the per-record-bounds engine (Saboteur_II,
    # Food_Feud -- 42 preset files), whose accumulator is per voice and
    # RESEEDED at every note without bit 7 in its note byte, so its walk is
    # driven by `free_rows` (the bit, carried out of `convert_patterns`
    # above and extended to the later passes' pattern copies by
    # `inherit_free_rows`) and plans a command only on the notes that
    # free-run. See goatwriter.PulseBoundsSim for the reading and
    # patterns.collect_pulse_phases for the two engines' walk. `bounds_sims`
    # is empty where the option is off, the engine absent, or the player's
    # reseed test is not the spelling the rule was validated on
    # (`pulse_reseed_gated`), and then this arm is the triangle engine's
    # alone, exactly as before.
    pulse_plan = None
    if (pulse_phase and pulse and group_tempos
            and (det.pulse_tri_hi >= 0 or det.pulse_bounds >= 0)):
        lead = phase_lead
        sims = pulse_phase_sims(sid, det, lead) or bounds_sims
        # THE TWO ENGINES' CLOCKS. The bounds engine's sim runs on the
        # original's FRAME clock: our calls a row (the GT tempo), turned
        # into frames by the multiplier (Saboteur_II, -S3: $756 planned
        # where the original held $2B0 before it did). The triangle
        # engine's runs on the original's TICK: a play call that passes the
        # player's outer gate, `frames_for` of them a row -- read off the
        # disassembly at 1dde44a, see goatwriter.PulsePhaseSim. Our tempo,
        # the multiplier and the outer gate's skip all drop out of it:
        # One_Man_and_his_Droid is 2 calls a tick at -S2 (tempo 4),
        # Game_Killer 10 at -S9 (tempo 20, `$0826` skipping a frame in
        # ten), Rasputin 3 at -S2 (tempo 6, an `R` its `$FE nn` moves
        # mid-song). Its per-voice cells and preroll come from the image
        # (`triangle_start`), and a player whose start cannot be read is
        # not walked at all.
        #
        # RETRACTED (the comment this replaces, v0.5.488 to here): "The
        # triangle engine's stays on OUR CALLS -- and that is now a
        # MEASUREMENT ... the onsets place this engine's DEC/BPL counter
        # inside the multispeed core that entry runs `multiplier` times";
        # its 61% was an index slip, and the counter sits behind the outer
        # gate, not inside a multispeed core. Also RETRACTED: "Rasputin and
        # One_Man_and_his_Droid are at chance on BOTH clocks under the same
        # probe -- their originals open notes on buckets the free-running
        # sim never plans (One_Man: every note at $8xx), a model defect,
        # not a clock one." The clock was the first defect on both; the
        # $8xx notes are the ACCUMULATE engine (record 8, rate $07, bit
        # $08: `$1226 LDA $151A / AND #$08 / BEQ`), which the walk
        # correctly never plans. tests/test_pulse_phase.py pins the figures.
        walk_tempos, calls_per_frame, start = group_tempos, multiplier, None
        if sims and not bounds_sims:
            tri = triangle_start(sid, det, lead)
            speeds = find_song_speeds(sid, det)
            groups = len(tracks) // 3
            # Per header subtune while the numbering lines up; a split
            # shifts it, and every group then takes subtune 0's -- the
            # rule `derived_group_tempos`' caller applies above.
            subs = (range(groups) if groups == subtunes_before
                    else [0] * groups)
            frames = ([speeds.frames_for(s) for s in subs]
                      if speeds is not None else [None])
            if tri is None or None in frames:
                log("Pulse phase.............: the triangle player's start "
                    "state or row clock cannot be read; not walked")
                sims = {}
            else:
                walk_tempos, calls_per_frame = frames, 1
                start = [(tri.prefetch(f), tuple(
                    (tri.instruments[x],) + tri.cells[x] for x in range(3)))
                    for f in frames]
        if sims:
            snapshot = [list(t) for t in tracks]
            free_rows = (inherit_free_rows(new_patterns, track_index.free_rows, log)
                         if bounds_sims else None)
            event_rows = (inherit_event_rows(new_patterns,
                                             track_index.event_rows, log)
                          if start is not None else None)
            plan = collect_pulse_phases(
                new_patterns, tracks, walk_tempos, sims, log,
                free_rows=free_rows, calls_per_frame=calls_per_frame,
                tri_start=start, event_rows=event_rows)
            table = None
            if plan:
                phases, writes = plan
                # A compilation's further players are appended after this
                # table (`_append_players`, the same gate), so it is laid
                # out as short as the same widths allow.
                table = build_pulse_phase_table(
                    sid, det, _instruments_used(det, None, lead), pulse,
                    multiplier, phases, log, lead,
                    prefer_short=(not isinstance(sid, PlayerView)
                                  and len(det.players) >= 2))
            if plan and table:
                entries, starts, index = table
                apply_pulse_phase(new_patterns, tracks, writes, index, log)
                pulse_plan = (entries, starts)
            else:
                # Nothing shipped: the expansion collect may have made is
                # playback-neutral but not byte-neutral, and a declined plan
                # must leave the output exactly as it was.
                tracks[:] = snapshot

    # The `prune` option's own promise, kept past the passes that break it:
    # `convert_patterns` pruned against the RAW orderlists, and every pass
    # since that repoints a position at a copy (tempo, fraction and tie
    # copies, pulse phase) can leave its source unplayed. Last before the
    # writer, after the last pass that rewrites an orderlist; it REBINDS
    # rather than edits (see `drop_unplayed_patterns`).
    if prune:
        tracks, new_patterns, dropped = drop_unplayed_patterns(
            tracks, new_patterns)
        if dropped:
            log(f"Pruned {len(dropped)} more pattern(s) the later passes' "
                "copies left unplayed")
    sng = build_sng(sid, det, tracks, new_patterns, log=log, fmt=fmt,
                     speed_table=speed_table, effects=effects,
                     pulse=pulse, multiplier=multiplier,
                     sustain_exact=sustain_exact,
                     no_hard_restart=no_hard_restart,
                     wide_hard_restart=wide_hard_restart,
                     max_hard_restart=max_hard_restart,
                     hard_restart_frames=hard_restart_frames,
                     no_test_restart=no_test_restart,
                     two_stage=two_stage,
                     voice_two_stage=voice_two_stage,
                     wave_alternate=wave_alternate,
                     instr_voices=instrument_voices(tracks, new_patterns),
                     # Per instrument where the orderlists allow it: the
                     # file-wide `short_row_calls` below caps EVERY instrument
                     # at the fastest subtune's row, including the ones that
                     # never sound in it. Returns {} wherever the attribution
                     # is unsafe, and then the file-wide bound stands.
                     instr_row_calls=instrument_row_calls(
                         tracks, new_patterns, group_tempos or []),
                     gate_skip=gate_skip,
                     sfx_drum=sfx_drum,
                     wave_program=wave_program,
                     vibrato_command=vibrato_command,
                     cut_release=cut_release,
                     pitch_seq=pitch_seq,
                     filters=filters, vibrato=vibrato,
                     min_notes=min_played_notes(tracks, new_patterns),
                     note_rows=median_played_durations(tracks, new_patterns),
                     row_calls=short_row_calls,
                     compact_instruments=compact_instruments,
                     real_firstwave_instruments=real_firstwave_instruments,
                     gate_off_firstwave_instruments=gate_off_firstwave_instruments,
                     arps=ilv_arps,
                     pulse_plan=pulse_plan,
                     ilv_filter_routing=ilv_filter_routing,
                     tie_restart=tie_restart)
    # A relative wave step past Goattracker's 96 notes reads gt2reloc's
    # orderlist addresses in the packed file, so its pitch moved with the
    # layout. Pinned to what the original reads there. Not an option: it is
    # what the player does. Before the appended players, whose steps belong
    # to another table (past_table_wave).
    sng = pin_past_table_wave_notes(sng, sid, det, log)
    sng = _append_players(sng, sid, det, multiplier, opts, log)
    if drop_unnamed_instruments:
        # Last, on the finished bytes: every pass that writes or renumbers
        # an instrument column (the clone passes included) has run.
        sng = drop_unnamed_instruments_from(sng, log)
    # The packed song's call phase (goatwriter.call_phase): part of what
    # `skip_gate` means, because it is the phase of the grid that option
    # corrects the rows to. After the drop above, which would remove the
    # record -- no pattern names it. Only where every note's onset is the
    # call after its tick 0 (`call_phase.ONSET_CALL`): a firstwave that
    # writes a waveform (`no_test_restart`, `real_firstwave_instruments`)
    # puts some onsets on tick 0 itself, and no one phase serves both. Not
    # where an orderlist `$FE nn` changes the tempo mid-song: the grid moves.
    startup = (startup_phase(sid, det, multiplier, group_tempos)
               if (skip_gate and group_tempos and not step_tempos
                   and not no_test_restart and not real_firstwave_instruments)
               else None)
    if startup is not None:
        before = len(sng)
        sng = add_startup_tempo(sng, startup.tempo, log)
        if len(sng) != before:
            log(f"Startup call phase......: instrument 63 AD ${startup.tempo:02X} "
                f"-- a {startup.tempo}-call startup row where gt2reloc's "
                f"default is {startup.default}; onsets off the original's "
                f"frame on {startup.default_mismatched} of {startup.rows} "
                f"rows -> {startup.mismatched}")
    return sng


def _append_players(sng: bytes, sid: SidFile, det: Detection, multiplier: int,
                    opts: dict, log: Logger) -> bytes:
    """`sng` with players 1..N-1 of a compilation appended as subtunes.

    Every gate below is a refusal to guess, and a refusal keeps what came
    before it -- the subtunes appended so far -- because subtune n of the
    result must be the original's subtune n, and skipping a player would
    renumber every one after it:

    * the dispatch names two or more players (`det.players`) and the first is
      the one `detect()` already read, so `sng`'s subtunes ARE player 0's;
    * `sng` carries exactly player 0's subtunes, numbered 0..B-1;
    * player k owns the next subtune number and is entered with A = 0, so a
      one-subtune view reads the orderlist the original plays
      (`detect.player_view`);
    * the view re-detects to player k's own tables (`find_players`' reading);
    * the appended song fits Goattracker's caps (`goatwriter.append_song`).

    Each view converts with this call's options at this file's pack factor,
    except the two that name things in the FIRST player: the per-instrument
    firstwave lists number player 0's instruments, and the unnamed-instrument
    drop runs once, on the finished file, after this.

    **The pulse table is the cap that binds.** 5_Title_Tunes' subtune 0
    spent 214 of its 255 pulse rows on `pulse_phase` in the per-phase
    layout, so players 1-4 appended only without sweeps. On a compilation
    `convert` therefore lays subtune 0's phase table with SHARED RAMPS
    (`build_pulse_phase_table(prefer_short=True)`): 167 rows, the same
    register writes (siddump, 180 s), and players 1-4 then append WITH their
    sweeps, without `pulse_phase` (pulse 248 of 255; measured at 81da71d).
    Their own phase tables still do not fit (player 2's takes 177 rows,
    player 3's 236). The appended players are tried at up to three levels
    -- the file's options, then without `pulse_phase`, then without `pulse`
    (each record's starting width, held) -- and the first level at which
    every player fits is kept; where none does, the one that appends the
    most. Subtune 0 is never degraded: it is the tune the file starts on,
    and nothing appended after it moves its bytes.
    """
    players = det.players
    if isinstance(sid, PlayerView) or len(players) < 2:
        return sng
    first = players[0]
    if first.instr_addr < 0 or first.pattern_lo_addr < 0 \
            or sid.to_offset(first.instr_addr) != det.instr_start \
            or sid.to_offset(first.pattern_lo_addr) != det.pattern_lo:
        log(f"Players.................: {len(players)}, but subtune 0 was not "
            "read from the first; nothing appended")
        return sng
    have = sng[HEADER_LEN]
    if first.subtunes != tuple(range(have)):
        log(f"Players.................: player 0 owns subtunes "
            f"{list(first.subtunes)} and the conversion carries {have}; "
            "nothing appended")
        return sng
    base_opts = dict(opts, real_firstwave_instruments=(),
                     gate_off_firstwave_instruments=(),
                     drop_unnamed_instruments=False, engine=0)
    levels = [("the file's options", base_opts)]
    for flag, what in (("pulse_phase", "without pulse_phase"),
                       ("pulse", "without pulse sweeps")):
        if levels[-1][1].get(flag):
            levels.append((what, dict(levels[-1][1], **{flag: False})))
    views = {}
    best = None
    for what, level_opts in levels:
        lines: List[str] = []
        out, appended = _append_level(sng, sid, players, have, multiplier,
                                      level_opts, views, lines.append)
        if best is None or appended > best[1]:
            best = (out, appended, what, lines)
        if appended == len(players) - 1:
            break
    out, appended, what, lines = best
    for line in lines:
        log(line)
    log(f"Players.................: {appended} of {len(players) - 1} further "
        f"player(s) appended as subtunes {have}..{have + appended - 1} "
        f"({what})" if appended else
        f"Players.................: none of {len(players) - 1} further "
        "player(s) appended")
    return out


def _append_level(sng: bytes, sid: SidFile, players, have: int,
                  multiplier: int, view_opts: dict, views: dict,
                  log: Logger):
    """(song, players appended) for one set of the appended players' options."""
    out = sng
    for k in range(1, len(players)):
        p = players[k]
        stop = None
        if k not in views:
            view = None
            if p.subtunes != (have + k - 1,):
                why = f"owns subtunes {list(p.subtunes)}, not [{have + k - 1}]"
            else:
                view = player_view(sid, players, k, multiplier)
                why = None if view is not None else \
                    "is not entered as `LDA #0 / JSR` with one subtune"
            if view is not None:
                _vs, vdet = _detect_tables(view, lambda _m: None)
                if (p.instr_addr < 0 or p.pattern_lo_addr < 0
                        or vdet.instr_start != view.to_offset(p.instr_addr)
                        or vdet.pattern_lo != view.to_offset(p.pattern_lo_addr)):
                    why = "re-detects to tables other than its own"
            views[k] = (view, why)
        view, stop = views[k]
        if stop is None:
            try:
                extra = convert(view, log=lambda m, k=k: log(f"[player {k}] {m}"),
                                **view_opts)
            except (UnsupportedSidError, ConversionAbort, ValueError) as exc:
                stop = f"does not convert ({exc})"
        if stop is None:
            merged = append_song(out, extra, tag=f"{k}/", log=log)
            if merged is None:
                stop = "does not fit beside the players before it"
            else:
                out = merged
        if stop is not None:
            log(f"*** PLAYER {k} {stop}; subtune {have + k - 1} onward NOT "
                "CONVERTED ***")
            return out, k - 1
    return out, len(players) - 1
