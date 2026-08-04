"""Track-list conversion (port of GoatConvertTracks, h2g.frm:1100-1231).

Each Goattracker track is represented as a plain list[int] of the track's
data bytes (excluding the leading Goattracker track-length byte, which
GoatSave derives as len(track) - 1).
"""
from __future__ import annotations

from typing import List

from .detect import Detection
from .sidfile import HLEN, SidFile

DEFAULT_TRACK = [0x00, 0xFF, 0x00]


def _build_track(data: bytes, addr: int, version: int) -> List[int]:
    track: List[int] = []
    i2 = 0
    while True:
        count = len(track) + 1
        b1 = data[addr + i2]
        if count >= 254:
            b1 = 0xFF
        i2 += 1

        if version == 4:  # ACE 2
            if b1 >= 0x80:
                track += [0xFF, 0x00]
                break

        elif version in (5, 6, 7, 8):  # Mega Apocalypse
            if 0x80 <= b1 <= 0x8F:
                track.append((b1 - 0x80) + 0xF0)  # transpose +
            if 0xEF <= b1 <= 0xFE:
                track.append(0xF0 - (b1 ^ 0xFF))  # transpose -
            if b1 == 0xFF:
                track += [0xFF, 0x00]
                break
            if b1 <= 0x7F:
                track.append(b1)

        elif version in (0, 1, 2, 3):  # Warhawk / IK+ / etc
            if b1 == 0xFE:
                track += [0xFF, 0xFD]  # illegal repeat position -> stop
                break
            if b1 == 0xFF:
                track += [0xFF, 0x00]
                break
            if b1 <= 0xFD:
                track.append(b1)

        else:
            raise ValueError(
                f"unsupported/undetected Hubbard player track-read version: ${version:X}"
            )
    return track


def convert_tracks(sid: SidFile, det: Detection, log) -> List[List[int]]:
    data = sid.data
    tracks: List[List[int]] = []

    for i in range(sid.subtunes):
        for voice in range(3):
            if voice >= det.track_voices:
                tracks.append(list(DEFAULT_TRACK))
                continue

            so = voice + i * (det.track_voices * 2)
            addr = data[det.track_hi + so] * 256 + data[det.track_lo + so]
            addr = addr - sid.load_addr + HLEN - 1
            if addr <= 1 or addr >= len(data):
                log(f"*** SUBTUNE ${i:X} (VOICE {voice:X}) ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
                tracks.append(list(DEFAULT_TRACK))
                continue

            tracks.append(_build_track(data, addr, det.read_track_version))

    return tracks
