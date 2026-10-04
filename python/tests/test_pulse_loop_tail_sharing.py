"""`_lay_out_pulse` shares a loop body, not only a whole (program, loop) block.

A pulse program is a prefix followed by a loop body whose closing entry is
`(0xFF, <absolute 1-based index of the body's first entry>)`. Two programs with
different prefixes and the same loop body used to cost two full blocks;
Knucklebusters' GT26 (prefix 3, body 4, same body as GT14) lost its sweep to
that (tests/test_pulse_layout_knucklebusters.py is the corpus pin). With
`share`, a block whose body is already in the table now writes its own prefix
and one jump into that body. These tests are synthetic and walk the finished
table the way the player does, so they pin the behaviour rather than a byte
layout.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g import goatwriter as gw                     # noqa: E402
from h2g.goatwriter import constants as C            # noqa: E402

lay = gw.pulse._lay_out_pulse

BODY = [(0x10 + k, 0x20 + k) for k in range(4)]
A = ([(0x81, 0x40), (0x7F, 0x0B)] + BODY, 2)
B = ([(0x82, 0x41)] + BODY, 1)


def _statics(programs):
    return [[p[0][0], (0xFF, 0)] for p in programs]


def _walk(entries, ptr, n):
    """The first `n` non-jump entries the player reads from 1-based `ptr`."""
    out, seen = [], 0
    while len(out) < n:
        seen += 1
        assert seen < 10_000, "jump loop with no entry in it"
        e = entries[ptr - 1]
        if e[0] == 0xFF:
            ptr = e[1]
            continue
        out.append(e)
        ptr += 1
    return out


def _expected(program, loop, n):
    out = list(program[:loop])
    while len(out) < n:
        out += program[loop:]
    return out[:n]


def test_body_already_placed_is_jumped_into_after_the_blocks_own_prefix():
    programs = [A, B]
    entries, starts, dropped, silent, shared = lay(
        programs, _statics(programs), 0, True)
    a_start, b_start = starts
    body_at = a_start + A[1]
    # A is written whole, B is its one-entry prefix and a jump into A's body.
    assert entries[b_start - 1] == B[0][0], "the prefix comes first"
    assert entries[b_start] == (0xFF, body_at)
    assert len(entries) == 2 + len(A[0]) + 1 + len(B[0][:B[1]]) + 1
    assert (dropped, silent, shared) == (0, 0, 1)
    for (prog, loop), start in zip(programs, starts):
        assert _walk(entries, start, 20) == _expected(prog, loop, 20)


def test_without_share_every_block_is_written_whole():
    programs = [A, B]
    entries, starts, dropped, silent, shared = lay(
        programs, _statics(programs), 0, False)
    assert len(entries) == 2 + (len(A[0]) + 1) + (len(B[0]) + 1)
    assert shared == 0
    assert entries[starts[1] - 1 + len(B[0])] == (0xFF, starts[1] + B[1])


def test_a_program_that_is_only_a_body_points_into_it_and_adds_nothing():
    only_body = (list(BODY), 0)
    programs = [A, only_body]
    entries, starts, dropped, silent, shared = lay(
        programs, _statics(programs), 0, True)
    assert starts[1] == starts[0] + A[1], "points at the placed body itself"
    assert len(entries) == 2 + len(A[0]) + 1
    assert shared == 1
    assert _walk(entries, starts[1], 12) == _expected(BODY, 0, 12)


def test_tail_sharing_rescues_a_sweep_the_full_block_could_not_afford():
    body = [(0x30 + k, 0x50 + k) for k in range(12)]
    a = ([(0x81, 0x40)] + body, 1)
    b = ([(0x82, 0x41)] + body, 1)
    filler = ([(0x90, k & 0x7F) for k in range(230)], None)
    programs = [a, filler, b]
    entries, starts, dropped, silent, shared = lay(
        programs, _statics(programs), 0, True)
    assert len(entries) <= C.GT_MAX_TABLELEN
    assert (dropped, silent) == (0, 0), "B kept its sweep"
    assert _walk(entries, starts[2], 30) == _expected(b[0], b[1], 30)
    # Written whole, B's block would have run past the end of the table.
    before_b = starts[2] - 1
    assert before_b + len(b[0]) + 1 > C.GT_MAX_TABLELEN


def test_a_static_fallback_body_is_never_a_jump_target():
    # A block that fell back to its static pair registers no loop body, so a
    # later program with that body must not jump into the static entries.
    big = ([(0x91, k & 0x7F) for k in range(300)] + BODY, 300)
    programs = [big, B]
    entries, starts, dropped, silent, shared = lay(
        programs, _statics(programs), 0, True)
    assert dropped >= 1
    assert _walk(entries, starts[1], 20) == _expected(B[0], B[1], 20)
