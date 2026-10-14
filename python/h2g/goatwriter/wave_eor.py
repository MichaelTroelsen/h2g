"""Effect bit $02's EOR toggle (Rasputin): a per-note phase, emitted.

`detect._find_wave_eor` reads the block (detect.WAVE_EOR_SHAPE, Rasputin
`$C35A`): on every second effect call, counted on a per-voice cell
(`$C533,X`) that nothing else writes and nothing resets, the voice's stored
waveform is EORed with `#$18` (triangle + TEST) and written to `$D404` with
its gate as stored. The block stops on the note's last tick (`$C512` = 0).

**The phase is per NOTE, and the orderlist walk knows it.** The fetch call
runs no effect, so a note of L ticks spends `2 * (L - 1) - 1` effect calls on
the counter -- odd, so every bit-$02 note of two ticks or more FLIPS the
voice's phase, and a one-tick note (the block never runs) leaves it. On a
note whose counter reads 0 the toggle lands on the first effect call (frame
1); on one reading 1 a call later, the first call of the note's second tick.
The residue is therefore the event PARITY on the voice, and the period is
one tick: the row's tempo in our calls. Walked over the finished
orderlists (`wave_eor_note_residues`) it predicts the original's phase on
416 of 416 record-10 notes and 128 of 128 record-4 notes of subtune 0 in
180 s (`tests/test_wave_eor_emit.py` re-derives it against the trace's own
release byte, `$58`/`$5A` after a toggled end and `$40`/`$42` after an
untoggled one).

A wavetable restarts at every note, so one record cannot carry both
phases: `wave_eor_split_plan` clones the record per (phase, period) the way
`arpeggio._note_phase_split` clones a fixed arp per counter residue, and the
record's own block carries the majority (`wave_eor_note_residues`' first
value).

**The period is not a number of calls where the gate skips often.** The
"effect call" the counter counts is a WORKING call of the outer gate, which
`$FE nn` restarts and skips one frame in R + 1 (`gate_tick`): a tick is two
working calls and 2 (R + 1) / R frames, 2.67 at R = 3 and 2.4 at R = 5, so
the toggles land on frames 2 or 3 apart in a cycle, and where in the cycle
a note's fetch falls moves each of its toggles. A fixed loop of the rounded
tick (the first emission, still the residue where the clock is not read)
agrees on 0.84 / 0.83 of those notes' frames. `gate_restart_rows` reads the
restarts' rows off the orderlists (convert.py, as `det.gate_restarts`),
`clock_residue` names the note's place in the cycle (`EorPhase.family`,
`.pos`), and `eor_library` lays the cycles out once for the residues to jump
into: a ring of nodes per R, a node being one toggle's state held for the
frames to the next. R = 2, 3 and 5 get a ring; every other R (10, 60, 120
and the closing 6) is read as a gate that does not skip inside a note.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETTEMPO, CMD_TONEPORTA, GT_FIRST_NOTE,
                        GT_KEYOFF, GT_LAST_NOTE, GT_WAVE_JUMP,
                        WAVE_MAX_DELAY, WAVE_NOISE_GATEOFF, WAVE_NOTE_BASE)
from .primitives import _first_frame_entry

# The effect byte's bit the block tests (`AND #$02`).
WAVE_EOR_EFFECT_BIT = 0x02
# The drum bit: such a record's block is the drum's (`_wavetable_entries`'
# noise tick and gate-off tail), and the toggle lands on it.
WAVE_EOR_DRUM_BIT = 0x01
# The arpeggio bit: a record setting it without the drum keeps its own block
# (no corpus record does; the toggle would need the arpeggio's entries too).
WAVE_EOR_ARP_BIT = 0x04
# Goattracker's KEYON row byte (gcommon.h:52) -- an event, like a note.
GT_KEYON = 0xBF


@dataclass(frozen=True, order=True)
class EorPhase:
    """A bit-$02 note's toggle, as a phase clone carries it.

    `phase` is the voice's counter on the attack: 0 toggles on the first
    effect call (the note's frame 1), 1 on the second (the first call of its
    second tick), -1 never (a one-tick note, or a drum record's note that
    keeps the drum's own shape). `period` is the note's tick in our calls,
    0 where the block does not depend on it. Its own type -- not an int (the
    fixed arp's residue) nor a tuple (bit $10's) -- so `_wavetable_layout`
    routes it to `wave_eor_block` and nothing else.

    `family` and `pos` are the note's place on the ORIGINAL'S gate clock
    (`gate_phase`), where the walk can read it: `family` is the outer gate's
    reload R of the segment the note starts in when the library has a cycle
    for it (`GATE_FAMILIES`), 0 for any other R, whose skip comes too rarely
    to fall inside a note; -1 for a residue read without the clock. `pos` is
    `(m + c) % R`, the toggle's working-call index modulo the cycle (0 for
    family 0). `period` is, on such a residue, the frames from the attack to
    the first toggle: the block is the clock's, not a fixed loop."""
    phase: int
    period: int
    family: int = -1
    pos: int = 0


NO_TOGGLE = EorPhase(-1, 0)


def _record_effect(sid: SidFile, det: Detection, i: int) -> int:
    at = det.instr_start + i * det.instr_stride + 7
    return sid.data[at] if 0 <= at < len(sid.data) else 0


def _is_drum(sid: SidFile, det: Detection, i: int) -> bool:
    return bool(det.effect_drum
                and _record_effect(sid, det, i) & WAVE_EOR_DRUM_BIT)


def eor_records(sid: SidFile, det: Detection, instr_used: int, lead: int,
                aliases: Optional[Dict[int, int]] = None) -> Dict[int, int]:
    """{GT number: record index} of every record whose +7 sets bit $02, in
    a file where `_find_wave_eor` read the block -- and each alias (another
    split's clone, `aliases` {clone: its record's GT number}) of one."""
    if det.wave_eor is None:
        return {}
    out = {}
    for i in range(max(instr_used - lead, 0)):
        if _record_effect(sid, det, i) & WAVE_EOR_EFFECT_BIT:
            out[i + lead + 1] = i
    for clone, base in (aliases or {}).items():
        if base in out:
            out[clone] = out[base]
    return out


def _plays(tracks: List[List[int]], patterns: List[List[int]]):
    """(track, position, play, pattern) in play order -- the walk
    `arpeggio._note_phase_split` renames in, so the keys agree."""
    from .arpeggio import _orderlist_occurrences
    for ti, track in enumerate(tracks):
        seen = Counter()
        for pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            yield ti, pos, seen[pos], p
            seen[pos] += 1


def _row_tempos(tracks: List[List[int]], patterns: List[List[int]],
                g: int) -> List[List[Optional[int]]]:
    """Per voice of subtune `g`, the calls each row of one lap plays for:
    the last `CMD_SETTEMPO` at or before it -- a global one (operand below
    `$80`) from any of the three voices, Goattracker's rows advancing in
    lockstep, or the voice's own (`$80` and up). None before the first."""
    lengths = []
    events: List[Tuple[int, int, int]] = []    # (row, voice or -1, calls)
    for v in range(3):
        row = 0
        for ti, _pos, _play, p in _plays(tracks[3 * g + v:3 * g + v + 1],
                                         patterns):
            pat = patterns[p]
            for k in range(len(pat) // 4):
                if pat[4 * k] == 0xFF:
                    break
                if pat[4 * k + 2] == CMD_SETTEMPO:
                    d = pat[4 * k + 3]
                    events.append((row, -1 if d < 0x80 else v, d & 0x7F))
                row += 1
        lengths.append(row)
    out = []
    for v in range(3):
        cur: Optional[int] = None
        mine = sorted((r, c) for r, who, c in events if who in (-1, v))
        rows: List[Optional[int]] = []
        j = 0
        for r in range(lengths[v]):
            while j < len(mine) and mine[j][0] <= r:
                cur = mine[j][1]
                j += 1
            rows.append(cur)
        out.append(rows)
    return out


# --- the original's outer gate, as a clock ------------------------------------
#
# Rasputin's `$FE nn` restarts the outer gate (`detect.track_fe_restarts_gate`):
# R working calls, then one skipped frame, counted from the call that read the
# change. The speed gate is untouched, so a row is `frames` (2) working calls
# whatever R is, and the effect block toggles on every second one. A note
# fetching at working call `m` of its segment therefore toggles at working
# calls `m + c + 2j` (c = 1 on counter phase 0, 2 on phase 1), and the frame a
# working call lands on is `gate_tick`. Where a note's first toggle falls, and
# every one after it, is a function of `m % R` alone.
#
# Measured against the trace, the 376 toggling record-10 notes of subtune 0 in
# 180 s: the model names every toggle frame of every note, all 376
# (`tests/test_wave_eor_clock.py` re-derives it).

# The segment reloads that get a cycle of their own in the library. Rasputin's
# others (10, 60, 120 and the 6 of the closing minutes) skip a frame too
# rarely for it to land inside one note, or cost a cycle the 255-entry
# wavetable has no room for (a cycle is `2R` nodes of two entries).
GATE_FAMILIES = (2, 3, 5)


def gate_tick(R: int, m: int) -> int:
    """The frame, counted from the change that restarted the gate, on which
    working call `m` runs: the call that read the change is call 0 on frame
    0, calls 1..R follow on the next frames, and the call after R is
    skipped (`tempo.restarted_gate_calls`). `R` 0 is a gate that never skips
    inside a note."""
    if not R or m < 1:
        return m
    return m + (m - 1) // R


def node_frames(R: int, w: int) -> int:
    """Frames from the toggle at working call `w` to the next one (`w + 2`).
    Periodic in `w` with period R; `w` 0 is read as R."""
    if not R:
        return 2
    w = (w - 1) % R + 1
    return gate_tick(R, w + 2) - gate_tick(R, w)


def gate_restart_rows(tracks: List[List[int]], track_index, patterns,
                      clocks: List[dict], floor: int) -> Optional[dict]:
    """Where the outer gate restarts, in rows from the start of its subtune.

    `tracks` are the orderlists as `reindex_tracks` takes them (the player's
    numbering, commands from `floor` up), `track_index[b]` the Goattracker
    patterns pattern `b` became and `clocks` `orderlist_tempo_clocks`'
    {orderlist position: (frames, R, multiplier)} per track. Every voice of a
    subtune plays the same rows at the same time, so the restart a track's
    command makes is a row of all three:

        {"groups": subtunes, "rows": [rows one lap of each track plays],
         "restarts": {subtune: [(row, frames, R), ...] sorted}}

    None where no track carries a restart."""
    restarts: Dict[int, list] = {}
    totals = []
    for ti, track in enumerate(tracks):
        at_row = {}
        row = 0
        for at, b in enumerate(track):
            at_row[at] = row
            if b == 0xFF:
                break
            if b >= floor:
                continue
            if b < len(track_index):
                for p in track_index[b]:
                    pat = patterns[p]
                    row += next((k for k in range(len(pat) // 4)
                                 if pat[4 * k] == 0xFF), len(pat) // 4)
        totals.append(row)
        for at, (frames, R, _mult) in (clocks[ti] if ti < len(clocks)
                                       else {}).items():
            if at in at_row:
                restarts.setdefault(ti // 3, []).append(
                    (at_row[at], frames, R))
    if not restarts:
        return None
    return {"groups": len(tracks) // 3, "rows": totals,
            "restarts": {g: sorted(v) for g, v in restarts.items()}}


def gate_phase(det: Detection, group: int, row: int):
    """(working calls since the gate's last restart, its R) for a call
    fetching on `row` of subtune `group`, or None where no restart is read."""
    gr = getattr(det, "gate_restarts", None)
    if not gr:
        return None
    seen = [x for x in gr["restarts"].get(group, ()) if x[0] <= row]
    if not seen:
        return None
    r0, frames, R = seen[-1]
    return frames * (row - r0), R


def _gate_valid(det: Detection, tracks: List[List[int]],
                rows: Dict[int, int]) -> bool:
    """Whether the finished orderlists are the ones `det.gate_restarts` was
    read from: the same number of subtunes, and no voice shorter than its
    original (a lap that plays FEWER rows than the original's has lost some,
    and every row after the loss is on the wrong clock)."""
    gr = getattr(det, "gate_restarts", None)
    if not gr or gr["groups"] != len(tracks) // 3:
        return False
    return all(rows.get(ti, 0) >= gr["rows"][ti] for ti in range(len(tracks)))


def _event_rows(tracks: List[List[int]], patterns: List[List[int]],
                ti: int) -> Tuple[Dict[tuple, int], int]:
    """({((track, orderlist position, play), row in pattern): rows since the
    start of the subtune}, rows in one lap) of track `ti`."""
    out: Dict[tuple, int] = {}
    row = 0
    for _ti, pos, play, p in _plays([tracks[ti]], patterns):
        pat = patterns[p]
        for k in range(len(pat) // 4):
            if pat[4 * k] == 0xFF:
                break
            out[((ti, pos, play), k)] = row
            row += 1
    return out, row


def clock_residue(det: Detection, group: int, row: int,
                  phase: int) -> Optional[EorPhase]:
    """The note's `EorPhase` on the original's gate clock, or None where the
    clock is not read. `phase` is the counter on the attack (0 or 1)."""
    st = gate_phase(det, group, row)
    if st is None:
        return None
    m, R = st
    family = R if R in GATE_FAMILIES else 0
    c = 1 if phase == 0 else 2
    first = gate_tick(family, m + c) - gate_tick(family, m)
    return EorPhase(phase, first, family, (m + c) % family if family else 0)


@dataclass
class EorLibrary:
    """The cycles the clocked residues jump into, laid out once, right after
    the wavetable's leading blocks. `nodes[(wave, R, state, w)]` is the
    1-based position of the node that holds `state` (0 the record's wave, 1
    the toggled one) from the toggle at working call `w` (mod R) to the next:
    `_hold` of `node_frames(R, w)` frames, two entries, and a ring's last
    entry jumps back to its first."""
    start: int
    left: List[int]
    right: List[int]
    nodes: Dict[Tuple[int, int, int, int], int]


def eor_library(waves: List[Tuple[int, int]], multiplier: int,
                start: int) -> EorLibrary:
    """`(wave, toggled wave)` pairs -> their rings, from position `start`.
    A ring is the nodes (state, w) -> (other state, w + 2 mod R) until it
    closes: one ring of 2R nodes for an odd R, two of R for an even one (the
    toggle's working call keeps its parity), and two nodes for R 0."""
    m = max(1, multiplier)
    left: List[int] = []
    right: List[int] = []
    nodes: Dict[Tuple[int, int, int, int], int] = {}
    for wave, alt in sorted(set(waves)):
        for R in (0,) + GATE_FAMILIES:
            seen = set()
            for w0 in (range(R) if R else (0,)):
                for s0 in (0, 1):
                    if (s0, w0) in seen:
                        continue
                    ring_start = start + len(left)
                    s, w = s0, w0
                    while (s, w) not in seen:
                        seen.add((s, w))
                        nodes[(wave, R, s, w)] = start + len(left)
                        hl, hr = _hold(alt if s else wave,
                                       node_frames(R, w) * m)
                        left += hl
                        right += hr
                        s, w = 1 - s, ((w + 2) % R if R else 0)
                    left.append(GT_WAVE_JUMP)
                    right.append(ring_start & 0xFF)
    return EorLibrary(start, left, right, nodes)


def note_parities(sid: SidFile, det: Detection, tracks: List[List[int]],
                  patterns: List[List[int]], instr_used: int, lead: int,
                  aliases: Optional[Dict[int, int]] = None) -> List[tuple]:
    """Every bit-$02 event of one lap, in play order per track: `(track,
    (track, orderlist position, play), row in pattern, GT number, record,
    rows it lasts, the counter on its attack, quiet, mean row tempo or
    None)`. `quiet` is a tied row or a key-off/key-on, which restarts no
    wavetable. The walk is `wave_eor_note_residues`'; see there."""
    records = eor_records(sid, det, instr_used, lead, aliases)
    out: List[tuple] = []
    if not records:
        return out
    for g in range(len(tracks) // 3):
        tempos = _row_tempos(tracks, patterns, g)
        for v in range(3):
            ti = 3 * g + v
            rows = tempos[v]
            evs = []                         # (row, key, k, gt, quiet)
            row, cur = 0, 0
            for _ti, pos, play, p in _plays([tracks[ti]], patterns):
                pat = patterns[p]
                for k in range(len(pat) // 4):
                    nb = pat[4 * k]
                    if nb == 0xFF:
                        break
                    if pat[4 * k + 1]:
                        cur = pat[4 * k + 1]
                    if (GT_FIRST_NOTE <= nb <= GT_LAST_NOTE
                            or nb in (GT_KEYOFF, GT_KEYON)):
                        tied = (pat[4 * k + 2] == CMD_TONEPORTA
                                and pat[4 * k + 3] == 0)
                        evs.append((row, (ti, pos, play), k, cur,
                                    tied or nb > GT_LAST_NOTE))
                    row += 1
            counter = 0
            for j, (r, key, k, gt, quiet) in enumerate(evs):
                length = (evs[j + 1][0] if j + 1 < len(evs)
                          else len(rows)) - r
                if gt not in records:
                    continue
                span = [c for c in rows[r:r + length] if c]
                tempo = sum(span) / length if len(span) == length else None
                out.append((ti, key, k, gt, records[gt], length, counter,
                            quiet, tempo))
                if length >= 2:
                    counter ^= 1
    return out


def wave_eor_note_residues(sid: SidFile, det: Detection,
                           tracks: List[List[int]],
                           patterns: List[List[int]], instr_used: int,
                           lead: int,
                           aliases: Optional[Dict[int, int]] = None
                           ) -> Optional[Tuple[dict, dict]]:
    """(phases, residues): {GT number: the record's majority `EorPhase`}
    and {(track, orderlist position, play): {row: EorPhase}} for every
    untied bit-$02 note, or None where the block was not read.

    Each subtune's voices are walked one lap in play order with the counter
    at 0 (its image bytes; init never writes it). An event is any row that
    fetches -- a note, tied or not, a key-off or a key-on -- and lasts until
    the voice's next; one under a bit-$02 record (an alias counts as its
    record) of two rows or more flips the voice's phase after it is read
    (`note_parities`). A tied row restarts no wavetable, so it flips the
    counter and takes no residue. A note's residue:

    * one row, or two rows on counter 1: `NO_TOGGLE` -- the block never
      toggles before the note's last tick, where it does not run;
    * two rows on counter 0, or a drum record's note on counter 0:
      `EorPhase(0, 0)`, one toggle on the first effect call, held;
    * a drum record's note on counter 1: `NO_TOGGLE` (the drum's own
      shape; a longer one would re-gate, which is not drawn);
    * otherwise `EorPhase(counter, period)`, the period the note's rows'
      mean tempo, rounded: a fixed loop cannot follow the fractional-row
      runs inside it. A note whose rows carry no tempo takes none.

    The majority is by note count, the lowest residue breaking a tie.
    """
    if not eor_records(sid, det, instr_used, lead, aliases):
        return None
    residues: dict = {}
    votes: Dict[int, Counter] = {}
    # The original's gate clock, where `det.gate_restarts` was read and the
    # finished orderlists are the ones it was read from.
    rowmap: Dict[int, dict] = {}
    laps: Dict[int, int] = {}
    for ti in range(len(tracks)):
        rowmap[ti], laps[ti] = _event_rows(tracks, patterns, ti)
    clocked = _gate_valid(det, tracks, laps)
    for ti, key, k, gt, i, length, phase, quiet, tempo in note_parities(
            sid, det, tracks, patterns, instr_used, lead, aliases):
        if quiet:
            continue
        if length < 2:
            res = NO_TOGGLE
        elif length == 2 or _is_drum(sid, det, i):
            res = EorPhase(0, 0) if phase == 0 else NO_TOGGLE
        else:
            res = (clock_residue(det, ti // 3, rowmap[ti][(key, k)], phase)
                   if clocked else None)
            if res is None:
                if tempo is None:
                    continue
                res = EorPhase(phase, int(tempo + 0.5))
        residues.setdefault(key, {})[k] = res
        votes.setdefault(gt, Counter())[res] += 1
    if not votes:
        return None
    phases = {gt: max(sorted(c), key=lambda s: c[s])
              for gt, c in votes.items()}
    return phases, residues


def _hold(w: int, calls: int) -> Tuple[List[int], List[int]]:
    """Entries sounding waveform `w` for `calls` of our calls: the waveform
    entry (one call) and a delay current for `value + 1` calls
    (gplay.c:697-704) -- `_wave_hold_byte`'s arithmetic."""
    if calls <= 0:
        return [], []
    left, right = [w], [WAVE_NOTE_BASE]
    rest = calls - 1
    while rest > 0:
        if rest == 1:
            left.append(w)
            right.append(WAVE_NOTE_BASE)
            rest = 0
        else:
            d = min(rest - 1, WAVE_MAX_DELAY)
            left.append(d)
            right.append(WAVE_NOTE_BASE)
            rest -= d + 1
    return left, right


def wave_eor_block(sid: SidFile, det: Detection, i: int, eor: EorPhase,
                   block: Optional[tuple], multiplier: int,
                   start: Optional[int], budget: int,
                   written: bool = False,
                   library: Optional[EorLibrary] = None):
    """Record `i`'s wavetable block under toggle `eor`, from `block` -- the
    block `_wavetable_entries` lays out for it with no toggle.

    * A residue on the original's gate clock (`eor.family` >= 0) is the
      library's (`eor_library`): on counter phase 1 the note's first tick is
      a whole node, so the answer is an INT, the position to start the
      instrument's wave pointer at -- one entry in, where the firstwave has
      already sounded the note's first call (`written`); on phase 0 it holds
      the record's wave for the frames up to the first toggle and jumps to
      the node that toggles it. The block is None-safe: without a library
      (or a node for it) `block` stands.

    * A drum record (`+7` bit $01 read): the toggle runs after the drum
      (Rasputin `$C31E` then `$C35A`) and overwrites its noise tick, so on
      phase 0 the tick's entries take `wave ^ mask` (gate as stored) and the
      gate-off tail `(wave ^ mask) & $FE` -- record 4 `43 5B 5A 5A` where
      the drum alone reads `43 80 42 42`, both traced. Exact for the
      two-tick notes the record plays (all 128 in subtune 0); a longer note
      would re-gate on every toggle call, which this does not draw.
    * Any other record: the frame-0 lead (`frame0` calls of `+2`: one
      frame, `multiplier` calls), then -- phase 1 -- the rest of the first
      tick, then halves of `period` calls, `wave ^ mask` first, looping.
      With `written` (the instrument's firstwave owns the init call) the
      entries start a call later and the lead is a call shorter.
    * `NO_TOGGLE`, or a record that also sets the arpeggio bit without the
      drum: `block` unchanged.
    """
    if block is None or eor.phase < 0 or det.wave_eor is None:
        return block
    data = sid.data
    base = det.instr_start + i * det.instr_stride
    wave = data[base + 2]
    mask = det.wave_eor.mask
    alt = wave ^ mask
    if eor.family >= 0:
        if (library is None or _is_drum(sid, det, i)
                or _record_effect(sid, det, i) & WAVE_EOR_ARP_BIT
                or not _first_frame_entry(wave)):
            return block
        R, p0, frames = eor.family, eor.pos, eor.period
        # Counter phase 1 starts on a whole node when the first toggle is a
        # full node's length away (every note but a segment's opening one,
        # whose first row has no skip behind it); anything else holds the
        # wave for `frames` frames (`period`) and jumps to the node that
        # toggles it.
        w0 = (p0 - 2) % R if R else 0
        if eor.phase == 1 and frames == node_frames(R, w0):
            at = library.nodes.get((wave, R, 0, w0))
            return block if at is None else at + (1 if written else 0)
        target = library.nodes.get((wave, R, 1, p0 if R else 0))
        if target is None or frames < 1:
            return block
        m = max(1, multiplier)
        lead_l, lead_r = _hold(wave, frames * m - (1 if written else 0))
        left = lead_l + [GT_WAVE_JUMP]
        right = lead_r + [target & 0xFF]
        return (left, right) if len(left) <= budget else block
    if _is_drum(sid, det, i):
        if eor.phase != 0:
            return block
        left, right = list(block[0]), list(block[1])
        tail = wave & 0xFE
        for k, b in enumerate(left):
            if b == GT_WAVE_JUMP:
                break
            if b in (WAVE_NOISE_GATEOFF, WAVE_NOISE_GATEOFF | 1):
                left[k] = alt
            elif b == tail and k:
                left[k] = alt & 0xFE
        return left, right
    if _record_effect(sid, det, i) & WAVE_EOR_ARP_BIT:
        return block
    if start is None or not _first_frame_entry(wave):
        return block
    m = max(1, multiplier)
    if eor.period == 0:
        # One toggle, held: a two-tick note toggles on its first effect call
        # (phase 0) and never again -- its second tick is its last.
        lead_l, lead_r = _hold(wave, m - (1 if written else 0))
        left = lead_l + [alt, GT_WAVE_JUMP]
        right = lead_r + [WAVE_NOTE_BASE, 0x00]
        return (left, right) if len(left) <= budget else block
    if eor.period < 2:
        return block
    # Phase 0 toggles on the next WORKING call after the fetch. Where a
    # change restarts the outer gate (`detect.track_fe_restarts_gate`) and
    # a tick is three frames -- two working calls and one skip, R = 2 -- the
    # skip sits right after the fetch: row j >= 1 fetches on frame 3j - 1 and
    # makes its second call on 3j + 1 (`tempo.restarted_gate_calls`), so the
    # toggle is two frames in. Traced: `41 41 59 59 59 41 41 41 59 58 58 58`.
    skip_first = (eor.phase == 0 and eor.period == 3 * m
                  and getattr(det, "track_fe_restarts_gate", False))
    first = (2 * m if skip_first else m) if eor.phase == 0 \
        else max(eor.period, m)
    lead_l, lead_r = _hold(wave, first - (1 if written else 0))
    a_l, a_r = _hold(alt, eor.period)
    b_l, b_r = _hold(wave, eor.period)
    left = lead_l + a_l + b_l + [GT_WAVE_JUMP]
    right = lead_r + a_r + b_r + [(start + len(lead_l)) & 0xFF]
    if len(left) > budget:
        return block
    return left, right


def carry_split_edits(tracks: List[List[int]], new_tracks: List[List[int]],
                      edits: dict) -> dict:
    """Another split's `{pattern: {row: (byte now, byte wanted)}}` with each
    pattern this plan copied given its source's edits: the two plans'
    instrument bytes are both written last (`apply_tempo_duty_edits`), and
    a copy made after the other plan was keyed would otherwise play its
    source's rows under the un-renamed instrument. Read off the orderlists:
    a position whose byte moved names a copy of what it named before."""
    out = {p: dict(rows) for p, rows in edits.items()}
    for old, new in zip(tracks, new_tracks):
        for a, b in zip(old, new):
            if a != b and a in edits:
                out.setdefault(b, dict(edits[a]))
    return out


def wave_eor_split_plan(sid: SidFile, det: Detection,
                        tracks: List[List[int]],
                        patterns: List[List[int]], instr_used: int,
                        lead: int, first_clone: int, distinct=None,
                        aliases: Optional[Dict[int, int]] = None,
                        exclude: frozenset = frozenset(), log=None):
    """`arpeggio._note_phase_split` over `wave_eor_note_residues`: one clone
    per (record, minority `EorPhase`) whose block `distinct` says differs,
    every minority cloned (the factor is None: a parity splits a record's
    notes evenly by construction, so no residue is a stray). `exclude` names
    GT numbers another split already renames, which this one leaves alone.
    None where nothing would change."""
    from .arpeggio import _note_phase_split
    walked = wave_eor_note_residues(sid, det, tracks, patterns, instr_used,
                                    lead, aliases)
    if walked is None:
        return None
    phases, residues = walked
    records = set(phases) - set(exclude)
    if not records:
        return None
    return _note_phase_split(tracks, patterns, residues, phases, records,
                             first_clone, distinct, "EOR phase split", log,
                             factor=None)
