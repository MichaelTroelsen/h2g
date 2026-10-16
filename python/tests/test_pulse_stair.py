"""A slow triangle step is laid as a HELD stair, not a slew
(`last-v8-instr1-stair-as-ramp`).

Last_V8's record 1 is rate $79: step 96 every 26 ticks, 52 calls at -S2. The
slew moved the width 2 a call (4914 voice-1 pulse changes against 189); the
player holds each width for the whole delay. `_stair_legs` lays a set row and
a speed-0 hold row per lattice width.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import pulse as P                         # noqa: E402


def _widths(entries, loop, calls):
    """Width after each call of a Goattracker pulse program (gplay.c:872-902):
    a set row spends its call; a modulation row (t, spd) adds spd for t calls;
    (FF, n) jumps to 1-based entry n."""
    out, ptr, width, left = [], 0, 0, 0
    start = 1
    block = list(entries) + [(0xFF, start + loop)]
    while len(out) < calls:
        a, b = block[ptr]
        if a == 0xFF:
            ptr = b - start
            continue
        if a >= 0x80:
            width = ((a & 0x0F) << 8) | b
            ptr += 1
            out.append(width)
            continue
        spd = b - 256 if b >= 128 else b
        for _ in range(a):
            width = (width + spd) & 0xFFF
            out.append(width)
        ptr += 1
    return out[:calls]


def test_stair_holds_each_width_for_the_delay():
    # Last_V8 record 1: width $9A0, step 96, 52 calls, bounds nibbles 8..14.
    from h2g.goatwriter.pulse import _stair_legs, _tri_turns
    turns = _tri_turns(0x9A0, 96, 8, 14)
    entries, loop = _stair_legs(0x9A0, 96, 52, *turns)
    w = _widths(entries, loop, 52 * 80)
    runs = []
    for x in w:
        if runs and runs[-1][0] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    assert all(n == 52 for _, n in runs)
    assert all(abs(a[0] - b[0]) % 4096 in (96, 4096 - 96)
               for a, b in zip(runs, runs[1:]))
    # the band stays inside the player's lattice turns
    assert min(r[0] for r in runs) >= 0x800 and max(r[0] for r in runs) <= 0xEFF


@needs_corpus
def test_last_v8_record_1_is_a_stair_and_fits():
    from h2g import detect
    from h2g.sidfile import load_sid
    sid = load_sid(CORPUS / "Last_V8.sid")
    det = detect.detect(sid, lambda *a, **k: None)
    slew = P._pulse_tri_program(sid, det, 1, 2)
    stair = P._pulse_tri_program(sid, det, 1, 2, stair=True)
    assert len(slew[0]) == 18 and len(stair[0]) > 18
    assert any(r == (51, 0) for r in stair[0])
    entries, starts = P._pulse_layout(sid, det, det.instr_used, True, 2, lead=1)
    assert len(entries) <= 255
    start = starts[1 + 1]
    assert entries[start - 1:start - 1 + 3] == stair[0][:3]


@needs_corpus
def test_stair_is_dropped_when_the_table_would_overflow(monkeypatch):
    from h2g import detect
    from h2g.sidfile import load_sid
    sid = load_sid(CORPUS / "Last_V8.sid")
    det = detect.detect(sid, lambda *a, **k: None)
    monkeypatch.setattr(P, "STAIR_MIN_FRAMES", 10 ** 6)
    base, _ = P._pulse_layout(sid, det, det.instr_used, True, 2, lead=1)
    monkeypatch.undo()
    monkeypatch.setattr(P._gw_constants, "GT_MAX_TABLELEN", len(base) + 5)
    entries, _ = P._pulse_layout(sid, det, det.instr_used, True, 2, lead=1)
    assert not any(r == (51, 0) for r in entries)


def test_below_the_threshold_nothing_changes(monkeypatch):
    monkeypatch.setattr(P, "STAIR_MIN_FRAMES", 10 ** 6)
    from h2g import detect
    from h2g.sidfile import load_sid
    if not (CORPUS / "Last_V8.sid").exists():
        pytest.skip("corpus missing")
    sid = load_sid(CORPUS / "Last_V8.sid")
    det = detect.detect(sid, lambda *a, **k: None)
    assert (P._pulse_tri_program(sid, det, 1, 2, stair=True)
            == P._pulse_tri_program(sid, det, 1, 2))
