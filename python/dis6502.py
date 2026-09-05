"""A 6502 disassembler for reading Hubbard players out of a `.sid`.

Every mechanism this converter emits was decoded by reading the player's own
code, and until v0.5.241 that was done with a throwaway script rewritten each
time it was needed -- most recently to find that Rikky's `AND #$04` block is
`detect.TWO_STAGE_SHAPE` byte for byte, which turned the onset census's largest
group into a one-line fix (H2G-CONVERSION-METHOD.md section 7.nnnn). CLAUDE.md's
rule about the census applies to this too: a scratch script that answers a
question twice is a tool that was not committed.

    python dis6502.py <file.sid> --at '$13C2' -n 12
    python dis6502.py <file.sid> --offset 0x443 -n 12
    python dis6502.py <file.sid> --find 'AD ?? ?? 29 04' -n 12

`--find` takes `search.search_file`'s wildcard syntax -- the same strings
`detect.py` fingerprints players with -- so a signature that is failing to match
can be pasted straight in and looked at. It is the step that was done with a
separate `data.find(b'\\x29\\x04')` and a hand-computed address before.

**Addresses, not offsets, are what the player's own operands name**, so every
line is printed at its C64 address and `--find` reports both. The mapping is
`SidFile.to_address`, called rather than re-derived -- **including its
relocation branch**, which this module used to declare unresolvable. A file
that copies part of itself elsewhere at init (I, Ball) holds those bytes at
`src` and the player reads them at `dst`, so an offset inside the moved region
names an address `dst - src` above the plain inversion: I_Ball's effect byte is
$E557, not the $9557 this printed before. A disassembler that labels a line
with an address the player never reads is worse than one that declines, which
is why the formula is now in exactly one place for every caller.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g.sidfile import HLEN, SidFile, load_sid           # noqa: E402

# mode -> operand length in bytes, the instruction being one more
MODES = {
    "imp": 0, "acc": 0, "imm": 1, "zp": 1, "zpx": 1, "zpy": 1, "izx": 1,
    "izy": 1, "rel": 1, "abs": 2, "abx": 2, "aby": 2, "ind": 2,
}

# The 151 legal opcodes. Anything absent is printed as `???` and stepped over
# one byte at a time: a disassembly that resynchronises is more useful than one
# that invents an operand, and Hubbard's players carry tables between routines.
OPCODES = {
    0x00: ("BRK", "imp"), 0x01: ("ORA", "izx"), 0x05: ("ORA", "zp"),
    0x06: ("ASL", "zp"), 0x08: ("PHP", "imp"), 0x09: ("ORA", "imm"),
    0x0A: ("ASL", "acc"), 0x0D: ("ORA", "abs"), 0x0E: ("ASL", "abs"),
    0x10: ("BPL", "rel"), 0x11: ("ORA", "izy"), 0x15: ("ORA", "zpx"),
    0x16: ("ASL", "zpx"), 0x18: ("CLC", "imp"), 0x19: ("ORA", "aby"),
    0x1D: ("ORA", "abx"), 0x1E: ("ASL", "abx"), 0x20: ("JSR", "abs"),
    0x21: ("AND", "izx"), 0x24: ("BIT", "zp"), 0x25: ("AND", "zp"),
    0x26: ("ROL", "zp"), 0x28: ("PLP", "imp"), 0x29: ("AND", "imm"),
    0x2A: ("ROL", "acc"), 0x2C: ("BIT", "abs"), 0x2D: ("AND", "abs"),
    0x2E: ("ROL", "abs"), 0x30: ("BMI", "rel"), 0x31: ("AND", "izy"),
    0x35: ("AND", "zpx"), 0x36: ("ROL", "zpx"), 0x38: ("SEC", "imp"),
    0x39: ("AND", "aby"), 0x3D: ("AND", "abx"), 0x3E: ("ROL", "abx"),
    0x40: ("RTI", "imp"), 0x41: ("EOR", "izx"), 0x45: ("EOR", "zp"),
    0x46: ("LSR", "zp"), 0x48: ("PHA", "imp"), 0x49: ("EOR", "imm"),
    0x4A: ("LSR", "acc"), 0x4C: ("JMP", "abs"), 0x4D: ("EOR", "abs"),
    0x4E: ("LSR", "abs"), 0x50: ("BVC", "rel"), 0x51: ("EOR", "izy"),
    0x55: ("EOR", "zpx"), 0x56: ("LSR", "zpx"), 0x58: ("CLI", "imp"),
    0x59: ("EOR", "aby"), 0x5D: ("EOR", "abx"), 0x5E: ("LSR", "abx"),
    0x60: ("RTS", "imp"), 0x61: ("ADC", "izx"), 0x65: ("ADC", "zp"),
    0x66: ("ROR", "zp"), 0x68: ("PLA", "imp"), 0x69: ("ADC", "imm"),
    0x6A: ("ROR", "acc"), 0x6C: ("JMP", "ind"), 0x6D: ("ADC", "abs"),
    0x6E: ("ROR", "abs"), 0x70: ("BVS", "rel"), 0x71: ("ADC", "izy"),
    0x75: ("ADC", "zpx"), 0x76: ("ROR", "zpx"), 0x78: ("SEI", "imp"),
    0x79: ("ADC", "aby"), 0x7D: ("ADC", "abx"), 0x7E: ("ROR", "abx"),
    0x81: ("STA", "izx"), 0x84: ("STY", "zp"), 0x85: ("STA", "zp"),
    0x86: ("STX", "zp"), 0x88: ("DEY", "imp"), 0x8A: ("TXA", "imp"),
    0x8C: ("STY", "abs"), 0x8D: ("STA", "abs"), 0x8E: ("STX", "abs"),
    0x90: ("BCC", "rel"), 0x91: ("STA", "izy"), 0x94: ("STY", "zpx"),
    0x95: ("STA", "zpx"), 0x96: ("STX", "zpy"), 0x98: ("TYA", "imp"),
    0x99: ("STA", "aby"), 0x9A: ("TXS", "imp"), 0x9D: ("STA", "abx"),
    0xA0: ("LDY", "imm"), 0xA1: ("LDA", "izx"), 0xA2: ("LDX", "imm"),
    0xA4: ("LDY", "zp"), 0xA5: ("LDA", "zp"), 0xA6: ("LDX", "zp"),
    0xA8: ("TAY", "imp"), 0xA9: ("LDA", "imm"), 0xAA: ("TAX", "imp"),
    0xAC: ("LDY", "abs"), 0xAD: ("LDA", "abs"), 0xAE: ("LDX", "abs"),
    0xB0: ("BCS", "rel"), 0xB1: ("LDA", "izy"), 0xB4: ("LDY", "zpx"),
    0xB5: ("LDA", "zpx"), 0xB6: ("LDX", "zpy"), 0xB8: ("CLV", "imp"),
    0xB9: ("LDA", "aby"), 0xBA: ("TSX", "imp"), 0xBC: ("LDY", "abx"),
    0xBD: ("LDA", "abx"), 0xBE: ("LDX", "aby"), 0xC0: ("CPY", "imm"),
    0xC1: ("CMP", "izx"), 0xC4: ("CPY", "zp"), 0xC5: ("CMP", "zp"),
    0xC6: ("DEC", "zp"), 0xC8: ("INY", "imp"), 0xC9: ("CMP", "imm"),
    0xCA: ("DEX", "imp"), 0xCC: ("CPY", "abs"), 0xCD: ("CMP", "abs"),
    0xCE: ("DEC", "abs"), 0xD0: ("BNE", "rel"), 0xD1: ("CMP", "izy"),
    0xD5: ("CMP", "zpx"), 0xD6: ("DEC", "zpx"), 0xD8: ("CLD", "imp"),
    0xD9: ("CMP", "aby"), 0xDD: ("CMP", "abx"), 0xDE: ("DEC", "abx"),
    0xE0: ("CPX", "imm"), 0xE1: ("SBC", "izx"), 0xE4: ("CPX", "zp"),
    0xE5: ("SBC", "zp"), 0xE6: ("INC", "zp"), 0xE8: ("INX", "imp"),
    0xE9: ("SBC", "imm"), 0xEA: ("NOP", "imp"), 0xEC: ("CPX", "abs"),
    0xED: ("SBC", "abs"), 0xEE: ("INC", "abs"), 0xF0: ("BEQ", "rel"),
    0xF1: ("SBC", "izy"), 0xF5: ("SBC", "zpx"), 0xF6: ("INC", "zpx"),
    0xF8: ("SED", "imp"), 0xF9: ("SBC", "aby"), 0xFD: ("SBC", "abx"),
    0xFE: ("INC", "abx"),
}

# What a store or load into the SID means, annotated on the line. These
# addresses are what the whole project is about -- `$D404` is the register
# `wave`, `onset` and `nrun` all read -- and naming them is the difference
# between reading a routine and decoding it twice.
SID_NAMES = {
    0x00: "freq lo", 0x01: "freq hi", 0x02: "pulse lo", 0x03: "pulse hi",
    0x04: "ctrl (waveform/gate)", 0x05: "attack/decay", 0x06: "sustain/release",
}
SID_GLOBAL = {
    0xD415: "cutoff lo", 0xD416: "cutoff hi", 0xD417: "resonance/routing",
    0xD418: "volume/filter mode",
}


@dataclass
class Instruction:
    address: int
    offset: int
    raw: bytes
    mnemonic: str
    mode: str
    operand: int | None

    @property
    def size(self) -> int:
        return len(self.raw)

    def target(self) -> int | None:
        """The address this instruction names, where it names one."""
        if self.mode == "rel":
            return (self.address + 2 + ((self.operand ^ 0x80) - 0x80)) & 0xFFFF
        if self.mode in ("abs", "abx", "aby", "ind"):
            return self.operand
        if self.mode in ("zp", "zpx", "zpy", "izx", "izy"):
            return self.operand
        return None

    def text(self) -> str:
        m, o = self.mode, self.operand
        if m == "imp":
            return self.mnemonic
        if m == "acc":
            return f"{self.mnemonic} A"
        if m == "imm":
            return f"{self.mnemonic} #${o:02X}"
        if m == "rel":
            return f"{self.mnemonic} ${self.target():04X}"
        arg = {
            "zp": f"${o:02X}", "zpx": f"${o:02X},X", "zpy": f"${o:02X},Y",
            "izx": f"(${o:02X},X)", "izy": f"(${o:02X}),Y",
            "abs": f"${o:04X}", "abx": f"${o:04X},X", "aby": f"${o:04X},Y",
            "ind": f"(${o:04X})",
        }[m]
        return f"{self.mnemonic} {arg}"

    def note(self) -> str:
        """A SID register comment, or empty.

        Indexed stores reach the register file through `,Y` holding the voice
        offset (0, 7, 14), so `$D404,Y` is *every* voice's control register --
        which is why the note names the register rather than the voice.
        """
        t = self.target()
        if t is None or not 0xD400 <= t <= 0xD41F:
            return ""
        if t in SID_GLOBAL:
            return SID_GLOBAL[t]
        name = SID_NAMES.get((t - 0xD400) % 7)
        if name is None:
            return ""
        voice = "" if self.mode in ("abx", "aby") else f" v{(t - 0xD400) // 7 + 1}"
        return f"{name}{voice}"


def find_all(data: bytes, pattern: str, limit: int = 0) -> list:
    """Every offset matching a wildcard byte pattern, `search_file`'s syntax.

    `search.search_file` answers with the first match only, and it starts at
    offset 1 rather than 0 -- a quirk carried from the VB original's
    `SSearchfile` and relied on by every signature in `detect.py`. This scans
    the same way for the same reason: a pattern that detection matches has to
    match here, at the same address, or the tool is answering a different
    question than the one being debugged. `tests/test_dis6502.py` pins the
    first result against `search_file` itself.
    """
    values = [None if t == "??" else int(t, 16) for t in pattern.split()]
    out = []
    for i in range(1, len(data) - len(values) + 1):
        if all(v is None or data[i + k] == v for k, v in enumerate(values)):
            out.append(i)
            if limit and len(out) >= limit:
                break
    return out


def to_address(sid: SidFile, offset: int) -> int:
    """File offset -> C64 address, delegating to `SidFile.to_address`.

    **This used to be the tenth hand-rolled copy of that formula**, and its
    docstring used to claim the relocation branch "cannot be recovered from an
    offset alone". That is false, and `SidFile.to_address` is the counterexample
    -- an offset inside the moved region names an address `dst - src` above the
    plain inversion, which is why I_Ball's effect byte reads $E557 where the
    plain formula says $9557. A disassembler that names the wrong address is
    worse than one that declines, so this had to be the same function as
    everyone else's rather than a near copy of it.

    The call is UNBOUND on purpose. `tests/test_dis6502.py` exercises this with
    a duck-typed stub that carries `load_addr` and `relocation` but defines no
    `to_address` of its own, and `sid.to_address(offset)` would narrow the
    contract to real `SidFile`s for no gain -- the method reads exactly those
    two attributes.
    """
    return SidFile.to_address(sid, offset)


def to_file_offset(sid: SidFile, address: int) -> int:
    """C64 address -> file offset, `SidFile.to_offset` exactly."""
    return sid.to_offset(address)


def decode(data: bytes, offset: int, address: int) -> Instruction:
    """One instruction. An unknown opcode is one `???` byte, not a guess."""
    op = data[offset]
    if op not in OPCODES:
        return Instruction(address, offset, bytes(data[offset:offset + 1]),
                           "???", "imp", None)
    mnemonic, mode = OPCODES[op]
    n = MODES[mode]
    raw = bytes(data[offset:offset + 1 + n])
    if len(raw) < 1 + n:                       # truncated at end of file
        return Instruction(address, offset, raw, "???", "imp", None)
    operand = None
    if n == 1:
        operand = raw[1]
    elif n == 2:
        operand = raw[1] | (raw[2] << 8)
    return Instruction(address, offset, raw, mnemonic, mode, operand)


def disassemble(data: bytes, offset: int, address: int, count: int):
    """`count` instructions from `offset`, stopping at the end of `data`."""
    out = []
    for _ in range(count):
        if offset >= len(data):
            break
        ins = decode(data, offset, address)
        out.append(ins)
        offset += ins.size
        address = (address + ins.size) & 0xFFFF
    return out


def format_lines(instructions) -> list:
    lines = []
    for ins in instructions:
        raw = " ".join(f"{b:02X}" for b in ins.raw)
        note = ins.note()
        line = f"{ins.address:04X}  {raw:<9} {ins.text()}"
        lines.append(f"{line:<34}; {note}" if note else line)
    return lines


def _number(text: str) -> int:
    """`$13C2`, `0x13c2` and `5058` all mean the same thing."""
    text = text.strip()
    if text.startswith("$"):
        return int(text[1:], 16)
    return int(text, 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="dis6502", description=__doc__.splitlines()[0])
    ap.add_argument("sid", help="a .sid file")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--at", help="start at this C64 address ($13C2)")
    where.add_argument("--offset", help="start at this file offset (0x443)")
    where.add_argument("--find", metavar="PATTERN",
                       help="disassemble at each match of a wildcard byte "
                            "pattern, `detect.py`'s syntax: 'AD ?? ?? 29 04'")
    ap.add_argument("-n", "--count", type=int, default=16,
                    help="instructions per listing (default 16)")
    ap.add_argument("-m", "--matches", type=int, default=4,
                    help="most --find matches to show (default 4)")
    args = ap.parse_args(argv)

    sid = load_sid(args.sid)
    data = sid.data

    starts = []
    if args.find:
        starts = find_all(data, args.find, limit=args.matches)
        if not starts:
            print(f"no match for {args.find!r}", file=sys.stderr)
            return 1
    elif args.at is not None:
        offset = to_file_offset(sid, _number(args.at))
        if not 0 <= offset < len(data):
            print(f"address {args.at} is outside the file", file=sys.stderr)
            return 1
        starts.append(offset)
    else:
        starts.append(_number(args.offset))

    for i, offset in enumerate(starts):
        if not 0 <= offset < len(data):
            print(f"offset {offset:#x} is outside the file", file=sys.stderr)
            return 1
        address = to_address(sid, offset)
        if i or args.find:
            print(f"# {Path(args.sid).name} @ ${address:04X} "
                  f"(offset {offset:#x})")
        print("\n".join(format_lines(
            disassemble(data, offset, address, args.count))))
        if i != len(starts) - 1:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
