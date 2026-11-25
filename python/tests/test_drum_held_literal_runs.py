"""`drum_held.literal_runs`: a repeat count whose plays land on different
clock residues stays written out, so the plan can spell each play.

The plays of a repeat count share one pattern cell, and `pack_repeats` folds
every run of one pattern into one. `drum_held_plan` then declined every note
row the plays disagreed on (`visits disagree`): Proteus 130 of them, with 68
rows spelled; 120 of the 145 notes whose original holds the noise a second
frame and ours did not were in those runs (heard.py, 180 s). The orderlist
is not the limit -- Proteus' three unpacked orderlists are 73, 90 and 166
bytes -- so `reindex_tracks(keep_literal=...)` writes those runs out.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import drum_held                         # noqa: E402
from h2g.patterns import pack_repeats                        # noqa: E402

PROTEUS = CORPUS / "Proteus.sid"
PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
needs_presets = pytest.mark.skipif(not PRESETS.exists(),
                                   reason="presets.json absent")


def test_pack_repeats_writes_a_literal_run_out_and_packs_the_rest():
    track = [3, 3, 3, 3, 4, 4, 4, 4, 255, 0]
    packed = pack_repeats(track)
    assert packed == [0xD3, 3, 0xD3, 4, 255, 0]
    # one index inside the first run keeps that run, and only that run
    assert pack_repeats(track, {2}) == [3, 3, 3, 3, 0xD3, 4, 255, 0]
    assert pack_repeats(track, set()) == packed
    assert pack_repeats(track, {8, 9}) == packed     # the restart is no run


def _log(monkeypatch=None, short_circuit=False):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, PROTEUS.name)
    if short_circuit:
        monkeypatch.setattr(drum_held, "literal_runs",
                            lambda *a, **k: set())
    lines: list = []
    convert(str(PROTEUS), log=lines.append, **opts)
    return next(m for m in lines if m.startswith("Drum held noise"))


@needs_corpus
@needs_presets
def test_proteus_spells_every_play_of_a_repeat_count():
    line = _log()
    assert "visits disagree" not in line, line
    flagged = int(line.split(":")[1].split()[0])
    # 68 of the rows with the runs folded into repeat counts
    assert flagged >= 100, line


@needs_corpus
@needs_presets
def test_short_circuited_literal_runs_decline_the_plays_again(monkeypatch):
    line = _log(monkeypatch, short_circuit=True)
    assert "visits disagree" in line, line
    assert int(line.split(":")[1].split()[0]) < 100, line
