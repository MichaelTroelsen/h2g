"""Which orderlist positions a position-driven master volume is ever written at.

The row-fetch spelling of the volume (`detect.master_fade_is_fetch`; Confuzion
`$0956`) writes `$D418` from inside the row fetch, and only for a row whose
status byte has bit 7 (the row that names an instrument). The level a
position gives is therefore on the chip only if some voice fetches such a row
while that position is current; Confuzion's last four positions hold one
instrument-less pattern on every voice, so the formula's `0` for the position
`$A0` is never written and `V` stays `1` until the tune's end routine zeroes
it. This module walks the three orderlists in time, the way
`stored_wave.stored_wave_notes` does, and reports the positions that see a
write.
"""
from __future__ import annotations

from typing import Dict, List

from .detect import Detection
from .sidfile import SidFile

MAX_TICKS = 1 << 20


def written_positions(sid: SidFile, det: Detection, tracks: List[List[int]],
                      group: int, voice: int, floor: int,
                      slides: bool = False,
                      status_bit6: bool = False) -> Dict[int, int]:
    """{position of `voice`: tick of the first write that sees it}.

    A voice's position steps when it fetches the LAST row of a pattern (the
    player looks one byte ahead for `$FF`), after that fetch's own write; the
    voices fetch in the order 2, 1, 0 within a tick. The walk ends when any
    voice reaches the orderlist's end: the player stops the tune there.
    """
    from .patterns import decode_entry
    cache: Dict[int, List[tuple]] = {}

    def events(entry: int) -> List[tuple]:
        if entry not in cache:
            ev: List[tuple] = []
            if decode_entry(sid, det, entry, slides=slides,
                            status_bit6=status_bit6, event_log=ev) is None:
                ev = []
            cache[entry] = ev
        return cache[entry]

    bodies: List[List[int]] = []
    for v in range(3):
        body: List[int] = []
        for b in tracks[3 * group + v]:
            if b >= floor:
                break
            body.append(b)
        bodies.append(body)
    if any(not b for b in bodies):
        return {}
    pos = [0, 0, 0]
    evi = [0, 0, 0]
    nxt = [0, 0, 0]
    seen: Dict[int, int] = {}
    t = 0
    while t < MAX_TICKS:
        for v in (2, 1, 0):
            if nxt[v] != t:
                continue
            if pos[v] >= len(bodies[v]):
                if v == voice:
                    return seen
                nxt[v] = MAX_TICKS      # a voice past its end writes nothing
                continue
            evs = events(bodies[v][pos[v]])
            if not evs:
                if v == voice:
                    return seen
                nxt[v] = MAX_TICKS
                continue
            wait, rec, _note = evs[evi[v]]
            if rec is not None:
                seen.setdefault(pos[voice], t)
            evi[v] += 1
            if evi[v] >= len(evs):
                evi[v] = 0
                pos[v] += 1
            nxt[v] = t + wait + 1
        t = min(nxt)
    return seen


def park_end_volume(tracks: List[List[int]], patterns: List[List[int]],
                    log=None, event_rows=None) -> int:
    """Write the tune-end `D00` into the silent park, one voice per subtune.

    The original's end routine (`detect.TUNE_END_VOLUME_SHAPE`) stores
    `$D418` = 0 when the tune ends; `legalise_restarts(silent_park)` parks
    each ended subtune on the shared `SILENT_PATTERN`, which is where that
    write belongs. The park is replaced, on the first voice of each subtune
    that parks, by a COPY of the silent pattern with `D00` on row 0, APPENDED
    after every other pattern: patterns are laid out in index order, so an
    edit of the silent pattern itself would move every pattern stored after it
    by a byte, which moves sidplayfp's render of the whole tune by tens of
    samples with the registers unchanged (python/tests/
    test_master_fade_tune_end.py, finding.md of the task that measured it).
    The parked entry loops on itself, so the copy re-issues the same `D00`
    on every pass, which changes nothing the first did not.

    Returns how many orderlists were changed.
    """
    from .patterns import CMD_SETMASTERVOL, GT_ORDER_RESTART, MAX_PATTERNS
    from .tracks import SILENT_EVENT_ROWS, SILENT_PATTERN
    copy_index = None
    done = 0
    for g in range(0, len(tracks), 3):
        for track in tracks[g:g + 3]:
            m = next((i for i, b in enumerate(track) if b == GT_ORDER_RESTART),
                     None)
            if (m is None or m < 1 or m + 1 >= len(track)
                    or track[m + 1] != m - 1):
                continue                    # not parked on its own last entry
            at = track[m - 1]
            if at >= len(patterns) or patterns[at] != list(SILENT_PATTERN):
                continue
            if copy_index is None:
                if len(patterns) >= MAX_PATTERNS:
                    if log:
                        log("*** NO ROOM FOR THE TUNE-END VOLUME PATTERN (AT "
                            f"GOATTRACKER'S {MAX_PATTERNS} LIMIT) ***")
                    return done
                copy = list(SILENT_PATTERN)
                copy[2], copy[3] = CMD_SETMASTERVOL, 0
                copy_index = len(patterns)
                patterns.append(copy)
                if event_rows is not None:
                    event_rows[copy_index] = SILENT_EVENT_ROWS
            track[m - 1] = copy_index
            done += 1
            break                           # one voice per subtune
    if log and done:
        log(f"Tune-end volume.........: D00 on the silent park of {done} "
            "subtune(s), the original's end routine zeroing $D418")
    return done
