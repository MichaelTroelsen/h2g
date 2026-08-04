"""End-to-end .sid -> .sng conversion (port of loadfile()'s FindEnd block)."""
from __future__ import annotations

from typing import Callable, List

from .detect import Detection, detect
from .goatwriter import build_sng
from .patterns import ConversionAbort, convert_patterns, reindex_tracks
from .sidfile import SidFile, load_sid
from .tracks import convert_tracks

Logger = Callable[[str], None]


class UnsupportedSidError(Exception):
    pass


def convert(sid_path: str, log: Logger = print) -> bytes:
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
    new_patterns, track_index = convert_patterns(sid, det, log)
    tracks = reindex_tracks(tracks, track_index)

    return build_sng(sid, det, tracks, new_patterns)
