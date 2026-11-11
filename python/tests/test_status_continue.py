"""A `$60`-class status byte is a held note in Delta, not a bit-6 rest.

Delta's fetch tests `status & $60 == $60` BEFORE the bit-6 branch
(`$BECA AND #$60 / CMP #$60 / BNE / JMP $BF74`, `detect.STATUS_CONTINUE_SHAPE`):
the event only reloads the counter and advances the cursor, so the voice keeps
its note, waveform and open gate, and bit 5 skips the gate-off at the counter's
end. The converter read every bit-6 byte as a rest (`KEYOFF`), so a `37 <note>
77` pair -- one held note of two events -- closed the gate at the `77` and
sounded the rest of the hold silent: Delta subtune 12 (`Delta_13`) voice 0,
17 runs of 32-122 gate-off frames, `gate` 85% -> 98% with the fix
(docs/LESSONS.md, v0.5.661).

Pinned here: the decode (with the detection short-circuited, the `KEYOFF`
comes back), the tie the next note owes an open gate, that a bit-6-only byte is
still a rest, and that Delta is the only corpus file carrying the shape.
"""
from corpus import CORPUS, needs_corpus
from h2g.detect import STATUS_CONTINUE_SHAPE
from h2g.patterns import (CMD_TONEPORTA, GT_KEYOFF, GT_NO_NOTE,
                          _build_raw_pattern)
from h2g.search import search_file
from h2g.sidfile import load_sid

END = 0xFF
ROW = 4


def _rows(events):
    return [tuple(events[i:i + ROW]) for i in range(0, len(events), ROW)]


def _decode(pattern, **kw):
    data = bytes(64) + bytes(pattern)
    ev = _build_raw_pattern(data, 64, status_bit6=True, rest_keyoff=True,
                            tie=True, **kw)
    assert ev is not None
    return _rows(ev)


# held note (wait 1, bit 5, note), a `$77` continue (wait 1), then a plain note
HELD = [0x21, 0x20, 0x61, 0x05, 0x24, END]


def test_continue_event_holds_without_a_rest():
    rows = _decode(HELD, status_continue=True)
    assert all(r[0] != GT_KEYOFF for r in rows)
    # note, its hold row, the continue event's first row and hold row
    assert rows[2] == (GT_NO_NOTE, 0, 0, 0)
    assert rows[3] == (GT_NO_NOTE, 0, 0, 0)


def test_short_circuited_the_continue_event_is_a_keyoff_again():
    rows = _decode(HELD, status_continue=False)
    assert rows[2][0] == GT_KEYOFF


def test_next_note_after_a_continue_event_arrives_on_an_open_gate():
    """Bit 5 skips the end-of-note close and the mask was reloaded to $FF."""
    rows = _decode(HELD, status_continue=True)
    note_row = rows[4]
    assert note_row[0] not in (GT_NO_NOTE, GT_KEYOFF)
    assert (note_row[2], note_row[3]) == (CMD_TONEPORTA, 0)


def test_exit_state_of_a_pattern_ending_on_a_continue_event_is_tied():
    ex: list = []
    data = bytes(64) + bytes([0x21, 0x20, 0x61, END])
    _build_raw_pattern(data, 64, status_bit6=True, rest_keyoff=True, tie=True,
                       status_continue=True, exits_tied=ex)
    assert ex == [True]


def test_a_bit6_only_status_byte_is_still_a_rest():
    p = [0x21, 0x20, 0x41, END]          # bit 6, no bit 5: a rest
    rows = _decode(p, status_continue=True)
    assert rows[2][0] == GT_KEYOFF


@needs_corpus
def test_only_delta_carries_the_shape():
    hits = []
    for path in sorted(CORPUS.glob("*.sid")):
        if search_file(load_sid(str(path)).data, STATUS_CONTINUE_SHAPE) >= 0:
            hits.append(path.name)
    assert hits == ["Delta.sid"]
