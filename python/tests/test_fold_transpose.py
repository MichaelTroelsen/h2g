"""Orderlist transposes above Goattracker's +14, folded into the notes.

Hubbard's players carry transposes of 24, 36 and 48 semitones. Goattracker's
orderlist transpose stops at +14 -- $FF is LOOPSONG, and gorder.c:70 rewrites
a typed $FF back to $FE for exactly that reason -- so those steps used to be
clamped, and every note under one played 10 to 34 semitones flat.

A transpose is a pitch offset on both sides (`CLC / ADC transpose,X` in the
player, `newnote + cptr->trans` at gplay.c:927), so T and (T mod 12) + 12k are
the same interval whichever side of the frequency lookup the octaves are
applied on. The remainder stays in the orderlist and the octaves go into a
copy of the pattern.

Measured end to end, this is the difference between a file playing in the
wrong key and playing in the right one: Deep Strike's voice 0 goes from
-10 semitones at 100% modal share to +0, Kings of the Beach (intro) and Rock
Tells the Tale from -21 to +1, One on One from -9 to +1 -- the +1 being the
separate, still-unexplained residual those files already showed on their
untransposed voices.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import Detection
from h2g.patterns import (GT_END_PATTERN, GT_KEYOFF, GT_NO_NOTE,
                          convert_patterns, pattern_top_note, reindex_tracks,
                          shift_notes)
from h2g.sidfile import HLEN, SidFile
from h2g.tracks import GT_TRANSUP, convert_tracks, fold_transposes

LOAD = 0x1000

# Classic pattern grammar: a status byte of $00 means "no operand, and a note
# byte follows" (_build_raw_pattern), so [$00, note] is one plain event and
# $FF ends the pattern. A decoded note is min(raw, $5C) + $60.
LOW_NOTE = 0x10          # -> $70, six octaves of headroom
TOP_NOTE = 0x5C          # -> $BC, none at all

TRACK_LO, TRACK_HI = 10, 13
PATT_LO, PATT_HI = 16, 18
VOICE_AT = (40, 50, 60)
PATT_AT = (100, 110)


def _addr_of(offset: int) -> int:
    return LOAD + offset - (HLEN - 1)


def _sid(voice0: list[int]) -> SidFile:
    """One subtune, three voices, a two-entry pattern table.

    Pattern 0 sounds a low note (room to rise); pattern 1 sounds the highest
    note the decoder can produce, so nothing can be folded into it.
    """
    data = bytearray(160)
    for v, off in enumerate(VOICE_AT):
        addr = _addr_of(off)
        data[TRACK_LO + v] = addr & 0xFF
        data[TRACK_HI + v] = addr >> 8
    for i, off in enumerate(PATT_AT):
        addr = _addr_of(off)
        data[PATT_LO + i] = addr & 0xFF
        data[PATT_HI + i] = addr >> 8
    data[VOICE_AT[0]:VOICE_AT[0] + len(voice0)] = bytes(voice0)
    for off in VOICE_AT[1:]:
        data[off:off + 2] = bytes([0x00, 0xFF])
    data[PATT_AT[0]:PATT_AT[0] + 3] = bytes([0x00, LOW_NOTE, 0xFF])
    data[PATT_AT[1]:PATT_AT[1] + 3] = bytes([0x00, TOP_NOTE, 0xFF])
    return SidFile(path="synthetic", data=bytes(data), name="", author="",
                   released="", load_addr=LOAD, subtunes=1)


def _det() -> Detection:
    return Detection(track_lo=TRACK_LO, track_hi=TRACK_HI,
                     pattern_lo=PATT_LO, pattern_hi=PATT_HI, pattern_used=1,
                     read_track_version=2, track_voices=3)


def _fold(voice0: list[int]):
    """(tracks, variants) for one orderlist, folded."""
    sid, det = _sid(voice0), _det()
    raw: list = []
    tracks = convert_tracks(sid, det, lambda m: None, raw)
    variants = fold_transposes(sid, det, tracks, raw)
    return tracks, variants


# --- the note-column arithmetic --------------------------------------------

def test_only_pitches_move():
    events = [0x70, 1, 0, 0,
              GT_NO_NOTE, 0, 0, 0,
              GT_KEYOFF, 0, 0, 0,
              GT_END_PATTERN, 0, 0, 0]
    assert shift_notes(events, 24) == [0x88, 1, 0, 0,
                                       GT_NO_NOTE, 0, 0, 0,
                                       GT_KEYOFF, 0, 0, 0,
                                       GT_END_PATTERN, 0, 0, 0]


def test_top_note_ignores_the_markers():
    assert pattern_top_note([GT_NO_NOTE, 0, 0, 0, 0x70, 0, 0, 0,
                             GT_END_PATTERN, 0, 0, 0]) == 0x70
    assert pattern_top_note([GT_NO_NOTE, 0, 0, 0]) == 0


# --- what the clamp threw away ---------------------------------------------

def test_the_true_transpose_is_recorded_beside_the_clamped_byte():
    sid, det = _sid([0x98, 0x00, 0xFF]), _det()     # transpose 24, pattern 0
    raw: list = []
    tracks = convert_tracks(sid, det, lambda m: None, raw)
    assert tracks[0][0] == 0xFE                     # clamped to +14 as before
    assert raw[0] == {0: 24}                        # ...and 24 is still known


def test_convert_tracks_still_takes_three_arguments():
    # The recorder is opt-in: every existing caller passes three arguments and
    # must keep getting exactly the orderlists it got before.
    sid, det = _sid([0x98, 0x00, 0xFF]), _det()
    assert convert_tracks(sid, det, lambda m: None) == \
        convert_tracks(sid, det, lambda m: None, [])


# --- the fold ---------------------------------------------------------------

def test_two_octaves_move_out_of_the_orderlist_and_into_the_pattern():
    tracks, variants = _fold([0x98, 0x00, 0xFF])    # 24 = two octaves exactly
    assert variants == [(0, 2)]
    # 24 mod 12 is 0, so the orderlist says "no transpose" and the whole
    # interval is in the notes. Variant j is entry pattern_used + 1 + j.
    assert tracks[0][:2] == [GT_TRANSUP, 2]


def test_a_remainder_stays_in_the_orderlist():
    tracks, variants = _fold([0x93, 0x00, 0xFF])    # 19 = one octave + 7
    assert variants == [(0, 1)]
    assert tracks[0][:2] == [GT_TRANSUP + 7, 2]
    # The two halves still add up to the transpose the player applies.
    assert (tracks[0][0] - GT_TRANSUP) + 12 * variants[0][1] == 19


def test_a_transpose_the_format_can_express_is_left_alone():
    tracks, variants = _fold([0x8C, 0x00, 0xFF])    # 12, well inside +14
    assert variants == []
    assert tracks[0][:2] == [GT_TRANSUP + 12, 0]


def test_a_pattern_with_no_room_is_left_clamped_rather_than_part_folded():
    # Pattern 1's top note is already $BC. Folding two octaves into it would
    # take it past the note column; folding *one* would leave it 12 semitones
    # flat, which is a different wrong pitch, not a smaller one -- so the step
    # keeps the clamp it had.
    tracks, variants = _fold([0x98, 0x01, 0xFF])
    assert variants == []
    assert tracks[0][:2] == [0xFE, 1]


def test_one_unfoldable_pattern_blocks_its_whole_step():
    # The transpose byte is shared by every pattern the step plays, so it
    # cannot be right for pattern 0 and clamped for pattern 1 at once.
    tracks, variants = _fold([0x98, 0x00, 0x01, 0xFF])
    assert variants == []
    assert tracks[0][:3] == [0xFE, 0, 1]


def test_the_same_pattern_and_octave_costs_one_entry():
    tracks, _ = _fold([0x98, 0x00, 0x00, 0x98, 0x00, 0xFF])
    tracks2, variants = _fold([0x98, 0x00, 0x00, 0x98, 0x00, 0xFF])
    assert variants == [(0, 2)]
    assert tracks == tracks2                       # and the numbering is stable
    # Both steps fold, both reference the one variant; $FF and the restart
    # position that follows it close the orderlist.
    assert tracks[0] == [GT_TRANSUP, 2, 2, GT_TRANSUP, 2, 0xFF, 0x00]


# --- and what the pattern builder does with it ------------------------------

def test_the_variant_is_the_source_two_octaves_up():
    sid, det = _sid([0x98, 0x00, 0xFF]), _det()
    raw: list = []
    tracks = convert_tracks(sid, det, lambda m: None, raw)
    variants = fold_transposes(sid, det, tracks, raw)
    patterns, index = convert_patterns(sid, det, lambda m: None,
                                       variants=variants)
    # Entries 0 and 1 are the table's own; entry 2 is the variant.
    assert len(index) == 3
    src, var = patterns[index[0][0]], patterns[index[2][0]]
    assert src[0] == 0x70 and var[0] == 0x70 + 24
    assert src[4:] == var[4:]                      # nothing else moved
    # The orderlist reaches it: reindexing resolves entry 2 like any other.
    out = reindex_tracks(tracks, index, floor=0xF0)
    assert out[0][:2] == [GT_TRANSUP, index[2][0]]


def test_a_variant_survives_pruning_of_its_source():
    # Nothing plays pattern 0 unshifted, so --prune-patterns drops it -- but
    # the variant is played and has to be decoded anyway.
    sid, det = _sid([0x98, 0x00, 0xFF]), _det()
    raw: list = []
    tracks = convert_tracks(sid, det, lambda m: None, raw)
    variants = fold_transposes(sid, det, tracks, raw)
    patterns, index = convert_patterns(sid, det, lambda m: None,
                                       used={2}, variants=variants)
    assert index[0] == [] and index[1] == []
    assert patterns[index[2][0]][0] == 0x70 + 24
