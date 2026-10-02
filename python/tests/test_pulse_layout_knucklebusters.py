"""Knucklebusters' pulse table, the corpus file that fills it: a played record
keeps at least its SET when the table is full, and GT26 is the one that pays.

The task this pins asked for a set-vs-sweep preference in `_lay_out_pulse`:
drop a program's sweep and keep its set rather than drop a later program
whole. Measured on the tree as found (Knucklebusters under its presets, the
usage pass of `_pulse_layout` in place), that preference already holds: the
table is 255 of 255; GT26 (record 25, 8 notes sounded, all in subtune 2)
keeps its set `$81 $40` at pointer 249 and loses only its sweep; the one
record with pointer 0 is GT29, which sounds nothing. GT26's full block is
eight entries and the played records ahead of it in usage order leave seven,
so no reordering among them buys it the sweep -- only a cheaper encoding of
its block could (its loop body is GT14's, entry for entry). See the comment
above `_lay_out_pulse`.
"""
import json
import sys
from pathlib import Path

from corpus import CORPUS, needs_corpus

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent
NAME = "Knucklebusters.sid"


def _convert_capturing(monkeypatch):
    """Convert under presets; return (sng, usage, programs, statics, lead)."""
    sys.path.insert(0, str(PYTHON_ROOT))
    import fidelity
    from h2g import goatwriter as gw
    from h2g.convert import convert
    presets = REPO_ROOT / "presets.json"
    if not presets.exists() or not (CORPUS / NAME).exists():
        pytest.skip(f"presets.json or {NAME} not available here")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, NAME)
    usages: list = []
    layouts: list = []
    real_usage, real_lay = gw.pulse_usage, gw._lay_out_pulse

    def usage(*a, **k):
        u = real_usage(*a, **k)
        usages.append(u)
        return u

    def lay(programs, statics, lead, share, **k):
        layouts.append((programs, statics, lead))
        return real_lay(programs, statics, lead, share, **k)

    monkeypatch.setattr(gw, "pulse_usage", usage)
    monkeypatch.setattr(gw, "_lay_out_pulse", lay)
    out = convert(str(CORPUS / NAME), **opts)
    assert usages and layouts, "the pulse layout never ran"
    programs, statics, lead = layouts[-1]
    return out, usages[-1], programs, statics, lead


@needs_corpus
def test_every_played_record_keeps_its_set_and_gt26_loses_only_its_sweep(
        monkeypatch):
    import songview
    out, usage, programs, statics, lead = _convert_capturing(monkeypatch)
    song = songview.parse_sng(out)
    ptbl = song.tables["PTBL"]
    assert len(ptbl) == 255, "the premise: Knucklebusters fills the table"
    by_number = {ins.number: ins for ins in song.instruments}
    played = [i for i, u in enumerate(usage) if u]
    assert 25 in played and usage[25] == 8, \
        "the premise: GT26 is record 25 and sounds 8 notes"
    for i in played:
        ptr = by_number[lead + i + 1].pulse_ptr
        assert ptr, f"GT{lead + i + 1} sounds {usage[i]} notes and has no width"
        assert ptbl[ptr - 1] == statics[i][0], \
            f"GT{lead + i + 1}'s pointer does not open on its own set"
    # GT26 is the one that pays: every other played record keeps its whole
    # program. Neither the usage pass nor its reservation decides that here:
    # with either removed the layout's bytes move but GT26 is still the only
    # played record short of its sweep and GT29 the only one with pointer 0.
    # Those two are pinned synthetically in test_pulse.py; on this file only
    # the static fallback in `_lay_out_pulse` is load-bearing.
    short = []
    for i in played:
        ptr, (program, _) = by_number[lead + i + 1].pulse_ptr, programs[i]
        if list(ptbl[ptr - 1:ptr - 1 + len(program)]) != list(program):
            short.append(lead + i + 1)
    assert short == [lead + 26], f"played records without their sweep: {short}"
    gt26 = by_number[lead + 26].pulse_ptr
    assert list(ptbl[gt26 - 1:gt26 + 1]) == list(statics[25]), \
        "GT26 keeps exactly its static pair: its set, then stop"
