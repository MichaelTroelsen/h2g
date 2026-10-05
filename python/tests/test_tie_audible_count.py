"""`tie_audibility` splits `tie_ratio`'s count by whether the tie is heard.

Task tie-column-counts-silent-frames (opened at 3b1c66d by
hunter-patrol-voice-1-2-tie-deficit): siddump calls a frequency write that
lands on a note pitch a tie even with the gate off and the envelope at zero,
and Hunter_Patrol's gate-off intro carries most of its original ties. The
fixtures are a voice parked silent for 100 frames, then one struck note.
"""
import fidelity

V = fidelity.Voice


def _build(intro_ties, audible_ties, wf):
    frames = list(intro_ties) + list(audible_ties)
    return V(attacks=["C-4"], attack_frames=[100], ties=len(frames),
             tie_frames=frames,
             wf_events=[(100, 0x41), (120, 0x40)] if wf else [],
             adsr_events=[(100, 0x070A), (125, 0x0000)])


def test_a_silent_frame_write_is_counted_apart_from_the_audible_ties():
    # 3 ties in the silent intro, 1 while sounding (112), 2 after the envelope
    # zero (140, 150).
    o = _build((10, 20, 30), (112, 140, 150), True)
    u = _build((), (112,), True)
    got = fidelity.tie_audibility([o], [u], 200)
    assert got["orig_ties_silent"] == 5
    assert got["our_ties_silent"] == 0
    assert got["tie_ratio_audible"] == 1.0           # 1 audible against 1
    # tie_ratio itself is untouched: 1 / 6.
    assert abs(fidelity.compare([o], [u])["tie_ratio"] - 1 / 6) < 1e-9


def test_the_silent_intro_write_no_longer_hides_a_real_deficit():
    o = _build((10, 20, 30, 40), (101, 103, 105, 107), True)
    u = _build((), (105,), True)
    got = fidelity.tie_audibility([o], [u], 200)
    assert got["orig_ties_silent"] == 4 and got["our_ties_silent"] == 0
    assert got["tie_ratio_audible"] == 0.25          # 1 / 4, not 1 / 8


def test_our_silent_ties_are_read_against_our_own_envelope():
    o = _build((), (105, 110), True)
    u = _build((5,), (105, 130), True)               # 5 and 130 are silent
    got = fidelity.tie_audibility([o], [u], 200)
    assert got["our_ties_silent"] == 2
    assert got["tie_ratio_audible"] == 0.5


def test_a_voice_without_waveform_events_has_no_silent_tie():
    o = _build((10, 20), (105,), False)
    got = fidelity.tie_audibility([o], [o], 200)
    assert got["orig_ties_silent"] == 0 and got["our_ties_silent"] == 0
    assert got["tie_ratio_audible"] == 1.0


def test_no_audible_original_tie_reads_none():
    o = _build((10, 20), (), True)
    got = fidelity.tie_audibility([o], [_build((), (105,), True)], 200)
    assert got["orig_ties_silent"] == 2
    assert got["tie_ratio_audible"] is None


def test_a_tie_past_the_window_is_not_counted_silent():
    o = _build((), (105, 250), True)                 # 250 is past nframes
    got = fidelity.tie_audibility([o], [o], 200)
    assert got["orig_ties_silent"] == 0
