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
from h2g.detect import detect, WAVEFORMS           # noqa: E402
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
                          GT_KEYOFF, GT_NO_NOTE, ILV_COMMAND_OPERANDS,
                          ILV_SLIDE)


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


# --------------------------------------------------------------------------
# Command $82 is a PORTAMENTO -- the only one of the seven effect commands
# translated. See ILV_SLIDE in patterns.py for the routine it is read out of;
# what matters here is the three properties that decide the emission, each of
# which would be silently wrong in a different way.
# --------------------------------------------------------------------------


def _slid(*by, instr_base=2, steps=None):
    return _build_raw_pattern_ilv(bytes([0, 0] + list(by)), 2,
                                  instr_base=instr_base, slides=True,
                                  steps=steps)


def test_the_slide_operands_are_high_byte_first_and_the_pair_is_signed():
    """`$1214 STA $1AB5,X` takes the FIRST operand and `$121A STA $1AB2,X` the
    second, and $1668's add is one CLC/ADC pair with no direction test -- so a
    high byte at or above $80 is a downward slide of the two's complement
    magnitude, not an upward one of $FFxx."""
    up = _slid(ILV_SLIDE, 0x01, 0x00, 0xC0, 20, 0x81)
    assert up[0:4] == [0x60 + 20, 0, 1, 0x0100 // 4]        # CMD_PORTAUP
    down = _slid(ILV_SLIDE, 0xFF, 0x00, 0xC0, 20, 0x81)
    assert down[0:4] == [0x60 + 20, 0, 2, 0x0100 // 4]      # CMD_PORTADOWN
    # ...and the halves are not interchangeable: $00 $01 is a step of ONE.
    assert _slid(ILV_SLIDE, 0x00, 0x01, 0xC0, 20, 0x81)[2:4] == [1, 0]


def test_the_slide_is_repeated_on_every_hold_row_of_its_own_event():
    """The player adds the step once a FRAME for as long as the event lasts,
    and a Goattracker command runs only on the row it appears on -- so a
    continuous effect has to be written on all wait+1 rows. Emitting it once
    would make a slide of any length last a single row."""
    got = _slid(0xC2, ILV_SLIDE, 0x01, 0x00, 20, 0x81)
    assert got[0:4] == [0x60 + 20, 0, 1, 0x40]
    assert got[4:8] == [GT_NO_NOTE, 0, 1, 0x40]
    assert got[8:12] == [GT_NO_NOTE, 0, 1, 0x40]
    assert got[12:16] == [GT_END_PATTERN, 0, 0, 0]


def test_the_slide_dies_with_its_event_and_needs_no_stop_command():
    """`$1147-$114F` zeroes the step, the accumulator and the effect flags at
    the top of EVERY pattern-byte fetch, before the command loop runs. So the
    next event starts from no slide -- and because a Goattracker command does
    not persist past its row, leaving the following rows blank reproduces that
    exactly. A version that held the command would slide the whole pattern."""
    got = _slid(0xC1, ILV_SLIDE, 0x01, 0x00, 20, 21, 0x81)
    assert got[2:4] == [1, 0x40] and got[6:8] == [1, 0x40]
    assert got[8:12] == [0x60 + 21, 0, 0, 0]
    assert got[12:16] == [GT_NO_NOTE, 0, 0, 0]


def test_a_rest_takes_the_slide_too_because_the_player_keeps_accumulating():
    """$60 branches to a path that sounds nothing, but $1663's add is in the
    frame routine and runs regardless, so the accumulator moves under a gated
    -off voice. Inaudible either way; this is the reading that matches."""
    got = _slid(ILV_SLIDE, 0x01, 0x00, 0xC0, 0x60, 0x81)
    assert got[0:4] == [GT_KEYOFF, 0, 1, 0x40]


def test_without_slides_the_command_is_consumed_and_no_column_is_written():
    """Off by default, exactly like every other decoder's slide reading -- and
    the operand count still has to be exact or the note after it would be
    decoded as an operand."""
    plain = _build_raw_pattern_ilv(
        bytes([0, 0, ILV_SLIDE, 0x01, 0x00, 0xC0, 20, 0x81]), 2)
    assert plain[0:4] == [0x60 + 20, 0, 0, 0]
    assert plain[4:8] == [GT_END_PATTERN, 0, 0, 0]


def test_the_step_is_collected_at_full_width_when_a_speed_table_is_offered():
    """`min(step // 4, $FF)` saturates every step above 1020 and rounds every
    step below 4 to nothing, so a GTS5 file carries an INDEX into its own list
    of distinct steps instead. Both halves are asserted: the list gets the
    16-bit value, the column gets its 1-based index."""
    steps = []
    got = _slid(ILV_SLIDE, 0x08, 0x00, 0xC0, 20, 0x81, steps=steps)
    assert steps == [0x0800]
    assert got[2:4] == [1, 1]
    # a second, distinct step appends rather than replacing
    got = _slid(ILV_SLIDE, 0x00, 0x02, 0xC0, 20, 0x81, steps=steps)
    assert steps == [0x0800, 0x0002]
    assert got[2:4] == [1, 2]


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_every_one_of_the_six_actually_emits_slides(stem):
    """The reach half. All six read `slides 0/nnn` and `bend 0.00x` before
    this command was decoded -- right notes, no pitch movement anywhere -- so
    a file that emits none has lost the command rather than not needing it."""
    from h2g.convert import convert
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import songview
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                   fmt="gts5", slides=True)
    song = songview.parse_sng(blob)
    slides = sum(1 for p in song.patterns
                 for j in range(0, len(p), 4) if p[j + 2] in (1, 2))
    assert slides > 0, f"{stem} emitted no portamento at all"


# --------------------------------------------------------------------------
# A KNOWN DEFECT, pinned so that fixing it announces itself.
# --------------------------------------------------------------------------


def _instrument_recount(sid, det, stride):
    """`detect`'s own instrument walk, at whatever stride is passed."""
    d = sid.data
    j, n = det.instr_start + 2, 0
    while True:
        if j < 0 or j >= len(d) or d[j] not in WAVEFORMS:
            return n
        j += stride
        if j >= len(d):
            return n
        n += 1


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INTERLEAVED))
def test_the_instrument_count_is_taken_at_the_dialects_own_stride(stem):
    """The count and the record reading must use the same stride.

    `_detect_interleaved_classic` is the rescue chain and is consulted LAST,
    long after the instrument walk -- so until `detect()` re-took the count
    where the stride settles, `instr_used` was a stride-8 count of a stride-16
    table on every one of these six files. It was not cosmetic: a Goattracker
    instrument number past the end of the table sounds NOTHING, and 1768 of
    Go_Go_Dash's 2456 notes (72%) named one, which was the whole of its 36%
    melody. Over-counting is the other half -- Lion_Heart read 27 where 17
    records exist, so ten instruments were written out of whatever follows the
    table.

    **This was a strict xfail until the re-take landed**, and the recount here
    is deliberately its OWN walk rather than a call to
    `detect._count_instruments`: sharing the shipped helper would make the
    assertion tautological, and the whole value of this test is that a second
    reader agrees.

    Censused at 64c795b: of the 15 corpus files with `instr_stride == 16`,
    exactly these six disagreed with their own recount; the nine digi files,
    whose chain sets the stride before the walk, always agreed.
    """
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    det = detect(sid, lambda m: None)
    assert det.instr_stride == 16
    assert det.instr_used == _instrument_recount(sid, det, det.instr_stride)
