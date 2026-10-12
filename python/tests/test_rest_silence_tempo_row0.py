"""A rest's `CMD_SETSR $00` survives the subtune's tempo taking row 0.

Mega_Apocalypse's bit-6 rest (`$4B91`) writes AD, SR and the stored waveform
to zero, and the instrument's per-frame effect keeps moving the frequency of
the now-silent voice -- the 192,939 of "travel under ADSR $0000" the original
shows and ours did not. `rest_envelope_silence` emits the zeroed pair as
`CMD_SETSR $00` on the KEYOFF row, but a pattern that OPENS on the rest has
that on row 0, which `CMD_SETTEMPO` outranks, so the SR half (the audible one)
was the half thrown away and the note rang out through its release.
"""
import os

import pytest

from h2g.convert import convert
from h2g.goatwriter import CMD_SETTEMPO
from h2g.patterns import (CMD_SETAD, CMD_SETSR, GT_KEYOFF, GT_NO_NOTE,
                          _move_rest_silence_off_row0, apply_tempo,
                          apply_tempos)

CORPUS = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"
MEGA = os.path.join(CORPUS, "Mega_Apocalypse.sid")
HOLD = [GT_NO_NOTE, 0, 0, 0]


def _rest_pattern(rows: int = 4) -> list:
    """KEYOFF + SETSR 0, hold row with SETAD 0, then empty hold rows."""
    p = [GT_KEYOFF, 0, CMD_SETSR, 0, GT_NO_NOTE, 0, CMD_SETAD, 0]
    for _ in range(rows - 2):
        p += HOLD
    return p


def test_the_sr_write_moves_to_hold_row_one_and_the_ad_to_row_two():
    p = _rest_pattern()
    _move_rest_silence_off_row0(p)
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETSR, 0]
    assert p[8:12] == [GT_NO_NOTE, 0, CMD_SETAD, 0]


def test_a_full_row_two_drops_the_inaudible_ad_half_rather_than_displacing():
    p = _rest_pattern()
    p[8:12] = [GT_NO_NOTE, 0, 8, 0x40]          # a wavetable pointer
    _move_rest_silence_off_row0(p)
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETSR, 0]
    assert p[8:12] == [GT_NO_NOTE, 0, 8, 0x40]


@pytest.mark.parametrize("mutate", [
    lambda p: p.__setitem__(0, 0x70),                  # a note, not a KEYOFF
    lambda p: p.__setitem__(2, CMD_SETAD),             # not a SETSR on row 0
    lambda p: p.__setitem__(3, 0x0F),                  # SR not zero
    lambda p: p.__setitem__(6, 0),                     # row 1 is not SETAD
    lambda p: p.__setitem__(7, 0x11),                  # row 1 AD not zero
    lambda p: p.__setitem__(4, 0x70),                  # row 1 is a note
])
def test_anything_but_the_exact_spelling_is_left_alone(mutate):
    p = _rest_pattern()
    mutate(p)
    before = list(p)
    _move_rest_silence_off_row0(p)
    assert p == before


def test_a_pattern_too_short_for_row_one_is_left_alone():
    p = [GT_KEYOFF, 0, CMD_SETSR, 0]
    _move_rest_silence_off_row0(p)
    assert p == [GT_KEYOFF, 0, CMD_SETSR, 0]


def test_apply_tempo_keeps_row_zero_for_the_tempo_and_the_sr_write():
    pats = [_rest_pattern()]
    apply_tempo(pats, [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]], 3)
    p = pats[0]
    assert p[2:4] == [CMD_SETTEMPO, 3]
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETSR, 0]


def test_apply_tempos_keeps_row_zero_for_the_tempo_and_the_sr_write():
    pats = [_rest_pattern()]
    apply_tempos(pats, [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]], [3])
    p = pats[0]
    assert p[2:4] == [CMD_SETTEMPO, 3]
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETSR, 0]


def test_a_pattern_the_tempo_cannot_enter_keeps_its_row_zero_sr():
    """No tempo is written where the command column is taken, so nothing
    outranks the SETSR and nothing moves."""
    p = _rest_pattern()
    p[2:4] = [3, 0x20]                                  # a portamento owns it
    pats = [p]
    apply_tempo(pats, [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]], 3)
    assert pats[0][2:4] == [3, 0x20]
    assert pats[0][4:8] == [GT_NO_NOTE, 0, CMD_SETAD, 0]


@pytest.mark.skipif(not os.path.exists(MEGA), reason="corpus not present")
def test_mega_apocalypse_no_tempo_row_zero_rest_loses_its_silencing_sr():
    """End to end: every pattern that opens on a KEYOFF under the tempo has
    the SR write on row 1, none leaves the bare AD half there."""
    from songview import parse_sng
    sng = bytes(convert(MEGA, log=lambda _m: None, rest_instrument=True,
                        rest_keyoff=True, rest_envelope_silence=True,
                        status_bit6=True, pack=True, prune=True,
                        compact_instruments=True, tempo="auto"))
    opening = [p for p in parse_sng(sng).patterns
               if len(p) >= 8 and p[0] == GT_KEYOFF and p[2] == CMD_SETTEMPO]
    assert opening, "Mega_Apocalypse has patterns that open on a rest"
    for p in opening:
        assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETSR, 0], p[:12]
