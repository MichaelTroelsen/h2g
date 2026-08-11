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
    assert len(found) == 7, sorted(found)
    # Every one of them is voice 3, and the pitch is a constant of the player
    # rather than the note -- which is the whole point: the SID's noise is an
    # LFSR clocked by the frequency, so noise at the note's own low pitch
    # writes the register and makes no sound.
    assert {v for _, v, _ in found.values()} == {2}
    assert found["Trans-Atlantic_Balloon_Challenge"][0] == 0x38
    assert {p for p, _, _ in found.values()} == {0x38, 0x48}
    assert {q for _, _, q in found.values()} <= {6, 8}


@needs_corpus
def test_the_two_files_without_the_block_report_no_pitch():
    """IK+ patches its own code instead of writing $D40F/$D412, and Ricochet's
    arms are empty in the rip. Neither may be handed a made-up pitch."""
    if not CORPUS.is_dir():
        return
    for name in ("IK_plus", "Ricochet"):
        _, det = _detect(name)
        assert det.effect_bit80 == "sfx"
        assert (det.sfx_pitch, det.sfx_voice, det.sfx_period) == (-1, -1, -1)


def test_the_hit_opens_on_the_note_and_not_on_the_noise():
    """The player's counter is per voice and free-running, so a hit falls
    wherever it falls relative to a note start; a wavetable always begins at
    the note. Opening on the noise puts the drum's pitch on the note's own
    first frame, where the played note never sounds -- measured, it took
    Trans-Atlantic's melody from 94.7% to 50.4%.
    """
    from h2g.goatwriter import _sfx_drum_entries, _sfx_note_byte
    left, right = _sfx_drum_entries(0x41, 0x38, 6)
    assert left == [0x41, 0x02, 0x81, 0x81]
    assert right == [0x00, 0x80, _sfx_note_byte(0x38), _sfx_note_byte(0x38)]
    assert right[0] == 0x00, "relative 0 -- the played note, not an absolute"


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


def test_an_instrument_with_no_waveform_gets_no_drum():
    """`(wave & 0xFE) | 0x01` is `$01` for a record whose +2 is $00, and $01-$0F
    are *delays* in a wavetable, not waveforms (readme.txt:3.4.1). Emitted, the
    instrument set no waveform at all -- it inherited noise from whatever played
    before, and its delay entry applied a relative note, so Bangkok Knights' GT 9
    sounded 40 frames at `freqtbl[0]` = $0117 where the drum belongs at $49E5.
    Half that file's noise frames were at the wrong pitch and the audibility
    guard read the median as inaudible."""
    from h2g.goatwriter import _sfx_drum_entries
    assert _sfx_drum_entries(0x00, 0x48, 6) is None
    assert _sfx_drum_entries(0x01, 0x48, 6) is None, "gate alone is not a waveform"
    left, _ = _sfx_drum_entries(0x41, 0x48, 6)
    assert left[0] > 0x0F, "the first entry must be a waveform, never a delay"


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
    assert seen == 41, seen


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


def test_the_pitch_is_not_wired_into_the_attack_yet():
    """It belongs on the attack's third frame; frame 0 keeps the played note and
    frame 1 is bit $80's drum. Applied to frame 0 -- the only place a two-stage
    block could put it today -- melody falls 85% to 39%. The emitter accepts the
    note so the shape is testable; nothing passes it."""
    from h2g.goatwriter import _two_stage_entries
    plain = _two_stage_entries(0x41, 0x81, 4, 1)
    assert plain[1][0] == 0x00, "frame 0 keeps the played note"
    fixed = _two_stage_entries(0x41, 0x81, 4, 1, attack_note=0xB4)
    assert fixed[1][0] == 0xB4
    # ...and the held frames spell themselves out rather than using a delay,
    # which would keep the fixed pitch for the whole window
    assert fixed[1][1] == 0x00 and fixed[0][1] == 0x81


def test_the_drum_can_carry_the_fixed_pitch_on_its_second_frame():
    """The two-pitch burst the trace shows: the drum's own high byte on the
    first noise frame, the $40 note on the second. This is the shape the
    `_sfx_drum_entries` docstring used to call "a fixed $15EB from somewhere
    this reader has not found"."""
    from h2g.goatwriter import (SFX_DRUM_FRAMES, _sfx_drum_entries,
                                _sfx_note_byte)
    assert SFX_DRUM_FRAMES == 2
    plain = _sfx_drum_entries(0x41, 56, 6, 1)
    assert plain[1][-2] == plain[1][-1] == _sfx_note_byte(56)
    two = _sfx_drum_entries(0x41, 56, 6, 1, second_note=0xB4)
    assert two[1][-2] == _sfx_note_byte(56), "the first frame keeps the drum"
    assert two[1][-1] == 0xB4, "the second carries the fixed pitch"
    assert two[0] == plain[0], "waveforms unchanged"


def test_the_fixed_pitch_is_not_passed_to_the_drum_block():
    """It fires once per *note* -- its counter runs out -- while the block's
    entries loop once per *period*. Passed here it lands on every tick: exact on
    Trans-Atlantic, whose bursts line up, and 281 frames against the original's
    35 on Pandora, which ships with --sfx-drum on. Emitting it needs a
    non-looping prologue ahead of the looping body, which one jump cannot say.
    """
    import inspect

    from h2g import goatwriter
    src = inspect.getsource(goatwriter._wavetable_entries)
    # Checked on the call itself, not on the source text: the comment beside
    # it names the argument it deliberately omits.
    src = inspect.getsource(goatwriter._wavetable_entries)
    calls = [l.strip() for l in src.splitlines()
             if "_sfx_drum_entries(" in l and not l.lstrip().startswith("#")]
    assert calls == [
        "hit = _sfx_drum_entries(wave, det.sfx_pitch, det.sfx_period, "
        "multiplier)"], calls
