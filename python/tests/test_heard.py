"""heard.py on synthetic traces: note anchoring, the known-equivalent gated
tick, pairing at a lag, and the `instr` share."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import heard as H  # noqa: E402

A4 = 0x1CD6  # a tonal pitch well above semi()'s floor


def _trace(voice0: list[tuple[int, int]], mult: int = 1,
           ad: int = 0x09, sr: int = 0x6A) -> dict:
    """One voice's frames as (control, freq); each frame's writes land on its
    first call, the other `mult - 1` calls write nothing."""
    writes = []
    for ctl, fr in voice0:
        writes.append([0, 5, ad, 0, 6, sr, 0, 0, fr & 0xFF, 0, 1, fr >> 8, 0, 4, ctl])
        writes += [[] for _ in range(mult - 1)]
    return {"writes": writes}


def _note(ctls: list[int], fr: int = A4) -> list[tuple[int, int]]:
    return [(c, fr) for c in ctls]


REST = _note([0x40] * 4)


def _one(orig, ours, mult=1):
    so, ro = H.frames(_trace(orig, mult), mult)
    sb, rb = H.frames(_trace(ours, mult), mult)
    a = H.notes(so, ro, 0, 0.0)
    b = H.notes(sb, rb, 0, 0.0)
    return a, b


def test_frames_reads_one_state_per_mult_calls():
    st, rose = H.frames(_trace(REST + _note([0x41, 0x40]), mult=3), 3)
    assert len(st) == 6
    assert [r[0] for r in rose] == [False] * 4 + [True, False]
    assert st[4][4] == 0x41 and st[5][4] == 0x40


def test_test_bit_frame_before_the_attack_is_testpre_not_a_shift():
    a, b = _one(REST + _note([0x41, 0x40, 0x40]),
                REST + _note([0x09, 0x41, 0x40, 0x40]))
    assert a[0]["start"] == 4 and a[0]["testpre"] == 0
    assert b[0]["start"] == 5 and b[0]["testpre"] == 1
    assert H.diffs(a[0], b[0]) == {"testpre"}


def test_gated_tick_is_known_above_s1_and_a_gate_difference_at_s1():
    orig = REST + _note([0x41, 0x80, 0x40, 0x40, 0x40, 0x40])
    ours = REST + _note([0x41, 0x81, 0x40, 0x40, 0x40, 0x40])
    a, b = _one(orig, ours, mult=2)
    assert H.diffs(a[0], b[0], multiplier=2) == {"gated_tick"}
    assert H.diffs(a[0], b[0], multiplier=1) == {"gate"}


def test_gate_held_on_a_tonal_frame_is_not_the_gated_tick():
    a, b = _one(REST + _note([0x41, 0x40, 0x40]), REST + _note([0x41, 0x41, 0x40]),
                mult=2)
    ds = H.diffs(a[0], b[0], multiplier=2)
    # holding the gate a frame longer also shortens the gate-off tail
    assert ds == {"gate", "tail_len"}


def test_compare_pairs_at_the_lag_and_counts_instr():
    notes = [0x41, 0x40, 0x40, 0x40, 0x40, 0x40, 0x40, 0x40]
    orig = REST + _note(notes) * 4
    ours = REST + _note([0x40] * 3) + _note(notes) * 3 + _note([0x41, 0x41] + [0x40] * 6)
    r = H.compare(_trace(orig), _trace(ours), 1, 1)
    assert r["lag"] == 3
    assert r["notes"] == 4 and r["missing"] == 0
    assert r["gate"] == 1 and r["match"] == 3
    assert r["instr"] == 0.75


def test_pair_leaves_a_far_note_missing_and_ours_invented():
    a = [{"start": 10}, {"start": 50}]
    b = [{"start": 11}, {"start": 90}]
    pairs, inv = H.pair(a, b, 0)
    assert pairs[0][1] is b[0] and pairs[1][1] is None
    assert inv == [b[1]]
