"""The drum's frame-0 lead against the wavetable budget (`kentilla-s10-drum-lead-trim`).

The task opened from a figure taken at 8586101: at -S10 Kentilla wrote
`12 12 81 81 14` where the original writes `12 15 80 80 14`, read as "the
budget trims the lead, so frame 0 reads noise". Re-measured at 0d18fce
(v0.5.524, presets, -t 180) that does not hold:

* Kentilla's six drum records are given budgets of 54 to 123 entries
  (`_wavetable_layout`), against the 6 the full shape needs above -S1. None is
  trimmed; frame 0 reads the record's own waveform (`12 15 81 81 14`).
* Over the whole corpus under presets the lead is trimmed on exactly two files,
  Chain_Reaction (-S3) and W_A_R (-S4), one record each at the floor of 5.
  Neither file's attacks suffer from it: Chain_Reaction pairs 1985 of 1985 on
  the first five waveform bytes of every attack, W_A_R differs on 44 of 1738
  and none of those is a lead (38 are a gate bit, 6 a different record).
* What still differs on Kentilla (204 of 826 paired attacks) is the gate bit
  (`_drum_tick_noise`) and the outer gate's skipped call
  (`gate_skip` 10: the tick lands a frame early or late by the note's place in
  the song), neither of which is the budget.

This file pins the two properties that make the lead survive: the full shape
is six entries above -S1, and `_drum_entries` only gives the lead up below
that. If a layout change hands Kentilla's drum records the floor, the second
test says so.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import wavetable                         # noqa: E402

KENTILLA_FULL_SHAPE = 6        # lead (wave + delay), noise, tick hold, tail, stop


def _entries(wave, budget, multiplier=10, **kw):
    left, right = wavetable._drum_entries(
        wave, "gts5", [], multiplier, min_note=None, sustain=0, budget=budget,
        tick_frames=2, note_rows=4, row_calls=33, gate_skip=10, sweep=False,
        **kw)
    return left, right


@pytest.mark.parametrize("wave", [0x13, 0x15, 0x41])
def test_the_lead_is_a_whole_frame_when_the_budget_holds_the_full_shape(wave):
    left, right = _entries(wave, KENTILLA_FULL_SHAPE)
    # entry 0 is the record's waveform for one call, the delay holds it for the
    # other nine of the frame (a delay is current for value + 1 calls).
    assert left[:2] == [wave, 0x08], [hex(b) for b in left]
    assert right[:2] == [0x00, 0x80]
    assert left[2] == 0x81, "the tick follows the whole lead frame"
    assert left[-2] == (wave & 0xFE) and left[-1] == 0xFF


@pytest.mark.parametrize("budget", [6, 7, 54, 123])
def test_no_budget_at_or_above_the_full_shape_trims_it(budget):
    left, _ = _entries(0x15, budget)
    assert left[:KENTILLA_FULL_SHAPE] == [0x15, 0x08, 0x81, 0x0F, 0x14, 0xFF]


def test_below_the_full_shape_the_lead_is_what_gives_way():
    # The floor of 5 (`WAVE_ENTRIES_PER_INSTR`): the lead is cut to one call and
    # the tick keeps its hold. Chain_Reaction and W_A_R are the corpus files
    # that take this path. It is the named, measured trade, not a bug: they
    # read the original's tick placement on 1985 of 1985 and 1694 of 1738
    # paired attacks.
    left, _ = _entries(0x15, 5)
    assert left[:3] == [0x15, 0x81, 0x0F], [hex(b) for b in left]
    assert left[3] == 0x14 and left[4] == 0xFF


@needs_corpus
def test_kentilla_s10_drum_records_keep_their_frame_zero_lead():
    path = CORPUS / "Kentilla.sid"
    if not path.exists():
        pytest.skip("Kentilla.sid not in the corpus")
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    calls = []
    real = wavetable._drum_entries

    def spy(wave, fmt, speed_table, multiplier=1, *a, **k):
        left, right = real(wave, fmt, speed_table, multiplier, *a, **k)
        calls.append((multiplier, k.get("budget"), left))
        return left, right

    wavetable._drum_entries = spy
    try:
        convert(str(path), log=lambda *a, **k: None,
                **fidelity._preset_opts(doc, "Kentilla.sid"))
    finally:
        wavetable._drum_entries = real
    assert calls, "Kentilla has drum records; the emitter was not reached"
    assert {m for m, _, _ in calls} == {10}, \
        "presets.json no longer gives Kentilla -S10; re-measure this file"
    for multiplier, budget, left in calls:
        assert budget is not None and budget >= KENTILLA_FULL_SHAPE, \
            f"a drum record was handed budget {budget}"
        assert left[1] == 0x08 and left[2] == 0x81, \
            f"lead trimmed at budget {budget}: {[hex(b) for b in left]}"
