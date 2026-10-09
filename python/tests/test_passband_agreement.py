"""`band`: frames both sides filter under the SAME $D418 passband.

`filt` counts a filtered frame under any passband, so it cannot see the
first-d418 seven (I_Ball, IK_plus, Nineteen, Pandora, Star_Paws, Thundercats,
Trans-Atlantic) filtering through bandpass where the original runs lowpass.
"""
import fidelity as F
from fidelity import FilterState

LOW, BAND, HIGH = 1, 2, 4          # $D418 bits 4-6 as (value >> 4) & 7


def fs(route, band, ctrl_at=0):
    return FilterState(ctrl_events=[(ctrl_at, route)],
                       passband_events=[(0, band)])


def test_wrong_passband_on_the_right_frames_reads_full_on_filt_and_zero_here():
    o, u = fs(1, LOW), fs(1, BAND)
    r = F.filter_compare(o, u, 100, lag=0)
    assert r["orig_filtered_frames"] == r["our_filtered_frames"] == 100
    assert r["passband_agree"] == 0.0
    assert r["passband_agree_frames"] == 0 and r["passband_union_frames"] == 100


def test_same_passband_scores_one():
    r = F.filter_compare(fs(1, LOW), fs(1, LOW), 100, lag=0)
    assert r["passband_agree"] == 1.0


def test_a_filter_we_invent_or_miss_is_charged_through_the_union():
    o = FilterState(ctrl_events=[(0, 1)], passband_events=[(0, LOW)])
    u = FilterState(ctrl_events=[(0, 1)], passband_events=[(0, LOW), (50, 0)])
    r = F.filter_compare(o, u, 100, lag=0)
    assert (r["passband_agree_frames"], r["passband_union_frames"]) == (50, 100)
    assert r["passband_agree"] == 0.5


def test_a_passband_with_no_voice_routed_is_not_filtering():
    r = F.filter_compare(fs(0, LOW), fs(0, BAND), 100, lag=0)
    assert r["passband_agree"] is None and r["passband_union_frames"] == 0


def test_resonance_nibble_and_unrouted_voice_bits_do_not_matter():
    r = F.filter_compare(fs(0xF1, LOW), fs(0x03, LOW), 100, lag=0)
    assert r["passband_agree"] == 1.0


def test_lag_aligns_our_timeline_before_comparing():
    o = FilterState(ctrl_events=[(0, 1)], passband_events=[(10, LOW)])
    u = FilterState(ctrl_events=[(0, 1)], passband_events=[(16, LOW)])
    unaligned = F.passband_agreement(o, u, 100, lag=0)
    aligned = F.passband_agreement(o, u, 100, lag=6)
    assert aligned["passband_agree"] > unaligned["passband_agree"]
    assert aligned["passband_agree_frames"] == 84   # 100 - 10 - 6 lagged frames


def test_without_a_lag_the_keys_are_absent_so_the_column_prints_a_dash():
    r = F.filter_compare(fs(1, LOW), fs(1, LOW), 100)
    assert "passband_agree" not in r
    d = next(d for d in F.DIMENSIONS if d.key == "passband_agree")
    assert d.fmt(d.value(r)) == "-"


def test_the_dimension_is_registered_and_printed():
    d = next(d for d in F.DIMENSIONS if d.key == "passband_agree")
    assert d.column == "band" and d.kind == "fraction"
    assert "$D418" in d.reads
    assert "passband" in d.of
