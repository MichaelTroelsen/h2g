"""ILV "restore" may write a `B` on pattern row 0 when that command cell is
empty at plan time.

Row 0's command column belongs to the subtune's clock, but `apply_tempos`
runs before `ilv_filter_routing_plan` (convert.py), so a clock that needs the
cell has already taken it; an empty row-0 cell is free. Sun_Never_Shines'
last 10 late rows were all changes landing on a row 0 (10 -> 0). "params" and
"shared" keep refusing row 0: only "restore" is relaxed.

SABOTAGE TARGET: restore the old `r and not cmd` condition in
`_ilv_routing_walk` (drop `or mode == "restore"`) and the first and last
tests here (and test_ilv_passband_restore.py::test_sun_takes_the_restore_spelling_and_stops_lagging) fail.
"""
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus  # noqa: F401
from h2g.convert import convert
from h2g.goatwriter import (CMD_SETFILTERCTRL, CMD_SETFILTERPTR,
                            _ilv_routing_walk, _ilv_voice_rows, pattern_rows)

REPO = Path(__file__).resolve().parents[2]
_REST = (0xBD, 0, 0, 0)
_MAJ = 1
_PROGRAMS = {0: (0x10, 0x40, 0x80, 0)}
_TEMPO = 0x0F


def _pattern(rows, length=8):
    rows = dict(rows)
    out = []
    for r in range(length):
        out += list(rows.get(r, _REST))
    return out + [0xFF, 0, 0, 0]


def _walk(patterns, tracks, mode):
    first = [_ilv_voice_rows(t, patterns) for t in tracks]
    horizon = max(len(f) for f in first)
    groups = [(horizon, [_ilv_voice_rows(t, patterns, horizon)
                         for t in tracks])]
    restore = None
    if mode == "restore":
        restore = {"pb": 0x10, "majority": frozenset({0}), "next": 7,
                   "len": {0: 3}, "blocks": {}}
    return _ilv_routing_walk(groups, patterns, 1, {0}, _PROGRAMS, mode,
                             {0: 0x41}, {}, restore)


def _song(row0_of_voice1=(0xBD, 0, 0, 0)):
    """Voice 0 plays a routed note on row 1 of pattern 0 (the passband is then
    the majority's). Voice 2 enters a routed note on row 0 of pattern 2, so
    its union change lands on a row 0."""
    patterns = [_pattern({1: (0x90, _MAJ, 0, 0)}),
                _pattern({0: row0_of_voice1}),
                _pattern({0: (0x92, _MAJ, 0, 0)})]
    tracks = [[0, 1, 0xFF, 0], [1, 1, 0xFF, 0], [1, 2, 0xFF, 0]]
    return patterns, tracks


def _row0(plan):
    return {k: v[0] for k, v in plan.items() if 0 in v}


def test_restore_writes_a_b_on_an_empty_row_0_cell():
    patterns, tracks = _song()
    plan, stats = _walk(patterns, tracks, "restore")
    got = _row0(plan)
    assert got and all(c[0] == CMD_SETFILTERCTRL for c in got.values()), plan
    assert stats["late_rows"] == 0, stats


def test_params_and_shared_never_write_row_0():
    patterns, tracks = _song()
    for mode in ("params",):
        plan, _stats = _walk(patterns, tracks, mode)
        assert _row0(plan) == {}, (mode, plan)


def test_restore_leaves_an_occupied_row_0_alone():
    """The clock's cell: every voice's row 0 holds a command (the tempo), so
    the change waits for a row that has a free cell, as before."""
    patterns, tracks = _song()
    for p in (0, 1, 2):
        patterns[p][2], patterns[p][3] = _TEMPO, 5
    plan, _stats = _walk(patterns, tracks, "restore")
    assert _row0(plan) == {}, plan


@needs_corpus
def test_sun_no_longer_has_late_rows_and_keeps_its_tempo_rows():
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = F._preset_opts(doc, "Sun_Never_Shines.sid")
    lines = []
    blob = convert(str(CORPUS / "Sun_Never_Shines.sid"), log=lines.append,
                   **opts)
    line = next(m for m in lines if m.startswith("ILV filter routing"))
    assert " 0 row(s) late," in line and " 0 lagged," in line, line
    song = parse_sng(blob)
    tempo_rows = sum(cmd == _TEMPO for p in song.patterns
                     for r, (_n, _i, cmd, _d) in enumerate(pattern_rows(p))
                     if r == 0)
    base = 0 if (opts.get("tempo") is False) else 1
    assert tempo_rows >= base, tempo_rows
    row0_b = [(r, cmd) for p in song.patterns
              for r, (_n, _i, cmd, _d) in enumerate(pattern_rows(p))
              if r == 0 and cmd in (CMD_SETFILTERCTRL, CMD_SETFILTERPTR)]
    assert row0_b, "the row-0 changes were not written"
