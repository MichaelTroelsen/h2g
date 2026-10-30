"""`attribute.py`: the per-group miss counts must add up to the column's own.

The tool is only worth its table if no miss can fall out of it, so every test
here ties the groups' sum to a count taken from the code that scores the
column (`fidelity.gate_compare`, `fidelity.wave_compare`, `heard.diffs`) on a
synthetic pair small enough to count by hand, and one pins that a dropped
group is refused.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import attribute as A  # noqa: E402
import fidelity as F  # noqa: E402
import heard as H  # noqa: E402

NFRAMES = 40


def _voice(wf, adsr, attacks) -> F.Voice:
    v = F.Voice()
    v.wf_events = list(wf)
    v.adsr_events = list(adsr)
    v.attack_frames = list(attacks)
    v.attacks = ["C-4"] * len(attacks)
    return v


def pair_of_voices() -> tuple[list[F.Voice], list[F.Voice]]:
    """Voice 0 is the case; voice 1 agrees exactly and must add nothing.

    Gate (original $41 on 0-9, off 10-19, on 20-39; ours on 0-7, off 8-15, on
    16-29, then $81 on 30-32 and off from 33): frames 8-9 are ours silent
    against the original sounding, frames 16-19 ours sustaining against the
    original off. Wave: ours selects noise from frame 30 while the original
    stays on pulse until it parks at $00 on frame 36, and ours' own gate has
    been off for long enough by then that its latched noise is the tail the
    column does not charge.
    """
    orig = [_voice([(0, 0x41), (10, 0x40), (20, 0x41), (36, 0x00)],
                   [(0, 0x090A), (20, 0x0B7A)], [0, 20]),
            _voice([(0, 0x11), (12, 0x10)], [(0, 0x0900)], [0])]
    ours = [_voice([(0, 0x41), (8, 0x40), (16, 0x41), (30, 0x81), (33, 0x80)],
                   [(0, 0x090A), (16, 0x0B70)], [0, 16, 30]),
            _voice([(0, 0x11), (12, 0x10)], [(0, 0x0900)], [0])]
    return orig, ours


def test_gate_groups_sum_to_gate_compare_misses():
    orig, ours = pair_of_voices()
    res = F.gate_compare(orig, ours, NFRAMES, lag=0)
    misses = A.gate_misses(orig, ours, NFRAMES, 0)
    groups = A.group(misses)
    assert (res["gate_ours_silent"], res["gate_ours_ringing"]) == (5, 4)
    assert A.verify(groups, A.gate_expected(res), "gate") == len(misses)
    assert sum(groups.values()) == res["gate_ours_ringing"] + res["gate_ours_silent"]
    silent = {k: n for k, n in groups.items() if k[2] == "ours off, orig sounds"}
    # frames 8-9 sit 8 and 9 frames after attack 0 (instrument $090A); frames
    # 33-35 sit 13-15 frames after attack 20 (instrument $0B7A)
    assert silent == {("AD$09 SR$0A", "8", "ours off, orig sounds"): 1,
                      ("AD$09 SR$0A", "9", "ours off, orig sounds"): 1,
                      ("AD$0B SR$7A", "13", "ours off, orig sounds"): 1,
                      ("AD$0B SR$7A", "14", "ours off, orig sounds"): 1,
                      ("AD$0B SR$7A", "15", "ours off, orig sounds"): 1}
    # the sustain at 16-19 is owned by the attack at 0
    assert groups[("AD$09 SR$0A", "16", "ours sustains, orig off")] == 1
    assert sum(n for k, n in groups.items() if k[2].startswith("ours sus")) == 4


def test_wave_groups_sum_to_wave_compare_misses():
    orig, ours = pair_of_voices()
    res = F.wave_compare(orig, ours, nframes=NFRAMES, lag=0)
    assert res["wave_tail_frames"] > 0          # the tail rule is exercised
    groups = A.group(A.wave_misses(orig, ours, NFRAMES, 0))
    expected = A.wave_expected(res)
    assert expected == res["wave_frames"] - round(res["wave"] * res["wave_frames"])
    assert expected > 0
    assert A.verify(groups, expected, "wave") == expected
    assert all(k[2].startswith("orig $") for k in groups)


def test_wave_groups_sum_holds_under_a_lag():
    orig, ours = pair_of_voices()
    for lag in (-2, 3):
        res = F.wave_compare(orig, ours, nframes=NFRAMES, lag=lag)
        groups = A.group(A.wave_misses(orig, ours, NFRAMES, lag))
        assert sum(groups.values()) == A.wave_expected(res), lag
        res = F.gate_compare(orig, ours, NFRAMES, lag=lag)
        groups = A.group(A.gate_misses(orig, ours, NFRAMES, lag))
        assert sum(groups.values()) == A.gate_expected(res), lag


def _note(start: int, ctl: list[int], ad: int = 0x09, sr: int = 0x0A) -> dict:
    pitch = (0, 57, 0, 7494)
    return {"start": start, "testpre": 0, "held": 57, "first": 57, "ad": ad,
            "sr": sr, "prog": [(c, 0, pitch) for c in ctl], "tail": 0,
            "tailenv": None}


def heard_pair() -> dict:
    """Five original notes on voice 0: matched, gate differs at frame 2,
    wave differs at frame 1, AD differs (frame-independent), and one we never
    played. Voices 1 and 2 are empty."""
    on = [_note(0, [0x41] * 4),
          _note(10, [0x41] * 4),
          _note(20, [0x41, 0x81, 0x81, 0x81]),
          _note(30, [0x41] * 4, ad=0x24),
          _note(40, [0x41] * 4, ad=0x58)]
    bn = [_note(0, [0x41] * 4),
          _note(10, [0x41, 0x41, 0x40, 0x40]),
          _note(20, [0x41, 0x41, 0x41, 0x41]),
          _note(30, [0x41] * 4, ad=0x25)]
    return {"on": [on, [], []], "bn": [bn, [], []], "lag": 0, "mult_b": 1}


def test_instr_groups_sum_to_the_notes_heard_does_not_match():
    d = heard_pair()
    pairs, _ = H.pair(d["on"][0], d["bn"][0], d["lag"])
    expected = sum(1 for a, b in pairs
                   if b is None or H.diffs(a, b, d["mult_b"]) & set(H.CORE))
    assert expected == 4                        # 4 of the 5 notes
    groups = A.group(A.instr_misses(d))
    assert A.verify(groups, expected, "instr") == expected
    assert groups == {
        ("AD$09 SR$0A", "2", "gate"): 1,
        ("AD$09 SR$0A", "1", "wave"): 1,
        ("AD$24 SR$0A", "head", "ad"): 1,
        ("AD$58 SR$0A", "-", "missing"): 1,
    }


def test_a_dropped_group_is_refused():
    orig, ours = pair_of_voices()
    res = F.gate_compare(orig, ours, NFRAMES, lag=0)
    groups = A.group(A.gate_misses(orig, ours, NFRAMES, 0))
    assert len(groups) > 1
    dropped = groups.copy()
    del dropped[next(iter(dropped))]
    with pytest.raises(AssertionError, match="groups sum to"):
        A.verify(dropped, A.gate_expected(res), "gate")
    d = heard_pair()
    g = A.group(A.instr_misses(d))
    del g[next(iter(g))]
    with pytest.raises(AssertionError):
        A.verify(g, 4, "instr")
