"""Bit $40 halves bit $04's attack, and the table byte does not say so.

H2G-CONVERSION-METHOD.md carried "the relationship between that byte and the
shared `$0FAA,X` counter is not established" as an open question for several
versions. It is a halving, and the evidence is in `_two_stage_frames`'
docstring: 527 onsets at frames-byte 2 sounding one frame, and five files at
frames-byte 4 sounding two.

The `frames = 4` measurements are what make this a test of a *halving* rather
than of "a record with $40 always sounds one frame" -- at frames 2 the two
rules are indistinguishable, which is why the first reading of this stopped
short of the mechanism.
"""
from h2g.goatwriter import EFFECT_FIXED_PITCH_MASK, _two_stage_frames


def test_without_bit_40_the_byte_is_taken_as_written():
    for n in (1, 2, 3, 4, 8):
        assert _two_stage_frames(n, 0x04) == n


def test_with_bit_40_the_attack_is_halved():
    # The two measured points, both directly out of the corpus traces.
    assert _two_stage_frames(2, 0x44) == 1      # Sigma Seven $0FFD, 124 onsets
    assert _two_stage_frames(4, 0x44) == 2      # Trans-Atlantic $0A99, 150


def test_four_frames_is_what_rules_out_always_one():
    """At frames 2 a halving and a constant 1 agree; at 4 they do not."""
    assert _two_stage_frames(4, 0x44) != 1


def test_it_never_returns_zero():
    """`_two_stage_entries` declines a record whose frames are <= 0, so a
    halved 1 must not silently delete the attack block."""
    assert _two_stage_frames(1, 0x44) == 1
    assert _two_stage_frames(0, 0x44) >= 1


def test_the_mask_is_bit_40():
    assert EFFECT_FIXED_PITCH_MASK == 0x40
    # ...and no other bit triggers the halving -- the drum, the arpeggio and
    # the filter share the same byte.
    for other in (0x01, 0x08, 0x10, 0x20, 0x80):
        assert _two_stage_frames(4, 0x04 | other) == 4
