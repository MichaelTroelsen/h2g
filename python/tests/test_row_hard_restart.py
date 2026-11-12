"""`row_hard_restart`: the gate-off before a note as long as the whole last row.

The Hubbard players release for exactly one beat, the converter's row. Goattracker
fetches the next row `gatetimer` calls early and the gate drops then, so the gap
is the gatetimer -- and `max_hard_restart` stops at `row - 1`, one frame short of
the original on every note of a `no_test_restart` song (the test-bit restart
frame is what makes `row - 1` enough elsewhere). Ninja at -S1: the original gates
off 4 frames before each note, the conversion 3 (2369 of 2427 miss frames, gate
74.8%); with the gatetimer at the row's 4 the gap is 4 and gate reads 99.4%,
attacks and melody unchanged. gplay.c:334 stops the EDITOR at that value; the
packed player does not (player.s:716-736), and one past the row collapses it
(Ninja: 3 attacks of 2378).
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import _hard_restart_ticks  # noqa: E402


def test_row_takes_the_whole_row_and_default_still_stops_short():
    for mult in (1, 2, 3):
        for rows in (3, 4, 8, 9):
            assert _hard_restart_ticks(mult, rows, False, True, 8) == rows - 1
            assert _hard_restart_ticks(mult, rows, False, True, 8,
                                       row=True) == rows


def test_row_is_inert_where_the_row_is_unknown_or_one_call():
    assert _hard_restart_ticks(1, 0, row=True) == _hard_restart_ticks(1, 0)
    assert _hard_restart_ticks(1, 1, row=True) == _hard_restart_ticks(1, 1)


def _stored(name, **extra):
    import json
    import fidelity as F
    import songview
    from h2g.convert import convert
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, name)
    opts.update(extra)
    sng = convert(str(CORPUS / name), log=lambda m: None, **opts)
    return sng, [i.gatetimer & 0x3F for i in songview.parse_sng(sng).instruments]


@needs_corpus
def test_ninja_stores_row_minus_one_which_the_editor_allows():
    """Ninja: 4-call rows, `aligned_firstwave` trims one, so the schedule's 3
    is stored as 2 and the row option's 4 as 3 -- `row - 1`, never past the
    tick (gplay.c:334), and one more frame of gate-off than the default."""
    _, off = _stored("Ninja.sid", row_hard_restart=False)
    _, on = _stored("Ninja.sid", row_hard_restart=True)
    assert max(off) == 2, off
    assert max(on) == 3, on
    assert max(on) <= 4 - 1


@needs_corpus
def test_without_the_trim_the_option_stops_at_row_minus_one():
    """Pandora (4-call rows) has no `aligned_firstwave`: a whole-row value
    would be stored as 4 and stop the editor (gplay.c:334), so the writer
    clamps it to the old bound, 3 -- the option never stores past the tick."""
    _, off = _stored("Pandora.sid", row_hard_restart=False)
    _, on = _stored("Pandora.sid", row_hard_restart=True)
    assert max(off) == 2, off
    assert max(on) == 3, on
