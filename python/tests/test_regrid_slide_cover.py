"""A regrid pair no clean row can take goes inside a run of identical 1XY/2XY.

`patterns._slide_covered_regrid_spot`: a one-shot `CMD_SETTEMPO` leaves the
running slide alone (player.s `mt_tick0_f` never writes `mt_chnfx`), so
overwriting a repeated slide cell keeps the slide. Ties (3XY) are excluded: the
cell decides whether its note is retriggered.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus
from h2g.goatwriter import CMD_SETTEMPO
from h2g.patterns import (CMD_TONEPORTA, GT_END_PATTERN, _regrid_spots,
                          _slide_covered_regrid_spot, regrid_tempos)


def _pattern(rows, cmds):
    out = []
    for r in range(rows):
        c, p = cmds.get(r, (0, 0))
        out += [0xBD, 1, c, p]
    return out + [GT_END_PATTERN, 0, 0, 0]


def _full(rows, cell):
    return _pattern(rows, {r: cell for r in range(1, rows)})


def test_a_full_slide_run_takes_the_pair_and_keeps_every_slide_cell():
    pat = _full(12, (1, 2))
    pats, log = [pat], []
    n = regrid_tempos(pats, [[0], [], []], [3], [0.1], 1, log.append)
    assert n == 1, log
    rows = [r for r in range(len(pat) // 4) if pats[0][r * 4 + 2] == CMD_SETTEMPO]
    assert rows == [6, 7]
    for r in range(1, 12):
        if r not in rows:
            assert pats[0][r * 4 + 2:r * 4 + 4] == [1, 2]


def test_a_tie_run_is_not_covered():
    pat = _full(12, (CMD_TONEPORTA, 0))
    assert _slide_covered_regrid_spot(pat, 6, 12) is None
    assert _regrid_spots(pat, 1, 12) == ([], 1)


def test_a_changing_slide_parameter_is_not_covered():
    pat = _pattern(12, {r: (1, 1 + r) for r in range(1, 12)})
    assert _slide_covered_regrid_spot(pat, 6, 12) is None


def test_the_first_cell_of_a_run_is_never_overwritten():
    pat = _pattern(12, {5: (2, 3), 6: (2, 3)})
    assert _slide_covered_regrid_spot(pat, 6, 12) is None
    pat = _pattern(12, {5: (2, 3), 6: (2, 3), 7: (2, 3)})
    assert _slide_covered_regrid_spot(pat, 6, 12) == 6
    pat = _pattern(12, {6: (2, 3), 7: (2, 3), 8: (2, 3)})
    assert _slide_covered_regrid_spot(pat, 6, 12) == 7


@needs_corpus
def test_nineteen_places_its_unplaced_pair():
    import json
    import warnings
    import fidelity as F
    from h2g.convert import convert
    warnings.simplefilter("ignore")
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    logs = []
    convert(str(CORPUS / "Nineteen.sid"), log=logs.append,
            **F._preset_opts(doc, "Nineteen.sid"))
    line = [m for m in logs if m.startswith("Re-grid")][0]
    assert "skipped" not in line, line
