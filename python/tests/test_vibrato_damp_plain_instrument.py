"""`_vibrato_command_pass` damps a short note only where a vibrato could
otherwise run on it.

The damp (`$04 00`) exists to cancel the instrument's own vibrato pointer on a
note shorter than the player's gate. An instrument with no `vib_ptrs` entry
has no pointer to cancel: the player's `!cmddata` break already gives its
notes nothing, so the damp only occupied the command column. Found by
vibrato-unnamed-count-mislabel (C64ME instrument 04, Rasputin's plain
instruments); the unnamed case (`live == 0`) still damps, because the
instrument may carry a pointer this pass cannot see.
"""
from h2g.detect import Detection
from h2g.goatwriter import _vibrato_command_pass


def _pattern(*rows):
    out = []
    for r in rows:
        out += list(r)
    return out


def _note(instr=0, cmd=0, data=0, note=0x70):
    return (note, instr, cmd, data)


def _hold(cmd=0, data=0):
    return (0xBD, 0x00, cmd, data)


def _col(pat, k):
    return [pat[i + k] for i in range(0, len(pat), 4)]


DET = Detection(triangle_vibrato=5, triangle_gate=4)
VIB = {0: (7, 8)}          # record 0 -> slot 2 at lead=1


def test_short_note_on_a_vibrato_instrument_is_still_damped():
    pat = _pattern(_note(instr=2), _hold())
    _vibrato_command_pass(DET, [pat], VIB, lead=1)
    assert _col(pat, 2) == [4, 4] and _col(pat, 3) == [0, 0]


def test_short_note_on_a_known_plain_instrument_is_left_free():
    pat = _pattern(_note(instr=4), _hold())
    lines: list = []
    _vibrato_command_pass(DET, [pat], VIB, lead=1, log=lines.append)
    assert _col(pat, 2) == [0, 0] and _col(pat, 3) == [0, 0]


def test_short_note_on_an_unnamed_instrument_is_still_damped():
    pat = _pattern(_note(), _hold())
    _vibrato_command_pass(DET, [pat], VIB, lead=1)
    assert _col(pat, 2) == [4, 4]


def test_a_plain_instrument_carried_across_the_orderlist_is_left_free():
    pats = [_pattern(_note(instr=4), _hold()),
            _pattern(_note(), _hold())]           # names none, entered on 4
    _vibrato_command_pass(DET, pats, VIB, lead=1, tracks=[[0, 1]])
    assert _col(pats[1], 2) == [0, 0]


def test_the_free_column_is_counted_in_the_log_not_as_damped():
    pats = [_pattern(_note(instr=2), _hold()),     # damped
            _pattern(_note(instr=4), _hold())]     # left free
    lines: list = []
    _vibrato_command_pass(DET, pats, VIB, lead=1, log=lines.append)
    assert lines == ["Vibrato command.........: 0 note(s) vibrated, "
                     "1 damped by length, 1 short on an instrument with no "
                     "vibrato left free"], lines


def test_a_free_short_note_keeps_a_row_command_someone_else_wrote():
    pat = _pattern(_note(instr=4, cmd=1, data=5), _hold(1, 5))
    _vibrato_command_pass(DET, [pat], VIB, lead=1)
    assert _col(pat, 2) == [1, 1] and _col(pat, 3) == [5, 5]
