"""`apply_pulse_phase(first_group=...)`: the start subtune's clones rank first.

A forced `pulse_phase` plan on Gremlins asks for 348 pattern copies against 11
free slots. The in-window ranking (`test_pulse_phase_window_ranking.py`)
maximises rows over every subtune, which gave all 11 copies to subtune 1's
voice 0 (224 of 598 note rows reach their phase) and none to the start
subtune's voice 2 (0 of 299). That voice opens its notes on eight different
duty cycles in the original, and ours on two: `pphase` 0.54. A clone serving a
row of `first_group` is kept ahead of every other.

Synthetic plans for the rule, and Gremlins itself for the effect it buys.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h2g.convert  # noqa: E402,F401
from h2g import patterns as P  # noqa: E402
from test_pulse_phase_window_ranking import (  # noqa: E402
    INDEX, _pattern, _ph, _table)


def _two_groups(**kw):
    """Group 0's note (pattern 0, one row) against group 1's (pattern 1, two
    rows); one copy free. Group 1's clone serves MORE rows, so the global
    ranking gives it the copy."""
    pats = _table(2, 1)
    pats[1] = _pattern(1)
    tracks = ([[0, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2
              + [[1, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2)
    writes = [(0, 0, {0: _ph(0x800)}),
              (3, 0, {0: _ph(0x800), 1: _ph(0x900)})]
    n = P.apply_pulse_phase(pats, tracks, writes, INDEX, None,
                            row_seconds=[1.0, 1.0], **kw)
    return n, tracks


def test_without_first_group_the_larger_clone_wins_the_copy():
    n, tracks = _two_groups()
    assert n == 2
    assert tracks[3][0] >= P.MAX_PATTERNS - 1
    assert tracks[0][0] == 0


def test_first_group_takes_the_only_copy_from_a_larger_clone():
    n, tracks = _two_groups(first_group=0)
    assert n == 1
    assert tracks[0][0] >= P.MAX_PATTERNS - 1, "the start subtune's clone"
    assert tracks[3][0] == 1, "the larger clone of group 1 stays on its original"


def test_first_group_is_inert_where_the_plan_fits():
    def build(first):
        pats = _table(2, 10)
        tracks = [[0, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2 \
            + [[1, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2
        writes = [(3, 0, {0: _ph(0x900)}), (0, 0, {0: _ph(0x800)})]
        P.apply_pulse_phase(pats, tracks, writes, INDEX, None,
                            row_seconds=[1.0, 1.0], first_group=first)
        return pats, tracks
    assert build(None) == build(0) == build(1)


def test_a_first_group_row_that_cannot_take_the_command_serves_nothing():
    pats = _table(2, 1)
    pats[0] = _pattern(0, command_on=(0,))        # group 0's only row is taken
    tracks = [[0, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2 \
        + [[1, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2
    writes = [(0, 0, {0: _ph(0x800)}), (3, 0, {0: _ph(0x900)})]
    n = P.apply_pulse_phase(pats, tracks, writes, INDEX, None,
                            row_seconds=[1.0, 1.0], first_group=0)
    assert n == 1
    assert tracks[3][0] >= P.MAX_PATTERNS - 1, "the copy is not spent on a taken row"


def test_gremlins_start_subtune_voice_2_gets_the_free_copies():
    """Gremlins under forced `pulse_phase`: 11 free slots, 348 wanted. Track 2
    is subtune 0's voice 2 (67 clones, 299 note rows)."""
    import json
    import fidelity as F
    from h2g import convert as C
    from test_pulse_phase import _corpus_and_presets
    corpus, doc = _corpus_and_presets()
    kwargs = F._preset_opts(doc, "Gremlins.sid")
    kwargs["pulse_phase"] = True
    seen: dict = {}
    real = C.apply_pulse_phase

    def spy(patterns, tracks, writes, index, *a, **kw):
        before = len(patterns)
        seen["first_group"] = kw.get("first_group")
        seen["room"] = P.MAX_PATTERNS - before
        out = real(patterns, tracks, writes, index, *a, **kw)
        seen["clones"] = {ti: len({n for n in t if before <= n < P.MAX_PATTERNS})
                          for ti, t in enumerate(tracks)}
        return out
    C.apply_pulse_phase = spy
    try:
        C.convert(str(corpus / "Gremlins.sid"), log=lambda m: None, **kwargs)
    finally:
        C.apply_pulse_phase = real
    assert seen["first_group"] == 0
    assert seen["room"] == 11
    assert seen["clones"][2] == 11, seen["clones"]
    assert sum(v for k, v in seen["clones"].items() if k != 2) == 0, seen["clones"]
