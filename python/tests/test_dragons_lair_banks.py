"""Dragons_Lair_Part_II: which pattern bank each PSID subtune plays on.

`dragons-lair-unmatched-subtunes`.  The `.sid`'s init at $AF00 does two things
a static rip cannot see.  PSID 0, 1 and 9 jump straight to song 9, 7 and 8.
PSID 2..8 pick song `$AF88[n-2]` and, AFTER the player's init returns, copy the
two pages at `$AF80[n-2]` / +1 over $BE00/$BF00 (self-modified operands at
$AF3D/$AF43).  The file as shipped holds the bank of PSID 5 in that window, so
the converter's song k reads song k's tracks against song 2's patterns.

Measured at 0.5.533 (pair of PSID n against ours k, window patched with the
bank init would have copied, -t 60): ours 1 vs PSID 2 100% (was 3%), ours 6 vs
PSID 3 100% (7%), ours 4 vs PSID 4 99% (5%), ours 3 vs PSID 6 98% (4%), ours 0
vs PSID 7 100% (10%), ours 5 vs PSID 8 100% (2%); ours 2 vs PSID 5 95% either
way.  These tests pin the facts that explanation rests on -- the init's table
and the static window -- not the converter's output, so fixing the converter
does not break them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

NAME = "Dragons_Lair_Part_II.sid"

# PSID subtune -> (song the player is initialised with, first page of the bank
# init copies into $BE00/$BF00).  PSID 0, 1, 9 copy nothing.
EXPECTED = {
    2: (1, 0xB0), 3: (6, 0xB2), 4: (4, 0xB4), 5: (2, 0xB6),
    6: (3, 0xB8), 7: (0, 0xBA), 8: (5, 0xBC),
}
DIRECT = {0: 9, 1: 7, 9: 8}


def bank_table(sid) -> tuple[dict[int, tuple[int, int]], dict[int, int]]:
    """Read the remap out of the init routine's own bytes."""
    d = sid.data
    at = sid.to_offset

    def u8(a: int) -> int:
        return d[at(a)]

    # the dispatch shape: CMP #n / BNE / LDA #song / JMP $C00F
    direct = {}
    for a, n in ((0xAF00, 0), (0xAF09, 9), (0xAF12, 1)):
        assert (u8(a), u8(a + 1)) == (0xC9, n)
        assert u8(a + 4) == 0xA9
        direct[n] = u8(a + 5)
    # SEC / SBC #2 / TAX / LDA $AF80,X / STA $AF3D ... LDA $AF88,X / JSR $C00F
    assert bytes(d[at(0xAF23):at(0xAF23) + 5]) == bytes([0x38, 0xE9, 0x02, 0xAA, 0xBD])
    assert (u8(0xAF28), u8(0xAF29)) == (0x80, 0xAF)
    assert (u8(0xAF33), u8(0xAF34), u8(0xAF35)) == (0xBD, 0x88, 0xAF)
    # the copy loop: LDA $xx00,X / STA $BE00,X / LDA $xx00,X / STA $BF00,X
    assert (u8(0xAF3B), u8(0xAF3E), u8(0xAF41), u8(0xAF44)) == (0xBD, 0x9D, 0xBD, 0x9D)
    assert (u8(0xAF3F), u8(0xAF40)) == (0x00, 0xBE)
    assert (u8(0xAF45), u8(0xAF46)) == (0x00, 0xBF)
    table = {n: (u8(0xAF88 + n - 2), u8(0xAF80 + n - 2)) for n in range(2, 9)}
    return table, direct


@needs_corpus
def test_init_table_maps_each_psid_subtune_to_a_song_and_a_bank():
    table, direct = bank_table(load_sid(CORPUS / NAME))
    assert direct == DIRECT
    assert table == EXPECTED
    # every song 0..9 is reached by exactly one PSID subtune
    songs = sorted([s for s, _ in table.values()] + list(direct.values()))
    assert songs == list(range(10))


@needs_corpus
def test_the_static_window_is_psid_5s_bank_and_no_other():
    """Why ours 2 matches PSID 5 and ours 0/1/3/4/5/6 do not match theirs."""
    sid = load_sid(CORPUS / NAME)
    d, at = sid.data, sid.to_offset

    def page(a: int) -> bytes:
        return bytes(d[at(a):at(a) + 256])

    window = page(0xBE00) + page(0xBF00)
    banks = {first: page(first << 8) + page((first + 1) << 8)
             for _, first in EXPECTED.values()}
    same = sorted(hex(first) for first, b in banks.items() if b == window)
    assert same == ["0xb6"], same
    # ... and that is PSID 5, i.e. song 2
    assert EXPECTED[5] == (2, 0xB6)


@needs_corpus
def test_the_banks_differ_from_each_other():
    """If two banks were equal the explanation above would not need seven."""
    sid = load_sid(CORPUS / NAME)
    d, at = sid.data, sid.to_offset
    blobs = {bytes(d[at(f << 8):at(f << 8) + 512]) for _, f in EXPECTED.values()}
    assert len(blobs) == len(EXPECTED)
