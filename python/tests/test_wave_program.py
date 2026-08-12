"""The byte-code wave program: 29 of 95 files, and nothing emits it.

A listener reported Trans-Atlantic's snare missing. It is GT 3, and its program
begins `81 30` -- the interpreter writes an opcode >= $80 straight to $D404 and
the next byte to $D401, so that is literally "noise at $30xx", which is the 43
onsets the trace shows on voice 2.

Two of these files were already known (ACE II and Auf Wiedersehen Monty, as
`effect_bit80 == "program"`). The other 27 were not, which makes this the most
widespread instrument mechanism the project has found unemitted -- and the first
census of it was wrong by a factor of 29, because the signature was written from
one file's exact operands rather than from the shape.

The gating bit reads too, once anchored on the pointer load rather than scanned
for loosely: $01 in 22 files, $08 in three, $20 in one, $80 in two (by sign,
`BPL`), and one shape unrecognised. In 18 of the 29 the cell the branch tests is
also independently known to be the effect byte, which is what makes this the
instrument's own flag rather than some other state; the other 11 are files whose
effect cell detection cannot locate at all. In these players effect bit $01 selects a wave program where in Warhawk's
dialect it means a drum -- and no file does both, so nothing `--effects` reads
collides with it.
"""
import pathlib

from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402

from h2g.convert import _detect_tables
from h2g.detect import (WAVE_PROGRAM_HOLD, decode_wave_program,
                        find_wave_program)
from h2g.sidfile import load_sid

CORPUS = _CORPUS


def _prog(name, instr):
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                              lambda *a, **k: None)
    base = det.wave_program
    off = base + instr * det.instr_stride
    at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
    return decode_wave_program(sid.data, at)


# --- the decoder, on synthetic programs ------------------------------------

def test_an_opcode_above_the_hold_is_a_waveform_and_an_absolute_pitch():
    """Both bytes go straight to the chip -- $D404 and $D401 -- so the pitch is
    the player's own and has nothing to do with the note being played."""
    assert decode_wave_program(bytes([0x81, 0x30, 0x85]), 0) == [
        ("set", 0x81, 0x30), ("hold", 0, 0)]


def test_an_opcode_below_the_hold_is_a_waveform_and_a_16_bit_step_down():
    got = decode_wave_program(bytes([0x10, 0x00, 0x02, 0x85]), 0)
    assert got == [("slide", 0x10, 0x0200), ("hold", 0, 0)]


def test_a_step_is_subtracted_so_a_large_one_slides_upward():
    """`SEC / LDA lo,X / SBC (ptr),Y` -- $FC00 taken away is $0400 added. The
    decoder reports the operand as written; reading it as unsigned "down" only
    would invert three of Trans-Atlantic's GT 13 steps."""
    got = decode_wave_program(bytes([0x50, 0x00, 0xFC, 0x85]), 0)
    assert got[0] == ("slide", 0x50, 0xFC00)
    assert (0x10000 - got[0][2]) == 0x0400


def test_the_hold_ends_the_program():
    assert WAVE_PROGRAM_HOLD == 0x85
    got = decode_wave_program(bytes([0x85, 0x81, 0x30]), 0)
    assert got == [("hold", 0, 0)]


def test_a_truncated_program_is_cut_rather_than_read_past_the_end():
    """Programs are not length-prefixed, so the only alternative to stopping is
    trusting a byte count nothing states."""
    assert decode_wave_program(bytes([0x81]), 0) == []
    assert decode_wave_program(bytes([0x10, 0x00]), 0) == []


def test_the_step_limit_is_honoured():
    assert len(decode_wave_program(bytes([0x81, 0x30] * 50), 0, limit=6)) == 6


# --- against the real players ----------------------------------------------

@needs_corpus
def test_the_interpreter_is_found_across_the_corpus():
    """29 files, and the first census said one. The signature that found one was
    written from Trans-Atlantic's exact operands; this one is written from the
    fetch-and-hold shape, which is what the players actually share.

    All 29 yield a pointer array. Only 27 also yield a plausible gating bit,
    which is why the gate is not part of the reading at all -- see the comment
    above WAVE_PROGRAM_FETCH."""
    sids = sorted(CORPUS.glob("*.sid"))
    if not sids:
        return
    found = 0
    for path in sids:
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        if find_wave_program(sid)[0] >= 0:
            found += 1
    assert found == 29, f"{found} -- the interpreter's reach changed"


@needs_corpus
def test_the_missing_snare_decodes_to_noise_at_a_fixed_pitch():
    if not CORPUS.is_dir():
        return
    steps = _prog("Trans-Atlantic_Balloon_Challenge", 2)
    assert steps[0] == ("set", 0x81, 0x30), steps[:3]
    # ...then two slides under a released waveform, then more noise pitches
    assert [s[0] for s in steps[:6]] == [
        "set", "slide", "slide", "set", "set", "set"], steps[:6]


@needs_corpus
def test_every_located_program_decodes_to_something():
    """A pointer array that resolves but decodes to nothing would mean the
    array was misidentified."""
    if not CORPUS.is_dir():
        return
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.wave_program < 0 or det.instr_used <= 0:
            continue
        nonempty = 0
        for i in range(det.instr_used):
            off = det.wave_program + i * det.instr_stride
            if off + 1 >= len(sid.data):
                break
            at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
            if at >= 0 and decode_wave_program(sid.data, at, 4):
                nonempty += 1
        assert nonempty, path.name
        checked += 1
    assert checked >= 20, checked


@needs_corpus
def test_the_gate_reads_and_never_guesses():
    """Anchored on the pointer load, not scanned for. The first attempt swept 40
    bytes back from the fetch and returned $01 for 21 files, which looked like
    the drum bit and was dismissed as a mismatch -- it was under-anchored, and
    $01 really is the gate in 13 of them."""
    if not CORPUS.is_dir():
        return
    from collections import Counter
    seen = Counter()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        at, gate = find_wave_program(sid)
        if at >= 0:
            seen[gate] += 1
    assert sum(seen.values()) == 29
    assert seen[0x01] == 22, dict(seen)
    assert seen[0x08] == 3, dict(seen)
    assert seen[0x20] == 1, dict(seen)
    assert seen[0x80] == 2, dict(seen)
    # ...and one shape this walk does not recognise, reported as unread
    assert seen[0] == 1, dict(seen)


@needs_corpus
def test_the_gate_never_collides_with_a_bit_effects_already_reads():
    """Bit $01 is a drum in Warhawk's dialect and a wave program here. If one
    file did both, `--effects` would fabricate a drum where the player runs a
    program."""
    if not CORPUS.is_dir():
        return
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.wave_program < 0 or not det.wave_program_gate:
            continue
        if det.wave_program_gate == 0x01:
            assert not det.effect_drum, path.name
        if det.wave_program_gate == 0x04:
            assert not det.effect_arp, path.name


# --- the encoding ----------------------------------------------------------
#
# This test used to assert that goatwriter mentioned none of it, because the
# gating bit was unread. v0.5.186 read the gate and v0.5.187 emits the program.

def test_a_set_opcode_becomes_one_entry_at_an_absolute_note():
    """The player writes $D401 directly and a wavetable names notes, so the
    pitch quantises to a semitone -- inaudible for the noise these opcodes
    mostly carry."""
    from h2g.goatwriter import _wave_byte, _sfx_note_byte
    assert _wave_byte(0x81) == 0x81
    assert 0x81 <= _sfx_note_byte(0x30) <= 0xDF


def test_a_waveform_below_ten_uses_the_inaudible_range():
    """$01-$0F are *delays* in a wavetable. $E0-$EF sets the waveform to $00-$0F
    instead (readme.txt:3.4.1, gplay.c:527), which is the only way to express
    `slide $01` -- and GT 11's program is three of them in a row."""
    from h2g.goatwriter import WAVE_SILENT_BASE, _wave_byte
    assert _wave_byte(0x01) == WAVE_SILENT_BASE | 0x01
    assert _wave_byte(0x00) == WAVE_SILENT_BASE
    assert _wave_byte(0x10) == 0x10, "a real waveform is written literally"


def test_a_speed_entry_is_reused_rather_than_duplicated():
    from h2g.goatwriter import _speed_index
    table = []
    assert _speed_index(table, (0x02, 0x00)) == 1
    assert _speed_index(table, (0x03, 0xC0)) == 2
    assert _speed_index(table, (0x02, 0x00)) == 1
    assert len(table) == 2


@needs_corpus
def test_the_snare_is_emitted_and_lands_on_noise():
    """GT 3's program opens `81 30`, and the emitted block opens on a noise
    waveform with an absolute note near $30xx. Before this, all 43 of its notes
    sounded a triangle."""
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _note_freq, _wavetable_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    speed = []
    left, right = _wavetable_entries(sid, det, 2, True, "gts5", speed, 1,
                                     start=1, budget=30, wave_program=True)
    # Entry 0 is the record's own `+2` -- the note's first frame, which the
    # player writes before it reaches the interpreter at all (v0.5.217, see
    # `_first_frame_entry`). The program itself starts at entry 1.
    assert left[0] == sid.data[det.instr_start + 2 * det.instr_stride + 2]
    assert left[1] == 0x81, "the snare must open on noise"
    assert abs(_note_freq(right[1] - 0x80) - 0x3000) < 0x0300
    assert left[-1] == 0xFF
    # v0.5.203: a slide is one entry, not a waveform plus a portamento command.
    # The two-entry form made the program 2 frames longer than the player's and
    # truncated the closing noise burst from 8 frames to 6 -- see
    # test_a_slide_opcode_costs_one_entry_so_the_program_keeps_its_length. The
    # frame count is what a percussion transient is; 2 frames of pitch movement
    # under a released waveform is not.
    assert 0xF2 not in left and 0xF1 not in left
    assert not speed, "a slide no longer allocates a speed-table entry"


def test_it_is_off_by_default_and_selected_per_song():
    from h2g.convert import convert
    import presets
    assert len(convert(str(pathlib.Path(__file__).resolve().parents[2]
                           / "Commando.sid"), log=lambda m: None)) == 15193
    assert "wave_program" in presets.EXCLUDED_FROM_ALWAYS
    assert "wave_program" in presets.FIDELITY_TOGGLES


def test_a_multispeed_file_is_left_alone():
    """The player advances one opcode per frame and a wavetable advances one
    entry per *call*, so at -S2 the whole program would run twice as fast.
    Slowing it needs a delay per opcode, which roughly doubles a budget that
    already reaches 131 entries on Kings of the Beach."""
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wave_program_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    assert _wave_program_entries(sid, det, 2, [], "gts5", 1, 30) is not None
    assert _wave_program_entries(sid, det, 2, [], "gts5", 2, 30) is None
    assert _wave_program_entries(sid, det, 2, [], "gts2", 1, 30) is None


# --- v0.5.203: the overshoot ------------------------------------------------

@needs_corpus
def test_a_slide_opcode_costs_one_entry_so_the_program_keeps_its_length():
    """The player runs one opcode per frame. A portamento needs a command entry
    of its own and a wavetable spends a call on it, so a two-entry slide made
    the program longer than the player's and ran everything after it late: on
    the snare, the closing noise burst came out 6 frames instead of 8.
    """
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wavetable_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    speed: list = []
    left, _right = _wavetable_entries(sid, det, 2, True, "gts5", speed, 1,
                                      start=1, budget=30, wave_program=True)
    steps = _prog("Trans-Atlantic_Balloon_Challenge", 2)
    opcodes = len([s for s in steps if s[0] != "hold"])
    # one entry per opcode, plus the note's own first frame ahead of the
    # program (v0.5.217), the waveform restore, and the stop
    assert len(left) == opcodes + 3, (len(left), opcodes)
    assert not speed, "a slide no longer allocates a speed-table entry"


@needs_corpus
def test_the_record_waveform_is_restored_before_the_program_stops():
    """The player's note-end routine writes the *stored* waveform with the gate
    cleared (`LDA $54F8,X / AND #$FE`), so a program ending on noise stops
    sounding noise. Holding it instead let Trans-Atlantic's snare run 30, 54 and
    78 frames where the original's runs are 8.
    """
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wavetable_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    left, _r = _wavetable_entries(sid, det, 2, True, "gts5", [], 1,
                                  start=1, budget=30, wave_program=True)
    rec = det.instr_start + 2 * det.instr_stride
    assert left[-1] == 0xFF
    assert left[-2] == sid.data[rec + 2] & 0xFE, [hex(x) for x in left[-3:]]
    assert not left[-2] & 0x80, "the restore must not itself be noise"
    assert left[-3] & 0x80, "...and it must follow the program's noise"


def test_the_listening_confirmation_is_recorded_with_its_reason():
    """`fidelity_better` scores the fixed program as worse, structurally: its
    `finds_noise` test requires the reference to have no audible noise, and this
    file has plenty from another instrument -- a per-file test for a per-
    instrument defect. The mirror of FIDELITY_VETOED records the listening
    verdict instead of hand-editing generated presets.json."""
    import presets
    confirmed = presets.FIDELITY_CONFIRMED[
        "Trans-Atlantic_Balloon_Challenge.sid"]
    assert "wave_program" in confirmed
    # v0.5.208: the sfx_drum veto is retired -- the listener reported no audible
    # difference once the snare existed and the burst had its two pitches, and
    # the oscillation scorer selects the setting on its own.
    #
    # v0.5.209: the corpus --fidelity run confirms sfx_drum and pitch_seq are
    # now selected independently, so both are trimmed from here -- only
    # wave_program still needs the hand-recorded measurement.
    assert "sfx_drum" not in confirmed
    assert "pitch_seq" not in confirmed
    assert confirmed == {"wave_program"}
    # FIDELITY_VETOED is no longer required to be empty: the same run found
    # Dragons_Lair_Part_II's subtune-correspondence bug (its init routine
    # remaps subtune 0 to our subtune 9) had invalidated its pitch_seq
    # measurement, an unrelated veto reason from the retired listening one.
    assert presets.FIDELITY_VETOED == {
        "Dragons_Lair_Part_II.sid": {"pitch_seq"}}
