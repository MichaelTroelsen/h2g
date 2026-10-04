import fidelity
import vicetrace as VT

F1_HELD, F1_DROPS = 0xFF82, (0x0F02, 0x0E02, 0x0D02, 0x0C02)


def _samples(frames):
    return [VT.Sample(voices=[VT.VoiceLine(freq=f)] * 1 + [VT.VoiceLine(), VT.VoiceLine()])
            for fr in frames for f in fr]


def _formula1():
    held = [[F1_HELD] * 312] * 3
    drops = [[F1_HELD] * 119 + [d] * 154 + [F1_HELD] * 39 for d in F1_DROPS]
    return _samples(held + drops + held)


def test_blind_frames_reach_the_row_per_side():
    clean = _samples([[0x1168] * 312] * 3)
    got = fidelity.vice_octave_split(clean, _formula1())
    assert got["orig_octave_split_blind_frames"] == 0
    assert got["our_octave_split_blind_frames"] == 2
    assert got["our_octave_split_frames"] == 0


def test_osplit_cell_says_how_many_frames_it_could_not_read():
    row = {"our_octave_split_frames": 0, "orig_octave_split_frames": 0,
           "our_octave_split_blind_frames": 58, "orig_octave_split_blind_frames": 0}
    assert fidelity._fmt_osplit(row) == "0/0 (blind 58/0)"
    row["our_octave_split_blind_frames"] = 0
    assert fidelity._fmt_osplit(row) == "0/0"
