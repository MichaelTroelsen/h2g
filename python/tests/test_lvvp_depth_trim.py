"""Las_Vegas_Video_Poker's $6B9A keeps the original's vibrato depth
(las-vegas-classic-vibrato-original-depth, user decision 2026-10-09).

`goatwriter.vibrato.CLASSIC_DEPTH_CMP_TRIM` takes one call off the `cmp` of
record 6 (`$6B9A`) only: `($8C, 4)` -> `($8B, 4)`. Record 11 (`$0AA0`) shares
the vibrato byte `$1A` and keeps `($8C, 4)` byte for byte; the entry formula
(`_classic_vibrato_entry`) is not touched, so every other file's bytes are the
ones they were. Measured figures are in that function's docstring ("DECIDED").
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import h2g.goatwriter.vibrato as V                            # noqa: E402
from h2g.detect import detect                                 # noqa: E402
from h2g.goatwriter import _classic_vibrato_entry             # noqa: E402
from h2g.goatwriter.constants import FORMAT_GTS5              # noqa: E402
from h2g.goatwriter.tempo import outer_gate_skip              # noqa: E402
from h2g.sidfile import load_sid                              # noqa: E402

LVVP = CORPUS / "Las_Vegas_Video_Poker.sid"
NAME = "Las Vegas Video Poker"
MULT, ROW_CALLS, GATE_SKIP = 4, 15, 4     # the preset -S4, short_row_calls, the outer gate


def test_the_trim_takes_one_call_off_record_six_only():
    shipped = _classic_vibrato_entry(0x1A, MULT, ROW_CALLS,
                                     gate_skip=GATE_SKIP)
    assert shipped == (0x8C, 4)
    assert V._depth_trimmed(NAME, 6, shipped) == (0x8B, 4)
    assert V._depth_trimmed(NAME, 11, shipped) == shipped
    assert V._depth_trimmed("Warhawk", 6, shipped) == shipped
    assert V._depth_trimmed(NAME, 6, None) is None
    assert V.CLASSIC_DEPTH_CMP_TRIM == {(NAME, 6): 1}


def test_the_trim_cannot_underflow_cmp():
    assert V._depth_trimmed(NAME, 6, (0x80, 3)) == (0x80, 3)


@needs_corpus
def test_the_layout_gives_record_six_its_own_entry_and_leaves_the_rest(monkeypatch):
    sid = load_sid(str(LVVP))
    assert sid.name == NAME
    det = detect(sid, lambda *a: None)
    # The two records the decision names carry one vibrato byte.
    off = det.vibrato_offset
    stride = det.instr_stride
    byte = lambda i: sid.data[det.instr_start + i * stride + off]
    assert byte(6) == byte(11) == 0x1A

    def layout():
        table: list = []
        out = V._vibrato_layout(sid, det, 30, True, FORMAT_GTS5, MULT, table,
                                row_calls=ROW_CALLS,
                                gate_skip=outer_gate_skip(sid))
        return {i: table[idx - 1] for i, (idx, _delay) in out.items()}

    after = layout()
    monkeypatch.setattr(V, "CLASSIC_DEPTH_CMP_TRIM", {})
    before = layout()
    assert before[6] == before[11] == (0x8C, 4)
    assert after[6] == (0x8B, 4)
    assert after[11] == (0x8C, 4)
    assert {i: e for i, e in after.items() if i != 6} == \
           {i: e for i, e in before.items() if i != 6}
