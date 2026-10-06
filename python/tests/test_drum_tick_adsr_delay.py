"""Why `_drum_tick_noise` keeps the gate above -S1: the SID's ADSR delay.

A measurement shipped as a keyed table (see `_drum_tick_noise`'s docstring).
Measured at 8586101 (v0.5.511) with VICE's `dump` device and the drum voice
swapped onto voice 3, so that ENV3 reads its envelope. When the gate rises,
the 15-bit rate counter is above the attack period. It wraps through $7FFF
before the first attack step, so the attack starts up to $8000 cycles after
the rise, which is 520 rasterlines.

Our gate is on `m + 1` play calls before the drum tick. In lines that is
`RISE_TO_TICK_LINES` below, measured per multiplier. A gate-off tick that
lands before the delay has run out releases a voice whose attack never
started. Above -S1 that happened on Rasputin (26 of 157 attacks started),
Formula_1_Simulator (0 of 63) and Bump_Set_Spike (1 of 104). So the gate may
be cleared only where the gate-on span outlasts the delay plus a full attack.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g.goatwriter import WAVE_NOISE_GATEOFF  # noqa: E402
from h2g.goatwriter.wavetable import _drum_tick_noise  # noqa: E402

CYCLES_PER_LINE = 63                # PAL
LINES_PER_FRAME = 312
ADSR_DELAY_MAX_CYCLES = 0x8000      # the rate counter's wrap
ATTACK_0_CYCLES = 255 * 9           # A=0: one step per 9 cycles, 0 -> 255

# Rise to tick in lines, VICE, 60 s under presets: Gerry_the_Germ and
# Action_Biker (-S1), Rasputin and Formula_1_Simulator (-S2),
# Bump_Set_Spike (-S5).
RISE_TO_TICK_LINES = {1: 624, 2: 468, 5: 373}
# The latest first attack step seen after a drum rise, on each of those files.
MEASURED_DELAY_MAX_LINES = 521


def test_the_measured_delay_is_the_rate_counter_wrap():
    assert MEASURED_DELAY_MAX_LINES * CYCLES_PER_LINE >= ADSR_DELAY_MAX_CYCLES - CYCLES_PER_LINE
    assert (MEASURED_DELAY_MAX_LINES - 1) * CYCLES_PER_LINE <= ADSR_DELAY_MAX_CYCLES


@pytest.mark.parametrize("multiplier,lines", sorted(RISE_TO_TICK_LINES.items()))
def test_the_gate_span_is_m_plus_one_calls(multiplier, lines):
    assert abs(lines - LINES_PER_FRAME * (multiplier + 1) / multiplier) <= 2


@pytest.mark.parametrize("multiplier", [1, 2, 3, 5, 7, 10])
def test_the_gate_clears_only_where_the_attack_has_finished(multiplier):
    span = LINES_PER_FRAME * (multiplier + 1) / multiplier * CYCLES_PER_LINE
    safe = span >= ADSR_DELAY_MAX_CYCLES + ATTACK_0_CYCLES
    cleared = _drum_tick_noise(0x41, multiplier) == WAVE_NOISE_GATEOFF
    assert cleared == safe, (
        f"-S{multiplier}: gate on {span:.0f} cycles before the tick, the "
        f"delay plus an A=0 attack is {ADSR_DELAY_MAX_CYCLES + ATTACK_0_CYCLES}; "
        f"tick {'clears' if cleared else 'keeps'} the gate")
