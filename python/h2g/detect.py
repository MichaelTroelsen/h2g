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

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .search import match_at, search_file
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
    # And a THIRD vibrato: one routine assembled into 25 corpus files, whose
    # oscillator is a global triangle rather than anything per instrument, and
    # whose record byte is a bare right-shift count rather than the $78/$07
    # pair. Mutually exclusive with both of the above -- see
    # _find_triangle_vibrato().
    triangle_vibrato: Optional[int] = None
    # The note-length threshold that player gates the vibrato on, read from
    # its own CMP -- _find_triangle_gate().
    triangle_gate: Optional[int] = None
    # Whether the player kills the envelope when a note ends, so the record's
    # release nibble is never audible -- find_envelope_cut().
    envelope_cut: bool = False
    # Whether the player tests effect bit $40 -- a fixed pitch for the attack,
    # taken from its own note table. _find_effect_bit40().
    effect_bit40: bool = False
    # Effect bit $10's arpeggio: a three-step semitone sequence stepped by a
    # *global* phase counter. _find_pitch_seq().
    pitch_seq: Optional["PitchSeq"] = None
    # True when the player's instrument effect byte (+7) really is Warhawk's
    # bit-field, proved by finding the routine that tests it. The byte is NOT
    # a shared format across the player family -- see _find_effect_routines().
    effect_rise: bool = False   # bit $02: +1 semitone every 4 frames
    effect_arp: bool = False    # bit $04: alternate with note - (byte >> 4)
    # Semitones *up* for the second arpeggio dialect, whose interval is
    # hardcoded in the routine rather than taken from the record's high
    # nibble. 0 means the nibble form above. See _find_effect_routines.
    arp_fixed_up: int = 0
    effect_drum: bool = False   # bit $01: pitch sweep down, then noise
    effect_pulse_lo: bool = False  # bit $08: accumulate +6 into pulse width LO
    # A SECOND, mutually exclusive reading of the same byte -- see
    # _find_two_stage(). In this family bit $04 is not an arpeggio at all: it
    # holds an attack waveform for a per-instrument number of frames and then
    # drops to the record's own +2. Both file offsets are indexed by the same
    # i * instr_stride the effect byte itself is.
    effect_two_stage: bool = False
    # Set from the player's own orderlist reader; see _find_track_terminators.
    track_fd_ends: bool = False
    track_fe_command: bool = False
    two_stage_wave: int = -1    # file offset of the attack-waveform table
    two_stage_frames: int = -1  # file offset of its duration table
    # Bit $02 in the SAME family, and not the rise: the voice's waveform
    # alternates every frame between the record's own +2 and a second table,
    # picked by a per-voice frame counter's low bit (W_A_R $E759). File offset
    # of that table's first entry, indexed by the same i * instr_stride.
    wave_alternate: int = -1
    # A second dialect of the same alternation (Hollywood or Bust $0774,
    # Chicken Song): the alternate is not tabled but *derived* from the
    # voice's own waveform as `$80 | (wave & $07)` -- noise keeping the
    # control bits -- and the counter is global rather than per voice. True
    # where that block was found; `wave_alternate` stays -1 for it.
    wave_alternate_noise: bool = False
    # A THIRD reading of bit $02, Ninja $CAFD: a two-stage attack whose
    # waveform and duration are per *voice* rather than per instrument -- two
    # static three-byte tables the player indexes by the voice it is
    # servicing. File offsets of those tables, or -1 -- see
    # _find_voice_two_stage().
    voice_two_stage_alt: int = -1
    voice_two_stage_frames: int = -1
    # Bit $01 in the same player, and the per-voice spelling of
    # `wave_alternate`: the voice's waveform alternates every call between the
    # record's own +2 and a three-byte table indexed by voice rather than by
    # instrument. File offset of that table, or -1 -- see
    # _find_voice_wave_alternate().
    voice_wave_alternate: int = -1
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
    # The third pulse engine -- see _find_pulse_tri(). A triangle across the
    # 12-bit width like `pulse_bounds`, but its turnaround nibbles are constants
    # in the routine rather than a per-record array, and its rate byte packs
    # two fields: & $E0 the step, & $1F the frames between steps. The high
    # nibbles are read from the two CMP operands, never assumed. `gated` is
    # whether the routine sits behind an effect-bit-$08 test, which decides
    # whether it or the accumulate engine above runs for a given record; five
    # of the 24 corpus files carrying it have no such test and sweep every
    # record. The rate is at record +6 in 24 of 24, the same byte the
    # accumulate engine uses.
    pulse_tri_lo: int = -1
    pulse_tri_hi: int = -1
    pulse_tri_gated: bool = False
    # Effect byte bit $80, in the eight-flag format only -- and it is not one
    # block. The 12 corpus files that test it split three ways; see
    # _find_effect_bit80(). "sfx" (9 files) is the *game's* sound effect, keyed
    # off a global state cell no converted tune ever writes; "program" (2) is a
    # per-instrument byte-code wave program; "pitch" (1) steps the frequency
    # from a duration/delta table. Read only -- goatwriter consumes none of it,
    # for the reasons in H2G-CONVERSION-METHOD.md section 7.jj.
    effect_bit80: str = ""
    # The "sfx" shape's own numbers -- see _find_sfx_drum(). It is a
    # fixed-pitch noise burst on one voice, fired every `sfx_period` frames
    # while an instrument with bit $80 is playing: frequency HIGH byte
    # `sfx_pitch` (never the note's), waveform $81, and a cutoff and volume
    # the block also writes. -1 when the block is absent.
    sfx_pitch: int = -1
    sfx_voice: int = -1
    sfx_period: int = -1
    # File offset of the "program" shape's per-instrument pointer array (two
    # bytes per record, strided like the instrument table), or -1.
    effect_program: int = -1
    # The byte-code wave program -- see find_wave_program(). Found in 29 of the
    # 95 corpus files, which makes it the most widespread instrument mechanism
    # still unemitted. `wave_program` is the file offset of the per-instrument
    # pointer array; `wave_program_gate` is the effect-byte bit that selects it,
    # 0 where the shape was not recognised. Read only -- goatwriter consumes
    # neither yet.
    wave_program: int = -1
    wave_program_gate: int = 0
    # Classic dialect only: bit 7 of a pattern note byte is a flag, not part of
    # the note -- the player masks it off before the frequency lookup.
    note_flag: bool = False
    # True when the player tests bit 6 of the status byte FIRST and alone
    # (`BIT status / BVS`), branching past the operand read AND the note read
    # -- so a $C0-$FE status byte consumes only itself. See STATUS_BIT6_SHAPE.
    status_bit6: bool = False
    # ...and whether the branch it takes silences the voice *itself* rather
    # than leaving it to the ordinary end-of-note path. 21 of the 61 files
    # with the shape do. Read and logged; **not** a gate on anything, because
    # the voice ends up released across the rest either way -- see
    # _find_rest_silences, which explains why gating `--rest-keyoff` on it
    # was wrong.
    rest_silences: bool = False
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


def detect(sid: SidFile, log: Logger, engine: int = 0) -> Detection:
    """Read one player's tables out of `sid`.

    `engine` selects *which* player, for a file that carries more than one.
    0 is the one the PSID header's `startSong` plays and the only one anything
    here converts by default; 1 is "not the digi engine", which is what
    separates the two copies in the only corpus file where they differ (see
    § 7.kkkkk). On a file with a single classic player the two are identical
    by construction -- `_detect_digi` returns False either way -- so the
    option can only ever change a file that has something else to find.
    """
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
    #
    # `engine` is asked here because this one probe is what forks the whole
    # rest of the function: every chain below is guarded on `digi`, so
    # declining it runs the classic chains over the same file and they find
    # the other player unaided. Powerplay Hockey's nine cues need no new
    # signature at all -- tracks $3C60/$3C63, selector $3C66, patterns
    # $3C9C/$3CBB and instruments $3BA0 all fall out of chains that were
    # already there and were simply never reached (§ 7.kkkkk).
    digi = False if engine else _detect_digi(sid, det, log)

    # --- Instruments ---------------------------------------------------
    # Every signature in this chain fingerprints the *store* into the SID:
    # `LDA record,X / STA $D40x,Y`. That is what makes them fail on a player
    # which reaches the SID through subroutines instead -- Phantoms of the
    # Asteroid writes its five instrument bytes with `JSR $F04E/$F056/$F066/
    # $F06E` and matches none of them, so it converted with zero instruments
    # and played silence. INSTRUMENT_INDEX_SHAPE below fingerprints the *load*
    # instead, which is common to both.
    idx = _find_instrument_index(sid, det, log)
    shape_used = "BD ?? ?? 99 02 D4 48 BD ?? ?? 99 03 D4"    # Chimera
    i = find(shape_used)
    if i <= -1:
        shape_used = "BD ?? ?? 99 02 D4 BD ?? ?? 99 03 D4"   # ACE2
        i = find(shape_used)
    if i <= -1:
        shape_used = "BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48"   # IK+
        i = find(shape_used)
    addr = -1
    if i > -1:
        addr = _addr16(data, i + 1, i + 2)
        # **A file can carry two copies of the player.** Powerplay Hockey has
        # one at $36xx driving nine short game cues and another at $43F0
        # driving the tune the PSID header starts on, the same code at a
        # different base -- and the chain above takes whichever match comes
        # first in the file, which is the cue engine's. Its orderlist and
        # pattern signatures matched the *other* copy, so the conversion
        # played the right notes through the wrong instruments: `adsr` 0%,
        # not one envelope pair shared with the original, and the four
        # columns keyed by instrument (`onset`, `nrun`, `hold`, `tail`) all
        # unmeasurable.
        #
        # So where the same signature matches more than once, take the table
        # nearest the pattern pointers -- the rule `find_song_speeds` already
        # uses to pick between several speed gates, in the other direction.
        # A single-match file cannot move.
        near = _nearest_table(data, shape_used, det.pattern_lo, sid)
        if near >= 0 and near != addr:
            log(f"Found Instruments at....: ${near:X} (nearest the patterns; "
                f"${addr:X} belongs to another copy of the player)")
            addr = near
        else:
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
        else:
            det.triangle_vibrato = _find_triangle_vibrato(sid, det)
            if det.triangle_vibrato is not None:
                det.triangle_gate = _find_triangle_gate(
                    sid, search_file(data, TRIANGLE_VIBRATO_SHAPE))
                log(f"Instrument vibrato......: record +{det.triangle_vibrato} "
                    f"(shift count, global {TRIANGLE_VIBRATO_PERIOD}-call "
                    f"triangle 0..{TRIANGLE_VIBRATO_PEAK}, no vibrato below "
                    f"duration {det.triangle_gate or TRIANGLE_VIBRATO_GATE}"
                    + ("" if det.triangle_gate else ", assumed") + ")")

    det.pitch_seq = _find_pitch_seq(sid)
    if det.pitch_seq is not None:
        log(f"Effect bit $10..........: {det.pitch_seq.steps}-step pitch "
            "sequence on a global phase counter")

    det.effect_bit40 = _find_effect_bit40(sid)
    if det.effect_bit40:
        log("Effect bit $40..........: fixed attack pitch from the note table")

    det.envelope_cut = find_envelope_cut(sid)
    if det.envelope_cut:
        log("Note end................: gate off and envelope zeroed "
            "(release nibble never sounds)")

    det.status_bit6 = _find_status_bit6(data)
    if det.status_bit6:
        det.rest_silences = _find_rest_silences(data)
        log("Pattern status bit 6....: skips operand and note (BIT/BVS)"
            + (" and silences the voice" if det.rest_silences else ""))

    (det.effect_rise, det.effect_arp, det.effect_drum,
     det.effect_pulse_lo, det.arp_fixed_up) = _find_effect_routines(sid, det)
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

    # Consulted whatever the two above found: this engine is a *branch* of the
    # same routine as the accumulate one in 19 of its 24 files, so finding that
    # one is no reason to stop looking, and in the other five it stands alone.
    if det.pulse_bounds < 0:
        (det.pulse_tri_lo, det.pulse_tri_hi,
         det.pulse_tri_gated) = _find_pulse_tri(sid, det)
        if det.pulse_tri_hi >= 0:
            log(f"Pulse-width triangle....: turns at ${det.pulse_tri_lo:X}00 "
                f"and ${det.pulse_tri_hi:X}00, rate at record +6 "
                f"(step & $E0, delay & $1F)"
                + ("" if det.pulse_tri_gated
                   else " -- every record, no bit $08 test"))

    det.track_fd_ends, det.track_fe_command = _find_track_terminators(sid)
    if det.track_fd_ends:
        log("Track reader............: $FD ends a voice's orderlist"
            + (" and $FE nn is a two-byte tempo command"
               if det.track_fe_command else ""))

    (det.effect_two_stage, det.two_stage_wave,
     det.two_stage_frames) = _find_two_stage(sid, det)
    if det.effect_two_stage:
        log("Instrument effect byte..: two-stage waveform (bit $04 is not "
            "an arpeggio in this player)")
        _bound_instruments(det, log)

    det.wave_alternate = _find_wave_alternate(sid, det)
    if det.wave_alternate >= 0:
        log("Instrument effect byte..: bit $02 alternates the waveform every "
            "frame with a second table (not the rise)")
    else:
        found = _effect_byte_address(sid, det)
        if found:
            addr, zp = found
            ld = (f"A5 {addr:02X}" if zp
                  else f"AD {addr & 0xFF:02X} {addr >> 8:02X}")
            det.wave_alternate_noise = search_file(
                sid.data, WAVE_ALT_NOISE_SHAPE.format(load=ld)) >= 1
            if det.wave_alternate_noise:
                log("Instrument effect byte..: bit $02 alternates the "
                    "waveform every frame with noise at its own control bits "
                    "(not the rise)")
        (det.voice_two_stage_alt,
         det.voice_two_stage_frames) = _find_voice_two_stage(sid, det)
        if det.voice_two_stage_alt >= 0:
            alt = sid.data[det.voice_two_stage_alt:
                           det.voice_two_stage_alt + VOICES]
            fr = sid.data[det.voice_two_stage_frames:
                          det.voice_two_stage_frames + VOICES]
            log("Instrument effect byte..: bit $02 is a two-stage attack with "
                "per-VOICE parameters -- waveform "
                + "/".join(f"${b:02X}" for b in alt)
                + " for " + "/".join(str(b) for b in fr) + " frames")

    # Bit $01's per-voice alternation. Outside the `else` above because it is
    # a different bit: a file can carry the bit-$02 reading and this one, and
    # Ninja carries both.
    det.voice_wave_alternate = _find_voice_wave_alternate(sid, det)
    if det.voice_wave_alternate >= 0:
        alt = sid.data[det.voice_wave_alternate:
                       det.voice_wave_alternate + VOICES]
        log("Instrument effect byte..: bit $01 alternates the waveform every "
            "call with a per-VOICE table -- "
            + "/".join(f"${b:02X}" for b in alt) + " (not the drum)")

    det.effect_bit80, det.effect_program = _find_effect_bit80(sid, det)
    if det.effect_bit80 == "sfx":
        det.sfx_pitch, det.sfx_voice, det.sfx_period = _find_sfx_drum(sid, det)
        if det.sfx_pitch >= 0:
            log(f"Instrument effect byte..: bit $80 is a fixed-pitch drum on "
                f"voice {det.sfx_voice + 1} -- noise at frequency high "
                f"${det.sfx_pitch:02X}xx"
                + (f", every {det.sfx_period} frames" if det.sfx_period
                   else "") + " (read, not written)")
        else:
            log("Instrument effect byte..: bit $80 writes voice 3 and the "
                "volume, in a shape this reader does not recognise -- not "
                "converted")
    elif det.effect_bit80 == "program":
        where = (f"file +0x{det.effect_program:04X}"
                 if det.effect_program >= 0 else "an unresolvable address")
        log(f"Instrument effect byte..: bit $80 selects a byte-code wave "
            f"program, pointers at {where} (read, not written)")
    elif det.effect_bit80 == "pitch":
        log("Instrument effect byte..: bit $80 steps the frequency from a "
            "duration/delta table (read, not written)")

    det.wave_program, det.wave_program_gate = find_wave_program(sid)
    if det.wave_program >= 0:
        where = (f"effect bit ${det.wave_program_gate:02X}"
                 if det.wave_program_gate else "an unrecognised gate")
        log(f"Instrument wave program.: byte-code, pointers at file "
            f"+0x{det.wave_program:04X}, selected by {where} "
            f"(read, not written)")

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


def _burst_cutoff_start(data: bytes, cutoff_var: int) -> int:
    """The `LDA #imm` feeding cutoff,X through a run of same-mode STAs, or -1.

    9 of the 95 corpus files (Lightforce, After_8, Rikky, Dragons_Lair_Part_II,
    Sanxion, Knucklebusters and three more) clear several per-voice arrays with
    one `LDA #imm` and a *run* of consecutive `STA arr,X` -- the cutoff
    accumulator among them -- rather than a dedicated load of its own:

        A9 00        LDA #$00
        9D EF F5     STA $F5EF,X
        9D FF F5     STA $F5FF,X
        9D 02 F6     STA $F602,X
        9D 05 F6     STA $F605,X   <- cutoff_var, the 4th STA in the run

    FILTER_CUTOFF_SHAPES only matches a `LDA #imm` immediately followed by ONE
    `STA`, so it can never see this. This walks backward from a `STA
    cutoff_var,X` (or the absolute `8D` form) through an unbroken run of
    same-opcode `STA`s to the `LDA #imm` that feeds them all -- confirmed
    identical (`LDA #$00`) on every one of the 9 files checked. Skips a `STA`
    immediately preceded by `CLC`/`ADC` -- the sweep routine's own read-modify-
    write of the accumulator, not an initialisation.
    """
    lo, hi = cutoff_var & 0xFF, cutoff_var >> 8
    for j in range(len(data) - 3):
        op = data[j]
        if op not in (0x9D, 0x8D):
            continue
        if data[j + 1] != lo or data[j + 2] != hi:
            continue
        if j >= 4 and data[j - 4] == 0x18 and data[j - 3] == 0x79:
            continue                      # CLC / ADC step,Y -- the sweep itself
        k = j
        while k - 3 >= 0 and data[k - 3] == op:
            k -= 3
        if k - 2 >= 0 and data[k - 2] == 0xA9:
            return data[k - 1]
    return -1

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
        cutoff = _burst_cutoff_start(data, cutoff_var)
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

# The two stores are the only thing that varies across the family. 56 files
# keep the bound in `STA abs,X` and the shift in `STA abs`; five reach the same
# two cells in zero page, which is one byte shorter for the indexed store and
# so misses the shape above by a single addressing mode:
#
#     W_A_R $E642   48 29 78 4A 4A 4A 95 D3 68 29 07 8D FE E8
#     canonical     48 29 78 4A 4A 4A 9D ?? ?? 68 29 07 8D ?? ??
#                                      ^^ STA $D3,X, not STA abs,X
#
# Same PHA/mask/LSR/PLA/mask structure, same $78 and $07, same `LDA record+5,Y`
# feeding it -- so these are one routine in three addressing dialects, not
# three signatures. Ordered canonical-first, which keeps every file that
# already read correctly on exactly the byte pattern it always matched.
VIBRATO_SHAPE_ZP_BOUND = "48 29 78 4A 4A 4A 95 ?? 68 29 07 8D ?? ??"
VIBRATO_SHAPE_ZP_BOTH = "48 29 78 4A 4A 4A 95 ?? 68 29 07 85 ??"
VIBRATO_SHAPES = (VIBRATO_SHAPE, VIBRATO_SHAPE_ZP_BOUND, VIBRATO_SHAPE_ZP_BOTH)

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
    than assumed: it is +5 in every file that has the routine and resolves, and
    a file whose addressing this does not recognise returns None and gets no
    vibrato -- an under-read, never a wrong one, the same rule find_relocation
    and the instrument-index shape follow.

    The operand is resolved through `sid.to_offset` rather than against the
    table's load-space address, because a file that relocates part of itself at
    init names its instrument table in the *relocated* space. I, Ball copies
    $9000-$9FFF to $E000 and its vibrato reads `$E710`, which against the
    load-space table at `$970B` is an offset of 20485 and gets rejected;
    resolved through the relocation it is the same +5 as everywhere else. For a
    file with no relocation -- or any address that already resolves -- this is
    algebraically what it always was, so no other file can move.
    """
    data = sid.data
    at = -1
    for shape in VIBRATO_SHAPES:
        at = search_file(data, shape)
        if at >= 1:
            break
    if at < 1:
        return None
    if not any(search_file(data, s) >= 1 for s in VIBRATO_DEPTH_SHAPES):
        return None
    for k in range(at - 3, max(0, at - 26), -1):
        if data[k] in (0xB9, 0xBD):     # LDA abs,Y / LDA abs,X
            off = sid.to_offset(data[k + 1] | data[k + 2] << 8) - det.instr_start
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
# --- The global-triangle vibrato -------------------------------------------
#
# A third form again, and the widest: one routine assembled unchanged into 25
# corpus files. It has neither the $78/$07 pair nor an LFO table. One_Man_and_
# his_Droid $11A0, with the whole effect being
#
#     frequency = note + phase x (semitone_at_note >> (record+5 + 1))
#
#     11A0  B9 8D 15  LDA record+5,Y
#           8D 00 15  STA shiftctr
#           F0 6F     BEQ past          ; zero -> no vibrato
#           AD 1C 15  LDA $151C         ; the GLOBAL oscillator counter
#           29 07     AND #$07
#           C9 04     CMP #$04
#           90 02     BCC +2
#           49 07     EOR #$07          ; -> 0,1,2,3,3,2,1,0
#           ...       (semitone interval at the note)
#     11C8  4A / 6E / CE / 10 F7        ; shift it right (record+5 + 1) times
#           ...       add the step `phase` times, then STA $D400/$D401
#
# Two things make it its own dialect rather than a variant. The period is
# **fixed**: `$151C` is incremented at the play routine's own entry point,
# unconditionally, and only three bits are used -- eight calls a cycle for
# every tune and every instrument. And the record byte is a bare shift count,
# so reading it through the $78/$07 split is not lossy but *wrong*: the six
# vibrato records in One_Man_and_his_Droid all hold 2, which that split reads
# as bound 0, i.e. no oscillation at all.
#
# The signature is one contiguous run from the triangle fold through the shift
# loop, operands wildcarded. It matches 25 files, every one of them a file the
# two shapes above find nothing in, and none that they do -- a clean partition,
# so it cannot disturb a file that already reads correctly.
TRIANGLE_VIBRATO_SHAPE = (
    "29 07 C9 04 90 02 49 07 8D ?? ?? BD ?? ?? 0A A8 38 "
    "B9 ?? ?? F9 ?? ?? 8D ?? ?? B9 ?? ?? F9 ?? ?? 4A 6E ?? ?? CE ?? ?? 10 F7")

# `LDA record+n,Y / STA abs / BEQ` -- the enable test whose operand names the
# byte. Read rather than assumed, the same way _find_vibrato reads its own; it
# comes out +5 in all 25.
TRIANGLE_VIBRATO_ENABLE = (0xB9, 0x8D, 0xF0)

# Play calls per full cycle: `AND #$07` over a counter stepped once per call,
# folded to 0,1,2,3,3,2,1,0.
TRIANGLE_VIBRATO_PERIOD = 8
# Peak of that triangle, so the excursion is `PEAK * (interval >> (n + 1))`.
TRIANGLE_VIBRATO_PEAK = 3
# A shift this large drives the 16-bit interval to zero, which is the player's
# own way of saying "no vibrato on this record" -- Last_V8 stores 81 and
# Human_Race 119, and no player in the family masks the byte.
TRIANGLE_VIBRATO_MAX_SHIFT = 15

# The gate: `LDA $14EF,X / AND #$1F / CMP #$08 / BCC out`. `$14EF,X` is the
# note's raw pattern status byte, stored once per note at $10A2
# (`LDA ($FD),Y / STA $14EF,X`) and never stepped, so `& $1F` is the note's
# *duration* and this is a length threshold, not a countdown: a note shorter
# than 8 of the player's frames gets no vibrato at all. See
# goatwriter._vibrato_delay for what Goattracker can and cannot express of it.
TRIANGLE_VIBRATO_GATE = 8


def _find_triangle_vibrato(sid: SidFile, det: Detection) -> Optional[int]:
    """Instrument-record offset of the shift-count byte, or None.

    Consulted only where `_find_vibrato` and `_find_table_vibrato` found
    nothing, so it can rescue a file that reads no vibrato and can never
    disturb one that reads correctly -- the same rule find_relocation and the
    instrument-index shape follow.
    """
    data = sid.data
    at = search_file(data, TRIANGLE_VIBRATO_SHAPE)
    if at < 1:
        return None
    lda, sta, beq = TRIANGLE_VIBRATO_ENABLE
    for k in range(at - 1, max(0, at - 48), -1):
        if data[k] == lda and data[k + 3] == sta and data[k + 6] == beq:
            off = sid.to_offset(data[k + 1] | data[k + 2] << 8) - det.instr_start
            if 0 <= off < det.instr_stride:
                return off
            return None
    return None


# The BVS lands at the DEC past both INY/LDA pairs, whatever bit 7 says --
# so a status byte of $C0-$FE consumes nothing but itself, where a decoder
# that honours bit 7 first reads an operand and a note it never read and
# desynchronises the rest of the pattern. 61 of 95 corpus files have this
# shape; the rest (the digi and cmdtable engines among them) fetch
# differently and are not touched by the flag this gates.
STATUS_BIT6_SHAPE = "B1 ?? 9D ?? ?? 8D ?? ?? 29 1F 9D ?? ?? 2C ?? ?? 70"


# Clearing the gate and then writing 0 to *both* envelope registers -- how the
# classic players end an untied note. Commando $518B:
#
#     518B  BD F8 54  LDA wave,X
#     518E  29 FE     AND #$FE      ; drop the gate bit
#     5190  99 04 D4  STA $D404,Y
#     5193  A9 00     LDA #$00
#     5195  99 05 D4  STA $D405,Y   ; attack/decay = 0
#     5198  99 06 D4  STA $D406,Y   ; sustain/release = 0
#
# reached from $517F when the note's status bit 5 is clear and the row counter
# has run out. The envelope is destroyed, so the note stops dead and the
# record's release nibble never sounds -- see goatwriter's `cut_release`.
#
# The gate-clear has to be part of the shape. `A9 00 / STA $D405 / STA $D406`
# on its own also matches an init routine clearing the chip at startup, which
# says nothing about how notes end; it appears in 9 further files that this
# does not claim.
# Effect bit $40 is tested with `BIT cell / BVC`, not `AND #$40` -- the 6502
# idiom for bit 6, the same one STATUS_BIT6_SHAPE relies on for a pattern byte.
# That is why every scan for the bit missed it: this converter's effect-bit
# detection looks for `AND #$xx`.
#
# The cell is identified rather than assumed: it is the address the player tests
# with at least two of the bit masks whose meaning is already known, which is
# what makes it the effect byte's copy and not some other flag word.
EFFECT_KNOWN_MASKS = (0x01, 0x02, 0x04, 0x08, 0x10)
EFFECT_BIT40_MASK = 0x40


def _effect_cells(data: bytes) -> dict:
    """{address: set of masks} for every `LDA addr / AND #imm` on a bit mask."""
    out: dict = {}
    for i in range(len(data) - 5):
        op = data[i]
        if op in (0xAD, 0xBD, 0xB9) and data[i + 3] == 0x29:
            addr, mask = data[i + 1] | (data[i + 2] << 8), data[i + 4]
        elif op in (0xA5, 0xB5) and data[i + 2] == 0x29:
            addr, mask = data[i + 1], data[i + 3]
        else:
            continue
        if mask and not mask & (mask - 1):          # a single bit
            out.setdefault(addr, set()).add(mask)
    return out


def _find_effect_bit40(sid: SidFile) -> bool:
    """Whether this player reads effect bit $40 (41 of 95 corpus files).

    Its body writes both halves of the voice frequency from the player's own
    note table while a countdown runs -- a fixed pitch for the attack, sharing
    its counter with bit $04's attack *waveform*. See goatwriter's
    `_two_stage_entries` and H2G-CONVERSION-METHOD.md section 7.qqq.
    """
    data = sid.data
    for addr, masks in _effect_cells(data).items():
        if len(masks & set(EFFECT_KNOWN_MASKS)) < 2:
            continue
        lo, hi = addr & 0xFF, (addr >> 8) & 0xFF
        for i in range(len(data) - 4):
            if (data[i] == 0x2C and data[i + 1] == lo and data[i + 2] == hi
                    and data[i + 3] in (0x50, 0x70)):
                return True
    return False


@dataclass
class PitchSeq:
    """Effect bit $10: `note = played note + seq[phase]`, in semitones.

    Read at Trans-Atlantic $0BBB, and the shape is in 34 of 95 corpus files --
    as widespread as the two-stage attack:

        LDA effect / AND #$10 / BEQ out
        LDA index,Y / ASL / TAY          ; the record's own byte, doubled
        LDA pairs,Y   / STA base+1       ; copy this instrument's two offsets
        LDA pairs+1,Y / STA base+2
        LDY phase                        ; a GLOBAL counter, not per note
        CLC / LDA note,X / ADC base,Y    ; the played note plus this step
        ASL / TAY / LDA freqtbl,Y ...    ; and out through the note table

    So `seq[0]` is the byte at `base`, which nothing ever writes -- 0 in every
    file checked, i.e. "the played note" -- and `seq[1]`/`seq[2]` are the
    instrument's own pair. Trans-Atlantic's records 0 and 3 both hold `18 00`:
    the note, two octaves up, the note, on a three-frame cycle. That is 1175 and
    637 of the original's pitch reversals, against 31 and 16 in a conversion that
    emitted none of it.

    `index` is the same array `wave_program` names and `_fixed_attack_note`
    reads -- a pointer low byte under bit $08, a note index under $40 and a
    sequence index under $10. One cell, three meanings, chosen by the bit.

    The phase is global and a Goattracker wavetable always restarts at the note,
    so the emitted arpeggio's phase can sit up to `steps - 1` frames off the
    player's. On a three-frame cycle that is inaudible; it is recorded because it
    is a real difference and not a rounding.
    """

    index: int                  # offset of the per-instrument index array
    pairs: int                  # offset of the pair table, indexed by 2 x index
    base: int                   # offset of seq[0]; seq[1..] follow it
    steps: int = 3


PITCH_SEQ_SHAPE = ("29 10 F0 ?? B9 ?? ?? 0A A8 B9 ?? ?? 8D ?? ?? B9 ?? ?? "
                   "8D ?? ?? AC ?? ?? 18 BD ?? ?? 79 ?? ?? 0A A8")
PITCH_SEQ_AT_INDEX = 5          # operand offsets within the shape
PITCH_SEQ_AT_PAIRS = 10
PITCH_SEQ_AT_PHASE = 22
PITCH_SEQ_AT_BASE = 29
PITCH_SEQ_STEPS = 3             # the default when the reload cannot be read


def _find_pitch_seq(sid: SidFile) -> Optional[PitchSeq]:
    """The bit-$10 arpeggio's three tables, or None."""
    data = sid.data
    at = search_file(data, PITCH_SEQ_SHAPE)
    if at < 1:
        return None

    def operand(k: int) -> int:
        return data[at + k] | (data[at + k + 1] << 8)

    phase = operand(PITCH_SEQ_AT_PHASE)
    # `DEC phase / BPL + / LDA #steps-1 / STA phase` closes the play routine, so
    # the immediate is one less than the cycle length. Read rather than assumed;
    # the constant only stands in where the reload is not found.
    steps = PITCH_SEQ_STEPS
    lo, hi = phase & 0xFF, (phase >> 8) & 0xFF
    for i in range(len(data) - 9):
        if (data[i] == 0xCE and data[i + 1] == lo and data[i + 2] == hi
                and data[i + 3] == 0x10 and data[i + 5] == 0xA9
                and data[i + 7] == 0x8D and data[i + 8] == lo):
            steps = data[i + 6] + 1
            break
    seq = PitchSeq(index=sid.to_offset(operand(PITCH_SEQ_AT_INDEX)),
                   pairs=sid.to_offset(operand(PITCH_SEQ_AT_PAIRS)),
                   base=sid.to_offset(operand(PITCH_SEQ_AT_BASE)),
                   steps=max(2, steps))
    if min(seq.index, seq.pairs, seq.base) < 0:
        return None
    return seq


ENVELOPE_CUT_SHAPES = (
    "29 FE 99 04 D4 A9 00 99 05 D4 99 06 D4",
    "29 FE 9D 04 D4 A9 00 9D 05 D4 9D 06 D4",
)


def find_envelope_cut(sid: SidFile) -> bool:
    """Whether this player zeroes AD and SR when a note ends (33 files)."""
    return any(search_file(sid.data, sh) >= 1 for sh in ENVELOPE_CUT_SHAPES)


# `LDA duration,X / AND #$1F / CMP #imm / BCC out` -- the per-note length gate
# in front of the global-triangle oscillator. It sits at a fixed +56 bytes from
# TRIANGLE_VIBRATO_SHAPE's match in all 25 corpus files that have the engine,
# which is why this reads one place rather than scanning: each player has a
# *second* gate on the same duration cell 377 bytes further on, guarding an
# unrelated effect, and a scan picks up whichever comes first.
TRIANGLE_GATE_SHAPE = "BD ?? ?? 29 1F C9 ?? 90"
TRIANGLE_GATE_DELTA = 56
TRIANGLE_GATE_IMMEDIATE = 6       # offset of the CMP operand within the shape


def _find_triangle_gate(sid: SidFile, at: int) -> Optional[int]:
    """The threshold `CMP #imm` this player compares the note duration against.

    `TRIANGLE_VIBRATO_GATE` was read from one file and is right for 20 of the
    25: the other five compare against 6 (Commando), 5, 4, 4 and 2. Commando's
    matters most, because assuming 8 there gated the vibrato onto notes of 8
    stored units where the player wants 6 -- and 6 is checkable against the
    trace, since it selects exactly the 31 notes of GT 1 the original is
    measured to vibrate.

    Read at the fixed delta rather than searched for; see TRIANGLE_GATE_SHAPE.
    """
    if at < 1:
        return None
    k = at + TRIANGLE_GATE_DELTA
    if match_at(sid.data, k, TRIANGLE_GATE_SHAPE):
        return sid.data[k + TRIANGLE_GATE_IMMEDIATE]
    return None


def _search_all(data: bytes, pattern: str, limit: int = 8):
    """Every offset `pattern` matches, not just the first."""
    out, at = [], 0
    while len(out) < limit:
        i = search_file(data[at:], pattern)
        if i <= -1:
            break
        out.append(at + i)
        at += i + 1
    return out


def _nearest_table(data: bytes, shape: str, pattern_lo: int,
                   sid: SidFile) -> int:
    """The address `shape` names whose table sits nearest the patterns, or -1.

    Only meaningful where the shape matches more than once, which on this
    corpus means a file carrying two copies of one player. See the call site.
    """
    if pattern_lo < 0 or not shape:
        return -1
    hits = _search_all(data, shape)
    if len(hits) < 2:
        return -1
    best, dist = -1, None
    for i in hits:
        addr = _addr16(data, i + 1, i + 2)
        off = sid.to_offset(addr)
        if not 0 <= off < len(data):
            continue
        d = abs(off - pattern_lo)
        if dist is None or d < dist:
            best, dist = addr, d
    return best


def _find_status_bit6(data: bytes) -> bool:
    return search_file(data, STATUS_BIT6_SHAPE) >= 1


# How far into the bit-6 branch to look for the silencing write. IK+'s is 13
# bytes in, behind a `LDY voice` and a two-cell zeroing; Ricochet's is 6.
REST_SILENCE_WINDOW = 24


def _find_rest_silences(data: bytes) -> bool:
    """Whether a bit-6 rest cuts the voice or merely holds it.

    Our decoder emits a hold row for such an event, which sustains the note
    that was playing. That is right for 40 of the 61 files with the shape --
    Commando's branch target goes straight on to the effect path and touches
    no register. The other 21 silence, in two different ways, and the branch
    target says which:

        914A  DEC .. / LDY voice / LDA #$00 / STA $D406,Y / STA $D405,Y
                                                        (Ricochet, 4 files)
        E138  LDY voice / LDA #$00 / STA .. / STA .. / LDA #$08 / JMP store
                                                        (IK+, 17 files)

    The first zeroes the envelope pair, the second writes the testbit into the
    voice's stored waveform. Both stop the sound; both are a Goattracker
    `KEYOFF`, which is the only row this format has that ends a note without
    starting one.

    **What the probe does not follow** is IK+'s `JMP` -- the `$08` is loaded
    in the rest path and stored one jump away, which was read by hand on that
    file rather than by this function. `#$08` is the testbit constant and it
    appears in no other reachable role here, but the honest statement is that
    this recognises the *load*, not the store.

    **And it is no longer a gate on anything.** v0.5.269 emitted the rest's
    `KEYOFF` only where this returned True, on the reading that the other 40
    players "really do hold". That was a reading of the *branch*: those
    players release the voice across the rest anyway, by the ordinary
    end-of-note path. Measured on the `gate` column over all 40, keying off
    regardless is **26 up, 0 down, 14 unchanged** with `melody` and `retrig`
    unmoved on every one. This stays because the distinction is real and
    worth logging -- one family cuts the sound in the branch, the other a
    frame earlier -- but nothing depends on it.
    """
    i = search_file(data, STATUS_BIT6_SHAPE)
    if i <= -1:
        return False
    at = i + len(STATUS_BIT6_SHAPE.split())     # the BVS's own operand
    if at >= len(data):
        return False
    rel = data[at] - 256 if data[at] > 127 else data[at]
    target = at + 1 + rel
    if not 0 <= target < len(data):
        return False
    window = data[target:target + REST_SILENCE_WINDOW]
    if b"\xa9\x08" in window:                   # LDA #$08, the testbit
        return True
    # LDA #$00 into the envelope pair: `STA $D405,Y` / `STA $D406,Y`.
    return (b"\xa9\x00" in window
            and (b"\x99\x05\xd4" in window or b"\x99\x06\xd4" in window))


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
    """(address, is_zeropage) the player keeps instrument byte +7 in, or None.

    **No stride condition.** This probed `instr_stride == 8` until v0.5.236,
    which silently switched off *every* effect-byte routine -- the two-stage
    attack, bit $02's alternation, bit $40's pitch, the whole family that reads
    +7 -- for the 9 corpus files whose records are 16 bytes. The address it
    computes is record 0's `+7` and the search is for the player's own
    `LDA base,Y`; neither depends on how far apart the records are, so the
    guard excluded a dialect rather than an error. It was the census's largest
    remaining group: `$04` x11 across five of those nine, whose block is
    `TWO_STAGE_SHAPE` byte for byte.
    """
    if det.instr_start < 0:
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
        return False, False, False, False, 0
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    any_load = "A5 ??" if zp else "AD ?? ??"
    rise = search_file(
        sid.data, f"{load} 29 02 F0 ?? {any_load} 29 03 D0 ?? FE") >= 1
    arp = search_file(
        sid.data, f"{load} 29 04 F0 ?? {load} 4A 4A 4A 4A 8D") >= 1
    # A second arpeggio dialect, and the reason 12 corpus files arpeggiate
    # with nothing emitted for them. It takes no interval from the record at
    # all -- the alternate note is a hardcoded `ADC #$0C`, an octave *up*,
    # where the nibble form subtracts. Commando $535E:
    #
    #     535E  AD 23 55  LDA effect
    #           29 04     AND #$04 / BEQ out
    #           AD 25 55  LDA $5525    ; the play routine's own frame counter,
    #           29 01     AND #$01     ; INC'd at its entry point, so this
    #           F0 ??     BEQ even     ; alternates every call
    #           BD FB 54  LDA note,X
    #           18 69 0C  CLC / ADC #$0C
    #
    # Because the interval is in the code and not the record, the high nibble
    # says nothing here -- which is why the nibble rule ("a zero nibble means
    # both halves play the same note") reads these files as having no
    # arpeggio at all. The VB6 original's flat +12 substitution was right for
    # *this* dialect and wrong for the other; h2g had it the other way round.
    arp_up = 0
    at = search_file(
        sid.data,
        f"{load} 29 04 F0 ?? AD ?? ?? 29 01 F0 ?? BD ?? ?? 18 69 ??")
    if at >= 1 and at + 19 < len(sid.data):
        arp_up = sid.data[at + 19]      # the ADC operand: semitones up
        arp = arp = True
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
    return rise, arp, drum, pulse_lo, arp_up


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


# The triangle sweep, in full, because every field this converter needs is an
# operand of it (Commando $524B, and 23 more files byte-for-byte apart from
# the operands):
#
#     524B  AD 07 55  LDA rate       ; self-modified from record +6 at note fetch
#     524E  F0 62     BEQ done
#     5250  AC 18 55  LDY instidx
#     5253  29 1F     AND #$1F       ; low five bits: frames between steps
#     5255  DE 0D 55  DEC counter,X  ; per VOICE
#     5258  10 58     BPL done
#     525A  9D 0D 55  STA counter,X  ; reload -- so the period is (rate&$1F)+1
#     525D  AD 07 55  LDA rate
#     5260  29 E0     AND #$E0       ; high three bits: the step itself
#     5262  8D 24 55  STA step
#     5265  BD 10 55  LDA dir,X
#     5268  D0 1A     BNE descend
#     526A  AD 24 55  LDA step
#     526D  18        CLC
#     526E  79 91 55  ADC record,Y   ; +0 is the running low byte...
#     5271  48        PHA
#     5272  B9 92 55  LDA record+1,Y ; ...and +1 the running high nibble
#     5275  69 00     ADC #$00
#     5277  29 0F     AND #$0F
#     5279  48        PHA
#     527A  C9 0E     CMP #$0E       ; the upper turnaround, an operand
#     527C  D0 1D     BNE write
#     527E  FE 10 55  INC dir,X
#     ...             descend: the same with SBC, ending CMP #$08
#
# Two things follow that no other engine in this player family does. The width
# is kept *in the instrument record*, so it is shared by every voice sounding
# that instrument and drifts for the rest of the tune; and nothing reseeds it
# at note start, so the sweep free-runs across notes. Goattracker restarts a
# pulse program whenever its instrument is triggered (gplay.c:375-379), so the
# free running is the one part of this that cannot be carried over.
PULSE_TRI_SHAPE = (
    "29 1F DE ?? ?? 10 ?? 9D ?? ?? AD ?? ?? 29 E0 8D ?? ?? "
    "BD ?? ?? D0 ?? AD ?? ?? 18 79 ?? ?? 48 B9 ?? ?? 69 00 29 0F 48 C9 ?? "
    "D0 ?? FE ?? ?? 4C ?? ?? 38 B9 ?? ?? ED ?? ?? 48 B9 ?? ?? E9 00 29 0F "
    "48 C9 ??")
_TRI_BASE = 28      # operand of the ADC record,Y that names the instrument table
_TRI_HI = 40        # operand of CMP #hi
_TRI_LO = 66        # operand of CMP #lo
# The routine is entered eight bytes above the match, at `LDA rate / BEQ /
# LDY idx`; a BEQ landing there is the effect-bit-$08 test that chooses between
# this engine and the accumulate one.
_TRI_ENTRY = 8


def _find_pulse_tri(sid: SidFile, det: Detection) -> tuple[int, int, bool]:
    """(low nibble, high nibble, gated on bit $08) for the triangle, or -1s.

    Both bounds come out of the routine's own CMP operands. They are $08 and
    $0E in all 24 corpus files that carry this engine, which is exactly why
    they are read rather than written down here -- a constant that holds
    everywhere is indistinguishable from one nobody checked.

    Anchored the way `_find_pulse_lo` is: the block must be indexing the
    instrument table this detection already found. A signature this long
    matching something else is unlikely, but "unlikely" is not the standard the
    rest of this file holds itself to, and the operand is right there.
    """
    off = search_file(sid.data, PULSE_TRI_SHAPE)
    if off < 0:
        return -1, -1, False
    d = sid.data
    base = d[off + _TRI_BASE] | (d[off + _TRI_BASE + 1] << 8)
    if sid.to_offset(base) != det.instr_start:
        return -1, -1, False
    lo, hi = d[off + _TRI_LO] & 0x0F, d[off + _TRI_HI] & 0x0F
    if hi <= lo:
        return -1, -1, False
    entry = off - _TRI_ENTRY
    gated = any(d[k] == 0x29 and d[k + 1] == 0x08 and d[k + 2] == 0xF0
                and k + 4 + d[k + 3] == entry
                for k in range(max(0, off - 64), entry))
    return lo, hi, gated


# A per-instrument BYTE-CODE WAVE PROGRAM, and the most widespread instrument
# mechanism this project has found unread: **29 of the 95 corpus files**. It was
# known in two of them (ACE II and Auf Wiedersehen Monty, as `effect_bit80
# == "program"`); the other 27 include the file whose snare a listener reported
# missing.
#
# The interpreter, Trans-Atlantic $0B4E (the operands differ; the shape does
# not):
#
#     0B4E  B9 6B 11  LDA ptrs,Y      ; Y = i * stride -- 16-bit per instrument
#     0B51  85 F0     STA $F0
#     0B53  B9 6C 11  LDA ptrs+1,Y
#     0B56  85 F1     STA $F1
#     0B58  BD 4D 10  LDA pc,X        ; per-VOICE program counter
#     0B5B  A8        TAY
#     0B5C  B1 F0     LDA ($F0),Y     ; fetch an opcode
#     0B5E  10 1E     BPL threebyte   ; < $80
#     0B60  C9 85     CMP #$85
#     0B62  D0 03     BNE twobyte
#     0B64  4C 60 0C  JMP done        ; $85 -- HOLD, the counter does not move
#
# Three opcodes, and nothing else:
#
#     $85          hold here for the rest of the note (the program's end)
#     >= $80       2 bytes: waveform -> $D404, then frequency HIGH -> $D401.
#                  Both written *directly*, bypassing the normal path, so the
#                  pitch is absolute and has nothing to do with the note.
#     < $80        3 bytes: waveform, then a 16-bit value SUBTRACTED from the
#                  voice's frequency accumulator (`SEC / LDA lo,X / SBC (ptr),Y
#                  / STA lo,X` then the high byte with the borrow). A downward
#                  pitch slide, per step.
#
# Trans-Atlantic's GT 3 -- the snare -- is `81 30 | 10 00 02 | 40 C0 03 |
# 80 30 | 80 15 | 80 20 | ...`: noise at $30xx, then two slides down under a
# released triangle and pulse, then three more noise pitches. Its first two
# bytes are literally "noise at $30xx", which is the 43 onsets the trace shows
# on voice 2 and which no conversion has ever emitted.
#
# The gating bit is the test *immediately* above the pointer load, and reading
# it needs that anchor. A first attempt scanned 40 bytes back from the fetch for
# any `AND #$xx / BEQ` and returned $01 for 21 of the 29 files, which looked
# like the drum bit in the other dialect and was dismissed as a wrong match. It
# was not wrong -- it was under-anchored, and $01 really is the gate in 13 of
# them. In *these* players effect bit $01 selects a wave program, where in
# Warhawk's dialect it means a drum; no file does both, so nothing `--effects`
# reads collides with it.
#
#     0B44  AD FB 0E  LDA effect      ; Trans-Atlantic: bit $08
#     0B47  29 08     AND #$08
#     0B49  F0 51     BEQ skip
#     0B4B  8E A2 0D  STX save
#     0B4E  B9 6B 11  LDA ptrs,Y      ; <- the anchor
#
#     E3D2  AD 7B E5  LDA effect      ; ACE II: bit $80, tested by sign
#     E3D5  10 51     BPL skip
#
# Read across the corpus: $01 in 13 files, $80 in 2 (ACE II and Monty, via
# `BPL`), $08 in 2, $20 in 1, and one shape (Mega Apocalypse) this walk does not
# recognise. Where detection independently knows the effect-byte cell -- 18 of
# the 29 -- the operand the branch tests is that same cell, which is what makes
# this the instrument's own flag rather than some other state.
WAVE_PROGRAM_FETCH = "B1 ?? 10 ?? C9 85 D0 03"
WAVE_PROGRAM_HOLD = 0x85
_WAVE_PROGRAM_SIGN_BRANCH = (0x10, 0x30)     # BPL / BMI -- the bit is $80
_WAVE_PROGRAM_BRANCH = (0x10, 0x30, 0xD0, 0xF0)


def find_wave_program(sid: SidFile) -> tuple[int, int]:
    """(pointer-array offset, gating bit) for the byte-code program, or (-1, 0).

    Anchored on the fetch rather than on any one player's operands: the
    zero-page pointer the fetch dereferences must be the same one the array is
    loaded into, which is what ties the two together across 29 of 29 files that
    carry the interpreter. The gate is then the branch immediately above that
    load, and 0 where this walk does not recognise the shape -- an unread gate
    is reported as unread, never guessed, because emitting on a wrong bit would
    invent a program for every record carrying it.

    **The store between the branch and the load may be zero page.** The walk
    stepped back a fixed three bytes for it, which is `STX abs` -- the form 28
    of the 29 use. Mega Apocalypse writes `STX $E4` (two bytes) and, one byte
    out, read no gate at all: its `LDA $EC / AND #$01 / BEQ` sits where the
    fixed step expects the middle of an operand. Both widths are tried now,
    which is a superset of the old rule and leaves the 28 unchanged. The same
    shape as `_burst_cutoff_start` (v0.5.210): a signature anchored at a fixed
    byte distance reads one dialect and silently declines the next.
    """
    off = search_file(sid.data, WAVE_PROGRAM_FETCH)
    if off < 0:
        return -1, 0
    d = sid.data
    zp = d[off + 1]
    site = -1
    for k in range(max(0, off - 40), off):
        if (d[k] == 0xB9 and k + 4 < len(d)
                and d[k + 3] == 0x85 and d[k + 4] == zp):
            site = k
    if site < 0:
        return -1, 0
    at = sid.to_offset(d[site + 1] | (d[site + 2] << 8))
    if at < 0:
        return -1, 0
    # ...past the `STX save` the block opens with, then the branch. The store
    # is three bytes absolute or two zero page, so the branch opcode sits five
    # or four bytes back; absolute is tried first because it is what 28 of the
    # 29 files carry and a two-byte step could otherwise land inside its
    # operand.
    gate = 0
    for width in (3, 2):
        q = site - width - 2                 # the branch opcode
        if q < 2 or d[q] not in _WAVE_PROGRAM_BRANCH:
            continue
        if d[q - 2] == 0x29:                 # AND #bit
            gate = d[q - 1]
        elif d[q] in _WAVE_PROGRAM_SIGN_BRANCH:
            gate = 0x80
        if gate:
            break
    return at, gate


def decode_wave_program(data: bytes, at: int, limit: int = 64) -> list:
    """The program at file offset `at` as (opcode, waveform, operand) steps.

    `opcode` is "hold", "set" (absolute frequency high) or "slide" (a 16-bit
    downward step). Stops at the hold, at `limit` steps, or at the end of the
    data -- a program is not length-prefixed, so a truncated read is the only
    alternative to trusting a byte count nothing states.
    """
    out: list = []
    i = at
    while len(out) < limit and i < len(data):
        op = data[i]
        if op == WAVE_PROGRAM_HOLD:
            out.append(("hold", 0, 0))
            return out
        if op >= 0x80:
            if i + 1 >= len(data):
                return out
            out.append(("set", op, data[i + 1]))
            i += 2
        else:
            if i + 2 >= len(data):
                return out
            out.append(("slide", op, data[i + 1] | (data[i + 2] << 8)))
            i += 3
    return out


# The "sfx" shape's payload, Trans-Atlantic $0C4A and six more files:
#
#     0C2E  AD FB 0E  LDA effect      ; the CURRENT INSTRUMENT's effect byte
#     0C31  10 2D     BPL skip        ; bit $80 clear -> nothing
#     0C33  AD AF 0F  LDA $0FAF       ; this voice's frame counter (INC $0FAD,X)
#     0C36  C9 01     CMP #$01
#     0C38  F0 10     BEQ fire
#     ...   C9 06     CMP #$06        ; ...and the counter wraps here
#     0C4A  A9 38     LDA #$38
#     0C4C  8D 0F D4  STA $D40F       ; frequency HIGH -- a constant, not the note
#     0C4F  A9 81     LDA #$81
#     0C51  8D 12 D4  STA $D412       ; ...and noise
#     0C54  A9 50     LDA #$50 / STA $D416
#     0C59  A9 2F     LDA #$2F / STA $D418
#
# **This is a drum, and it is music.** It was read as the game's own sound
# effect and left unconverted on the grounds that it keys off global state; the
# gate is the instrument's effect byte -- the very cell `_effect_byte_address`
# locates -- and `$0FAF` is not global, it is `$0FAD,X` for the third voice.
# Seven of the nine files classified "sfx" carry this block byte for byte apart
# from the pitch, which is $48 in six of them and $38 in Trans-Atlantic.
#
# It matters because the noise is at a *fixed* pitch. Trans-Atlantic's traces
# read `41 05CE / 81 38CE / 81 15EB / 41 05CE` -- the note, then two frames of
# noise an octave and a half above it, then the note again. A conversion that
# sounds noise at the note's own $05CE writes the register and makes no sound:
# the SID's noise is an LFSR clocked by the frequency, so pitch is not a
# refinement here, it is the difference between a drum and silence.
SFX_DRUM_SHAPE = "A9 ?? 8D ?? D4 A9 81 8D ?? D4"


def _find_sfx_drum(sid: SidFile, det: Detection) -> tuple[int, int, int]:
    """(frequency high byte, voice, frames between hits) for the bit-$80 drum.

    (-1, -1, -1) unless the block is found *and* its two stores name the
    frequency-high and control registers of one and the same voice -- the check
    that makes this a reading rather than a pattern that happens to match.
    """
    off = search_file(sid.data, SFX_DRUM_SHAPE)
    if off < 0:
        return -1, -1, -1
    d = sid.data
    freq_reg, ctrl_reg = d[off + 3], d[off + 8]
    # $D401 + 7v is the frequency high byte, $D404 + 7v the control register.
    if (freq_reg - 0x01) % 7 or (ctrl_reg - 0x04) % 7:
        return -1, -1, -1
    voice = (freq_reg - 0x01) // 7
    if voice != (ctrl_reg - 0x04) // 7 or not 0 <= voice <= 2:
        return -1, -1, -1
    # The period is the `CMP #n` the counter wraps on, a little above the
    # `CMP #$01` that fires it. Reported as 0 rather than guessed if absent.
    period = 0
    for k in range(max(0, off - 32), off):
        if d[k] == 0xC9 and d[k + 2:k + 3] and d[k + 1] > 1:
            period = d[k + 1]
    return d[off + 1], voice, period


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
# IK+ $E38B, which 43 files share byte-for-byte in shape -- a 44th, Mega
# Apocalypse, spells the same block with its per-voice cells in zero page
# (TWO_STAGE_SHAPE_ZP below):
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
# Corpus-wide that push chain names exactly `attack + 2` in **44 files out of
# 44**. Requiring both is what makes this a reading rather than an inference:
# a player that matches the block but keeps its duration elsewhere is skipped
# instead of being given a made-up one.
TWO_STAGE_SHAPE = ("{load} 29 04 F0 ?? BD ?? ?? F0 ?? DE ?? ?? "
                   "B9 ?? ?? 4C ?? ?? B9 ?? ?? 9D ?? ??")
# Mega Apocalypse $4DDA is the same block with its three per-voice cells in
# zero page, so those instructions are a byte shorter -- `B5 E0` / `D6 E0` /
# `95 C6` where the shape above reads `BD ?? ??` / `DE ?? ??` / `9D ?? ??`.
# Nothing else moves: both `LDA table,Y` loads are still absolute and the push
# chain still names attack+2, so the file passes the same second reading every
# other member of the family does. It is the *only* corpus file this spelling
# matches and it matches none of the absolute one, which is what makes it a
# second spelling rather than a looser pattern. The attack operand sits at +11
# instead of +13, hence `attack_at` below.
TWO_STAGE_SHAPE_ZP = ("{load} 29 04 F0 ?? B5 ?? F0 ?? D6 ?? "
                      "B9 ?? ?? 4C ?? ?? B9 ?? ?? 95 ??")
# LDA instr+0,X / STA .. / PHA / LDA instr+1,X / STA .. / PHA / LDA dur,X / PHA
TWO_STAGE_PUSH = "BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48 BD ?? ?? 48"


WAVE_ALT_SHAPE = ("{load} 29 02 F0 ?? AC ?? ?? BD ?? ?? 29 01 F0 ?? "
                  "B9 ?? ?? 4C ?? ?? B9 ?? ?? 9D ?? ??")
# Hollywood or Bust $0774. Same alternation, two differences: the counter is
# global (`AD`, not `BD ..,X`) and the alternate is derived from the voice's
# own waveform -- `AND #$07 / ORA #$80`, noise keeping the control bits --
# rather than read from a table. The `STA $D404,Y` at the end is what makes it
# specific: this block writes the chip itself.
WAVE_ALT_NOISE_SHAPE = ("{load} 29 02 F0 ?? AD ?? ?? 29 01 F0 ?? "
                        "BD ?? ?? 29 07 09 80 4C ?? ?? BD ?? ?? 99 04 D4")


def _find_wave_alternate(sid: SidFile, det: Detection) -> int:
    """File offset of bit $02's alternate-waveform table, or -1.

    **Bit $02 is the rise in Warhawk's dialect and something else here.**
    W_A_R $E759, and the same block in 21 corpus files:

        E759  LDA effect / AND #$02 / BEQ out
        E760  LDY voice
        E763  LDA counter,X / AND #$01 / BEQ alt   ; a per-voice frame counter
        E76A  LDA instr+2,Y                        ; the record's own waveform
        E76D  JMP store
        E770  alt: LDA alttbl,Y                    ; the alternate
        E773  store: STA wavecell,X

    So the voice's waveform alternates every frame between the record's `+2`
    and a second per-instrument table. In all 21 files the alternate is `$81`
    -- noise with the gate on -- so what this sounds is a noise frame every
    other frame, under the note.

    **Anchored on the first operand being the records' own `+2`.** That is
    what ties the block to this instrument table rather than to any
    `AND #$02` that happens to be followed by two indexed loads; the second
    operand is then the table this returns.

    The phase is reproducible even though the counter is free-running: the
    note's first frame is spent by the init path (section 7.www), and W_A_R's
    205 onsets of instrument $0900 all read `tri tri noi tri` -- one shape,
    no distribution at all.
    """
    found = _effect_byte_address(sid, det)
    if not found or det.instr_start < 0:
        return -1
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    i = search_file(sid.data, WAVE_ALT_SHAPE.format(load=load))
    if i <= -1:
        return -1
    data = sid.data
    p = i + len(load.split())
    if p + 23 >= len(data):
        return -1
    own = data[p + 15] | data[p + 16] << 8
    alt = data[p + 21] | data[p + 22] << 8
    instr_cpu = det.instr_start - (HLEN - 1) + sid.load_addr
    if own != instr_cpu + 2:            # not this instrument table's +2
        return -1
    off = alt - instr_cpu + det.instr_start
    span = max(det.instr_used, 0) * det.instr_stride
    if not (0 <= off and off + span <= len(data)):
        return -1
    return off


# Ninja $CAFD -- bit $02 read a third way, and the first mechanism in this
# project whose parameters are per *voice*:
#
#     CAFD  LDA effect / AND #$02 / BEQ out
#     CB04  LDA counter,X        ; frames since this voice's note started
#     CB07  CMP thresh,X         ; ...against a per-voice threshold
#     CB0A  BCS +                ; past it -> the record's own waveform
#     CB0C  LDA alt,X            ; ...before it -> a per-voice alternate
#     CB0F  JMP ++
#     CB12  + LDA wave,X         ; the voice's current waveform cell
#     CB15  ++ AND mask,X / STA $D404,Y
#
# `alt` and `thresh` are three bytes each and nothing in the file writes
# either, so they are static player data: `11 81 15` and `04 06 04`. The
# indexed *compare* is what makes the block unambiguous -- `DD` reads a table
# rather than an immediate, which is what says the threshold is per voice and
# not a constant.
VOICE_TWO_STAGE_SHAPE = ("{load} 29 02 F0 ?? BD ?? ?? DD ?? ?? B0 ?? "
                         "BD ?? ?? 4C ?? ?? BD ?? ?? 3D ?? ??")
# The voices are three, so the tables are three bytes. Read as such rather
# than as `instr_used * instr_stride`: this is the one family here whose
# effect parameters are not indexed by the instrument.
VOICES = 3


def _find_voice_two_stage(sid: SidFile, det: Detection):
    """(alt table, threshold table) file offsets for bit $02, or (-1, -1).

    **Per voice, not per instrument.** Every other effect table this module
    locates is indexed by `i * instr_stride`; these two are indexed by the
    voice the player is servicing, so one instrument sounds a different attack
    on each voice it is played on. What that costs the emitter is a map from
    instrument to voice, which `patterns.instrument_voices` builds from the
    orderlists -- see `goatwriter._voice_two_stage_entries`.

    **Consulted only where `_find_wave_alternate` found nothing**, the same
    rule `find_relocation` and `INSTRUMENT_INDEX_SHAPE` follow: both read bit
    $02 and a file matching both would be ambiguous about which one the bit
    means. The shapes are in fact disjoint -- the alternation tests the
    counter's low bit with `AND #$01` where this compares the whole counter
    against a table -- so the gate has never fired; it is there so that a
    future dialect matching both is refused rather than silently given this
    reading.

    The counter's address is checked against an `INC counter,X` somewhere in
    the file. Without it `BD ?? ?? DD ?? ??` is just two indexed loads, and
    what makes this a two-stage attack rather than an arbitrary comparison is
    that the left-hand side counts frames.
    """
    found = _effect_byte_address(sid, det)
    if not found:
        return -1, -1
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    i = search_file(sid.data, VOICE_TWO_STAGE_SHAPE.format(load=load))
    if i <= -1:
        return -1, -1
    data = sid.data
    p = i + len(load.split())
    if p + 23 >= len(data):
        return -1, -1
    counter = data[p + 5] | data[p + 6] << 8
    thresh = data[p + 8] | data[p + 9] << 8
    alt = data[p + 13] | data[p + 14] << 8
    if search_file(data, "FE %02X %02X" % (counter & 0xFF, counter >> 8)) <= -1:
        return -1, -1                   # nothing increments it: not a counter
    alt_off, thresh_off = sid.to_offset(alt), sid.to_offset(thresh)
    for off in (alt_off, thresh_off):
        # Parenthesised, for the reason `_find_two_stage` spells out: without
        # the brackets this rejects only a negative offset that is also in
        # range, i.e. nothing, and lets a table past EOF through.
        if not (0 <= off and off + VOICES <= len(data)):
            return -1, -1
    return alt_off, thresh_off


# Ninja $CADD, 25 bytes above the block above and the same idea in the other
# axis: this is `wave_alternate` with a per-*voice* table.
#
#     CADD  LDA effect / AND #$01 / BEQ out
#     CAE4  LDA counter,X / AND #$01 / BEQ own   ; the per-note frame counter
#     CAEB  LDA alt,X                            ; odd  -> a per-voice alternate
#     CAEE  JMP store
#     CAF1  own: LDA wave,X                      ; even -> the voice's own
#     CAF4  store: AND mask,X / LDY voice / STA $D404,Y
#
#     alt  $CC60   81 81 81      noise, gate on
#
# **The branch runs the other way round from W_A_R's.** There `AND #$01 / BEQ`
# jumps to the alternate and falls through to the record's own; here it jumps
# to the record's own and falls through to the alternate. The counter reads 1
# on the first call that reaches the block (the note-start path skips it), so
# the note's second call sounds the *alternate* -- which is what
# `_wave_alternate_entries(alt_first=True)` encodes, and what Ninja's voice 1
# measures: `41` on the onset frame and `81` on the next.
VOICE_WAVE_ALT_SHAPE = ("{load} 29 01 F0 ?? BD ?? ?? 29 01 F0 ?? "
                        "BD ?? ?? 4C ?? ?? BD ?? ?? 3D ?? ??")


def _find_voice_wave_alternate(sid: SidFile, det: Detection) -> int:
    """File offset of bit $01's per-voice alternate table, or -1.

    The sibling of `_find_voice_two_stage`, and read on the same terms: two
    indexed loads off a per-note frame counter that something in the file
    increments, with the table three bytes long because the voices are three.

    **Consulted only where the drum block is absent.** Bit $01 is the
    percussive drum in Warhawk's dialect (`det.effect_drum`), which is a
    decoded, emitted and measured reading of the same bit; a file matching
    both would be ambiguous and the established one wins. No corpus file
    matches both -- the shapes are disjoint, this one testing the counter's
    low bit where the drum block tests nothing -- so the gate has never
    fired. It is there so a future dialect is refused rather than silently
    given this reading, the rule `_find_voice_two_stage` follows against
    `wave_alternate`.
    """
    if det.effect_drum:
        return -1
    found = _effect_byte_address(sid, det)
    if not found:
        return -1
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    i = search_file(sid.data, VOICE_WAVE_ALT_SHAPE.format(load=load))
    if i <= -1:
        return -1
    data = sid.data
    p = i + len(load.split())
    if p + 22 >= len(data):
        return -1
    counter = data[p + 5] | data[p + 6] << 8
    alt = data[p + 12] | data[p + 13] << 8
    if search_file(data, "FE %02X %02X" % (counter & 0xFF, counter >> 8)) <= -1:
        return -1                       # nothing increments it: not a counter
    off = sid.to_offset(alt)
    if not (0 <= off and off + VOICES <= len(data)):
        return -1
    return off


# The orderlist reader, anchored on the one test every dialect makes: it loads
# a byte through a zero-page pointer and compares it with `$FF`.
#
#     C094  LDY index,X / LDA (ptr),Y / CMP #$FF / BEQ stop      (Rasputin)
#
# What it tests *next* is the dialect. Three corpus files -- Knucklebusters,
# Rasputin and Tarzan -- also compare `#$FD`, and for them that byte ends the
# voice's list rather than naming pattern 253. The other version-0 players
# never mention `$FD`, and reading it as a pattern is what let a voice run
# straight on into the next voice's data.
#
# **Anchored on the reader and not on the file**, because `CMP #$FD` occurs
# somewhere in plenty of players -- the window is the 48 bytes after the `$FF`
# test, which is where a dialect's other terminators live.
TRACK_READER = re.compile(rb"\xb1(.)\xc9\xff", re.DOTALL)
TRACK_FD_TEST = b"\xc9\xfd"
# Rasputin only: `$FE nn` is a two-byte command that *continues* the list --
# `CMP #$FE / BNE + / INC index,X / INY / LDA (ptr),Y / STA .. / STA ..`, the
# operand becoming a second gate's reload, i.e. a tempo change mid-orderlist.
# Everywhere else `$FE` ends the tune, which is what `legalise_restarts` is
# for; applying Rasputin's reading to all of version 0 rewrote 23 files and
# broke the byte-exact fixture.
TRACK_FE_COMMAND = re.compile(
    rb"\xc9\xfe\xd0(.)\xfe(..)\xc8\xb1(.)\x8d(..)\x8d(..)", re.DOTALL)


def _find_track_terminators(sid: SidFile) -> tuple:
    """(does `$FD` end a list, is `$FE` a two-byte command) for this player."""
    fd = any(TRACK_FD_TEST in sid.data[m.start():m.start() + 48]
             for m in TRACK_READER.finditer(sid.data))
    return fd, bool(TRACK_FE_COMMAND.search(sid.data))


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
    attack_at = 13
    if i <= -1:
        i = search_file(sid.data, TWO_STAGE_SHAPE_ZP.format(load=load))
        attack_at = 11
    if i <= -1:
        return False, -1, -1
    data = sid.data
    p = i + len(load.split())
    if p + 20 >= len(data):
        return False, -1, -1
    attack = data[p + attack_at] | data[p + attack_at + 1] << 8

    # **Every match, not the first.** The push chain is here to confirm the
    # block independently -- `duration == attack + 2` in 44 of 44 files -- and
    # taking only the first match turns that confirmation into a coincidence
    # of file order. Powerplay Hockey carries the player twice (section
    # 7.iiiii): the block above matches the engine that owns the patterns and
    # names `$4A09`, the first push chain is the *other* engine's and names
    # `$3C03`, and the pair disagreed for a reason that has nothing to do
    # with this file's two-stage attack. Its second push chain names `$4A0B`.
    #
    # The check itself is unchanged and still has to pass; what changes is
    # that a file may offer it more than one candidate.
    duration = -1
    for j in _search_all(data, TWO_STAGE_PUSH):
        if j + 16 >= len(data):
            continue
        cand = data[j + 15] | data[j + 16] << 8
        if cand == attack + 2:
            duration = cand
            break
    if duration < 0:
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
    arithmetic. The bound adds no dangling reference that was not already
    there -- five files reference instruments they never contained at any
    count, from unreachable patterns full of bytes that were never note data,
    and the bound moves how many are unmet rather than which byte is at the
    top (`test_the_bound_adds_no_dangling_reference`). And over the 35
    stride-8 files carrying the array, 32 of which convert, in **five** the
    bound is exactly the highest record any pattern names: Auf Wiedersehen
    Monty, Kings of the Beach ingame, Lightforce, Nemesis the Warlock and
    Saboteur II. An accidental boundary does not land on the last instrument
    a tune plays, five times. (The note here used to claim the bound never
    falls below any reference, and to name Dragon's Lair II among the exact
    landings; the first overstated what the test pins, and the second no
    longer converts at all.)

    Mega Apocalypse, which v0.5.253's zero-page spelling adds to that
    population, was checked the same way before it was let in: 43 records
    counted, 21 before the array, and the highest instrument its patterns name
    is 18. (Its patterns also carry six rows naming instrument $43, which is
    beyond either count and was dangling before this too -- a bound is only
    answerable for the references that were resolvable without it.)

    **Only on the dialect it was validated on.** That paragraph is a
    measurement over the 34 *stride-8* files carrying the array, and v0.5.236
    made the two-stage block detectable in the stride-16 dialect too -- where
    the two bytes are inside the records (`+9` and `+11`) rather than in a
    table after them. **All nine of those files fail the multiple-of-stride
    test below and are untouched**, so the guard above is what the dialect
    rests on rather than the arithmetic.

    That sentence used to name Powerplay Hockey as the ninth file *passing*
    the test -- "the counter-example the rule promised could not exist", with
    a bound of 6 against the instrument 8 its patterns name, costing melody
    72% -> 66%. The counter-example was an artefact of reading the wrong copy
    of the player. That file carries the engine twice (section 7.iiiii), the
    block found for it was the cue engine's, and its two bytes sat in a table
    after the records the way the stride-8 dialect has them. Read from the
    engine its patterns belong to (section 7.jjjjj) they are inside record 0
    at `+9`/`+11` like the rest of the dialect, `span` is 8 against a stride
    of 16, and the test declines it. A reduction is still only meaningful on
    the population it was measured on -- but the file that appeared to
    disprove the boundary was measuring a table nobody plays.
    """
    if det.instr_stride != 8:
        return
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
