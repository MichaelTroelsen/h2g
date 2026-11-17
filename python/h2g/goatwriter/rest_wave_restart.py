"""The tabled alternation dialect restarts its toggle on a REST, and ours did not.

Effect bit $02 in the 21 files `detect._find_wave_alternate` reads (W_A_R,
W_A_R_Preview, Knucklebusters, ...) alternates the voice's waveform between
the record's own `+2` and a second table on the LOW BIT of a per-voice call
counter (W_A_R `$E763`, `LDA $E93F,X / AND #$01`). The counter is zeroed in
the note's fetch (`$E4F7 STA $E93F,X`), and the fetch is the path a REST
takes too: the bit-6 test (`$E512 BVS $E552`) comes AFTER the zeroing. So a
rest is a note for the counter: it starts the voice's toggle over, frame 0
the record's waveform, frame 1 the record's waveform again (the counter is 1
by then, odd), frame 2 the alternate, and so on. That is the shape
`_wave_alternate_entries` lays out for a NOTE (lead, then the pair).

A Goattracker KEYOFF clears the gate and nothing else (gplay.c:920): the
wavetable program the previous note started runs on, in whatever phase that
note left it. Where the two parities disagree the whole span to the next
event is in anti-phase -- W_A_R voice 2's `10 80 10 80` against the
original's `80 10 80 10`, a toggle running 280 frames with no attack to
anchor it, and Knucklebusters voice 1 where the original's rests slip a phase
(`10 10 10 80`, `10 10 80`) that ours never does.

`CMD_SETWAVEPTR` on the KEYOFF row is the restart (gplay.c:436-445 sets the
pointer and zeroes `wavetime`; the entry runs on that same tick, as a note's
first does). It points at a small block appended to the wavetable
(`restart_block`) rather than at the record's own start, for two things the
rest does differently from a note:

* **no pitch on frame 0.** The rest reaches the write at `$E7ED` without the
  fetch's `$E536-$E54F`, which load a note's pitch, so `$D400/1` keep what
  the last frame left; the block's first entry carries `WAVE_NOTE_KEEP`.
  Pointing at the record's start wrote the played note there and moved
  Knucklebusters' tie count off the original's by a frame at every rest.
* **one call of delay** (`REST_RESTART_DELAY`). Our rest rows are laid out in
  whole calls and a third of Knucklebusters' land a call BEFORE the
  original's frame (-S3: row start at call 3F-1, sampled in frame F-1), which
  starts the toggle a frame early. A call of delay moves it into frame F; the
  rows already inside the frame (calls 3F, 3F+1) stay inside. The cost is the
  rows that land on call 3F+2 (a frame late): 20 wrong wave frames remain in
  the first 60 s of Knucklebusters voice 1, against 340 with no restart.
  MEASURED, not derived -- the per-song constant that remains (finding.md):
  Knucklebusters `wave` at 180 s, D = 0 .9826, D = 1 .9961, D = 2 .9807.

Written under `rest_reseed`'s conditions, which are the same question asked of
a different command: the row's command column must be free (the pointer is a
one-shot, and a rest that already carries a command keeps it), and the
channel's running command must be `CMD_DONOTHING`, so a pointer on the row
after a slide does not carry the slide into the rest. Every pass through an
orderlist position must agree, and a pattern its positions want differently
is cloned, as there. Where the table has no room for the blocks, the pointer
names the record's own start.

Only records whose finished program IS the alternation are touched
(`alternating_records`): bit $02 set, the player's alternate read as a
waveform, and that waveform present in the program with a loop back into it.
Everything else (a drum's gate-off program, an arpeggio's, a record the
alternation declined) keeps the plain KEYOFF.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETWAVEPTR, GT_MAX_TABLELEN, WAVE_MAX_DELAY,
                        WAVE_NOTE_KEEP, _SONG_MAX_PATTERNS)
from .rest_reseed import _rest_reseed_plan

# The effect byte's bit that selects the alternation (`AND #$02`).
ALTERNATE_BIT = 0x02

# Calls a restart waits before it starts over; see `restart_block`.
REST_RESTART_DELAY = 1


def alternating_records(sid: SidFile, det: Detection,
                        wave_entries: List[Tuple[int, int]],
                        wave_starts: List[int], instr_used: int,
                        lead: int) -> Dict[int, int]:
    """{GT instrument number: wavetable start} of every record whose
    finished program is the tabled alternation.

    The program is read off the table, not re-derived: a record the
    alternation declined (an alternate equal to `+2`, a budget that did not
    fit) or that another block owns (the arpeggio's, the drum's) carries no
    entry naming the alternate waveform, and is left out."""
    out: Dict[int, int] = {}
    if det.wave_alternate < 0 or det.instr_start < 0 or det.instr_stride <= 0:
        return out
    data = sid.data
    for i in range(max(instr_used - lead, 0)):
        if i + lead >= len(wave_starts) or not wave_starts[i + lead]:
            continue
        rec = det.instr_start + i * det.instr_stride
        a = det.wave_alternate + i * det.instr_stride
        if rec + 7 >= len(data) or a >= len(data):
            continue
        if not data[rec + 7] & ALTERNATE_BIT:
            continue
        alt = data[a]
        if alt <= WAVE_MAX_DELAY:
            continue
        start = wave_starts[i + lead]
        pos = start - 1
        seen = False
        looped = False
        while 0 <= pos < len(wave_entries):
            left, right = wave_entries[pos]
            if left == 0xFF:
                looped = bool(right) and start <= right <= pos + 1
                break
            if left >= 0xF0:
                break
            if left > WAVE_MAX_DELAY and (left & 0xFE) == (alt & 0xFE):
                seen = True
            pos += 1
        if seen and looped:
            out[i + lead + 1] = start & 0xFF
    return out


def restart_block(wave_entries: List[Tuple[int, int]], start: int,
                  delay: int = REST_RESTART_DELAY) -> List[Tuple[int, int]]:
    """The rows a rest's pointer names: `delay` calls of nothing, the record's
    lead with its frequency writes taken out, and a jump to the pair.

    The rest's frame 0 is the fetch's tail with no pitch of its own: the
    waveform is written and `$D400/1` keep what the last frame left (W_A_R
    `$E7ED` is reached without `$E536-$E54F`, which load a NOTE's pitch), so
    the lead's first entry carries `WAVE_NOTE_KEEP` and not the played note.
    Every later entry of the copied lead keeps its own right side: the drum-
    gate shape has a gated half of the pair BEFORE its loop target
    (Knucklebusters instrument 2, `15 01 15 01 | 80 01 14 01`), and that half
    is frame 1, whose `$D400` is the note's own (`$E798-$E7A8`).
    `delay` holds the waveform already set for that many calls first (a delay
    entry is current for `value + 1` calls, so `delay - 1` here; `$00` is
    one): our rest rows land up to a call before the original's frame on a
    third of Knucklebusters' rests, which samples the restart a frame early.
    Empty where the program has no lead to copy."""
    pos = start - 1
    left, right = wave_entries[pos]
    if left == 0xFF or left >= 0xF0:
        return []
    # The loop target is the pair; everything before it is the lead.
    end = pos
    while end < len(wave_entries) and wave_entries[end][0] != 0xFF:
        end += 1
    if end >= len(wave_entries):
        return []
    target = wave_entries[end][1]
    if not (start < target <= end):
        return []
    block: List[Tuple[int, int]] = []
    if delay > 0:
        block.append((delay - 1, WAVE_NOTE_KEEP))
    for k in range(start - 1, target - 1):
        lft, rgt = wave_entries[k]
        # Only the fetch frame's own write loses its pitch: what follows the
        # lead (a gated half before the loop, as the drum-gate shape has one)
        # is the next frame's and keeps its note.
        block.append((lft, WAVE_NOTE_KEEP if k == start - 1 else rgt))
    block.append((0xFF, target & 0xFF))
    return block


def rest_wave_restarts(sid: SidFile, det: Detection,
                       tracks: List[List[int]], patterns: List[List[int]],
                       wave_entries: List[Tuple[int, int]],
                       wave_starts: List[int], instr_used: int, lead: int,
                       log=None, delay: int = REST_RESTART_DELAY) -> tuple:
    """(patterns, tracks, written): `CMD_SETWAVEPTR` to the record's start on
    every KEYOFF row whose current instrument is an alternating record,
    under the module docstring's conditions. Changed patterns and tracks are
    COPIES; clones are appended."""
    starts = alternating_records(sid, det, wave_entries, wave_starts,
                                 instr_used, lead)
    if not starts:
        return patterns, tracks, 0, wave_entries
    plan, skipped = _rest_reseed_plan(tracks, patterns, starts, set(starts),
                                      ties=False)
    # Only a pointer some row ended up with gets a block: an alternating
    # record no KEYOFF row follows costs the table nothing.
    used = sorted({start for want in plan.values() for _row, start in want})
    wave_entries = list(wave_entries)
    blocks = {ptr: restart_block(wave_entries, ptr, delay) for ptr in used}
    fit = len(wave_entries) + sum(len(b) for b in blocks.values()
                                  ) <= GT_MAX_TABLELEN
    remap: Dict[int, int] = {}
    for ptr in used:
        block = blocks[ptr]
        if not block or not fit:
            continue            # the plain pointer: no room, or no lead
        remap[ptr] = (len(wave_entries) + 1) & 0xFF
        wave_entries.extend(block)
    groups: Dict[int, Dict[frozenset, list]] = {}
    for (ti, pos), want in plan.items():
        groups.setdefault(tracks[ti][pos], {}).setdefault(want, []).append(
            (ti, pos))
    out = list(patterns)
    new_tracks = [list(t) for t in tracks]
    written = clones = full = 0

    def patched(b: int, want: frozenset) -> List[int]:
        rows = list(patterns[b])
        for row, start in want:
            rows[4 * row + 2], rows[4 * row + 3] = (
                CMD_SETWAVEPTR, remap.get(start, start))
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
        log(f"Rest wave restart.......: CMD_SETWAVEPTR on {written} "
            f"row(s) over the orderlists, {clones} pattern copy(ies)"
            + "".join(f", {n} {why}" for why, n in sorted(skipped.items()))
            + (f", {full} position(s) left alone: pattern table full"
               if full else ""))
    return out, new_tracks, written, wave_entries
