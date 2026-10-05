"""The gate bit on `_drum_entries`' noise tick (`_drum_tick_noise`).

The player writes the tick as `LDA #$80 / STA $D404,Y`, so its gate is off.
Rasputin's original reads $80 on all 660 drum noise frames. We now clear the
gate at -S1, where an A/B over 11 files found register gains and no sound
cost. Above -S1 we keep the record's gate bit: clearing it there cost `loud` on
ten files and 71 Kentilla attacks. The numbers are in the docstring.

Rasputin's other disagreement is not a converter defect. The original's noise
sometimes lands at attack+2 instead of +1 (129 of 660). That happens when its
outer speed counter (`DEC $C53A / BPL`, `$C012`) skips the play call right
after the note's own frame. The skip phase is a global counter, so no
per-instrument wavetable can follow it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g.goatwriter import WAVE_NOISE_GATEOFF, _drum_entries  # noqa: E402
from h2g.goatwriter.wavetable import _drum_tick_noise  # noqa: E402


@pytest.mark.parametrize("wave", [0x41, 0x15, 0x43, 0x81])
@pytest.mark.parametrize("tick_frames", [1, 2])
def test_the_tick_clears_the_gate_at_single_speed(wave, tick_frames):
    left, _ = _drum_entries(wave, "gts5", [], 1, min_note=40, sustain=0,
                            budget=8, tick_frames=tick_frames)
    assert left[0] == wave, "frame 0 is still the record's own gated waveform"
    noise = left[1:1 + tick_frames]
    assert noise == [WAVE_NOISE_GATEOFF] * tick_frames, \
        f"the player's #$80 on every tick entry, got {[hex(b) for b in noise]}"


@pytest.mark.parametrize("multiplier", [2, 3, 5, 10])
def test_the_tick_keeps_the_gate_above_single_speed(multiplier):
    # The refusal: clearing it here cost `loud` on ten of 22 files, and
    # Kentilla (-S10) 71 attacks. See `_drum_tick_noise`.
    left, _ = _drum_entries(0x41, "gts5", [], multiplier, min_note=40,
                            sustain=0, budget=8, tick_frames=1)
    assert 0x81 in left and WAVE_NOISE_GATEOFF not in left, \
        f"-S{multiplier}: {[hex(b) for b in left]}"


def test_a_written_frame_zero_keeps_the_gate():
    # With `written` there is no lead: the tick follows the firstwave call
    # directly. That is the layout the Commando GT 13 onset loss was measured
    # on, and the A/B did not reach it.
    left, _ = _drum_entries(0x41, "gts5", [], 1, min_note=40, sustain=0,
                            budget=8, tick_frames=2, written=True)
    assert left[:2] == [0x81, 0x81]


@pytest.mark.parametrize("multiplier", [1, 2, 10])
def test_a_record_without_a_gate_bit_is_unchanged(multiplier):
    assert _drum_tick_noise(0x40, multiplier) == WAVE_NOISE_GATEOFF
    assert _drum_tick_noise(0x40, multiplier, written=True) == WAVE_NOISE_GATEOFF


def test_the_rule_in_one_table():
    assert _drum_tick_noise(0x41, 1) == 0x80
    assert _drum_tick_noise(0x41, 2) == 0x81
    assert _drum_tick_noise(0x41, 1, written=True) == 0x81
