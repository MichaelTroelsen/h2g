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

Their pattern data uses a FOURTH grammar, `pattern_dialect "ilv"`: bit 7 SET
is a command, bit 7 CLEAR a note (`$116C LDA (patt),Y / BMI`), where the
classic reader takes bit 7 as "an operand follows". Read classically the
patterns came out at 945-5927 rows with 28 of 114 undecodable and the
conversion aborted on the pattern count; read under their own grammar every
pattern decodes, the rows land on bar lengths and nothing clamps. Both halves
are asserted below -- the tables first, then the grammar.
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


# --------------------------------------------------------------------------
# The pattern grammar. Bit 7 SET is a command, bit 7 CLEAR a note -- inverted
# from the classic reader, which takes bit 7 as "an operand follows".
# --------------------------------------------------------------------------
from h2g.patterns import (_build_raw_pattern_ilv, GT_END_PATTERN,  # noqa: E402
                          GT_KEYOFF, GT_NO_NOTE, ILV_COMMAND_OPERANDS)


def _ilv(*by, instr_base=2):
    return _build_raw_pattern_ilv(bytes([0, 0] + list(by)), 2,
                                  instr_base=instr_base)


def test_a_note_emits_one_row_plus_its_wait_in_holds():
    """`$C0-$FF` sets the wait and emits NO row of its own; the sequencer is
    DEC/BMI, so an event lasts wait+1 rows."""
    got = _ilv(0xC3, 20, 0x81)
    assert got[0:4] == [0x60 + 20, 0, 0, 0]
    assert got[4:16] == [GT_NO_NOTE, 0, 0, 0] * 3
    assert got[16:20] == [GT_END_PATTERN, 0, 0, 0]


def test_a_wait_of_zero_is_a_single_row():
    assert _ilv(0xC0, 20, 0x81)[:8] == [0x60 + 20, 0, 0, 0, GT_END_PATTERN, 0, 0, 0]


def test_the_wait_persists_until_the_next_duration_byte():
    got = _ilv(0xC1, 20, 21, 0x81)
    assert got[0:4] == [0x60 + 20, 0, 0, 0]
    assert got[4:8] == [GT_NO_NOTE, 0, 0, 0]
    assert got[8:12] == [0x60 + 21, 0, 0, 0]      # same wait, not reset
    assert got[12:16] == [GT_NO_NOTE, 0, 0, 0]


def test_60_is_a_rest_and_not_a_note():
    """$60 is one past the frequency table's 96 entries; the player tests it
    at $1264 and branches to a path that sounds nothing."""
    got = _ilv(0xC0, 0x60, 0x81)
    assert got[0:4] == [GT_KEYOFF, 0, 0, 0]


def test_80_sets_the_instrument_and_it_persists():
    got = _ilv(0x80, 3, 0xC0, 20, 21, 0x81, instr_base=2)
    assert got[0:4] == [0x60 + 20, 5, 0, 0]       # 3 + instr_base
    assert got[4:8] == [0x60 + 21, 5, 0, 0]


def test_the_instrument_base_reaches_the_row():
    assert _ilv(0x80, 3, 0xC0, 20, 0x81, instr_base=1)[1] == 4


def test_every_command_consumes_exactly_its_operands():
    """The table is the point: one wrong count desynchronises everything
    after it, and the note that follows each command here would come out as
    an operand byte instead."""
    for cmd, n in sorted(ILV_COMMAND_OPERANDS.items()):
        body = [cmd] + [0x00] * n + [0xC0, 20, 0x81]
        got = _ilv(*body)
        assert got is not None, f"${cmd:02X} failed to decode"
        # $80's operand here is 0x00, so its instrument is 0 + instr_base.
        assert got[0:4] == [0x60 + 20, 2 if cmd == 0x80 else 0, 0, 0], \
            f"${cmd:02X} with {n} operand(s) left the stream out of step"


def test_an_unknown_command_refuses_rather_than_skipping():
    """The player's dispatch falls through `$11AE BNE $116C` with no INY and
    would spin, so such a byte means the decode has lost the stream. Skipping
    it would invent music."""
    assert _ilv(0x85, 0xC0, 20, 0x81) is None


def test_81_ends_the_pattern():
    got = _ilv(0xC0, 20, 0x81, 20, 20, 20)
    assert got[-4:] == [GT_END_PATTERN, 0, 0, 0]
    assert len(got) == 8


def test_a_stream_that_runs_off_the_end_returns_none():
    assert _build_raw_pattern_ilv(bytes([0, 0, 0xC0, 20]), 2) is None


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_the_six_convert(stem):
    from h2g.convert import convert
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None)
    assert len(blob) > 1000


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_every_pattern_decodes_and_the_music_is_in_range(stem):
    """The check that says the grammar is RIGHT rather than merely accepted.
    Under the classic reading these same patterns gave 945-5927 rows with 28
    of 114 undecodable and constant clamping at GT_LASTNOTE; under this one
    every pattern decodes, the rows land on bar lengths, and nothing clamps."""
    from h2g.patterns import decode_entry, GT_FIRSTNOTE, GT_LASTNOTE
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    det = detect(sid, lambda m: None)
    rows, clamped, notes = [], 0, 0
    for i in range(det.pattern_used + 1):
        ev = decode_entry(sid, det, i)
        assert ev is not None, f"pattern {i} did not decode"
        rows.append(len(ev) // 4)
        for k in range(0, len(ev), 4):
            if GT_FIRSTNOTE <= ev[k] <= GT_LASTNOTE:
                notes += 1
                clamped += ev[k] == GT_LASTNOTE
    assert notes > 100, "a whole file of patterns sounding almost nothing"
    assert clamped == 0, "notes are hitting the GT ceiling; the reading is off"
    assert max(rows) <= 200, f"{max(rows)} rows is not a pattern, it is a runaway"
