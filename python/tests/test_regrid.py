"""Re-gridding: the fractional part of a row the tempo cannot express."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import CMD_SETTEMPO
from h2g.patterns import GT_END_PATTERN, regrid_tempos


def _pattern(rows, cmd_at=()):
    out = []
    for r in range(rows):
        out += [0x30, 1, (CMD_SETTEMPO if r in cmd_at else 0), 0]
    return out + [GT_END_PATTERN, 0, 0, 0]


def _one_subtune(pat_rows=12, cmd_at=()):
    return [_pattern(pat_rows, cmd_at)], [[0], [], []]


def test_a_compensated_row_is_lengthened_and_the_next_row_restores_it():
    pats, tracks = _one_subtune()
    assert regrid_tempos(pats, tracks, [3], [0.25], 1) >= 1
    rows = [pats[0][r * 4 + 2:r * 4 + 4] for r in range(len(pats[0]) // 4)]
    ups = [r for r, c in enumerate(rows) if c == [CMD_SETTEMPO, 4]]
    assert ups, rows
    for r in ups:
        assert rows[r + 1] == [CMD_SETTEMPO, 3], f"row {r+1} must restore"


def test_row_zero_is_never_taken_because_it_is_the_subtunes_clock():
    pats, tracks = _one_subtune(pat_rows=40)
    regrid_tempos(pats, tracks, [3], [0.5], 1)
    assert pats[0][2] == 0, "row 0 belongs to CMD_SETTEMPO/apply_tempos"


def test_the_restore_never_falls_outside_the_pattern():
    """The row after the last is whatever the orderlist plays next, which is
    position-dependent -- the thing this design exists to avoid."""
    pats, tracks = _one_subtune(pat_rows=8)
    regrid_tempos(pats, tracks, [3], [0.9], 1)
    n = len(pats[0]) // 4
    for r in range(n):
        if pats[0][r * 4 + 2] == CMD_SETTEMPO and pats[0][r * 4 + 3] == 4:
            assert r + 1 < n - 1, "a lengthened row needs a restore row after it"


def test_an_occupied_command_column_is_left_alone():
    pats, tracks = _one_subtune(pat_rows=12, cmd_at=range(1, 12))
    regrid_tempos(pats, tracks, [3], [0.9], 1)
    for r in range(1, 12):
        assert pats[0][r * 4 + 3] == 0, "an existing command was overwritten"


def test_a_pattern_two_subtunes_with_different_clocks_reach_is_refused():
    """CMD_SETTEMPO under $80 sets all three channels, so the restore would
    name the wrong subtune's tempo -- the v0.5.330 defect."""
    pats = [_pattern(20)]
    tracks = [[0], [], [], [0], [], []]          # both subtunes play pattern 0
    assert regrid_tempos(pats, tracks, [3, 4], [0.5, 0.5], 1) == 0
    assert all(pats[0][r * 4 + 2] == 0 for r in range(len(pats[0]) // 4))


def test_only_one_voice_is_scheduled_per_subtune():
    """A tempo command sets all three channels, so placing one in each of the
    three voices' patterns lengthens the same row three times -- measured on
    Monty as a 15-frame deficit becoming a 21-frame surplus."""
    pats = [_pattern(20), _pattern(20), _pattern(20)]
    tracks = [[0], [1], [2]]
    regrid_tempos(pats, tracks, [3], [0.5], 1)
    touched = [i for i, pat in enumerate(pats)
               if any(pat[r * 4 + 2] for r in range(len(pat) // 4))]
    assert touched == [0], f"scheduled in patterns {touched}, want voice 0 only"


def test_a_zero_deficit_writes_nothing():
    pats, tracks = _one_subtune(pat_rows=40)
    assert regrid_tempos(pats, tracks, [3], [0.0], 1) == 0


def test_the_deficit_is_frames_and_the_command_counts_calls():
    """A multispeed song needs `frames * multiplier` calls of compensation."""
    a, ta = _one_subtune(pat_rows=30)
    b, tb = _one_subtune(pat_rows=30)
    n1 = regrid_tempos(a, ta, [3], [0.02], 1)
    n2 = regrid_tempos(b, tb, [3], [0.02], 3)
    assert n2 >= n1, f"multiplier 3 wants at least as many calls ({n1} -> {n2})"


def test_convert_leaves_the_byte_exact_fixture_alone_by_default():
    from h2g.convert import convert
    root = pathlib.Path(__file__).resolve().parents[2]
    assert convert(str(root / "Commando.sid")) == (root / "Commando.sng").read_bytes()
