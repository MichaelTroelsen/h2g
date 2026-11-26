"""The combined rest_wave_silence + rest_envelope_silence spelling keeps its
`CMD_SETSR $00` when the subtune's tempo takes row 0.

Combined, a rest is KEYOFF + SETWAVE $08 on row 0 and SETSR 0 on hold row 0
(the park first: the original writes the stored waveform, SR and AD on ONE
call, and the park is the write the `hold` column reads -- Thundercats
`$EE38`; two rows, not three, so the regrid tempo pair keeps the rows it has
without the park). `_move_rest_silence_off_row0` used to match only
row 1 = SETAD, so the combined form lost its SETSR (Mega_Apocalypse voice 2's
first rest read $00FC again)."""
import pytest

from h2g.goatwriter import CMD_SETTEMPO
from h2g.patterns import (CMD_SETAD, CMD_SETSR, CMD_SETWAVE, GT_KEYOFF,
                          GT_NO_NOTE, REST_SILENT_WAVE,
                          _move_rest_silence_off_row0, apply_tempo)

HOLD = [GT_NO_NOTE, 0, 0, 0]


def _combined(rows: int = 5) -> list:
    p = [GT_KEYOFF, 0, CMD_SETWAVE, REST_SILENT_WAVE,
         GT_NO_NOTE, 0, CMD_SETSR, 0]
    for _ in range(rows - 2):
        p += HOLD
    return p


def test_park_takes_row_one_sr_row_two():
    p = _combined()
    _move_rest_silence_off_row0(p)
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETWAVE, REST_SILENT_WAVE]
    assert p[8:12] == [GT_NO_NOTE, 0, CMD_SETSR, 0]
    assert p[12:16] == HOLD


def test_full_row_two_drops_sr_rather_than_displacing():
    p = _combined()
    p[8:12] = [GT_NO_NOTE, 0, 8, 0x40]
    _move_rest_silence_off_row0(p)
    assert p[8:12] == [GT_NO_NOTE, 0, 8, 0x40]
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETWAVE, REST_SILENT_WAVE]


@pytest.mark.parametrize("mutate", [
    lambda p: p.__setitem__(6, 0),            # row 1 not SETSR
    lambda p: p.__setitem__(7, 0x0F),         # row 1 SR not zero
    lambda p: p.__setitem__(3, 0x09),         # row 0 wave not the park
])
def test_anything_but_the_exact_combined_spelling_is_left_alone(mutate):
    p = _combined()
    mutate(p)
    before = list(p)
    _move_rest_silence_off_row0(p)
    assert p == before


def test_combined_pattern_too_short_for_row_two_is_left_alone():
    p = _combined()[:8]
    before = list(p)
    _move_rest_silence_off_row0(p)
    assert p == before


def test_apply_tempo_keeps_the_park_and_sr_writes_on_the_combined_spelling():
    pats = [_combined()]
    apply_tempo(pats, [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]], 3)
    p = pats[0]
    assert p[2:4] == [CMD_SETTEMPO, 3]
    assert p[4:8] == [GT_NO_NOTE, 0, CMD_SETWAVE, REST_SILENT_WAVE]
    assert p[8:12] == [GT_NO_NOTE, 0, CMD_SETSR, 0]


def test_program_stop_clearing_a_tempo_taken_combined_rest_restores_the_envelope_layout():
    """`rest_park_pass` must undo the combined move on a rest it clears, or a
    pattern that opens on the rest comes out a row later than the envelope
    option alone (Thundercats under --rest-program-stop)."""
    from h2g.goatwriter import rest_park as RP
    p = _combined(6)
    apply_tempo([p], [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]], 3)
    want = [GT_KEYOFF, 0, CMD_SETTEMPO, 3,
            GT_NO_NOTE, 0, CMD_SETSR, 0,
            GT_NO_NOTE, 0, CMD_SETAD, 0] + HOLD * 3
    out = RP.rest_park_pass([p + [0xFF, 0, 0, 0]],
                            [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]],
                            frozenset(), 0, only=frozenset({9}))
    assert out[0][:len(want)] == want
