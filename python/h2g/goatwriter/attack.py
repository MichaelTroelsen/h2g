"""Fixed attack pitch, first-frame entries, two-stage and alternate-wave entries (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from typing import (List, Optional)

from ..detect import (Detection, EFFECT_BIT40_MASK)
from ..sidfile import (SidFile)
from .constants import (EFFECT_FIXED_PITCH_MASK, EFFECT_NOTE_ALT_MASK,
                        GT_WAVE_LAST_DELAY, WAVE_ENTRIES_PER_INSTR,
                        WAVE_MAX_DELAY, WAVE_NOTE_BASE)
from .primitives import (_counter_gate_call, _first_frame_entry,
                         _first_frame_lead, _fixed_pitch_yield_field,
                         _freq_table_note, _gate_calls, _wave_byte)
def _fixed_attack_note(sid: SidFile, det: Detection, i: int) -> Optional[int]:
    """Absolute-note byte for effect bit $40's fixed attack pitch, or None.

    The derivation, which took two wrong turns worth recording. The routine is

        LDA counter,X / BEQ + / DEC counter,X / LDA $116B,Y / JMP fetch
        + LDA gate,Y / BNE out / LDA note,X
        fetch  ASL / TAY / LDA table,Y / STA freqlo,X
                           LDA table+1,Y / STA freqhi,X

    and three things had to be pinned before it could be emitted:

    * **What the two cells are.** They feed `$D400`/`$D401` directly
      (`LDA freqhi,X / STA $D401,Y`), so they are the voice frequency.
    * **What the table is.** `sidfile.find_freq_table` locates it
      independently and returns the same address the routine indexes -- so the
      pitch is a *note*, not an arbitrary value.
    * **What indexes it.** `$116B,Y` read with `Y` as the instrument *number*
      gives 129 on Trans-Atlantic's record 1, which maps to `$1A03` and is not
      the pitch the trace shows. `Y` is the record **offset**: index × stride.
      At that offset the byte is `$34` = 52, and `freqtable[52]` is `$15EB` --
      exactly the frequency the original sounds on 226 of 226 frames.

    **The table it indexes is the handler's own operand,
    `det.fixed_pitch_index`** (`detect._find_fixed_pitch_index`: the `LDA
    idx,Y` in the routine above, read out of the player). Through v0.5.486
    this read `det.wave_program` instead -- the array the `$08` interpreter reads
    as a *pointer low byte* -- on the strength of the two agreeing in the
    files this was derived on. They agree in 25 of 27 corpus files where
    both exist, and the derivation had two holes:

    * **Sixteen files have `$40` records and no wave program at all**
      (Food Feud, Sanxion, Tarzan, Delta, Knucklebusters, ...), so their
      fixed pitch was never emitted. Food Feud's voice 3: the original
      sounds `$295E` (D#5, record 0's `$3F` = 63) on the noise frame of
      every hit, 1396 ties; the conversion wrote the waveform with no
      frequency, 36.
    * **After 8's two arrays differ by four bytes**: the handler reads
      record `+12` (note 60, C-5, 914 sightings in a 180 s trace) and
      `wave_program` is `+8` (notes 0-2, never sounded).

    So the handler operand is preferred and `wave_program` is the fallback,
    consulted only where the handler was not read. Read as a pointer the
    `$08` records hold 176, 201 and 178 -- `$3E00`, `$FF34`, `$3C00` --
    nonsense as pitches, which is why either path is gated on
    `det.effect_bit40`.

    Returns None where the byte cannot be a note -- the player's table has a
    definite length and an index past it is reading something else, which is a
    reading this function will not guess at.
    """
    if not det.effect_bit40:
        return None
    index = det.fixed_pitch_index
    if index < 0:
        index = det.wave_program
    if index < 0:
        return None
    # **Per record, not per file.** `det.effect_bit40` says the player reads the
    # bit; only this record's own effect byte says whether it is set. Checking
    # the file alone applied the pitch to Thundercats' drum, whose record does
    # not carry $40 -- 99 frames at a pitch the original never sounds there, and
    # melody 77% -> 72%.
    rec7 = det.instr_start + i * det.instr_stride + 7
    if rec7 >= len(sid.data) or not sid.data[rec7] & EFFECT_BIT40_MASK:
        return None
    off = index + i * det.instr_stride
    if off >= len(sid.data):
        return None
    return _freq_table_note(sid, sid.data[off])


def _note_alternate_note(sid: SidFile, det: Detection,
                         i: int) -> Optional[int]:
    """Absolute-note byte for effect bit $08's alternate note, or None.

    `detect._find_note_alternate` reads the block (Flash Gordon `$139A`, 21
    corpus files, 80 records): the voice's pitch alternates every frame
    between the note the pattern played and a fixed note *number* held in a
    parallel per-instrument array, on the same per-voice counter bit $02's
    waveform alternation uses. The array is indexed by `i * instr_stride`
    like every other effect table in this family, and the byte in it is an
    index into the player's own frequency table -- so what a wavetable can say
    is the nearest absolute note.

    **Per record, not per file**, the rule bit $40 had to learn the hard way:
    `det.note_alternate` says the player reads the bit, and only this record's
    own effect byte says it is set.
    """
    if det.note_alternate < 0 or det.instr_start < 0:
        return None
    rec7 = det.instr_start + i * det.instr_stride + 7
    if rec7 >= len(sid.data) or not sid.data[rec7] & EFFECT_NOTE_ALT_MASK:
        return None
    off = det.note_alternate + i * det.instr_stride
    if off >= len(sid.data):
        return None
    return _freq_table_note(sid, sid.data[off])


def _two_stage_frames(frames: int, effect: int) -> int:
    """How many frames bit $04's attack actually lasts, from its table byte.

    **A record that also sets bit `$40` sounds half of them**, and the byte on
    its own does not say so -- which is why H2G-CONVERSION-METHOD.md carried
    "the relationship between that byte and the shared `$0FAA,X` counter is not
    established" as an open question. It is a halving, measured across the
    corpus rather than reasoned:

        frames byte 2, effect $44   ->  1 frame   Sigma Seven $0FFD (124 onsets)
                                                  Ricochet $0CE8 (77)
                                                  Skate or Die $08D9 (300), $0AD8 (26)
        frames byte 4, effect $44   ->  2 frames  Trans-Atlantic $0A99 (150)
                                                  Sanxion $1909 (81), Pandora $0D99 (31)
                                                  Auf Wiedersehen Monty $0AF9 (10)
                                                  Knucklebusters $0AAD (4)
        frames byte 2, effect $04   ->  2 frames  Sigma Seven $2B9D (61)

    527 onsets on the first line alone and not one counter-example there; the
    `frames = 4` line is what rules out "always one frame", which the first line
    alone cannot distinguish from a halving.

    The mechanism this implies -- and it is an implication, not a reading of the
    6502 -- is that `$40`'s handler decrements the same per-voice attack counter
    `$04`'s does, so with both live it counts down twice per frame. That would
    make the halving exact rather than approximate, which is what the two
    measured points show.

    **One counter-example, recorded rather than smoothed over.** Lightforce's
    `$1FF9` is `$44` with a frames byte of 4 and measures 0 attack frames over
    15 onsets. Not explained. It is one record against nine.

    A halved byte never reaches zero here: `_two_stage_entries` declines a
    record whose frames are <= 0, and this returns at least 1 so such a record
    keeps an attack rather than silently losing the block.
    """
    if effect & EFFECT_FIXED_PITCH_MASK:
        return max(1, frames // 2)
    return frames


def _wave_alternate_entries(wave: int, alt: int, multiplier: int = 1,
                            start: Optional[int] = None,
                            budget: int = WAVE_ENTRIES_PER_INSTR,
                            written: bool = False,
                            alt_first: bool = False,
                            alt_note: Optional[int] = None) -> Optional[tuple]:
    """Bit $02's every-other-frame waveform, or None where it says nothing.

    `detect._find_wave_alternate` reads the block: the voice's waveform
    alternates each frame between the record's own `+2` and a second
    per-instrument table, chosen by the low bit of a per-voice frame counter.
    In 20 of the 21 corpus files carrying it the alternate is `$81` -- noise
    with the gate on -- so what it sounds is a noise frame every other frame
    under the note.

    **The phase is not free, and it is not guessed.** The note's first frame is
    spent by the init path writing the record's waveform (section 7.www), and
    the alternation runs from the second: W_A_R's instrument `$0900` reads
    `tri tri noi tri` on all 205 of its onsets, one shape with no distribution
    at all. So the shape is the frame-0 lead, then the pair, looping -- which
    is what a wavetable can hold. Contrast bit `$10`'s arpeggio (section
    7.ttt), whose global counter gives a note no reproducible starting phase.

    Each half lasts one *frame*, which is `multiplier` play calls, bought with
    a delay entry beside it exactly as `_first_frame_lead` does. The loop
    target is the first of the pair, so the lead is passed once per note and
    the alternation is continuous after it.

    **`alt_note` is effect bit $08, which is the same alternation applied to
    the note** -- a second block on the same counter and the same phase test,
    24 bytes after this one in Flash Gordon (`detect._find_note_alternate`).
    All 80 corpus records that set bit $08 also set bit $02, so the two are
    one shape and not two: the alternate half gets the alternate waveform
    *and* the alternate pitch, and the record's own half keeps its own of
    both. Passed as an absolute note byte (`_note_alternate_note`), None where
    the record does not set the bit or the index is not a note.

    The right side of the record's own half is `$00`, which is what puts the
    played note *back*: `gt2reloc` inverts bit 7 of every non-command right
    byte (`greloc.c:1339-1341`), so a `.sng` `$00` reaches the packed player
    as `$80` and writes `adc mt_chnnote,x / and #$7f` -- the note's own pitch
    -- on every call it is current for. `$80` would be no write at all, and
    the alternate pitch would simply stay. See `_hold_wave_program_entry`,
    where reading those two bytes the other way round made the whole
    `program` bucket of `VIBRATO.md` read zero.
    """
    if (alt <= WAVE_MAX_DELAY
            or (alt == wave and alt_note is None)
            or not (wave & 0xF0)):
        # An alternate in the delay range is not a waveform; an alternate
        # equal to `+2` alternates with itself; and a record with no waveform
        # of its own has nothing to alternate *from*. That last is a real
        # under-read rather than the one `_sfx_drum_entries` used to make: a
        # bit-$80 record with no waveform is the drum *alone* and is now
        # encoded (v0.5.253), where an alternation genuinely needs two.
        #
        # **`alt == wave` is a statement about the waveform only, so it stops
        # being a refusal the moment `alt_note` is present.** Bit $08 rides
        # this pair (see the docstring), and when the record's `+2` and its
        # alternate name the same waveform the *pitch* is the whole of what
        # the player alternates: same counter, same `AND #$01 / BEQ`, one half
        # sounding the pattern's note and the other the record's own index
        # into the player's frequency table. Declining there emitted a flat
        # note where the player sounds two.
        #
        # Corpus-wide this reaches **one record**: Dragons_Lair_Part_II's 24
        # (`+2 $81`, alternate `$81`, effect `$0A`, note index `$20` -> `$A0`),
        # the only record in any file where `alt == wave`, bit $08 is set, the
        # index resolves to a note, and the record is inside `det.instr_used`.
        # The other eleven bit-$08 records that resolve a note and reach no
        # alternation -- for any of these three reasons, or because the record
        # does not set bit $02 at all -- sit *past* `instr_used`: dead table
        # cells, the same shape the note-frequency census found. Neither of
        # the other two clauses fires on a single in-use record, so there is
        # no evidence to widen either of them on.
        # This one is played: 3 rows of GT pattern 39, reached by subtune 7
        # voice 1.
        #
        # **No column of `FIDELITY.md` can adjudicate this**, and that is
        # structural rather than a gap in the effort. The change moves a noise
        # instrument's *pitch*, and `nrun` compares run lengths while `melody`
        # reads the attack frame -- CLAUDE.md's own "no report column sees a
        # noise frame's pitch". The file is doubly unadjudicable: its traced
        # subtune is not the music our subtune 0 plays (15% on the diagonal,
        # 60% at o9), and this record only sounds in subtune 7, which nothing
        # traces. What is checked is the reach -- a corpus byte-hash names
        # this one file -- and `tests/test_note_alternate.py`.
        return None
    if start is None:
        return None
    lead, lead_r = _first_frame_lead(wave, multiplier, written=written)

    def half(w: int, note: int = WAVE_NOTE_BASE) -> tuple:
        # **`$00` re-asserts the played note and `$80` writes nothing.** This
        # comment had those two the wrong way round from v0.5.130 until the
        # `alt_note` work, on a reading of `player.s:976-977` alone: the
        # measurement it cited ("Hollywood or Bust's melody 58% -> 25% with
        # `$80` against 47% with `$00`") is right, and so is the byte, but the
        # reason is `greloc.c:1339-1341` -- `gt2reloc` packs every non-command
        # right byte as `b ^ $80`, so a `.sng` `$00` reaches the packed
        # player's `bne` as `$80`, takes the `bmi` path and writes
        # `adc mt_chnnote,x / and #$7f`, the note's own pitch. `$80` becomes
        # packed `$00` and makes no write at all. Same conclusion, and the
        # difference matters the moment an entry beside this one sets an
        # absolute pitch, as `alt_note` does: `$00` is what takes it back off.
        # `_hold_wave_program_entry` is where this was measured.
        left, right = [w], [note]
        rest = max(1, multiplier) - 1          # ...the entry above is one call
        if rest == 1:
            left.append(w)
            right.append(note)
        elif rest > 1:
            # The delay carries this half's own note, so one block keeps one
            # convention -- and with `alt_note` that is no longer merely
            # tidiness. A delay entry's right side is read on its *last* call
            # (gplay.c:697-723), which is the last call of the frame and the
            # one siddump samples: `$00` there would put the played note back
            # a call after the alternate was set, and the alternation would
            # measure as flat. Recorded when it was only tidiness: `$80` and
            # `$00` are equivalent on a delay entry, traced on W_A_R both ways
            # with 0 of 1500 frames differing on all three voices; they are
            # *not* on a waveform entry (see `half`'s first line).
            left.append(min(rest - 1, WAVE_MAX_DELAY))
            right.append(note)
        return left, right

    # **Which of the pair the note's second frame gets is read off the
    # branch, not assumed.** Both dialects test the counter with
    # `AND #$01 / BEQ`, and in both the note's frame 1 takes the
    # *fall-through* -- the tabled dialect's is the record's own waveform
    # (W_A_R measures `tri tri noi tri`) and the derived dialect's is the
    # noise (Hollywood or Bust measures `tri noi tri noi`). Same rule, opposite
    # output, which is why this is a parameter rather than a constant.
    # The alternate note travels with the alternate *waveform*: one counter,
    # one branch, one phase -- the player's two blocks read the same cell with
    # the same `AND #$01 / BEQ`, so the frame that sounds the alternate
    # waveform is the frame that sounds the alternate pitch.
    own_note = WAVE_NOTE_BASE
    alt_r = own_note if alt_note is None else alt_note
    first, second = (alt, wave) if alt_first else (wave, alt)
    first_r, second_r = ((alt_r, own_note) if alt_first
                         else (own_note, alt_r))
    a_l, a_r = half(first, first_r)
    b_l, b_r = half(second, second_r)
    left = lead + a_l + b_l
    right = lead_r + a_r + b_r
    if len(left) + 1 > budget:
        return None
    return left + [0xFF], right + [(start + len(lead)) & 0xFF]


def _two_stage_entries(wave: int, attack: int, frames: int,
                       multiplier: int = 1,
                       attack_note: Optional[int] = None,
                       budget: int = WAVE_ENTRIES_PER_INSTR,
                       written: bool = False,
                       hold_attack: bool = False,
                       start: Optional[int] = None,
                       restore_call: Optional[int] = None) -> tuple:
    """Wavetable entries for the two-stage waveform, or None if it says nothing.

    The dialect `detect._find_two_stage` reads, in 44 corpus files: effect bit
    $04 is not an arpeggio but an *attack waveform*, held for a per-instrument
    number of frames and then dropped to the record's own +2. Detection has
    located both arrays since it was written and nothing consumed them, so
    every one of those files played the second stage from its first frame.

    What that costs is not subtle. Trans-Atlantic's GT 2 is `$81` noise for 4
    frames before its pulse -- 226 notes of drum the conversion played as a
    pulse -- and its GT 4 has **no waveform of its own at all** (`+2` is `$00`),
    so the attack is the only waveform it ever has and the instrument was
    silent for all 70 of its notes.

    A record whose `+2` is zero has **no** second stage: the player writes
    `$00` there, which selects no waveform and stops the sound outright. That
    used to be emitted as the attack waveform released, on the grounds that a
    wavetable cannot say `$00` -- `$00`-`$0F` are delays. It can: `$18` is the
    test bit with a waveform selected, and the test bit holds the oscillator at
    zero, so it is silent in both players (`_wave_byte`). Trans-Atlantic's
    `$0AF8` is the one corpus record that reaches this: the original sounds
    five frames and stops, and the released attack kept sounding for the whole
    slot -- 11 frames on a twelve-frame note, and 23 on a twenty-four.

    `frames` is a per-frame count and the table steps per *call*, so it is
    scaled by `multiplier`; and a delay entry holds for `value + 1` calls, with
    entry 0 itself being one, exactly as `_wave_hold_byte` sets out.
    """
    if attack == 0 or frames <= 0:
        return None
    calls = max(1, frames) * max(1, multiplier)
    second = _wave_byte(wave & 0xFE) if not wave & 0xF0 else wave & 0xFE
    # `attack_note` is effect bit $40: the attack does not play the pattern's
    # note at all, it plays a fixed pitch out of the player's own note table
    # (detect._find_effect_bit40). Without it the attack sounded at whatever the
    # pattern asked for, and since these attacks are mostly noise -- whose pitch
    # is the rate its shift register clocks -- that is the difference between a
    # snare and a thud. Trans-Atlantic's GT 2 sounded its noise at frequency
    # high bytes 3-13 where the original sounds every one of 226 at $15EB.
    left, right = [attack], [attack_note if attack_note is not None else 0x00]
    extra = calls - 1             # entry 0 is already one call
    if attack_note is not None:
        # **The remaining calls are spelled out rather than folded into a
        # delay.** The reason recorded here was corrected once and is corrected
        # again: it read "the rest of the attack returns to the played note",
        # then was rewritten to "`$00` is no frequency write at all", citing
        # `player.s:976-977`. That second reading is the PACKED byte's, and
        # this is a `.sng` byte -- `gt2reloc` inverts bit 7 of every
        # non-command right byte (`greloc.c:1340-1341`), so a `.sng` `$00`
        # arrives as packed `$80` and DOES write: `adc mt_chnnote / and #$7f`,
        # the played note. The original wording was nearer the truth than its
        # correction.
        #
        # What actually separates the two forms is the other end. A delay's
        # right side is read on its FINAL call, so folding these into one
        # delay would re-assert the played note once at the end of the attack
        # instead of on every call of it -- and on a fixed-attack-pitch record
        # that is the difference between holding the pitch and dropping back.
        # Spelled out, every call carries the same byte and the shape is
        # explicit.
        #
        # THIS IS THE THIRD COMMENT IN THIS FILE ABOUT THAT ONE BYTE. The
        # other two (`WAVE_NOTE_BASE`'s definition and
        # `_wave_alternate_entries.half()`) were each corrected by a separate
        # change that did not know about this one, which is how a superseded
        # reading survived beside two correct ones. When this byte's meaning is
        # restated, grep the file for `greloc.c` and `976-977` and fix every
        # site, or the next reader will find the wrong one first.
        #
        # Holding is what the player does. One_on_One's GT 2 (`$44`, frames
        # byte 4 -> 2), 372 onsets and no distribution on any offset: the
        # played note on frame 0, then `$4310` on frames 1, 2 **and** 3 --
        # one frame past the attack waveform, which drops back to the
        # record's own `+2` on frame 3. So the fixed pitch outlives the stage
        # it belongs to, and a form that ended it early would be the wrong
        # one. (Where it outlives the stage is the vibrato's counter gate:
        # One_on_One's gate is 4 -- see `restore_call` below.)
        # **The fixed note, not `$00`.** Until v0.5.459 this line read
        # `right += [0x00] * extra`, and the paragraph above says exactly why
        # that is wrong without noticing that the code did it: a `.sng` `$00`
        # is packed `$80` and WRITES the played note, so every call after the
        # first undid entry 0 and the fixed pitch lasted one call. The
        # One_on_One trace quoted above -- `$4310` on frames 1, 2 and 3 -- is
        # the measurement that says the pitch outlives the stage, and it was
        # sitting in this comment while the line below contradicted it.
        # Repeating the note rather than writing `WAVE_NOTE_KEEP` is the same
        # choice the paragraph makes for spelling the calls out at all: it is
        # robust to anything else writing $D400/$D401 during the attack, where
        # "leave the frequency alone" inherits whatever did.
        #
        # **Spelled out only where the budget allows it.** Spelling costs
        # `calls + 2` entries and the layout guarantees a later record only
        # `WAVE_ENTRIES_PER_INSTR` (`tests/test_instrument_bound.py`). This
        # branch never checked, and nothing caught it while the records
        # reaching it were Trans-Atlantic's and One_on_One's two- and
        # three-call attacks; reading the note index out of the handler
        # (`det.fixed_pitch_index`) reached Delta Mix-E-Load's
        # ten-call attack at `-S1` and Go Go Dash's four, 12 and 6 entries
        # against a budget of five. Over budget the remaining calls fold
        # into one delay whose right side is the fixed note: a delay writes
        # no frequency until its final call (`test_call_rate.wave_timeline`,
        # gplay.c:697-704), so entry 0's pitch stands through it and the
        # final call re-asserts the same byte. What the fold gives up is the
        # robustness above, not the pitch.
        #
        # The fold is the default, not an option: it was behind a `fold_note`
        # kwarg only because `tests/test_effect_bit80.py` pinned the
        # spelled-out form at the DEFAULT budget of five for a four-call
        # attack -- six entries, the overrun itself. Those tests now pass an
        # explicit budget, as `test_call_rate` does, and
        # `tests/test_instrument_bound.py` holds the guarantee across both.
        if 1 + extra + 2 <= budget or extra <= 1:
            left += [attack] * extra
            right += [attack_note] * extra
        else:
            left.append(min(extra - 1, WAVE_MAX_DELAY))
            right.append(attack_note)
    elif extra == 1:
        left.append(attack)       # no delay encodes one call; rewrite instead
        right.append(0x00)
    elif extra > 1:
        left.append(min(extra - 1, WAVE_MAX_DELAY))
        right.append(0x80)
    # `hold_attack`: the second stage leaves the fixed pitch standing instead
    # of writing the played note back. That is the player's own branch once
    # the countdown runs out on a record whose vibrato byte is set (Sanxion
    # $B40B `LDA $B571,Y / BNE $B421` -- record +5, the byte its vibrato
    # reads -- skips the `LDA note,X` restore), and only the vibrato writes
    # the frequency after it. See `_attack_hold_pass` for which notes that
    # leaves holding the attack pitch, and why it is a per-note choice.
    #
    # **The held stage loops on itself, writing the fixed note every call;
    # it does not end on `WAVE_NOTE_KEEP`.** Ending the program (`FF 00`)
    # handed the frequency to GoatTracker's own instrument vibrato, and
    # `gplay.c:351-353` reloads `vibdelay` on every new note, so a short
    # note of a vibrato instrument vibrated anyway: Sanxion's i14 stepped
    # C#6 -> D-6 at N+4 on 81 short notes in 100 s at v0.5.496, where the
    # original's `$B257` duration gate never vibrates them. A wavetable
    # entry whose right side is not `$80` sets the frequency and jumps to
    # PULSEEXEC, skipping TICKNEFFECTS (gplay.c, the `note != 0x80` block)
    # -- so an entry that is current on every call keeps the vibrato off.
    # The jump is absolute, hence `start` (C:/t/sanxion-held-attack-loop).
    held = hold_attack and attack_note is not None
    if held and start is None:
        raise ValueError("hold_attack loops to an absolute wavetable "
                         "position and needs the block's `start`")
    attack_end = len(left)
    left += [second | (wave & 0x01), 0xFF]
    right += [attack_note if held else 0x00, 0x00]
    # The note's first frame is the record's own waveform; the attack starts on
    # the second. See `_first_frame_entry`. One frame is `multiplier` calls, the
    # same conversion `calls` above makes -- and the entries are dropped whole
    # rather than the block truncated where the 255-entry table has no room for
    # them, which is the degradation every other emitter here already makes.
    lead, lead_r = _first_frame_lead(wave, multiplier, written=written)
    # `restore_call`: the fixed pitch stands until the counter gate opens
    # (`_counter_gate_restore_call`), so the second stage starts on the fixed
    # note and the played note comes back on call `restore_call` -- the call
    # the classic vibrato first writes in the original. Only where the hold
    # fits beside the lead; otherwise the block is the one it always was.
    if restore_call is not None and attack_note is not None and not held:
        before = _wave_block_calls(lead + left[:attack_end])
        room = budget - len(left) - len(lead)
        hold = _fixed_hold_entries(second | (wave & 0x01), attack_note,
                                   restore_call - 1 - before, room)
        if hold is not None:
            left[attack_end:attack_end] = hold[0]
            right[attack_end:attack_end] = hold[1]
    if lead and len(left) + len(lead) <= budget:
        left[:0] = lead
        right[:0] = lead_r
    if held:
        right[-1] = (start + len(left) - 2) & 0xFF
    return left, right


def _wave_block_calls(left: List[int]) -> int:
    """Calls a straight run of wavetable left bytes occupies: a delay (or
    `$00`) `v` is current for `v + 1` calls (gplay.c:697-704), anything else
    for one. No jump is expected inside the run."""
    return sum(v + 1 if v <= GT_WAVE_LAST_DELAY else 1 for v in left)


def _fixed_hold_entries(wave: int, note: int, calls: int,
                        room: int) -> Optional[tuple]:
    """(left, right) holding absolute `note` on `wave` for `calls` calls in
    at most `room` entries, or None where that is nothing or does not fit.

    The first entry sets the waveform (the attack's stage is over) and is
    one call; the rest are spelled out where they fit -- each one a
    frequency write, so no continuous effect runs on it -- and otherwise
    fold into delays whose right side is the same note. A delay writes
    nothing until its final call (`test_call_rate.wave_timeline`), so the
    note entry 0 wrote stands through it, and its effect ticks are spent
    against `vibdelay` exactly as `_effect_call_list` counts them.
    """
    if calls <= 0 or room <= 0:
        return None
    left, right = [wave], [note]
    rest = calls - 1
    if 1 + rest <= room:
        return left + [wave] * rest, right + [note] * rest
    while rest > 0:
        step = min(rest, WAVE_MAX_DELAY + 1)
        left.append(step - 1)
        right.append(note)
        rest -= step
    return (left, right) if len(left) <= room else None


def _counter_gate_restore_call(sid: SidFile, det: Detection, i: int,
                               multiplier: int,
                               written: bool) -> Optional[int]:
    """The call on which record `i`'s played note comes back after effect bit
    $40's fixed attack pitch, where a counter vibrato gate decides it; else
    None (the note comes back when the attack stage ends, as before).

    The `$40` handler hands the frequency to the vibrato once its countdown
    runs out on a record whose vibrato byte is set (`_fixed_pitch_yield_field`
    -- the `LDA field,Y / BNE out` that skips `LDA note,X`), and a counter
    (dialect A) vibrato does not write until frame `gate`
    (`_classic_gate_delay`). Nothing writes the frequency in between, so the
    fixed pitch stands to frame `gate` and the vibrato then runs from the
    played note. Measured on the originals' first frames after an attack
    whose pitch steps to the fixed one (C:/t/counter-gate-fixed-attack-holds-
    to-the-g, 2026-10-03): Wiz record 8 (gate 4) `N F F F` then the vibrato
    from frame 4; Nemesis record 0 (gate 3) `N F F` then from frame 3. The
    conversion wrote the note back the call after the attack stage.

    The call is the gate's own target (`_counter_gate_call`), counted from
    the call the attack is seen on. A record whose vibrato byte is 0 takes
    the handler's other branch, `LDA note,X`, and is not this; nor is the
    duration form, whose short notes never vibrate at all
    (`_attack_hold_records`).
    """
    vg = det.vibrato_gate
    if (vg is None or vg.form != "counter" or det.vibrato_offset is None
            or det.instr_start < 0):
        return None
    base = det.instr_start + i * det.instr_stride
    if base + det.vibrato_offset >= len(sid.data):
        return None
    if not sid.data[base + det.vibrato_offset]:
        return None
    if _fixed_pitch_yield_field(sid, det) != det.vibrato_offset:
        return None
    return _counter_gate_call(det, max(1, multiplier),
                              0 if written else 1, i)


def _voice_two_stage_entries(wave: int, alt: int, threshold: int,
                             multiplier: int = 1,
                             budget: int = WAVE_ENTRIES_PER_INSTR,
                             written: bool = False,
                             gate_skip: Optional[int] = None
                             ) -> Optional[tuple]:
    """Bit $02's attack where its parameters are per voice, or None.

    The same *shape* as `_two_stage_entries` -- an attack waveform, then the
    record's own -- so it delegates rather than re-emitting one; what is new is
    where the two parameters come from. `detect._find_voice_two_stage` reads
    them out of two static three-byte tables the player indexes by voice, so
    the caller has already resolved which voice this instrument is played on
    (`tracks.instrument_voices`) and passes that voice's pair.

    **`threshold - 1`, and the `- 1` is measured rather than reasoned.** The
    player compares a per-note frame counter against the threshold, and the
    counter is zeroed and then incremented on the note's *first* call, which
    is the one call that never reaches the effect block -- the note-start path
    jumps straight past it (Ninja `$C95C`). So the second call reads 1, not 0,
    and the attack ends `threshold - 1` calls later. Traced three ways on
    Ninja's voice 3, whose pair is `$15`/4: the file as it ships sounds the
    alternate for four displayed frames of which one is a skipped gate call,
    a copy patched to `threshold = 1` sounds it for none at all, and a copy
    with the alternate's table load redirected to the counter prints the
    counter itself into `$D404`. The first of those alone reads as `threshold`
    frames and is the wrong reading; it took the second to separate them.

    **Then corrected for the gate the player skips calls on.** Those three
    active calls occupy four *displayed* frames on Ninja, whose outer counter
    (`$C806`, `DEC / BPL / reload 3 / RTS`) does nothing on one call in four,
    and our player has no such counter -- see `_gate_calls`. Measured against
    the uncorrected form on the one file that carries this: `slides` 947 ->
    1026 of the original's 1338, `bend` 0.67x -> 0.75x and `vib` 0.59x ->
    0.79x, with `onset`, `melody` and `wave` unmoved. Both readings give 4 for
    a threshold of 4, which is every threshold this corpus actually reaches --
    they part company at Ninja's third voice, whose 6 is `_gate_calls(5) = 7`
    against a bare `threshold` of 6, and no instrument is played there. So the
    ratios above are what chose the correction; the arithmetic is what makes
    it a reading rather than a coincidence.
    """
    return _two_stage_entries(wave, alt, _gate_calls(threshold - 1, gate_skip),
                              multiplier, budget=budget, written=written)


def _two_stage_pitch_seq_entries(wave: int, attack: int, frames: int,
                                 notes: List[int], start: int,
                                 multiplier: int = 1,
                                 budget: int = WAVE_ENTRIES_PER_INSTR,
                                 written: bool = False,
                                 frames_per_step: int = 1,
                                 phases: Optional[tuple] = None,
                                 phase_notes: Optional[List[int]] = None
                                 ) -> Optional[tuple]:
    """One block carrying bit $04's attack waveform *and* bit $10's arpeggio.

    The two bits are **sequential, independent tests on the same effect byte**,
    not exclusive branches. Read off Trans-Atlantic's player, whose record byte
    +7 is copied to the scratch cell `$0EFB` once and then tested five times in
    a row -- `$08` at $0B44, `$04` at $0B9C, `$10` at $0BB8, `$20` at $0BEB and
    `$40` (as `BIT`/`BVC`) at $0C05:

        0B9C  LDA $0EFB / AND #$04 / BEQ $0BB7   ; bit $04: the *waveform*
        0BA3  LDA $0FAA,X / BEQ +                ;   attack counter still running?
        0BA8  DEC $0FAA,X / LDA $116C,Y          ;   yes: the attack waveform
        0BB1 +LDA $10DB,Y                        ;   no:  the record's own +2
        0BB4  STA $0D5E,X                        ;   -> the voice's waveform cell
        0BB7  CLC
        0BB8  LDA $0EFB / AND #$10 / BEQ $0BEB   ; bit $10: the *note*
        ...   LDY $107C / LDA note,X / ADC seq,Y ;   played note + this step
        0BDC  LDA $0C8C,Y / STA $0EE5,X          ;   -> the voice's frequency
              LDA $0C8D,Y / STA $0EB5,X

    Nothing between $0BB7 and $0BB8 can skip the second test, so a record whose
    effect byte is `$14` gets both: the attack's waveform and, on the same
    frames, the arpeggio's note. Trans-Atlantic's record 3 (`0AF8`) is the one
    such record any corpus file plays with both options on, and the original's
    trace shows exactly that -- five frames of `$11` from the note's onset with
    the frequency stepping `+24, 0, 0, +24, 0` through them, and the arpeggio
    continuing after the waveform goes to `$00`.

    So the arpeggio runs across *both* stages, and the block loops on the
    sustain stage rather than stopping there, because the player keeps writing
    the frequency for as long as the note is held. Every frame gets its own
    entry: a delay entry cannot carry a note that changes on the frames it
    covers (gplay.c:697-723 applies the right side only on the delay's last
    call), which is the cost of the mechanism and not a choice.

    The rate is scaled the way `_two_stage_entries` scales `frames`: the
    player's phase counter advances once per frame of a single-speed original,
    and the wavetable steps once per *play call*, so each step holds
    `multiplier` entries. `_pitch_seq_entries` **now does the same** -- it did
    not for as long as this function has existed, and this docstring flagged the
    divergence rather than fixing it ("consistent with this function only at
    multiplier 1"). It also over-counted the reach: the flag said correcting the
    standalone path "would move three shipped multispeed files", and it moves
    **two** (Shockway_Rider and Star_Paws). Flash_Gordon, Mr_Meaner and
    Thundercats are multispeed with `--pitch-seq` on and emit nothing from that
    path at all: every record that reaches it has bit $10 *clear* (28 of them
    across the three), so their bit-$10 records were taken by an earlier branch
    -- this block among them. Count what an option reaches before sizing a
    change to it. Note what the scaling costs to check: no trace in the repo can
    adjudicate it, because
    siddump samples once per frame whatever the call rate, so on Thundercats at
    -S3 the scaled and unscaled blocks emit different bytes and score the
    identical 1308 reversals. The scaling is shipped because it is what the
    player says, not because a column moved.

    `frames_per_step` is the player's divider (`detect.PitchSeq.frames_per_step`,
    Food_Feud's 4, 1 everywhere else): each arpeggio step is held that many
    frames, i.e. `frames_per_step * multiplier` calls, while the ATTACK keeps
    its own `frames * multiplier` -- the divider gates the phase cell only,
    and bit $04's counter is a separate per-voice cell (`$0FAA,X` above).

    `phases` and `phase_notes` (both or neither) carry the player's global
    phase where it is knowable (`pitch_seq_phases`): `phase_notes` indexed by
    the phase cell's value, `phases` the cell's reading on frames 1, 2, ...
    after the attack. Entry `c` past the lead is frame `1 + c // hold` of
    the note, so it names `phase_notes[phases[c // hold % period]]` and the
    rotation below is not applied -- the phase says where the cycle stands.
    The loop is the counter's period in calls, which is `len(notes) * step`
    for a counter that steps every `frames_per_step` frames, so the block is
    the same length either way.

    Returns None where the block will not fit the record's budget, so the
    caller falls back to the plain two-stage shape rather than emitting a
    truncated arpeggio.
    """
    if attack == 0 or frames <= 0 or not notes:
        return None
    if phases and phase_notes:
        if any(not 0 <= k < len(phase_notes) for k in phases):
            phases = None
    # **The attack frame sounds the pattern's own note.** Entry 0 is applied on
    # the note's first call, and that is the frame `melody` and a listener alike
    # read the note's identity from. The player's phase is global, so whichever
    # step really falls there is unknowable and any step we choose is a guess --
    # but a step of zero is the one guess that cannot *rename* the note, so the
    # cycle is rotated to open on one where it has one (`seq[0]` is the byte
    # nothing writes, so it nearly always does). Measured on Thundercats, whose
    # sequence opens `+3`: without this the reversals come out exact, 1308
    # against the original's 1308, and melody falls 77.3% -> 65.7% on unchanged
    # note counts -- 148 notes named three semitones sharp. The same trap as
    # section 7.qqq's `$40` pitch on frame 0, and it is invisible on
    # Trans-Atlantic, whose rotation already opens on zero and whose bytes this
    # rule leaves untouched.
    #
    # A rotation is the freedom `_pitch_seq_notes` already exercises for the
    # same reason, so this narrows a choice rather than contradicting one; it is
    # applied here only, leaving the eight files that ship the standalone path
    # byte for byte as they are.
    if WAVE_NOTE_BASE in notes:
        turn = notes.index(WAVE_NOTE_BASE)
        notes = notes[turn:] + notes[:turn]
    hold = max(1, multiplier)
    calls = max(1, frames) * hold
    # Calls per arpeggio step: the attack's `calls` is NOT scaled by this.
    step = hold * max(1, frames_per_step)
    # Same rule as `_two_stage_entries`, and this is the path that reaches the
    # record it was written for: a `+2` selecting no waveform is silence, not
    # the attack released. Trans-Atlantic's `$0AF8` carries `$14`, so with
    # `--pitch-seq` on -- which its preset has -- it comes here.
    second = _wave_byte(wave & 0xFE) if not wave & 0xF0 else wave & 0xFE
    tail = second | (wave & 0x01)
    loop = len(notes) * step
    if phases and phase_notes:
        loop = len(phases) * hold
    # The note's first frame is the record's own waveform (`_first_frame_entry`)
    # and the attack -- with the arpeggio that runs across it -- starts on the
    # second. Trans-Atlantic's GT 4, the one corpus record this path reaches, has
    # `+2 $00` and so takes no such entry; the branch is here because the other
    # files carrying both bits do have a waveform. It is one *frame*, so `hold`
    # calls -- spelled out rather than delayed, because this block spells every
    # other frame out for the same reason (a delay entry's right side is read
    # only on its last call, and the note base has to be current from the first).
    lead = hold if _first_frame_entry(wave, written) else 0
    if lead + calls + loop + 1 > budget:
        return None
    left: List[int] = [wave] * lead
    right: List[int] = [WAVE_NOTE_BASE] * lead
    for c in range(calls + loop):
        left.append(attack if c < calls else tail)
        if phases and phase_notes:
            right.append(phase_notes[phases[(c // hold) % len(phases)]])
        else:
            right.append(notes[(c // step) % len(notes)])
    # The jump targets the sustain stage, not the block: the attack runs once
    # per note, and so does the first-frame entry before it -- which is why the
    # target carries `lead`. `loop` is exactly `len(notes)` steps of `step`
    # calls, so the entry after the loop's last would name the step the loop's
    # first names, whatever `calls` is modulo `step`: the cycle stays
    # continuous across the jump, as the player's free-running counter does.
    left.append(0xFF)
    right.append(start + lead + calls)
    return left, right
