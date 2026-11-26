"""Shockway_Rider's vibrato byte $23 gets one more call than the formula gives
(`listen-sub99-shockway-rider`; figures historical, -t 180 at v0.5.676).

`_classic_vibrato_entry` rounds the tick-0-compensated half-period 8 * 4/5 =
6.4 down to 6 calls, which swings 0.75 of the original's with the integer
`rshift` fixed, so `depth` read 0.662. `CLASSIC_DEPTH_CMP_TRIM`'s negative
entries add the call back for the two records carrying the byte (4 and 8):
`($84, 4)` -> `($85, 4)`, `depth` 0.828, `bend` 0.729 -> 0.747, `vib`
1.047 -> 1.014. Record 10 (byte $2B) and every other file keep their bytes.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import h2g.goatwriter.vibrato as V                            # noqa: E402
from h2g.detect import detect                                 # noqa: E402
from h2g.goatwriter import _classic_vibrato_entry             # noqa: E402
from h2g.goatwriter.constants import FORMAT_GTS5              # noqa: E402
from h2g.sidfile import load_sid                              # noqa: E402

SHOCKWAY = CORPUS / "Shockway_Rider.sid"
NAME = "Shockway Rider"
MULT, ROW_CALLS = 2, 5                    # the preset -S2 and the tune's 5-call row


def test_the_formula_gives_84_and_the_trim_adds_one_call_to_records_4_and_8():
    formula = _classic_vibrato_entry(0x23, MULT, ROW_CALLS)
    assert formula == (0x84, 4)
    assert V._depth_trimmed(NAME, 4, formula) == (0x85, 4)
    assert V._depth_trimmed(NAME, 8, formula) == (0x85, 4)
    assert V._depth_trimmed(NAME, 10, formula) == formula
    assert V._depth_trimmed("Warhawk", 4, formula) == formula
    assert V._depth_trimmed(NAME, 4, (0xFF, 3)) == (0xFF, 3)       # cmp stays <= $7F


@needs_corpus
def test_the_layout_gives_the_two_records_one_more_call_and_leaves_the_rest(monkeypatch):
    sid = load_sid(str(SHOCKWAY))
    assert sid.name == NAME
    det = detect(sid, lambda *a: None)
    stride, off = det.instr_stride, det.vibrato_offset
    byte = lambda i: sid.data[det.instr_start + i * stride + off]
    assert byte(4) == byte(8) == 0x23

    def layout():
        table: list = []
        out = V._vibrato_layout(sid, det, 30, True, FORMAT_GTS5, MULT, table,
                                row_calls=ROW_CALLS)
        return {i: table[idx - 1] for i, (idx, _delay) in out.items()}

    after = layout()
    monkeypatch.setattr(V, "CLASSIC_DEPTH_CMP_TRIM", {})
    before = layout()
    assert before[4] == before[8] == (0x84, 4)
    assert after[4] == after[8] == (0x85, 4)
    assert {i: e for i, e in after.items() if i not in (4, 8)} == \
           {i: e for i, e in before.items() if i not in (4, 8)}
