"""Goattracker v2.34+ .sng file writer (port of GoatClear + GoatSave, h2g.frm).

`GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead arrays in the
original -- written by GoatClear but never read anywhere -- so they are not
modeled here.
"""
from __future__ import annotations

from typing import List

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

# Speed-table left side with bit $80 set selects a realtime-calculated,
# note-relative speed; the right side is then a shift applied to the semitone
# interval at the current note (readme.txt:171-174, gplay.c:539-547). Shift 2
# is a quarter semitone per frame == one semitone per four frames.
SPEED_NOTE_RELATIVE = 0x80
RISE_SHIFT = 2


# --- Tempo -----------------------------------------------------------------
#
# This converter emits exactly one pattern row per Hubbard player tick (see
# patterns.py: an event with wait W occupies W+1 rows, one frame each). So a row
# must last one player tick.
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


def tempo_command_value(sid: SidFile, subtune: int = 0) -> int:
    """Calls-per-row to write for this SID, from its PSID speed field.

    The header records only *whether* a subtune is CIA-timed, never at what
    rate, so it cannot yield a multispeed factor. Either way one row is one
    player tick, so the answer is the same minimum in both cases; the speed bit
    is surfaced for logging and for callers that want to warn about multispeed.
    """
    return TEMPO_FASTEST_STEADY


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

    With `effects` false this reproduces the VB6 original exactly. With it on,
    the two effect-byte bits the original mis-read are decoded as the player
    reads them -- but only where detection actually found the routine that
    reads them (det.effect_rise / det.effect_arp), because +7 is not a shared
    format: see detect._find_effect_routines. 4 of 83 convertible corpus files
    have the rise routine and 13 the arpeggio one; for the rest this is a
    no-op, which is the point.
    """
    data = sid.data
    base = det.instr_start + i * det.instr_stride
    arp_style = data[base + 7]
    arp_set_keybit = 0 if (arp_style & 1) == 1 else 1
    wave = data[base + 2]
    tail = (wave & 0xFE) | arp_set_keybit

    arp_note = (arp_style & 0xF0) >> 4
    # The original substitutes $74 -- a +12 relative note, an octave-up
    # arpeggio -- whenever the high nibble is zero. The player does no such
    # thing: the nibble is written into the operand of the `SBC` at $13F4
    # ($13DB `STA $13F5`), so a nibble of zero subtracts zero and both halves
    # of the alternation play the same note. Half of every arpeggio instrument
    # in the corpus (315 of 660 records) has nibble zero, so the substitution
    # invents an octave arpeggio for all of them.
    arp = (arp_style & 4) == 4
    if effects and det.effect_arp and arp_note == 0:
        arp = False
    if arp_note == 0:
        arp_note = 0x74

    left = [wave, 0x00, tail, 0xFF, 0xFF]
    right = [0x00, 0x00, 0x00, 0x00, 0x00]

    # 2nd tick: the $01 "drum" bit swaps in noise and drops the pitch. Left
    # alone here -- the player's version of it is a per-frame frequency
    # decrement at $1372-$138D, which this two-entry shape only gestures at,
    # but correcting that is a separate question from the arpeggio.
    if (arp_style & 1) == 1:
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
