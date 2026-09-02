"""The hard-restart sub-search's pre-check.

`tune_by_fidelity` ends with a nine-point pass -- `HARD_RESTART_SEARCH` (3, 4,
5) crossed with `(None, max_hard_restart, wide_hard_restart)` -- and each point
costs a convert, a `gt2reloc` pack and a `siddump` trace. On about a third of
the corpus not one of those nine points moves a single byte, so the nine traces
can only reproduce the reference.

`_hard_restart_grid_inert` proves that with nine CONVERSIONS and no emulation,
and the skip is sound for the reason its docstring gives: `fidelity_better`
scores traces, a trace is a function of the packed bytes and the packed bytes
of the converted ones, so a point that converts identically to the reference
scores identically to it -- and an acceptance rule that needs a strict
improvement accepts none of them.

Pinned the way `_redundant_combination` is: the property, not a corpus number.
The number lives in the docstring and is graded there.
"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import presets as P                                   # noqa: E402
from corpus import CORPUS, needs_corpus               # noqa: E402

REPO = Path(__file__).resolve().parents[2]
COMMANDO = REPO / "Commando.sid"


def _grid():
    return [(f, e) for f in P.HARD_RESTART_SEARCH
            for e in (None, *P.HARD_RESTART_ENABLERS)]


def test_the_grid_is_nine_points():
    """Nine is the number the saving is quoted in; if the grid grows, the
    docstring's arithmetic silently stops describing it."""
    assert len(_grid()) == 9
    assert len(P.HARD_RESTART_SEARCH) == 3
    assert len(P.HARD_RESTART_ENABLERS) == 2


@needs_corpus
def test_inert_means_every_point_converts_to_the_same_bytes():
    """The claim the skip rests on, checked directly rather than inferred.

    Takes files the census ACTUALLY finds inert rather than a file chosen in
    advance: the first draft asserted this on Commando, whose grid is live at
    the default options, so the test skipped itself and pinned nothing. A
    check that cannot fire is worse than no check, because the suite still
    reports it green.
    """
    import json
    doc = json.loads((REPO / "presets.json").read_text(encoding="utf-8"))
    checked = 0
    for name, e in sorted(doc["songs"].items()):
        if checked >= 3:
            break
        p = CORPUS / name
        if not p.exists():
            continue
        base = {k: e[k] for k in ("max_rows", *P.TOGGLES) if k in e}
        out = {k: v for k, v in e.items() if k in P.FIDELITY_TOGGLES and v}
        if not P._hard_restart_grid_inert(p, base, out):
            continue
        ref = hashlib.sha1(P.convert(str(p), log=lambda m: None,
                                     **base, **P.FIXED, **out)).hexdigest()
        for frames, enabler in _grid():
            extra = dict(out, hard_restart_frames=frames)
            if enabler is not None:
                extra[enabler] = True
            got = hashlib.sha1(P.convert(str(p), log=lambda m: None,
                                         **base, **P.FIXED, **extra)).hexdigest()
            assert got == ref, f"{name}: frames={frames} enabler={enabler} moved bytes"
        checked += 1
    assert checked == 3, "fewer than three inert files found; the census is wrong"


def test_a_conversion_that_raises_is_not_called_inert(monkeypatch):
    """False is the honest answer for a file the check cannot evaluate: the
    pass must then run so `play()` can decline the combination itself. Same
    convention as `_inert_frames`, which this sits beside."""
    def boom(*a, **k):
        raise ValueError("nope")
    monkeypatch.setattr(P, "convert", boom)
    assert P._hard_restart_grid_inert(COMMANDO, {"max_rows": 94}, {}) is False


def test_a_grid_that_moves_one_point_is_live(monkeypatch):
    """One differing point is enough to run the pass -- the check is an ALL,
    not a majority. Driven by a stub so the property holds whatever the corpus
    happens to contain."""
    calls = {"n": 0}

    def convert(path, log=None, **kw):
        calls["n"] += 1
        # the reference call is first; make exactly the last grid point differ
        return b"x" if calls["n"] <= 9 else b"y"
    monkeypatch.setattr(P, "convert", convert)
    assert P._hard_restart_grid_inert(COMMANDO, {"max_rows": 94}, {}) is False
    assert calls["n"] == 10, "it should stop at the first point that differs"


def test_an_all_identical_grid_is_inert(monkeypatch):
    monkeypatch.setattr(P, "convert", lambda path, log=None, **kw: b"same")
    assert P._hard_restart_grid_inert(COMMANDO, {"max_rows": 94}, {}) is True


def test_it_costs_ten_conversions_and_no_emulation(monkeypatch):
    """The whole point is that it is cheaper than the pass it guards: one
    reference plus nine points, and nothing packed or traced."""
    n = {"c": 0}

    def convert(path, log=None, **kw):
        n["c"] += 1
        return b"same"
    monkeypatch.setattr(P, "convert", convert)
    monkeypatch.setattr(P, "FIXED", P.FIXED)
    assert P._hard_restart_grid_inert(COMMANDO, {"max_rows": 94}, {}) is True
    assert n["c"] == 10


@needs_corpus
def test_the_corpus_splits_and_the_split_is_not_all_one_way():
    """A pre-check that skipped everything, or nothing, would be a bug wearing
    a measurement. Kept as a range rather than a count so the corpus can grow
    without the test lying; the exact figure is graded in the docstring."""
    import json
    doc = json.loads((REPO / "presets.json").read_text(encoding="utf-8"))
    inert = live = 0
    for name, e in sorted(doc["songs"].items()):
        p = CORPUS / name
        if not p.exists():
            continue
        base = {k: e[k] for k in ("max_rows", *P.TOGGLES) if k in e}
        out = {k: v for k, v in e.items() if k in P.FIDELITY_TOGGLES and v}
        if P._hard_restart_grid_inert(p, base, out):
            inert += 1
        else:
            live += 1
    assert inert + live > 80, "the corpus census did not run"
    assert inert > 0, "nothing is inert: the skip can never fire"
    assert live > 0, "everything is inert: the pass would never run at all"
