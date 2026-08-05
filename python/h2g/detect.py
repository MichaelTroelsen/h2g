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

from dataclasses import dataclass
from typing import Callable, Optional

from .search import search_file
from .sidfile import SidFile

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


def detect(sid: SidFile, log: Logger) -> Detection:
    data = sid.data
    det = Detection()

    def find(pattern: str) -> int:
        return search_file(data, pattern)

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
    log(f"Player Trackread version: {det.read_track_version:X}")
    if det.transpose_operand:
        log("Track transpose form....: two-byte (value follows the command)")

    return det
