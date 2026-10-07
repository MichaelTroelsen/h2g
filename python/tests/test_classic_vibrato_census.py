"""The classic vibrato's counter update, read off the disassembly of every
file the split matches -- including the three the first census could not.

Opened by lvvp-vibrato-phase, which byte-searched two spellings of the update
(`LDA dir,X / BPL / DEC ctr,X` with absolute cells, or with zero-page cells) and
left Mozart and Tarzan unresolved and Mega_Apocalypse's writers unread.
Resolved by classic-vibrato-census-unresolved (figures historical; the
byte pins below are what stays true):

* **Tarzan** is the same mechanism with mixed addressing: the counter `$49,X`
  and the bound `$4C,X` are zero page, the direction `$5500,X` is absolute.
  The first census only knew all-absolute and all-zero-page.
* **Mega_Apocalypse** was resolved by the update (all zero page: ctr `$B0,X`,
  bound `$B3,X`, dir `$B6,X`); its "zero-page writers" were byte-search hits on
  operands and tables. The one real writer is the init-time clear
  `LDX #$44 / LDA #$00 / STA $B0,X / DEX / BPL` at `$580F`, entered by
  `JMP $580F` at `$4AA0`, which the init calls (`JSR $4AA0`).
* **Mozart** is NOT the same mechanism on voices 1 and 2. Its update steps
  `$0C24,X` like the others, but its add loop is `LDY $0C24` -- absolute, no
  `,X` -- so every voice adds VOICE 0's counter. Measured in an emulator that
  agrees with siddump on all 1000 frames compared (C:/t/classic-vibrato-census-
  unresolved/emu_check.py): voice 2 (bound 5) and voice 1 (bound 2) follow
  voice 0's counter 0..3, period 7 ticks, over 31 consecutive ticks
  (mozart_period.py). The emitter models each voice with its own bound.
* The update's top turnaround comes in two families, which differ in the
  counter's period: `clamp-then-step-back` (STA ctr / DEC dir / DEC ctr) turns
  at the bound without a dwell, period `2 * bound`; `clamp-to-bound` (Mozart's
  `LDA #$FF / STA dir`, or the six `$1003` files' bare `DEC dir`) holds the
  bound for two frames, period `2 * bound + 1`. Measured counter sequences
  (ctr_seq.py): Warhawk bound 4 period 8, Las_Vegas bound 3 period 6, Tarzan
  bound 4 period 8, Mega bound 3 period 6; Mozart bound 3 period 7, Go_Go_Dash
  bound 4 period 9, Lakers_vs_Celtics bound 5 period 11.

All of it is static here (bytes and decoded instructions); the dynamic
measurements are cited, not re-run.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
from dis6502 import decode                                   # noqa: E402
from h2g.detect import VIBRATO_SHAPES, _shape_matches        # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

WRITES = {"STA", "STX", "STY", "INC", "DEC", "ASL", "LSR", "ROL", "ROR"}
BRANCH = {"BPL", "BMI", "BVC", "BVS", "BCC", "BCS", "BNE", "BEQ"}

# The files whose update holds the bound for two frames (period 2*bound + 1).
DWELL = {"Mozart", "Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
         "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines"}

# Files with a store to the counter or direction cell outside the update, in
# code reachable from init / play / the split. Each is an init-time clear.
INIT_CLEARS = {"Mega_Apocalypse", "Shockway_Rider", "Spellbound", "W_A_R"}


def _run(sid, off, n):
    out = []
    for _ in range(n):
        ins = decode(sid.data, off, sid.to_address(off))
        out.append(ins)
        off += ins.size
    return out


def _cell(ins):
    return (ins.mode, ins.operand)


def _read(path):
    """The update, the clamp, the two loops of one player, or None."""
    sid = load_sid(str(path))
    hits = [at for s in VIBRATO_SHAPES for at in _shape_matches(sid.data, s)]
    if not hits:
        return None
    at = min(hits)                       # the PHA of the split
    ins = _run(sid, at, 140)
    r = {"name": path.stem, "sid": sid, "split": sid.to_address(at)}
    k0 = next((i for i, x in enumerate(ins[:30])
               if x.mnemonic == "LDA" and x.mode in ("abx", "zpx")
               and ins[i + 1].mnemonic == "BPL"
               and ins[i + 2].mnemonic == "DEC"
               and ins[i + 2].mode in ("abx", "zpx")), None)
    assert k0 is not None, f"{path.stem}: no `LDA dir,X / BPL / DEC ctr,X`"
    ctr, dirc = _cell(ins[k0 + 2]), _cell(ins[k0])
    blk = ins[k0:k0 + 20]
    cl = next(i for i, x in enumerate(blk)
              if x.mnemonic == "CMP" and _cell(x) == ctr)
    bound = _cell(blk[cl - 1])
    t = [(x.mnemonic, _cell(x)) for x in blk[cl + 2:cl + 5]]
    if t[0] == ("STA", ctr) and t[1][0] == "LDA" and t[2] == ("STA", dirc):
        top, end = "A", cl + 5                       # clamp, dir := $FF
    elif t[0] == ("STA", ctr) and t[1] == ("DEC", dirc) and t[2] == ("DEC", ctr):
        top, end = "B", cl + 5                       # clamp, dir--, ctr--
    elif t[0] == ("STA", ctr) and t[1] == ("DEC", dirc):
        top, end = "C", cl + 4                       # clamp, dir--
    else:
        top, end = "?", cl + 4
    r.update(ctr=ctr, dir=dirc, bound=bound, top=top,
             block=(blk[0].address, blk[end - 1].address + blk[end - 1].size - 1))
    sub = next((i for i in range(len(ins) - 5)
                if [x.mnemonic for x in ins[i:i + 5]]
                == ["LSR", "TAY", "DEY", "BMI", "SEC"]), None)
    r["sub_bound"] = _cell(ins[sub - 1]) if sub is not None else None
    add = next((i for i in range(sub or 0, len(ins) - 3)
                if [x.mnemonic for x in ins[i:i + 4]]
                == ["LDY", "DEY", "BMI", "CLC"]), None)
    r["add"] = ins[add] if add is not None else None
    return r


def _reachable(sid, roots):
    """Instruction start -> Instruction, by recursive descent."""
    seen, todo = {}, list(roots)
    while todo:
        a = todo.pop()
        while a not in seen:
            try:
                off = sid.to_offset(a)
            except Exception:                         # noqa: BLE001
                break
            if not 0 <= off < len(sid.data):
                break
            ins = decode(sid.data, off, a)
            if ins.mnemonic == "???":
                break
            seen[a] = ins
            m = ins.mnemonic
            if m in BRANCH:
                todo.append(ins.target())
            elif m == "JSR":
                todo.append(ins.operand)
            elif m == "JMP":
                if ins.mode == "abs":
                    todo.append(ins.operand)
                break
            elif m in ("RTS", "RTI", "BRK"):
                break
            a = (a + ins.size) & 0xFFFF
    return seen


def _writers(r):
    """Stores to the counter / direction cells (X = voice 0..2) in reachable
    code, outside the update block. Decoded instructions only: a byte search
    also hits operands and tables, which is how Mega_Apocalypse's first census
    got ten false writers."""
    sid = r["sid"]
    code = _reachable(sid, [sid.init_addr, sid.play_addr, r["split"]])
    lo, hi = r["block"]
    out = []
    for a, x in sorted(code.items()):
        if x.mnemonic not in WRITES or lo <= a <= hi:
            continue
        for mode, op in (r["ctr"], r["dir"]):
            direct = "abs" if mode == "abx" else "zp"
            indexed = (mode, "aby" if mode == "abx" else "zpy")
            if (x.mode == direct and x.operand == op) or \
                    (x.mode in indexed and op - 2 <= x.operand <= op):
                out.append((a, x))
    return out, code


def _all():
    rows = []
    for path in sorted(CORPUS.glob("*.sid")):
        r = _read(path)
        if r is not None:
            rows.append(r)
    return rows


def _bytes_at(sid, addr, n):
    off = sid.to_offset(addr)
    return bytes(sid.data[off:off + n])


@needs_corpus
def test_every_update_is_read_off_the_disassembly():
    rows = _all()
    names = {r["name"] for r in rows}
    assert len(rows) >= 56
    assert {"Mozart", "Tarzan", "Mega_Apocalypse"} <= names
    for r in rows:
        assert r["top"] in "ABC", r["name"]
        assert r["sub_bound"] == r["bound"], r["name"]     # sub loop reads the bound
        assert r["add"] is not None, r["name"]


@needs_corpus
def test_the_add_loop_reads_the_voices_own_counter_except_in_mozart():
    off = [r["name"] for r in _all() if _cell(r["add"]) != r["ctr"]]
    assert off == ["Mozart"]


@needs_corpus
def test_mozart_add_loop_loads_voice_zero_counter_whatever_the_voice():
    sid = load_sid(str(CORPUS / "Mozart.sid"))
    r = _read(CORPUS / "Mozart.sid")
    assert r["ctr"] == ("abx", 0x0C24) and r["bound"] == ("abx", 0x0C30)
    assert r["dir"] == ("abx", 0x0C2D) and r["top"] == "A"
    # the update steps $0C24,X ...
    assert _bytes_at(sid, 0x09B2, 12) == bytes(
        [0xBD, 0x2D, 0x0C, 0x10, 0x0C, 0xDE, 0x24, 0x0C, 0xD0, 0x1A, 0xA9, 0x00])
    # ... the subtract loop reads the voice's own bound ...
    assert _bytes_at(sid, 0x0A03, 6) == bytes([0xBD, 0x30, 0x0C, 0x4A, 0xA8, 0x88])
    # ... and the add loop is LDY $0C24 (AC, absolute): no `,X`.
    assert _bytes_at(sid, 0x0A2A, 7) == bytes(
        [0xAC, 0x24, 0x0C, 0x88, 0x30, 0x16, 0x18])
    assert r["add"].address == 0x0A2A and r["add"].mode == "abs"


@needs_corpus
def test_tarzan_counter_is_zero_page_and_its_direction_absolute():
    sid = load_sid(str(CORPUS / "Tarzan.sid"))
    r = _read(CORPUS / "Tarzan.sid")
    assert r["ctr"] == ("zpx", 0x49) and r["bound"] == ("zpx", 0x4C)
    assert r["dir"] == ("abx", 0x5500) and r["top"] == "B"
    # LDA $5500,X / BPL / DEC $49,X / BNE / INC $5500,X / BPL / INC $49,X /
    # LDA $4C,X / CMP $49,X / BCS / STA $49,X / DEC $5500,X / DEC $49,X
    assert _bytes_at(sid, 0x56F6, 29) == bytes([
        0xBD, 0x00, 0x55, 0x10, 0x09, 0xD6, 0x49, 0xD0, 0x14, 0xFE, 0x00, 0x55,
        0x10, 0x0F, 0xF6, 0x49, 0xB5, 0x4C, 0xD5, 0x49, 0xB0, 0x07, 0x95, 0x49,
        0xDE, 0x00, 0x55, 0xD6, 0x49])
    # the add loop is LDY $49,X / DEY / BMI / CLC
    assert _bytes_at(sid, 0x5766, 6) == bytes([0xB4, 0x49, 0x88, 0x30, 0x10, 0x18])
    assert _cell(r["add"]) == r["ctr"]


@needs_corpus
def test_mega_apocalypse_counter_is_cleared_only_by_the_init_block():
    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    r = _read(CORPUS / "Mega_Apocalypse.sid")
    assert r["ctr"] == ("zpx", 0xB0) and r["bound"] == ("zpx", 0xB3)
    assert r["dir"] == ("zpx", 0xB6) and r["top"] == "B"
    assert _bytes_at(sid, 0x4C4A, 12) == bytes(
        [0xB5, 0xB6, 0x10, 0x08, 0xD6, 0xB0, 0xD0, 0x12, 0xF6, 0xB6, 0x10, 0x0E])
    assert _bytes_at(sid, 0x4CB4, 4) == bytes([0xB4, 0xB0, 0x88, 0x30])   # LDY $B0,X
    # init ($5822) -> JSR $4AA0 -> JMP $580F: LDX #$44 / LDA #0 / STA $B0,X ...
    assert sid.init_addr == 0x5822
    assert _bytes_at(sid, 0x585F, 3) == bytes([0x20, 0xA0, 0x4A])
    assert _bytes_at(sid, 0x4AA0, 3) == bytes([0x4C, 0x0F, 0x58])
    assert _bytes_at(sid, 0x580F, 9) == bytes(
        [0xA2, 0x44, 0xA9, 0x00, 0x95, 0xB0, 0xCA, 0x10, 0xFB])
    writers, _ = _writers(r)
    assert [a for a, _ in writers] == [0x5813]


@needs_corpus
def test_only_four_files_store_to_the_counter_outside_the_update_and_all_clear():
    seen = {}
    for r in _all():
        writers, code = _writers(r)
        if writers:
            seen[r["name"]] = (r, writers, code)
    assert set(seen) == INIT_CLEARS
    for name, (r, writers, code) in seen.items():
        for a, x in writers:
            # a store of zero: LDA #$00 or LDX #$00 among the eight before it
            # (W_A_R stores six cells from one `LDX #$00`)
            prev = [code[b] for b in sorted(code) if b < a][-8:]
            assert any(p.mnemonic in ("LDA", "LDX") and p.mode == "imm"
                       and p.operand == 0 for p in prev), (name, hex(a))


@needs_corpus
def test_two_turnaround_families_differ_in_whether_the_bound_is_held():
    dwell = {r["name"] for r in _all() if r["top"] in "AC"}
    assert dwell == DWELL
