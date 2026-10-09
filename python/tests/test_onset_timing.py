"""`onset_timing`: do our notes open on the frame the original's do?

`onset_agreement` / `onset_frame_agreement` read each side at its OWN attack
frames, so a constant offset cancels. Food_Feud at multiplier 3 (v0.5.517,
-t 180, presets) read `onset_frame_agreement` 1.000 with `startup_lag` 3 while
1158 of its 3491 paired attacks landed a frame after the lag-shifted original.
"""
import fidelity as F

AD = [(0, 0x0729)]


def _side(attacks, shift=0):
    """One voice whose every note opens on the same four-frame shape."""
    wf, at = [], []
    for a in attacks:
        a += shift
        at.append(a)
        wf += [(a + k, 0x41) for k in range(4)]
    return [F.Voice(wf_events=wf, adsr_events=list(AD), attack_frames=at),
            F.Voice(), F.Voice()]


ATT = [2, 10, 18, 26]


def test_registered_as_a_dimension():
    d = next(d for d in F.DIMENSIONS if d.key == "onset_timing")
    assert d.kind == "fraction" and d.column == "otime"
    assert "$D404" in d.reads


def test_identical_traces_read_one():
    r = F.onset_timing_compare(_side(ATT), _side(ATT), 40)
    assert r["onset_timing"] == 1.0 and r["onset_timing_paired"] == 4
    assert r["onset_timing_late"] == r["onset_timing_early"] == 0


def test_a_startup_lag_is_taken_out():
    r = F.onset_timing_compare(_side(ATT), _side(ATT, shift=3), 40, lag=3)
    assert r["onset_timing"] == 1.0


def test_a_constant_extra_frame_is_seen_by_timing_and_not_by_onset_agreement():
    """The defect this column exists for: every onset one frame late."""
    o, u = _side(ATT), _side(ATT, shift=4)
    assert F.onset_agreement(o, u, 40)["onset_frame_agreement"] == 1.0
    r = F.onset_timing_compare(o, u, 40, lag=3)
    assert r["onset_timing"] == 0.0
    assert r["onset_timing_late"] == 4 and r["onset_timing_early"] == 0
    assert r["onset_timing_offset"] == 1


def test_early_is_signed_the_other_way():
    r = F.onset_timing_compare(_side(ATT), _side(ATT, shift=2), 40, lag=3)
    assert r["onset_timing_early"] == 4 and r["onset_timing_late"] == 0
    assert r["onset_timing_offset"] == -1


def test_a_partial_slip_gives_a_fraction():
    u = _side([2, 11, 18, 27])                   # two of four a frame late
    r = F.onset_timing_compare(_side(ATT), u, 40)
    assert r["onset_timing"] == 0.5 and r["onset_timing_late"] == 2


def test_a_missing_note_is_not_charged_here():
    """`melody` reports a dropped note; counting it twice moves two columns."""
    r = F.onset_timing_compare(_side(ATT), _side([2, 10, 26]), 40)
    assert r["onset_timing_paired"] == 3 and r["onset_timing"] == 1.0


def test_an_attack_outside_the_window_is_not_paired():
    far = 2 + F.ONSET_TIMING_WINDOW + 1
    r = F.onset_timing_compare(_side([2]), _side([far]), 40)
    assert r["onset_timing"] is None and r["onset_timing_paired"] == 0


def test_no_attacks_is_none_not_one():
    r = F.onset_timing_compare([F.Voice()] * 3, [F.Voice()] * 3, 40)
    assert r["onset_timing"] is None
