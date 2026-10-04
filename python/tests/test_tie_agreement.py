"""`tie_agreement`: same-frame tie agreement beside `tie_ratio`'s count.

The count ratio credits a tie on the wrong frame. A phase fix that removes
spurious ties (Zoids voice 2: ours-only 178 -> 44, same-frame 2099 unchanged,
at d52a1bf, historical) must not read as a loss.
"""
import pytest

import fidelity


def _v(ties):
    return fidelity.Voice(attacks=["C-4"], ties=len(ties), tie_frames=list(ties))


def test_the_count_ratio_cannot_tell_a_misplaced_tie_from_a_placed_one():
    orig = [_v([10, 20, 30])]
    on = fidelity.compare(orig, [_v([10, 20, 30])])
    off = fidelity.compare(orig, [_v([11, 21, 31])])
    assert on["tie_ratio"] == off["tie_ratio"] == 1.0
    a = fidelity.tie_compare(orig, [_v([10, 20, 30])], 100)
    b = fidelity.tie_compare(orig, [_v([11, 21, 31])], 100)
    assert a["tie_agreement"] == 1.0
    assert b["tie_agreement"] == 0.0
    assert b["tie_ours_only"] == 3 and b["tie_orig_only"] == 3


def test_removing_spurious_ties_raises_agreement_while_the_ratio_falls():
    """The Zoids shape, scaled down: same-frame ties unchanged, ours-only
    ties 178 -> 44 (here 8 -> 2)."""
    orig_frames = list(range(0, 200, 2))                # 100 ties
    orig = [_v(orig_frames)]
    before = [_v(orig_frames + [f + 1 for f in range(0, 16, 2)])]   # +8 spurious
    after = [_v(orig_frames + [f + 1 for f in range(0, 4, 2)])]     # +2 spurious
    rb, ra = fidelity.compare(orig, before), fidelity.compare(orig, after)
    assert ra["tie_ratio"] < rb["tie_ratio"]            # the count reads a "loss"
    tb = fidelity.tie_compare(orig, before, 400)
    ta = fidelity.tie_compare(orig, after, 400)
    assert tb["tie_same_frame"] == ta["tie_same_frame"] == 100
    assert (tb["tie_ours_only"], ta["tie_ours_only"]) == (8, 2)
    assert ta["tie_agreement"] > tb["tie_agreement"]


def test_it_is_aligned_by_the_startup_lag():
    orig = [_v([10, 20])]
    ours = [_v([17, 27])]
    assert fidelity.tie_compare(orig, ours, 100, lag=0)["tie_agreement"] == 0.0
    got = fidelity.tie_compare(orig, ours, 100, lag=7)
    assert got["tie_agreement"] == 1.0 and got["tie_same_frame"] == 2


def test_both_sides_are_cut_to_the_same_window():
    # The original's tie at 95 lands at 102 once shifted, past a 100-frame
    # window: it is out of the window, not a tie we failed to reproduce.
    orig = [_v([10, 95])]
    ours = [_v([17])]
    got = fidelity.tie_compare(orig, ours, 100, lag=7)
    assert got["tie_orig_only"] == 0 and got["tie_agreement"] == 1.0


def test_the_window_is_cut_at_both_ends_for_either_sign_of_lag():
    # lag +7: our tie at frame 3 precedes the aligned origin (frame 7) and is
    # outside the window -- not a spurious tie of ours.
    got = fidelity.tie_compare([_v([10])], [_v([3, 17])], 100, lag=7)
    assert got["tie_ours_only"] == 0 and got["tie_agreement"] == 1.0
    # lag -7: the original's tie at 10 lands on 3; our tie at 97 is past the
    # shifted window end (93) and must not be charged as ours-only.
    got = fidelity.tie_compare([_v([10])], [_v([3, 97])], 100, lag=-7)
    assert got["tie_ours_only"] == 0 and got["tie_orig_only"] == 0
    assert got["tie_agreement"] == 1.0


def test_none_when_neither_side_ties_and_per_voice_is_reported():
    assert fidelity.tie_compare([_v([])], [_v([])], 100)["tie_agreement"] is None
    got = fidelity.tie_compare([_v([1]), _v([])], [_v([1]), _v([4])], 100)
    assert [v["tie_agreement"] for v in got["tie_voices"]] == [1.0, 0.0]
    assert got["tie_agreement"] == pytest.approx(1 / 2)


def test_the_dimension_sits_beside_tie_and_dashes_when_absent():
    cols = [d.column for d in fidelity.DIMENSIONS]
    assert cols.index("tiefr") == cols.index("tie") + 1
    d = next(x for x in fidelity.DIMENSIONS if x.key == "tie_agreement")
    assert d.kind == "fraction" and d.reads == fidelity._PITCH_REGS
    assert d.fmt(None) == "-"
    row = {"tie_agreement": None}
    assert "tie_agreement" not in fidelity.dimensions_present(row)
    assert "tie_agreement" in fidelity.dimensions_present({"tie_agreement": 0.0})
