"""A skydive note that runs off the end of a looping lap ends at the lap's
first event (`skydive._lap_restart`, `skydive_plan`).

One_Man_and_his_Droid's pattern 27 row 107 opens the window of three notes:
two mid-lap and one whose note starts 8672 rows into an 8704-row lap and has
no event before the lap ends. That third play used to be skipped ("no end"),
so `take` saw 2 asks for 3 plays and refused the row as "mixed or occupied",
dropping the two real windows (frames 3027 and 6611 on voice 0, 42 store
frames the original lowers the high byte on). The track ends `$FF $00`, so
the note lasts until row 0 of the next lap.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_lap_restart_reads_the_operand_after_ff():
    assert S._lap_restart([5, 6, 0xFF, 0]) == 0
    assert S._lap_restart([5, 6, 0xFF, 3]) == 3
    assert S._lap_restart([5, 6, 7]) is None


@needs_corpus
def test_one_man_places_the_wrapped_play_and_no_row_is_left_mixed():
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    name = "One_Man_and_his_Droid.sid"
    C.convert(str(CORPUS / name), log=lines.append,
              **fidelity._preset_opts(doc, name))
    (msg,) = [m for m in lines if m.startswith("Skydive (bit $02)")]
    assert "9 window row(s)" in msg, msg
    assert "mixed or occupied" not in msg, msg
