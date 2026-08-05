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

from math import gcd
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

# Orderlist REPEAT, gcommon.h: $D0-$DF. gplay.c:983 loads `repeat = value -
# REPEAT`, then reads the pattern *without advancing* while repeat counts down
# (:988), so $D0+n plays the following pattern n+1 times. $D0 itself is a no-op
# the packed-player exporter discards outright (greloc.c:680), and that same
# code requires a pattern number to follow immediately (:683) -- both honoured
# here.
GT_REPEAT = 0xD0
GT_TRANSPOSE_DOWN = 0xE0        # TRANSDOWN: first byte past the repeat range
GT_TRANSPOSE_UP = 0xF0          # TRANSUP
GT_MAX_REPEAT_RUN = 16          # $DF -> repeat 15 -> 16 plays
# Below this a run costs the same packed as unpacked (2 bytes either way for a
# run of 2), so leave it alone rather than emit a construct for nothing.
GT_MIN_REPEAT_RUN = 3

# A minimal, valid orderlist: play pattern 0, then restart at position 0. Used
# for a subtune that cannot be represented -- an unusable pointer, or one whose
# orderlist will not fit. tracks.py imports it so both reasons produce the same
# shape, which is one Goattracker is known to load.
DEFAULT_TRACK = [0x00, 0xFF, 0x00]

GT_END_PATTERN = 0xFF          # ENDPATT: note-column value marking a pattern's end
GT_END_ROW = [GT_END_PATTERN, 0x00, 0x00, 0x00]

# Lowest byte value that is a *command* rather than a pattern number, used to
# read a track that convert_tracks has produced but reindex_tracks has not yet
# renumbered. Such a track is still in Hubbard numbering, and which byte values
# are commands depends on the player dialect -- so the Goattracker range
# ($D0-$FF) is the wrong answer for most of them. See command_floor().
GT_COMMAND_FLOOR = MAX_PATTERNS


def command_floor(version: int) -> int:
    """Lowest byte a version-`version` orderlist uses as a command.

    _build_track leaves each dialect's pattern numbers as it found them and
    translates only that dialect's own commands into Goattracker ones, so the
    boundary moves with the version:

        0, 1, 3, 4   no command but $FF -- every other byte, up to $FD, is a
                     Hubbard pattern number
        5            likewise, and it does not even test $FE
        2, 6, 7, 8   transposes emitted as $F0-$FE; pattern numbers are <= $7F
                     because the player reads bit 7 as a command flag

    Reading a version-0 track with Goattracker's own $D0 boundary silently
    reinterprets pattern numbers $D0-$FD as repeat and transpose commands. That
    is wrong twice over: the pattern reference is lost, and a command that was
    never in the tune is inserted. 146 such bytes occur across 7 corpus files.

    Post-reindex tracks are a different thing entirely -- they are in
    Goattracker numbering, where $D0-$FF really are commands, and callers
    reading those should use GT_COMMAND_FLOOR.
    """
    if version in (2, 6, 7, 8):
        return GT_TRANSPOSE_UP
    return GT_ORDER_RESTART


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


# --- The "digi" engine's pattern grammar -----------------------------------
#
# A different encoding from the classic players', read at Off the Cuff $1104:
#
#     1104  B1 FA     LDA (patt),Y
#     1106  10 4E     BPL $1156        ; < $80 -> a note
#     1109  29 40     AND #$40
#     110B  F0 0D     BEQ $111A        ; bit 6 clear -> a command
#     110E  9D 4E 16  STA $164E,X      ; bit 6 set -> duration prefix,
#     1111  29 1F     AND #$1F         ;   wait = b & $1F, and it is *sticky*:
#     1116  C8 4C..   INY / JMP $1104  ;   fetch the next byte for the note
#     111B  C9 80     CMP #$80 -> one operand  (instrument, $165A,X)
#     111F  C9 82     CMP #$82 -> two operands ($167B,X / $1678,X)
#     1123  C9 83     CMP #$83 -> two operands ($1681,X / $1684,X)
#
# and the note path at $1156 reads the *following* byte to find the end:
#
#     1158  B1 FA     LDA (patt),Y     ; peek past the note
#     115A  C9 81     CMP #$81
#     115E  A0 00     LDY #$00         ; end of pattern: rewind
#     1160  FE 42 16  INC $1642,X      ; ...and step the orderlist
#     1168  C9 60     CMP #$60         ; $60 is a rest, not a note
#     116D  7D A0 16  ADC $16A0,X      ; note + orderlist transpose
#     1173  0A A8     ASL / TAY        ; ...into a 2-byte-per-note frequency table
#
# So $81 never appears at the fetch point -- it is only ever seen as the
# lookahead after a note. A duration of W holds for W+1 frames, the same
# DEC/BMI convention as the classic players ($10A2).
DIGI_DURATION = 0xC0        # bit 7 and bit 6 set
DIGI_END = 0x81
DIGI_SET_INSTRUMENT = 0x80
DIGI_TWO_OPERAND = (0x82, 0x83)
DIGI_REST = 0x60
DIGI_MAX_NOTE = 0x5C        # same ceiling the classic decoder clamps to


def _build_raw_pattern_digi(data: bytes, addr: int) -> Optional[List[int]]:
    """Flat event stream for one digi-engine pattern, or None if out of range.

    Effects $82 and $83 are parsed for their length but not translated -- their
    two operands land in per-voice slots this converter does not model. Notes,
    instruments and timing are complete; dropping an effect leaves a note
    playing plainly rather than corrupting the stream.
    """
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    instrument = 0
    wait = 0

    while True:
        if addr <= 1 or addr >= len(data):
            return None
        b = data[addr]

        if b == DIGI_END:
            events += [GT_END_PATTERN, 0x00, 0x00, 0x00]
            break
        if b >= DIGI_DURATION:
            wait = b & 0x1F
            addr += 1
            continue
        if b == DIGI_SET_INSTRUMENT:
            if addr + 1 >= len(data):
                return None
            # +2 for the same reason the classic decoder adds it: Goattracker
            # instrument 1 is the empty "Clear Voice" slot, so the player's
            # record 0 is written as instrument 2.
            instrument = data[addr + 1] + 2
            addr += 2
            continue
        if b in DIGI_TWO_OPERAND:
            addr += 3
            continue
        if b >= 0x80:
            # $84-$BF reach a `BNE` back to the fetch with no INY, i.e. the
            # player would spin forever. Real data never contains one, so this
            # means the pointer is not at a pattern.
            return None

        if b == DIGI_REST:
            events += [GT_NO_NOTE, 0x00, 0x00, 0x00]
        else:
            note = min(b, DIGI_MAX_NOTE) + 0x60
            events += [note, instrument, 0x00, 0x00]
        for _ in range(wait):
            events += [GT_NO_NOTE, 0x00, 0x00, 0x00]
        addr += 1

        # The terminator is only ever read as the byte after a note.
        if addr < len(data) and data[addr] == DIGI_END:
            events += [GT_END_PATTERN, 0x00, 0x00, 0x00]
            break

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


def pattern_references(tracks: List[List[int]],
                       floor: int = GT_COMMAND_FLOOR) -> List[int]:
    """Every pattern number the orderlists name, in order, with repeats.

    Walks the orderlists exactly as reindex_tracks does: $FF (LOOPSONG) is
    followed by a restart *position*, which is a small number but not a pattern
    reference, and $D0-$FE are repeat/transpose commands with no operand.

    Occurrences rather than distinct values, because callers weighing how much
    of a track is nonsense need to count how often a bad reference is played,
    not how many different ones exist.

    `floor` is the lowest byte to treat as a command. It defaults to
    Goattracker's own $D0, which is right for a track that has already been
    reindexed; pass command_floor(version) for one that has not.
    """
    refs: List[int] = []
    for track in tracks:
        expect_operand = False
        for b in track:
            if expect_operand:
                expect_operand = False
            elif b == GT_ORDER_RESTART:
                expect_operand = True
            elif b < floor:
                refs.append(b)
    return refs


def referenced_patterns(tracks: List[List[int]],
                        floor: int = GT_COMMAND_FLOOR) -> Set[int]:
    """Distinct raw Hubbard pattern numbers that some track actually plays.

    det.pattern_used is inferred from the gap between the pattern LO and HI
    tables, so it counts every entry the table has room for -- not every entry
    the song plays. Several tunes carry large unplayed remainders (Dragon's
    Lair II references 71 of the 202 patterns it emits).
    """
    return set(pattern_references(tracks, floor))


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
        step = i * det.table_stride
        lo_i, hi_i = det.pattern_lo + step, det.pattern_hi + step
        if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
            log(f"*** PATTERN ${i:X} TABLE INDEX OUT OF RANGE, CAN'T CONVERT ***")
            raw_patterns.append(list(ERROR_PATTERN))
            continue

        addr = data[hi_i] * 256 + data[lo_i]
        addr = addr - sid.load_addr + HLEN - 1
        events = (_build_raw_pattern_digi(data, addr)
                  if det.pattern_dialect == "digi"
                  else _build_raw_pattern(data, addr))
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


def pack_repeats(track: List[int]) -> List[int]:
    """Collapse runs of one repeated pattern into REPEAT commands.

    Hubbard orderlists hold long runs of a single pattern -- a drum bar held
    under a melody, a sustained intro -- and pattern slicing multiplies them,
    since every slice of a repeated pattern repeats too. Goattracker can say
    "play the next pattern n+1 times" in two bytes, so a run of L costs
    ceil(L/16)*2 instead of L. That is the only lever on the 254-byte orderlist
    limit, which no other option touches: dedup renumbers entries without
    removing any, and pruning removes patterns, not orderlist positions.

    Runs shorter than GT_MIN_REPEAT_RUN are emitted literally -- packing them
    saves nothing and a repeat of 0 is a construct the exporter drops anyway.
    """
    out: List[int] = []
    i, n = 0, len(track)
    while i < n:
        b = track[i]
        if b == GT_ORDER_RESTART:
            # $FF and the restart position that follows it are copied as a
            # unit: the operand is an ordinary small number and must never be
            # mistaken for a pattern to repeat.
            out += track[i:i + 2]
            i += 2
            continue
        if b >= MAX_PATTERNS:
            out.append(b)   # repeat/transpose command, no operand
            i += 1
            continue

        run = 0
        while i + run < n and track[i + run] == b:
            run += 1
        i += run

        # Goattracker parses one orderlist step as [transpose][repeat][pattern]
        # (gplay.c:977-988), so a repeat may follow a transpose but never
        # another repeat -- the second would be read as the step's pattern
        # number. If the stream already ends in a repeat-range byte, the first
        # element of this run is that repeat's pattern and has to stay literal.
        # Such bytes are not ours: version 0/1/3 orderlists can carry Hubbard
        # pattern numbers in $D0-$FD, which reindex_tracks passes through
        # untouched. greloc.c:683 makes the same check when exporting.
        if out and GT_REPEAT <= out[-1] < GT_TRANSPOSE_DOWN:
            out.append(b)
            run -= 1

        # Greedy is optimal here: every group costs 2 bytes whatever its
        # length, so taking the largest possible group each time minimises the
        # count, and a leftover below the threshold is cheaper written out
        # (a run of 17 packs to $DF,P,P -- 3 bytes -- not two groups of 4).
        while run >= GT_MIN_REPEAT_RUN:
            take = min(run, GT_MAX_REPEAT_RUN)
            out += [GT_REPEAT + take - 1, b]
            run -= take
        out += [b] * run
    return out


def _merged_pattern(a: int, b: int, patterns: List[List[int]], max_rows: int,
                    cache: dict) -> Optional[int]:
    """Index of a pattern playing `a` then `b`, creating it if it will fit.

    The first part's ENDPATT row is dropped: Goattracker does not trust a
    pattern's stored length, it rescans the note column for ENDPATT
    (countpatternlengths, gsong.c), so an interior one would cut the merged
    pattern in half and the second part would never play.
    """
    key = (a, b)
    if key in cache:
        return cache[key]
    if a >= len(patterns) or b >= len(patterns):
        return None
    head, tail = patterns[a], patterns[b]
    if len(head) >= 4 and head[-4] == GT_END_PATTERN:
        head = head[:-4]
    if (len(head) + len(tail)) // 4 > max_rows:
        return None
    if len(patterns) >= MAX_PATTERNS:
        return None            # no room left in Goattracker's pattern table
    patterns.append(head + tail)
    cache[key] = len(patterns) - 1
    return cache[key]


def _merge_pass(track: List[int], patterns: List[List[int]], max_rows: int,
                cache: dict) -> List[int]:
    """One left-to-right sweep merging adjacent, distinct pattern references."""
    out: List[int] = []
    i, n = 0, len(track)
    while i < n:
        b = track[i]
        if b == GT_ORDER_RESTART:
            out += track[i:i + 2]
            i += 2
            continue
        if b >= MAX_PATTERNS:
            out.append(b)       # repeat/transpose command
            i += 1
            continue
        # Only a neighbouring pattern reference with nothing between them can
        # merge -- a transpose in between applies to the second alone.
        if i + 1 < n and track[i + 1] < MAX_PATTERNS and track[i + 1] != b:
            merged = _merged_pattern(b, track[i + 1], patterns, max_rows, cache)
            if merged is not None:
                out.append(merged)
                i += 2
                continue
        out.append(b)
        i += 1
    return out


def compact_orderlist(track: List[int], patterns: List[List[int]],
                      max_rows: int, pack: bool,
                      cache: Optional[dict] = None) -> List[int]:
    """Shorten one orderlist by merging patterns, or return it unchanged.

    Slicing splits long patterns and nothing puts short ones back together, so
    an orderlist can carry more entries than the music needs. Merging two
    consecutive patterns into one costs a pattern-table slot and saves an
    orderlist byte.

    Identical neighbours are deliberately never merged: a run of one repeated
    pattern is REPEAT packing's job, and it does it better. Knucklebusters'
    middle voice packs 261 bytes down to 56 precisely because it is such a run;
    merging those pairs first would make them distinct and cost ~224 bytes.
    That is why the two are costed together here rather than applied in
    sequence -- a merge is kept only if the *packed* result is shorter.
    """
    if cache is None:
        cache = {}
    best = pack_repeats(track) if pack else track
    current = track
    while len(best) >= MAX_TRACK_LEN:
        merged = _merge_pass(current, patterns, max_rows, cache)
        if merged == current:
            break                       # nothing left to merge
        candidate = pack_repeats(merged) if pack else merged
        if len(candidate) >= len(best):
            break                       # merging is not helping this track
        best, current = candidate, merged
    return best


# --- Splitting an over-long subtune ----------------------------------------
#
# A subtune whose orderlist will not fit can be cut into consecutive subtunes,
# each of which does. The cut is not free: Goattracker starts *every* voice at
# orderlist position 0 when a subtune begins, while the C64 player lets each
# voice loop its own orderlist independently. So at the seam the short voices
# jump back to the top of their figure, and unless the cut lands on a whole
# number of their loops, everything after it plays with the accompaniment
# offset against the melody -- a subtune that sounds wrong, which is the thing
# dropping was chosen to avoid.
#
# Hence the alignment constraint. Monty on the Run's subtune 11 is the case
# that motivates it: a 27657-row voice against two 194-row voices carrying 56
# notes each. Seven of its orderlist boundaries fall on exact multiples of 194
# and four of those fit, the largest at 251 entries -- 20176 rows, exactly 104
# loops, packing to 247 bytes. A greedy "largest prefix that fits" rule takes
# 254 bytes instead and lands mid-figure.
#
# Where the short voices are silent the constraint vanishes: silence has no
# phase, so any cut is exact. That is Gremlins' subtune 23.
MAX_SUBTUNE_PARTS = 16          # runaway guard; real splits need two or three


def _unpack_repeats(track: List[int]) -> List[int]:
    """Inverse of pack_repeats: one entry per pattern played."""
    out: List[int] = []
    i = 0
    while i < len(track):
        b = track[i]
        if b == GT_ORDER_RESTART:
            out += track[i:i + 2]
            i += 2
        elif GT_REPEAT <= b < GT_TRANSPOSE_DOWN and i + 1 < len(track):
            out += [track[i + 1]] * (b - GT_REPEAT + 1)
            i += 2
        else:
            out.append(b)
            i += 1
    return out


def _body_and_tail(track: List[int]):
    """Split a track into its orderlist entries and its restart pair."""
    if len(track) >= 2 and track[-2] == GT_ORDER_RESTART:
        return track[:-2], track[-2:]
    return list(track), [GT_ORDER_RESTART, 0x00]


def _voice_rows(body: List[int], patterns: List[List[int]]) -> int:
    return sum(len(patterns[b]) // 4
               for b in body if b < MAX_PATTERNS and b < len(patterns))


def _voice_sounds(body: List[int], patterns: List[List[int]]) -> bool:
    """True if any row of any pattern this voice plays carries a note."""
    for b in body:
        if b >= MAX_PATTERNS or b >= len(patterns):
            continue
        p = patterns[b]
        if any(0x60 <= p[k] <= 0xBC for k in range(0, len(p), 4)):
            return True
    return False


def _cut_points(body: List[int], patterns: List[List[int]]):
    """(index, rows before it, transpose in effect) for every entry boundary."""
    points = []
    rows = 0
    trans = None
    for i, b in enumerate(body):
        if GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
            trans = b
            continue
        points.append((i, rows, trans))
        if b < MAX_PATTERNS and b < len(patterns):
            rows += len(patterns[b]) // 4
    return points


def split_subtune(group: List[List[int]], patterns: List[List[int]],
                  pack: bool) -> Optional[List[List[List[int]]]]:
    """Cut one over-long subtune into consecutive subtunes, or return None.

    Returns a list of 3-voice groups to play in order. None means no cut both
    fits and keeps the other voices in phase, in which case the caller drops
    the subtune rather than emitting one that plays wrongly.
    """
    if len(group) != 3:
        return None
    bodies, tails = [], []
    for t in group:
        b, tail = _body_and_tail(_unpack_repeats(t))
        bodies.append(b)
        tails.append(tail)

    over = [v for v in range(3) if len(group[v]) >= MAX_TRACK_LEN]
    if len(over) != 1:
        # Two long voices would each need their own cut, and the two cuts would
        # have to coincide. Knucklebusters is the corpus case: 21349, 15939 and
        # 19501 rows, looping independently, with no boundary common to all.
        return None
    long_v = over[0]

    # The other voices loop; a cut must land on a whole number of those loops
    # or they restart out of phase. Silent voices impose nothing.
    period = 1
    for v in range(3):
        if v == long_v or not _voice_sounds(bodies[v], patterns):
            continue
        loop = _voice_rows(bodies[v], patterns)
        if loop:
            period = period * loop // gcd(period, loop)

    def fits(entries, tail):
        out = pack_repeats(entries + tail) if pack else entries + tail
        return len(out) < MAX_TRACK_LEN

    parts: List[List[List[int]]] = []
    body = bodies[long_v]
    while True:
        if fits(body, tails[long_v]):
            parts.append((body, tails[long_v]))
            break
        if len(parts) + 1 >= MAX_SUBTUNE_PARTS:
            return None
        best = None
        for i, rows, trans in _cut_points(body, patterns):
            if i == 0 or rows % period:
                continue
            if fits(body[:i], [GT_ORDER_RESTART, 0x00]):
                best = (i, trans)
        if best is None:
            return None
        i, trans = best
        parts.append((body[:i], [GT_ORDER_RESTART, 0x00]))
        # Goattracker resets a voice's transpose to 0 at the start of a
        # subtune (gplay.c:222), so whatever was in effect at the cut has to
        # be restated or the remainder plays at the wrong pitch.
        body = ([trans] if trans is not None else []) + body[i:]

    out: List[List[List[int]]] = []
    for entries, tail in parts:
        voices = []
        for v in range(3):
            raw = (entries + tail) if v == long_v else (bodies[v] + tails[v])
            voices.append(pack_repeats(raw) if pack else raw)
        if any(len(t) >= MAX_TRACK_LEN for t in voices):
            return None
        out.append(voices)
    return out


def reindex_tracks(tracks: List[List[int]], track_index: List[List[int]],
                   pack: bool = False,
                   floor: int = GT_COMMAND_FLOOR,
                   log=None,
                   dropped: Optional[List[int]] = None,
                   split: Optional[List[int]] = None,
                   patterns: Optional[List[List[int]]] = None,
                   max_rows: int = GT_DEFAULT_ROWS) -> List[List[int]]:
    """Rewrite each orderlist's pattern numbers to their post-slicing indices.

    The length check runs at the end of each track so that `pack` -- which only
    becomes possible once the final numbering is known -- gets to act before a
    track is judged too long.

    A track over Goattracker's 254-byte orderlist limit costs its *subtune*,
    not the file. Aborting the whole conversion threw away everything else the
    tune contained: across the corpus exactly one subtune is over-long in each
    affected file, and that one abort discarded 25 good subtunes of Gremlins,
    18 of Monty on the Run and 2 of Knucklebusters.

    The subtune is replaced wholesale rather than truncated. Cutting one voice
    short while its neighbours play on makes that voice loop early and drift
    against them for the rest of the subtune -- a subtune that sounds wrong,
    which is worse than one that is plainly absent. Indices of dropped subtunes
    are appended to `dropped`, and of split ones to `split`, for callers that
    report them.

    Before dropping, a cut into consecutive subtunes is attempted -- see
    split_subtune, which refuses any cut that would restart the other voices
    out of phase.

    If nothing survives, the caller's own emptiness check refuses the file:
    a .sng of nothing but placeholders is exactly the fake success v0.5.26
    removed.
    """
    new_tracks: List[List[int]] = []
    merge_cache: dict = {}      # shared, so one merged pattern serves every voice
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
            elif b >= floor:
                # Transpose command, already in Goattracker encoding. Passes
                # through, but -- unlike the original's sticky end-marker flag
                # -- does NOT stop re-indexing the rest of the track. Mega
                # Apocalypse-family transposes emit $E0-$FF, so the old latch
                # silently left every pattern number after the first transpose
                # pointing at pre-split indices.
                #
                # `floor` moves with the player dialect. Using Goattracker's
                # own $D0 here read a version-0 pattern number of $D0-$FD as a
                # command and emitted it verbatim, losing the reference and
                # inventing a repeat or transpose in its place.
                new_track.append(b)
            else:
                new_track.extend(track_index[b] if b < len(track_index) else [])
        packed = pack_repeats(new_track) if pack else new_track
        # Merging is attempted only for a track that would otherwise cost its
        # subtune, so no track that already fits is rewritten and the fixture
        # cannot move.
        if len(packed) >= MAX_TRACK_LEN and patterns is not None:
            packed = compact_orderlist(new_track, patterns, max_rows, pack,
                                       merge_cache)
        new_tracks.append(packed)

    # Voices come in threes; one over-long voice takes its subtune with it,
    # because a subtune missing a voice does not play the tune either.
    out: List[List[int]] = []
    for first in range(0, len(new_tracks), 3):
        group = new_tracks[first:first + 3]
        longest = max((len(t) for t in group), default=0)
        if longest < MAX_TRACK_LEN:
            out += group
            continue
        subtune = first // 3

        # Prefer cutting the subtune into consecutive parts over losing it, but
        # only where the cut keeps the other voices in phase -- see
        # split_subtune. Falls back to dropping when no such cut exists.
        parts = (split_subtune(group, patterns, pack)
                 if patterns is not None and len(group) == 3 else None)
        if parts:
            if log:
                log(f"Subtune ${subtune:X} orderlist is {longest} bytes; split "
                    f"into {len(parts)} consecutive subtunes")
            if split is not None:
                split.append(subtune)
            for voices in parts:
                out += voices
            continue

        if log:
            log(f"*** SUBTUNE ${subtune:X} ORDERLIST IS {longest} BYTES, OVER "
                f"GOATTRACKER'S {MAX_TRACK_LEN - 1}-BYTE LIMIT -- DROPPED ***")
        if dropped is not None:
            dropped.append(subtune)
        out += [list(DEFAULT_TRACK) for _ in range(3)]
    return out
