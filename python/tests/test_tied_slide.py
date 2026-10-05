"""A slide event that follows a tied note is itself a tie: row 0 ties, the hold rows slide.

The classic grammar's slide event is `status, $8x operand, note`. It carries a
note byte like any other event, so when the PREVIOUS event's bit 5 left the gate
open the player writes that note into an open gate -- a frequency change and no
attack. `_build_raw_pattern`'s tie block used to require `cmd1 == 0`, which a
slide event never satisfies, so the slide won the command column and the note
re-struck: One_Man_and_his_Droid voice 0 played A#3 at frame 9735 AND at 9751
where the original strikes once (frame 9728) and slides from frame 9745, and the
next C-4 the same way, every 128 frames (task
`one-man-restrike-at-attack-856`).

A row has one command, so the claimants are split across rows: row 0 is
`CMD_TONEPORTA 0`, the hold rows carry the slide -- which is also where the
player puts it, since a slide steps on an event's non-fetch frames. An event
with `wait == 0` has no hold row, hence no slide frame in the original, and
keeps the old reading.
"""
from corpus import CORPUS, needs_corpus
from h2g.patterns import CMD_TONEPORTA, GT_NO_NOTE, _build_raw_pattern

CMD_PORTAUP = 1        # gcommon.h; patterns.py writes the literals 1 and 2
CMD_PORTADOWN = 2
END = 0xFF
NOTE = 0x2E            # the raw note byte One_Man's A#3 event carries
INSTR = 0x0D
SLIDE_UP = 0x96        # bit 7 set, bit 0 clear -> CMD_PORTAUP, (0x16 // 4) = 5
SLIDE_DOWN = 0x97      # bit 0 set -> CMD_PORTADOWN
SLIDE_DATA = 5
ROW = 4


def _status(wait, *, get_next=True, no_adsr=False):
    return (wait & 0x1F) | (0x80 if get_next else 0) | (0x20 if no_adsr else 0)


def _rows(pattern, **kw):
    data = bytes(64) + bytes(pattern)
    ev = _build_raw_pattern(data, 64, **kw)
    assert ev is not None
    return [ev[i:i + ROW] for i in range(0, len(ev), ROW)]


def _tied_then_slide(slide_byte=SLIDE_UP, *, first_adsr=True, wait=7):
    """A#3 (bit 5 unless told otherwise), 8 frames, then a slide event."""
    return [_status(7, no_adsr=first_adsr), INSTR, NOTE,
            _status(wait, no_adsr=True), slide_byte, NOTE, END]


def test_slide_after_tied_note_ties_on_row0_and_slides_on_hold_rows():
    rows = _rows(_tied_then_slide(), tie=True)
    first_note = rows[0][0]
    assert rows[8] == [first_note, 0, CMD_TONEPORTA, 0]
    for r in range(9, 16):
        assert rows[r] == [GT_NO_NOTE, 0, CMD_PORTAUP, SLIDE_DATA], r


def test_slide_down_is_tied_too():
    rows = _rows(_tied_then_slide(SLIDE_DOWN), tie=True)
    assert rows[8][2:] == [CMD_TONEPORTA, 0]
    assert rows[9][2:] == [CMD_PORTADOWN, SLIDE_DATA]


def test_without_tie_the_slide_keeps_row0():
    """`tie` is the option that reads bit 5; off, the old emission is untouched."""
    rows = _rows(_tied_then_slide(), tie=False)
    assert rows[8][2:] == [CMD_PORTAUP, SLIDE_DATA]
    assert rows[9][2:] == [CMD_PORTAUP, SLIDE_DATA]


def test_slide_after_an_untied_note_keeps_row0():
    """Previous event closed its gate: this note really attacks, slide on row 0."""
    rows = _rows(_tied_then_slide(first_adsr=False), tie=True)
    assert rows[8][2:] == [CMD_PORTAUP, SLIDE_DATA]


def test_zero_wait_slide_has_no_hold_row_and_keeps_the_old_reading():
    rows = _rows(_tied_then_slide(wait=0), tie=True)
    assert rows[8][2:] == [CMD_PORTAUP, SLIDE_DATA]
    assert len(rows) == 9 + 1          # the 9 rows, then END


def test_the_tie_state_runs_on_through_the_slide_event():
    """The slide event carries bit 5 as well, so the next plain note ties."""
    p = [_status(7, no_adsr=True), INSTR, NOTE,
         _status(7, no_adsr=True), SLIDE_UP, NOTE,
         _status(7, get_next=False), 0x30, END]
    rows = _rows(p, tie=True)
    assert rows[8][2:] == [CMD_TONEPORTA, 0]
    assert rows[16][2:] == [CMD_TONEPORTA, 0]
    assert rows[16][0] != GT_NO_NOTE


@needs_corpus
def test_one_man_pattern_entry_31_does_not_restrike_at_the_slide():
    """Entry 31 is the original's `a7 0d 2e  a7 96 2e`: A#3 then a slide event."""
    from h2g.convert import _detect_tables
    from h2g.patterns import decode_entry
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "One_Man_and_his_Droid.sid")), lambda m: None, 0)
    ev = decode_entry(sid, det, 31, slides=True, tie=True, status_bit6=True,
                      instr_base=2)
    rows = [ev[i:i + ROW] for i in range(0, len(ev), ROW)]
    assert rows[0][0] == rows[8][0] != GT_NO_NOTE      # A#3 both times
    assert rows[8][2:] == [CMD_TONEPORTA, 0]           # ...but the 2nd is a tie
    assert rows[9][2:] == [CMD_PORTAUP, SLIDE_DATA]    # slide from the next row
