"""A hold plays the opening width on its attack frame under the SHARED layout
too (`pulse._phase_block`'s `attack`, `pulse._lay_attack_or_plain`), and for
as many ticks as the original keeps it there (`hold_direction`'s `wait`,
`patterns._triangle_hold`).

Opened by `devils-galop-two-voice-triangle-hold`: Devils_Galop voice 1 agreed
with the original on 533 of 624 frames after an attack against voice 0's 623,
because the shared layout is `set held / FF 00` and so plays the held width
on the attack frame itself, where the original reads the opening width for
one frame or two. Measured here, forced `pulse_phase`, presets, 180 s, the
first 12 frames of 60 attacks (tolerance speed * multiplier + $10):
Devils_Galop v1 533 -> 624 of 624 (v0 623 -> 624), Chimera (-S1) v0 725 ->
732 and v1 661 -> 732 of 732, Thing_on_a_Spring v2 42 -> 48 of 48 hold notes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402

from h2g.goatwriter import (HOLD_WAIT, _phase_block, hold_direction,  # noqa: E402
                            hold_rest, hold_steps, hold_wait, is_hold)

LO, HI = 0x800, 0xE00
OPEN = (0xF00, hold_direction(-1))          # opens $F00, holds $E80


def _block(want, share, attack, multiplier=2):
    return _phase_block(0, 1, want, 0x880, 0x40, LO, HI, False, 0x80,
                        share=share, attack=attack, multiplier=multiplier)


# --------------------------------------------------------------------------
# The direction code
# --------------------------------------------------------------------------

def test_a_hold_direction_carries_steps_and_wait_and_stays_a_hold():
    for k in range(-6, 24):
        for wait in (0, 1, 2, 5):
            d = hold_direction(k, wait)
            assert is_hold(d) and hold_steps(d) == k and hold_wait(d) == wait
    assert hold_direction(3) == hold_direction(3, 0) < HOLD_WAIT


def test_the_rest_between_the_widths_is_multiplier_calls_a_tick():
    """The fetch call writes the opening width, so the first tick costs
    `multiplier - 1` calls and every tick of wait `multiplier` more."""
    assert hold_rest(hold_direction(0, 0), 2) == [(1, 0)]
    assert hold_rest(hold_direction(0, 1), 2) == [(3, 0)]
    assert hold_rest(hold_direction(0, 2), 3) == [(8, 0)]
    assert hold_rest(hold_direction(0, 0), 1) == []
    assert hold_rest(hold_direction(0, 2), 1) == [(2, 0)]


# --------------------------------------------------------------------------
# The shared layout
# --------------------------------------------------------------------------

def test_the_plain_shared_layout_plays_the_held_width_on_the_attack_call():
    rows, index = _block({OPEN}, share=True, attack=False)
    assert _play_pulse_table(rows, index[(1, *OPEN)], 4) == [0xE80] * 4


def test_the_attack_form_keeps_the_opening_width_for_the_attack_frame():
    """-S2: the attack call and one rest call on $F00, then $E80."""
    rows, index = _block({OPEN}, share=True, attack=True)
    assert _play_pulse_table(rows, index[(1, *OPEN)], 6) == \
        [0xF00, 0xF00] + [0xE80] * 4


def test_the_attack_form_plays_what_the_per_phase_layout_plays():
    """The per-phase layout has always spent four rows on this; the shared
    form must play the same widths for every wait and multiplier."""
    for multiplier in (1, 2, 3):
        for wait in (0, 1, 2):
            want = {(0xF00, hold_direction(-1, wait))}
            r_shared, i_shared = _block(want, True, True, multiplier)
            r_per, i_per = _block(want, False, False, multiplier)
            key = (1, 0xF00, hold_direction(-1, wait))
            a = _play_pulse_table(r_shared, i_shared[key], 12)
            b = _play_pulse_table(r_per, i_per[key], 12)
            assert a == b, (multiplier, wait, a, b)
            on_open = a.count(0xF00)
            assert on_open == (multiplier - 1) + wait * multiplier + 1, a


def test_the_opening_waits_as_many_ticks_as_the_original_does():
    rows, index = _block({(0xF00, hold_direction(-1, 1))}, True, True, 2)
    assert _play_pulse_table(rows, index[(1, 0xF00, hold_direction(-1, 1))],
                             8) == [0xF00] * 4 + [0xE80] * 4


def test_three_rows_an_opening_and_two_a_held_width():
    """Three openings that hold $E80, one of them on it already: the held
    pair is laid once, the two off-width openings take `set / rest / jump`."""
    want = {(0xF00, hold_direction(-1)), (0xE80, hold_direction(0)),
            (0xE00, hold_direction(+1))}
    plain, _ = _block(want, True, False)
    attack, index = _block(want, True, True)
    assert len(attack) - len(plain) == 2 * 3
    tail = index[(1, 0xE80, hold_direction(0))]
    assert attack[tail - 1:tail + 1] == [(0x8E, 0x80), (0xFF, 0x00)]
    at = index[(1, *OPEN)]
    assert attack[at - 1:at + 2] == [(0x8F, 0x00), (1, 0), (0xFF, tail)]


def test_a_hold_that_opens_on_its_width_needs_no_attack_form():
    want = {(0xE80, hold_direction(0, 1))}
    assert _block(want, True, True) == _block(want, True, False)


# --------------------------------------------------------------------------
# Only where the table has the rows
# --------------------------------------------------------------------------

def test_devils_galop_ships_the_attack_form_and_gives_way_when_it_will_not_fit(
        monkeypatch):
    from test_pulse_phase_union import _table_calls
    from h2g.goatwriter import build_pulse_phase_table, constants
    args = _table_calls("Devils_Galop.sid")[0]
    key = (10, 0xF00, hold_direction(-1))
    entries, _, index = build_pulse_phase_table(*args)
    assert _play_pulse_table(entries, index[key], 6) == \
        [0xF00, 0xF00] + [0xE80] * 4
    # One row short of the attack form: the plain shared form ships, every
    # phase still placed, the held width on the attack call.
    monkeypatch.setattr(constants, "GT_MAX_TABLELEN", len(entries) - 1)
    short, _, sindex = build_pulse_phase_table(*args)
    assert len(short) < len(entries)
    assert set(sindex) == set(index)
    assert _play_pulse_table(short, sindex[key], 4) == [0xE80] * 4
