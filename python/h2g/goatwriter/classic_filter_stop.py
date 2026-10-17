"""The classic filter sweep's stop: `A 00` on the note where the sweeping voice
moves to an unfiltered record.

**THE PLAYER SWEEPS A VOICE'S CUTOFF ONLY WHILE THE VOICE'S RECORD FILTERS,
AND GOATTRACKER'S ONE GLOBAL PROGRAM CANNOT STOP ON ITS OWN.** An unfiltered
record's instrument loads no filter pointer (player.s `mt_skipfilt`), so the
program a filtered note started runs on past the note that, in the original,
ended its sweep. `classic_sweep_calls` could only compromise on one length
for all of a record's occurrences (`_best_sweep_length`): short enough that
the stops do not overshoot, so the occurrences that sweep on to a filtered
strike fall short. `CMD_SETFILTERPTR` with data 0 stops the program where it
stands (gplay.c:459 `filterptr = newcmddata`, and nothing steps at 0;
player.s `mt_tick0_a`), the cutoff left where it was -- exactly what the
player does -- so putting one on the unfiltered follower's note lets the
sweep run the longest gap of its record.

Placed as `free_running_fetch_holds` places its pointers: a command column
nobody else took, a pattern played at several positions that want different
rows copied per distinct set. Last of the passes that fill a command column.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional

from .constants import (CMD_SETFILTERPTR, CMD_TONEPORTA, GT_FIRST_NOTE,
                        GT_LAST_NOTE, PACKED_PATTERN_LIMIT,
                        _SONG_MAX_PATTERNS)
from .filters import _best_sweep_length, _ilv_voice_rows
from .pulse import packed_pattern_size, pattern_rows


class SweepLengths(dict):
    """{record: calls}, and in `free` the records whose every gap ends on a
    filtered strike (or on a stop that has its place): for those any length
    from the longest gap up costs nothing, because the next strike of the
    voice restarts or replaces the program. `filters._fit_sized_sweeps`
    reads it to let such records share one longer block."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.free: set = set()


def _stop_row(pattern: List[int], r: int) -> Optional[int]:
    """The row to write `A 00` on for the note at row `r` of `pattern`.

    The note's own row where its command column is free (a new note resets
    the channel's running command, so a one-shot there cancels nothing);
    else the first free row after it, up to the next note, provided no
    running command (1-4: slide, vibrato) started on the way, because a
    one-shot row entered under a running command is not taken (the rule
    `_fetch_hold_pattern` applies)."""
    n = 0
    while 4 * n + 3 < len(pattern) and pattern[4 * n] != 0xFF:
        n += 1
    if r >= n:
        return None
    if pattern[4 * r + 2] == 0:
        return r
    if 1 <= pattern[4 * r + 2] <= 4:
        return None
    for c in range(r + 1, n):
        if GT_FIRST_NOTE <= pattern[4 * c] <= GT_LAST_NOTE:
            return None
        cmd = pattern[4 * c + 2]
        if cmd == 0:
            return c
        if cmd <= 4:
            return None
    return None


def classic_filter_stops(tracks: List[List[int]], patterns: List[List[int]],
                         filtered: set, instr_base: int, row_calls: int,
                         instr_row_calls: Optional[dict] = None) -> tuple:
    """(sweep_calls, sites, stats): the sweep lengths and the stops to write.

    Walked as `classic_sweep_calls` walks (every voice's orderlist, the
    striking notes of each record, a tie striking nothing). A stop is owed
    where a voice's next note is an unfiltered record and the voice's last
    one was filtered; `sites` maps (track index, orderlist position) to the
    frozenset of pattern rows that take it, only for a position every play of
    which wants the same rows. A gap whose stop has a place no longer counts
    as one in the length (`_best_sweep_length`), so the record's length is
    the longest gap it has, as far as the player sweeps. `stats` counts the
    stops wanted, placed and unplaced by reason."""
    per_record: dict = {}
    start = getattr(instr_row_calls, "start_rows", None) or {}
    wanted: dict = {}
    plays_at: dict = {}
    stats = {"wanted": 0, "placed": 0, "no column": 0, "disagree": 0}
    for ti, track in enumerate(tracks):
        live = 1
        events: List[tuple] = []
        for t, (pos, n, p, r) in enumerate(_ilv_voice_rows(track, patterns)):
            plays_at.setdefault((ti, pos), set()).add(n)
            note, ins, cmd, _dat = patterns[p][4 * r:4 * r + 4]
            if ins:
                live = ins
            if GT_FIRST_NOTE <= note <= GT_LAST_NOTE and cmd != CMD_TONEPORTA:
                rc = (start.get(live) or (instr_row_calls or {}).get(live)
                      or row_calls or 1)
                events.append((t, live - instr_base, rc, pos, p, r))
        for (t0, rec, rc, _a, _b, _c), (t1, nxt, _rc, pos, p, r) in zip(
                events, events[1:]):
            if rec not in filtered:
                continue
            gap = (t1 - t0) * rc
            at = None
            if nxt not in filtered:
                stats["wanted"] += 1
                row = _stop_row(patterns[p], r)
                if row is None:
                    stats["no column"] += 1
                else:
                    wanted.setdefault((ti, pos), []).append(row)
                    at = (ti, pos, row)
            per_record.setdefault(rec, []).append(
                (gap, nxt not in filtered, at))
    sites: dict = {}
    agreed_rows: set = set()
    for key, rows in wanted.items():
        agreed = set()
        for row, n in Counter(rows).items():
            if n == len(plays_at[key]):
                agreed.add(row)
                agreed_rows.add(key + (row,))
                stats["placed"] += n
            else:
                stats["disagree"] += n
        if agreed:
            sites[key] = frozenset(agreed)
    lengths = SweepLengths()
    for rec, entries in per_record.items():
        # a gap is a stop for the length only where its stop has no place
        gaps = [(g, stop and at not in agreed_rows)
                for g, stop, at in entries]
        length = _best_sweep_length(gaps)
        if length:
            lengths[rec] = length
            if not any(stop for _g, stop in gaps):
                lengths.free.add(rec)
    return lengths, sites, stats


def apply_stops(tracks: List[List[int]], patterns: List[List[int]],
                sites: dict, log=None) -> tuple:
    """(patterns, tracks, written): `A 00` at every site. Changed patterns and
    tracks are COPIES, a pattern wanted differently at its positions cloned
    and only those positions repointed (same length, same place); past
    `_SONG_MAX_PATTERNS` or `PACKED_PATTERN_LIMIT` a position keeps its old
    rows, counted. A row whose column another pass filled since the plan was
    made is left alone."""
    occurrences: dict = {}
    for ti, track in enumerate(tracks):
        for pos, b in enumerate(track):
            if b == 0xFF:
                break
            if b < _SONG_MAX_PATTERNS and b < len(patterns):
                occurrences.setdefault(b, []).append((ti, pos))
    new_tracks = [list(t) for t in tracks]
    new_patterns = list(patterns)
    written = clones = dropped = 0
    for p, occs in occurrences.items():
        sigs = {}
        for occ in occs:
            rows = sorted(r for r in sites.get(occ, ())
                          if patterns[p][4 * r + 2] == 0)
            sigs[occ] = tuple(rows)
        distinct = list(dict.fromkeys(sigs.values()))
        if distinct == [()]:
            continue
        keeper = (() if () in distinct
                  else Counter(sigs.values()).most_common(1)[0][0])
        number = {(): p}
        for sig in distinct:
            if not sig:
                continue
            edited = list(patterns[p])
            for r in sig:
                edited[4 * r + 2], edited[4 * r + 3] = CMD_SETFILTERPTR, 0
            if packed_pattern_size(pattern_rows(edited)) > PACKED_PATTERN_LIMIT:
                dropped += len(sig)
                number[sig] = p
            elif sig == keeper:
                new_patterns[p] = edited
                number[sig] = p
                written += len(sig)
            elif len(new_patterns) >= _SONG_MAX_PATTERNS:
                dropped += len(sig)
                number[sig] = p
            else:
                number[sig] = len(new_patterns)
                new_patterns.append(edited)
                clones += 1
                written += len(sig)
        for ti, pos in occs:
            new_tracks[ti][pos] = number[sigs[(ti, pos)]]
    if log and (written or dropped):
        log(f"Classic filter stop.....: CMD_SETFILTERPTR 0 on {written} "
            f"row(s), {clones} pattern copy(ies)"
            + (f", {dropped} DROPPED (pattern table / packed size)"
               if dropped else ""))
    return new_patterns, new_tracks, written
