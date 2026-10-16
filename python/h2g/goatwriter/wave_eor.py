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
and the closing 6) is read as a gate that skips only on a ROW of the note, and
`eor_skip_detours` puts a pointer on that row (see "the skip row" below).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETTEMPO, CMD_SETWAVEPTR, CMD_TONEPORTA,
                        CMD_VIBRATO,
                        GT_FIRST_NOTE, GT_KEYOFF, GT_LAST_NOTE, GT_REST,
                        GT_WAVE_JUMP, GT_WAVE_NO_NOTE, WAVE_MAX_DELAY, WAVE_NOISE_GATEOFF,
                        WAVE_NOTE_BASE)
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
# rarely for it to land inside every note, or cost a cycle the 255-entry
# wavetable has no room for (a cycle is `2R` nodes of two entries; R = 10's
# two rings are 42 rows): their skip is a pointer on its row instead
# (`eor_skip_detours`).
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
    # A gate with no ring still skips: the first toggle is late when the
    # skip falls between the fetch and it (`m` on a multiple of R).
    first = gate_tick(R, m + c) - gate_tick(R, m)
    return EorPhase(phase, first, family, (m + c) % family if family else 0)


@dataclass
class EorLibrary:
    """The cycles the clocked residues jump into, laid out once, right after
    the wavetable's leading blocks. `nodes[(wave, R, state, w)]` is the
    1-based position of the node that holds `state` (0 the record's wave, 1
    the toggled one) from the toggle at working call `w` (mod R) to the next:
    `_hold` of `node_frames(R, w)` frames, two entries, and a ring's last
    entry jumps back to its first.

    `detours[(wave, state)]` is a skip row's program (`eor_skip_detours`):
    `state` written and held `DETOUR_FRAMES` frames, then a jump into the R = 0
    ring at the other state. Entered one row in -- at its delay -- it is the
    plain wait of `DETOUR_FRAMES * 2 - 1` calls, state already there.
    `owner[row - start]` names what each row belongs to,
    `(wave, R, state, w)` for a node and `("d", wave, state)` for a detour,
    None for a ring's closing jump."""
    start: int
    left: List[int]
    right: List[int]
    nodes: Dict[Tuple[int, int, int, int], int]
    detours: Dict[Tuple[int, int], int] = field(default_factory=dict)
    owner: List[Optional[tuple]] = field(default_factory=list)


# Frames the node after a skip row's toggle is held: the skip adds one to the
# ring's two (`eor_skip_detours`).
DETOUR_FRAMES = 3


def eor_library(waves: List[Tuple[int, int]], multiplier: int,
                start: int, detours: bool = False) -> EorLibrary:
    """`(wave, toggled wave)` pairs -> their rings, from position `start`.
    A ring is the nodes (state, w) -> (other state, w + 2 mod R) until it
    closes: one ring of 2R nodes for an odd R, two of R for an even one (the
    toggle's working call keeps its parity), and two nodes for R 0. A ring
    whose nodes hold exactly what an earlier one's do is that ring: R = 2's
    second ring is its first (its nodes are all three frames), five rows
    back. With `detours` each pair also gets the two detour nodes."""
    m = max(1, multiplier)
    left: List[int] = []
    right: List[int] = []
    owner: List[Optional[tuple]] = []
    nodes: Dict[Tuple[int, int, int, int], int] = {}
    for wave, alt in sorted(set(waves)):
        rings: Dict[tuple, List[int]] = {}
        for R in (0,) + GATE_FAMILIES:
            seen = set()
            for w0 in (range(R) if R else (0,)):
                for s0 in (0, 1):
                    if (s0, w0) in seen:
                        continue
                    ring_start = start + len(left)
                    s, w = s0, w0
                    keys, holds = [], []
                    while (s, w) not in seen:
                        seen.add((s, w))
                        keys.append((s, w))
                        holds.append(_hold(alt if s else wave,
                                           node_frames(R, w) * m))
                        s, w = 1 - s, ((w + 2) % R if R else 0)
                    shape = tuple((k[0], tuple(h[0]), tuple(h[1]))
                                  for k, h in zip(keys, holds))
                    if shape in rings:
                        for k, at in zip(keys, rings[shape]):
                            nodes[(wave, R, k[0], k[1])] = at
                        continue
                    ats = []
                    for k, (hl, hr) in zip(keys, holds):
                        ats.append(start + len(left))
                        nodes[(wave, R, k[0], k[1])] = start + len(left)
                        left += hl
                        right += hr
                        owner += [(wave, R, k[0], k[1])] * len(hl)
                    rings[shape] = ats
                    left.append(GT_WAVE_JUMP)
                    right.append(ring_start & 0xFF)
                    owner.append(None)
    lib = EorLibrary(start, left, right, nodes, owner=owner)
    if detours:
        for wave, alt in sorted(set(waves)):
            for s in (0, 1):
                # The state held three frames, then the ring at the other.
                hl, hr = _hold(alt if s else wave, DETOUR_FRAMES * m)
                lib.detours[(wave, s)] = start + len(left)
                left += hl + [GT_WAVE_JUMP]
                right += hr + [nodes[(wave, 0, 1 - s, 0)] & 0xFF]
                owner += [("d", wave, s)] * len(hl) + [None]
    return lib


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
        if not R:
            # A gate with no ring, its skip right after the fetch: the first
            # toggle is a node's length away on phase 0 (two frames), and a
            # skip row's three on phase 1 -- the detour node, which holds the
            # wave that long and enters the ring at the toggled one.
            if eor.phase == 0 and frames == node_frames(0, 0):
                at = library.nodes.get((wave, 0, 0, 0))
                return block if at is None else at + (1 if written else 0)
            if eor.phase == 1 and frames == DETOUR_FRAMES:
                at = library.detours.get((wave, 0))
                if at is not None:
                    return at + (1 if written else 0)
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


# --- the last tick: the original's block does not run there --------------------
#
# The block stops on a note's last tick (`$C512` = 0), so the voice holds the
# state its last toggle left. A ring or loop in a wavetable has no such stop:
# it toggles on its schedule until the next note's fetch restarts it, and the
# schedule always puts one toggle inside the last tick (the note spends an odd
# number of effect calls before it). Measured at c4eedc4, Rasputin record 10,
# subtune 0 in 180 s: the original changes the waveform on 0 of the last-tick
# frames of 336 toggling notes, the conversion toggles once in each of the 336.
# The wavetable cannot know the note's length, but the pattern can: a
# `CMD_SETWAVEPTR` on the note's LAST row points the voice at a program that
# does nothing and stops (`EOR_STOP_PROGRAM`), so the waveform holds. The
# pointer may not name an `$FF` row itself (gplay.c:436-445 stops the song on
# a jump target), which is why the program is a no-op step then the stop.

# Right side `$80` leaves the pitch alone; left `$00` keeps the waveform.
EOR_STOP_PROGRAM = ((0x00, GT_WAVE_NO_NOTE), (GT_WAVE_JUMP, 0x00))
# The commands that set the voice's continuous effect (gplay.c:409-422);
# every other command leaves it as it was.
CMD_DONOTHING = 0
CONTINUOUS_COMMANDS = frozenset({1, 2, CMD_TONEPORTA, CMD_VIBRATO})


def eor_ring_instruments(entries: List[Tuple[int, int]],
                         starts: Dict[int, int],
                         span: Tuple[int, int]) -> frozenset:
    """The instrument numbers (keys of `starts`: number -> 1-based wavetable
    row) whose program, read from its start, never ends and jumps back into
    the EOR cycles `span` = (first, last) rows -- the ones that toggle until
    something restarts them. Delays and waveforms step one row, an `$FF` row
    jumps (no call of its own) and `$FF 00` ends the program."""
    out = set()
    for number, start in starts.items():
        at, seen = start, set()
        while 1 <= at <= len(entries) and at not in seen:
            seen.add(at)
            left, right = entries[at - 1]
            if left == GT_WAVE_JUMP:
                if right and span[0] <= right <= span[1]:
                    out.add(number)
                if not right or right in seen:
                    break
                at = right
                continue
            at += 1
    return frozenset(out)


def _orderlist_edges(tracks: List[List[int]], patterns: List[List[int]]):
    """(successors, predecessors): pattern number -> the set of pattern
    numbers the orderlists play right after / right before it.

    Walked like `note_passes._successor_heads` (repeats honoured, transposes
    skipped). `None` marks what the walk cannot name: the pattern before an
    orderlist's `$FF` (the restart target is an operand), and, among the
    predecessors, a track's first pattern and the one its restart lands on.
    """
    succ: Dict[int, set] = {}
    pred: Dict[int, set] = {}
    for track in tracks:
        seq, at, repeat = [], [], 1
        restart = 0
        for k, b in enumerate(track):
            if b == 0xFF:
                restart = track[k + 1] if k + 1 < len(track) else 0
                break
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b < len(patterns):
                seq += [b] * repeat
                at += [k] * repeat
            repeat = 1
        for a, b in zip(seq, seq[1:]):
            succ.setdefault(a, set()).add(b)
            pred.setdefault(b, set()).add(a)
        if seq:
            succ.setdefault(seq[-1], set()).add(None)
            pred.setdefault(seq[0], set()).add(None)
            for p, k in zip(seq, at):
                if k >= restart:
                    pred.setdefault(p, set()).add(None)
                    break
    return succ, pred


def _leading_rests(pat: List[int]) -> int:
    """How many rows a pattern opens with that are plain rests (no
    instrument), when the event after them is a plain note (not a tie);
    0 when it opens on anything else or the rests lead nowhere."""
    i = 0
    while i + 3 < len(pat) and pat[i] == GT_REST and not pat[i + 1]:
        i += 4
    if i == 0 or i + 3 >= len(pat):
        return 0
    nb = pat[i]
    if not GT_FIRST_NOTE <= nb <= GT_LAST_NOTE:
        return 0
    if pat[i + 2] == CMD_TONEPORTA and pat[i + 3] == 0:
        return 0
    return i // 4


def eor_stop_pass(patterns: List[List[int]], tracks: List[List[int]],
                  rings: frozenset, stop: int, log=None) -> List[List[int]]:
    """`CMD_SETWAVEPTR` to `stop` on the last row of each note of a `rings`
    instrument that lasts two rows or more.

    Declined, and counted:

    * **followed**: the next event is not a plain note. A tie
      (`CMD_TONEPORTA 00`) restarts no wavetable, so the ring runs on into it
      as the original's toggling does (the counter flips through a tie,
      `note_parities`); a key-off or key-on is a quiet event of its own.
      And a note can run on past the pattern's end: `--max-rows` slices
      long patterns, and a slice's tail is rest rows, not an event. So at the
      pattern's end every successor's first row must be a plain note.
      **Unless the successor opens on rest rows and then a plain note**: the
      note runs on through them (a slice's continuation), and its last tick
      is the last of those rest rows, where the pointer goes instead. That
      successor is edited in place, so it must be entered ONLY from such
      tails (every orderlist predecessor ends on a ring note of its own,
      none is unknown, no track starts or restarts on it); a successor that
      other notes also reach would stop theirs, and is declined (**shared**).
    * **unknown**: no row of the pattern has named the instrument and the
      orderlists enter it holding more than one.
    * **busy**: the last row's command column is taken.
    * **running**: a portamento, tone portamento or vibrato command set on
      an earlier row of the note is still running into the last row. The
      empty column is `CMD_DONOTHING` there, which ends it (gplay.c:403-406);
      `CMD_SETWAVEPTR` leaves it running. A new note zeroes the command
      first, so the walk starts from none at the note row.
    * **over**: the command would pack the pattern past
      `PACKED_PATTERN_LIMIT`.

    Changed patterns are COPIES.
    """
    if not rings or not stop:
        return patterns
    from .note_passes import _entry_instruments, _successor_heads
    from .pulse import packed_pattern_size, pattern_rows
    from .constants import PACKED_PATTERN_LIMIT
    entry = _entry_instruments(tracks, patterns)
    heads = _successor_heads(tracks, patterns)
    out: List[List[int]] = []
    placed = unfollowed = unknown = busy = over = persistent = 0
    shared = 0
    succ, pred = _orderlist_edges(tracks, patterns)
    carried: Dict[int, int] = {}     # pattern -> row offset its tail note starts
    for number, pat in enumerate(patterns):
        held = entry.get(number, ())
        live = next(iter(held)) if len(held) == 1 else 0
        ambiguous = len(held) > 1 and any(h in rings for h in held)
        events = []                  # (row offset, instrument, plain note, tie)
        stop_at = len(pat)
        i = 0
        while i + 3 < len(pat):
            nb = pat[i]
            if nb == 0xFF:
                stop_at = i
                break
            if pat[i + 1]:
                live = pat[i + 1]
            note = GT_FIRST_NOTE <= nb <= GT_LAST_NOTE
            tie = note and pat[i + 2] == CMD_TONEPORTA and pat[i + 3] == 0
            if note or nb in (GT_KEYOFF, GT_KEYON):
                events.append((i, live, note and not tie, tie))
            i += 4
        copy = None
        for j, (at, ins, plain, _tie) in enumerate(events):
            if not plain:
                continue
            if ins not in rings:
                unknown += 1 if not ins and ambiguous else 0
                continue
            end = events[j + 1][0] if j + 1 < len(events) else stop_at
            if (end - at) // 4 < 2:
                continue
            if j + 1 < len(events):
                followed = events[j + 1][2]
            else:
                followed = all(
                    h is not None and GT_FIRST_NOTE <= h[0] <= GT_LAST_NOTE
                    and not (h[2] == CMD_TONEPORTA and h[3] == 0)
                    for h in heads.get(number, {None}))
            if not followed:
                if (j + 1 == len(events) and succ.get(number)
                        and all(s is not None and _leading_rests(patterns[s])
                                for s in succ[number])):
                    carried[number] = at
                else:
                    unfollowed += 1
                continue
            last = end - 4
            cur = copy if copy is not None else pat
            if cur[last + 2] or cur[last + 3]:
                busy += 1
                continue
            running = 0
            for r in range(at, last, 4):
                if cur[r + 2] == CMD_DONOTHING:
                    running = 0
                elif cur[r + 2] in CONTINUOUS_COMMANDS:
                    running = cur[r + 2]
            if running:
                persistent += 1
                continue
            trial = list(cur)
            trial[last + 2] = CMD_SETWAVEPTR
            trial[last + 3] = stop & 0xFF
            if packed_pattern_size(pattern_rows(trial)) > PACKED_PATTERN_LIMIT:
                over += 1
                continue
            copy = trial
            placed += 1
        out.append(pat if copy is None else copy)
    # A note that runs on into rest rows: the pointer on the last of them.
    # All its successors are such openings (`carried`'s test); a note counts
    # as placed when every successor took the pointer.
    taken: Dict[int, bool] = {}
    for number, at in carried.items():
        done = True
        for s in sorted(succ[number]):
            if s not in taken:
                taken[s] = False
                lead = _leading_rests(patterns[s])
                mates = pred.get(s, {None})
                if None in mates or not all(p in carried for p in mates):
                    shared += 1
                    continue
                cur = out[s]
                last = 4 * (lead - 1)
                if cur[last + 2] or cur[last + 3]:
                    busy += 1
                    continue
                running = 0
                for p in sorted(mates):
                    rows = list(range(carried[p], len(patterns[p]), 4))
                    walk = [patterns[p][r + 2] for r in rows
                            if patterns[p][r] != 0xFF]
                    walk += [cur[r + 2] for r in range(0, last, 4)]
                    run = 0
                    for c in walk:
                        if c == CMD_DONOTHING:
                            run = 0
                        elif c in CONTINUOUS_COMMANDS:
                            run = c
                    running = running or run
                if running:
                    persistent += 1
                    continue
                trial = list(cur)
                trial[last + 2] = CMD_SETWAVEPTR
                trial[last + 3] = stop & 0xFF
                if packed_pattern_size(pattern_rows(trial)) >                         PACKED_PATTERN_LIMIT:
                    over += 1
                    continue
                out[s] = trial
                taken[s] = True
            done = done and taken[s]
        if done:
            placed += 1
        else:
            unfollowed += 1
    if log and (placed or busy or unknown or over or unfollowed or persistent
                or shared):
        log(f"EOR last tick...........: {placed} note(s) stop their toggle "
            "on the last row"
            + (f", {unfollowed} not followed by a plain note"
               if unfollowed else "")
            + (f", {shared} rest opening(s) other notes also enter"
               if shared else "")
            + (f", {busy} with the column in use" if busy else "")
            + (f", {persistent} under a running effect" if persistent
               else "")
            + (f", {unknown} of an instrument not yet named" if unknown
               else "")
            + (f", {over} over the pack limit" if over else ""))
    return out


# --- the skip row: the gate's skip where no ring is laid out ---------------------
#
# A gate with no ring of its own (Rasputin's R = 10, 60, 120, 6: `GATE_FAMILIES`
# gives a cycle only to 2, 3 and 5 -- R = 10's would be two rings of twenty
# rows, and the table has not the room) is read as one that never skips, and
# a note whose window holds the skip has every toggle after it a frame off.
# R is even there, so the skip lands exactly on a ROW: row `i` of the note with
# `(m + 2 i) % R == 0` has its first call, then the skip, then its second call
# -- a three-frame row (`restarted_gate_calls` places our next row six calls
# on). The toggle runs once a row, on its second call on phase 0 and its first
# on phase 1, so on the skip row:
#
#   phase 0  the toggle is a frame late: the state the voice holds (`i` mod 2
#            toggles have run) stays five calls from the row start, then the
#            R = 0 ring goes on from the other state.
#   phase 1  the toggle is on time but the NEXT is a frame late: the state it
#            makes (`i` mod 2) is written and held three frames, then the ring.
#
# A `CMD_SETWAVEPTR` on the skip row's pattern row is the timer a wavetable
# does not have; it enters the library's detour (`EorLibrary.detours`) or the
# ring itself. The row is looked up on the finished orderlists as the residues
# were (`_event_rows`), and a pattern played at two places that want different
# commands is COPIED, as `classic_filter_stop.apply_stops` does.
#
# **Our row does not start where the original's does.** The tempo runs round
# the 4.4 calls a row to whole calls, so a row starts 0 to 2 calls after its
# ideal place; the pointer enters the program that many calls early on the
# state it must hold (`late`, below). A note fetched ON the skip row has no
# row to put a pointer on: `clock_residue` makes its first toggle late, and
# `wave_eor_block` enters the library by a row.

def _effect_runs_into(pat: List[int], r: int) -> bool:
    """Whether a continuous effect (`CONTINUOUS_COMMANDS`) set on an earlier
    row is still running on row `r`: an empty column ends it, a new note zeroes
    it, any other command leaves it (gplay.c:340-422)."""
    for j in range(r - 1, -1, -1):
        c = pat[4 * j + 2]
        if c in CONTINUOUS_COMMANDS:
            return True
        if c == CMD_DONOTHING or GT_FIRST_NOTE <= pat[4 * j] <= GT_LAST_NOTE:
            return False
    return False


def skip_clock(det: Detection, group: int, row: int):
    """(working calls since the gate's last restart, its R, frames a row
    works) for a row of subtune `group`, or None where no restart is read."""
    gr = getattr(det, "gate_restarts", None)
    if not gr:
        return None
    seen = [x for x in gr["restarts"].get(group, ()) if x[0] <= row]
    if not seen:
        return None
    r0, frames, R = seen[-1]
    return frames * (row - r0), R, frames


def has_skip_rows(det: Detection, multiplier: int = 2) -> bool:
    """Whether some restart of the file has an R the detours serve: even, two
    frames a row, and without a ring of its own -- and the song packs at two
    calls a frame, the length the detour programs are written in."""
    gr = getattr(det, "gate_restarts", None)
    if not gr or multiplier != 2:
        return False
    return any(frames == 2 and R and R % 2 == 0 and R not in GATE_FAMILIES
               for rs in gr["restarts"].values() for _row, frames, R in rs)


def ring0_waves(entries: List[Tuple[int, int]], starts: Dict[int, int],
                library: EorLibrary) -> Dict[int, int]:
    """{instrument number: the wave it toggles} for each instrument (keys of
    `starts`, number -> 1-based wavetable row) whose program reaches the
    library's R = 0 ring, or a detour into it, before anything else: those
    toggle on the gate with no ring of its own."""
    lo, hi = library.start, library.start + len(library.left)
    out: Dict[int, int] = {}
    for number, start in starts.items():
        at, seen = start, set()
        while 1 <= at <= len(entries) and at not in seen:
            seen.add(at)
            if lo <= at < hi:
                key = library.owner[at - lo]
                if key is not None:
                    if key[0] == "d":
                        out[number] = key[1]
                    elif key[1] == 0:
                        out[number] = key[0]
                break
            left, right = entries[at - 1]
            if left == GT_WAVE_JUMP:
                if not right:
                    break
                at = right
                continue
            at += 1
    return out


def program_waves(entries: List[Tuple[int, int]], start: int, calls: int,
                  firstwave: int = 0) -> List[int]:
    """The waveform after each of `calls` calls of the program entered at
    `start`: a waveform entry is a call, a delay `$01-$0F` holds for
    `value + 1`, `$00` keeps the wave, `$FF xx` jumps free and `$FF 00` stops.
    A `firstwave` owns the attack call and the entries begin the next."""
    out: List[int] = []
    wave = firstwave or 0
    if firstwave:
        out.append(wave)
    at, guard = start, 0
    while len(out) < calls and guard < 10 * calls + 100:
        guard += 1
        if not 1 <= at <= len(entries):
            out.append(wave)
            continue
        left, right = entries[at - 1]
        if left == GT_WAVE_JUMP:
            if not right:
                at = 0
            else:
                at = right
            continue
        if 0x01 <= left <= WAVE_MAX_DELAY:
            out += [wave] * (left + 1)
        else:
            if left:
                wave = left
            out.append(wave)
        at += 1
    return out[:calls]


def eor_skip_detours(sid: SidFile, det: Detection, tracks: List[List[int]],
                     patterns: List[List[int]], instr_used: int, lead: int,
                     aliases: Optional[Dict[int, int]],
                     entries: List[Tuple[int, int]], starts: Dict[int, int],
                     firstwaves: Dict[int, int], library: EorLibrary,
                     multiplier: int, log=None):
    """`(patterns, tracks)` with a `CMD_SETWAVEPTR` on each skip row inside a
    toggling note of an R = 0 ring instrument (see above). `entries` is the
    finished wavetable, `starts` {instrument number: wavetable row},
    `firstwaves` {instrument number: its firstwave byte} and `library` the
    one `eor_library` laid out with its detours; `aliases` maps each clone to
    the record whose bit $02 it carries (`eor_records`).

    Declined, and counted:

    * **program**: the instrument's own program does not already toggle where
      the clock puts the toggles around the skip row (`sim`, the calls
      `program_waves` reads off it) -- a note on the wrong clone is not mended
      by a mid-note jump.
    * **timing**: our row starts more than two calls after the original's
      (`late`; the tempo runs round to whole calls), or a row's tempo is not
      known.
    * **busy**: the row's command column is taken.
    * **running**: a portamento, tone portamento or vibrato set on the row
      before is still running into it (an empty column ends it, a
      `CMD_SETWAVEPTR` does not).
    * **start**: the note's pattern begins on the row (what ran before it
      is in another pattern).
    * **over**: the pattern would pack past `PACKED_PATTERN_LIMIT`, or the
      copy it needs would pass the pattern table.
    * **disagree**: a repeated orderlist entry whose plays want different
      commands keeps what all of them agree on.

    A pattern wanted differently at its positions is COPIED and only those
    positions repointed (same length, same place)."""
    from .constants import _SONG_MAX_PATTERNS
    from .pulse import packed_pattern_size, pattern_rows
    from .constants import PACKED_PATTERN_LIMIT
    if (library is None or not library.detours
            or not has_skip_rows(det, multiplier)):
        return patterns, tracks
    toggles = ring0_waves(entries, starts, library)
    if not toggles:
        return patterns, tracks
    laps: Dict[int, int] = {}
    rowmap: Dict[int, dict] = {}
    for ti in range(len(tracks)):
        rowmap[ti], laps[ti] = _event_rows(tracks, patterns, ti)
    if not _gate_valid(det, tracks, laps):
        return patterns, tracks
    where: Dict[int, Dict[int, tuple]] = {}
    for ti in range(len(tracks)):
        at, row = {}, 0
        for _t, pos, play, p in _plays([tracks[ti]], patterns):
            pat = patterns[p]
            for k in range(len(pat) // 4):
                if pat[4 * k] == 0xFF:
                    break
                at[row] = (pos, play, p, k)
                row += 1
        where[ti] = at
    m = max(1, multiplier)
    mask = det.wave_eor.mask
    wanted: Dict[tuple, Dict[int, int]] = {}      # (ti, pos, play) -> {row: operand}
    stats = Counter()
    tempos: Dict[int, list] = {}
    for ti, key, k, gt, _rec, length, phase, quiet, _tempo in note_parities(
            sid, det, tracks, patterns, instr_used, lead, aliases):
        if quiet or length < 3 or gt not in toggles:
            continue
        row = rowmap[ti][(key, k)]
        clock = skip_clock(det, ti // 3, row)
        if clock is None:
            continue
        w0, R, frames = clock
        if frames != 2 or not R or R % 2 or R in GATE_FAMILIES:
            continue
        wave = toggles[gt]
        alt = wave ^ mask
        written = firstwaves.get(gt, 0)
        if ti // 3 not in tempos:
            tempos[ti // 3] = _row_tempos(tracks, patterns, ti // 3)
        row_calls = tempos[ti // 3][ti % 3]
        sim = flips = None
        for i in range(1, length - 1):
            if (w0 + frames * i) % R:
                continue
            state = i % 2
            at = library.detours.get((wave, state))
            ring = library.nodes.get((wave, 0, state, 0))
            if at is None or ring is None:
                continue
            # Where our row `i` starts against where the original's does:
            # the tempo runs round to whole calls, so it is 0 to 2 late.
            lens = row_calls[row:row + i]
            ideal = m * (gate_tick(R, w0 + frames * i) - gate_tick(R, w0))
            if len(lens) < i or None in lens:
                stats["timing"] += 1
                continue
            late = sum(lens) - ideal
            if sim is None:
                sim = program_waves(entries, starts[gt],
                                    m * (length + 1) * 3, written)
                flips = {c for c in range(1, len(sim))
                         if sim[c] != sim[c - 1] and {sim[c], sim[c - 1]}
                         == {wave, alt}}
            # Phase 0 toggles on the row's second call, a frame late here:
            # hold the state `5 - late` calls and enter the ring at the other.
            # Phase 1 toggles on the first call, on time, and the next one a
            # frame later than the ring's: `late` 1 writes the state and
            # holds six calls, 2 -- the toggle already past -- holds five, and
            # 0 would want a call kept first, which the table has no row for.
            # The ring's own toggles sit where the clock puts them; where they
            # do not, the program is not the one the model describes.
            if phase == 0:
                ok = {ideal - 1, ideal + 3} <= flips
                operand = {0: at + 1, 1: ring, 2: ring + 1}.get(late)
            else:
                ok = ({ideal + 1, ideal + 5} | ({ideal - 3} if i > 1 else set())
                      ) <= flips
                operand = {0: at, 1: at, 2: at + 1}.get(late)
            if not ok:
                stats["program"] += 1
                continue
            if operand is None:
                stats["timing"] += 1
                continue
            site = where[ti].get(row + i)
            if site is None:
                continue
            pos, play, _p, kk = site
            wanted.setdefault((ti, pos, play), {})[kk] = operand
    # Per orderlist position: the rows every play wants alike.
    plays_at: Dict[tuple, int] = Counter()
    for ti in range(len(tracks)):
        for _t, pos, play, p in _plays([tracks[ti]], patterns):
            plays_at[(ti, pos)] += 1
    votes: Dict[tuple, Counter] = {}
    for (ti, pos, _play), rows in wanted.items():
        for r, operand in rows.items():
            votes.setdefault((ti, pos), Counter())[(r, operand)] += 1
    sites: Dict[tuple, Dict[int, int]] = {}
    for (ti, pos), c in votes.items():
        for (r, operand), n in c.items():
            if n == plays_at[(ti, pos)]:
                sites.setdefault((ti, pos), {})[r] = operand
            else:
                stats["disagree"] += n
    occurrences: Dict[int, list] = {}
    for ti, track in enumerate(tracks):
        for pos, b in enumerate(track):
            if b == 0xFF:
                break
            if b < _SONG_MAX_PATTERNS and b < len(patterns):
                occurrences.setdefault(b, []).append((ti, pos))
    new_tracks = [list(t) for t in tracks]
    new_patterns = list(patterns)
    placed = copies = 0
    for p, occs in occurrences.items():
        pat = patterns[p]
        sigs = {}
        for occ in occs:
            keep = []
            for r, operand in sorted(sites.get(occ, {}).items()):
                if pat[4 * r + 2] or pat[4 * r + 3]:
                    stats["busy"] += 1
                elif r == 0:
                    stats["start"] += 1
                elif _effect_runs_into(pat, r):
                    stats["running"] += 1
                else:
                    keep.append((r, operand))
            sigs[occ] = tuple(keep)
        distinct = list(dict.fromkeys(sigs.values()))
        if distinct == [()]:
            continue
        keeper = (() if () in distinct
                  else Counter(sigs.values()).most_common(1)[0][0])
        number = {(): p}
        for sig in distinct:
            if not sig:
                continue
            edited = list(pat)
            for r, operand in sig:
                edited[4 * r + 2], edited[4 * r + 3] = CMD_SETWAVEPTR, operand
            if packed_pattern_size(pattern_rows(edited)) > PACKED_PATTERN_LIMIT:
                stats["over"] += len(sig)
                number[sig] = p
            elif sig == keeper:
                new_patterns[p] = edited
                number[sig] = p
                placed += len(sig)
            elif len(new_patterns) >= _SONG_MAX_PATTERNS:
                stats["over"] += len(sig)
                number[sig] = p
            else:
                number[sig] = len(new_patterns)
                new_patterns.append(edited)
                copies += 1
                placed += len(sig)
        for ti, pos in occs:
            new_tracks[ti][pos] = number[sigs[(ti, pos)]]
    if log and (placed or stats):
        log(f"EOR skip rows...........: CMD_SETWAVEPTR on {placed} row(s), "
            f"{copies} pattern copy(ies)"
            + "".join(f", {n} {why}" for why, n in sorted(stats.items())))
    return new_patterns, new_tracks


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
