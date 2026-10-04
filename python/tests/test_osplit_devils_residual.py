"""osplit-devils-residual-16: the 16 octave-split frames Devils_Galop's
voice 1 showed on ours (frames 38, 70, 102 ... 518, every 32nd, identical with
the ticked arpeggio shipped or disabled) were a VIBRATO TURNAROUND, not an
octave and not the arpeggio.

At the extreme of a 3-call-a-frame vibrato whose step is $7D a call, the frame
holds `$81FA` (dumped sign-extended as `$FFFA`) and the extreme `$817D`, in an
a-b-a shape: two values, two changes, a 153-line minority -- every trill test
passes. The verdict read `$817D` against `$FFFA` as an octave because
`2 * $817D = $102FA` and the dump's low byte `$FA` agreed with it. An octave
above `$8000` is not a 16-bit freq (v0.5.497), so the pair is now False: not
counted, and not blind either.

Frame data are the run-lengths of the real trace (`--vice -t 12`, ours, voice
1, frames 37-39); the other two voices are silent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity
import vicetrace as VT

N = VT.PAL_LINES_PER_FRAME


def _frame(runs):
    seq = [f for f, n in runs for _ in range(n)]
    assert len(seq) == N
    return [VT.Sample(voices=[VT.VoiceLine(), VT.VoiceLine(freq=f), VT.VoiceLine()])
            for f in seq]


# frames 37, 38, 39 of the shipped conversion, voice 1: the turnaround is 38
TURNAROUND = (
    _frame([(0x8277, 279), (0xFFFA, 33)])
    + _frame([(0xFFFA, 126), (0x817D, 153), (0xFFFA, 33)])
    + _frame([(0xFFFA, 279), (0x8277, 33)])
)


def test_the_turnaround_frame_has_every_shape_the_trill_rule_tests():
    """What made it a candidate: two values, >= 2 changes, a big minority.
    Pins the premise, so the next test cannot pass by the frame going quiet."""
    mid = TURNAROUND[N:2 * N]
    seq = [s.voices[1].freq for s in mid]
    assert sorted(set(seq)) == [0x817D, 0xFFFA]
    changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    assert changes == 2 and seq.count(0x817D) >= VT.OCTAVE_MINORITY_LINES


def test_the_turnaround_is_neither_an_octave_nor_a_blind_frame():
    blind: list = []
    first: list = []
    got = VT.octave_split_frames(TURNAROUND, blind=blind, first=first)
    assert got == [0, 0, 0]
    assert blind == [0, 0, 0]
    assert first == [None, None, None]


def test_the_row_reads_zero_on_both_sides():
    row = fidelity.vice_octave_split(TURNAROUND, TURNAROUND)
    assert row["our_octave_split_frames"] == 0
    assert row["our_octave_split_blind_frames"] == 0
    assert fidelity._fmt_osplit(row) == "0/0"


def test_the_above_8000_skip_is_not_a_blanket_refusal():
    """A pair whose octave IS a 16-bit freq and whose low byte agrees with the
    extended member stays unreadable (None): `$207D` doubled is `$40FA`."""
    assert VT._octave_verdict(0xFFFA, 0x207D) is None
    assert VT._octave_verdict(0x207D, 0xFFFA) is None
