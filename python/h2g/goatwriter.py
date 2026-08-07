"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .detect import (Detection, FILTER_ENABLE_BIT,
                     VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                     VIBRATO_SHIFT_MASK)
from .sidfile import SidFile

HEADER_LEN = 0x64
FIELD_LEN = 0x20

# Output format. Both are accepted by GoatTracker 2.77 (src/gsong.c:189,249).
#
# GTS2 is the 3-table format the original VB6 tool wrote, and what the
# byte-exact Commando fixture encodes -- hence the default.
#
# GTS5 is the modern 4-table format. Prefer it for anything you intend to open
# in GoatTracker: the GTS2 *import* path contains a buffer overrun that GTS5
# avoids entirely. gsong.c:306 runs
#     for (d = 0; d < length; d++)  switch (pattern[c][d*4+2]) ...
# where `length` is already rows*4 *bytes*, but `d` indexes rows -- so it walks
# 4x too far, up to pattern[c][1503] in a row of MAX_PATTROWS*4+4 == 516 bytes,
# writing into following patterns wherever it finds command $1/$2/$3/$4/$0E.
# Those are exactly the portamento commands this converter emits. The GTS3/4/5
# loader has no such conversion loop.
FORMAT_GTS2 = "gts2"
FORMAT_GTS5 = "gts5"
FORMATS = (FORMAT_GTS2, FORMAT_GTS5)
DEFAULT_FORMAT = FORMAT_GTS2

# MAX_TABLES in gcommon.h is 4 (WTBL, PTBL, FTBL, STBL). The GTS2 loader reads
# MAX_TABLES-1 and derives the speed table by converting instrument bytes;
# GTS3+ stores all four.
GT_TABLES_GTS2 = 3
GT_TABLES_GTS5 = 4

# Goattracker limits, from goattracker2 src/gcommon.h.
GT_MAX_INSTR = 64      # MAX_INSTR
GT_MAX_TABLELEN = 255  # MAX_TABLELEN -- ltable/rtable are this many bytes each

# Wave/pulse table entries emitted per instrument.
WAVE_ENTRIES_PER_INSTR = 5
PULSE_ENTRIES_PER_INSTR = 2
# A pulse-table left side is a tick count only in 01-7F; 80 and above are read
# as "set pulse width" and FF as a jump (readme.txt:887-891). The right side is
# a signed 8-bit speed (gplay.c:888-900), so a positive step tops out at 7F too.
GT_MAX_PULSE_TICKS = 0x7F
GT_MAX_PULSE_SPEED = 0x7F

# The binding constraint is NOT MAX_INSTR. Each instrument costs 5 wavetable
# entries, and the wavetable's stored length is a single byte bounded by
# MAX_TABLELEN, so at most 255//5 == 51 instruments can be represented at all.
# Raising the clamp to GT_MAX_INSTR (64) would need 320 entries: the length byte
# would wrap and Goattracker would read a truncated table over the following
# section. Keep this at or below MAX_REPRESENTABLE_INSTRUMENTS.
MAX_REPRESENTABLE_INSTRUMENTS = GT_MAX_TABLELEN // WAVE_ENTRIES_PER_INSTR  # 51

# 50 is what the original VB6 tool used, and what the byte-exact Commando
# fixture encodes. It is one below the representable maximum; leave it alone
# unless you are deliberately changing output.
MAX_INSTRUMENTS = 50

assert MAX_INSTRUMENTS <= MAX_REPRESENTABLE_INSTRUMENTS

# Wavetable left-side encodings, readme.txt:790-792. $F0-$FE execute a pattern
# command with the right side as its parameter; $F0 + CMD_PORTAUP (1) is a
# portamento up, and $FF is a jump whose right side is the target position.
WAVECMD_PORTAUP = 0xF1
WAVECMD_PORTADOWN = 0xF2

# Waveform value $80 is noise with the gate bit clear -- literally the `LDA
# #$80 / STA $D404,Y` the drum block ends on. A gated-off voice keeps its last
# waveform latched, so this is also what the voice shows until its next note.
WAVE_NOISE_GATEOFF = 0x80
# Speed-table left side with bit $80 set selects a realtime-calculated,
# note-relative speed; the right side is then a shift applied to the semitone
# interval at the current note (readme.txt:171-174, gplay.c:539-547). Shift 2
# is a quarter semitone per frame == one semitone per four frames.
SPEED_NOTE_RELATIVE = 0x80
RISE_SHIFT = 2

# A note-relative speed is the semitone interval shifted right by the table's
# right byte; past 15 the interval is gone whatever the note, so a shift beyond
# this is a vibrato with no depth rather than a very small one.
GT_MAX_VIB_SHIFT = 0x0F
# gplay.c:769-772 counts the delay down and only acts at 1, so 1 is "start on
# the note". None of the players this reads has a delay before the vibrato.
VIBRATO_DELAY = 0x01

# An absolute speed-table entry is (hi, lo) of a frequency step applied once
# per *play call* (gplay.c:562, inside the per-call TICKNEFFECTS at :748/758).
# The drum block decrements the frequency HIGH byte once per *frame*
# ($1387-$138D: `LDA counter / DEC counter / STA $D401,Y`), which is exactly
# 256 units per frame.
#
# Those two units are the same only at `gt2reloc -S1`. Under -S2 a call is
# half a frame, so a step written as 256 travels 512 units per frame -- twice
# the player's -- and under -S3, three times. `_drum_speed` divides the
# per-frame step by the multiplier the file will be packed at, which is what
# makes the emitted sweep the player's sweep at any -S value.
#
# siddump ignores the PSID speed field (siddump.c:309/325), so no number in
# FIDELITY.md can move on this; RetroDebugger can see it.
DRUM_SPEED_PER_FRAME = 0x0100


def _drum_speed(multiplier: int = 1) -> tuple:
    """`DRUM_SPEED_PER_FRAME` as a per-call (hi, lo) step at `-S{multiplier}`.

    Floor rather than round, and never zero: a step of zero is a sweep that
    does not move, which is further from the player than one 1/256th slow.
    """
    step = max(1, DRUM_SPEED_PER_FRAME // max(1, multiplier))
    return (step >> 8) & 0xFF, step & 0xFF


# The multiplier-1 value, kept as a name because the wavetable tests and the
# method doc both quote it.
DRUM_SPEED = _drum_speed(1)


# A wavetable left side of $01-$0F is a delay: the entry holds whatever
# waveform is already set for that many play calls before advancing
# (gcommon.h:56-57 WAVEDELAY/WAVELASTDELAY, executed at gplay.c:698-704).
WAVE_MAX_DELAY = 0x0F


def _wave_delay(multiplier: int = 1) -> int:
    """Delay entry that stretches one play call to `multiplier` calls, or 0.

    Zero at -S1, where a call already is a frame and no entry is needed.
    """
    return min(max(0, max(1, multiplier) - 1), WAVE_MAX_DELAY)


def _rate_shift(multiplier: int = 1) -> int:
    """Extra right-shift that turns a per-frame rate into a per-call one.

    Only the note-relative speed entries take their rate as a shift, so this
    is exact for 1 and 2 and rounds for 3 (log2(3) = 1.58 -> 2, a division by
    four where three is wanted). See _rise_speed_index.
    """
    m = max(1, multiplier)
    return max(0, round(math.log2(m)))


# --- Tempo -----------------------------------------------------------------
#
# This converter emits exactly one pattern row per Hubbard player tick (see
# patterns.py: an event with wait W occupies W+1 rows). So a row must last one
# player tick -- and a tick is reload+1 frames, not one frame: see the speed
# gate below (find_song_speeds).
#
# Goattracker makes a row last `tempo+1` calls of the play routine (gplay.c:325
# reloads tick from tempo, :322 advances the row when it hits 0). The startup
# default is 6 calls per row, and it scales with the speed multiplier
# (`6*multiplier-1`, gplay.c:212) -- so raising the multiplier alone never
# changes the row rate, it only subdivides each call.
#
# The one lever stored *in the file* is the last instrument's Attack/Decay:
#
#     if ((instr[MAX_INSTR-1].ad >= 2) && (!(instr[MAX_INSTR-1].ptr[WTBL])))
#         cptr->tempo = instr[MAX_INSTR-1].ad - 1;          gplay.c:221
#
# That override does NOT scale with the multiplier, so it sets calls-per-row
# absolutely: instr[63].ad == A gives A calls per row, hence A/multiplier frames
# per row. Goattracker rejects A < 2 (values 0 and 1 select funktempo instead),
# so the fastest expressible row is 2 calls -- i.e. one frame per row requires
# speed multiplier 2. That is exactly the "2x" needed to make a converted tune
# play at the right speed.
GT_TEMPO_INSTRUMENT = 63          # MAX_INSTR-1 -- the old route, see below
GT_DEFAULT_TEMPO_CALLS = 6        # Goattracker's startup default

# CMD_SETTEMPO (gcommon.h: 15). gplay.c:494 takes the low 7 bits, decrements
# them when >= 3, and assigns the result to all three channels when the value
# is under $80. gplay.c:325 then makes a row last `tempo + 1` play-routine
# calls -- but only for `tempo >= 2`; 0 and 1 are *funktempo*, which alternates
# two tick lengths out of funktable[] rather than holding a steady rate.
#
# So the fastest steady row the format can express is tempo 2, i.e. three
# calls, reached by a command value of 2 or 3.
CMD_SETTEMPO = 15
GT_MIN_TEMPO = 2                  # below this is funktempo, not a rate
TEMPO_FASTEST_STEADY = 3          # value -> tempo 2 -> 3 calls per row

# The superseded route: instrument 63's attack/decay (gplay.c:221). It was
# wrong twice over. `ad = 2` yields tempo 1, which is funktempo -- the
# alternating 9/6 tick pattern, not the steady 2 calls/row it was documented
# as -- and reaching instrument 63 meant declaring 63 instruments, ~1.2 KB of
# inert padding that gt2reloc strips when packing to .sid, leaving the packed
# tune silent. A CMD_SETTEMPO in the pattern data survives relocation, shows up
# in the editor, and costs nothing.


# --- The player's own song speed -------------------------------------------
#
# The classic players do NOT advance the sequencer every frame. Commando $5052:
#
#     5054  CE 13 55  DEC $5513     ; master speed counter, every call
#     5057  10 06     BPL $505F
#     5059  AD 17 55  LDA $5517     ; reload value
#     505C  8D 13 55  STA $5513
#     ...
#     5066  AD 13 55  LDA $5513
#     5069  CD 17 55  CMP $5517     ; equal only on the reload frame
#     506C  D0 15     BNE $5083     ; other frames skip the sequencer
#     ...
#     5078  DE F2 54  DEC $54F2,X   ; the per-voice duration DEC (wait+1 rows)
#
# so a duration *unit* -- what one converted pattern row represents -- lasts
# reload+1 frames, not one. The reload value is per subtune where init loads it
# from a table (Commando $5F0F: TAX / LDA $5514,X / STA $5517 -> speeds 2,3,2
# for its three tunes), and a static data byte in the players whose init never
# writes it (Zoids: $146F holds 2, one speed for every subtune). The digi
# engine carries the same gate (Off the Cuff: table at $183F, value 1).
#
# The DEC/BPL/LDA/STA 10-byte sequence with matching counter operands is the
# fingerprint; it matches 85 of the 95 corpus files, and everywhere it was
# checked per voice against siddump of the original (Commando, Thing on a
# Spring, Crazy Comets, IK+, Zoids, After 8, Pandora, Nemesis, Off the Cuff)
# the original's attack gaps are exactly reload+1 times the decoded rows.
#
# What it deliberately does not match: the *prescaler* variant (Mozart, Ninja,
# Mega Apocalypse), `DEC / BPL past-an-RTS / LDA #imm / STA / RTS`, which runs
# the whole player only v of every v+1 calls -- an effective rate of (v+1)/v
# frames per call that no steady Goattracker tempo can express -- and the
# command-table dialect, whose row length comes from its duration table's
# common factor instead (patterns.cmdtable_frames_per_row).
SPEED_GATE = re.compile(rb"\xce(..)\x10\x06\xad(..)\x8d(..)", re.DOTALL)
SPEED_TABLE_LOAD = b"\xbd"       # LDA abs,X -- X is the subtune number
SPEED_RELOAD_STORE = b"\x8d"     # STA abs

# A reload byte above this is not a song speed. Real corpus values are 0-8
# (f = 1..9); per-subtune tables are read past their end for files whose
# header over-counts subtunes (Commando claims 19), and the bytes that follow
# are code whose values (0x70+) would otherwise become absurd tempos.
MAX_SANE_SPEED_RELOAD = 15


@dataclass(frozen=True)
class SongSpeeds:
    """Frames per duration unit, per subtune, read from the player.

    `frames[s]` is reload+1 for subtune `s`, or None where the table byte is
    not a sane speed (over-counted subtunes read past the real table).
    """
    frames: Tuple[Optional[int], ...]
    reload_addr: int
    table_addr: Optional[int]    # None = static reload byte, one speed for all

    def frames_for(self, subtune: int) -> Optional[int]:
        if 0 <= subtune < len(self.frames):
            return self.frames[subtune]
        return None

    @property
    def source(self) -> str:
        if self.table_addr is not None:
            return f"per-subtune table at ${self.table_addr:04X}"
        return f"static reload byte at ${self.reload_addr:04X}"


def _gate_hits(data: bytes):
    """(match offset, reload address) for every speed-gate shape in the file."""
    hits = []
    for m in SPEED_GATE.finditer(data):
        ctr, rel, ctr2 = m.group(1), m.group(2), m.group(3)
        if ctr != ctr2:
            continue
        hits.append((m.start(), rel[0] | rel[1] << 8))
    return hits


def _speeds_for_reload(sid: SidFile, rel_addr: int) -> Optional[SongSpeeds]:
    """SongSpeeds for one gate, from its init table or its static byte."""
    data = sid.data
    rel_bytes = bytes([rel_addr & 0xFF, rel_addr >> 8])
    load = re.escape(SPEED_TABLE_LOAD) + b"(..)" + \
        re.escape(SPEED_RELOAD_STORE + rel_bytes)
    n = max(sid.subtunes, 1)
    for m in re.finditer(load, data, re.DOTALL):
        t = m.group(1)
        table_addr = t[0] | t[1] << 8
        off = sid.to_offset(table_addr)
        if not 0 <= off < len(data):
            continue
        vals = data[off:off + n]
        frames = tuple(v + 1 if v <= MAX_SANE_SPEED_RELOAD else None
                       for v in vals)
        if frames and frames[0] is not None:
            return SongSpeeds(frames, rel_addr, table_addr)
    off = sid.to_offset(rel_addr)
    if 0 <= off < len(data) and data[off] <= MAX_SANE_SPEED_RELOAD:
        return SongSpeeds((data[off] + 1,) * n, rel_addr, None)
    return None


def find_song_speeds(sid: SidFile,
                     det: Detection | None = None) -> Optional[SongSpeeds]:
    """The tune's frames-per-duration-unit, or None where it cannot be read.

    A file can hold several gate shapes (5 Title Tunes carries five separate
    players; One on One's sample data happens to contain the byte sequence).
    With a detection to hand, the gate nearest the detected instrument table is
    the detected player's own. Without one, agreement across all hits is
    required -- disagreeing hits mean the wrong one may be chosen, and a wrong
    tempo is worse than the old constant.
    """
    candidates = []
    for pos, rel_addr in _gate_hits(sid.data):
        speeds = _speeds_for_reload(sid, rel_addr)
        if speeds is not None:
            candidates.append((pos, speeds))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][1]
    if det is not None and det.instr_start >= 0:
        return min(candidates, key=lambda c: abs(c[0] - det.instr_start))[1]
    first = candidates[0][1]
    if all(c[1].frames == first.frames for c in candidates):
        return first
    return None


def recommended_multiplier(speeds: Optional[SongSpeeds],
                           subtune: int = 0) -> int:
    """gt2reloc -S value under which this tune's tempo is expressible.

    A row must last `frames` player calls scaled by the multiplier, and
    Goattracker's fastest steady row is three calls (values 2 and 3 both give
    tempo 2; below that is funktempo). So frames >= 3 works at 1x, frames == 2
    needs the play routine called twice per frame, and frames == 1 three
    times. greloc.c:1595 arms a CIA stub for exactly this.
    """
    f = speeds.frames_for(subtune) if speeds is not None else None
    if f is None or f >= GT_MIN_TEMPO + 1:
        return 1
    return -(-(GT_MIN_TEMPO + 1) // f)     # ceil(3 / f)


def tempo_command_value(sid: SidFile, subtune: int = 0,
                        speeds: Optional[SongSpeeds] = None,
                        multiplier: int = 1) -> int:
    """CMD_SETTEMPO value for this subtune: its player's frames per unit.

    One converted row is one duration unit, and the player's speed gate says a
    unit lasts `frames` frames -- so a row must last `frames` play calls, and
    the command value for any count >= 3 *is* the count (gplay.c:494
    decrements values >= 3, :325 makes a row last tempo+1 calls).

    `multiplier` is the gt2reloc -S factor the caller intends to pack with:
    at 50*m Hz a row of the same real length needs frames*m calls. Where the
    speed cannot be read (no gate shape, a prescaler player, an over-counted
    subtune) the old constant stands, scaled the same way, so a file keeps one
    consistent timebase.
    """
    if speeds is None:
        speeds = find_song_speeds(sid)
    f = speeds.frames_for(subtune) if speeds is not None else None
    if f is None:
        # The old constant, scaled to the caller's timebase: 3 calls at 1x is
        # 3*m calls at m-times the call rate.
        return min(TEMPO_FASTEST_STEADY * multiplier, 0x7F)
    # The floor is not only the funktempo boundary: every instrument this
    # writer emits carries gatetimer 2 (_write_instruments), and gplay.c:334
    # stops the song outright when gatetimer exceeds the channel's tick. A
    # command value of 3 lands as effective tempo 2 -- exactly at that
    # boundary -- so nothing below 3 may ever be emitted here.
    return min(max(f * multiplier, TEMPO_FASTEST_STEADY), 0x7F)


def derived_group_tempos(sid: SidFile, det: Detection,
                         groups: int) -> Tuple[List[int], int, str]:
    """Per-subtune CMD_SETTEMPO values, the -S multiplier, and a source note.

    `groups` is how many 3-track groups the caller has, which equals the
    header subtune numbering as long as no subtune has been split (the caller
    checks that). The multiplier is chosen from subtune 0 -- the canonical
    tune, and what a packed .sid plays by default -- and every subtune's value
    is scaled by it, so the whole file shares one timebase.
    """
    speeds = find_song_speeds(sid, det)
    mult = recommended_multiplier(speeds)
    values = [tempo_command_value(sid, s, speeds, mult) for s in range(groups)]
    note = speeds.source if speeds is not None else \
        "no speed gate found, keeping the constant"
    return values, mult, note


def _table_length_byte(entries: int, what: str) -> int:
    """Length byte for a wave/pulse table, refusing to silently wrap.

    The original masked with & 0xFF, which turns an over-long table into a
    plausible-looking short one -- Goattracker then reads the remainder as
    whatever section follows. Fail loudly instead.
    """
    if not 0 <= entries <= GT_MAX_TABLELEN:
        raise ValueError(
            f"{what} table needs {entries} entries, exceeding Goattracker's "
            f"MAX_TABLELEN ({GT_MAX_TABLELEN})"
        )
    return entries


def _padded_name_bytes(name: str, width: int = 16) -> bytes:
    raw = name.encode("latin-1", errors="replace")[:width]
    return raw + bytes(width - len(raw))


def _field_bytes(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")[:FIELD_LEN]
    return raw.ljust(FIELD_LEN, b"\x00")


def _build_header(sid: SidFile, fmt: str = DEFAULT_FORMAT) -> bytearray:
    header = bytearray(HEADER_LEN)
    header[0:4] = b"GTS2" if fmt == FORMAT_GTS2 else b"GTS5"
    header[0x04:0x04 + FIELD_LEN] = _field_bytes(sid.name)
    header[0x24:0x24 + FIELD_LEN] = _field_bytes(sid.author)
    header[0x44:0x44 + FIELD_LEN] = _field_bytes(sid.released)
    return header


def _instruments_used(det: Detection, log=None) -> int:
    """How many instrument slots the file will carry, Clear Voice included."""
    available = det.instr_used + 1
    instr_used = min(available, MAX_INSTRUMENTS)
    if log and available > instr_used:
        # The count itself is bounded at the records (see detect's
        # `_bound_instruments`); what remains here is Goattracker's own
        # ceiling, which the wavetable's one-byte length imposes.
        log(f"*** INSTRUMENT TABLE HAS {available} ENTRIES, ONLY {instr_used} FIT "
            f"(GOATTRACKER WAVETABLE LIMIT) -- {available - instr_used} DROPPED ***")
    return instr_used


def _write_instruments(out: bytearray, sid: SidFile, det: Detection,
                       instr_used: int, pulse_starts: List[int],
                       sustain_exact: bool = False,
                       no_hard_restart: bool = False,
                       filter_ptrs: dict | None = None,
                       vib_ptrs: dict | None = None) -> int:
    out.append(instr_used)

    # Instrument 1: always the empty "Clear Voice" slot.
    out += bytes([0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00, 0x02, 0x09])
    out += _padded_name_bytes("Clear Voice")

    # The digi engine's records are 16 bytes rather than 8. The fields read
    # here -- pulse +0/+1, waveform +2, attack/decay +3, sustain/release +4 --
    # sit at the same offsets in both layouts, so only the stride differs.
    wtable_start = 6
    data = sid.data
    n = max(instr_used - 1, 0)  # number of real (non-empty) instruments

    for i in range(n):
        base = det.instr_start + i * det.instr_stride
        ad = data[base + 3]
        sr = data[base + 4]
        if not sustain_exact and sr >= 0xF0:
            # Inherited from the VB6 original (h2g.frm:578-579), whose comment
            # reads "&SSSXRRRR (S=Sustain, R=Release, X=Cut this bit out)".
            # There is no X bit: SID register 6 is SSSS RRRR, four bits of
            # sustain and four of release (6581 datasheet). Clearing $10 lowers
            # a sustain of F to E on every instrument that asked for full
            # sustain -- the level the note holds at for its whole duration.
            # Kept as the default only because the byte-exact Commando fixture
            # encodes it; --sustain-exact reads the register as the SID does.
            sr &= 0xEF
        wave_ptr = (i * 5 + wtable_start) & 0xFF
        # Not a stride: a swept instrument's pulse program is longer than a
        # static one's, so the start positions come from the built table.
        pulse_ptr = (pulse_starts[i + 1] if i + 1 < len(pulse_starts) else 0) & 0xFF
        # gatetimer bit $80 is Goattracker's "no hard restart" flag
        # (gsong.c:381). Without it, gplay.c:930-937 writes `adparam` -- the
        # editor's HR value, default $0F00 (goattrk2.c:49), baked into the
        # packed player as ADPARAM/SRPARAM (greloc.c:1138) -- into $D405/$D406
        # for one frame before every note. Hubbard's players never do that:
        # $0F00 appears in none of the corpus originals and is the most common
        # ADSR value in every conversion without this flag.
        gatetimer = 0x82 if no_hard_restart else 0x02
        filt_ptr = (filter_ptrs or {}).get(i, 0x00)
        # Bytes 5 and 6 are ptr[STBL] and vibdelay in a GTS5 file
        # (gsong.c:224-225) and the same pair the other way round, packed, in a
        # GTS2 one (gsong.c:284-285) -- which is why they stay 0,0 unless
        # _vibrato_layout produced something, and it only does for GTS5.
        stbl_ptr, vib_delay = (vib_ptrs or {}).get(i, (0x00, 0x00))
        out += bytes([ad, sr, wave_ptr, pulse_ptr, filt_ptr, stbl_ptr,
                      vib_delay, gatetimer, 0x09])

        b5, b6, b7 = data[base + 5], data[base + 6], data[base + 7]
        name = f"{i + 2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"
        out += _padded_name_bytes(name)

    return instr_used


# What Goattracker's vibrato actually does, simulated from gplay.c:795-801
# rather than read off the constants:
#
#     if ((vibtime < 0x80) && (vibtime > cmpvalue)) vibtime ^= 0xff;
#     vibtime += 0x02;
#     if (vibtime & 0x01) freq -= speed; else freq += speed;
#
# `vibtime` walks the even values up to `cmpvalue`, flips to the odd half by
# XOR, walks that down, and flips back. Counting the calls in each phase for
# cmpvalue 0..16, odd and even alike:
#
#     peak-to-peak = (cmpvalue + 2) * speed
#     full period  = 2 * (cmpvalue + 2) calls
#
# so an amplitude (half the peak-to-peak) of `(cmpvalue + 2) / 2 * speed`, and
# a HALF period of `cmpvalue + 2` calls. The +2 matters at the small values
# both engines produce: cmpvalue 2 oscillates twice as fast as cmpvalue 6, not
# three times.
VIBRATO_CMP_BIAS = 2


def _classic_vibrato_entry(byte: int, multiplier: int) -> Optional[tuple]:
    """Speed-table entry for one instrument byte in the $78/$07 format.

    The mapping is close to literal because both sides express the depth the
    same way. The player computes `(freq(note) - freq(note-1)) >> shift` and
    oscillates a counter between 0 and `bound`; Goattracker's note-relative
    speed (`ltable >= $80`) computes the interval at the current note shifted
    right by `rtable`, and flips direction when its own counter passes
    `ltable & $7f`. So:

        entry = ($80 | cmp, rshift)

    with the two derived from the excursion and the half-period:

    * The player's peak excursion is `(bound >> 1) * depth` and its half-period
      is `bound` frames. Matching the period against a Goattracker half-period
      read as `cmp / 2` *calls* gives `cmp = 2 * bound * multiplier`, and
      matching the excursion then gives `rshift = shift + 1 + log2(multiplier)`.
    * `multiplier` is there because Goattracker's counter advances per play
      call and the player's per frame -- the same per-frame/per-call division
      every other rate in this file takes (see _drum_speed).

    **The half-period this assumes is wrong, and these numbers are kept
    anyway.** Simulating gplay.c (see VIBRATO_CMP_BIAS) puts it at
    `cmp + 2` calls, not `cmp / 2`, so the emitted oscillation runs at about
    half the player's rate; the excursion, which the `+1` in the shift was
    chosen to match, comes out right regardless. Correcting it is
    `cmp = bound * multiplier - VIBRATO_CMP_BIAS` with
    `rshift = shift + log2(multiplier)`, and it moves the output of all 56
    files that carry this format -- a measured change of its own, not a
    silent rider on the table-vibrato commit that found it.
    _table_vibrato_entry below is derived from the simulated semantics.

    Two deliberate approximations besides, neither hidden: the player applies
    its counter as a *position* (an absolute offset from the note) where
    Goattracker integrates a step, which is the same triangle reached
    differently; and Goattracker takes the interval *above* the note where the
    player takes the one below, about 6% of a semitone.
    """
    bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
    if not byte or not bound:
        # The player's own test: `LDA record+5,Y / BNE` at Warhawk $11EA. A
        # bound of zero is an oscillation with no excursion, which is the same
        # silence reached one step later.
        return None
    shift = byte & VIBRATO_SHIFT_MASK
    cmp_value = min(0x7F, 2 * bound * multiplier)
    rshift = min(shift + 1 + _rate_shift(multiplier), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _table_vibrato_entry(byte: int, tv, multiplier: int) -> Optional[tuple]:
    """Speed-table entry for one instrument byte in the LFO-table format.

    The command-table engine's vibrato is a table walked one entry per frame,
    the offset in frame `i` being `table[i] * count * (interval >> unit)` with
    `count` the parameter byte's low nibble and the table its high one; see
    detect._find_table_vibrato for the routine. All four tables in both corpus
    files are triangles, which is the only reason a fixed triangle can stand
    in for them at all -- an arbitrary shape could not be approximated, and
    this returns None for a table that is not one (peak or length unreadable).

    The table's LENGTH is the whole period in frames, against Goattracker's
    `2 * (cmp + 2)` calls, so matching the period gives

        cmp = length * multiplier / 2 - 2

    and matching the excursion equates the two amplitudes,

        (cmp + 2) / 2 * (interval >> rshift)
            == peak * count * (interval >> unit)

    which the interval cancels out of entirely, leaving

        rshift = log2((cmp + 2) * 2**unit / (2 * peak * count))

    rounded to the nearest integer -- Goattracker's depth is a shift, so only
    powers of two are reachable and the rounding is in log space, where the
    error is multiplicative and symmetric. Hollywood or Bust's seven vibrato
    records ask for ratios of 4, 4, 3, 5.33, 4, 8 and 4 -- five land on a
    power of two exactly and two round, the worst of them by a third.

    Both numbers come from the *simulated* gplay.c semantics (see
    VIBRATO_CMP_BIAS), not from the reading _classic_vibrato_entry above was
    built on. A `cmp` of 0 is a legal entry, not an empty one: `$80` still
    selects the note-relative speed and `cmpvalue & 0x7f` is then 0, which is
    the fastest oscillation Goattracker has -- 4 calls -- and exactly what the
    shortest of the four tables asks for.

    One approximation the classic mapping has and this does not: the player
    takes the interval *above* the note here (`freq(note+1) - freq(note)`),
    which is the one Goattracker computes. What remains is the shape: the
    player's table is a position sequence sampled per frame where Goattracker
    integrates a step per call, so the two triangles agree in period and
    excursion and differ in how they get there whenever the table is not
    symmetric -- table 1 (`0 1 2 1 0 -1`) spends four of its six frames above
    zero.
    """
    count = byte & 0x0F
    index = (byte & 0xF0) >> 4
    if not byte or not count or index >= len(tv.shapes):
        # The player's own test is on the whole byte (`LDA record+5,Y / BNE`
        # at Hollywood or Bust $05D1); a count of zero multiplies the unit by
        # nothing, which is the same silence reached one step later.
        return None
    length, peak = tv.shapes[index]
    if not length or not peak:
        return None
    half = max(1, round(length * multiplier / 2.0))
    cmp_value = min(0x7F, max(0, half - VIBRATO_CMP_BIAS))
    ratio = ((cmp_value + VIBRATO_CMP_BIAS) * (1 << tv.unit_shift)
             / (2.0 * peak * count))
    rshift = min(max(round(math.log2(ratio)), 0), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _vibrato_layout(sid: SidFile, det: Detection, instr_used: int,
                    vibrato: bool, fmt: str, multiplier: int,
                    speed_table: List[tuple], log=None) -> dict:
    """{instrument index: (speed-table index, vibdelay)} for `--vibrato`.

    Goattracker runs a per-instrument vibrato with no pattern command at all:
    on every new note `gplay.c:352-354` loads `cptr->vibdelay = iptr->vibdelay`
    and `cptr->cmddata = iptr->ptr[STBL]`, and a channel whose command is
    CMD_DONOTHING falls through into CMD_VIBRATO once the delay expires
    (gplay.c:769-780). Those are instrument-record bytes 5 and 6, and this
    writer has always written `0x00, 0x00` there -- which is why no file it has
    ever produced vibrates, and why a third of the corpus moves the pitch not
    at all where the original does.

    Two player engines reach this, and they share no byte format: the classic
    $78-bound/$07-shift pair (56 corpus files, _classic_vibrato_entry) and the
    command-table engine's LFO table (2 files, _table_vibrato_entry). Both end
    at the same place -- a note-relative speed-table entry and a vibdelay --
    and the derivation of each is in its own function.

    GTS5 only. A GTS2 file stores no speed table -- its loader packs the
    vibrato into a single instrument byte and calls makespeedtable itself
    (gsong.c:285), and it reads bytes 5 and 6 the other way round
    (vibdelay first, gsong.c:284) -- so the same numbers would need a
    different encoding, and the byte-exact fixture is a GTS2 file.
    """
    if not vibrato or fmt != FORMAT_GTS5:
        return {}
    mult = max(1, multiplier)
    if det.vibrato_offset is not None:
        offset = det.vibrato_offset
        entry_of = lambda b: _classic_vibrato_entry(b, mult)
        engine = "bound/shift"
    elif det.table_vibrato is not None:
        offset = det.table_vibrato.offset
        entry_of = lambda b: _table_vibrato_entry(b, det.table_vibrato, mult)
        engine = "LFO table"
    else:
        return {}
    data = sid.data
    out: dict = {}
    for i in range(max(instr_used - 1, 0)):
        base = det.instr_start + i * det.instr_stride + offset
        if base >= len(data):
            continue
        entry = entry_of(data[base])
        if entry is None:
            continue
        if entry not in speed_table:
            if len(speed_table) >= GT_MAX_TABLELEN:
                continue
            speed_table.append(entry)
        out[i] = (speed_table.index(entry) + 1, VIBRATO_DELAY)
    if log and out:
        log(f"Instrument vibrato......: {len(out)} of "
            f"{max(instr_used - 1, 0)} record(s), "
            f"{len({v[0] for v in out.values()})} speed-table entry(ies) "
            f"({engine})")
    return out


def _wavetable_entries(sid: SidFile, det: Detection, i: int, effects: bool,
                       fmt: str, speed_table: List[tuple],
                       multiplier: int = 1) -> tuple:
    """The five (left, right) wavetable entries for instrument `i`.

    With `effects` false this reproduces the VB6 original exactly, fabricating
    a drum and an arpeggio from bits $01 and $04 of every instrument record in
    every file. With it on, each bit is read only where detection found the
    routine that reads it (det.effect_drum / det.effect_arp / det.effect_rise),
    because +7 is not a shared format: see detect._find_effect_routines and the
    census in H2G-CONVERSION-METHOD.md section 7. Corpus-wide that gate is the
    larger half of this function's error -- 159 of 450 records setting the drum
    bit and 544 of 683 setting the arpeggio bit are in a player with no such
    routine, and the original invents the effect for all of them.

    Where the drum routine *is* present the shape is also deepened; see
    _drum_entries.
    """
    data = sid.data
    base = det.instr_start + i * det.instr_stride
    arp_style = data[base + 7]
    wave = data[base + 2]

    arp_note = (arp_style & 0xF0) >> 4
    # The original substitutes $74 -- a +12 relative note, an octave-up
    # arpeggio -- whenever the high nibble is zero. The player does no such
    # thing: the nibble is written into the operand of the `SBC` at $13F4
    # ($13DB `STA $13F5`), so a nibble of zero subtracts zero and both halves
    # of the alternation play the same note. Half of every arpeggio instrument
    # in the corpus (315 of 660 records) has nibble zero, so the substitution
    # invents an octave arpeggio for all of them.
    drum = (arp_style & 1) == 1
    arp = (arp_style & 4) == 4
    if effects:
        if not det.effect_drum:
            drum = False
        if not det.effect_arp or arp_note == 0:
            arp = False
    if arp_note == 0:
        arp_note = 0x74

    arp_set_keybit = 0 if drum else 1
    tail = (wave & 0xFE) | arp_set_keybit

    left = [wave, 0x00, tail, 0xFF, 0xFF]
    right = [0x00, 0x00, 0x00, 0x00, 0x00]

    # A record that sets both bits gets both blocks in the player -- the drum
    # sets the waveform, the arpeggio then overwrites the frequency it swept
    # ($13F4 runs after $139F). Five entries cannot hold both, so the arpeggio
    # keeps the pair it needs and such a record stays on the original's shape.
    # 62 of the 291 drum records this gate keeps are in that case.
    if drum and effects and not arp:
        return _drum_entries(wave, fmt, speed_table, multiplier)

    if drum:
        if effects:
            # The arpeggio keeps entries 2-4, so all the drum can say here is
            # where it starts: the voice's own waveform, gate released. The
            # leading noise tick the original wrote is not in the player at
            # all, and on the corpus it scores at chance.
            left[1] = (wave & 0xFE) or WAVE_NOISE_GATEOFF
        else:
            left[1] = 0x80 | arp_set_keybit
            right[1] = (0x80 - arp_note) & 0xFF
    else:
        left[1] = tail

    # The instrument's own entries are 1-based indices i*5+6 .. i*5+10, so its
    # third is i*5+8 -- the loop target for both the arpeggio and the rise.
    third = (i * WAVE_ENTRIES_PER_INSTR + 8) & 0xFF

    if arp:
        # $13CD: alternate between the note and the note minus the high
        # nibble, one frame each. Readme p.794: right side $60-$7F is a
        # negative relative note, so $80-N is -N semitones.
        #
        # The alternation is one entry per play call, so at -S2 it swaps twice
        # a frame and at -S3 three times -- the player's rate only at -S1. Each
        # half would need a delay entry beside it and the five-entry layout has
        # no room, so this one stays at the call rate. Named here rather than
        # left to be re-found.
        left[3] = tail
        right[3] = (0x80 - arp_note) & 0xFF
        right[4] = third
    elif effects and det.effect_rise and (arp_style & 2) == 2:
        index = _rise_speed_index(fmt, speed_table, multiplier)
        if index:
            left[2] = WAVECMD_PORTAUP
            right[2] = index
            right[3] = third

    # The attack entry holds for one play call, which is one frame only at
    # -S1; under -S{m} it needs m. A delay entry ($01-$0F, held for N calls --
    # gcommon.h:56-57, gplay.c:698-704) buys those calls without spending a
    # waveform slot, and entry 1 is where it fits: in the plain and arpeggio
    # shapes entry 1 merely repeats entry 2's `tail`, and in the arpeggio's
    # case the loop runs over entries 2 and 3, so entry 1 is passed once.
    #
    # The rise shape is the exception -- its entry 2 is a command, so entry 1
    # is the only place the tail waveform is written, and the delay may take it
    # only where the tail *is* the attack byte and writing it changes nothing.
    hold = _wave_delay(multiplier)
    if hold and not drum and (left[2] == tail or tail == wave):
        left[1] = hold

    return left, right


def _drum_entries(wave: int, fmt: str, speed_table: List[tuple],
                  multiplier: int = 1) -> tuple:
    """The five wavetable entries for a record whose player really has a drum.

    Warhawk `$1366`, read out of the 6502 rather than inferred from the bit:

        1366  LDA effect / AND #$01 / BEQ out
        136D  LDA $15B1,X / BEQ out       ; per-voice drum counter, still running?
        1372  LDA $1576,X / BEQ out       ; drum length, set?
        1377  LDA $1579,X / AND #$1F / SEC / SBC #$01 / CMP $1576,X
        1385  BCC $1397                   ; R still large -> EARLY in the note
        1387  LDA $15B1,X / DEC $15B1,X / STA $D401,Y  ; freq HI -= 1 per frame
        1390  LDA $157C,X / AND #$FE / BNE $139F       ; the voice's own waveform
        1397  LDA $15B1,X / STA $D401,Y / LDA #$80     ; ... or noise
        139F  STA $D404,Y

    So the drum is the voice's own waveform with the gate released and the
    frequency falling one high byte per frame -- and noise at the *start* (the
    BCC branch, taken while the remaining-duration counter is still large),
    or throughout, when the waveform masked to `& $FE` is zero.

    **The branch direction was recorded backwards until v0.5.90.** `A` is
    `W - 1` (the note's original duration less one) and `M` is the counter
    still counting down from `W`, so `BCC` -- taken on `A < M` -- fires while
    the counter is large, which is the beginning of the note, not its end. The
    sweep then runs for the rest of it: `W - 1` steps per note against the one
    this writes -- confirmed in VICE at v0.5.91, where Bump_Set_Spike's voice-2
    frequency-high shadow walks `0D 0C 0B 0A 09 08 07`, one per play call. The
    single step here is an under-render, and `bend` reports it as an overshoot
    only because siddump names the player's 256-unit steps as notes rather than
    bends. See H2G-CONVERSION-METHOD.md section 7.ii. H2G's version was a single noise tick *first* and then the waveform,
    with no sweep at all.

    Emitted here: attack, the gate-off waveform, one step of the sweep, stop.
    The sweep is one entry rather than a loop because the player's is bounded
    by a runtime counter and the table has three free slots (the fifth is the
    stop); the step size is literal (see _drum_speed, which divides the
    player's per-frame step by the -S multiplier) and the depth is not. All
    five entries are in use, so unlike the plain shape this one has no slot for
    a delay: its attack entry lasts one play call at every -S value. The
    wave metric cannot see it either way -- it compares waveform class, and the
    class does not change while the frequency falls.

    **The noise ending is deliberately not written.** Emitting it as a fourth
    entry costs 2.4 points of corpus wave agreement (60.5% -> 58.1%) and takes
    noise frames from 5680 to 10666 against the original's 11641: in
    Goattracker a gated-off voice keeps its last waveform latched until the
    next note, so a noise entry at the end of the table stands for the whole
    rest of the note, while the player stops writing $D404 the moment its
    counter runs out. Measured on the corpus, not argued.

    A record that also sets the rise bit loses the rise here; it needs the same
    slots. 4 files have the rise routine at all.
    """
    left = [wave, (wave & 0xFE) or WAVE_NOISE_GATEOFF, 0xFF, 0xFF, 0xFF]
    right = [0x00, 0x00, 0x00, 0x00, 0x00]
    index = _drum_speed_index(fmt, speed_table, multiplier)
    if index:
        left[2], right[2] = WAVECMD_PORTADOWN, index
    return left, right


def _drum_speed_index(fmt: str, speed_table: List[tuple],
                      multiplier: int = 1) -> int:
    """1-based speed-table index for the drum's downward sweep, or 0.

    Zero for a GTS2 file for the same reason as _rise_speed_index: it stores no
    speed table, so an index written here would name whatever entry the
    loader's own reconstruction happened to put at that position.
    """
    if fmt != FORMAT_GTS5:
        return 0
    entry = _drum_speed(multiplier)
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _rise_speed_index(fmt: str, speed_table: List[tuple],
                      multiplier: int = 1) -> int:
    """1-based speed-table index for the effect byte's chromatic rise, or 0.

    Effect bit $02 makes the player raise the note by one semitone every four
    frames, for as long as the note is held: `$13A2 LDA effect / AND #$02`,
    then `LDA $15BF / AND #$03 / BNE` -- the global frame counter, so it acts
    only on every fourth frame -- then `INC $157F,X`, the voice's note index,
    and a rewrite of $D400/$D401 from the frequency table. 252 instrument
    records across 59 corpus files set it, and H2G read none of them.

    Goattracker cannot step a note from the wavetable without spending one
    entry per semitone, which the fixed five-entry-per-instrument layout has
    no room for. It *can* glide at a note-relative rate: readme.txt:171 says a
    speed-table left side with bit $80 set selects a realtime-calculated
    speed, and gplay.c:539-547 then computes it as the semitone interval at
    the current note shifted right by the table's right byte. A shift of 2 is
    a quarter of a semitone per frame -- the player's rate exactly, as a
    continuous glide rather than four-frame steps. That approximation is
    deliberate and is the only part of this mapping that is not literal.

    "Per frame" holds only at -S1: the shift is applied once per play call, so
    each doubling of the call rate needs one more shift to keep the same rate
    per frame. The multipliers this converter emits are 2 and 3 (ceil(3/f),
    f in 1..2), and 3 is not a power of two -- shift 4 divides by four where
    three is wanted, which is the closest either neighbouring shift gets.
    Recorded rather than hidden: at -S3 the rise glides 3/4 of the player's
    rate, where before this it glided three times it.

    Returns 0 for a GTS2 file, which has no stored speed table: its loader
    builds one from instrument vibrato bytes and *pattern* command columns
    only (gsong.c:285, :311-321) and reads the wavetable verbatim, so an index
    written here would name whatever entry happened to land at that position.
    """
    if fmt != FORMAT_GTS5:
        return 0
    entry = (SPEED_NOTE_RELATIVE, RISE_SHIFT + _rate_shift(multiplier))
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _write_wavetable(out: bytearray, sid: SidFile, det: Detection,
                     instr_used: int, effects: bool = False,
                     fmt: str = DEFAULT_FORMAT,
                     speed_table: List[tuple] | None = None,
                     multiplier: int = 1) -> None:
    n = max(instr_used - 1, 0)
    table = speed_table if speed_table is not None else []
    entries = [_wavetable_entries(sid, det, i, effects, fmt, table, multiplier)
               for i in range(n)]

    out.append(_table_length_byte(instr_used * WAVE_ENTRIES_PER_INSTR, "wave"))
    out += bytes([0x09, 0xFF, 0x00, 0x00, 0x00])
    for left, _ in entries:
        out += bytes(left)

    out += bytes([0x00, 0x00, 0x00, 0x00, 0x00])
    for _, right in entries:
        out += bytes(right)


def _split_ticks(ticks: int) -> List[int]:
    """`ticks` as steps of at most GT_MAX_PULSE_TICKS, longest first.

    A pulse-table left side is a tick count in 01-7F -- 80 and above mean "set
    pulse width" instead -- so a leg longer than 127 calls has to be spelled as
    consecutive steps carrying the same speed. gplay.c:902 advances to the next
    entry when a step's counter reaches zero and the modulation simply
    continues, so N steps of the same speed and a single step of their total
    are the same sweep.
    """
    full, rest = divmod(ticks, GT_MAX_PULSE_TICKS)
    steps = [GT_MAX_PULSE_TICKS] * full
    if rest:
        steps.append(rest)
    return steps or [1]


def _pulse_program(sid: SidFile, det: Detection, i: int, pulse: bool,
                   multiplier: int) -> tuple[List[tuple], int | None]:
    """The pulse-table entries for instrument `i`, and where a jump loops back.

    Without `pulse`, or where the player has no sweep, this is what H2G has
    always written: one "set pulse width" from record bytes +0/+1, then stop.
    That is correct for the 328 corpus records whose sweep rate is zero and
    wrong for the 414 that sweep, which came out with a duty cycle frozen at
    its starting value -- audible as a flat, static timbre under notes that are
    otherwise right, and invisible to every metric in the repo (`wave` compares
    the waveform *class*, so pulse is pulse whatever its width).

    The player's sweep is a triangle: add `rate` to a 12-bit accumulator each
    frame, flip direction when the high nibble reaches either bound. In a
    Goattracker pulse table that is a "set" to the lower bound, an ascending
    step, a descending step, and a jump -- readme.txt:887-891 for the encoding
    and gplay.c:872-902 for the execution.

    Two places this is an approximation, both stated rather than hidden:

    * the player turns around when the high nibble *equals* a bound, so a rate
      that does not divide the span exactly overshoots by up to one step before
      flipping; the tick count here is the span divided by the speed, which
      turns around a fraction of a step early instead.
    * `multiplier` is the gt2reloc -S factor. Goattracker steps the pulse table
      once per play *call* (gplay.c:872, inside the per-call block) where the
      player steps once per *frame*, so at -S2 an unscaled speed would sweep at
      twice the player's rate. Dividing rounds, and an odd rate at -S2 cannot
      be expressed exactly; the tick count is recomputed from the speed that
      was actually emitted so the sweep still covers the right span.
    """
    data = sid.data
    base = det.instr_start + i * det.instr_stride
    static = [((data[base + 1] | 0x80) & 0xFF, data[base]), (0xFF, 0x00)]
    if not pulse:
        return static, None
    if det.pulse_bounds < 0:
        if det.pulse_lo_base >= 0:
            program = _pulse_lo_program(sid, det, i, multiplier)
            if program is not None:
                return program
        return static, None
    bounds_at = det.pulse_bounds + i * det.instr_stride
    rate_at = base + det.pulse_rate_field
    if bounds_at >= len(data) or rate_at >= len(data):
        return static, None
    rate = data[rate_at]
    bounds = data[bounds_at]
    low, high = bounds & 0x0F, bounds >> 4
    # rate 0 is the player's own "do not sweep"; high <= low leaves it no band
    # to travel, and what it does then depends on 12-bit wrap-around. Both keep
    # the static width -- an under-read never invents movement.
    if rate == 0 or high <= low:
        return static, None
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / multiplier)))
    steps = _split_ticks(max(1, ((high - low) << 8) // speed))
    entries = [((0x80 | low) & 0xFF, 0x00)]
    entries += [(t, speed) for t in steps]
    entries += [(t, (0x100 - speed) & 0xFF) for t in steps]
    return entries, 1


def _pulse_lo_program(sid: SidFile, det: Detection, i: int,
                      multiplier: int) -> tuple[List[tuple], int | None] | None:
    """The accumulate engine's entries, or None if this record does not use it.

    The other pulse engine, selected per *instrument* by effect-byte bit $08 and
    mutually exclusive with the sweep: 34 corpus files sweep, 21 accumulate, and
    none do both. It adds record +6 to the width's low byte every frame and
    writes only $D402, never $D403 -- so the duty cycle races around one
    256-wide band while the high nibble stays where the note put it.

    In a Goattracker pulse table that is a set to the seeded width, one
    ascending leg long enough to cross the low byte, and a jump back to the
    *set* rather than to the leg. Jumping to the set is what pins the high
    nibble: Goattracker's modulation carries into it (gplay.c:888-900) and the
    player never does, so a leg allowed to run on would climb out of the band
    the player stays inside.

    The approximation, stated rather than hidden: the player's accumulator wraps
    mod 256 and carries its phase into the next cycle, so a rate that does not
    divide 256 exactly starts each cycle a little further along. Restarting at
    the seed keeps the period and the band right and loses that drift. It also
    restarts with the note, which is correct here -- $D402/$D403 are reseeded at
    every note fetch (see `_find_pulse_lo`), so the engine has no state to carry
    across a note anyway.
    """
    data = sid.data
    rec = det.pulse_lo_base + i * det.instr_stride
    if rec + 7 >= len(data):
        return None
    # The player gates the block on the instrument's own bit $08. A record
    # without it keeps the static width, which is exactly what it plays.
    if not data[rec + 7] & 0x08:
        return None
    rate = data[rec + 6]
    if rate == 0:
        return None
    lo, hi = data[rec], data[rec + 1]
    speed = min(GT_MAX_PULSE_SPEED, max(1, round(rate / multiplier)))
    entries = [((0x80 | (hi & 0x0F)) & 0xFF, lo)]
    entries += [(t, speed) for t in _split_ticks(max(1, 0x100 // speed))]
    return entries, 0


def _pulse_layout(sid: SidFile, det: Detection, instr_used: int,
                  pulse: bool, multiplier: int,
                  log=None) -> tuple[List[tuple], List[int]]:
    """The whole pulse table, plus each instrument's 1-based start entry.

    Entries were a fixed two per instrument until the sweep gave some of them
    four or more, so the start positions are returned rather than computed from
    a stride -- `_write_instruments` writes them into the records.
    """
    entries: List[tuple] = [(0x80, 0x00), (0xFF, 0x00)]
    starts = [1]                       # instrument 1, the empty Clear Voice
    dropped = silent = 0
    for i in range(max(instr_used - 1, 0)):
        program, loop = _pulse_program(sid, det, i, pulse, multiplier)
        start = len(entries) + 1
        block = program if loop is None else program + [(0xFF, start + loop)]
        if len(entries) + len(block) > GT_MAX_TABLELEN:
            # Out of table: keep the instrument, lose only its movement.
            block, _ = _pulse_program(sid, det, i, False, multiplier)
            dropped += 1
        if len(entries) + len(block) > GT_MAX_TABLELEN:
            # Not even the static pair fits. Pointer 0 leaves the pulse width
            # alone (readme.txt:714) -- the record must still get one, or every
            # instrument after it reads another instrument's program.
            starts.append(0)
            silent += 1
            continue
        starts.append(start)
        entries += block
    if log and dropped:
        log(f"*** PULSE TABLE FULL -- {dropped} INSTRUMENT(S) KEEP A STATIC "
            f"WIDTH INSTEAD OF THEIR SWEEP"
            + (f", {silent} SET NO WIDTH AT ALL ***" if silent else " ***"))
    return entries, starts


def _write_pulsetable(out: bytearray, entries: List[tuple]) -> None:
    out.append(_table_length_byte(len(entries), "pulse"))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)


# Goattracker's filter table is bounded by MAX_FILT, not MAX_TABLELEN
# (gcommon.h:26), and it is the only table with a limit that low -- which is
# why entries are spent only on instruments whose routing byte actually routes
# a channel, rather than one block per instrument as wave and pulse do.
GT_MAX_FILT = 64

# Goattracker filter-table left side (readme.txt:905-913):
FILT_SET_CUTOFF = 0x00   # right side is the cutoff
FILT_SET_PARAMS = 0x80   # | passband; right side is resonance/routing
FILT_STOP = 0xFF
# "For N ticks, change cutoff by the signed right side." $7F is the longest a
# single step can run, and the sweep is meant to last the note, so one maximal
# step is the closest a static table gets to a per-frame accumulation.
FILT_MODULATE = 0x7F


def _filter_entries(sid: SidFile, det: Detection, instr_used: int):
    """(entries, pointers) for the filter table, or ([], {}) when unreadable.

    The player adds a per-instrument step to a per-voice cutoff accumulator
    every frame and writes the result to $D416; Goattracker's filter table
    expresses exactly that as "set params, set cutoff, modulate". What it
    cannot express is the accumulator being *per voice* -- Goattracker has one
    filter and one cutoff for the whole tune, as the SID chip does, so two
    voices sweeping at once come out as whichever instrument was struck last.
    That is the chip's limit, not the format's: the original has the same
    single filter and the same last-writer-wins race.
    """
    filt = det.filter
    if filt is None:
        return [], {}
    data = sid.data
    entries: List[tuple] = []
    pointers: dict = {}
    for i in range(max(instr_used - 1, 0)):
        base = filt.offset + i * det.instr_stride
        if base + 1 >= len(data):
            break
        status = filt.status + i * det.instr_stride
        if status >= len(data):
            break
        # The player's own switch, not ours: it runs the whole filter block
        # only for an instrument whose status byte has bit $20 set. Reading the
        # array without this test gives a plausible resonance byte for every
        # instrument in every file that merely *contains* the routine.
        if not data[status] & FILTER_ENABLE_BIT:
            continue
        resctl, step = data[base], data[base + 1]
        if not resctl & 0x0F:
            continue  # routes no voice through the filter: nothing to hear
        block = [(FILT_SET_PARAMS | filt.passband, resctl),
                 (FILT_SET_CUTOFF, filt.cutoff)]
        if step:
            block.append((FILT_MODULATE, step))
        block.append((FILT_STOP, 0x00))
        if len(entries) + len(block) > GT_MAX_FILT:
            break
        pointers[i] = len(entries) + 1  # table steps are 1-based
        entries += block
    return entries, pointers


def _write_filtertable(out: bytearray, entries: List[tuple]) -> None:
    if not entries:
        out += bytes([0x02, 0x11, 0xFF, 0x22, 0x01])  # empty filter table
        return
    out.append(len(entries))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)


def _highest_instrument_referenced(patterns: List[List[int]]) -> int:
    """Largest instrument number any pattern row selects (column 1 of 4)."""
    highest = 0
    for pattern in patterns:
        for k in range(1, len(pattern), 4):
            if pattern[k] > highest:
                highest = pattern[k]
    return highest


def build_sng(sid: SidFile, det: Detection, tracks: List[List[int]],
              patterns: List[List[int]], log=None,
              fmt: str = DEFAULT_FORMAT,
              speed_table: List[tuple] | None = None,
              effects: bool = False, pulse: bool = False,
              multiplier: int = 1,
              sustain_exact: bool = False,
              no_hard_restart: bool = False,
              filters: bool = False,
              vibrato: bool = False) -> bytes:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {fmt!r}")
    # _write_wavetable may append the note-relative entry the chromatic rise
    # needs, and the table is written after it, so give it a list to grow.
    table = list(speed_table or [])
    out = bytearray()
    out += _build_header(sid, fmt)
    # Derived from the tracks actually emitted, not sid.subtunes: convert_tracks
    # trims subtunes the track table cannot back, and the count byte must agree
    # with the number of tracks that follow or the file is unreadable. Identical
    # to sid.subtunes whenever nothing was trimmed.
    out.append((len(tracks) // 3) & 0xFF)

    for track in tracks:
        out.append((len(track) - 1) & 0xFF)
        out += bytes(track)

    instr_used = _instruments_used(det, log)
    # The filter and pulse tables are both built before the instruments,
    # because each instrument record carries the table step it starts on --
    # but both are written after them, with the other tables. A swept
    # instrument's pulse program is longer than a static one's, so that start
    # position is not a stride either.
    if filters:
        filter_entries, filter_ptrs = _filter_entries(sid, det, instr_used)
    else:
        filter_entries, filter_ptrs = [], {}
    pulse_entries, pulse_starts = _pulse_layout(sid, det, instr_used, pulse,
                                                multiplier, log)
    # Before the records, because each one carries its speed-table index -- and
    # into `table`, which the wavetable also grows and the file writes last.
    vib_ptrs = _vibrato_layout(sid, det, instr_used, vibrato, fmt, multiplier,
                               table, log)
    _write_instruments(out, sid, det, instr_used, pulse_starts,
                       sustain_exact, no_hard_restart, filter_ptrs, vib_ptrs)
    _write_wavetable(out, sid, det, instr_used, effects, fmt, table, multiplier)
    _write_pulsetable(out, pulse_entries)

    if log:
        # Instruments are written as 1..instr_used, so anything above that is a
        # reference to a slot the file does not contain. Goattracker will play
        # those rows with an undefined instrument.
        highest = _highest_instrument_referenced(patterns)
        if highest > instr_used:
            log(f"*** PATTERNS REFERENCE INSTRUMENT ${highest:X} BUT ONLY "
                f"${instr_used:X} WERE WRITTEN -- {highest - instr_used} DANGLING ***")

    _write_filtertable(out, filter_entries)
    if fmt == FORMAT_GTS5:
        # Fourth table (STBL), stored only in GTS3+. A GTS2 file has none: its
        # loader builds one while reading, both from each instrument's vibrato
        # byte and from every portamento command's data column
        # (gsong.c:285, :311-321).
        #
        # So the same conversion that is correct in a GTS2 file is inert in a
        # GTS5 one unless the table is written out here -- gplay.c:740 reads a
        # portamento's speed from `ltable[STBL][cmddata-1]`, and against an
        # empty table that is zero, i.e. no pitch movement at all. See
        # patterns.build_speed_table.
        out.append(_table_length_byte(len(table), "speed"))
        out += bytes(left for left, _ in table)
        out += bytes(right for _, right in table)

    out.append(len(patterns) & 0xFF)
    for pattern in patterns:
        out.append((len(pattern) // 4) & 0xFF)
        out += bytes(pattern)

    return bytes(out)
