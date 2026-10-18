"""The command-table engine's LFO vibrato as a per-frame wave program.

`detect._find_table_vibrato` reads the player (Hollywood or Bust $05CE,
Chicken Song the same block): each frame a voice's current record has a
non-zero parameter byte (+5), it reads the next byte of the record's LFO
table at a per-voice index (`$05F3 LDY $09B1,X / INC $09B1,X / LDA table,Y /
CMP #$FF`, `$FF` resets the index to 0 and reads again), and sets the voice's
frequency to the note's plus `value * count * ((freq(note) - freq(note-1))
>> 4)` -- an absolute POSITION per frame, sign in bit 7.

`_table_vibrato_entry` maps that onto Goattracker's vibrato, which cannot
say it: Goattracker's is a symmetric triangle restarted by every note, its
depth a power-of-two shift of the interval, and the plain program's note
steps (`41 00` on the note's first calls) suspend it for as long as they run.
Hollywood or Bust sub 2's lead (record 6, `$14`: table 1 `00 01 02 01 00 81`,
count 4) measured `684C 66D8 684C 69C0 6B34 69C0` from each onset in the
original against ours `6853 6853 6853 6B6D 6853 6853` -- held but for one
frame.

**The program.** Entry 0 is the record's waveform on the note (frame 0);
each later frame is one wavetable step moving the frequency by the change
in position since the frame before: `F1`/`F2` (portamento up/down, executed
from the wavetable on every call, player.s `mt_execwavecmd`) by a
note-relative speed `(freq(note+1) - freq(note)) >> r`, or a one-call delay
(`$00`, right `$80`: no pitch write) where the position holds. `r` is the
player's own `unit_shift - log2(count * |step|)`, so a record qualifies only
where `count * |step|` is a power of two the shift can still divide by --
any other would be a rounded depth, which is what the vibrato mapping
already is. The steps loop over the table's period once the walk has
wrapped.

**The phase is the walk's, replayed.** The index is per voice and never
reset at a note: it starts at the image's bytes (`$09B1` = `04 00 02` in
Hollywood or Bust) and steps once on every frame the voice's current record
vibrates, whatever the note does -- a rest included, since the effect block
runs for the record the voice holds. So each note's first-frame index is a
function of the song up to it. `lfo_phases` walks the finished orderlists
one lap per subtune at `det.frames_per_row` frames a row, and each record's
program is laid out at the index most of its untied notes start on. The
model was checked against the original before anything was emitted: replayed
frame by frame on siddump of Hollywood or Bust (subtunes 0-2, 180 s, the
record identified by its ADSR), it predicts the measured positions of 1793
of 1821 vibrato onsets; the 28 others read a slide's or a tie's pitch, not
a different phase (C:/t/hob-snare/lfo_sim.py).

**What it costs.** One porta step on every frame that moves means the
pattern's own continuous effect does not run on those calls (the wavetable
command takes the call, player.s `mt_execwavecmd` -> `mt_done`), so a slide
under such a record moves only on its held frames. Goattracker's interval
is the semitone above the note and the player's the one below, so the
excursion is about 6% deep. A note whose index is not the record's modal one
plays the right shape at the wrong phase. Frame 0 sounds the note itself,
where the original sounds `value(idx0)` -- 0 on the modal phase of every
Hollywood or Bust record this reaches.

Behind `convert(lfo_wave=...)`, off by default; -S1 only (the walk is one
step a frame and a step here is one call).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, CMD_TONEPORTA, GT_FIRST_NOTE, GT_LAST_NOTE,
                        GT_MAX_TABLELEN, GT_WAVE_JUMP,
                        WAVECMD_PORTADOWN, WAVECMD_PORTAUP)

# The LFO table's end marker and sign bit (detect.TABLE_VIBRATO_END/_SIGN).
LFO_END = 0xFF
LFO_SIGN = 0x80
# A note-relative speed-table row: left bit 7 set, right the shift
# (gplay.c:545-550, player.s `mt_calculatedspeed`).
LFO_SPEED_RELATIVE = 0x80
# A one-call delay whose right side writes no pitch (.sng `$80`).
LFO_HOLD = (0x00, 0x80)
# Reads past which a walk that never meets `$FF` is not a table.
LFO_MAX_READS = 0x100


def _byte(sid: SidFile, addr: int) -> Optional[int]:
    off = sid.to_offset(addr)
    return sid.data[off] if 0 <= off < len(sid.data) else None


def lfo_record(sid: SidFile, det: Detection, i: int,
               multiplier: int) -> Optional[Tuple[int, int, int]]:
    """(table address, count, base shift r) for record `i`, or None.

    `r` is the shift that turns Goattracker's note-relative interval into one
    of the player's units (`count / 2**unit_shift` of it). None where there
    is no LFO table, the walk's cell is unread, the call rate is not 1, the
    record does not vibrate or sets an effect bit the wavetable already
    spends (+7's low nibble: this player's $01/$02/$04/$08 blocks), its count
    is not a power of two the shift can hold, or it has no waveform.
    """
    tv = det.table_vibrato
    if (tv is None or tv.index_cell < 0 or not tv.bases or multiplier != 1
            or det.instr_start < 0 or i < 0):
        return None
    base = det.instr_start + i * det.instr_stride
    data = sid.data
    if base + 7 >= len(data):
        return None
    byte = data[base + tv.offset]
    count, table = byte & 0x0F, byte >> 4
    if not count or table >= len(tv.bases) or not tv.bases[table]:
        return None
    if data[base + 7] & 0x0F or not data[base + 2] & 0xF0:
        return None
    if count & (count - 1):
        return None
    r = tv.unit_shift - (count.bit_length() - 1)
    if r < 0:
        return None
    return tv.bases[table], count, r


def _walk_reads(sid: SidFile, table: int, idx: int,
                n: int) -> Optional[Tuple[List[int], List[int]]]:
    """(signed values, index read) for `n` frames from `idx`, the player's
    `LDY / INC / LDA table,Y / CMP #$FF` with its reset; None off the image."""
    values, at = [], []
    for _ in range(n):
        for _guard in range(LFO_MAX_READS):
            b = _byte(sid, table + idx)
            if b is None:
                return None
            if b == LFO_END:
                idx = 0
                continue
            break
        else:
            return None
        at.append(idx)
        values.append(-(b & 0x7F) if b & LFO_SIGN else b)
        idx = (idx + 1) & 0xFF
    return values, at


def _step(sid: SidFile, table: int, idx: int) -> Optional[int]:
    got = _walk_reads(sid, table, idx, 1)
    return None if got is None else (got[1][0] + 1) & 0xFF


def _note_walk(sid: SidFile, det: Detection, tracks: List[List[int]],
               patterns: List[List[int]], lead: int, multiplier: int):
    """(track, pattern, row offset, Goattracker instrument, LFO index) for every
    untied note row of every lap of the finished orderlists, in play order;
    None (once) where the walk cannot be replayed (no index cell, no row
    clock, a split subtune numbering, a table read off the image)."""
    tv = det.table_vibrato
    if (tv is None or tv.index_cell < 0 or multiplier != 1
            or len(tracks) // 3 > max(sid.subtunes, 1)):
        yield None
        return
    fpr = max(1, det.frames_per_row)
    data = sid.data
    n_rec = max(det.instr_used + 1, 0)

    def vib_table(rec: Optional[int]) -> Optional[int]:
        if rec is None or not 0 <= rec < n_rec:
            return None
        b = det.instr_start + rec * det.instr_stride + tv.offset
        if b >= len(data) or not data[b]:
            return None
        t = data[b] >> 4
        return tv.bases[t] if t < len(tv.bases) and tv.bases[t] else None

    for ti, track in enumerate(tracks):
        v = ti % 3
        idx = _byte(sid, tv.index_cell + v) or 0
        rec = (_byte(sid, det.cmd_instr_cell + v)
               if det.cmd_instr_cell >= 0 else None)
        repeat = 1
        for b in track:
            if b == 0xFF:
                break                    # the restart: one lap only
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b >= len(patterns):
                continue
            pat = patterns[b]
            for _ in range(repeat):
                for r in range(0, len(pat) - 3, 4):
                    if pat[r] == 0xFF:
                        break
                    if pat[r + 1]:
                        rec = pat[r + 1] - lead - 1
                    if (GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE
                            and not (pat[r + 2] == CMD_TONEPORTA
                                     and pat[r + 3] == 0)
                            and rec is not None and rec >= 0):
                        yield ti, b, r, rec + lead + 1, idx
                    tbl = vib_table(rec)
                    if tbl is not None:
                        for _f in range(fpr):
                            nxt = _step(sid, tbl, idx)
                            if nxt is None:
                                yield None
                                return
                            idx = nxt
            repeat = 1


def lfo_phases(sid: SidFile, det: Detection, tracks: List[List[int]],
               patterns: List[List[int]], lead: int,
               multiplier: int) -> Dict[int, int]:
    """{Goattracker instrument: the LFO index most of its untied notes open
    on}, for every record `lfo_record` accepts; {} where the walk cannot be
    replayed."""
    votes: Dict[int, Counter] = {}
    for got in _note_walk(sid, det, tracks, patterns, lead, multiplier):
        if got is None:
            return {}
        _ti, _pn, _r, gt, idx = got
        votes.setdefault(gt, Counter())[idx] += 1
    out = {}
    for gt, counts in votes.items():
        if lfo_record(sid, det, gt - lead - 1, multiplier) is None:
            continue
        out[gt] = max(counts, key=lambda k: (counts[k], -k))
    return out


@dataclass(frozen=True)
class LfoPhase:
    """An `arps` operand: the record's LFO program laid out from walk index
    `idx` instead of its modal one (`lfo_phase_pointers`)."""
    idx: int


def lfo_phase_pointers(sid: SidFile, det: Detection,
                       tracks: List[List[int]], patterns: List[List[int]],
                       lead: int, multiplier: int, arps: list,
                       log=None) -> List[List[int]]:
    """`patterns` with a `CMD_SETWAVEPTR` to the record's program at the
    note's own phase on every note row the record's modal phase misses.

    The operand is the 1-based index of a `(record, LfoPhase)` pair in
    `arps`, the route the chord and the interleaved arpeggio already take
    (`build._resolve_arp_pointers` turns it into a table row, or clears it
    where the layout found no room). A row is left on the modal program
    where its command column is taken, or where its pattern's visits open it
    on different indexes or under different records (one row cannot say two,
    and a pointer would hand another record's visit this program); both are
    counted in the log.
    """
    phases = det.lfo_wave_phases
    if not phases:
        return patterns
    seen: Dict[tuple, set] = {}
    for got in _note_walk(sid, det, tracks, patterns, lead, multiplier):
        if got is None:
            return patterns
        _ti, pn, r, gt, idx = got
        # Every visit, whatever its record: a row is one row of a pattern
        # every visit plays, under whichever instrument each one latched.
        seen.setdefault((pn, r), set()).add((gt, idx))
    out = [list(p) for p in patterns]
    placed = taken = split = 0
    wanted: Dict[tuple, list] = {}
    for (pn, r), visits in sorted(seen.items()):
        if not any(gt in phases for gt, _x in visits):
            continue
        if len(visits) != 1:
            split += 1
            continue
        gt, idx = next(iter(visits))
        if idx == phases[gt]:
            continue
        if out[pn][r + 2] or out[pn][r + 3]:
            taken += 1
            continue
        wanted.setdefault((gt - lead - 1, LfoPhase(idx)), []).append((pn, r))
    # The most-pointed block first: the layout appends the `arps` blocks in
    # order and declines what no longer fits, so the table's last rows go to
    # the phases the most notes open on.
    for key, rows in sorted(wanted.items(),
                            key=lambda kv: (-len(kv[1]), kv[0][0],
                                            kv[0][1].idx)):
        if key not in arps:
            if len(arps) >= 0xFF:
                taken += len(rows)
                continue
            arps.append(key)
        for pn, r in rows:
            out[pn][r + 2], out[pn][r + 3] = CMD_SETWAVEPTR, arps.index(key) + 1
            placed += 1
    if log and (placed or taken or split):
        log(f"LFO wave phases.........: {placed} note row(s) ask for their "
            f"own phase's program ({len(wanted)} block(s), placed or "
            f"declined by the layout), {taken} keep the modal one (command "
            f"column taken), {split} (visits disagree)")
    return out


def _program(sid: SidFile, det: Detection, i: int,
             idx0: int, multiplier: int) -> Optional[tuple]:
    """(lead steps, cycle steps, cycle entry) of record `i` from `idx0`.

    A step is `(delta, shift)` -- `shift` None for a held frame. The cycle
    is the table's own period, one step per index `j` (the move from index
    `j - 1`, or from the last one where `j` is 0: the reset); the lead is
    frames 1.. before the walk is on a step the cycle already holds, i.e.
    until a frame whose index follows the one before it. Frame 1 moves from
    the note itself (position 0), so it is a lead step unless that move is
    the cycle's own. None where a step is not a power-of-two number of units
    the record's shift can hold, or the walk leaves the image.
    """
    rec = lfo_record(sid, det, i, multiplier)
    if rec is None:
        return None
    table, _count, r = rec
    tv = det.table_vibrato
    period = tv.shapes[sid.data[det.instr_start + i * det.instr_stride
                                + tv.offset] >> 4][0]
    if period < 2:
        return None
    cyc = _walk_reads(sid, table, 0, period)
    got = _walk_reads(sid, table, idx0, period + LFO_MAX_READS // 8)
    if cyc is None or got is None:
        return None
    cv = cyc[0]

    def step(d: int):
        m = abs(d)
        if not m:
            return (0, None)
        if m & (m - 1) or (m.bit_length() - 1) > r:
            raise ValueError
        return (d, r - (m.bit_length() - 1))

    values, at = got
    try:
        cycle = [step(cv[j] - cv[j - 1]) for j in range(period)]
        lead, pos = [], 0
        for k in range(1, len(at)):
            j, d = at[k], values[k] - pos
            # On the cycle from here: an index inside the table whose move
            # from where we are is the cycle's own (from frame 2 on that is
            # every index following the one before it; on frame 1 only where
            # the note's own position, 0, is the index before it).
            if j < period and d == cv[j] - cv[j - 1]:
                return lead, cycle, j
            lead.append(step(d))
            pos = values[k]
    except ValueError:
        return None
    return None


def _spell(steps, speed_table: List[tuple]) -> Optional[tuple]:
    """(left, right) for `steps`, adding their speed rows; None where the
    speed table cannot take them (nothing is added then)."""
    new = {(LFO_SPEED_RELATIVE, sh) for _d, sh in steps if sh is not None}
    new = {e for e in new if e not in speed_table}
    if len(speed_table) + len(new) > GT_MAX_TABLELEN:
        return None
    left, right = [], []
    for d, sh in steps:
        if sh is None:
            left.append(LFO_HOLD[0])
            right.append(LFO_HOLD[1])
            continue
        entry = (LFO_SPEED_RELATIVE, sh)
        if entry not in speed_table:
            speed_table.append(entry)
        left.append(WAVECMD_PORTAUP if d > 0 else WAVECMD_PORTADOWN)
        right.append(speed_table.index(entry) + 1)
    return left, right


def lfo_wave_entries(sid: SidFile, det: Detection, i: int, idx0: int,
                     wave: int, speed_table: List[tuple],
                     start: Optional[int], budget: int,
                     multiplier: int = 1,
                     cycle_at: Optional[int] = None) -> Optional[tuple]:
    """(left, right) of record `i`'s LFO program from index `idx0`, or None.

    Laid out as the note (entry 0), the lead steps, a jump into the cycle
    where the lead does not end on its first step, then the cycle, which
    loops on itself. With `cycle_at` (the table row of the record's own
    cycle, from `cycle_row`) only the note, the lead and the jump are laid
    out: a phase block shares its record's cycle. None where the record does
    not qualify, the program does not fit `budget` or the speed table is
    full -- the caller keeps the record's plain shape (or, for a phase
    block, the record's own program).
    """
    if start is None:
        return None
    prog = _program(sid, det, i, idx0, multiplier)
    if prog is None:
        return None
    lead, cycle, j = prog
    own = cycle_at is None
    after = start + 1 + len(lead)            # the row after the lead
    if own:
        jump = j != 0
        cyc_row = after + (1 if jump else 0)
    else:
        jump, cyc_row = True, cycle_at
    size = 1 + len(lead) + (1 if jump else 0) + (len(cycle) + 1 if own else 0)
    if size > budget:
        return None
    spelt = _spell(lead + (cycle if own else []), speed_table)
    if spelt is None:
        return None
    sl, sr = spelt
    left, right = [wave] + sl[:len(lead)], [0x00] + sr[:len(lead)]
    if jump:
        left.append(GT_WAVE_JUMP)
        right.append((cyc_row + j) & 0xFF)
    if own:
        left += sl[len(lead):] + [GT_WAVE_JUMP]
        right += sr[len(lead):] + [cyc_row & 0xFF]
    return left, right


def cycle_row(sid: SidFile, det: Detection, i: int, idx0: int,
              start: int, multiplier: int = 1) -> Optional[int]:
    """The table row of the cycle in record `i`'s own program laid out at
    `start` from `idx0` (`lfo_wave_entries` without `cycle_at`)."""
    prog = _program(sid, det, i, idx0, multiplier)
    if prog is None:
        return None
    lead, _cycle, j = prog
    return start + 1 + len(lead) + (1 if j != 0 else 0)


def usable_phases(sid: SidFile, det: Detection, phases: Dict[int, int],
                  lead: int, multiplier: int,
                  speed_table: List[tuple]) -> Dict[int, int]:
    """`phases` less every record whose program cannot be built at all
    (a step of a non-power-of-two size, a walk off the image), dry-run on a
    copy of the speed table with an unlimited budget -- so the vibrato
    layout skips only records that will have a program instead."""
    out = {}
    for gt, idx0 in sorted(phases.items()):
        i = gt - lead - 1
        base = det.instr_start + i * det.instr_stride
        if not 0 <= base + 2 < len(sid.data):
            continue
        if lfo_wave_entries(sid, det, i, idx0, sid.data[base + 2],
                            speed_table, 1, GT_MAX_TABLELEN,
                            multiplier) is not None:
            out[gt] = idx0
    return out
