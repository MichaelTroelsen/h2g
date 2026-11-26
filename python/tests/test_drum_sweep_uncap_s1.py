"""At -S1 the drum sweep is not cut at DRUM_MAX_SWEEP_STEPS where the record's
own notes are measured.

`_drum_max_steps` applied the corpus-wide cap (8) on top of
`_drum_duration_steps`, "whichever is smaller wins" -- but the cap was only
ever a stand-in for the per-record number. Zoids' bit-$01 drum records fall
`$106E -> $016E` (15 frames) and `0DD0 -> 01D0` (12), and ours stopped at 8:
266 of subtune 0 voice 0's 477 original-only ties were the missing sweep steps
(tiefr 78.8% -> 81.6%, tie 0.845 -> 0.879, travel 0.966 -> 0.984, cents 92.0%
-> 93.3% once lifted; task `listen-sub99-zoids`, historical, re-measure).

The lift is -S1 only. Above it the same lift ran a step or two past the
original on Rasputin voice 1 (12 against 11 frames; tie ratio 0.96 -> 1.20)
and put Formula_1_Simulator's table at 255 of 255, losing it tie blocks
(melody 100% -> 98%), so a multiplier > 1 record keeps the cap.

Figures are historical; the assertions are the mechanism.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter import FORMAT_GTS5                          # noqa: E402
from h2g.goatwriter.constants import (DRUM_DEEPEN_MARGIN,       # noqa: E402
                                      DRUM_MAX_SWEEP_STEPS,
                                      WAVECMD_PORTADOWN)
from h2g.goatwriter.notes import _note_freq                     # noqa: E402
from h2g.goatwriter.wavetable import (_drum_duration_steps,     # noqa: E402
                                      _drum_entries, _drum_max_steps)


def _sweep_steps(multiplier, note_rows, row_calls, min_note=44, budget=200):
    table = []
    left, _right = _drum_entries(0x41, FORMAT_GTS5, table, multiplier,
                                 min_note, sustain=0, budget=budget,
                                 tick_frames=1, note_rows=note_rows,
                                 row_calls=row_calls, gate_skip=None)
    return sum(1 for entry in left if entry == WAVECMD_PORTADOWN)


def test_max_steps_cap_is_a_knob_and_defaults_on():
    room = (_note_freq(44) - DRUM_DEEPEN_MARGIN) // 0x100
    assert room > DRUM_MAX_SWEEP_STEPS
    assert _drum_max_steps(44, 1) == DRUM_MAX_SWEEP_STEPS
    assert _drum_max_steps(44, 1, capped=False) == room


def test_s1_record_with_measured_notes_sweeps_past_the_cap():
    # A 20-row note at 3 calls a row holds the player's sweep for
    # (20 - 2) * 3 - 1 = 53 decrements; the pitch bound of note 44 is 13.
    held = _drum_duration_steps(20, 3, 1)
    room = (_note_freq(44) - DRUM_DEEPEN_MARGIN) // 0x100
    assert held > room > DRUM_MAX_SWEEP_STEPS
    assert _sweep_steps(1, 20, 3) == room


def test_s1_record_the_notes_end_early_keeps_the_shorter_bound():
    # Commando's instrument 13: 4-row notes at 3 calls, 5 steps -- below both.
    assert _drum_duration_steps(4, 3, 1) == 5
    assert _sweep_steps(1, 4, 3) == 5


def test_unmeasured_record_keeps_the_cap():
    # No note_rows: `_drum_duration_steps` is None, the cap stands in for it.
    assert _sweep_steps(1, None, 3) == DRUM_MAX_SWEEP_STEPS


def test_multispeed_record_keeps_the_cap():
    # -S2: the cap is DRUM_MAX_SWEEP_STEPS working frames of calls, as before.
    assert _drum_duration_steps(20, 6, 2) > 2 * DRUM_MAX_SWEEP_STEPS
    assert _sweep_steps(2, 20, 6) == 2 * DRUM_MAX_SWEEP_STEPS


@needs_corpus
def test_zoids_drum_record_sweeps_its_own_depth():
    """Zoids (-S1) converts a drum sweep of more than the cap's 8 steps."""
    import json
    import fidelity
    from h2g import convert as hconvert
    import songview

    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    opts = fidelity._preset_opts(doc, "Zoids.sid")
    opts["pack"] = False
    sng = hconvert.convert(str(CORPUS / "Zoids.sid"), log=lambda *_: None,
                           **opts)
    wtbl = songview.parse_sng(sng).tables["WTBL"]
    # A drum program is a run of F2 (pitch down) entries; its longest run.
    best = run = 0
    for left, _right in wtbl:
        run = run + 1 if left == WAVECMD_PORTADOWN else 0
        best = max(best, run)
    assert best > DRUM_MAX_SWEEP_STEPS, best
