"""The command-table engine's chord arpeggio (pattern command `$82 a b`).

Read out of Chicken Song's player (Hollywood or Bust spells the same code at
$07D8/$0868 with its own cells). The handler and the per-frame routine:

    144B  C8 / B1 FD / 9D DD 15   INY / LDA (patt),Y / STA $15DD,X  ; op 1
    1451  C8 / B1 FD / 9D E0 15   INY / LDA (patt),Y / STA $15E0,X  ; op 2
    1457  A9 01 / 9D E3 15        LDA #$01 / STA $15E3,X           ; enable
    1470  A9 00 / 9D E3 15        LDA #$00 / STA $15E3,X           ; `$84`: off

    13D8  BD E3 15  LDA $15E3,X / BEQ out   ; per-voice enable
    13DD  CE E6 15  DEC $15E6               ; ONE counter for all three voices
    13E0  D0 05 / A9 03 / 8D E6 15          ; 0 -> reload 3
    13E7  AD E6 15 / C9 01 / D0 06 / BD DA 15 / JMP   ; 1 -> $15DA,X (never written: 0)
    13F4  C9 02 / D0 06 / BD DD 15 / JMP              ; 2 -> op 1
    13FE  BD E0 15                                    ; 3 -> op 2
    1401  18 / 7D 99 15 / 0A / A8   CLC / ADC note,X / ASL / TAY
    1407  B9 C6 14 ... STA $D401,Y / STA $D400,Y      ; the player's note table

So it is a SEMITONE chord added to the voice's note number, written over
whatever frequency the effects before it wrote, every frame the enable is
set -- and the enable is NOT cleared at a note start: it stays set until a
`$84`, across notes and across patterns (Chicken Song's pattern 5 ends with
it set and pattern $1D, which carries no chord command, plays chorded).

**The counter is global and is stepped once per ENABLED voice per frame**
(it sits inside the X = 2..0 voice loop, after each voice's fetch). So which
offset a voice reads on a frame depends on the other voices, and that is why
the phase is not read from the record: `chord_note_cycles` walks the three
orderlists frame by frame, applies every command in the order the player
does, steps the counter exactly as above from its image value, and records
the three offsets each chorded note reads on its first three frames. Every
duration Chicken Song uses is a multiple of 3 and only one voice is ever
chorded at a time, so there every chorded note reads the same rotation
(op 2, op 1, 0 from its fetch frame); Hollywood or Bust's image counter is 3,
so its notes read (op 1, 0, op 2). The walk does not assume either.

Emitted as `CMD_SETWAVEPTR` on the note's row (the interleaved engine's
`$83` route, `patterns.ILV_ARP`), with the note written as the pitch the
original sounds on the fetch frame and a block cycling the three offsets
relative to it from wavetable call 0 (`goatwriter.drums._chord_block`, which
says why call 0 is the original's frame 0).

**The intro waveform.** Effect bit $01 (Chicken Song $133B) writes, for the
first three frames of every event, the per-voice constant `$15ED,X` to
$D404 instead of the record's waveform (`LDA total / SBC #$03 / CMP
remaining / BCC` -> `LDA $15ED,X / STA $D404,Y`): $11 on voice 2 ($81 on
voices 1 and 3, whose bit-$01 notes are the drum, not this). Inside a chord
block it is spelled on those frames' wavetable calls; our init call, a frame
earlier, writes the instrument's firstwave and stays the record's. The same
branch also decrements the frequency high byte from frame 3 on, which the
chord's own write overwrites on every chorded frame -- the fall is audible
only on unchorded bit-$01 notes and is not emitted here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .search import search_file
from .sidfile import SidFile

CHORD_FRAME = ("BD ?? ?? F0 ?? CE ?? ?? D0 05 A9 03 8D ?? ?? AD ?? ?? C9 01 "
               "D0 06 BD ?? ?? 4C ?? ?? C9 02 D0 06 BD ?? ?? 4C ?? ?? "
               "BD ?? ?? 18 7D ?? ??")
CHORD_DISPATCH = "B1 ?? 10 ?? 29 0F AA BD ?? ?? 8D ?? ?? BD ?? ?? 8D ?? ??"
# Effect bit $01's intro (Chicken Song $133B-$1371): the count is the SBC
# immediate, the waveform table the LDA abs,X stored to $D404.
CHORD_INTRO = ("AD ?? ?? 29 01 F0 ?? BD ?? ?? F0 ?? BD ?? ?? F0 ?? BD ?? ?? "
               "38 E9 ?? DD ?? ?? AC ?? ?? 90 ?? BD ?? ?? DE ?? ?? 99 01 D4 "
               "BD ?? ?? D0 ?? BD ?? ?? 99 01 D4 BD ?? ?? 99 04 D4")
WALK_FRAMES = 400_000       # an upper bound; the walk stops after two laps


@dataclass(frozen=True)
class ChordArp:
    """An `arps` operand: the chord a note reads, relative to its frame-0 pitch.

    `rel` is the offset for frames 0, 1, 2 (rel[0] is 0 by construction) and
    `intro` the waveform the player writes for frames below `intro_frames`
    (0: none)."""
    rel: Tuple[int, int, int]
    intro: int = 0
    intro_frames: int = 0


@dataclass(frozen=True)
class CmdChord:
    cmd: int                 # command index (b & $0F) of the setter
    off: int                 # command index of the clear, or -1
    resume: int              # command index that re-arms the kept operands, or -1
    enable: int              # addresses, as the player names them
    counter: int
    cells: Tuple[int, int, int]      # read on counter value 1, 2, 3
    op_cells: Tuple[int, int]        # where the setter's two operands go
    intro_table: int = -1    # address of the per-voice intro waveform
    intro_frames: int = 0
    effect_offset: int = -1  # record byte the effect bits are read from


def _addr(data: bytes, i: int) -> int:
    return data[i] | data[i + 1] << 8


def _stores(data: bytes, addr: int) -> bool:
    lo, hi = addr & 0xFF, addr >> 8
    pat = f"9D {lo:02X} {hi:02X}"
    return search_file(data, pat) >= 1 or search_file(data, f"99 {lo:02X} {hi:02X}") >= 1


def find_cmd_chord(sid: SidFile, det) -> Optional[CmdChord]:
    """The chord's cells and commands, or None where the shape is absent."""
    if det.pattern_dialect != "cmdtable":
        return None
    data = sid.data
    at = search_file(data, CHORD_FRAME)
    disp = search_file(data, CHORD_DISPATCH)
    if at < 1 or disp < 1:
        return None
    enable = _addr(data, at + 1)
    counter = _addr(data, at + 6)
    if _addr(data, at + 13) != counter or _addr(data, at + 16) != counter:
        return None
    cells = (_addr(data, at + 23), _addr(data, at + 33), _addr(data, at + 39))
    cmd_lo = sid.to_offset(_addr(data, disp + 8))
    cmd_hi = sid.to_offset(_addr(data, disp + 14))
    count = cmd_hi - cmd_lo
    cmd = off = resume = -1
    op_cells = None
    for c in range(max(0, min(count, 16))):
        h = sid.to_offset(data[cmd_lo + c] | data[cmd_hi + c] << 8)
        if not 0 < h < len(data) - 20:
            continue
        b = data[h:h + 20]
        if (b[0] == 0xC8 and b[1] == 0xB1 and b[3] == 0x9D and b[6] == 0xC8
                and b[7] == 0xB1 and b[9] == 0x9D and b[12] == 0xA9
                and b[13] == 0x01 and b[14] == 0x9D
                and _addr(b, 15) == enable and b[17] == 0xC8 and b[18] == 0x4C):
            cmd, op_cells = c, (_addr(b, 4), _addr(b, 10))
        elif (b[0] == 0xA9 and b[1] in (0x00, 0x01) and b[2] == 0x9D
              and _addr(b, 3) == enable and b[5] == 0xC8 and b[6] == 0x4C):
            # `$84` clears the enable; Hollywood or Bust's `$86` is the
            # setter's own tail ($0874), re-arming the operands it kept.
            if b[1]:
                resume = c
            else:
                off = c
    if cmd < 0 or set(op_cells) != {cells[1], cells[2]}:
        return None
    if _stores(data, cells[0]):
        return None             # the value-1 cell is read as a constant below
    intro_table, intro_frames, effect_offset = -1, 0, -1
    it = search_file(data, CHORD_INTRO)
    if it >= 1 and det.instr_start > 0:
        eff = _addr(data, it + 1)
        intro_frames = data[it + 22]
        intro_table = _addr(data, it + 52)
        # The record byte that feeds the effect cell: `LDA rec,Y / STA eff`.
        lo, hi = eff & 0xFF, eff >> 8
        st = search_file(data, f"B9 ?? ?? 8D {lo:02X} {hi:02X}")
        base = sid.to_address(det.instr_start)
        if st >= 1:
            off_ = _addr(data, st + 1) - base
            if 0 <= off_ < det.instr_stride:
                effect_offset = off_
        if effect_offset < 0 or not 1 <= intro_frames <= 8:
            intro_table, intro_frames, effect_offset = -1, 0, -1
    return CmdChord(cmd, off, resume, enable, counter, cells, tuple(op_cells),
                    intro_table, intro_frames, effect_offset)


def _byte(sid: SidFile, addr: int) -> int:
    o = sid.to_offset(addr)
    return sid.data[o] if 0 <= o < len(sid.data) else 0


def _signed(b: int) -> int:
    return b - 256 if b > 127 else b


def _pattern_events(sid: SidFile, det, ch: CmdChord, i: int):
    """[(changes, duration, is_note, record)] for pattern `i`, or None.

    `changes` is the list of chord-state writes before the event, each
    ('on', a, b) or ('off',)."""
    data = sid.data
    step = i * det.table_stride
    lo_i, hi_i = det.pattern_lo + step, det.pattern_hi + step
    if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
        return None
    addr = sid.to_offset(data[hi_i] * 256 + data[lo_i])
    out = []
    changes: list = []
    record = None
    for _ in range(20000):
        if not 1 < addr < len(data):
            return None
        b = data[addr]
        if b == 0xFF:
            break
        if b & 0x80:
            c = b & 0x0F
            if c >= len(det.cmd_operands) or addr + det.cmd_operands[c] >= len(data):
                return None
            if c == ch.cmd:
                changes.append(('on', data[addr + 1], data[addr + 2]))
            elif c == ch.off:
                changes.append(('off',))
            elif c == ch.resume:
                changes.append(('resume',))
            elif c == det.cmd_instrument:
                record = data[addr + 1]
            addr += 1 + det.cmd_operands[c]
            continue
        di = det.duration_table + (b & 0x1F)
        if not 0 <= di < len(data) or data[di] < 1:
            return None
        note = not b & 0x40
        out.append((changes, data[di], note, record))
        changes = []
        addr += 2 if note else 1
        if addr < len(data) and data[addr] == 0xFF:
            break
    return out


def chord_note_cycles(sid: SidFile, det, ch: CmdChord, tracks: List[List[int]],
                      floor: int, origin: Optional[Dict[int, int]] = None
                      ) -> Dict[int, Dict[int, tuple]]:
    """{pattern: {event ordinal: (offsets on frames 0-2, voice, record)}}.

    For the chorded notes only; `record` is the instrument the voice holds,
    which may have been set by an earlier pattern.

    Walks each subtune's three orderlists together, in the player's own
    order (voice 2 first; a voice's fetch, then its chord step), from the
    image values of the enable, operand and counter cells. A pattern-event
    played under different chords takes the majority (ties: the first
    play); one played unchorded most often is left out. `origin` maps a variant's number to the
    pattern it was made from.
    """
    origin = origin or {}
    cache: Dict[int, Optional[list]] = {}
    votes: Dict[Tuple[int, int], Counter] = {}
    for g in range(0, len(tracks) - 2, 3):
        group = tracks[g:g + 3]
        en = [_byte(sid, ch.enable + x) for x in range(3)]
        ops = {a: [_byte(sid, a + x) for x in range(3)]
               for a in (ch.cells[0], ch.cells[1], ch.cells[2])}
        counter = _byte(sid, ch.counter)
        if not 1 <= counter <= 3:
            return {}
        pos = [0, 0, 0]          # orderlist position per voice
        cur = [None, None, None] # (pattern, events, index)
        remain = [0, 0, 0]
        laps = [0, 0, 0]
        pending: List[Optional[list]] = [None, None, None]
        rec: List[Optional[int]] = (list(det.initial_instruments)
                                    if len(det.initial_instruments) == 3
                                    else [None, None, None])
        for _f in range(WALK_FRAMES):
            if min(laps) >= 2:
                break
            for x in (2, 1, 0):
                if remain[x] == 0:
                    ev = None
                    for _guard in range(512):
                        if cur[x] is not None and cur[x][2] < len(cur[x][1]):
                            ev = cur[x]
                            break
                        cur[x] = None
                        tr = group[x]
                        if pos[x] >= len(tr):
                            break
                        b = tr[pos[x]]
                        if b == 0xFF:
                            nxt = tr[pos[x] + 1] if pos[x] + 1 < len(tr) else 0
                            pos[x] = nxt
                            laps[x] += 1
                            continue
                        pos[x] += 1
                        if b >= floor:
                            continue
                        src = origin.get(b, b)
                        if src not in cache:
                            cache[src] = _pattern_events(sid, det, ch, src)
                        evs = cache[src]
                        if evs:
                            cur[x] = [src, evs, 0]
                    if ev is None:
                        laps[x] = max(laps[x], 2)
                        remain[x] = 1 << 30
                        continue
                    src, evs, k = ev
                    changes, dur, is_note, r = evs[k]
                    ev[2] += 1
                    if r is not None:
                        rec[x] = r
                    for c in changes:
                        if c[0] == 'on':
                            ops[ch.op_cells[0]][x] = c[1]
                            ops[ch.op_cells[1]][x] = c[2]
                        en[x] = int(c[0] != 'off')
                    remain[x] = dur
                    pending[x] = None
                    if is_note:
                        pending[x] = [src, k, [], rec[x]] if en[x] else None
                        if not en[x]:
                            votes.setdefault((src, k), Counter())[None] += 1
                if en[x]:
                    counter -= 1
                    if counter == 0:
                        counter = 3
                    off = _signed(ops[ch.cells[counter - 1]][x])
                    p = pending[x]
                    if p is not None:
                        p[2].append(off)
                        if len(p[2]) == 3:
                            votes.setdefault((p[0], p[1]), Counter())[
                                (tuple(p[2]), x, p[3])] += 1
                            pending[x] = None
                remain[x] -= 1
    out: Dict[int, Dict[int, tuple]] = {}
    for (src, k), c in votes.items():
        # Most plays win, and a tie goes to the play heard first (Counter
        # keeps insertion order and most_common is stable): where the other
        # voices' durations are not multiples of 3 a pattern can read a
        # different rotation on its second lap (Hollywood or Bust's 14).
        (best, n), = c.most_common(1)
        if best is None:
            continue
        out.setdefault(src, {})[k] = best
    return out


def chord_arp(cycle: Tuple[int, int, int], intro: int, intro_frames: int
              ) -> Optional[ChordArp]:
    """The `arps` operand for a note reading `cycle`, or None for no motion."""
    rel = tuple(o - cycle[0] for o in cycle)
    if not any(rel) and not intro:
        return None
    return ChordArp(rel, intro, intro_frames if intro else 0)


def record_intro(sid: SidFile, det, ch: CmdChord, record: Optional[int],
                 voice: int) -> int:
    """The intro waveform a note of `record` on `voice` opens with, or 0."""
    if ch.intro_table < 0 or record is None or det.instr_start < 0:
        return 0
    o = det.instr_start + record * det.instr_stride + ch.effect_offset
    if not 0 <= o < len(sid.data) or not sid.data[o] & 0x01:
        return 0
    return _byte(sid, ch.intro_table + voice)
