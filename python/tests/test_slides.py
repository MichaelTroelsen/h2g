"""Pitch movement: the speed table, and the two-byte slide operand.

Two independent faults kept every converted tune from bending pitch at all.
Corpus-wide, over 10 s of each of 82 files, the originals slide 22876 times
and this converter used to manage **7**.

1. **The speed table was never written.** A portamento's data byte is a packed
   value only in a GTS2 file; in GTS3+ it is a 1-based index into the song's
   speed table (gplay.c:740 -- `(ltable[STBL][cmddata-1] << 8) |
   rtable[STBL][cmddata-1]`). This writer emitted an empty speed table, so
   every portamento it wrote resolved to speed 0 in exactly the format the
   presets use. GTS2 files escaped because their loader builds the table while
   reading (gsong.c:311-321).

2. **The step is 16 bits, split across two pattern bytes.** 41 of 95 corpus
   players fetch a second byte after the command operand (Warhawk $10EC:
   `INY / LDA (patt),Y / STA slidehi,X`). Reading only the first gave half the
   parameter and, worse, left the *second* byte to be played as a note with
   everything after it in that pattern read one position out.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import SLIDE_OPERAND_SHAPE, _find_slide_operand
from h2g.patterns import (GT_NO_NOTE, GT_SPEEDTABLE_COMMANDS,
                          _build_raw_pattern, build_speed_table)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _rows(events):
    return [tuple(events[k:k + 4]) for k in range(0, len(events), 4)]


# --- the operand ------------------------------------------------------------
#
# One event, laid out as the player reads it: b1 $80 (an operand follows, wait
# 0), operand $D9 (>= $80 so a slide; bit 0 set so downward, step low $58),
# step high $01, then the note -- and $FF to end the pattern.
#
# The two vectors differ only in where the terminator has to sit, because the
# whole point is that the two readings consume a different number of bytes.
TWO_BYTE = [0x00, 0x00, 0x80, 0xD9, 0x01, 0x17, 0xFF]
ONE_BYTE = [0x00, 0x00, 0x80, 0xD9, 0x01, 0xFF]


def test_without_the_flag_the_high_byte_is_played_as_the_note():
    # The behaviour every release up to v0.5.48 had, on a player that does have
    # the second byte. Pinned, not endorsed: it is still the default, so it has
    # to stay reachable and stated.
    rows = _rows(_build_raw_pattern(bytes(ONE_BYTE), 2))
    assert rows[0][0] == 0x01 + 0x60, "the step's high byte became the note"


def test_with_the_flag_the_note_is_the_note():
    rows = _rows(_build_raw_pattern(bytes(TWO_BYTE), 2, slide_operand=True))
    assert rows[0][0] == 0x17 + 0x60


def test_the_step_is_assembled_from_both_bytes():
    # ($01 << 8) | ($D9 & $7E) = $0158, and Goattracker stores a quarter of the
    # 16-bit step (gtable.c:881), so $0158 // 4 == $56.
    rows = _rows(_build_raw_pattern(bytes(TWO_BYTE), 2, slide_operand=True))
    assert rows[0][3] == 0x56
    # Reading one byte sees only the low half: ($D9 & $7F) // 4 == $16. The
    # high byte is zero in most events, which is why the old reading sounded
    # plausible where it did not desynchronise the pattern outright.
    assert _rows(_build_raw_pattern(bytes(ONE_BYTE), 2))[0][3] == 0x16


def test_direction_comes_from_bit_0():
    # Warhawk $132D: `AND #$01 / BEQ add`. Clear adds to the frequency
    # (CMD_PORTAUP 1), set subtracts (CMD_PORTADOWN 2).
    up = _rows(_build_raw_pattern(bytes([0, 0, 0x80, 0xD8, 0x01, 0x17, 0xFF]),
                                  2, slide_operand=True))
    down = _rows(_build_raw_pattern(bytes(TWO_BYTE), 2, slide_operand=True))
    assert up[0][2] == 1 and down[0][2] == 2


def test_a_truncated_operand_rejects_the_pattern_rather_than_over_reading():
    assert _build_raw_pattern(bytes([0x00, 0x00, 0x80, 0xD9]), 2,
                              slide_operand=True) is None


def test_an_instrument_operand_still_consumes_one_byte():
    # < $80 is an instrument number, not a slide, and has no second byte.
    rows = _rows(_build_raw_pattern(bytes([0, 0, 0x80, 0x03, 0x17, 0xFF]), 2,
                                    slide_operand=True))
    assert rows[0][0] == 0x17 + 0x60
    assert rows[0][1] == 0x03 + 2


# --- detection --------------------------------------------------------------

def test_the_shape_matches_the_players_that_have_the_second_fetch():
    # INY / LDA (zp),Y / BPL / STA abs,X / INY / LDA (zp),Y / STA abs,X
    two = bytes([0x00, 0xC8, 0xB1, 0xFD, 0x10, 0x0F, 0x9D, 0xB7, 0x15,
                 0xC8, 0xB1, 0xFD, 0x9D, 0xBA, 0x15])
    assert _find_slide_operand(two)


def test_the_shape_does_not_match_a_single_fetch():
    one = bytes([0x00, 0xC8, 0xB1, 0xFD, 0x10, 0x0F, 0x9D, 0xB7, 0x15,
                 0xA9, 0x00, 0x85, 0xFE, 0x60, 0x00])
    assert not _find_slide_operand(one)


def test_commando_does_not_have_it():
    # The fixture's own player, which is why the original tool never needed the
    # second byte and why honouring it cannot move the byte-exact output.
    assert not _find_slide_operand((REPO_ROOT / "Commando.sid").read_bytes())


# --- the speed table --------------------------------------------------------

def test_distinct_values_become_entries_and_the_column_becomes_an_index():
    patterns = [[0x60, 1, 1, 0x08,
                 GT_NO_NOTE, 0, 2, 0x0A,
                 GT_NO_NOTE, 0, 1, 0x08]]      # 0x08 again -- one entry, not two
    table = build_speed_table(patterns)
    assert table == [(0, 0x20), (0, 0x28)]      # 8*4 = 32, 10*4 = 40
    assert [patterns[0][k + 3] for k in range(0, 12, 4)] == [1, 2, 1]


def test_a_zero_parameter_stays_zero():
    # gplay.c special-cases cmddata 0 for every one of these commands (an
    # instant tone-portamento, a no-op slide). Turning it into index 1 would
    # silently give it the first entry's speed.
    patterns = [[0x60, 1, 3, 0x00]]
    assert build_speed_table(patterns) == []
    assert patterns[0][3] == 0


def test_commands_that_do_not_use_the_table_are_left_alone():
    # CMD_SETTEMPO (15) takes its value directly (gplay.c:494).
    patterns = [[0x60, 1, 15, 0x03]]
    assert build_speed_table(patterns) == []
    assert patterns[0][3] == 0x03
    assert 15 not in GT_SPEEDTABLE_COMMANDS


def test_the_table_cannot_overflow_max_tablelen():
    # A data byte has 255 non-zero values and each distinct one costs one
    # entry, which is exactly MAX_TABLELEN -- so no clamp is needed anywhere.
    patterns = [[b for v in range(1, 256)
                 for b in (GT_NO_NOTE, 0, 1, v)]]
    assert len(build_speed_table(patterns)) == 255
