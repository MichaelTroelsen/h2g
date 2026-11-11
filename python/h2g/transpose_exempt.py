"""Records the interleaved ("ILV") players do NOT transpose.

The six `$FD nn` files (Go_Go_Dash, Lakers_vs_Celtics, Lion_Heart,
Pacific_Coast, Radio_ACE, Sun_Never_Shines) add the voice's orderlist transpose
to a note only for SOME instrument records. Lakers_vs_Celtics $1270:

    1270  C9 60     CMP #$60
    1274  8D 7F 12  STA $127F        ; the note, patched into the LDA #imm below
    1277  AD E9 1A  LDA $1AE9        ; the record's flag byte (record + 7)
    127A  29 01     AND #$01
    127C  D0 09     BNE $1287        ; bit 0 set -> the raw note
    127E  A9 00     LDA #$00         ; (patched: the note)
    1280  18        CLC
    1281  7D 02 1B  ADC $1B02,X      ; ...bit 0 clear -> note + transpose
    1284  4C 8A 12  JMP $128A
    1287  AD 7F 12  LDA $127F

The flag cell is written at the note start from a 16-byte-stride record table
(`LDA $1B7A,X` with X = 16 * the `$80 nn` operand). Goattracker's orderlist
transpose is per voice and applies to every note, so a record with bit 0 set
sounds `transpose` semitones off wherever the voice is transposed: measured at
v0.5.660 on Lakers_vs_Celtics as voice 0 `+2` x24 and voice 1 `-2` x52 / `-5` x5
(exactly the notes of records 2 and 0 under `F2`, `EE`, `EB`), and on
Pacific_Coast voice 1 as `+5`/`+3` on records 0 and 2.
"""
from __future__ import annotations

from typing import FrozenSet

from .detect import Detection
from .search import search_file
from .sidfile import SidFile

# The reader: `LDA flag / AND #$01 / BNE raw / LDA #imm / CLC / ADC t,X / JMP / LDA imm`.
EXEMPT_READ = "AD ?? ?? 29 01 D0 09 A9 00 18 7D ?? ?? 4C ?? ?? AD ?? ??"


def exempt_flag_table(sid: SidFile, det: Detection) -> int:
    """File offset of record 0's flag byte, or -1 when the player has none.

    Only the `$FD nn` interleaved files are consulted: the shape means nothing
    without an orderlist transpose, and gating on the dialect keeps every other
    conversion byte-identical.
    """
    if not (det.track_fd_transpose and det.pattern_dialect == "ilv"):
        return -1
    data = sid.data
    at = search_file(data, EXEMPT_READ)
    if at < 1:
        return -1
    cell = data[at + 1:at + 3]
    found = set()
    # The writer: `LDA table,X / STA cell`, X = 16 * record.
    for j in range(1, len(data) - 5):
        if data[j] == 0xBD and data[j + 3] == 0x8D and data[j + 4:j + 6] == cell:
            found.add(data[j + 1] | data[j + 2] << 8)
    if len(found) != 1:
        return -1
    table = found.pop()
    base = sid.to_address(det.instr_start)
    # The flag lives inside the 16-byte record it indexes.
    if not 0 <= table - base < det.instr_stride:
        return -1
    off = sid.to_offset(table)
    last = off + det.instr_stride * max(det.instr_used, 0)
    return off if 0 < off and last < len(data) else -1


def exempt_records(sid: SidFile, det: Detection) -> FrozenSet[int]:
    """Records whose notes the player leaves untransposed (flag bit 0 set)."""
    off = exempt_flag_table(sid, det)
    if off < 0:
        return frozenset()
    data = sid.data
    return frozenset(r for r in range(max(det.instr_used, 0) + 1)
                     if data[off + det.instr_stride * r] & 1)
