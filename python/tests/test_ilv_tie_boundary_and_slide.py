"""ILV ties the shared command column used to lose.

Two spellings of one fact -- the duration byte's bit 5 (`ILV_TIE`) skips the
player's note-start block for the NEXT note -- that the decoder missed:

* a tied note carrying a `$82` slide: the slide took the note row, a
  `CMD_PORTAUP/DOWN` row re-strikes, and Pacific_Coast's 192-frame note at
  f4418 became 72 + 84 (`hold` .909 -> 1.000);
* a tied note at row 0 of a pattern whose predecessor left the flag set: the
  decoder never reported `exits_tied` for this grammar, so
  `_apply_boundary_ties` never ran (Sun_Never_Shines `hold` .667 -> .889).

`TIE_UNDER_SLIDE` short-circuits the first; the second is short-circuited by
the decoder not reporting the exit.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import patterns as P  # noqa: E402

TIE = P.ILV_TIE
SID_DIR = pathlib.Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")


def _decode(*b, **kw):
    kw.setdefault("tie", True)
    ev = P._build_raw_pattern_ilv(bytes([0, 0, 0x80, 0x05, *b, P.ILV_END]), 2,
                                  **kw)
    return [ev[i:i + 4] for i in range(0, len(ev), 4)]


def _tied_slide_rows():
    # note 0x30 (flag) | slide | note 0x31 held 3 rows (the tied one)
    return _decode(0xC0 | TIE, 0x30, 0x82, 0xFF, 0xF6, 0xC0 | 2, 0x31,
                   slides=True, steps=[])


def test_tied_note_under_a_slide_carries_the_tie_on_its_row():
    rows = _tied_slide_rows()
    assert rows[1][0] == P.GT_FIRSTNOTE + 0x31 and rows[1][2:] == [P.CMD_TONEPORTA, 0]


def test_tied_note_under_a_slide_carries_the_slide_on_its_hold_rows():
    rows = _tied_slide_rows()
    assert [r[2] for r in rows[2:4]] == [2, 2]          # CMD_PORTADOWN, both hold rows
    assert rows[2][3] == rows[3][3] != 0


def test_a_one_row_tied_slide_note_keeps_the_slide():
    rows = _decode(0xC0 | TIE, 0x30, 0x82, 0x00, 0x01, 0xC0, 0x31,
                   slides=True, steps=[])
    assert rows[1][2] in (1, 2)


def test_an_untied_slide_note_is_unchanged():
    # (the first note is two rows long: behind a one-row note this one would
    # be a pitch change -- see the one-row tests below)
    rows = _decode(0xC0 | 1, 0x30, 0x82, 0xFF, 0xF6, 0xC0 | 2, 0x31,
                   slides=True, steps=[])
    assert [r[2] for r in rows[2:5]] == [2, 2, 2]


def test_exit_state_is_reported_when_the_last_durations_flag_is_set():
    # the flag of the byte before the LAST note governs the next pattern's first
    ex: list = []
    _decode(0xC0 | 1, 0x30, 0xC0 | TIE | 1, 0x31, exits_tied=ex)
    assert ex == [True]
    ex = []
    _decode(0xC0 | TIE | 1, 0x30, 0xC0 | 1, 0x31, exits_tied=ex)
    assert ex == [False]


def test_exit_state_needs_the_tie_option():
    ex: list = []
    _decode(0xC0 | TIE | 1, 0x30, exits_tied=ex, tie=False)
    assert ex == [False]


@pytest.mark.skipif(not (SID_DIR / "Lion_Heart.sid").exists(),
                    reason="corpus not present")
def test_interleaved_index_reports_exits_and_declines_the_wrap_tie():
    # The wrap tie would replace the first pass's attack AND the row-0 filter
    # command of Lion_Heart voice 2 (filter start f3 -> f34, passband .9998 ->
    # .9964): the original attacks that note on the first pass.
    from h2g.sidfile import load_sid
    from h2g import convert as C
    sid = load_sid(str(SID_DIR / "Lion_Heart.sid"))
    det = C._detect_tables(sid, lambda *a, **k: None)[1]
    _, ti = P.convert_patterns(sid, det, lambda *a, **k: None, slides=True,
                               tie=True, steps=[])
    assert det.pattern_dialect == "ilv"
    assert ti.wrap_tie is False
    assert any(ti.exits_tied), "ILV patterns that end tied are now reported"


@pytest.mark.skipif(not (SID_DIR / "Pacific_Coast.sid").exists(),
                    reason="corpus not present")
def test_pacific_coast_slide_tie_row_is_emitted_from_the_player_bytes():
    from h2g.sidfile import load_sid
    from h2g import convert as C
    sid = load_sid(str(SID_DIR / "Pacific_Coast.sid"))
    det = C._detect_tables(sid, lambda *a, **k: None)[1]
    # pattern 33 is `80 0b f7 30 82 ff f6 e7 30 ...`: a 24-row note whose flag
    # ties the slid 8-row note behind it
    ev = P.decode_entry(sid, det, 33, slides=True, tie=True, steps=[])
    rows = [ev[i:i + 4] for i in range(0, len(ev), 4)]
    first = next(i for i, r in enumerate(rows) if r[0] != P.GT_NO_NOTE)
    slid = [i for i, r in enumerate(rows) if r[2] == P.CMD_TONEPORTA]
    assert slid, "the tied slid note must carry a tie row"
    assert rows[slid[0] + 1][2] in (1, 2), "and its hold rows the slide"
    assert first == 0


# --- a one-row note leaves the gate open -----------------------------------
#
# Lion_Heart voice 0 f5149 (pattern 81 `80 07 c5 2b c3 60 c0 2b c0 2e c3 2f`):
# the original strikes the G-3 and then plays A#3 and B-3 as pitch changes on
# the same open gate -- one 16-frame note -- because a one-row note's gate-off
# never fires. Converted, the A#3 and B-3 were struck again and `hold` for
# instrument $0AF9 read 11 against the original's 16 (.923 -> 1.000).

def test_the_note_after_a_one_row_note_is_a_pitch_change():
    rows = _decode(0xC0, 0x30, 0xC0, 0x31, 0xC0 | 2, 0x32)
    notes = [r for r in rows if r[0] != P.GT_NO_NOTE and r[0] != P.GT_END_PATTERN]
    assert [r[2:] for r in notes] == [[0, 0], [P.CMD_TONEPORTA, 0], [P.CMD_TONEPORTA, 0]]


def test_the_note_after_a_longer_note_is_struck():
    rows = _decode(0xC0 | 1, 0x30, 0xC0, 0x31, 0xC0 | 2, 0x32)
    notes = [r for r in rows if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    assert [r[2:] for r in notes] == [[0, 0], [0, 0], [P.CMD_TONEPORTA, 0]]


def test_a_rest_after_a_one_row_note_is_not_a_note():
    rows = _decode(0xC0, 0x30, 0xC0, P.ILV_REST, 0xC0, 0x31)
    notes = [r for r in rows if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    assert notes[1][0] == P.GT_KEYOFF


def test_the_one_row_tie_is_off_without_the_tie_option():
    rows = _decode(0xC0, 0x30, 0xC0, 0x31, tie=False)
    assert all(r[2] != P.CMD_TONEPORTA for r in rows)


def test_one_row_tie_short_circuit(monkeypatch):
    monkeypatch.setattr(P, "ONEROW_TIE", False)
    rows = _decode(0xC0, 0x30, 0xC0, 0x31, 0xC0 | 2, 0x32)
    notes = [r for r in rows if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    assert [r[2:] for r in notes] == [[0, 0], [0, 0], [0, 0]]


@pytest.mark.skipif(not (SID_DIR / "Lion_Heart.sid").exists(),
                    reason="corpus not present")
def test_lion_heart_pattern_81_ties_the_two_notes_behind_the_one_row_g3():
    from h2g.sidfile import load_sid
    from h2g import convert as C
    sid = load_sid(str(SID_DIR / "Lion_Heart.sid"))
    det = C._detect_tables(sid, lambda *a, **k: None)[1]
    ev = P.decode_entry(sid, det, 81, slides=True, tie=True, steps=[])
    rows = [ev[i:i + 4] for i in range(0, len(ev), 4)]
    notes = [r for r in rows if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    # notes: 2b (6 rows), the rest (4 rows), then the one-row G-3 `c0 2b`, the
    # one-row A#3 `c0 2e` and the B-3 `c3 2f`
    assert notes[1][0] == P.GT_KEYOFF
    assert [r[2] for r in notes[2:5]] == [0, P.CMD_TONEPORTA, P.CMD_TONEPORTA]
