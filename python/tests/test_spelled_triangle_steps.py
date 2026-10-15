"""A triangle step above 127 a call is SPELLED, not clamped
(`goatwriter.pulse._ramp_rows`, `_tri_table_speed`).

A Goattracker pulse speed is a signed byte, so one modulation row moves the
width at most 127 a call; the player's `$E0` step reaches 224. At `-S1` that
step was emitted at 127 and swept 1.8x slow (Commando's records 0 and 6,
Zoids' 0 and 14, Gerry_the_Germ's 17). A set-width row spends its call setting
the width (gplay.c:874-879, player.s `mt_setpulse`), so a row PER CALL plays
the widths a faster modulation row would have. Measured at 1172704 + this
change (presets, packed at -S1, original at -m1, 180 s, 48 frames after each
paired attack, tolerance the clamped speed's for both): notes whose original
sweep turns inside the window agree on Commando 1038 -> 3788 of 4728, Zoids
443 -> 1826 of 1944 and the Gerry_the_Germ subtunes 3167 -> 9910 of 12108 in
all (26% -> 82%).

The widths the player plays are re-derived here by an independent walk
(`_walk`: add the step, mask to 12 bits, turn when the high nibble equals the
bound), not through `PulsePhaseSim`, so a defect in the sim cannot hide in
both readers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import needs_corpus                              # noqa: E402
from test_pulse_phase import _play_pulse_table               # noqa: E402
from h2g.goatwriter.pulse import (SPELLED_SPEED_MIN,         # noqa: E402
                                  _phase_block, _pulse_triangle,
                                  _ramp_rows, _tri_call_speed, _tri_speed,
                                  _tri_table_speed)

LO, HI = 0x08, 0x0E


def _walk(width: int, direction: int, step: int, calls: int) -> list:
    """The widths the routine plays from a note opening on (width,
    direction): `width` on the first call, then one step a call, turning when
    the high nibble after the step equals the bound it is heading for
    (`ADC #$00 / AND #$0F / CMP #$0E / BNE`, Commando $5275-$527C)."""
    out, x, d = [width], width, direction
    for _ in range(calls - 1):
        x = (x + d * step) & 0xFFF
        out.append(x)
        if x >> 8 == (HI if d > 0 else LO):
            d = -d
    return out


def test_a_slow_ramp_is_the_modulation_row_it_always_was():
    assert _ramp_rows(0x800, 5, +1, 0x40) == [(5, 0x40)]
    assert _ramp_rows(0x800, 5, -1, 0x40) == [(5, 0xC0)]
    assert _ramp_rows(0x800, 200, +1, 0x7F) == [(0x7F, 0x7F), (73, 0x7F)]
    assert _ramp_rows(0x800, 0, +1, 0x40) == []


def test_a_fast_ramp_is_a_set_row_a_call_and_wraps_at_fff():
    assert _ramp_rows(0x800, 3, +1, 0xE0) == [(0x88, 0xE0), (0x89, 0xC0),
                                              (0x8A, 0xA0)]
    assert _ramp_rows(0x800, 2, -1, 0xE0) == [(0x87, 0x20), (0x86, 0x40)]
    # across $FFF: $F40 + $E0 = $1020 -> $020, + $E0 = $100
    assert _ramp_rows(0xF40, 2, +1, 0xE0) == [(0x80, 0x20), (0x81, 0x00)]


def test_the_table_speed_is_spelled_only_where_the_clamp_costs_over_5_percent():
    # -S1, delay 1, no outer gate: the step itself, a step a call
    assert _tri_table_speed(224, 1, 1, None) == 224
    assert _tri_table_speed(192, 1, 1, None) == 192
    assert _tri_table_speed(160, 1, 1, None) == 160
    # 128 clamps to 127: 0.8% slow, below SPELLED_SPEED_MIN
    assert SPELLED_SPEED_MIN == 134
    assert _tri_table_speed(128, 1, 1, None) == 127
    # a slower clock brings it under the byte on its own
    assert _tri_table_speed(224, 1, 2, None) == 112
    assert _tri_table_speed(224, 2, 1, None) == 112
    # gated and ticked clocks divide as they always did
    assert _tri_table_speed(224, 1, 9, 9) == _tri_speed(224, 1, 9, 9) == 22
    # `_tri_speed` is still the clamped figure
    assert _tri_call_speed(224, 1, 1, None) == 224
    assert _tri_speed(224, 1, 1, None) == 127


def test_a_fast_triangle_program_plays_the_players_widths_call_for_call():
    """`_pulse_triangle` at speed == step above the byte: every call of the
    first 4000 is the width the routine has, for every seed and every step
    from $90 to $F0."""
    for step in range(0x90, 0x100, 0x10):
        for width in range(0, 0xE00, 0x61):
            entries, loop = _pulse_triangle(width, LO, HI, step, step)
            assert all(l >= 0x80 for l, _ in entries), (hex(width), step)
            got = _play_pulse_table(entries + [(0xFF, loop + 1)], 1, 4000)
            assert got == _walk(width, +1, step, 4000), (hex(width), step)


def test_the_fast_loop_costs_a_row_a_call():
    """A $900 seed at step $E0 first turns on $E60 and then cycles
    $820..$E40, seven calls a leg: the loop is fourteen set rows where the
    clamped program was two modulation rows."""
    step = 0xE0
    entries, loop = _pulse_triangle(0x900, LO, HI, step, step)
    walk = _walk(0x900, +1, step, 400)[20:]
    leg = (max(walk) - min(walk)) // step
    assert (min(walk), max(walk), leg) == (0x820, 0xE40, 7)
    assert len(entries) - loop == 2 * leg


def _block_plays(share: bool, step: int, phases: list, calls: int = 40):
    lo_v, hi_v = LO << 8, HI << 8
    rows, index = _phase_block(0, 1, set(phases), phases[0][0], step,
                               lo_v, hi_v, False, step, share=share)
    assert all(l >= 0x80 or l == 0xFF for l, _ in rows)
    for (w, d) in phases:
        want = _walk(w, d, step, calls)
        got = _play_pulse_table(rows, index[(1, w, d)], calls)
        assert got == want, (share, hex(w), d, [hex(x) for x in got[:9]],
                             [hex(x) for x in want[:9]])


def test_a_phase_block_on_the_lattice_plays_the_walk_per_phase_and_shared():
    """Every phase on the $8E0 lattice, both directions, in the per-phase
    layout and in the shared chain: each entry plays the widths the player
    plays from it."""
    step = 0xE0
    on = [0x8E0 + step * k for k in range(7)]          # 8E0 .. E20
    phases = [(w, d) for w in on for d in (+1, -1)
              if not (w == on[-1] and d > 0) and not (w == on[0] and d < 0)]
    _block_plays(False, step, phases)
    _block_plays(True, step, phases)


def test_a_phase_off_the_lattice_plays_the_walk_from_its_own_piece():
    """Alone in its record, a phase outside the band or off the cycle's
    lattice -- one that laps $1000 (`$800` down), wraps (`$080` down,
    `$F00` up) or climbs a step and comes back (`$E00` up, `back` != 0) --
    plays the walk call for call, in the pieces' set rows."""
    for ph in [(0xE00, +1), (0x800, -1), (0x080, -1), (0xF00, +1),
               (0x840, -1), (0xA00, +1), (0x900, -1)]:
        _block_plays(False, 0xE0, [ph], 200)


def test_a_sparse_chain_ramps_between_its_phases_in_set_rows():
    """Phases two to four lattice points apart: the chain lays the points
    between them as set rows (one tick short of each phase's own row, as the
    modulation chain does), and every entry still plays the walk."""
    step = 0xE0
    on = [0x8E0 + step * k for k in range(7)]
    _block_plays(True, step, [(on[1], +1), (on[4], +1), (on[2], -1),
                              (on[5], -1), (on[0], +1), (on[6], -1)], 60)


def test_the_shared_chain_is_shorter_than_one_piece_a_phase():
    step = 0xE0
    on = [0x8E0 + step * k for k in range(7)]
    phases = {(w, d) for w in on for d in (+1, -1)
              if not (w == on[-1] and d > 0) and not (w == on[0] and d < 0)}
    lo_v, hi_v = LO << 8, HI << 8
    own, _ = _phase_block(0, 1, phases, on[0], step, lo_v, hi_v, False, step)
    shared, _ = _phase_block(0, 1, phases, on[0], step, lo_v, hi_v, False,
                             step, share=True)
    assert len(shared) < len(own)


def test_a_modulation_speed_is_laid_exactly_as_before():
    """Below the spelling threshold nothing moves: a slow block has no set
    row but its entry points and the chain's."""
    rows, _ = _phase_block(0, 1, {(0x900, +1)}, 0x900, 0x40, LO << 8, HI << 8,
                           False, 0x40)
    assert [r for r in rows if 0x80 <= r[0] < 0xFF] == [(0x89, 0x00)]


@needs_corpus
def test_the_shipped_tables_turn_on_the_players_widths():
    """Commando, Zoids and Gerry_the_Germ under presets (`pulse_phase`
    forced is what they ship): every index entry of a $E0/$C0-step record
    plays the first three turns of `PulsePhaseSim` -- 88 of Commando's 90
    were exact (the two off are ($800, up), a phase on another lattice that
    snaps onto the loop's), 42 of Zoids' 42, and record 17 of Gerry's. At
    1172704 the exact counts were 4 / 2 / 129 of 165 (the turns of its other
    records included)."""
    from test_pulse_phase_union import _table_calls
    from h2g.goatwriter import build_pulse_phase_table
    from h2g.goatwriter.pulse import (PulsePhaseSim, PulseVoiceCell,
                                      _phase_sweep_params)
    want_exact = {"Commando.sid": (87, 90), "Zoids.sid": (42, 42),
                  "Gerry_the_Germ.sid": (None, None)}
    for name, (min_exact, total) in want_exact.items():
        args = _table_calls(name)[0]
        sid, det, mult = args[0], args[1], args[4]
        lead = args[7]
        entries, _, index = build_pulse_phase_table(*args)
        exact = seen = 0
        for (num, w, d), at in sorted(index.items()):
            if not isinstance(d, int) or abs(d) != 1:
                continue
            p = _phase_sweep_params(sid, det, num - 1 - lead, mult)
            if p is None or p[5] is None or p[1] < SPELLED_SPEED_MIN:
                continue
            step = p[5]
            sim = PulsePhaseSim(w, step, 1, p[2] >> 8, p[3] >> 8,
                                PulseVoiceCell(d, 0))
            turns, going = [], d
            for _ in range(3):
                for _ in range(0x1000 // step + 2):
                    sim.advance(1)
                    if sim.direction == -going:
                        break
                turns.append(sim.width)
                going = -going
            played = _play_pulse_table(entries, at, 400)
            got, last = [], 0
            for a, b, c in zip(played, played[1:], played[2:]):
                if b != a:
                    last = 1 if ((b - a + 0x800) & 0xFFF) < 0x800 else -1
                if c != b and last and (
                        1 if ((c - b + 0x800) & 0xFFF) < 0x800 else -1) != last:
                    got.append(b)
            for k in range(3):
                seen += 1
                exact += k < len(got) and got[k] == turns[k]
        assert seen, name
        if min_exact is not None:
            assert exact >= min_exact and seen == total, (
                name, exact, seen)
        else:
            assert exact >= seen - 1, (name, exact, seen)


@needs_corpus
def test_the_static_program_of_a_fast_record_plays_the_walk():
    """The program a note with no CMD_SETPULSEPTR sweeps (`_pulse_tri_program`,
    which `_pulse_layout` lays for every record) is spelled too: Commando's
    records 0, 6 and 22 ($E0, $E0 and $C0 at -S1), Zoids' 0 and 14, Gerry's
    17, each from its own seed, call for call against the walk."""
    from corpus import CORPUS
    from h2g.convert import _detect_tables
    from h2g.goatwriter.pulse import _pulse_tri_program, _tri_step_delay
    from h2g.sidfile import load_sid
    cases = {"Commando.sid": (0, 6, 22), "Zoids.sid": (0, 14),
             "Gerry_the_Germ.sid": (17,)}
    for name, records in cases.items():
        sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                                  lambda *_: None)
        assert (det.pulse_tri_lo, det.pulse_tri_hi) == (LO, HI), name
        for i in records:
            rec = det.instr_start + i * det.instr_stride
            step, _ = _tri_step_delay(det, sid.data[rec + 6])
            assert step >= 0xC0, (name, i, step)
            width = ((sid.data[rec + 1] & 0x0F) << 8) | sid.data[rec]
            entries, loop = _pulse_tri_program(sid, det, i, 1)
            assert all(l >= 0x80 for l, _ in entries), (name, i)
            got = _play_pulse_table(entries + [(0xFF, loop + 1)], 1, 600)
            assert got == _walk(width, +1, step, 600), (name, i, hex(width))
