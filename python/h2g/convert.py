"""End-to-end .sid -> .sng conversion (port of loadfile()'s FindEnd block)."""
from __future__ import annotations

from typing import Callable, List

from .detect import Detection, detect
from .goatwriter import DEFAULT_FORMAT, FORMATS, build_sng
from .patterns import (GT_DEFAULT_ROWS, ConversionAbort, convert_patterns,
                       reindex_tracks)
from .sidfile import SidFile, load_sid
from .tracks import convert_tracks

Logger = Callable[[str], None]


class UnsupportedSidError(Exception):
    pass


def convert(sid_path: str, log: Logger = print,
            max_rows: int = GT_DEFAULT_ROWS,
            terminate_patterns: bool = False,
            fmt: str = DEFAULT_FORMAT) -> bytes:
    """Convert a .sid to .sng bytes.

    max_rows is the pattern-slicing length. It defaults to 94 (what the
    original VB6 tool used, and what the byte-exact Commando fixture encodes);
    128 is Goattracker's real MAX_PATTROWS since v2.32 and produces fewer,
    longer patterns -- which shortens orderlists and converts some tunes that
    otherwise exceed Goattracker's limits.

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
    new_patterns, track_index = convert_patterns(
        sid, det, log, max_rows, terminate_patterns)
    tracks = reindex_tracks(tracks, track_index)

    return build_sng(sid, det, tracks, new_patterns, log=log, fmt=fmt)
