"""The union-fit check in `_lay_pulse_phase_pass` against GT_MAX_TABLELEN.

The check (`<= _gw_constants.GT_MAX_TABLELEN`, the union branch) is inert on
the corpus, so no corpus test notices it moving. This one drives the layout
pass with stubbed sweep params and a stubbed `_phase_block` so a union block
ends exactly 1 row past the limit (and, as a control, exactly on it).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from h2g.goatwriter import constants as K  # noqa: E402
from h2g.goatwriter import pulse as P  # noqa: E402

HEAD = 2  # rows the pass opens with: (80 00) (FF 00)


def _run(monkeypatch, union_len: int):
    phases = {1: {(0x100, 1)}, 2: {(0x200, 1)}}
    unions = {"g": {1: {(0x100, 1), (0x200, 1)}, 2: {(0x100, 1), (0x200, 1)}}}

    def fake_params(sid, det, i, mult):
        return (0x100, 1, 0, 0x1000, False)

    def fake_block(base, num, want_set, *params, share=False):
        n = union_len if num == 0 else 3
        rows = [(0x80, 0x00)] * n
        idx = {(num, w, d): base + 1 + k
               for k, (w, d) in enumerate(sorted(want_set))}
        return rows, idx

    monkeypatch.setattr(P, "_phase_sweep_params", fake_params)
    monkeypatch.setattr(P, "_phase_block", fake_block)
    return P._lay_pulse_phase_pass(None, None, 2, True, 1, phases, None, 0,
                                   True, unions, False)


def test_union_ending_one_row_past_the_limit_is_not_laid(monkeypatch):
    limit = K.GT_MAX_TABLELEN
    entries = _run(monkeypatch, limit - HEAD + 1)[0]
    assert len(entries) <= limit, (
        f"table of {len(entries)} rows past GT_MAX_TABLELEN {limit}")
    assert len(entries) == HEAD + 3 + 3, "records fall back to their own blocks"


def test_union_ending_exactly_on_the_limit_is_laid(monkeypatch):
    limit = K.GT_MAX_TABLELEN
    entries = _run(monkeypatch, limit - HEAD)[0]
    assert len(entries) == limit
