"""Module-level constants of the .sng writer (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import re

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
# Effect-byte bits whose routine writes the envelope registers on every
# frame, so the note-end cut (detect.ENVELOPE_CUT_SHAPES) is immediately
# overwritten and the record's release *is* audible after all. Bit $01
# alone: over the 143 unambiguous instruments of the 33 files that have the
# cut routine, `effect & $01 == 0` predicts the cut with 98.6% accuracy, no
# false negatives and 2 false positives. `& $07` scores 86.0%, `== 0` 78.3%.
#
# The same rule looked like 59.8% when first tested, because that test ran
# over all 95 files -- in the 62 with no cut routine nothing is cut whatever
# the effect byte says, so they contributed only false positives. A
# discriminator is only meaningful on the population the behaviour occurs
# in, and that mistake is why v0.5.200 shipped the cut for every record.
EFFECT_PER_FRAME = 0x01

DRUM_SPEED_PER_FRAME = 0x0100


def _drum_speed(multiplier: int = 1, gate_skip: int | None = None) -> tuple:
    """`DRUM_SPEED_PER_FRAME` as a per-call (hi, lo) step at `-S{multiplier}`.

    Floor rather than round, and never zero: a step of zero is a sweep that
    does not move, which is further from the player than one 1/256th slow.

    **The step is per WORKING frame**, and a player with an outer gate of
    reload O (`tempo.outer_gate_skip`) runs nothing at all -- the drum block
    included -- on one call in `O + 1`. Our tempo spreads those skipped
    frames over every row (`SongSpeeds.exact_row`), so a frame of the
    player's sweep occupies `multiplier * (O + 1) / O` of our calls, the
    divisor `pulse._tri_speed` already uses for the same reason. Measured on
    Warhawk `$0F0A` and Proteus `$090A` (O 7, `-S7`): the original falls
    exactly `$0300` on every one of 82 notes and never `$0400`, so no skipped
    frame ever carries a decrement; `/7` overshot that travel by 8/7.
    """
    m = max(1, multiplier)
    if gate_skip:
        step = max(1, (DRUM_SPEED_PER_FRAME * gate_skip) // (m * (gate_skip + 1)))
    else:
        step = max(1, DRUM_SPEED_PER_FRAME // m)
    return (step >> 8) & 0xFF, step & 0xFF


# The multiplier-1 value, kept as a name because the wavetable tests and the
# method doc both quote it.
DRUM_SPEED = _drum_speed(1)


# Units of headroom required above the exact no-underflow bound before a second
# sweep step is written. _note_freq floors a formula where Goattracker's own
# table rounds, so the two can disagree by a unit or two; 32 is far more than
# that, and costs no corpus coverage (184 of 192 drum instruments still deepen).
DRUM_DEEPEN_MARGIN = 32

# Record byte +8, the waveform Goattracker writes on a note's first frame.
#
# `$09` is testbit plus gate -- Goattracker's own editor default and what this
# tool has always written. The testbit holds the oscillator's phase accumulator
# and the noise LFSR at zero, so the frame it occupies is *silent*, and it
# occupies one on every note. Hubbard's players spend 4273 such frames across
# 12 of the 83 corpus files; ours spent 9179 across 79.
#
# `$FF` is the alternative gplay.c:355-363 offers: a firstwave of `$FE` or above
# is read as a gate value and assigned straight to `cptr->gate`, leaving
# `cptr->wave` alone. So `$FF` opens the gate -- the note still attacks -- and
# the frame keeps whatever waveform was already there instead of going quiet.
# Anything below `$FE` is written to the waveform and forces the gate on.
# How long the gate is closed before each note, in *frames*. It is the low
# six bits of the instrument's gatetimer: Goattracker fetches the next note
# that many calls early and holds the gate off for them (gplay.c:905), which
# is this writer's only release between two adjacent notes.
#
# It was 2 **calls**, which is 2 frames at `-S1` and two thirds of one at
# `-S3`, against the players' own releases -- 3.3 frames on average, from the
# gate census. Measured in frames it is `frames * multiplier` calls, the same
# conversion every other rate in this file makes.
#
# **2 because 1 is worse and 3 buys nothing**, on the bytes rather than on a
# derived row: raising it to 3 changes 3 of 83 corpus files (Chicken Song,
# Mr Meaner, Rock Tells the Tale) and moves no dimension of the report, and
# 4 and 6 change exactly the same three. Lowering it to 1 changes 15 and
# costs 1.2pp of mean gate. So the constant is nearly inert, and the reason
# is that the two bounds below decide almost everywhere -- the floor for the
# single-speed files, the row for the multispeed ones.
#
# The lever is the row bound. Swept over the corpus: `row // 3` costs 1.7pp
# of gate for nothing, `2 * row // 3` and `row - 1` buy 1.6pp and 3.3pp and
# take Saboteur II's melody from 98% to 67% and 62%. `row // 2` is not a
# corpus optimum -- it is the last value before that single file breaks.
#
# `--wide-hard-restart` offers `2 * row // 3` per song, which is what a
# ceiling set by one file asks for. v0.5.276 declined to offer it, on the
# ground that a sixth `--fidelity` toggle "would double a four-hour search";
# that cost was never timed and is 8 minutes (v0.5.301), so the refusal had
# no basis and the option is searched per song like the other five.
HARD_RESTART_FRAMES = 2

FIRSTWAVE_TESTBIT = 0x09
FIRSTWAVE_GATE_ONLY = 0xFF


# A wavetable left side of $01-$0F is a delay: the entry holds whatever
# waveform is already set for that many play calls before advancing
# (gcommon.h:56-57 WAVEDELAY/WAVELASTDELAY, executed at gplay.c:698-704).
WAVE_MAX_DELAY = 0x0F

# Frames of noise the drum block writes before the voice's own waveform,
# measured off the original's trace rather than assumed: 349 of Commando's
# note onsets hold noise for exactly this many frames and then switch.
#
# **It is not 2 everywhere, and this is known to be wrong for more notes than it
# is right for.** Across every drum-flagged note in the corpus, a *pitched*
# record gets a run of 1 on 1548 notes and 2 on 934; Monty gives 1 where
# Commando gives 2 from a byte-identical routine, so the difference is in the
# surrounding order and not in any record byte. A record whose waveform carries
# no waveform bits gets noise for the whole note instead -- Hubbard's own
# comment, "ctrlreg 0 is always noise" -- and that half `_drum_entries` already
# emits correctly. Flipping this to 1 would suit the majority and break the one
# file whose drum a listener validated. See H2G-CONVERSION-METHOD.md 7.ggg.
NOISE_TICK_FRAMES = 2


SFX_DRUM_FRAMES = 2          # frames of noise per hit, measured off the trace
WAVE_JUMP = 0xFF             # left side: jump, the right side naming the row
WAVE_NOTE_BASE = 0x00        # right side: **writes the pattern's own note**. This is a
#                              `.sng` byte and `gt2reloc` inverts bit 7 of every
#                              non-command right byte on the way in (greloc.c:1340-1341,
#                              `insertbyte(rtable[c][d] ^ 0x80)`), so $00 reaches the
#                              packed player as $80 and takes the `bmi` at
#                              `mt_wavefreq` -- `adc mt_chnnote / and #$7f`. The comment
#                              here used to read "no frequency write (player.s:976-977
#                              `bne`)", which is true of the *packed* byte $00 and so of
#                              the `.sng` byte $80. See v0.5.336 and CLAUDE.md.
WAVE_NOTE_KEEP = 0x80        # right side: leave the frequency alone
WAVE_NOTE_ABS = 0x80         # ...and $80 + index is an absolute note


ARP_MAX_STEPS = 3            # the player's cycle: 0, the high nibble, the low one


# How many frames the player spends on the arpeggio's step 0 before the cycle
# starts advancing. **MEASURED, not derived** (v0.5.461), from the originals'
# own per-offset-from-attack profile at `-t 180` -- the check CLAUDE.md
# requires before emitting a newly decoded effect, and the one that had not
# been run for this one.
#
# Radio_ACE voice 2, semitone offset relative to the frequency ON the attack
# frame, frames 0-5, the four commonest shapes and their counts:
#
#     ORIGINAL   +0 +0 +7 +0 +7 +0  x232      OURS  +0 -7 +0 -7 +0 +0  x232
#                +0 +0 +5 +0 +5 +0  x206            +0 -5 +0 -5 +0 +0  x206
#                +0 +0 +4 +0 +4 +0  x24             +0 -4 +0 -4 +0 +0  x24
#                +0 +0 +6 +0 +6 +0  x20             +0 -6 +0 -6 +0 +0  x20
#
# The counts match one for one, so these are the same notes. The original
# holds step 0 for frames 0 AND 1 and puts its first raised step on frame 2;
# ours put it on frame 0 -- so the offset landed ON the attack, and siddump
# names an attack from the frequency on the frame the gate rises. That is why
# this option cost `melody` and `sequence` while leaving the attack COUNT
# untouched, which is the signature of a renamed attack rather than a wrong
# one.
#
# **THAT PAIR WAS TAKEN WITHOUT THE SONGS' PRESETS and is kept because the
# shape is what it shows; the numbers below are the ones to quote.** Under the
# shipped preset the same check on Lakers_vs_Celtics voice 2 reads `+0 -5 +0
# -5 +0 -5` x16 at head 0 and **`+0 +0 +5 +0 +5 +0` x16 at head 2 -- the
# original's own shape, sign included**.
#
# **THE A/B, AT `-t 180`, EVERY OTHER OPTION AT THE SONG'S SHIPPED PRESET.**
# Three arms: `arpeggio` OFF, ON at head 0 (what shipped), ON at head 2.
#
#     file               melody OFF   ON head 0   ON head 2
#     Lakers_vs_Celtics    0.8176      0.7758      0.8176
#     Go_Go_Dash           0.9483      0.9386      0.9483
#     Lion_Heart           0.9043      0.9030      0.9043
#     Radio_ACE            0.9406      0.8373      0.8373
#
# `sequence` moves with it (Lakers 0.8122 / 0.7742 / 0.8122, Go_Go_Dash
# 0.9499 / 0.9411 / 0.9499); `our_attacks`, `orig_attacks`, `pitch_jaccard`
# and `onset_agreement` are identical across all three arms on all four files.
#
# **So on three of the four the head makes the arpeggio FREE**: melody and
# sequence return EXACTLY to the arpeggio-off baseline while `reversal_ratio`
# goes 0.0057 -> 0.556 (Lion_Heart), 0.0181 -> 0.1265 (Go_Go_Dash) and
# 0.0 -> 0.2243 (Lakers). That is the whole oscillation measure bought for
# nothing the report can see.
#
# **RADIO_ACE IS THE EXCEPTION AND THE HEAD IS NOT ITS PROBLEM**: 0.8373 at
# heads 0, 1 AND 2 alike, against 0.9406 with the arpeggio off. Its profile
# says why the head cannot help it -- `no_test_restart` is in its preset and
# owns frame 0, so its arpeggio already lands on the original's frames (`+0
# +0 -7 +0 -7 +0` at head 0, the right FRAMES with the wrong SIGN) and adding
# a head only moves it off them again (`+0 -7 -7 +0 -7 +0`). Whatever costs
# that file 10 points of melody is a second defect, not this one.
#
# **WHAT IS MEASURED IS THE PROFILE, NOT THE ROUTINE.** Two frames is what the
# originals do; whether it is the note-start path at $1388 clearing the step
# counter *after* the frame routine has run, or the packed player's own
# one-call wavetable offset on top of a one-frame player head, is not settled
# here. Read $1400-$1446 against $1388 before changing this number.
ARP_HEAD_FRAMES = 2


# Goattracker's "inaudible waveform" range: $E0-$EF sets the waveform to
# $00-$0F (readme.txt:3.4.1, gplay.c:527). A player waveform below $10 -- gate
# alone, or nothing at all -- cannot be written literally, because $01-$0F are
# *delays*. This is the encoding for it, and the reason a wave program can carry
# `slide $01` at all.
WAVE_SILENT_BASE = 0xE0
# gcommon.h:60. $F0-$FE are Goattracker's wavetable commands and $FF is the
# jump, so no byte from $F0 up can be a waveform.
WAVECMD_BASE = 0xF0
# $D404 bit 3. With it set the oscillator is held in reset and outputs nothing
# whatever the four select bits say -- which is why `FIRSTWAVE_TESTBIT` ($09)
# is a silent frame. `$18` is that bit with triangle selected, and it is the
# **only** way to reach silence from a wavetable in the packed player: see
# `_wave_byte` for why `$E0` is not.
WAVE_TEST_BIT = 0x08
WAVE_SILENT_TESTBIT = 0x18


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
CMD_SETWAVEPTR = 8              # gcommon.h:12 -- point the wavetable at a row
CMD_SETPULSEPTR = 9             # gcommon.h:13 -- the same for the pulse table;
                                # patterns.py carries its own copy, pinned equal
                                # by tests/test_pattern_budget.py
CMD_SETTEMPO = 15
GT_MIN_TEMPO = 2                  # below this is funktempo, not a rate
TEMPO_FASTEST_STEADY = 3          # value -> tempo 2 -> 3 calls per row

# A row of TWO calls is still expressible, through the other door: CMD_FUNKTEMPO
# (gcommon.h:18) pointing at a speed-table entry `02 02` -- Goattracker's own
# recipe (readme.txt:1078-1081: "by using the funktempo command you can get
# tempo 2 ... speedtable entry: 02 02 ... gateoff timer 1 in all instruments
# and disable the pulse-optimization skipping"). The packed player loads both
# halves into mt_funktempotbl (player.s:310-316) and reloads the counter with
# `value - 1` = 1 (player.s:725-733: carry clear after `bcs`), so tick 0 comes
# every second call; gplay.c:486-487/330 is the same in the editor. The two
# conditions hold by construction here: gt2reloc is always run `-O0`, and the
# gatetimer of an instrument played on a 2-call row is bounded to 1 by
# `_hard_restart_ticks(row_calls=2)`. Only a GTS5 file has a speed table, so a
# GTS2 file keeps the steady floor.
CMD_FUNKTEMPO = 14
FUNK_ROW_CALLS = 2                # the row CMD_FUNKTEMPO + `02 02` plays
FUNK_SPEED_ENTRY = (FUNK_ROW_CALLS, FUNK_ROW_CALLS)

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
# The same gate with an *immediate* reload -- `BPL +5` rather than `+6`,
# because `LDA #imm` is two bytes where `LDA abs` is three:
#
#     C83D  DEC $CC46 / BPL +5 / LDA #$02 / STA $CC46      (Ninja)
#     C84E  LDA $CC46 / CMP #$02 / BNE skip    ; work on the reload frame
#
# 35 corpus files carry this shape and 33 of them already read a gate through
# the absolute spelling, so it is consulted **only where that one found
# nothing** -- the rule `find_relocation` and `INSTRUMENT_INDEX_SHAPE` follow.
# What the other 33 count is not established, and a wrong tempo is worse than
# the old constant.
SPEED_GATE_IMM = re.compile(rb"\xce(..)\x10\x05\xa9(.)\x8d(..)", re.DOTALL)

# THE SAME GATE WITH ITS COUNTER IN ZERO PAGE. `DEC zp` is two bytes where
# `DEC abs` is three and `STA zp` two where `STA abs` is three, so the branch
# steps over one byte fewer and reads `+5` rather than `+6`. The reload is
# still absolute -- it is a per-subtune table address, not a zero-page cell.
#
#     70C7  DEC $E9 / BPL $70CE / LDA $7405 / STA $E9   (Samantha Fox)
#
# Consulted only where BOTH spellings above matched nothing, so no file that
# reads a gate today can be moved by it. Without it Samantha Fox found no
# inner gate at all and `frames_for` fell back to 1, which -- against a real
# row of 3 -- put the whole tune three times too fast once its outer gate was
# read (`--pace`: "speed gate reads nothing frame(s) per duration unit").
SPEED_GATE_ZP = re.compile(rb"\xc6(.)\x10\x05\xad(..)\x85(.)", re.DOTALL)

SPEED_TABLE_LOAD = b"\xbd"       # LDA abs,X -- X is the subtune number
SPEED_RELOAD_STORE = b"\x8d"     # STA abs

# The gate is not the only thing counting frames. Immediately above it sits a
# second counter of the same shape but with an *immediate* reload, and on the
# frame it underflows the gate's DEC is jumped over entirely:
#
#     DEC outer / BPL +8 / LDA #O / STA outer / JMP past-the-gate
#     DEC gate  / BPL +6 / LDA reload / STA gate
#
# So the gate is decremented on O of every O+1 frames, and a row that should
# last `frames` frames lasts `frames * (O+1)/O`. That factor is why
# find_song_speeds reads low on a large minority of the corpus -- measured
# against 15 files whose row length was timed independently, the corrected
# number is within 5% on all 15 and within 1% on 10 (see whats-next.md 7b).
OUTER_GATE = re.compile(rb"\xce(..)\x10\x08\xa9(.)\x8d(..)\x4c(..)", re.DOTALL)
# **And it has a second spelling, unread until v0.5.248.** At the PSID *play*
# address the same counter ends in `RTS` -- "on the underflow call, do nothing
# at all" -- rather than jumping past the gate, and its branch is `BPL +6`
# instead of `+8` because it steps over one byte and not three:
#
#     1012  DEC $15AE / BPL $101D / LDA #$07 / STA $15AE / RTS   (Warhawk)
#
# Nine corpus files open their play routine this way -- Warhawk, Proteus,
# International Karate, Bump Set Spike, Game Killer, Thrust, Mozart, Ninja
# and Formula 1 Simulator -- and **none of them carries the `JMP` form as
# well**, so there is no question of which one applies. `SPEED_GATE`'s own
# comment names this idiom, but as the prescaler variant of three files,
# excluded because "no steady Goattracker tempo can express it": it also
# sits above a normal gate here, where it multiplies rather than replaces,
# and `_skip_gate_multiplier` is what expresses such a row when the
# denominator is small enough.
OUTER_GATE_RTS = re.compile(rb"\xce(..)\x10\x06\xa9(.)\x8d(..)\x60", re.DOTALL)

# TWO MORE SPELLINGS OF THE SAME GATE, each of which was costing a whole song.
# Consulted ONLY where the two above find nothing -- the rescue rule
# `find_relocation` and `INSTRUMENT_INDEX_SHAPE` already follow -- so no file
# that reads a gate correctly today can be disturbed by either.
#
# ZERO PAGE. The counter and its reload both live in zero page, so `DEC` is two
# bytes rather than three and `STA` likewise -- and the branch offset moves with
# them, `+5` where the absolute form needs `+6`. That is the trap this file has
# now hit three times: a signature encoding an addressing mode encodes an
# instruction LENGTH, and that length is in every branch offset around it, so
# two spellings of one idiom differ in two places at once.
#
#     7084  DEC $EA / BPL $708D / LDA #$04 / STA $EA / RTS    (Samantha Fox)
OUTER_GATE_RTS_ZP = re.compile(rb"\xc6(.)\x10\x05\xa9(.)\x85(.)\x60", re.DOTALL)

# PAL/NTSC-SELECTED RELOAD. The gate picks its reload from the KERNAL's PAL/NTSC
# flag at $02A6 (0 = NTSC), so there are two immediates and the PAL branch is the
# one this corpus runs. It also carries the value in Y rather than A --
# `LDY #imm ... STY` where every other spelling is `LDA #imm ... STA` -- which is
# why nothing anchored on an `LDA #` opcode could ever have seen it.
#
#     5084  DEC $54E8 / BPL $5096 / LDY #$02 / LDA $02A6 / BEQ $5092
#           / LDY #$04 / STY $54E8 / RTS                      (Las Vegas)
#
# This is the mechanism CLAUDE.md carries as a standing hypothesis for Skate or
# Die intro ("its speed table is indexed by the PAL/NTSC flag rather than the
# subtune"). It is real, and these are the two files that carry it.
OUTER_GATE_PAL = re.compile(
    rb"\xce(..)\x10\x0d\xa0.\xad\xa6\x02\xf0\x02\xa0(.)\x8c(..)\x60", re.DOTALL)


# A reload byte above this is not a song speed. Real corpus values are 0-8
# (f = 1..9); per-subtune tables are read past their end for files whose
# header over-counts subtunes (Commando claims 19), and the bytes that follow
# are code whose values (0x70+) would otherwise become absurd tempos.
MAX_SANE_SPEED_RELOAD = 15


# The KERNAL's PAL/NTSC flag: 0 is NTSC, non-zero PAL. A player that ships one
# binary for both territories selects its rates through it.
PAL_NTSC_FLAG_LDX = b"\xae\xa6\x02"        # LDX $02A6
# Anything that would put a different value in X between that load and ours.
_X_RELOADERS = frozenset({0xA2, 0xAE, 0xA6, 0xB6, 0xBE})
# How far back to look. The three loads of Skate or Die intro's init span 18
# bytes from its `LDX $02A6`; 24 covers that without reaching the previous
# routine. Widening it is what would start matching an unrelated `LDX $02A6`.
PAL_NTSC_WINDOW = 24
# Which entry to take when a table is flag-indexed rather than subtune-indexed.
# This corpus is PAL and every measurement here compares against a 50 Hz
# trace, the same reason `OUTER_GATE_PAL` reads its second immediate.
PAL_NTSC_ENTRY = 1


# Any `LDA table,X` -- used only to find *other* per-subtune tables read the
# same way, near the one `_find_outer_gate` has already found.
_ABS_X_LOAD = re.compile(rb"\xbd(..)", re.DOTALL)

# How far either side of a found `LDA table,X` to look for a second one, when
# bounding that table's real length (see `_adjacent_table_bound`). Generous
# enough to span the handful of instructions between two loads in the same
# init loop (Knucklebusters and W_A_R's are 6 bytes apart); the corpus has
# no closer false match at this width or twice it (checked at 32/64/128).
_ADJACENT_TABLE_WINDOW = 32


# How far the -S factor may be raised to make a fractional row exact.
#
# The bound is playability, not fidelity. Six calls a frame is ~300 a second
# and about 9k cycles of a PAL frame's 19656 at 1.5k a call -- heavy but
# real. Ten would be three quarters of the frame and twenty impossible, and
# the rows those would buy are within ~1.3% of a whole number anyway (3.02,
# 3.03, 4.04), so they round.
#
# v0.5.121 capped this at 4 because -S5 appeared to regress three files. It
# did not: siddump samples once per frame whatever the call rate, so tracing
# a multiplier-5 file at -m5 discards four calls in five along with the gate
# edges inside them (v0.5.124). Measured at equal sampling with
# `fidelity.py --equal-calls`, nothing regresses and three files gain --
# Kings_of_the_Beach_intro, the supposed worst case at 96% -> 61%, is 96% at
# -S5.
#
# v0.5.313 raised it 6 -> 10, and the reason is not the size of q but **how
# badly the row rounds without it**. This comment used to say the rows beyond
# six "are within ~1.3% of a whole number anyway, so they round", which is
# true of most of them and false of exactly the three shapes a cap of 10
# reaches:
#
#     16/7   = 2.286  ->  2   12.5% out   Warhawk, Proteus
#     20/9   = 2.222  ->  2   10.0%       Game Killer
#     33/10  = 3.300  ->  3    9.1%       Delta Mix-E-Load, IK, Kentilla
#     -------------------------------------------------------------------
#     81/20  = 4.050  ->  4    1.2%       After 8, Rikky
#     113/28 = 4.036  ->  4    0.9%       Pandora
#     109/36 = 3.028  ->  3    0.9%       Sanxion, Sigma Seven
#     339/112= 3.027  ->  3    0.9%       IK+, I Ball, Nineteen, ...
#     384/127= 3.024  ->  3    0.8%       BMX Kidz, Wiz, Skate or Die, ...
#
# A 7.5x gap between the worst rounder and the best non-rounder, with nothing
# in between -- so the cap is a property of the corpus rather than a number to
# tune. Ten calls a frame is about three quarters of a PAL frame's 19656
# cycles, which is heavy; 127 would be 6350 Hz, which is not a call rate at
# all. The six files it reaches all gain: `drift` -> 0.00 on every one, `wave`
# +16.1pp mean, `gate` +30pp, and `retrig` toward 1.00. See section 8.
MAX_ROW_DENOMINATOR = 10


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


# Goattracker's wavetable left-column ranges (gcommon.h:56-61).
GT_WAVE_LAST_DELAY = 0x0F
GT_WAVE_FIRST_CMD = 0xF0
GT_WAVE_LAST_CMD = 0xFE
GT_WAVE_JUMP = 0xFF
GT_WAVE_NO_NOTE = 0x80


EFFECT_NOTE_ALT_MASK = 0x08     # bit $08's two-note alternation (7.hhhh's
#                                 other half); the pulse-width accumulator in
#                                 the disjoint dialect `det.pulse_lo_base`
#                                 reads the same bit
EFFECT_PITCH_SEQ_MASK = 0x10    # the effect byte's bit-$10 arpeggio
# Bit $40: a fixed attack pitch out of the player's own note table. It also
# halves bit $04's attack -- see `_two_stage_frames`, which is where the
# measurement behind that is recorded.
EFFECT_FIXED_PITCH_MASK = 0x40
# Bit $80: the sfx drum. Named here because bit $40's pitch is only emitted
# from the two-stage block on a record that does *not* set it -- see the call
# site, and section 7.qqq for why the two cannot share a frame.
EFFECT_SFX_DRUM_MASK = 0x80
WAVE_GATE_BIT = 0x01            # $D404 bit 0
CMD_VIBRATO = 0x04              # gcommon.h:8
GT_FIRST_NOTE = 0x60            # gcommon.h:48 FIRSTNOTE
GT_LAST_NOTE = 0xBC             # gcommon.h:49 LASTNOTE
GT_REST = 0xBD                  # gcommon.h:50 REST -- "no new note", not a stop
GT_KEYOFF = 0xBE                # gcommon.h:51 KEYOFF -- patterns.GT_KEYOFF


CMD_TONEPORTA = 0x03            # gcommon.h:7 -- patterns.CMD_TONEPORTA
CMD_SETAD = 0x05                # gcommon.h:9 -- patterns.CMD_SETAD
CMD_SETSR = 0x06                # gcommon.h:10 -- patterns.CMD_SETSR


# --- A tie whose landing note restarts the instrument -------------------------
#
# `patterns._build_raw_pattern` spells a tie as `CMD_TONEPORTA 00`, and both
# Goattracker players answer that command by skipping the WHOLE new-note init:
# gplay.c:353 `if (cptr->newcommand != CMD_TONEPORTA)` wraps the firstwave,
# the wave/pulse/filter pointer reloads and the `iptr->ad/sr` writes
# (:353-398), and player.s `cmp #TONEPORTA / beq mt_nonewnoteinit` jumps past
# the same block. That is right only where the original skips its instrument
# start on the landing note as well.
#
# The legato-marker players (`det.note_flag`) do not skip it for a tie. Auf
# Wiedersehen Monty, read at d52a1bf:
#
#     E569  AD 2D EB  LDA flag        ; the note byte, bit 7 included ($E5A7)
#     E56C  30 35     BMI $E5A3       ; bit 7 set -> skip the start
#     E56E  BD B0 EC  LDA pulse,X / STA $D402,Y ... $D403, $D405, $D406
#     E58F  A9 00     LDA #0 / STA $EA27,X / STA $EA24,X   ; effect state
#     E597  68        PLA / STA $EB72,X ...                ; drum counter
#     E5A3  AD 21 EA  LDA wave / STA $E924,X               ; waveform, always
#
# and status bit 5 is tested only at the note's END (`$E5C3-$E5D4`, `AND #$20
# / BNE` past the gate-off), so a tie's landing note with bit 7 clear keeps
# its gate open AND restarts pulse, envelope, effect state and drum counter.
# Its voice-3 drum is where that is audible: every such landing is a noise
# tick the original sounds and `CMD_TONEPORTA` drops (orig frame 1556: no
# gate change, PW 200, ADSR 09B9, noise at 1557). Delta's `$BF31-$BF68` is
# the same block byte for byte, and `legato_tie_family` finds it, with the
# flag the note store wrote, in 34 corpus files (at 3b1c66d).
#
# Measured HISTORICALLY (2026-10-03, 3b1c66d dirty, under presets, sub 0,
# 60 s, gt2reloc + siddump-rt, C:/t/tie-legato-clone/ticks.py): Auf
# Wiedersehen Monty's 33 respelled rows take voice-3 noise ticks 210 -> 269
# (original 240) and exact hits 45 -> 61; the new set is a superset of the
# old and 57 of its 59 additions sit within 2 frames of an original tick.
# The overshoot past 240 is not in the additions: 30 of the common 210 sit
# 4-6 frames from every original tick (nearest-offset census, both arms).
# Gate-on edges 106/149/194 in all three.
# Only -S1 songs are respelled: see the multispeed note in `build_sng`.
#
# Goattracker's spelling for "gate held, instrument started" is a LEGATO
# instrument: gatetimer bit $40 skips the hard-restart gate-off at the note
# fetch (gplay.c:930, player.s `mt_nohr_legato ... bcs mt_rest`; greloc.c:347
# sorts such records last), and the note then takes the ordinary init. So the
# tie becomes a plain note on a clone of its instrument with `$40` set. The
# clone's firstwave is the record's own waveform with the gate where the
# record's is `FIRSTWAVE_TESTBIT`: the original re-stores its waveform at the
# landing ($E5A3) and resets no oscillator, and a test-bit frame on a held
# note would be a click the original never makes.
#
# A landing with bit 7 SET keeps `CMD_TONEPORTA 00`: there the player skips
# its start, which is exactly what that command says. In Auf Wiedersehen Monty
# that is 119 of its 150 tie events.
LEGATO_TIE_GATE_SHAPE = "AD ?? ?? 30 ?? BD ?? ?? 99 02 D4"
LEGATO_TIE_FLAG_STORE_SHAPE = "C8 B1 ?? 8D ?? ?? 29 7F"
GATETIMER_LEGATO = 0x40          # gplay.c:930, greloc.c:347


# The state a channel enters its first pattern in: no row before it, command 0
# (gplay.c:187-190 zeroes `command`/`newcommand` on song init; player.s
# `mt_resetloop` zeroes `mt_chnnewfx` with the rest of the channel block).
SONG_START_ROW = ()


# --- Expanding vibrato: the apply loop that adds the note's age ---------------
#
# Five corpus files (Arcade_Classics, BMX_Kidz, Mega_Apocalypse, Ricochet,
# Skate_or_Die_intro) carry a vibrato routine that reads the same $78/$07 byte
# as Warhawk's and computes a different depth from it. Warhawk's step is the
# semitone interval shifted (VIBRATO_DEPTH_SHAPES); this one adds the note's
# AGE IN FRAMES to the interval's high byte first, BMX_Kidz $AFA3-$AFC6:
#
#     BD 43 B3  LDA note,X / ASL / TAY / SEC
#     B9 6E B2  LDA freqlo,Y / F9 6C B2  SBC freqlo-2,Y / 85 F9  STA lo
#     B9 6F B2  LDA freqhi,Y / F9 6D B2  SBC freqhi-2,Y
#     7D 88 B3  ADC age,X          ; <-- the per-voice frame counter
#     4A        LSR A              ; halve the high byte (bit 0 dropped)
#     CE 50 B3  DEC shift / 30 06 BMI done / 4A 66 F9 LSR / ROR lo / JMP
#
# `age,X` ($B388 there) is zeroed by the note fetch and INC'd once per frame
# after the register write ($B193), so the step grows by 128 >> shift units
# every frame the note holds -- 16 a frame at shift 3, whatever the pitch.
# The apply loop then centres the swing on the note (`- (bound >> 1) * step
# + ctr * step`, ctr walking 0..bound), so the peak-to-peak is `bound * step`
# and it widens for as long as the note lasts. Traced on BMX_Kidz's $0878
# (B-6, interval $0760): the frames read +172, +344, +204, 0, -236, -472 --
# steps 172, 172, 204, 204, 236 at ages 2, 3, 4, 5, 6, which is the formula
# below to the unit. Over an 84-frame note the swing reaches three semitones
# and the median cycle measures 11.4% of the pitch, against 2.2% from a
# static entry: `depth` read 0.195 on BMX_Kidz, 0.056-0.149 on the other
# four, and 0.50-1.34 on all 51 static-shaped files (build/fidelity.json at
# v0.5.487, -t 180, presets). Historical figures; the population split is
# what the shape reproduces, and tests/test_vibrato.py pins it.
#
# A Goattracker instrument holds ONE speed-table entry, so the growth cannot
# live in the record. It can live in the pattern: a `4xy` on a hold row
# swaps the speed-table entry for that row without resetting the phase
# (player.s `mt_tick0_34` stores the parameter and leaves `mt_chnvibtime`
# alone; only a new note resets it), and the note-relative entries at
# shifts 3, 2, 1, 0 are a staircase of doublings the linear ramp can be
# rounded onto. That is what `_expanding_vibrato_pass` writes: per hold row,
# the entry whose swing is nearest the original's in log space, on every
# free row from the first that leaves the instrument's own level.

# The two spellings of the loop above, anchored like VIBRATO_DEPTH_SHAPES on
# the `ASL / TAY / SEC / LDA freqlo,Y` that names the note table, and
# extended through the high-byte subtraction to the ADC that names the
# counter. Absolute (`7D`, `CE`) and zero-page (`75`, `C6`) operands are two
# instruction lengths and so two shapes (CLAUDE.md, "A signature encodes an
# addressing mode").
EXPANDING_VIBRATO_SHAPES = (
    "0A A8 38 B9 ?? ?? F9 ?? ?? 85 ?? B9 ?? ?? F9 ?? ?? 7D ?? ?? 4A CE ?? ?? 30",
    "0A A8 38 B9 ?? ?? F9 ?? ?? 85 ?? B9 ?? ?? F9 ?? ?? 75 ?? 4A C6 ?? 30",
)
EXPANDING_VIBRATO_TABLE_AT = 4      # `B9 lo hi`: entry 0 of the note table
EXPANDING_VIBRATO_COUNTER_AT = 17   # `7D lo hi` / `75 zz`: the age counter


# The fixed-interval arpeggio's counter mask Commando's block divides by:
# `AND #$01 / BEQ` -- up on every odd call. The one-call alternation the
# untimed shape and the tick shape emit is this mask's, and only this mask's;
# the other three the corpus carries ($02, $04, $07) are DUTY CYCLES, and
# `fixed_arp_duty_entries` is what emits them.
FIXED_ARP_PARITY_MASK = 0x01

# The two branch senses the block is spelled with. `BEQ` takes the base path
# on a ZERO result, so the octave is up where the masked counter is nonzero;
# `BNE` is the same block with the paths swapped (Zoids, One_Man_and_his_Droid).
BEQ, BNE = 0xF0, 0xD0


# `LDA #$00 / STA counter` -- the new-song path's reset, which sits within
# this many bytes of the play entry's `INC counter` in every file that has one
# (`INC ctr / BIT flag / BMI / BVC / LDA #0 / STA ctr`, 15 bytes).
FIXED_ARP_RESET_WINDOW = 24

# An outer gate ending IMMEDIATELY before the `INC counter`, so the counter
# steps on R of every R+1 play calls rather than on every one. Two spellings
# in the corpus, both read off the files (v0.5.489):
#
#     0826  DEC $0C8C / BPL +6 / LDA #$09 / STA $0C8C / RTS       (Game_Killer)
#     C012  DEC $C53A / BPL +9 / LDA $C539 / STA $C53A / JMP $C3C5 (Rasputin)
#
# Game_Killer's reload is the immediate 9; Rasputin's `$C539` is written by
# the track's own `$FE nn` tempo command (tracks.py) and runs 2, 3, 5, 10,
# 60, 120, 6 and 2 across one lap of subtune 0. With the step skipped one
# call in R+1 the counter is not the FRAME number -- but the gate's `RTS`
# skips the whole player, sequencer included, so the counter IS the number
# of calls that passed the gate, and the sequencer's rows are counted in
# the same calls. Through v0.5.490 this read "no phase can be walked for
# these two" and both took residue 0; the walk in `fixed_arp_phases` is in
# the player's own passing-call clock, where the gate is invisible, and
# `fixed_arp_counter_base` reads the reset for a gated counter as for any
# other. What the gate DOES change is the length of a counter step in
# frames, (R + 1) / R -- `_gate_calls`, applied to the duty's call count in
# `_wavetable_entries`. Rasputin's DUTY moves with the tempo: at the
# opening's R = 2 its `$02` mask sounds three frames and three (12 onsets in
# the trace), and at R >= 5 the two-and-two the mask names (232 of 293
# octave onsets in a 240 s trace, `bbuu`). A wavetable cannot follow a
# tempo command, so Rasputin's records take the mask's own reading and
# `tempo_duty_split_plan` gives the notes played at R = 2 a clone stepping
# three calls; its cell reload is not a `SongSpeeds.skip`, so the record's
# own step stays one frame.
FIXED_ARP_GATED_INC = (
    re.compile(rb"\xce..\x10\x06\xa9.\x8d..\x60$", re.DOTALL),
    re.compile(rb"\xce..\x10\x09\xad..\x8d..\x4c..$", re.DOTALL),
)


# **A duty record played under TIE CHAINS needs its octave locked to the
# ROW, not to the counter.** Chimera's two such records (GT 5 and 8, ADSR
# $0060 / $BF00) play almost nothing but tie rows -- `CMD_TONEPORTA $00` on
# 377 of 380 and 157 of 161 note rows -- re-pitching every 3 frames (1603 of
# 1707 re-pitches 3 frames apart, every one on a multiple of 3 from the
# chain's attack; `C:/t/chimera-gk-duty/probe_rows.py`). The original
# writes each tied note's BASE on its fetch frame, its octave block not
# running there, and the counter's octave on the frames after: `b u u` per
# row, plus one base frame in eight. The duty shape cannot carry that, for
# a reason in the packed player rather than in the shape: a tie row's
# effect 3 with speed $00 (player.s `mt_effect_3` -> `mt_effect_3_found`,
# gplay.c's `CMD_TONEPORTA` `!cmddata`) re-writes the note's base on EVERY
# call whose wavetable entry writes no note -- an unfinished delay
# (`inc mt_chnwavetime,x / bne mt_wavedone`) or a `$80` right side -- on
# every tick but 0, where `REALTIMEOPTIMIZATION` runs no continuous effect.
# The duty shape holds its octave on delay entries, so a tied row sounded
# `b b b` (v0.5.494: `vib` 0.48, 2853 reversals against 5944, the two
# records' 2763 + 778 sounding 1143 + 394). Writing the octave on EVERY
# call instead (measured, rejected) re-pitched each row on tick 0, a frame
# ahead of the original, and sounded `u u u`: `vib` 0.48 -> 0.48 and frame
# agreement on the two records' frames 0.457 -> 0.309.
#
# What reproduces the original is a loop of one ROW: nothing on tick 0 (the
# previous note's octave holds, as the original's last frame of a row
# does), nothing on tick 1 (the tie writes the new base -- the original's
# fetch frame), the octave on ticks 2..R-1. Measured on Chimera at -t 180
# (`C:/t/chimera-gk-duty/variant2.py`): `vib` 0.48 -> 0.85, `tie` 0.66 ->
# 0.80, frame agreement 0.457 -> 0.870, ADSR $0060's reversals 2764 against
# the original's 2763, and no other column moved. The counter's own base
# frame (one in eight) is NOT carried: a 24-frame loop carrying it at the
# record's majority residue measured worse (agreement 0.796, `vib` 0.77).
#
# **RETRACTED (v0.5.496): "because a chain's residue is its first attack's,
# not the record's" was not the cause.** The residue was wrong -- the record
# majority counts tie rows too, so Chimera's ADSR $0060 record votes 0
# while all 6 of its chain attacks, all 3 of $BF00's and every one of the
# original's chains of 144 frames or more sit on 2 -- but at the chain's
# residue the counter's base frame is still not worth carrying, for a reason
# in the packed player: on TICK 0 the wavetable's relative note is already
# the NEXT row's (player.s `mt_newnoteinit` stores `mt_chnnote` before the
# `cmp #TONEPORTA / beq mt_nonewnoteinit` that runs the wavetable after
# it). A base frame on tick 2 can be written, but the octave's return on
# the tick 0 after it, and a base frame landing on tick 0 itself, can only
# be the next note's. Measured on Chimera at -t 180 against this shape
# (agreement on the two records' frames 5241 of 6024, `vib` 0.847, `tie`
# 0.799; `C:/t/tie-chain-counter-base`): the counter's state written on
# ticks 2.. and on tick 0 where it turns, at residue 2 -- tick-2 base frames
# 194 of 198 right where none were, the 177 tick-0 returns now the next
# note's octave, agreement 5242, `vib` 0.829, `tie` 0.797; the same with
# nothing on tick 0 -- 195 tick-0 frames base where the original is up,
# agreement 5240, `vib` 0.772, `tie` 0.766. Every arm trades its gained
# frames one for one and loses reversals. The original's tie rows DO sound
# the counter's base frame (on the two frames after the fetch frame, 452 of
# 456), so this is a limit of the spelling, not of the reading.
FIXED_ARP_TIE_SHARE = 0.5      # more than this share of the notes are ties


# Rasputin's duty follows its tempo, and a wavetable cannot. Its outer gate
# reloads from the cell the track's `$FE nn` writes (`FIXED_ARP_GATED_INC`),
# so a counter step is (R + 1) / R frames with R moving mid-song: at the
# opening's R = 2 the `$02` mask sounds three frames and three, at R >= 5 the
# two-and-two the mask names. **Measured** (v0.5.494, siddump -t 30 of
# subtune 0, `C:/t/rasputin-tempo-duty/measure_duty.py`): the original's
# voice-0 octave onsets read `bbbuuubbbuuu` on 14 of 16 and ours
# `bbuubbuubbuu` on all 16 -- an 8.3 Hz octave trill played at 12.5 Hz on
# every held note of the 23 s opening; a `--vice -t 30` A/B with GT
# instrument 7 alone at three calls a step moved `vib` 3.61x -> 3.10x and
# `tie` 1.18 -> 1.08 and nothing else (`C:/t/rasputin-tempo-duty/ab.md`).
# So the instrument is SPLIT by position: a clone whose duty steps
# `tempo / frames` calls -- the row's own length over the counter steps in
# it -- for the notes played where that is a whole number other than the
# file-wide step, and the record for the rest. A tempo whose quotient is
# not whole (Rasputin's 5, which is R = 3, 5 and 6 rounded together) keeps
# the file-wide step, which is what it had.
TEMPO_DUTY_MAX_CLONE = GT_TEMPO_INSTRUMENT - 1


# The per-note fixed-arp phase (METHOD 7.bbbbbb's "opened, not built"). The
# counter's residue on a note's attack frame is static, but `fixed_arp_phases`
# gives each RECORD one residue, the majority of its notes', so a record whose
# notes attack on more than one residue sounds the minority out of phase:
# Hunter_Patrol (rows of 3 frames, so consecutive rows alternate parity)
# attacks its instrument 11 60:36 across the parity mask's two residues, and
# Game_Killer's one melodic record cycles 1 -> 7 -> 5 -> 3 across its 7-frame
# notes at -S9 -- a four-way tie the vote resolves to 1, whose base frame
# (offset 7) never sounds before the next attack, so the record plays an
# unbroken octave. A residue whose notes are within this factor of the
# majority's gets a clone of the record carrying its own wavetable, and each
# such note is renamed to it; a rarer residue stays on the record.
FIXED_ARP_SPLIT_FACTOR = 2


# The longest `nibble_gate_runs` cycle, in halves, a record may take. Every
# half is a waveform entry and a hold, so a cycle costs at least twice its
# halves -- and the table is laid out greedily (`_wavetable_layout`), so a
# record that grows takes the room a LATER record's own shape needed.
# Measured at v0.5.496 with no cap: International_Karate and Kentilla (O 10,
# so a one-step cycle is 10 halves, 21+ entries a record) moved their
# one-step records and, through the budget, cost IK records 12, 14, 15 and
# 16 their phased tick shapes and Kentilla record 5 a third of its sweep.
# Four is Formula_1_Simulator's and Las_Vegas_Video_Poker's cycle (O 4);
# both move only their arpeggio records under it.
NIBBLE_GATE_MAX_HALVES = 4


# Steps the player itself can take: it sweeps once per frame for `W - 1`
# frames, and section 7.ii measured W across the corpus at 2-9 ticks. So eight
# is the deepest sweep any note is actually held long enough to receive, and a
# chain longer than that is not fidelity -- it is table space spent on frames
# the note has already finished. Before this cap the safe bound alone produced
# a 136-step chain and drove three files to the 255-row table ceiling.
#
# It is a corpus-wide stand-in for the per-record number `_drum_duration_steps`
# now derives, and the two are both applied: whichever is smaller wins.
DRUM_MAX_SWEEP_STEPS = 8


# The bounds engine's reseed test as Saboteur_II spells it -- `LDA note /
# BMI skip / LDA rec+0,X / STA $D402,Y / PHA / LDA rec+1,X / STA $D403,Y /
# PHA` ($F162-$F174) -- and the only spelling `PulseBoundsSim`'s reseed rule
# has been validated against (Saboteur_II and Food_Feud, 1314/1314 and
# 1554/1554 onsets). 28 of the 42 preset files carrying the engine have it;
# the 13 that test something else before the seed copy (After_8 `$11A4 LDA
# $1684 / BNE`) and IK_plus, which writes $D402 another way, have not been
# read, and a walk that reseeds them on the note byte's bit 7 would be a
# guess about a player. `tests/test_pulse_phase.py` re-counts the 28.
PULSE_RESEED_GATE = "AD ?? ?? 30 ?? BD ?? ?? 99 02 D4 48 BD ?? ?? 99 03 D4 48"


# `LDA instr,X / ASL / ASL / ASL / TAY / STY idx`: the effects path turning
# a voice's instrument number into the record offset the sweep's `LDY idx`
# reads. The three shifts are the 8-byte stride, so a player with another
# stride is not this shape.
_TRI_INSTR_CELL = rb"\xbd(..)\x0a\x0a\x0a\xa8\x8c"


# --------------------------------------------------------------------------
# The packed size of a pattern, and the budget the phase writer runs against.
#
# greloc.c's `packpattern()` (v2.77, greloc.c:1715) packs each pattern for the
# player and returns -1 past 256 bytes; gt2reloc then prints "PATTERN xx IS
# TOO COMPLEX (OVER 256 BYTES PACKED)!" to the console that does not exist
# headless, writes no file and exits 0. A command/data pair costs two packed
# bytes wherever it CHANGES from the row before, and CMD_SETPULSEPTR on nearly
# every note row of a 127-row pattern changes on nearly every one -- which is
# what refused Rasputin at -S2 under `pulse_phase` while the `multiplier == 1`
# gate in convert.py was the only thing keeping the option off that file.
# `budget_pulse_phase_commands` runs this arithmetic over the finished rows of
# every pattern and re-places the phase commands first-fit, dropping the one
# that would cross the limit; the note then opens on the record's own width,
# exactly as every note did before the option. `tests/test_pattern_budget.py`
# keeps a second reader of the same arithmetic and walks the corpus with it.
# --------------------------------------------------------------------------

PACKED_PATTERN_LIMIT = 256
_PACK_FX, _PACK_FXONLY, _PACK_FIRSTNOTE = 0x40, 0x50, 0x60


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


# All three voices, because the player's routing is a LIVE accumulator and
# nothing static names the voice an instrument will play on. See
# _ilv_filter_entries.
#
# **THAT SECOND CLAUSE IS FALSE, MEASURED AT v0.5.461: A STATIC READING
# PREDICTS ALL SIX ORIGINALS.** The voices each original actually routes,
# taken from its own trace ($D417's low nibble with a passband selected,
# `-t 180`):
#
#     file               routes            frames   ctrl low nibble
#     Radio_ACE          voice 2            2688    $4
#     Lion_Heart         voice 2            8954    $4
#     Go_Go_Dash         voices 2 and 0+2   1172    $4 x868, $5 x304
#     Sun_Never_Shines   voices 0 and 2     8997    $5 x7657, $1 x1340
#     Lakers_vs_Celtics  none                  0    $0
#     Pacific_Coast      none                  0    $2 x6, no passband
#
# And the static predictor -- **the voices whose orderlists play a record
# carrying `FILTER_ENABLE_BIT`** -- gives exactly that set on every one:
# Radio_ACE voice 2 alone plays GT 9; Lion_Heart voice 2 alone plays GT 5 and
# 15; Go_Go_Dash voices 0 and 2 play GT 9; Sun_Never_Shines voices 0 and 2
# play GT 3/9 and 6; Lakers plays none; Pacific_Coast voice 1 plays GT 7. Six
# for six, including both files that route nothing.
#
# It is computable HERE: `build_sng` already receives `tracks` and `patterns`,
# so the map from instrument to the voices that name it needs no new plumbing
# through `convert()`. (`instr 00` is inheritance, so the quantity is the
# instruments a voice NAMES, not the rows it fills -- CLAUDE.md's rule.)
#
# **NOT NARROWED YET, AND THE REASON IS THAT IT WOULD MOVE NO COLUMN.**
# `fidelity._filter_side` counts a frame as filtered when ANY routing bit is
# set and a passband is selected, so routing one voice instead of three leaves
# `filt` identical -- and `filt` is where the real defect shows: ours reads
# 6682 against 2688 on Radio_ACE, 6526 against 1172 on Go_Go_Dash, and **1366
# against 0 on Pacific_Coast**. That is a DURATION difference, not a width
# one, and the two want fixing together rather than in two byte-changing
# passes over one emitter.
#
# Two readings that would have explained Pacific_Coast were tried and REFUTED
# on the bytes, so the next attempt need not repeat them. `prog[7] & 0x0F` is
# **zero in every program of all six files**, so the classic path's guard
# (`if not resctl & 0x0F: continue`) transfers to nothing here. And `+5` is
# the ping-pong LOWER BOUND, not a duration -- `IlvFilterInfo`'s own field map
# says so, and Go_Go_Dash filters 1172 frames with `+5 = 00`.
#
# Where to start instead: the routing store is gated on a GLOBAL cell.
#
#     1807  AD 8C 1A  LDA $1A8C
#     180A  F0 17     BEQ $1823      ; zero -> $181B LDA #$00 / STA $D417
#     180C  AD 65 1A  LDA $1A65      ; resonance
#     180F  19 87 1A  ORA $1A87,Y    ; the live per-voice routing bits
#     1812  8D 17 D4  STA $D417
#
# and that code is BYTE-IDENTICAL in Pacific_Coast and Radio_ACE, so whatever
# silences the one and not the other is in the data reaching `$1A8C` or
# `$1A87,Y`, not in the player.
#
# **THE DISARM IS READ NOW (v0.5.461), AND SO IS THE PRICE OF EMITTING IT.**
# `$1A65` is the live per-voice routing ACCUMULATOR, and the note path both
# arms and disarms it:
#
#     15B1  29 20     AND #$20        the record's filter-enable bit
#     15B3  D0 1E     BNE $15D3       set -> ARM
#     15B5  BD 90 1A  LDA $1A90,X     clear: was this voice armed?
#     15BD  A9 00     STA $1A90,X       yes -> forget it,
#     15C7  BD 8D 1A  LDA $1A8D,X       and MASK THE VOICE'S BIT OUT:
#     15CA  2D 65 1A  AND $1A65
#     15CD  8D 65 1A  STA $1A65
#     15D3  A9 01     STA $1A90,X     the arm, and
#     15D8  AD 65 1A  LDA $1A65 / ORA $1A67,X / STA $1A65
#     15E4  BD 77 1A  LDA $1A77,X / ORA $1A7A,X / BNE   a ZERO step exits
#
# with a second, self-modified clear at `$1725 BIT $173F / BEQ` -> `$1732 LDA
# $1A65 / AND $1A8D,X`. **Goattracker cannot express any of it**: there is one
# global $D417, and `FILT_STOP` ends the TABLE rather than the routing, so
# whatever a `FILT_SET_PARAMS` last wrote stands for the rest of the song.
# That is the whole over-production.
#
# **A CLEAR BLOCK WAS BUILT AND MEASURED IN TWO FORMS, AND BOTH BREAK THE ONE
# CONSTRAINT THAT MATTERS -- so neither shipped.** Filtered frames ours
# against the original's, `-t 180`, with `melody` and `sequence` IDENTICAL to
# the shipped arm on all six files in every arm:
#
#     file               shipped   blanket clear   clear on filtering voices   orig
#     Radio_ACE          6682      2688 EXACT      2688 EXACT                  2688
#     Pacific_Coast      1366         0 EXACT         6                           0
#     Go_Go_Dash         6526       604             668                        1172
#     Lion_Heart         8994      3845            5057                        8954
#     Sun_Never_Shines   8992      4370            4370                        8997
#
# So the clear fixes exactly the files the task names and **loses the two that
# were already within 0.5%**, which is what its verify forbids. Restricting
# the clear to instruments played by a voice that ALSO plays a filtered one --
# the static map that predicts every original's routing -- recovers a third of
# Lion_Heart and none of Sun_Never_Shines, so the per-voice map is not the
# missing piece either.
#
# **WHAT THAT LEAVES, precisely.** Lion_Heart's voice 2 plays four
# instruments of which two are filtered, and its ORIGINAL holds the circuit in
# for 8954 of 9000 frames -- so on that file an unfiltered record on the
# filtering voice does NOT take it out.
#
# **THE TWO READINGS THAT COULD HAVE EXPLAINED IT ARE BOTH REFUTED (v0.5.461),
# so the disarm is exactly as described above and the cause is elsewhere.**
#
# * *'the `AND #$20` at $15B1 is reached on a path narrower than every note
#   start'* -- NO. It sits at the end of the pulse-write block, but `$154D`
#   branches straight to **`$15AB`**, one instruction above it, so a record
#   with no pulse work still reaches the test. Both entries converge on it.
# * *'`$1A90,X` is not the per-voice latch this reading takes it for'* -- it
#   is, and the byte it guards is not stale either. `$1AC1` -- the cell
#   `$15AE` loads and `$15B1` masks -- has TWO writers: the note-start path
#   (`$1256 LDA $1B52,X / $1259 STA $1AC1`) and a PER-FRAME refresh at
#   `$13F2 LDA $1B52,Y / $13F5 STA $1AC1`, beside `$13F8 LDA $1B51,Y`. So the
#   tested byte is the current voice's current record, reloaded every frame,
#   and the mask at `$15C7` fires once per arm->disarm transition because
#   `$1A90,X` is cleared at `$15BD` on the way through.
#
# **OCCUPANCY, MEASURED (v0.5.461), AND IT DISSOLVES THE PUZZLE.** Per FRAME,
# which record each voice of each ORIGINAL is playing -- keyed by the ADSR
# pair `onset`/`hold` already key on, over frames with a waveform selected:
#
#     file               voice  frames on a filtered record   original routes
#     Radio_ACE            2     2688 of 8998 (29.9%)            2688  EXACT
#     Lion_Heart           2     8391 of 8998 (93.3%), 43 not    8954
#     Sun_Never_Shines     0     7532 of 8998 (83.7%)            8997
#                          2     6204 of 8998 (68.9%)
#     Go_Go_Dash           0      272, voice 2 1020              1172
#     Pacific_Coast        1        6, and no passband              0
#
# **Radio_ACE is exact to the frame**, which confirms the whole model: the
# player routes for as long as a filtered record is sounding. And Lion_Heart's
# 8954-of-9000 needed no mechanism at all -- its filtered pair simply occupies
# 93% of voice 2. The census that made it look like a contradiction counted
# instruments NAMED, not frames OCCUPIED.
#
# **SO THE OVER-PRODUCTION IS STRUCTURAL, AND A THIRD ARM PROVED WHERE THE
# LIMIT SITS.** A Goattracker filter pointer belongs to an INSTRUMENT and
# fires on every voice that plays it; the player's mask belongs to a VOICE.
# Arm 3 -- clear only from instruments played EXCLUSIVELY on voices that also
# play a filtered record, the narrowest rule that can reproduce the player --
# reads:
#
#     Radio_ACE 6682 -> 4602 (orig 2688)   Lion_Heart 8994 PRESERVED (8954)
#     Go_Go_Dash 6526 ->  836 (orig 1172)  Lakers 0 PRESERVED (0)
#     Pacific_Coast 1366 UNCHANGED (0)     Sun_Never_Shines 8992 -> 4370 (8997)
#
# Lion_Heart survives where arms 1 and 2 destroyed it, so the rule is right as
# far as it goes -- and it still fails the task's constraint, because
# **Sun_Never_Shines has TWO filtering voices**. With one $D417, voice 0's
# unfiltered record clears a circuit voice 2 is still holding, which the
# player never does. Pacific_Coast is unchanged for the mirror reason: its
# voice 1's unfiltered records are shared with voices 0 and 2, so none of them
# qualifies and no clear is emitted at all.
#
# **THE HONEST STATEMENT OF THE LIMIT**: a clear is expressible only where
# exactly ONE voice ever filters AND its unfiltered records are played nowhere
# else. Radio_ACE, Lion_Heart and Pacific_Coast have the first property;
# Sun_Never_Shines and Go_Go_Dash do not; and Radio_ACE and Pacific_Coast fail
# the second. Emitting the routing faithfully needs a per-voice filter, which
# the format does not have.
#
# **AND THAT IS WHY ARM 3 SHIPS GATED RATHER THAN NOT AT ALL (v0.5.467).**
# The limit above is a statement about which FILES a clear can be expressed
# on, so it is a gate, not a refusal. `_ilv_clearing_instruments` now emits
# the clear only where exactly ONE voice ever filters -- Radio_ACE, Lion_Heart
# and Pacific_Coast (voices 2, 2 and 1); never on Go_Go_Dash or
# Sun_Never_Shines, which filter on two. Corpus byte-hash: **89 compared,
# MOVED 1, and it is Radio_ACE**, whose filtered frames go 6682 -> 4602
# against its original's 2688 with `melody` 0.9406 and `sequence` 0.9446
# IDENTICAL to four decimals in both arms. Sun_Never_Shines keeps 8992
# against 8997 -- ungated, arm 3 cost it 4622 of those frames, which is the
# whole reason for the gate.
#
# Arms 1 and 2 remain measured and unshipped, in
# `C:/t/ilv-filter-overproduce/edit2.py` and `edit3.py`; arm 3 is `edit7.py`
# plus the gate, re-appliable as `apply_gated.py`.
ILV_FILTER_ROUTING = 0x07


# --- Per-voice ILV routing as CMD_SETFILTERCTRL (`ilv_filter_routing`) --------
#
# **THE LIMIT `ILV_FILTER_ROUTING` STATES IS ABOUT THE FILTER TABLE, NOT ABOUT
# THE FORMAT.** A filter pointer belongs to an instrument, so the table cannot
# say "voice 0 left the circuit and voice 2 is still in it". A pattern command
# can: `B XY` writes the whole $D417 byte -- resonance X, channel mask Y -- on
# the row it is fetched on, whichever voice's column carries it (readme.txt
# "Command BXY"; gplay.c:469-471; player.s `mt_tick0_b`). And the ILV player's
# routing nibble is a pure function of the song position: the UNION over
# voices of "this voice's current record carries `FILTER_ENABLE_BIT`", each
# voice's bit taken at its last note start (the arm at $15D3 and the mask at
# $15C7, quoted at ILV_FILTER_ROUTING). So the routing is computable from the
# orderlists and expressible as one `B` at every row where that union changes.
# Design: C:/t/design-a-cross-voice-synchro/DESIGN.md (1dde44a).
#
# Two facts of the replay routines decide the spelling, both read, not guessed:
#
# * `B $00` ALSO STOPS THE FILTER TABLE (gplay.c:471 `if (!filterctrl)
#   filterptr = 0`; player.s `mt_tick0_b` falls into `mt_tick0_a_step`). An
#   empty union is therefore written `$X0` with X nonzero -- `$10` where the
#   resonance is 0, which nothing routed can hear.
# * THE FILTER STEP RUNS BEFORE THE CHANNELS (player.s `mt_play` reaches
#   `mt_filtstep` before the channel loop; gplay.c:253 before :340). A note's
#   instrument loads the pointer on its tick 0 and the program's first step
#   runs on the NEXT call -- so a program opening with `FILT_SET_PARAMS`
#   overwrites a `B` written on its own note row. Two spellings follow, and
#   the plan measures both (`late_rows`) and keeps the better:
#     "shared": every program has the same passband, so programs open at
#       their CUTOFF row and one `[PARAMS passband, $00][STOP]` block is run
#       per subtune by a `CMD_SETFILTERPTR` on a free row before the first
#       routed note. Every `B` lands on its own row.
#     "params": each program keeps its params row, whose routing nibble is
#       the union its notes most often open on; a note opening on any other
#       union takes its `B` one row late (`lagged`). The only spelling for a
#       file whose programs need different passbands (Sun_Never_Shines).
#
# Never on pattern row 0 (CLAUDE.md: row 0's command column belongs to the
# subtune's clock), never over an occupied command column. A change that
# finds no free column waits for the next row that has one (`unplaceable`),
# and the rows spent wrong are counted (`late_rows`) rather than hidden. A
# pattern played at several orderlist positions wanting different commands
# is copied per distinct command set, `apply_pulse_phase`'s rule; a copy past
# `MAX_PATTERNS` or a pattern packing past `PACKED_PATTERN_LIMIT` keeps its
# old rows and is counted as `dropped`.
#
# NOT MODELLED, and each is a known gap rather than a hidden one: the walk
# is on Goattracker's ROW clock, so a change is placed at the row start; the
# song's loop re-enters with the end-of-song routing where the walk assumed
# the power-on state; and a voice shorter than the longest is walked looping
# from its restart, with commands placed only on an occurrence's FIRST play.
CMD_SETFILTERPTR = 0x0A     # gcommon.h:14
CMD_SETFILTERCTRL = 0x0B    # gcommon.h:15
# The $D417 value written for "nothing routed" where the resonance nibble is
# 0: `B $00` would stop the table (above), and with no voice routed the
# resonance is inaudible.
ILV_EMPTY_UNION = 0x10


# --- Appending one song's subtunes to another --------------------------------
#
# A compilation's players convert one at a time (`convert._append_players`),
# and Goattracker keeps ONE instrument list, one pattern list and one copy of
# each table for every subtune. So appending a song is a renumbering: every
# reference the appended song makes into one of those lists moves to where
# its target landed. The references, from Goattracker's readme.txt
# (commands :641-700, tables :785-950):
#
#   orderlist     $00-$CF pattern number (repeat $D0-$DF, transpose $E0-$FE
#                 and the $FF terminator with its restart position do not)
#   instrument    +2 wave, +3 pulse, +4 filter pointer (0 = none); +5 the
#                 vibrato speed-table index (GTS5; in GTS2 it is the value)
#   pattern row   instrument column (0 = no change); command 1-4 and E data
#                 = speed-table index (GTS5, 0 = none), 8/9/A data = wave/
#                 pulse/filter pointer (0 = stop)
#   wavetable     $FF jump target (0 = stop); $F1-$F4 right side = speed index
#                 (GTS5), $F9/$FA right side = pulse/filter pointer
#   pulse/filter  $FF jump target (0 = stop)
#   speed table   values only, no references
#
# **The caps are what this is about.** A table holds 255 rows (the filter
# table 64), the instrument list 63 records, the pattern list 208. Appended
# naively, 5_Title_Tunes' five players need 426 wavetable rows, 729 pulse
# rows and 82 instruments. So the appended song's table rows are placed by
# REGION -- the rows reachable from one entry point (a pointer some record,
# row or command holds) up to its `$FF`, closed under the jumps inside it --
# and a region whose rows already stand somewhere in the table (jumps
# compared relative to the region's start) is pointed at rather than copied.
# The players share most of their records byte for byte (records 8-15 are
# identical in all five). A row no entry point reaches is not copied at all:
# nothing can play it. An instrument whose finished record (pointers already
# moved) equals one already in the list is the same instrument and shares
# its number.
#
# Returns None, and appends nothing, where the result would still pass one of
# Goattracker's caps: an over-cap list is not refused by anything downstream,
# it is truncated or wrapped silently (see MAX_PATTERNS in patterns.py).

GT_MAX_SONGS = 32                       # gcommon.h MAX_SONGS
GT_MAX_INSTRUMENTS = GT_MAX_INSTR - 1   # numbered 1..63; 0 is "no change"
_SONG_MAX_PATTERNS = 0xD0               # gcommon.h MAX_PATT
_ORDERLIST_REPEAT = 0xD0                # orderlist: below this, a pattern
_ORDERLIST_TRANSPOSE = 0xE0             # orderlist: $D0-$DF repeat, then this
_RECORD_LEN = 25
_NAME_AT = 9
_TABLE_NAMES = ("wave", "pulse", "filter", "speed")
_SPEED_COMMANDS = (0x1, 0x2, 0x3, 0x4, 0xE)
_POINTER_COMMANDS = {0x8: 0, 0x9: 1, 0xA: 2}      # pattern command -> table
_WAVE_SPEED_COMMANDS = (0xF1, 0xF2, 0xF3, 0xF4)
_WAVE_POINTER_COMMANDS = {0xF9: 1, 0xFA: 2}       # wavetable command -> table
_JUMP = 0xFF
