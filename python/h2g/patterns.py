"""Pattern conversion (port of GoatConvertPattern, h2g.frm:818-1097).

Two passes, matching the original:
 1. Decode each Hubbard pattern into a flat Goattracker-style event stream
    (4 bytes per row: note, instrument, command, command-value).
 2. Slice event streams longer than Goattracker's 94-row (376-byte) pattern
    limit into multiple patterns, and re-index every track's pattern-number
    references accordingly.

See `_slice_pattern` docstring for how the VB original's slicing loop
(which iterates one index past the real data, relying on implicit
zero-initialized arrays) was proven equivalent to plain chunking.
"""
from __future__ import annotations

from typing import List, Optional

from .detect import Detection
from .sidfile import HLEN, SidFile

GT_MAX_PATTERN_LEN = 94 * 4  # 376: Goattracker's max pattern length in bytes
GT_NO_NOTE = 0xBD
MAX_PATTERNS = 0xD0
MAX_TRACK_LEN = 0xFF

ERROR_PATTERN = [0xBD, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]


class ConversionAbort(Exception):
    pass


def _build_raw_pattern(data: bytes, addr: int) -> Optional[List[int]]:
    """Flat event stream for one Hubbard pattern, or None if out of range."""
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    g_instrument = 0
    g_old_instr1 = -1
    g_old_instr2 = -2
    i2 = 0

    while True:
        if addr + i2 <= 1 or addr + i2 >= len(data):
            return None

        g_note = GT_NO_NOTE
        cmd1 = 0
        cmd2 = 0
        b1 = data[addr + i2]

        if b1 == 0xFF:
            events += [0xFF, 0x00, 0x00, 0x00]
            break

        get_next = b1 & 0x80
        no_note = b1 & 0x40
        no_adsr = b1 & 0x20
        wait = b1 & 0x1F

        if get_next:
            i2 += 1
            b2 = data[addr + i2]
            if no_adsr:
                if g_old_instr1 == g_old_instr2:
                    cmd1 = 3   # Portamento (no new ADSR)
                    cmd2 = 0x00
                g_old_instr2 = g_old_instr1
            if b2 & 0x80:
                if (b2 & 1) == 0:
                    cmd1, g_instrument = 1, 0  # pitch down
                else:
                    cmd1, g_instrument = 2, 0  # pitch up
                cmd2 = (b2 & 0x7F) // 4
            else:
                g_instrument = (b2 & 0x7F) + 2
                g_old_instr2 = g_old_instr1
                g_old_instr1 = g_instrument

        if get_next or not no_note:
            i2 += 1
            g_note = data[addr + i2]
            if g_note >= 0x5C:
                g_note = 0x5C
            g_note += 0x60

        resc_instr = -1
        if g_note == GT_NO_NOTE and g_instrument != 0:
            g_note = 0x60
            resc_instr = g_instrument
            g_instrument = 1

        if wait >= 1:
            events += [g_note, g_instrument, cmd1, cmd2]
            if cmd1 == 3:
                cmd1 = 0
            for _ in range(wait):
                events += [GT_NO_NOTE, 0x00, cmd1, cmd2]

        if resc_instr != -1:
            g_instrument = resc_instr

        i2 += 1

    return events


def _slice_pattern(events: List[int]) -> List[List[int]]:
    """Chunk a flat event stream into <=GT_MAX_PATTERN_LEN pieces.

    A trailing (possibly empty) slice is always emitted, matching the VB
    original: when len(events) is an exact multiple of GT_MAX_PATTERN_LEN,
    an extra zero-length pattern is produced and referenced by the track.
    """
    slices = []
    pos = 0
    n = len(events)
    while n - pos >= GT_MAX_PATTERN_LEN:
        slices.append(events[pos:pos + GT_MAX_PATTERN_LEN])
        pos += GT_MAX_PATTERN_LEN
    slices.append(events[pos:n])
    return slices


def convert_patterns(sid: SidFile, det: Detection, log):
    data = sid.data

    raw_patterns: List[List[int]] = []
    for i in range(det.pattern_used + 1):
        addr = data[det.pattern_hi + i] * 256 + data[det.pattern_lo + i]
        addr = addr - sid.load_addr + HLEN - 1
        events = _build_raw_pattern(data, addr)
        if events is None:
            log(f"*** PATTERN ${i:X} ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            events = list(ERROR_PATTERN)
        raw_patterns.append(events)

    new_patterns: List[List[int]] = []
    track_index: List[List[int]] = []

    for i, events in enumerate(raw_patterns):
        start = len(new_patterns)
        slices = _slice_pattern(events)
        for k, s in enumerate(slices):
            new_patterns.append(s)
            if k < len(slices) - 1:
                log(f"Extending Pattern: ${i:X} (${len(new_patterns):X})")
            if len(new_patterns) >= MAX_PATTERNS:
                raise ConversionAbort("TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER")
        track_index.append(list(range(start, len(new_patterns))))

    return new_patterns, track_index


def reindex_tracks(tracks: List[List[int]], track_index: List[List[int]]) -> List[List[int]]:
    new_tracks: List[List[int]] = []
    for track in tracks:
        new_track: List[int] = []
        end_marker = False
        for b in track:
            if b >= 0xD0 or end_marker:
                end_marker = True
                new_track.append(b)
            else:
                new_track.extend(track_index[b] if b < len(track_index) else [])
            if len(new_track) >= MAX_TRACK_LEN:
                raise ConversionAbort("TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER")
        new_tracks.append(new_track)
    return new_tracks
