"""A gate lead longer than one row: a KEYOFF on the last rest row, a short gatetimer.

**The row ceiling.** Goattracker clears the gate `gatetimer` calls before the
next row's tick 0, and `gplay.c:334` stops the song when the gatetimer exceeds
the channel's tick, so a lead can never reach the row length
(`hard_restart._hard_restart_ticks`; `row_hard_restart` takes it to the row
itself). W_A_R's tick is three frames: its player clears the gate on the last
tick of every note (`$E5D1 LDA #$FE / STA $E8F7,X`), so the original's gate is
off for exactly 12 calls (3 frames at -S4) before the next note, whatever the
note's length (80 of 80 period-27 notes, 614 of 614 period-9 notes on voice 1,
800 of 800 on voice 2: gate on 6 of 9 frames against ours 7). Our rows are 9
calls, so the gatetimer stops at 8, one frame short, and `gate` reads 77% with
`gate_ours_ringing` 1679 frames.

**The lead is one row PLUS the gatetimer.** The gatetimer only decides when the
NEXT ROW is fetched, and a KEYOFF is fetched like a note: `gplay.c:905-921`
at `tick == gatetimer` of the row before it reads the row's note and a KEYOFF
sets `gate = $FE` there. So a KEYOFF on the last REST row of a note, the row
just before the next note, clears the gate `gatetimer` calls before THAT row,
which is `row + gatetimer` calls before the next note: with a 9-call row and a
gatetimer of 3, 12 calls. The note's own next-note fetch then comes 3 calls
early and clears a gate that is already clear.

    lead L = frames * multiplier calls,   row R,   R < L < 2R
    gatetimer = L - R,                    KEYOFF on the row before each note

**Measured on W_A_R** (`-t 180 --presets`, `release_row` and
`hard_restart_frames` 3, subtune 0): gate 77.0% -> 99.2%, `gate_ours_ringing`
1679 -> 40 frames, the period-9 notes on voice 1 gate-on 6 frames 611 of 614.

A row is rewritten only where the playing instrument is released this way
(`release_ticks`), the track's own row is the instrument's (a pattern shared
with a faster subtune keeps its lead), the row is a free REST (no instrument
column; a command column is kept, a KEYOFF carries one) and the next row is a
note that does not tie (`CMD_TONEPORTA` reads as "no gate-off", gplay.c:925).
The note at the first row of a pattern puts its KEYOFF on the PREVIOUS
position's last row, and every visit of a position must agree: a pattern its
positions want differently is cloned, as `rest_reseed` does.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constants import (CMD_TONEPORTA, GT_KEYOFF, GT_LAST_NOTE, GT_REST,
                        HARD_RESTART_FRAMES)
from . import hard_restart as _gw_hard_restart


# Test seam: False leaves every REST where it is (tests/test_release_row.py).
ENABLED = True


def release_calls(multiplier: int, frames: Optional[int]) -> int:
    """The lead the original gives, in play calls."""
    base = max(1, int(frames)) if frames else HARD_RESTART_FRAMES
    return base * max(1, multiplier)


def release_ticks(lead_calls: int, row_calls: int) -> int:
    """The gatetimer that, beside a KEYOFF on the row before the note, gives
    `lead_calls`; 0 where the lead is not between one row and two."""
    if row_calls and row_calls > 1 and row_calls < lead_calls < 2 * row_calls:
        return lead_calls - row_calls
    return 0


def instrument_release_ticks(instr_row_calls: Optional[dict], row_calls: int,
                             count: int, lead_calls: int,
                             wave_entries=None, wave_starts=None,
                             lead: int = 0) -> Dict[int, int]:
    """{Goattracker instrument: gatetimer} for the instruments released by a
    KEYOFF row. `count` is the number of record instruments (instrument
    numbers 1..count + lead)... a record whose waveform program has a gate
    PULSE the longer mask would swallow is left on the ordinary schedule
    (`hard_restart.strike_safe_ticks` at the full lead), as are the
    instruments whose every note is one row (no rest row to carry a KEYOFF)."""
    out: Dict[int, int] = {}
    single = getattr(instr_row_calls, "single_row", ())
    for i in range(count):
        gt = i + lead + 1
        own = (instr_row_calls or {}).get(gt, row_calls)
        ticks = release_ticks(lead_calls, own)
        if not ticks or gt in single:
            continue
        if wave_entries and wave_starts is not None and i + lead < len(
                wave_starts):
            ptr = wave_starts[i + lead] & 0xFF
            if _gw_hard_restart.strike_safe_ticks(
                    wave_entries, ptr, own, lead_calls) != lead_calls:
                continue
        out[gt] = ticks
    return out


def _release_walk(pattern: List[int], instr: int, ok) -> tuple:
    """One pass of one pattern: (rows to KEYOFF, instrument and whether the
    last real row is a free rest the playing instrument releases, whether
    the first row is a note that does not tie)."""
    rows = len(pattern) // 4
    if rows and pattern[4 * (rows - 1)] == 0xFF:
        rows -= 1
    want = set()
    first_note = (rows > 0 and pattern[0] <= GT_LAST_NOTE
                  and pattern[2] != CMD_TONEPORTA)
    for r in range(rows):
        note, named, cmd, _data = pattern[4 * r:4 * r + 4]
        if named:
            instr = named
        if (note == GT_REST and not named and r + 1 < rows and ok(instr)):
            nn, _nm, ncmd, _nd = pattern[4 * (r + 1):4 * (r + 1) + 4]
            if nn <= GT_LAST_NOTE and ncmd != CMD_TONEPORTA:
                want.add(r)
    last_free = bool(
        rows and pattern[4 * (rows - 1)] == GT_REST
        and not pattern[4 * (rows - 1) + 1] and ok(instr))
    return want, instr, (rows - 1 if last_free else None), first_note


def release_row_plan(tracks: List[List[int]], patterns: List[List[int]],
                     eligible: Dict[int, int], track_rows: List[int],
                     row_calls: int, lead_calls: int) -> dict:
    """{(track, orderlist position): frozenset of rows to KEYOFF}, only the
    rows every visit of the position agrees on. Walked as
    `rest_reseed._rest_reseed_plan` walks (instrument 1 before any row,
    transposes skipped, a repeat is that many visits, the restart lapped
    once)."""
    plan: dict = {}
    for ti, track in enumerate(tracks):
        end = track.index(0xFF) if 0xFF in track else len(track)
        restart = track[end + 1] if end + 1 < len(track) else None
        laps = [range(0, end)]
        if restart is not None and restart < end:
            laps.append(range(restart, end))
        calls = track_rows[ti // 3] if ti // 3 < len(track_rows) else row_calls
        if not release_ticks(lead_calls, calls):
            # Nothing to write, but every position is named so that a
            # pattern patched in place for another track is not patched here.
            for lap in laps:
                for pos in lap:
                    if track[pos] < len(patterns):
                        plan[(ti, pos)] = frozenset()
            continue

        def ok(instr, calls=calls):
            return eligible.get(instr) == lead_calls - calls

        visits: list = []
        instr = 1
        lap_two = None
        for lap_no, lap in enumerate(laps):
            if lap_no == 1:
                lap_two = len(visits)
            repeat = 1
            for pos in lap:
                b = track[pos]
                if 0xE0 <= b < 0xFF:
                    continue
                if 0xD0 <= b < 0xE0:
                    repeat = b - 0xD0 + 1
                    continue
                if b >= len(patterns):
                    repeat = 1
                    continue
                for _ in range(repeat):
                    want, instr, last, first_note = _release_walk(patterns[b], instr,
                                                          ok)
                    visits.append([(ti, pos), want, last, first_note])
                repeat = 1
        pairs = list(zip(visits, visits[1:]))
        if lap_two is not None and lap_two < len(visits):
            # The song's loop: the last visit is followed by the restart's.
            pairs.append((visits[-1], visits[lap_two]))
        for cur, nxt in pairs:
            if nxt[3] and cur[2] is not None:
                cur[1].add(cur[2])
        for key, want, _last, _first in visits:
            want = frozenset(want)
            plan[key] = plan[key] & want if key in plan else want
    return plan


def release_row_keyoffs(blob: bytes, group_tempos: Optional[List[int]],
                        lead_calls: int, log=None) -> bytes:
    """`blob` with a KEYOFF on each planned REST row, on the FINISHED song.

    Here and not in `build_sng` because later passes key rows by pattern
    number (the past-table split writes `CMD_SETWAVEPTR` on the top-note rows
    of `det.top_cols`), and a pattern copy made before them is a pattern they
    do not know: Master-of-nothing, W_A_R's `G#7` row beside a copy read
    `G#7` where the original plays `A-7` (pitch 100% -> 96%). The records are
    final here too, which is what says what each instrument will do: an
    instrument whose written gatetimer is `lead - row` is released by a KEYOFF
    (`_write_instruments(release_ticks=...)`, clones copy their parent's).

    Patterns are edited in place where every visit agrees and copied where
    not (`rest_late_keyoff`'s layout and limits: 208 patterns, the packed
    pattern size)."""
    if (not ENABLED or not group_tempos
            or bytes(blob[:4]) not in (b"GTS2", b"GTS5")):
        return bytes(blob)
    from ..patterns import GT_END_PATTERN, MAX_PATTERNS
    from ..prev_class_firstwave import _layout
    from .constants import HEADER_LEN, PACKED_PATTERN_LIMIT
    from .pulse import packed_pattern_size, pattern_rows
    tracks, instr_at, _wtbl, _tables_at, patt_at, spans = _layout(blob)
    pos = HEADER_LEN + 1
    track_at = []
    for _ in range(len(tracks)):
        track_at.append(pos + 1)
        pos += blob[pos] + 2
    recs = instr_at + 1
    written = {n: blob[recs + (n - 1) * 25 + 7] & 0x3F
               for n in range(1, blob[instr_at] + 1)}
    patterns = [list(blob[start:start + 4 * rows]) for start, rows in spans]
    plan = release_row_plan(tracks, patterns, written, list(group_tempos),
                            0, lead_calls)
    groups: Dict[int, Dict[frozenset, list]] = {}
    for (ti, pos_), want in plan.items():
        groups.setdefault(tracks[ti][pos_], {}).setdefault(want, []).append(
            (ti, pos_))

    def patched(b: int, want: frozenset) -> List[int]:
        rows = list(patterns[b])
        for r in want:
            rows[4 * r] = GT_KEYOFF
        return rows

    def fits(rows: List[int]) -> bool:
        real = rows[:4 * (len(rows) // 4)]
        end = next((k for k in range(0, len(real), 4)
                    if real[k] == GT_END_PATTERN), len(real))
        return packed_pattern_size(pattern_rows(real[:end]))             <= PACKED_PATTERN_LIMIT

    out = bytearray(blob)
    new_patterns: List[bytes] = []
    npat = len(patterns)
    written_rows = clones = full = unfit = 0
    for b in sorted(groups):
        by_want = groups[b]
        wanted = [w for w in by_want if w]
        if not wanted:
            continue
        if frozenset() in by_want:
            stays = frozenset()
        else:
            stays = max(wanted, key=lambda w: (len(by_want[w]), sorted(w)))
            edited = patched(b, stays)
            if fits(edited):
                start = spans[b][0]
                out[start:start + len(edited)] = bytes(edited)
                written_rows += len(stays) * len(by_want[stays])
            else:
                unfit += len(by_want[stays])
        for want in sorted((w for w in wanted if w != stays), key=sorted):
            if npat + len(new_patterns) >= MAX_PATTERNS:
                full += len(by_want[want])
                continue
            edited = patched(b, want)
            if not fits(edited):
                unfit += len(by_want[want])
                continue
            number = npat + len(new_patterns)
            new_patterns.append(bytes([spans[b][1]]) + bytes(edited))
            clones += 1
            for ti, pos_ in by_want[want]:
                out[track_at[ti] + pos_] = number
            written_rows += len(want) * len(by_want[want])
    if not written_rows:
        return bytes(blob)
    out[patt_at] = (npat + len(new_patterns)) & 0xFF
    for body in new_patterns:
        out += body
    if log is not None:
        log(f"Release row...........: KEYOFF on {written_rows} rest row(s) "
            f"over the orderlists, {clones} pattern copy(ies)"
            + (f", {full} position(s) left alone: pattern table full"
               if full else "")
            + (f", {unfit} left alone: packed pattern too large"
               if unfit else ""))
    return bytes(out)
