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


# --- the second slide dialect ----------------------------------------------
#
# The two-byte fetch says a second byte exists. It does not say which half of
# the step it is, and two players disagree behind the same fetch shape:
#
#   Warhawk $1320     operand & $7E is the LOW half, bit 0 the direction,
#                     the fetched byte the HIGH half
#   Flash Gordon $12EB  operand & $3F is the HIGH half (self-modified into an
#                     immediate), the fetched byte the LOW half, and the
#                     direction is `CMP #$BF / BCC` rather than a bit
#
# Read Flash Gordon's bytes Warhawk's way round and the step comes out about
# 256x too large -- which then saturated the 8-bit pattern column. All 15
# corpus files whose parameter sat on that clamp are in this dialect.

from h2g.detect import (SLIDE_HIGH_FIRST_DOWN, SLIDE_HIGH_FIRST_MASK,
                        _find_slide_high_first)
from h2g.patterns import MAX_SLIDE_STEPS, _step_index

CORPUS = pathlib.Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")

# The operand $84: bit 7 set (a command), below $BF so upward, and its low 6
# bits are 4 -- so the step's high half is 4. The next byte, $48, is the low
# half: $0448. Read the other way round it would be $4884, which saturates.
HIGH_FIRST = [0x00, 0x00, 0x80, 0x84, 0x48, 0x17, 0xFF]


def test_the_operand_carries_the_high_half():
    rows = _rows(_build_raw_pattern(bytes(HIGH_FIRST), 2, slide_operand=True,
                                    slide_high_first=True))
    assert rows[0][3] == min(0x0448 // 4, 0xFF), "0x0448 packed, not clamped"


def test_the_other_way_round_saturates_the_column():
    # The reading this replaces, on the same bytes: $4884 // 4 is 4641, which
    # the byte cannot hold, so it lands on the clamp and the step is lost.
    rows = _rows(_build_raw_pattern(bytes(HIGH_FIRST), 2, slide_operand=True))
    assert rows[0][3] == 0xFF


def test_the_direction_is_a_threshold_not_a_bit():
    # $84 and $85 differ in bit 0 -- Warhawk's direction flag -- and both are
    # below $BF, so both slide the same way here.
    for operand in (0x84, 0x85):
        ev = [0x00, 0x00, 0x80, operand, 0x48, 0x17, 0xFF]
        rows = _rows(_build_raw_pattern(bytes(ev), 2, slide_operand=True,
                                        slide_high_first=True))
        assert rows[0][2] == 1, "CMD_PORTAUP below the threshold"
    ev = [0x00, 0x00, 0x80, SLIDE_HIGH_FIRST_DOWN, 0x48, 0x17, 0xFF]
    rows = _rows(_build_raw_pattern(bytes(ev), 2, slide_operand=True,
                                    slide_high_first=True))
    assert rows[0][2] == 2, "$BF itself subtracts -- CMP/BCC, not CMP/BCC+1"


def test_the_two_dialects_partition_the_corpus():
    if not CORPUS.is_dir():
        return
    from h2g.search import search_file
    from h2g.sidfile import load_sid
    warhawk = "BD ?? ?? F0 ?? 29 7E 8D ?? ?? BD ?? ?? 29 01 F0 ??"
    both = []
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        if search_file(data, warhawk) >= 1 and _find_slide_high_first(data):
            both.append(path.name)
    assert both == [], "a file matching both consumers would need a tiebreak"


def test_the_dialect_is_read_out_of_the_two_named_players():
    if not CORPUS.is_dir():
        return
    from h2g.sidfile import load_sid
    assert _find_slide_high_first(load_sid(str(CORPUS / "Flash_Gordon.sid")).data)
    assert not _find_slide_high_first(load_sid(str(CORPUS / "Warhawk.sid")).data)


# --- the step index ---------------------------------------------------------
#
# A pattern data column is one byte and a step is sixteen. In a GTS5 file the
# column becomes a 1-based speed-table index anyway, so the decoder writes that
# index directly and the step keeps its full width.

def test_the_index_is_one_based_and_deduplicates():
    steps: list = []
    assert [_step_index(steps, v) for v in (0x0448, 0x0063, 0x0448)] == [1, 2, 1]
    assert steps == [0x0448, 0x0063]


def test_a_zero_step_stays_zero():
    # gplay.c reads cmddata 0 as "no parameter"; an index of 1 would name the
    # first entry instead.
    steps: list = []
    assert _step_index(steps, 0) == 0
    assert steps == []


def test_past_the_ceiling_the_nearest_step_is_reused():
    steps = list(range(100, 100 + MAX_SLIDE_STEPS))
    assert len(steps) == MAX_SLIDE_STEPS
    got = _step_index(steps, 10_000)
    assert len(steps) == MAX_SLIDE_STEPS, "the column cannot hold a 256th index"
    assert steps[got - 1] == max(steps), "the nearest one it has"


def test_the_table_is_the_steps_when_the_decoder_indexed_them():
    # The column already holds indices, so build_speed_table emits the steps
    # rather than unpacking a column -- and does not rewrite anything.
    patterns = [[GT_NO_NOTE, 0, 1, 1, GT_NO_NOTE, 0, 2, 2]]
    table = build_speed_table(patterns, 1, [0x0448, 0x0063])
    assert table == [(0x04, 0x48), (0x00, 0x63)]
    assert [patterns[0][3], patterns[0][7]] == [1, 2], "columns left alone"


def test_indexed_steps_are_scaled_by_the_multiplier_too():
    assert build_speed_table([], 2, [0x0448]) == [(0x02, 0x24)]
