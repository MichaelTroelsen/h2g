"""`tie_audibility` carries the silent-tie split per voice (task per-voice-orig-ties-silent).

Hunter_Patrol's defect is on voices 1 and 2 only; the file total hides which.
"""
import fidelity

V = fidelity.Voice


def _v(ties, wf=True):
    return V(attacks=["C-4"], attack_frames=[100], ties=len(ties), tie_frames=list(ties),
             wf_events=[(100, 0x41), (120, 0x40)] if wf else [],
             adsr_events=[(100, 0x070A), (125, 0x0000)])


def test_each_voice_carries_its_own_silent_split_and_they_sum_to_the_total():
    o = [_v((10, 20, 112)), _v((112, 140)), _v((30,), wf=False)]
    u = [_v((112,)), _v((112, 150)), _v((30,), wf=False)]
    got = fidelity.tie_audibility(o, u, 200)
    pv = got["tie_audible_voices"]
    assert [(p["orig_ties"], p["orig_ties_silent"]) for p in pv] == [(3, 2), (2, 1), (1, 0)]
    assert [(p["our_ties"], p["our_ties_silent"]) for p in pv] == [(1, 0), (2, 1), (1, 0)]
    assert [p["tie_ratio_audible"] for p in pv] == [1.0, 1.0, 1.0]
    assert sum(p["orig_ties_silent"] for p in pv) == got["orig_ties_silent"] == 3
    assert sum(p["our_ties_silent"] for p in pv) == got["our_ties_silent"] == 1


def test_a_voice_with_no_audible_original_tie_has_no_ratio():
    got = fidelity.tie_audibility([_v((10, 20))], [_v((112,))], 200)
    assert got["tie_audible_voices"][0]["tie_ratio_audible"] is None
    assert got["tie_ratio_audible"] is None
