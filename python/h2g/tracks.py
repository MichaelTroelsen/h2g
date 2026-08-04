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


def _build_track(data: bytes, addr: int, version: int, log=None) -> List[int]:
    track: List[int] = []
    i2 = 0
    while True:
        # The track byte stream is only terminated by a marker byte, so a bad
        # start address (or a stream with no terminator before EOF) walks off
        # the end. `_build_raw_pattern` guards this; this function did not, and
        # crashed with IndexError. Terminate the track cleanly instead -- the VB
        # original read past its fixed-size array here and died with a runtime
        # error, so there is no original behavior worth reproducing.
        if addr + i2 < 0 or addr + i2 >= len(data):
            if log:
                log("*** TRACK DATA RUNS PAST END OF FILE, TRUNCATED ***")
            track += [0xFF, 0x00]
            break

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


def _voice_addr(sid: SidFile, det: Detection, i: int, voice: int):
    """File offset of one subtune/voice orderlist, or None if unusable.

    Returns None both when the *table index* falls outside the file (the track
    table itself is unbounded -- nothing records its length) and when the
    16-bit address it holds resolves outside the file.
    """
    data = sid.data
    so = voice + i * (det.track_voices * 2)
    lo_i, hi_i = det.track_lo + so, det.track_hi + so
    if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
        return None
    addr = data[hi_i] * 256 + data[lo_i] - sid.load_addr + HLEN - 1
    if addr <= 1 or addr >= len(data):
        return None
    return addr


def convert_tracks(sid: SidFile, det: Detection, log) -> List[List[int]]:
    data = sid.data
    tracks: List[List[int]] = []

    # The track table has no length field, and the PSID header's song count is
    # frequently larger than the table really is (Knucklebusters claims 11
    # subtunes but has room for 3). Reading past the end yields garbage pointers
    # -- offsets that are negative or far beyond EOF -- which used to be emitted
    # as empty placeholder tracks, padding the .sng with phantom subtunes.
    #
    # Only the *trailing* run of unusable subtunes is dropped. Trimming at the
    # first unusable one is tempting but wrong: across the corpus the valid/
    # invalid map is interleaved (Commando is "...XXXXXXX........X"), so valid
    # subtunes routinely follow a gap and stopping early would discard real
    # music. Interior gaps keep their placeholder tracks, exactly as before.
    n_voices = min(3, det.track_voices)
    valid = [all(_voice_addr(sid, det, i, v) is not None for v in range(n_voices))
             for i in range(sid.subtunes)]
    keep = max((i + 1 for i, ok in enumerate(valid) if ok), default=0)
    if keep < sid.subtunes:
        log(f"Header claims ${sid.subtunes:X} subtune(s); last usable is "
            f"${keep - 1:X}, dropping {sid.subtunes - keep} phantom")

    for i in range(keep):
        for voice in range(3):
            if voice >= det.track_voices:
                tracks.append(list(DEFAULT_TRACK))
                continue
            addr = _voice_addr(sid, det, i, voice)
            if addr is None:
                log(f"*** SUBTUNE ${i:X} (VOICE {voice:X}) ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
                tracks.append(list(DEFAULT_TRACK))
                continue
            tracks.append(_build_track(data, addr, det.read_track_version, log))

    if not tracks:
        # Keep the .sng structurally valid: a file with zero subtunes is not
        # loadable. One placeholder subtune preserves the previous behaviour for
        # this degenerate case.
        tracks = [list(DEFAULT_TRACK) for _ in range(3)]

    return tracks
