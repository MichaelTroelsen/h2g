"""`gate_compare` skips a 0/0 frame only BEFORE the voice first sounds.

A `$00` after a waveform was selected is a written WF 0 (the original's
player parks voices on it at tune end), both sides' gate is off, and the frame
is agreement -- not a frame to drop from the denominator.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fidelity import Voice, gate_compare  # noqa: E402


def _run(orig_events, our_events, nframes=10):
    orig = [Voice(wf_events=list(orig_events)), Voice(wf_events=[]), Voice(wf_events=[])]
    ours = [Voice(wf_events=list(our_events)), Voice(wf_events=[]), Voice(wf_events=[])]
    return gate_compare(orig, ours, nframes)


def test_written_wf_zero_after_sounding_counts_as_agreement():
    # Gate on frames 2-3; original parks on WF 00 from frame 6, ours parks on
    # WF 00 as well. Frames 2-3 gate on (not scored), 4-5 both released ($40), 6-9 both $00.
    ev = [(2, 0x41), (4, 0x40), (6, 0x00)]
    got = _run(ev, ev)
    assert got["gate_frames"] == 6          # frames 4..9 are gate-off
    assert got["gate"] == 1.0


def test_parked_tail_stays_in_the_denominator():
    # Original: on 2-3, released 4-5, parked WF 00 from 6. Ours rings through
    # 4-5 and parks at 6. The 2 ringing frames are the disagreement; the 4
    # parked frames are agreement and must count (4/6), not vanish (0/2).
    orig = [(2, 0x41), (4, 0x40), (6, 0x00)]
    ours = [(2, 0x41), (6, 0x00)]
    got = _run(orig, ours)
    assert got["gate_ours_ringing"] == 2
    assert got["gate_frames"] == 6
    assert abs(got["gate"] - 4 / 6) < 1e-9


def test_a_voice_neither_side_ever_sounds_still_scores_nothing():
    got = _run([], [])
    assert got["gate"] is None and got["gate_frames"] == 0


def test_leading_zero_frames_before_first_sound_still_skipped():
    ev = [(5, 0x41), (7, 0x40)]
    got = _run(ev, ev)
    assert got["gate_frames"] == 3          # frames 7..9 gate-off
