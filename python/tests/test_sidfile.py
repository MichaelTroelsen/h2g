"""`SidFile.to_address`, and the round trip that makes it worth having.

The inversion of `to_offset` was hand-rolled at nine call sites in five
spellings -- `off - (HLEN - 1) + load_addr`, `off + load_addr - HLEN + 1`,
`load_addr + off - HLEN + 1`, and twice as a `base = load_addr -
to_offset(load_addr)` delta added later. Only one of them knew about the
relocation branch, so I_Ball -- the corpus's only file that copies part of
itself at init -- was resolved wrongly by the other eight whenever it reached
them.

These pin the property the helper exists for rather than its arithmetic: the
formula can be rewritten any way at all as long as `to_offset(to_address(off))`
comes back to `off`, on the relocated file as well as the ordinary ones.
"""
import pathlib
import sys

from corpus import CORPUS  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.sidfile import HLEN, load_sid  # noqa: E402


def test_to_address_round_trips_through_to_offset_on_the_whole_corpus():
    """Every offset of every file, not a sample.

    The branch boundary is the whole question, so a sampled check could miss
    it by landing either side. 95 files at v0.5.461, zero failures.
    """
    if not CORPUS.is_dir():
        return
    checked = files = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        files += 1
        for off in range(HLEN - 1, len(sid.data)):
            addr = sid.to_address(off)
            if not 0 <= addr <= 0xFFFF:
                continue          # an address the C64 cannot name
            checked += 1
            assert sid.to_offset(addr) == off, (path.name, off, hex(addr))
    assert files >= 80, files
    assert checked > 100000, checked


def test_the_relocated_file_is_where_the_plain_formula_is_wrong():
    """I_Ball, and the test is written so it cannot pass vacuously.

    A helper that quietly returned the plain formula would satisfy the round
    trip above on 94 of the 95 files, so this asserts the DIFFERENCE: the
    relocated branch must give a different answer from the plain one, and it
    must give the address the player actually reads.
    """
    if not CORPUS.is_dir():
        return
    sid = load_sid(str(CORPUS / "I_Ball.sid"))
    assert sid.relocation is not None, "I_Ball is the corpus's relocated file"

    off = sid.to_offset(0xE557)          # the effect byte, via the moved region
    plain = off - HLEN + 1 + sid.load_addr
    assert sid.to_address(off) == 0xE557, hex(sid.to_address(off))
    assert plain != 0xE557, (
        "the plain inversion must genuinely differ here, or this proves "
        f"nothing -- got ${plain:04X}")


def test_an_unrelocated_file_is_the_plain_formula_exactly():
    """The other 94 must not pay for the branch.

    `to_offset`'s relocation branch is consulted only where the plain formula
    lands outside the file; this is the same restraint coming back, asserted
    on a file the corpus has always read correctly.
    """
    if not CORPUS.is_dir():
        return
    sid = load_sid(str(CORPUS / "Commando.sid"))
    assert sid.relocation is None
    for off in (HLEN - 1, HLEN + 100, len(sid.data) - 1):
        assert sid.to_address(off) == off - HLEN + 1 + sid.load_addr
