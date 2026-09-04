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
from typing import Dict, List, Optional, Set

from .detect import (Detection, SLIDE_HIGH_FIRST_DOWN,
                     SLIDE_HIGH_FIRST_MASK)
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

# **Which commands survive into a hold row.** An event with wait W occupies
# W+1 rows, and a Goattracker command byte is executed on the row it appears
# on -- so a *continuous* effect has to be repeated on every one of them,
# which is how a portamento keeps stepping (gplay.c:740 re-reads the speed
# each tick), while a *one-shot* effect must appear once or a single intent
# becomes W+1 of them.
#
# Only three commands are emitted from here: CMD_PORTAUP (1) and
# CMD_PORTADOWN (2), which are continuous, and CMD_TONEPORTA (3), which is
# not -- with parameter 0 it assigns `freq = targetfreq` in one call
# (gplay.c:811), and repeating it would re-assign the same value on every
# hold row. CMD_SETTEMPO reaches patterns through `apply_tempo` and never
# this loop.
#
# A set rather than the `if cmd1 == 3` this replaces, because **the default
# of the hold loop is repeat** and a one-shot command added later inherits
# that silently. v0.5.284's CMD_SETWAVE experiment did exactly that: 61 rows
# were designed and 673 command bytes were written, so its corpus A/B
# measured something other than the change it described, and the -43pp it
# produced was attributed to a mechanism that occurs nowhere in the affected
# files (H2G-CONVERSION-METHOD.md sections 7.ooooo and 7.ppppp). Anything
# added here that acts once belongs in this set.
CMD_SETWAVE = 7                 # gcommon.h:11
# Test bit set, no waveform selected: the value IK+'s player parks in the
# voice's stored waveform on a bit-6 rest. `$18` would also be silent to the
# ear but is class `$10` to every register column and stays above the `$10`
# siddump needs to name the next attack, which is why v0.5.282's `$18`
# attempt moved no column on any file.
REST_SILENT_WAVE = 0x08
# gcommon.h:10. Writes one byte to $D406 on the row it appears and nothing
# afterwards (gplay.c:428-430, player.s:209-213), and the next note's
# instrument load overwrites it (gplay.c:398, player.s:882-884) -- so it is
# self-restoring, exactly like the player's own write. That is what makes it
# the right spelling for a rest that hard-silences: see
# detect._find_rest_silence_envelope.
CMD_SETSR = 6
# gcommon.h:9, the other half of the pair. Emitted only on a bit-6 rest's
# first hold row -- see decode_entry for why the delay is inaudible.
CMD_SETAD = 5
ONE_SHOT_COMMANDS = frozenset({3, CMD_SETWAVE, CMD_SETSR})
# Commands a subtune's `CMD_SETTEMPO` may overwrite on row 0 of an entry
# pattern. **A whole subtune's clock outranks any of them**, and that is not
# a preference: `apply_tempo`/`apply_tempos` skip a pattern whose command
# column is taken, so a row-0 command silently costs the subtune its tempo
# and it plays at Goattracker's default 6. `_apply_boundary_ties` was
# measured losing Star_Paws two of three tempo writes that way (`drift`
# -111 -> +1667, all three voices down three quarters of their attacks),
# and a `CMD_SETSR` rest added here without this entry reproduced it across
# **12 of 19 files** -- ACE_II `drift` 0.00 -> 1250, Ricochet -7.81 ->
# 1976.54, mean melody -47pp. Anything new that can land on row 0 belongs
# in this set, not merely in ONE_SHOT_COMMANDS.
TEMPO_OVERWRITABLE = frozenset({0, CMD_SETWAVE, CMD_SETSR})
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

# gcommon.h's CMD_TONEPORTA. With a parameter of 0 it is Goattracker's only
# way of saying "this row changes the pitch and does not attack" -- see the
# tie block in _build_raw_pattern and _apply_boundary_ties.
CMD_TONEPORTA = 3
CMD_SETPULSEPTR = 9
# Startup calls the classic engine's sweep has already run by the first
# fetch -- see collect_pulse_phases. Measured, not derived.
PULSE_PHASE_PREROLL = 7

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


# Distinct slide steps a file may carry. A pattern data column is one byte and
# 0 means "no parameter", so 255 indices are available -- the same ceiling
# MAX_TABLELEN puts on the speed table those indices name.
MAX_SLIDE_STEPS = 0xFF


def _step_index(steps: List[int], speed: int) -> int:
    """1-based index of `speed` in `steps`, appending it if new.

    The pattern column cannot hold a 16-bit step, so for a GTS5 file it holds
    an *index* into the file's own list of distinct steps instead of a packed
    value -- which is what build_speed_table would overwrite it with anyway.
    That removes both ends of the packing error at once: `min(step // 4, 0xFF)`
    saturated every step above 1020 (2189 of the corpus's 5566 portamento
    parameters before the dialect fix) and rounded every step below 4 to zero,
    which reads as no parameter at all.

    Past 255 distinct steps the nearest one already listed is reused. No corpus
    file comes close, and reusing a neighbour is a slide a fraction off rather
    than a column that means something else entirely.
    """
    if not speed:
        return 0
    try:
        return steps.index(speed) + 1
    except ValueError:
        pass
    if len(steps) < MAX_SLIDE_STEPS:
        steps.append(speed)
        return len(steps)
    nearest = min(range(len(steps)), key=lambda k: abs(steps[k] - speed))
    return nearest + 1


def _build_raw_pattern(data: bytes, addr: int,
                       slide_operand: bool = False,
                       note_flag: bool = False,
                       status_bit6: bool = False,
                       rest_instrument: bool = False,
                       instr_base: int = 2,
                       span: Optional[List[int]] = None,
                       note_base: int = 0,
                       slide_high_first: bool = False,
                       steps: Optional[List[int]] = None,
                       tie: bool = False,
                       gate_hold: bool = False,
                       rest_keyoff: bool = False,
                       rest_wave: bool = False,
                       rest_envelope: bool = False,
                       exits_tied: Optional[List[bool]] = None
                       ) -> Optional[List[int]]:
    """Flat event stream for one Hubbard pattern, or None if out of range.

    slide_operand says the player fetches a *second* byte after a `>= $80`
    command operand -- the high half of a 16-bit pitch-slide step. See
    detect.SLIDE_OPERAND_SHAPE. It is off by default because 54 of 95 corpus
    players do not have that fetch, and reading a byte they never read
    desynchronises the rest of the pattern.

    slide_high_first says that in *this* player the fetched byte is the step's
    LOW half and the operand carries the high half -- a second dialect behind
    the same fetch shape, in 22 corpus files. Read the wrong way round the step
    comes out about 256x too large; see detect.SLIDE_HIGH_FIRST_SHAPE. It has
    no effect unless slide_operand is set, since without the fetch there is no
    second byte to assign.

    status_bit6 says the player tests bit 6 of the status byte first and
    alone (`BIT status / BVS`, detect.STATUS_BIT6_SHAPE), branching past the
    operand read AND the note read -- so a $C0-$FE status byte consumes only
    itself, where the bit-7-first reading below consumes three bytes. Off by
    default: the byte-exact Commando fixture encodes the old reading.

    `span`, when given a list, receives the number of bytes the decode
    consumed (terminator included) -- what phantom_patterns needs to know
    which file bytes an entry would claim as pattern data. Nothing is
    appended when the decode fails.

    `gate_hold` says this player's note-end gate-off sits behind
    `LDA counter,X / BNE` on the *hold* path of a `DEC counter,X / BMI
    fetch-next` sequencer, so an event whose `wait` field is zero never
    reaches it and ties into the next note. See detect.find_gate_hold and the
    `pending_tie` assignment below; it does nothing unless `tie` is also set.

    `exits_tied`, when given a list, receives one bool: whether the decode
    ended with `pending_tie` set -- that is, whether the player would carry
    the open gate out of this pattern and into whatever the orderlist plays
    next. Nothing is appended when the decode fails. It is an out-parameter
    rather than a second return value so that no caller has to change, and it
    changes no byte of the event stream. See `boundary_ties`.

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
    # Set by an event whose status bit 5 is clear-gate-suppressed; consumed by
    # the next event that carries a note. See the `tie` block below.
    pending_tie = False

    while True:
        if addr + i2 <= 1 or addr + i2 >= len(data):
            return None

        g_note = GT_NO_NOTE
        cmd1 = 0
        cmd2 = 0
        # (command, data) for the event's FIRST hold row, where it needs one
        # of its own rather than the repeat of `cmd1` the loop below writes.
        # One (cmd, value) per HOLD row of a bit-6 event, in order.
        # A list rather than a single slot because a rest can owe
        # THREE writes -- see the rest branch below -- and a row has
        # one command column.
        hold_cmds: list = []
        b1 = data[addr + i2]

        if b1 == 0xFF:
            events += [0xFF, 0x00, 0x00, 0x00]
            if span is not None:
                span.append(i2 + 1)
            if exits_tied is not None:
                exits_tied.append(pending_tie)
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
            # ...and a bit-6 event is a **rest**: the voice is released for
            # its duration in every player with the shape. `KEYOFF` is the
            # only row this format has that ends a note without starting one,
            # and the instrument column goes with it, since the event reads
            # no operand and can carry no instrument change.
            #
            # **Not gated on the branch writing a silencing value**, which is
            # what v0.5.269 did and what kept this to 19 files. 21 of the 61
            # players cut the voice in the branch itself -- the testbit into
            # the stored waveform (IK+ `$E138`), or the envelope pair zeroed
            # (Ricochet `$914A`) -- and the other 40 reach the same state by
            # the ordinary end-of-note path a frame earlier. The branch was
            # read; what it *means* for the gate was inferred from it, and
            # the trace says the gate is off across the rest either way.
            # Forced on for those 40 and measured against the `gate` column:
            # **26 up, 0 down, 14 unchanged**, with `melody` and `retrig`
            # unmoved on every one -- Battle of Britain 21 -> 90%, Gremlins
            # 25 -> 89%, Thrust 47 -> 87%. See H2G-CONVERSION-METHOD.md
            # section 7.ggggg.
            if rest_keyoff:
                g_note = GT_KEYOFF
                g_instrument = 0
            # A KEYOFF clears the *gate* and nothing else (`wave & gate`,
            # gplay.c:951), so the waveform stays latched at whatever the
            # wavetable last wrote. The testbit family's player parks `$08`
            # in the voice's stored waveform instead -- test bit, no waveform
            # selected, silence. CMD_SETWAVE is the only row-level way to
            # write a waveform with no note (gplay.c:433).
            #
            # It survives the frame here because our tables *stop*: `$FF 00`
            # zeroes `ptr[WTBL]` (gplay.c:711) and WAVEEXEC is guarded on that
            # pointer, so nothing overwrites `cptr->wave` afterwards. Checked
            # on the conversions rather than assumed -- IK+ ends 26 of 26
            # tables that way, Auf Wiedersehen Monty 24 of 24. Where a table
            # *loops*, WAVEEXEC runs every frame at gplay.c:525 and would
            # clobber this within the frame; that is why the claim is about
            # these files and not about the format.
            # BOTH FAMILIES AT ONCE, ordered by audibility. Until
            # v0.5.453 this was `if rest_wave: ... elif rest_envelope: ...`,
            # so a conversion asking for both got the waveform park and the
            # envelope write was dropped WITHOUT a word -- measured
            # byte-identical to wave-only on ACE_II, Monty, Thundercats and
            # Shockway_Rider. The two are not alternatives: one parks a
            # waveform and the other stops the envelope, and the player does
            # both on the same rest.
            #
            # A row has ONE command column, so the schedule spends row 0 on
            # the audible write and the hold rows on the rest, which is the
            # mechanism the AD half already used:
            #
            #     row 0        CMD_SETSR $00   the release rate the ring-out
            #                                  plays at -- the audible one
            #     hold row 0   CMD_SETWAVE     the parked waveform
            #     hold row 1   CMD_SETAD $00   inaudible across a rest
            #
            # A `wait` too short to hold them all drops from the END, so the
            # audible write is never the one displaced. With only one option
            # set the emission is UNCHANGED, which is what keeps every
            # shipped conversion byte-identical.
            if rest_wave and rest_envelope and rest_keyoff:
                cmd1, cmd2 = CMD_SETSR, 0x00
                hold_cmds = [(CMD_SETWAVE, REST_SILENT_WAVE),
                             (CMD_SETAD, 0x00)]
            elif rest_wave:
                cmd1, cmd2 = CMD_SETWAVE, REST_SILENT_WAVE
            # ...and the half of that branch **both** families share: the
            # envelope pair is zeroed, so the note that was sounding stops
            # dead rather than releasing at the record's own rate. A KEYOFF
            # cannot say that -- it clears the gate and the release nibble
            # then plays out. ACE_II's two lead instruments carry release 9
            # (~750ms) and ring through 575 of its voice-1 frames where the
            # original's ADSR reads $0000, which is 31% of the trace and the
            # whole of that voice's shortfall.
            #
            # `CMD_SETSR $00` is the write, not `--cut-release`'s zeroed
            # nibble: this player zeroes the pair **only here**, and a plain
            # note end merely clears the gate ($E1E6 `LDA #$FE` into the mask
            # ANDed at $E464), so the release does sound there and destroying
            # it in the instrument would be wrong. See
            # detect._find_rest_silence_envelope for the routine and for why
            # the population is all 21 `rest_silences` files, not the 4 the
            # `"envelope"` name suggests.
            #
            # Only the SR half is emitted. A row has one command column, and
            # AD governs nothing while the gate is off -- the next note
            # reloads both from the instrument anyway (gplay.c:397-398,
            # player.s:882-892), which is also what makes this self-restoring
            # exactly as the player's own write is.
            elif rest_envelope and rest_keyoff:
                # Gated on `rest_keyoff` because the two writes are one
                # act in the player: it clears the gate on the same
                # call it zeroes the pair. A sustain of 0 on a voice
                # whose gate is still OPEN silences a note that should
                # still be sounding -- the opposite defect, and a worse
                # one. Nothing in `presets.json` turns `rest_keyoff`
                # off today, which is exactly why the guard is here
                # rather than left to the caller.
                cmd1, cmd2 = CMD_SETSR, 0x00
                # The AD half goes on the event's first HOLD row, because a
                # row has one command column and the two writes cannot share
                # it. That is a one-row delay on a register which, across a
                # rest, is **inaudible**: $D405 shapes only a rising envelope,
                # the gate is off for the whole rest, and the next note
                # reloads it from the instrument before it gates on
                # (gplay.c:397, player.s:892 `lda mt_insad-1,y`) -- a bit-6
                # event never carries `pending_tie`, so that next note really
                # does attack. The SR half keeps row 0 because it is the
                # audible one: it is the release rate the ring-out plays at.
                #
                # It is also what lets a trace *see* the fix. `adsr_compare`
                # compares the whole 16-bit pair and drops frames both sides
                # read as $0000, so emitting SR alone leaves ACE_II's 575 rest
                # frames reading $0800 against $0000 -- still a disagreement,
                # and the column reported the change as a no-op. With both,
                # those frames leave the denominator because we now hold what
                # the original holds.
                #
                # A `wait` of 0 has no hold row, so such a rest gets the SR
                # write only. That is the right half to keep, and the AD is
                # dropped rather than displacing it.
                hold_cmds = [(CMD_SETAD, 0x00)]

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
                    # The step is 16-bit and split across these two bytes --
                    # but which byte is which half depends on the player, and
                    # the two dialects share one fetch shape. See
                    # detect.SLIDE_HIGH_FIRST_SHAPE for both routines.
                    #
                    # Goattracker's own portamento parameter is the 16-bit
                    # speed divided by four (gtable.c:881, MST_PORTAMENTO:
                    # `l = (data << 2) >> 8, r = (data << 2) & 0xff`), so
                    # emit that and let build_speed_table encode it.
                    i2 += 1
                    if addr + i2 >= len(data):
                        return None
                    if slide_high_first:
                        # Flash Gordon $12EB: the operand's low 6 bits are the
                        # step's HIGH half (self-modified into an immediate)
                        # and the fetched byte is its low half. Direction is a
                        # threshold, not a bit: `CMP #$BF / BCC` adds below it.
                        speed = ((b2 & SLIDE_HIGH_FIRST_MASK) << 8) \
                            | data[addr + i2]
                        cmd1 = 2 if b2 >= SLIDE_HIGH_FIRST_DOWN else 1
                    else:
                        # Warhawk $1320: this byte is the low half (masked
                        # $7E -- bit 0 is the direction flag, bit 7 the command
                        # flag) and the *next* byte is the high half.
                        speed = (data[addr + i2] << 8) | (b2 & 0x7E)
                    if steps is not None:
                        cmd2 = _step_index(steps, speed)
                    else:
                        cmd2 = min(speed // 4, 0xFF)
            else:
                g_instrument = (b2 & 0x7F) + instr_base
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
        # `instr_base > 1` is not a style check: the placeholder trick points a
        # dummy note at instrument 1, and under --compact-instruments slot 1
        # holds the player's record 0, so pointing at it would sound a real
        # instrument instead of silence. With no empty slot there is nothing to
        # aim at, and carrying the change on the rest is the only correct form.
        if (not rest_instrument and instr_base > 1
                and g_note == GT_NO_NOTE and g_instrument != 0):
            g_note = 0x60
            resc_instr = g_instrument
            g_instrument = 1
        # An instrument change landing on a rest needs no note to carry it.
        # gplay.c:912-914 latches the column whenever it is non-zero, *before*
        # and independently of the note test:
        #
        #     newnote = pattern[pattnum][pattptr];
        #     if (pattern[pattnum][pattptr+1])
        #       cptr->instr = pattern[pattnum][pattptr+1];
        #
        # so a $BD rest row carrying an instrument number latches it and sounds
        # nothing. This used to emit a C-0 on instrument 1 instead -- the
        # hardcoded Clear Voice, whose record is all-zero ADSR with the testbit
        # set, i.e. a click and a retrigger of whatever was sounding. 1422 rows
        # across 64 corpus files did that, and it is audible: found by ear on
        # Commando, not by any dimension of FIDELITY.md.

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
        if (tie and pending_tie and cmd1 == 0
                and g_note != GT_NO_NOTE):
            # The *previous* event carried status bit 5, so the player never
            # closed the gate at its end (Commando $517F) and this note arrives
            # with the gate still open -- a frequency change and no attack.
            # `CMD_TONEPORTA` with parameter 0 is that, exactly: gplay.c:811
            # assigns `freq = targetfreq` in one call, gplay.c:930 skips the
            # hard-restart gate-off *because* the command is TONEPORTA, and
            # gplay.c:355 skips the firstwave testbit for the same reason. It
            # also zeroes `vibtime`, so the vibrato restarts on the landing --
            # which is what the original does at the end of a slide.
            #
            # **The spelling carries more than "no attack", and one of the
            # extras can raise a file's attack count.** The packed player
            # answers `CMD_TONEPORTA` with "no gateoff" (player.s:1298-1301,
            # `lda mt_chnnewfx,x / cmp #TONEPORTA / beq mt_rest`), so a tied
            # row skips the hard restart *and* the `firstwave` call after it.
            # On a **3-call row** those two are the whole row -- 2 calls of
            # `_hard_restart_ticks` plus 1 of `$09`, the testbit that outputs
            # nothing -- so an *untied* one-row note there is inaudible, and
            # tying it is what lets it be heard. Nineteen's voice 0 went 69
            # attacks -> 74 on that alone when `gate_hold` landed, and reads
            # as a `melody` regression while being the conversion recovering
            # notes it had swallowed. 38 of the 83 convertible corpus files
            # carry such a row, so this is a short-row property and not a
            # player dialect: see tests/test_row_budget.py, and do not gate
            # the tie on the files it happens to show up in.
            cmd1, cmd2 = 3, 0x00
        # ...and so does an event whose `wait` field is **zero**, for a
        # different reason in the same routine. The players sequence a note's
        # end as
        #
        #     09E4  DEC counter,X      ; counter = status & $1F, written at
        #     09E7  BMI fetch-next     ;   fetch time ($0A35 in Human_Race)
        #     09E9  JMP hold-path      ; -> the gate-off test at $0AD3
        #
        # and the gate-off test lives on the **hold** path only:
        #
        #     0AD6  LDA status,X / AND #$20 / BNE skip   ; bit 5 -- the tie above
        #     0ADD  LDA counter,X        / BNE skip      ; not the last frame
        #     0AE2  LDA wave,X / AND #$FE / STA $D404,Y  ; gate off
        #
        # A `wait` of 0 loads the counter with 0, so the very first DEC
        # underflows, `BMI` is taken, and the hold path -- and with it the
        # only gate-off this player performs at a note's end -- is never
        # executed at all. The next note therefore arrives with the gate
        # still open: a frequency change and no attack, exactly what bit 5
        # produces deliberately. Human_Race's voice 1 is 414 such rows and
        # sounded 452 attacks against the original's 48.
        #
        # Whether the *player* ties there is a property of the player and not
        # of this byte -- see detect.find_gate_hold, which reads the one
        # branch target that decides it, and note that `gate_hold` is what
        # keeps Saboteur_II out. This condition is not that test.
        #
        # A **bit-6 event is excluded, and from BOTH halves** -- a bit-6 event
        # is a rest, and the rest branch closes the gate on its own, off the
        # counter path entirely: Human_Race `$0A7C DEC $0DBC` (the mask ANDed
        # into $D404 at $0A95), Saboteur_II `$F13C DEC $F566,X` (ANDed in at
        # $F465). The idiom is the same in every player that has it and it is
        # worth reading once in full, here Battle of Britain:
        #
        #     8065  A9 FF     LDA #$FF        ; the gate mask, reloaded on
        #     8067  8D FF 83  STA $83FF       ;   every fetch frame
        #     806A  B1 FD     LDA ($FD),Y     ; the status byte
        #     ...
        #     8077  2C 00 84  BIT $8400       ; bit 6
        #     807A  70 44     BVS $80C0       ;   set -> the rest branch
        #     80C0  CE FF 83  DEC $83FF       ; $FF -> $FE
        #     80D6  BD 22 84  LDA $8422,X     ; the voice's waveform
        #     80D9  2D FF 83  AND $83FF       ;   with bit 0 cleared
        #     80DC  99 04 D4  STA $D404,Y     ; gate OFF
        #
        # Devils Galop is the same routine at $1399/$13BA/$13FA/$141B. The
        # `AND` is unconditional: nothing on that path consults bit 5, so a
        # rest ends with the gate shut **whatever the status byte's bit 5
        # says**, and the next note really does attack.
        #
        # Excluding it from the zero-`wait` half alone is byte-inert on all 83
        # convertible corpus files (measured by flipping it and hashing every
        # conversion), which is why this read as settled. It is not: a rest
        # carrying bit 5 as well -- `$7F`, the byte four of these players end a
        # pattern on -- set `pending_tie` through `no_adsr`, and
        # `_apply_boundary_ties` then tied the next pattern's opening note into
        # a gate the rest had already closed. Battle of Britain, Devils Galop,
        # Crazy Comets and Monty on the Run each lost a handful of real attacks
        # that way at v0.5.339 (`retrig` 0.988/0.995/0.995/0.996 against 1.000
        # with the carry suppressed). The rest is not a note whose end can be
        # held open; it is the thing that ends the note before it.
        #
        # Kept pinned by tests/test_gate_hold.py and tests/test_wait0_tie.py so
        # a file that exercises either half cannot quietly get the other
        # reading. It was briefly believed to be what spared Saboteur_II. It is
        # not: with it in place Saboteur_II still fell from melody 98% to 69%
        # until `gate_hold` excluded the file outright.
        pending_tie = tie and not no_note and (
            bool(no_adsr) or (wait == 0 and gate_hold))
        events += [g_note, g_instrument, cmd1, cmd2]
        if cmd1 in ONE_SHOT_COMMANDS:
            cmd1 = 0
        for h in range(wait):
            if h < len(hold_cmds):
                events += [GT_NO_NOTE, 0x00, hold_cmds[h][0], hold_cmds[h][1]]
                continue
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
# $82 is a 16-bit pitch slide added to the voice frequency every frame. Off the
# Cuff's handler stores the two operands ($1133) and its consumer ($134C) adds
# them:
#
#     1133  C8 B1 FA  INY / LDA (patt),Y
#     1136  9D 7B 16  STA slidehi,X      ; FIRST operand is the HIGH half
#     1139  C8 B1 FA  INY / LDA (patt),Y
#     113C  9D 78 16  STA slidelo,X      ; second is the low half
#     1140  DE 7E 16  DEC gate,X         ; 0 -> $FF, i.e. "slide running"
#
#     134C  BD 7E 16  LDA gate,X / BEQ out
#     1351  18        CLC
#     1352  BD 75 16  LDA freqlo,X / ADC slidelo,X / STA freqlo,X
#     135B  BD 72 16  LDA freqhi,X / ADC slidehi,X / STA freqhi,X
#
# One `CLC / ADC` pair, so the step is *signed*: a high byte of $80 or above
# slides down. All nine digi files carry both shapes. The gate is cleared at
# every note start ($10F4-$10F6), so the slide runs for the whole EVENT.
#
# **This used to read "which is also what Goattracker does with a channel's
# command (gplay.c:351), so the two persist alike", and that is wrong.** It
# conflates the player's gate, which persists until the next note, with a
# Goattracker command byte, which executes on the row it appears on and
# nowhere else -- see the module header on `ONE_SHOT_COMMANDS`, and the ILV
# decoder, which was given the repeat at v0.5.454 for this reason. The two do
# NOT persist alike, and the emission repeats the command on the event's hold
# rows to make them.
#
# $83 sets a vibrato, in the same $78-bound/$07-shift format the classic
# players use, overriding the instrument's own byte for the rest of the note
# (Off the Cuff $1229, falling back to $1704,Y at $123F). Not translated: the
# instrument-level vibrato --vibrato already emits covers the common case, and
# Goattracker's CMD_VIBRATO would have to displace the slide in the one command
# column a row has.
DIGI_SLIDE = 0x82
DIGI_VIBRATO = 0x83
DIGI_REST = 0x60
DIGI_MAX_NOTE = 0x5C        # same ceiling the classic decoder clamps to


def _digi_command(pending: tuple, steps: Optional[List[int]]) -> tuple:
    """(command, data) columns for a decoded $82 slide.

    Packed exactly as the classic decoder packs its own: an index into `steps`
    where the caller is collecting them at full 16-bit width, and otherwise the
    old `step // 4` byte, which a GTS2 loader multiplies back (gsong.c:311-321).
    """
    cmd, step = pending
    if steps is not None:
        return cmd, _step_index(steps, step)
    return cmd, min(step // 4, 0xFF)


def _build_raw_pattern_digi(data: bytes, addr: int,
                            note_base: int = 0,
                            slides: bool = False,
                            steps: Optional[List[int]] = None,
                            instr_base: int = 2,
                            ) -> Optional[List[int]]:
    """Flat event stream for one digi-engine pattern, or None if out of range.

    With `slides`, effect $82 becomes a portamento: its two operands are the
    high and low halves of a signed 16-bit per-frame step (see DIGI_SLIDE), and
    it is attached to the next row this decoder emits -- which is where the
    player starts it, since a command byte is read between one note's rows and
    the next's. Off by default like the classic decoder's slide reading.

    Effect $83 is parsed for its length and not translated; see DIGI_VIBRATO.
    Notes, instruments and timing are complete either way, and dropping an
    effect leaves a note playing plainly rather than corrupting the stream.
    """
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    instrument = 0
    wait = 0
    pending: Optional[tuple] = None

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
            instrument = data[addr + 1] + instr_base
            addr += 2
            continue
        if b in DIGI_TWO_OPERAND:
            if addr + 2 >= len(data):
                return None
            if b == DIGI_SLIDE and slides:
                # First operand high, second low, and the pair is signed: the
                # player has one CLC/ADC and no direction test.
                step = (data[addr + 1] << 8) | data[addr + 2]
                if step >= 0x8000:
                    pending = (2, 0x10000 - step)   # CMD_PORTADOWN
                else:
                    pending = (1, step)             # CMD_PORTAUP
            addr += 3
            continue
        if b >= 0x80:
            # $84-$BF reach a `BNE` back to the fetch with no INY, i.e. the
            # player would spin forever. Real data never contains one, so this
            # means the pointer is not at a pattern.
            return None

        cmd = _digi_command(pending, steps) if pending is not None else None
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
        if cmd is not None:
            events[-2], events[-1] = cmd
        for _ in range(wait):
            events += [GT_NO_NOTE, 0x00, 0x00, 0x00]
            if cmd is not None:
                # **Repeated on every hold row, exactly as the ILV decoder
                # does** (v0.5.454). A Goattracker command byte executes on the
                # row it appears on and nowhere else -- the module header on
                # `ONE_SHOT_COMMANDS` -- and `CMD_PORTAUP`/`CMD_PORTADOWN` are
                # continuous, so one row of command is one row of slide. The
                # player's is not: $134C adds the step on EVERY frame while
                # `gate,X` is set, and that gate is cleared only at the next
                # NOTE START ($10F4-$10F6), so a slide runs for its whole
                # event -- its hold rows included. Attached to the note row
                # alone it stopped after one row, and 6 of the 9 digi files
                # place hold rows immediately after their slides.
                events[-2], events[-1] = cmd
        pending = None
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


# --- The interleaved-table engine's pattern grammar ------------------------
#
# A FOURTH grammar, carried by the six files `_detect_interleaved_classic`
# rescues (Go_Go_Dash, Lion_Heart, Pacific_Coast, Radio_ACE, Sun_Never_Shines,
# Lakers_vs_Celtics). It is the mirror image of the classic reader: there bit 7
# on a status byte means "an operand follows" and a note byte always follows;
# here bit 7 SET is a COMMAND and bit 7 CLEAR is the note itself. Read under
# the classic grammar these patterns come out at 945-5927 rows with a quarter
# of them undecodable, which is why the six aborted on the pattern count
# rather than converting wrongly.
#
# Transcribed from Lion_Heart's reader at $116C:
#
#     116C  B1 FA     LDA (patt),Y
#     116E  30 03     BMI $1173        ; >= $80 -> command or duration
#     1170  4C 24 12  JMP $1224        ; <  $80 -> a note event
#     1173  48        PHA
#     1174  29 40     AND #$40         ; bit 6 splits the two high families
#     1176  F0 15     BEQ $118D        ; $80-$BF -> the command dispatch
#     1178  68        PLA              ; $C0-$FF -> a DURATION byte
#     1179  9D 3D 1A  STA $1A3D,X
#     117C  29 20     AND #$20         ;   bit 5 is a separate per-voice flag
#     117E  9D 94 01  STA $0194,X
#     1184  29 1F     AND #$1F         ;   low five bits are the wait
#     1186  9D 3A 1A  STA $1A3A,X
#     1189  C8        INY              ;   ...and it emits NO row of its own
#     118A  4C 6C 11  JMP $116C
#
# THE DURATION IS THE CLASSIC ONE. Its counter is sequenced by
# `$10F9 DEC $1A37,X / $10FC BMI`, the same DEC/BMI shape `_build_raw_pattern`
# documents for Commando's `$54F2,X`, so an event lasts wait+1 rows: its own
# row plus `wait` holds.
#
# `$60` IS A REST, not a note. The note path tests it twice -- `$1238 CMP #$60`
# in the lookahead and `$1264 CMP #$60 / BEQ $129D` on the note itself -- and
# the branch decrements the voice's own counter rather than sounding anything.
# It is one past the frequency table's 96 entries, which is what makes it
# available as a marker.
#
# `$81` ENDS THE PATTERN and is NOT in the command dispatch. The player only
# ever meets it as the byte AFTER a note, where the lookahead at `$1228 CMP #$81`
# does `LDY #$00 / INC $1A31,X` -- reset the pattern cursor, advance the
# orderlist. Scanning for it at the top of the loop is equivalent on
# well-formed data (a pattern always sounds a note before it ends) and is what
# this decoder does; reaching it any other way would spin the player, since the
# dispatch below has no arm for it.
ILV_END = 0x81
ILV_REST = 0x60
ILV_MAX_NOTE = 0x5C          # the same GT ceiling the classic decoder clamps to

# `$80-$BF`, dispatched at $118D-$11AE on the EXACT value, with the operand
# count read from each handler's own INY count. Getting one of these wrong
# desynchronises everything after it, which is why they are a table rather
# than a rule.
#
#   $80 nn      instrument       -> $1A49,X   ($1204)
#
# **AND THE NUMBER `$80` CARRIES ROUTINELY EXCEEDS THE INSTRUMENT TABLE THIS
# CONVERTER WRITES -- 1768 of Go_Go_Dash's 2456 notes, 72%, which is the whole
# of its 36% melody. The cause is in `detect`, not here.** `detect()` counts
# the instrument table by walking `instr_start + 2 + n * instr_stride` while
# the byte is in `WAVEFORMS` -- and it does that BEFORE
# `_detect_interleaved_classic` sets `instr_stride = 16`, so all six of these
# files count 16-byte records at a stride of 8. The comment beside that
# assignment already says what goes wrong when the stride is 8 ("every record
# after the first is read from the middle of its predecessor"); the count was
# simply never re-taken. Censused over the corpus at 64c795b: 15 files have
# `instr_stride == 16`, and **exactly the six interleaved-classic ones** have
# an `instr_used` that disagrees with a recount at 16 --
#
#     Go_Go_Dash        3 counted,  18 at stride 16   1768 notes dangling
#     Radio_ACE         9 counted,  17 at stride 16    529 notes dangling
#     Lakers_vs_Celtics 13 counted, 17 at stride 16     85 notes dangling
#     Lion_Heart        27 counted, 17 at stride 16      0 (over-counts)
#     Pacific_Coast     25 counted, 18 at stride 16      0 (over-counts)
#     Sun_Never_Shines  11 counted, 18 at stride 16      0 (under, unreached)
#
# -- while the nine digi files, whose chain sets the stride before the walk,
# all agree with their own recount. Note the defect cuts both ways: an
# under-count silences notes (a Goattracker instrument past the table sounds
# nothing) and an over-count writes records out of whatever follows the table.
# Pinned by `tests/test_interleaved_classic.py`'s strict xfail, which XPASSes
# the moment the count is re-taken.
#   $82 nn mm   PORTAMENTO       -> $1AB5,X / $1AB2,X, and DEC $1AB8,X ($1211)
#   $83 nn                       -> $1A55,X, zeroes $1A58,X            ($11F0)
#   $84                          -> $1A86 = 1                          ($11E7)
#   $86 nn                       -> $1A5B,X, sets $1A62                ($11C5)
#   $87 nn mm                    -> $1A74,X / $1A71,X                  ($11B0)
#   $88                          -> $1A64 = 1                          ($11DE)
#   $89 nn                       -> $1A66 (global)                     ($11D4)
#
# $80 and $82 are translated. The rest are effects, and dropping one leaves
# its note playing plainly -- but ONLY because the operand counts here are
# exact, so the stream stays in step.
#
# **$82 IS A PORTAMENTO, read end to end out of Lion_Heart rather than guessed
# from its shape.** The handler stores its first operand to `$1AB5,X` and its
# second to `$1AB2,X`, and the frame routine at $1663 adds that pair into a
# per-voice 16-bit accumulator whenever the counter `$1AB8,X` is non-zero:
#
#     1663  BD B8 1A  LDA $1AB8,X      ; the counter the command DECs from 0
#     1666  F0 13     BEQ $167B        ;   ...to $FF, i.e. "running"
#     1668  18        CLC
#     1669  BD B2 1A  LDA $1AB2,X      ; step low
#     166C  7D BB 1A  ADC $1ABB,X
#     166F  9D BB 1A  STA $1ABB,X      ; accumulator low
#     1672  BD B5 1A  LDA $1AB5,X      ; step high
#     1675  7D BE 1A  ADC $1ABE,X
#     1678  9D BE 1A  STA $1ABE,X      ; accumulator high
#
# and the accumulator is added to the note's own table frequency on the way to
# the chip -- $1461-$1476 for the ordinary path and $17A0-$17CC for the other,
# which ends `STA $D401` / `STA $D400`. So it is a per-frame 16-bit frequency
# delta, exactly the digi engine's `$82` (DIGI_SLIDE): first operand HIGH,
# second LOW, and **signed**, because the add is one CLC/ADC pair with no
# direction test anywhere.
#
# **IT IS PER EVENT, WHICH IS WHAT DECIDES THE EMISSION.** $1147-$114F zeroes
# `$1AB8`, `$1ABB` and `$1ABE` (and the five effect flags after them) at the
# top of every pattern-byte fetch pass, i.e. once per event, BEFORE the
# command loop at $116C reads the bytes that set them. So a `$82` belongs to
# the one event that follows it and dies with it. A Goattracker command byte
# is executed only on the row it appears on (see the header comment on
# `ONE_SHOT_COMMANDS`), so the faithful spelling is: repeat CMD_PORTAUP /
# CMD_PORTADOWN on the event's own row AND on each of its `wait` hold rows,
# and emit nothing on the next event's rows -- which reproduces the player's
# reset for free rather than needing a stop command.
ILV_SLIDE = 0x82
ILV_COMMAND_OPERANDS = {0x80: 1, ILV_SLIDE: 2, 0x83: 1, 0x84: 0,
                        0x86: 1, 0x87: 2, 0x88: 0, 0x89: 1}


def _build_raw_pattern_ilv(data: bytes, addr: int,
                           note_base: int = 0,
                           instr_base: int = 2,
                           span: Optional[List[int]] = None,
                           slides: bool = False,
                           steps: Optional[List[int]] = None,
                           ) -> Optional[List[int]]:
    """Flat event stream for one interleaved-engine pattern, or None.

    Returns None rather than guessing on an unrecognised `$80-$BF` byte: the
    player's own dispatch falls through `$11AE BNE $116C` with no INY there
    and would spin, so such a byte means the decode has lost the stream and a
    skip would invent music.

    With `slides`, command `$82` becomes a portamento -- see ILV_SLIDE for the
    routine it is read from. It is attached to the event that follows it and
    repeated on that event's hold rows, because the player clears the step at
    every fetch and a Goattracker command runs only on its own row; the two
    facts cancel, so no stop command is needed. Off by default like every
    other decoder's slide reading, and `presets.json`'s `always` block turns
    it on.
    """
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    instrument = 0
    wait = 0
    i2 = 0
    pending: Optional[tuple] = None

    while True:
        if addr + i2 <= 1 or addr + i2 >= len(data):
            return None
        b = data[addr + i2]

        if b == ILV_END:
            events += [GT_END_PATTERN, 0x00, 0x00, 0x00]
            if span is not None:
                span.append(i2 + 1)
            return events

        if b >= 0xC0:                       # duration; emits no row
            wait = b & 0x1F
            i2 += 1
            continue

        if b >= 0x80:                       # command
            n = ILV_COMMAND_OPERANDS.get(b)
            if n is None:
                return None
            if addr + i2 + n >= len(data):
                return None
            if b == 0x80:
                instrument = data[addr + i2 + 1] + instr_base
            elif b == ILV_SLIDE and slides:
                # First operand high, second low, and the pair is signed: the
                # player has one CLC/ADC and no direction test.
                step = (data[addr + i2 + 1] << 8) | data[addr + i2 + 2]
                if step >= 0x8000:
                    pending = (2, 0x10000 - step)   # CMD_PORTADOWN
                else:
                    pending = (1, step)             # CMD_PORTAUP
            i2 += 1 + n
            continue

        if b == ILV_REST:
            events += [GT_KEYOFF, 0x00, 0x00, 0x00]
        else:
            note = max(0, min(b, ILV_MAX_NOTE) + note_base) + 0x60
            events += [note, instrument, 0x00, 0x00]
        cmd = _digi_command(pending, steps) if pending is not None else None
        if cmd is not None:
            events[-2], events[-1] = cmd
        for _ in range(wait):
            events += [GT_NO_NOTE, 0x00, 0x00, 0x00]
            if cmd is not None:
                # Continuous, so it is repeated rather than held: gplay.c
                # executes a command on the row it appears on and nowhere
                # else. The player's own step lasts exactly this event.
                events[-2], events[-1] = cmd
        pending = None
        i2 += 1


def _build_raw_pattern_cmdtable(data: bytes, addr: int, durations: int,
                                operands, instr_cmd: int,
                                frames_per_row: int = 1,
                                collect: Optional[Set[int]] = None,
                                note_base: int = 0,
                                slides: bool = False,
                                slide_cmd: int = -1,
                                slide_mask: int = 0x3F,
                                steps: Optional[List[int]] = None,
                                instr_base: int = 2,
                                ) -> Optional[List[int]]:
    """Flat event stream for one command-table pattern, or None if unusable.

    With `collect` given, the durations the pattern uses are added to it and
    the returned stream is ignored -- that pre-pass is how frames_per_row is
    derived (see cmdtable_frames_per_row).

    With `slides` and a `slide_cmd` from detection, that command becomes a
    portamento: its first operand is the step's low half, its second carries
    the high half under `slide_mask` and the direction in bit 7. Its third
    operand is a per-voice onset delay in frames, which Goattracker has no way
    to express and which is therefore read and dropped -- the one
    approximation here. See detect.CMDTABLE_SLIDE_SHAPE.
    """
    if addr <= 1 or addr >= len(data):
        return None

    events: List[int] = []
    instrument = 0
    pending: Optional[tuple] = None

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
                instrument = data[addr + 1] + instr_base
            elif c == slide_cmd and slides and operands[c] >= 2:
                lo, d2 = data[addr + 1], data[addr + 2]
                step = ((d2 & slide_mask) << 8) | lo
                # `LDA dir,X / BPL up`: bit 7 clear adds, set subtracts.
                pending = ((2 if d2 & 0x80 else 1), step)
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
        if pending is not None:
            events[-2], events[-1] = _digi_command(pending, steps)
            pending = None
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
                 status_bit6: bool = False,
                 steps: Optional[List[int]] = None,
                 rest_instrument: bool = False,
                 instr_base: int = 2, tie: bool = False,
                 rest_keyoff: bool = False,
                 rest_wave: bool = False,
                 rest_envelope: bool = False,
                 exits_tied: Optional[List[bool]] = None
                 ) -> Optional[List[int]]:
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
        return _build_raw_pattern_digi(data, addr, det.note_base,
                                       slides=slides, steps=steps,
                                       instr_base=instr_base)
    if det.pattern_dialect == "ilv":
        return _build_raw_pattern_ilv(data, addr, note_base=det.note_base,
                                      instr_base=instr_base,
                                      slides=slides, steps=steps)
    if det.pattern_dialect == "cmdtable":
        return _build_raw_pattern_cmdtable(
            data, addr, det.duration_table, det.cmd_operands,
            det.cmd_instrument, det.frames_per_row,
            note_base=det.note_base, slides=slides,
            slide_cmd=det.cmd_slide, slide_mask=det.cmd_slide_mask or 0x3F,
            steps=steps, instr_base=instr_base)
    return _build_raw_pattern(data, addr, slides and det.slide_operand,
                              det.note_flag, status_bit6 and det.status_bit6,
                              rest_instrument=rest_instrument,
                              rest_keyoff=rest_keyoff,
                              rest_wave=rest_wave,
                              rest_envelope=rest_envelope,
                              instr_base=instr_base,
                              note_base=det.note_base,
                              slide_high_first=det.slide_high_first,
                              steps=steps, tie=tie,
                              gate_hold=tie and det.gate_hold,
                              exits_tied=exits_tied)


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

    The "94 > 64" luck above runs out at `max_rows == GT_MAX_ROWS`: a real,
    unterminated slice that is exactly GT_MAX_ROWS (128) rows fills
    Goattracker's own pattern buffer to its declared capacity, leaving no
    row behind it for clearpattern()'s pre-fill to have survived on -- the
    rescan runs straight past the buffer into whatever memory follows,
    which on real hardware/VICE is several seconds of near-silence before it
    happens to find a byte that reads as ENDPATT (H2G-CONVERSION-METHOD.md
    §7.rr). Only reachable when `terminate` is false, since a terminated
    128-row slice gets its marker as row 129 -- still inside the buffer
    (MAX_PATTROWS*4+4 bytes, see the .sng layout section of the method doc).
    Shaving one row off keeps every *other* max_rows value's chunking
    unchanged: 127 was already safe by the same "row behind it" logic this
    docstring describes for 94.
    """
    if not terminate and max_len == GT_MAX_ROWS * 4:
        max_len -= 4
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
            events = _build_raw_pattern_digi(data, addr,
                                             slides=slides)
        elif det.pattern_dialect == "ilv":
            events = _build_raw_pattern_ilv(data, addr,
                                            note_base=det.note_base,
                                            slides=slides)
        elif det.pattern_dialect == "cmdtable":
            events = _build_raw_pattern_cmdtable(
                data, addr, det.duration_table, det.cmd_operands,
                det.cmd_instrument, det.frames_per_row, slides=slides,
                slide_cmd=det.cmd_slide,
                slide_mask=det.cmd_slide_mask or 0x3F)
        else:
            events = _build_raw_pattern(data, addr,
                                        slides and det.slide_operand,
                                        det.note_flag,
                                        status_bit6 and det.status_bit6,
                                        span=span,
                                        slide_high_first=det.slide_high_first)
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


def _scaled_step(step: int, multiplier: int, row_calls: int = 0) -> tuple:
    """A 16-bit per-frame step as a per-call (hi, lo) speed-table entry.

    Never rounds down to zero: a step of nothing is a slide that does not move,
    which is further from the player than the slowest step the table can hold.
    Never reaches $8000 either -- a left side that high selects Goattracker's
    note-relative mode (gplay.c:539-547) and would mean something else
    entirely. Both bounds are reachable only with absurd inputs; they are here
    so that is a fact about the code rather than about the corpus.

    `row_calls` is the row length in play calls, and compensates the one call a
    slide loses every row. A row lasts `tempo + 1` calls (gplay.c:325) and the
    portamento does not run on one of them, so a step encoded at face value is
    delivered at `(row_calls - 1) / row_calls` of its intended rate -- measured
    at or below that ceiling in 13 of 13 files with enough steady runs to
    measure, and at `row_calls == 3`, the corpus's most common tempo, that
    discards a third of every bend. See H2G-CONVERSION-METHOD.md section 7.vv.

    Zero means "do not compensate", and so does anything under 3: below that
    the value is funktempo rather than a rate (gplay.c:325), and `row_calls - 1`
    stops being a call count worth dividing by.
    """
    if row_calls >= 3:
        step = step * row_calls / (row_calls - 1)
    v = min(max(1, round(step / max(1, multiplier))), 0x7FFF)
    return (v >> 8) & 0xFF, v & 0xFF


def build_speed_table(patterns: List[List[int]],
                      multiplier: int = 1,
                      steps: Optional[List[int]] = None,
                      row_calls: int = 0) -> List[tuple]:
    """Encode every portamento parameter as a speed table, in place.

    Rewrites each speedtable-requiring command's data column to a 1-based
    index and returns the table as (left, right) pairs.

    The encoding is Goattracker's own, so a GTS5 file plays identically to the
    GTS2 file it was written from: `makespeedtable(v, MST_PORTAMENTO)` is
    `l = (v << 2) >> 8, r = (v << 2) & 0xff` (gtable.c:881-884), i.e. the
    16-bit frequency step is four times the stored value. gplay.c reassembles
    it as `(l << 8) | r`.

    `multiplier` is the gt2reloc -S factor the file will be packed at. The step
    the pattern decoder read is the *player's*, applied once per frame; a
    speed-table step is applied once per play call (gplay.c:748/758), so at -S2
    the same number slides twice as far per frame. Dividing here is what makes
    the emitted slide the player's slide -- and it is exact, because the table
    stores the 16-bit step rather than the pattern column's eighth of it.

    `row_calls` compensates the call a slide loses per row; see _scaled_step.
    It is one number for the whole file rather than one per pattern because 17
    of the 18 corpus files carrying several tempos play at least one pattern at
    two different ones, so a per-pattern value is ambiguous exactly where it
    would be needed. The caller passes the *largest* row length, which
    under-compensates a faster subtune rather than overshooting a slower one --
    and for the 65 of 83 files whose subtunes all share one tempo it is exact.

    The table cannot overflow: a data byte has 255 non-zero values and each
    distinct one costs one entry, which is exactly MAX_TABLELEN. Compensation
    cannot change that -- it is one monotone map applied to every value, so it
    can merge distinct steps but never split one.
    """
    m = max(1, multiplier)
    if steps is not None:
        # The decoder already wrote 1-based indices into the data column, so
        # the table is `steps` itself and no column needs rewriting. This is
        # the path that carries the step at full 16-bit width; see _step_index.
        return [_scaled_step(v, m, row_calls) for v in steps]
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
                # Never round down to zero: a step of nothing is a slide that
                # does not move, which is further from the player than the
                # slowest step the table can hold.
                table.append(_scaled_step(value * 4, m, row_calls))
            pattern[k + 3] = index[value] + 1
    return table


def scale_portamento_data(patterns: List[List[int]], multiplier: int) -> int:
    """Divide every portamento parameter by `multiplier`, in place.

    The GTS2 counterpart of build_speed_table's division, for the same reason:
    a GTS2 file stores no speed table, and its loader rebuilds one from the
    pattern data column (gsong.c:311-321) as `value * 4`. So the column is the
    only place the rate can be scaled -- and unlike the speed table it holds an
    eighth of the step, which is why this rounds where build_speed_table does
    not. Returns the number of columns changed.

    Not called at -S1, where it would be the identity.
    """
    m = max(1, multiplier)
    changed = 0
    for pattern in patterns:
        for k in range(0, len(pattern), 4):
            cmd, value = pattern[k + 2], pattern[k + 3]
            if cmd not in GT_SPEEDTABLE_COMMANDS or not value:
                continue
            scaled = max(1, round(value / m))
            if scaled != value:
                pattern[k + 3] = scaled
                changed += 1
    return changed


class TrackIndex(list):
    """The per-entry slice lists, with each entry's exit tie state attached.

    `exits_tied[i]` says whether pattern-table entry `i`'s decode ended with
    `_build_raw_pattern`'s `pending_tie` set -- i.e. whether the player would
    carry an open gate out of that pattern and into whatever the orderlist
    plays next. It has to travel from `convert_patterns`, which is the only
    place a pattern's *bytes* are read, to `reindex_tracks`, which is the only
    place the *orderlist* and the sliced patterns are both in hand; a list
    subclass is what lets it do that without every caller in between having to
    grow a parameter for it. Same shape, and for the same reason, as
    fidelity.Trace hanging the global filter state off the three voices.

    A plain list is still a valid `track_index` -- `reindex_tracks` reads the
    attribute with `getattr`, so a caller that builds one by hand simply gets
    no boundary ties.
    """

    def __init__(self, items=(), exits_tied=None):
        super().__init__(items)
        self.exits_tied: List[bool] = list(exits_tied or ())


def convert_patterns(sid: SidFile, det: Detection, log,
                     max_rows: int = GT_DEFAULT_ROWS,
                     terminate_patterns: bool = False,
                     dedup: bool = False,
                     used: Optional[Set[int]] = None,
                     slides: bool = False,
                     status_bit6: bool = False,
                     phantoms: Optional[dict] = None,
                     variants: Optional[List[tuple]] = None,
                     steps: Optional[List[int]] = None,
                     rest_instrument: bool = False,
                     instr_base: int = 2, tie: bool = False,
                     rest_keyoff: bool = False,
                     rest_wave: bool = False,
                     rest_envelope: bool = False):
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
    # Entry -> "the decode ended with pending_tie set". Default False, which is
    # what every entry that is not decoded at all (pruned, phantom, out of
    # range) has to be: an ERROR_PATTERN carries no note and ties into nothing.
    exits: Dict[int, bool] = {}
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

        ex: List[bool] = []
        events = decode_entry(sid, det, i, slides, status_bit6, steps,
                              rest_instrument, instr_base, tie=tie,
                              rest_keyoff=rest_keyoff,
                              rest_wave=rest_wave,
                              rest_envelope=rest_envelope, exits_tied=ex)
        exits[i] = bool(ex and ex[0])
        if events is None:
            log(f"*** PATTERN ${i:X} ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            events = list(ERROR_PATTERN)
        raw_patterns.append(events)

    # Appended after the whole table, never inserted into it, so entry numbers
    # 0..pattern_used keep meaning what the orderlists say they mean.
    for src, octaves in (variants or ()):
        base = raw_patterns[src] if 0 <= src < len(raw_patterns) else None
        if base is None:
            ex = []
            base = decode_entry(sid, det, src, slides, status_bit6,
                                steps, tie=tie, exits_tied=ex)
            exits[src] = bool(ex and ex[0])
        # A variant is the source's own event stream with its notes shifted, so
        # it ends on the source's status byte and leaves the gate exactly as
        # the source does.
        exits[len(raw_patterns)] = exits.get(src, False)
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

    return new_patterns, TrackIndex(
        track_index,
        [exits.get(i, False) for i in range(len(raw_patterns))])


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


def _entry_reference(track: List[int]) -> int | None:
    """Index into `track` of the first byte that names a pattern, or None.

    The orderlist grammar, not a scan for a small byte: `$FF` is followed by a
    restart *position*, which is small and is not a pattern reference.
    """
    expect_operand = False
    for i, b in enumerate(track):
        if expect_operand:
            expect_operand = False
        elif b == GT_ORDER_RESTART:
            expect_operand = True
        elif b < GT_COMMAND_FLOOR:
            return i
    return None


def regrid_tempos(patterns: List[List[int]], tracks: List[List[int]],
                  bases: List[int], deficits: List[float],
                  multiplier: int = 1, log=None) -> int:
    """Spend the fractional part of a row the tempo cannot express.

    A Goattracker row is a whole number of play calls, so a player whose row
    is 384/127 = 3.0236 frames (Auf Wiedersehen Monty, subtune 0) is emitted
    at 3 and loses 0.0236 frames every row. Nothing about the music is wrong
    -- `--pace` reads the ratio as 1.000 over 436 gaps -- but the tune runs
    0.78% fast and the error INTEGRATES: 15 frames by 38 seconds, which is
    where a listener reported voice 2 entering early after a 12-second rest.
    A voice that never stops is inaudibly fast; a voice that re-enters is
    audibly early against the ones that did not.

    `effective_frames` already declines the exact row when its denominator
    exceeds MAX_ROW_DENOMINATOR, because 384/127 wants `-S127`. That refusal
    is right and this is the other half of it: **3 is the best rational
    approximation to 3.0236 at every denominator up to 10** (the next
    candidate, 31/10, is three times worse), so no tempo can fix this and the
    only repair is to give one row in 42 an extra call and take it back.

    THE COMPENSATION IS A PROPERTY OF THE PATTERN, NEVER OF THE ORDERLIST
    POSITION, and that is what makes it affordable. Goattracker's patterns are
    global -- 56 of Monty's 153 are played more than once -- so a per-position
    schedule would need a copy per phase, the cost that stopped the pulse-phase
    work. Choosing the rows from the pattern's own geometry means every
    occurrence behaves identically, which is what a global structure requires.

    Three refusals, each of which is a defect this repo has already shipped
    once:

    * **Row 0 is never taken.** It belongs to the subtune's clock
      (`TEMPO_OVERWRITABLE`), and a row-0 command silently costs a subtune its
      `CMD_SETTEMPO` -- three changes have been caught by that.
    * **The restore stays inside the pattern.** The row after a lengthened one
      must put the tempo back, and the row after the LAST row is whatever the
      orderlist plays next -- which is position-dependent, so the last row is
      never chosen.
    * **A pattern reached by subtunes with different clocks is left alone.**
      `CMD_SETTEMPO` under $80 sets all three channels, so the restore value
      would be wrong for the other subtune -- the v0.5.330 defect exactly.

    `deficits` is in FRAMES per row and the command counts CALLS, so a
    multispeed song needs `frames * multiplier` calls of compensation; below
    one whole call the pattern is skipped rather than rounded up.

    WHY THIS IS PER SONG AND NEVER A DEFAULT, measured at v0.5.407.
    One_on_One loses 37.0pp of melody and Sanxion 19.9pp, and the cause is
    now bounded from both sides:

    * **It is the EXTRA CALL, not the command.** Writing the same
      `CMD_SETTEMPO` pair with `base` instead of `base + 1` -- the column
      occupied identically, the row not lengthened -- costs **0.0pp on both
      files**, and each damaged voice's collapsed-note count returns exactly
      to its baseline (One_on_One v3 189, Sanxion v2 346). So nothing about
      placing the command is wrong.
    * **The damage is WRONG PITCHES, not extra attacks.** In the damaged
      voice the attack count *falls* slightly (One_on_One v3 375 -> 371)
      while the COLLAPSED count rises (189 -> 211 against the original's
      186). `melody` collapses consecutive duplicates, so a longer collapsed
      sequence means more adjacent notes now DIFFER -- notes being named as
      neighbouring semitones, which is what a per-call pitch generator
      sampled at a shifted phase produces. siddump names a note from the
      frequency on the frame the gate rises, so one extra call before that
      frame is enough.
    * **One voice per file, and NOT always voice 0's neighbours.** The guard
      above checks the command column of the pattern it writes into, which is
      voice 0's; `CMD_SETTEMPO` under $80 sets all three channels
      (gplay.c:494), so the lengthening reaches voices 1 and 2 where nothing
      looked. This bullet used to say "Never voice 0", inferred from two
      files; measured over all seven at v0.5.410, **Powerplay Hockey's damaged
      voice IS voice 0**. What does hold is that exactly one voice per file is
      damaged, and `--diagnose`'s worst-voice ratio is monotone in the file's
      loss: One_on_One v2 0.47 (-37.0pp), Sanxion v1 0.55 (-19.9pp), Wiz v1
      0.79 (+0.8pp), Powerplay v0 0.84 (-2.9pp), and Rikky, Sigma Seven and
      Arcade Classics all >= 0.97 (~0pp).

    TWO LEADS ARE DEAD, and one of them was this defect's own title.
    An "extended in-progress slide" is refuted: with `slides` off entirely
    the collapse is IDENTICAL (-37.0pp and -19.9pp, 189 -> 211 and
    346 -> 357), and `slides: False` demonstrably changes both files' bytes,
    so the arm is not vacuous. Three earlier hypotheses -- the funktempo
    restore value, over-delivery, and slide-heaviness -- are recorded dead in
    `runs.jsonl` under `regrid-melody-collapse-on-the-six-refused-files`.

    THEY DO SHARE ONE CAUSE, AND IT IS `--no-test-restart`. The paragraph
    this replaces said the opposite -- "the two files do not share one cause"
    -- on the strength of a vibrato A/B, and that reading was WRONG. It is
    corrected here rather than only in a commit message, because the wrong
    version is exactly the kind of sentence that gets quoted forward.

    Turning `no_test_restart` off removes the collapse on BOTH files, and the
    damaged voice lands on the original's own note count:

        Sanxion     -19.9pp -> **+0.2pp**   v2 collapsed 346 -> 343 (orig 344)
        One_on_One  -37.0pp -> **+0.5pp**   v3 collapsed 188 -> 186 (orig 186)

    Neither `slides`, `vibrato` nor `two_stage` moves Sanxion's -19.9pp by a
    tenth of a point. Vibrato DOES mask One_on_One's (-37.0 -> -0.2), which is
    what produced the wrong reading: it is a CO-FACTOR on that file, not the
    cause, and one A/B that happens to remove a symptom is not an attribution.

    The mechanism is the one this option is already documented for.
    `--no-test-restart` deletes the testbit frame, which is the only frame our
    conversions spend below $10, and siddump needs a frame below $10 to name an
    attack at all (siddump.c:434-437). So that option OWNS FRAME 0 -- and a
    compensating row moves the frame boundary underneath it. Nothing here is a
    pitch generator; it is two options contending for one frame, which is the
    Star Paws shape CLAUDE.md already records: when a forced option produces a
    COLLAPSE rather than a shortfall, suspect the combination before the
    mechanism.

    NECESSARY, NOT SUFFICIENT -- and that is the open question, which is also
    the Rikky question in its sharper form. **SEVEN** corpus files carry
    `no_test_restart` and are regrid-eligible, not six: Powerplay Hockey is
    the one this paragraph used to miss, and it ships `regrid: false` because
    it was never measured rather than because it was refused -- `--regrid` is
    not searchable by `fidelity_better`, so every adoption is hand-recorded
    and an unmeasured file is indistinguishable from a rejected one. Measured
    at v0.5.410 (melody, regrid off -> on): Arcade_Classics -0.01, Sigma_Seven
    -0.14, Rikky -0.79, Wiz **+0.84**, Powerplay **-2.87**, Sanxion -19.87,
    One_on_One -37.02. It is a continuum, and "four immune, two collapse" was
    an artefact of the missing seventh and of reading a per-FILE number: Wiz
    carries a voice at 0.79 while its file score improves.

    THREE CANDIDATE DISCRIMINATORS ARE DEAD, all measured at v0.5.410.
    **Dose**: compensating rows per 1000 song rows run Wiz 2.90, Arcade 3.73,
    Sigma_Seven 3.89, Sanxion 4.13, Powerplay 4.83, One_on_One 7.34, **Rikky
    13.18** -- Rikky takes the heaviest dose of all seven, 196 rows against
    One_on_One's 41, and is unharmed. **Per-call pitch movement**, at file
    level: Rikky has the most slides per attack (29.5) and is immune, while
    Sanxion has the FEWEST of everything (0.43 slides, 0.82 reversals, 48.5
    bend per attack) and collapses second-worst -- exactly backwards. **A
    harness subtune artefact**: the correspondence is the identity 0->0 and
    `startup_lag` is identical in both arms on all seven, so the two arms do
    compare the same music.

    AND THE TWO CASUALTIES DO NOT SHARE A PROXIMATE DAMAGE, though
    `no_test_restart` remains necessary for both. Sanxion's damaged voice has
    its pitches **97% the same** at ratio 0.55 -- spurious or missing note
    EVENTS, not misnaming -- where One_on_One's has pitches 40% the same and
    no constant shift beats it. Note also that `--regrid` moves our attack
    count toward the original's on all seven and exactly onto it on five,
    One_on_One included (543 -> 537 against 537) while its melody falls 37pp:
    the right notes, in the right number, with the wrong names.

    THE STANDING LEAD, unfalsified, is cross-voice pattern GEOMETRY. The
    compensation is chosen from voice 0's exclusive patterns and placed by
    voice 0's geometry, but the lengthening reaches all three channels -- so
    where the other voices share voice 0's pattern lengths it lands at a
    musically equivalent point, and where they do not it lands arbitrarily.
    Rikky's three voices are near-identical ([2,4,5,65,68,127] /
    [2,3,5,65,68,127] / [2,3,5,17,68,127]) and it absorbs 196 compensations;
    Sigma Seven's v0 and v1 are identical; One_on_One's damaged v2 is [17,65]
    against v0's [2,3,33,53,65,127] and is the worst. Falsify it by forcing
    compensation into a length-matched and a mismatched pattern on ONE file
    and seeing whether the effect follows the geometry rather than the file.
    Until then: do not adopt `--regrid` on a file carrying `no_test_restart`
    without measuring that file.

    **THE DISCRIMINATOR IS FOUND, AND IT IS NOT A PROPERTY OF THE FILE BUT OF
    WHAT `melody` SCORES** (v0.5.436). `melody` is a difflib ratio over the
    COLLAPSED attack sequence -- consecutive repeats removed, `compare()` at
    fidelity.py:828 -- so the cost of an attack being renamed depends entirely
    on its neighbours:

        inside a run   X X X  ->  X Y X   one collapsed note becomes THREE
        isolated       W X Y  ->  W Y Y   one substitution, possibly none

    So `--regrid` perturbs every file's attack grid, and that only costs
    anything where the perturbation SPLITS A RUN of repeated attacks. Measured
    as the collapsed-note count against the ORIGINAL's: without `--regrid`
    every file sits just above it (+2..+9), and with it the refused files'
    surplus GROWS while the adopted files' SHRINKS TOWARD ZERO --

        REFUSED   One_on_One +6 -> +24   Sanxion +6 -> +12   Powerplay +4 -> +6
        ADOPTED   Rikky +4 -> -1   Sigma_Seven +2 -> +1   Arcade +3 -> +1
                  Wiz +9 -> +3

    -- a separation by DIRECTION with no overlap, and the melody loss is
    monotone in the growth (+18 -> -37.0pp, +6 -> -19.9pp, +2 -> -2.9pp).
    Renames landing inside a run agree: 86 / 100 / 29 on the refused files
    against 4 / 14 / 10 / 4 on the adopted. This also explains why the RENAME
    RATE never separated them -- Wiz churns 127 renames and GAINS 0.8pp
    because its voice 0 alternates on 99% of consecutive pairs and has almost
    nothing to split, where One_on_One's voice 2 is 93 singles and 93 TRIPLES.
    It does not retire the cross-voice geometry lead above; geometry may well
    be what decides WHERE a compensation lands, and this says what it costs
    when it lands in a run.

    **THE POPULATION IS 17 REACHED / 5 REFUSED, NOT THE 18 / 6 THIS FILE AND
    CLAUDE.md BOTH RECORDED.** Re-measured at v0.5.436 by corpus byte-hash --
    convert every file on its shipped preset with `regrid` forced False and
    True, 83 of 83 converting -- `--regrid` moves 17 files, 12 are adopted,
    and the refusals are BMX_Kidz, IK_plus, One_on_One, Powerplay and Sanxion.
    Settled on that measurement, with `drift` from `fidelity.drift()`:

        IK_plus     melody 99.0 -> 99.4   surplus +6 -> -4   drift 8.85 -> 4.10
                    ADOPTED: the adopted signature on every column.
        BMX_Kidz    melody 100.0 -> 100.0 surplus +0 -> +0   drift -7.87 -> -7.87
                    REFUSED: the bytes move and NOTHING else does -- the drift
                    is identical to two decimals, so the compensation does not
                    reach this file's phase error at all. No upside to record.
        Sanxion     melody 96.6 -> 76.7   surplus +6 -> +12  drift 9.17 -> 4.42
                    REFUSED: drift more than halves and melody collapses 19.9pp
                    -- the option working as designed and destroying the score.
        One_on_One  melody 98.6 -> 61.6   surplus +6 -> +24  drift UNFITTABLE
                    REFUSED: with `--regrid` the offsets scatter 725 frames
                    about the fit over 2967, i.e. the two sides stop drifting
                    and start wandering; no rate describes them.
        Powerplay   melody 99.3 -> 96.4   surplus +4 -> +6   drift 7.90 -> 1.12
                    NOT SETTLED HERE -- a user adoption call carried by
                    `powerplay-regrid-refusal-rests-on-a-naming-artefact`.
                    Note for that decision: its drift improves SEVENFOLD.

    **A ROW GUARD FOR THE `--no-test-restart` CLASH IS REFUTED, measured at
    f0fd20c.** The proposal was to decline compensation on the rows where
    `--no-test-restart` owns frame 0. This schedule writes only into voice 0's
    exclusive patterns, so such a guard can inspect voice 0 and nothing else,
    and two counts close it: only **142 of 1107 lengthened rows (12.8%)** have
    a voice-0 note on the row after the lengthened one -- One_on_One 7 of 41,
    Sanxion 7 of 73, Powerplay 6 of 45 -- and the damaged voice is **v2** on
    One_on_One and **v1** on Sanxion, which no voice-0 test can see. Declining
    those rows would also cost the 13 adopters budget (Rikky 14 of 196) for a
    guard that cannot reach two of the three casualties. The cross-voice
    version is ill-defined for the reason the paragraph above gives.

    So the incompatibility is DOCUMENTED rather than guarded, and the
    discriminator is the collapsed-surplus DIRECTION below, which needs a
    trace. README.md § `--regrid` carries the whole account, including why no
    trace-free proxy exists.
    """
    groups = len(tracks) // 3
    if groups != len(bases) or groups != len(deficits):
        raise ValueError(f"{groups} subtune(s) but {len(bases)} base(s) "
                         f"and {len(deficits)} deficit(s)")

    # Which subtunes reach each pattern, and therefore whose clock the
    # restore would have to name -- and how often each pattern is PLAYED,
    # which is the quantity the budget below is denominated in. A pattern
    # played five times delivers its compensation five times; budgeting it
    # once over-supplies by exactly that factor, which is how the first
    # version of this turned a 15-frame deficit into a 16-frame surplus.
    # **`plays` IS BUILT AND NEVER READ, AND THE DEFECT ITS OWN COMMENT
    # DESCRIBES IS THEREFORE LIVE** (found at v0.5.453, chasing BMX_Kidz).
    # The debt below accumulates PER ORDERLIST ENTRY, which is right -- every
    # play raises its own fraction. But it is spent with
    # `want[pat] = max(want.get(pat, 0), n)`, which writes `n` rows into the
    # PATTERN once, and a pattern is then PLAYED `plays[pat]` times. So the
    # delivery is `n * plays[pat]` while `acc` was debited about `n`.
    #
    # It bites in proportion to how CONCENTRATED a subtune's exclusive
    # patterns are and how often they replay. Measured -- debt in calls
    # against compensation actually delivered:
    #
    #     BMX_Kidz     46.28 ->  172   **3.72x**   4 patterns, plays 12/6/6/1
    #     After_8     179.95 ->  179     0.99x    34 patterns, plays mostly 1-3
    #     Monty       145.21 ->  163     1.12x    49 patterns
    #     Rikky       250.35 ->  251     1.00x    34 patterns
    #     Sanxion     142.64 ->  149     1.04x    28 patterns
    #
    # The twelve adopters land at 0.99-1.12x because they spread the
    # compensation over dozens of patterns played once or twice, so
    # `n * plays == n` to within rounding and nobody noticed. BMX_Kidz writes
    # into FOUR patterns played 12, 6, 6 and 1 times, and its drift goes
    # -7.81 -> **+44.88** at `-t 180` (at `-t 60` it reads -7.87 -> -7.87
    # unchanged, which is why this looked like "regrid moves the bytes and
    # not the drift" for two sessions -- the short window hid an
    # over-correction, not an absence).
    #
    # THE FIX IS NOT SHIPPED HERE and the reason is blast radius rather than
    # difficulty: debiting `n * plays[pat]`, or capping `n` so that
    # `n * plays[pat] <= acc`, changes the bytes of all 17 reached files --
    # including the 12 whose adoption was MEASURED under this arithmetic, so
    # every one of those decisions would need re-searching and both fidelity
    # artefacts regenerating. That wants a task declaring presets.json,
    # docs/FIDELITY.md and build/fidelity.json; see
    # `regrid-over-supplies-a-subtune-whose-exclusive-patterns-replay`.
    # `tests/test_regrid.py` carries an xfail(strict=True) for the correct
    # behaviour, so whoever fixes it is told to drop the marker.
    reach: dict = {}
    where: dict = {}
    plays: dict = {}
    for k in range(groups):
        for ti in range(3 * k, 3 * k + 3):
            if ti >= len(tracks):
                continue
            operand = False
            for entry in tracks[ti]:
                if operand:
                    operand = False
                elif entry == GT_ORDER_RESTART:
                    operand = True
                elif entry < GT_COMMAND_FLOOR:
                    reach.setdefault(entry, set()).add(k)
                    where.setdefault(entry, set()).add((k, ti - 3 * k))
                    plays[entry] = plays.get(entry, 0) + 1

    # THE BUDGET IS PER SUBTUNE, over that subtune's own orderlist, and it
    # only spends patterns that subtune has to itself. A pattern several
    # subtunes play delivers its compensation inside every one of their
    # timelines, so budgeting it against its total play count over-supplies
    # whichever subtune plays it least -- measured on Monty, that turned a
    # 15-frame deficit into a 24-frame surplus, the same size of error in the
    # other direction. An exclusive pattern is the only one whose deliveries
    # a single subtune's debt can account for.
    plan: dict = {}
    for k in range(groups):
        d = deficits[k]
        base = bases[k]
        if d <= 0:
            continue
        # ONE VOICE ONLY. `CMD_SETTEMPO` under $80 sets all three channels
        # (gplay.c:494), so a compensating row placed in each of the three
        # voices' patterns lengthens the same row three times -- measured, a
        # 15-frame deficit became a 21-frame surplus, and the 2.4x is the
        # three voices minus what the occupied-column check declined. The
        # debt is one subtune's, so the schedule that pays it is one voice's.
        order = []
        ti = 3 * k
        if ti < len(tracks):
            operand = False
            for entry in tracks[ti]:
                if operand:
                    operand = False
                elif entry == GT_ORDER_RESTART:
                    operand = True
                elif entry < GT_COMMAND_FLOOR and entry < len(patterns):
                    order.append(entry)
        if not order:
            continue
        # Exclusive to this subtune AND to this voice: a pattern voice 1 also
        # plays would deliver the same row twice inside one subtune.
        exclusive = {p for p in set(order)
                     if reach.get(p) == {k} and where.get(p) == {(k, 0)}}
        # Error diffusion along the orderlist: every played row adds its own
        # fraction of a call to the debt, and only an exclusive pattern can
        # pay it. The debt a shared pattern raises is carried forward rather
        # than dropped, so the exclusive ones absorb the whole subtune's
        # deficit and the rate stays right on average.
        # **How often THIS subtune's voice 0 plays each pattern**, which is
        # the quantity the budget is denominated in. A row written into a
        # pattern fires once per PLAY, so `n` rows in a pattern played `p`
        # times deliver `n * p` calls of compensation -- and until v0.5.455
        # the debit was `n`, so a replayed pattern over-supplied by exactly
        # `p`. `plays` above counts every subtune and voice; this counts the
        # orderlist actually being budgeted, and for an `exclusive` pattern
        # (reach == {k} and where == {(k, 0)}) the two agree by construction.
        order_plays: dict = {}
        for pat in order:
            order_plays[pat] = order_plays.get(pat, 0) + 1
        acc = 0.0
        want: dict = {}
        for pat in order:
            rows = len(patterns[pat]) // 4
            acc += d * rows * multiplier
            # `rows` counts the GT_END_PATTERN row, so the last MUSICAL
            # row is rows - 2 and a lengthened row needs rows - 3 at the
            # latest: its restore must be a real row, not the end marker,
            # or the raised tempo leaks into whatever plays next.
            if pat in exclusive and acc >= 1.0 and rows >= 4:
                # **Buy rows for every play at once, and pay for every play.**
                # `prev` is what this pattern already carries, so only the
                # INCREMENT is charged -- which keeps the error diffusion the
                # comment above describes (a later visit can still raise the
                # count as the debt grows) while making delivery and debit the
                # same quantity. `int(acc / p)` is what the accumulator can
                # afford across all `p` plays; where it is 0 the row is simply
                # not bought yet and the debt carries forward, exactly as a
                # shared pattern's does.
                p = max(1, order_plays.get(pat, 1))
                prev = want.get(pat, 0)
                n = min(prev + int(acc / p), max(1, (rows - 3) // 2))
                if n > prev:
                    want[pat] = n
                    acc -= (n - prev) * p
        for pat, n in want.items():
            plan[pat] = (base, n)

    written = skipped = 0
    for pat, (base, n) in plan.items():
        rows = len(patterns[pat]) // 4
        # Spread them: never row 0, and never the last row, whose restore
        # would land in whatever the orderlist plays next.
        spots = [max(1, min(rows - 3, round((i + 1) * rows / (n + 1))))
                 for i in range(n)]
        for r in dict.fromkeys(spots):
            row, nxt = r * 4 + 2, (r + 1) * 4 + 2
            # ONE VOICE'S COLUMN IS THE WHOLE OF WHAT THIS GUARD OWES, and it
            # was proposed at v0.5.411 that it should consult voices 1 and 2
            # at the same row, since CMD_SETTEMPO lengthens all three. That
            # conflates two different things and is a category error.
            # Overwriting a command is this guard's job; the tempo reaching
            # the other voices is a TIMING effect, and no column-occupancy
            # test can address it -- v0.5.408 measured the command's mere
            # presence at 0.0pp on both casualties (base+0, column occupied
            # identically, row not lengthened), so the damage is the extra
            # CALL, which declining columns cannot prevent.
            # And there is nothing there to clobber: `exclusive` above admits
            # only patterns whose `where` is exactly {(k, 0)}, so voices 1 and
            # 2 never play a pattern this writes into. Checked over all 12
            # files that ship --regrid: 304 patterns written, and every one
            # has `where == {(k, 0)}`. (A first census said 2 of them leaked;
            # it was counting the byte AFTER GT_ORDER_RESTART as a pattern
            # reference, which the `operand` skip above exists to avoid.)
            # A positional guard would also be ill-defined: 169 of those 304
            # (55.6%) are replayed, Wiz's up to 14 times, so "what voices 1
            # and 2 are doing at the same row" has up to 14 answers -- and
            # answering it per position is the per-copy cost this schedule is
            # pattern-global to avoid.
            if patterns[pat][row] or patterns[pat][nxt]:
                skipped += 1             # the column is spoken for; leave it
                continue
            patterns[pat][row], patterns[pat][row + 1] = CMD_SETTEMPO, base + 1
            patterns[pat][nxt], patterns[pat][nxt + 1] = CMD_SETTEMPO, base
            written += 1
    if log:
        log(f"Re-grid.................: {written} compensating row(s) in "
            f"{len(plan)} pattern(s) for a fractional row"
            + (f", {skipped} skipped (command column in use)" if skipped else ""))
    return written


def apply_tempos(patterns: List[List[int]], tracks: List[List[int]],
                 values: List[int], log=None) -> int:
    """`apply_tempo` for a song whose subtunes want *different* tempos.

    Patterns are global and orderlists are per subtune, so a value written for
    subtune j is executed by every subtune that plays the same pattern -- and
    `CMD_SETTEMPO` under $80 sets all three channels (gplay.c:494), so it does
    not even have to be the same voice. `apply_tempo`'s docstring said "a
    pattern shared by several positions simply re-applies the same tempo, which
    is harmless"; that is true within one subtune and false across two.

    Human_Race is the case that found it. Its subtune 2 enters voice 0 on
    pattern 0 and is written 3; its subtune 0 enters voice 0 on pattern 1 and
    is written 4 -- but subtune 0 also enters **voice 2** on pattern 0, so both
    writes land on row 0 of the same call and the higher voice index wins.
    Subtune 0 played its whole tune at 3 frames a row where its player's own
    reload table asks for 4: 25% fast, measured as 24-frame note gaps against
    the original's 32, and it read `retrig` 2.28 / `melody` 65% / `drift`
    -250 for it. Seven corpus files and eleven subtunes are in that position,
    five of them files the widened-write A/B measured without anyone noticing
    the default write had the same exposure.

    The rule here is that **a per-subtune tempo may only be written where no
    other subtune with a different tempo can reach it**. Where the entry
    pattern is shared with such a subtune, the pattern is cloned and this
    subtune's *entry reference alone* is repointed at the clone: the rest of
    its orderlist keeps playing the shared original, which is right because a
    re-application of the same tempo mid-tune is the harmless case. Where a
    clone will not fit under `MAX_PATTERNS`, the write is dropped rather than
    made wrong -- the same choice the occupied-command-column case makes.
    """
    groups = len(tracks) // 3
    if groups != len(values):
        raise ValueError(f"{groups} subtune(s) but {len(values)} tempo value(s)")

    def plays(k: int) -> set:
        return set(pattern_references(tracks[3 * k:3 * k + 3],
                                      GT_COMMAND_FLOOR))

    reach = [plays(k) for k in range(groups)]
    written = cloned = dropped = 0
    for k in range(groups):
        track = tracks[3 * k]
        at = _entry_reference(track)
        if at is None or track[at] >= len(patterns):
            continue
        target = track[at]
        if any(j != k and target in reach[j] and values[j] != values[k]
               for j in range(groups)):
            if len(patterns) >= MAX_PATTERNS:
                dropped += 1
                continue
            patterns.append(list(patterns[target]))
            target = track[at] = len(patterns) - 1
            reach[k].add(target)
            cloned += 1
        pattern = patterns[target]
        if len(pattern) < 4:
            continue
        if pattern[2] not in TEMPO_OVERWRITABLE:
            continue
        pattern[2], pattern[3] = CMD_SETTEMPO, values[k]
        written += 1
    if log and (cloned or dropped):
        log(f"Tempo conflicts.........: {cloned} pattern(s) cloned so a "
            f"subtune's tempo cannot reach another's"
            + (f"; {dropped} write(s) dropped at the {MAX_PATTERNS}-pattern "
               f"ceiling" if dropped else ""))
    return written


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
    several positions simply re-applies the same tempo, which is harmless --
    **true only while every subtune wants the same value**. Where they differ,
    `apply_tempos` is the entry point, and it clones a shared entry pattern
    rather than letting one subtune's tempo reach another's; see its docstring
    for the seven files that were reading another subtune's clock.

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
        # The command column is one byte per row and the tempo is not its only
        # claimant, so a subtune whose entry row already carries a command
        # gets no tempo at all and plays at Goattracker's default. That is not
        # a subtle loss -- on the eight files where `--rest-wave-silence`
        # takes row 0, `drift` goes 0 -> ~1000 frames per 1000 and `melody`
        # falls 43pp, which is the whole of that option's regression.
        #
        # **The tempo outranks a rest's waveform, and nothing else.** Widening
        # this to "scan for any free row" was measured and refused twice --
        # v0.5.312, and again at v0.5.318 after v0.5.313's re-grid and
        # v0.5.315's re-search had moved three of the files the first refusal
        # named. It reaches exactly 25 corpus files; 19 of them move no
        # printed number at all, and of the 6 that do, 2 gain and 4 lose:
        #
        #   Knucklebusters  melody 50 -> 81%  retrig 0.39 -> 0.69   gain
        #   Geoff Capes     melody 49 -> 60%  retrig 3.21 -> 2.40   gain
        #   Warhawk         melody 90 -> 47%  retrig 1.00 -> 0.34   loss
        #   Delta Mix-E-Load   seq 100 -> 57% retrig 1.00 -> 0.40   loss
        #   Human Race      melody 65 -> 56%  retrig 2.28 -> 5.57   loss
        #   Rasputin        melody 75 -> 73%  retrig 1.66 -> 1.72   loss
        #
        # `retrig` is the tell and it is exact: every gain moves toward 1.0,
        # every loss away from it. The re-measurement did not weaken the
        # refusal, it strengthened it -- Warhawk's loss was 26pp when it read
        # 82 -> 56% and is 43pp now that the file starts at 90%.
        #
        # **One explanation has been tested and refused.** The obvious reading
        # is that subtune k's value lands on a row another subtune also plays,
        # since the harmlessness argument above is written for row 0 of the
        # ENTRY pattern. A variant restricting the widened write to patterns
        # no other subtune's orderlist references emits **byte-identical**
        # output on all six files, so those patterns are already exclusive and
        # sharing is not the cause. What is left as a lead, unproven: the
        # widened write is not an opening tempo at all but a tempo *change*
        # partway through a pattern, re-applied on every playthrough, and the
        # damage tracks how far the derived value sits from Goattracker's
        # default of 6 -- Warhawk derives 8..40 calls a row and Delta
        # Mix-E-Load 20..127, against [3, 6] for Knucklebusters. That fits the
        # direction of retrig on 5 of the 6 (Geoff Capes is the exception) and
        # has not been tested. Until it is, the absent write stays absent.
        if len(pattern) < 4:
            continue
        if pattern[2] not in TEMPO_OVERWRITABLE:
            continue
        pattern[2], pattern[3] = CMD_SETTEMPO, value
        written += 1
    if log and written:
        log(f"Tempo...................: CMD_SETTEMPO ${value:02X} in {written} "
            f"pattern(s) -- {value if value < 3 else value - 1} tempo, "
            f"{(value if value < 3 else value - 1) + 1} calls per row")
    return written


def _entry_instruments(tracks: List[List[int]],
                       patterns: List[List[int]]) -> dict:
    """`{pattern: set of instruments it can be entered on}`, `None` for unknown.

    Which instruments a pattern can be entered on, found by walking each
    voice's orderlist the way the player does -- carrying the instrument
    across pattern boundaries, because the column is sticky between patterns
    and not only within one. Iterated to a fixpoint because a pattern reached
    again after a loop or a repeat can be entered in a state the first lap
    never produced; without that this would be an under-estimate, and an
    under-estimate here is a bound that is too *high*.

    Shared by `min_played_notes` and `median_played_durations`, which need the
    same attribution over the same rows and differ only in what they measure.
    """
    entry: dict = {}
    # A track's orderlist loops, so the state it *starts* a lap in is whatever
    # the previous lap left -- not "no instrument". Seeding only with None
    # would miss states the second lap onward can produce, and a missed state
    # is a bound that comes out too HIGH, which is the unsafe direction here.
    track_starts = [{None} for _ in tracks]
    changed = True
    while changed:
        changed = False
        for t, track in enumerate(tracks):
          for begin in list(track_starts[t]):
            current, operand = begin, False
            for b in track:
                if operand:
                    operand = False
                    continue
                if b == GT_ORDER_RESTART:
                    operand = True
                    continue
                if GT_REPEAT <= b < GT_ORDER_RESTART:
                    continue             # transpose or repeat, no operand
                if b >= len(patterns):
                    continue
                seen = entry.setdefault(b, set())
                if current not in seen:
                    seen.add(current)
                    changed = True
                pattern = patterns[b]
                for row in range(len(pattern) // 4):
                    instr = pattern[4 * row + 1]
                    if instr:
                        current = instr
            if current not in track_starts[t]:
                track_starts[t].add(current)   # the next lap begins here
                changed = True
    return entry


def _pattern_plays(tracks: List[List[int]],
                   patterns: List[List[int]]) -> dict:
    """How many times each pattern is played per lap of the orderlists.

    The same walk `pattern_references` makes, with the one thing it leaves
    out: a `$D0`-`$DF` REPEAT applies to the entry that *follows* it
    (gplay.c's `cptr->repeat`), so the pattern after one is played that many
    times and a bare count of references understates it.
    """
    out: dict = {}
    for track in tracks:
        operand, repeat = False, 1
        for b in track:
            if operand:
                operand = False
            elif b == GT_ORDER_RESTART:
                operand = True
            elif GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
                pass
            elif GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
                repeat = b - GT_REPEAT + 1
            elif b < len(patterns):
                out[b] = out.get(b, 0) + repeat
                repeat = 1
    return out


def median_played_durations(tracks: List[List[int]],
                            patterns: List[List[int]]) -> dict:
    """The rows each instrument's *typical* note lasts, before the next fetch.

    The companion to `min_played_notes`, and the other half of the drum
    sweep's depth: the player's block sweeps for as long as the *note* lasts
    (goatwriter._drum_entries), so a bound taken from pitch alone describes
    only how far a sweep may fall before wrapping, never how far this
    instrument's own notes give it time to. Commando's instrument 13 is the
    case -- its pitch allows thirteen steps and the sweep was capped at eight,
    where a siddump of the original takes five, because the note is four rows
    long and that is all the frames the player gets.

    One converted row is one of the player's duration units
    (`goatwriter.tempo_command_value`), so the gap in rows from an event to
    the next one *is* the note's length in the units the drum block counts
    down. This measures rows; the caller turns rows into steps.

    A row counts as an event -- a fetch, which reloads the counter the drum
    reads -- when it carries a note or an instrument. Hold rows carry
    neither: `_build_raw_pattern` emits `wait` of them after every event and
    fills only the command columns, so nothing else can be confused for one.

    **The median, and not the minimum.** A wavetable holds one sweep for all
    of an instrument's notes, so whatever single number goes in is wrong for
    every note of a different length, and the reduction that minimises the
    total error of a single value against a distribution is its median -- not
    its smallest member. The distinction is not academic: Bump_Set_Spike's
    record 0 is played at 2, 4 and 6 rows in almost equal measure, its
    original sweeps 5 steps 221 times in 240 s, and the minimum would emit
    **0** and delete the sweep. Scored over the corpus as play-weighted L1
    error against each note's own true depth, the median is best-or-tied on
    all 122 measurable drum records where the minimum is on 97, and it takes
    the total from 331064 steps (the pitch bound alone) to 98669.

    Weighted by how often the orderlists actually play each pattern, because
    the median is a statement about what is *heard*: a duration that occurs
    in one pattern played sixteen times outweighs one in a pattern played
    once. Each row contributes once per play even where several orderlist
    paths reach the pattern in different instrument states -- the state
    changes who the row is attributed to, not how often it sounds.

    On an even split this returns the *lower* of the two middle values, which
    is the shallower sweep. Both are L1-optimal, so the tie is broken on the
    same ground as `_drum_steps_safe`'s: only the deep side can wrap.

    **An occurrence whose hold rows run to the end of its pattern is
    dropped.** What that measures is not the note's length but the distance to
    a pattern boundary, and the note continues into whichever pattern the
    orderlist plays next -- so the count is a lower bound on the real duration
    rather than the duration. Counting them would read Commando's instrument
    13 as two rows (a two-row pattern whose only row is such a note). An
    instrument with no untruncated occurrence at all is simply absent from the
    result, which callers must read as "unknown" rather than as "short".

    Returns `{goattracker instrument number: rows}`.
    """
    entry = _entry_instruments(tracks, patterns)
    weight = _pattern_plays(tracks, patterns)

    hist: dict = {}
    for index, pattern in enumerate(patterns):
        if index not in entry:
            continue                     # no orderlist reaches this pattern
        plays = weight.get(index) or 1
        rows = len(pattern) // 4
        # A non-final slice carries no ENDPATT row (_slice_pattern), so its
        # end is simply its row count.
        end = rows
        for row in range(rows):
            if pattern[4 * row] == GT_END_PATTERN:
                end = row
                break
        events = [row for row in range(end)
                  if pattern[4 * row] != GT_NO_NOTE or pattern[4 * row + 1]]
        # Who each event row belongs to, over every state the pattern can be
        # entered in. A row reachable on two instruments counts for both --
        # once each, not once per orderlist path.
        owners: dict = {}
        for opener in (entry.get(index) or {None}):
            current = opener
            for row in events:
                instr = pattern[4 * row + 1]
                if instr:
                    current = instr
                if current is not None:
                    owners.setdefault(row, set()).add(current)
        for k, row in enumerate(events):
            if k + 1 >= len(events):
                break                    # runs to the pattern end: unknown
            gap = events[k + 1] - row
            for instr in owners.get(row, ()):
                counts = hist.setdefault(instr, {})
                counts[gap] = counts.get(gap, 0) + plays

    out: dict = {}
    for instr, counts in hist.items():
        total = sum(counts.values())
        seen = 0
        for gap in sorted(counts):
            seen += counts[gap]
            if seen * 2 >= total:
                out[instr] = gap
                break
    return out


def min_played_notes(tracks: List[List[int]],
                     patterns: List[List[int]]) -> dict:
    """Lowest note index each instrument is ever actually played at.

    Two things stand between a pattern's note column and the pitch a voice
    sounds, and a bound that ignores either is not safe to build on:

    * **An orderlist transpose shifts every note in the patterns that follow
      it** -- gplay.c:977-981 sets `cptr->trans` from a `$E0`-`$FE` orderlist
      byte and gplay.c:927 adds it to the note. So a pattern's lowest note is
      not its lowest *pitch*: its lowest pitch is that note under the lowest
      transpose any orderlist position plays the pattern at.
    * **The instrument column is sticky.** 15162 of the corpus's 61611 note
      rows name no instrument and inherit whichever one a previous row -- in
      this pattern or a previous one -- last named. Rows before the first
      naming row in a pattern are therefore unattributable, and their note
      has to lower the bound for *every* instrument rather than for one.
      Attributing them to whatever the pattern happens to name first reads a
      quarter of the corpus's notes onto the wrong instrument.

    Returns `{goattracker instrument number: lowest note index}`, omitting an
    instrument no orderlist-reachable pattern plays -- callers must treat a
    missing key as "unknown", not as "high". Indices are relative to
    `GT_FIRSTNOTE` and can be negative under a transpose.
    """
    lowest_trans: dict = {}
    for track in tracks:
        trans = 0
        operand = False
        for b in track:
            if operand:
                operand = False          # a restart position, not a pattern
            elif b == GT_ORDER_RESTART:
                operand = True
            elif GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
                trans = b - GT_TRANSPOSE_UP
            elif GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
                pass                     # repeat count, no operand
            else:
                lowest_trans[b] = min(trans, lowest_trans.get(b, trans))

    entry = _entry_instruments(tracks, patterns)

    out: dict = {}
    unattributed = None
    for index, pattern in enumerate(patterns):
        if index not in lowest_trans:
            continue                     # no orderlist reaches this pattern
        shift = lowest_trans[index]
        # Every instrument this pattern can start on. `None` means some path
        # reaches it before any row has ever named one, which is genuinely
        # unattributable and still has to lower every bound.
        openers = entry.get(index) or {None}
        for opener in openers:
            current = opener
            for row in range(len(pattern) // 4):
                note, instr = pattern[4 * row], pattern[4 * row + 1]
                if instr:
                    current = instr
                if not GT_FIRSTNOTE <= note <= GT_LASTNOTE:
                    continue
                n = note - GT_FIRSTNOTE + shift
                if current is None:
                    unattributed = (n if unattributed is None
                                    else min(unattributed, n))
                else:
                    out[current] = min(n, out.get(current, n))
    if unattributed is not None:
        out = {k: min(v, unattributed) for k, v in out.items()}
    return out


def _apply_orderlist_tempos(new_track: List[int], moved: dict,
                            tempos: dict, patterns: List[List[int]],
                            copies: dict, log=None) -> int:
    """Write each mid-orderlist tempo change into the pattern it lands on.

    Goattracker's orderlist carries no tempo command, so the only place a
    tempo change can be said is a pattern row -- which means the pattern
    played at that step, entered at row 0. `apply_tempo` does the same thing
    for a subtune's opening tempo; this is the same trick at an arbitrary
    step.

    **Always into a copy, never in place.** The pattern a tempo change lands
    on is played elsewhere too, at whatever tempo is current there: Rasputin
    changes tempo three times in one voice's list and all three land on its
    pattern `$01`. Patching the shared pattern would apply the last one
    everywhere. Copies are shared between steps that ask for the same
    (pattern, value), so a tune with one tempo alternating between two values
    costs two patterns rather than one per step.

    Skipped rather than approximated where the row is not free -- a
    portamento or vibrato this converter emitted has to keep its column, and
    a tempo one row late is a change the player did not make. Returns how many
    were written.
    """
    written = 0
    for at in sorted(tempos):
        value = tempos[at]
        i = moved.get(at)
        if i is None or i >= len(new_track):
            continue
        entry = new_track[i]
        if entry >= MAX_PATTERNS or entry >= len(patterns):
            continue                    # a command byte, or a dangling number
        pattern = patterns[entry]
        if len(pattern) < 4:
            continue
        if pattern[2] == CMD_SETTEMPO and pattern[3] == value:
            written += 1                # already says it
            continue
        if pattern[2] != 0:
            if log:
                log(f"*** ORDERLIST TEMPO ${value:02X} AT STEP {at} FALLS ON "
                    f"PATTERN ${entry:X} ROW 0, WHOSE COMMAND COLUMN IS "
                    "TAKEN -- NOT WRITTEN ***")
            continue
        key = (entry, value)
        if key not in copies:
            if len(patterns) >= MAX_PATTERNS:
                if log:
                    log("*** NO ROOM FOR AN ORDERLIST-TEMPO PATTERN COPY (AT "
                        f"GOATTRACKER'S {MAX_PATTERNS} LIMIT) ***")
                break
            copy = list(pattern)
            copy[2], copy[3] = CMD_SETTEMPO, value
            copies[key] = len(patterns)
            patterns.append(copy)
        new_track[i] = copies[key]
        written += 1
    return written


def _apply_boundary_ties(new_track: List[int], moved: dict,
                         steps: Set[int], patterns: List[List[int]],
                         copies: dict, log=None) -> int:
    """Tie the first note of a pattern the player enters with the gate open.

    `_build_raw_pattern`'s `pending_tie` is a local, so it starts False at
    every pattern -- but the player's state does not. Its note-end gate-off
    lives on the hold path of the *previous* event, and a `$FF` terminator is
    an orderlist fetch, not an event: nothing between the two patterns closes
    the gate. So a pattern whose predecessor's last event carried status bit 5
    (or, where `gate_hold` reads it, a zero `wait`) is entered exactly as a
    tied note is entered inside a pattern -- a frequency change and no attack
    -- and this converter re-struck it.

    The tie lands on **row 0 and nowhere else**, because that is where the
    decoder would have consumed it: `pending_tie` is recomputed at the end of
    every event, so an opening event with no note of its own overwrites the
    carried state with its own, and the intra-pattern rule already handles
    everything after that. Row 0 must also carry a note and an empty command
    column, which is the same `cmd1 == 0` condition the intra-pattern tie
    tests.

    **Always into a copy, never in place**, for the reason apply_tempos
    documents: Goattracker's patterns are global and its orderlists are per
    subtune, and whether a pattern is entered tied is a property of the
    orderlist *position*. 96 of the 180 corpus entries that are ever entered
    tied are also entered untied somewhere -- more than half -- so patching
    the shared pattern would silence attacks the player really makes. Copies
    are shared between every step that asks for the same pattern.

    Returns how many steps were tied.
    """
    written = 0
    for at in sorted(steps):
        i = moved.get(at)
        if i is None:
            continue
        n = _tie_step(new_track, i, patterns, copies, log)
        if n < 0:
            break                       # the pattern table is full
        written += n
    return written


def _tie_step(new_track: List[int], i: int, patterns: List[List[int]],
              copies: dict, log=None) -> int:
    """Point orderlist step `i` at a copy of its pattern whose row 0 ties.

    The one place a boundary tie is written, so that both callers -- the
    pattern-to-pattern boundary and the orderlist's own wrap -- obey the same
    rule rather than agreeing by inspection. That is the lesson
    `_first_frame_entry` records: a rule about the player belongs in a helper
    every emitter has to call, not in prose beside one of them.

    **Always into a copy, never in place**, for the reason apply_tempos
    documents: Goattracker's patterns are global and its orderlists are per
    subtune, and whether a pattern is entered tied is a property of the
    orderlist *position*. 96 of the 180 corpus entries that are ever entered
    tied are also entered untied somewhere -- more than half -- so patching
    the shared pattern would silence attacks the player really makes. Copies
    are shared between every step that asks for the same pattern.

    Returns 1 where the step ends up tied (including one whose pattern
    already said so and cost no copy), 0 where it cannot carry one, and -1
    where Goattracker's pattern table is full -- a caller in a loop stops
    rather than asking again for every remaining step.
    """
    if i < 0 or i >= len(new_track):
        return 0
    entry = new_track[i]
    if entry >= MAX_PATTERNS or entry >= len(patterns):
        return 0                        # a command byte, or a dangling number
    pattern = patterns[entry]
    if len(pattern) < 4:
        return 0
    if not GT_FIRSTNOTE <= pattern[0] <= GT_LASTNOTE:
        return 0                        # nothing on row 0 to tie into
    if pattern[2] == CMD_TONEPORTA and pattern[3] == 0:
        return 1                        # already says it
    if pattern[2] != 0:
        # An orderlist tempo copy, or a slide the decoder emitted: the
        # decoder does not tie over a taken command column either.
        return 0
    if entry not in copies:
        if len(patterns) >= MAX_PATTERNS:
            if log:
                log("*** NO ROOM FOR A BOUNDARY-TIE PATTERN COPY (AT "
                    f"GOATTRACKER'S {MAX_PATTERNS} LIMIT) ***")
            return -1
        copy = list(pattern)
        copy[2], copy[3] = CMD_TONEPORTA, 0x00
        copies[entry] = len(patterns)
        patterns.append(copy)
    new_track[i] = copies[entry]
    return 1


def _apply_wrap_tie(new_track: List[int], patterns: List[List[int]],
                    copies: dict, exits_tied: bool, tempo_voice: bool,
                    log=None) -> int:
    """Carry the last orderlist entry's exit state around the restart.

    `_apply_boundary_ties` reaches every boundary *inside* a list and none of
    the one that closes it. The player's `$FF` is an orderlist fetch exactly
    like a pattern's own terminator -- version 4 is `LDA #$00 / STA` the three
    indices `/ JMP` the top, version 9 the same shape -- and nothing on that
    path writes `$D404`. So a list whose last entry exits tied re-enters the
    pattern at its restart position with the gate still open, and this
    converter re-struck it there too.

    **Only where the restart position is in range**, which is what tells a
    real loop from Hubbard's `$FE` stop. `convert_tracks` writes `$FF $FD` for
    *tune ended* -- an out-of-range position, deliberately, so the editor
    stops (h2g.frm:1206) -- and `legalise_restarts` only later rewrites it to
    0 so gt2reloc will pack the file at all. That 0 is a loop this tune never
    plays, so tying into it would suppress an attack the player does make on
    every pass but the fabricated one. Corpus: 5 of 711 voice orderlists end
    on a tied pattern and 2 of those 5 are `$FD`.

    The position is read as an index into `new_track`, which is what
    Goattracker's player will do with it (gsong.c:1344). The pre- and
    post-reindex numberings agree only at 0 -- one old entry can become
    several patterns -- and 0 is the only value `convert_tracks` and
    `legalise_restarts` ever produce, so nothing here depends on the wider
    claim. A transpose byte at the restart position is stepped over, for the
    same reason `reindex_tracks` lets `prev_ref` survive one: the reader
    consumes it and plays nothing, so the gate is still open when the pattern
    behind it arrives.

    Returns 1 if the restart position ended up tied, else 0.

    **The subtune's clock outranks it, and that is what makes this pass inert
    on today's corpus.** `apply_tempo`/`apply_tempos` write `CMD_SETTEMPO`
    into row 0 of voice 0's *entry reference* -- and they run after
    `reindex_tracks`, so they cannot see a command column this pass has
    already taken; `apply_tempos` simply skips such a pattern
    (`pattern[2] not in TEMPO_OVERWRITABLE`). A restart position of 0 makes the
    step this would tie exactly that entry reference, so on voice 0 the tie
    and the tempo want one column. Measured on Star_Paws, which is the only
    corpus file this pass reaches: taking the column dropped its tempo writes
    from **3 patterns to 1** (the converter's own log line), so subtunes 1 and
    2 played at the table's other value -- 4 frames a row where they want 11 --
    and subtune 1 read `melody 75% -> 37%`, `retrig 0.96 -> 0.30`, `drift
    -111 -> +1667`, with **all three voices** losing three quarters of their
    attacks though the tie was written on voice 0 alone. A whole subtune's
    clock against one note's attack is the same trade `reindex_tracks` already
    makes between the orderlist-tempo pass and `_apply_boundary_ties`, decided
    the same way. `tempo_voice` is that veto; `_apply_boundary_ties` never
    needs it because a boundary tie has a predecessor by construction and so
    can never land on position 0.

    **What this cannot express** even where the column is free: Goattracker
    starts a subtune at orderlist position 0 and every corpus restart position
    *is* 0, so the step this ties is also the step the song opens on. The
    original attacks that note on the first pass and ties it on every later
    one; one orderlist entry cannot say both.

    **THERE ARE THREE DECLINES HERE, NOT ONE, AND ONLY ONE OF THEM IS ON
    VOICE 0.** Censused by wrapping this function at its own call site and
    converting the corpus with its own presets -- 83 converted, 12 refused for
    having no Hubbard player -- 5 voice orderlists exit tied and 3 of those
    have an in-range restart:

        Flash_Gordon  s6 v0   restart 253 >= songlen 11   -- $FD, a stop
        Warhawk       s4 v2   restart 253 >= songlen  1   -- $FD, a stop
        Chimera       s0 v1   restart 0 -> pos 0          -- row 0 is $BE
        Star_Paws     s1 v0   restart 0 -> pos 1 == ref   -- the tempo veto
        Star_Paws     s2 v0   restart 0 -> pos 1 == ref   -- the tempo veto

    Chimera is the one this pass had been described as unable to reach and can
    reach perfectly well: it is on **voice 1**, so `tempo_voice` is False and
    the veto never runs. It declines in `_tie_step` because its restart
    pattern's row 0 is `GT_KEYOFF` ($BE), which sits just above `GT_LASTNOTE`
    ($BC) and so fails the note-range test. That is the RIGHT answer and not a
    limitation: a KEYOFF row is the player's own data saying *release here*,
    so there is no attack to suppress and nothing to tie into. So "every
    corpus instance is on voice 0" is false, and "this pass reaches nothing"
    is true for two unrelated reasons rather than one.

    **The veto lift is refuted again, at this head, on the subtunes that carry
    the ties.** The numbers above were taken before v0.5.330's `apply_tempos`,
    which clones a contested entry pattern instead of skipping blindly, so the
    trade could have changed; it has not. Forcing `tempo_voice=False` moves
    Star_Paws' bytes (c6b37cdc6cc8 -> fcc868e88ab5) and takes the converter's
    own tempo line from `in 3 pattern(s)` to `in 1`:

        subtune 1   melody .7481 -> .3663   seq .8636 -> .4571   pitch .9643 -> .3929
        subtune 2   melody .9869 -> .9647   seq .9854 -> .9649   pitch 1.0000 -> .9667
        subtune 0   unchanged on all three

    Subtune 0 being flat is the whole reason the original A/B read as harmless:
    it is the only subtune with no tie at the wrap, and it is the one a default
    trace looks at.

    **It IS expressible, and the price is the reason it is not taken.** To say
    both halves -- attacked on the first pass, tied on every later one -- the
    loop body has to appear twice, `[T P1..Pn T P1_tied..Pn $FF restart=n+2]`,
    so that the opening entry stays untied and keeps its `CMD_SETTEMPO` while
    the restart lands on a tied second copy; the veto then dissolves on its
    own. Star_Paws' two lists are 29 and 48 entries and would go to about 58
    and 96 against `MAX_TRACK_LEN` 255, plus a pattern copy each. The prize is
    one spurious attack per wrap on one file's two subtunes -- voice 0 of
    subtune 2 over-attacks by 3 in 60 s, and subtune 1 by 12 beside a voice-1
    deficit of -58 that this cannot touch. Near-doubling two orderlists inside
    the function whose last regression cost three quarters of a subtune's
    attacks is not worth that, so the pass declines on voice 0 by design. The
    day a file exercises it with more than one note at stake, the route is
    written down here and the decision is an A/B rather than a re-derivation.
    """
    if not exits_tied:
        return 0
    songlen = next((i for i, b in enumerate(new_track)
                    if b == GT_ORDER_RESTART), None)
    if songlen is None or songlen + 1 >= len(new_track):
        return 0                        # no marker, or no operand to read
    pos = new_track[songlen + 1]
    if pos >= songlen:
        return 0                        # a stop marker, not a loop
    while pos < songlen and new_track[pos] >= MAX_PATTERNS:
        pos += 1                        # a transpose the reader consumes
    if pos >= songlen:
        return 0
    if tempo_voice and pos == _entry_reference(new_track):
        return 0                        # the opening tempo owns that column
    return max(0, _tie_step(new_track, pos, patterns, copies, log))


# --------------------------------------------------------------------------
# Pulse phase: CMD_SETPULSEPTR on the note rows of a free-running sweep.
#
# The mechanics of the sweep live in goatwriter (PulsePhaseSim, the table
# builder); what lives HERE is everything that touches orderlists and
# patterns -- the play-order walk, the repeat-fold expansion, and the
# clone-per-vector discipline apply_tempos established: patterns are global
# and a phase belongs to an orderlist POSITION, so a pattern entered at two
# phases needs two copies, never an in-place edit.
# --------------------------------------------------------------------------

def _expand_repeats(track: List[int]) -> tuple:
    """The track with every $D0-$DF fold written out, plus the index map.

    Playback-neutral by construction -- a fold IS its expansion -- but the
    restart operand indexes into the track, so it is remapped through the
    same table every other index goes through. Returns (new_track, old->new
    index map) or (None, None) where the expansion would not fit.
    """
    out: List[int] = []
    remap: dict = {}
    i, n = 0, len(track)
    while i < n:
        b = track[i]
        remap[i] = len(out)
        if b == GT_ORDER_RESTART:
            out.append(b)
            if i + 1 < n:
                remap[i + 1] = len(out)
                out.append(track[i + 1])
            i += 2
            continue
        if GT_REPEAT <= b < GT_REPEAT + 16 and i + 1 < n \
                and track[i + 1] < MAX_PATTERNS:
            plays = b - GT_REPEAT + 1
            remap[i + 1] = len(out)
            out += [track[i + 1]] * plays
            i += 2
            continue
        out.append(b)
        i += 1
    if len(out) >= MAX_TRACK_LEN:
        return None, None
    # the restart operand is an index and must survive the shift
    songlen = next((k for k, v in enumerate(out) if v == GT_ORDER_RESTART), None)
    if songlen is not None and songlen + 1 < len(out):
        old_songlen = next(k for k, v in enumerate(track)
                           if v == GT_ORDER_RESTART)
        pos = track[old_songlen + 1]
        if pos < len(track):
            out[songlen + 1] = remap.get(pos, pos)
    return out, remap


def _phase_note_rows(pattern: List[int], live_instr: int, sims: dict):
    """Yield (row_index, kind, instr) walking one pattern's rows.

    kind: "note" for a played note, "row" for anything else. `live_instr`
    carries the last non-zero instrument byte in, exactly as the player
    does -- instrument 00 means KEEP.
    """
    rows = len(pattern) // 4
    for r in range(rows):
        note = pattern[4 * r]
        if note == GT_END_PATTERN:
            return
        instr = pattern[4 * r + 1] or live_instr
        if pattern[4 * r + 1]:
            live_instr = pattern[4 * r + 1]
        kind = "note" if GT_FIRSTNOTE <= note <= GT_LASTNOTE else "row"
        yield r, kind, instr


def collect_pulse_phases(patterns: List[List[int]], tracks: List[List[int]],
                         tempos: List[int], sims: dict, log=None):
    """Walk every subtune in play order and plan the phase of every note.

    Returns (phases, writes) or None where the plan cannot be trusted:
      phases -- {instrument byte: set of (width, direction)}
      writes -- [(track index, slot index, {row: (instr, (width, dir))})]

    Declines -- whole voices or whole groups, logged -- rather than guessing:
    a record sounded by two voices of one group shares one accumulator and
    the walk simulates voices independently; a loop whose second pass opens
    its notes on different phases than its first cannot be expressed by a
    per-position command at all. Tracks are MUTATED only by `_expand_repeats`
    (playback-neutral); the caller holds a snapshot to restore on decline.
    """
    groups = len(tracks) // 3
    if len(tempos) != groups:
        raise ValueError(f"{groups} group(s), {len(tempos)} tempo(s)")
    phases: dict = {}
    writes: list = []
    for g in range(groups):
        # a record on two voices shares one accumulator: decline the group
        owner: dict = {}
        clash = False
        for v in range(3):
            live = 0
            for b in tracks[3 * g + v]:
                if b >= MAX_PATTERNS:
                    continue
                if b >= len(patterns):
                    continue
                for _, kind, instr in _phase_note_rows(patterns[b], live, sims):
                    if kind == "note" and instr in sims:
                        if owner.setdefault(instr, v) != v:
                            clash = True
                    if instr:
                        live = instr
        if clash:
            if log:
                log("Pulse phase.............: a record sounds on two voices "
                    f"of subtune {g}; the accumulator is shared and the plan "
                    "declines the subtune")
            continue

        tempo = max(1, tempos[g])
        for v in range(3):
            ti = 3 * g + v
            expanded, _ = _expand_repeats(tracks[ti])
            if expanded is None:
                if log:
                    log(f"Pulse phase.............: subtune {g} voice {v} "
                        "cannot expand its repeats inside the orderlist "
                        "limit; declined")
                continue
            tracks[ti] = expanded
            track = expanded
            songlen = next((k for k, b in enumerate(track)
                            if b == GT_ORDER_RESTART), len(track))
            restart = track[songlen + 1] if songlen + 1 < len(track) else 0
            voice_sims = {num: sim.clone() for num, sim in sims.items()
                          if owner.get(num) == v}
            if not voice_sims:
                continue
            # THE STARTUP PREROLL, measured rather than derived: the record
            # that is current when the tune starts has already swept for a
            # few calls by the time its first note fetches -- init plus the
            # player's warm-up. Seven calls reproduces every one of
            # 5_Title_Tunes voice 3's 188 measured onsets exactly (0..8 were
            # swept; 7 alone scores 188/188, its neighbours 94). A record
            # that is NOT the voice's opening instrument is frozen until its
            # first note and needs none -- voices 1 and 2's first onsets
            # measure exactly the record width, which is the zero-preroll
            # prediction. A wrong value here costs a fixed orbit offset,
            # never the band or the travel.
            first_instr = 0
            live_scan = 0
            for b in track:
                if b == GT_ORDER_RESTART:
                    break
                if b >= MAX_PATTERNS or b >= len(patterns):
                    continue
                for _, kind, instr in _phase_note_rows(
                        patterns[b], live_scan, voice_sims):
                    if instr:
                        live_scan = instr
                    if kind == "note":
                        first_instr = instr
                        break
                if first_instr:
                    break
            if first_instr in voice_sims:
                voice_sims[first_instr].advance(PULSE_PHASE_PREROLL)

            def one_pass(start: int, live: int):
                out: dict = {}
                pos = start
                while pos < songlen:
                    b = track[pos]
                    if b >= MAX_PATTERNS or b >= len(patterns):
                        pos += 1
                        continue
                    for r, kind, instr in _phase_note_rows(
                            patterns[b], live, voice_sims):
                        if instr:
                            live = instr
                        sim = voice_sims.get(instr)
                        if sim is None:
                            continue
                        if kind == "note":
                            out.setdefault(pos, {})[r] = (instr, sim.phase())
                            sim.advance(tempo, skip_first=True)
                        else:
                            sim.advance(tempo)
                    pos += 1
                return out, live

            first, live = one_pass(0, 0)
            second, _ = one_pass(restart, live)
            # The loop's second pass re-enters wherever the free-running
            # accumulator happens to be, and a per-position command cannot
            # follow that -- so the FIRST pass's phases are anchored and
            # every later loop repeats them. That is not a shim: the
            # original's own re-entry phase is an accident of arithmetic,
            # not a composed value (5_Title_Tunes' whole 120s trace is a
            # single pass, so no re-entry was ever even observed), and the
            # cost is one width jump at the loop seam against a whole pass
            # of restored phasing. Logged so a reader knows which kind of
            # file this is.
            stable = all(second.get(pos, first[pos]) == first[pos]
                         for pos in first if pos >= restart)
            if not stable and log:
                log(f"Pulse phase.............: subtune {g} voice {v} "
                    "re-enters its loop mid-sweep; the first pass's phases "
                    "are anchored and every repeat plays them")
            for pos, rows in first.items():
                writes.append((ti, pos, rows))
                for (num, ph) in rows.values():
                    phases.setdefault(num, set()).add(ph)
    if not writes:
        return None
    return phases, writes


def apply_pulse_phase(patterns: List[List[int]], tracks: List[List[int]],
                      writes: list, index: dict, log=None) -> int:
    """Write the planned CMD_SETPULSEPTR commands, always into copies.

    One clone per distinct (pattern, command vector), shared across every
    slot that wants the same vector -- `_tie_step`'s rule. A row whose
    command column is already taken keeps its command (the tempo pass ran
    first and a subtune's clock outranks one note's phase); the skip is
    counted and logged rather than silent.
    """
    clones: dict = {}
    written = skipped = 0
    for (ti, pos, rows) in writes:
        track = tracks[ti]
        target = track[pos]
        if target >= len(patterns):
            continue
        vector = tuple(sorted(
            (r, index[(num, ph[0], ph[1])])
            for r, (num, ph) in rows.items()
            if (num, ph[0], ph[1]) in index))
        if not vector:
            continue
        src = patterns[target]
        # already carrying exactly this vector (a shared clone reused)
        if all(src[4 * r + 2] == CMD_SETPULSEPTR and src[4 * r + 3] == e
               for r, e in vector):
            continue
        key = (target, vector)
        if key not in clones:
            if len(patterns) >= MAX_PATTERNS:
                if log:
                    log("Pulse phase.............: pattern table full, a "
                        "phase clone was dropped")
                skipped += len(vector)
                continue
            copy = list(src)
            for r, e in vector:
                if copy[4 * r + 2] == 0:
                    copy[4 * r + 2], copy[4 * r + 3] = CMD_SETPULSEPTR, e
                    written += 1
                else:
                    skipped += 1
            clones[key] = len(patterns)
            patterns.append(copy)
        track[pos] = clones[key]
    if log and (written or skipped):
        log(f"Pulse phase.............: CMD_SETPULSEPTR on {written} note "
            f"row(s) in {len(clones)} pattern copy(ies)"
            + (f", {skipped} skipped over occupied columns" if skipped else ""))
    return written


def reindex_tracks(tracks: List[List[int]], track_index: List[List[int]],
                   pack: bool = False,
                   floor: int = GT_COMMAND_FLOOR,
                   log=None,
                   dropped: Optional[List[int]] = None,
                   split: Optional[List[int]] = None,
                   patterns: Optional[List[List[int]]] = None,
                   max_rows: int = GT_DEFAULT_ROWS,
                   tempos: Optional[List[dict]] = None) -> List[List[int]]:
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
    tempo_copies: dict = {}     # (pattern, value) -> the copy carrying it
    tie_copies: dict = {}       # pattern -> the copy whose row 0 is tied
    # Present only on a TrackIndex, which is what convert_patterns returns; a
    # hand-built list simply gets no boundary ties.
    exits_tied = getattr(track_index, "exits_tied", None)
    for ti, track in enumerate(tracks):
        new_track: List[int] = []
        # Positions of this track whose *predecessor* pattern leaves the gate
        # open. See _apply_boundary_ties.
        tied_steps: Set[int] = set()
        prev_ref: Optional[int] = None
        # Where each of this track's own positions ended up, for the tempo
        # pass below. One old entry can become several (a sliced pattern), and
        # the tempo belongs on the first of them.
        moved: Dict[int, int] = {}
        expect_operand = False
        for at, b in enumerate(track):
            moved[at] = len(new_track)
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
                # A transpose byte between two pattern references is consumed
                # by the orderlist reader and plays nothing, so `prev_ref`
                # deliberately survives one: the gate the previous pattern left
                # open is still open when the next one's first note arrives.
                if (exits_tied is not None and prev_ref is not None
                        and prev_ref < len(exits_tied) and exits_tied[prev_ref]):
                    tied_steps.add(at)
                prev_ref = b
                new_track.extend(track_index[b] if b < len(track_index) else [])
        # Before packing, and that is the whole reason it is here rather than
        # in a pass of its own: the tempo rides in a *copy* of the pattern it
        # lands on, so substituting the copy's number is what keeps
        # `pack_repeats` from folding that step back into the run around it.
        # A pass after packing would have to undo a repeat to say anything.
        if tempos and ti < len(tempos) and tempos[ti] and patterns is not None:
            _apply_orderlist_tempos(new_track, moved, tempos[ti], patterns,
                                    tempo_copies, log)
        # Same placement, and for the same two reasons: the tie rides in a
        # *copy*, so it has to be substituted before pack_repeats can fold the
        # step back into the run around it -- and after the tempo pass, whose
        # copy owns the same command column (a step that is both is left to
        # the tempo, which is a whole subtune's clock against one note's
        # attack). Only one corpus player has orderlist tempos at all and no
        # entry of it is ever entered tied, so the two never meet today.
        if tied_steps and patterns is not None:
            _apply_boundary_ties(new_track, moved, tied_steps, patterns,
                                 tie_copies, log)
        # And the boundary the list closes on, which is the one every step of
        # the pass above cannot reach: `prev_ref` is this track's last pattern
        # reference, and the wrap plays the restart position with whatever gate
        # it left open. See _apply_wrap_tie for why only an in-range restart
        # position counts, and why voice 0 of a subtune yields to the tempo
        # `apply_tempos` writes into that same row after this runs.
        if (patterns is not None and exits_tied is not None
                and prev_ref is not None and prev_ref < len(exits_tied)):
            _apply_wrap_tie(new_track, patterns, tie_copies,
                            bool(exits_tied[prev_ref]), ti % 3 == 0, log)
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
