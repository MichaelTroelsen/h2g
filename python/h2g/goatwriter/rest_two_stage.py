"""A REST replays the two-stage attack: one gate-off frame of the attack wave.

Chain_Reaction, Zoolook (`det.effect_two_stage`, the `AND #$04` block read by
`detect._find_two_stage`). Voice 3 of Chain_Reaction shows, in the original's
trace, `$D404` `40 -> 50 -> 40` one frame after a rest, with the pulse register
stepping `110 -> 080 -> 090` beside it (frames 727-729). It looks like a
"flash after the pulse wrap", and it is neither: the pulse jump to `$080` is
the rest's own re-initialisation, and the `$50` is the same event's second
stage.

The writer is `$0C13 STA $D404,Y` (Zoolook `$43C7`), fed `$0D06,X AND $0D0F,X`:

    $0938  DEC $0D0F,X        the rest path (status bit 6): gate mask $FF -> $FE
    $0953  .. $0985           the init tail a NOTE takes too: pulse lo/hi from
                              the record, AD, SR, and
    $0961  LDA $0E70,X / PHA ... $097D PLA / STA $0D3A,X
                              the record's stage-one frame count
    $0988  LDA $0D15 / STA $0D06,X        the record's own waveform ($41)
    $0B35  LDA $0D30 / AND #$04 / BEQ     the two-stage block, every frame:
    $0B39  LDA $0D3A,X / BEQ $0B47 / DEC  count > 0: write $0E6E,Y (attack,
    $0B41  LDA $0E6E,Y                    here $51) and count it down;
    $0B47  LDA $0D87,Y                    else the record's own waveform.

So a rest frame writes `$41 & $FE = $40`, the next `count` frames write
`$51 & $FE = $50`, and the record's `$40` resumes. A Goattracker KEYOFF clears
the gate and nothing else (gplay.c:920): the finished program the last note ran
is at its stop, so ours stays `$40` and the frame is missing. All 119 rests of
instrument 5 in 180 s of Chain_Reaction flash (119 of 119; the 152 rests of
the four other instruments, none of them two-stage, do not), every one with
the stale `$0D32` bit 7 clear that lets the init tail run. Zoolook is the same
player relocated: 119 gate-off `$50` frames, the same writer.

Rasputin is NOT this mechanism. Its 247 "`$50`" runs are `$58` frames -- the
TEST bit, `$08` -- the hard restart, `detect`'s TEST stand-in shape.

`CMD_SETWAVEPTR` on the KEYOFF row is the replay (gplay.c:436-445 sets the
pointer and zeroes `wavetime`; the entry runs on that tick, as a note's first
does). It names a block appended to the wavetable, a copy of the record's own
program with the first entry's frequency kept (`WAVE_NOTE_KEEP`: the rest
reaches the write with no pitch load of its own). Written under
`rest_reseed`'s conditions -- free command column, running command
`CMD_DONOTHING`, every pass through a position agreeing, a pattern its
positions want differently cloned -- and only for a record whose finished
program IS the plain two-stage shape (`two_stage_records`): waveform, delay,
a different waveform, delay, the first waveform again, stop; nothing else.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..detect import Detection, _status_bit6_bvs
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, GT_MAX_TABLELEN, WAVE_MAX_DELAY,
                        WAVE_NOTE_KEEP, _SONG_MAX_PATTERNS)
from .rest_reseed import _rest_reseed_plan

# The effect byte's bit the two-stage block tests (`AND #$04`).
TWO_STAGE_BIT = 0x04

# 6502 instruction length by opcode (1 for an undocumented one), the table
# `dis6502.OPCODES` gives, spelled out so the package stays free of the tool.
_LEN = ("12111221121113312211122113111331" "32112221121133312211122113111331"
        "12111221121133312211122113111331" "12111221121133312211122113111331"
        "12112221111133312211222113111311" "22212221121133312211222113113331"
        "22112221121133312211122113111331" "22112221121133312211122113111331")
# Opcodes that end a straight-line walk: BRK, RTI, JMP abs, RTS, JMP ind.
_ENDS = frozenset((0x00, 0x40, 0x4C, 0x60, 0x6C))
# How far past the rest branch's target the stage count's load may sit.
REST_REACH = 96


def rest_reaches_stage_count(sid: SidFile, det: Detection) -> bool:
    """Whether a bit-6 rest runs the init tail that reloads the two-stage
    frame count.

    The player's rest is the BVS target found by `detect._status_bit6_bvs`
    (Chain_Reaction `$0938 DEC $0D0F,X`); it falls into the shared note tail,
    whose push chain loads the count (`$0961 LDA $0E70,X`) -- the table
    `det.two_stage_frames` names. True where straight-line code from the target
    reaches a `LDA abs,X/Y` of exactly that address within `REST_REACH` bytes
    with no jump, return or break in between: the 15 players spelling the tail
    as Chain_Reaction does. A player whose rest goes elsewhere (Sanxion, Star
    Paws, Bangkok Knights) or whose bit-6 test is not read (Mr_Meaner,
    Lion_Heart, Off_the_Cuff, Go_Go_Dash, Rock_Tells_the_Tale) reloads
    nothing on the evidence we have, and replaying the attack there moved
    them the wrong way (Mr_Meaner wave .9986 -> .9899, Lion_Heart ctrl .9931
    -> .9678, Off_the_Cuff depth_ratio .9969 -> .6343)."""
    if det.two_stage_frames < 0:
        return False
    data = sid.data
    at = _status_bit6_bvs(data)
    if at < 0 or at >= len(data):
        return False
    rel = data[at] - 256 if data[at] > 127 else data[at]
    off = at + 1 + rel
    want = sid.to_address(det.two_stage_frames)
    end = min(off + REST_REACH, len(data) - 2)
    while 0 <= off < end:
        op = data[off]
        if op in (0xBD, 0xB9) and (data[off + 1] | data[off + 2] << 8) == want:
            return True
        if op in _ENDS:
            return False
        off += int(_LEN[op])
    return False

# Calls of the record's own waveform a rest holds before the attack stage.
# MEASURED, not derived (fidelity.py -t 180 --presets --sound, `wave` column):
# Chain_Reaction .9892 -> .9913 at 0, **.9941 at 1**, .9912 at 2; Zoolook
# .9881 -> .9914 at 0, **.9943 at 1**, .9916 at 2. Our rest rows land up to a
# call before the original's frame, which samples the replay a frame early.
REST_TWO_STAGE_DELAY = 1


def two_stage_records(sid: SidFile, det: Detection,
                      wave_entries: List[Tuple[int, int]],
                      wave_starts: List[int], instr_used: int,
                      lead: int) -> Dict[int, int]:
    """{GT instrument number: wavetable start} of every record whose
    finished program is the plain two-stage shape.

    Read off the table, not re-derived: a record another block owns (an
    arpeggio, a fixed attack pitch, a vibrato) carries commands or pitches in
    its program and is left out."""
    out: Dict[int, int] = {}
    if (not det.effect_two_stage or det.instr_start < 0
            or det.instr_stride <= 0):
        return out
    data = sid.data
    for i in range(max(instr_used - lead, 0)):
        if i + lead >= len(wave_starts) or not wave_starts[i + lead]:
            continue
        rec = det.instr_start + i * det.instr_stride
        if rec + 7 >= len(data) or not data[rec + 7] & TWO_STAGE_BIT:
            continue
        start = wave_starts[i + lead]
        if _plain_two_stage(wave_entries, start) is not None:
            out[i + lead + 1] = start & 0xFF
    return out


def _plain_two_stage(wave_entries: List[Tuple[int, int]], start: int):
    """The program's entries when it is `wave, delay, other wave, delay,
    wave, stop` with every waveform on the played note, else None."""
    pos = start - 1
    prog: List[Tuple[int, int]] = []
    while 0 <= pos < len(wave_entries):
        left, right = wave_entries[pos]
        if left == 0xFF:
            if right != 0:
                return None
            break
        if left >= 0xF0:
            return None
        prog.append((left, right))
        pos += 1
    else:
        return None
    waves = [e for e in prog if e[0] > WAVE_MAX_DELAY]
    delays = [e for e in prog if e[0] <= WAVE_MAX_DELAY]
    if len(waves) != 3 or len(delays) != 2 or len(prog) != 5:
        return None
    if [e[0] <= WAVE_MAX_DELAY for e in prog] != [False, True, False, True,
                                                  False]:
        return None
    if any(w[1] != 0 for w in waves):
        return None
    if waves[0][0] != waves[2][0] or (waves[0][0] & 0xFE) == (
            waves[1][0] & 0xFE):
        return None
    return prog


def two_stage_block(wave_entries: List[Tuple[int, int]], start: int,
                  delay: int = REST_TWO_STAGE_DELAY) -> List[Tuple[int, int]]:
    """The rows a rest's pointer names: `delay` calls holding the record's
    waveform, then the record's program with its first entry's frequency
    kept. Empty where the record is not the plain shape."""
    prog = _plain_two_stage(wave_entries, start)
    if prog is None:
        return []
    block: List[Tuple[int, int]] = []
    if delay > 0:
        # A delay entry is current for `value + 1` calls (gplay.c:697-704).
        block.append((delay - 1, WAVE_NOTE_KEEP))
    block.append((prog[0][0], WAVE_NOTE_KEEP))
    block.extend(prog[1:])
    block.append((0xFF, 0))
    return block


def rest_two_stages(sid: SidFile, det: Detection,
                    tracks: List[List[int]], patterns: List[List[int]],
                    wave_entries: List[Tuple[int, int]],
                    wave_starts: List[int], instr_used: int, lead: int,
                    log=None, delay: int = REST_TWO_STAGE_DELAY) -> tuple:
    """(patterns, tracks, written, wave_entries): `CMD_SETWAVEPTR` to a
    copy of the record's program on every KEYOFF row whose current
    instrument is a plain two-stage record, under the module docstring's
    conditions. Changed patterns and tracks are COPIES; clones are appended."""
    if not rest_reaches_stage_count(sid, det):
        return patterns, tracks, 0, wave_entries
    starts = two_stage_records(sid, det, wave_entries, wave_starts,
                               instr_used, lead)
    if not starts:
        return patterns, tracks, 0, wave_entries
    plan, skipped = _rest_reseed_plan(tracks, patterns, starts, set(starts),
                                      ties=False)
    used = sorted({start for want in plan.values() for _row, start in want})
    wave_entries = list(wave_entries)
    blocks = {ptr: two_stage_block(wave_entries, ptr, delay) for ptr in used}
    # Records sharing a program share a block: the table is the scarce thing.
    unique = {tuple(b) for b in blocks.values() if b}
    fit = len(wave_entries) + sum(len(b) for b in unique) <= GT_MAX_TABLELEN
    remap: Dict[int, int] = {}
    placed: Dict[tuple, int] = {}
    for ptr in used:
        block = blocks[ptr]
        if not block or not fit:
            continue            # no room, or not the plain shape: leave it
        if tuple(block) not in placed:
            placed[tuple(block)] = (len(wave_entries) + 1) & 0xFF
            wave_entries.extend(block)
        remap[ptr] = placed[tuple(block)]
    if not remap:
        return patterns, tracks, 0, wave_entries
    groups: Dict[int, Dict[frozenset, list]] = {}
    for (ti, pos), want in plan.items():
        want = frozenset(w for w in want if w[1] in remap)
        groups.setdefault(tracks[ti][pos], {}).setdefault(want, []).append(
            (ti, pos))
    out = list(patterns)
    new_tracks = [list(t) for t in tracks]
    written = clones = full = 0

    def patched(b: int, want: frozenset) -> List[int]:
        rows = list(patterns[b])
        for row, start in want:
            rows[4 * row + 2], rows[4 * row + 3] = (
                CMD_SETWAVEPTR, remap[start])
        return rows

    for b in sorted(groups):
        by_want = groups[b]
        wanted = [w for w in by_want if w]
        if not wanted:
            continue
        if frozenset() in by_want:
            stays = frozenset()
        else:
            stays = max(wanted, key=lambda w: (len(by_want[w]), sorted(w)))
            out[b] = patched(b, stays)
            written += len(stays) * len(by_want[stays])
        for want in sorted((w for w in wanted if w != stays), key=sorted):
            if len(out) >= _SONG_MAX_PATTERNS:
                full += len(by_want[want])
                continue
            out.append(patched(b, want))
            clones += 1
            for ti, pos in by_want[want]:
                new_tracks[ti][pos] = len(out) - 1
            written += len(want) * len(by_want[want])
    if log and (written or skipped or full):
        log(f"Rest two-stage..........: CMD_SETWAVEPTR on {written} "
            f"row(s) over the orderlists, {clones} pattern copy(ies)"
            + "".join(f", {n} {why}" for why, n in sorted(skipped.items()))
            + (f", {full} position(s) left alone: pattern table full"
               if full else ""))
    return out, new_tracks, written, wave_entries
