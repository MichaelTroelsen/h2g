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


def test_a_relocating_player_resolves_its_vibrato_byte_too():
    """I, Ball names its instrument table in the space it relocates *into*.

    It copies $9000-$9FFF to $E000 at init, so the vibrato reads `$E710` while
    the table's load-space address is `$970B` -- a difference of 20485, which
    the stride check rejects, and the file got no vibrato at all. Resolving the
    operand through sid.to_offset (which consults the relocation only when the
    plain formula lands outside the file) makes it the same +5 as every other
    file that has the routine.

    Five of its eighteen records carry a non-zero vibrato byte, so this is not
    a cosmetic detection change -- but note that no dimension available here
    can show it: the original's within-note travel over the traced window is 0
    with ties excluded and melody-dominated with them included. See
    H2G-CONVERSION-METHOD.md section 7.yy.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect
    sid = load_sid(str(CORPUS / "I_Ball.sid"))
    assert sid.relocation is not None, "the fixture for this test relocates"
    det = detect(sid, log=lambda m: None)
    assert det.vibrato_offset == 5
    records = [sid.data[det.instr_start + i * det.instr_stride + 5]
               for i in range(det.instr_used)]
    assert sum(1 for v in records if v) == 5


def test_resolving_through_to_offset_moves_no_other_file():
    """The rescue must not be able to disturb a file that already read right.

    For an address the plain formula resolves, `to_offset(a) - instr_start` is
    algebraically `a - (instr_start + load_addr - HLEN + 1)`, the subtraction
    this replaced -- so the census below is the same one it always was, and
    every file in it still answers +5.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            det = detect(load_sid(str(path)), log=lambda m: None)
        except Exception:      # noqa: BLE001 -- an unconvertible file is not this test's business
            continue
        if det.vibrato_offset is not None:
            found[path.name] = det.vibrato_offset
    assert set(found.values()) == {5}, f"unexpected offsets: {found}"
    assert len(found) >= 50, f"the rescue should add one, found {len(found)}"


def test_the_zero_page_dialects_are_the_same_routine():
    """One vibrato in three addressing dialects, not three signatures.

    W_A_R stores the bound with `STA $D3,X` where the canonical shape has
    `STA abs,X` -- one addressing mode, one byte shorter, so the pattern
    misses. The masks, the PHA/PLA split and the `LDA record+5,Y` feeding it
    are identical, which is why these are variants rather than new signatures.
    See H2G-CONVERSION-METHOD.md section 7.zz.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect, VIBRATO_SHAPES
    assert VIBRATO_SHAPES[0] == VIBRATO_SHAPE, "canonical must be tried first"
    for name in ("W_A_R", "Tarzan", "Mega_Apocalypse",
                 "Samantha_Fox_Strip_Poker", "Spellbound"):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        assert search_file(sid.data, VIBRATO_SHAPE) < 1, \
            f"{name} is meant to miss the canonical shape"
        det = detect(sid, log=lambda m: None)
        assert det.vibrato_offset == 5, name
        # and the byte it now reads is real data, not an empty column
        records = [sid.data[det.instr_start + i * det.instr_stride + 5]
                   for i in range(det.instr_used)
                   if det.instr_start + i * det.instr_stride + 5 < len(sid.data)]
        assert any(records), f"{name} would gain a vibrato with no depth"


def test_the_store_variants_are_a_closed_set():
    """The fourth combination does not occur, so the set is not open-ended.

    56 files use abs,X + abs; 2 use zp,X + abs; 3 use zp,X + zp; and abs,X + zp
    has no instance. A file turning up in that last cell would mean the two
    stores vary independently and this enumeration is the wrong shape.
    """
    if not CORPUS.is_dir():
        return
    absx_zp = "48 29 78 4A 4A 4A 9D ?? ?? 68 29 07 85 ??"
    hits = [p.name for p in sorted(CORPUS.glob("*.sid"))
            if search_file(load_sid(str(p)).data, absx_zp) >= 1]
    assert hits == [], f"a fourth dialect exists: {hits}"


def test_the_triangle_gate_becomes_a_vibdelay():
    """The player's gate is a note-length threshold, not a countdown.

    `LDA $14EF,X / AND #$1F / CMP #$08 / BCC out` tests the note's own stored
    duration, and $14EF,X is written once per note and never stepped -- so a
    note shorter than 8 of the player's frames gets no vibrato at all.
    Goattracker cannot say "only notes this long", but vibdelay reproduces the
    half that matters: a note shorter than the delay ends before the
    oscillator starts. It counts play calls, so it scales by the multiplier.
    """
    from h2g.detect import Detection, TRIANGLE_VIBRATO_GATE
    from h2g.goatwriter import VIBRATO_DELAY, _vibrato_delay
    tri = Detection(triangle_vibrato=5)
    assert _vibrato_delay(tri, 1) == TRIANGLE_VIBRATO_GATE
    assert _vibrato_delay(tri, 2) == TRIANGLE_VIBRATO_GATE * 2
    # the gated players are the only ones that move: nothing else has a gate
    assert _vibrato_delay(Detection(vibrato_offset=5), 1) == VIBRATO_DELAY
    assert _vibrato_delay(Detection(vibrato_offset=5), 4) == VIBRATO_DELAY
    assert _vibrato_delay(Detection(), 1) == VIBRATO_DELAY


def test_vibdelay_stays_a_byte_and_never_disables():
    """0 would mean "never oscillate" (gplay.c:770), which is not the gate.

    A big multiplier must clamp rather than wrap past $FF into something the
    loader reads as a different delay entirely.
    """
    from h2g.detect import Detection
    from h2g.goatwriter import _vibrato_delay
    for mult in (1, 2, 3, 4, 5, 6, 40, 255):
        d = _vibrato_delay(Detection(triangle_vibrato=5), mult)
        assert 1 <= d <= 0xFF, mult
