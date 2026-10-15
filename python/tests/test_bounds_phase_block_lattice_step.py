"""The per-record-bounds engine's PHASE table turns on the player's lattice.

`_phase_sweep_params` handed the bounds engine's records no `step` (None), so
`_phase_cycle` returned the record's bounds, `_leg_ramps` took modulo-$1000
distances to them, and `_phase_block` laid its loop, chained legs and entry
pieces on `lo << 8` / `hi << 8` -- while the static program (`_pulse_program`,
task `bounds-engine-lattice-turns`) already turned where the player turns: on
the first width of the rate's lattice whose high nibble EQUALS the bound
(`PulseBoundsSim.advance`, Saboteur_II $F297-$F2F0). It now hands the record's
rate in as the step, and `_leg_ramps` takes the lattice distance for a wrapped
record as it does for the triangle's.

Reachable only under `pulse_phase` (no shipped preset sets it on a bounds
file, so the shipped byte-hash does not move; forced, 14 files do). Census,
presets with `pulse_phase` forced, first three turns of every shipped index
entry of the 14 bounds files against `PulseBoundsSim` (123 entries, 369
turns): exact 99 -> 286, within half a GT speed 121 -> 355, within one speed
217 -> 369.

The player's turns are re-derived here by an independent walk (`_walk`), not
through either sim, so a defect in the sims cannot hide in both readers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corpus import needs_corpus                                       # noqa: E402
from test_bounds_engine_lattice_turns import _det, _sid                # noqa: E402
from test_phase_block_lattice import _turns                            # noqa: E402
from test_pulse_phase import _forced_table_args, _play_pulse_table     # noqa: E402


def _walk(w: int, d: int, rate: int, lo: int, hi: int, turns: int = 3) -> list:
    """The widths a sweep entered at (w, d) turns on: add (or subtract) the
    rate into 12 bits, turn when the high nibble of the result equals the
    bound being approached (`hi` going up, `lo` going down)."""
    x, out = w, []
    for _ in range(turns):
        for _ in range(0x1000 // rate + 3):
            x = (x + d * rate) & 0xFFF
            if x >> 8 == (hi if d > 0 else lo):
                break
        else:
            raise AssertionError("never turns")
        out.append(x)
        d = -d
    return out


def _phases(seed: int, rate: int, lo: int, hi: int, n: int = 40) -> set:
    """The (width, direction) states a free-running sweep from `seed` passes
    through, by the independent walk -- what the orderlist walk plans."""
    out, x, d = {(seed, +1)}, seed, +1
    for _ in range(n):
        x = (x + d * rate) & 0xFFF
        if x >> 8 == (hi if d > 0 else lo):
            d = -d                     # the phase is read AFTER the turn
        out.add((x, d))
    return out


def test_the_bounds_engine_hands_its_rate_in_as_the_step():
    from h2g.goatwriter.pulse import _phase_sweep_params
    for rate, bounds in ((0x40, 0x9F), (0x84, 0x02), (0x24, 0xE8)):
        width, speed, lo_v, hi_v, wrap, step = _phase_sweep_params(
            _sid(0x160, rate, bounds), _det(), 0, 1)
        assert (width, wrap, step) == (0x160, True, rate), (rate, bounds)
        assert (lo_v, hi_v) == ((bounds & 0xF) << 8, (bounds >> 4) << 8)


def test_a_wrapped_record_ramps_the_lattice_distance_not_the_modular_one():
    """Seed $160, rate $40, bounds $9F (so the band wraps; Saboteur_II's
    record 10 has this shape): the player's first top is $920, the first
    lattice width in nibble 9. Without a step the ramp aims at the bound
    ($900 - $160 = $7A0); with one it travels the lattice, $7C0."""
    from h2g.goatwriter.pulse import _leg_ramps
    assert _leg_ramps(0x160, +1, 0xF00, 0x900, True, None) == (0x7A0, 0)
    assert _walk(0x160, +1, 0x40, 0xF, 0x9)[0] == 0x920
    # aimed at the lattice turn the ramp lands ON it
    assert _leg_ramps(0x160, +1, 0xF00, 0x920, True, 0x40) == (0x920 - 0x160, 0)
    # and from the same width heading for the low nibble, through the wrap
    out, back = _leg_ramps(0x160, -1, 0xFE0, 0x920, True, 0x40)
    assert (0x160 - out + back) & 0xFFF == 0xFE0, (hex(out), hex(back))


@pytest.mark.parametrize("lo,hi", [(2, 8), (8, 8), (0xF, 9), (0, 0xF), (5, 5), (3, 0)])
@pytest.mark.parametrize("rate", [0x10, 0x20, 0x40])
def test_every_planned_phase_turns_on_the_players_widths(rate, lo, hi):
    """Rates dividing $1000 keep every phase on one lattice, so each entry's
    first three turns are EXACTLY the player's, banded or wrapped."""
    from h2g.goatwriter.pulse import _phase_block, _phase_sweep_params
    bounds = (hi << 4) | lo
    seed = 0x160
    sid, det = _sid(seed, rate, bounds), _det()
    width, speed, lo_v, hi_v, wrap, step = _phase_sweep_params(sid, det, 0, 1)
    assert speed == rate and step == rate
    want_set = _phases(seed, rate, lo, hi)
    # ... and a note may open anywhere on the lattice, in either bound's
    # nibble included: a phase ON the top nibble heading up steps, turns and
    # comes back (the modular distance to the edge would lap $1000 instead).
    # (A one-nibble band, hi == lo, is left out: every lattice point in it is
    # its own two-point jitter cycle, and one shared loop can hold only one.)
    for nib in (lo, hi) if lo != hi else ():
        for k in range(0, 0x100, rate):
            base = (nib << 8) + k + seed % rate
            want_set |= {(base, +1), (base, -1)}
    rows, index = _phase_block(0, 1, want_set, width, speed, lo_v, hi_v, wrap, step)
    n = 4 * (0x1000 // rate) + 200
    for (w, d) in sorted(want_set):
        got = _turns(_play_pulse_table(rows, index[(1, w, d)], n))[:3]
        want = _walk(w, d, rate, lo, hi)
        assert got == want, (hex(w), d, [hex(t) for t in got], [hex(t) for t in want])


@pytest.mark.parametrize("rate,lo,hi", [(0x54, 2, 8), (0x7F, 0xF, 9), (0x24, 3, 0xE)])
def test_a_rate_that_does_not_divide_the_wrap_stays_within_a_step(rate, lo, hi):
    """Such a rate shifts the lattice at every 12-bit wrap, so a phase can sit
    on a cycle other than the loop's; its entry piece keeps its own turn and
    every turn is within one GT speed (= the rate here) of the player's."""
    from h2g.goatwriter.pulse import _phase_block, _phase_sweep_params
    sid, det = _sid(0x160, rate, (hi << 4) | lo), _det()
    width, speed, lo_v, hi_v, wrap, step = _phase_sweep_params(sid, det, 0, 1)
    want_set = _phases(0x160, rate, lo, hi, 120)
    rows, index = _phase_block(0, 1, want_set, width, speed, lo_v, hi_v, wrap, step)
    n = 5 * (0x1000 // rate) + 200
    for (w, d) in sorted(want_set):
        got = _turns(_play_pulse_table(rows, index[(1, w, d)], n))[:3]
        want = _walk(w, d, rate, lo, hi)
        assert len(got) == 3, (hex(w), d)
        for g, x in zip(got, want):
            assert abs(((g - x + 0x800) & 0xFFF) - 0x800) <= speed, (
                hex(w), d, [hex(t) for t in got], [hex(t) for t in want])


def test_the_bounds_engine_without_a_step_keeps_its_bounds():
    """A caller that passes no step (the old `_phase_sweep_params` shape) still
    lays the loop on the bounds, modular distances and whole ticks."""
    from h2g.goatwriter.pulse import _phase_block, _phase_cycle
    lo_v, hi_v = 0xF00, 0x900
    assert _phase_cycle({(0x160, +1)}, lo_v, hi_v, None) == (lo_v, hi_v)
    rows, index = _phase_block(0, 1, {(0x160, +1)}, 0x160, 0x40, lo_v, hi_v, True, None)
    played = _play_pulse_table(rows, index[(1, 0x160, +1)], 600)
    # whole ticks short of the bounds ($900 top, $F00 bottom), as before
    assert {0x8E0, 0xEE0} <= set(played[40:])
    assert 0x920 not in played          # the lattice turn the step version reaches


def _census(name: str, mult_ok=None):
    """(exact, within_speed, turns) of every index entry of `name`'s forced
    shipped table against the independent walk."""
    from h2g.goatwriter.pulse import _bounds_record, _phase_sweep_params
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args(name)
    entries, starts, index = table
    exact = within = total = 0
    for (num, w, d), at in index.items():
        i = num - 1 - lead
        rec = _bounds_record(sid, det, i)
        p = _phase_sweep_params(sid, det, i, mult)
        _, rate, lo, hi = rec
        assert p[5] == rate
        got = _turns(_play_pulse_table(entries, at, 9000))[:3]
        want = _walk(w, d, rate, lo, hi)
        assert len(got) == 3, (num, hex(w), d)
        for g, x in zip(got, want):
            err = abs(((g - x + 0x800) & 0xFFF) - 0x800)
            exact += err == 0
            within += err <= p[1]
            total += 1
    return exact, within, total


@needs_corpus
@pytest.mark.parametrize("name,entries", [("Pandora.sid", 17), ("Sigma_Seven.sid", 9),
                                           ("Lightforce.sid", 26)])
def test_shipped_tables_of_these_bounds_files_turn_exactly(name, entries):
    exact, within, total = _census(name)
    assert total == 3 * entries and exact == total, (name, exact, within, total)


@needs_corpus
def test_saboteur_iis_shipped_table_turns_within_a_speed():
    """-S3: Saboteur_II's rates do not divide the GT speed, so only 6 of the 39
    turns are exact, but every turn of every entry is within one GT speed of
    the player's (26 of 39 were before)."""
    exact, within, total = _census("Saboteur_II.sid")
    assert total == 39 and within == total, (exact, within, total)
