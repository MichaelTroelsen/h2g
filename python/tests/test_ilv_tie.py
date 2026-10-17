"""ILV duration-byte bit 5 (ILV_TIE) -> CMD_TONEPORTA 0 on the NEXT note.

Measured at -t 60 under presets.json: Go_Go_Dash melody .950 -> .999,
Radio_ACE .945 -> .974, Sun_Never_Shines .884 -> .911, Lakers .887 -> .919,
Lion_Heart .900 -> .930, Pacific_Coast .976 -> .983. The corpus byte-hash
moves exactly those six files.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import patterns as P  # noqa: E402

TIE = P.ILV_TIE


def _rows(*b, **kw):
    kw.setdefault("tie", True)
    ev = P._build_raw_pattern_ilv(bytes([0, 0, 0x80, 0x05, *b, P.ILV_END]), 2,
                                  **kw)
    return [ev[i:i + 4] for i in range(0, len(ev), 4)]


def test_flag_governs_the_next_note_not_its_own():
    rows = _rows(0xC0 | TIE | 1, 0x30, 0xC0 | 1, 0x31, 0xC0 | 1, 0x32)
    notes = [r for r in rows if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    assert [r[2:] for r in notes] == [[0, 0], [P.CMD_TONEPORTA, 0], [0, 0]]


def test_tie_is_one_shot_on_hold_rows():
    rows = _rows(0xC0 | TIE | 2, 0x30, 0xC0 | 2, 0x31)
    assert rows[3][2:] == [P.CMD_TONEPORTA, 0]
    assert [r[2:] for r in rows[4:6]] == [[0, 0]] * 2


def test_slide_wins_the_command_column():
    rows = _rows(0xC0 | TIE | 0, 0x30, 0x82, 0x00, 0x01, 0x31, slides=True,
                 steps=[])
    assert rows[1][2] in (1, 2)


def test_rest_consumes_the_flag_and_row0_is_never_tied():
    rows = _rows(0xC0 | TIE, 0x30, P.ILV_REST, 0x31)
    assert rows[0][2:] == [0, 0]
    assert rows[2][2:] == [0, 0]


def test_no_flag_no_command():
    rows = _rows(0xC0 | 1, 0x30, 0x31)
    assert all(r[2] != P.CMD_TONEPORTA for r in rows)


def test_an_armed_arpeggio_keeps_the_column_over_the_tie():
    arps: list = []
    rows = _rows(0xC0 | TIE, 0x30, 0x83, 0x50, 0x31, arps=arps)
    assert rows[1][2:] == [P.CMD_SETWAVEPTR, 1]


def test_tie_is_opt_in():
    rows = _rows(0xC0 | TIE, 0x30, 0x31, tie=False)
    assert all(r[2] != P.CMD_TONEPORTA for r in rows)
