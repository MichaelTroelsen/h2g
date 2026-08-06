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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import Detection, detect
from h2g.patterns import (ERROR_PATTERN, convert_patterns, phantom_patterns)
from h2g.sidfile import HLEN, SidFile, load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

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
