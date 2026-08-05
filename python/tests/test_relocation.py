"""A file that copies part of itself somewhere else before the player runs.

I, Ball loads at $9000, but its init copies $9000-$9FFF up to $E000 and the
tune lives there: every address its player names is an $Exxx one, past the end
of a file that stops at $C2CF. Detection found the tables and then rejected
all four of them as out of range.

The copy is a plain page loop, and the pointers it walks are set up
immediately before it, so both the block and its destination can be read
straight out of the init code -- see sidfile.RELOC_COPY_LOOP for the listing.

The rule that keeps this safe is that `to_offset` consults a relocation *only*
for an address that does not resolve inside the file at all. A misread copy
loop can therefore fail to rescue a file, but it can never move an address in
a file that already works -- which is why parsing only the page numbers, and
assuming page alignment, is good enough.
"""
import struct

import pytest

from h2g.detect import detect
from h2g.sidfile import (HLEN, Relocation, SidFile, find_relocation,
                         load_sid)

LOAD_ADDR = 0x9000
SRC_PAGE, DST_PAGE, PAGES = 0x90, 0xE0, 0x10


def _copy_loop(pages=PAGES, src_page=SRC_PAGE, dst_page=DST_PAGE,
               src_zp=0xFB, dst_zp=0xFD, inc_dst_first=False):
    """I, Ball's init verbatim, with the parts under test parameterised."""
    setup = bytes([
        0xA9, 0x00, 0x85, dst_zp,          # LDA #$00 / STA dst lo
        0x85, src_zp,                      # STA src lo   (shares the same LDA)
        0xA9, src_page, 0x85, src_zp + 1,  # LDA #src / STA src hi
        0xA9, dst_page, 0x85, dst_zp + 1,  # LDA #dst / STA dst hi
    ])
    incs = ([dst_zp + 1, src_zp + 1] if inc_dst_first
            else [src_zp + 1, dst_zp + 1])
    loop = bytes([
        0xA2, pages, 0xA0, 0x00,           # LDX #pages / LDY #$00
        0xB1, src_zp, 0x91, dst_zp,        # LDA (src),Y / STA (dst),Y
        0xC8, 0xD0, 0xF9,                  # INY / BNE
        0xE6, incs[0], 0xE6, incs[1],      # INC src hi / INC dst hi
        0xCA, 0xD0, 0xF0,                  # DEX / BNE
    ])
    return setup + loop


def _sid(data_len=0x107E, reloc=Relocation(0x9000, 0xE000, 0x1000)):
    return SidFile(path="", data=bytes(data_len), name="", author="",
                   released="", load_addr=LOAD_ADDR, subtunes=1,
                   relocation=reloc)


# --- reading the copy loop -------------------------------------------------

def test_the_relocation_is_read_out_of_the_init_code():
    r = find_relocation(b"\x00" + _copy_loop())
    assert r == Relocation(src=0x9000, dst=0xE000, length=0x1000)


def test_the_destination_pointer_may_be_incremented_first():
    # Nothing about the loop requires source-then-destination, so the INC
    # operands are matched as a set rather than in order.
    assert find_relocation(b"\x00" + _copy_loop(inc_dst_first=True)) == \
        Relocation(src=0x9000, dst=0xE000, length=0x1000)


def test_a_file_with_no_copy_loop_has_no_relocation():
    assert find_relocation(bytes(256)) is None


def test_the_inc_operands_must_be_the_two_pointers_high_bytes():
    """Otherwise the loop is walking pointers we have not identified."""
    blob = bytearray(b"\x00" + _copy_loop())
    blob[blob.index(0xA2, 14) + 12] = 0x20      # INC $20 instead of INC $FC
    assert find_relocation(bytes(blob)) is None


def test_a_pointer_with_no_immediate_setup_is_not_a_relocation():
    # Drop the `LDA #$E0 / STA $FE` pair: the destination page is then unknown,
    # and guessing it would be exactly the kind of invention this must not do.
    loop = _copy_loop()
    assert find_relocation(b"\x00" + loop.replace(b"\xA9\xE0\x85\xFE", b"")) \
        is None


def test_a_copy_that_does_not_move_anything_is_not_a_relocation():
    assert find_relocation(b"\x00" + _copy_loop(dst_page=SRC_PAGE)) is None


def test_a_zero_page_count_is_not_a_relocation():
    assert find_relocation(b"\x00" + _copy_loop(pages=0)) is None


# --- applying it -----------------------------------------------------------

def test_an_address_in_the_relocated_block_resolves_to_its_source():
    sid = _sid()
    # $E000 runs from what the file holds at $9000, so both name one offset.
    assert sid.to_offset(0xE000) == sid.to_offset(0x9000) == HLEN - 1
    assert sid.to_offset(0xE123) == sid.to_offset(0x9123)


def test_an_address_past_the_relocated_block_is_left_alone():
    sid = _sid()
    # The block is 16 pages, so $F000 is one past its end.
    assert sid.to_offset(0xF000) == 0xF000 - LOAD_ADDR + HLEN - 1


def test_a_file_without_a_relocation_is_unaffected():
    sid = _sid(reloc=None)
    assert sid.to_offset(0xE000) == 0xE000 - LOAD_ADDR + HLEN - 1


def test_a_relocation_never_moves_an_address_that_already_resolves():
    """The fallback-only rule, stated as a test.

    This relocation's destination window lies *inside* the file, so both
    readings exist. The direct one has to win, or discovering a relocation
    could change a file that converts correctly today.
    """
    sid = _sid(reloc=Relocation(src=0x9000, dst=0x9800, length=0x800))
    assert sid.to_offset(0x9800) == 0x800 + HLEN - 1


# --- end to end ------------------------------------------------------------

def _make_sid(tmp_path, code: bytes, name="probe.sid"):
    header = bytearray(0x7C)
    header[0:4] = b"PSID"
    struct.pack_into(">HHH", header, 4, 2, 0x7C, 0)
    struct.pack_into(">H", header, 0x0E, 1)
    path = tmp_path / name
    path.write_bytes(bytes(header) + struct.pack("<H", LOAD_ADDR) + code)
    return path


def test_load_sid_attaches_the_relocation(tmp_path):
    sid = load_sid(str(_make_sid(tmp_path, _copy_loop() + bytes(64))))
    assert sid.relocation == Relocation(0x9000, 0xE000, 0x1000)


def test_detection_resolves_a_relocated_table(tmp_path):
    """A pattern table named at $E0xx must be found in the $90xx block."""
    op = struct.pack("<H", 0xE010)
    op2 = struct.pack("<H", 0xE030)
    sig = (b"\x4C\x00\x00\xA8\xB9" + op + b"\x85\x00\xB9" + op2
           + b"\x85\x00\xA9\x00\x95")          # Mega Apocalypse shape, so=5
    sid = load_sid(str(_make_sid(tmp_path, _copy_loop() + sig + bytes(256))))
    lines = []
    det = detect(sid, lines.append)

    assert not any("OUT OF RANGE" in line for line in lines)
    assert det.pattern_lo == sid.to_offset(0x9010)
    assert det.pattern_hi == sid.to_offset(0x9030)
