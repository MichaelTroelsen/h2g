"""The accumulate pulse engine's ZERO-PAGE dialect (detect.PULSE_LO_SHAPES).

Samantha Fox ($721E) and Spellbound ($E261) spell the effect-bit-$08 block
`LDY zp` (and Samantha Fox `ADC zp`) where the 21 absolute-dialect files spell
`LDY abs / ADC abs`, so `_find_effect_routines` and `_find_pulse_lo` read
nothing there and Spellbound's record 20 (bit $08, rate $02) kept a static
width. Traced on the original (siddump -t180 -we5e8, record 20's +0 cell):
the cell takes all 256 values in subtunes 1 and 2, ~1.9 per frame, so the
record really does sweep there.
"""
import dataclasses

import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import (PULSE_LO_SHAPES, _effect_byte_address, _find_pulse_lo,
                        _pulse_lo_block, detect)
from h2g.goatwriter import _pulse_program
from h2g.sidfile import load_sid

# The two files the dialect reaches, and which fallback spelling each carries.
ZP_DIALECT = {"Samantha_Fox_Strip_Poker": 2, "Spellbound": 1}

# Every corpus file the accumulate engine is read on: the 21 absolute-spelling
# files plus the two above. Censused over all eight LDY/ADC/LDY addressing
# combinations; no other combination occurs anywhere in the corpus.
ACCUMULATE_FILES = {
    "5_Title_Tunes", "Battle_of_Britain", "Bump_Set_Spike", "Chicken_Song",
    "Commando", "Formula_1_Simulator", "Geoff_Capes_Strongman_Challenge",
    "Gerry_the_Germ", "Gremlins", "Hunter_Patrol", "International_Karate",
    "Kentilla", "Las_Vegas_Video_Poker", "Master_of_Magic", "Mozart",
    "One_Man_and_his_Droid", "Proteus", "Rasputin", "Thrust", "Warhawk",
    "Zoids",
} | set(ZP_DIALECT)


def _load(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda *_a, **_k: None)


def _block(sid, det):
    addr, zp = _effect_byte_address(sid, det)
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    return _pulse_lo_block(sid.data, load)


@needs_corpus
@pytest.mark.parametrize("stem,spelling", sorted(ZP_DIALECT.items()))
def test_the_zero_page_dialect_is_read(stem, spelling):
    sid, det = _load(stem)
    assert det.effect_pulse_lo
    assert det.pulse_lo_base == det.instr_start
    lda, rate, found = _block(sid, det)
    assert found == spelling
    d = sid.data
    # The operands the reader took are the instrument table and its rate cell.
    assert d[lda] == 0xB9 and sid.to_offset(d[lda + 1] | d[lda + 2] << 8) \
        == det.instr_start
    assert d[rate] == (0x65 if spelling == 2 else 0x6D)


@needs_corpus
def test_the_corpus_population_is_exactly_these_files():
    found, spellings = set(), {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _load(path.stem)
        if det.pulse_lo_base >= 0:
            found.add(path.stem)
            spellings[path.stem] = _block(sid, det)[2]
    assert found == ACCUMULATE_FILES
    # The fallbacks reach exactly the two files and no absolute-dialect file.
    assert {s: k for s, k in spellings.items() if k} == ZP_DIALECT


def _mutated(sid, old: bytes, new: bytes):
    assert sid.data.count(old) == 1, old.hex()
    return dataclasses.replace(sid, data=sid.data.replace(old, new))


@needs_corpus
def test_a_fallback_needs_its_rate_cell_filled_from_record_6():
    sid, det = _load("Spellbound")
    # `LDA $E54E,Y / STA $E4D0` -- record +6 into the ADC's rate cell.
    broken = _mutated(sid, bytes.fromhex("B94EE58DD0E4"),
                      bytes.fromhex("B94EE58DD1E4"))
    assert _find_pulse_lo(broken, det) == -1
    assert _find_pulse_lo(sid, det) == det.instr_start


@needs_corpus
def test_a_fallback_store_must_name_the_array_it_loaded():
    sid, det = _load("Samantha_Fox_Strip_Poker")
    # `ADC $BD / STA $7407,Y` -> `STA $7408,Y`.
    broken = _mutated(sid, bytes.fromhex("65BD990774"),
                      bytes.fromhex("65BD990874"))
    assert _find_pulse_lo(broken, det) == -1


@needs_corpus
def test_spellbound_record_20_accumulates_instead_of_holding_still():
    sid, det = _load("Spellbound")
    rec = det.instr_start + 20 * det.instr_stride
    assert sid.data[rec + 7] & 0x08 and sid.data[rec + 6] == 0x02
    entries, loop = _pulse_program(sid, det, 20, True, 5)
    # A set to the record's own width ($100), then one ascending leg across
    # the low byte, then the jump back to the set (`_pulse_lo_program`).
    assert entries[0] == (0x81, 0x00)
    assert loop == 0
    legs = entries[1:]
    assert all(speed == 1 for _t, speed in legs)
    assert sum(t for t, _s in legs) == 0x100


@needs_corpus
def test_samantha_fox_has_no_record_the_engine_reaches():
    # Why its converted bytes do not move: the engine is read, but no record
    # carries bit $08, so `_pulse_lo_program` declines every one.
    sid, det = _load("Samantha_Fox_Strip_Poker")
    assert det.pulse_lo_base >= 0
    assert not any(sid.data[det.instr_start + i * det.instr_stride + 7] & 0x08
                   for i in range(det.instr_used))


def test_the_absolute_spelling_is_tried_first():
    # Order is the rule: a fallback is consulted only where the absolute
    # spelling matched nothing.
    assert PULSE_LO_SHAPES[0].split()[4] == "AC"
    assert all(s.split()[4] == "A4" for s in PULSE_LO_SHAPES[1:])
