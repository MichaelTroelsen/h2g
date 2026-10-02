"""The triangle pulse engine's zero-page per-voice dialect (PULSE_TRI_ZP_SHAPE).

`PULSE_TRI_SHAPE` matches only the absolute-address player (Commando and 23
more). Samantha Fox ($7231) and Spellbound ($E275) carry the same triangle --
CMP #$0E / CMP #$08 turnarounds, rate at record +6, behind an effect-bit-$08
test -- with three differences, each pinned here:

* the accumulator is a per-voice zero-page pair (`ADC $DC,X` / `LDA $E0,X`)
  RESEEDED from record +0/+1 at every note fetch, which is what the match is
  anchored on, since its own ADC operand no longer names the record;
* the rate byte splits $F0 step / $0F delay, not $E0 / $1F;
* the spelling is consulted only where the absolute one matched nothing.
"""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import (PULSE_TRI_SHAPE, PULSE_TRI_ZP_SHAPE,  # noqa: E402
                        Detection, _find_pulse_tri, _find_pulse_tri_zp,
                        detect)
from h2g.goatwriter import (_phase_sweep_params, _pulse_program,  # noqa: E402
                            pulse_phase_sims)
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import SidFile, load_sid                    # noqa: E402

SAMANTHA = "Samantha_Fox_Strip_Poker.sid"
SPELLBOUND = "Spellbound.sid"


def _quiet(*_a, **_k):
    pass


def _sam():
    sid = load_sid(str(CORPUS / SAMANTHA))
    return sid, detect(sid, _quiet)


def _patched(sid: SidFile, at: int, new: bytes) -> SidFile:
    data = bytearray(sid.data)
    data[at:at + len(new)] = new
    return dataclasses.replace(sid, data=bytes(data))


# --- detection, on the corpus -----------------------------------------------

@needs_corpus
def test_the_zero_page_dialect_is_found_on_exactly_its_two_files():
    """Every corpus file's detection, so a looser signature that started
    matching a third player -- or the absolute dialect's files -- fails here
    by name rather than moving a byte-hash nobody re-reads."""
    zp, absolute = set(), set()
    for path in sorted(CORPUS.glob("*.sid")):
        det = detect(load_sid(str(path)), _quiet)
        if det.pulse_tri_hi < 0:
            continue
        if det.pulse_tri_per_voice:
            zp.add(path.name)
            assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0E), path.name
            assert (det.pulse_tri_step_mask,
                    det.pulse_tri_delay_mask) == (0xF0, 0x0F), path.name
            assert det.pulse_tri_gated, path.name
        else:
            absolute.add(path.name)
            assert (det.pulse_tri_step_mask,
                    det.pulse_tri_delay_mask) == (0xE0, 0x1F), path.name
    assert zp == {SAMANTHA, SPELLBOUND}
    assert absolute, "the absolute dialect's files should still be detected"


@needs_corpus
def test_the_fallback_is_consulted_only_where_the_absolute_shape_matched_nothing():
    """A rescue must never disturb a file the primary path reads. No corpus
    file carries both spellings, and the two zero-page files carry no
    absolute one at all -- so the ordering in `detect` is the only thing
    deciding, and it is exercised by both populations."""
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, _quiet)
        if search_file(sid.data, PULSE_TRI_SHAPE) >= 0 and \
                _find_pulse_tri(sid, det)[1] >= 0:
            assert not det.pulse_tri_per_voice, path.name
    for name in (SAMANTHA, SPELLBOUND):
        sid = load_sid(str(CORPUS / name))
        assert search_file(sid.data, PULSE_TRI_SHAPE) < 0, name
        assert search_file(sid.data, PULSE_TRI_ZP_SHAPE) >= 0, name


@needs_corpus
def test_the_match_is_anchored_on_the_note_fetch_seeding_from_record_zero():
    """Samantha Fox $7110: `LDA $7407,X / STA $D402,Y / PHA / LDA $7408,X
    ...`, $7407 being instr_start. Point the seed's operand anywhere else and
    the match must be refused: the ADC operand here is the accumulator, so
    this is the only thing tying the routine to the instrument table."""
    sid, det = _sam()
    assert _find_pulse_tri_zp(sid, det) is not None
    seed = sid.data.find(bytes([0xBD, 0x07, 0x74, 0x99, 0x02, 0xD4]))
    assert seed >= 0 and sid.to_offset(0x7407) == det.instr_start
    assert _find_pulse_tri_zp(_patched(sid, seed + 1, b"\x17"), det) is None


@needs_corpus
def test_the_rate_cell_must_be_filled_from_record_six():
    """$717A `LDA $740D,Y / STA $BD`: the routine's rate cell is record +6.
    Re-point the fill at +5 and the match must be refused."""
    sid, det = _sam()
    fill = sid.data.find(bytes([0xB9, 0x0D, 0x74, 0x85, 0xBD]))
    assert fill >= 0
    assert _find_pulse_tri_zp(_patched(sid, fill + 1, b"\x0C"), det) is None


@needs_corpus
def test_the_masks_are_read_off_the_routine_not_assumed_from_the_dialect():
    """Rewrite Samantha Fox's `AND #$F0` / `AND #$0F` to the absolute
    dialect's $E0 / $1F and the finder must report $E0 / $1F; make the two
    overlap and it must refuse."""
    sid, det = _sam()
    off = search_file(sid.data, PULSE_TRI_ZP_SHAPE)
    head = off - 2 - 8                      # zero-page `LDA rate`, then head
    assert sid.data[off:off + 2] == b"\x29\xF0"
    assert sid.data[head:head + 2] == b"\x29\x0F"
    swapped = _patched(_patched(sid, off + 1, b"\xE0"), head + 1, b"\x1F")
    assert _find_pulse_tri_zp(swapped, det)[3:] == (0xE0, 0x1F)
    overlap = _patched(sid, head + 1, b"\x1F")
    assert _find_pulse_tri_zp(overlap, det) is None


# --- the emitter, on a synthetic record -------------------------------------

INSTR_AT = 0x100
STRIDE = 8


def _one_record(rate: int, width_lo=0x00, width_hi=0x08) -> SidFile:
    data = bytearray(0x200)
    data[INSTR_AT:INSTR_AT + STRIDE] = bytes(
        [width_lo, width_hi, 0x41, 0, 0, 0, rate, 0x00])
    return SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                   released="r", load_addr=0x1000, subtunes=1)


def _tri_det(zp: bool) -> Detection:
    det = Detection(instr_start=INSTR_AT, instr_used=1, instr_stride=STRIDE,
                    track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                    pattern_used=0, read_track_version=0)
    det.pulse_tri_lo, det.pulse_tri_hi, det.pulse_tri_gated = 8, 0x0E, True
    if zp:
        det.pulse_tri_step_mask, det.pulse_tri_delay_mask = 0xF0, 0x0F
        det.pulse_tri_per_voice = True
    return det


def test_rate_34_steps_30_every_five_frames_in_the_zero_page_dialect():
    """$34 is a step of $30 every 5 frames under $F0/$0F (speed 48/5 -> 10)
    and a step of $20 every 21 under $E0/$1F (32/21 -> 2). The ascent from
    the record's $800 to $E00 is the second entry, so its speed byte is the
    one the mask decides."""
    sid = _one_record(0x34)
    zp_entries, _ = _pulse_program(sid, _tri_det(True), 0, True, 1)
    abs_entries, _ = _pulse_program(sid, _tri_det(False), 0, True, 1)
    assert zp_entries[0] == (0x88, 0x00)
    assert zp_entries[1][1] == 10
    assert abs_entries[1][1] == 2


def test_a_rate_whose_step_only_the_zero_page_mask_sees_sweeps():
    """$10 is a step of $10 every frame under $F0, and no step at all under
    $E0 -- Samantha Fox's records 11, 13 and 14 carry exactly this rate."""
    sid = _one_record(0x10)
    entries, loop = _pulse_program(sid, _tri_det(True), 0, True, 1)
    assert loop is not None and entries[1][1] == 0x10
    static, loop = _pulse_program(sid, _tri_det(False), 0, True, 1)
    assert loop is None and static == [(0x88, 0x00), (0xFF, 0x00)]


def test_the_phase_table_speed_agrees_with_the_static_program():
    """`_phase_sweep_params` promises the same speed `_pulse_tri_program`
    emits; under the zero-page masks it must keep that promise."""
    sid = _one_record(0x34)
    det = _tri_det(True)
    params = _phase_sweep_params(sid, det, 0, 1)
    entries, _ = _pulse_program(sid, det, 0, True, 1)
    assert params[1] == entries[1][1] == 10


def test_a_reseeded_accumulator_gets_no_phase_walk():
    """The walk plans a free-running accumulator's phase. The zero-page
    dialect reseeds at every note, so it has none to plan."""
    sid = _one_record(0x34)
    assert pulse_phase_sims(sid, _tri_det(False)) != {}
    assert pulse_phase_sims(sid, _tri_det(True)) == {}
