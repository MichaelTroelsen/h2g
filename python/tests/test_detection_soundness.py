"""Rejecting detections that matched something other than the tune's player.

Signature matching gives no guarantee the operands it reads are really table
addresses. When they are not, every downstream guard behaves correctly on
garbage and the result is a structurally valid, musically empty .sng -- a
failure that reads as a success. Two corpus files did exactly that:

  One on One: Jordan vs Bird  the three "orderlist" pointers land in
                              nibble-packed sample data; 89% of the references
                              they yield name patterns that do not exist
  ACE 2                       the first orderlist byte is already a restart
                              command, so no subtune plays anything

Individually bad references are normal -- phantom subtunes alone account for
up to 46% of a real file's references (Mega Apocalypse) -- so only the
proportion across the whole file separates the two cases.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from h2g.convert import (MAX_DANGLING_SHARE, UnsupportedSidError,
                         check_detection_sound)

PATTERN_USED = 9   # patterns $00-$09 exist


def _check(tracks):
    check_detection_sound(tracks, PATTERN_USED, log=lambda m: None)


def test_clean_orderlist_passes():
    _check([[0x00, 0x01, 0x09, 0xFF, 0x00]])


def test_no_subtune_at_all_is_rejected():
    # convert_tracks returns [] rather than fabricating a placeholder subtune;
    # the placeholder referenced pattern 0 and so looked sound to every check.
    with pytest.raises(UnsupportedSidError, match="NO PLAYABLE SUBTUNE"):
        _check([])


def test_mostly_dangling_orderlist_is_rejected():
    # 3 of 4 references (75%) name patterns that do not exist.
    with pytest.raises(UnsupportedSidError, match="UNSOUND"):
        _check([[0x63, 0x7A, 0x05, 0x51, 0xFF, 0x00]])


def test_a_minority_of_dangling_references_is_tolerated():
    # Half the references dangle -- worse than any real corpus file, and still
    # not enough to condemn the detection. Losing those rows is the known,
    # reported behaviour; refusing the file outright would be worse.
    _check([[0x63, 0x01, 0x7A, 0x02, 0xFF, 0x00]])


def test_threshold_is_exclusive():
    # Exactly at the limit passes; the check fires only above it.
    assert MAX_DANGLING_SHARE == 2 / 3
    _check([[0x63, 0x7A, 0x05, 0xFF, 0x00]])                   # 2 of 3 dangle
    with pytest.raises(UnsupportedSidError):
        _check([[0x63, 0x7A, 0x51, 0x05]])                     # 3 of 4 dangle


def test_restart_position_is_not_counted_as_a_reference():
    # The byte after $FF is a restart position, not a pattern reference. Here
    # it is $63 -- out of range, so counting it would put this file at 25%
    # dangling instead of 0%. The grammar itself is covered by test_prune.
    _check([[0x01, 0x02, 0x03, 0xFF, 0x63]])


def test_commands_are_not_counted_as_references():
    # $D0-$FE are repeat/transpose commands, all >= the pattern ceiling. If
    # they were counted, every transposed tune would look unsound.
    _check([[0xF7, 0x01, 0xF2, 0x02, 0xD3, 0x03, 0xFF, 0x00]])
