"""A record two voices step in opposite directions is HELD, not swept
(`patterns._triangle_hold`, `goatwriter.hold_direction`).

The triangle engine's width is per record and its direction per voice, so
voices X = 2, 1, 0 stepping one record up and down by one step on the same
tick put it back where it was, and the pulse register each voice writes
(only on a tick it stepped) reads one constant for as long as the pair
lasts. Devils_Galop's instrument 10 is the carrier: voice 0 and voice 1
play it on the same 57 notes, the walk planned `($F00, up)` and `($F00,
down)` -- two ramps away from the width the original holds -- and the
packed output agreed with the original on 66 of 624 frames after the
attack on voice 0 and 149 of 624 on voice 1, over the notes' first 12
frames (`follow` of the task's scratch, FIDELITY's rule: the top 8 bits
within one table step of the original). With the holds: 623 of 624 and
533 of 624. The same shape is Monty_on_the_Run's instrument 10,
Chimera's 6 and Thing_on_a_Spring's 14.

A hold is a phase whose direction is `hold_direction(k)`: the width it opens
on (the record's width at the fetch, as ever) and `k` steps from it to the
width it then reads on every step. Voice 1 of Devils_Galop opens on $F00 and
holds $E80 (k = -1); voice 0 opens on $F00 and holds it (k = 0).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402
from test_triangle_lockstep import _STOP, _pattern, _sim  # noqa: E402

from h2g.goatwriter import (_chained_phases, _phase_block, _phase_cycle, _union_kind,
                            hold_direction, hold_steps, is_hold)
from h2g.patterns import GT_ORDER_RESTART, collect_pulse_phases  # noqa: F401

LO, HI = 0x800, 0xE00


def _pair(delay: int, counters=(0, 0), width: int = 0xA00, rows: int = 4):
    """Voice 1 sweeps record 2 down, voice 0 up, from the lead-in; both
    play a note on record 2 at row `rows`. The plan of the first pass."""
    pat = _pattern([(None, 0)] * rows + [(0x70, 2), (None, 0)])
    tracks = [[0] + _STOP, [0] + _STOP, [GT_ORDER_RESTART, 0x00]]
    start = [(0, ((2, +1, counters[0]), (2, -1, counters[1]), (0, +1, 0)))]
    got = collect_pulse_phases([pat], tracks, [1],
                               {2: _sim(width, 0x40, delay)}, tri_start=start)
    assert got is not None
    return got[1]


def test_the_direction_codes_round_trip_and_are_not_a_sweep():
    assert not is_hold(+1) and not is_hold(-1)
    for k in range(-3, 4):
        assert is_hold(hold_direction(k)) and hold_steps(hold_direction(k)) == k
    assert hold_direction(0) not in (+1, -1)


def test_two_voices_stepping_opposite_ways_open_on_a_hold():
    """Voice 1 steps first in the tick ($A00 -> $9C0) and voice 0 puts it
    back, so voice 0 reads $A00 on every step after its fetch (k = 0) and
    voice 1 reads $9C0 (k = -1, one step down) -- both open on the width
    the record is at when they fetch, $A00."""
    got = _pair(delay=1)
    assert got == [(0, 0, {4: (2, (0xA00, hold_direction(0)))}),
                   (1, 0, {4: (2, (0xA00, hold_direction(-1)))})], got


def test_a_delay_changes_the_ticks_a_voice_reads_not_the_hold():
    """At delay 2 a voice steps every second tick and writes the register
    only then, so its reads are the same constants: the ticks its counter
    spends counting down read nothing (reads taken on every tick would
    alternate $9C0 and $A00 for voice 1 and decline the hold). Which of the
    two steps first decides the steps each reads away from the width at the
    fetch: voice 1 first (counters 0, 0), voice 1 down and voice 0 back;
    voice 0 first (voice 1's counter at 1), voice 0 up and voice 1 back."""
    want = {(0, 0): (0, -1), (0, 1): (+1, 0), (1, 0): (0, -1), (1, 1): (0, -1)}
    for counters, (k0, k1) in want.items():
        got = _pair(delay=2, counters=counters)
        [(_, _, v0), (_, _, v1)] = got
        assert v0[4][1][0] == v1[4][1][0] == 0xA00, (counters, got)
        assert (v0[4][1][1], v1[4][1][1]) == (hold_direction(k0), hold_direction(k1)),             (counters, got)


def test_two_voices_stepping_the_same_way_are_not_a_hold():
    """Both up: the record climbs two steps a tick, and each voice's phase
    is the sweep it always was."""
    pat = _pattern([(None, 0)] * 4 + [(0x70, 2), (None, 0)])
    tracks = [[0] + _STOP, [0] + _STOP, [GT_ORDER_RESTART, 0x00]]
    start = [(0, ((2, +1, 0), (2, +1, 0), (0, +1, 0)))]
    got = collect_pulse_phases([pat], tracks, [1], {2: _sim(0x900)},
                               tri_start=start)
    assert got is not None
    for _, _, rows in got[1]:
        assert rows[4][1][1] == +1, got[1]


def test_a_voice_alone_on_its_record_sweeps():
    """The other voices sweep other records: nobody holds this one."""
    pat = _pattern([(None, 0)] * 4 + [(0x70, 2), (None, 0)])
    rest = _pattern([(None, 0)] * 6)
    tracks = [[0] + _STOP, [1] + _STOP, [GT_ORDER_RESTART, 0x00]]
    start = [(0, ((2, +1, 0), (3, -1, 0), (0, +1, 0)))]
    sims = {2: _sim(0xA00), 3: _sim(0xA00)}
    got = collect_pulse_phases([pat, rest], tracks, [1], sims, tri_start=start)
    assert got is not None
    assert got[1] == [(0, 0, {4: (2, (0xB00, +1))})], got[1]


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

def _block(want: set, share: bool, step: int = 0x80, speed: int = 0x40):
    rows, index = _phase_block(0, 1, want, 0x880, speed, LO, HI, False,
                               step, share=share)
    return rows, index


def test_a_hold_that_opens_on_its_width_is_a_set_row_and_a_stop():
    want = {(0xF00, hold_direction(0))}
    for share in (False, True):
        rows, index = _block(want, share)
        at = index[(1, 0xF00, hold_direction(0))]
        assert rows[at - 1:at + 1] == [(0x8F, 0x00), (0xFF, 0x00)], rows
        assert _play_pulse_table(rows, at, 5) == [0xF00] * 5


def test_a_hold_off_its_width_plays_the_attack_then_the_width_it_holds():
    """The per-phase layout spends four rows on it: the opening width, one
    call of nothing (the attack frame at -S2 stays on it), the held width
    one step down at step $80, the stop."""
    want = {(0xF00, hold_direction(-1))}
    rows, index = _block(want, share=False)
    at = index[(1, 0xF00, hold_direction(-1))]
    assert rows[at - 1:at + 3] == [(0x8F, 0x00), (1, 0), (0x8E, 0x80), (0xFF, 0x00)]
    assert _play_pulse_table(rows, at, 6) == [0xF00, 0xF00] + [0xE80] * 4


def test_the_shared_layout_shares_one_pair_of_rows_per_width_held():
    """Three openings that all hold $E80 -- $F00 one step down, $E80 itself,
    $E00 one step up: the shared layout lays the width once and every
    opening names it."""
    want = {(0xF00, hold_direction(-1)), (0xE80, hold_direction(0)),
            (0xE00, hold_direction(+1))}
    rows, index = _block(want, share=True)
    held = {k: v for k, v in index.items()}
    assert held[(1, 0xF00, hold_direction(-1))] == held[(1, 0xE80, hold_direction(0))] \
        == held[(1, 0xE00, hold_direction(+1))]
    assert rows.count((0x8E, 0x80)) == 1
    at = held[(1, 0xF00, hold_direction(-1))]
    assert _play_pulse_table(rows, at, 4) == [0xE80] * 4


def test_a_hold_takes_no_part_in_the_chain_or_the_kind():
    """A hold is on no leg and lands on no bound: it neither enters
    `_chained_phases` nor changes `_union_kind` -- a record whose moving
    phases chain still chains."""
    moving = {(0x880, +1), (0x900, -1), (0xA00, +1)}
    with_holds = moving | {(0xF00, hold_direction(0)), (0xE80, hold_direction(-1))}
    assert _chained_phases(with_holds, 0x40, LO, HI, False, 0x80) \
        == _chained_phases(moving, 0x40, LO, HI, False, 0x80)
    assert _union_kind(with_holds, 0x40, LO, HI, False, 0x80) \
        == _union_kind(moving, 0x40, LO, HI, False, 0x80) == "chained"


# --------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------

def test_devils_galops_instrument_10_is_planned_as_holds():
    """Under forced `pulse_phase` the plan for instrument 10 and 11 -- the
    records voices 0 and 1 sound together -- is holds only: $F00 on voice 0
    ($F00, k = 0) and $E80 on voice 1 (opening $F00, k = -1), and the two
    first notes' $E00 (k = +1, +2). No ($F00, up) or ($F00, down) remain."""
    from test_pulse_phase_union import _table_calls
    phases = _table_calls("Devils_Galop.sid")[0][5]
    assert phases[10] == {(0xE00, hold_direction(1)), (0xE00, hold_direction(2)),
                          (0xF00, hold_direction(-1)), (0xF00, hold_direction(0))}, phases[10]
    assert all(is_hold(d) for _, d in phases[10] | phases[11])


def test_the_wrap_ramps_still_play_in_the_table():
    """Devils_Galop's ($F00, up) and ($E00, up) are no longer planned (they
    are holds), and `test_triangle_wrap_ramps` used to read their entries off
    the shipped table. The blocks themselves are unchanged: $F00 up climbs
    through $FFF to nibble E, and $E00 up -- already on the high nibble --
    climbs one step and comes back to $E00 (`_leg_ramps`)."""
    want = {(0xF00, +1), (0xE00, +1)}
    rows, index = _phase_block(0, 1, want, 0x880, 0x20, LO, HI, False, 0x80)
    assert _play_pulse_table(rows, index[(1, 0xF00, +1)], 5) \
        == [0xF00, 0xF20, 0xF40, 0xF60, 0xF80]
    got = _play_pulse_table(rows, index[(1, 0xE00, +1)], 100)
    assert got[:10] == [0xE00, 0xE20, 0xE40, 0xE60, 0xE80, 0xE60, 0xE40, 0xE20,
                        0xE00, 0xDE0]
    # ... and the way back puts it ON $E00, so the loop's down leg turns at
    # the cycle's bottom: $880 for step $80 since the phase tables turn on the
    # nibble lattice (`_phase_cycle`, METHOD 7.iiiiiiii; $800 on the bounds)
    assert _phase_cycle(want, LO, HI, 0x80) == (0x880, 0xE00)
    assert min(got) == 0x880, hex(min(got))
