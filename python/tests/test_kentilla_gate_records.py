"""Kentilla's one-step records all reach the phased nibble shape.

`ik-kentilla-gate-long-half` (partial at 6e467ff) left 34 of Kentilla's 86
one-step notes with the long half on the wrong note: its records 6, 12, 13
and 14 were laid out in a 5-entry wavetable budget (a full table), the
phased shape takes 9, so the unphased loop -- the alternation from the
attack -- stood. Re-measured at 0d18fce (v0.5.524) the 34 are gone: the
budgets are 76, 66, 62 and 58, the shape is the 9-entry phased one, and all
86 one-step notes and all 108 octave notes are frame-exact against the
original (abnote.py, subtune 0, 120 s, gated).

What freed the room is v0.5.520's "a nibble-dialect arp record with nibble 0
overwrites the drum sweep" (warhawk-proteus-0f09-never-swept): the sweep it
no longer appends was the table's bulk. Bisected by laying out Kentilla at
5248ee2 (budget 5, len 5) and 5fd69ef (budget 76/66/62/58, len 9).

The first test is the layout (fast), the second the sound against the
original (siddump, ~1 min). If the first fails, the second will say how many
notes it cost.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus
from test_nibble_gate_step_lead import (_converted, _notes, _paired,
                                        needs_gt2reloc, needs_siddump)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from h2g.goatwriter import wavetable as _wavetable           # noqa: E402

RECORDS = (6, 12, 13, 14)       # the four that sat in a 5-entry budget
PHASED = 9                      # four base/interval pairs + the jump


@needs_corpus
def test_records_6_12_13_14_get_the_phased_shape(monkeypatch):
    seen = {}
    real = _wavetable._wavetable_entries

    def spy(sid, det, i, *a, **k):
        out = real(sid, det, i, *a, **k)
        if i in RECORDS and k.get("budget", 255) < 255:
            seen.setdefault(i, []).append((k["budget"], len(out[0])))
        return out

    monkeypatch.setattr(_wavetable, "_wavetable_entries", spy)
    _converted("Kentilla")
    assert sorted(seen) == list(RECORDS), seen
    for rec, calls in seen.items():
        for budget, n in calls:
            assert budget >= PHASED, (rec, budget)
            assert n == PHASED, (rec, budget, n)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_every_kentilla_arp_note_plays_the_originals_frames(tmp_path):
    """Subtune 0, 120 s, gated: each two-valued arpeggio note paired with
    ours is frame-exact. The floors are the counts at 0d18fce; 52/86 and
    84/84 at 6e467ff."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    seconds, n = 120, 120 * 50
    orig = _notes(fidelity.run_siddump(CORPUS / "Kentilla.sid", seconds, 0,
                                       calls=1), n, True)
    sng, m = _converted("Kentilla")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    got = _paired(orig, _notes(fidelity.run_siddump(packed, seconds, 0,
                                                    calls=m), n, True))
    assert got[("one", "differ")] == 0 and got[("oct", "differ")] == 0, got
    assert got[("one", "exact")] >= 86, got
    assert got[("oct", "exact")] >= 108, got
