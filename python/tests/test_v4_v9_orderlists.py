"""Two orderlist dialects that produced nothing until v0.5.48.

**Version 4 (ACE 2)** was a do-nothing branch: it broke on `b1 >= 0x80` and
otherwise fell through without appending, so every version-4 orderlist came out
empty and the file failed with NO PLAYABLE SUBTUNE. The fault is inherited, not
introduced -- `h2g.frm:1152` `Case 4` is the same empty branch, and the later
`Case 0, 1, 2, 3, 4` at `:1199` that would have appended is unreachable for 4
because VB's `Select Case` takes the first match. ACE 2 is the corpus's only
version-4 file, so nothing else ever exposed it.

The player at $E0CF is a plain BPL split:

    E0CF  LDY $E550,X / LDA ($FC),Y / BPL $E0E4      ; < $80 -> pattern number
    E0D6  LDA #$00 / STA the three indices / JMP $E0CF

**Version 9 (Chain Reaction)** is version 0's shape with one terminator instead
of two. At $089A:

    089A  LDY $0CFA,X / LDA ($FC),Y / CMP #$FE / BEQ $08AD   ; loop to start
    08A3  CMP #$FE                                           ; dead code

The second CMP can never fire -- the first test took every $FE -- so the tune
has no stop marker at all, only loop-to-start. Version 0's signature expects
`C9 FF F0 ?? C9 FE`; this file is `C9 FE F0 ?? C9 FE`, matched nothing, and
fell through to version $FF.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import command_floor
from h2g.tracks import _build_track

END = [0xFF, 0x00]


def _track(raw, version):
    return _build_track(bytes(raw), 0, version, log=None, transpose_operand=False)


# --- version 4 -------------------------------------------------------------

def test_v4_keeps_its_pattern_numbers():
    # The regression itself: this used to return just the terminator.
    assert _track([0x00, 0x01, 0x23, 0x84], 4) == [0x00, 0x01, 0x23] + END


def test_v4_ends_on_any_byte_with_bit_7_set():
    # BPL, not CMP -- ACE 2's three subtunes terminate $84, $86 and $89, so a
    # decoder testing for one specific end byte would run off two of them.
    for end in (0x80, 0x84, 0x86, 0x89, 0xFF):
        assert _track([0x05, end, 0x06], 4) == [0x05] + END


def test_v4_restarts_at_zero():
    # The player zeroes its three indices and jumps back to $E0CF, so the
    # restart position is the start of the orderlist, not the terminator's
    # position.
    assert _track([0x05, 0x84], 4)[-2:] == END


# --- version 9 -------------------------------------------------------------

def test_v9_loops_to_start_on_fe():
    assert _track([0x00, 0x19, 0x0A, 0xFE], 9) == [0x00, 0x19, 0x0A] + END


def test_v9_has_no_stop_marker():
    # $FF is not special to this player -- the only test it performs is
    # CMP #$FE -- so it must not end the track the way it does in version 0.
    assert _track([0x05, 0xFF, 0x06, 0xFE], 9)[-2:] == END


def test_v9_drops_the_one_byte_it_cannot_represent():
    # command_floor is $FE, so $FF cannot survive reindex_tracks as a pattern
    # number; it is dropped rather than emitted as a Goattracker command that
    # was never in the tune. Nothing is lost in practice -- the player would
    # read it as pattern 255 against a table of 25 -- and Chain Reaction, the
    # only version-9 file, contains no $FF at all.
    assert _track([0x05, 0xFF, 0x06, 0xFE], 9) == [0x05, 0x06] + END


def test_v9_keeps_fd_as_a_pattern_number():
    assert _track([0xFD, 0xFE], 9) == [0xFD] + END


def test_v9_command_floor_leaves_fd_a_pattern_number():
    # $FE is the only byte this dialect reserves, so reindex_tracks must not
    # read $FD (or anything below it) as a command.
    assert command_floor(9) == 0xFE
