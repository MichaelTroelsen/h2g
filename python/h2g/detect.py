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
    # True when the player's instrument effect byte (+7) really is Warhawk's
    # bit-field, proved by finding the routine that tests it. The byte is NOT
    # a shared format across the player family -- see _find_effect_routines().
    effect_rise: bool = False   # bit $02: +1 semitone every 4 frames
    effect_arp: bool = False    # bit $04: alternate with note - (byte >> 4)
    effect_drum: bool = False   # bit $01: pitch sweep down, then noise
    effect_pulse_lo: bool = False  # bit $08: accumulate +6 into pulse width LO
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
    # Player calls one emitted row is meant to last. 1 everywhere except the
    # "cmdtable" dialect, whose durations come from a table of multiples --
    # see patterns.cmdtable_frames_per_row, which fills this in.
    frames_per_row: int = 1
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
    i = find("BD ?? ?? 99 02 D4 48 BD ?? ?? 99 03 D4")       # Chimera
    if i <= -1:
        i = find("BD ?? ?? 99 02 D4 BD ?? ?? 99 03 D4")      # ACE2
    if i <= -1:
        i = find("BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48")  # IK+
    if i <= -1:
        log("*** CAN'T FIND INSTRUMENTS ***")
    else:
        addr = _addr16(data, i + 1, i + 2)
        det.instr_start = sid.to_offset(addr)
        log(f"Found Instruments at....: ${addr:X}")
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
    if det.slide_operand:
        log("Pattern slide form......: two-byte (16-bit step)")

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

    return det


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
    # Warhawk $12A3. Selects a variant of the +6 pulse-width sweep: instead of
    # the triangle into $D403 (pulse HI), it ADCs +6 into the instrument's own
    # +0 byte and writes that to $D402 (pulse LO) -- and stores the running
    # total back into the record, so a static read of +0 sees only its initial
    # value.
    pulse_lo = search_file(
        sid.data,
        f"{load} 29 08 F0 ?? AC ?? ?? B9 ?? ?? 6D ?? ?? "
        f"99 ?? ?? AC ?? ?? 99 02 D4") >= 1
    return rise, arp, drum, pulse_lo
