"""A flagged note on a record with NO attack still skips the pulse reseed:
the pulse-only free-note variant (`goatwriter.note_passes.free_note_variants`'
`pulse_only`).

The legato-marker players' bit-7 `BMI` (Lightforce $F1FA, the shape
`free_note_skips_two_stage` reads) jumps over the whole note-start block --
pulse write and accumulator reseed, envelope write, sweep-direction clear and
the frame-counter reload -- whatever the record holds. The two-stage variant
covered only records with an attack in the wavetable; the rest kept the full
start and reset their sweep on every flagged note. Traced on the originals
against a copy with the BMI NOPped (C:/t/free-note-pulse-only-variant/
trace_orig.py, 400 s, every subtune): the PW differs on records with no
counter-driven attack in all eleven files the old variant declined (Lightforce
32 divergence onsets, Delta 158, Saboteur_II 135, Pandora 3, Knucklebusters
452, Flash_Gordon 80, ...). Lightforce sub 0 at 233.8 s, voice 1, instr 07:
the original sweeps 370 -> 380 -> 390 through the note, the NOPped copy and
the old conversion reset to 1C0/1C8, the variant carries on 380 -> 390.
HISTORICAL figures (2026-10-07, 6e467ff plus the cycle-4 merge; the byte
movers re-taken on the cycle-5 merge).
"""
import dataclasses
import json
import pathlib

import pytest

from h2g.convert import convert
from h2g.detect import detect
from h2g.goatwriter import constants as C
from h2g.goatwriter import note_passes as NP
from h2g.goatwriter.primitives import _wave_byte
from h2g.sidfile import load_sid
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60


def _load(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, lambda *a, **k: None)


def _with(sid, at, value):
    data = bytearray(sid.data)
    data[at] = value
    return dataclasses.replace(sid, data=bytes(data))


def _preset_opts(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, name)


def _convert(name, pulse_only=True):
    real = NP.free_note_attack_bits
    if not pulse_only:
        NP.free_note_attack_bits = lambda sid, det: None
    try:
        lines = []
        sng = convert(str(CORPUS / name), log=lines.append, **_preset_opts(name))
    finally:
        NP.free_note_attack_bits = real
    return parse_sng(sng), [l for l in lines if l.startswith("Free note")]


# --- the walk ----------------------------------------------------------------

def test_a_pulse_only_row_is_taken_only_after_its_own_instrument():
    pat = [NOTE, 5, 0, 0,
           NOTE + 1, 0, 0, 0,        # flagged, the channel holds 5: taken
           NOTE + 2, 6, 0, 0,
           NOTE + 3, 5, 0, 0,        # flagged, the channel held 6: declined
           NOTE + 4, 0, 0, 0]
    lines = []
    out, variants, declined = NP.free_note_variants(
        [pat], {(0, 1), (0, 3)}, None, {5: 12}, 30, log=lines.append,
        pulse_only={5})
    assert variants == [(5, 30)]
    assert out[0][4:8] == [NOTE + 1, 30, 0, 0]
    assert out[0][8:12] == pat[8:12]
    assert declined == {(0, 3)} and out[0][12:16] == pat[12:16]
    assert lines == ["Free note (bit 7).......: 1 flagged note row(s) on 1 "
                     "variant(s) with no attack stage and no pulse reset (1 "
                     "pulse-only: the record has no attack), 1 kept the full "
                     "start (1 follows another instrument)"]


def test_a_pulse_only_row_after_an_unsettled_entry_says_so():
    """The pattern is entered with nothing known (no orderlists): the row
    names its own instrument, but what the channel held before is unknown,
    so whether the running width is this record's cannot be told."""
    pat = [NOTE, 5, 0, 0, NOTE + 1, 0, 0, 0]
    _out, variants, declined = NP.free_note_variants(
        [pat], {(0, 0)}, None, {5: 12}, 30, pulse_only={5})
    lines = []
    NP.free_note_variants([pat], {(0, 0)}, None, {5: 12}, 30,
                          log=lines.append, pulse_only={5})
    assert not variants and declined == {(0, 0)}
    assert lines[0].endswith("(1 follows an unsettled instrument)")


def test_a_two_stage_variant_still_takes_a_row_after_another_instrument():
    pat = [NOTE, 6, 0, 0, NOTE + 1, 5, 0, 0, NOTE + 2, 0, 0, 0]
    out, variants, declined = NP.free_note_variants(
        [pat], {(0, 1)}, None, {5: 40}, 30)
    assert variants == [(5, 30)] and not declined


def test_a_record_with_no_variant_declines_with_its_own_reason():
    pat = [NOTE, 7, 0, 0, NOTE + 1, 0, 0, 0, NOTE + 2, 0, 0, 0]
    lines = []
    NP.free_note_variants([pat], {(0, 1)}, None, {}, 30, log=lines.append,
                          no_variant={7: "attack the wavetable cannot skip"})
    assert lines[0].endswith("(1 attack the wavetable cannot skip)")


def _two_entry(no_variant):
    """Pattern 1 entered from pattern 0 (instrument 7) and pattern 2
    (instrument 8); its flagged row 0 names nothing."""
    pats = [[NOTE, 7, 0, 0, 0xFF, 0, 0, 0],
            [NOTE + 1, 0, 0, 0, NOTE + 2, 0, 0, 0],
            [NOTE, 8, 0, 0, 0xFF, 0, 0, 0]]
    tracks = [[0, 1, 2, 1, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    lines = []
    NP.free_note_variants(pats, {(1, 0)}, tracks, {}, 30, log=lines.append,
                          no_variant=no_variant)
    return lines[0]


def test_two_entry_instruments_with_one_reason_decline_for_it():
    same = {7: "full start already keeps the pulse",
            8: "full start already keeps the pulse"}
    assert _two_entry(same).endswith("(1 full start already keeps the pulse)")


def test_two_entry_instruments_with_two_reasons_say_two_instruments():
    mixed = {7: "full start already keeps the pulse",
             8: "attack the wavetable cannot skip"}
    assert _two_entry(mixed).endswith("(1 entered with two instruments)")


# --- the player --------------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("name, bits", [
    ("Lightforce.sid", 0x44),    # $F414 AND #$04 / $F4A1 BIT / BVC
    ("Saboteur_II.sid", 0x44),
    ("Flash_Gordon.sid", 0x04),  # the AND guard alone
    ("Commando.sid", None),      # no legato marker at all
])
def test_the_counter_guards_are_read_off_the_player(name, bits):
    sid, det = _load(name)
    assert NP.free_note_attack_bits(sid, det) == bits


def _lightforce_and_guard():
    sid, det = _load("Lightforce.sid")
    at = sid.data.find(bytes([0xAD, 0xF2, 0xF5, 0x29, 0x04, 0xF0]))
    assert at > 0 and sid.to_address(at) == 0xF411   # LDA $F5F2 / AND #$04 / BEQ
    return sid, det, at


@needs_corpus
def test_an_unguarded_counter_read_is_not_read():
    sid, det, at = _lightforce_and_guard()
    data = bytearray(sid.data)
    # `BIT $F5F2` on the effect cell, but no branch after it: the counter
    # read at $F418 then runs for every record.
    data[at:at + 7] = bytes([0xEA, 0xEA, 0x2C, 0xF2, 0xF5, 0xEA, 0xEA])
    assert NP.free_note_attack_bits(
        dataclasses.replace(sid, data=bytes(data)), det) is None


@needs_corpus
def test_a_counter_read_behind_another_bit_turns_the_variant_off():
    """`AND #$08` instead of `#$04`: the counter would drive a stage
    `free_note_record_has_attack` does not know, so no record can be called
    attack-free."""
    sid, det, at = _lightforce_and_guard()
    assert NP.free_note_attack_bits(_with(sid, at + 4, 0x08), det) is None


@needs_corpus
@pytest.mark.parametrize("record, attack", [
    (7, False),   # fx $20, frames 2: the record the flagged notes play
    (6, False),   # fx $40 alone: a fixed attack pitch our wavetable never writes
    (5, True),    # fx $04: the two-stage waveform
    (9, False),   # fx $10, a pitch sequence on a global phase
])
def test_which_lightforce_records_have_an_attack(record, attack):
    sid, det = _load("Lightforce.sid")
    assert NP.free_note_record_has_attack(sid, det, record) is attack


@needs_corpus
def test_a_zero_frame_count_or_attack_waveform_is_no_attack():
    sid, det = _load("Lightforce.sid")
    assert NP.free_note_record_has_attack(sid, det, 5)
    fr = det.two_stage_frames + 5 * det.instr_stride
    aw = det.two_stage_wave + 5 * det.instr_stride
    assert not NP.free_note_record_has_attack(_with(sid, fr, 0), det, 5)
    assert not NP.free_note_record_has_attack(_with(sid, aw, 0), det, 5)


@needs_corpus
def test_the_drum_fixed_pitch_prologue_is_an_attack():
    """Pandora has the bit-$80 drum: a record carrying $80 and $40 plays the
    fixed pitch as a once-per-note prologue on the frame counter
    (`_sfx_drum_entries`' `second_note`), which a flagged note skips and a
    pulse-only variant would keep. Record 8 is $A0; set $40 on it."""
    sid, det = _load("Pandora.sid")
    assert det.sfx_pitch >= 0 and det.effect_bit40
    fx = det.instr_start + 8 * det.instr_stride + 7
    assert sid.data[fx] == 0xA0
    assert not NP.free_note_record_has_attack(sid, det, 8)
    drum = _with(sid, fx, 0xE0)
    assert NP.free_note_record_has_attack(drum, det, 8)
    assert not NP.free_note_record_has_attack(
        drum, dataclasses.replace(det, sfx_pitch=-1), 8)
    # ... and it has no second stage for the two-stage variant to start on,
    # even in a block the two-stage walk WOULD enter past ($A4: the same
    # record as a two-stage one, attack $81, then its second stage, stop).
    two = _with(sid, fx, 0xA4)
    wave = sid.data[det.instr_start + 8 * det.instr_stride + 2]
    second = (_wave_byte(wave & 0xFE) if not wave & 0xF0
              else wave & 0xFE) | (wave & 0x01)
    block = [(0x81, 0x00), (second, 0x00), (C.GT_WAVE_JUMP, 0x00)]
    assert NP.free_note_wave_start(two, det, 8, block, 1) == 2
    assert NP.free_note_wave_start(drum, det, 8, block, 1) == 0


# --- end to end --------------------------------------------------------------

@pytest.fixture(scope="module")
def lightforce():
    if not CORPUS.is_dir():
        pytest.skip("corpus absent")
    old, _ = _convert("Lightforce.sid", pulse_only=False)
    new, lines = _convert("Lightforce.sid")
    return old, new, lines


@needs_corpus
def test_lightforce_respells_its_flagged_notes_on_one_pulse_only_variant(
        lightforce):
    old, new, lines = lightforce
    assert lines == ["Free note (bit 7).......: 81 flagged note row(s) on 1 "
                     "variant(s) with no attack stage and no pulse reset (1 "
                     "pulse-only: the record has no attack), 1 kept the full "
                     "start (1 follows another instrument)"]
    n_old = len(old.instruments)
    assert len(new.instruments) == n_old + 1
    assert new.instruments[:n_old] == old.instruments
    assert old.tracks == new.tracks and old.tables == new.tables
    var = new.instruments[n_old]
    base = old.instruments[8 - 1]
    assert var.pulse_ptr == 0 and base.pulse_ptr != 0
    assert dataclasses.replace(var, number=base.number, pulse_ptr=base.pulse_ptr,
                               name=base.name) == base


@needs_corpus
def test_lightforce_moves_only_the_instrument_column(lightforce):
    old, new, _ = lightforce
    n_old = len(old.instruments)
    kinds = {"free": 0, "relatch": 0}
    for x, y in zip(old.patterns, new.patterns):
        for r in range(len(x) // 4):
            a, b = x[4 * r:4 * r + 4], y[4 * r:4 * r + 4]
            if a == b:
                continue
            assert a[0] == b[0] and a[2:] == b[2:], (a, b)
            kinds["free" if b[1] > n_old else "relatch"] += 1
    assert kinds["free"] == 81


@needs_corpus
def test_saboteur_ii_takes_all_nineteen():
    old, _ = _convert("Saboteur_II.sid", pulse_only=False)
    new, lines = _convert("Saboteur_II.sid")
    assert lines == ["Free note (bit 7).......: 19 flagged note row(s) on 1 "
                     "variant(s) with no attack stage and no pulse reset (1 "
                     "pulse-only: the record has no attack)"]
    var = new.instruments[-1]
    base = old.instruments[4 - 1]
    assert (var.wave_ptr, var.pulse_ptr) == (base.wave_ptr, 0)
    assert base.pulse_ptr != 0


@needs_corpus
def test_flash_gordon_keeps_the_full_start_on_an_attack_it_cannot_skip():
    """Instruments 7 and 8 carry the two-stage bit and a frame count, but
    their wavetable block is not one `free_note_wave_start` enters past: a
    pulse-only variant would keep the attack the original skips. The two
    rows free-note-two's entry split settles stay on their two-stage
    variant."""
    _, lines = _convert("Flash_Gordon.sid")
    # The "4 instrument unsettled" rows this line also counted before
    # v0.5.514 sat in patterns no orderlist reaches; the presets regeneration
    # turned `prune` on for Flash_Gordon, and drop_unplayed_patterns removes
    # those patterns with them.
    assert lines == ["Free note (bit 7).......: 5 flagged note row(s) on 4 "
                     "variant(s) with no attack stage and no pulse reset (3 "
                     "pulse-only: the record has no attack), 4 kept the full "
                     "start (4 attack the wavetable cannot skip)"]
