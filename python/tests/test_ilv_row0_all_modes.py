"""ILV routing: every spelling ("params", "shared", "restore") may write a `B`
on an EMPTY pattern row-0 command cell, not only "restore".

Go_Go_Dash's seven unplaceable changes (shared spelling) were all row-0 cells;
the late `B $00` / union `B` left the filter program sweeping the cutoff with
$D417 at $00 (23 frames at v0.5.5xx, 242,688 unrouted travel at -t 180). Now 0
unplaceable, 0 rows late.

SABOTAGE TARGET: put `r and` back in front of `not cmd` in the placement
condition of `_ilv_routing_walk` (filters.py): the synthetic test and the
Go_Go_Dash log test fail.
"""
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus  # noqa: F401
from h2g.convert import convert
from test_ilv_row0_restore import _song, _walk, _row0, _TEMPO

REPO = Path(__file__).resolve().parents[2]


def test_shared_takes_an_empty_row_0_cell_and_loses_no_row():
    patterns, tracks = _song()
    plan, stats = _walk(patterns, tracks, "shared")
    assert _row0(plan), plan
    assert stats["unplaceable"] == 0, stats


def test_an_occupied_row_0_cell_is_still_left_alone():
    patterns, tracks = _song()
    for p in (0, 1, 2):
        patterns[p][2], patterns[p][3] = _TEMPO, 5
    plan, _stats = _walk(patterns, tracks, "shared")
    assert _row0(plan) == {}, plan


@needs_corpus
def test_go_go_dash_has_no_unplaceable_change():
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = F._preset_opts(doc, "Go_Go_Dash.sid")
    lines = []
    convert(str(CORPUS / "Go_Go_Dash.sid"), log=lines.append, **opts)
    line = next(m for m in lines if m.startswith("ILV filter routing"))
    assert " 0 unplaceable," in line and " 0 row(s) late," in line, line
