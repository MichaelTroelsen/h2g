"""The skydive tie window above -S1, and the window that starts too early.

`test_skydive_tie_window.py` measures Zoids' two tied windows at -S1, the one
rate the corpus has them at (Zoids is the only file whose plan reports a tie;
every other tied note is on a record that is not a skydive). Above -S1 the
pointer row's program starts through `skydive_row_offset` and every frame is
`multiplier` calls, and nothing but arithmetic had said that the tie window
survives that. Zoids is therefore replanned here as if it were packed at -S2
and -S3: the plan is called with the multiplier forced and every row's
`CMD_SETTEMPO` scaled to a whole number of frames, the table ceiling lifted
(the tie programs are twice and three times as long and Zoids' table is
already at 254/255 at -S1), and the held programs only (`window_vibrato`
None), so the program under test is `skydive_program` itself. The plan is
inspected and the build stopped there: a synthetic -S2 Zoids is not a
conversion anyone ships.

A window whose store 0 falls two or more frames before the pointer row
(`tie_window_phase` < -1) is DECLINED, not emitted from a later store: the
tie row's own command column is the tie and cannot take a pointer, and the
row before it is not a row the tie's fall can start on. Pinned below by moving
Zoids' counter one frame, which turns its ties from phase 2 into phase 1.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import arpeggio as A                     # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETTEMPO,          # noqa: E402
                                      CMD_SETWAVEPTR)

import test_skydive_tie_window as T                          # noqa: E402

TIE_NEXT_ROWS = ((0x26, 65), (0x27, 10))


class _Stop(Exception):
    pass


def _plan(monkeypatch, multiplier, *, flip_parity=False,
          no_test_restart=None):
    """Zoids' skydive plan as if packed at -S`multiplier`: the plan or None,
    the log lines, the speed table and the wavetable the plan appends to."""
    real = S.skydive_plan
    got = {}
    monkeypatch.setattr(S, "GT_MAX_TABLELEN", 4000)
    monkeypatch.setattr(S, "window_vibrato", lambda *a, **k: None)
    if flip_parity:
        real_base = A.frame_counter_base
        monkeypatch.setattr(
            A, "frame_counter_base",
            lambda *a, **k: (lambda b: None if b is None else b + 1)(
                real_base(*a, **k)))

    def forced(sid, det, tracks, patterns, lead, instr_used, fmt, mult,
               gate, table, wave_used, ntr, *rest, **kw):
        patterns = [list(p) for p in patterns]
        for p in patterns:
            for i in range(2, len(p), 4):
                if p[i] == CMD_SETTEMPO:
                    p[i + 1] = (p[i + 1] & 0x80) | (
                        (p[i + 1] & 0x7F) * multiplier)
        mine = kw.get("log")
        kw["log"] = lambda m: (got.setdefault("lines", []).append(m),
                               mine and mine(m))
        got["plan"] = real(sid, det, tracks, patterns, lead, instr_used, fmt,
                           multiplier, gate, table, wave_used,
                           ntr if no_test_restart is None else no_test_restart,
                           *rest, **kw)
        got["table"] = list(table)
        got["wave"] = list(kw["wave_entries"])
        raise _Stop

    monkeypatch.setattr(S, "skydive_plan", forced)
    lines = []
    with pytest.raises(_Stop):
        import json
        import fidelity
        import h2g.convert as C
        doc = json.loads((T.PYTHON_ROOT.parent / "presets.json").read_text())
        C.convert(str(CORPUS / "Zoids.sid"), log=lines.append,
                  **fidelity._preset_opts(doc, "Zoids.sid"))
    return got["plan"], got.get("lines", []), got["table"], got["wave"]


def _run(wave, start):
    out, at, seen = [], start, set()
    while True:
        assert at not in seen and 1 <= at <= len(wave)
        seen.add(at)
        left, right = wave[at - 1]
        if left == 0xFF:
            if right == 0:
                return out
            at = right
            continue
        out.append((left, right))
        at += 1


@needs_corpus
def test_the_tie_window_is_pointed_and_writes_every_call_at_s2(
        monkeypatch):
    multiplier = 2
    plan, lines, table, wave = _plan(monkeypatch, multiplier)
    assert plan is not None
    log = [m for m in lines if m.startswith("Skydive (bit $02)")][0]
    assert "after a tie: 2 row(s)" in log, log
    wave = wave + plan.entries
    if plan.base is not None:
        wave = plan.base + plan.entries

    def index(k):
        return table.index(S.skydive_speed(k, multiplier)) + 1

    want = S.skydive_program(0, 35, True, index, multiplier)[:-1]
    for p, r in TIE_NEXT_ROWS:
        cell = plan.patterns[p][4 * r:4 * r + 4]
        assert cell[2] == CMD_SETWAVEPTR, (p, r, cell)
        # the pointer's program is the held alternating fall from the row's
        # first call (store 0 on it), however the tail is shared ...
        assert _run(wave, cell[3]) == want, (p, r)
        # ... and it writes on EVERY call, so the tie's toneporta left in
        # the command column never runs (the premise of the pointer row)
        assert None not in S.instrument_calls(wave + [(0xFF, 0)], cell[3])


@needs_corpus
def test_the_tie_window_is_declined_at_s3_for_the_speed_table(monkeypatch):
    """-S3: store k's per-call step is `$100 * k / 3`, not a whole number of
    frequency units for k not a multiple of 3 (`skydive_speed` None), so the
    full-rate tie program cannot be written; only the compact program (one
    -S1 step a frame) exists there, and the tie window does not use it. The
    decline is counted and the rows after the ties are left alone. Opened as
    a follow-up: a compact tie program."""
    plan, lines, _t, _w = _plan(monkeypatch, 3)
    log = [m for m in lines if m.startswith("Skydive (bit $02)")][0]
    assert "after a tie: 0 row(s)" in log and "declined: 1 speed table" in log
    for p, r in TIE_NEXT_ROWS:
        assert plan.patterns[p][4 * r + 2] != CMD_SETWAVEPTR, (p, r)


@needs_corpus
def test_a_window_two_frames_before_the_pointer_row_is_declined(monkeypatch):
    """Phase 1 with no start lag puts store 0 at -2: nothing is emitted for
    the ties (and the plan says why), where phase 1 with the lag of one is
    store 0 a frame before the pointer row and is emitted."""
    plan, lines, _t, _w = _plan(monkeypatch, 2, flip_parity=True,
                                no_test_restart=True)
    log = [m for m in lines if m.startswith("Skydive (bit $02)")][0]
    for p, r in TIE_NEXT_ROWS:
        assert plan.patterns[p][4 * r + 2] != CMD_SETWAVEPTR, (p, r)
    assert "after a tie: 0 row(s)" in log, log
    assert "declined: 2 stores before the next row" in log, log


def test_the_window_start_is_phase_plus_lag_minus_the_row():
    assert S.tie_window_phase(1, 0, 3) == -2          # declined
    assert S.tie_window_phase(1, 1, 3) == -1          # emitted, a frame early
    assert S.tie_window_phase(2, 0, 3) == -1
    assert S.tie_window_phase(2, 1, 3) == 0
    # a longer row (more frames) than Zoids' is declined at either phase
    assert S.tie_window_phase(2, 1, 4) == -1
    assert S.tie_window_phase(1, 0, 4) == -3
