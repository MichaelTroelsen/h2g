"""PSID/RSID header parsing.

Mirrors the header reads in loadfile() (h2g.frm lines 240-298). The tool
does not parse the PSID `dataOffset` field; it hardcodes a 0x7C-byte (v2NG)
header plus a 2-byte embedded load address, i.e. HLEN = 0x7F. This matches
the original VB behavior exactly and is preserved here rather than "fixed",
since the goal is a faithful base to redevelop from.
"""
from __future__ import annotations

from dataclasses import dataclass

HLEN = 0x7F  # dataOffset(0x7C) + 2-byte embedded load address, then -1 in to_offset()
MAX_SID_SIZE = 65536


class SidFormatError(Exception):
    pass


@dataclass
class SidFile:
    path: str
    data: bytes  # raw file bytes; data[k] == VB's SIDfile(k)
    name: str
    author: str
    released: str
    load_addr: int
    subtunes: int
    speed: int = 0  # PSID `speed`, 32-bit BE at 0x12: one bit per subtune

    def to_offset(self, addr: int) -> int:
        """C64 address -> byte offset into `data` (SIDRHinstrStart-style formula)."""
        return addr - self.load_addr + HLEN - 1

    def is_cia_timed(self, subtune: int = 0) -> bool:
        """True if this subtune is driven by a CIA timer rather than the VBI.

        Per the PSID spec the `speed` field is a bitmap, one bit per subtune,
        bit N covering subtune N (subtunes past 31 reuse bit 31). 0 means the
        play routine is called once per vertical blank (50Hz PAL); 1 means a
        CIA timer drives it, at a rate the header does not record.

        Note this does NOT give a multispeed factor -- a CIA tune may tick at
        any rate. It only says "not plain 50Hz", which is why it cannot by
        itself determine a Goattracker tempo. See goatwriter.tempo_for().
        """
        return bool(self.speed & (1 << min(subtune, 31)))


def _read_padded_string(data: bytes, offset: int, length: int) -> str:
    # loadfile() only skips zero bytes; any non-zero byte (even after a zero)
    # is appended. Fields are null-padded so this is equivalent to filtering
    # out nulls.
    return "".join(chr(b) for b in data[offset:offset + length] if b != 0)


def load_sid(path: str) -> SidFile:
    with open(path, "rb") as f:
        data = f.read()

    if len(data) >= MAX_SID_SIZE:
        raise SidFormatError(f"file too large ({len(data)} bytes >= {MAX_SID_SIZE})")
    if len(data) < 0x7E or data[1:4] != b"SID":
        raise SidFormatError("not a PSID/RSID file")

    name = _read_padded_string(data, 0x16, 0x20)
    author = _read_padded_string(data, 0x36, 0x20)
    released = _read_padded_string(data, 0x56, 0x20)
    load_addr = data[0x7D] * 256 + data[0x7C]
    subtunes = data[0x0F]
    # PSID `speed` at 0x12-0x15, big-endian. Unlike load_addr/dataOffset (which
    # the original tool ignores and this port deliberately keeps ignoring), this
    # field is read straight from the header -- nothing in the VB6 original
    # depended on it, so reading it changes no existing behaviour.
    speed = int.from_bytes(data[0x12:0x16], "big")

    return SidFile(
        path=path,
        data=data,
        name=name,
        author=author,
        released=released,
        load_addr=load_addr,
        subtunes=subtunes,
        speed=speed,
    )
