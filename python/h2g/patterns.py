"""Pattern conversion (port of GoatConvertPattern, h2g.frm:818-1097).

Two passes, matching the original:
 1. Decode each Hubbard pattern into a flat Goattracker-style event stream
    (4 bytes per row: note, instrument, command, command-value).
 2. Slice event streams longer than Goattracker's 94-row (376-byte) pattern
    limit into multiple patterns, and re-index every track's pattern-number
    references accordingly.

See `_slice_pattern` docstring for how the VB original's slicing loop
(which iterates one index past the real data, relying on implicit
zero-initialized arrays) was proven equivalent to plain chunking.
"""
from __future__ import annotations

from typing import List, Optional, Set

from .detect import Detection
from .sidfile import HLEN, SidFile

# Rows per pattern to slice at. The original VB6 tool used 94, the limit of the
# Goattracker of its day; v2.32 raised MAX_PATTROWS to 128 (confirmed in
# goattracker2 src/gcommon.h and readme.txt). 94 stays the default because it is
# what the byte-exact Commando fixture encodes -- see convert(max_rows=...).
GT_DEFAULT_ROWS = 94
GT_MAX_ROWS = 128  # == MAX_PATTROWS in gcommon.h

GT_MAX_PATTERN_LEN = GT_DEFAULT_ROWS * 4  # 376 bytes
GT_NO_NOTE = 0xBD
MAX_PATTERNS = 0xD0
MAX_TRACK_LEN = 0xFF

# Goattracker orderlist byte ranges: $00-$CF pattern number, $D0-$FE command
# (repeat / transpose, no operand), $FF restart -- the only one that takes an
# operand, the restart position, which follows it.
GT_ORDER_RESTART = 0xFF

GT_END_PATTERN = 0xFF          # ENDPATT: note-column value marking a pattern's end
GT_END_ROW = [GT_END_PATTERN, 0x00, 0x00, 0x00]

ERROR_PATTERN = [0xBD, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]


class ConversionAbort(Exception):
    pass


def _build_raw_pattern(data: bytes, addr: int) -> Optional[List[int]]:
    """Flat event stream for one Hubbard pattern, or None if out of range."""
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    g_instrument = 0
    g_old_instr1 = -1
    g_old_instr2 = -2
    i2 = 0

    while True:
        if addr + i2 <= 1 or addr + i2 >= len(data):
            return None

        g_note = GT_NO_NOTE
        cmd1 = 0
        cmd2 = 0
        b1 = data[addr + i2]

        if b1 == 0xFF:
            events += [0xFF, 0x00, 0x00, 0x00]
            break

        get_next = b1 & 0x80
        no_note = b1 & 0x40
        no_adsr = b1 & 0x20
        wait = b1 & 0x1F

        if get_next:
            i2 += 1
            b2 = data[addr + i2]
            if no_adsr:
                if g_old_instr1 == g_old_instr2:
                    cmd1 = 3   # Portamento (no new ADSR)
                    cmd2 = 0x00
                g_old_instr2 = g_old_instr1
            if b2 & 0x80:
                if (b2 & 1) == 0:
                    cmd1, g_instrument = 1, 0  # pitch down
                else:
                    cmd1, g_instrument = 2, 0  # pitch up
                cmd2 = (b2 & 0x7F) // 4
            else:
                g_instrument = (b2 & 0x7F) + 2
                g_old_instr2 = g_old_instr1
                g_old_instr1 = g_instrument

        if get_next or not no_note:
            i2 += 1
            g_note = data[addr + i2]
            if g_note >= 0x5C:
                g_note = 0x5C
            g_note += 0x60

        resc_instr = -1
        if g_note == GT_NO_NOTE and g_instrument != 0:
            g_note = 0x60
            resc_instr = g_instrument
            g_instrument = 1

        # An event lasts wait+1 frames, so it always emits at least its own row.
        # The player holds a fetched event until a per-voice counter loaded with
        # `wait` underflows -- Commando's is $54F2,X, sequenced by
        #     $5078  DEC $54F2,X
        #     $507B  BMI  fetch-next-event
        # DEC/BMI means the counter must pass below zero, so wait==0 is a
        # legitimate one-frame event, not a no-op.
        #
        # The VB6 original wrapped this whole block in `If nWait >= 1` (h2g.frm
        # :984) and so dropped every one-frame event, shortening the pattern and
        # drifting the voice against the other two for the rest of it. The inner
        # `If nWait >= 1` guarding only the hold-rows (h2g.frm:996) is the one
        # that belongs; the outer was the mistake. Corpus-wide the guard
        # discarded 2562 events across 43 files -- Chimera's pattern $6 is 96
        # consecutive one-frame events and came out completely empty.
        events += [g_note, g_instrument, cmd1, cmd2]
        if cmd1 == 3:
            cmd1 = 0
        for _ in range(wait):
            events += [GT_NO_NOTE, 0x00, cmd1, cmd2]

        if resc_instr != -1:
            g_instrument = resc_instr

        i2 += 1

    return events


def _slice_pattern(events: List[int], max_len: int = GT_MAX_PATTERN_LEN,
                   terminate: bool = False) -> List[List[int]]:
    """Chunk a flat event stream into <=max_len pieces.

    A trailing (possibly empty) slice is always emitted, matching the VB
    original: when len(events) is an exact multiple of max_len, an extra
    zero-length pattern is produced and referenced by the track.

    Only the *final* slice inherits the stream's ENDPATT row; non-final slices
    are max_len bytes of pure data. Goattracker does not trust the stored
    length -- countpatternlengths() (gsong.c) rescans for ENDPATT -- so an
    unterminated pattern's length is whatever clearpattern() left behind, which
    is ENDPATT only from row `defaultpatternlength` (64 by default) onward.
    Slicing at 94 therefore works by luck: 94 > 64. Raise the loader's default
    pattern length above the slice length and every sliced pattern silently
    grows trailing rows.

    `terminate=True` appends an explicit ENDPATT row to any slice lacking one,
    which is what Goattracker itself writes (savesong stores pattlen+1 rows,
    gsong.c:116) and makes the output self-describing. It is opt-in because it
    changes the bytes, and the byte-exact Commando fixture encodes the
    original tool's unterminated output.
    """
    slices = []
    pos = 0
    n = len(events)
    while n - pos >= max_len:
        slices.append(events[pos:pos + max_len])
        pos += max_len
    slices.append(events[pos:n])
    if terminate:
        # A row is 4 bytes; s[-4] is the last row's note column. ENDPATT only
        # ever occurs as the stream's final row, so a non-final slice never
        # already ends with one -- the check just avoids doubling it up.
        slices = [s if (len(s) >= 4 and s[-4] == GT_END_PATTERN) else s + GT_END_ROW
                  for s in slices]
    return slices


def referenced_patterns(tracks: List[List[int]]) -> Set[int]:
    """Raw Hubbard pattern numbers that some track actually plays.

    Walks the orderlists exactly as reindex_tracks does: $FF (LOOPSONG) is
    followed by a restart *position*, which is a small number but not a pattern
    reference, and $D0-$FE are repeat/transpose commands with no operand.

    det.pattern_used is inferred from the gap between the pattern LO and HI
    tables, so it counts every entry the table has room for -- not every entry
    the song plays. Several tunes carry large unplayed remainders (Dragon's
    Lair II references 71 of the 202 patterns it emits).
    """
    used: Set[int] = set()
    for track in tracks:
        expect_operand = False
        for b in track:
            if expect_operand:
                expect_operand = False
            elif b == GT_ORDER_RESTART:
                expect_operand = True
            elif b < MAX_PATTERNS:
                used.add(b)
    return used


def convert_patterns(sid: SidFile, det: Detection, log,
                     max_rows: int = GT_DEFAULT_ROWS,
                     terminate_patterns: bool = False,
                     dedup: bool = False,
                     used: Optional[Set[int]] = None):
    """Decode, slice and (optionally) de-duplicate every pattern.

    `used` (from referenced_patterns) restricts output to the patterns some
    track plays. Unlike dedup this can rescue tunes that abort on
    MAX_PATTERNS, because the skipped patterns are never decoded or counted in
    the first place -- and unlike the orderlist optimisations it cannot change
    playback, since a pattern no orderlist names can never be reached.

    dedup makes identical slices share one Goattracker pattern. Hubbard tunes
    repeat heavily -- 12-21% of slices are byte-identical duplicates across the
    corpus -- so this is the difference between fitting under MAX_PATTERNS and
    aborting for several tunes. It is opt-in because it changes the output
    bytes, and the byte-exact Commando fixture encodes the original tool's
    un-deduplicated output.

    Note it cannot help the *orderlist* limit: sharing a pattern renumbers a
    track's entries without removing any, so track length is unchanged.
    """
    if not 1 <= max_rows <= GT_MAX_ROWS:
        raise ValueError(f"max_rows must be 1..{GT_MAX_ROWS}, got {max_rows}")
    max_len = max_rows * 4
    data = sid.data

    raw_patterns: List[Optional[List[int]]] = []
    for i in range(det.pattern_used + 1):
        if used is not None and i not in used:
            # Not decoded at all: an unreferenced entry is often out-of-range
            # table padding, whose address diagnostics would be noise.
            raw_patterns.append(None)
            continue

        # pattern_used is inferred from the gap between the LO and HI tables, so
        # a misdetected table pair can claim more entries than the file holds.
        # Bounds-check the table index itself, not just the address it yields.
        lo_i, hi_i = det.pattern_lo + i, det.pattern_hi + i
        if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
            log(f"*** PATTERN ${i:X} TABLE INDEX OUT OF RANGE, CAN'T CONVERT ***")
            raw_patterns.append(list(ERROR_PATTERN))
            continue

        addr = data[hi_i] * 256 + data[lo_i]
        addr = addr - sid.load_addr + HLEN - 1
        events = _build_raw_pattern(data, addr)
        if events is None:
            log(f"*** PATTERN ${i:X} ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            events = list(ERROR_PATTERN)
        raw_patterns.append(events)

    new_patterns: List[List[int]] = []
    track_index: List[List[int]] = []
    seen: dict = {}          # pattern bytes -> index in new_patterns
    reused = 0

    for i, events in enumerate(raw_patterns):
        if events is None:
            # No track names this pattern, so its (empty) index list is never
            # consulted by reindex_tracks.
            track_index.append([])
            continue
        slices = _slice_pattern(events, max_len, terminate_patterns)
        indices: List[int] = []
        for k, s in enumerate(slices):
            key = bytes(s) if dedup else None
            if key is not None and key in seen:
                idx = seen[key]
                reused += 1
            else:
                idx = len(new_patterns)
                new_patterns.append(s)
                if key is not None:
                    seen[key] = idx
            indices.append(idx)
            if k < len(slices) - 1:
                # idx+1 equals len(new_patterns) when nothing is shared, so the
                # log is unchanged from the original in the non-dedup path.
                log(f"Extending Pattern: ${i:X} (${idx + 1:X})")
            if len(new_patterns) >= MAX_PATTERNS:
                raise ConversionAbort("TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER")
        track_index.append(indices)

    if used is not None:
        pruned = sum(1 for p in raw_patterns if p is None)
        if pruned:
            log(f"Pruned {pruned} of {len(raw_patterns)} patterns "
                f"({100 * pruned // len(raw_patterns)}%) that no track plays")

    if dedup and reused:
        total = len(new_patterns) + reused
        log(f"De-duplicated {reused} of {total} patterns "
            f"({100 * reused // total}%), {len(new_patterns)} remain")

    return new_patterns, track_index


def reindex_tracks(tracks: List[List[int]], track_index: List[List[int]]) -> List[List[int]]:
    new_tracks: List[List[int]] = []
    for track in tracks:
        new_track: List[int] = []
        expect_operand = False
        for b in track:
            if expect_operand:
                # Restart position following $FF: an ordinary small number that
                # must NOT be re-indexed as a pattern reference.
                new_track.append(b)
                expect_operand = False
            elif b == GT_ORDER_RESTART:
                new_track.append(b)
                expect_operand = True
            elif b >= MAX_PATTERNS:
                # Repeat/transpose command. Passes through, but -- unlike the
                # original's sticky end-marker flag -- does NOT stop re-indexing
                # the rest of the track. Mega Apocalypse-family transposes emit
                # $E0-$FF, so the old latch silently left every pattern number
                # after the first transpose pointing at pre-split indices.
                new_track.append(b)
            else:
                new_track.extend(track_index[b] if b < len(track_index) else [])
            if len(new_track) >= MAX_TRACK_LEN:
                raise ConversionAbort("TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER")
        new_tracks.append(new_track)
    return new_tracks
