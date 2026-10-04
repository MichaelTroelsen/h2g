"""`_pulse_layout`'s "KEEP A STATIC WIDTH" count excludes records that then
lost even the static pair (they are the "SET NO WIDTH AT ALL" count)."""
import re

from h2g.goatwriter import _pulse_layout, _pulse_program
from h2g.goatwriter import constants as _constants
from test_pulse import _det, _record, _sid


def test_keep_static_count_excludes_records_that_set_no_width(monkeypatch):
    n = 8
    sid = _sid([_record(pulse_lo=i, rate=0x01) for i in range(n)], [0xF0] * n)
    det = _det(n)
    sweep = len(_pulse_program(sid, det, 0, True, 1)[0])
    monkeypatch.setattr(_constants, "GT_MAX_TABLELEN", 2 + sweep + 1 + 2 * 3 + 1)
    messages = []
    entries, starts = _pulse_layout(sid, det, n + 1, True, 1, messages.append)
    rec = starts[1:]
    silent = rec.count(0)
    kept = sum(1 for i in range(n) if rec[i]
               and entries[rec[i] - 1:rec[i] + 1]
               == _pulse_program(sid, det, i, False, 1)[0])
    assert silent >= 1 and kept >= 1, (silent, kept, rec)
    line = next(m for m in messages if "KEEP A STATIC" in m)
    shown = (int(re.search(r"FULL -- (\d+) ", line).group(1)),
             int(re.search(r", (\d+) SET NO", line).group(1)))
    assert shown == (kept, silent), (line, kept, silent)
