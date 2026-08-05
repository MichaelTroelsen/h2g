"""The "digi" engine: interleaved pointer tables and a second pattern grammar.

Nine corpus files share a later Hubbard engine that none of the classic
signatures can read. Two things defeat them:

  * its pointer tables interleave lo,hi,lo,hi and the player doubles the index
    (`ASL` / `TAY` / `LDA table,Y` / `LDA table+1,Y`), so the classic
    "count = HI - LO - 1" yields zero patterns;
  * the table the orderlist-read instruction names is a runtime one, all zeroes
    on disk, with the authored pointers 8 bytes further on.

The orderlist grammar is the one versions 2/6/7 already use, so only the
pattern grammar is new. Read at Off the Cuff $1104:

    LDA (patt),Y / BPL note / AND #$40 / BEQ command
    -> bit 6 set: duration prefix, wait = b & $1F, sticky, then fetch again
    -> $80 + operand: set instrument      $82/$83 + two operands: effects
    -> note path peeks the *following* byte for $81, the end marker

so $81 never appears at the fetch point. A duration of W holds W+1 frames,
the same DEC/BMI convention as the classic players.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import (DIGI_END, GT_END_PATTERN, GT_KEYOFF, GT_NO_NOTE,
                          _build_raw_pattern_digi)

PAD = [0x00, 0x00]          # _build_raw_pattern_digi rejects addr <= 1
END_ROW = [GT_END_PATTERN, 0x00, 0x00, 0x00]


def _decode(stream):
    return _build_raw_pattern_digi(bytes(PAD + stream), len(PAD))


def _rows(events):
    return [tuple(events[k:k + 2]) for k in range(0, len(events), 4)]


# --- notes -----------------------------------------------------------------

def test_a_note_becomes_one_row_at_goattracker_pitch():
    # Goattracker's FIRSTNOTE is $60, and this engine's note values are plain
    # semitone offsets -- the same +$60 the classic decoder applies.
    assert _decode([0x17, DIGI_END]) == [0x77, 0x00, 0x00, 0x00] + END_ROW


def test_rest_gates_off():
    # $60 is compared before the frequency lookup ($1168) and gates off: $1184
    # decrements the gate mask $165D,X from $FF to $FE, which is what the
    # end-of-note release path writes too. A hold row would sustain instead.
    assert _decode([0x60, DIGI_END]) == [GT_KEYOFF, 0x00, 0x00, 0x00] + END_ROW


def test_notes_are_clamped_to_the_frequency_table():
    assert _decode([0x7F, DIGI_END])[0] == 0x5C + 0x60


# --- duration --------------------------------------------------------------

def test_duration_prefix_holds_for_wait_plus_one_rows():
    # $C3 -> wait 3 -> the note occupies 4 rows.
    assert _rows(_decode([0xC3, 0x17, DIGI_END])) == \
        [(0x77, 0x00), (GT_NO_NOTE, 0x00), (GT_NO_NOTE, 0x00),
         (GT_NO_NOTE, 0x00), (GT_END_PATTERN, 0x00)]


def test_duration_is_sticky_across_notes():
    # The player stores it once ($164B,X) and reloads it per event, so one
    # prefix governs every following note until another appears.
    rows = _rows(_decode([0xC1, 0x17, 0x23, DIGI_END]))
    assert rows == [(0x77, 0x00), (GT_NO_NOTE, 0x00),
                    (0x83, 0x00), (GT_NO_NOTE, 0x00), (GT_END_PATTERN, 0x00)]


def test_duration_zero_still_emits_its_own_row():
    assert _rows(_decode([0xC0, 0x17, DIGI_END])) == \
        [(0x77, 0x00), (GT_END_PATTERN, 0x00)]


# --- commands --------------------------------------------------------------

def test_set_instrument_applies_to_following_notes():
    # Goattracker instrument 1 is the empty "Clear Voice" slot, so the
    # player's record 0 is written as instrument 2 -- the same offset the
    # classic decoder uses.
    assert _rows(_decode([0x80, 0x03, 0x17, DIGI_END])) == \
        [(0x77, 0x05), (GT_END_PATTERN, 0x00)]


def test_instrument_persists_until_changed():
    rows = _rows(_decode([0x80, 0x01, 0x17, 0x80, 0x04, 0x17, DIGI_END]))
    assert [r[1] for r in rows[:2]] == [0x03, 0x06]


def test_two_operand_effects_are_skipped_whole():
    # $82/$83 take two operands. Consuming the wrong number would read an
    # operand as a note and desynchronise everything after it.
    for cmd in (0x82, 0x83):
        assert _rows(_decode([cmd, 0x11, 0x22, 0x17, DIGI_END])) == \
            [(0x77, 0x00), (GT_END_PATTERN, 0x00)]


# --- termination and bounds ------------------------------------------------

def test_the_end_marker_is_found_as_a_lookahead_after_a_note():
    events = _decode([0x17, DIGI_END, 0x17, 0x17])
    assert events[-4:] == END_ROW
    assert len(events) == 8          # one note row, one end row: nothing past $81


def test_an_unreachable_command_byte_rejects_the_pattern():
    # $84-$BF branch back to the fetch without advancing -- the player would
    # spin forever, so real data never contains one. Seeing it means the
    # pointer is not at a pattern.
    assert _decode([0x84, 0x17, DIGI_END]) is None


def test_out_of_range_addresses_are_rejected():
    assert _build_raw_pattern_digi(bytes([0x17, DIGI_END]), 0) is None
    assert _build_raw_pattern_digi(bytes([0x17, DIGI_END]), 99) is None


def test_a_stream_with_no_terminator_is_rejected_rather_than_run_off():
    assert _decode([0x17, 0x17, 0x17]) is None


# --- detection -------------------------------------------------------------

def test_the_engine_probe_requires_the_table_offset_relation():
    from h2g.detect import DIGI_RUNTIME_TABLE_LEN, DIGI_TRACK_TO_PATTERN
    # The orderlist table sits 8 bytes past the runtime one, and the pattern
    # table 10 past that. Six further corpus files match both code shapes but
    # fail this relation, and SIDId names every one of them RobTracker.
    assert DIGI_RUNTIME_TABLE_LEN == 8
    assert DIGI_TRACK_TO_PATTERN == 10
