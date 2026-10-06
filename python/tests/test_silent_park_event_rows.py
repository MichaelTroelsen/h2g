"""The silent park pattern carries its event starts to the triangle walk.

`legalise_restarts` appends `tracks.SILENT_PATTERN` (a KEYOFF row, then
ENDPATT) for a tune that ended on Hubbard's `$FE`. It is a pattern of our
own, not a copy, so `patterns.inherit_event_rows` -- which attributes the
later passes' copies by their note column -- found no source for it, and it
reached the walk with no event starts. Measured at 075a175, presets with
`pulse_phase` forced, every file the triangle walk runs on (23): exactly one
pattern on each of 11 files reached the walk unattributed, and on all 11 it
was the silent pattern -- Geoff_Capes on 24 orderlist positions,
Action_Biker / Last_V8 / Last_V8_C128_version / Zoids 6, Master_of_Magic 5,
Commando / Confuzion / Monty_on_the_Run / Phantoms_of_the_Asteroid /
Rasputin 3 (the census the task `event-rows-unknown-copies` opened with).
With the pass entering `SILENT_EVENT_ROWS` the census reads 0.

The walk read it by its bytes, where a KEYOFF row is a fetch, so `{0}` is
the same answer and the corpus byte-hash moved nothing (89 converted, 6
refused, 89 compared, 0 moved, shipped and forced).
"""
import json
import sys
from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent
sys.path.insert(0, str(PYTHON_ROOT))

from h2g import patterns as P  # noqa: E402
from h2g.tracks import (SILENT_EVENT_ROWS, SILENT_PATTERN,  # noqa: E402
                        legalise_restarts)

CORPUS = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")

# Orderlist positions naming the silent pattern, per file, at 075a175
# (presets + pulse_phase forced): the census of unattributed patterns
# before this change, every one of them the silent pattern.
PARKED_REFS = {
    "Action_Biker.sid": 6, "Commando.sid": 3, "Confuzion.sid": 3,
    "Geoff_Capes_Strongman_Challenge.sid": 24, "Last_V8.sid": 6,
    "Last_V8_C128_version.sid": 6, "Master_of_Magic.sid": 5,
    "Monty_on_the_Run.sid": 3, "Phantoms_of_the_Asteroid.sid": 3,
    "Rasputin.sid": 3, "Zoids.sid": 6,
}


def _ended(entries):
    return list(entries) + [P.GT_ORDER_RESTART, 0xFD]


def test_the_park_enters_the_silent_patterns_event_starts():
    patterns = [[0] * 8, [0] * 8]
    tracks = [_ended([0, 1]), _ended([1]), _ended([0])]
    ev = {0: frozenset({0}), 1: None}
    assert legalise_restarts(tracks, None, patterns, event_rows=ev) == 3
    silent = len(patterns) - 1
    assert patterns[silent] == SILENT_PATTERN
    assert ev == {0: frozenset({0}), 1: None, silent: frozenset({0})}


def test_without_the_channel_or_the_park_nothing_is_entered():
    patterns = [[0] * 8]
    assert legalise_restarts([_ended([0])], None, patterns) == 1
    ev = {}
    # restart-0 workaround: no pattern appended, so nothing to enter
    assert legalise_restarts([_ended([0])], None, None, event_rows=ev) == 1
    assert ev == {}


def test_the_entry_is_what_the_bytes_say():
    """`SILENT_EVENT_ROWS` must be the rows the walk's bytes reading calls
    a fetch (`_triangle_rows`' fallback), or entering it would move a
    plan the file never asked to move."""
    by_bytes = frozenset(
        r for r, kind, _ in P._phase_note_rows(SILENT_PATTERN, 0, {})
        if kind == "note" or SILENT_PATTERN[4 * r] == P.GT_KEYOFF
        or SILENT_PATTERN[4 * r + 1])
    assert SILENT_EVENT_ROWS == by_bytes == frozenset({0})


def test_a_copy_of_the_silent_pattern_inherits_it():
    patterns = [[0] * 8, list(SILENT_PATTERN),
                [x if i != 2 else 0x0F for i, x in enumerate(SILENT_PATTERN)]]
    out = P.inherit_event_rows(patterns, {0: frozenset({0}),
                                          1: SILENT_EVENT_ROWS})
    assert out[2] == SILENT_EVENT_ROWS


def _walk_call(name, **force):
    import fidelity
    from h2g import convert as C
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    kw = fidelity._preset_opts(doc, name)
    kw.update(force)
    calls, parks = [], []
    real_walk, real_park = C.collect_pulse_phases, C.legalise_restarts

    def walk(pats, tracks, *a, **k):
        calls.append((pats, [list(t) for t in tracks], k.get("event_rows")))
        return real_walk(pats, tracks, *a, **k)

    def park(*a, **k):
        parks.append(k.get("event_rows"))
        return real_park(*a, **k)
    C.collect_pulse_phases, C.legalise_restarts = walk, park
    try:
        C.convert(str(CORPUS / name), log=lambda *a, **k: None, **kw)
    finally:
        C.collect_pulse_phases, C.legalise_restarts = real_walk, real_park
    return calls, parks


def _need(name):
    if not (REPO_ROOT / "presets.json").exists() or not (CORPUS / name).exists():
        pytest.skip("corpus or presets.json not available here")


@pytest.mark.parametrize("name", sorted(PARKED_REFS))
def test_the_walk_receives_no_unattributed_pattern(name):
    _need(name)
    calls, _ = _walk_call(name, pulse_phase=True)
    assert calls, "the triangle walk did not run"
    pats, tracks, ev = calls[0]
    unknown, parked = set(), 0
    for t in tracks:
        for b in t:
            if b == P.GT_ORDER_RESTART:
                break
            if b >= P.MAX_PATTERNS or b >= len(pats):
                continue
            if list(pats[b]) == SILENT_PATTERN:
                parked += 1
                assert ev.get(b) == SILENT_EVENT_ROWS, b
            if b not in ev:
                unknown.add(b)
    assert parked == PARKED_REFS[name]
    assert unknown == set()


def test_the_channel_is_entered_only_where_the_walk_asked():
    name = "Geoff_Capes_Strongman_Challenge.sid"
    _need(name)
    _, parks = _walk_call(name, pulse_phase=False)
    assert parks == [None]
    _, parks = _walk_call(name, pulse_phase=True)
    assert len(parks) == 1 and parks[0] is not None
