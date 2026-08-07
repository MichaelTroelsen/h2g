"""Rob Hubbard player-engine detection via opcode-signature matching.

Port of the FindInstruments/FindSubSongs/FindTrackSelector/FindPattern/
FindPlayerVersion blocks in loadfile() (h2g.frm:300-473).

Every game listed in a comment below is a distinct Hubbard player-engine
binary layout; the tool has no idea what game a file is, it just tries each
known byte fingerprint in turn until one matches. Adding support for a new
game/player revision means adding a new signature (and offset) to one of
these chains -- see CLAUDE.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .search import search_file
from .sidfile import HLEN, FreqTable, SidFile, find_freq_table

WAVEFORMS = {
    0x00, 0x01, 0x09, 0x11, 0x13, 0x15, 0x17, 0x21, 0x23, 0x25, 0x27,
    0x41, 0x43, 0x45, 0x47, 0x51, 0x53, 0x55, 0x57, 0x81,
}

Logger = Callable[[str], None]


@dataclass
class Detection:
    instr_start: int = -1
    instr_used: int = -1
    track_voices: int = 3
    track_selector: bool = False
    track_hi: int = -1
    track_lo: int = -1
    pattern_hi: int = -1
    pattern_lo: int = -1
    pattern_used: int = -1
    read_track_version: int = 0xFF
    # Upper bound on subtunes taken from the data rather than the PSID header,
    # or 0 when nothing bounds it. The digi engine's orderlist table is capped
    # by the pattern table that follows it.
    subtunes_available: int = 0
    # Version 2 only: the transpose value lives in the byte *after* the command
    # byte rather than in the command byte's own low 7 bits. See detect().
    transpose_operand: bool = False
    # Distance in bytes between consecutive entries of a pointer table. 1 for
    # the separate LO-table/HI-table layout every classic Hubbard player uses;
    # 2 for the "digi" engine, which interleaves lo,hi,lo,hi and doubles the
    # index with ASL before TAY. When it is 2, pattern_hi == pattern_lo + 1.
    table_stride: int = 1
    # Bytes per instrument record: 8 in the classic players, 16 in the digi
    # engine. The fields this converter reads (waveform +2, attack/decay +3,
    # sustain/release +4) sit at the same offsets in both.
    instr_stride: int = 8
    # Which pattern-byte grammar the tune uses -- see patterns.py.
    pattern_dialect: str = "classic"
    # True when the player fetches a SECOND pattern byte after a `>= $80`
    # command operand -- the high byte of a 16-bit pitch-slide step. See
    # _find_slide_operand().
    slide_operand: bool = False
    # True when that second byte is the step's LOW half rather than its high,
    # and the direction is a `CMP #$BF` threshold rather than the operand's
    # bit 0 -- a second slide dialect sharing the same fetch shape. 22 corpus
    # files. See _find_slide_high_first().
    slide_high_first: bool = False
    # Instrument-record offset of the vibrato parameter byte (+5 wherever it
    # is found), or None where the player has no such routine. See
    # _find_vibrato().
    vibrato_offset: Optional[int] = None
    # The OTHER vibrato: an LFO table walked one entry per frame, which is the
    # command-table engine's form and shares no byte format with the above.
    # Mutually exclusive with vibrato_offset -- see _find_table_vibrato().
    table_vibrato: "TableVibrato | None" = None
    # True when the player's instrument effect byte (+7) really is Warhawk's
    # bit-field, proved by finding the routine that tests it. The byte is NOT
    # a shared format across the player family -- see _find_effect_routines().
    effect_rise: bool = False   # bit $02: +1 semitone every 4 frames
    effect_arp: bool = False    # bit $04: alternate with note - (byte >> 4)
    effect_drum: bool = False   # bit $01: pitch sweep down, then noise
    effect_pulse_lo: bool = False  # bit $08: accumulate +6 into pulse width LO
    # A SECOND, mutually exclusive reading of the same byte -- see
    # _find_two_stage(). In this family bit $04 is not an arpeggio at all: it
    # holds an attack waveform for a per-instrument number of frames and then
    # drops to the record's own +2. Both file offsets are indexed by the same
    # i * instr_stride the effect byte itself is.
    effect_two_stage: bool = False
    two_stage_wave: int = -1    # file offset of the attack-waveform table
    two_stage_frames: int = -1  # file offset of its duration table
    # The per-frame pulse-width sweep -- see _find_pulse_sweep(). Both are set
    # together or neither is. `pulse_bounds` is the file offset of an array
    # indexed by the same i * instr_stride the records are, holding the two
    # nibbles the sweep turns around at; `pulse_rate_field` is the byte offset
    # within a record that holds the per-frame step.
    pulse_bounds: int = -1
    pulse_rate_field: int = -1
    # The *other* pulse engine, selected by effect bit $08 and mutually
    # exclusive with the sweep above: 34 corpus files sweep, 21 accumulate,
    # none do both. `pulse_lo_base` is the file offset of a second
    # per-instrument record array, strided like the instrument table, whose
    # +0/+1 seed the 12-bit width at note start and whose +6 is added to the
    # low byte every frame. -1 when the block is absent or unreadable.
    pulse_lo_base: int = -1
    # Effect byte bit $80, in the eight-flag format only -- and it is not one
    # block. The 12 corpus files that test it split three ways; see
    # _find_effect_bit80(). "sfx" (9 files) is the *game's* sound effect, keyed
    # off a global state cell no converted tune ever writes; "program" (2) is a
    # per-instrument byte-code wave program; "pitch" (1) steps the frequency
    # from a duration/delta table. Read only -- goatwriter consumes none of it,
    # for the reasons in H2G-CONVERSION-METHOD.md section 7.jj.
    effect_bit80: str = ""
    # File offset of the "program" shape's per-instrument pointer array (two
    # bytes per record, strided like the instrument table), or -1.
    effect_program: int = -1
    # Classic dialect only: bit 7 of a pattern note byte is a flag, not part of
    # the note -- the player masks it off before the frequency lookup.
    note_flag: bool = False
    # True when the player tests bit 6 of the status byte FIRST and alone
    # (`BIT status / BVS`), branching past the operand read AND the note read
    # -- so a $C0-$FE status byte consumes only itself. See STATUS_BIT6_SHAPE.
    status_bit6: bool = False
    # "cmdtable" dialect only (see _detect_cmdtable): file offset of the
    # note-duration lookup table, how many operand bytes each $8x command
    # takes, and which command index sets the instrument.
    duration_table: int = -1
    cmd_operands: tuple = ()
    cmd_instrument: int = -1
    # "cmdtable" dialect: which $8x command is the pitch slide, and the mask
    # its handler applies to the second operand to get the step's high half.
    # -1 when the shape is absent. See _cmdtable_slide().
    cmd_slide: int = -1
    cmd_slide_mask: int = 0
    # Player calls one emitted row is meant to last. 1 everywhere except the
    # "cmdtable" dialect, whose durations come from a table of multiples --
    # see patterns.cmdtable_frames_per_row, which fills this in.
    frames_per_row: int = 1
    # The instrument each voice plays before any pattern selects one. The
    # player keeps a per-voice instrument index in a three-byte array and only
    # writes it when a pattern carries an instrument byte, so the array's
    # image value is what a voice sounds until then. Empty when the shape that
    # names it (INSTRUMENT_INDEX_SHAPE) is not present. See
    # tracks.apply_initial_instruments.
    initial_instruments: Tuple[int, ...] = ()
    # The per-instrument filter array, once located. None in the 71 corpus
    # files whose player either has no filter routine or whose sweep origin
    # cannot be read statically -- see find_filter().
    filter: "FilterInfo | None" = None
    # (offset, length) of every signature the main detection chains matched.
    # Each is a run of bytes *known* to be the player's own code -- that is
    # what the signature fingerprints -- so anything else claiming those bytes
    # (a pattern-table entry, say) is provably not pointing at pattern data.
    # See patterns.phantom_patterns.
    code_spans: List[Tuple[int, int]] = field(default_factory=list)
    # The player's note frequency table, once located, and the semitone
    # offset a pattern's note byte needs to name the same pitch in
    # Goattracker. 0 for 88 of the 95 corpus files; -1 for the one whose
    # table has an unused $0000 at entry 0 (Skate or Die intro), which
    # without this plays a semitone sharp from end to end. See
    # sidfile.find_freq_table -- the *tuning* half of the same measurement
    # is deliberately not applied here, only reported.
    freq_table: Optional[FreqTable] = None
    note_base: int = 0

    @property
    def can_convert(self) -> bool:
        return (self.track_lo > 0 and self.track_hi > 0
                and self.pattern_lo > 0 and self.pattern_hi > 0)


def _addr16(data: bytes, lo_pos: int, hi_pos: int) -> int:
    return data[hi_pos] * 256 + data[lo_pos]


def _base_ok(label: str, offset: int, data_len: int, log: Logger) -> bool:
    """True if a table base offset lands inside the data section.

    Signature matching gives no guarantee that the address it extracts is
    meaningful: a fingerprint can match a byte sequence that is not really the
    player's table-read instruction, and the operand then points anywhere. The
    per-read guards downstream stop that from crashing, but on their own they
    turn a wholly bogus detection into a structurally valid, musically empty
    .sng -- a silent failure that reads as success. Rejecting the base here
    makes it a loud one.
    """
    if 0 <= offset < data_len:
        return True
    log(f"*** {label} ADDRESS OUT OF RANGE (offset {offset}, file {data_len} bytes) ***")
    return False


def _span_warn(label: str, offset: int, count: int, data_len: int, log: Logger) -> None:
    """Warn when a table's *extent* runs past EOF, without rejecting it.

    Unlike a bad base this is recoverable -- the entry count is inferred, not
    read, so an over-long table usually means the count is wrong rather than
    the address. Callers bounds-check each entry, so the usable prefix still
    converts; this only surfaces that some entries were unreachable.
    """
    if count > 0 and offset >= 0 and offset + count > data_len:
        log(f"*** {label} TABLE EXTENDS PAST EOF "
            f"({offset}+{count} > {data_len}), ENTRIES WILL BE SKIPPED ***")


# --- The "digi" engine -----------------------------------------------------
#
# A later Hubbard engine, shared by nine corpus files, that none of the classic
# signatures can read. Two things defeat them:
#
#  1. Its pointer tables are *interleaved* -- one table holds lo,hi,lo,hi and
#     the player doubles the index (`ASL` / `TAY` / `LDA table,Y` /
#     `LDA table+1,Y`). The classic "entry count = HI - LO - 1" then yields
#     zero patterns, because HI is one byte past LO rather than a table away.
#
#  2. The table the orderlist-read instruction names is a *runtime* one, all
#     zeroes on disk, filled in at init. The authored pointers sit 8 bytes
#     further on (4 voices x 2 bytes of runtime pointer), and the pattern table
#     10 past those.
#
# Off the Cuff, $10AD:
#     10AD  BD 2F 18  LDA $182F,X      ; runtime pointer, zero-filled on disk
#     10B7  BC 42 16  LDY $1642,X
#     10BA  B1 F8     LDA ($F8),Y      ; orderlist byte
#     10E5  0A A8     ASL / TAY        ; pattern number * 2
#     10E7  B9 41 18  LDA $1841,Y      ; pattern lo  ) interleaved,
#     10EC  B9 42 18  LDA $1842,Y      ; pattern hi  ) one byte apart
#
# The two signatures are read independently -- one names $182F, the other
# $1841 -- and `$182F + 18 == $1841` in every file of this family. That
# relation is the discriminator: six further files match both code shapes but
# fail it, and SIDId identifies every one of those as Jason_Page/RobTracker,
# a related engine whose tables sit elsewhere.
DIGI_TRACKS = "BD ?? ?? 85 ?? BD ?? ?? 85 ?? BC ?? ?? B1"
DIGI_PATTERN = "9D ?? ?? 4C ?? ?? 0A A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? BC"
DIGI_RUNTIME_TABLE_LEN = 8   # 4 voices x 2 bytes, zero on disk
DIGI_TRACK_TO_PATTERN = 10   # authored orderlist pointers -> pattern pointers
DIGI_VOICES = 4              # the fourth carries the sample channel


def _digi_entry_ok(sid: SidFile, k: int) -> bool:
    """True if an interleaved table entry at file offset k resolves in-file."""
    data = sid.data
    if k < 0 or k + 1 >= len(data):
        return False
    off = sid.to_offset(data[k + 1] * 256 + data[k])
    return 1 < off < len(data)


# `LDA voice_instr,X / STX save / ASL ASL ASL / TAX / LDA record+2,X`: the
# player turning a voice's instrument *number* into a record offset. Records
# are 8 bytes, so the three shifts are the multiply, and the load that follows
# names the record's waveform field -- two bytes into the table.
#
# This fingerprints the load rather than the store, which is what makes it
# work where the store-shaped signatures do not, and it yields two addresses
# at once: the instrument table (operand of the second `LDA`, minus 2) and the
# per-voice instrument array the first `LDA` indexes.
INSTRUMENT_INDEX_SHAPE = "BD ?? ?? 8E ?? ?? 0A 0A 0A AA BD ?? ??"


def _find_instrument_index(sid: SidFile, det: Detection, log: Logger) -> int:
    """Locate the per-voice instrument array, and return the match offset.

    Fills `det.initial_instruments` with the array's image bytes: the
    instrument each voice sounds until one of its patterns selects another.
    The player writes this array only when a pattern carries an instrument
    byte, so for a voice whose first pattern carries none -- 41 of the
    corpus's 821 voice orderlists -- the image value is the whole answer.
    Goattracker has no equivalent: gplay.c:223 starts every channel on
    instrument 1, which this converter writes as the empty "Clear Voice"
    record, so those voices come out silent. See
    tracks.apply_initial_instruments.

    Returns -1 when the shape is absent, which leaves every caller on its
    existing path.
    """
    data = sid.data
    i = search_file(data, INSTRUMENT_INDEX_SHAPE)
    if i <= -1:
        return -1
    off = sid.to_offset(_addr16(data, i + 1, i + 2))
    if off < 0 or off + 3 > len(data):
        return i
    det.initial_instruments = tuple(data[off:off + 3])
    log("Initial instruments.....: "
        + " ".join(f"${b:02X}" for b in det.initial_instruments))
    return i


def _detect_digi(sid: SidFile, det: Detection, log: Logger) -> bool:
    """Recognise the interleaved-table engine, or leave `det` untouched."""
    data = sid.data
    it, ip = search_file(data, DIGI_TRACKS), search_file(data, DIGI_PATTERN)
    if it <= -1 or ip <= -1:
        return False
    runtime = _addr16(data, it + 1, it + 2)
    pattern = _addr16(data, ip + 9, ip + 10)
    tracks = runtime + DIGI_RUNTIME_TABLE_LEN
    if pattern != tracks + DIGI_TRACK_TO_PATTERN:
        return False

    lo = sid.to_offset(tracks)
    plo = sid.to_offset(pattern)
    if not (_base_ok("DIGI TRACKS", lo, len(data), log)
            and _base_ok("DIGI PATTERN", plo, len(data), log)):
        return False

    # Matching the code shape and the table offset is not proof the tables are
    # really interleaved here: Powerplay Hockey matches both signatures and the
    # +18 relation, yet its orderlist table is the classic lo,lo,lo,hi,hi,hi
    # layout, and reading it two-byte-interleaved yields $DEDA -- 43352 bytes
    # into an 11598-byte file. Require subtune 0's pointers to resolve before
    # believing the layout; otherwise leave the file to the classic chains.
    if not all(_digi_entry_ok(sid, lo + v * 2) for v in range(DIGI_VOICES)):
        return False

    log(f"Found Tracks LO at......: ${tracks:X} (interleaved)")
    log(f"Found Pattern LO at.....: ${pattern:X} (interleaved)")
    det.table_stride = 2
    det.instr_stride = 16
    det.pattern_dialect = "digi"
    det.track_voices = DIGI_VOICES
    det.track_lo, det.track_hi = lo, lo + 1
    det.pattern_lo, det.pattern_hi = plo, plo + 1
    # The orderlist table runs from `tracks` to `pattern`, so its extent says
    # how many subtunes there really are -- one, in every file of this family.
    # Powerplay Hockey's header claims ten; reading them walks straight into
    # the pattern table and returns 4119 references to 45 patterns.
    det.subtunes_available = max(
        1, DIGI_TRACK_TO_PATTERN // (2 * DIGI_VOICES))
    # Interleaved tables carry no count -- there is no second table whose
    # distance reveals it -- so take every entry that still resolves inside the
    # file. The table is followed by pattern data, which reads as wild
    # addresses, so this stops at the real end.
    used = 0
    while _digi_entry_ok(sid, plo + used * 2):
        used += 1
    det.pattern_used = used - 1
    log(f"Pattern used............: ${det.pattern_used:X}")
    return det.pattern_used >= 0


# --- The "command table" engine --------------------------------------------
#
# A third pattern grammar, used by Chicken Song ($10A0) and Hollywood or Bust
# ($04A9). Its orderlist is version 0's, and its tables are found by the
# classic chains, so only the pattern-byte grammar differs -- but it differs
# completely:
#
#     10A0  B1 FD     LDA (patt),Y
#     10A2  10 15     BPL $10B9          ; < $80 -> a note event
#     10A4  29 0F     AND #$0F           ; >= $80 -> a command, low nibble
#     10A6  AA        TAX                ;   indexes a jump table...
#     10A7  BD 38 17  LDA $1738,X        ;   ...whose LO half is here
#     10AA  8D B7 10  STA $10B7          ;   (self-modifying JMP operand)
#     10AD  BD 3E 17  LDA $173E,X        ;   ...and HI half here
#
#     10B9  9D 93 15  STA $1593,X        ; note event: keep the status byte
#     10BF  29 1F     AND #$1F           ; low 5 bits are an INDEX...
#     10C1  AA        TAX
#     10C2  BD BE 14  LDA $14BE,X        ; ...into a note-DURATION table
#     10C8  9D 90 15  STA $1590,X        ;    (6 12 24 36 72 48 96 18)
#     10CE  2C A1 15  BIT $15A1
#     10D1  50 03     BVC $10D6          ; bit 6 clear -> a note byte follows
#     10D6  C8 ...    INY / LDA (patt),Y ; note; bit 7 is a flag (AND #$7F)
#
# Three things the classic decoder gets wrong here, in order of damage:
#   * the low 5 bits are a table index, not a frame count -- so every event's
#     length was wrong, and the file's whole rhythm with it;
#   * bit 7 of the status byte is not "an operand follows", it makes the byte
#     a command with its own operand count, so the byte stream desynchronised
#     at the first one;
#   * the instrument comes from a command, not from a per-event operand.
#
# Everything the decoder needs is read out of the code rather than assumed:
# the two jump-table halves are adjacent, so their distance is the command
# count (the same trick §4.2 uses for the pattern table), and each handler's
# operand count is its INY count minus one -- one INY to reach the operand,
# one to step past the last of them before jumping back to the fetch.
CMDTABLE_DISPATCH = "B1 ?? 10 ?? 29 0F AA BD ?? ?? 8D ?? ?? BD ?? ?? 8D ?? ??"
CMDTABLE_DURATION = "9D ?? ?? 8D ?? ?? 29 1F AA BD ?? ??"
CMDTABLE_INSTR_CELL = "BD ?? ?? 0A 0A 0A"
CMDTABLE_MAX_COMMANDS = 16      # the dispatch masks with AND #$0F

# The command-table engine's pitch slide, which its decoder consumed for length
# and dropped. Hollywood or Bust $071B, Chicken Song $1301 -- byte for byte the
# same routine:
#
#     071B  BD 9A 09  LDA dir,X          ; operand 2, raw
#     071E  10 1C     BPL up             ; bit 7 clear -> add, set -> subtract
#     0720  38        SEC
#     0721  BD 97 09  LDA freqlo,X
#     0724  FD A5 09  SBC steplo,X       ; operand 1 is the step's LOW half
#     0727  9D 97 09  STA freqlo,X / STA $D400,Y
#     072D  BD 94 09  LDA freqhi,X
#     0730  FD 9D 09  SBC stephi,X       ; operand 2 AND #$3F is the HIGH half
#     0733  9D 94 09  STA freqhi,X / STA $D401,Y
#
# and its handler ($084D / $1430) stores the three operands in one order in
# both files: step low, direction-and-high raw, then a per-voice delay counter
# ($09A8,X) that holds the slide off for that many frames. Goattracker has no
# per-command onset delay, so that third operand is read and dropped -- an
# approximation, and the only one in this mapping.
#
# Note the shape is the *high-first* dialect again (SLIDE_HIGH_FIRST_SHAPE):
# `AND #$3F` for the high half. The direction is bit 7 here rather than a CMP
# threshold, because the two bytes are separate pattern operands.
CMDTABLE_SLIDE_SHAPE = ("BD ?? ?? 10 ?? 38 BD ?? ?? FD ?? ?? 9D ?? ?? 99 00 D4 "
                        "BD ?? ?? FD ?? ?? 9D ?? ?? 99 01 D4")


def _handler_operands(data: bytes, off: int, instr_cell: int):
    """(operand count, sets-the-instrument) for one command handler.

    Walks until the JMP back to the fetch point, counting INY. Sizes are
    taken from the handful of opcodes these handlers are built from; anything
    else is assumed one byte, which is safe because the walk stops at the
    first JMP or RTS either way.
    """
    size = {0xA9: 2, 0xB1: 2, 0x9D: 3, 0x29: 2, 0x8D: 3, 0xBD: 3, 0xB9: 3}
    iny = 0
    sets_instr = False
    for _ in range(40):
        if not 0 <= off < len(data):
            return None, False
        b = data[off]
        if b == 0xC8:               # INY
            iny += 1
            off += 1
            continue
        if b in (0x4C, 0x60):       # JMP back / RTS
            break
        if b == 0x9D and off + 2 < len(data):
            if (data[off + 1] | data[off + 2] << 8) == instr_cell:
                sets_instr = True
        off += size.get(b, 1)
    else:
        return None, False
    return max(0, iny - 1), sets_instr


def _cmdtable_slide(sid: SidFile, data: bytes, cmd_lo: int, cmd_hi: int,
                    count: int) -> Tuple[int, int]:
    """(command index, high-half mask) of the cmdtable pitch slide, or (-1, 0).

    The consumer names the cells; the handler that fills them names the
    command. Requiring both, and requiring the handler to store them in the
    order the consumer reads them, is what makes this a reading rather than a
    guess -- a file whose handler differs returns -1 and keeps the old
    behaviour of dropping the command, which is an under-read.
    """
    at = search_file(data, CMDTABLE_SLIDE_SHAPE)
    if at < 1:
        return -1, 0
    dir_cell = data[at + 1] | data[at + 2] << 8
    lo_cell = data[at + 10] | data[at + 11] << 8
    for c in range(count):
        if cmd_hi + c >= len(data):
            break
        handler = sid.to_offset(data[cmd_lo + c] | data[cmd_hi + c] << 8)
        if not 0 < handler < len(data):
            continue
        stores, mask = [], 0
        for k in range(handler, min(handler + 30, len(data) - 2)):
            if data[k] == 0x9D:
                stores.append(data[k + 1] | data[k + 2] << 8)
            elif data[k] == 0x29 and len(stores) == 2:
                mask = data[k + 1]
            elif data[k] == 0x4C:
                break
        if stores[:2] == [lo_cell, dir_cell] and mask:
            return c, mask
    return -1, 0


def _detect_cmdtable(sid: SidFile, det: Detection, log: Logger) -> bool:
    """Recognise the command-table pattern grammar, or leave `det` untouched."""
    data = sid.data
    disp = search_file(data, CMDTABLE_DISPATCH)
    dur = search_file(data, CMDTABLE_DURATION)
    cell = search_file(data, CMDTABLE_INSTR_CELL)
    if min(disp, dur, cell) <= -1:
        return False

    cmd_lo = sid.to_offset(_addr16(data, disp + 8, disp + 9))
    cmd_hi = sid.to_offset(_addr16(data, disp + 14, disp + 15))
    duration = sid.to_offset(_addr16(data, dur + 10, dur + 11))
    instr_cell = _addr16(data, cell + 1, cell + 2)
    count = cmd_hi - cmd_lo
    if not 1 <= count <= CMDTABLE_MAX_COMMANDS:
        return False
    if not (_base_ok("COMMAND TABLE", cmd_lo, len(data), log)
            and _base_ok("COMMAND TABLE HI", cmd_hi, len(data), log)
            and _base_ok("DURATION TABLE", duration, len(data), log)):
        return False

    operands, instrument = [], -1
    for c in range(count):
        if cmd_hi + c >= len(data):
            return False
        handler = sid.to_offset(data[cmd_lo + c] | data[cmd_hi + c] << 8)
        n, is_instr = _handler_operands(data, handler, instr_cell)
        if n is None:
            return False
        operands.append(n)
        if is_instr and instrument < 0:
            instrument = c
    if instrument < 0:
        return False        # no handler feeds the instrument index: not this engine

    det.pattern_dialect = "cmdtable"
    det.duration_table = duration
    det.cmd_operands = tuple(operands)
    det.cmd_instrument = instrument
    det.cmd_slide, det.cmd_slide_mask = _cmdtable_slide(
        sid, data, cmd_lo, cmd_hi, count)
    if det.cmd_slide >= 0:
        log(f"Pattern slide command...: ${0x80 + det.cmd_slide:02X} "
            f"(low, high & ${det.cmd_slide_mask:02X} + bit 7 direction, delay)")
    log(f"Pattern grammar.........: command-table ({count} commands, "
        f"${0x80 + instrument:02X} sets the instrument)")
    log("Note durations..........: " + " ".join(
        str(data[duration + i]) for i in range(min(8, len(data) - duration))))
    return True


def detect(sid: SidFile, log: Logger) -> Detection:
    data = sid.data
    det = Detection()

    def find(pattern: str) -> int:
        i = search_file(data, pattern)
        if i >= 1:
            # A successful match IS player code -- that is the premise the
            # whole detection method rests on -- so remember where it was.
            det.code_spans.append((i, len(pattern.split())))
        return i

    # Probed before anything else: it sets the instrument record size the
    # instrument pass below depends on, and its tables are read from their own
    # signatures rather than the classic chains.
    digi = _detect_digi(sid, det, log)

    # --- Instruments ---------------------------------------------------
    # Every signature in this chain fingerprints the *store* into the SID:
    # `LDA record,X / STA $D40x,Y`. That is what makes them fail on a player
    # which reaches the SID through subroutines instead -- Phantoms of the
    # Asteroid writes its five instrument bytes with `JSR $F04E/$F056/$F066/
    # $F06E` and matches none of them, so it converted with zero instruments
    # and played silence. INSTRUMENT_INDEX_SHAPE below fingerprints the *load*
    # instead, which is common to both.
    idx = _find_instrument_index(sid, det, log)
    i = find("BD ?? ?? 99 02 D4 48 BD ?? ?? 99 03 D4")       # Chimera
    if i <= -1:
        i = find("BD ?? ?? 99 02 D4 BD ?? ?? 99 03 D4")      # ACE2
    if i <= -1:
        i = find("BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48")  # IK+
    addr = -1
    if i > -1:
        addr = _addr16(data, i + 1, i + 2)
        log(f"Found Instruments at....: ${addr:X}")
    elif idx >= 0:
        # Last, and only consulted once every store-shaped signature has
        # failed, so it can rescue a file that finds nothing and can never
        # move one that already reads correctly. Corpus-wide the shape is
        # present in 70 files and names the same address the chain above
        # already found in 68 of them; the two it does not are the digi
        # engine, which has its own detection path and never reaches here.
        addr = _addr16(data, idx + 11, idx + 12) - 2
        log(f"Found Instruments at....: ${addr:X} (via the index load)")
    if addr < 0:
        log("*** CAN'T FIND INSTRUMENTS ***")
    else:
        det.instr_start = sid.to_offset(addr)
        if not _base_ok("INSTRUMENTS", det.instr_start, len(data), log):
            # instr_used stays 0, not -1: goatwriter always emits the "Clear
            # Voice" record, so -1 would write a count byte of 0 that disagrees
            # with the record that follows it.
            det.instr_start, det.instr_used = -1, 0
        j = det.instr_start + 2
        instr_used = 0
        while True:
            # Guard the read itself. The loop below only bounds-checks `j` after
            # advancing, so an out-of-range instr_start crashed on the very first
            # iteration; a negative one would have silently indexed from the end
            # of the file. Both are start-address problems, so this only fires on
            # the first pass -- the post-advance check still governs the count.
            if j < 0 or j >= len(data):
                log("*** CAN'T FIND INSTRUMENT-END, SET TO DEFAULT (1 INSTRUMENT) ***")
                break
            if data[j] not in WAVEFORMS:
                break
            j += det.instr_stride
            if j >= len(data):
                log("*** CAN'T FIND INSTRUMENT-END, SET TO DEFAULT (1 INSTRUMENT) ***")
                break
            instr_used += 1
        det.instr_used = instr_used
        log(f"Instruments used........: ${instr_used:X}")
        if det.instr_start >= 0:
            _span_warn("INSTRUMENT", det.instr_start,
                       instr_used * det.instr_stride, len(data), log)

    # --- Tracks / subsongs ----------------------------------------------
    if digi:
        i = -2      # tables already known; skip the classic chain and its log
    else:
        det.track_voices = 3
        so = 3
        i = find("D0 ?? BD ?? ?? 85 ?? BD ?? ?? 85 ?? DE ?? ?? 30 ?? 4C")       # IK+ / Warhawk
    if i == -1:
        i = find("D0 ?? BD ?? ?? 85 ?? BD ?? ?? 85 ?? D6 ?? 30 ?? 4C")         # Mega Apocalypse
    if i == -1:
        i = find("D0 ?? BD ?? ?? 85 ?? BD ?? ?? 85 ?? E0 ?? D0 ?? CE")         # Ricochet
    if i == -1:
        i = find("8E ?? ?? A8 BD ?? ?? 85 ?? BD ?? ?? 85 ?? BD ?? ?? F0")      # Hollywood or bust
        so = 5
    if i == -1:
        i = find("8D ?? ?? A8 BD ?? ?? 85 ?? BD ?? ?? 85 ?? DE ?? ?? 30")      # Harvey Smith Show Jumper
        so = 5
    i2 = i
    if i == -2:
        pass                       # digi engine: already located above
    elif i <= -1:
        log("*** CAN'T FIND TRACKS/SUBSONGS ***")
    else:
        addr = _addr16(data, i + so, i + so + 1)
        log(f"Found Tracks LO at......: ${addr:X}")
        det.track_lo = sid.to_offset(addr)
        i = i2
        addr = _addr16(data, i + so + 5, i + so + 6)
        log(f"Found Tracks HI at......: ${addr:X}")
        det.track_hi = sid.to_offset(addr)
        if not (_base_ok("TRACKS LO", det.track_lo, len(data), log)
                and _base_ok("TRACKS HI", det.track_hi, len(data), log)):
            det.track_lo = det.track_hi = -1

    # --- Track selector ---------------------------------------------------
    det.track_selector = False
    so = 6
    # Not consulted for the digi engine: its orderlist table was located from
    # its own signature and is interleaved, whereas a selector match rewrites
    # track_lo/track_hi assuming the classic separate-table layout. Powerplay
    # Hockey matches a selector signature and had its perfectly good digi
    # tables ($4BA4/$4BC3/$4BE2) replaced by one that resolves nowhere.
    i = -1 if digi else find("18 6D ?? ?? AA BD ?? ?? 99 ?? ?? E8 C8 C0 06")  # Rasputin
    if i <= -1 and not digi:
        i = find("8A 0A 0A AA BD ?? ?? 99 ?? ?? E8 C8 C0 04")  # Human Race
        if i >= 1:
            so = 5
            det.track_voices = 2
            log("'Human Race' player (2 voices) detected.")
    if i <= -1:
        pass  # no music selector found, might not be needed
    else:
        det.track_selector = True
        addr = _addr16(data, i + so, i + so + 1)
        log(f"Found Music selector....: ${addr:X}")
        selector = sid.to_offset(addr)
        # The selector overwrites whatever the subsong pass found, so validate
        # before clobbering it -- a bogus selector must not discard a good pair.
        if _base_ok("MUSIC SELECTOR", selector, len(data), log):
            det.track_lo = selector
            det.track_hi = selector + det.track_voices
        else:
            det.track_selector = False

    # --- Pattern table ---------------------------------------------------
    so = 11
    i = -2 if digi else find(
        "9D ?? ?? 4C ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D")       # LastV8
    if i == -1:
        i = find("9D ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D")  # Delta
        so = 8
    if i == -1:
        i = find("4C ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? BC ?? ?? A9")  # Battle of Britain
        so = 8
    if i == -1:
        i = find("4C ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 95")  # Samantha Fox
        so = 8
    if i == -1:
        i = find("20 ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D")  # SaboteurII
        so = 8
    if i == -1:
        i = find("4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 95")  # Mega Apocalypse
        so = 5
    if i == -1:
        # Delta (Mix-E-Load loader). Mega Apocalypse's shape exactly, except
        # that it clears its per-voice state with STA abs,X rather than
        # STA zp,X -- `9D` where that one has `95`. $C0CA:
        #     C0CA  4C 9D C0  JMP $C09D     ; back to the orderlist read
        #     C0CD  A8        TAY
        #     C0CE  B9 6E C7  LDA $C76E,Y   ; pattern lo
        #     C0D3  B9 96 C7  LDA $C796,Y   ; pattern hi
        #     C0D8  A9 00     LDA #$00
        #     C0DA  9D 68 C5  STA $C568,X
        # Last in the chain, so it can only speak for a file every other
        # signature has already declined.
        i = find("4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D")  # Delta loader
        so = 5
    if i == -2:
        pass                       # digi engine: already located above
    elif i <= -1:
        log("*** CAN'T FIND PATTERN ***")
    else:
        i2 = i
        addr = _addr16(data, i + so, i + so + 1)
        log(f"Found Pattern LO at.....: ${addr:X}")
        det.pattern_lo = sid.to_offset(addr)
        i = i2
        addr = _addr16(data, i + so + 5, i + so + 6)
        log(f"Found Pattern HI at.....: ${addr:X}")
        det.pattern_hi = sid.to_offset(addr)
        det.pattern_used = (det.pattern_hi - det.pattern_lo) - 1
        log(f"Pattern used............: ${det.pattern_used:X}")
        if not (_base_ok("PATTERN LO", det.pattern_lo, len(data), log)
                and _base_ok("PATTERN HI", det.pattern_hi, len(data), log)):
            det.pattern_lo = det.pattern_hi = -1
            det.pattern_used = -1
        elif det.pattern_used < 0:
            # The count is the gap between the LO and HI tables, so HI landing
            # below LO means the pair is not a real table pair at all.
            log(f"*** PATTERN COUNT NEGATIVE ({det.pattern_used}), "
                "HI TABLE PRECEDES LO -- NOT A VALID TABLE PAIR ***")
            det.pattern_lo = det.pattern_hi = -1
            det.pattern_used = -1
        else:
            _span_warn("PATTERN LO", det.pattern_lo, det.pattern_used, len(data), log)
            _span_warn("PATTERN HI", det.pattern_hi, det.pattern_used, len(data), log)

    # --- Player (track-read) version ---------------------------------------
    det.read_track_version = 0xFF
    i = find("BC ?? ?? B1 ?? C9 FF F0 ?? C9 FE")
    if i >= 1:
        det.read_track_version = 0        # Warhawk...
    if i <= -1:
        i = find("BC ?? ?? B1 ?? C9 FE D0 ?? 4C ?? ?? C9 FF")
        if i >= 1:
            det.read_track_version = 1    # Last V8...
    if i <= -1:
        i = find("BC ?? ?? B1 ?? 10 ?? C9 FF F0 ?? C9 FE F0")
        if i >= 1:
            det.read_track_version = 2    # Auf Wiedersehen Monty...
            # The `10 rr` is BPL: bytes >= $80 are commands, not pattern
            # numbers. Two sub-variants share this signature, told apart by the
            # first instruction on that path -- the byte right after the match:
            #   $29  AND #$7F   the command byte's own low 7 bits are the value
            #   $C8  INY        the value is the *next* byte (2 bytes consumed)
            # Corpus-wide, 13 of 14 version-2 players use the AND form; only
            # Auf Wiedersehen Monty itself uses the INY form.
            if i + 15 < len(data):
                det.transpose_operand = data[i + 15] == 0xC8
    if i <= -1:
        i = find("B4 ?? B1 ?? C9 FF F0 ?? C9 FE D0")
        if i >= 1:
            det.read_track_version = 3    # Samantha Fox Strip Poker...
    if i <= -1:
        i = find("BC ?? ?? B1 ?? 10 ?? A9 ?? 9D ?? ?? 9D ?? ?? 9D")
        if i >= 1:
            det.read_track_version = 4    # ACE 2...
    if i <= -1:
        i = find("BC ?? ?? B1 ?? C9 FF D0 ?? A9 ?? 9D ?? ?? 9D ?? ?? 9D")
        if i >= 1:
            det.read_track_version = 5    # Battle of Britain...
    if i <= -1:
        i = find("B4 ?? B1 ?? 10 ?? C9 FF F0 ?? 29 7F")
        if i >= 1:
            det.read_track_version = 6    # Mega Apocalypse
    if i <= -1:
        i = find("BC ?? ?? B1 ?? 10 ?? C9 FF F0 ?? 29 7F")
        if i >= 1:
            det.read_track_version = 7    # IK+
    if i <= -1:
        # Chain Reaction: version 0's shape with $FE where it expects $FF, and
        # no second marker -- the tune can only loop, never stop. Last in the
        # chain, so it speaks only for a file every earlier signature declined;
        # it matches this file and no other in the corpus.
        i = find("BC ?? ?? B1 ?? C9 FE F0 ?? C9 FE D0")
        if i >= 1:
            det.read_track_version = 9    # Chain Reaction
    # --- Pattern grammar ----------------------------------------------------
    # Probed after the tables, which the classic chains locate correctly for
    # this engine too -- only the bytes inside a pattern are read differently.
    if not digi:
        _detect_cmdtable(sid, det, log)

    # --- Pattern note byte: is bit 7 part of the note? ----------------------
    # Commando $50ED reads the note and indexes the frequency table with it
    # directly:
    #     INY / LDA (patt),Y / STA note,X / ASL / TAY
    # Delta $BEFF, Sanxion $B11C, W.A.R. $E536 and Zoolook $411D keep the raw
    # byte in a scratch cell and mask it first:
    #     INY / LDA (patt),Y / STA flag / AND #$7F / STA note,X / ASL / TAY
    # and the saved bit 7 is tested a few instructions later ($BF31 `LDA
    # $C33D` / `BMI`) to skip the pulse-width and ADSR writes -- i.e. it is a
    # legato marker, and the low seven bits are the note.
    #
    # h2g clamped the whole byte to $5C ("if note >= 0x5C: note = 0x5C"), so
    # in these 14 files every flagged note collapsed onto the top note of the
    # range. Delta's pattern $01 is `01 B4 01 B2 01 B4 01 AF 01 AD 01 AF FF`,
    # whose notes siddump confirms the player plays as absolute $B4 $B2 $B4
    # $AF $AD $AF -- all six were emitted as one repeated $BC.
    if find("C8 B1 ?? 8D ?? ?? 29 7F 9D ?? ?? 0A A8") >= 1:
        det.note_flag = True

    # Delta's orderlist carries a repeat count between pattern numbers. Its
    # *read* is version 0's shape byte for byte ($BE79: LDY $C2EC,X /
    # LDA ($A6),Y / CMP #$FF / BEQ / CMP #$FE), so the discriminator has to be
    # the advance, at the end of a pattern ($BF85):
    #     DEC $C354,X    ; repeat counter
    #     BNE  ...       ; still repeating -> replay, orderlist unmoved
    #     INC $C2EC,X    ; else step the orderlist
    #     LDY $C2EC,X / LDA ($A6),Y
    #     BMI  ...       ; $FE/$FF marker -> leave it to be read as one
    #     STA $C354,X    ; else the byte is the NEXT pattern's repeat count
    #     INC $C2EC,X    ; ...and step past it to the pattern number
    # Warhawk's equivalent ($115D) has a plain INC where this has the DEC, and
    # no second read at all. Delta is the only corpus file with the DEC form.
    if det.read_track_version == 0 and find(
            "DE ?? ?? D0 ?? FE ?? ?? BC ?? ?? B1 ?? 30 ?? 9D ?? ?? FE ?? ??") >= 1:
        det.read_track_version = 10   # Delta
    log(f"Player Trackread version: {det.read_track_version:X}")
    if det.transpose_operand:
        log("Track transpose form....: two-byte (value follows the command)")

    det.slide_operand = _find_slide_operand(data)
    det.slide_high_first = _find_slide_high_first(data)
    if det.slide_operand:
        log("Pattern slide form......: two-byte (16-bit step), "
            + ("operand is the HIGH half (CMP #$BF direction)"
               if det.slide_high_first else
               "operand is the low half (bit 0 direction)"))

    det.vibrato_offset = _find_vibrato(sid, det)
    if det.vibrato_offset is not None:
        log(f"Instrument vibrato......: record +{det.vibrato_offset} "
            "(bound $78>>3, depth shift $07, note-relative)")
    else:
        det.table_vibrato = _find_table_vibrato(sid, det)
        if det.table_vibrato is not None:
            tv = det.table_vibrato
            log(f"Instrument vibrato......: record +{tv.offset} "
                f"(LFO table $F0>>4, unit $0F x interval>>{tv.unit_shift}), "
                + ", ".join(f"len {l} peak {p}" for l, p in tv.shapes))

    det.status_bit6 = _find_status_bit6(data)
    if det.status_bit6:
        log("Pattern status bit 6....: skips operand and note (BIT/BVS)")

    (det.effect_rise, det.effect_arp,
     det.effect_drum, det.effect_pulse_lo) = _find_effect_routines(sid, det)
    if any((det.effect_rise, det.effect_arp, det.effect_drum,
            det.effect_pulse_lo)):
        found = ", ".join(n for n, ok in (("drum", det.effect_drum),
                                          ("rise", det.effect_rise),
                                          ("arpeggio", det.effect_arp),
                                          ("pulse-lo", det.effect_pulse_lo))
                          if ok)
        log(f"Instrument effect byte..: {found}")

    det.pulse_bounds, det.pulse_rate_field = _find_pulse_sweep(sid, det)
    if det.pulse_bounds >= 0:
        log(f"Pulse-width sweep.......: bounds at file +0x{det.pulse_bounds:04X}, "
            f"rate at record +{det.pulse_rate_field}")

    if det.effect_pulse_lo:
        det.pulse_lo_base = _find_pulse_lo(sid, det)
        if det.pulse_lo_base >= 0:
            log(f"Pulse-width accumulate..: state array at file "
                f"+0x{det.pulse_lo_base:04X} (+0 lo, +1 hi, +6 rate)")

    (det.effect_two_stage, det.two_stage_wave,
     det.two_stage_frames) = _find_two_stage(sid, det)
    if det.effect_two_stage:
        log("Instrument effect byte..: two-stage waveform (bit $04 is not "
            "an arpeggio in this player)")
        _bound_instruments(det, log)

    det.effect_bit80, det.effect_program = _find_effect_bit80(sid, det)
    if det.effect_bit80 == "sfx":
        log("Instrument effect byte..: bit $80 fires the game's own sound "
            "effect (global state, voice 3 + volume) -- not music, not "
            "converted")
    elif det.effect_bit80 == "program":
        where = (f"file +0x{det.effect_program:04X}"
                 if det.effect_program >= 0 else "an unresolvable address")
        log(f"Instrument effect byte..: bit $80 selects a byte-code wave "
            f"program, pointers at {where} (read, not written)")
    elif det.effect_bit80 == "pitch":
        log("Instrument effect byte..: bit $80 steps the frequency from a "
            "duration/delta table (read, not written)")

    det.freq_table = find_freq_table(sid)
    if det.freq_table is not None:
        ft = det.freq_table
        det.note_base = ft.shift
        if ft.shift:
            log(f"Note frequency table....: ${ft.addr:04X}, entry {ft.start} "
                f"is Goattracker's note 0 ({ft.shift:+d} semitone)")
        elif abs(ft.detune) > 0.2:
            log(f"Note frequency table....: ${ft.addr:04X}, tuned "
                f"{-100 * ft.detune:.0f} cents flat of Goattracker's")

    det.filter = find_filter(sid, det)
    if det.filter is not None:
        f = det.filter
        log(f"Filter..................: ${f.addr:04X}, stride "
            f"{det.instr_stride}, passband ${f.passband:02X}, "
            f"cutoff starts at ${f.cutoff:02X}")

    return det


# --- Filter ---------------------------------------------------------------
#
# Hubbard's filter is per instrument, in a two-byte-per-record array parallel
# to the instrument table and indexed by the same `i * instr_stride`. The
# routine that reads it is the same in every player that has it -- Deep Strike
# $C376, and 23 more files byte-for-byte apart from the operands:
#
#     C376  BD E9 C4  LDA cutoff,X      ; per-VOICE running cutoff
#     C379  18        CLC
#     C37A  79 56 C5  ADC step,Y        ; += this instrument's sweep step
#     C37D  9D E9 C4  STA cutoff,X      ; accumulate back
#     C380  8D 16 D4  STA $D416         ; cutoff HIGH byte only
#     C383  B9 55 C5  LDA resctl,Y      ; this instrument's resonance/routing
#     C386  8D 17 D4  STA $D417
#
# `resctl` is always exactly `step - 1` -- one array, byte +0 resonance and
# routing, byte +1 the signed per-frame step. That held in 24 of 24 files the
# shape matched, which is what proves the layout rather than assuming it.
#
# Y is the instrument index scaled by the record stride: the players shift it
# left three times (x8) and the one digi player that has the routine shifts
# four (x16), matching det.instr_stride in every case.
#
# Only $D416 is written -- the low three bits of cutoff at $D415 are untouched
# in 26 of the 32 filter-using files -- and Goattracker's filter table cutoff
# is likewise a single byte, so the value transfers without scaling.
# The routine is entered only when bit $20 of the instrument's status byte is
# set -- `LDA status / AND #$20 / BEQ past`. That bit is the player's own
# per-instrument filter switch, and it is the gate that matters: a file can
# carry the routine and the array and still never filter anything, which is
# what Powerplay Hockey and Wiz do. Reading the array without this test
# invents a filter for both of them.
FILTER_SHAPE = ("AD ?? ?? 29 20 F0 ?? BD ?? ?? "
                "18 79 ?? ?? 9D ?? ?? 8D 16 D4 B9 ?? ?? 8D 17 D4")

# `LDA status_array,Y / STA status` -- how that byte is loaded for the
# instrument about to be played, which names the per-instrument array.
FILTER_STATUS_SHAPE = "B9 ?? ?? 8D {lo:02X} {hi:02X}"

FILTER_ENABLE_BIT = 0x20

# `LDA #imm / STA cutoff,X` at note start: the cutoff every note begins from.
# Without it the sweep has no origin -- Goattracker would carry whatever the
# previous instrument left -- so a file whose start value cannot be read is
# left alone rather than given an invented one.
FILTER_CUTOFF_SHAPES = ("A9 ?? 9D {lo:02X} {hi:02X}", "A9 ?? 8D {lo:02X} {hi:02X}")

# `LDA #imm / STA $D418`: mode nibble (bit 4 lowpass, 5 bandpass, 6 highpass)
# plus master volume. Goattracker's filter-table left side is $80 | those same
# three bits, so the passband maps across unshifted.
FILTER_MODE_SHAPE = "A9 ?? 8D 18 D4"


@dataclass
class FilterInfo:
    addr: int      # C64 address of the parallel array (resonance byte of #0)
    offset: int    # the same, as an offset into sid.data
    passband: int  # $D418 & $70
    cutoff: int    # the value every note's sweep starts from
    status: int    # offset of the per-instrument status array (bit $20 = on)


def find_filter(sid: SidFile, det: Detection) -> "FilterInfo | None":
    """The per-instrument filter array, or None when the player has no filter.

    Under-reads by design: every gate here can only refuse a file, so a player
    without the routine, without a readable start cutoff, or without a mode
    write keeps the empty filter table it has always had.
    """
    if det.instr_start < 0:
        return None
    data = sid.data
    i = search_file(data, FILTER_SHAPE)
    if i <= -1:
        return None

    status_var = data[i + 1] | data[i + 2] << 8
    step = data[i + 12] | data[i + 13] << 8
    cutoff_var = data[i + 15] | data[i + 16] << 8
    resctl = data[i + 21] | data[i + 22] << 8
    # The layout claim, tested rather than assumed: one array, resonance then
    # step. A file where the two operands are not adjacent is reading some
    # other pair of tables and is not ours to interpret.
    if resctl != step - 1:
        return None

    j = search_file(data, FILTER_MODE_SHAPE)
    if j <= -1:
        return None
    passband = data[j + 1] & 0x70
    if not passband:
        return None  # filter switched off at the mode register: nothing to say

    cutoff = -1
    for shape in FILTER_CUTOFF_SHAPES:
        k = search_file(data, shape.format(lo=cutoff_var & 0xFF,
                                           hi=cutoff_var >> 8))
        if k > -1:
            cutoff = data[k + 1]
            break
    if cutoff < 0:
        return None

    m = search_file(data, FILTER_STATUS_SHAPE.format(lo=status_var & 0xFF,
                                                    hi=status_var >> 8))
    if m <= -1:
        return None
    status = sid.to_offset(data[m + 1] | data[m + 2] << 8)

    offset = sid.to_offset(resctl)
    if not 0 <= offset < len(data) or not 0 <= status < len(data):
        return None
    return FilterInfo(addr=resctl, offset=offset, passband=passband,
                      cutoff=cutoff, status=status)


# The pattern-fetch shape that consumes a second operand byte. Warhawk $10EC:
#
#     10EC  C8        INY
#     10ED  B1 FD     LDA (patt),Y      ; the command operand
#     10EF  10 0F     BPL instrument    ; < $80 -> an instrument number instead
#     10F1  9D B7 15  STA slidelo,X     ; >= $80 -> slide step LOW + direction
#     10F4  C8        INY
#     10F5  B1 FD     LDA (patt),Y      ; <- the byte H2G never consumed
#     10F7  9D BA 15  STA slidehi,X     ; slide step HIGH
#
# The two `STA abs,X` targets are the low and high halves of the 16-bit value
# the slide routine adds to the voice frequency each frame (Warhawk $1320:
# `LDA slidelo,X / AND #$7E` and `SBC/ADC slidehi,X`, written to $D400/$D401).
#
# Not every player has it. Of 95 corpus files 41 match this shape and **none**
# match a one-byte variant of it -- the rest have a differently shaped fetch
# routine altogether. Version 5 (Battle of Britain, Gremlins) and Commando are
# among those that do not, which is why the original VB6 tool -- written and
# verified against Commando -- never needed the second byte and why the
# byte-exact fixture does not move when this is honoured.
SLIDE_OPERAND_SHAPE = "C8 B1 ?? 10 ?? 9D ?? ?? C8 B1 ?? 9D ?? ??"


def _find_slide_operand(data: bytes) -> bool:
    return search_file(data, SLIDE_OPERAND_SHAPE) >= 1


# The fetch above says a second byte exists. It does not say which half of the
# step it is -- and two players disagree, with the *same* fetch shape.
#
# Warhawk $1320 is the reading this converter was built on:
#
#     1320  BD B7 15  LDA slidelo,X
#     1325  29 7E     AND #$7E          ; the operand IS the step's low half
#     132A  BD B7 15  LDA slidelo,X
#     132D  29 01     AND #$01          ; ...and its bit 0 is the direction
#     132F  F0 1C     BEQ add
#     1332  BD B4 15  LDA freqlo,X / SBC $1588 / STA $D400,Y
#     133E  BD B1 15  LDA freqhi,X
#     1341  FD BA 15  SBC slidehi,X     ; the second byte is the HIGH half
#
# Flash Gordon $12EB puts the halves the other way round, and takes the
# direction from a threshold rather than a bit:
#
#     12EB  BD 40 15  LDA slidelo,X
#     12F0  C9 BF     CMP #$BF
#     12F2  90 1A     BCC up            ; < $BF adds, >= $BF subtracts
#     12F4  29 3F     AND #$3F          ; the operand is the step's HIGH half,
#     12F6  8D 07 13  STA $1307         ; self-modified into the SBC below
#     12FA  BD 3A 15  LDA freqlo,X
#     12FD  FD 3D 15  SBC slidehi,X     ; the second byte is the LOW half
#     1303  BD 37 15  LDA freqhi,X
#     1306  E9 08     SBC #$08          ; <- operand written at $12F6
#
# Read Flash Gordon's bytes Warhawk's way round and the step comes out about
# 256 times too large, which then saturates the 8-bit pattern column: **all 15
# corpus files whose slide parameter sits on that clamp are in this dialect.**
#
# The census partitions cleanly, the same way the effect byte's two formats do:
# of 95 corpus files 25 have Warhawk's consumer and 22 have this one, and
# **none has both**. 22 of the 41 files with the two-byte fetch are in this
# dialect and were being decoded with the halves swapped. The `CMP` immediate
# is $BF in all 22 and the mask is $3F in all 22, so both are literals here
# rather than parameters.
SLIDE_HIGH_FIRST_SHAPE = \
    "BD ?? ?? F0 ?? C9 BF 90 ?? 29 3F 8D ?? ?? 38 BD ?? ?? FD ?? ??"

# The `CMP #$BF` above: an operand at or above this subtracts.
SLIDE_HIGH_FIRST_DOWN = 0xBF
# The `AND #$3F`: which bits of the operand are the step's high half.
SLIDE_HIGH_FIRST_MASK = 0x3F


def _find_slide_high_first(data: bytes) -> bool:
    return search_file(data, SLIDE_HIGH_FIRST_SHAPE) >= 1


# --- Vibrato ---------------------------------------------------------------
#
# The pitch movement that is in no byte the ripper reads. The player applies it
# *between* the frequency-table lookup and the SID write, so nothing in a
# pattern or an instrument record shows it happening -- only the one byte that
# parameterises it. 33 corpus files moved the pitch not at all where the
# original does, and 20 of those originals are vibrato-shaped (their movement
# returns rather than travels); see H2G-CONVERSION-METHOD.md section 7.dd.
#
# Warhawk $11EF, the parameter split -- one record byte carries both halves:
#
#     11E7  B9 3C 16  LDA record+5,Y
#     11EA  D0 03     BNE on            ; zero -> no vibrato at all
#     11EF  48        PHA
#     11F0  29 78     AND #$78          ; bits 3-6: the amplitude bound
#     11F2  4A 4A 4A  LSR A x3
#     11F5  9D C3 15  STA bound,X
#     11F8  68        PLA
#     11F9  29 07     AND #$07          ; bits 0-2: a right-shift
#     11FB  8D 8A 15  STA shift
#
# ... and $1221, the depth, which is the whole reason this maps onto
# Goattracker at all:
#
#     1221  BD 7F 15  LDA note,X
#     1224  0A A8     ASL A / TAY
#     1226  38        SEC
#     1227  B9 AC 14  LDA freqtbl+2,Y
#     122A  F9 AA 14  SBC freqtbl,Y     ; the semitone interval AT THIS NOTE
#     122D  8D 8C 15  STA depth         ; ...then >> shift
#
# That is `gplay.c:786-792` in 6502: a speed-table left side with bit $80 set
# makes Goattracker compute the speed as the semitone interval at the current
# note shifted right by the table's right byte. The player and the tracker
# express the depth the same way.
#
# The census is unusually clean -- **56 of 95 files match the split, all 56
# with the masks $78 and $07, and all 56 also have the note-relative depth.**
# Unlike the effect byte at +7, this one is a shared format.
VIBRATO_SHAPE = "48 29 78 4A 4A 4A 9D ?? ?? 68 29 07 8D ?? ??"

# The depth, in the two forms the corpus uses: the interval stored to an
# absolute cell or to zero page. Nothing else differs, and 56 of 56 match one.
VIBRATO_DEPTH_SHAPES = (
    "0A A8 38 B9 ?? ?? F9 ?? ?? 8D ?? ??",
    "0A A8 38 B9 ?? ?? F9 ?? ?? 85 ??",
)

VIBRATO_BOUND_MASK = 0x78       # AND #$78 -- the amplitude bound...
VIBRATO_BOUND_SHIFT = 3         # ...>> 3, so 0..15
VIBRATO_SHIFT_MASK = 0x07       # AND #$07 -- the depth's right-shift


def _find_vibrato(sid: SidFile, det: Detection) -> Optional[int]:
    """Instrument-record offset of the vibrato byte, or None.

    The offset is read out of the `LDA record+n,Y` that feeds the split rather
    than assumed: it is +5 in 49 of the 56 files that have the routine, and the
    other 7 reach the byte by some addressing this does not recognise. Those
    return None and get no vibrato -- an under-read, never a wrong one, the
    same rule find_relocation and the instrument-index shape follow.
    """
    data = sid.data
    at = search_file(data, VIBRATO_SHAPE)
    if at < 1:
        return None
    if not any(search_file(data, s) >= 1 for s in VIBRATO_DEPTH_SHAPES):
        return None
    start = det.instr_start + sid.load_addr - HLEN + 1
    for k in range(at - 3, max(0, at - 26), -1):
        if data[k] in (0xB9, 0xBD):     # LDA abs,Y / LDA abs,X
            off = (data[k + 1] | data[k + 2] << 8) - start
            if 0 <= off < det.instr_stride:
                return off
    return None


# --- The table-driven vibrato ----------------------------------------------
#
# The command-table engine (Hollywood or Bust, Chicken Song) has no vibrato
# byte in the shared $78/$07 format, and _find_vibrato returns None for both.
# Its movement is a *table*: an arbitrary LFO shape walked one entry per frame,
# which is a third form again -- neither the classic pair nor anything
# Goattracker has. Hollywood or Bust $05CE, the parameter split:
#
#     05CE  B9 00 0A  LDA record+5,Y    ; ...the same +5 the classic form uses
#     05D1  D0 03     BNE on
#     05D3  4C 91 06  JMP past          ; zero -> no vibrato at all
#     05D6  48        PHA
#     05D7  29 0F     AND #$0F          ; low nibble: how many units per step
#     05D9  8D 86 09  STA count
#     05DC  68        PLA
#     05DD  29 F0     AND #$F0          ; high nibble: WHICH LFO table
#     05DF  4A 4A 4A 4A  LSR A x4
#     05E3  AA        TAX
#     05E4  BD F3 09  LDA lfo_lo,X      ; the two pointer tables...
#     05E7  8D FA 05  STA $05FA         ; ...patched into the fetch below
#     05EA  BD F7 09  LDA lfo_hi,X
#     05ED  8D FB 05  STA $05FB
#
# then $05F3, the walk, and $060E, the unit:
#
#     05F3  BC B1 09  LDY lfo_index,X / INC lfo_index,X   ; one entry per frame
#     05F9  B9 DF 09  LDA table,Y / CMP #$FF              ; $FF wraps to 0
#     060E  BD 7A 09  LDA note,X / ASL / TAY
#     0613  38 B9 A7 08 F9 A5 08  SEC / LDA freq+2,Y / SBC freq,Y   ; interval
#     0622  4A 66 4D  LSR / ROR x4                        ; >> 4 -> the unit
#     0630  AC 86 09  LDY count / ... ADC ... DEY / BNE   ; unit x count
#     0652  68 F0 2F 30 17  PLA / BEQ / BMI               ; the entry sign
#     0657  A8 ... 18 65 ...  add (or, at $066E, AND #$7F and subtract) that
#                             many times, to the note frequency itself
#
# So the offset in frame `i` is `table[i] * count * (interval >> 4)`, applied
# as an absolute *position* relative to the note rather than integrated. Both
# corpus files carry the same four tables, and all four are triangles:
#
#     0: 0 1 0 -1                    len  4, peak 1
#     1: 0 1 2 1 0 -1                len  6, peak 2
#     2: 0 1 2 1 0 -1 -2 -1          len  8, peak 2
#     3: 0 1 2 3 2 1 0 -1 -2 -1      len 10, peak 3
#
# which is why this maps onto Goattracker at all: an arbitrary shape could not
# be approximated by a fixed triangle, and these are already triangles. The
# table PEAK gives the excursion and its LENGTH the period; the arithmetic is
# in goatwriter._table_vibrato_entry.
#
# One thing the classic form has and this does not: the interval here is
# `freq(note+1) - freq(note)`, the semitone ABOVE the note, which is exactly
# what Goattracker note-relative speed computes. The classic players take the
# one below, about 6% of a semitone out. This mapping has no such error.
TABLE_VIBRATO_SHAPE = ("B9 ?? ?? D0 03 4C ?? ?? 48 29 0F 8D ?? ?? 68 29 F0 "
                       "4A 4A 4A 4A AA BD ?? ?? 8D ?? ?? BD ?? ?? 8D ?? ??")

# The walk: index per voice, one entry per frame, $FF wraps to 0.
TABLE_VIBRATO_LFO_SHAPE = ("BC ?? ?? FE ?? ?? B9 ?? ?? C9 FF D0 07 "
                           "A9 00 9D ?? ?? F0")

# The unit: the 16-bit semitone interval at the current note, then one
# `LSR A / ROR zp` per bit of right shift. The shift is COUNTED rather than
# assumed -- it is the 16 in the excursion arithmetic, and a player that
# shifted by 3 would bend twice as far for the same parameter byte.
TABLE_VIBRATO_UNIT_SHAPE = ("0A A8 38 B9 ?? ?? F9 ?? ?? 85 ?? "
                            "B9 ?? ?? F9 ?? ?? 4A 66 ??")

# The high nibble indexes the pointer tables, so no more than 16 of them; and
# the LO table is immediately followed by the HI one, which is what gives the
# count. Anything outside this is not the layout and the file gets no vibrato.
TABLE_VIBRATO_MAX_SHAPES = 16
# The end marker of an LFO table, and the bit that makes an entry negative.
TABLE_VIBRATO_END = 0xFF
TABLE_VIBRATO_SIGN = 0x80
# A table shorter than this is not an oscillation.
TABLE_VIBRATO_MIN_LEN = 2


@dataclass
class TableVibrato:
    """The command-table engine LFO vibrato, once located.

    `offset` is the instrument-record offset of the parameter byte (+5 in both
    corpus files, read out of the `LDA record,Y` rather than assumed).
    `unit_shift` is the player's own right shift on the semitone interval.
    `shapes` is (length, peak) per LFO table, indexed by the parameter byte's
    high nibble; an unreadable table is (0, 0) and yields no vibrato.
    """
    offset: int
    unit_shift: int
    shapes: Tuple[Tuple[int, int], ...]


def _table_vibrato_unit_shift(data: bytes) -> Optional[int]:
    """How far the player shifts the semitone interval right, or None."""
    at = search_file(data, TABLE_VIBRATO_UNIT_SHAPE)
    if at < 1:
        return None
    zp = data[at + 19]          # the `ROR zp` operand of the first pair
    shift, k = 1, at + 20
    while k + 2 < len(data) and data[k] == 0x4A and data[k + 1] == 0x66 \
            and data[k + 2] == zp:
        shift += 1
        k += 3
    return shift


def _read_lfo_table(sid: SidFile, addr: int) -> Tuple[int, int]:
    """(length, peak magnitude) of the LFO table at `addr`, or (0, 0)."""
    data = sid.data
    off = sid.to_offset(addr)
    if not 0 <= off < len(data):
        return 0, 0
    peak = length = 0
    while off < len(data) and data[off] != TABLE_VIBRATO_END:
        peak = max(peak, data[off] & (TABLE_VIBRATO_SIGN - 1))
        length += 1
        off += 1
        if length > 0xFF:
            return 0, 0         # ran off the end of a table with no marker
    if length < TABLE_VIBRATO_MIN_LEN or not peak:
        return 0, 0
    return length, peak


def _find_table_vibrato(sid: SidFile, det: Detection) -> Optional[TableVibrato]:
    """The LFO vibrato of the command-table engine, or None.

    Consulted only where `_find_vibrato` found nothing, so it can rescue a
    file that vibrates not at all and never disturb one that already reads --
    the same rule find_relocation, find_init_writes and the instrument-index
    shape follow.
    """
    data = sid.data
    at = search_file(data, TABLE_VIBRATO_SHAPE)
    if at < 1:
        return None
    if search_file(data, TABLE_VIBRATO_LFO_SHAPE) < 1:
        return None
    unit_shift = _table_vibrato_unit_shift(data)
    if unit_shift is None:
        return None
    # The two STAs must patch consecutive bytes -- the operand of the LDA
    # abs,Y in the walk. If they do not, this is not the routine it looks like.
    if (data[at + 32] | data[at + 33] << 8) != (data[at + 26]
                                                | data[at + 27] << 8) + 1:
        return None
    start = det.instr_start + sid.load_addr - HLEN + 1
    offset = (data[at + 1] | data[at + 2] << 8) - start
    if not 0 <= offset < det.instr_stride:
        return None
    lo = data[at + 23] | data[at + 24] << 8
    hi = data[at + 29] | data[at + 30] << 8
    count = hi - lo
    if not 1 <= count <= TABLE_VIBRATO_MAX_SHAPES:
        return None
    shapes = []
    for i in range(count):
        a, b = sid.to_offset(lo + i), sid.to_offset(hi + i)
        if not (0 <= a < len(data) and 0 <= b < len(data)):
            return None
        shapes.append(_read_lfo_table(sid, data[a] | data[b] << 8))
    if not any(s[0] for s in shapes):
        return None
    return TableVibrato(offset, unit_shift, tuple(shapes))


# The status-byte fetch that tests bit 6 first, and alone. Commando $50C2
# (Last V8 $80CF is byte-for-byte the same shape):
#
#     50C2  B1 5F     LDA ($5F),Y       ; the status byte
#     50C4  9D F5 54  STA $54F5,X       ; kept raw, per voice
#     50C7  8D 02 55  STA $5502         ; ...and in a scratch cell
#     50CA  29 1F     AND #$1F
#     50CC  9D F2 54  STA $54F2,X       ; wait counter (low 5 bits)
#     50CF  2C 02 55  BIT $5502         ; V := bit 6 of the status byte
#     50D2  70 44     BVS $5118         ; set -> skip BOTH reads below
#     50D4  ...       INC / LDA $5502 / BPL ...
#     50DC  C8 B1 5F  INY / LDA ($5F),Y ; bit 7 set: the operand byte
#     50ED  C8 B1 5F  INY / LDA ($5F),Y ; the note byte
#
# The BVS lands at the DEC past both INY/LDA pairs, whatever bit 7 says --
# so a status byte of $C0-$FE consumes nothing but itself, where a decoder
# that honours bit 7 first reads an operand and a note it never read and
# desynchronises the rest of the pattern. 61 of 95 corpus files have this
# shape; the rest (the digi and cmdtable engines among them) fetch
# differently and are not touched by the flag this gates.
STATUS_BIT6_SHAPE = "B1 ?? 9D ?? ?? 8D ?? ?? 29 1F 9D ?? ?? 2C ?? ?? 70"


def _find_status_bit6(data: bytes) -> bool:
    return search_file(data, STATUS_BIT6_SHAPE) >= 1


# --- The instrument effect byte (+7) ---------------------------------------
#
# H2G has always read +7 as a bit-field -- bit $01 a drum, bit $04 an arpeggio
# whose interval is the high nibble -- and written a fabricated wavetable from
# it for every file. That reading is Warhawk's, and it is **not** the format.
# Reading the byte's own consumers out of four other players:
#
#     Warhawk               $15BD   AND #$08 / AND #$01 / AND #$02 / AND #$04
#                                   / LSR x4        <- the bit-field
#     Mega Apocalypse       $4F60   LDA / BEQ       <- whole byte, zero or not
#     W.A.R. Preview        $0CF8   LDA / BEQ, then CLC / ADC
#     One Man and his Droid $1501   LDA / BEQ, then AND #$E0
#     Chicken Song          $15C1   AND #$02, but the block ORAs #$80 into the
#                                   waveform at $D404 -- a noise swap, not a
#                                   pitch rise
#
# So the same bit means different things in different players, and a converter
# that assumes otherwise invents effects. Measured: applying Warhawk's reading
# corpus-wide put 287 frames of pitch movement into W.A.R. Preview and 256 into
# Mega Apocalypse, whose originals have none at all in the traced window.
#
# Hence these two probes, which do not trust the dialect number or a bare
# opcode shape. They resolve the address the instrument-load routine stores +7
# to, and then require the test block to name *that* address. Warhawk $13A2:
#
#     13A2  AD BD 15  LDA effect        13CD  AD BD 15  LDA effect
#     13A5  29 02     AND #$02          13D0  29 04     AND #$04
#     13A7  F0 24     BEQ                13D2  F0 3F     BEQ
#     13A9  AD BF 15  LDA framecount    13D4  AD BD 15  LDA effect
#     13AC  29 03     AND #$03          13D7  4A 4A 4A 4A  LSR x4
#     13AE  D0 1D     BNE                13DB  8D F5 13  STA (into an SBC operand)
#     13B0  FE 7F 15  INC noteindex,X
#
# 4 of 83 convertible corpus files have the rise block, 13 the arpeggio block.
EFFECT_STORE_ABS = 0x8D
EFFECT_STORE_ZP = 0x85


def _effect_byte_address(sid: SidFile, det: Detection):
    """(address, is_zeropage) the player keeps instrument byte +7 in, or None."""
    if det.instr_start < 0 or det.instr_stride != 8:
        return None
    # Inverse of SidFile.to_offset. A relocated file (to_offset's `relocation`
    # branch) would need the relocated form instead, but no such corpus file
    # gets this far -- the probe returns None when the load is not found.
    base = det.instr_start - (HLEN - 1) + sid.load_addr + 7
    if not 0 <= base <= 0xFFFF:
        return None
    i = search_file(sid.data, "B9 %02X %02X" % (base & 0xFF, base >> 8))
    if i <= -1 or i + 5 >= len(sid.data):
        return None
    store = sid.data[i + 3]
    if store == EFFECT_STORE_ABS:
        return (sid.data[i + 4] | sid.data[i + 5] << 8, False)
    if store == EFFECT_STORE_ZP:
        return (sid.data[i + 4], True)
    return None


# Flash Gordon $128F. The pulse-width sweep, and the only routine in this
# family that writes $D402/$D403 every frame rather than once at note start:
#
#   LDY $1535        ; instrument index * 8, saved by the note-start code
#   LDA bounds,Y     ; one byte holding both turning points
#   AND #$0F         ; low nibble  -> lower bound
#   STA $12D4        ; self-modifies the CMP in the descending branch
#   LDA bounds,Y
#   LSR LSR LSR LSR  ; high nibble -> upper bound
#   STA $12BA        ; self-modifies the CMP in the ascending branch
#
# The two self-modified compares are what make the shape unambiguous: the
# routine writes its own bounds into its own operands, so both nibbles of one
# byte are provably the turning points and nothing else. The block then adds or
# subtracts a rate to a 12-bit per-voice accumulator and flips direction when
# the HIGH nibble reaches a bound -- a triangle wave on the duty cycle, which
# is the sound the aggregate "waveform class agrees" metric cannot see at all.
PULSE_SWEEP = ("AC ?? ?? B9 ?? ?? 29 0F 8D ?? ?? "
               "B9 ?? ?? 4A 4A 4A 4A 8D ?? ??")
# The note-start code that feeds it: instrument index * 8 into Y, then two
# record bytes copied into fixed cells. The second is the sweep rate -- the
# cell the block above reads with `LDA rate / ADC accumulator`.
PULSE_SETUP = "0A 0A 0A A8 8C ?? ?? B9 ?? ?? 8D ?? ?? B9 ?? ?? 8D ?? ??"
# The adding branch sits 26 bytes past the block start in every corpus file
# that carries it; the window is generous enough for a reordered variant and
# short enough not to reach the next routine.
PULSE_SWEEP_WINDOW = 64


def _find_pulse_sweep(sid: SidFile, det: Detection):
    """(bounds_offset, rate_field): the per-frame pulse sweep, or (-1, -1).

    Both halves are required. The sweep block alone gives the bounds array but
    not which record byte sets the rate, and the setup block alone proves
    nothing about what the rate is used for -- it is the `8D` naming the same
    cell the sweep reads that ties them together.

    The bounds array sits outside the instrument records, at a file-dependent
    distance (corpus range: +12 to +348 bytes from `instr_start`), so its
    address is read from the instruction rather than assumed. The rate field is
    +5 in 42 of the 43 corpus files that carry the block; the 43rd resolves
    outside the file and is rejected here rather than trusted.
    """
    i = search_file(sid.data, PULSE_SWEEP)
    j = search_file(sid.data, PULSE_SETUP)
    if i < 1 or j < 1:
        return -1, -1
    bounds_addr = sid.data[i + 4] | sid.data[i + 5] << 8
    rate_addr = sid.data[j + 14] | sid.data[j + 15] << 8
    # The sweep must read the cell the setup writes, or the two blocks belong
    # to different routines and the rate is not this rate.
    if (sid.data[j + 17] | sid.data[j + 18] << 8) != _sweep_rate_cell(sid, i):
        return -1, -1
    try:
        bounds = sid.to_offset(bounds_addr)
        rate_field = sid.to_offset(rate_addr) - det.instr_start
    except Exception:                                    # noqa: BLE001
        return -1, -1
    if not 0 <= bounds < len(sid.data):
        return -1, -1
    if not 0 <= rate_field < det.instr_stride:
        return -1, -1
    return bounds, rate_field


def _sweep_rate_cell(sid: SidFile, sweep: int) -> int:
    """Address the sweep block loads its per-frame step from.

    Immediately past the bounds read, one branch is `LDA rate / CLC / ADC acc`
    and the other `SEC / LDA acc / SBC rate`. The absolute load in the adding
    branch is the cell. Searched in a window starting at the matched block so
    it stays tied to that routine rather than to any `LDA/CLC/ADC` in the file.
    """
    window = sid.data[sweep:sweep + PULSE_SWEEP_WINDOW]
    i = search_file(window, "AD ?? ?? 18 7D ?? ?? 48")
    if i < 1:
        return -1
    return window[i + 1] | window[i + 2] << 8


def _find_effect_routines(sid: SidFile, det: Detection):
    """(rise, arp, drum, pulse_lo): which +7 bits the player really implements.

    Each probe requires the block to name the *resolved* +7 address, so a
    player that happens to `AND #$04` against something else does not count.
    That distinction is the whole finding: corpus-wide the bits are tested far
    more often than Warhawk's blocks appear -- bit $04 is tested against the
    effect byte in 62 files and only 13 of them arpeggiate with it. See the
    census table in H2G-CONVERSION-METHOD.md section 7.
    """
    found = _effect_byte_address(sid, det)
    if not found:
        return False, False, False, False
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    any_load = "A5 ??" if zp else "AD ?? ??"
    rise = search_file(
        sid.data, f"{load} 29 02 F0 ?? {any_load} 29 03 D0 ?? FE") >= 1
    arp = search_file(
        sid.data, f"{load} 29 04 F0 ?? {load} 4A 4A 4A 4A 8D") >= 1
    # Warhawk $1366. Two guard loads follow the bit test -- a per-voice drum
    # counter and the note's own duration -- before the block decrements the
    # counter into $D401 (frequency high) and finally writes #$80 (noise) to
    # $D404. The two BEQ guards are what make this shape specific: a bare
    # `LDA effect / AND #$01 / BEQ` matches far more players than mean by it
    # what Warhawk means.
    drum = search_file(
        sid.data, f"{load} 29 01 F0 ?? BD ?? ?? F0 ?? BD ?? ?? F0") >= 1
    # Warhawk $12A3, Commando $52AC. The other pulse engine: it adds a rate to
    # a running accumulator and writes that to $D402 (pulse LO) alone, never
    # touching $D403, so the width wraps inside one 256-wide band instead of
    # travelling the 12-bit range.
    #
    # `LDY` loads a *byte offset* (instrument index times stride) and
    # `LDA base,Y` reads the instrument records themselves -- Commando's block
    # names $5591, which is where its instrument table starts. See
    # `_find_pulse_lo` for the field layout and the corpus evidence.
    pulse_lo = search_file(
        sid.data,
        f"{load} 29 08 F0 ?? AC ?? ?? B9 ?? ?? 6D ?? ?? "
        f"99 ?? ?? AC ?? ?? 99 02 D4") >= 1
    return rise, arp, drum, pulse_lo


def _find_pulse_lo(sid: SidFile, det: Detection) -> int:
    """File offset of the pulse-lo state array, or -1.

    The block matched by `_find_effect_routines` names the array in its own
    operands:

        LDA base,Y  /  ADC ratecell  /  STA base,Y  /  LDY voice  /  STA $D402,Y

    `base` is the instrument table itself -- the block indexes it by the same
    stride the records use. The field layout is read out of two further sites
    rather than assumed:

    * the rate is not in that block -- `ratecell` is absolute, self-modified at
      note fetch from `base + 6` (Commando $5232). Across the 21 corpus files
      carrying this engine the rate is loaded from **base + 6 in 21 of 21**,
      which is what establishes +6 as the rate field. It agrees with the
      independent SF2 reading recorded in SIDM2-HUBBARD-KNOWLEDGE.md.
    * the width is seeded per note by `PLA / STA base+1,Y / STA $D403,X /
      PLA / STA base,Y / STA $D402,X` (Commando $5326), giving +0 = low and
      +1 = high -- the same two bytes the static path has always written as a
      fixed width. That site is findable in 12 of the 21, and in all 12 the
      high byte is at base+1; the other nine take it by that rule.

    The seeding matters beyond the layout: because the accumulator is reloaded
    at every note fetch, Goattracker's pulse table -- which restarts with the
    note -- models this engine faithfully. A free-running accumulator could not
    have been expressed at all.
    """
    found = _effect_byte_address(sid, det)
    if not found:
        return -1
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    off = search_file(
        sid.data,
        f"{load} 29 08 F0 ?? AC ?? ?? B9 ?? ?? 6D ?? ?? "
        f"99 ?? ?? AC ?? ?? 99 02 D4")
    if off < 0:
        return -1
    d = sid.data
    base = d[off + 11] | (d[off + 12] << 8)
    # The store must name the same array the load read, or this is not the
    # accumulate-in-place shape and nothing here is trustworthy.
    if (d[off + 17] | (d[off + 18] << 8)) != base:
        return -1
    at = sid.to_offset(base)
    if at < 0 or at + 6 >= len(d):
        return -1
    # The block must be reading the instrument records. Anything else means the
    # signature matched a shape whose field offsets are not the ones above.
    if at != det.instr_start:
        return -1
    return at


def _find_effect_bit80(sid: SidFile, det: Detection) -> tuple[str, int]:
    """("sfx"|"program"|"pitch"|"", pointer-array offset): what bit $80 drives.

    Bit $80 belongs to the eight-flag reading of +7 (see below), and the one
    thing every earlier note about it got wrong is treating it as *one* block.
    All 12 corpus files that test it reach it the same way -- `LDA effect /
    BPL` -- and then do three unrelated things:

    **"sfx", 9 files.** IK+ `$E41A`, Bangkok Knights `$8488`, Mega Apocalypse
    `$4E43`, Nineteen `$946E`, Pandora `$F81E`, Ricochet `$946D`, Star Paws
    `$B3F9`, Thundercats `$F17E`, Trans-Atlantic Balloon `$0C2E`. A *global*
    state cell -- not per voice, not per instrument -- is compared against 1
    and then against 6, 8 or 9, and the arms write fixed constants into
    `$D40F` (cutoff high, `$48`/`$38`), `$D412` (voice-3 control, `$81` =
    noise + gate), `$D416` (`$60`/`$50`) and `$D418` (volume, `$2F`/`$1F`),
    zeroing the cell when it runs past the end. IK+ writes two of them into
    its own code (`$E5F2`, `$E5F5`) rather than to the chip; Ricochet's arms
    are `LDA #$00` with the writes stripped out of the rip entirely.

    That is the game's noise -- an explosion or a hit -- triggered by code
    that is not in the SID file at all, and nothing a converted tune does ever
    writes the cell. So it is not merely inexpressible in a per-instrument
    wavetable (it is global, and it seizes voice 3 and the master volume): it
    is **not music, and must not be converted**. This probe exists to say so.

    **"program", 2 files.** ACE II `$E357`, Auf Wiedersehen Monty `$E743`. A
    16-bit pointer per instrument, from an array strided like the records
    (`LDA $E624,Y / LDA $E625,Y`, the same `Y = i * instr_stride`), into a
    byte-code program stepped one entry per frame by a per-voice program
    counter (`$EBC7,X`). An entry >= $80 is `$85` -- hold here, the counter is
    not advanced -- or a two-byte (waveform -> `$D404`, next byte -> `$D401`
    frequency high) pair. An entry < $80 is three bytes: a waveform into the
    voice's own waveform cell, then a 16-bit `SBC` of the following two bytes
    off the voice's frequency. This one *is* a wavetable, and Goattracker can
    carry the waveform half exactly; the pitch half is a raw frequency delta
    where Goattracker's right column is a note, so it can only be approximated.

    **"pitch", 1 file.** Delta `$C1EC`. A per-voice counter (`$C351,X`) is
    decremented, and on expiry reloaded from `$C43E,Y` while `$C43F,Y` is
    added to the voice's frequency-high cell (`$C34B,X`) -- a stepped sweep in
    the same family as the vibrato of section 7.ee, but table-walked.

    Nothing here is written to the output. The reading ships and the encoding
    does not, for the reason `_find_two_stage` records: resolve what the byte
    means from the 6502, then decide separately, by measurement, whether the
    target format should carry it.
    """
    found = _effect_byte_address(sid, det)
    if not found:
        return "", -1
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    llen = 2 if zp else 3
    data = sid.data

    # The pointer-array shape. The two `B9`s must read consecutive bytes of the
    # same array (low then high) into consecutive zero-page cells, and the
    # program byte itself is fetched indirectly through them.
    off = search_file(
        data,
        f"{load} 10 ?? 8E ?? ?? B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? "
        f"BD ?? ?? A8 B1 ?? 10 ??")
    if off >= 0:
        lo = data[off + llen + 6] | (data[off + llen + 7] << 8)
        hi = data[off + llen + 11] | (data[off + llen + 12] << 8)
        zp_lo, zp_hi = data[off + llen + 9], data[off + llen + 14]
        at = sid.to_offset(lo)
        if hi == lo + 1 and zp_hi == zp_lo + 1 and 0 <= at < len(data):
            return "program", at
        return "program", -1

    # Delta's counter/delta table: DEC the per-voice counter, and only on the
    # frame it goes negative reload it and add the paired byte to the voice's
    # frequency cell. The `18 79` (CLC / ADC abs,Y) is what separates it from
    # every reload-a-counter block that does not move pitch.
    if search_file(
            data,
            f"{load} 10 ?? AC ?? ?? DE ?? ?? 10 ?? B9 ?? ?? 9D ?? ?? "
            f"BD ?? ?? 18 79 ?? ?? 9D ?? ??") >= 0:
        return "pitch", -1

    # The sound effect: bit $80 set, then a *global* cell (absolute or
    # zero-page, never indexed) compared against a constant. Deliberately loose
    # about what the arms write -- IK+ patches its own code and Ricochet's arms
    # are empty -- because the shape being matched is "a global state machine",
    # which is already enough to know this is not per-instrument music.
    for state in ("AD ?? ??", "A5 ??"):
        if search_file(data, f"{load} 10 ?? {state} C9 ?? F0 ??") >= 0:
            return "sfx", -1
    return "", -1


# --- The same byte, a second format ----------------------------------------
#
# _find_effect_routines reads +7 as Warhawk does: four flags in the low nibble
# and an arpeggio interval in the high one, taken with `LSR x4`. That is not
# the only format. Across the corpus the two readings are cleanly disjoint --
# 13 files take the high nibble as a number and 41 test $10/$20/$40/$80 as
# single bits, and **no file does both**. In that second family +7 is eight
# flags, and bit $04 is not an arpeggio at all.
#
# IK+ $E38B, which 34 files share byte-for-byte in shape:
#
#     E38B  29 04     AND #$04
#     E38D  F0 14     BEQ out
#     E38F  BD FC E7  LDA counter,X     ; per-voice, set at note start
#     E392  F0 09     BEQ expired
#     E394  DE FC E7  DEC counter,X
#     E397  B9 EE E9  LDA attack,Y      ; still running -> the attack waveform
#     E39A  4C A0 E3  JMP store
#     E39D  B9 77 E9  LDA $E977,Y       ; expired  -> instrument +2
#     E3A0  9D 8F E5  STA wavslot,X
#
# `$E977` is the instrument's own +2, the waveform H2G already emits, so the
# only new datum is the attack waveform and how long it lasts. Both live in a
# second 8-byte-per-instrument array that runs parallel to the records and is
# indexed by the same `Y = i * stride`: attack at its +1, duration at its +3.
#
# The duration is resolved a second, independent way and the two are required
# to agree. At note start the player pushes three record fields and pops them
# into per-voice slots, and the last thing pushed is the first thing popped --
# into the very counter this block decrements (IK+ $E16E / $E18A):
#
#     E160  BD 75 E9 / 99 E5 E5 / 48     LDA instr+0,X / STA / PHA
#     E167  BD 76 E9 / 99 E6 E5 / 48     LDA instr+1,X / STA / PHA
#     E16E  BD F0 E9 / 48                LDA duration,X / PHA
#     ...
#     E18A  68 / 9D FC E7                PLA / STA counter,X
#
# Corpus-wide that push chain names exactly `attack + 2` in **34 files out of
# 34**. Requiring both is what makes this a reading rather than an inference:
# a player that matches the block but keeps its duration elsewhere is skipped
# instead of being given a made-up one.
TWO_STAGE_SHAPE = ("{load} 29 04 F0 ?? BD ?? ?? F0 ?? DE ?? ?? "
                   "B9 ?? ?? 4C ?? ?? B9 ?? ?? 9D ?? ??")
# LDA instr+0,X / STA .. / PHA / LDA instr+1,X / STA .. / PHA / LDA dur,X / PHA
TWO_STAGE_PUSH = "BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48 BD ?? ?? 48"


def _find_two_stage(sid: SidFile, det: Detection):
    """(found, attack_offset, duration_offset) for the two-stage waveform.

    Both offsets are into `sid.data` and are indexed by `i * instr_stride`,
    exactly like the instrument records themselves. Returns (False, -1, -1)
    unless the block is found *and* the note-start push chain independently
    puts the duration at attack+2.
    """
    found = _effect_byte_address(sid, det)
    if not found or det.instr_start < 0:
        return False, -1, -1
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    i = search_file(sid.data, TWO_STAGE_SHAPE.format(load=load))
    if i <= -1:
        return False, -1, -1
    data = sid.data
    p = i + len(load.split())
    if p + 20 >= len(data):
        return False, -1, -1
    attack = data[p + 13] | data[p + 14] << 8

    j = search_file(data, TWO_STAGE_PUSH)
    if j <= -1 or j + 16 >= len(data):
        return False, -1, -1
    duration = data[j + 15] | data[j + 16] << 8
    if duration != attack + 2:
        return False, -1, -1

    # Same inverse of SidFile.to_offset _effect_byte_address uses.
    instr_cpu = det.instr_start - (HLEN - 1) + sid.load_addr
    off = attack - instr_cpu + det.instr_start
    span = max(det.instr_used, 0) * det.instr_stride
    # Parenthesised: `not 0 <= off and ...` binds as `(not (0 <= off)) and
    # (...)`, which rejects only a negative offset that is also in range --
    # i.e. nothing -- and lets a table running off the end of the file
    # through. This is the guard on the offset the instrument bound is
    # computed from, so a bad one would be silently trusted.
    if not (0 <= off and off + span + 2 <= len(data)):
        return False, -1, -1
    return True, off, off + 2


def _bound_instruments(det: Detection, log: Logger):
    """End the instrument table where the two-stage array begins.

    The count comes from walking the records in `instr_stride` steps and
    stopping at the first +2 byte that is not a waveform. Nothing stops that
    walk at the end of the records: the array `_find_two_stage` just located
    follows them immediately, its rows are the same 8 bytes long, and its own
    +2 -- the low byte of the duration -- is a legal waveform often enough to
    keep the walk going. So it counts both tables and lands at roughly twice
    the truth: IK+ 30 where 15 are real, Wiz 40 where 20 are, Delta 44/22.

    The consequence is not cosmetic. Those phantom records are written out as
    instruments with an ADSR read from duration bytes, and a table of 58 trips
    the wavetable ceiling, so files were reported as losing real instruments
    to Goattracker's limit when they have half as many as counted.

    `two_stage_wave` is the array's +1, so the array -- and therefore the end
    of the records -- is one byte below it. Applied only when that lands on an
    exact multiple of the stride, i.e. when the two tables really are adjacent
    and equally sized; three corpus files (ACE II, Trans-Atlantic Balloon
    Challenge, W.A.R.) do not, and keep the count they had.

    Checked against what the music asks for rather than against the
    arithmetic: over the 34 corpus files with this array, the bound never
    falls below the highest instrument any pattern references, and in four
    (Dragon's Lair II, Kings of the Beach ingame, Lightforce, Nemesis) it is
    exactly that instrument. An accidental boundary does not land on the last
    instrument a tune plays, four times.
    """
    base = det.two_stage_wave - 1
    span = base - det.instr_start
    if span <= 0 or span % det.instr_stride:
        return
    bound = span // det.instr_stride
    if bound >= det.instr_used:
        return
    log(f"Instrument table ends at: ${base:X} (file offset) -- "
        f"{det.instr_used} counted, {bound} before the two-stage array")
    det.instr_used = bound
