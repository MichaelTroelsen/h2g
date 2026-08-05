"""Which orderlist bytes are commands depends on the player dialect.

`convert_tracks` produces a track that is still in *Hubbard* numbering, with
each dialect's own commands already translated to Goattracker ones. Which byte
values are commands therefore moves with the version:

    0, 1, 3, 4   nothing but $FF -- every other byte, up to $FD, is a pattern
                 number, because those players compare against $FE/$FF and
                 nothing else
    2            transposes at $F0-$FE; pattern numbers are <= $7F, since the
                 player reads bit 7 as a command flag (BPL)
    5, 6, 7, 8   transposes at $E0-$FF; pattern numbers <= $7F

`reindex_tracks` used Goattracker's own $D0 boundary for all of them, so a
version-0 pattern number of $D0-$FD was emitted verbatim as a repeat or
transpose command: the reference was lost *and* a command the tune never
contained was inserted. 146 such bytes across 7 corpus files (Last V8 C128 47,
Geoff Capes 30, Last V8 24, Warhawk 20, Commando 14, Tarzan 8, Rasputin 3).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import (GT_COMMAND_FLOOR, command_floor, pattern_references,
                          reindex_tracks)

# Hubbard pattern n -> Goattracker patterns; $D4 is the interesting one.
INDEX = [[i] for i in range(0x100)]


def test_versions_without_a_high_bit_check_have_no_command_range():
    # Verified against the fingerprints in detect.py: versions 0/1/3 compare
    # against $FF and $FE only, and version 4's non-$FF path emits nothing.
    for version in (0, 1, 3, 4):
        assert command_floor(version) == 0xFF


def test_version_2_commands_start_at_transup():
    assert command_floor(2) == 0xF0


def test_mega_apocalypse_family_commands_start_at_transdown():
    for version in (5, 6, 7, 8):
        assert command_floor(version) == 0xE0


def test_goattracker_floor_is_the_default():
    # Post-reindex tracks are in Goattracker numbering, where $D0-$FF really
    # are commands, so callers reading those get the right answer by default.
    assert GT_COMMAND_FLOOR == 0xD0


# --- reindex_tracks --------------------------------------------------------

def test_a_version_0_high_pattern_number_is_reindexed():
    track = [0x05, 0xD4, 0x06, 0xFF, 0x00]
    assert reindex_tracks([track], INDEX, floor=command_floor(0)) == \
        [[0x05, 0xD4, 0x06, 0xFF, 0x00]]


def test_a_version_0_high_pattern_number_follows_the_index():
    # Renumbering must reach it like any other reference -- here every pattern
    # shifts by one, and $D4 must shift too rather than pass through.
    index = [[i + 1] for i in range(0x100)]
    assert reindex_tracks([[0x05, 0xD4, 0xFF, 0x00]], index,
                          floor=command_floor(0)) == [[0x06, 0xD5, 0xFF, 0x00]]


def test_an_out_of_range_high_pattern_number_is_dropped_not_emitted():
    # The 146 corpus bytes are all out of range. Dropping them is what happens
    # to every other dangling reference; emitting them invented a command.
    short_index = [[i] for i in range(0x10)]
    assert reindex_tracks([[0x05, 0xD4, 0xFF, 0x00]], short_index,
                          floor=command_floor(0)) == [[0x05, 0xFF, 0x00]]


def test_the_goattracker_floor_reproduces_the_old_behaviour():
    # Documents the bug rather than endorsing it: with $D0, the same byte is
    # passed straight through as a Goattracker repeat command.
    assert reindex_tracks([[0x05, 0xD4, 0xFF, 0x00]], INDEX) == \
        [[0x05, 0xD4, 0xFF, 0x00]]
    short_index = [[i] for i in range(0x10)]
    assert reindex_tracks([[0x05, 0xD4, 0xFF, 0x00]], short_index) == \
        [[0x05, 0xD4, 0xFF, 0x00]]


def test_version_2_transposes_still_pass_through():
    assert reindex_tracks([[0x7F, 0xF7, 0x05, 0xFF, 0x00]], INDEX,
                          floor=command_floor(2)) == [[0x7F, 0xF7, 0x05, 0xFF, 0x00]]


def test_mega_apocalypse_transposes_still_pass_through():
    assert reindex_tracks([[0xE5, 0x05, 0xFF, 0x00]], INDEX,
                          floor=command_floor(6)) == [[0xE5, 0x05, 0xFF, 0x00]]


def test_the_restart_operand_is_never_reindexed_at_any_floor():
    index = [[i + 1] for i in range(0x100)]
    for version in (0, 2, 6):
        out = reindex_tracks([[0xFF, 0x02]], index, floor=command_floor(version))
        assert out == [[0xFF, 0x02]], version


# --- pattern_references ----------------------------------------------------

def test_high_pattern_numbers_count_as_references_for_version_0():
    assert pattern_references([[0x05, 0xD4, 0xFF, 0x00]], command_floor(0)) == \
        [0x05, 0xD4]


def test_they_do_not_count_at_the_goattracker_floor():
    assert pattern_references([[0x05, 0xD4, 0xFF, 0x00]]) == [0x05]


def test_version_2_transposes_are_not_references():
    assert pattern_references([[0x7F, 0xF7, 0x05, 0xFF, 0x00]],
                              command_floor(2)) == [0x7F, 0x05]
