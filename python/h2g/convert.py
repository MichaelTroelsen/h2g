"""End-to-end .sid -> .sng conversion (port of loadfile()'s FindEnd block)."""
from __future__ import annotations

from typing import Callable, List

from .detect import Detection, detect
from .goatwriter import (DEFAULT_FORMAT, FORMAT_GTS2, FORMATS, GT_MIN_TEMPO,
                         build_sng, derived_group_tempos)
from .patterns import (DEFAULT_TRACK, GT_COMMAND_FLOOR, GT_DEFAULT_ROWS,
                       ConversionAbort, build_speed_table, command_floor,
                       convert_patterns, apply_tempo, cmdtable_frames_per_row,
                       pattern_references, phantom_patterns,
                       referenced_patterns, reindex_tracks)
from .sidfile import SidFile, load_sid
from .tracks import (apply_initial_instruments, convert_tracks,
                     ensure_playable_orderlists, fold_transposes,
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


def _detect_tables(sid: SidFile, log: Logger):
    """(image, detection), re-reading the file with init's writes if needed.

    The re-read is a strict fallback: a file whose operands already name real
    tables is returned untouched, so applying init writes can rescue a file
    that reads nothing but can never disturb one that reads correctly. Only
    the winning attempt's log lines are emitted, so the output shows one
    SEARCHING block either way.
    """
    lines: List[str] = []
    det = detect(sid, lines.append)
    if not _tables_readable(det):
        staged = sid.with_init_writes()
        if staged is not None:
            staged_lines: List[str] = []
            staged_det = detect(staged, staged_lines.append)
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


def convert(sid_path: str, log: Logger = print,
            max_rows: int = GT_DEFAULT_ROWS,
            terminate_patterns: bool = False,
            fmt: str = DEFAULT_FORMAT,
            dedup: bool = False,
            prune: bool = False,
            pack: bool = False,
            legal_restart: bool = False,
            slides: bool = False,
            effects: bool = False,
            status_bit6: bool = False,
            reject_phantoms: bool = False,
            fold_transpose: bool = False,
            initial_instrument: bool = False,
            sustain_exact: bool = False,
            no_hard_restart: bool = False,
            filters: bool = False,
            pulse: bool = False,
            tempo: int | str | None = None) -> bytes:
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

    reject_phantoms validates the inferred pattern table against the
    player's own layout (patterns.phantom_patterns): an entry whose decode
    runs off the file, or whose bytes overlap the pointer tables or
    signature-matched player code, is replaced by the ERROR_PATTERN
    placeholder instead of being decoded as music. The `hi - lo - 1` entry
    count over-counts, and a phantom entry is what made the bit-6 fix
    net-negative on Last V8. Off by default: it changes the bytes of the
    files it reaches.

    fold_transpose recovers the orderlist transposes Goattracker's +14
    ceiling used to clamp away, by keeping `T mod 12` in the orderlist and
    folding the whole octaves into a copy of each pattern the step plays.
    17 corpus files carry such a transpose and five of them are audibly
    detuned by it -- up to 34 semitones. Costs one pattern-table entry per
    distinct (pattern, octaves) pair; steps whose notes have no room to rise
    are left clamped. Off by default: it changes the bytes of the files it
    reaches. See tracks.fold_transposes.
    """
    sid = load_sid(sid_path)
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
    sid, det = _detect_tables(sid, log)

    log("--------------------------------------------------------STATUS---")
    if not det.can_convert:
        raise UnsupportedSidError("NO HUBBARD PLAYER DETECTED, CAN'T CONVERT")

    log("*** HUBBARD PLAYER DETECTED, CONVERTING ***")
    log("----------------------------------------------------CONVERTING---")

    raw_transposes: List[dict] | None = [] if fold_transpose else None
    tracks = convert_tracks(sid, det, log, raw_transposes)
    # These three all read orderlists that are still in Hubbard numbering, so
    # they need the dialect's command boundary rather than Goattracker's.
    floor = command_floor(det.read_track_version)
    check_detection_sound(tracks, det.pattern_used, log, floor)
    # After the soundness check, which counts a reference above pattern_used as
    # dangling -- and every variant this adds is one, by construction. Before
    # `played`, so the variants are what pruning keeps rather than what it
    # drops.
    variants = (fold_transposes(sid, det, tracks, raw_transposes, log,
                                slides, status_bit6)
                if fold_transpose else [])
    played = referenced_patterns(tracks, floor)
    # Decided before the patterns are built, because it sets how many rows
    # each event becomes -- and it is only ever anything but 1 for the
    # command-table dialect, so no other file's output can move.
    det.frames_per_row = cmdtable_frames_per_row(sid, det, played)
    new_patterns, track_index = convert_patterns(
        sid, det, log, max_rows, terminate_patterns, dedup,
        used=played if prune else None,
        slides=slides, status_bit6=status_bit6,
        phantoms=(phantom_patterns(sid, det, slides, status_bit6)
                  if reject_phantoms else None),
        variants=variants)
    # Captured before reindexing: groups equal header subtune numbers until a
    # split inserts extra ones, and the tempo derivation is per subtune.
    subtunes_before = len(tracks) // 3
    tracks = reindex_tracks(tracks, track_index, pack, floor, log,
                            patterns=new_patterns, max_rows=max_rows)
    # Unconditional, and before the restart pass: a voice whose orderlist
    # holds nothing but an end marker makes greloc.c skip its whole subtune,
    # and every subtune past the resulting count is never written to the
    # packed .sid at all. That is silent data loss, not a stylistic choice,
    # so it is not gated behind an option.
    ensure_playable_orderlists(tracks, log)
    # After reindexing, so the orderlist bytes and `new_patterns` indices are
    # both Goattracker's; before the restart pass, which reads orderlist
    # lengths this may not change but must not race.
    if initial_instrument:
        apply_initial_instruments(tracks, new_patterns, det, log)
    if legal_restart:
        # After reindexing, packing, merging and splitting: those all change an
        # orderlist's length, and whether a restart position is in range is a
        # question about the finished list.
        legalise_restarts(tracks, log)
    # Every subtune dropped means the file carries no orderlist at all -- the
    # same refusal the empty-tracks case gets, for the same reason.
    if all(t == DEFAULT_TRACK for t in tracks):
        raise UnsupportedSidError(
            "EVERY SUBTUNE'S ORDERLIST EXCEEDS GOATTRACKER'S LIMIT, CAN'T CONVERT")

    # The gt2reloc -S factor this tune needs, where it is derivable. The pulse
    # table is stepped per play call, so a sweep written for one call a frame
    # runs at twice its rate under -S2; only the auto path knows the factor.
    multiplier = 1
    if tempo != "auto":
        resolved_tempo = tempo
    elif det.frames_per_row > 1:
        # gplay.c:494 decrements a value >= 3 and gplay.c:325 makes a row last
        # tempo+1 calls, so for values in this range the command value *is*
        # the number of player calls per row.
        resolved_tempo = det.frames_per_row
        log(f"Row length..............: {det.frames_per_row} player calls "
            "(from the note-duration table's common factor)")
    else:
        # Derived per file, per subtune, from the player's own speed gate --
        # see goatwriter.find_song_speeds. Applied here rather than through
        # resolved_tempo because the values differ between subtunes.
        resolved_tempo = None
        groups = len(tracks) // 3
        values, mult, note = derived_group_tempos(sid, det, groups)
        multiplier = mult
        if groups != subtunes_before:
            # A split subtune shifted the numbering, so per-subtune
            # attribution is unsafe; every group gets subtune 0's timebase.
            values = [values[0]] * groups
        written = sum(apply_tempo(new_patterns, tracks[3 * k:3 * k + 3],
                                  values[k]) for k in range(groups))
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
        apply_tempo(new_patterns, tracks, resolved_tempo, log)

    # Last, so it sees every command any earlier stage emitted. It rewrites the
    # data column in place, so nothing downstream may read it as a value again.
    speed_table = build_speed_table(new_patterns) if fmt != FORMAT_GTS2 else []
    if log and speed_table:
        log(f"Speed table entries.....: {len(speed_table)}")
    return build_sng(sid, det, tracks, new_patterns, log=log, fmt=fmt,
                     speed_table=speed_table, effects=effects,
                     pulse=pulse, multiplier=multiplier,
                     sustain_exact=sustain_exact,
                     no_hard_restart=no_hard_restart,
                     filters=filters)
