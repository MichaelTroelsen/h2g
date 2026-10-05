"""The drum sweep's onset and depth on a multispeed, outer-gated player.

Warhawk `$0F0A` and Proteus `$090A` are drum-only records (+7 = `$01`) on a
player with an outer gate of reload 7 (`tempo.outer_gate_skip`), packed at
`-S7`. Traced at 120 s, the original holds the note through frame 3 and then
falls `$0100` a working frame for three frames -- `0DD0 0DD0 0DD0 0DD0 0CD0
0BD0 0AD0` -- exactly `$0300` on all 82 notes (40 + 42), its first decrement
on frame 3 or 4 (22/18 and 24/18; 4 where the skipped frame falls in the
note's opening). Before this the conversion swept from frame 2 (28/40 and
30/41) and fell `$0144` (Warhawk) and `$0384` (Proteus). Three causes, one
helper each:

* **onset** -- `_drum_sweep_hold`: the block's first sweep frame stores the
  value it loaded (`LDA freqhi / DEC / STA`), so the gate-off waveform entry
  before the first `CMD_PORTADOWN` must last a whole frame, which is one call
  only at `-S1`;
* **rate** -- `_drum_speed(multiplier, gate_skip)`: a frame of the player's
  sweep is `multiplier * (O + 1) / O` of our calls, not `multiplier`;
* **length** -- `_drum_duration_steps(..., gate_skip)` charges one working
  frame, and the layout passes the record's own row (`instr_row_calls`):
  Warhawk's `$0F0A` plays only in 16-call subtunes and was charged the 8-call
  row of the file's one-frame sound effects.

Figures are historical (measured at be0aeb1 + this change); the assertions
below are the mechanism, not the figures.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter import FORMAT_GTS5                          # noqa: E402
from h2g.goatwriter.constants import (DRUM_DEEPEN_MARGIN,       # noqa: E402
                                      DRUM_MAX_SWEEP_STEPS,
                                      WAVECMD_PORTADOWN, _drum_speed)
from h2g.goatwriter.notes import _note_freq                     # noqa: E402
from h2g.goatwriter.wavetable import (_drum_duration_steps,     # noqa: E402
                                      _drum_entries, _drum_max_steps,
                                      _drum_sweep_hold)
from test_call_rate import wave_timeline                        # noqa: E402


def _step(hi_lo):
    return (hi_lo[0] << 8) | hi_lo[1]


def _record(multiplier, gate_skip, tick_frames=1, note_rows=4, row_calls=16,
            budget=200, min_note=43):
    table = []
    left, right = _drum_entries(0x41, FORMAT_GTS5, table, multiplier,
                                min_note, sustain=0, budget=budget,
                                tick_frames=tick_frames, note_rows=note_rows,
                                row_calls=row_calls, gate_skip=gate_skip)
    return left, right, table


def _first_sweep_call(left, right):
    """The 0-based play call on which the first CMD_PORTADOWN executes."""
    for call, (here, _, _) in enumerate(wave_timeline(left, right, first=1,
                                                      calls=300)):
        if here is not None and left[here - 1] == WAVECMD_PORTADOWN:
            return call
    return None


def _travel(left, right, table):
    """Total fall of the record's sweep, in frequency units."""
    steps = [r for l, r in zip(left, right) if l == WAVECMD_PORTADOWN]
    assert steps and len(set(steps)) == 1, (left, right)
    return len(steps) * _step(table[steps[0] - 1])


def test_step_is_per_working_frame():
    # Without an outer gate the step is the frame's /multiplier, as before.
    assert _drum_speed(1) == (0x01, 0x00)
    assert _drum_speed(7) == (0x00, 0x24)
    assert _drum_speed(7, None) == (0x00, 0x24)
    # With one, a working frame is (O + 1) / O frames of ours.
    assert _drum_speed(7, 7) == (0x00, 0x20)
    for m, o in ((7, 7), (3, 3), (5, 5), (9, 9)):
        step = _step(_drum_speed(m, o))
        assert step * m * (o + 1) <= 0x100 * o < (step + 1) * m * (o + 1)


def test_duration_charges_one_working_frame():
    # Proteus $090A: f 2, O 7, -S7, 16-call rows, 4-row notes.
    assert _drum_duration_steps(4, 16, 7, 7) == 24
    assert 24 * _step(_drum_speed(7, 7)) == 0x300
    # No gate: unchanged (Commando's 4-row instrument 13 at 3 frames, -S1).
    assert _drum_duration_steps(4, 16, 7) == 25
    assert _drum_duration_steps(4, 3, 1) == 5


def test_max_steps_counts_working_frames():
    # The pitch bound divides by the gated step ...
    low = 24
    room = _note_freq(low) - DRUM_DEEPEN_MARGIN
    assert _drum_max_steps(low, 7, 7) == room // 0x20
    assert _drum_max_steps(low, 7) == room // 0x24
    # ... and the cap is DRUM_MAX_SWEEP_STEPS working frames of calls.
    assert _drum_max_steps(43, 7, 7) == DRUM_MAX_SWEEP_STEPS * 8
    assert _drum_max_steps(43, 7) == DRUM_MAX_SWEEP_STEPS * 7


def test_sweep_hold_shapes():
    assert _drum_sweep_hold(0x40, 1) == ([], [])
    assert _drum_sweep_hold(0x40, 1, None) == ([], [])
    assert _drum_sweep_hold(0x40, 2) == ([0x40], [0x00])
    assert _drum_sweep_hold(0x40, 7) == ([0x05], [0x80])
    assert _drum_sweep_hold(0x40, 7, 7) == ([0x06], [0x80])


@pytest.mark.parametrize("m, o, tick", [
    (1, None, 1), (1, None, 2), (2, None, 1), (2, None, 2), (4, None, 2),
    (3, 3, 1), (5, 5, 2), (7, 7, 1), (9, 9, 1)])
def test_first_decrement_lands_on_the_players_frame(m, o, tick):
    """Frame 0 the record's waveform, `tick` frames of noise, then the
    no-op sweep frame: the first decrement the chip sees is frame tick + 2,
    at every -S value. At -S7 it used to be frame 2 (call 15)."""
    left, right, _ = _record(m, o, tick_frames=tick, row_calls=8 * m)
    call = _first_sweep_call(left, right)
    assert call is not None, (left, right)
    assert call // m == tick + 2, (m, o, tick, call, left)


def test_warhawk_shaped_record_falls_0300():
    left, right, table = _record(7, 7)
    assert _travel(left, right, table) == 0x300
    assert _first_sweep_call(left, right) == 7 + 7 + 8


def test_no_hold_without_a_sweep():
    # A 2-row note leaves the player no sweep frames: no hold entry either.
    left, right, _ = _record(7, 7, note_rows=2)
    assert WAVECMD_PORTADOWN not in left
    k = left.index(0x40)
    assert left[k + 1] == 0xFF, left


@pytest.mark.parametrize("budget", range(5, 12))
def test_hold_counts_against_the_budget(budget):
    left, _, _ = _record(7, 7, budget=budget)
    assert len(left) <= budget, (budget, left)


def _converted(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng[0] if isinstance(sng, tuple) else sng


@needs_corpus
@pytest.mark.parametrize("name, ad, sr", [("Warhawk", 0x0F, 0x0A),
                                          ("Proteus", 0x09, 0x0A)])
def test_corpus_record_falls_0300_from_frame_3(name, ad, sr):
    sys.path.insert(0, str(PYTHON_ROOT))
    import songview
    s = songview.parse_sng(_converted(name))
    ins = [i for i in s.instruments if (i.ad, i.sr) == (ad, sr)]
    assert len(ins) == 1, [(i.number, i.adsr) for i in s.instruments]
    wt = s.tables["WTBL"]
    k = ins[0].wave_ptr - 1
    left, right = [], []
    while wt[k][0] != 0xFF:
        left.append(wt[k][0])
        right.append(wt[k][1])
        k += 1
    left.append(0xFF)
    right.append(0x00)
    assert _travel(left, right, s.tables["STBL"]) == 0x300, (left, right)
    assert _first_sweep_call(left, right) // 7 == 3, left
