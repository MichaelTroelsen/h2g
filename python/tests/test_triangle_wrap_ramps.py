"""The triangle engine's phase ramps outside its band (`_leg_ramps`).

`_phase_block` used to clamp a triangle phase's distance to its bound at
zero, so a phase outside the band -- below the low nibble going down, above
the high nibble going up, or on a bound heading out of it -- laid an empty
ramp and joined the loop at once, turning where the player's sweep runs on
through the 12-bit wrap until the high nibble EQUALS the bound
(`PulsePhaseSim.advance`). Opened by triangle-lockstep-walk at 8586101:
Human_Race's instrument 2 at ($080, down) should play $080 $000 $F80 and the
table played $080 $0C0 $100; Devils_Galop's $F00+/$E00+ phases read a step
down at the -S2 attack (57 of 551 on v0 and 1 of 61 on v1 commanded but
wrong).

What a reached count does NOT say, measured with this change (presets,
`pulse_phase` forced, 180 s, packed trace against the original's, frame by
frame from each paired attack): Devils_Galop's instrument 10 is swept by v0
(planned $F00 up) and v1 ($F00 down) on the same notes, and the original
HOLDS $F00 through them -- two voices stepping one record in opposite
directions. The wrap ramp now climbs where the table used to descend; the
attack frame agrees either way and the frames after it agree in neither,
57 of 588 before and after. The per-voice phase cannot say "hold".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402

LO, HI = 0x800, 0xE00


def _clamp(w: int, d: int) -> int:
    return max(0, HI - w) if d > 0 else max(0, w - LO)


def test_inside_the_band_the_ramps_are_the_clamps():
    """Every phase whose sweep stays in the band ramps exactly as the clamp
    did, at every step the triangle's masks allow: the change is confined
    to the phases outside it. Strictly inside (nibbles 9-D) both
    directions; on the low nibble going up, the high one going down."""
    from h2g.goatwriter.pulse import _leg_ramps
    for step in range(0x10, 0x100, 0x10):
        for w in range(0, 0x1000, 0x10):
            nib = w >> 8
            for d in (+1, -1):
                inside = (LO >> 8) < nib < (HI >> 8)
                inside |= (nib == LO >> 8 and d > 0) or (nib == HI >> 8 and d < 0)
                if inside:
                    assert _leg_ramps(w, d, LO, HI, False, step) == (_clamp(w, d), 0), \
                        (hex(w), d, hex(step))


def test_the_named_phases_ramp_the_way_the_sweep_runs():
    """The four shapes, as distances: below the band going down wraps
    ($080 -> nibble 8 is $880 of travel); above it going up wraps ($F00 ->
    nibble E is $F00); on the low nibble going down, a first step that
    leaves the nibble laps $1000 (Commando's $800, step $E0); on the high
    nibble going up, a first step that stays in it climbs one step and
    comes back ($E00, step $80). The bounds engine is untouched: modulo
    $1000, never back."""
    from h2g.goatwriter.pulse import _leg_ramps
    assert _leg_ramps(0x080, -1, LO, HI, False, 0x80) == (0x880, 0)
    assert _leg_ramps(0xF00, +1, LO, HI, False, 0x80) == (0xF00, 0)
    assert _leg_ramps(0x800, -1, LO, HI, False, 0xE0) == (0x1000, 0)
    assert _leg_ramps(0xE00, +1, LO, HI, False, 0x80) == (0x80, 0x80)
    assert _leg_ramps(0xEC0, +1, LO, HI, False, 0x80) == (0xF40, 0)   # $F40: laps
    assert _leg_ramps(0x080, -1, LO, HI, True, None) == (0x880, 0)
    assert _leg_ramps(0xE40, +1, 0x200, 0xE00, True, None) == (0xFC0, 0)


def _sim_until_turn_up(w: int, d: int, step: int, calls: int) -> list:
    """The player's widths from a note opening on (w, d), one tick a call,
    up to and including the tick its sweep first turns from down to up --
    where the table's convention (descend to `lo_v`) leaves it."""
    from h2g.goatwriter.pulse import PulsePhaseSim, PulseVoiceCell
    sim = PulsePhaseSim(w, step, 1, LO >> 8, HI >> 8, PulseVoiceCell(d, 0))
    out = [w]
    for _ in range(calls):
        was = sim.direction
        sim.advance(1)
        out.append(sim.width)
        if was < 0 and sim.direction > 0:
            break
    return out


def test_an_out_of_band_entry_plays_the_sweep_until_its_low_turn():
    """Played from its own entry point, every out-of-band phase's block
    plays, call for call, the widths the single-voice sweep plays, through
    the wrap and the high turn, up to the sweep's first turn at the low
    nibble (one tick a call, step == speed). The clamp's block failed every
    one of these at the second call."""
    from h2g.goatwriter.pulse import _phase_block
    step = 0x40
    for (w, d) in [(0x080, -1), (0x400, -1), (0x7C0, -1), (0x800, -1),
                   (0xF00, +1), (0xEC0, +1), (0xE00, +1), (0xE40, +1)]:
        rows, index = _phase_block(0, 1, {(w, d)}, w, step, LO, HI, False, step)
        want = _sim_until_turn_up(w, d, step, 400)
        got = _play_pulse_table(rows, index[(1, w, d)], len(want))
        assert got == want, (hex(w), d, [hex(x) for x in got[:8]], [hex(x) for x in want[:8]])


def test_a_lap_on_a_bound_does_not_chain_and_still_lands():
    """A phase ON a bound heading out of the band is on the speed lattice
    but on no leg, so `_chained_phases` leaves it out -- chained, ($800,
    down) would end the down leg and turn at once where the sweep laps --
    and its own piece arrives ON the bound, so the record stays
    "chained" and keeps its unions (Human_Race 1+2, Monty_on_the_Run
    1+10+11; tests/test_pulse_phase_union.py)."""
    from h2g.goatwriter.pulse import _chained_phases, _union_kind
    want = {(0x800, +1), (0x900, +1), (0xA00, -1), (0x800, -1), (0xE00, +1)}
    assert _chained_phases(want, 0x40, LO, HI, False, 0x80) == {(0x800, +1), (0x900, +1),
                                                                (0xA00, -1)}
    assert _union_kind(want, 0x40, LO, HI, False, 0x80) == "chained"
    # the clamp's reading of the same set, kept for a hand-built tuple
    assert _chained_phases(want, 0x40, LO, HI) == want


def _shipped_table(name: str) -> tuple:
    from test_pulse_phase_union import _table_calls
    from h2g.goatwriter import build_pulse_phase_table
    args = _table_calls(name)[0]
    return build_pulse_phase_table(*args)


def test_the_shipped_tables_open_the_named_phases_the_sweeps_way():
    """In the tables convert.py ships (presets, `pulse_phase` forced), the
    out-of-band entries named by the opening task now move the way the
    original's sweep does on their first calls. Before: Human_Race $080
    $0C0 $100, Devils_Galop $F00 $EE0 and $E00 $DE0, Commando $800 $87F."""
    cases = {
        "Human_Race.sid": {(2, 0x080, -1): [0x080, 0x040, 0x000, 0xFC0, 0xF80]},
        "Devils_Galop.sid": {(10, 0xF00, +1): [0xF00, 0xF20, 0xF40, 0xF60, 0xF80],
                             (10, 0xE00, +1): [0xE00, 0xE20, 0xE40, 0xE60, 0xE80,
                                               0xE60, 0xE40, 0xE20, 0xE00, 0xDE0]},
        "Commando.sid": {(7, 0x800, -1): [0x800, 0x781, 0x702, 0x683]},
    }
    for name, want in cases.items():
        entries, _, index = _shipped_table(name)
        for key, widths in want.items():
            assert key in index, (name, key)
            assert _play_pulse_table(entries, index[key], len(widths)) == widths, (name, key)


def test_devils_galops_out_of_band_phases_reach_the_packed_attack():
    """The opening task's count, re-measured: Devils_Galop's commanded but
    wrong attacks go 57 -> 0 on v0 and 1 -> 0 on v1 (494/551 -> 551/551,
    60/61 -> 61/61). Monty_on_the_Run's v0 goes 387 -> 401 of 405: its 2
    wrong go to 0, and its record 10 now chains and unions with 1 and 11,
    which frees the rows record 16 needed, so 12 of its 16 un-commanded
    notes get their command (v1 went 1 -> 0 of 61 the other way, and
    reaches 61 of 61 since v0.5.514's presets regeneration raised Monty's
    max_rows 94 -> 128). Same rule as `test_triangle_lockstep._reach`. The module docstring says what
    this count does not say about the frames after the attack."""
    from test_triangle_lockstep import _reach
    # Voice 2 was 33/33 before tie_restart's adoption (v0.5.516): its first
    # note's row now carries no CMD_SETPULSEPTR, but the packed width at the
    # attack is $A41, the planned $A40 by this count's own rule -- the clone
    # keeps the running sweep, so the width is right and only the command
    # the count requires is gone.
    assert _reach("Devils_Galop.sid") == {(0, 0): (551, 551), (0, 1): (61, 61),
                                          (0, 2): (32, 33)}
    got = _reach("Monty_on_the_Run.sid")
    assert (got[(0, 0)], got[(0, 1)]) == ((401, 405), (61, 61)), got
