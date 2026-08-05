"""Delta (Mix-E-Load loader): Mega Apocalypse's pattern shape, one opcode apart.

The loader's pattern-table read is the Mega Apocalypse fingerprint exactly,
except that it clears its per-voice state with `STA abs,X` rather than
`STA zp,X` -- `9D` where that one has `95`. $C0CA:

    C0CA  4C 9D C0  JMP $C09D     ; $FF handled: back to the orderlist read
    C0CD  A8        TAY
    C0CE  B9 6E C7  LDA $C76E,Y   ; pattern lo
    C0D1  85 FA     STA $FA
    C0D3  B9 96 C7  LDA $C796,Y   ; pattern hi
    C0D6  85 FB     STA $FB
    C0D8  A9 00     LDA #$00
    C0DA  9D 68 C5  STA $C568,X

One byte was the whole difference between converting and
"*** CAN'T FIND PATTERN ***".

The signature goes last in the chain, so it can only speak for a file every
other fingerprint has already declined; the tail byte stays a literal rather
than a wildcard for the same reason.
"""
import struct

import pytest

from h2g.detect import detect
from h2g.sidfile import load_sid

LOAD_ADDR = 0x1000
PATTERN_LO, PATTERN_HI = 0x1020, 0x1040


def _make_sid(tmp_path, code: bytes, name="probe.sid"):
    header = bytearray(0x7C)
    header[0:4] = b"PSID"
    struct.pack_into(">HHH", header, 4, 2, 0x7C, 0)
    struct.pack_into(">H", header, 0x0E, 1)
    path = tmp_path / name
    path.write_bytes(bytes(header) + struct.pack("<H", LOAD_ADDR) + code)
    return path


def _pattern_read(tail: int) -> bytes:
    """The shared shape, `tail` being the opcode the two dialects differ in."""
    lo = struct.pack("<H", PATTERN_LO)
    hi = struct.pack("<H", PATTERN_HI)
    return (b"\x4C\x00\x00\xA8\xB9" + lo + b"\x85\xFA\xB9" + hi
            + b"\x85\xFB\xA9\x00" + bytes([tail]))


def _detect(tmp_path, code, name):
    sid = load_sid(str(_make_sid(tmp_path, code + bytes(0x60), name)))
    return sid, detect(sid, lambda _m: None)


@pytest.mark.parametrize("tail,dialect", [(0x95, "Mega Apocalypse"),
                                          (0x9D, "Delta loader")])
def test_both_tail_opcodes_locate_the_same_table_pair(tmp_path, tail, dialect):
    sid, det = _detect(tmp_path, _pattern_read(tail), f"{tail:02x}.sid")
    assert det.pattern_lo == sid.to_offset(PATTERN_LO)
    assert det.pattern_hi == sid.to_offset(PATTERN_HI)
    assert det.pattern_used == PATTERN_HI - PATTERN_LO - 1


def test_an_unlisted_tail_opcode_is_not_accepted(tmp_path):
    """The tail is what makes the two signatures distinct; keep it literal.

    `99` is STA abs,Y -- a plausible-looking neighbour of both. Matching it
    would mean the chain no longer identifies a dialect, only a rough shape.
    """
    _sid, det = _detect(tmp_path, _pattern_read(0x99), "99.sid")
    assert det.pattern_lo == -1 and det.pattern_used == -1
