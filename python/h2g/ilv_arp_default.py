"""The interleaved engine's per-instrument DEFAULT arpeggio (record byte +10).

`patterns.ILV_ARP` documents `$83 nn`, the per-note arpeggio operand the
player keeps in `$1A55,X`. That cell is not only the command's: the note-start
block ends

    12BB  BD 55 1B  LDA $1B55,X     ; record +10 (instr_start + 10)
    12BE  8D A0 13  STA $13A0       ; patches the operand of the LDA #imm below
    ...
    139A  AD 61 1A  LDA $1A61       ; was a $83 read this event?
    139D  D0 05     BNE $13A4       ; yes -> keep its operand
    139F  A9 00     LDA #$00        ; operand patched to the record's +10
    13A1  9D 55 1A  STA $1A55,X     ; no  -> the instrument's own arpeggio

so every note of a record whose +10 is non-zero arpeggiates, with no command in
the pattern at all. Go_Go_Dash's record 1 (`$0286`, `+10 = $C0`) is an octave
trill note / note+12 on alternate frames -- 1382 reversals in the original,
none in a conversion that reads `$83` only.

The shape is matched on the player's bytes (the LDA abs,X of the record's +10
feeding a STA abs that patches an `LDA #imm` whose result is stored by a STA
abs,X), never assumed from the dialect, so a player that spells it otherwise
returns an empty dict and nothing changes.
"""
from __future__ import annotations

from typing import Dict

from .detect import Detection
from .sidfile import SidFile

LDA_ABSX = 0xBD
STA_ABS = 0x8D
STA_ABSX = 0x9D
LDA_IMM = 0xA9


def default_arp_patch_site(sid: SidFile, det: Detection):
    """File offset of the patched `LDA #imm` operand, or None if not found."""
    if det.instr_start < 0 or det.instr_stride < 11:
        return None
    data = sid.data
    cell = sid.to_address(det.instr_start) + 10
    lo, hi = cell & 0xFF, cell >> 8
    for i in range(len(data) - 6):
        if data[i] != LDA_ABSX or data[i + 1] != lo or data[i + 2] != hi:
            continue
        if data[i + 3] != STA_ABS:
            continue
        target = sid.to_offset(data[i + 4] | data[i + 5] << 8)
        if not 1 <= target < len(data) - 2:
            continue
        if (data[target - 1] == LDA_IMM and data[target + 1] == STA_ABSX):
            return target
    return None


def ilv_default_arps(sid: SidFile, det: Detection) -> Dict[int, int]:
    """`{record: operand}` for every record whose +10 byte is a non-zero
    default arpeggio, or {} where the player does not read it that way."""
    if det.pattern_dialect != "ilv" or det.instr_stride < 11:
        return {}
    if default_arp_patch_site(sid, det) is None:
        return {}
    data = sid.data
    out: Dict[int, int] = {}
    for r in range(det.instr_used):
        o = det.instr_start + r * det.instr_stride + 10
        if o < len(data) and data[o]:
            out[r] = data[o]
    return out
