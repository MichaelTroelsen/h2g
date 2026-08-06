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
from .goatwriter import CMD_SETTEMPO
from .sidfile import SidFile

# Rows per pattern to slice at. The original VB6 tool used 94, the limit of the
# Goattracker of its day; v2.32 raised MAX_PATTROWS to 128 (confirmed in
# goattracker2 src/gcommon.h and readme.txt). 94 stays the default because it is
# what the byte-exact Commando fixture encodes -- see convert(max_rows=...).
GT_DEFAULT_ROWS = 94
GT_MAX_ROWS = 128  # == MAX_PATTROWS in gcommon.h

GT_MAX_PATTERN_LEN = GT_DEFAULT_ROWS * 4  # 376 bytes
# gcommon.h calls $BD "REST", but in a pattern's note column it is a no-op:
# gplay.c:908-941 tests KEYOFF ($BE), KEYON ($BF) and <= LASTNOTE ($BC), and
# $BD matches none of them, so the row leaves the gate and the note untouched.
# Silencing a voice is $BE, which clears cptr->gate.
GT_NO_NOTE = 0xBD
GT_KEYOFF = 0xBE
# gcommon.h FIRSTNOTE/LASTNOTE: the whole note column, C-0 to G#7. Every other
# value in that column ($BD-$BF, $FF) is a marker, not a pitch.
GT_FIRSTNOTE = 0x60
GT_LASTNOTE = 0xBC
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

# Commands whose data byte is a *packed value* in a GTS2 file but a **1-based
# index into the speed table** everywhere else (gcommon.h: CMD_PORTAUP 1,
# CMD_PORTADOWN 2, CMD_TONEPORTA 3). gplay.c:740 reads the speed as
# `(ltable[STBL][cmddata-1] << 8) | rtable[STBL][cmddata-1]`, so a raw value
# left in that column indexes whatever the speed table holds at that position
# -- and this writer emitted an *empty* speed table, which meant every
# portamento command it wrote was silently inert in a GTS5 file. GTS2 files
# escaped it because the loader converts the column itself (gsong.c:311-321).
#
# CMD_SETTEMPO (15) is deliberately absent: gplay.c:494 uses its value
# directly and never consults the table.
GT_SPEEDTABLE_COMMANDS = (1, 2, 3)

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
        9            $FE is the only marker it has (loop to start), so $FD is
                     still a pattern number

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
    if version == 9:
        return 0xFE
    return GT_ORDER_RESTART


ERROR_PATTERN = [0xBD, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]


class ConversionAbort(Exception):
    pass


def _build_raw_pattern(data: bytes, addr: int,
                       slide_operand: bool = False,
                       note_flag: bool = False,
                       status_bit6: bool = False,
                       span: Optional[List[int]] = None,
                       note_base: int = 0) -> Optional[List[int]]:
    """Flat event stream for one Hubbard pattern, or None if out of range.

    slide_operand says the player fetches a *second* byte after a `>= $80`
    command operand -- the high half of a 16-bit pitch-slide step. See
    detect.SLIDE_OPERAND_SHAPE. It is off by default because 54 of 95 corpus
    players do not have that fetch, and reading a byte they never read
    desynchronises the rest of the pattern.

    status_bit6 says the player tests bit 6 of the status byte first and
    alone (`BIT status / BVS`, detect.STATUS_BIT6_SHAPE), branching past the
    operand read AND the note read -- so a $C0-$FE status byte consumes only
    itself, where the bit-7-first reading below consumes three bytes. Off by
    default: the byte-exact Commando fixture encodes the old reading.

    `span`, when given a list, receives the number of bytes the decode
    consumed (terminator included) -- what phantom_patterns needs to know
    which file bytes an entry would claim as pattern data. Nothing is
    appended when the decode fails.

    `note_base` shifts every note byte before it becomes a Goattracker note,
    for the player whose frequency table does not start where Goattracker's
    does (detect.Detection.note_base). Zero for all but one corpus file.
    """
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
            if span is not None:
                span.append(i2 + 1)
            break

        get_next = b1 & 0x80
        no_note = b1 & 0x40
        no_adsr = b1 & 0x20
        wait = b1 & 0x1F

        # In the players with the BIT/BVS shape, bit 6 is tested *first* and
        # on its own -- Commando $50CF `BIT status / BVS $5118` jumps past the
        # operand read AND the note read whatever bit 7 says, so a status byte
        # of $C0-$FE consumes nothing but itself where the `get_next` /
        # `get_next or not no_note` reads below consume three bytes. Zeroing
        # get_next reproduces that skip: no operand is read, and the note
        # condition reduces to `not no_note`, which bit 6 has already denied.
        # The low 5 bits still count -- the player stores the wait before the
        # BVS -- and the event emits its hold rows like any other no-note one.
        if status_bit6 and no_note:
            get_next = 0

        if get_next:
            i2 += 1
            b2 = data[addr + i2]
            if no_adsr:
                if g_old_instr1 == g_old_instr2:
                    cmd1 = 3   # Portamento (no new ADSR)
                    cmd2 = 0x00
                g_old_instr2 = g_old_instr1
            if b2 & 0x80:
                # Bit 0 is the direction, and it is the player's own test:
                # Warhawk $132D does `AND #$01 / BEQ add`, so a clear bit adds
                # to the frequency (CMD_PORTAUP, 1) and a set bit subtracts
                # (CMD_PORTADOWN, 2). The two comments below have always been
                # the wrong way round; the values they emit are right.
                if (b2 & 1) == 0:
                    cmd1, g_instrument = 1, 0  # pitch down
                else:
                    cmd1, g_instrument = 2, 0  # pitch up
                cmd2 = (b2 & 0x7F) // 4
                if slide_operand:
                    # The step is 16-bit: this byte is its low half (masked
                    # $7E -- bit 0 is the direction flag, bit 7 the command
                    # flag) and the *next* byte is its high half. Warhawk
                    # $1320 adds both to the voice frequency each frame.
                    #
                    # Goattracker's own portamento parameter is the 16-bit
                    # speed divided by four (gtable.c:881, MST_PORTAMENTO:
                    # `l = (data << 2) >> 8, r = (data << 2) & 0xff`), so
                    # emit that and let build_speed_table encode it.
                    i2 += 1
                    if addr + i2 >= len(data):
                        return None
                    speed = (data[addr + i2] << 8) | (b2 & 0x7E)
                    cmd2 = min(speed // 4, 0xFF)
            else:
                g_instrument = (b2 & 0x7F) + 2
                g_old_instr2 = g_old_instr1
                g_old_instr1 = g_instrument

        if get_next or not no_note:
            i2 += 1
            g_note = data[addr + i2]
            if note_flag:
                # Bit 7 is the player's legato flag (`AND #$7F` before the
                # frequency lookup), not part of the note. Goattracker has no
                # tie, so the flag itself is dropped and the note is kept --
                # the player still re-gates, so the attack is real.
                g_note &= 0x7F
            if g_note >= 0x5C:
                g_note = 0x5C
            # A shifted table can push the lowest byte below its own entry 0;
            # that entry holds $0000 in the one player this applies to, so the
            # player sounds no pitch there at all. Goattracker's bottom note is
            # 16 Hz and equally inaudible, which is what the byte already
            # produced before the shift existed.
            g_note = max(0, g_note + note_base) + 0x60

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


def _build_raw_pattern_digi(data: bytes, addr: int,
                            note_base: int = 0) -> Optional[List[int]]:
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
            # The player's rest closes the gate: $1184 does DEC $165D,X, taking
            # the mask just set to $FF at $10FF down to $FE -- the same value
            # its end-of-note release path writes. $165D,X is ANDed into the
            # $D404 write at $148D, so bit 0 (GATE) is cleared. A hold row
            # ($BD) would sustain the previous note instead.
            events += [GT_KEYOFF, 0x00, 0x00, 0x00]
        else:
            note = max(0, min(b, DIGI_MAX_NOTE) + note_base) + 0x60
            events += [note, instrument, 0x00, 0x00]
        for _ in range(wait):
            events += [GT_NO_NOTE, 0x00, 0x00, 0x00]
        addr += 1

        # The terminator is only ever read as the byte after a note.
        if addr < len(data) and data[addr] == DIGI_END:
            events += [GT_END_PATTERN, 0x00, 0x00, 0x00]
            break

    return events


# --- The "command table" engine's pattern grammar ---------------------------
#
# Chicken Song $10A0 / Hollywood or Bust $04A9; see detect._detect_cmdtable
# for the disassembly this is read from.
#
#   b >= $80   a command. b & $0F indexes a jump table of handlers, each of
#              which consumes a fixed number of operand bytes and returns to
#              the fetch point without consuming a duration. One of them sets
#              the instrument.
#   b <  $80   a note event lasting durations[b & $1F] frames -- an index
#              into a table, not a frame count.
#              bit 6 set -> no note byte follows (the event is a hold)
#              bit 6 clear -> a note byte follows; its bit 7 is a legato flag
#              that the player masks off (`AND #$7F`) before the frequency
#              lookup, and its low 7 bits are the note.
#   $FF        end of pattern -- and, exactly as in the digi engine, it is
#              only ever *peeked* ($1169: INC pos / LDA (patt),Y / CMP #$FF),
#              never fetched, so a decoder that only tests fetched bytes runs
#              past the end of every pattern.
#
# A duration D is D frames, not D+1: $105C tests the counter for zero
# *before* the fetch and $141C decrements it at the end of each frame's
# per-voice pass, so the DEC/BMI reasoning of the classic players (§5) does
# not apply here.
CMDTABLE_MAX_NOTE = 0x5C


def _build_raw_pattern_cmdtable(data: bytes, addr: int, durations: int,
                                operands, instr_cmd: int,
                                frames_per_row: int = 1,
                                collect: Optional[Set[int]] = None,
                                note_base: int = 0
                                ) -> Optional[List[int]]:
    """Flat event stream for one command-table pattern, or None if unusable.

    With `collect` given, the durations the pattern uses are added to it and
    the returned stream is ignored -- that pre-pass is how frames_per_row is
    derived (see cmdtable_frames_per_row).
    """
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    instrument = 0

    for _ in range(20000):
        if addr <= 1 or addr >= len(data):
            return None
        b = data[addr]
        if b == GT_END_PATTERN:
            # Only reachable on a malformed pattern -- a well-formed one ends
            # at the peek below -- but ending here beats reading $FF as
            # command $F, which indexes past a jump table of six entries.
            events += [GT_END_PATTERN, 0x00, 0x00, 0x00]
            break

        if b & 0x80:
            c = b & 0x0F
            if c >= len(operands):
                return None
            if addr + operands[c] >= len(data):
                return None
            if c == instr_cmd:
                # +2 for the same reason every other decoder here adds it:
                # Goattracker instrument 1 is the empty "Clear Voice" slot.
                instrument = data[addr + 1] + 2
            addr += 1 + operands[c]
            continue

        di = durations + (b & 0x1F)
        if not 0 <= di < len(data):
            return None
        frames = data[di]
        if frames < 1:
            return None
        if collect is not None:
            collect.add(frames)
        rows = max(1, frames // frames_per_row)
        if b & 0x40:
            events += [GT_NO_NOTE, 0x00, 0x00, 0x00]
            addr += 1
        else:
            if addr + 1 >= len(data):
                return None
            note = max(0, min(data[addr + 1] & 0x7F,
                              CMDTABLE_MAX_NOTE) + note_base) + 0x60
            events += [note, instrument, 0x00, 0x00]
            addr += 2
        events += [GT_NO_NOTE, 0x00, 0x00, 0x00] * (rows - 1)

        if addr < len(data) and data[addr] == GT_END_PATTERN:
            events += [GT_END_PATTERN, 0x00, 0x00, 0x00]
            break
    else:
        return None

    return events


def cmdtable_frames_per_row(sid: SidFile, det: Detection,
                            used: Optional[Set[int]] = None) -> int:
    """How many player calls one Goattracker row should last, for this tune.

    Every other dialect measures an event in frames and emits one row per
    frame, so a row is a frame. This engine measures events in a *duration
    table* whose entries are 6 12 24 36 72 48 96 18 (Chicken Song) and
    3 6 12 18 36 24 48 (Hollywood or Bust) -- so its shortest note is already
    three or six frames long, and one row per frame would make the tune three
    to six times longer than the .sng needs to be.

    That is not merely wasteful: Goattracker's fastest *steady* row is three
    calls (gplay.c:325 -- 0 and 1 are funktempo, not a rate), so a one-row-
    per-frame stream cannot play at one frame per row and the tune comes out
    three times too slow. Dividing the durations by their common factor and
    handing that factor to CMD_SETTEMPO plays them at exactly the right rate.
    Chicken Song's melody similarity goes from 47% to 98% on this alone.

    Only the durations the tune actually uses are divided: the table's length
    is not recorded anywhere, and reading past its end picks up the frequency
    table that follows it, whose bytes would destroy the common factor.
    Returns 1 when no usable factor exists, which leaves the old behaviour.
    """
    if det.pattern_dialect != "cmdtable":
        return 1
    data = sid.data
    seen: Set[int] = set()
    for i in range(det.pattern_used + 1):
        if used is not None and i not in used:
            continue
        lo_i, hi_i = det.pattern_lo + i, det.pattern_hi + i
        if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
            continue
        _build_raw_pattern_cmdtable(
            data, sid.to_offset(data[hi_i] * 256 + data[lo_i]),
            det.duration_table, det.cmd_operands, det.cmd_instrument,
            collect=seen)
    factor = 0
    for v in seen:
        factor = gcd(factor, v)
    # Goattracker reads a tempo under 2 as funktempo rather than a rate, and
    # CMD_SETTEMPO's value is 7 bits.
    return factor if 2 <= factor <= 0x7F else 1


def decode_entry(sid: SidFile, det: Detection, i: int,
                 slides: bool = False,
                 status_bit6: bool = False) -> Optional[List[int]]:
    """Decoded event stream for pattern-table entry `i`, or None if unusable.

    The dialect dispatch convert_patterns and phantom_patterns both perform,
    in one place, so a caller that needs a pattern's *contents* (rather than
    its place in the output) reads it under exactly the grammar the
    conversion will use. tracks.fold_transposes is such a caller: it has to
    know a pattern's highest note before deciding whether an octave can be
    folded into it, and reading that under a different grammar would answer a
    question about a file that is not being converted.
    """
    data = sid.data
    step = i * det.table_stride
    lo_i, hi_i = det.pattern_lo + step, det.pattern_hi + step
    if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
        return None
    addr = sid.to_offset(data[hi_i] * 256 + data[lo_i])
    if det.pattern_dialect == "digi":
        return _build_raw_pattern_digi(data, addr, det.note_base)
    if det.pattern_dialect == "cmdtable":
        return _build_raw_pattern_cmdtable(
            data, addr, det.duration_table, det.cmd_operands,
            det.cmd_instrument, det.frames_per_row,
            note_base=det.note_base)
    return _build_raw_pattern(data, addr, slides and det.slide_operand,
                              det.note_flag, status_bit6 and det.status_bit6,
                              note_base=det.note_base)


def pattern_top_note(events: List[int]) -> int:
    """Highest pitch in an event stream, or 0 if it sounds no note."""
    return max((events[k] for k in range(0, len(events), 4)
                if GT_FIRSTNOTE <= events[k] <= GT_LASTNOTE), default=0)


def shift_notes(events: List[int], semitones: int) -> List[int]:
    """Copy of an event stream with every pitch raised, markers untouched.

    Only the note column moves, and only where it holds a pitch: $BD (hold),
    $BE (key off) and $FF (end of pattern) are not notes and shifting them
    would turn one into another.
    """
    out = list(events)
    for k in range(0, len(out), 4):
        if GT_FIRSTNOTE <= out[k] <= GT_LASTNOTE:
            out[k] += semitones
    return out


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


def _overlap(a_start: int, a_len: int, b_start: int, b_len: int) -> bool:
    return a_start < b_start + b_len and b_start < a_start + a_len


def phantom_patterns(sid: SidFile, det: Detection,
                     slides: bool = False,
                     status_bit6: bool = False) -> dict:
    """Entries of the inferred pattern table that provably are not pattern data.

    The `hi - lo - 1` entry count (detect.py, H2G-CONVERSION-METHOD.md §4.2)
    is table-adjacency arithmetic: nothing says every byte in the gap between
    the LO and HI arrays is an authored entry, so the table can claim entries
    whose "pointer" is whatever bytes happen to sit in the cells. Decoding
    such an entry yields garbage whose shape swings arbitrarily with any
    change to the decode grammar -- Last V8's entry $1C points one byte past
    the last real pattern's terminator, straight into the player's own
    track-selector routine, and blocked the (verified-correct) bit-6 status
    read for exactly that reason.

    An entry is judged phantom on the player's own terms, never statistically:

      * its table cell, or the address stored in it, lies outside the file
        (the existing per-entry guards in convert_patterns catch these too;
        naming them here gives every rejection one vocabulary), or
      * decoding it under the file's own grammar -- the same dialect,
        slide-operand, note-flag and bit-6 settings the conversion will use
        -- runs off the end of the file, or
      * the bytes the decode would claim overlap the pattern pointer tables
        themselves, or code that detection matched a player signature in
        (det.code_spans). Those bytes are *known* to be something other than
        pattern data; a decode that "succeeds" over them is reading the
        player as music.

    This is deliberately not a reachability test: patterns that no orderlist
    references are --prune-patterns' business, and orderlists that reference
    entries beyond the table (dangling references, SURVEY.md) are a separate,
    known phenomenon this pass must not conflate with.

    Returns {entry index: reason string}; empty when the table is sound.
    """
    data = sid.data
    n = det.pattern_used + 1
    stride = det.table_stride
    # The pointer tables themselves, and every signature-matched run of
    # player code, are provably not pattern data.
    not_data = [(det.pattern_lo, n * stride), (det.pattern_hi, n * stride)]
    not_data += det.code_spans

    out: dict = {}
    for i in range(n):
        step = i * stride
        lo_i, hi_i = det.pattern_lo + step, det.pattern_hi + step
        if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
            out[i] = "table cell outside the file"
            continue
        addr = sid.to_offset(data[hi_i] * 256 + data[lo_i])
        if addr <= 1 or addr >= len(data):
            out[i] = "address outside the file"
            continue

        span: List[int] = []
        if det.pattern_dialect == "digi":
            events = _build_raw_pattern_digi(data, addr)
        elif det.pattern_dialect == "cmdtable":
            events = _build_raw_pattern_cmdtable(
                data, addr, det.duration_table, det.cmd_operands,
                det.cmd_instrument, det.frames_per_row)
        else:
            events = _build_raw_pattern(data, addr,
                                        slides and det.slide_operand,
                                        det.note_flag,
                                        status_bit6 and det.status_bit6,
                                        span=span)
        if events is None:
            out[i] = "decode runs off the end of the file"
            continue
        if span:        # classic dialect only: the byte extent is known
            hit = next((s for s in not_data
                        if _overlap(addr, span[0], s[0], s[1])), None)
            if hit is not None:
                what = ("the pattern pointer tables"
                        if hit in not_data[:2] else
                        f"player code (signature at offset {hit[0]})")
                out[i] = f"decode overlaps {what}"
    return out


def build_speed_table(patterns: List[List[int]]) -> List[tuple]:
    """Encode every portamento parameter as a speed table, in place.

    Rewrites each speedtable-requiring command's data column to a 1-based
    index and returns the table as (left, right) pairs.

    The encoding is Goattracker's own, so a GTS5 file plays identically to the
    GTS2 file it was written from: `makespeedtable(v, MST_PORTAMENTO)` is
    `l = (v << 2) >> 8, r = (v << 2) & 0xff` (gtable.c:881-884), i.e. the
    16-bit per-frame frequency step is four times the stored value. gplay.c
    reassembles it as `(l << 8) | r`.

    The table cannot overflow: a data byte has 255 non-zero values and each
    distinct one costs one entry, which is exactly MAX_TABLELEN.
    """
    index: dict = {}
    table: List[tuple] = []
    for pattern in patterns:
        for k in range(0, len(pattern), 4):
            cmd, value = pattern[k + 2], pattern[k + 3]
            # value 0 means "no parameter": gplay.c leaves cmddata 0 alone and
            # every command special-cases it, so it must stay 0 rather than
            # become index 1.
            if cmd not in GT_SPEEDTABLE_COMMANDS or not value:
                continue
            if value not in index:
                index[value] = len(table)
                table.append(((value * 4) >> 8 & 0xFF, (value * 4) & 0xFF))
            pattern[k + 3] = index[value] + 1
    return table


def convert_patterns(sid: SidFile, det: Detection, log,
                     max_rows: int = GT_DEFAULT_ROWS,
                     terminate_patterns: bool = False,
                     dedup: bool = False,
                     used: Optional[Set[int]] = None,
                     slides: bool = False,
                     status_bit6: bool = False,
                     phantoms: Optional[dict] = None,
                     variants: Optional[List[tuple]] = None):
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

    `phantoms` (from phantom_patterns) rejects entries that provably are not
    pattern data: each gets the same ERROR_PATTERN placeholder an
    undecodable address gets, so a track that references one still resolves
    -- to a single rest -- instead of to the player's own code decoded as
    music.

    `variants` (from tracks.fold_transposes) appends octave-shifted copies of
    existing entries, as `(source entry, octaves)` pairs. They extend the
    pattern table's numbering rather than replacing anything: variant j is
    entry `det.pattern_used + 1 + j`, which is the number the folded
    orderlists already reference. A source that `used` pruned is decoded here
    anyway -- the variant is played even when the unshifted original is not.
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

        if phantoms and i in phantoms:
            log(f"*** PATTERN ${i:X} IS NOT PATTERN DATA "
                f"({phantoms[i]}), REJECTED ***")
            raw_patterns.append(list(ERROR_PATTERN))
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

        events = decode_entry(sid, det, i, slides, status_bit6)
        if events is None:
            log(f"*** PATTERN ${i:X} ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            events = list(ERROR_PATTERN)
        raw_patterns.append(events)

    # Appended after the whole table, never inserted into it, so entry numbers
    # 0..pattern_used keep meaning what the orderlists say they mean.
    for src, octaves in (variants or ()):
        base = raw_patterns[src] if 0 <= src < len(raw_patterns) else None
        if base is None:
            base = decode_entry(sid, det, src, slides, status_bit6)
        if base is None:
            log(f"*** PATTERN ${len(raw_patterns):X} (${src:X} +{12 * octaves}) "
                "ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            raw_patterns.append(list(ERROR_PATTERN))
        else:
            raw_patterns.append(shift_notes(base, 12 * octaves))

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
        # Over the pattern *table*, not raw_patterns: appended variants are
        # extra outputs, not table entries that could have been pruned.
        total = det.pattern_used + 1
        pruned = sum(1 for p in raw_patterns[:total] if p is None)
        if pruned:
            log(f"Pruned {pruned} of {total} patterns "
                f"({100 * pruned // total}%) that no track plays")

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
        if any(GT_FIRSTNOTE <= p[k] <= GT_LASTNOTE for k in range(0, len(p), 4)):
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


def apply_tempo(patterns: List[List[int]], tracks: List[List[int]],
                value: int, log=None) -> int:
    """Write CMD_SETTEMPO into the first row each subtune plays.

    Goattracker has no per-row duration, so a converted tune needs the song
    tempo set once; gplay.c:494 applies a value under $80 to all three
    channels at once, and the setting persists, so one row per subtune is
    enough. It goes in *pattern data*, which is why it survives gt2reloc --
    the instrument-63 route it replaces did not.

    Written only into a row whose command column is free, so a portamento or
    vibrato this converter emitted is never overwritten. A pattern shared by
    several positions simply re-applies the same tempo, which is harmless.

    Returns how many rows were written.
    """
    written = 0
    for first in range(0, len(tracks), 3):
        # The orderlist grammar, not a scan for a small byte: the value after
        # $FF is a restart *position*, and taking it as a pattern number would
        # aim the tempo at whatever pattern happens to share that index -- or
        # at pattern 0 of a subtune that plays nothing.
        played = pattern_references([tracks[first]], GT_COMMAND_FLOOR)
        if not played or played[0] >= len(patterns):
            continue
        target = played[0]
        pattern = patterns[target]
        if len(pattern) < 4 or pattern[2] != 0:
            continue
        pattern[2], pattern[3] = CMD_SETTEMPO, value
        written += 1
    if log and written:
        log(f"Tempo...................: CMD_SETTEMPO ${value:02X} in {written} "
            f"pattern(s) -- {value if value < 3 else value - 1} tempo, "
            f"{(value if value < 3 else value - 1) + 1} calls per row")
    return written


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
