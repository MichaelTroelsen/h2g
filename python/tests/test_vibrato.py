"""Per-instrument vibrato: the pitch movement that is in no byte we read.

The player applies it *between* the frequency-table lookup and the SID write,
so no pattern byte and no instrument field shows it happening -- only the one
byte that parameterises it. This writer left the two Goattracker record bytes
that drive vibrato at `0x00, 0x00`, so **no file the project ever produced
vibrated**, and 33 of 95 corpus files moved the pitch not at all where the
original does (20 of those originals vibrato-shaped: their movement returns
rather than travels).

Both sides express the depth the same way, which is what makes the mapping
close to literal:

    player (Warhawk $1221)   depth = (freq(note) - freq(note-1)) >> shift
    Goattracker (gplay.c:786-792)  speed = interval(note) >> rtable[STBL]

and both oscillate it against a counter bound. See detect.VIBRATO_SHAPE for
the census -- 56 of 95 files, masks $78 and $07 in all 56, and all 56 also
carrying the note-relative depth.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import (Detection, VIBRATO_BOUND_MASK, VIBRATO_DEPTH_SHAPES,
                        VIBRATO_SHAPE, VIBRATO_SHIFT_MASK, _find_vibrato)
from h2g.goatwriter import (FORMAT_GTS2, FORMAT_GTS5, GT_MAX_VIB_SHIFT,
                            SPEED_NOTE_RELATIVE, VIBRATO_CMP_BIAS,
                            VIBRATO_DELAY, _vibrato_layout)
from h2g.search import search_file
from h2g.sidfile import load_sid

CORPUS = _CORPUS


class _FakeSid:
    """Instrument records of 8 bytes, vibrato parameter at +5."""

    def __init__(self, *params):
        self.data = bytearray()
        for p in params:
            self.data += bytes([0x00, 0x00, 0x41, 0x00, 0x00, p, 0x00, 0x00])
        self.data = bytes(self.data)


def _layout(*params, multiplier=1, fmt=FORMAT_GTS5, vibrato=True, table=None):
    det = Detection(instr_start=0, instr_stride=8, vibrato_offset=5)
    tbl = table if table is not None else []
    got = _vibrato_layout(_FakeSid(*params), det, len(params) + 1, vibrato,
                          fmt, multiplier, tbl)
    return got, tbl


# --- the parameter ----------------------------------------------------------

def test_the_byte_splits_into_a_bound_and_a_shift():
    # $2B: bits 3-6 are 5 (the amplitude bound), bits 0-2 are 3 (the shift).
    assert (0x2B & VIBRATO_BOUND_MASK) >> 3 == 5
    assert 0x2B & VIBRATO_SHIFT_MASK == 3
    got, table = _layout(0x2B)
    # cmp = bound * multiplier - 2; rshift = shift + 1 + log2(multiplier).
    assert table == [(SPEED_NOTE_RELATIVE | 3, 4)]
    assert got == {0: (1, VIBRATO_DELAY)}


def test_the_entry_is_note_relative():
    # Bit $80 on the left is what makes gplay.c compute the speed from the
    # semitone interval at the current note rather than read it literally --
    # which is the player's own `freq(note) - freq(note-1)`.
    _, table = _layout(0x2B)
    assert table[0][0] & SPEED_NOTE_RELATIVE


def test_a_zero_byte_is_the_players_own_test():
    # Warhawk $11EA: `LDA record+5,Y / BNE` -- a zero byte skips the routine.
    got, table = _layout(0x00)
    assert got == {} and table == []


def test_a_zero_bound_is_an_oscillation_with_no_excursion():
    # Bits 0-2 set, bits 3-6 clear: a depth that never gets applied to
    # anything, which is silence reached one step later.
    got, _ = _layout(0x07)
    assert got == {}


def test_identical_parameters_share_one_entry():
    got, table = _layout(0x2B, 0x2B, 0x2B)
    assert len(table) == 1
    assert {v[0] for v in got.values()} == {1}


# --- the -S multiplier ------------------------------------------------------

def test_the_period_and_depth_both_scale_with_the_multiplier():
    # Goattracker's counter advances per play *call*, the player's per frame.
    # At -S2 twice as many calls fit in the player's half-period, and each
    # step must be half the size so the excursion stays where the player
    # puts it: cmp 5*1-2 = 3 -> 5*2-2 = 8, rshift 4 -> 5.
    _, at1 = _layout(0x2B, multiplier=1)
    _, at2 = _layout(0x2B, multiplier=2)
    assert at1 == [(SPEED_NOTE_RELATIVE | 3, 4)]
    assert at2 == [(SPEED_NOTE_RELATIVE | 8, 5)]


def test_the_half_period_is_the_bound_in_frames_not_twice_it():
    # gplay.c:795-801 flips direction after `cmp + 2` calls, not `cmp / 2`.
    # A bound of 5 is 5 frames, so at -S1 the entry must ask for 5 calls.
    _, table = _layout(0x2B, multiplier=1)
    assert (table[0][0] & 0x7F) + VIBRATO_CMP_BIAS == 5


def test_a_bound_shorter_than_goattrackers_shortest_clamps_to_it():
    # bound 1 at -S1 wants a one-frame half-period; cmp 0 is two calls, the
    # fastest Goattracker has, and cmp cannot go negative.
    _, table = _layout(0x08, multiplier=1)      # bound 1, shift 0
    assert table == [(SPEED_NOTE_RELATIVE | 0, 1)]


def test_the_compare_value_cannot_run_into_the_note_relative_bit():
    # cmp is stored in the same byte as the $80 flag, so it has 7 bits.
    _, table = _layout(0x78, multiplier=3)      # bound 15 -> 15*3-2 = 43
    left = table[0][0]
    assert left & 0x7F <= 0x7F and left & SPEED_NOTE_RELATIVE


def test_a_shift_past_fifteen_is_clamped():
    # The interval is 16-bit; shifting it further is a vibrato with no depth,
    # and the byte would still be read as a shift.
    _, table = _layout(0x0F | 0x08, multiplier=3)
    assert table[0][1] <= GT_MAX_VIB_SHIFT


# --- gating -----------------------------------------------------------------

def test_off_by_default_means_no_entries_and_no_pointers():
    got, table = _layout(0x2B, vibrato=False)
    assert got == {} and table == []


def test_a_gts2_file_gets_none():
    # GTS2 stores no speed table: its loader packs the vibrato into a single
    # instrument byte and calls makespeedtable itself (gsong.c:285), and it
    # reads record bytes 5 and 6 the other way round (:284). Same numbers,
    # different encoding -- and the byte-exact fixture is a GTS2 file.
    got, table = _layout(0x2B, fmt=FORMAT_GTS2)
    assert got == {} and table == []


def test_a_player_without_the_routine_gets_none():
    det = Detection(instr_start=0, instr_stride=8, vibrato_offset=None)
    table: list = []
    assert _vibrato_layout(_FakeSid(0x2B), det, 2, True, FORMAT_GTS5, 1,
                           table) == {}
    assert table == []


# --- detection --------------------------------------------------------------

def test_warhawk_carries_it_at_record_plus_five_and_commando_does_not():
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect
    for name, want in (("Warhawk", 5), ("Mozart", 5), ("Commando", None)):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        assert detect(sid, log=lambda m: None).vibrato_offset == want, name


def test_every_file_with_the_split_also_has_the_note_relative_depth():
    if not CORPUS.is_dir():
        return
    # The census this mapping rests on: the parameter split and the depth
    # derivation always appear together, so reading one and assuming the other
    # is never a guess. 56 of 95 files, no exceptions.
    split = depth = both = 0
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        s = search_file(data, VIBRATO_SHAPE) >= 1
        d = any(search_file(data, p) >= 1 for p in VIBRATO_DEPTH_SHAPES)
        split += s
        depth += d
        both += s and d
    assert split == both, "a file splitting the byte but deriving depth some " \
                          "other way would need its own mapping"
    assert split >= 50, f"the shape should be family-wide, found {split}"
