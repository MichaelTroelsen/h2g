"""A tie survives a pattern boundary, because the player's gate does.

`_build_raw_pattern`'s `pending_tie` is a local and starts False at every
pattern; the player's state does not restart. Its note-end gate-off sits on
the *hold* path of the previous event and a `$FF` terminator is an orderlist
fetch, not an event -- so nothing between two patterns closes the gate, and a
pattern whose predecessor's last event carried status bit 5 (or, where
`gate_hold` reads it, a zero `wait`) is entered exactly as a tied note is
entered inside a pattern. Until this, the converter re-struck it.

Three halves are pinned here:

  * `_build_raw_pattern` reports that state through its `exits_tied`
    out-parameter, and reports it for the same two causes and under the same
    gates the intra-pattern tie uses (`tests/test_gate_hold.py` pins those);
  * `_apply_boundary_ties` writes the tie into row 0 of a **copy** of the
    successor, never in place -- 96 of the 180 corpus entries that are ever
    entered tied are also entered untied somewhere, so a shared pattern would
    silence attacks the player really makes;
  * `reindex_tracks` carries that state from the orderlist step that produces
    it to the one that consumes it, across a transpose byte, and does nothing
    at all when handed a plain list instead of a `TrackIndex`.

The file is named for the wait==0 tie because that is the cause this defect
was found behind: on Human_Race the boundary tie is *entirely* downstream of
it -- with `gate_hold` forced off the boundary pass changes not one byte of
that file. It is not downstream of it corpus-wide: 22 of the 30 files the
pass moves still move with the wait==0 clause disabled, on status bit 5
alone.
"""
import pathlib

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import _detect_tables
from h2g.patterns import (CMD_TONEPORTA, GT_NO_NOTE, MAX_PATTERNS, TrackIndex,
                          _apply_boundary_ties, _build_raw_pattern,
                          decode_entry, reindex_tracks)
from h2g.sidfile import load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

END = 0xFF          # ENDPATT status byte terminating a Hubbard pattern
NOTE = 0x64         # an arbitrary Goattracker note in range
ROW = 4


def _status(wait, *, get_next=False, no_note=False, no_adsr=False):
    b = wait & 0x1F
    if get_next:
        b |= 0x80
    if no_note:
        b |= 0x40
    if no_adsr:
        b |= 0x20
    return b


def _exit_state(pattern_bytes, **kw):
    ex: list = []
    data = bytes(64) + bytes(pattern_bytes)
    events = _build_raw_pattern(data, 64, exits_tied=ex, **kw)
    assert events is not None
    assert len(ex) == 1, f"expected exactly one report, got {ex}"
    return ex[0]


# One ordinary note, then the event whose status byte decides the exit state.
def _ending_on(status_byte, *, operand=True):
    p = [_status(1, get_next=True), 0x05, 0x20, status_byte]
    if operand:
        p += [0x05, 0x24]
    return p + [END]


# --- what _build_raw_pattern reports --------------------------------------

def test_bit5_last_event_exits_tied():
    p = _ending_on(_status(1, get_next=True, no_adsr=True))
    assert _exit_state(p, tie=True) is True


def test_plain_last_event_does_not_exit_tied():
    assert _exit_state(_ending_on(_status(1, get_next=True)), tie=True) is False


def test_zero_wait_last_event_exits_tied_only_with_gate_hold():
    p = _ending_on(_status(0, get_next=True))
    assert _exit_state(p, tie=True, gate_hold=True) is True
    assert _exit_state(p, tie=True, gate_hold=False) is False


def test_zero_wait_rest_does_not_exit_tied():
    """The rest branch closes the gate itself -- see test_gate_hold.py."""
    p = _ending_on(_status(0, no_note=True), operand=False)
    assert _exit_state(p, tie=True, gate_hold=True) is False


def test_tie_off_never_exits_tied():
    """`tie` is the option the whole mechanism hangs off, fixture included."""
    for sb in (_status(1, get_next=True, no_adsr=True), _status(0, get_next=True)):
        assert _exit_state(_ending_on(sb), tie=False, gate_hold=True) is False


def test_nothing_is_reported_when_the_decode_fails():
    ex: list = []
    assert _build_raw_pattern(bytes(16), 900, exits_tied=ex, tie=True) is None
    assert ex == []


def test_the_out_parameter_changes_no_byte():
    p = _ending_on(_status(1, get_next=True, no_adsr=True))
    data = bytes(64) + bytes(p)
    with_it = _build_raw_pattern(data, 64, tie=True, exits_tied=[])
    without = _build_raw_pattern(data, 64, tie=True)
    assert with_it == without


# --- what _apply_boundary_ties writes -------------------------------------

def _pattern(note=NOTE, cmd=0, data=0):
    return [note, 0x01, cmd, data, 0xFF, 0, 0, 0]


def test_the_tie_lands_on_a_copy_and_not_on_the_pattern():
    patterns = [_pattern()]
    track = [0]
    n = _apply_boundary_ties(track, {0: 0}, {0}, patterns, {})
    assert n == 1
    assert len(patterns) == 2, "no copy was made"
    assert track == [1], "the step was not pointed at the copy"
    assert patterns[0][2:4] == [0, 0], "the shared pattern was patched"
    assert patterns[1][:4] == [NOTE, 0x01, CMD_TONEPORTA, 0]


def test_a_contested_pattern_keeps_its_untied_entries():
    """The apply_tempos rule: the state belongs to the position, not the
    pattern. Steps 0 and 2 play pattern 0; only step 0 is entered tied."""
    patterns = [_pattern()]
    track = [0, 0, 0]
    _apply_boundary_ties(track, {0: 0, 1: 1, 2: 2}, {0}, patterns, {})
    assert track == [1, 0, 0]


def test_one_copy_serves_every_tied_step():
    patterns = [_pattern()]
    track = [0, 0]
    n = _apply_boundary_ties(track, {0: 0, 1: 1}, {0, 1}, patterns, {})
    assert n == 2
    assert len(patterns) == 2 and track == [1, 1]


def test_a_row_zero_with_no_note_is_left_alone():
    """`pending_tie` is consumed by a note, and recomputed by anything else."""
    patterns = [_pattern(note=GT_NO_NOTE)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert track == [0] and len(patterns) == 1


def test_a_taken_command_column_is_left_alone():
    """The intra-pattern tie tests `cmd1 == 0` too; this is the same rule."""
    patterns = [_pattern(cmd=15, data=6)]        # CMD_SETTEMPO
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert track == [0] and len(patterns) == 1


def test_a_row_that_already_ties_costs_no_copy():
    patterns = [_pattern(cmd=CMD_TONEPORTA, data=0)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 1
    assert track == [0] and len(patterns) == 1


def test_the_pattern_limit_is_respected():
    patterns = [_pattern() for _ in range(MAX_PATTERNS)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert len(patterns) == MAX_PATTERNS


# --- what reindex_tracks carries ------------------------------------------

def _index(exits):
    """One slice per entry, entry i -> Goattracker pattern i."""
    return TrackIndex([[i] for i in range(len(exits))], exits)


def test_reindex_ties_the_step_after_a_tied_pattern():
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 1, 0xFF, 0]]
    out = reindex_tracks(tracks, _index([True, False]), patterns=patterns)
    # Step 1 follows entry 0, which exits tied, so it plays a tied copy.
    assert out[0][:2] == [0, 2]
    assert patterns[2][2:4] == [CMD_TONEPORTA, 0]


def test_reindex_does_not_tie_after_an_untied_pattern():
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 1, 0xFF, 0]]
    out = reindex_tracks(tracks, _index([False, False]), patterns=patterns)
    assert out[0][:2] == [0, 1] and len(patterns) == 2


def test_a_transpose_byte_does_not_break_the_carry():
    """An orderlist transpose is consumed by the reader and plays nothing, so
    the gate the previous pattern left open is still open."""
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 0xD5, 1, 0xFF, 0]]
    out = reindex_tracks(tracks, _index([True, False]), patterns=patterns,
                         floor=0xD0)
    assert out[0][:3] == [0, 0xD5, 2]


def test_a_restart_operand_is_not_read_as_a_pattern():
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 0xFF, 0x00, 1]]
    out = reindex_tracks(tracks, _index([True, False]), patterns=patterns)
    # $00 after $FF is the restart position, not a reference, so entry 1 is
    # still preceded by entry 0 and ties.
    assert out[0] == [0, 0xFF, 0x00, 2]


def test_a_plain_list_gets_no_boundary_ties():
    """Backwards compatible: only a TrackIndex carries the state."""
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 1]]
    out = reindex_tracks(tracks, [[0], [1]], patterns=patterns)
    assert out[0] == [0, 1] and len(patterns) == 2


def test_no_patterns_means_no_pass():
    """reindex_tracks is called without `patterns` in several tests and by
    tracks.py; the pass must simply not run rather than raise."""
    out = reindex_tracks([[0, 1]], _index([True, False]))
    assert out[0] == [0, 1]


# --- the corpus files this was found on -----------------------------------

@needs_corpus
@pytest.mark.parametrize("name,tied,untied", [
    ("Human_Race.sid", (0x2, 0x3, 0x5, 0x6, 0x8, 0x9, 0xB, 0xC, 0x11),
     (0x0, 0x1, 0x4, 0x7, 0xA, 0xD)),
    ("Warhawk.sid", (0x23, 0x25, 0x26, 0x27, 0x28, 0x2F, 0x30),
     (0x0, 0x1, 0x2, 0x22, 0x24)),
])
def test_corpus_entries_report_the_expected_exit_state(name, tied, untied):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda m: None, 0)
    assert det.can_convert and det.gate_hold

    def state(i):
        ex: list = []
        assert decode_entry(sid, det, i, slides=True, status_bit6=True,
                            rest_instrument=True, instr_base=1, tie=True,
                            rest_keyoff=True, exits_tied=ex) is not None
        assert len(ex) == 1
        return ex[0]

    assert [i for i in tied if not state(i)] == []
    assert [i for i in untied if state(i)] == []
