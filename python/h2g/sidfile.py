"""PSID/RSID header parsing.

Mirrors the header reads in loadfile() (h2g.frm lines 240-298). The tool
does not parse the PSID `dataOffset` field; it hardcodes a 0x7C-byte (v2NG)
header plus a 2-byte embedded load address, i.e. HLEN = 0x7F. This matches
the original VB behavior exactly and is preserved here rather than "fixed",
since the goal is a faithful base to redevelop from.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .search import search_file

HLEN = 0x7F  # dataOffset(0x7C) + 2-byte embedded load address, then -1 in to_offset()
MAX_SID_SIZE = 65536


class SidFormatError(Exception):
    pass


@dataclass
class Relocation:
    """A block the file copies elsewhere before the player runs.

    `src` is where the block sits in the loaded image (so where it is in the
    file), `dst` where it executes from. Everything the player's code names --
    table bases, and the pointers those tables hold -- is written for `dst`.
    """
    src: int
    dst: int
    length: int


# I, Ball loads at $9000 but its init copies $9000-$9FFF up to $E000 and the
# tune lives there: every address its player names is an $Exxx one, which is
# past EOF in a file that ends at $C2CF. The copy is a page loop, and the two
# pointers it walks are set up immediately before it:
#
#     C20C  A9 00     LDA #$00
#     C20E  85 FD     STA $FD      ; dst lo
#     C210  85 FB     STA $FB      ; src lo
#     C212  A9 90     LDA #$90
#     C214  85 FC     STA $FC      ; src hi
#     C216  A9 E0     LDA #$E0
#     C218  85 FE     STA $FE      ; dst hi
#     C21A  A2 10     LDX #$10     ; 16 pages   <- RELOC_COPY_LOOP matches here
#     C21C  A0 00     LDY #$00
#     C21E  B1 FB     LDA ($FB),Y
#     C220  91 FD     STA ($FD),Y
#     C222  C8 D0 F9  INY / BNE
#     C225  E6 FC     INC $FC
#     C227  E6 FE     INC $FE
#     C229  CA D0 F0  DEX / BNE
#
# Only the page counts are read back, so the copy is assumed page-aligned --
# which the loop shape implies, since it starts at Y=0 and runs whole pages.
RELOC_COPY_LOOP = "A2 ?? A0 00 B1 ?? 91 ?? C8 D0 F9 E6 ?? E6 ?? CA D0 F0"
RELOC_SETUP_WINDOW = 64   # bytes before the loop that may hold the pointer setup


def _last_immediate_store(data: bytes, before: int, zp: int) -> Optional[int]:
    """Value of the last `LDA #imm` / `STA <zp>` pair in the bytes before `before`."""
    found = None
    for k in range(max(0, before - RELOC_SETUP_WINDOW), before - 3):
        if data[k] == 0xA9 and data[k + 2] == 0x85 and data[k + 3] == zp:
            found = data[k + 1]
    return found


def find_relocation(data: bytes) -> Optional[Relocation]:
    """The block a self-relocating file copies at init, or None.

    Recognising this wrong is harmless: `to_offset` consults the result only
    for an address that does not resolve inside the file at all, so a bogus
    relocation can fail to rescue a file but can never move a working one.
    """
    i = search_file(data, RELOC_COPY_LOOP)
    if i <= -1:
        return None
    pages, src_zp, dst_zp = data[i + 1], data[i + 5], data[i + 7]
    # The two INC operands must be the two pointers' high bytes. Comparing them
    # as a set rather than in order means a player that increments the
    # destination first still reads correctly.
    if {data[i + 12], data[i + 14]} != {(src_zp + 1) & 0xFF, (dst_zp + 1) & 0xFF}:
        return None
    src = _last_immediate_store(data, i, (src_zp + 1) & 0xFF)
    dst = _last_immediate_store(data, i, (dst_zp + 1) & 0xFF)
    if src is None or dst is None or src == dst or pages == 0:
        return None
    return Relocation(src=src << 8, dst=dst << 8, length=pages << 8)


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
    magic: str = "PSID"     # "PSID" or "RSID", header 0x00-0x03
    version: int = 0        # header `version`, 16-bit BE at 0x04
    relocation: Optional[Relocation] = None  # block moved at init, see to_offset

    @property
    def source_format(self) -> str:
        """The input file's own format version, e.g. "PSID v2".

        This is the *source* player-file version, distinct from the Hubbard
        player-engine variant that detect() fingerprints and from the
        Goattracker output format.
        """
        return f"{self.magic} v{self.version}"

    def to_offset(self, addr: int) -> int:
        """C64 address -> byte offset into `data` (SIDRHinstrStart-style formula).

        A file that relocates part of itself at init names addresses the load
        address alone cannot resolve. The relocation is consulted only when the
        plain formula lands outside the file, so a file without one, and any
        address that already resolves, behave exactly as before.
        """
        off = addr - self.load_addr + HLEN - 1
        r = self.relocation
        if r is not None and not 0 <= off < len(self.data) \
                and r.dst <= addr < r.dst + r.length:
            return addr - r.dst + r.src - self.load_addr + HLEN - 1
        return off

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
    # Magic and header version. Read for reporting only -- the original tool
    # ignores both (it hardcodes a v2NG layout, see HLEN), and this port keeps
    # that behaviour, so nothing downstream branches on these.
    magic = data[0:4].decode("latin-1")
    version = int.from_bytes(data[0x04:0x06], "big")

    return SidFile(
        path=path,
        data=data,
        name=name,
        author=author,
        released=released,
        load_addr=load_addr,
        subtunes=subtunes,
        speed=speed,
        magic=magic,
        version=version,
        relocation=find_relocation(data),
    )
