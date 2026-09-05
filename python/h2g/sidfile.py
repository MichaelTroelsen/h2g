"""PSID/RSID header parsing.

Mirrors the header reads in loadfile() (h2g.frm lines 240-298). The tool
does not parse the PSID `dataOffset` field; it hardcodes a 0x7C-byte (v2NG)
header plus a 2-byte embedded load address, i.e. HLEN = 0x7F. This matches
the original VB behavior exactly and is preserved here rather than "fixed",
since the goal is a faithful base to redevelop from.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Optional

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


# --- init-time writes -------------------------------------------------------
#
# Some players do not store their table addresses in the table-read
# instructions at all: the operands on disk are placeholders, and the init
# routine writes the real addresses over them before the first play call.
# Devils Galop is the corpus's one example. Its player reads
#
#     1359  BD 95 17  LDA $1795,X      ; orderlist pointer lo, per voice
#     135E  BD 96 17  LDA $1796,X      ;                    hi
#     138C  B9 97 17  LDA $1797,Y      ; pattern pointer lo
#     1391  B9 98 17  LDA $1798,Y      ;                 hi
#
# and $1790-$1798 is nine bytes of zeroes -- nothing is ever stored there, so
# read literally every one of those pointers is $0000. The addresses are real
# but they arrive from the init routine at $18B3, which writes each operand
# byte individually:
#
#     18B3  A9 1E     LDA #$1E
#     18B5  8D 5A 13  STA $135A        ; the lo operand byte of the LDA at $1359
#     18B8  A9 0A     LDA #$0A
#     18BA  8D 5B 13  STA $135B        ; ...and its hi byte -> $0A1E
#     18BD  8D 60 13  STA $1360        ; one LDA can feed several stores
#     ...
#
# leaving orderlists at $0A1E/$0A21 and patterns at $0A24/$0A50. That last
# pair is 44 apart, so the file has 44 patterns where reading the placeholders
# gives `$1798 - $1797 - 1` = none, which is why it converted to nothing.
#
# The same routine ends with a block copy that moves the authored instrument
# records into the address the player reads them from:
#
#     18E7  A2 00     LDX #$00
#     18E9  BD 3B 18  LDA $183B,X
#     18EC  9D 99 17  STA $1799,X
#     18EF  E8        INX
#     18F0  E0 78     CPX #$78         ; 15 records x 8 bytes
#     18F2  D0 F5     BNE $18E9
#
# On disk $1799 holds a *different*, stale set of records, so without the copy
# the tune converts with the wrong instruments -- a quiet fidelity loss rather
# than a failure, and the reason this is applied alongside the operand stores
# rather than separately.
#
# Byte length of each opcode, indexed by opcode; 0 marks an undocumented one,
# which stops the walk rather than risk desynchronising it.
_OPLEN = (
    "12000220121003302200022013000330"
    "32002220121033302200022013000330"
    "12000220121033302200022013000330"
    "12000220121033302200022013000330"
    "02002220101033302200222013100300"
    "22202220121033302200222013103330"
    "22002220121033302200022013000330"
    "22002220121033302200022013000330"
)

INIT_WALK_LIMIT = 256   # instructions, before the walk gives up

# LDX #$00 / LDA src,X / STA dst,X / INX / CPX #len / BNE -- an indexed block
# copy, matched as a unit during the walk so that it is provably part of init
# rather than merely present somewhere in the file.
_BLOCK_COPY = (0xA2, 0xBD, 0x9D, 0xE8, 0xE0, 0xD0)


def find_init_writes(data: bytes, init_addr: int, load_addr: int) -> Dict[int, int]:
    """Bytes the init routine writes into the loaded image, as offset -> value.

    Walks from the PSID init address, following a leading chain of `JMP`s (the
    near-universal `init: JMP realinit` indirection) and then running straight
    through until the routine branches away. `JSR`s are stepped over rather
    than followed, so writes a helper makes are missed -- an under-read, which
    costs a rescue at worst and can never invent one.
    """
    def offset(addr: int) -> int:
        return addr - load_addr + HLEN - 1

    writes: Dict[int, int] = {}
    off = offset(init_addr)
    seen = set()
    # Leading JMP chain: taken only before any other instruction has run, so a
    # `JMP` reached mid-routine ends the walk instead of diverting it into the
    # play code, where an `LDA #imm` / `STA abs` pair is ordinary per-frame
    # state rather than a patch.
    while 0 <= off < len(data) and data[off] == 0x4C and off not in seen:
        seen.add(off)
        off = offset(data[off + 2] * 256 + data[off + 1])

    acc: Optional[int] = None
    for _ in range(INIT_WALK_LIMIT):
        if not 0 <= off < len(data):
            break
        op = data[off]
        n = int(_OPLEN[op])
        if n == 0 or off + n > len(data):
            break

        if op == 0xA9:                                    # LDA #imm
            acc = data[off + 1]
        elif op == 0x8D and acc is not None:              # STA abs
            target = offset(data[off + 2] * 256 + data[off + 1])
            if 0 <= target < len(data):
                writes[target] = acc
        elif op in (0xAD, 0xA5, 0xB5, 0xBD, 0xB9, 0xA1, 0xB1, 0x68, 0x8A, 0x98):
            acc = None                                    # A reloaded from elsewhere
        elif op in (0x60, 0x40, 0x00):                    # RTS / RTI / BRK
            break
        elif op == 0x4C:                                  # JMP away: end of init
            break

        if op == _BLOCK_COPY[0]:
            src, dst, length = _read_block_copy(data, off)
            if length:
                s, d = offset(src), offset(dst)
                if 0 <= s and s + length <= len(data) and 0 <= d and d + length <= len(data):
                    for k in range(length):
                        writes[d + k] = data[s + k]

        off += n

    return writes


def _read_block_copy(data: bytes, off: int):
    """(src, dst, length) of the indexed copy loop at `off`, or (0, 0, 0)."""
    shape = [(off, 2), (off + 2, 3), (off + 5, 3), (off + 8, 1), (off + 9, 2), (off + 11, 2)]
    if off + 13 > len(data):
        return 0, 0, 0
    for (k, _), want in zip(shape, _BLOCK_COPY):
        if data[k] != want:
            return 0, 0, 0
    if data[off + 1] != 0x00:          # copies that do not start at index 0
        return 0, 0, 0
    src = data[off + 4] * 256 + data[off + 3]
    dst = data[off + 7] * 256 + data[off + 6]
    return src, dst, data[off + 10]


# --------------------------------------------------------------------------
# the player's own note frequency table
# --------------------------------------------------------------------------
# Goattracker's freqtbl[0] (gplay.c:9/23), the frequency its lowest note
# FIRSTNOTE ($60) plays. Every Hubbard player carries the equivalent table of
# its own, and the two do not have to agree -- neither on where the note index
# starts nor on what pitch it is tuned to. Both differences are measurable from
# the file, and they mean opposite things:
#
#   * an index shift is a *converter* concern -- Skate or Die's table has a
#     $0000 dummy at entry 0, so its note byte n means Goattracker's note n-1,
#     and emitting $60+n plays the whole tune a semitone sharp;
#   * a tuning offset is not. Four corpus files (Kings of the Beach intro, One
#     on One, Powerplay Hockey, Rock Tells the Tale) carry tables computed for
#     the NTSC C64's faster clock, so every register value is 0.65 semitones
#     below the PAL equivalent. The notes are right; the whole tune sounds a
#     little flat, and nothing in a Goattracker file can express that. It
#     matters only to a harness that names notes from register values.
GT_FREQ0 = 0x0117

# How far off the semitone grid a table may sit and still be read as an index
# shift rather than a tuning. The two populations are not close: a shifted
# table is within 7 cents of the grid, and the NTSC tables sit 65 cents off it
# (985248/1022727 clocks = 0.647 semitones).
_GRID_TOLERANCE = 0.15


@dataclass(frozen=True)
class FreqTable:
    """A player's note frequency table, placed against Goattracker's.

    `shift` is what a note byte must be offset by to name the same pitch in
    Goattracker (-1 for a table whose entry 0 is an unused $0000), and
    `detune` is what is left over: the semitones the table sits below
    Goattracker's tuning, which no note number can express.

    `ambiguous` says the file offered more than one validated table and they
    do **not** agree about the tuning, with nothing given to choose between
    them -- so `detune` here is one of two answers rather than the file's.

    `length` and `run` are **not** the same number, and the difference is
    the top of the table. `run` is what `_table_run` validated -- entries
    that really do rise a semitone at a time -- and `length` is how many
    entries the table has, which is one more wherever the last one is a
    clamp the 16-bit frequency registers forced (see `_grid_edge_clamp`).
    Read `length` to bound an index into the table, and `run` to compare
    two candidate tables with each other: the tie-break is about which
    reading of the file is better evidenced, and a clamped entry is
    evidence of nothing.
    """
    addr: int          # C64 address of entry 0
    start: int         # first entry with a frequency in it
    length: int        # entries in the table
    shift: int
    detune: float
    ambiguous: bool = False
    run: int = 0       # entries in the validated semitone run


def _semitones(freq: float) -> float:
    """Goattracker note index (fractional) for a SID frequency register value."""
    from math import log2
    return 12 * log2(freq / GT_FREQ0)


def _table_run(vals, start: int) -> int:
    """How many entries from `start` rise by one semitone each, +-14 cents."""
    from math import log2
    n, i = 0, start
    while i + 1 < len(vals) and vals[i] > 0 and vals[i + 1] > vals[i]:
        if abs(1200 * log2(vals[i + 1] / vals[i]) - 100) > 14:
            break
        n += 1
        i += 1
    return n + 1 if n else 0


# One semitone as a frequency ratio. `_grid_edge_clamp` is the only user, and
# it needs the ratio rather than the logarithm `_table_run` works in.
_SEMITONE = 2.0 ** (1.0 / 12.0)


def _grid_edge_clamp(vals, i: int) -> bool:
    """Is `vals[i]` a table entry the 16-bit frequency registers cut short?

    The top of a note table is not a semitone above the entry below it,
    because it cannot be. Entry 94 of the commoner PAL table is `$F820` =
    63520; a semitone above that is 67297, which does not fit in
    `$D400`/`$D401`, so entry 95 is written as far up as the register goes.

    **It has two spellings, and a rule about the top of a note table must
    expect both.** Of the 97 candidate tables this corpus offers, 88 carry a
    clamped entry 95: `$FD2E` in 82 of them and a flat `$FFFF` in the other
    six -- Go_Go_Dash, Lakers_vs_Celtics, Lion_Heart, Pacific_Coast,
    Radio_ACE and Sun_Never_Shines. The six are not the same table with a
    different top: they are a second, independently rounded PAL table that
    differs from the first at **64 of its 96 entries** by one LSB, and their
    entry 94 is `$F80F` = 63503, not `$F820`. So the clamp is 34.91 cents in
    one family and 54.53 in the other, and any rule keyed on either of those
    numbers -- the value `$FD2E`, the value `$F820`, a cents threshold --
    reads one family and silently misses the other. The test below is keyed
    on none of them: it asks whether a full semitone above the *predecessor*
    would overflow 16 bits, which is true at 67297 and at 67279 alike and
    false everywhere below the top of a table.

    `_table_run` is a *validation*, so it stops at that entry, and the run it
    returns is one short of the table it validated.
    `goatwriter._freq_table_note` -- rightly -- refuses an index past the
    table's end, so five records were declined for naming an entry that is
    really there: Tarzan's 0 and 16 and Delta_Mix-E-Load_loader's 5 through
    effect bit `$08`'s alternate note, and Ricochet's 0 and 20 through bit
    `$40`'s fixed attack.

    **Three files' converted bytes move, not two.** The plan this came from
    said the byte-hash would name Tarzan and Delta_Mix-E-Load_loader only,
    and that cannot hold beside its own next sentence: both mechanisms pass
    through the one `index < table.length` gate in
    `goatwriter._freq_table_note`, so fixing bit `$08` fixes bit `$40` with
    it, and Ricochet is the necessary consequence rather than a leak. The
    clause is restated here rather than met.

    The test is the *cause*, not the symptom: an entry qualifies only where a
    full semitone above its predecessor would overflow 16 bits, which nothing
    below the top of a table can do. So this widens the reported length by at
    most one entry, at one place in one table, and `_table_run` itself is
    left alone -- deliberately, because the same function serves Skate or Die
    intro's `$0000` at entry 0, and that is a `shift` rather than a longer
    run. Relaxing the semitone test would blur the two.

    **And the widening stops here, because the next index up is not a clamp
    and cannot be one.** 11 corpus records still name index **99** against a
    96-entry table and are refused by `goatwriter._freq_table_note`; that
    refusal is correct, and the reason is in the players' own bytes rather
    than in any threshold. Three things settle it:

    * **What the routine reads.** Bit `$08`'s block (`NOTE_ALT_SHAPE`) ends
      `ASL / TAY / LDA freqtbl,Y`, an 8-bit shift with no mask and no bound,
      so index 99 loads `freqtbl+198/+199` -- six bytes past a 192-byte
      table. What is there is not a note and is not the same thing twice:
      `$1517` Bangkok_Knights, `$0000` Chain_Reaction, `$0000`
      Delta_Mix-E-Load_loader, `$0E12` Dragons_Lair_Part_II, `$0002`
      Knucklebusters, `$0002` Nineteen, `$0C08` Sanxion, `$1309`
      Thundercats, `$1300` W_A_R, `$1C03` W_A_R_Preview, `$1302` Zoolook.
      Two are a silent DC pitch and two are subsonic. In W_A_R the sixteen
      bytes from `$E81E+192` read `00 07 0e 00 00 00 00 13 13 13 12 12 12
      1f 1f 1f` -- per-voice triples following the table, and index 99
      straddles the boundary between the `00` run and the `13` triple. No
      semitone relation to entry 95 exists or could: `$FD2E` is already the
      register ceiling, which is the whole point of the clamp above.
    * **Whose record it is.** All 11 are record **26**, and the record is
      byte-identical in every one of the 11 files: `80 08 41 7E 08 00 30 0A`.
      Boilerplate, carried from tune to tune. Every *other* bit-`$08` record
      in the corpus names an index in 32..95 -- in range, in run.
    * **Whether it is played.** At each file's shipped presets, 10 of the 11
      emit **zero** pattern rows naming that instrument. W_A_R emits exactly
      one: pattern 142 row 0, the entry row of orderlist track 21 = subtune
      7 voice 0 of its 8 emitted subtunes, followed by 126 rests. Its PSID
      `startSong` is 1, so the traced subtune is 0 and no `FIDELITY.md`
      dimension can see that row either.

    So the cells are dead, and nothing is emitted for them. `_table_run`,
    `_grid_edge_clamp` and `FreqTable.length` all stay as they are.

    The four *other* out-of-range indices are a different question and are
    **not** answered here: ACE_II record 11 (206), Powerplay Hockey record 3
    (141) and Trans-Atlantic record 15 (174) / 18 (132) all come through bit
    `$40`, all are >= 128, and the same 8-bit `ASL` wraps them -- `2*idx &
    $FF` lands on entries 78, 13, 46 and 4 respectively, every one inside the
    validated run. Whether those bytes are meant as note indices at all is
    open (the same cell is a wave-program pointer low byte); the wrap is in
    `goatwriter._freq_table_note`, not in this module.
    """
    if not 0 < i < len(vals):
        return False
    prev = vals[i - 1]
    if prev <= 0 or prev * _SEMITONE <= 0xFFFF:
        return False
    return prev < vals[i] <= 0xFFFF


def _freq_table_sites(data: bytes):
    """Addresses a player looks a note frequency up in.

    Three idioms cover the corpus, all of them "index the note, fetch the
    frequency": `ASL / TAY / LDA tbl,Y` and `ASL / TAX / LDA tbl,X` for the
    lo,hi,lo,hi tables, and a bare `TAY / LDA tbl,Y` for the split ones. The
    candidates are only candidates -- each is confirmed by reading the table
    and checking it really does rise a semitone at a time.
    """
    for i in range(len(data) - 5):
        b = data[i]
        if b == 0x0A and data[i + 1] == 0xA8 and data[i + 2] == 0xB9:
            yield data[i + 3] | (data[i + 4] << 8)
        elif b == 0x0A and data[i + 1] == 0xAA and data[i + 2] == 0xBD:
            yield data[i + 3] | (data[i + 4] << 8)
        elif b == 0xA8 and data[i + 1] == 0xB9 and (i == 0 or data[i - 1] != 0x0A):
            yield data[i + 2] | (data[i + 3] << 8)


def find_freq_table(sid: "SidFile", near: Optional[int] = None) -> Optional[FreqTable]:
    """The player's note frequency table, or None if no candidate validates.

    Six corpus files hide their lookup behind an idiom this does not know; a
    file with no table found keeps the default mapping, which is what it had
    before this existed.

    **A file can carry two players, and then "the file's table" is not a
    thing.** Powerplay Hockey has one at `$3A36` driving its nine game cues
    and one at `$4895` driving the tune, and they are tuned 0.63 semitones
    apart -- the tune's is NTSC, the cues' is not. The rule used to be "the
    longest validated run wins", which separates those two by **one entry**
    (96 against 95): a coin flip standing in for a choice. `near` is a byte
    offset into `data` -- the caller's own player, its pattern pointers for
    preference, the rule `_nearest_table` already uses -- and the table
    nearest it wins. Without `near` the longest run still wins, so a caller
    that has no engine to point at behaves exactly as before.

    Two guards on top, for what is left when the candidates disagree:

    * on the **shift**, neither is applied, because a wrong shift transposes a
      whole tune and no shift merely leaves it as it was;
    * on the **detune** there is no such null action -- naming a tune on the
      wrong tuning and naming it on none are both wrong, and by the same 0.65
      semitones -- so the answer is reported rather than suppressed. An
      `ambiguous` table is one whose `detune` was picked by a rule that had
      nothing to go on, and a caller applying it (siddump's `-c`, say) is
      entitled to know that. Passing `near` resolves the choice and clears it.
    """
    data = sid.data
    cands: list[FreqTable] = []
    seen = set()
    for addr in _freq_table_sites(data):
        if addr in seen:
            continue
        seen.add(addr)
        off = sid.to_offset(addr)
        if not 0 <= off < len(data) - 8:
            continue
        n = min(100, (len(data) - off) // 2)
        vals = [data[off + 2 * i] | (data[off + 2 * i + 1] << 8) for i in range(n)]
        start, run = max(((s, _table_run(vals, s)) for s in range(3)),
                         key=lambda t: t[1])
        if run < 36:
            continue
        offset = _semitones(vals[start]) - start
        shift = round(offset)
        if abs(offset - shift) > _GRID_TOLERANCE:
            shift = 0
        length = run + 1 if _grid_edge_clamp(vals, start + run) else run
        cands.append(FreqTable(addr, start, length, shift, offset - shift,
                               run=run))
    if not cands:
        return None
    # Both tie-breaks rank on `run`, not `length` -- the validated run is the
    # evidence, and a clamped top entry is not. Powerplay Hockey's two players
    # are separated by exactly that one entry (its tune table is NTSC, so its
    # own entry 95 still fits the grid and its cue table's does not); ranking
    # on `length` would tie them and hand the blind path back the coin flip
    # `near` exists to remove.
    if near is None:
        # `max` keeps the first of equal keys, which is the file order the
        # old `run > best.length` walk kept.
        best = max(cands, key=lambda c: c.run)
    else:
        best = min(cands, key=lambda c: (abs(sid.to_offset(c.addr) - near),
                                         -c.run))
    if len({c.shift for c in cands}) > 1:
        best = replace(best, shift=0, detune=best.detune + best.shift)
    if near is None and _detunes_disagree(cands):
        best = replace(best, ambiguous=True)
    return best


def _detunes_disagree(cands: "list[FreqTable]") -> bool:
    """True if these tables are not all tuned alike.

    The threshold is the one that separates an index shift from a tuning:
    below it the tables name the same pitches and which one is read cannot
    change a note name, above it they do not.
    """
    detunes = [c.detune + c.shift for c in cands]
    return bool(detunes) and max(detunes) - min(detunes) > _GRID_TOLERANCE


@dataclass
class SidFile:
    path: str
    data: bytes  # raw file bytes; data[k] == VB's SIDfile(k)
    name: str
    author: str
    released: str
    load_addr: int
    subtunes: int
    # PSID `startSong`, 16-bit BE at 0x10, **1-based**: which subtune a player
    # picks when the user picks none. Seven corpus files set it to something
    # other than 1, and for those, subtune 0 is not the tune -- Samantha Fox
    # Strip Poker's is a one-note stub while the music is at startSong 10. Read
    # for measurement only; conversion emits every subtune and does not reorder
    # them, so nothing in the pipeline branches on this.
    start_song: int = 1
    speed: int = 0  # PSID `speed`, 32-bit BE at 0x12: one bit per subtune
    magic: str = "PSID"     # "PSID" or "RSID", header 0x00-0x03
    version: int = 0        # header `version`, 16-bit BE at 0x04
    init_addr: int = 0      # header `initAddress`, 16-bit BE at 0x0A
    # header `playAddress`, 16-bit BE at 0x0C. The routine the C64 calls
    # every frame, and therefore where a player's OUTER gate lives -- the
    # counter that decides whether this call does anything at all. Read
    # for detection only: `_find_outer_gate` anchors its rescue spellings
    # here, because `DEC zp / BPL / LDA # / STA zp / RTS` is a common
    # enough idiom that a file-wide search matched non-gate code and cost
    # Spellbound 55 points of melody before it was caught. Zero means the
    # tune installs its own interrupt handler and the header names no
    # routine, in which case nothing can be anchored and the rescue
    # spellings simply decline.
    play_addr: int = 0
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

    def to_address(self, off: int) -> int:
        """Byte offset into `data` -> the C64 address the PLAYER reads it at.

        `to_offset`'s inverse, and it needs both of that function's branches.
        A file that moves part of itself at init holds those bytes at `src` in
        its own image and the player reads them at `dst`, so an offset inside
        the moved region names an address `dst - src` higher than the plain
        formula gives. I_Ball is the corpus's only such file and the difference
        is not subtle: its effect byte sits at offset 1493, which the plain
        inversion calls **$9557** and the player reads at **$E557**.

        **Written because the inversion was hand-rolled at nine call sites in
        FIVE spellings** -- `off - (HLEN - 1) + load_addr`,
        `off + load_addr - HLEN + 1`, `load_addr + off - HLEN + 1`, and twice
        as a `base = load_addr - to_offset(load_addr)` delta added later --
        and only one of them (`detect._effect_byte_address`) knew about the
        relocation. A formula repeated five ways is a formula nobody can grep
        for; `tests/test_sidfile.py` pins the round trip over the whole corpus.
        """
        addr = off - HLEN + 1 + self.load_addr
        r = self.relocation
        if r is not None and r.src <= addr < r.src + r.length:
            return addr - r.src + r.dst
        return addr

    def with_init_writes(self) -> Optional["SidFile"]:
        """This file with the init routine's writes applied, or None.

        Returns None when the init address is unusable or the walk finds
        nothing to apply. Callers must treat the result as a *fallback* image:
        the writes are only correct for a player that really does patch itself,
        and applying them to one that does not would overwrite real data. See
        convert() for the guard that keeps a file which already reads correctly
        from ever seeing a patched byte.
        """
        if not 0 < self.init_addr:
            return None
        writes = find_init_writes(self.data, self.init_addr, self.load_addr)
        if not writes:
            return None
        patched = bytearray(self.data)
        for off, value in writes.items():
            patched[off] = value
        if bytes(patched) == self.data:
            return None
        return replace(self, data=bytes(patched))

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
    # PSID `startSong` at 0x10-0x11, big-endian and 1-based. Clamped into
    # range rather than trusted: a file claiming a subtune it does not have
    # would otherwise send the harness to trace silence.
    start_song = int.from_bytes(data[0x10:0x12], "big")
    if not 1 <= start_song <= max(subtunes, 1):
        start_song = 1
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
    # initAddress. Read only so find_init_writes has an entry point; nothing
    # else consults it, and a file whose player needs no patching never does.
    init_addr = int.from_bytes(data[0x0A:0x0C], "big")
    play_addr = int.from_bytes(data[0x0C:0x0E], "big")

    return SidFile(
        path=path,
        data=data,
        name=name,
        author=author,
        released=released,
        load_addr=load_addr,
        subtunes=subtunes,
        start_song=start_song,
        speed=speed,
        magic=magic,
        version=version,
        init_addr=init_addr,
        play_addr=play_addr,
        relocation=find_relocation(data),
    )
