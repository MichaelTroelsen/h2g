"""The digi engine's tie: bit 5 of a `$C0-$FF` duration byte (DIGI_TIE).

`_build_raw_pattern_digi` used to keep only `b & 0x1F` of the duration byte,
so every note the player lands on an open gate was re-attacked. Rikky's voice
0 is where it was found -- 62 of its ties land at the end of an `$82` slide --
and at 04fdcb5 the conversion carried 0 TONEPORTA rows and sounded 774 attacks
against the original's 674 at `-t 180` (HISTORICAL; the A/B is in
C:/t/digi-tie). The routine is transcribed at DIGI_TIE in patterns.py.

Pinned here:

  * the constant is the operand the players' own hold path ANDs with, in
    every digi file of the corpus -- not a number read from one player;
  * a note after a DIGI_TIE note is `CMD_TONEPORTA 00`, a note after an
    untied note or after a rest is struck, and `tie=False` changes nothing;
  * a tied note owning a slide keeps both, the classic decoder's spelling:
    the tie on the note's row and the slide on its hold rows -- and with no
    hold row the slide keeps the row and the note stays struck;
  * `exits_tied` reports a pattern that ends on an open gate, which is what
    `_apply_boundary_ties` consumes;
  * `decode_entry` forwards `tie` and `exits_tied` to the digi decoder, and
    on Rikky the decoder's tie count agrees with an independent walk of the
    raw bytes.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g import detect
from h2g.patterns import (CMD_TONEPORTA, DIGI_TIE, GT_END_PATTERN, GT_KEYOFF,
                          GT_NO_NOTE, _build_raw_pattern_digi, decode_entry)
from h2g.search import search_file
from h2g.sidfile import load_sid

# The hold path's gate-off test (Rikky $11F9-$1208): copy the duration byte,
# AND it with the tie bit, skip the gate-off when set.
HOLD_PATH = "BD ?? ?? 9D ?? ?? 29 ?? D0 0A BD ?? ?? D0 05 A9 FE"
# The note start's read of the copied byte (Rikky $118B): AND, stash, and
# later branch past the pulse/ADSR/table block.
NOTE_START = "BD ?? ?? 29 ?? 8D ?? ?? BD ?? ?? 8E ?? ?? 0A 0A 0A 0A AA"


def _rows(events):
    return [tuple(events[i:i + 4]) for i in range(0, len(events), 4)]


def _decode(body, **kw):
    # Two pad bytes: the decoder refuses addr <= 1 as "not a pattern".
    return _build_raw_pattern_digi(bytes([0, 0]) + bytes(body), 2, **kw)


def _note(n):
    return n + 0x60


def test_note_after_a_tied_note_is_toneporta_and_after_an_untied_one_struck():
    # $E1 (tie, wait 1) is sticky over $3E and $40; $C1 (no tie) times $3E
    # and $41. So $40 and the second $3E land on an open gate, $41 does not.
    body = [0x80, 0x00, 0xE1, 0x3E, 0x40, 0xC1, 0x3E, 0x41, 0x81]
    rows = _rows(_decode(body, tie=True))
    assert rows == [
        (_note(0x3E), 2, 0, 0), (GT_NO_NOTE, 0, 0, 0),
        (_note(0x40), 2, CMD_TONEPORTA, 0), (GT_NO_NOTE, 0, 0, 0),
        (_note(0x3E), 2, CMD_TONEPORTA, 0), (GT_NO_NOTE, 0, 0, 0),
        (_note(0x41), 2, 0, 0), (GT_NO_NOTE, 0, 0, 0),
        (GT_END_PATTERN, 0, 0, 0),
    ]
    # Off, the stream is what it always was: no command anywhere.
    assert all(r[2] == 0 for r in _rows(_decode(body)))


def test_a_rest_is_not_held_open():
    # `$117F DEC $165B,X` closes the gate whatever the byte says: the note
    # after a rest attacks, and the rest itself carries no tie.
    rows = _rows(_decode([0xE1, 0x3E, 0x60, 0x3E, 0x81], tie=True))
    assert rows[2] == (GT_KEYOFF, 0, 0, 0)
    assert rows[4] == (_note(0x3E), 0, 0, 0)
    assert not any(r[2] == CMD_TONEPORTA for r in rows)


def test_a_tied_note_owning_a_slide_ties_on_its_row_and_slides_on_its_holds():
    # `$82 00 5A` is a slide up owned by the tied $40 (wait 1).
    rows = _rows(_decode([0xE1, 0x3E, 0x82, 0x00, 0x5A, 0x40, 0x81],
                         tie=True, slides=True))
    assert rows[2] == (_note(0x40), 0, CMD_TONEPORTA, 0)
    assert rows[3] == (GT_NO_NOTE, 0, 1, 0x5A // 4)


def test_a_tied_slide_owner_with_no_hold_row_keeps_the_slide_and_is_struck():
    # $E0: tie, wait 0 -- nowhere to move the slide to.
    rows = _rows(_decode([0xE0, 0x3E, 0x82, 0x00, 0x5A, 0x40, 0x81],
                         tie=True, slides=True))
    assert rows[1] == (_note(0x40), 0, 1, 0x5A // 4)


@pytest.mark.parametrize("body, tie, want", [
    ([0xE1, 0x3E, 0x81], True, True),           # ends on an open gate
    ([0xC1, 0x3E, 0x81], True, False),          # ends on a closed one
    ([0xE1, 0x3E, 0x60, 0x81], True, False),    # a rest closed it
    ([0xE1, 0x3E, 0x81], False, False),         # the option is off
])
def test_exits_tied_reports_the_gate_the_pattern_leaves(body, tie, want):
    ex = []
    assert _decode(body, tie=tie, exits_tied=ex) is not None
    assert ex == [want]


def _digi_files():
    out = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect.detect(sid, lambda *a, **k: None)
        except Exception:
            continue
        if det.pattern_dialect == "digi":
            out.append((path.name, sid, det))
    return out


@needs_corpus
def test_the_tie_bit_is_the_operand_every_digi_player_tests():
    files = _digi_files()
    assert len(files) >= 9, [f for f, _, _ in files]
    for name, sid, _ in files:
        at = search_file(sid.data, HOLD_PATH)
        assert at >= 0, f"{name}: hold-path gate-off shape not found"
        assert sid.data[at + 7] == DIGI_TIE, name
        at = search_file(sid.data, NOTE_START)
        assert at >= 0, f"{name}: note-start tie read not found"
        assert sid.data[at + 4] == DIGI_TIE, name


def _expected_ties(sid, det):
    """An independent walk of the raw bytes: notes landing on an open gate."""
    data = sid.data
    total = 0
    for i in range(det.pattern_used + 1):
        s = i * det.table_stride
        a = sid.to_offset(data[det.pattern_hi + s] * 256 + data[det.pattern_lo + s])
        dur, prev_open, slide = 0, False, False
        while 1 < a < len(data):
            b = data[a]
            if b == 0x81:
                break
            if b >= 0xC0:
                dur, a = b, a + 1
                continue
            if b == 0x80:
                a += 2
                continue
            if b in (0x82, 0x83):
                slide = slide or b == 0x82
                a += 3
                continue
            if b >= 0x80:
                break
            if b != 0x60 and prev_open and not (slide and dur & 0x1F == 0):
                total += 1
            prev_open = b != 0x60 and bool(dur & 0x20)
            slide = False
            a += 1
            if a < len(data) and data[a] == 0x81:
                break
    return total


@needs_corpus
def test_rikky_decode_entry_ties_exactly_what_the_bytes_say():
    sid = load_sid(str(CORPUS / "Rikky.sid"))
    det = detect.detect(sid, lambda *a, **k: None)
    assert det.pattern_dialect == "digi"
    got = off = 0
    for i in range(det.pattern_used + 1):
        ex = []
        ev = decode_entry(sid, det, i, slides=True, tie=True, exits_tied=ex)
        got += sum(1 for r in _rows(ev or []) if r[2] == CMD_TONEPORTA)
        # One report per decoded pattern: `convert_patterns` reads `ex[0]`.
        assert ev is None or len(ex) == 1, i
        ev = decode_entry(sid, det, i, slides=True, tie=False)
        off += sum(1 for r in _rows(ev or []) if r[2] == CMD_TONEPORTA)
    want = _expected_ties(sid, det)
    assert off == 0
    assert want > 60                    # 62 on voice 0's slides alone
    assert got == want
