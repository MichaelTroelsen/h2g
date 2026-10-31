"""arp_fixed_note: an absolute note in a drum record's source stays absolute
when the record is arpeggiated (goatwriter.drums._arp_block).

The arpeggio adds to the NOTE, so a frame the record plays at a fixed pitch
(right byte above $80, gplay.c:717-723) is not stepped: Sun_Never_Shines
record 07 holds its noise strike at $AF68 on every row note, and Go_Go_Dash 03
and Lakers 08/0A the same. Heard 2026-10-31: Sun_Never_Shines instr .46 -> .86.
"""
from h2g.goatwriter.drums import _arp_block

OFFSETS = [0, 4, 7]


def test_a_noise_strike_at_a_fixed_note_keeps_its_note():
    left, right = _arp_block([(0x81, 0xD8), (0x41, 0x80), (0xFF, 0)],
                             OFFSETS, 1, 1)
    assert left[0] == 0x81 and right[0] == 0xD8


def test_the_relative_frames_still_step_the_arpeggio():
    left, right = _arp_block([(0x81, 0xD8), (0x41, 0x80), (0xFF, 0)],
                             OFFSETS, 1, 1)
    steps = right[1:left.index(0xFF)]
    assert set(steps) >= {0, 4, 7}, steps


def test_a_relative_source_frame_is_arpeggiated_as_before():
    """A right byte at or below WAVE_NOTE_KEEP is relative: it takes the step."""
    left, right = _arp_block([(0x81, 0x00), (0x41, 0x80), (0xFF, 0)],
                             OFFSETS, 1, 1)
    assert right[0] in OFFSETS


def test_a_delay_entry_is_never_taken_for_a_fixed_note():
    left, right = _arp_block([(0x02, 0xD8), (0x41, 0x80), (0xFF, 0)],
                             OFFSETS, 1, 1)
    assert left[0] == 0x02 and right[0] < 0x80
