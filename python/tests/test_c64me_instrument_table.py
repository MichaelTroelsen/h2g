"""Commodore 64 Music Examples: the $1D1D table is NOT the wrong engine's.

The file is a five-engine compilation (init $087C dispatches through a
20-entry pointer pair at $08D8/$08EC to play routines $0903, $1119, $1D8B,
$2A23, $33DB), and detection reads exactly one of them -- $1119, which hosts
the file's subtune 1. A task was raised proposing that it had the Powerplay
Hockey defect of § 7.iiiii: orderlists taken from engine $1119 and
instruments from engine $1D8B, to be fixed by taking "the instrument table
nearest the pattern pointers".

**It is not that defect, and the proposed fix has nothing to select.** Three
independent facts, each pinned below:

1.  Engine $1119's own code loads the records. `$11CF LDA $1D1F,X`,
    `$11DE LDA $1D1D,X / STA $D402,Y`, `$11E4 $1D1E`, `$11EA $1D20`,
    `$11F0 $1D21` all sit inside the $1119-$1334 body. The table is 13
    records of 8 bytes, $1D1D-$1D84, abutting engine $1D8B's own entry --
    physically adjacent to it, owned by neither but read by $1119.

2.  There is no candidate to switch to. `_nearest_table` only fires where the
    winning store signature matches more than once; in this file it matches
    once, at $11DE.

3.  There is no room for an instrument table beside the pattern pointers
    either. $143C + 145 = $14CD is the pattern HI table and $14CD + 145 =
    $155E is voice 0's orderlist, which is the triple $1436 holds. The
    verify clause's "$1436/$143C's neighbour" does not exist.

The positive evidence is in the trace rather than in a test, because it needs
siddump: over 60 s of the original's subtune 1, every non-zero ADSR pair
written to $D405/$D406 -- $2524 x115, $1774 x111, $2740 x89, $2720 x56,
$4644 x48, $4764 x28 -- is a record of this table (7, 8, 5, 4, 3, 0). That is
the exact inverse of Powerplay Hockey's signature, where the two sides shared
no pair at all.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.convert import _detect_tables  # noqa: E402
from h2g.detect import _addr16, _nearest_table, _search_all  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

C64ME = "Commodore_64_Music_Examples.sid"

# The one store shape that matches this file, from detect()'s instrument chain.
ACE2_STORE = "BD ?? ?? 99 02 D4 BD ?? ?? 99 03 D4"


def _cpu(sid, off):
    return sid.load_addr + off - sid.to_offset(sid.load_addr)


@needs_corpus
def test_the_instrument_store_matches_once_so_nothing_can_be_nearer():
    sid = load_sid(str(CORPUS / C64ME))
    hits = _search_all(sid.data, ACE2_STORE)
    assert len(hits) == 1
    assert _cpu(sid, hits[0]) == 0x11DE            # inside engine $1119's body
    assert _addr16(sid.data, hits[0] + 1, hits[0] + 2) == 0x1D1D
    _, det = _detect_tables(load_sid(str(CORPUS / C64ME)), lambda *a, **k: None)
    # The § 7.iiiii rule declines: one match is not a choice.
    assert _nearest_table(sid.data, ACE2_STORE, det.pattern_lo, sid) == -1


@needs_corpus
def test_the_table_is_engine_1119s_and_ends_at_engine_1d8bs_entry():
    sid, det = _detect_tables(load_sid(str(CORPUS / C64ME)),
                              lambda *a, **k: None)
    assert _cpu(sid, det.instr_start) == 0x1D1D
    assert det.instr_stride == 8
    assert det.instr_used == 13
    # 13 * 8 = 104: $1D1D..$1D84 inclusive, and $1D85 is already engine
    # $1D8B's tail -- `BIT $FFFB / JMP $EA31`, with $1D88 the guard byte
    # init pokes an RTS into.
    o = sid.to_offset(0x1D85)
    assert sid.data[o:o + 6] == bytes((0x2C, 0xFB, 0xFF, 0x4C, 0x31, 0xEA))


@needs_corpus
def test_the_pattern_pointers_have_no_neighbouring_table_to_take():
    sid, det = _detect_tables(load_sid(str(CORPUS / C64ME)),
                              lambda *a, **k: None)
    assert _cpu(sid, det.track_lo) == 0x1436
    assert _cpu(sid, det.track_hi) == 0x1439
    assert _cpu(sid, det.pattern_lo) == 0x143C
    assert _cpu(sid, det.pattern_hi) == 0x14CD
    assert det.pattern_used == 0x90
    # 145 bytes each: LO $143C..$14CC, HI $14CD..$155D. The byte after them
    # is voice 0's orderlist, which is what the track triple names.
    assert det.pattern_hi - det.pattern_lo == 145
    lo = sid.data[det.track_lo:det.track_lo + 3]
    hi = sid.data[det.track_hi:det.track_hi + 3]
    assert [h * 256 + l for l, h in zip(lo, hi)] == [0x155E, 0x1637, 0x1710]
    assert 0x14CD + 145 == 0x155E
