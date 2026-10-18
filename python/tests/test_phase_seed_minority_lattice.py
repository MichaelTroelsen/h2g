"""A phase on ANOTHER lattice than the record's other phases runs a loop of
its own (`goatwriter.pulse._minority_cycles`, `_phase_block`).

A sweep that never wraps keeps its step lattice for good, and one that wraps
the 12-bit width settles on another (a step that does not divide $1000
shifts the lattice at each lap). Human_Race's records 18 and 23 (step $E0)
seed at ($800, up), which cycles $8E0..$E20 for ever, while 17 of 18 (18 of
19) phases entered through a wrap and cycle $840..$E60. One loop cannot turn
on both: the seed's piece joined the dominant loop and ran its widths off
the player's ($E90 where the player turns at $E20), and the record's
`_union_kind` was None -- so it chained nothing and, at 245 rows, took the
rows record 23 needed. Task `phase-seed-minority-lattice`: the minority
phase's piece ramps to its OWN cycle's edge and joins a private loop on that
cycle, and the record's kind is read over the phases that join the shared
loop.

Figures (4c9dab5 -> this change, presets with `pulse_phase` forced, scripts
and outputs in C:/t/phase-seed-minority-lattice): Human_Race's shipped table
245 -> 197 rows, records 18 and 23 "chained", turns of the first three legs
of every shipped index entry exact 351/354 -> 285/285 (the table now keeps
23 where it kept 21, so fewer entries); Commando's 185 -> 117 rows, 88/90 ->
90/90 exact (record 7 is "chained"); Thing_on_a_Spring 381/393 -> 384/393 and
Trans-Atlantic_Balloon_Challenge's two phases 1/2 -> 2/2 exact.

The player's turns are re-derived by an independent walk (`_walk`), not
through `PulsePhaseSim`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_pulse_phase import _play_pulse_table  # noqa: E402
from test_phase_block_lattice import _turns, _walk  # noqa: E402

STEP, SPEED, LO, HI = 0xE0, 0x70, 0x800, 0xE00
DOMINANT = (0x840, 0xE60)
OWN = (0x8E0, 0xE20)


def _synthetic() -> set:
    """The seed ($800, up) cycles $8E0..$E20; the rest sit on the
    $840..$E60 lattice ($840 + k * $E0)."""
    return {(0x800, +1), (0x920, +1), (0xA00, +1), (0xAE0, -1), (0xBC0, -1)}


def _record(num: int):
    from test_pulse_phase_union import _table_calls
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = _table_calls("Human_Race.sid")[0]
    params = P._phase_sweep_params(sid, det, num - 1 - lead, mult)
    return P, params, set(phases[num]) | {(params[0], +1)}


def test_the_walks_the_test_relies_on():
    assert _walk(0x800, +1, STEP)[:3] == [0xE20, 0x8E0, 0xE20]
    assert _walk(0x920, +1, STEP)[:3] == [0xE60, 0x840, 0xE60]


def test_only_the_seed_is_a_minority_and_no_step_means_none():
    from h2g.goatwriter.pulse import _minority_cycles, _phase_cycle
    want = _synthetic()
    assert _phase_cycle(want, LO, HI, STEP) == DOMINANT
    assert _minority_cycles(want, DOMINANT, STEP) == {(0x800, +1): OWN}
    assert _minority_cycles(want, DOMINANT, None) == {}
    assert _minority_cycles(want, DOMINANT, 0) == {}
    # a hold moves nowhere and is never a minority
    from h2g.goatwriter.pulse import hold_direction
    assert _minority_cycles({(0x800, hold_direction(1))}, DOMINANT, STEP) == {}


@pytest.mark.parametrize("share", [False, True])
def test_every_entry_of_a_synthetic_block_turns_where_the_player_does(share):
    """Both layouts: the seed's entry plays $E20 / $8E0 / $E20 (its own loop),
    every other entry $E60 / $840 ... (the dominant one)."""
    from h2g.goatwriter.pulse import _phase_block
    want = _synthetic()
    rows, index = _phase_block(0, 1, want, 0x800, SPEED, LO, HI, False, STEP,
                               share)
    for (w, d) in sorted(want):
        played = _play_pulse_table(rows, index[(1, w, d)], 3000)
        want_turns = _walk(w, d, STEP, 3)
        assert _turns(played)[:3] == want_turns, (hex(w), d, share)


def test_a_record_with_no_minority_lays_what_it_always_laid(monkeypatch):
    from h2g.goatwriter import pulse as P
    want = {(0x920, +1), (0xA00, +1), (0xAE0, -1), (0xBC0, -1)}
    assert P._minority_cycles(want, DOMINANT, STEP) == {}
    for share in (False, True):
        got = P._phase_block(0, 1, want, 0x920, SPEED, LO, HI, False, STEP, share)
        monkeypatch.setattr(P, "_minority_cycles", lambda w, c, s: {})
        assert P._phase_block(0, 1, want, 0x920, SPEED, LO, HI, False, STEP,
                              share) == got


def test_the_private_loop_is_laid_once_per_cycle():
    """A second phase on the same own cycle costs its piece (set row, ramp,
    jump) and no second loop."""
    from h2g.goatwriter.pulse import _minority_cycles, _phase_block
    one = _synthetic()
    two = one | {(0x8E0, +1)}
    assert set(_minority_cycles(two, DOMINANT, STEP)) == {(0x800, +1), (0x8E0, +1)}
    rows1, _ = _phase_block(0, 1, one, 0x920, SPEED, LO, HI, False, STEP)
    rows2, idx2 = _phase_block(0, 1, two, 0x920, SPEED, LO, HI, False, STEP)
    assert len(rows2) - len(rows1) == 3
    for (w, d) in ((0x800, +1), (0x8E0, +1)):
        assert _turns(_play_pulse_table(rows2, idx2[(1, w, d)], 3000))[:3] ==             _walk(w, d, STEP, 3)


def test_human_races_seed_records_chain_and_union():
    P, params, want = _record(18)
    assert P._phase_cycle(want, *params[2:4], params[5]) == DOMINANT
    assert P._minority_cycles(want, DOMINANT, params[5]) == {(0x800, +1): OWN}
    assert P._union_kind(want, *params[1:]) == "chained"
    assert (0x800, +1) not in P._chained_phases(want, *params[1:])
    P, params, want = _record(23)
    assert P._minority_cycles(want, DOMINANT, params[5]) == {(0x800, +1): OWN}
    assert P._union_kind(want, *params[1:]) == "chained"


def test_human_races_shipped_table_turns_exactly_and_is_smaller():
    """Every index entry of the shipped table (18 and 23 among them): its
    first three turns are the player's. 285 of 285 where 351 of 354 were;
    197 rows where it took 245, record 23 swept in 21's place. Re-pinned by
    lay-pulse-phase-table-adopts-union-groups: 242 rows, 6 records, both
    unions adopted; the exactness check below runs over every entry."""
    from test_pulse_phase import _forced_table_args
    from h2g.goatwriter import pulse as P
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args("Human_Race.sid")
    entries, starts, index = table
    assert len(entries) == 242
    assert {k[0] for k in index} == {1, 2, 4, 18, 21, 23}
    bad = []
    for (num, w, d), at in sorted(index.items()):
        step = P._phase_sweep_params(sid, det, num - 1 - lead, mult)[5]
        got = _turns(_play_pulse_table(entries, at, 9000))[:3]
        if got != _walk(w, d, step, 3):
            bad.append((num, hex(w), d, [hex(x) for x in got]))
    assert not bad, bad


def test_commando_record_7_chains_and_the_table_shrinks():
    from test_pulse_phase import _forced_table_args
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args("Commando.sid")
    entries, starts, index = table
    assert len(entries) == 117
    from h2g.goatwriter import pulse as P
    bad = []
    for (num, w, d), at in sorted(index.items()):
        step = P._phase_sweep_params(sid, det, num - 1 - lead, mult)[5]
        got = _turns(_play_pulse_table(entries, at, 9000))[:3]
        if got != _walk(w, d, step, 3):
            bad.append((num, hex(w), d, [hex(x) for x in got]))
    assert not bad, bad


def test_trans_atlantic_bounds_record_plays_both_phases_exactly():
    """The bounds engine passes its rate as the step, so its two phases
    ($100 and $A80, rate 6) sit on cycles $FA..$802 and $FE..$800: the
    second ran $F8 until it had its own loop."""
    from test_pulse_phase import _forced_table_args
    from h2g.goatwriter import pulse as P
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args(
        "Trans-Atlantic_Balloon_Challenge.sid")
    entries, starts, index = table
    assert sorted(index) == [(10, 0x100, +1), (10, 0xA80, +1)]
    got = {(w, d): [hex(x) for x in _turns(_play_pulse_table(entries, at, 6000))[:3]]
           for (num, w, d), at in index.items()}
    assert got == {(0x100, +1): ["0x802", "0xfa", "0x802"],
                   (0xA80, +1): ["0x800", "0xfe", "0x800"]}, got


from corpus import folds_unread  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _folds_as_measured(folds_unread):
    """The layouts here were measured before the folded accumulate spelling
    was read; see `corpus.folds_unread`."""
