"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

from typing import List

from .detect import Detection
from .sidfile import SidFile

HEADER_LEN = 0x64
FIELD_LEN = 0x20

# Goattracker limits, from goattracker2 src/gcommon.h.
GT_MAX_INSTR = 64      # MAX_INSTR
GT_MAX_TABLELEN = 255  # MAX_TABLELEN -- ltable/rtable are this many bytes each

# Wave/pulse table entries emitted per instrument.
WAVE_ENTRIES_PER_INSTR = 5
PULSE_ENTRIES_PER_INSTR = 2

# The binding constraint is NOT MAX_INSTR. Each instrument costs 5 wavetable
# entries, and the wavetable's stored length is a single byte bounded by
# MAX_TABLELEN, so at most 255//5 == 51 instruments can be represented at all.
# Raising the clamp to GT_MAX_INSTR (64) would need 320 entries: the length byte
# would wrap and Goattracker would read a truncated table over the following
# section. Keep this at or below MAX_REPRESENTABLE_INSTRUMENTS.
MAX_REPRESENTABLE_INSTRUMENTS = GT_MAX_TABLELEN // WAVE_ENTRIES_PER_INSTR  # 51

# 50 is what the original VB6 tool used, and what the byte-exact Commando
# fixture encodes. It is one below the representable maximum; leave it alone
# unless you are deliberately changing output.
MAX_INSTRUMENTS = 50

assert MAX_INSTRUMENTS <= MAX_REPRESENTABLE_INSTRUMENTS


def _table_length_byte(entries: int, what: str) -> int:
    """Length byte for a wave/pulse table, refusing to silently wrap.

    The original masked with & 0xFF, which turns an over-long table into a
    plausible-looking short one -- Goattracker then reads the remainder as
    whatever section follows. Fail loudly instead.
    """
    if not 0 <= entries <= GT_MAX_TABLELEN:
        raise ValueError(
            f"{what} table needs {entries} entries, exceeding Goattracker's "
            f"MAX_TABLELEN ({GT_MAX_TABLELEN})"
        )
    return entries


def _padded_name_bytes(name: str, width: int = 16) -> bytes:
    raw = name.encode("latin-1", errors="replace")[:width]
    return raw + bytes(width - len(raw))


def _field_bytes(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")[:FIELD_LEN]
    return raw.ljust(FIELD_LEN, b"\x00")


def _build_header(sid: SidFile) -> bytearray:
    header = bytearray(HEADER_LEN)
    header[0:4] = b"GTS2"
    header[0x04:0x04 + FIELD_LEN] = _field_bytes(sid.name)
    header[0x24:0x24 + FIELD_LEN] = _field_bytes(sid.author)
    header[0x44:0x44 + FIELD_LEN] = _field_bytes(sid.released)
    return header


def _write_instruments(out: bytearray, sid: SidFile, det: Detection,
                       log=None) -> int:
    available = det.instr_used + 1
    instr_used = min(available, MAX_INSTRUMENTS)
    if log and available > instr_used:
        # Not an over-read: Hubbard players carry a shared instrument bank
        # (drum/noise entries recur byte-identically across games), so tables of
        # 56-58 real records are normal even when a tune plays a dozen. The
        # wavetable simply cannot address more than MAX_REPRESENTABLE_INSTRUMENTS.
        log(f"*** INSTRUMENT TABLE HAS {available} ENTRIES, ONLY {instr_used} FIT "
            f"(GOATTRACKER WAVETABLE LIMIT) -- {available - instr_used} DROPPED ***")
    out.append(instr_used)

    # Instrument 1: always the empty "Clear Voice" slot.
    out += bytes([0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00, 0x02, 0x09])
    out += _padded_name_bytes("Clear Voice")

    wtable_start = 6
    ptable_start = 3
    data = sid.data
    n = max(instr_used - 1, 0)  # number of real (non-empty) instruments

    for i in range(n):
        base = det.instr_start + i * 8
        ad = data[base + 3]
        sr = data[base + 4]
        if sr >= 0xF0:
            sr &= 0xEF
        wave_ptr = (i * 5 + wtable_start) & 0xFF
        pulse_ptr = (i * 2 + ptable_start) & 0xFF
        out += bytes([ad, sr, wave_ptr, pulse_ptr, 0x00, 0x00, 0x00, 0x02, 0x09])

        b5, b6, b7 = data[base + 5], data[base + 6], data[base + 7]
        name = f"{i + 2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"
        out += _padded_name_bytes(name)

    return instr_used


def _write_wavetable(out: bytearray, sid: SidFile, det: Detection, instr_used: int) -> None:
    data = sid.data
    n = max(instr_used - 1, 0)

    # LEFT side
    out.append(_table_length_byte(instr_used * WAVE_ENTRIES_PER_INSTR, "wave"))
    out += bytes([0x09, 0xFF, 0x00, 0x00, 0x00])
    for i in range(n):
        base = det.instr_start + i * 8
        arp_style = data[base + 7]
        arp_set_keybit = 0 if (arp_style & 1) == 1 else 1
        wave = data[base + 2]

        out.append(wave)  # 1st tick
        if (arp_style & 1) == 1:
            out.append(0x80 | arp_set_keybit)  # 2nd tick: noise
        else:
            out.append((wave & 0xFE) | arp_set_keybit)

        tail = (wave & 0xFE) | arp_set_keybit
        if (arp_style & 4) == 4:
            out += bytes([tail, tail, 0xFF])
        else:
            out += bytes([tail, 0xFF, 0xFF])

    # RIGHT side
    out += bytes([0x00, 0x00, 0x00, 0x00, 0x00])
    for i in range(n):
        base = det.instr_start + i * 8
        arp_style = data[base + 7]
        arp_note = (arp_style & 0xF0) >> 4
        if arp_note == 0:
            arp_note = 0x74

        out.append(0x00)  # 1st tick note
        if (arp_style & 1) == 1:  # (ArpStyle&4)==1 in the original is always false
            out.append((0x80 - arp_note) & 0xFF)
        else:
            out.append(0x00)

        if (arp_style & 4) == 4:
            jump_to = ((i + 2) * 5 - 2) & 0xFF
            out += bytes([0x00, (0x80 - arp_note) & 0xFF, jump_to])
        else:
            out += bytes([0x00, 0x00, 0x00])


def _write_pulsetable(out: bytearray, sid: SidFile, det: Detection, instr_used: int) -> None:
    data = sid.data
    n = max(instr_used - 1, 0)

    out.append(_table_length_byte(instr_used * PULSE_ENTRIES_PER_INSTR, "pulse"))
    out += bytes([0x80, 0xFF])
    for i in range(n):
        base = det.instr_start + i * 8
        out.append((data[base + 1] | 0x80) & 0xFF)
        out.append(0xFF)

    out += bytes([0x00, 0x00])
    for i in range(n):
        base = det.instr_start + i * 8
        out.append(data[base])
        out.append(0x00)


def _highest_instrument_referenced(patterns: List[List[int]]) -> int:
    """Largest instrument number any pattern row selects (column 1 of 4)."""
    highest = 0
    for pattern in patterns:
        for k in range(1, len(pattern), 4):
            if pattern[k] > highest:
                highest = pattern[k]
    return highest


def build_sng(sid: SidFile, det: Detection, tracks: List[List[int]],
              patterns: List[List[int]], log=None) -> bytes:
    out = bytearray()
    out += _build_header(sid)
    # Derived from the tracks actually emitted, not sid.subtunes: convert_tracks
    # trims subtunes the track table cannot back, and the count byte must agree
    # with the number of tracks that follow or the file is unreadable. Identical
    # to sid.subtunes whenever nothing was trimmed.
    out.append((len(tracks) // 3) & 0xFF)

    for track in tracks:
        out.append((len(track) - 1) & 0xFF)
        out += bytes(track)

    instr_used = _write_instruments(out, sid, det, log)
    _write_wavetable(out, sid, det, instr_used)
    _write_pulsetable(out, sid, det, instr_used)

    if log:
        # Instruments are written as 1..instr_used, so anything above that is a
        # reference to a slot the file does not contain. Goattracker will play
        # those rows with an undefined instrument.
        highest = _highest_instrument_referenced(patterns)
        if highest > instr_used:
            log(f"*** PATTERNS REFERENCE INSTRUMENT ${highest:X} BUT ONLY "
                f"${instr_used:X} WERE WRITTEN -- {highest - instr_used} DANGLING ***")

    out += bytes([0x02, 0x11, 0xFF, 0x22, 0x01])  # empty filter table

    out.append(len(patterns) & 0xFF)
    for pattern in patterns:
        out.append((len(pattern) // 4) & 0xFF)
        out += bytes(pattern)

    return bytes(out)
