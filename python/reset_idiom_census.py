"""Census of the reset idiom `LDA #imm / STA cell,X` on a voice's instrument cell.

Mega_Apocalypse's player starts every voice on instrument 17: its init loop
(`4AC6 LDA #$11 / 4AC8 STA $C9,X`) writes the per-voice instrument index, and
record 17 is eight zero bytes. That is a *silent power-on instrument*, so a
converter that emits no instrument for it is right -- and a "missing
instrument" report against the same shape elsewhere can be closed or opened by
one question: which corpus files carry the idiom, what index does each reset
to, and is that record all-zero?

    python reset_idiom_census.py <sid_dir>            # one line per idiom site
    python reset_idiom_census.py <sid_dir> --all      # also files with none

The cell is found from the player's own LOAD, not from a guess at an address:
`LDA cell,X` (zero page or absolute), up to one store, three or four `ASL A`,
`TAY`/`TAX`, then a table read whose operand lands inside the instrument table
`detect.detect` located. That names the per-voice instrument array in the
player's own spelling -- `INSTRUMENT_INDEX_SHAPE` reaches only the absolute
`LDA abs,X / STX / ASL x3 / TAX / LDA abs,X` spelling and misses Mega's
zero-page one, which is why that shape alone cannot answer this.

A store site is the idiom when an `LDA #imm` reaches `STA cell,X` through
instructions that leave A alone (`STRICT` when it is the very next one). Sites
whose stored value is not a literal (the pattern reader's `STA cell,X`) are
the player WRITING A NOTATED INSTRUMENT, not a power-on reset, and are counted
separately.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dis6502                                              # noqa: E402
from h2g import detect as D, sidfile                        # noqa: E402

# Opcodes that overwrite A, so a literal loaded before them no longer reaches
# a later store. Anything that transfers control ends the walk as well: past a
# branch the next instruction is not the one that runs.
WRITES_A = {"LDA", "TXA", "TYA", "PLA", "ADC", "SBC", "AND", "ORA", "EOR",
            "ASL", "LSR", "ROL", "ROR"}
ENDS_WALK = {"JSR", "JMP", "RTS", "RTI", "BRK", "BPL", "BMI", "BVC", "BVS",
             "BCC", "BCS", "BNE", "BEQ", "???"}
WALK_LIMIT = 6              # instructions between the LDA #imm and the STA
LOAD_TO_TABLE_WINDOW = 24   # bytes from the TAY/TAX to the table read
TABLE_SLACK = 1             # one record past instr_used still counts as table

Cell = Tuple[str, int]      # ("zp", $C9) or ("abs", $1535)


@dataclass
class Site:
    cell: Cell
    at: int                 # C64 address of the `LDA #imm`
    store_at: int           # C64 address of the `STA cell,X`
    imm: int
    distance: int           # instructions between the LDA and the STA (0 = next)
    record_addr: int
    record: Optional[bytes]     # None when the record lies past the image

    @property
    def strict(self) -> bool:
        return self.distance == 0

    @property
    def all_zero(self) -> Optional[bool]:
        return None if self.record is None else not any(self.record)


@dataclass
class Census:
    name: str
    refused: bool = False
    instr_addr: int = -1
    stride: int = 0
    instr_used: int = 0
    cells: List[Cell] = field(default_factory=list)
    sites: List[Site] = field(default_factory=list)
    other_writes: int = 0   # `STA cell,X` not reached by a literal


def _cell_text(cell: Cell) -> str:
    return f"${cell[1]:02X}" if cell[0] == "zp" else f"${cell[1]:04X}"


def find_cells(sid: sidfile.SidFile, instr_addr: int, stride: int,
               used: int) -> List[Cell]:
    """Per-voice instrument cells, named by the load that feeds the table read."""
    data = sid.data
    lo = instr_addr
    hi = instr_addr + stride * (used + TABLE_SLACK)
    shifts = {stride.bit_length() - 1} if stride in (8, 16) else {3, 4}
    found: Dict[Cell, None] = {}
    n = len(data)
    for k in range(n - 4):
        op = data[k]
        if op == 0xB5:                              # LDA zp,X
            cell, nxt = ("zp", data[k + 1]), k + 2
        elif op == 0xBD and k + 2 < n:              # LDA abs,X
            cell, nxt = ("abs", data[k + 1] | data[k + 2] << 8), k + 3
        else:
            continue
        # At most one store between the load and the shifts (the player keeps
        # X, or the index, in a scratch cell while it works).
        for first in (nxt, nxt + (2 if data[nxt] in (0x85, 0x86, 0x84) else
                                  3 if data[nxt] in (0x8D, 0x8E, 0x8C) else 99)):
            if first >= n:
                continue
            j = first
            while j < n and data[j] == 0x0A:
                j += 1
            if j - first not in shifts or j >= n or data[j] not in (0xA8, 0xAA):
                continue
            end = min(n - 2, j + 1 + LOAD_TO_TABLE_WINDOW)
            m = j + 1
            while m < end:
                ins = dis6502.decode(data, m, 0)
                if ins.mnemonic == "???":
                    break
                if ins.mode in ("aby", "abx") and ins.mnemonic == "LDA" \
                        and lo <= ins.operand < hi:
                    found.setdefault(cell, None)
                    break
                if ins.mnemonic in ENDS_WALK:
                    break
                m += ins.size
            if cell in found:
                break
    return list(found)


def find_sites(sid: sidfile.SidFile, cells: List[Cell], instr_addr: int,
               stride: int) -> Tuple[List[Site], int]:
    data = sid.data
    sites: List[Site] = []
    reached: Set[int] = set()       # offsets of STA cell,X reached by a literal
    cellset = set(cells)
    for p in range(len(data) - 1):
        if data[p] != 0xA9:
            continue
        imm = data[p + 1]
        q = p + 2
        for dist in range(WALK_LIMIT):
            if q >= len(data):
                break
            ins = dis6502.decode(data, q, 0)
            if ins.mnemonic == "STA" and (
                    (ins.mode == "zpx" and ("zp", ins.operand) in cellset) or
                    (ins.mode in ("abx", "aby")
                     and ("abs", ins.operand) in cellset)):
                cell = (("zp", ins.operand) if ins.mode == "zpx"
                        else ("abs", ins.operand))
                rec_addr = instr_addr + imm * stride
                off = sid.to_offset(rec_addr)
                rec = (bytes(data[off:off + stride])
                       if 0 <= off and off + stride <= len(data) else None)
                sites.append(Site(cell, sid.to_address(p),
                                  sid.to_address(q), imm, dist, rec_addr, rec))
                reached.add(q)
                break
            if ins.mnemonic in WRITES_A or ins.mnemonic in ENDS_WALK:
                break
            q += ins.size
    other = 0
    for k in range(len(data) - 2):
        if data[k] == 0x95 and ("zp", data[k + 1]) in cellset and k not in reached:
            other += 1
        elif data[k] in (0x9D, 0x99) and ("abs", data[k + 1] | data[k + 2] << 8) \
                in cellset and k not in reached:
            other += 1
    return sites, other


def census_file(path: Path) -> Census:
    c = Census(path.stem)
    sid = sidfile.load_sid(str(path))
    det = D.detect(sid, lambda s: None)
    if det.instr_start < 0 or det.instr_used <= 0:
        c.refused = True
        return c
    c.instr_addr = sid.to_address(det.instr_start)
    c.stride, c.instr_used = det.instr_stride, det.instr_used
    c.cells = find_cells(sid, c.instr_addr, c.stride, c.instr_used)
    c.sites, c.other_writes = find_sites(sid, c.cells, c.instr_addr, c.stride)
    return c


# --- runtime confirmation ------------------------------------------------
# A literal reaching `STA cell,X` is a statement about the bytes. Whether the
# routine holding it RUNS at power-on is a statement about the player, and the
# two come apart: most of these stores sit in a state-flag-guarded reset block
# (`BIT flag / BMI / BVC`) that init arms and the first play call executes, so
# reading the cell straight after init sees the OLD value and reading it three
# frames later sees a pattern-set one. The only direct evidence is to watch the
# store execute.
SENTINEL = 0x0300
INIT_STEPS = 1_500_000
FRAME_STEPS = 400_000
POWER_ON_FRAMES = 10
IRQ_PERIOD = 5000           # main-thread instructions between interrupts
KERNAL_EXIT = {0xEA31, 0xEA7E, 0xEA81}   # where a $0314 handler chains on


@dataclass
class Hit:
    frame: int      # -1 = inside init, otherwise the 0-based play call
    x: int
    a: int


def trace_sites(path: Path, sites: List[Site],
                frames: int = POWER_ON_FRAMES) -> Dict[int, List[Hit]]:
    """{store address: every execution} over subtune 0's init and `frames` frames.

    py65, subtune 0 (A=0). A frame is the header's play routine, or -- for a
    play address of 0, the RSID shape -- an interrupt through the vector the
    init installed ($FFFE, else the KERNAL's $0314), fired every
    IRQ_PERIOD main-thread instructions while init is still running (only if
    it has cleared I) and back to back once it has returned. An RSID init
    that never returns because it idles or waits on a flag its own interrupt
    clears (Ricochet's `JMP *`, I_Ball's `BNE` poll) is therefore driven the
    way the machine would drive it. Hits inside init have frame -1.
    """
    from py65.devices.mpu6502 import MPU
    sid = sidfile.load_sid(str(path))
    m = MPU()
    mem = m.memory
    for i, b in enumerate(sid.data[sidfile.HLEN - 1:]):
        if 0 <= sid.load_addr + i < 0x10000:
            mem[sid.load_addr + i] = b
    watch = {s.store_at for s in sites}
    hits: Dict[int, List[Hit]] = {a: [] for a in watch}

    def vector() -> int:
        return (mem[0xFFFE] | mem[0xFFFF] << 8) or (mem[0x314] | mem[0x315] << 8)

    def irq(frame: int) -> None:
        vec = vector()
        if not vec:
            return
        sp, pc, p = m.sp, m.pc, m.p
        m.stPush(SENTINEL >> 8)
        m.stPush(SENTINEL & 0xFF)
        m.stPush(p & ~0x10)
        m.p |= 0x04
        m.pc = vec
        n = 0
        exits = KERNAL_EXIT if not (mem[0xFFFE] | mem[0xFFFF] << 8) else ()
        while m.pc != SENTINEL and m.pc not in exits and n < FRAME_STEPS:
            if m.pc in watch:
                hits[m.pc].append(Hit(frame, m.x, m.a))
            m.step()
            n += 1
        # Back to what the main thread was doing, exactly as RTI would.
        m.sp, m.pc, m.p = sp, pc, p

    def push_return() -> None:
        m.stPush(((SENTINEL - 1) >> 8) & 0xFF)
        m.stPush((SENTINEL - 1) & 0xFF)

    m.sp = 0xFF
    push_return()
    m.pc, m.a, m.x, m.y = sid.init_addr, 0, 0, 0
    frame = 0
    main_steps = 0
    # The main thread: init, then (RSID only) whatever it idles in. Interrupts
    # that land while init is still running are labelled -1 like init's own
    # hits and do not use up the frames below.
    while m.pc != SENTINEL and main_steps < INIT_STEPS:
        if m.pc in watch:
            hits[m.pc].append(Hit(-1, m.x, m.a))
        before = m.pc
        m.step()
        main_steps += 1
        if sid.play_addr:
            continue
        if main_steps % IRQ_PERIOD == 0 and not m.p & 0x04:
            irq(-1)
        elif m.pc == before:                # `JMP *`: the idle loop
            break
    if m.pc != SENTINEL and sid.play_addr:
        return hits                         # init never came back
    while frame < frames:
        if sid.play_addr:
            m.sp = 0xFF
            push_return()
            m.pc = sid.play_addr
            n = 0
            while m.pc != SENTINEL and n < FRAME_STEPS:
                if m.pc in watch:
                    hits[m.pc].append(Hit(frame, m.x, m.a))
                m.step()
                n += 1
            if m.pc != SENTINEL:
                break
        else:
            if not vector():
                break
            irq(frame)
        frame += 1
    return hits


def describe(c: Census) -> List[str]:
    if c.refused:
        return [f"{c.name}: no instrument table detected"]
    head = (f"{c.name}: table ${c.instr_addr:04X} stride {c.stride} "
            f"used {c.instr_used}; cells "
            + (", ".join(_cell_text(x) for x in c.cells) or "none found"))
    lines = [head]
    for s in c.sites:
        zero = {None: "past image", True: "ALL-ZERO", False: "non-zero"}[s.all_zero]
        lines.append(
            f"    LDA #${s.imm:02X} @${s.at:04X} -> STA {_cell_text(s.cell)},X "
            f"@${s.store_at:04X}  {'strict' if s.strict else f'+{s.distance}'}"
            f"  record {s.imm} @${s.record_addr:04X} {zero}"
            + ("" if s.imm < c.instr_used else
               f"  (beyond the {c.instr_used} counted records)"))
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sid_dir")
    ap.add_argument("--all", action="store_true", help="list files with no site")
    a = ap.parse_args(argv)
    files = sorted(Path(a.sid_dir).glob("*.sid"))
    hits = nocell = refused = 0
    for f in files:
        try:
            c = census_file(f)
        except Exception as e:                      # noqa: BLE001
            print(f"{f.stem}: ERROR {type(e).__name__}: {e}")
            continue
        refused += c.refused
        nocell += (not c.refused and not c.cells)
        if c.sites:
            hits += 1
        if c.sites or a.all:
            print("\n".join(describe(c)))
    print(f"\nfiles {len(files)}, no table {refused}, table but no cell "
          f"located {nocell}, with an idiom site {hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
