"""Version 5/6/7 orderlist commands.

The VB6 original had one branch for "the Mega Apocalypse family" covering
versions 5-8, and it matched none of those players:

    $80-$8F  scaled to $F0-$FF, so a transpose of +15 became $FF -- LOOPSONG,
             a spurious song loop where a transposed pattern belongs
    $90-$EE  discarded outright
    $EF-$FE  read as *negative* transposes, a form these players do not have
    version 5  given the whole command set although its player has none

Ground truth is the players' own code. Versions 6 and 7 branch on the high
bit and take the low seven as the value:

    Mega Apocalypse $4B15          IK+ $E09B
      B4 D6     LDY $D6,X            BC 40 E5  LDY $E540,X
      B1 F8     LDA ($F8),Y          B1 40     LDA ($40),Y
      10 19     BPL pattern          10 1D     BPL pattern
      C9 FF     CMP #$FF             C9 FF     CMP #$FF
      29 7F     AND #$7F             29 7F     AND #$7F
      9D 22 52  STA $5222,X          9D B4 E8  STA $E8B4,X

and read it back the same way version 2 does -- `AND #$7F` / `CLC` /
`ADC transpose,X` on the note before the frequency lookup ($4B7D, $E11E).
Neither tests $FE. Version 5 (Battle of Britain $803D) has no BPL and no
`AND #$7F` anywhere in the player: every byte but $FF is a pattern number.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.tracks import GT_MAX_TRANSPOSE, GT_TRANSUP, _build_track

END = [0xFF, 0x00]


def _track(raw, version, operand=False):
    return _build_track(bytes(raw), 0, version, log=None, transpose_operand=operand)


# --- the reported bug ------------------------------------------------------

def test_transpose_of_fifteen_is_not_emitted_as_loopsong():
    # $8F is +15. The old mapping made it $FF, which Goattracker reads as
    # LOOPSONG -- the track would restart instead of transposing. Three such
    # bytes sit in real subtunes (Bangkok Knights, Deep Strike, Shockway
    # Rider) and 22 more in Mega Apocalypse's later subtunes.
    for version in (6, 7):
        track = _track([0x8F, 0x05, 0xFF], version)
        assert track == [GT_TRANSUP + GT_MAX_TRANSPOSE, 0x05] + END
        assert 0xFF not in track[:-2]


# --- the other three faults in the same branch -----------------------------

def test_high_transposes_are_clamped_not_discarded():
    # $90-$EE used to be dropped, losing the transpose entirely. 16 occur in
    # real subtunes across six files.
    for version in (6, 7):
        assert _track([0x98, 0x05, 0xFF], version) == [0xFE, 0x05] + END
        assert _track([0xEE, 0x05, 0xFF], version) == [0xFE, 0x05] + END


def test_high_bytes_are_positive_transposes_not_negative_ones():
    # The player does AND #$7F and adds; there is no negative form. $F8 is
    # +120 (clamped), never -8.
    for version in (6, 7):
        assert _track([0xF8, 0x05, 0xFF], version)[0] == 0xFE


def test_fe_is_a_transpose_not_a_terminator_in_6_and_7():
    # Only version 2 compares against $FE. 6/7 fall through to the command
    # path, so $FE is transpose +126, clamped.
    for version in (6, 7):
        assert _track([0xFE, 0x05, 0xFF], version) == [0xFE, 0x05] + END


def test_in_range_transposes_map_exactly():
    for version in (6, 7):
        assert _track([0x80, 0x01, 0x87, 0x02, 0x8C, 0x03, 0xFF], version) == \
            [0xF0, 0x01, 0xF7, 0x02, 0xFC, 0x03] + END


# --- version 5 has no command set ------------------------------------------

def test_version_5_reads_every_byte_but_ff_as_a_pattern_number():
    assert _track([0x05, 0x80, 0x8F, 0x9A, 0xEF, 0xFE, 0xFF], 5) == \
        [0x05, 0x80, 0x8F, 0x9A, 0xEF, 0xFE] + END


def test_version_5_does_not_treat_fe_as_a_terminator():
    # Unlike versions 0/1/3, this player never compares against $FE.
    assert _track([0x01, 0xFE, 0x02, 0xFF], 5) == [0x01, 0xFE, 0x02] + END


# --- unchanged neighbours --------------------------------------------------

def test_version_2_still_terminates_on_fe():
    assert _track([0x01, 0xFE], 2) == [0x01, 0xFF, 0xFD]


def test_version_0_is_untouched():
    assert _track([0x80, 0x0A, 0xFF], 0) == [0x80, 0x0A] + END
