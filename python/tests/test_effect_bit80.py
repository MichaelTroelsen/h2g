"""Effect byte bit $80 -- three different blocks, one of which is not music.

Every note this project has carried about bit $80 said one thing: that it
"drives a hard-coded voice-3 noise hit plus global filter/volume off a global
state byte, which no per-instrument wavetable can express". That is true of
nine of the twelve corpus files that test the bit, and false of the other
three. Reading all twelve blocks out of the 6502 splits them:

    sfx      9  a fixed-pitch noise hit on voice 3, plus cutoff and volume
    program  2  a per-instrument byte-code wave program (ACE II, Monty)
    pitch    1  a counter-driven frequency step (Delta)

The "sfx" nine are the strongest of the three results even though they are the
negative one: the cell they switch on is written by the *game*, not by
anything in the SID, so in a rip the block is dead code -- and if it did fire
it would seize voice 3 and the master volume. It is not merely inexpressible;
converting it would be wrong.

`goatwriter` consumes none of this. See H2G-CONVERSION-METHOD.md section 7.jj.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402


from h2g.detect import detect
from h2g.sidfile import load_sid

COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"

CORPUS = _CORPUS

SFX = ["ACE_II", "Auf_Wiedersehen_Monty", "Bangkok_Knights", "Delta",
       "IK_plus", "Mega_Apocalypse", "Nineteen", "Pandora", "Ricochet",
       "Star_Paws", "Thundercats", "Trans-Atlantic_Balloon_Challenge"]
# v0.5.236: the six 16-byte-record files the stride guard in
# `_effect_byte_address` had been hiding this routine from as well (see
# test_two_stage.py). They report the same $48 / voice 2 / period 6 the
# stride-8 members of their family do -- and **not one of them has a record
# that sets bit $80**, so the drum is read and emitted nowhere, which is the
# per-record rule working rather than a detection that spread.
SFX += ["After_8", "Mr_Meaner", "Off_the_Cuff", "Pygmies_Revenge", "Rikky",
        "Rock_Tells_the_Tale"]
# v0.5.455: I_Ball, hidden the same way by a DIFFERENT guard in the same
# function -- `_effect_byte_address` inverted only the plain branch of
# `to_offset`, and I_Ball is the corpus's one relocated file, so the probe
# looked for `LDA $9712,Y` where the player reads the moved copy at $E712.
#
# DISASSEMBLED before being added here, because this list's own rule is that a
# thirteenth match would be "a shape nobody has disassembled". Its block is the
# documented family verbatim:
#
#   E3E9  LDA $E557        ; the effect byte -- the address the fix computes
#   E3EC  BPL $E41B        ; the "LDA effect / BPL" entry all 12 share
#   E3EE  LDA $E566        ; a GLOBAL cell, not per voice or per instrument
#   E3F1  CMP #$01 ... CMP #$06
#   E405  LDA #$48 / STA $D40F      ; voice-3 frequency high
#   E40A  LDA #$81 / STA $D412      ; noise + gate
#   E40F  LDA #$60 / STA $D416      ; cutoff high
#   E414  LDA #$2F / STA $D418      ; volume
#   E400  STA $E566                 ; zeroed when it runs past the end
#
# UNLIKE the six above, I_Ball DOES have records that set bit $80 -- four of
# its nineteen -- so here the drum is read AND emitted. Forced on, it takes
# `sequence` 0.776 -> 0.980 and `retrig` 0.697 -> 0.979 with the attack count
# 594 -> 834 against the original's 852.
SFX += ["I_Ball"]

EXPECTED = {
    "ACE_II": "program",
    "Auf_Wiedersehen_Monty": "program",
    "Delta": "pitch",
}


def _detect(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, log=lambda m: None)


def test_the_twelve_files_split_three_ways():
    if not CORPUS.is_dir():
        return
    got = {n: _detect(n)[1].effect_bit80 for n in SFX}
    for name, shape in got.items():
        assert shape == EXPECTED.get(name, "sfx"), (name, shape)


def test_no_other_corpus_file_is_classified():
    if not CORPUS.is_dir():
        return
    # The probe must not spread: every file it claims has to be one of the
    # twelve whose block was actually read. A signature that matched a
    # thirteenth would be matching a shape nobody has disassembled.
    named = set(SFX)
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _, det = _detect(path.stem)
        except Exception:
            continue
        if det.effect_bit80:
            assert path.stem in named, (path.stem, det.effect_bit80)


def test_the_program_pointer_array_resolves_and_parses():
    if not CORPUS.is_dir():
        return
    sid, det = _detect("ACE_II")
    assert det.effect_program >= 0
    data, stride = sid.data, det.instr_stride
    # Instrument 1 sets bit $80; its pointer must land inside the file and the
    # bytes there must parse as the engine reads them -- an entry >= $80 is a
    # two-byte (waveform, frequency-high) pair, one < $80 is a three-byte
    # (waveform, 16-bit downward frequency delta).
    rec = det.instr_start + 1 * stride
    assert data[rec + 7] & 0x80
    ptr = data[det.effect_program + stride] | (data[det.effect_program + stride + 1] << 8)
    at = sid.to_offset(ptr)
    assert 0 <= at < len(data)
    assert data[at] == 0x81 and data[at + 1] == 0x40      # noise+gate, freq hi
    assert data[at + 2] == 0x41                            # pulse+gate, then a
    assert data[at + 3:at + 5] == bytes((0x80, 0x03))      # 16-bit SBC pair


def test_the_sound_effect_files_are_not_given_a_program():
    if not CORPUS.is_dir():
        return
    # IK+ patches its own code instead of writing $D40F/$D412, and Ricochet's
    # arms are empty in the rip. Both must still read as "sfx" and must not
    # hand goatwriter a pointer array that does not exist.
    for name in ("IK_plus", "Ricochet"):
        _, det = _detect(name)
        assert det.effect_bit80 == "sfx"
        assert det.effect_program == -1


# --- what the "sfx" block actually is (v0.5.181) ---------------------------
#
# It was read as the *game's* sound effect and left unconverted because it
# "keys off a global state byte". Both halves are wrong. The gate is
# `LDA effect / BPL` on the very cell _effect_byte_address locates -- the
# playing instrument's own +7 -- and the counter is `$0FAD,X` for the third
# voice, not a global. It is a drum, and it is music. A listener found it by
# reporting Trans-Atlantic's drums missing.

@needs_corpus
def test_the_sfx_block_is_a_fixed_pitch_drum_on_one_voice():
    if not CORPUS.is_dir():
        return
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            det = detect(load_sid(str(path)), log=lambda m: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.effect_bit80 == "sfx" and det.sfx_pitch >= 0:
            found[path.stem] = (det.sfx_pitch, det.sfx_voice, det.sfx_period)
    # 7 until v0.5.236, when lifting the stride guard reached six more; 14
    # since v0.5.455, when `_effect_byte_address` learned to invert
    # `to_offset`'s RELOCATION branch as well and reached I_Ball; **15 since
    # v0.5.459**, when `_find_sfx_drum` learned the SHADOW spelling and reached
    # IK+. All three increments are the same shape -- a probe that could only
    # read one spelling of an address, hiding this whole family from a subset
    # of the corpus -- and that is now three sightings of it in one function's
    # neighbourhood.
    assert len(found) == 15, sorted(found)
    # Every one of them is voice 3, and the pitch is a constant of the player
    # rather than the note -- which is the whole point: the SID's noise is an
    # LFSR clocked by the frequency, so noise at the note's own low pitch
    # writes the register and makes no sound.
    assert {v for _, v, _ in found.values()} == {2}
    assert found["Trans-Atlantic_Balloon_Challenge"][0] == 0x38
    assert {p for p, _, _ in found.values()} == {0x38, 0x48}
    assert {q for _, _, q in found.values()} <= {6, 8}


@needs_corpus
def test_the_one_file_without_the_block_reports_no_pitch():
    """Ricochet's arms are empty in the rip. It may not be handed a made-up
    pitch.

    **This was two files, and the reason given for the other one was wrong.**
    The docstring read "IK+ patches its own code instead of writing
    $D40F/$D412". It does not: IK+ writes those two registers to a RAM image of
    the SID at `$E5E3` and flushes it once a frame, and its drum block is the
    documented one byte for byte apart from the two store targets. Disassembled
    at $E41C at v0.5.459 and rescued there -- so IK+ now reads voice 2, `$48`,
    period 6, and only Ricochet is left.

    Ricochet is a different case and stays: neither the direct nor the shadow
    spelling matches it, and its SID image base IS $D400, so it is not a shadow
    player with an unread base -- the block simply is not there to find.
    """
    if not CORPUS.is_dir():
        return
    _, det = _detect("Ricochet")
    assert det.effect_bit80 == "sfx"
    assert (det.sfx_pitch, det.sfx_voice, det.sfx_period) == (-1, -1, -1)


def test_the_hit_is_on_the_notes_second_frame():
    """**Frame 0 is the played note and frame 1 is the hit** (v0.5.246).

    This test used to assert the noise sat at the *end* of the cycle, on the
    reading that the player's counter was "per voice and free-running". It is
    not: Bangkok Knights zeroes it at note start (`LDA #$00 / STA $8934,X` at
    $80CE, in the block clearing this voice's other per-note cells) and `INC`s
    it once a frame at $84D2, then fires on `CMP #$01 / BEQ`. Trans-Atlantic's
    player is the same routine byte for byte at $0C2E.

    The measurement that reading rested on is real and was misread: opening on
    the noise at **frame 0** puts the drum's pitch on the note's own attack
    frame, where siddump names the note, and Trans-Atlantic's melody fell
    94.7% -> 50.4%. That is an argument against frame 0, which this shape still
    respects -- it is not an argument for putting the hit last.
    """
    from h2g.goatwriter import _sfx_drum_entries, _sfx_note_byte
    left, right, loop = _sfx_drum_entries(0x41, 0x38, 6)
    assert left == [0x41, 0x81, 0x41, 0x03]
    assert right[0] == 0x00, "relative 0 -- the played note, not an absolute"
    assert left[1] == 0x81 and right[1] == _sfx_note_byte(0x38)
    assert loop == 1, "the loop returns to the hit, not to the note"


def test_the_pitch_becomes_the_nearest_absolute_note():
    """A wavetable's right side names a note, where the player writes $D401
    directly and keeps the note's low byte. $3800 lands on index 68 ($375C)
    and $4800 on 73 ($49E5), both inside a quarter-tone -- which for noise is
    a difference nobody can hear, the pitch only setting how fast the shift
    register clocks."""
    from h2g.goatwriter import _note_freq, _sfx_note_byte
    for hi in (0x38, 0x48):
        idx = _sfx_note_byte(hi) - 0x80
        assert abs(_note_freq(idx) - (hi << 8)) < (hi << 8) * 0.03
        assert 0x81 <= _sfx_note_byte(hi) <= 0xDF, "outside GT's absolute range"


def test_it_is_off_by_default_and_selected_per_song():
    from h2g.convert import convert
    import presets
    assert len(convert(str(CORPUS.parent / "x.sid") if False
                       else str(COMMANDO), log=lambda m: None)) == 15193
    assert "sfx_drum" in presets.EXCLUDED_FROM_ALWAYS
    assert "sfx_drum" in presets.FIDELITY_TOGGLES


def test_an_instrument_with_no_waveform_is_the_drum_on_its_own():
    """`(wave & 0xFE) | 0x01` is `$01` for a record whose +2 is $00 or $01, and
    $01-$0F are *delays* in a wavetable, not waveforms (readme.txt:3.4.1).
    Written literally the instrument set no waveform at all -- it inherited
    noise from whatever played before, and its delay entry applied a relative
    note, so Bangkok Knights' GT 9 sounded 40 frames at `freqtbl[0]` = $0117
    where the drum belongs at $49E5.

    **The conclusion drawn from that was to decline the record**, and declining
    it silenced the drum instead: such a record is the drum *on its own*.
    Nineteen's record 4 is 58 pattern rows and 151 of its original's 267 attacks
    on voice 3 in 60 s, and it emitted three one-call delays and a stop. The
    encoding that was missing is `_wave_byte`'s -- `$E0`-`$EF` writes $00-$0F to
    $D404 as the control bits they are (gplay.c:527) -- which is why the
    invariant below is about the *range*, not about refusing.
    """
    from h2g.goatwriter import _sfx_drum_entries, WAVE_SILENT_BASE
    for wave in (0x00, 0x01, 0x41):
        left, _r, _loop = _sfx_drum_entries(wave, 0x48, 6)
        assert left[0] > 0x0F, "the first entry must be a waveform, never a delay"
    for wave in (0x00, 0x01):
        left, _r, _loop = _sfx_drum_entries(wave, 0x48, 6)
        assert left[0] == WAVE_SILENT_BASE | 0x01, "gate alone, via $E0-$EF"


# --- v0.5.204: effect bit $40, decoded ---------------------------------------

def test_bit40_is_tested_with_bit_and_bvc_not_and():
    """Which is why every scan for it missed it. Bit 6 has a 6502 idiom of its
    own -- `BIT cell / BVC` -- and this converter's effect-bit detection looks
    for `AND #$xx`. The same idiom STATUS_BIT6_SHAPE relies on for a pattern
    byte, one field over.
    """
    from h2g.detect import EFFECT_BIT40_MASK, _find_effect_bit40

    class _S:
        def __init__(self, data):
            self.data = data
    assert EFFECT_BIT40_MASK == 0x40
    # a cell tested with two known masks, then BIT/BVC on the same cell
    body = bytes.fromhex("AD341229 04 F0 05 AD3412 29 08 F0 05 2C 3412 50 04".replace(" ", ""))
    assert _find_effect_bit40(_S(b"\x00" + body))
    # ...the BIT must be on *that* cell, not any cell
    other = bytes.fromhex("AD341229 04 F0 05 AD3412 29 08 F0 05 2C 9999 50 04".replace(" ", ""))
    assert not _find_effect_bit40(_S(b"\x00" + other))


def test_the_cell_is_identified_by_the_masks_already_understood():
    """A lone `BIT addr / BVC` proves nothing -- the idiom is everywhere. What
    makes the address the effect byte is that the player also tests it with at
    least two of the bit masks whose meaning is known."""
    from h2g.detect import _effect_cells, _find_effect_bit40

    class _S:
        def __init__(self, data):
            self.data = data
    one = bytes.fromhex("AD341229 04 F0 05 2C 3412 50 04".replace(" ", ""))
    assert not _find_effect_bit40(_S(b"\x00" + one)), "one known mask is not a cell"
    cells = _effect_cells(b"\x00" + one)
    assert cells[0x1234] == {0x04}
    # a non-power-of-two mask is not a bit test and must not register
    assert not _effect_cells(bytes.fromhex("00AD341229070000"))


@needs_corpus
def test_it_reads_across_the_corpus_and_commando_does_not_have_it():
    if not CORPUS.is_dir():
        return
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    seen = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _sid, det = _detect_tables(load_sid(str(path)), lambda *a: None)
        except Exception:                                  # noqa: BLE001
            continue
        seen += det.effect_bit40
    # 41 -> 43 at the mask fix: EFFECT_KNOWN_MASKS gained $20, and Auf
    # Wiedersehen Monty and Sigma Seven both test their effect cell with $20
    # plus one other known bit, so their `BIT cell / BVC` reads of bit $40
    # were below the >=2 gate and invisible. Both have records with $40
    # actually set (Monty 0 and 3, Sigma Seven 2). This pin is what said the
    # population moved -- keep it exact.
    assert seen == 43, seen


@needs_corpus
def test_the_fixed_pitch_resolves_through_the_players_own_note_table():
    """The derivation: Y is the record *offset*, not its number. Read as a
    number it gives 129 on Trans-Atlantic's record 1, which maps to $1A03 and is
    not the pitch the trace shows; read as index x stride the byte is $34 = 52,
    and freqtable[52] is $15EB -- the frequency the original sounds on 226 of
    226 frames.
    """
    if not CORPUS.is_dir():
        return
    from h2g.convert import _detect_tables
    from h2g.goatwriter import WAVE_NOTE_ABS, _fixed_attack_note, _note_freq
    from h2g.sidfile import find_freq_table, load_sid
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a: None)
    assert det.effect_bit40
    # the same array the $08 interpreter reads as a pointer low byte
    assert det.wave_program == sid.to_offset(0x116B)
    assert sid.data[det.wave_program + 1 * det.instr_stride] == 52
    tbl = find_freq_table(sid)
    at = sid.to_offset(tbl.addr) + 2 * 52
    assert (sid.data[at] | (sid.data[at + 1] << 8)) == 0x15EB
    got = _fixed_attack_note(sid, det, 1)
    assert got is not None and got >= WAVE_NOTE_ABS
    assert abs(_note_freq(got - WAVE_NOTE_ABS) - 0x15EB) < 0x0100


@needs_corpus
def test_an_index_past_the_note_table_is_declined_rather_than_guessed():
    """Records 15 and 18 hold 174 and 132, past the 95-entry table -- either
    they take the played-note branch or the byte means something else there.
    Reading past the table would invent a pitch."""
    if not CORPUS.is_dir():
        return
    from h2g.convert import _detect_tables
    from h2g.goatwriter import _fixed_attack_note
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a: None)
    assert _fixed_attack_note(sid, det, 15) is None
    assert _fixed_attack_note(sid, det, 18) is None
    # ...and a record without the bit reads that cell as a pointer, not a note
    assert _fixed_attack_note(sid, det, 2) is None


def test_the_fixed_attack_pitch_is_held_for_the_whole_attack():
    """It must survive every call of the attack, not just the first.

    **This test replaces one that pinned the opposite** (v0.5.459). The old
    `test_the_pitch_is_not_wired_into_the_attack_yet` asserted
    `fixed[1][1] == 0x00` on the continuation call, and `$00` is not "leave the
    pitch alone": `gt2reloc` inverts bit 7 of every non-command right byte
    (greloc.c:1340-1341), so a `.sng` `$00` arrives as packed `$80` and writes
    `adc mt_chnnote / and #$7f` -- the PLAYED note. The fixed pitch therefore
    lasted exactly one call and every call after it undid entry 0. The old
    test's own name and docstring ("nothing passes it") were stale too:
    `goatwriter.py` passes `attack_note=_fixed_attack_note(sid, det, i)` on
    every non-drum record.

    What the player does is in `_two_stage_entries`' own comment, and it was
    sitting there while the line below it did the opposite: One_on_One's GT 2,
    372 onsets with no distribution on any offset, plays the note on frame 0
    and then `$4310` on frames 1, 2 **and** 3 -- one frame past the attack
    waveform. The pitch outlives the stage it belongs to.

    Reaches 7 corpus files, byte-hashed at v0.5.459: ACE_II,
    Auf_Wiedersehen_Monty, One_on_One_Jordan_vs_Bird, Ricochet, Saboteur_II,
    Skate_or_Die_intro, Thundercats.
    """
    from h2g.goatwriter import _two_stage_entries
    plain = _two_stage_entries(0x41, 0x81, 4, 1)
    assert plain[1][0] == 0x00, "frame 0 keeps the played note"

    fixed = _two_stage_entries(0x41, 0x81, 4, 1, attack_note=0xB4)
    left, right = fixed
    assert right[0] == 0xB4, "the attack opens on the fixed pitch"
    # Every call of the attack, not merely its first. `frames=4` at
    # `multiplier=1` is four calls, and the attack waveform holds across all of
    # them -- so the pitch must too.
    # Expressed as the INVARIANT rather than as a slice: the block may open
    # with the record's own `+2` waveform on the note's first frame
    # (`_first_frame_lead`), and whether it does depends on frames and
    # multiplier -- a first version of this test asserted `left[:4]` and broke
    # on `frames=2` for exactly that reason. What must hold everywhere is that
    # every call of the ATTACK carries the fixed pitch.
    atk = [i for i, w in enumerate(left) if w == 0x81]
    assert len(atk) == 4, f"four calls of the attack waveform, got {len(atk)}"
    assert [right[i] for i in atk] == [0xB4] * 4, (
        "the fixed pitch is HELD; $00 here would re-assert the played note "
        "on every call after the first")
    # ...and it ends with the stage it belongs to: the second-stage entry and
    # the terminator hand the note back.
    assert left[4] & 0xFE == 0x40 and right[4] == 0x00
    assert left[5] == 0xFF and right[5] == 0x00

    # The change is to the pitch, NOT to the block's length -- an emitter that
    # grew the block would spend a budget `_wavetable_layout` reserves.
    assert len(left) == len(_two_stage_entries(0x41, 0x81, 4, 1,
                                               attack_note=0x00)[0])


def test_the_held_pitch_scales_with_the_multiplier_like_the_attack_does():
    """A rate read out of the player is per FRAME and the table steps per CALL.
    The attack waveform is already scaled; the pitch beside it must cover the
    same calls or it stops early on every multispeed file.
    """
    from h2g.goatwriter import _two_stage_entries
    for mult in (1, 2, 3):
        left, right = _two_stage_entries(0x41, 0x81, 2, mult, attack_note=0xB4)
        atk = [i for i, w in enumerate(left) if w == 0x81]
        assert len(atk) == 2 * mult, (mult, len(atk))
        assert [right[i] for i in atk] == [0xB4] * (2 * mult), mult


def test_the_drum_can_carry_the_fixed_pitch_on_its_second_frame():
    """The two-pitch burst the trace shows: the drum's own high byte on the
    first noise frame, the $40 note on the second. This is the shape the
    `_sfx_drum_entries` docstring used to call "a fixed $15EB from somewhere
    this reader has not found"."""
    from h2g.goatwriter import (SFX_DRUM_FRAMES, _sfx_drum_entries,
                                _sfx_note_byte)
    # Two frames is **this dialect's** burst -- the one carrying $40's second
    # pitch. The plain shape sounds one frame per period, which is what the
    # counter test implies and what all four $48 files measure (noise at
    # offset 1 on 100% of onsets, Bangkok 226 of 232 reading `noi` at 1 and 7).
    assert SFX_DRUM_FRAMES == 2
    # Without it the plain shape sounds **one** noise frame per period, at the
    # drum's own pitch. It carried two until v0.5.246, for want of knowing
    # where $15EB came from -- and both of them at the wrong offset.
    plain_l, plain_r, plain_loop = _sfx_drum_entries(0x41, 56, 6, 1)
    assert plain_l.count(0x81) == 1
    assert plain_r[plain_loop] == _sfx_note_byte(56)
    # With it the burst moves to the front and carries the two pitches in order.
    left, right, _loop = _sfx_drum_entries(0x41, 56, 6, 1, second_note=0xB4)
    assert right[1] == _sfx_note_byte(56), "the first frame keeps the drum"
    assert right[2] == 0xB4, "the second carries the fixed pitch"
    assert left[1] == left[2], "both frames are the same noise waveform"


def test_the_fixed_pitch_goes_in_a_prologue_the_loop_skips():
    """It fires once per *note* -- its counter runs out -- while the ticks recur
    per *period*. Inside a single looping block it landed on every tick: exact on
    Trans-Atlantic, whose bursts line up, and 281 frames against the original's
    35 on Pandora. A prologue the jump skips gets both -- Pandora's 35 then match
    exactly and its nrun goes 0% -> 100%.
    """
    from h2g.goatwriter import _sfx_drum_entries, _sfx_note_byte
    left, right, loop = _sfx_drum_entries(0x41, 56, 6, 1, second_note=0xB4)
    assert loop > 0, "the prologue must not repeat"
    assert right[1] == _sfx_note_byte(56) and right[2] == 0xB4
    assert 0xB4 not in right[loop:], "the $40 pitch must sit outside the loop"
    assert right[loop] == _sfx_note_byte(56)
    # The plain shape has a prologue too, since v0.5.246: one frame of the
    # played note before the hit, which the loop skips. Its jump returns to the
    # hit at index 1, so the hits recur at 1, 1+period, 1+2*period ... as the
    # counter does.
    assert _sfx_drum_entries(0x41, 56, 6, 1)[2] == 1


def test_the_period_is_kept_across_the_prologue_and_the_loop():
    """Ticks at offsets 1, 2 and 7 on a period of 6, and a loop body exactly one
    period long so the next lands on 13 -- what the trace shows on every note."""
    from h2g.goatwriter import WAVE_MAX_DELAY, _sfx_drum_entries
    left, right, loop = _sfx_drum_entries(0x41, 56, 6, 1, second_note=0xB4)

    def calls(byte):
        return (byte + 1) if 0 < byte <= WAVE_MAX_DELAY else 1
    hits, t = [], 0
    for l in left:
        if 0x10 <= l < 0xE0 and l & 0x80:
            hits.append(t)
        t += calls(l)
    assert hits == [1, 2, 7], hits
    assert t - sum(calls(l) for l in left[:loop]) == 6


def test_the_fixed_pitch_is_gated_on_the_record_not_the_file():
    """`det.effect_bit40` says the player reads the bit; only the record's own
    effect byte says it is set. Checked on the file alone it reached
    Thundercats' drum, whose record does not carry $40 -- 99 frames at a pitch
    the original never sounds there, and melody 77% -> 72%."""
    from h2g.detect import Detection
    from h2g.goatwriter import _fixed_attack_note

    class _S:
        def __init__(self, eff):
            self.data = bytes([0, 0, 0x41, 0x09, 0x99, 0, 0, eff]) * 4

        def to_offset(self, a):
            return 0
    det = Detection(instr_start=0, instr_stride=8, effect_bit40=True,
                    wave_program=0)
    assert _fixed_attack_note(_S(0x80), det, 0) is None, "$40 clear"


# --- the shadow SID -------------------------------------------------------
#
# IK+ carries the bit-$80 drum and `SFX_DRUM_SHAPE` could not see it: the
# player writes the two SID registers to a RAM image and flushes it once a
# frame, so its stores read `8D F2 E5` / `8D F5 E5` where the signature demands
# `8D ?? D4`. Every other byte of the block is the documented Trans-Atlantic
# listing -- same opcodes, same branch offsets, same immediates in order.

@needs_corpus
def test_the_sid_image_base_is_derived_and_is_right_where_it_is_not_needed():
    """$D400 for a player that writes the chip, the shadow's base for one that
    does not.

    **The check that this reads the player rather than matching a coincidence
    is that it is correct on the files that do not need it.** Every corpus file
    carrying the sfx drum directly must come back $D400; only IK+ differs.
    """
    from h2g.detect import detect, sid_image_base
    from h2g.sidfile import load_sid

    direct = ("Bangkok_Knights", "Nineteen", "Thundercats", "Star_Paws",
              "Pandora", "Trans-Atlantic_Balloon_Challenge")
    for stem in direct:
        p = _CORPUS / f"{stem}.sid"
        if not p.exists():
            continue
        assert sid_image_base(load_sid(str(p))) == 0xD400, stem

    ik = _CORPUS / "IK_plus.sid"
    if ik.exists():
        assert sid_image_base(load_sid(str(ik))) == 0xE5E3


@needs_corpus
def test_ik_plus_reads_the_drum_through_its_shadow():
    """voice 2, `$48`, period 6 -- the same shape all thirteen direct files
    read, and the shape IK+'s own trace shows: 242 gate rising edges with the
    noise on offset +1 of every one, run gaps of 6 on 244 of 257.
    """
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    p = _CORPUS / "IK_plus.sid"
    if not p.exists():
        return
    det = detect(load_sid(str(p)), log=lambda *a, **k: None)
    assert det.effect_bit80 == "sfx"
    assert (det.sfx_voice, det.sfx_pitch, det.sfx_period) == (2, 0x48, 6)


@needs_corpus
def test_the_shadow_spelling_is_a_FALLBACK_and_the_direct_files_are_unmoved():
    """The shadow shape wildcards the store target, so it also matches every
    file the direct form already reads, AT THE SAME OFFSET. Ordered wrongly it
    would replace thirteen working readings with the same answers by luck --
    and the day one of them differed, nothing would say so.

    This pins the ordering by pinning its consequence: the direct population
    still reads voice 2 with a period the direct form derived.
    """
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    seen = 0
    for stem, period in (("Bangkok_Knights", 6), ("Nineteen", 6),
                         ("Thundercats", 6), ("Pandora", 8), ("Star_Paws", 8)):
        p = _CORPUS / f"{stem}.sid"
        if not p.exists():
            continue
        det = detect(load_sid(str(p)), log=lambda *a, **k: None)
        assert (det.sfx_voice, det.sfx_period) == (2, period), stem
        seen += 1
    assert seen >= 3, "not enough of the direct population present to check"


def test_the_shadow_pair_alone_cannot_name_the_voice():
    """Why `sid_image_base` has to exist at all, asserted rather than argued.

    The two shadow stores are `base + 1 + 7v` and `base + 4 + 7v`, which are 3
    apart for EVERY voice. So `$E5F2`/`$E5F5` is voice 2 of a SID based at
    `$E5E3` and voice 0 of one based at `$E5F1`, and the pair chooses neither.
    A reading that guessed the base would be right by luck on this file and
    silently wrong on the next one.
    """
    lo, hi = 0xE5F2, 0xE5F5
    assert hi - lo == 3
    for base, voice in ((0xE5E3, 2), (0xE5EA, 1), (0xE5F1, 0)):
        assert (lo - base - 1) // 7 == voice
        assert (hi - base - 4) // 7 == voice
