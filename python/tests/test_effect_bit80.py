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


def test_the_reading_is_landed_and_not_yet_written():
    """Same discipline as the two-stage attack before v0.5.179: resolve what
    the block means from the 6502, then decide separately, by measurement,
    whether the target format should carry it. Emitting it needs a wavetable
    entry with an *absolute* note -- $38xx is about G-5 -- and that has not
    been measured yet."""
    import h2g.goatwriter as gw
    src = pathlib.Path(gw.__file__).read_text(encoding="utf-8")
    assert "sfx_pitch" not in src
