"""osplit-window-covers-file: the first frame an octave split plays is
recorded, so a 0 can be told from "the window never reached it"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity
import vicetrace as VT

N = VT.PAL_LINES_PER_FRAME


def _trill():
    return [VT.Sample(voices=[VT.VoiceLine(freq=0x1168 if (i % 156) < 78 else 0x22D0)] * 3)
            for i in range(N)]


def _flat():
    return [VT.Sample(voices=[VT.VoiceLine(freq=0x1168)] * 3) for _ in range(N)]


def test_first_frame_is_the_index_of_the_first_counted_frame():
    samples = _flat() * 5 + _trill() * 2
    first: list = []
    counts = VT.octave_split_frames(samples, first=first)
    assert counts == [2, 2, 2]
    assert first == [5, 5, 5]


def test_first_frame_is_none_where_the_window_never_reaches_the_shape():
    first: list = []
    assert VT.octave_split_frames(_flat() * 6, first=first) == [0, 0, 0]
    assert first == [None, None, None]


def test_row_fields_tell_zero_from_not_reached():
    got = fidelity.vice_octave_split(_flat() * 4 + _trill(), _flat() * 5)
    assert got["orig_octave_first_frame"] == 4
    assert got["our_octave_first_frame"] is None
    assert got["octave_window_frames"] == 5


def test_vsid_timeout_scales_with_the_window_and_keeps_its_floor():
    assert VT.vsid_timeout(60) == 300.0
    assert VT.vsid_timeout(180) >= 300.0
    assert VT.vsid_timeout(400) >= 1200.0
