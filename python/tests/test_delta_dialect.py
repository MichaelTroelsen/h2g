"""Delta's orderlist repeat counts (version 10) and the bit-7 note flag.

**Version 10** is version 0's orderlist read with a repeat counter woven
through it. The pattern-end path at $BF85:

    DEC $C354,X / BNE      ; replay the same pattern, orderlist unmoved
    INC $C2EC,X            ; else step to the repeat byte
    LDA (track),Y / BMI    ; $FE/$FF: a marker, leave it to be read as one
    STA $C354,X            ; else it is the NEXT pattern's repeat count
    INC $C2EC,X            ; step past it to the pattern number

$BE8C seeds the counter with 1, so the layout is  P0, r1, P1, r2, ... marker.
Reading it flat -- what version 0 does, and what Delta got until v0.5.52 --
plays every repeat count as a pattern number: half of every orderlist was
garbage. Delta is the only corpus file with the DEC form (Warhawk's $115D has
a plain INC there). Confirmation that this reading is right and the equally
plausible (pattern, repeat) pairing is not: decoded this way all 13 subtunes
come out with their three voices exactly equal in frames (subtune 0 is 13632
frames in all three); the pairing disagrees by up to 12x.

**The bit-7 note flag**: the player stores the raw pattern byte, masks with
AND #$7F before the frequency lookup, and BMIs on the stored copy to skip the
pulse/ADSR retrigger (Delta $BEFF/$BF31; same idiom in Sanxion $B11C, W.A.R.
$E536, Zoolook $411D -- 14 corpus files). The old decoder clamped the raw
byte, so every flagged note collapsed onto $BC: Delta pattern $01's six
distinct notes ($B4 $B2 $B4 $AF $AD $AF, per siddump) all played as one.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import _build_raw_pattern
from h2g.tracks import _build_track

END = [0xFF, 0x00]
STOP = [0xFF, 0xFD]


def _track(raw):
    return _build_track(bytes(raw), 0, 10, log=None, transpose_operand=False)


# --- version 10 orderlists --------------------------------------------------

def test_repeat_counts_are_not_pattern_numbers():
    # P0=5, r=2, P1=6, r=3, P2=7, end. Flat version-0 reading would emit
    # [5, 2, 6, 3, 7]; the counts must instead multiply their patterns.
    assert _track([0x05, 0x02, 0x06, 0x03, 0x07, 0xFF]) == \
        [0x05, 0x06, 0x06, 0x07, 0x07, 0x07] + END


def test_first_pattern_plays_once():
    # $BE8C seeds the counter with 1: position 0 is a pattern, not a count.
    assert _track([0x09, 0xFF]) == [0x09] + END


def test_a_marker_is_not_read_as_a_repeat_count():
    # The BMI at $BF92 leaves $FE/$FF in place, so a pattern followed
    # immediately by the terminator plays once.
    assert _track([0x05, 0x03, 0x06, 0xFF]) == [0x05, 0x06, 0x06, 0x06] + END


def test_fe_still_means_tune_ended():
    assert _track([0x05, 0xFE]) == [0x05] + STOP


def test_a_repeat_of_zero_counts_256_times():
    # The player's DEC wraps $00 to $FF and the BNE keeps replaying, so a
    # stored 0 is 256 plays -- which cannot fit in a 254-byte orderlist and
    # must truncate cleanly rather than emit nothing.
    track = _track([0x05, 0x00, 0x06, 0xFF])
    assert track[-2:] == END
    assert len(track) <= 254


# --- the bit-7 note flag ----------------------------------------------------

def _first_note(raw, note_flag):
    events = _build_raw_pattern(bytes([0x00, 0x00]) + bytes(raw), 2,
                                note_flag=note_flag)
    return events[0]


def test_note_flag_masks_bit_7_before_the_clamp():
    # $01 $B4 is a one-frame event with note $B4. The player's `ASL / TAY`
    # table fetch reads it as $34 (patterns._wrap_note) whether or not the
    # note_flag mask ran first, so the clamp onto $5C is never reached.
    assert _first_note([0x01, 0xB4, 0xFF], note_flag=True) == 0x34 + 0x60
    assert _first_note([0x01, 0xB4, 0xFF], note_flag=False) == 0x34 + 0x60


def test_unflagged_notes_are_untouched_by_the_mask():
    assert _first_note([0x01, 0x34, 0xFF], note_flag=True) == \
        _first_note([0x01, 0x34, 0xFF], note_flag=False)


# --- status bit 5 -----------------------------------------------------------
#
# Bit 5 of a classic status byte is tested by the player in ONE place, the
# hold path at the note's end (Commando $517F `LDA $54F5,X / AND #$20 / BNE`
# past the gate-off at $518B; IK_plus $E1B8 into its mask at $E5E0,X). The
# fetch writes the frequency, the gated waveform and the ADSR pair for a
# bit-5 event exactly as for any other ($5106-$5151), so the event that
# carries the bit attacks, and the NEXT note is the one that arrives on an
# open gate. The VB6 original (h2g.frm:927-933) put `CMD_TONEPORTA 0` on the
# bit-5 event itself when bit 7 was set and the last two instruments named
# were equal; the port carried that through v0.5.487. See the comment at the
# operand fetch in patterns._build_raw_pattern.

def _rows(raw, **kw):
    events = _build_raw_pattern(bytes([0x00, 0x00]) + bytes(raw), 2, **kw)
    return [tuple(events[k:k + 4]) for k in range(0, len(events), 4)]


# wait 1 + instr 2 + note; the same again (so the VB6 history test would
# hold); wait 1 + BIT 5 + instr 2 + note; wait 1 + note; end.
_BIT5_RUN = [0x81, 0x02, 0x30, 0x81, 0x02, 0x34, 0xA1, 0x02, 0x38,
             0x01, 0x3C, 0xFF]


def test_the_event_carrying_bit_5_attacks():
    # Row 4 is the bit-5 event. The player writes its gate and envelope like
    # any other note, so no command may suppress its attack -- at defaults
    # or with `tie`, since a tie is the NEXT note's property.
    for tie in (False, True):
        rows = _rows(_BIT5_RUN, tie=tie)
        assert rows[4][0] == 0x38 + 0x60, rows
        assert rows[4][2:] == (0, 0), (tie, rows[4])


def test_the_note_after_a_bit_5_event_is_the_tied_one():
    # Row 6 is the note the player never gated off before: `tie` spells it
    # TONEPORTA 0, and without `tie` nothing else may.
    assert _rows(_BIT5_RUN, tie=True)[6] == (0x3C + 0x60, 0x04, 3, 0)
    assert _rows(_BIT5_RUN, tie=False)[6] == (0x3C + 0x60, 0x04, 0, 0)


def test_no_note_row_carries_toneporta_without_tie():
    # The property behind both: with `tie` off, `_build_raw_pattern` has no
    # emitter of CMD_TONEPORTA left. Every bit-5 / bit-7 / instrument-history
    # combination the VB6 branch keyed on is in this run.
    raw = [0x81, 0x02, 0x30, 0xA1, 0x02, 0x34, 0xA1, 0x02, 0x38,
           0xA1, 0x83, 0x3C, 0xA1, 0x02, 0x40, 0x21, 0x44, 0xFF]
    for note, _instr, cmd, _data in _rows(raw, tie=False):
        assert cmd != 3, (note, cmd)
