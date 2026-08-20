"""Phantom pattern-table entries, and the validation pass that rejects them.

The `hi - lo - 1` entry count (H2G-CONVERSION-METHOD.md §4.2) is
table-adjacency arithmetic and over-counts: a cell in the gap that was never
an authored entry decodes whatever its bytes happen to address. Last V8's
entry $1C points one byte past the last real pattern's terminator, into the
player's own track-selector routine -- and the garbage it decodes to fed the
packed file's *speed table*, whose gt2reloc re-encoding is global, which is
how an entry played by no real subtune dragged the measured melody of
subtune 0 from 71% to 3% the moment the (correct) bit-6 decode changed how
the garbage read.

phantom_patterns judges entries on the player's own terms -- decode runs off
the file, or the decode's bytes overlap the pointer tables or code that
detection matched a signature in -- never on how the decode "looks".
Unreferenced-ness alone is --prune-patterns' business, and orderlists naming
entries beyond the table (dangling references) are a separate phenomenon
this pass deliberately leaves alone.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import Detection, detect
from h2g.patterns import (ERROR_PATTERN, convert_patterns, phantom_patterns)
from h2g.sidfile import HLEN, SidFile, load_sid
from h2g.tracks import convert_tracks, track_table_extent

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = pathlib.Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
needs_corpus = pytest.mark.skipif(not CORPUS.is_dir(),
                                  reason="corpus not available")

LOAD = 0x1000


def _addr_of(offset: int) -> int:
    """The C64 address whose SidFile.to_offset is `offset`."""
    return LOAD + offset - (HLEN - 1)


def _fake_sid() -> SidFile:
    """Four-entry pattern table: one real pattern, three phantoms.

    entry 0 -> offset 30: a real two-row pattern.
    entry 1 -> offset 40: decodes fine, but over bytes a signature matched.
    entry 2 -> beyond the file.
    entry 3 -> offset 90: all zeroes to EOF, no terminator.
    """
    data = bytearray(96)
    targets = [30, 40, 200, 90]
    for i, off in enumerate(targets):
        addr = _addr_of(off)
        data[10 + i] = addr & 0xFF          # lo table at offset 10
        data[14 + i] = addr >> 8            # hi table at offset 14
    data[30:33] = bytes([0x00, 0x00, 0xFF])
    data[40:43] = bytes([0x00, 0x00, 0xFF])
    return SidFile(path="synthetic", data=bytes(data), name="", author="",
                   released="", load_addr=LOAD, subtunes=1)


def _fake_det() -> Detection:
    return Detection(track_lo=1, track_hi=2,
                     pattern_lo=10, pattern_hi=14, pattern_used=3,
                     read_track_version=0,
                     code_spans=[(41, 8)])   # "player code" inside entry 1


def test_each_reason_fires_and_the_real_pattern_does_not():
    ph = phantom_patterns(_fake_sid(), _fake_det())
    assert 0 not in ph
    assert "player code" in ph[1]
    assert ph[2] == "address outside the file"
    assert ph[3] == "decode runs off the end of the file"


def test_pointer_table_overlap_is_phantom():
    # An entry aimed at its own pointer table: those bytes are provably the
    # table, not pattern data.
    sid = _fake_sid()
    det = _fake_det()
    data = bytearray(sid.data)
    addr = _addr_of(11)
    data[10 + 1], data[14 + 1] = addr & 0xFF, addr >> 8
    sid = SidFile(path="synthetic", data=bytes(data), name="", author="",
                  released="", load_addr=LOAD, subtunes=1)
    det.code_spans = []
    ph = phantom_patterns(sid, det)
    assert "pointer tables" in ph[1]


def test_convert_patterns_rejects_with_a_placeholder():
    sid, det = _fake_sid(), _fake_det()
    ph = phantom_patterns(sid, det)
    patterns, index = convert_patterns(sid, det, lambda m: None, phantoms=ph)
    # The real pattern converts; every phantom is the same one-rest
    # placeholder an undecodable address gets, so a track referencing one
    # still resolves.
    assert patterns[index[0][0]][:4] == [0x00 + 0x60, 0, 0, 0]
    for i in (1, 2, 3):
        assert patterns[index[i][0]] == ERROR_PATTERN


def test_without_the_pass_the_phantom_decodes_as_music():
    # Pinned, not endorsed: the default still decodes entry 1's bytes.
    sid, det = _fake_sid(), _fake_det()
    patterns, index = convert_patterns(sid, det, lambda m: None)
    assert patterns[index[1][0]] != ERROR_PATTERN


def test_commando_has_no_phantoms():
    # The reference file's table is exactly authored: every entry must pass.
    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    det = detect(sid, lambda m: None)
    assert phantom_patterns(sid, det) == {}
    assert phantom_patterns(sid, det, slides=True, status_bit6=True) == {}


# --- The same hole in the TRACK table ---------------------------------------
#
# `track_table_extent` is phantom_patterns' argument one table over: the track
# table has no length field either, so a header count larger than the table
# reads cells that belong to whatever follows -- in every corpus file that has
# the problem, the pattern LO array, which begins at the byte after the track
# table's last cell.


def _extent_case(n_subtunes: int, pattern_lo: int) -> tuple:
    """A synthetic file whose track table is followed by the pattern table."""
    data = bytearray(96)
    return (SidFile(path="synthetic", data=bytes(data), name="", author="",
                    released="", load_addr=LOAD, subtunes=n_subtunes),
            Detection(track_lo=10, track_hi=13,
                      pattern_lo=pattern_lo, pattern_hi=pattern_lo + 4,
                      pattern_used=3, read_track_version=0))


def test_extent_stops_where_the_pattern_table_starts():
    # Track cells run 10..15 for subtune 0, 16..21 for subtune 1; the pattern
    # LO array claims 16..19, so only subtune 0 is in the table.
    sid, det = _extent_case(8, pattern_lo=16)
    assert track_table_extent(sid, det) == 1
    # Move the pattern table two subtunes further out and two rows fit.
    sid, det = _extent_case(8, pattern_lo=28)
    assert track_table_extent(sid, det) == 3


def test_extent_never_looks_past_the_header_count():
    sid, det = _extent_case(2, pattern_lo=90)
    assert track_table_extent(sid, det) == 2


def test_extent_is_none_when_nothing_bounds_the_table():
    sid, det = _extent_case(4, pattern_lo=16)
    det.pattern_lo = det.pattern_hi = -1
    det.pattern_used = -1
    assert track_table_extent(sid, det) is None


def test_signature_matched_code_bounds_the_table_too():
    sid, det = _extent_case(8, pattern_lo=90)
    det.code_spans = [(17, 4)]      # player code inside subtune 1's cells
    assert track_table_extent(sid, det) == 1


@needs_corpus
def test_c64_music_examples_emits_one_subtune():
    """The file this bound was found on.

    Its PSID header claims 15 subtunes and its track table holds exactly one:
    the LO array is at $1436 and the pattern LO array begins six bytes later
    at $143C, which is 3 voices x 2 bytes. Subtune 14 read its "pointers" out
    of pattern LO entries 78 and 81, which compose $08F2 -- six bytes into the
    init dispatch's LO table at $08EC (`$08CB: LDA $08EC,X / STA $0878`,
    self-modifying the operand of the `JSR` at $0877, with the HI half coming
    from $08D8). It decoded 277 pattern references out of a table of routine
    addresses, and being the last declared subtune it kept the twelve
    placeholders in front of it alive too.
    """
    sid = load_sid(str(CORPUS / "Commodore_64_Music_Examples.sid"))
    det = detect(sid, lambda m: None)
    assert sid.subtunes == 15
    assert det.track_lo == sid.to_offset(0x1436)
    assert det.pattern_lo == sid.to_offset(0x143C)
    assert track_table_extent(sid, det) == 1

    # $08F2 is inside the dispatch LO table, and the table is the operand of
    # the LDA that reads it.
    data = sid.data
    lda = sid.to_offset(0x08CB)
    assert data[lda] == 0xBD                      # LDA abs,X
    assert data[lda + 1] | data[lda + 2] << 8 == 0x08EC
    assert data[lda + 3] == 0x8D                  # STA abs
    assert data[lda + 4] | data[lda + 5] << 8 == 0x0878   # the JSR's operand

    cen = []
    tracks = convert_tracks(sid, det, lambda *a, **k: None, census=cen)
    assert len(tracks) // 3 == 1
    assert [r["fate"] for r in cen[1:]] == ["beyond_table"] * 14


@needs_corpus
@pytest.mark.parametrize("name,extent", [
    ("Commando", 3), ("Commodore_64_Music_Examples", 1), ("Crazy_Comets", 2),
    ("Delta_Mix-E-Load_loader", 1), ("Geoff_Capes_Strongman_Challenge", 8),
    ("Gremlins", 7), ("Last_V8", 3), ("Last_V8_C128_version", 3),
    ("Mega_Apocalypse", 1), ("Monty_on_the_Run", 3),
    ("Nemesis_the_Warlock", 1), ("One_Man_and_his_Droid", 1),
    ("Rasputin", 2), ("Spellbound", 4), ("Thing_on_a_Spring", 1),
    ("Thundercats", 1), ("Warhawk", 9),
])
def test_the_bounded_files_end_exactly_where_the_pattern_table_begins(name, extent):
    """These seventeen are the whole reach of the bound, and it is not a cutoff.

    In every one the track table's last cell is the byte immediately before
    the pattern LO array -- the tables are adjacent, so the extent is the
    table's real end rather than a threshold. Warhawk is the independent
    check: SUBTUNES.md names its subtunes 0-8 ($1847..$1A14) as the real rows
    and its subtune 9 ($6C16 $1840 $3C56) as one that merely "resolves", and
    the bound lands on exactly that boundary without being told.
    """
    import dataclasses
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    det = detect(sid, lambda m: None)
    assert track_table_extent(sid, det) == extent
    last_cell = max(det.track_lo, det.track_hi) + \
        (det.track_voices - 1) + (extent - 1) * det.track_voices * 2
    assert last_cell + 1 == det.pattern_lo
    # The emitted count is checked with the player's sfx dispatch switched
    # OFF, because this test is about the layout bound alone. With it on,
    # Spellbound emits 3 rather than 4 -- the dispatch is tighter there and
    # wins, which is the composition working, not this bound failing.
    # test_tracks.test_the_dispatch_caps_the_orderlists_a_file_emits pins
    # the other side and their agreement.
    layout_only = dataclasses.replace(det, music_subtunes=None)
    assert len(convert_tracks(sid, layout_only, lambda *a, **k: None)) // 3 == extent


@needs_corpus
def test_the_bound_reaches_no_other_corpus_file():
    """A byte-hash names the same seventeen; this names them structurally.

    Many more files carry a header count larger than their table -- the bound
    is *some* number below `sid.subtunes` on 22 of them -- but on all but
    these seventeen the playability test has already trimmed at or below it,
    so the extent decides nothing. The comparison is against the converter
    with the bound switched off, which is what removing the two spans it reads
    does, rather than against a number written down here.
    """
    import dataclasses

    from h2g.convert import _detect_tables

    moved = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                                   # noqa: BLE001
            continue
        assert track_table_extent(sid, det) != 0, \
            f"{path.name}: subtune 0's own cells are in a table"
        # The player's sfx dispatch is switched off on BOTH sides: this test
        # measures the extent's reach, and leaving the dispatch on either side
        # would silently subtract the eight files it also bounds. With it off
        # the seventeen below are unchanged by the merge, which is the claim.
        det = dataclasses.replace(det, music_subtunes=None)
        unbounded = dataclasses.replace(det, pattern_lo=-1, pattern_hi=-1,
                                        code_spans=[])
        assert track_table_extent(sid, unbounded) is None
        try:
            before = len(convert_tracks(sid, unbounded, lambda *a, **k: None)) // 3
            after = len(convert_tracks(sid, det, lambda *a, **k: None)) // 3
        except ValueError:          # no readable orderlist dialect at all
            continue
        assert after <= before
        if after != before:
            moved[path.stem] = (before, after)
    assert moved == {
        "Commando": (18, 3),
        "Commodore_64_Music_Examples": (15, 1),
        "Crazy_Comets": (17, 2),
        "Delta_Mix-E-Load_loader": (14, 1),
        "Geoff_Capes_Strongman_Challenge": (21, 8),
        "Gremlins": (26, 7),
        "Last_V8": (12, 3),
        "Last_V8_C128_version": (12, 3),
        "Mega_Apocalypse": (11, 1),
        "Monty_on_the_Run": (19, 3),
        "Nemesis_the_Warlock": (15, 1),
        "One_Man_and_his_Droid": (13, 1),
        "Rasputin": (17, 2),
        "Spellbound": (13, 4),
        "Thing_on_a_Spring": (13, 1),
        "Thundercats": (11, 1),
        "Warhawk": (18, 9),
    }
