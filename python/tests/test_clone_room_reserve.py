"""A phase clone with no room asks the records for the least that makes room.

The wavetable is laid out greedily: every record, then the clones. Entries that
come free early go to the next record that can use more than five, and the
clones get what is left of that. Bump_Set_Spike's GT 13 gave 25 entries back
(`patterns.median_played_durations`, see test_last_event_through_empty_pattern)
and GT 16 and 18 took 22 of them to complete a gate-off nibble shape, so GT 2's
clone (21 entries a block) still found no room. `_wavetable_layout` now holds
back the smallest `clone_reserve` at which every such clone is placed.

Figures are historical (v0.5.541, 180 s, presets, Bump_Set_Spike): the same
entries given to the clone read `aud` 0.9058 -> 0.9065 and `tie_agreement`
0.591 -> 0.609, where the greedy order read 0.9053 and 0.591.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import h2g.convert  # noqa: E402,F401  (import order: patterns <-> goatwriter cycle)
from h2g.goatwriter import wavetable  # noqa: E402


class _Once:
    """A stand-in for `_wavetable_layout_once`: `need` entries are unplaced
    until `reserve` reaches `fits_at`, and every call is recorded."""

    def __init__(self, need, fits_at):
        self.need, self.fits_at, self.calls = need, fits_at, []

    def __call__(self, *args, clone_reserve=0, unplaced=None, **kwargs):
        self.calls.append((clone_reserve, unplaced is not None,
                           kwargs.get("log"),
                           kwargs.get("phase_clone_starts")))
        if unplaced is not None and clone_reserve < self.fits_at:
            unplaced.append(self.need)
        return ([], [], [])


def _layout(monkeypatch, once, **kwargs):
    monkeypatch.setattr(wavetable, "_wavetable_layout_once", once)
    starts = []
    marker = object()
    wavetable._wavetable_layout(
        "sid", "det", phase_clones=[(2, 26, "gate")],
        phase_clone_starts=starts, log=marker, **kwargs)
    return starts, marker


def test_the_smallest_reserve_that_places_every_clone(monkeypatch):
    once = _Once(need=21, fits_at=9)
    _layout(monkeypatch, once)
    final = once.calls[-1]
    assert final[0] == 9, once.calls
    # The last call is the real one: no `unplaced` probe, the caller's log and
    # the caller's output list; every trial before it ran on scratch ones.
    assert final[1] is False
    assert final[2] is not None
    assert all(c[1] for c in once.calls[:-1])
    assert all(c[2] is None for c in once.calls[:-1])
    assert all(c[3] == [] for c in once.calls[:-1])


def test_a_table_where_every_clone_fits_is_laid_out_with_no_reserve(monkeypatch):
    once = _Once(need=0, fits_at=0)
    _layout(monkeypatch, once)
    assert [c[0] for c in once.calls] == [0, 0]


def test_no_reserve_that_helps_leaves_the_greedy_layout(monkeypatch):
    # The records are already at their five each: even the whole block's worth
    # of reserve places nothing, so nothing is held back.
    once = _Once(need=21, fits_at=10 ** 6)
    _layout(monkeypatch, once)
    assert once.calls[-1][0] == 0


def test_a_layout_with_no_phase_clones_is_one_call(monkeypatch):
    once = _Once(need=21, fits_at=9)
    monkeypatch.setattr(wavetable, "_wavetable_layout_once", once)
    wavetable._wavetable_layout("sid", "det", phase_clones=None)
    wavetable._wavetable_layout("sid", "det", phase_clones=[])
    wavetable._wavetable_layout("sid", "det", phase_clones=[(2, 26, "g")],
                                phase_probe=[(2, 3, None)])
    assert [c[0] for c in once.calls] == [0, 0, 0]
    assert all(c[1] is False for c in once.calls)


def _logged(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    convert(str(CORPUS / f"{name}.sid"), log=lines.append,
            **fidelity._preset_opts(doc, f"{name}.sid"))
    return lines


@needs_corpus
def test_bump_set_spike_places_its_gate_phase_clone():
    lines = _logged("Bump_Set_Spike")
    assert not [m for m in lines if "gate phase split" in m
                and "no room" in m], lines
    assert any("gate phase split: 1 clone(s) [(2, " in m for m in lines)


@needs_corpus
@pytest.mark.parametrize("name", ["Thrust"])
def test_no_gate_phase_clone_is_left_without_room(name):
    lines = _logged(name)
    assert not [m for m in lines if "gate phase split" in m
                and "no room" in m], lines
