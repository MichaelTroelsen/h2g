"""`_bend_tail` also takes bend printed after the envelope has died, even when
a later SR write puts a long release nibble back in force (Confuzion voice 0:
AD/SR $0000 on the gate-off frame, the instrument's SR three frames later)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity  # noqa: E402


def _voice(zero_write: bool) -> fidelity.Voice:
    v = fidelity.Voice()
    v.wf_events = [(0, 0x41), (10, 0x40)]
    v.adsr_events = [(0, 0x09A9)]
    if zero_write:
        v.adsr_events += [(10, 0x0000), (13, 0x09A9)]
    v.bend_events = [(5, 7), (20, 11), (60, 13)]
    v.bend = sum(d for _, d in v.bend_events)
    return v


def test_bend_after_a_zeroed_release_is_tail_though_sr_is_restored():
    # Gate off at 10 with SR zeroed: the envelope is gone a frame later and
    # the SR restored at 13 cannot revive it, so the bend at 20 is inaudible.
    v = _voice(zero_write=True)
    assert fidelity._release_frames(9) == 38
    assert fidelity._bend_tail(v) == 11 + 13
    assert fidelity._bend_travel(v) == 7


def test_bend_inside_a_real_release_is_still_travel():
    # The same notes without the zero write: release 9 is sounding at frame 20
    # (10 + 38 = 48 is when it runs out), so only the bend at 60 is tail.
    v = _voice(zero_write=False)
    assert fidelity._bend_tail(v) == 13
    assert fidelity._bend_travel(v) == 7 + 11


def test_dead_frames_stop_at_the_next_gate_rise():
    v = _voice(zero_write=True)
    v.wf_events.append((40, 0x41))
    v.adsr_events.append((40, 0x09A9))
    dead = fidelity._envelope_dead_frames(v)
    assert 20 in dead and 39 in dead
    assert 40 not in dead and 50 not in dead
