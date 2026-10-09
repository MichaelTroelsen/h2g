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
    routes it to `wave_eor_block` and nothing else."""
    phase: int
    period: int


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
    for _ti, key, k, gt, i, length, phase, quiet, tempo in note_parities(
            sid, det, tracks, patterns, instr_used, lead, aliases):
        if quiet:
            continue
        if length < 2:
            res = NO_TOGGLE
        elif length == 2 or _is_drum(sid, det, i):
            res = EorPhase(0, 0) if phase == 0 else NO_TOGGLE
        elif tempo is None:
            continue
        else:
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
                   written: bool = False) -> Optional[tuple]:
    """Record `i`'s wavetable block under toggle `eor`, from `block` -- the
    block `_wavetable_entries` lays out for it with no toggle.

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
