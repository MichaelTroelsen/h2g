"""A zero-`wait` event ties into the next note, in the players that let it.

The mechanism, and the one branch target that decides it per player, are
written up in detect.find_gate_hold. Two halves are pinned here:

  * `_build_raw_pattern` emits the tie for a zero-`wait` **note** and not for
    a zero-`wait` **rest**, and only when `gate_hold` and `tie` are both on;
  * `find_gate_hold` says yes for a player whose row-clock bypass lands past
    the gate-off test (Human_Race's `BNE $09EF -> JMP $0AF2`) and no for one
    whose bypass lands inside it (Saboteur_II's `BNE $F094 -> JMP $F1BC`).

The second half is built from synthetic bytes rather than corpus files, so
the two directions are pinned by something the repo carries; `Commando.sid`
anchors the yes direction on a real player.
"""
import pathlib

from h2g.detect import find_gate_hold
from h2g.patterns import GT_NO_NOTE, _build_raw_pattern
from h2g.sidfile import SidFile, load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

END = 0xFF          # ENDPATT status byte terminating a Hubbard pattern
ROW = 4             # bytes per Goattracker row
CMD_TONEPORTA = 3   # what a tie is spelled as, gcommon.h


def _rows(pattern_bytes, **kw):
    data = bytes(64) + bytes(pattern_bytes)
    events = _build_raw_pattern(data, 64, **kw)
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


# A zero-`wait` note, then a note. The second is the one that ties.
ZERO_WAIT_THEN_NOTE = [_status(0, get_next=True), 0x05, 0x20,
                       _status(1, get_next=True), 0x05, 0x24, END]
# A zero-`wait` *rest* (bit 6), then a note. The rest branch of these players
# closes the gate on its own -- Human_Race `$0A7C DEC $0DBC` -- so the note
# after it really does attack.
ZERO_WAIT_REST_THEN_NOTE = [_status(0, no_note=True),
                            _status(1, get_next=True), 0x05, 0x24, END]


def _cmd_of_second_note(rows):
    notes = [r for r in rows if r[0] not in (GT_NO_NOTE, END)]
    assert len(notes) == 2, f"expected 2 note rows, got {rows}"
    return notes[1][2]


def test_zero_wait_note_ties_the_next_note():
    rows = _rows(ZERO_WAIT_THEN_NOTE, tie=True, gate_hold=True)
    assert _cmd_of_second_note(rows) == CMD_TONEPORTA


def test_zero_wait_note_does_not_tie_without_gate_hold():
    rows = _rows(ZERO_WAIT_THEN_NOTE, tie=True, gate_hold=False)
    assert _cmd_of_second_note(rows) == 0


def test_zero_wait_note_does_not_tie_without_tie():
    rows = _rows(ZERO_WAIT_THEN_NOTE, tie=False, gate_hold=True)
    assert _cmd_of_second_note(rows) == 0


def test_nonzero_wait_note_does_not_tie():
    p = [_status(1, get_next=True), 0x05, 0x20,
         _status(1, get_next=True), 0x05, 0x24, END]
    assert _cmd_of_second_note(_rows(p, tie=True, gate_hold=True)) == 0


def test_zero_wait_rest_does_not_tie():
    """The rest branch closes the gate itself, so the next note attacks."""
    for sb6 in (False, True):
        rows = _rows(ZERO_WAIT_REST_THEN_NOTE, tie=True, gate_hold=True,
                     status_bit6=sb6)
        notes = [r for r in rows if r[0] not in (GT_NO_NOTE, END)]
        assert len(notes) == 1, f"status_bit6={sb6}: {rows}"
        assert notes[0][2] == 0, f"status_bit6={sb6}: rest tied the next note"


def test_bit5_tie_still_fires_with_gate_hold_off():
    """The rule this one was added beside must be untouched by it."""
    p = [_status(1, get_next=True, no_adsr=True), 0x05, 0x20,
         _status(1, get_next=True), 0x05, 0x24, END]
    assert _cmd_of_second_note(_rows(p, tie=True, gate_hold=False)) \
        == CMD_TONEPORTA


# --- detection ------------------------------------------------------------
#
# A minimal player carrying both halves of the routine. Laid out so the
# row-clock branch's target is the only thing that differs between the two
# cases; addresses are chosen to keep every branch in range.
LOAD = 0x1000
CLOCK = 0x40        # offset of `LDA abs / CMP abs / Bxx` -- the row clock
DEC = 0x50          # offset of `DEC counter,X / BMI / JMP hold`
TEST = 0x80         # offset of `LDA status,X / AND #$20 / ...`
COUNTER = 0x1234    # the cell the DEC decrements and the second LDA reads


def _player(bypass_into_test: bool) -> SidFile:
    from h2g.sidfile import HLEN
    base = HLEN - 1                     # to_offset(LOAD) == base + 0
    data = bytearray(base + 0x200)

    def addr(off):
        return LOAD + off

    def put(off, *bs):
        data[base + off:base + off + len(bs)] = bytes(bs)

    def rel(frm, to):                   # frm = offset of the branch opcode
        d = to - (frm + 2)
        assert -128 <= d <= 127, (frm, to)
        return d & 0xFF

    # The gate-off test: LDA status,X / AND #$20 / BNE out / LDA COUNTER,X /
    # BNE out / LDA wave,X / AND #$FE / STA $D404,Y
    out = TEST + 12
    put(TEST, 0xBD, 0x00, 0x13, 0x29, 0x20, 0xD0, rel(TEST + 5, out),
        0xBD, COUNTER & 0xFF, COUNTER >> 8, 0xD0, rel(TEST + 10, out))
    put(out, 0xBD, 0x10, 0x13, 0x29, 0xFE, 0x99, 0x04, 0xD4)

    # DEC counter,X / BMI fetch / JMP test-entry
    put(DEC, 0xDE, COUNTER & 0xFF, COUNTER >> 8, 0x30, 0x08,
        0x4C, (LOAD + TEST) & 0xFF, (LOAD + TEST) >> 8)

    # The row clock. Its bypass either lands on the JMP in front of the test
    # (Saboteur_II) or on `out`, past it (Human_Race).
    target = DEC + 5 if bypass_into_test else CLOCK + 8
    put(CLOCK, 0xAD, 0x20, 0x13, 0xCD, 0x21, 0x13,
        0xD0, rel(CLOCK + 6, target))
    if not bypass_into_test:
        put(CLOCK + 8, 0x4C, (addr(out)) & 0xFF, addr(out) >> 8)

    return SidFile(path="synthetic", data=bytes(data), name="", author="",
                   released="", load_addr=LOAD, subtunes=1)


def test_bypass_past_the_test_is_a_gate_hold_player():
    assert find_gate_hold(_player(bypass_into_test=False)) is True


def test_bypass_into_the_test_is_not():
    """Saboteur_II: the clock's own bypass shuts a zero-`wait` note's gate."""
    assert find_gate_hold(_player(bypass_into_test=True)) is False


def test_commando_is_a_gate_hold_player():
    assert find_gate_hold(load_sid(str(REPO_ROOT / "Commando.sid"))) is True
