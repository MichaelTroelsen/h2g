"""The ILV players' `$FD nn` orderlist transpose, and the floor that admits it.

Six corpus files (Go_Go_Dash, Lakers_vs_Celtics, Lion_Heart, Pacific_Coast,
Radio_ACE, Sun_Never_Shines) read version 0's orderlist with `$FD nn` as a
two-byte per-voice transpose that continues the list (Lion_Heart $110E:
`CMP #$FF / BEQ stop / CMP #$FD / BNE pattern / INY / LDA (ptr),Y /
STA $1ADA,X`). `_build_track` lifted it into the orderlist as a Goattracker
transpose byte -- and `command_floor(0)` is $FF, under which `reindex_tracks`
dropped every one as a dangling pattern reference: 80 bytes emitted across
the six at v0.5.487 (3 / 28 / 11 / 32 / 3 / 3) and none in any .sng.

Two readings fixed together, because the second only shows once the first
lets the bytes through:

- the floor is keyed on `Detection.track_fd_transpose` -- the flag that
  makes `_build_track` emit the byte -- and sits at GT_TRANSPOSE_DOWN;
- the operand is SIGNED: `$1274 CLC / ADC $1ADA,X` adds it 8-bit to the
  note index, so `$FE` is -2 and `$FB` is -5 (Lakers_vs_Celtics and
  Pacific_Coast both carry them). `& $7F` had read them as +126 and +123
  and clamped both to +14 -- which, once admitted, would have moved those
  voices 16 semitones the wrong way.

Measured at v0.5.487 on the six at -t 180 under presets.json: melody
82 -> 94% (Pacific_Coast), 82 -> 91% (Lakers_vs_Celtics), 90 -> 91%
(Lion_Heart); the other three carry only `$FD $00` -- a transpose of zero
at the head of each voice -- so their bytes change and no column can see
it. The corpus byte-hash moves exactly the six.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.patterns import (GT_ORDER_RESTART, GT_TRANSPOSE_DOWN,  # noqa: E402
                          GT_TRANSPOSE_UP, command_floor, reindex_tracks)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import (GT_MIN_TRANSPOSE, _build_track,  # noqa: E402
                        _transpose_byte, convert_tracks)

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
LAKERS = CORPUS / "Lakers_vs_Celtics.sid"
FD_FILES = {"Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart", "Pacific_Coast",
            "Radio_ACE", "Sun_Never_Shines"}


def _quiet(*_a, **_k):
    pass


def _transposes(track):
    """Transpose bytes of one orderlist, skipping the restart operand."""
    out = []
    skip = False
    for b in track:
        if skip:
            skip = False
        elif b == GT_ORDER_RESTART:
            skip = True
        elif GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
            out.append(b)
    return out


# --- the floor ---------------------------------------------------------------

def test_the_fd_transpose_flag_moves_version_0s_floor_to_the_transpose_range():
    """Version 0 alone keeps $FF; with the flag the floor is Goattracker's
    own transpose range, the same place version 11 put it."""
    assert command_floor(0) == GT_ORDER_RESTART
    assert command_floor(0, fd_transpose=True) == GT_TRANSPOSE_DOWN
    assert command_floor(0, fd_transpose=False) == GT_ORDER_RESTART
    # A dialect already below the range is not raised by the flag.
    assert command_floor(11, fd_transpose=True) == GT_TRANSPOSE_DOWN
    assert command_floor(2, fd_transpose=True) == GT_TRANSPOSE_DOWN
    assert command_floor(2) == GT_TRANSPOSE_UP


def test_reindex_keeps_the_transpose_only_under_the_flagged_floor():
    """The defect, in miniature: the same track through both floors."""
    track = [0xF0, 0x01, 0xEE, 0x02, 0xFF, 0x00]
    index = [[0], [1], [2]]
    assert reindex_tracks([track], index, floor=command_floor(0)) == \
        [[0x01, 0x02, 0xFF, 0x00]]
    assert reindex_tracks([track], index,
                          floor=command_floor(0, fd_transpose=True)) == \
        [[0xF0, 0x01, 0xEE, 0x02, 0xFF, 0x00]]


# --- the operand -------------------------------------------------------------

def test_the_fd_operand_is_signed():
    """`$FD $FE` is -2 and lands at $EE; `$FD $05` is +5 at $F5. The map
    fold_transposes reads records the signed value, not the byte."""
    data = bytes([0xFD, 0x00, 0x01, 0xFD, 0xFE, 0x02, 0xFD, 0x05, 0x03, 0xFF])
    seen: dict = {}
    got = _build_track(data, 0, 0, fd_transpose=True, transposes=seen)
    assert got == [0xF0, 0x01, 0xEE, 0x02, 0xF5, 0x03, 0xFF, 0x00], got
    assert seen == {0: 0, 2: -2, 4: 5}, seen
    # Without the flag the same bytes are version 0's: $FD is a pattern
    # number, and the `$FE` operand is "tune ended" (see legalise_restarts).
    assert _build_track(data, 0, 0) == [0xFD, 0x00, 0x01, 0xFD, 0xFF, 0xFD]


def test_consecutive_fd_transposes_collapse_across_the_whole_range():
    """The player assigns, so `$FD $FE / $FD $03` keeps +3 -- and the
    collapse has to recognise a NEGATIVE predecessor ($E0-$EF), which the
    old `>= $F0` test would have appended a second byte after."""
    data = bytes([0xFD, 0xFE, 0xFD, 0x03, 0x01, 0xFF])
    got = _build_track(data, 0, 0, fd_transpose=True)
    assert got == [0xF3, 0x01, 0xFF, 0x00], got


def test_transpose_byte_clamps_both_ends():
    assert _transpose_byte(-2) == 0xEE
    assert _transpose_byte(GT_MIN_TRANSPOSE) == GT_TRANSPOSE_DOWN
    # Below -16 the byte would be a REPEAT command ($D0-$DF).
    assert _transpose_byte(-17) == GT_TRANSPOSE_DOWN
    assert _transpose_byte(-100) == GT_TRANSPOSE_DOWN
    assert _transpose_byte(0) == GT_TRANSPOSE_UP
    assert _transpose_byte(14) == 0xFE
    assert _transpose_byte(21) == 0xFE


# --- the corpus --------------------------------------------------------------

@needs_corpus
def test_exactly_the_six_ilv_files_carry_the_fd_transpose():
    found = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _sid, det = _detect_tables(load_sid(str(path)), _quiet)
        except Exception:                              # noqa: BLE001
            continue
        if det.track_fd_transpose:
            assert det.read_track_version == 0, (path.stem, det.read_track_version)
            found.add(path.stem)
    assert found == FD_FILES, sorted(found)


@needs_corpus
def test_lakers_raw_orderlist_carries_signed_transposes():
    """Voice 0 opens `FD 00 / 0B / 05 / FD FE / 0B / FD 00 / 01` in the file:
    transpose 0, two patterns, -2, a pattern, 0, and on."""
    sid = load_sid(str(LAKERS))
    sid, det = _detect_tables(sid, _quiet)
    tracks = convert_tracks(sid, det, _quiet)
    assert tracks[0][:7] == [0xF0, 0x0B, 0x05, 0xEE, 0x0B, 0xF0, 0x01], tracks[0]
    assert sum(len(_transposes(t)) for t in tracks) == 28
    # Voice 1's `FD FB` is -5: the byte is $EB, not the +14 `& $7F` gave it.
    assert 0xEB in _transposes(tracks[1]), tracks[1]


@needs_corpus
def test_lakers_final_sng_orderlists_carry_every_transpose():
    """Read with songview, never an intermediate: every one of the 28 bytes
    convert_tracks emits survives reindex, prune, dedup and packing, and
    voice 0's sequence of them is the file's own."""
    import songview
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    import fidelity as F
    blob = convert(str(LAKERS), log=_quiet, **F._preset_opts(doc, LAKERS.name))
    song = songview.parse_sng(blob)
    got = [_transposes(t) for t in song.tracks[:3]]
    assert got[0] == [0xF0, 0xEE, 0xF0, 0xF2, 0xF0, 0xF2, 0xF0, 0xF2, 0xF0], got[0]
    assert sum(len(g) for g in got) == 28, [len(g) for g in got]
    assert 0xEB in got[1], got[1]


@needs_corpus
def test_pacific_coast_folds_its_plus_21_through_the_flagged_floor():
    """Voice 1 opens `FD 15`: +21, past Goattracker's +14. fold_transposes
    walks the raw orderlist under `command_floor(.., fd_transpose)` -- under
    version 0's $FF it finds no transpose step at all and the byte ships
    clamped at $FE. Folded, the step reads $F9 (21 mod 12) and the two
    patterns it governs play through octave variants. Presets: fold_transpose
    is in the always block."""
    import songview
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    import fidelity as F
    path = CORPUS / "Pacific_Coast.sid"
    blob = convert(str(path), log=_quiet, **F._preset_opts(doc, path.name))
    song = songview.parse_sng(blob)
    got = [_transposes(t) for t in song.tracks[:3]]
    assert got[1][0] == 0xF9, got[1]
    assert 0xFE not in got[1], got[1]
    assert got[0][:4] == [0xF0, 0xF5, 0xEB, 0xF2], got[0]
    assert sum(len(g) for g in got) == 32, [len(g) for g in got]
