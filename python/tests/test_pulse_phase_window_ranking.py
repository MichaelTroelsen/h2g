"""`apply_pulse_phase`'s ranking of pattern copies by WHEN their notes sound.

The pattern table holds `MAX_PATTERNS`; a forced `pulse_phase` plan on
Human_Race, Rasputin and Gremlins asks for more copies than fit. First-come
(plan order) gave the copies to the tracks handed over first and let the
later ones go whatever their notes were worth. With `row_seconds` the copies
go to the clones serving the most command rows that START inside the 180 s
window of their own subtune, then the most rows in all, then plan order.

Synthetic plans here; the corpus effect is measured in the task's record
(`docs/H2G-CONVERSION-METHOD.md`) and pinned on Human_Race below.
"""
from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import h2g.convert  # noqa: E402,F401
from h2g import patterns as P  # noqa: E402

END = [P.GT_END_PATTERN, 0, 0, 0]
NOTE = P.GT_FIRSTNOTE + 12
# One row lasts a minute: rows 0, 1, 2 of a track start inside 180 s, row 3
# (at 180 s) and everything after it does not.
MINUTE = 60.0
INDEX = {(1, 0x800, 1): 5, (1, 0x900, 1): 6}


def _pattern(salt: int, rows: int = 4, command_on: tuple = ()) -> list:
    out: list = []
    for r in range(rows):
        out += [NOTE + salt, 1, 0x0F if r in command_on else 0, 0x11 if r in command_on else 0]
    return out + END


def _table(extra: int, free: int) -> list:
    """`extra` distinct played patterns, padded so `free` slots remain."""
    pats = [_pattern(s) for s in range(extra)]
    while len(pats) < P.MAX_PATTERNS - free:
        pats.append(list(END))
    return pats


def _ph(width: int) -> tuple:
    return (1, (width, 1))


def _run(pats, tracks, writes, row_seconds):
    log: list = []
    n = P.apply_pulse_phase(pats, tracks, writes, INDEX, log.append,
                            row_seconds=row_seconds)
    return n, log


def _copy_of(pats, tracks, ti, pos):
    return pats[tracks[ti][pos]]


def test_a_plan_that_fits_is_written_exactly_as_in_plan_order():
    def build():
        pats = _table(3, 10)
        tracks = [[0, 1, 2, P.GT_ORDER_RESTART, 0]]
        writes = [(0, 2, {0: _ph(0x800)}), (0, 0, {0: _ph(0x900)})]
        return pats, tracks, writes
    a = build()
    b = build()
    na, _ = _run(*a, None)
    nb, _ = _run(*b, [MINUTE])
    assert na == nb == 2
    assert a[0] == b[0] and a[1] == b[1]


def test_the_late_clone_loses_its_copy_to_an_in_window_one():
    pats = _table(2, 1)
    tracks = [[0, 1, P.GT_ORDER_RESTART, 0]]
    # pattern 1 starts at row 4 = 240 s: outside the window. It is FIRST in
    # plan order, so first-come would give it the only copy.
    writes = [(0, 1, {0: _ph(0x800)}), (0, 0, {0: _ph(0x900)})]
    first_come = ([list(p) for p in pats], [list(t) for t in tracks])
    n0, _ = _run(first_come[0], first_come[1], list(writes), None)
    assert n0 == 1 and first_come[1][0][1] >= P.MAX_PATTERNS - 1 \
        and first_come[1][0][0] == 0
    n, log = _run(pats, tracks, writes, [MINUTE])
    assert n == 1
    assert tracks[0][0] >= P.MAX_PATTERNS - 1, "the early note keeps its copy"
    assert tracks[0][1] == 1, "the late note stays on its original"
    assert _copy_of(pats, tracks, 0, 0)[2] == P.CMD_SETPULSEPTR
    assert any("clone was dropped" in m for m in log)


def test_slots_sharing_a_clone_add_their_rows():
    # Pattern 0 is played at two in-window positions with the same vector
    # (one clone, two rows served); pattern 1 serves one. One copy free.
    pats = _table(2, 1)
    tracks = [[1, 0, 0, P.GT_ORDER_RESTART, 0]]
    pats[0] = _pattern(0)
    # positions 1 and 2 start at rows 4 and 8: both outside 180 s at a
    # minute a row, so use a faster clock where 4 rows = 20 s.
    writes = [(0, 0, {0: _ph(0x800)}),
              (0, 1, {0: _ph(0x900)}), (0, 2, {0: _ph(0x900)})]
    n, _ = _run(pats, tracks, writes, [5.0])
    assert n == 1
    assert tracks[0][1] == tracks[0][2] >= P.MAX_PATTERNS - 1
    assert tracks[0][0] == 1, "the one-row clone, first in plan, loses"


def test_a_taken_command_column_serves_nothing():
    pats = _table(2, 1)
    pats[0] = _pattern(0, command_on=(0,))    # row 0's column is taken
    tracks = [[0, 1, P.GT_ORDER_RESTART, 0]]
    writes = [(0, 0, {0: _ph(0x800)}), (0, 1, {0: _ph(0x900)})]
    n, _ = _run(pats, tracks, writes, [5.0])
    assert n == 1
    assert tracks[0][0] == 0, "no copy is spent on a row that cannot take it"
    assert tracks[0][1] >= P.MAX_PATTERNS - 1


def test_ties_keep_the_plans_order():
    pats = _table(2, 1)
    tracks = [[0, 1, P.GT_ORDER_RESTART, 0]]
    writes = [(0, 1, {0: _ph(0x800)}), (0, 0, {0: _ph(0x900)})]
    n, _ = _run(pats, tracks, writes, [5.0])    # both inside the window
    assert n == 1
    assert tracks[0][1] >= P.MAX_PATTERNS - 1 and tracks[0][0] == 0


def test_each_group_has_its_own_clock():
    # Two subtunes (tracks 0-2 and 3-5); the second plays slowly, so its
    # note at row 1 is already past the window while the first's is not.
    pats = _table(2, 1)
    tracks = [[0, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2 \
        + [[1, P.GT_ORDER_RESTART, 0]] + [[2, P.GT_ORDER_RESTART, 0]] * 2
    writes = [(3, 0, {2: _ph(0x800)}), (0, 0, {1: _ph(0x900)})]
    n, _ = _run(pats, tracks, writes, [1.0, 100.0])
    assert n == 1
    assert tracks[0][0] >= P.MAX_PATTERNS - 1, "group 0 (fast) wins"
    assert tracks[3][0] == 1


def test_human_races_window_reach_total_rises_and_subtune_zero_holds():
    """The corpus pin: under forced `pulse_phase` the packed file's phases
    reached in the first 180 s. First-come reached 899 in all (subtunes 3
    and 4 starved: 0/138 and 0/386); ranking by in-window rows reaches 1171.
    Named trade: subtune 2 voice 1 goes 108 -> 69 and subtune 4 voice 1
    stays at 0 of 264 (the pulse table, not the pattern table, is what
    holds it)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import test_triangle_lockstep as T
    got = T._reach("Human_Race.sid", 180)
    first_come = {(0, 0): 455, (0, 1): 120, (1, 1): 216, (2, 1): 108,
                  (3, 0): 0, (4, 0): 0, (4, 1): 0}
    reached = {k: v[0] for k, v in got.items()}
    for k in ((0, 0), (0, 1), (1, 1)):
        assert reached[k] >= first_come[k], (k, reached)
    assert reached[(3, 0)] == 138 and reached[(4, 0)] > 0, reached
    assert sum(reached.values()) >= sum(first_come.values()), reached
    # 1171 until phase-seed-minority-lattice (records 18 and 23 chain, the
    # table keeps 23 in 21's place): subtune 4 voice 0 173 -> 210, subtune 2
    # voice 1 69 -> 63.
    # 1202 until lay-pulse-phase-table-adopts-union-groups (both unions
    # adopted, 242 rows): subtune 4 voice 0 210 -> 383, subtune 2 voice 1
    # 63 -> 39.
    assert sum(reached.values()) == 1351, reached


# --- following the tempo changes the tempo pass wrote ----------------------
# calls_per_frame=0.02 makes a SETTEMPO of 0x7F last 127 s a row.
SLOW = 0x7F
CPF = 0.02


def _tempo_at(pats, k, value, row=0):
    pats[k][4 * row + 2], pats[k][4 * row + 3] = P.CMD_SETTEMPO, value


def _run_cpf(pats, tracks, writes, row_seconds, cpf):
    log: list = []
    n = P.apply_pulse_phase(pats, tracks, writes, INDEX, log.append,
                            row_seconds=row_seconds, calls_per_frame=cpf)
    return n, log


def test_settempo_calls_matches_gplay():
    # gplay.c:494-505: >= 3 is decremented into the tempo, a tempo of n >= 2
    # lasts n + 1 calls; under 2 is the funktempo table, under no one number.
    assert [P._settempo_calls(v) for v in (0, 1, 2, 3, 4, 0x7F, 0x80)] == \
        [None, None, 3, 3, 4, 0x7F, None]


def test_a_slow_opening_tempo_pushes_the_later_clone_out_of_the_window():
    def build():
        pats = _table(2, 1)
        _tempo_at(pats, 0, SLOW)
        return pats, [[0, 1, P.GT_ORDER_RESTART, 0]], \
            [(0, 1, {0: _ph(0x800)}), (0, 0, {1: _ph(0x900)})]
    a = build()
    na, _ = _run_cpf(*a, [1.0], None)           # the constant estimate
    assert na == 1 and a[1][0][1] >= P.MAX_PATTERNS - 1, \
        "constant 1 s a row: both inside, plan order, the later position wins"
    b = build()
    nb, _ = _run_cpf(*b, [1.0], CPF)            # row 4 is at 508 s
    assert nb == 1
    assert b[1][0][0] >= P.MAX_PATTERNS - 1 and b[1][0][1] == 1


def test_a_tempo_in_another_voice_of_the_group_is_followed():
    pats = _table(3, 1)
    _tempo_at(pats, 2, SLOW)
    tracks = [[0, 1, P.GT_ORDER_RESTART, 0], [2, P.GT_ORDER_RESTART, 0],
              [2, P.GT_ORDER_RESTART, 0]]
    writes = [(0, 1, {0: _ph(0x800)}), (0, 0, {1: _ph(0x900)})]
    n, _ = _run_cpf(pats, tracks, writes, [1.0], CPF)
    assert n == 1
    assert tracks[0][0] >= P.MAX_PATTERNS - 1 and tracks[0][1] == 1


def test_a_change_only_moves_the_rows_after_it():
    # Pattern 1 (row 4 on) slows the tune; position 2 (row 8) is late, but
    # position 1's row 0 (row 4 itself, at 4 s) and pattern 0's rows are not.
    pats = _table(3, 1)
    _tempo_at(pats, 1, SLOW)
    tracks = [[0, 1, 2, P.GT_ORDER_RESTART, 0]]
    writes = [(0, 2, {0: _ph(0x800)}), (0, 1, {1: _ph(0x900)})]
    n, _ = _run_cpf(pats, tracks, writes, [1.0], CPF)
    assert n == 1
    assert tracks[0][1] >= P.MAX_PATTERNS - 1 and tracks[0][2] == 2


def test_a_funktempo_value_leaves_the_constant_clock():
    def build():
        pats = _table(2, 1)
        _tempo_at(pats, 0, 1)                   # < 2: funk table, ignored
        return pats, [[0, 1, P.GT_ORDER_RESTART, 0]], \
            [(0, 1, {0: _ph(0x800)}), (0, 0, {1: _ph(0x900)})]
    a, b = build(), build()
    _run_cpf(*a, [1.0], None)
    _run_cpf(*b, [1.0], CPF)
    assert a[0] == b[0] and a[1] == b[1]


from corpus import folds_unread  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _folds_as_measured(folds_unread):
    """The layouts here were measured before the folded accumulate spelling
    was read; see `corpus.folds_unread`."""
