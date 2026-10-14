"""`bnote`: band-pass frames counted from the voice's last attack.

`band` aligns on one global startup lag, so a drum blip at the right place
inside its note is charged for every note whose onset is off the lag.
`bnote` counts each side's pure band-pass frames from its OWN last attack and
compares the offset histograms, so a shift of the whole side changes nothing.
"""
import fidelity as F
from fidelity import FilterState, Trace, Voice

LOW, BAND = 1, 2          # $D418 bits 4-6 as (value >> 4) & 7
N = 200


def side(attacks, blips, route=1, voice=0, unnamed=()):
    """One voice attacking at `attacks`; one-frame BP blips at `blips`
    (low-pass otherwise); `route` is the $D417 low nibble."""
    band = [(0, LOW)]
    for b in blips:
        band += [(b, BAND), (b + 1, LOW)]
    filt = FilterState(ctrl_events=[(0, route)], passband_events=sorted(band))
    voices = [Voice(), Voice(), Voice()]
    voices[voice] = Voice(attack_frames=list(attacks),
                          attacks=["C-4"] * len(attacks),
                          unnamed_attack_frames=list(unnamed))
    return Trace(voices, filt)


def test_identical_sides_read_full():
    t = side([10, 50, 90], [11, 51, 91])
    r = F.passband_note_relative(t, side([10, 50, 90], [11, 51, 91]), N)
    assert r["passband_note"] == 1.0
    assert r["passband_note_orig_frames"] == r["passband_note_our_frames"] == 3


def test_a_whole_side_shifted_by_a_lag_still_reads_full_where_band_does_not():
    o = side([10, 50, 90], [13, 53, 93])
    u = side([16, 56, 96], [19, 59, 99])          # everything 6 frames late
    r = F.passband_note_relative(o, u, N)
    assert r["passband_note"] == 1.0
    assert F.passband_agreement(o.filter, u.filter, N, lag=0)["passband_agree"] < 1.0


def test_a_blip_at_the_wrong_distance_from_its_note_scores_zero():
    o = side([10], [13])
    u = side([10], [17])
    assert F.passband_note_relative(o, u, N)["passband_note"] == 0.0


def test_a_missing_and_an_invented_blip_both_cost():
    o = side([10, 50], [13, 53])
    missing = side([10, 50], [13])
    invented = side([10, 50], [13, 53, 55])
    assert F.passband_note_relative(o, missing, N)["passband_note"] == 0.5
    assert F.passband_note_relative(o, invented, N)["passband_note"] == 2 / 3


def test_neither_side_with_a_band_pass_frame_is_none():
    r = F.passband_note_relative(side([10], []), side([10], []), N)
    assert r["passband_note"] is None
    assert r["passband_note_agree_frames"] == 0


def test_only_pure_band_pass_is_counted():
    lp = side([10], [])                           # low-pass throughout
    assert F.passband_note_relative(lp, lp, N)["passband_note_orig_frames"] == 0
    combo = side([10], [])
    combo.filter.passband_events[:] = [(0, 3)]    # L+B
    assert F.passband_note_relative(combo, combo, N)["passband_note_orig_frames"] == 0


def test_the_attack_counted_is_on_a_routed_voice():
    # voice 1 attacks at 12 but only voice 0 is routed: offset is from 10
    o = side([10], [13])
    o.filter.ctrl_events[:] = [(0, 1)]
    o[1].attack_frames[:] = [12]
    o[1].attacks[:] = ["C-4"]
    ref = side([10], [13])
    assert F.passband_note_relative(o, ref, N)["passband_note"] == 1.0
    routed = side([10], [13])
    routed.filter.ctrl_events[:] = [(0, 3)]
    routed[1].attack_frames[:] = [12]
    routed[1].attacks[:] = ["C-4"]
    # with voice 1 routed too, the blip is 1 frame from its last attack
    assert F.passband_note_relative(routed, ref, N)["passband_note"] == 0.0


def test_an_unnamed_attack_anchors_a_blip():
    named = side([10], [13])
    unnamed = side([], [13], unnamed=[10])
    assert F.passband_note_relative(named, unnamed, N)["passband_note"] == 1.0


def test_a_blip_before_any_attack_is_skipped():
    r = F.passband_note_relative(side([20], [5]), side([20], [5]), N)
    assert r["passband_note_orig_frames"] == 0 and r["passband_note"] is None


def test_the_window_bounds_the_read():
    o = side([10], [13, 150])
    assert F.passband_note_relative(o, o, 100)["passband_note_orig_frames"] == 1


def test_the_dimension_is_registered():
    d = next(d for d in F.DIMENSIONS if d.key == "passband_note")
    assert d.column == "bnote" and d.kind == "fraction"
    assert "$D418" in d.reads and "band-pass" in d.of
    assert d.fmt(d.value({"passband_note": 0.5})) == "50%"
    assert d.fmt(d.value({})) == "-"


def test_the_column_reaches_the_report_beside_band():
    from test_fidelity import _Args, _row
    row = _row("A.sid", "measured", 1.0)
    row["passband_note"] = 0.25
    text = F.report([row], _Args())
    header = next(l for l in text.splitlines() if l.startswith("| File |"))
    assert " band | bnote | len |" in header
    body = next(l for l in text.splitlines() if l.startswith("| A.sid |"))
    assert " 25% |" in body
