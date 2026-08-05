"""End-to-end .sid -> .sng conversion (port of loadfile()'s FindEnd block)."""
from __future__ import annotations

from typing import Callable, List

from .detect import Detection, detect
from .goatwriter import (DEFAULT_FORMAT, FORMATS, GT_MIN_TEMPO, build_sng,
                         tempo_command_value)
from .patterns import (DEFAULT_TRACK, GT_COMMAND_FLOOR, GT_DEFAULT_ROWS,
                       ConversionAbort, command_floor, convert_patterns,
                       apply_tempo, pattern_references, referenced_patterns,
                       reindex_tracks)
from .sidfile import SidFile, load_sid
from .tracks import convert_tracks

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

    terminate_patterns appends an explicit ENDPATT row to every pattern
    slice that lacks one, matching what Goattracker's own saver writes.
    Off by default: it changes the bytes, and the Commando fixture encodes
    the original tool's unterminated output.
    """
    sid = load_sid(sid_path)
    log("------------------------------------------------------SID INFO---")
    log(f"SID Name....: '{sid.name}'")
    log(f"SID Author..: '{sid.author}'")
    log(f"SID Released: '{sid.released}'")
    log(f"SID Loadaddr: ${sid.load_addr:X}")
    log(f"SID Subtunes: ${sid.subtunes:X}")

    log("-----------------------------------------------------SEARCHING---")
    det = detect(sid, log)

    log("--------------------------------------------------------STATUS---")
    if not det.can_convert:
        raise UnsupportedSidError("NO HUBBARD PLAYER DETECTED, CAN'T CONVERT")

    log("*** HUBBARD PLAYER DETECTED, CONVERTING ***")
    log("----------------------------------------------------CONVERTING---")

    tracks = convert_tracks(sid, det, log)
    # These three all read orderlists that are still in Hubbard numbering, so
    # they need the dialect's command boundary rather than Goattracker's.
    floor = command_floor(det.read_track_version)
    check_detection_sound(tracks, det.pattern_used, log, floor)
    new_patterns, track_index = convert_patterns(
        sid, det, log, max_rows, terminate_patterns, dedup,
        used=referenced_patterns(tracks, floor) if prune else None)
    tracks = reindex_tracks(tracks, track_index, pack, floor, log,
                            patterns=new_patterns, max_rows=max_rows)
    # Every subtune dropped means the file carries no orderlist at all -- the
    # same refusal the empty-tracks case gets, for the same reason.
    if all(t == DEFAULT_TRACK for t in tracks):
        raise UnsupportedSidError(
            "EVERY SUBTUNE'S ORDERLIST EXCEEDS GOATTRACKER'S LIMIT, CAN'T CONVERT")

    resolved_tempo = tempo_command_value(sid) if tempo == "auto" else tempo
    if resolved_tempo is not None:
        if not GT_MIN_TEMPO <= resolved_tempo <= 0x7F:
            raise ValueError(
                f"tempo must be {GT_MIN_TEMPO}..127 (Goattracker reads 0 and 1 "
                f"as funktempo, gplay.c:325), got {resolved_tempo}")
        apply_tempo(new_patterns, tracks, resolved_tempo, log)
    return build_sng(sid, det, tracks, new_patterns, log=log, fmt=fmt)
