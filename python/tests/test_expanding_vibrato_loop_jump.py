"""A swell loop behind a remainder ends in a jump onto the speed's loop.

Opened by mega-wavetable-room: `rest / F4 idx / FF -> F4` repeated the F4/FF
pair for every remainder, so Mega_Apocalypse's 56 loops wanted 126 wavetable
entries for 101 and 13 of them merged onto a neighbour's speed. The pair is
the same whatever the remainder, and gplay.c:709-712 follows a jump the moment
the pointer steps onto it, so the block can be `rest / FF -> the F4 entry`:
the call after the remainder's last step runs the speed's F4, as the loop's
own `FF` would. These tests walk the table the way gplay.c's wavetable does.
"""
import hashlib
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import note_passes as NP  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR, CMD_VIBRATO,  # noqa: E402
                                      GT_MAX_TABLELEN)
from h2g.goatwriter.note_passes import (  # noqa: E402
    _expanding_vibrato_loop_cost, _expanding_vibrato_loops)

F4 = 0xF4
JUMP = 0xFF
END = 0xFF
ENTRY = (0, 64)                 # an absolute speed: (cmp, speed)
OTHER = (0, 76)


# --- the cost model ----------------------------------------------------------

def test_a_bare_loop_costs_its_pair():
    assert _expanding_vibrato_loop_cost([((), ENTRY)]) == 2
    assert _expanding_vibrato_loop_cost([((), ENTRY), ((), OTHER)]) == 4


def test_a_remainder_costs_itself_and_a_jump_and_the_first_carries_the_pair():
    rest = ((0x41, 0), (0x40, 0))
    # [rest, F4, FF] and a bare loop that points at its F4: 4 entries
    assert _expanding_vibrato_loop_cost([(rest, ENTRY), ((), ENTRY)]) == 4
    # a second remainder is the remainder and one jump
    other = ((0x41, 0),)
    assert _expanding_vibrato_loop_cost(
        [(rest, ENTRY), (other, ENTRY)]) == 4 + 2
    # another speed has a pair of its own
    assert _expanding_vibrato_loop_cost(
        [(rest, ENTRY), (rest, OTHER)]) == 4 + 4


# --- the emission, walked as gplay.c walks it ---------------------------------

def _run(table, start, calls):
    """Entries executed on `calls` calls from pointer `start` (1-based);
    gplay.c:699-712: a delay holds `value` more calls, the pointer steps,
    and a jump under it is taken at once."""
    ptr, wavetime, seen = start, 0, []
    for _ in range(calls):
        left, right = table[ptr - 1]
        assert left != JUMP, f"pointer {ptr} stands on a jump"
        if left <= 0x0F and wavetime != left:
            wavetime += 1
            seen.append(None)
            continue
        wavetime = 0
        seen.append((left, right))
        ptr += 1
        if table[ptr - 1][0] == JUMP:
            ptr = table[ptr - 1][1]
    return seen


PROG_A = [(0x41, 0), (0x41, 0), (0x41, 0), (0x40, 0), (JUMP, 0)]
PROG_B = [(0x41, 0), (0x41, 0), (0x41, 0), (0x41, 0), (0x40, 0), (JUMP, 0)]
ROW_CALLS = 3


def _loops(monkeypatch, rows, table=None, pad=0):
    """Run `_expanding_vibrato_loops` on a pattern of `rows` (each
    `(slot, k, entry)`: instrument `slot`'s k-th row wants `entry`). Returns
    (pattern, wavetable, converted, speed table, log)."""
    wave = list(table if table is not None else PROG_A + PROG_B)
    wave += [(0x11, 0)] * pad
    starts = [1, len(PROG_A) + 1]
    pat = []
    wants, where = {}, {}
    for i, (slot, k, entry) in enumerate(rows):
        pat += [0x40, slot, CMD_VIBRATO, 0x23]
        wants[(0, 4 * i)] = {entry}
        where[(0, 4 * i)] = [(slot, k)]
    pat += [END, 0, 0, 0]
    by_slot = {1: object(), 2: object()}
    monkeypatch.setattr(NP, "_expanding_vibrato_setup",
                        lambda *a, **k: (by_slot, {}, lambda b, a: None, True))
    monkeypatch.setattr(NP, "_expanding_vibrato_wants",
                        lambda *a, **k: (wants, where, 0))
    monkeypatch.setattr(NP, "_counter_gate_call", lambda *a, **k: None)
    speed_table: list = []
    lines: list = []
    out, n = _expanding_vibrato_loops(
        None, None, [[0, END, 0]], [pat], {0: (1, 2)}, speed_table, 0, 1,
        ROW_CALLS, wave, starts, log=lines.append)
    return pat, out, n, speed_table, lines


def _pointer(pat, i):
    assert pat[4 * i + 2] == CMD_SETWAVEPTR, pat[4 * i:4 * i + 4]
    return pat[4 * i + 3]


def test_remainder_blocks_run_what_a_loop_of_their_own_ran(monkeypatch):
    # slot 1 at row 1 (call 3): steps 3-4 of PROG_A remain; slot 2 at row 1:
    # steps 3-5 of PROG_B; slot 1 at row 5 (call 15): nothing remains.
    rows = [(1, 1, ENTRY), (2, 1, ENTRY), (1, 5, ENTRY)]
    pat, out, n, st, _lines = _loops(monkeypatch, rows)
    assert n == 3
    f4 = (F4, st.index(ENTRY) + 1)
    first = _run(out, _pointer(pat, 0), 12)
    second = _run(out, _pointer(pat, 1), 12)
    bare = _run(out, _pointer(pat, 2), 12)
    assert first[:2] == [(0x41, 0), (0x40, 0)] and set(first[2:]) == {f4}
    assert second[:3] == [(0x41, 0), (0x41, 0), (0x40, 0)]
    assert set(second[3:]) == {f4}
    assert set(bare) == {f4}
    assert len(st) == 1


def test_one_pair_per_speed_and_the_remainders_jump_onto_it(monkeypatch):
    rows = [(1, 1, ENTRY), (2, 1, ENTRY), (1, 5, ENTRY)]
    _pat, out, _n, _st, lines = _loops(monkeypatch, rows)
    added = out[len(PROG_A) + len(PROG_B):]
    # [rest(2), F4, FF->F4] then [rest(3), FF->that F4]: 4 + 4 entries, the
    # bare row pointing at the F4, against 4 + 5 + 2 with a pair apiece.
    assert len(added) == 8
    assert sum(1 for left, _ in added if left == F4) == 1
    assert added[-1] == (JUMP, len(PROG_A) + len(PROG_B) + 3)
    assert "3 row(s) on 3 wavetable loop(s)" in lines[0], lines


def test_a_bare_row_ahead_of_a_remainder_still_shares_the_remainders_pair(
        monkeypatch):
    rows = [(1, 5, ENTRY), (1, 1, ENTRY)]
    pat, out, n, st, _lines = _loops(monkeypatch, rows)
    assert n == 2
    assert len(out) - len(PROG_A) - len(PROG_B) == 4      # not 2 + 4
    f4 = (F4, st.index(ENTRY) + 1)
    assert set(_run(out, _pointer(pat, 0), 8)) == {f4}
    seq = _run(out, _pointer(pat, 1), 8)
    assert seq[:2] == [(0x41, 0), (0x40, 0)] and set(seq[2:]) == {f4}


def test_speeds_do_not_share_a_loop(monkeypatch):
    rows = [(1, 1, ENTRY), (2, 1, OTHER)]
    pat, out, _n, st, _lines = _loops(monkeypatch, rows)
    a = _run(out, _pointer(pat, 0), 8)
    b = _run(out, _pointer(pat, 1), 8)
    assert {x for x in a[2:]} == {(F4, st.index(ENTRY) + 1)}
    assert {x for x in b[3:]} == {(F4, st.index(OTHER) + 1)}


def test_a_block_that_does_not_fit_leaves_its_row_alone(monkeypatch):
    # 255 - 11 - 244 = 0 left: neither the pair nor a jump fits.
    pad = GT_MAX_TABLELEN - len(PROG_A) - len(PROG_B)
    pat, out, n, _st, lines = _loops(monkeypatch, [(1, 5, ENTRY)], pad=pad)
    assert n == 0 and len(out) == GT_MAX_TABLELEN
    assert pat[2] == CMD_VIBRATO
    assert "1 with a table full" in lines[0], lines


# --- Mega_Apocalypse, end to end ---------------------------------------------

@needs_corpus
def test_mega_apocalypse_merges_fewer_loops_and_keeps_every_row():
    import fidelity
    from h2g.convert import convert
    path = CORPUS / "Mega_Apocalypse.sid"
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    lines: list = []
    convert(path, lines.append, **fidelity._preset_opts(
        doc, "Mega_Apocalypse.sid"))
    swell = [m for m in lines if m.startswith("Expanding vibrato loops")]
    assert len(swell) == 1, swell
    assert "table full" not in swell[0], swell
    # 13 swings merged (17 rows, mean 2% off in size) before the jump; 4 with
    # it alone. Merged in cycle 29 beside mega-gt10-second-lap-hold, whose
    # later laps add 117 rows (1279 -> 1396) and alone merged 18 swings:
    # the two together merge 11 and still lose no row to a full table.
    assert "(11 swing(s) merged" in swell[0], swell
    assert swell[0].split(":")[1].split(" row(s)")[0].strip() == "1321", swell
