"""The triangle's phase blocks turn where the sweep turns: on the nibble
lattice (`goatwriter.pulse._phase_cycle`, `_phase_turns`, `_phase_block`).

The routine adds its step into a 12-bit width and turns when the high nibble
AFTER the step equals the bound it is heading for (`PulsePhaseSim.advance`),
so it cycles between the first lattice width inside the low nibble and the
first inside the high one -- Game_Killer's record 3 (step $E0) between $8E0
and $E20, 1344 a leg. `_phase_block` laid its loop, its chained legs and the
edge its entry pieces ramp to on the BOUNDS ($800..$E00): the loop spanned
1518 against 1344, and every phase-tracked record turned a nibble off the
player's widths. Task `phase-block-legs-on-the-nibble-lattice` (the static
program's half is `tests/test_triangle_lattice_turns.py`).

Census at f75cc7f + this change, presets with `pulse_phase` forced, the
first three turns of every shipped index entry against `PulsePhaseSim`
(23 files, scripts in the task's scratch directory): within half a GT speed
1851 of 4503 before, 4647 of 4704 after; exact 1701 before, 4151 after. The
rest are speeds that do not divide the step and the $E0 steps clamped at
127 (Commando, Zoids, Gerry_the_Germ 18).

The player's turns are re-derived here by an independent walk (`_walk`), not
through `PulsePhaseSim`, so a defect in the sim cannot hide in both readers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_pulse_phase import _forced_table_args, _play_pulse_table  # noqa: E402

LO, HI = 0x800, 0xE00


def _walk(w: int, d: int, step: int, turns: int = 4) -> list:
    """The widths a sweep entered at (w, d) turns on, by the routine's own
    rule: step, then turn when the high nibble equals the bound being
    approached (8 going down, E going up)."""
    x, out = w, []
    for _ in range(turns):
        for _ in range(0x1000 // step + 2):
            x = (x + d * step) & 0xFFF
            if x >> 8 == (0xE if d > 0 else 0x8):
                break
        else:
            raise AssertionError("never turns")
        out.append(x)
        d = -d
    return out


def _turns(widths: list) -> list:
    """Where a played table reverses, modulo the 12-bit wrap."""
    out, last = [], 0
    sg = lambda a, b: 0 if a == b else (1 if ((b - a + 0x800) & 0xFFF) < 0x800 else -1)  # noqa: E731
    for a, b, c in zip(widths, widths[1:], widths[2:]):
        if b != a:
            last = sg(a, b)
        if c != b and last and sg(b, c) != last:
            out.append(b)
    return out


def test_phase_turns_and_cycle_agree_with_the_independent_walk():
    from h2g.goatwriter.pulse import _phase_cycle, _phase_turns
    for step in range(0x10, 0x100, 0x10):
        for w in range(0, 0x1000, 0x2C):
            for d in (+1, -1):
                want = _walk(w, d, step)
                assert _phase_turns(w, d, step, 8, 14) == tuple(want), (hex(w), d, step)
                cyc = (want[1], want[2]) if d > 0 else (want[2], want[3])
                assert _phase_cycle({(w, d)}, LO, HI, step) == cyc, (hex(w), d, step)


def test_the_cycle_is_the_one_most_phases_reach_and_a_tie_goes_to_the_lowest():
    from h2g.goatwriter.pulse import _phase_cycle
    # step $E0: ($9C0, up) cycles $8E0..$E20, ($800, down) wraps onto $840..$E60
    a, b = (0x9C0, +1), (0x800, -1)
    assert _phase_cycle({a}, LO, HI, 0xE0) == (0x8E0, 0xE20)
    assert _phase_cycle({b}, LO, HI, 0xE0) == (0x840, 0xE60)
    assert _phase_cycle({a, (0xAA0, +1), b}, LO, HI, 0xE0) == (0x8E0, 0xE20)
    assert _phase_cycle({b, (0x700, -1), a}, LO, HI, 0xE0) == (0x820, 0xE40)  # 3-way tie
    assert _phase_cycle({a, b}, LO, HI, 0xE0) == (0x840, 0xE60)       # tie: lowest


def test_the_bounds_engine_keeps_its_bounds():
    """`step` is what says which engine: without it the loop edges are the
    bounds, whatever the phases."""
    from h2g.goatwriter.pulse import _phase_block, _phase_cycle
    assert _phase_cycle({(0x9C0, +1)}, LO, HI, None) == (LO, HI)
    assert _phase_cycle({(0x9C0, +1)}, LO, HI, 0) == (LO, HI)
    rows, index = _phase_block(0, 1, {(0xA00, +1)}, 0xA00, 0x40, LO, HI, True, None)
    played = _play_pulse_table(rows, index[(1, 0xA00, +1)], 600)
    assert min(played[40:]) == LO and max(played[40:]) == HI


def test_leg_ramps_aim_at_the_edge_from_either_side():
    """The overshoot is signed: an arrival short of the edge climbs on to it,
    one past it comes back, and the same going down (a phase ON the low
    nibble whose first step stays in it steps down and comes back up)."""
    from h2g.goatwriter.pulse import _leg_ramps
    # up: ($800) climbs $8E0 ... $E20 in 7 steps of $E0 = $620
    assert _leg_ramps(0x800, +1, 0x8E0, 0xE20, False, 0xE0) == (0x620, 0)   # on the edge
    assert _leg_ramps(0x800, +1, 0x8E0, 0xE60, False, 0xE0) == (0x660, 0)   # short: on to it
    assert _leg_ramps(0x800, +1, 0x8E0, 0xE00, False, 0xE0) == (0x620 - 0x20, 0)  # past: back
    # down: ($9C0) steps to $8E0 and turns
    assert _leg_ramps(0x9C0, -1, 0x8E0, 0xE20, False, 0xE0) == (0xE0, 0)
    assert _leg_ramps(0x9C0, -1, 0x8F0, 0xE20, False, 0xE0) == (0xE0 - 0x10, 0)   # short of the edge
    assert _leg_ramps(0x9C0, -1, 0x8C0, 0xE20, False, 0xE0) == (0xE0 + 0x20, 0)   # past it
    # down, the edge is the phase itself: one step ($800, still nibble 8),
    # turn, and back up to it
    assert _leg_ramps(0x8E0, -1, 0x8E0, 0xE20, False, 0xE0) == (0xE0, 0xE0)
    # up on the top: $E00 climbs to $E80 and comes back down to the edge
    assert _leg_ramps(0xE00, +1, 0x880, 0xE00, False, 0x80) == (0x80, 0x80)


def _sim_phases(seed: int, step: int) -> set:
    """Every (width, direction) the sweep from `seed` passes through over
    four full cycles -- the phases a note can open on."""
    from h2g.goatwriter.pulse import PulsePhaseSim
    sim = PulsePhaseSim(seed, step, 1, 8, 14)
    out = {sim.phase()}
    for _ in range(4 * 2 * 0x600 // step):
        sim.advance(1)
        out.add(sim.phase())
    return out


def _sim_run(w: int, d: int, step: int, calls: int) -> list:
    from h2g.goatwriter.pulse import PulsePhaseSim, PulseVoiceCell
    sim = PulsePhaseSim(w, step, 1, 8, 14, PulseVoiceCell(d, 0))
    out = [w]
    for _ in range(calls - 1):
        sim.advance(1)
        out.append(sim.width)
    return out


def test_every_phase_entry_plays_the_sweep_call_for_call_where_speed_is_step():
    """-S1, delay 1, step <= 127: the GT speed IS the step, so a table
    entered at any phase of the sweep plays, call for call over three full
    cycles, the widths `PulsePhaseSim` plays from that phase -- per-phase
    blocks, and the shared layout wherever the record chains. The loop,
    the legs and the piece all turn on the lattice: laid bound to bound the
    first turn is already a nibble off for every step here."""
    from h2g.goatwriter.pulse import _phase_block, _union_kind
    chained_seen = 0
    for step in (0x20, 0x30, 0x40, 0x50, 0x60, 0x70):
        for seed in (0x800, 0x9C0, 0xA30, 0xE00 - step):
            phases = _sim_phases(seed, step)
            calls = 3 * 2 * 0x600 // step + 8
            kind = _union_kind(phases, step, LO, HI, False, step)
            for share in (False, True):
                rows, index = _phase_block(0, 1, phases, seed, step, LO, HI, False,
                                           step, share)
                for (w, d) in phases:
                    got = _play_pulse_table(rows, index[(1, w, d)], calls)
                    assert got == _sim_run(w, d, step, calls), (
                        hex(step), hex(seed), hex(w), d, share)
            chained_seen += kind == "chained"
    assert chained_seen, "no (step, seed) chained: the shared legs were never exercised"


def test_the_loop_spans_the_lattice_cycle_not_the_bounds():
    """Step $E0 at two calls a step (speed $70, which divides it): the table
    entered at ($9C0, up) turns on $E20, $8E0, $E20, $8E0 -- 12 ticks of $70
    a leg, 1344 -- where the bounds gave a 13-tick leg ending on $E00 and
    $800 + 1 tick."""
    from h2g.goatwriter.pulse import _phase_block
    step, speed = 0xE0, 0x70
    rows, index = _phase_block(0, 1, {(0x9C0, +1)}, 0x9C0, speed, LO, HI, False, step)
    turns = _turns(_play_pulse_table(rows, index[(1, 0x9C0, +1)], 400))
    assert turns[:4] == [0xE20, 0x8E0, 0xE20, 0x8E0], [hex(t) for t in turns]


def test_game_killers_shipped_table_turns_on_8e0_and_e20():
    """The real table, record 3 and 8 (step $E0, speed 22): every index entry
    reaches its first three turns within one speed of the player's (68 of the
    72 within half; an entry piece and the loop each round to the nearest
    tick), and the loop is 61 ticks of 22 a leg -- 1342 against the
    player's 1344."""
    from h2g.goatwriter.pulse import _phase_sweep_params
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args("Game_Killer.sid")
    entries, starts, index = table
    checked = half = 0
    for (num, w, d), at in index.items():
        width, speed, lo_v, hi_v, wrap, step = _phase_sweep_params(sid, det, num - 1 - lead, mult)
        assert (speed, step) == (22, 0xE0)
        want = _walk(w, d, step, 3)
        got = _turns(_play_pulse_table(entries, at, 6000))[:3]
        assert len(got) == 3, (num, hex(w), d)
        for g, x in zip(got, want):
            err = abs(((g - x + 0x800) & 0xFFF) - 0x800)
            assert err <= speed, (num, hex(w), d, [hex(t) for t in got],
                                  [hex(t) for t in want])
            half += 2 * err <= speed
        checked += 1
    assert checked == 24 and half == 68, (checked, half)   # of 72 turns
    assert {x for (_, w, d) in index for x in _walk(w, d, 0xE0, 4)[1:]} == {0x8E0, 0xE20}


def test_last_v8s_shipped_table_turns_exactly():
    """Last_V8 (speed divides every step): all 103 index entries of the
    shipped table reach their first three turns on the player's widths --
    63 of 243 on the bound-to-bound loops."""
    from h2g.goatwriter.pulse import _phase_sweep_params
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args("Last_V8.sid")
    entries, starts, index = table
    assert len(index) == 103
    for (num, w, d), at in index.items():
        width, speed, lo_v, hi_v, wrap, step = _phase_sweep_params(sid, det, num - 1 - lead, mult)
        want = _walk(w, d, step, 3)
        got = _turns(_play_pulse_table(entries, at, 9000))[:3]
        assert got == want, (num, hex(w), d, [hex(t) for t in got], [hex(t) for t in want])


def test_records_on_different_lattices_do_not_share_a_union():
    """A union is laid over ONE loop, so records of one sweep join it only on
    the same cycle: Gremlins' records 3 and 7 (step $40, speed 32) turn on
    $8E0..$E20 and $8C0..$E00 and are no longer offered together; 6 and 20
    still are."""
    from h2g.goatwriter import pulse as P
    from test_pulse_phase_union import _table_calls
    sid, det, iu, pulse, mult, phases, _, lead = _table_calls("Gremlins.sid")[0]
    cycles = {}
    for n in (3, 7):
        p = P._phase_sweep_params(sid, det, n - 1 - lead, mult)
        cycles[n] = P._phase_cycle(set(phases[n]) | {(p[0], +1)}, p[2], p[3], p[5])
    assert cycles == {3: (0x8E0, 0xE20), 7: (0x8C0, 0xE00)}, cycles
    groups = P._union_groups(sid, det, iu, mult, phases, lead)
    assert sorted(sorted(m) for m in groups.values()) == [[6, 20]]
