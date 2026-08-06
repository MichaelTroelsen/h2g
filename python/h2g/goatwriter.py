"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .detect import Detection
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

# An absolute speed-table entry is (hi, lo) of a per-frame frequency step
# (gplay.c:562). The drum block decrements the frequency HIGH byte once per
# frame ($1387-$138D: `LDA counter / DEC counter / STA $D401,Y`), which is
# exactly 256 units per frame.
#
# KNOWN DEFECT, not fixed here: "per frame" is this player's unit, but
# Goattracker applies a speed-table delta once per *play call*
# (gplay.c:748/758, inside the per-call TICKNEFFECTS) and advances the
# wavetable one entry per play call (gplay.c:707). In the 33 corpus files
# packed at `gt2reloc -S2` a call is half a frame, so this sweep -- and every
# slide -- travels twice as far per frame as the player's, and an instrument
# transient lasts half as long. `multiplier` reaches the tempo path (below)
# and nothing else. siddump ignores the PSID speed field, so the harness
# cannot see this; RetroDebugger can. See whats-next.md work_remaining SS1.
DRUM_SPEED = (0x01, 0x00)


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


def _write_instruments(out: bytearray, sid: SidFile, det: Detection,
                       log=None) -> int:
    available = det.instr_used + 1
    instr_used = min(available, MAX_INSTRUMENTS)
    if log and available > instr_used:
        # Not an over-read: Hubbard players carry a shared instrument bank
        # (drum/noise entries recur byte-identically across games), so tables of
        # 56-58 real records are normal even when a tune plays a dozen. The
        # wavetable simply cannot address more than MAX_REPRESENTABLE_INSTRUMENTS.
        log(f"*** INSTRUMENT TABLE HAS {available} ENTRIES, ONLY {instr_used} FIT "
            f"(GOATTRACKER WAVETABLE LIMIT) -- {available - instr_used} DROPPED ***")

    out.append(instr_used)

    # Instrument 1: always the empty "Clear Voice" slot.
    out += bytes([0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00, 0x02, 0x09])
    out += _padded_name_bytes("Clear Voice")

    # The digi engine's records are 16 bytes rather than 8. The fields read
    # here -- pulse +0/+1, waveform +2, attack/decay +3, sustain/release +4 --
    # sit at the same offsets in both layouts, so only the stride differs.
    wtable_start = 6
    ptable_start = 3
    data = sid.data
    n = max(instr_used - 1, 0)  # number of real (non-empty) instruments

    for i in range(n):
        base = det.instr_start + i * det.instr_stride
        ad = data[base + 3]
        sr = data[base + 4]
        if sr >= 0xF0:
            sr &= 0xEF
        wave_ptr = (i * 5 + wtable_start) & 0xFF
        pulse_ptr = (i * 2 + ptable_start) & 0xFF
        out += bytes([ad, sr, wave_ptr, pulse_ptr, 0x00, 0x00, 0x00, 0x02, 0x09])

        b5, b6, b7 = data[base + 5], data[base + 6], data[base + 7]
        name = f"{i + 2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"
        out += _padded_name_bytes(name)

    return instr_used


def _wavetable_entries(sid: SidFile, det: Detection, i: int, effects: bool,
                       fmt: str, speed_table: List[tuple]) -> tuple:
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
        return _drum_entries(wave, fmt, speed_table)

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
        left[3] = tail
        right[3] = (0x80 - arp_note) & 0xFF
        right[4] = third
    elif effects and det.effect_rise and (arp_style & 2) == 2:
        index = _rise_speed_index(fmt, speed_table)
        if index:
            left[2] = WAVECMD_PORTAUP
            right[2] = index
            right[3] = third

    return left, right


def _drum_entries(wave: int, fmt: str, speed_table: List[tuple]) -> tuple:
    """The five wavetable entries for a record whose player really has a drum.

    Warhawk `$1366`, read out of the 6502 rather than inferred from the bit:

        1366  LDA effect / AND #$01 / BEQ out
        136D  LDA $15B1,X / BEQ out       ; per-voice drum counter, still running?
        1372  LDA $1576,X / BEQ out       ; drum length, set?
        1377  LDA $1579,X / AND #$1F / SEC / SBC #$01 / CMP $1576,X
        1385  BCC $1397                   ; late in the note -> the noise ending
        1387  LDA $15B1,X / DEC $15B1,X / STA $D401,Y  ; freq HI -= 1 per frame
        1390  LDA $157C,X / AND #$FE / BNE $139F       ; the voice's own waveform
        1397  LDA $15B1,X / STA $D401,Y / LDA #$80     ; ... or noise
        139F  STA $D404,Y

    So the drum is the voice's own waveform with the gate released and the
    frequency falling one high byte per frame -- and noise either at the end
    (the BCC branch) or throughout, when the waveform masked to `& $FE` is
    zero. H2G's version was a single noise tick *first* and then the waveform,
    with no sweep at all.

    Emitted here: attack, the gate-off waveform, one step of the sweep, stop.
    The sweep is one entry rather than a loop because the player's is bounded
    by a runtime counter and the table has three free slots (the fifth is the
    stop); the step size is literal (see DRUM_SPEED) and the depth is not. The
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
    index = _drum_speed_index(fmt, speed_table)
    if index:
        left[2], right[2] = WAVECMD_PORTADOWN, index
    return left, right


def _drum_speed_index(fmt: str, speed_table: List[tuple]) -> int:
    """1-based speed-table index for the drum's downward sweep, or 0.

    Zero for a GTS2 file for the same reason as _rise_speed_index: it stores no
    speed table, so an index written here would name whatever entry the
    loader's own reconstruction happened to put at that position.
    """
    if fmt != FORMAT_GTS5:
        return 0
    if DRUM_SPEED not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(DRUM_SPEED)
    return speed_table.index(DRUM_SPEED) + 1


def _rise_speed_index(fmt: str, speed_table: List[tuple]) -> int:
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

    Returns 0 for a GTS2 file, which has no stored speed table: its loader
    builds one from instrument vibrato bytes and *pattern* command columns
    only (gsong.c:285, :311-321) and reads the wavetable verbatim, so an index
    written here would name whatever entry happened to land at that position.
    """
    if fmt != FORMAT_GTS5:
        return 0
    entry = (SPEED_NOTE_RELATIVE, RISE_SHIFT)
    if entry not in speed_table:
        if len(speed_table) >= GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _write_wavetable(out: bytearray, sid: SidFile, det: Detection,
                     instr_used: int, effects: bool = False,
                     fmt: str = DEFAULT_FORMAT,
                     speed_table: List[tuple] | None = None) -> None:
    n = max(instr_used - 1, 0)
    table = speed_table if speed_table is not None else []
    entries = [_wavetable_entries(sid, det, i, effects, fmt, table)
               for i in range(n)]

    out.append(_table_length_byte(instr_used * WAVE_ENTRIES_PER_INSTR, "wave"))
    out += bytes([0x09, 0xFF, 0x00, 0x00, 0x00])
    for left, _ in entries:
        out += bytes(left)

    out += bytes([0x00, 0x00, 0x00, 0x00, 0x00])
    for _, right in entries:
        out += bytes(right)


def _write_pulsetable(out: bytearray, sid: SidFile, det: Detection, instr_used: int) -> None:
    data = sid.data
    n = max(instr_used - 1, 0)

    out.append(_table_length_byte(instr_used * PULSE_ENTRIES_PER_INSTR, "pulse"))
    out += bytes([0x80, 0xFF])
    for i in range(n):
        base = det.instr_start + i * det.instr_stride
        out.append((data[base + 1] | 0x80) & 0xFF)
        out.append(0xFF)

    out += bytes([0x00, 0x00])
    for i in range(n):
        base = det.instr_start + i * det.instr_stride
        out.append(data[base])
        out.append(0x00)


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
              effects: bool = False) -> bytes:
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

    instr_used = _write_instruments(out, sid, det, log)
    _write_wavetable(out, sid, det, instr_used, effects, fmt, table)
    _write_pulsetable(out, sid, det, instr_used)

    if log:
        # Instruments are written as 1..instr_used, so anything above that is a
        # reference to a slot the file does not contain. Goattracker will play
        # those rows with an undefined instrument.
        highest = _highest_instrument_referenced(patterns)
        if highest > instr_used:
            log(f"*** PATTERNS REFERENCE INSTRUMENT ${highest:X} BUT ONLY "
                f"${instr_used:X} WERE WRITTEN -- {highest - instr_used} DANGLING ***")

    out += bytes([0x02, 0x11, 0xFF, 0x22, 0x01])  # empty filter table
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
