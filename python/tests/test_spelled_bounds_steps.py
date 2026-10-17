"""A per-record-bounds step above 134 a call is SPELLED where the table has the
rows (`pulse._pulse_program(spell=True)`, `pulse._pulse_layout`), and keeps its
clamp where it does not.

The bounds engine emitted `min(GT_MAX_PULSE_SPEED, rate / multiplier)`, a
signed-byte speed, so a rate of $F4 swept at 127 a call against 244 (1.9x
slow). The triangle engine's `_ramp_rows` already spells that step as one set
row a call (`test_spelled_triangle_steps.py`); this is the same mechanism for
the other engine, laid record by record against the 255-row budget the way the
held stairs are.

The widths the player plays are re-derived by an independent walk (`_walk`:
add the rate, mask to 12 bits, turn when the high nibble equals the bound it is
heading for), not through `PulseBoundsSim`.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_pulse_phase import _play_pulse_table               # noqa: E402
from h2g.goatwriter import constants as _gw_constants        # noqa: E402
from h2g.goatwriter import pulse as PU                       # noqa: E402

LO, HI = 0x2, 0xE
RATE = 0xF4
SEED = 0x800


def _file():
    """One record: width $800, rate $F4 at +2, bounds byte $E2 at address 4."""
    data = bytearray(16)
    data[0], data[1], data[2], data[4] = SEED & 0xFF, SEED >> 8, RATE, (HI << 4) | LO
    sid = SimpleNamespace(data=bytes(data))
    det = SimpleNamespace(instr_start=0, instr_stride=8, pulse_bounds=4,
                          pulse_rate_field=2, pulse_lo_base=-1, pulse_tri_hi=-1)
    return sid, det


def _walk(calls: int) -> list:
    out, x, d = [SEED], SEED, +1
    for _ in range(calls - 1):
        x = (x + d * RATE) & 0xFFF
        out.append(x)
        if x >> 8 == (HI if d > 0 else LO):
            d = -d
    return out


def _table(program, loop):
    start = 1
    return program + [(0xFF, start + loop)], start


def test_the_clamped_program_is_the_modulation_rows_it_was():
    sid, det = _file()
    program, loop = PU._pulse_program(sid, det, 0, True, 1)
    assert all(left < 0x80 for left, _ in program[1:])
    assert all(right <= PU.GT_MAX_PULSE_SPEED or right >= 0x80
               for _, right in program[1:])


def test_a_spelled_record_plays_the_players_widths():
    sid, det = _file()
    program, loop = PU._pulse_program(sid, det, 0, True, 1, spell=True)
    assert len(program) > 20
    assert all(left >= 0x80 for left, _ in program)
    entries, ptr = _table(program, loop)
    calls = 120
    assert _play_pulse_table(entries, ptr, calls) == _walk(calls)


def test_a_rate_the_clamp_costs_under_five_percent_stays_a_modulation_row():
    sid, det = _file()
    data = bytearray(sid.data)
    data[2] = 0x84                        # 132 a call: 127 sweeps 4% slow
    sid = SimpleNamespace(data=bytes(data))
    assert (PU._pulse_program(sid, det, 0, True, 1, spell=True)
            == PU._pulse_program(sid, det, 0, True, 1))


def test_the_layout_spells_where_the_rows_fit_and_clamps_where_they_do_not(
        monkeypatch):
    sid, det = _file()
    prog = PU._pulse_program(sid, det, 0, True, 1)
    static = PU._pulse_program(sid, det, 0, False, 1)[0]
    clamped = PU._lay_out_pulse([prog], [static], 1, share=False)[0]
    spelled, _ = PU._pulse_layout(sid, det, 2, True, 1)
    assert len(spelled) > len(clamped)    # the roomy table spells
    assert all(left >= 0x80 for left, _ in spelled[:-1])
    # One row short of the spelled table: the record keeps its clamp.
    monkeypatch.setattr(_gw_constants, "GT_MAX_TABLELEN", len(spelled) - 1)
    tight, _ = PU._pulse_layout(sid, det, 2, True, 1)
    assert tight == clamped
    # Exactly the spelled table's length: it fits and is spelled.
    monkeypatch.setattr(_gw_constants, "GT_MAX_TABLELEN", len(spelled))
    snug, _ = PU._pulse_layout(sid, det, 2, True, 1)
    assert snug == spelled
