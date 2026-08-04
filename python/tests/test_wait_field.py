"""An event's wait field means wait+1 frames, including wait==0.

Established by disassembling Commando's player. Each voice has a duration
counter (Commando: $54F2,X) loaded with `status & $1F`, sequenced by:

    $5078  DEC $54F2,X
    $507B  BMI  <fetch next event>
    $507D  JMP  <keep sustaining>

DEC/BMI fires only once the counter passes *below* zero, so a stored 0 still
occupies one frame before the next event is fetched. The VB6 original wrapped
the emit block in `If nWait >= 1` (h2g.frm:984) and dropped those events.
"""
from h2g.patterns import GT_NO_NOTE, _build_raw_pattern

END = 0xFF          # ENDPATT status byte terminating a Hubbard pattern
ROW = 4             # bytes per Goattracker row


def _rows(pattern_bytes):
    """Decode a synthetic pattern placed past the header guard in _build_raw_pattern."""
    data = bytes(64) + bytes(pattern_bytes)
    events = _build_raw_pattern(data, 64)
    assert events is not None
    return [events[i:i + ROW] for i in range(0, len(events), ROW)]


def _status(wait, *, get_next=False, no_note=False, no_adsr=False):
    b = wait & 0x1F
    if get_next:
        b |= 0x80
    if no_note:
        b |= 0x40
    if no_adsr:
        b |= 0x20
    return b


def test_wait_zero_still_emits_one_row():
    """The regression this test exists for: wait==0 used to emit nothing."""
    rows = _rows([_status(0, get_next=True), 0x05, 0x20, END])
    assert len(rows) == 2, f"expected 1 note row + ENDPATT, got {rows}"
    assert rows[0][0] != GT_NO_NOTE, "the note row was dropped"
    assert rows[1][0] == END


def test_wait_n_emits_n_plus_one_rows():
    for wait in (0, 1, 2, 5, 31):
        rows = _rows([_status(wait, get_next=True), 0x05, 0x20, END])
        assert len(rows) == wait + 2, (
            f"wait={wait}: expected {wait + 1} rows + ENDPATT, got {len(rows)}")
        # First row carries the note; the hold rows are all rests.
        assert rows[0][0] != GT_NO_NOTE
        for held in rows[1:wait + 1]:
            assert held[0] == GT_NO_NOTE
        assert rows[-1][0] == END


def test_consecutive_one_frame_events_all_survive():
    """Chimera pattern $6 is 96 back-to-back wait==0 events; it came out empty."""
    n = 96
    body = []
    for _ in range(n):
        body += [_status(0, get_next=True), 0x05, 0x20]
    rows = _rows(body + [END])
    assert len(rows) == n + 1, f"expected {n} rows + ENDPATT, got {len(rows)}"
    assert all(r[0] != GT_NO_NOTE for r in rows[:-1])


def test_total_duration_matches_player_frame_count():
    """Rows emitted must equal the frames the player would spend."""
    waits = [0, 3, 0, 7, 1, 0, 31]
    body = []
    for w in waits:
        body += [_status(w, get_next=True), 0x05, 0x20]
    rows = _rows(body + [END])
    assert len(rows) - 1 == sum(w + 1 for w in waits)
