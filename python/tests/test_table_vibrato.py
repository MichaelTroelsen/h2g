"""The other vibrato: an LFO table walked one entry per frame.

The command-table engine (Hollywood or Bust, Chicken Song) carries no byte in
the $78/$07 format every other player shares, so `_find_vibrato` returns None
for both and neither file vibrated. Its parameter byte is a pair of nibbles --
which of four LFO tables, and how many units of `interval >> 4` one table step
is worth -- and the offset it produces each frame is

    table[i] * count * (interval >> unit_shift)

applied as an absolute position relative to the note. All four tables in both
files are triangles, which is the only reason Goattracker's fixed triangle can
stand in for them at all.

The mapping rests on what Goattracker's vibrato actually does, which these
tests pin by simulating gplay.c:795-801 rather than by quoting a constant:
peak-to-peak `(cmpvalue + 2) * speed` over a period of `2 * (cmpvalue + 2)`
calls. See goatwriter.VIBRATO_CMP_BIAS.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import (Detection, TABLE_VIBRATO_LFO_SHAPE, TABLE_VIBRATO_SHAPE,
                        TABLE_VIBRATO_UNIT_SHAPE, TableVibrato, detect,
                        _find_table_vibrato, _find_vibrato)
from h2g.goatwriter import (FORMAT_GTS2, FORMAT_GTS5, GT_MAX_VIB_SHIFT,
                            SPEED_NOTE_RELATIVE, VIBRATO_CMP_BIAS,
                            VIBRATO_DELAY, _table_vibrato_entry,
                            _vibrato_layout)
from h2g.search import search_file
from h2g.sidfile import load_sid

CORPUS = pathlib.Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
# The two files that carry it, and the four tables both of them carry.
TABLE_FILES = ("Hollywood_or_Bust", "Chicken_Song")
SHAPES = ((4, 1), (6, 2), (8, 2), (10, 3))
UNIT_SHIFT = 4


def _quiet(*_args):
    pass


class _FakeSid:
    """Instrument records of 8 bytes, vibrato parameter at +5."""

    def __init__(self, *params):
        data = bytearray()
        for p in params:
            data += bytes([0x00, 0x00, 0x41, 0x00, 0x00, p, 0x00, 0x00])
        self.data = bytes(data)


def _tv(shapes=SHAPES, unit_shift=UNIT_SHIFT, offset=5):
    return TableVibrato(offset, unit_shift, tuple(shapes))


def _layout(*params, multiplier=1, fmt=FORMAT_GTS5, vibrato=True, tv=None):
    det = Detection(instr_start=0, instr_stride=8,
                    table_vibrato=_tv() if tv is None else tv)
    table = []
    got = _vibrato_layout(_FakeSid(*params), det, len(params) + 1, vibrato,
                          fmt, multiplier, table)
    return got, table


def _gplay_vibrato(cmpvalue, speed, calls=400):
    """gplay.c:795-801, verbatim. The derivation's only load-bearing fact."""
    vibtime, freq, trace = 0, 0, []
    for _ in range(calls):
        if vibtime < 0x80 and vibtime > cmpvalue:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        freq += -speed if vibtime & 1 else speed
        trace.append(freq)
    return trace


# --- what Goattracker's vibrato does ---------------------------------------

def test_the_excursion_and_period_carry_a_bias_of_two():
    # Both halves of the mapping's arithmetic, for every cmpvalue either
    # engine can ask for. The +2 is not a rounding allowance: at cmpvalue 0 it
    # is the whole of the period.
    for cmp_value in range(0, 24):
        trace = _gplay_vibrato(cmp_value, 1)[20:]
        peak_to_peak = max(trace) - min(trace)
        top = [i for i in range(1, len(trace) - 1)
               if trace[i] == max(trace) and trace[i - 1] < trace[i]]
        assert peak_to_peak == cmp_value + VIBRATO_CMP_BIAS, cmp_value
        assert top[1] - top[0] == 2 * (cmp_value + VIBRATO_CMP_BIAS), cmp_value


def test_a_compare_value_of_zero_is_the_fastest_vibrato_not_an_absent_one():
    # cmp 0 is what the shortest of the four tables asks for, and $80 still
    # selects the note-relative speed, so it must not be read as "no entry".
    assert max(_gplay_vibrato(0, 1)) - min(_gplay_vibrato(0, 1)) == 2
    entry = _table_vibrato_entry(0x01, _tv(), 1)   # table 0, the 4-entry one
    assert entry is not None and entry[0] == SPEED_NOTE_RELATIVE


# --- the parameter byte -----------------------------------------------------

def test_the_byte_splits_into_a_table_index_and_a_count():
    # $24: table 2 (the 8-entry triangle), 4 units per table step.
    tv = _tv()
    assert tv.shapes[(0x24 & 0xF0) >> 4] == (8, 2)
    assert 0x24 & 0x0F == 4


def test_a_zero_byte_is_the_players_own_test():
    # `LDA record+5,Y / BNE` at Hollywood or Bust $05D1 jumps past the whole
    # routine, so a zero byte is no vibrato rather than table 0 count 0.
    assert _table_vibrato_entry(0x00, _tv(), 1) is None


def test_a_zero_count_multiplies_the_unit_by_nothing():
    assert _table_vibrato_entry(0x20, _tv(), 1) is None


def test_a_table_index_past_the_tables_read_gets_nothing():
    assert _table_vibrato_entry(0x91, _tv(), 1) is None


def test_an_unreadable_table_gets_nothing():
    assert _table_vibrato_entry(0x11, _tv(shapes=((4, 1), (0, 0))), 1) is None


# --- the mapping ------------------------------------------------------------

def test_the_period_matches_the_tables_length():
    # The table is walked one entry per frame, so its length IS the period;
    # Goattracker's is 2 * (cmp + 2) calls.
    for index, (length, _peak) in enumerate(SHAPES):
        entry = _table_vibrato_entry((index << 4) | 1, _tv(), 1)
        cmp_value = entry[0] & 0x7F
        assert 2 * (cmp_value + VIBRATO_CMP_BIAS) == length, index


def test_the_excursion_matches_the_tables_peak():
    # Both amplitudes in units of the semitone interval, which cancels: the
    # player's is peak * count / 2**unit_shift, Goattracker's is
    # (cmp + 2) / 2 * 2**-rshift. Exact wherever the ratio is a power of two.
    for byte, index, count in ((0x24, 2, 4), (0x13, 1, 3), (0x22, 2, 2)):
        length, peak = SHAPES[index]
        cmp_value, rshift = _table_vibrato_entry(byte, _tv(), 1)
        ours = (cmp_value & 0x7F) + VIBRATO_CMP_BIAS
        assert ours / 2.0 / (1 << rshift) == peak * count / (1 << UNIT_SHIFT)


def test_a_ratio_that_is_not_a_power_of_two_rounds_in_log_space():
    # $14 asks for 3x, which sits between shifts 1 and 2; log-space rounding
    # takes the multiplicatively nearer, which is 2 (4/3) over 1 (3/2).
    _cmp, rshift = _table_vibrato_entry(0x14, _tv(), 1)
    assert rshift == 2
    assert round(math.log2(3.0)) == 2


def test_the_entry_is_note_relative_and_starts_on_the_note():
    got, table = _layout(0x24)
    assert table[0][0] & SPEED_NOTE_RELATIVE
    assert got[0] == (1, VIBRATO_DELAY)


def test_the_period_and_excursion_both_scale_with_the_multiplier():
    # Goattracker's counter advances per play call and the player's per frame,
    # so at -S2 the period doubles in calls and the step must halve to keep
    # the same excursion -- the same division every other rate here takes.
    one = _table_vibrato_entry(0x24, _tv(), 1)
    two = _table_vibrato_entry(0x24, _tv(), 2)
    assert (two[0] & 0x7F) + VIBRATO_CMP_BIAS \
        == 2 * ((one[0] & 0x7F) + VIBRATO_CMP_BIAS)
    assert two[1] == one[1] + 1


def test_identical_parameters_share_one_entry():
    got, table = _layout(0x24, 0x24, 0x13)
    assert len(table) == 2
    assert got[0] == got[1] != got[2]


def test_no_parameter_byte_can_produce_an_unencodable_entry():
    # Every byte the format can hold, against the four real tables, at every
    # multiplier the packer uses. The shift clamp is defensive rather than
    # reached: the widest ratio these tables can ask for is about 2**10, so a
    # depth of zero would need a table this corpus does not contain.
    widest = 0
    for multiplier in (1, 2, 3):
        for byte in range(0x100):
            entry = _table_vibrato_entry(byte, _tv(), multiplier)
            if entry is None:
                continue
            left, rshift = entry
            assert left & SPEED_NOTE_RELATIVE
            assert 0 <= left & 0x7F <= 0x7F
            assert 0 <= rshift <= GT_MAX_VIB_SHIFT
            widest = max(widest, rshift)
    assert widest < GT_MAX_VIB_SHIFT


def test_the_compare_value_cannot_run_into_the_note_relative_bit():
    cmp_value, _ = _table_vibrato_entry(0x01, _tv(shapes=((0xFE, 1),)), 3)
    assert cmp_value & 0x7F == 0x7F


# --- when it applies --------------------------------------------------------

def test_off_by_default_means_no_entries():
    got, table = _layout(0x24, vibrato=False)
    assert got == {} and table == []


def test_a_gts2_file_gets_none():
    # GTS2 stores no speed table; its loader packs the vibrato into one byte
    # and reads the two record bytes the other way round (gsong.c:284-285).
    got, table = _layout(0x24, fmt=FORMAT_GTS2)
    assert got == {} and table == []


def test_a_player_with_neither_form_gets_none():
    det = Detection(instr_start=0, instr_stride=8)
    table = []
    assert _vibrato_layout(_FakeSid(0x24), det, 2, True, FORMAT_GTS5, 1,
                           table) == {}
    assert table == []


# --- against the corpus -----------------------------------------------------

def test_both_files_carry_it_at_record_plus_five():
    for name in TABLE_FILES:
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = detect(sid, _quiet)
        assert det.vibrato_offset is None, name
        assert det.table_vibrato is not None, name
        assert det.table_vibrato.offset == 5, name


def test_both_files_carry_the_same_four_triangles():
    for name in TABLE_FILES:
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        tv = detect(sid, _quiet).table_vibrato
        assert tv.shapes == SHAPES, name
        assert tv.unit_shift == UNIT_SHIFT, name


def test_the_unit_shift_is_counted_rather_than_assumed():
    # It is the 16 in the excursion arithmetic: a player shifting by 3 would
    # bend twice as far for the same parameter byte, so it is read off the
    # LSR/ROR pairs the player actually executes.
    sid = load_sid(str(CORPUS / "Hollywood_or_Bust.sid"))
    at = search_file(sid.data, TABLE_VIBRATO_UNIT_SHAPE)
    zp = sid.data[at + 19]
    pairs = 1
    k = at + 20
    while sid.data[k:k + 3] == bytes([0x4A, 0x66, zp]):
        pairs += 1
        k += 3
    assert pairs == UNIT_SHIFT


def test_it_is_consulted_only_where_the_classic_form_found_nothing():
    # The same rule find_relocation and the instrument-index shape follow: it
    # can rescue a file that vibrates not at all and never disturb one that
    # already reads. Warhawk carries the classic form; it must keep it.
    sid = load_sid(str(CORPUS / "Warhawk.sid"))
    det = detect(sid, _quiet)
    assert det.vibrato_offset == 5
    assert det.table_vibrato is None


def test_no_other_corpus_file_matches_the_shape():
    # Two files, and the whole corpus checked rather than the two asserted:
    # a shape this long matching a third player would be news either way.
    matched = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if search_file(sid.data, TABLE_VIBRATO_SHAPE) >= 1 \
                and search_file(sid.data, TABLE_VIBRATO_LFO_SHAPE) >= 1:
            matched.append(path.stem)
    assert matched == sorted(TABLE_FILES)


def test_the_files_that_do_not_match_get_nothing_from_it():
    for name in ("Commando", "Warhawk", "Delta"):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = detect(sid, _quiet)
        assert _find_table_vibrato(sid, det) is None, name


def test_hollywood_or_bust_emits_the_entries_its_records_ask_for():
    # Seven of twenty records carry a parameter byte; those seven collapse to
    # three distinct speed-table entries.
    sid = load_sid(str(CORPUS / "Hollywood_or_Bust.sid"))
    det = detect(sid, _quiet)
    table = []
    got = _vibrato_layout(sid, det, det.instr_used, True, FORMAT_GTS5, 1,
                          table)
    assert len(got) == 7
    assert len(table) == 3
    assert all(left & SPEED_NOTE_RELATIVE for left, _ in table)
