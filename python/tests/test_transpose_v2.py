"""Version-2 orderlist transpose commands.

The version-2 player checks the high bit before anything else:

    LDY index,X / LDA (track),Y / BPL pattern_number / CMP #$FF / CMP #$FE

so $80-$FD are commands. The VB6 original grouped version 2 with versions
0/1/3, which have no such branch, and emitted those command bytes as pattern
numbers -- they then dangled past the end of the pattern table and were
dropped, and in the two-byte form the operand landed on a real but wrong
pattern.

The command sets a per-voice transpose. Saboteur II stores it at $F5B2,X
(`AND #$7F` / `STA $F5B2,X`) and reads it back at $F125 as
`AND #$7F` / `CLC` / `ADC $F5B2,X` -- added to the note before the frequency
table lookup. Auf Wiedersehen Monty is the same idiom at $E4AF / $E52C.
Goattracker's `cptr->trans` has identical semantics (assigned at gplay.c:979,
added at :927), so in-range values map exactly.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.tracks import (GT_MAX_TRANSPOSE, GT_TRANSUP, _build_track,
                        _transpose_byte)

V2 = 2
END = [0xFF, 0x00]


def _track(raw, version=V2, operand=False):
    return _build_track(bytes(raw), 0, version, log=None, transpose_operand=operand)


# --- the clamp -------------------------------------------------------------

def test_transpose_maps_zero_to_transup():
    assert _transpose_byte(0) == GT_TRANSUP  # $F0 == no transposition


def test_transpose_maps_in_range_values_exactly():
    assert _transpose_byte(7) == 0xF7
    assert _transpose_byte(GT_MAX_TRANSPOSE) == 0xFE


def test_transpose_clamps_above_the_format_ceiling():
    # $FF is LOOPSONG, not transpose +15: gplay.c:977 gates on `< LOOPSONG`
    # and gorder.c:70 rewrites a typed $FF back to $FE. So +14 is the ceiling.
    assert _transpose_byte(15) == 0xFE
    assert _transpose_byte(48) == 0xFE
    assert _transpose_byte(127) == 0xFE


# --- one-byte form (13 of the 14 version-2 players) ------------------------

def test_command_byte_carries_the_transpose():
    # Saboteur II voice 1 opens with exactly this: pattern $0A at transpose 0,
    # then +7, then +2, then +9 -- the same riff moved up a fifth, a second
    # and a sixth.
    assert _track([0x80, 0x0A, 0x87, 0x0A, 0x82, 0x0A, 0x89, 0x0A, 0xFF]) == \
        [0xF0, 0x0A, 0xF7, 0x0A, 0xF2, 0x0A, 0xF9, 0x0A] + END


def test_out_of_range_transpose_is_clamped_not_dropped():
    # Dropping it would leave the voice at the *previous* transpose for the
    # rest of the track; clamping is wrong by a known number of semitones.
    assert _track([0x98, 0x03, 0xFF]) == [0xFE, 0x03] + END


# --- two-byte form (Auf Wiedersehen Monty) ---------------------------------

def test_operand_form_takes_the_value_from_the_next_byte():
    # AWM's command byte is always $80; the transpose follows it.
    assert _track([0x80, 0x09, 0x03, 0xFF], operand=True) == [0xF9, 0x03] + END


def test_operand_form_does_not_emit_the_operand_as_a_pattern():
    # This is the corrupting case: before the fix $80 dangled (harmlessly
    # dropped) but the operand $09 was played as pattern 9.
    assert 0x09 not in _track([0x80, 0x09, 0xFF], operand=True)


def test_operand_form_truncates_cleanly_at_end_of_file():
    assert _track([0x80], operand=True) == END


# --- shared -----------------------------------------------------------------

def test_consecutive_transposes_collapse_to_the_last():
    # Legal in the player (it loops back for the next byte) but not in
    # Goattracker, which tests for one transpose per orderlist step. Both
    # assign rather than accumulate, so keeping the last is equivalent.
    assert _track([0x82, 0x85, 0x03, 0xFF]) == [0xF5, 0x03] + END


def test_terminators_still_win_over_the_command_path():
    assert _track([0x05, 0xFF]) == [0x05] + END
    assert _track([0x05, 0xFE]) == [0x05, 0xFF, 0xFD]


def test_low_bytes_are_still_pattern_numbers():
    assert _track([0x00, 0x7F, 0xFF]) == [0x00, 0x7F] + END


# --- the other versions must be untouched ----------------------------------

def test_version_0_still_reads_high_bytes_as_pattern_numbers():
    # Version 0 (Commando) has no BPL: only $FE/$FF are special there.
    assert _track([0x80, 0x0A, 0xFF], version=0) == [0x80, 0x0A] + END


def test_version_1_still_reads_high_bytes_as_pattern_numbers():
    assert _track([0x80, 0x0A, 0xFF], version=1) == [0x80, 0x0A] + END
