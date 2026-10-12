"""`skydive_row_offset` is for rows of whole frames (`goatwriter.skydive`).

The offset is the residue of a row's tick 0 in its frame, `1 mod multiplier`,
only while every row before it is `row_calls` long with `row_calls` a multiple
of the multiplier. A song with a row of `row_calls` calls that is not -- the
fractional-row pass, the orderlist step tempos (`$FE nn`), the regrid
compensation (`CMD_SETTEMPO base + 1` on one hold row), a 2-call
`CMD_FUNKTEMPO` row -- moves it, and a program counted call by call is then
right for one residue and a call early or late on the others. None of the two
corpus files that emit the program above -S1 has such a row (Master_of_Magic,
One_Man_and_his_Droid: every row `CMD_SETTEMPO 4` at -S2), so the plan declines
the orderlist instead of emitting a program it cannot place.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_FUNKTEMPO, CMD_SETTEMPO)  # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _lap(*cmds):
    """One pattern whose rows carry `cmds` ((command, data) pairs) and the lap
    over it, as `skydive._lap_rows` yields it."""
    pat = []
    for cmd, data in cmds:
        pat += [0xBD, 1, cmd, data]
    return [pat], [(0, r, 0) for r in range(len(cmds))]


@pytest.mark.parametrize("mult,cmds,off", [
    (2, [(CMD_SETTEMPO, 4), (0, 0)], False),
    (2, [(CMD_SETTEMPO, 4), (CMD_SETTEMPO, 5), (CMD_SETTEMPO, 4)], True),
    (2, [(CMD_SETTEMPO, 0x84)], False),            # per-channel, still 4 calls
    (2, [(CMD_SETTEMPO, 0x85)], True),
    (3, [(CMD_SETTEMPO, 8)], True),                # Lion_Heart's row at -S3
    (3, [(CMD_SETTEMPO, 9), (CMD_SETTEMPO, 6)], False),
    (2, [(CMD_FUNKTEMPO, 1)], True),               # a 2-call row
    (1, [(CMD_SETTEMPO, 5), (CMD_FUNKTEMPO, 1)], False),    # residue 0 at -S1
    (2, [(0x1, 5), (0x2, 3)], False),              # data of other commands
])
def test_a_lap_with_a_row_that_is_not_whole_frames_is_off_the_grid(
        mult, cmds, off):
    patterns, rows = _lap(*cmds)
    assert S.rows_off_the_frame_grid(rows, patterns, mult) is off


def _converted(name):
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append,
                    **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng, lines


@needs_corpus
def test_master_of_magic_keeps_its_program_and_a_5_call_row_costs_it(monkeypatch):
    """Row 1 of every pattern a 5-call row at -S2: the plan reads an off-grid
    lap and emits nothing, and says why. Unmodified, it emits its program."""
    _sng, lines = _converted("Master_of_Magic")
    (msg,) = [m for m in lines if m.startswith("Skydive (bit $02)")]
    assert "4 window row(s)" in msg and "not whole frames" not in msg, msg

    real = S.skydive_plan

    def with_a_5_call_row(sid, det, tracks, patterns, *a, **k):
        patterns = [list(p) for p in patterns]
        for p in patterns:
            if len(p) > 7 and p[4] != 0xFF:
                p[6], p[7] = CMD_SETTEMPO, 5
        return real(sid, det, tracks, patterns, *a, **k)

    monkeypatch.setattr(S, "skydive_plan", with_a_5_call_row)
    _sng, lines = _converted("Master_of_Magic")
    (msg,) = [m for m in lines if m.startswith("Skydive (bit $02)")]
    assert "none taken" in msg and "not whole frames" in msg, msg
