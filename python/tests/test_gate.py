"""The `gate` dimension: $D404 bit 0, which every other column ignores.

`wave_compare` excludes the gate bit deliberately and gives a good reason --
a gated-off voice keeps its waveform latched, so folding the gate into a
timbre score would count every note-length disagreement twice. `hold` counts
frames with a waveform *selected*; `adsr` and `tail` read the envelope pair.
Nothing read the bit itself, and the cost surfaced when `--rest-keyoff`
(v0.5.269) moved 19 files' bytes and one number on one file.

Scored over the *gate-off* frames alone -- `|both off| / |either off|` --
because both sides hold the gate on for most of a tune and counting those
would put every file in the high nineties.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity  # noqa: E402
from fidelity import Voice, gate_compare  # noqa: E402


def _voice(pairs):
    """A Voice whose $D404 writes are `pairs` of (frame, value)."""
    return Voice(wf_events=list(pairs))


def _one(orig_events, our_events, nframes=8, lag=0):
    orig = [_voice(orig_events), _voice([]), _voice([])]
    ours = [_voice(our_events), _voice([]), _voice([])]
    return gate_compare(orig, ours, nframes, lag=lag)


def test_identical_gating_scores_one():
    ev = [(0, 0x41), (4, 0x40)]
    got = _one(ev, ev)
    assert got["gate"] == 1.0
    assert got["gate_ours_ringing"] == 0 and got["gate_ours_silent"] == 0


def test_a_voice_we_never_release_scores_zero():
    got = _one([(0, 0x41), (4, 0x40)], [(0, 0x41)])
    assert got["gate"] == 0.0
    # Four frames the original spends released and we do not.
    assert got["gate_ours_ringing"] == 4
    assert got["gate_ours_silent"] == 0


def test_the_direction_is_reported_both_ways():
    """A note we end early is a different defect from one we never end."""
    got = _one([(0, 0x41)], [(0, 0x41), (4, 0x40)])
    assert got["gate_ours_ringing"] == 0
    assert got["gate_ours_silent"] == 4


def test_frames_both_sides_hold_the_gate_on_say_nothing():
    """They are most of a tune; counting them would drown the signal."""
    on = [(0, 0x41)]
    got = _one(on, on, nframes=1000)
    # Nothing is gated off on either side, so there is nothing to compare.
    assert got["gate"] is None
    assert got["gate_frames"] == 0


def test_a_release_at_the_wrong_moment_scores_between():
    got = _one([(0, 0x41), (2, 0x40)], [(0, 0x41), (4, 0x40)], nframes=8)
    # Original off from 2, ours from 4: both off on 4..7, either off on 2..7.
    assert got["gate_frames"] == 6
    assert got["gate"] == 4 / 6
    assert got["gate_ours_ringing"] == 2


def test_the_lag_shifts_ours_like_every_other_per_frame_column():
    """The packed player reaches its first note several frames late."""
    orig = [(0, 0x41), (4, 0x40)]
    ours = [(2, 0x41), (6, 0x40)]
    assert _one(orig, ours, nframes=10)["gate"] < 1.0
    assert _one(orig, ours, nframes=10, lag=2)["gate"] == 1.0


def test_it_is_a_declared_dimension_reading_D404():
    dim = next(d for d in fidelity.DIMENSIONS if d.key == "gate")
    assert dim.column == "gate"
    assert dim.reads == ("$D404",)
    assert dim.kind == "fraction"
    # The gaming vector is named in the column's own description, so the
    # report carries it rather than a docstring nobody prints.
    assert "removed" in dim.of


def test_a_row_without_it_does_not_claim_it():
    assert "gate" not in fidelity.dimensions_present({"file": "x"})
    assert "gate" in fidelity.dimensions_present({"gate": 0.5})
