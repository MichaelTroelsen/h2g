"""A hold ENDS when the partner that kept the record still leaves
(`patterns._hold_resume`, `goatwriter.hold_direction`'s `then`,
`pulse._phase_block`'s `resume`).

`_triangle_hold` plans a hold on the lookahead of the first few ticks, and the
table held to the voice's next command. The partner can leave inside the note:
Monty_on_the_Run's instrument 11 on voice 0 reads $F00 for 135 ticks and then
$F80, $000, $080 ... up the record, the original sweeping on alone, where the
table read $F00 to the note's end. Under forced `pulse_phase`, presets, 180 s,
paired by note against the original's siddump, frames from the attack to the
next attack (tolerance speed * multiplier + $10): that note 135 -> 191 of 192,
Monty voice 0's out-of-band notes 643 -> 699 of 752; no other note of
Monty_on_the_Run, Devils_Galop, Chimera or Thing_on_a_Spring moves.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402
from test_triangle_lockstep import _STOP, _pattern, _sim  # noqa: E402

from h2g.goatwriter import (HOLD_THEN, HOLD_WAIT, _phase_block,  # noqa: E402
                            hold_direction, hold_steps, hold_then, hold_wait,
                            is_hold, resume_phase)
from h2g.patterns import GT_ORDER_RESTART, collect_pulse_phases  # noqa: E402

LO, HI = 0x800, 0xE00


# --------------------------------------------------------------------------
# The direction code
# --------------------------------------------------------------------------

def test_a_hold_that_ends_keeps_its_steps_and_wait_and_names_its_sweep():
    for k in (-6, 0, 3, 23):
        for wait in (0, 1, 5):
            for then in (None, (1, 0xA00, +1), (135, 0xF00, -1), (4000, 0, +1)):
                d = hold_direction(k, wait, then)
                assert is_hold(d) and d != +1 and d != -1
                assert hold_steps(d) == k and hold_wait(d) == wait
                assert hold_then(d) == then
                assert resume_phase(d) == (None if then is None else then[1:])
    assert hold_direction(2, 1) == hold_direction(2, 1, None) < HOLD_THEN
    assert hold_direction(0, 0, (3, 0xA00, +1)) != hold_direction(0, 0, (4, 0xA00, +1))
    assert hold_direction(0, 0, (3, 0xA00, +1)) != hold_direction(0, 0, (3, 0xA00, -1))
    assert HOLD_WAIT * 2048 == HOLD_THEN


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------

def _leaves(leave_row: int, total: int = 12, third=None):
    """Voice 0 and voice 1 step record 2 in opposite directions from $A00 and
    voice 0 plays a note on it at row 4 (a hold, k = 0). Voice 1 plays a note
    on record 3 at `leave_row`: the partner leaves. The pattern ends at row
    `total`. `third` is a row of voice 2 that also plays record 2."""
    pat0 = _pattern([(None, 0)] * 4 + [(0x70, 2)] + [(None, 0)] * (total - 5))
    pat1 = _pattern([(None, 0)] * leave_row + [(0x72, 3)]
                    + [(None, 0)] * (total - leave_row - 1))
    pats = [pat0, pat1]
    tracks = [[0] + _STOP, [1] + _STOP, [GT_ORDER_RESTART, 0x00]]
    sims = {2: _sim(0xA00, 0x40, 1), 3: _sim(0x900, 0x40, 1)}
    start = [(0, ((2, +1, 0), (2, -1, 0), (0, +1, 0)))]
    if third is not None:
        pats.append(_pattern([(None, 0)] * third + [(0x74, 2)]
                             + [(None, 0)] * (total - third - 1)))
        tracks[2] = [2] + _STOP
        start = [(0, ((2, +1, 0), (2, -1, 0), (3, +1, 0)))]
    got = collect_pulse_phases(pats, tracks, [1], sims, tri_start=start)
    assert got is not None
    return got


def _voice0_note(got):
    [(_, _, rows)] = [w for w in got[1] if w[0] == 0]
    return rows[4][1]


def test_a_partner_that_leaves_ends_the_hold_and_the_voice_sweeps_on_alone():
    """Voice 1 steps first in a tick ($A00 -> $9C0) and voice 0 puts it back,
    so voice 0, fetching on tick 4 after voice 1's step, opens on $9C0 and
    reads $9C0 on every step. Voice 1 fetches on tick 8 and sweeps record 3
    from then on: voice 0 steps record 2 alone, up from the $9C0 the hold
    left it on. Held for the ticks 5, 6, 7 (n = 3)."""
    got = _leaves(leave_row=8)
    w, d = _voice0_note(got)
    assert w == 0x9C0 and is_hold(d) and hold_steps(d) == 0
    assert hold_then(d) == (3, 0x9C0, +1), hold_then(d)
    assert (0x9C0, +1) not in got[0][2], "the resume phase is the table's to add"


def test_a_partner_that_stays_leaves_the_hold_a_hold():
    got = _leaves(leave_row=99, total=12)
    w, d = _voice0_note(got)
    assert is_hold(d) and hold_steps(d) == 0 and hold_then(d) is None


def test_one_read_after_the_partner_is_not_an_end():
    """A partner's fetch tick leaves the record unrestored for a tick or two
    and the voice reads off its hold and back on it; one read before the note
    ends is as likely that as an end."""
    got = _leaves(leave_row=11, total=12)
    assert hold_then(_voice0_note(got)[1]) is None
    got = _leaves(leave_row=10, total=12)
    assert hold_then(_voice0_note(got)[1]) == (5, 0x9C0, +1)


def test_a_rest_or_a_legato_tie_does_not_end_the_hold():
    """Neither reloads the pulse pointer (the tie's command column is taken,
    so no phase is written there): the table goes on holding through them, and
    so does the walk's reading of the hold -- Monty_on_the_Run's note runs
    through a keyoff row before its partner leaves. A note that does reload it
    ends the hold at its fetch."""
    from h2g.patterns import CMD_TONEPORTA
    pat0 = _pattern([(None, 0)] * 4 + [(0x70, 2), (None, 0), (0x71, 2)]
                    + [(None, 0)] * 5)
    tie = 4 * 6
    assert pat0[tie:tie + 2] == [0x71, 2]
    pat0[tie + 2] = CMD_TONEPORTA
    pat1 = _pattern([(None, 0)] * 8 + [(0x72, 3)] + [(None, 0)] * 3)
    tracks = [[0] + _STOP, [1] + _STOP, [GT_ORDER_RESTART, 0x00]]
    sims = {2: _sim(0xA00, 0x40, 1), 3: _sim(0x900, 0x40, 1)}
    start = [(0, ((2, +1, 0), (2, -1, 0), (0, +1, 0)))]
    got = collect_pulse_phases([pat0, pat1], tracks, [1], sims, tri_start=start)
    [(_, _, rows)] = [w for w in got[1] if w[0] == 0]
    # (Voice 0 does not step on the tick it fetches the tie, so the record
    # is left a step low for the ticks 7 on and the width voice 1's departure
    # puts it back on is read on tick 8: n = 4, not 3.)
    assert hold_then(rows[4][1][1]) == (4, 0x9C0, +1), rows
    # The same row as a plain note (no tie): the hold ends at its fetch, one
    # read short of an end, and the new note opens the hold of its own.
    pat0[tie + 2] = 0
    got = collect_pulse_phases([pat0, pat1], tracks, [1], sims, tri_start=start)
    [(_, _, rows)] = [w for w in got[1] if w[0] == 0]
    assert hold_then(rows[4][1][1]) is None, rows


def test_what_follows_must_be_the_lone_sweep():
    """Voice 2 starts stepping record 2 on tick 9, as voice 1 leaves it: the
    record moves two steps a tick, not the one voice 0 would give it alone,
    so what voice 0 reads after its hold is no sweep of its own and the hold
    stays a hold."""
    got = _leaves(leave_row=8, third=8)
    assert hold_then(_voice0_note(got)[1]) is None


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

def _block(want, resume, multiplier=2, share=False):
    return _phase_block(0, 1, want, 0x880, 0x20, LO, HI, False, 0x40,
                        share=share, multiplier=multiplier, resume=resume)


def test_the_table_holds_n_ticks_and_hands_over_to_the_sweep():
    """-S2, n = 3, wait 0: the attack call and seven calls of rest on $A00
    (eight calls, the four ticks 4..7 less none), the entry's own set row on
    the ninth, then the ramp at 0x20 a call."""
    then = (3, 0xA00, +1)
    d = hold_direction(0, 0, then)
    want = {(0xA00, d), (0xA00, +1)}
    for share in (False, True):
        rows, index = _block(want, True, share=share)
        got = _play_pulse_table(rows, index[(1, 0xA00, d)], 14)
        assert got == [0xA00] * 9 + [0xA20, 0xA40, 0xA60, 0xA80, 0xAA0], got
        # the hand-over is a jump to the sweep's entry, which a call plays
        assert any(r == (0xFF, index[(1, 0xA00, +1)]) for r in rows)


def test_without_resume_the_hold_is_a_hold_to_the_next_command():
    d = hold_direction(0, 0, (3, 0xA00, +1))
    for share in (False, True):
        rows, index = _block({(0xA00, d), (0xA00, +1)}, False, share=share)
        assert _play_pulse_table(rows, index[(1, 0xA00, d)], 30) == [0xA00] * 30


def test_the_wait_and_the_held_width_count_before_the_length():
    """Opens $A40, waits one tick, holds $A00 (k = -1) for n = 2 ticks, then
    sweeps down from $A00 at -S2: opening call + 3 rest calls of the wait
    (`hold_rest`), the held width for n * 2 = 4 calls with the set row,
    then the entry's set row."""
    d = hold_direction(-1, 1, (2, 0xA00, -1))
    want = {(0xA40, d), (0xA00, -1)}
    rows, index = _block(want, True)
    got = _play_pulse_table(rows, index[(1, 0xA40, d)], 14)
    assert got[:4] == [0xA40] * 4
    assert got[4:9] == [0xA00] * 5, got
    assert got[9] == 0x9E0, got


def test_a_hold_whose_sweep_is_not_in_the_record_stays_a_hold():
    d = hold_direction(0, 0, (3, 0xA00, +1))
    rows, index = _block({(0xA00, d)}, True)
    assert _play_pulse_table(rows, index[(1, 0xA00, d)], 30) == [0xA00] * 30


def test_equal_holds_of_different_length_each_get_their_own_rows():
    d3, d5 = (hold_direction(0, 0, (n, 0xA00, +1)) for n in (3, 5))
    rows, index = _block({(0xA00, d3), (0xA00, d5), (0xA00, +1)}, True)
    assert index[(1, 0xA00, d3)] != index[(1, 0xA00, d5)]
    assert _play_pulse_table(rows, index[(1, 0xA00, d3)], 20).count(0xA00) == 9
    assert _play_pulse_table(rows, index[(1, 0xA00, d5)], 20).count(0xA00) == 13


# --------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------

def test_monty_ships_the_hold_that_ends_and_gives_way_when_it_will_not_fit(
        monkeypatch):
    from test_pulse_phase_union import _table_calls
    from h2g.goatwriter import build_pulse_phase_table, constants
    args = _table_calls("Monty_on_the_Run.sid")[0]
    phases = args[5]
    ends = [(w, d) for w, d in phases[11] if is_hold(d) and hold_then(d)]
    assert len(ends) == 1, phases[11]
    (w, d), = ends
    n, w2, d2 = hold_then(d)
    assert (w2, d2) == (0xF00, +1) and n > 100
    key = (11, w, d)
    entries, _, index = build_pulse_phase_table(*args)
    played = _play_pulse_table(entries, index[key], 2 * n + 40)
    assert set(played[:2 * n]) <= {w, 0xF00}, "holds $F00 for n ticks"
    assert played[2 * n + 10] != 0xF00 and played[-1] != 0xF00, \
        "and then the voice sweeps on"
    # One row short: the hold stays a hold for the rest of its note, and the
    # table places every key it placed.
    monkeypatch.setattr(constants, "GT_MAX_TABLELEN", len(entries) - 1)
    short, _, sindex = build_pulse_phase_table(*args)
    assert set(sindex) >= set(index) - {(11, w2, d2)}
    assert len(short) < len(entries)
    assert set(_play_pulse_table(short, sindex[key], 2 * n + 40)) == {0xF00}
