"""Wave program entries and travel (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from typing import (List, Optional)

from ..detect import (decode_wave_program, Detection)
from ..sidfile import (SidFile)
from .constants import (FORMAT_GTS5, WAVE_GATE_BIT, WAVE_NOTE_BASE,
                        WAVE_NOTE_KEEP, WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from .primitives import (_first_frame_lead, _sfx_note_byte, _speed_index,
                         _wave_byte, _wave_hold_byte)
from .vibrato import (_classic_vibrato_entry, _table_vibrato_entry,
                      _triangle_vibrato_entry)
def _hold_wave_program_entry(left: List[int], right: List[int],
                             wave: int, multiplier: int) -> None:
    """Extend the entry just appended to cover a whole frame at `-S{m}`.

    One opcode of the byte-code program is one of the player's frames, and a
    frame is `multiplier` play calls. `_wave_hold_byte` is the shared encoding
    of that -- a repeat of the waveform at `-S2`, where no delay value exists
    for a single extra call, and a delay of `m - 2` above it.

    **Right side `$80`, and `$00` was the defect this fixed.** `gt2reloc`
    inverts bit 7 of every non-command wavetable right byte on the way in --
    `insertbyte(rtable[c][d] ^ 0x80)`, greloc.c:1339-1341 -- so the packed
    player's `lda mt_notetbl-2,y / bne mt_wavefreq` (player.s:974-977) is
    testing the *inverted* byte. A `.sng` `$80` becomes packed `$00` and makes
    no frequency write at all; a `.sng` `$00` becomes packed `$80`, takes the
    `bmi` path at `mt_wavefreq` and writes `adc mt_chnnote,x / and #$7f` --
    the note's own pitch, every hold call.

    That is what made the `program` bucket of `VIBRATO.md` read zero. At `-S2`
    an opcode is entry + hold, so the opcode's absolute pitch was written on
    the frame's first call and overwritten by the base note on its second;
    siddump samples the register once a frame and saw a flat pitch. Ricochet's
    `$09F9` measured 184 reversals in the original and 0 here, with the
    waveforms `11 81 41 41 80 80 80` landing exactly right beside them.

    See `_wave_program_entries` for the same byte on the opcode entries.
    """
    hold = _wave_hold_byte(multiplier, _wave_byte(wave))
    if hold is not None:
        left.append(hold)
        right.append(WAVE_NOTE_KEEP)


def _wave_program_travels(multiplier: int, fmt: str, running: int) -> bool:
    """Whether a slide's accumulated travel can be carried at this call rate.

    A `< $80` opcode is one of the player's *frames*, and a frame is
    `multiplier` play calls. Above `-S1` the opcode's waveform entry does not
    need all of them, so the spare call can hold a `CMD_PORTADOWN` and the
    travel reaches the chip inside the same frame the player spends on it. At
    `-S1` there is no spare call and a second entry would make the program run
    at half the player's rate -- the trade v0.5.203 measured and refused, and
    the reason this is gated rather than unconditional.

    **THE `-S1` REFUSAL IS ABOUT THIS PAIRING, NOT ABOUT RELATIVE PITCH AS
    SUCH** (established at v0.5.453, chasing Monty's drums). This entry is
    designed to sit BESIDE a waveform entry -- two entries per opcode -- so at
    `-S1` it doubles the program's length, which is the measured refusal
    above. A CHAIN is a different shape and a different cost: one waveform
    entry followed by N portamentos is N+1 entries for N steps, because a
    command entry advances the pointer and skips the note write without
    touching the latched waveform (the paragraph below, and `gplay.c:557-573`
    / `player.s:1531-1547`). This file already emits exactly that shape --
    `_drum_entries`' `[WAVECMD_PORTADOWN] * steps` -- so it is established
    rather than speculative.
    For a five-step sweep the chain costs SIX frames against five, a 20% rate
    error, where the pairing costs ten and a 100% one. So "relative pitch is
    impossible at `-S1`" is too strong a reading of this gate, and five
    successive attempts on `monty-drums-play-four-octaves-too-low` treated it
    as closed on that basis. What the chain cannot do is carry a waveform
    CHANGE mid-sweep; Monty's sweep re-asserts the identical `$80` on all five
    steps, so it loses nothing there.
    """
    return fmt == FORMAT_GTS5 and multiplier >= 2 and bool(running & 0xFFFF)


def _wave_program_hold_travels(fmt: str, running: int) -> bool:
    """Whether the travel that puts the `$85` hold on the accumulator's
    pitch can be emitted -- at EVERY call rate, `-S1` included.

    `_wave_program_travels` refuses `-S1` for a portamento sitting BESIDE an
    opcode's waveform entry, because there it makes the opcode two calls
    where the player spends one, and every opcode after it runs a frame late
    (v0.5.203). The closing travel is not beside an opcode. It follows the
    restore entry, and only the stop follows it, so nothing after it can run
    late: the restore's waveform still lands on the hold's own frame, and the
    one frame the travel costs is the pitch of that frame alone -- the note's,
    where the original sounds the accumulator. Every frame after it, for the
    rest of the note, is the accumulator's pitch, which is what the
    interpreter's `$85` writes. Mega_Apocalypse's own: `$4D8C CMP #$85 /
    $4D90 JMP $4E63`, and `$4E63` is the per-frame writer, `LDA $C0,X / STA
    $D401,Y / LDA $C3,X / STA $D400,Y` -- the accumulator the slides
    (`$4DAB-$4DB6`, `SBC ($F8),Y` into `$C3,X` / `$C0,X`) count down.

    Refusing it at `-S1` held the NOTE for the whole tail instead.
    Mega_Apocalypse's `$09F9` record 3 (`set $81 / slide $10 $0200 / slide
    $40 $03C0 / set $80 x8 / hold`) reads `$0EEF` = `$14AF - $05C0` (-1472)
    for the rest of every note longer than its 12 frames; ours read `$14AF`.

    **This is the encoding's question only.** Whether the travel belongs on
    a record at all at `-S1` is `_wave_program_entries`' `hold_travel` and
    `_wave_program_record_vibrates`.
    """
    return fmt == FORMAT_GTS5 and bool(running & 0xFFFF)


def _wave_program_record_vibrates(sid: SidFile, det: Detection,
                                  i: int) -> bool:
    """Whether the player's own instrument vibrato runs on record `i`.

    **A vibrating record's tail is centred on the NOTE, not on the
    accumulator.** Every vibrato engine this converter reads computes the
    pitch from the note (`_classic_vibrato_entry`: `freq(note) + counter x
    interval`), so once it runs it rewrites the frequency the `$85` hold
    would have left. Nemesis_the_Warlock measured it: `$0B09` (record 11,
    `slide $41 $20 / $150 / $180`, sum `$2F0`) reads `-32 -368 -384` and
    then `-37 0 37 0` around the note for the rest of every note, and
    `$0C5A` (record 12, sum `$15D0`) `-147 -294 -147 0 147` around it. A
    closing travel there put ours `-752` and `-5584` below it for the whole
    tail. So the `-S1` travel is declined for such a record.

    The test is the player's: each engine's entry function returns None on
    exactly the byte the player's own `BNE`/`BEQ` reads as "no vibrato"
    (Warhawk `$11EA`, Hollywood or Bust `$05D1`). Read whatever the
    `vibrato` option says, because the original vibrates either way.
    """
    if det.vibrato_offset is not None:
        offset, entry_of = (det.vibrato_offset,
                            lambda b: _classic_vibrato_entry(b, 1))
    elif det.table_vibrato is not None:
        offset, entry_of = (det.table_vibrato.offset,
                            lambda b: _table_vibrato_entry(
                                b, det.table_vibrato, 1))
    elif det.triangle_vibrato is not None:
        offset, entry_of = (det.triangle_vibrato,
                            lambda b: _triangle_vibrato_entry(b, 1))
    else:
        return False
    at = det.instr_start + i * det.instr_stride + offset
    return 0 <= at < len(sid.data) and entry_of(sid.data[at]) is not None


def _wave_program_travel_entry(left: List[int], right: List[int],
                               running: int, speed_table: List[tuple],
                               fmt: str, multiplier: int,
                               closing: bool = False) -> bool:
    """Append the portamento carrying `running`, the slides' summed operands.

    The player subtracts each `< $80` opcode's 16-bit operand from a frequency
    **accumulator** that note-start loaded with the note's own frequency, so
    after k slides the voice sounds `note - sum(operands)`. The waveform entry
    beside this one writes the note (`WAVE_NOTE_BASE`); this entry takes it the
    rest of the way.

    **The sum, not the step.** Written per opcode as the running total rather
    than as that opcode's own delta so the entry is correct without depending
    on what the previous entries left in `cptr->freq` -- a `>= $80` opcode
    between two slides writes `$D401` directly and never touches the
    accumulator, so a delta chain would drift by exactly that opcode's absolute
    pitch. Each entry re-derives the whole offset from the note.

    One entry is one subtraction: `gplay.c:557-573` and `player.s:1531-1547`
    both execute the command, advance the pointer and skip the note write on
    the same call -- the packed player routes it through `mt_execwavetickn`,
    which sets `mt_effectjump+1` and falls into `mt_effect_12` *without*
    writing `mt_chnfx,x`, so it is a one-shot and not a standing effect. Same
    shape as the drum sweep's `[WAVECMD_PORTADOWN] * steps` chain.

    A sum at or above `$8000` is a net *rise* (the player's subtraction is
    modular 16-bit) and takes `CMD_PORTAUP` with the two's complement, which
    also keeps the speed's high byte below `$80` -- at or above it the players
    read the entry as note-relative and take the low byte as a shift
    (`gplay.c:548-552`, `player.s:1027`), which is a different quantity
    entirely.
    """
    # `closing`: the entry after the `$85` restore, gated on its own rule --
    # see `_wave_program_hold_travels`.
    if not (_wave_program_hold_travels(fmt, running) if closing
            else _wave_program_travels(multiplier, fmt, running)):
        return False
    s = running & 0xFFFF
    if s < 0x8000:
        cmd, speed = WAVECMD_PORTADOWN, s
    else:
        cmd, speed = WAVECMD_PORTAUP, 0x10000 - s
    if not 0 < speed < 0x8000:
        return False
    index = _speed_index(speed_table, ((speed >> 8) & 0xFF, speed & 0xFF))
    if not index:
        return False
    left.append(cmd)
    right.append(index)
    return True


def _gated_slide_chain(sid: SidFile, det: Detection, i: int, prog: list,
                       lead_l: List[int], lead_r: List[int],
                       speed_table: List[tuple], multiplier: int,
                       budget: int) -> Optional[tuple]:
    """At `-S1`, the slides of a program the player's vibrato takes over
    from, as a chain of portamentos -- or None where the shape is not this.

    **What the original moves on frame 1.** Nemesis_the_Warlock records
    3/11 (`$0B09`/`$0C0A`, program `slide $41 $0020 / $0150 / $0180 / hold`)
    and 12 (`$0C5A`, five `$11` slides `$0C20 $02C0 $01F0 $0200 $0300`)
    read, from the attack: `0 -32 -368 vib-384 vib vib ...` and `0 -3104
    -3808 vib-496 vib-512 vib-768 vib ...`, where the counter gate says
    the vibrato (`$E261 LDA $E6D7,X / CMP #$03 / BCC`) cannot store before
    age 3. The frame-1 move is the PROGRAM, not the vibrato: `$E32E-$E341`
    subtracts each slide's operand from the frequency cell `$E55D/$E517`
    that `$E3F0` writes to `$D400/$D401`, one opcode a frame from age 1.
    Below the gate nothing else writes that cell, so the slides accumulate;
    from the gate on, `$E280/$E285` re-store the vibrato's ABSOLUTE pitch
    (computed from the note) into it every frame BEFORE the program's
    subtraction runs, so each later slide is a one-frame dip below the
    vibrato and the sum is discarded. IK_plus record 13 (`$00C9`, gate 4,
    slides `-$0380 -$0280 +$0180 +$0380`) reads the same: `+896 +1536
    +1152 vib-896 vib`.

    At `-S1` `_wave_program_entries` drops the slides (an opcode's one call
    is spent on its waveform entry, v0.5.203), so those records held the
    note flat to the hold. Where every opcode is a slide on the waveform
    the lead already latched, no waveform entry is needed: a wavetable
    command changes the frequency and leaves `wave` alone (`gplay.c`
    `CMD_PORTADOWN`: `cptr->freq -= speed`, then `goto PULSEEXEC`), one
    call each -- the chain shape `_wave_program_travels` describes, at the
    player's rate exactly. Each command carries the change between the
    original's offsets, `sum(s_1..s_a)` below the gate and `s_a` from it.
    The restore after the last slide writes the note (`/00`, which also
    zeroes `vibtime`), because the original's vibrato is centred on the
    note and Goattracker's runs from wherever the frequency stands.

    Only where: `-S1`; a counter gate is read for the record and the
    record vibrates (`_wave_program_record_vibrates`); every opcode before
    the hold is a slide on the record's own `+2` waveform with at least one
    non-zero operand; and the hold's age is at or past the gate, so the
    note never sounds the bare accumulator after the program (a later gate
    would need a re-anchor this chain does not emit). A full speed table
    refuses the whole chain, leaving the old entries.
    """
    if multiplier != 1:
        return None
    vg = det.vibrato_gate
    if vg is None or vg.form != "counter":
        return None
    gate = vg.gate_for(i)
    if gate is None or not _wave_program_record_vibrates(sid, det, i):
        return None
    gate = max(1, gate)
    wave = sid.data[det.instr_start + i * det.instr_stride + 2]
    if not prog or prog[-1][0] != "hold":
        return None
    slides = prog[:-1]
    if (not slides or any(k != "slide" or w != wave for k, w, _ in slides)
            or not any(a for _, _, a in slides)):
        return None
    if len(slides) + 1 < gate:
        return None
    if len(lead_l) + len(slides) + 2 > budget:
        return None
    left, right = list(lead_l), list(lead_r)
    acc = was = 0
    for age, (_, _, arg) in enumerate(slides, 1):
        acc = (acc + arg) & 0xFFFF
        now = acc if age < gate else arg & 0xFFFF
        delta = (now - was) & 0xFFFF
        was = now
        if not delta:
            left.append(_wave_byte(wave))
            right.append(WAVE_NOTE_KEEP)
            continue
        cmd, speed = ((WAVECMD_PORTADOWN, delta) if delta < 0x8000
                      else (WAVECMD_PORTAUP, 0x10000 - delta))
        index = _speed_index(speed_table, (speed >> 8, speed & 0xFF))
        if not index:
            return None
        left.append(cmd)
        right.append(index)
    # The same restore byte the general path writes (`persist`, gate
    # cleared), on the note rather than the accumulator.
    left.append(_wave_byte(wave & ~WAVE_GATE_BIT & 0xFF))
    right.append(WAVE_NOTE_BASE)
    left.append(0xFF)
    right.append(0x00)
    return left, right


def _wave_program_entries(sid: SidFile, det: Detection, i: int,
                          speed_table: List[tuple], fmt: str,
                          multiplier: int, budget: int,
                          written: bool = False,
                          hold_travel: bool = False) -> Optional[tuple]:
    """Wavetable entries for the byte-code wave program, or None.

    The interpreter `detect.find_wave_program` reads, in 29 corpus files -- the
    most widespread instrument mechanism this converter has left unemitted, and
    the one carrying Trans-Atlantic's snare (`81 30`, noise at `$30xx`, 43 onsets
    a listener reported missing).

    Each opcode becomes entries:

    * `>= $80` -- waveform plus an absolute frequency high byte -- is one entry:
      the waveform, with the nearest absolute note on the right. The player
      writes `$D401` directly and a wavetable names notes, so the pitch is
      quantised to a semitone; for the noise these opcodes mostly carry, that is
      inaudible (see `_sfx_note_byte`).
    * `< $80` with a zero operand is also one entry: a waveform change and no
      pitch movement, which is most of what GT 11-13 do.
    * `< $80` with a nonzero operand is two **above `-S1`**: the waveform on
      the note's own pitch, then a portamento carrying the running sum of the
      operands (`_wave_program_travel_entry`). The pair still costs one frame,
      because a frame is `multiplier` calls and the waveform entry does not
      need them all. At `-S1` there is no spare call and the travel is dropped,
      which is what v0.5.203 measured and chose.
    * `$85` holds, which is the program's end. The interpreter does **not**
      loop back: on `$85` it jumps straight to the per-frame writer without
      advancing the program index, and the index is zeroed only by note start
      (ACE II `$E36C-$E370` against `$E0F7 STA $EBC7,X` on the note-fetch
      path). So the block stops there, restoring the stored waveform on the
      accumulator's pitch, as the player does.

    **One opcode is one frame, and one frame is `multiplier` play calls.** The
    player advances one opcode per frame; a wavetable advances one entry per
    *call*, so each opcode gets a hold entry after it (`_wave_hold_byte`, the
    same rule as `_first_frame_lead`) and the program runs at the player's
    rate at every `-S`. Until v0.5.234 the function simply refused a multiplier
    above 1, which is what kept the largest group of the onset census
    unrendered: 7 of the 9 files whose `$01` records the original opens on
    noise and we held flat -- Kings of the Beach, Ricochet, Saboteur II,
    Shockway Rider, Star Paws, Thundercats -- carry a wave program and pack at
    `-S2`, `-S3` or `-S5`, so the option was selectable, measured, and inert.

    The cost is a table roughly twice as long. Nothing starves for it: the
    caller's budget already reserves five entries for every later record and
    this loop already stops on it, so an over-long program loses its trailing
    opcodes rather than another instrument's block.

    **The hold entry's right side is `$80`, not `$00`.** It was `$00` from
    v0.5.234, on a reading of `player.s:974-977` that had not accounted for
    `greloc.c:1339-1341` inverting bit 7 of the right column as it packs. The
    two bytes mean the opposite of what that reading said: `$80` makes no
    frequency write, `$00` re-asserts the pattern's own note, and the hold was
    therefore undoing the absolute pitch of every `>= $80` opcode one call
    after it was set. See `_hold_wave_program_entry`.

    **`hold_travel`: the `$85` hold's travel at `-S1` too**
    (`_wave_program_hold_travels`), for a record the player does not
    vibrate (`_wave_program_record_vibrates`). The caller passes it only
    where no instrument of the song writes a real or gate-off firstwave
    (`build_sng`), because the tail's pitch is still in the register when
    the voice's NEXT note opens: Goattracker's note-init call writes the
    waveform alone (`player.s` `jmp mt_loadregswaveonly`), so a real
    firstwave gates the next note on at the previous tail's pitch for one
    frame. Under the test-bit firstwave that frame is silent. Measured on
    the three corpus files with a real firstwave the travel reached
    (Auf_Wiedersehen_Monty, Pygmies_Revenge, held Arcade_Classics): melody
    0.9876 -> 0.6868, 0.9741 -> 0.7828, 0.9205 -> 0.5102, and identical on
    both trees when every attack is named one frame in -- the whole loss is
    that frame. Above `-S1` the travel is emitted as it always was.
    """
    if fmt != FORMAT_GTS5:
        return None
    if det.wave_program < 0 or not det.wave_program_gate:
        return None
    data = sid.data
    rec = det.instr_start + i * det.instr_stride
    off = det.wave_program + i * det.instr_stride
    if max(rec + 7, off + 1) >= len(data):
        return None
    if not data[rec + 7] & det.wave_program_gate:
        return None
    at = sid.to_offset(data[off] | (data[off + 1] << 8))
    if at < 0:
        return None

    # **The note's first frame is the record's own waveform**, and the program
    # runs from the second (`_first_frame_entry`): Trans-Atlantic's GT 3 opens
    # `tri` -- its `+2`, `$11` -- and only then the program's `$81` noise. Opened
    # on the program, every frame it emits ran one early and that first frame was
    # lost. Counted in the budget below like any other entry, so a record too
    # long for the table loses a trailing opcode rather than this.
    # `_first_frame_lead` rather than a lead written out here: the rule has two
    # halves and this function only ever had the first. Its one-entry seed was
    # one *call* where frame 0 is `multiplier` of them -- the same defect
    # v0.5.220 fixed in `_drum_entries` and v0.5.226 in the plain tick block,
    # latent here only because the multiplier gate above made it unreachable.
    lead_l, lead_r = _first_frame_lead(data[rec + 2], multiplier,
                                       written=written)
    chain = _gated_slide_chain(sid, det, i, decode_wave_program(data, at),
                               lead_l, lead_r, speed_table, multiplier,
                               budget)
    if chain is not None:
        return chain
    left: List[int] = list(lead_l)
    right: List[int] = list(lead_r)
    seed = len(left)
    # **The two opcode kinds write different cells, and the hold reverts to the
    # one the `< $80` opcodes own.** IK+ `$E348`: a `>= $80` opcode stores to
    # `$E5E7,X` -- the cell the per-frame writer copies to `$D404` -- while a
    # `< $80` opcode stores to `$E58F,X`, the voice's *stored* waveform. On
    # `$85` the interpreter jumps to `$E44C`, which is
    # `LDA $E58F,X / AND gate,X / STA $E5E7,X`: the voice goes back to the last
    # `< $80` opcode's waveform, not to the record's `+2`. Its `$08D8` is the
    # proof -- program `81 11 40 80 80 80 80 80`, and the original reads
    # `11 81 11 40 80 80 80 80 80 40 40 40`, three frames of the `$40` that
    # opcode 2 stored, where we wrote the record's `$11` released.
    # Seeded with `+2` because that is what the note-start code puts in the
    # cell, so a program of nothing but `>= $80` opcodes restores what it
    # always did.
    persist = data[rec + 2]
    # What one opcode costs: its own entry, plus the hold that makes it last a
    # whole frame above -S1. The guard below has to count both, or a program
    # that fills the table overruns the budget by one entry and takes it from
    # the five every later record is reserved -- the one property that makes
    # the variable-length layout safe (`_wavetable_layout`).
    per_opcode = 1 + (_wave_hold_byte(multiplier) is not None)
    # The slides' running total, in the units the player's accumulator counts
    # in. Zero for a program of nothing but `>= $80` opcodes, which is what
    # makes those records byte-identical to before the travel was emitted.
    running = 0
    # Whether the frequency Goattracker is holding right now IS that
    # accumulator. False after a `>= $80` opcode, which writes an absolute
    # pitch over it, and false at `-S1`, where no portamento is emitted at all
    # and the entries stay exactly the bytes they were before the travel
    # existed. See the slide branch: it decides between re-anchoring on the
    # note and stepping on from where the last one left off.
    carried = False
    # What the block after the loop needs: the restore entry, the stop, and
    # the portamento that puts the restore on the accumulator's pitch. Above
    # `-S1` that third entry is reserved whatever this opcode does, because the
    # closing travel is decided by the sum of *every* slide and a `set` can be
    # the last opcode a full budget admits. At `-S1` it is reserved from the
    # first opcode that leaves the sum non-zero (`_wave_program_hold_travels`),
    # so a program with no travel to close keeps every opcode it had.
    closing = hold_travel and not _wave_program_record_vibrates(sid, det, i)

    def tail(r: int) -> int:
        return 2 + (1 if (_wave_program_travels(multiplier, fmt, 1)
                          or (closing and _wave_program_hold_travels(fmt, r)))
                    else 0)
    for kind, wave, arg in decode_wave_program(data, at):
        if kind == "hold":
            break
        if kind == "set":
            if len(left) + per_opcode + tail(running) > budget:
                break
            left.append(_wave_byte(wave))
            right.append(_sfx_note_byte(arg))
            _hold_wave_program_entry(left, right, wave, multiplier)
            carried = False     # an absolute pitch, not the accumulator
            continue
        # **One entry, even when the operand is non-zero** (v0.5.203). A
        # portamento needs a command entry of its own, and a wavetable spends a
        # call on it, so a two-entry slide makes the program one frame longer
        # than the player's -- which runs the whole thing late and truncates
        # what follows. On Trans-Atlantic's snare the two slides cost 2 of 11
        # frames and cut the closing noise burst from 8 frames to 6. The
        # frame count is what the ear hears in a percussion transient; two
        # frames of pitch movement under a released waveform is not, so the
        # waveform keeps its frame and the movement is dropped.
        #
        # **But the frame it lands on is the note's own pitch, not the last
        # `set` opcode's.** The two opcode kinds do not write the same cells,
        # and this one does not go through `$D401` at all. Saboteur II $F36B,
        # Shockway Rider $F05A -- the same routine byte for byte:
        #
        #     F36B  9D 5D F5   STA $F55D,X   ; waveform -> the STORED cell
        #     F36F  38 BD 8F F5 F1 F8 9D 8F F5    ; freq LO acc -= operand
        #     F379  BD 7B F5 F1 F8 9D 7B F5       ; freq HI acc -= borrow
        #     F386  4C 5F F4   JMP $F45F
        #     ...
        #     F45F  AC 50 F5   LDY $F550
        #     F462  BD 5D F5 3D 66 F5 99 04 D4    ; stored waveform & gate
        #     F46B  BD 7B F5 99 01 D4             ; the ACCUMULATOR -> $D401
        #     F471  BD 8F F5 99 00 D4             ; ...and $D400
        #
        # The accumulator is loaded with the note's frequency at note start and
        # a `>= $80` opcode never touches it -- that one writes `$D401`
        # directly and exits by another path ($F477). So the first `< $80`
        # opcode of a program **abandons the absolute pitch and returns to the
        # note**, minus the running sum of the operands, and every later one
        # continues from there. Exact on both files and on four different base
        # notes: Saboteur's $1739 - $0180 = $15B9 and $49B8 - $0180 = $4838,
        # Shockway's $1168 - $01C0 = $0FA8 and $14AF - $01C0 = $12EF.
        #
        # `WAVE_NOTE_KEEP` here held whatever the last `set` put in `$D401`,
        # which is an absolute pitch with nothing to do with the note -- on
        # Saboteur's $0888 it froze the program at $20DC where the original
        # descends from $15B9, and on a *high* note it was an octave and a half
        # below where the player goes. `WAVE_NOTE_BASE` says "back to the
        # note", which is exact whenever the running sum is zero and the right
        # side of the truth otherwise. The sum itself is still dropped: it is a
        # linear frequency subtraction and a wavetable's right column names
        # notes, so its size in semitones depends on the note it is played at
        # (Saboteur's first slide is -1.16 st under $1739 and -0.36 st under
        # $49B8) and no single byte can carry both.
        #
        # **The travel itself is carried where there is a call to carry it in**
        # -- `_wave_program_travel_entry`, a `CMD_PORTADOWN` on the spare call
        # of the frame at `-S2` and above. The paragraph above is what remains
        # true at `-S1`, where the opcode's one call is already spent on its
        # waveform. So `WAVE_NOTE_BASE` is no longer the whole answer, it is
        # the entry the portamento starts from, and the sum is dropped only
        # where the call rate leaves nowhere to put it.
        #
        # **The step, not the sum, wherever the last entry left the frequency
        # on the accumulator.** Both are exact in the player's terms and they
        # differ in *when inside the frame* the pitch is right. Re-anchoring
        # (`WAVE_NOTE_BASE` + a portamento of the whole running sum) writes the
        # bare note on the frame's first call and corrects it on the second, so
        # a trace sampling once a frame can read the note -- ACE II's `$EB0A`
        # sat at `0EA3` for the whole slide that way while the calls underneath
        # it stepped correctly. `WAVE_NOTE_KEEP` plus this opcode's own operand
        # never writes the note at all, so the frequency only ever moves the
        # way the player moves it. The anchor is still needed for the first
        # slide of a program and for the one after any `>= $80` opcode, because
        # those leave an absolute pitch in the register that has nothing to do
        # with the accumulator.
        delta = arg & 0xFFFF if carried else (running + arg) & 0xFFFF
        travel = int(_wave_program_travels(multiplier, fmt, delta))
        cost = 1 + travel + (_wave_hold_byte(multiplier - travel) is not None)
        if len(left) + cost + tail(running + arg) > budget:
            break
        left.append(_wave_byte(wave))
        right.append(WAVE_NOTE_KEEP if carried else WAVE_NOTE_BASE)
        # `moved` rather than `travel`: a full speed table refuses the index,
        # and the hold has to cover the call the portamento did not take.
        moved = int(_wave_program_travel_entry(left, right, delta, speed_table,
                                               fmt, multiplier))
        _hold_wave_program_entry(left, right, wave, multiplier - moved)
        running = (running + arg) & 0xFFFF
        # The frequency now matches the accumulator only if this entry actually
        # said so: a step it could not encode (a full speed table) leaves it a
        # step behind, and the next slide re-anchors instead of compounding the
        # error. `delta == 0` needs no portamento to be right either way.
        carried = bool(travel and moved) or (not delta and bool(
            _wave_program_travels(multiplier, fmt, 1)))
        persist = wave              # a `< $80` opcode owns the stored cell
    # `seed` alone is not a program: a record whose interpreter holds on its
    # first opcode has nothing to say here and falls through to the shapes
    # below, exactly as it did before the seed entry existed.
    if len(left) <= seed:
        return None
    # **Restore the record's own waveform before stopping** (v0.5.203). The
    # docstring above used to say Goattracker keeps the last waveform "as the
    # player does"; the player does not. Its note-end routine writes the
    # *stored* waveform with the gate cleared -- `LDA $54F8,X / AND #$FE /
    # STA $D404,Y`, the same routine as the envelope cut (detect
    # .ENVELOPE_CUT_SHAPES) -- so a program that ends on noise stops sounding
    # noise when the note ends. Holding it instead let the noise run into the
    # gap: Trans-Atlantic's snare had runs of 30, 54 and 78 frames where the
    # original's are 8.
    #
    # **What is restored is the stored cell, not the record's `+2`** -- see
    # `persist` above. Where the program's last `< $80` opcode selects no
    # waveform (Skate or Die intro and Arcade Classics both end on `slide
    # $00`) that restore is silence, which is what the original sounds for the
    # rest of the note; `_wave_byte` is what makes it reach the packed player.
    #
    # **And the hold writes a pitch too** -- `WAVE_NOTE_KEEP` here was the same
    # defect v0.5.341 fixed one loop above, left in the one emitter that is not
    # in the loop. `$85` does not stop the interpreter, it *jumps* to the
    # per-frame writer ($F45F on Saboteur II / Shockway Rider -- the listing
    # above), and that path ends `LDA $F57B,X / STA $D401,Y` and
    # `LDA $F58F,X / STA $D400,Y`: the frequency **accumulator**, which is the
    # note's own frequency minus the running sum of the `slide` operands. It
    # is **not** whatever the last `set` opcode put in
    # `$D401` -- that one writes the register directly and exits by another
    # path, so its absolute pitch has nothing to do with where the hold sits.
    # Traced on Nineteen's `$0797` (record 6, program `set $81 $30 / slide $11
    # $0400 / slide $40 $0E40 / set $80 $30 $15 $20 $10 $20 / hold`): over a
    # 19-frame note the original reads
    # `17A1 0961 3061 1561 2061 1061 2061 0961 0961 ...` -- base note `$1BA1`,
    # then the two slides, then the five absolute pitches, then **back to
    # `$0961` = `$1BA1 - $0400 - $0E40`** for the whole tail. Ours held `20DC`,
    # the last `set`'s pitch, an octave and a half above it.
    # `WAVE_NOTE_BASE` is exact whenever the running sum is zero (a program of
    # nothing but `set` opcodes, which is most of them) and the right side of
    # the truth otherwise -- the identical argument the slide entries carry.
    # The sum is carried here by the same portamento the slide entries take
    # (`_wave_program_travel_entry`), and dropped at `-S1` for the same reason
    # it is dropped there. It is the *whole* running sum, because the hold
    # writes where the accumulator ended up and not where the last slide moved
    # it -- the entry re-derives the offset from the note, so a `>= $80` opcode
    # after the last slide changes nothing about it. Nothing follows the stop,
    # so the pitch this leaves stands for the rest of the note, which is what
    # the interpreter's `$85` does.
    left.append(_wave_byte(persist & ~WAVE_GATE_BIT & 0xFF))
    right.append(WAVE_NOTE_KEEP if carried else WAVE_NOTE_BASE)
    # **At `-S1` too, where `closing` says so** (`hold_travel`,
    # `_wave_program_hold_travels`): there the restore writes the note on
    # the hold's frame and this entry moves it onto the accumulator on the
    # next, which then stands for the rest of the note.
    if not carried:
        _wave_program_travel_entry(left, right, running, speed_table,
                                   fmt, multiplier, closing=closing)
    left.append(0xFF)
    right.append(0x00)
    return left, right
