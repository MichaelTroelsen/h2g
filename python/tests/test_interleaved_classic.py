"""The interleaved-table engine read under the classic grammar.

Six corpus files -- Go_Go_Dash, Lion_Heart, Pacific_Coast, Radio_ACE,
Sun_Never_Shines and Lakers_vs_Celtics -- share one player build whose track
and pattern tables are INTERLEAVED (lo/hi pairs, `ASL A / TAY` before the
load) and whose authored track table is written into a zero-filled runtime
block by the init routine. `detect()` was finding their instrument table,
frequency table, `pulse_bounds` and `pitch_seq` all along; only
`pattern_lo/hi` and `track_lo/hi` were missing, and the file refused with
NO HUBBARD PLAYER DETECTED.

What is pinned here is the part that can rot silently, in both directions:

* the six are recognised, with the table shape the player actually uses;
* the NINE files that share the same two signatures and already convert
  through `_detect_digi` are untouched -- that overlap is the whole reason
  this chain is consulted last, and a future edit that promoted it would
  overwrite nine working files with an interleaved reading of tables that are
  not interleaved.

They do NOT convert yet: their pattern data uses a third grammar (bit 7 SET
is a command, bit 7 CLEAR a note -- `$116C LDA (patt),Y / BMI`), where the
classic grammar reads bit 7 as "an operand follows". Read classically the
patterns decode to 945-5927 rows and 28 of 114 are undecodable, so the
conversion aborts on the pattern count. That is a separate piece of work and
this file asserts the tables only.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus            # noqa: E402
from h2g.detect import detect                      # noqa: E402
from h2g.sidfile import load_sid                    # noqa: E402

# The six, and the address their init routine copies the authored track table
# FROM -- `runtime + DIGI_RUNTIME_TABLE_LEN`, read out of the copy loop.
INTERLEAVED = {
    "Go_Go_Dash": 0x1B43,
    "Lion_Heart": 0x1B43,
    "Pacific_Coast": 0x1B43,
    "Radio_ACE": 0x1B43,
    "Sun_Never_Shines": 0x1B43,
    "Lakers_vs_Celtics": 0x1B6B,      # the same build at its own addresses
}

# Files that match DIGI_TRACKS and DIGI_PATTERN *and already convert*, through
# `_detect_digi`. The new chain must not reach any of them.
DIGI_FILES = [
    "After_8", "Kings_of_the_Beach_intro", "Mr_Meaner", "Off_the_Cuff",
    "One_on_One_Jordan_vs_Bird", "Powerplay_Hockey_USA_vs_USSR",
    "Pygmies_Revenge", "Rikky", "Rock_Tells_the_Tale",
]


def _det(stem):
    return detect(load_sid(str(CORPUS / f"{stem}.sid")), lambda m: None)


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_the_interleaved_tables_are_found(stem):
    det = _det(stem)
    assert det.table_stride == 2, "lo/hi are neighbours, so entries are 2 apart"
    assert det.pattern_hi == det.pattern_lo + 1
    assert det.track_hi == det.track_lo + 1
    assert det.track_lo > 0 and det.pattern_lo > 0
    assert det.can_convert


@needs_corpus
@pytest.mark.parametrize("stem,addr", sorted(INTERLEAVED.items()))
def test_the_track_table_is_the_authored_one_not_the_runtime_copy(stem, addr):
    """The runtime table the player reads is zero on disk; the authored table
    sits eight bytes past it and is copied there at init. Reading the runtime
    block would yield three null pointers."""
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    det = detect(sid, lambda m: None)
    assert det.track_lo == sid.to_offset(addr)
    runtime = sid.to_offset(addr - 8)
    assert all(sid.data[runtime + k] == 0 for k in range(8)), \
        "the runtime block must be zero-filled, or this is a different build"


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_three_voices_and_one_subtune(stem):
    """`CPY #$04` in the copy loop counts POINTERS COPIED, not voices. The
    play loop's own bound cell holds 2, so X runs 2..0, and the per-voice SID
    offset table is [0, 7, 14, 0] -- three voices and a dead fourth entry."""
    det = _det(stem)
    assert det.track_voices == 3
    assert det.subtunes_available == 1


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_the_orderlists_reference_exactly_the_patterns_that_exist(stem):
    """The check that says the tables are read right rather than merely read:
    `pattern_used` is derived by walking the table until an entry stops
    resolving, and the orderlists are decoded independently of it. The highest
    pattern any voice names must be exactly the last one the walk found -- one
    off in either direction would mean the walk or the orderlist is wrong."""
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    det = detect(sid, lambda m: None)
    from h2g.tracks import convert_tracks
    refs = {b for track in convert_tracks(sid, det, lambda m: None)
            for b in track if b < 0xD0}
    assert refs, "every voice named no pattern at all"
    assert max(refs) == det.pattern_used


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_the_track_reader_ends_on_ff_and_transposes_on_fd(stem):
    det = _det(stem)
    assert det.read_track_version == 0
    assert det.track_fd_transpose is True


@needs_corpus
@pytest.mark.parametrize("stem", DIGI_FILES)
def test_the_digi_files_that_share_both_signatures_are_untouched(stem):
    """The nine-file overlap this chain is ordered last to protect. They must
    still be recognised as the digi engine, with its four voices and its own
    grammar -- not re-read by the classic chain."""
    det = _det(stem)
    assert det.pattern_dialect == "digi"
    assert det.track_voices == 4
    assert det.track_fd_transpose is False
    assert det.can_convert
