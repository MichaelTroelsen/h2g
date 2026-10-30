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


# --- MagPlaySID's four rules, each pinned by the test that fails without it ---

def _fr(n: int) -> int:
    """The frequency of semitone `n` above C0 on a zero-tuned side."""
    return round(H.C0 * 2 ** (n / 12))


def _frames(spec: list[tuple[int, int, int]], ad: int = 0x09, sr: int = 0x6A) -> dict:
    """Frames of (control, semitone-or-raw-freq, sr); a freq below 100 is a
    semitone, so a test can say 'the same pitch' by number."""
    writes = []
    for ctl, f, s in spec:
        fr = _fr(f) if f < 100 else f
        writes.append([0, 5, ad, 0, 6, s or sr, 0, 0, fr & 0xFF, 0, 1, fr >> 8, 0, 4, ctl])
    return {"writes": writes}


def _two(orig, ours, row=None):
    so, ro = H.frames(_frames(orig), 1)
    sb, rb = H.frames(_frames(ours), 1)
    return H.notes(so, ro, 0, 0.0, row), H.notes(sb, rb, 0, 0.0, row)


def _on(ctl, pitches):
    return [(ctl, p, 0) for p in pitches]


OFF = [(0x40, 40, 0)] * 6   # a gate-off run long enough that no tail is read


def test_rule1_a_pitch_named_after_other_frames_is_not_a_defect():
    # the sides hold different frames longest, so the relative form differs on
    # frames 0 and 3, but each of those frames agrees in the absolute form
    a = _on(0x41, [50, 50, 50, 52, 52, 40])
    b = _on(0x41, [50, 50, 52, 52, 52, 40])
    na, nb = _two(a + OFF, b + OFF)
    assert na[0]["held"] != nb[0]["held"]
    assert H.diffs(na[0], nb[0]) == {"pitch_rel"}
    assert "pitch_rel" in H.KNOWN and "pitch" in H.CORE


def test_rule1_a_pitch_differing_in_every_form_is_pitch():
    a = _on(0x41, [50] * 6)
    b = _on(0x41, [50, 50, 50, 55, 55, 55])
    na, nb = _two(a + OFF, b + OFF)
    assert na[0]["held"] == nb[0]["held"]
    assert H.diffs(na[0], nb[0]) == {"pitch"}


def test_rule2a_a_silent_frame_takes_the_next_frames_pitch():
    # the test-bit frame holds a stray frequency on one side only
    a = [(0x41, 50, 0), (0x49, 77, 0), (0x41, 50, 0), (0x41, 50, 0),
         (0x41, 50, 0), (0x41, 50, 0)]
    b = [(0x41, 50, 0), (0x49, 50, 0), (0x41, 50, 0), (0x41, 50, 0),
         (0x41, 50, 0), (0x41, 50, 0)]
    na, nb = _two(a + OFF, b + OFF)
    assert na[0]["prog"][1][2] == na[0]["prog"][2][2]
    assert H.diffs(na[0], nb[0]) == set()


def test_rule2a_a_frame_silent_on_one_side_only_has_no_pitch_to_compare():
    # the original strikes a noise frame at $FFFF; ours holds the oscillator
    # with the test bit there (wave ignores that bit), and keeps its pitch
    a = [(0x41, 50, 0), (0x81, 65535, 0)] + [(0x41, 50, 0)] * 4
    b = [(0x41, 50, 0), (0x89, 50, 0)] + [(0x41, 50, 0)] * 4
    na, nb = _two(a + OFF, b + OFF)
    assert H.diffs(na[0], nb[0]) == set()


def test_rule2b_no_pitch_is_read_after_the_gate_goes_off():
    # in the release both sides set up the next note, to different pitches
    a = _on(0x41, [50, 50]) + _on(0x40, [60, 60, 60, 60]) + OFF
    b = _on(0x41, [50, 50]) + _on(0x40, [65, 65, 65, 65]) + OFF
    na, nb = _two(a, b)
    assert na[0]["held"] == nb[0]["held"]
    assert [f is None for _, _, f in na[0]["prog"]] == [False, False] + [True] * 4
    assert H.diffs(na[0], nb[0]) == set()


def test_rule3_a_restrike_continues_the_note():
    one = _on(0x41, [50]) + _on(0x40, [50]) + _on(0x41, [50]) + _on(0x40, [50] * 3) + OFF
    na, _ = _two(one, one)
    assert len(na) == 1
    # off for 3 frames, or on for 3, is a new note
    for spec in (_on(0x41, [50]) + _on(0x40, [50] * 3) + _on(0x41, [50]) + OFF,
                 _on(0x41, [50] * 3) + _on(0x40, [50]) + _on(0x41, [50]) + OFF):
        assert len(_two(spec, spec)[0]) == 2
    # the test bit between the strikes is a hard restart, not a restrike
    hard = _on(0x41, [50]) + _on(0x08, [50]) + _on(0x41, [50] * 3) + OFF
    assert len(_two(hard, hard)[0]) == 2
    # a changed envelope is a new note
    w = _frames(one + OFF)["writes"]
    w[2][2] = 0x19
    so, ro = H.frames({"writes": w}, 1)
    assert len(H.notes(so, ro, 0, 0.0)) == 2


def test_rule3b_a_strike_on_the_row_grid_is_a_note():
    # on 2, off 2, on again: 4 frames apart. On a 4-frame grid that is the next
    # row's note; with no grid, or a 6-frame one, it is the same note struck again
    spec = _on(0x41, [50] * 2) + _on(0x40, [50] * 2) + _on(0x41, [50] * 2) + OFF
    so, ro = H.frames(_frames(spec), 1)
    assert len(H.notes(so, ro, 0, 0.0, grid=4)) == 2
    assert len(H.notes(so, ro, 0, 0.0, grid=6)) == 1
    assert len(H.notes(so, ro, 0, 0.0)) == 1


def test_shortest_row_ignores_rare_short_gaps():
    assert H.shortest_row([[0, 4, 8, 12, 16, 20, 24, 26, 30, 34]]) == 4
    assert H.shortest_row([[0, 8, 16, 24, 32, 40, 48, 50, 58]]) == 8
    assert H.shortest_row([[5]]) is None


def test_rule4a_a_note_is_compared_to_gate_off_plus_its_release():
    # release 0 is 6 ms: one frame. The sides differ from frame 3 on only
    sr = 0x60
    a = [(0x41, 50, sr)] * 2 + [(0x40, 50, sr)] * 4 + [(0x40, 40, sr)] * 6
    b = [(0x41, 50, sr)] * 2 + [(0x40, 50, sr)] + [(0x20, 50, sr)] * 3 + [(0x40, 40, sr)] * 6
    na, nb = _two(a, b)
    assert len(na[0]["prog"]) == 3
    assert H.diffs(na[0], nb[0]) == set()


def test_rule4b_a_note_is_compared_to_its_first_silent_frame():
    a = [(0x41, 50, 0), (0x40, 50, 0), (0x40, 50, 0), (0x08, 50, 0),
         (0x40, 50, 0), (0x40, 50, 0)]
    b = [(0x41, 50, 0), (0x40, 50, 0), (0x40, 50, 0), (0x08, 50, 0),
         (0x20, 50, 0), (0x20, 50, 0)]
    na, nb = _two(a + OFF, b + OFF)
    assert len(na[0]["prog"]) == 3
    assert H.diffs(na[0], nb[0]) == set()


def test_rule4c_a_gate_off_at_the_end_of_the_row_is_the_tunes_not_the_instruments():
    # the side's rows are 6 frames, so a gate-off at frame 4 or 5 is the note-off.
    # A longer note (a rest after it, so no hard-restart tail) note-offs a frame
    # apart on the two sides: the tune's timing, not the instrument's gate
    a = _on(0x41, [50] * 4) + _on(0x40, [50] * 8)
    b = _on(0x41, [50] * 5) + _on(0x40, [50] * 7)
    na, nb = _two(a, b, row=6)
    assert [len(n[0]["prog"]) for n in (na, nb)] == [4, 5]
    assert H.diffs(na[0], nb[0]) == set()
    # at frame 3 it is inside the row: the instrument's, and a gate difference
    c = _on(0x41, [50] * 3) + _on(0x40, [50] * 9)
    nc, _ = _two(c, c, row=6)
    assert H.diffs(nc[0], nb[0]) == {"gate"}


def test_rule4_near_the_row_end_the_hard_restart_tail_carries_the_difference():
    a = (_on(0x41, [50] * 4) + _on(0x40, [50] * 2)) * 3
    b = (_on(0x41, [50] * 5) + _on(0x40, [50])) * 3
    na, nb = _two(a, b)
    assert len(na) == len(nb) == 3
    assert H.diffs(na[0], nb[0]) == {"tail_len"}
