"""Arp block and sfx drum entries (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from typing import (List, Optional)

from .constants import (ARP_HEAD_FRAMES, SFX_DRUM_FRAMES, WAVE_JUMP,
                        WAVE_MAX_DELAY, WAVE_NOISE_GATEOFF, WAVE_NOTE_BASE,
                        WAVE_NOTE_KEEP)
from .primitives import (_sfx_note_byte, _wave_byte)
def _arp_offsets(operand: int) -> Optional[List[int]]:
    """The player's semitone cycle for a `$83 nn`, or None where there is none.

    `patterns.ILV_ARP` carries the derivation. Step 0 leaves the note alone,
    step 1 adds the operand's high nibble, step 2 its low nibble -- and the
    player's own `AND #$0F / BNE` at $1431 wraps at step 1 when the low nibble
    is zero, so a `$x0` operand is a two-step trill rather than a three-step one
    with a repeat. An operand of $00 is no arpeggio at all and is declined
    rather than emitted as identical entries, exactly as `_pitch_seq_entries`
    declines an all-zero sequence.
    """
    hi, lo = operand >> 4, operand & 0x0F
    if not hi and not lo:
        return None
    return [0, hi] if not lo else [0, hi, lo]


def _arp_block(source: List[tuple], offsets: List[int],
               multiplier: int, start: int) -> Optional[tuple]:
    """One `CMD_SETWAVEPTR` target: `source`'s waveform program, arpeggiated.

    `source` is the instrument's own laid-out block, and copying it is what
    makes this faithful rather than an approximation: the arpeggio is a pitch
    cycle the player adds to the NOTE and it changes nothing about the
    waveform. So the left column is copied verbatim -- delay entries included
    -- and only the right column is written, with the offset belonging to the
    frame that entry is current on. Holding one waveform instead would have
    silently dropped Go_Go_Dash's `02` and Lion_Heart's `01` attack delays,
    which is two of the five arpeggiated files.

    **The frame arithmetic is the packed player's, not the editor's.**
    `gt2reloc`'s player does not execute the wavetable on a note's first call
    (player.s:908-911), so wavetable call `c` is play call `c + 1` and hence
    frame `(c + 1) // multiplier`. A delay entry (left `$00`-`$0F`) is current
    for `left + 1` calls and applies its right side on the LAST of them
    (gplay.c:697-704), so it is charged to that call's frame.

    After the source program the cycle has to keep running for as long as the
    note is held, which the source's own terminator would not do. The tail is
    one entry per play call for a whole cycle -- `len(offsets) * multiplier`
    entries -- and the jump goes back to the tail's first entry rather than the
    block's: a whole cycle is a whole number of frames, so the phase across the
    jump is exact, and re-running the attack program on every wrap would not be.

    Returns None where there is nothing usable to copy.
    """
    body = []
    for left, _ in source:
        if left == WAVE_JUMP:
            break
        body.append(left)
    if not body:
        return None

    def note(frame: int) -> int:
        return (WAVE_NOTE_BASE + offsets[frame % len(offsets)]) & 0xFF

    hold = max(1, multiplier)
    left: List[int] = []
    right: List[int] = []
    call = 0
    for w in body:
        last = call + (w if w < 0x10 else 0)   # a delay covers `w + 1` calls
        left.append(w)
        # `ARP_HEAD_FRAMES` of step 0 before the cycle advances -- the
        # head the originals have, measured. Clamping at 0 repeats
        # step 0 rather than wrapping backwards into the cycle.
        right.append(note(max(0, (last + 1) // hold - ARP_HEAD_FRAMES)))
        call = last + 1

    # The sustained waveform: the last real waveform the program reaches. A
    # program of nothing but delays has none -- guarded rather than assumed,
    # because `$00`-`$0F` on the left is a delay and would read as a waveform.
    held = next((w for w in reversed(body) if w >= 0x10), None)
    if held is None:
        return None
    tail = start + len(left)
    for _ in range(len(offsets) * hold):
        left.append(held)
        right.append(note((call + 1) // hold))
        call += 1
    left.append(WAVE_JUMP)
    right.append(tail & 0xFF)
    return left, right


def _sfx_drum_entries(wave: int, pitch_hi: int, period: int,
                      multiplier: int = 1,
                      second_note: Optional[int] = None) -> tuple:
    """Entries for the bit-$80 drum: a noise hit every `period` frames.

    `detect._find_sfx_drum` reads what this plays -- noise at a fixed frequency
    high byte, on a per-voice counter, while an instrument carrying bit $80 is
    held. It is the drum of seven corpus files and was left unwritten while it
    was believed to be the game's own sound effect (§7).

    **`pitch_hi` IS ONE ABSOLUTE PITCH, AND ON ONE VOICE OF ONE FILE THE
    PLAYER'S IS NOT. THAT IS BANGKOK'S 18-ATTACK RESIDUAL, ATTRIBUTED
    (v0.5.468).** Measured on both sides at `-t 180` through the harness's own
    subtune and multiplier, counting frames whose waveform byte is `$81` and
    censusing the frequency held on each:

        voice 1   original  2 frequencies: $486E x558, $30AF x207
                  ours      2 frequencies: $49C5 x558, $313C x207
        voice 2   original  15 frequencies: $482C x311, $4837 x254,
                            $48E8 x137, $4857 x134, $4827 x122, $48C1 x97,
                            $4816 x96, $484E x68, ... over 1423 frames
                  ours       1 frequency:  $49C5 x1324

    **Voice 1 is the control and it passes**: two frequencies on each side in
    the IDENTICAL 558/207 proportions, so the shape is right and only the
    absolute values differ. Voice 2 is where all 18 missing attacks live, and
    there the original's tick FOLLOWS THE MUSIC across fifteen frequencies
    while ours is pinned to a single $49C5 -- the same $49C5 it writes on
    voice 1.

    **So the deficit is not 18 notes we fail to write; it is 18 repetitions
    siddump does not NAME.** It names a note from the frequency on the frame
    the gate rises, so a tick that moves gets named again and a tick that does
    not is one note held. We emit 1324 of the original's 1423 tick frames --
    93% of the sound -- and 18 fewer attacks. `retrig 0.9719` on this file is
    a statement about the naming, which is this repo's rule that a low score
    is a claim about the harness until it is a claim about the converter.

    **NOT FIXED, and the reason is a cross-file one.** Pinning a different
    constant would be wrong by construction; what the player does is track the
    note. That is the SAME SHAPE as the open Monty task, whose entry already
    records "the original's voice 1 FOLLOWS THE MUSIC ... an attempt to fix it
    by pinning a constant attack pitch would be wrong by construction". Two
    files, two voices, one mechanism -- worth taking together rather than
    separately, and worth a listening check before either, since 93% of the
    tick frames are already there.

    The shape is a loop, because the player's is: two frames of noise at the
    drum's pitch, the instrument's own waveform and note back again, a delay
    covering the rest of the period, and a jump to the top. That is five
    entries, which is exactly `WAVE_ENTRIES_PER_INSTR`.

The burst is **two** frames in the trace where the counter test (`CMP #$01`)
    implies one, which is still measured rather than derived.

    **The second frame's pitch is effect bit $40, found in v0.5.204.** This
    docstring used to record `$15EB` as "a fixed frequency from somewhere this
    reader has not found", and both frames were written at the drum's own high
    byte for want of anything better. It is the player's note table indexed by
    the instrument's own byte -- `freqtable[52]` on Trans-Atlantic's record 1 --
    and `_fixed_attack_note` derives it. Passed as `second_note`, the two frames
    now carry the two pitches the trace shows:

        +1  noise at the drum's high byte   ($38xx; low byte left as it was)
        +2  noise at freqtable[index]       ($15EB, exactly)

    That profile is identical on all 226 notes of that instrument, so it is the
    shape and not a sample.

    **THE HIT'S PITCH IS ABSOLUTE ON PURPOSE, AND "FOLLOW THE PATTERN NOTE" IS
    REFUTED THREE WAYS** -- measured at 64c795b over all 7 corpus files that
    ship `--sfx-drum` (Bangkok Knights, Mega Apocalypse, Nineteen, Pandora,
    Star Paws, Thundercats, Trans-Atlantic Balloon). The standing suggestion
    was that this tick is "pinned to one pitch where the player tracks the
    note", from both Bangkok and Monty showing one pitch where the original
    shows several.

    * **The player cannot track it.** `detect.SFX_DRUM_SHAPE` is
      `A9 ?? 8D ?? D4 A9 81 8D ?? D4` and `_find_sfx_drum` *verifies* that its
      two stores name the frequency-HIGH and control registers of one and the
      same voice. There is no store to the frequency LOW byte in the block, so
      the drum sounds at `$xx00` plus whatever low byte the played note left
      behind -- a residue, not a transposition.
    * **And the residue is measured rather than argued.** Traced 180 s of each
      original at `-m1` (the multiplier belongs to our side only) on its own
      `sfx_voice`, over every frame whose waveform is the drum's `$81`: the
      high byte is the drum's on **1423 of 1423** frames on Bangkok, 1276/1276
      on Mega Apocalypse, 1370/1370 on Nineteen and 1116/1116 on Star Paws,
      across 10-31 distinct frequencies spanning **181-242 units** -- under 256
      by construction and **under 23 cents** at `$48xx`. The three files that
      are not 100% have a second mechanism on that voice, and Trans-Atlantic's
      second high byte is `$15` on 683 frames, which is exactly the `$15EB` of
      `second_note` above.
    * **Following the note would move the drum by octaves.** Read back out of
      the shipped `.sng` with `songview.parse_sng`, restricted to the
      instruments whose wavetable actually carries this hit, the median gap
      between the hit's note and the notes those instruments play is **+34 to
      +56 semitones, 2.8 to 4.7 octaves** (Bangkok +34, Mega Apocalypse +42,
      Thundercats +46, Pandora +53, Nineteen +56). The ticked records are the
      bass and percussion ones, so they play the file's lowest notes.

    A/B'd anyway, because the shape of an argument is not a measurement:
    `$00` instead of `note` on the hit frames -- the 14 of 16 emitted records
    that take the branch below -- over all 7 files at `-t 60` and `-t 180`.
    Every file's bytes move; **three move a column, all three move down, and
    identically at both windows** (Nineteen melody 98.8 -> 82.8% and sequence
    99.2 -> 75.3%, Bangkok sequence 98.6 -> 83.2%, Pandora melody
    99.4 -> 96.5%), and **zero files improve on anything**. The other four are
    invisible because **no report column reads a noise frame's pitch**: the
    change only surfaces where the tick's sub-`$10` neighbour makes siddump
    name it as an attack, and there it renames one.

    Pinned by `tests/test_ticks.py`'s two `drum_hit` tests -- one on the note
    byte both branches emit, one on `_find_sfx_drum` refusing a block whose
    store names the frequency LOW register.
    """
    if pitch_hi <= 0 or period <= 0:
        return None
    m = max(1, multiplier)
    # **A record whose +2 selects no waveform is the drum on its own**, and it
    # goes through `_wave_byte` for the reason every other such byte does:
    # `$01`-`$0F` are *delays* in a wavetable, and the `$E0`-`$EF` encoding is
    # what writes them to $D404 as the control bits they are (readme.txt
    # 3.4.1, gplay.c:527). Written literally the entry set no waveform at all
    # -- Bangkok Knights' GT 9 inherited noise from whatever played before and
    # its delay entry applied a relative note, 40 frames at `freqtbl[0]` =
    # $0117 where the drum belongs at $49E5 -- and this function declined the
    # record rather than encode it, which silenced the drum instead.
    #
    # Nineteen is what that cost. Records 0 and 4 share ADSR $0B06 and effect
    # $A0; 0 carries `+2 $41` and is the pulse bass with the drum over it,
    # 4 carries `+2 $01` and is the **drum alone** -- 151 of the original's
    # 267 attacks on voice 3 in 60 s, every one of them named C#6 at the drum's
    # own $482D. Declining record 4 emitted `01/00 01/00 01/00 FF/00`: three
    # one-call delays and a stop, no waveform and no drum. `$E1` writes the
    # $01 the player holds between hits, and because $01 is below $10
    # siddump's keyoff-keyon test fires on the `$81` that follows it, so the
    # ticks are named as notes on our side exactly as they are on the
    # original's.
    held = _wave_byte((wave & 0xFE) | 0x01)
    note = _sfx_note_byte(pitch_hi)
    noise = WAVE_NOISE_GATEOFF | 0x01

    def hold(left: list, right: list, calls: int) -> None:
        """Append entries covering `calls` calls of the instrument's own note.

        One explicit entry is one call; a delay entry is current for `value + 1`
        (gplay.c:697-704), and `$00` is not a delay -- `$01`-`$0F` are -- so a
        remainder of exactly one call is spelled out rather than encoded.
        """
        if calls <= 0:
            return
        left.append(held)
        right.append(0x00)                   # relative 0: the played note
        rest = calls - 1
        if rest == 1:
            left.append(held)
            right.append(0x00)
        elif rest > 1:
            left.append(min(rest - 1, WAVE_MAX_DELAY))
            right.append(WAVE_NOTE_KEEP)

    if second_note is None:
        # **The hit is on the note's second frame, and every `period` after.**
        # Bangkok Knights $8488, and the same block byte for byte in Mega
        # Apocalypse, Star Paws and Thundercats:
        #
        #     848D  LDA $8936 / CMP #$01 / BEQ fire     ; counter == 1 -> hit
        #     8499  CMP #$06 / BCC out                  ; == period -> wrap
        #     84A4  fire: LDA #$48 / STA $D40F / LDA #$81 / STA $D412
        #
        # and the counter is **zeroed at note start** -- `LDA #$00 / STA
        # $8934,X` at $80CE, in the block that clears this voice's other
        # per-note cells -- then `INC $8934,X` once a frame at $84D2. So it is
        # note-locked, the phase is reproducible, and a wavetable can hold it.
        #
        # **This docstring used to say the opposite**, that the counter was
        # "per voice and free-running", and put the noise at the *end* of the
        # cycle for that reason. The measurement it cited is real and was
        # misread: opening on the noise at **frame 0** puts the drum's pitch on
        # the note's own attack frame, where siddump names the note, and
        # Trans-Atlantic's melody duly fell 94.7% -> 50.4%. That is an argument
        # against frame 0, not against frame 1 -- the same collapse
        # `--no-test-restart` produces on Star Paws by the same route. Measured
        # on the original, all four files sound noise at offset 1 on 100% of
        # onsets, and Bangkok's 226 of 232 read `noi` at 1 and 7 -- one frame
        # each, not the two the second-note dialect shows.
        left: List[int] = []
        right: List[int] = []
        hold(left, right, m)                 # frame 0: the record's own note
        loop = len(left)
        left.append(noise)
        right.append(note)
        rest = m - 1                         # ...the hit lasts one frame
        if rest == 1:
            left.append(noise)
            right.append(note)
        elif rest > 1:
            left.append(min(rest - 1, WAVE_MAX_DELAY))
            right.append(WAVE_NOTE_KEEP)
        hold(left, right, (period - 1) * m)
        return left, right, loop

    # With the $40 pitch: a prologue that runs once, then a loop that does not.
    # The burst at offsets +1..+2 carries two pitches, the drum's and $40's; the
    # ticks after it carry one, because $40's counter has run out. Offsets are
    # the trace's, on every note of Trans-Atlantic's instrument 0A99.
    left = [held, noise, noise]
    right = [0x00, note, second_note]
    hold(left, right, (period - SFX_DRUM_FRAMES) * m)
    loop = len(left)
    left.append(noise)
    right.append(note)
    hold(left, right, (period - 1) * m)
    return left, right, loop
