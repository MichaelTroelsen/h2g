"""`depth` at multiplier > 1: the frame reading keeps 1 call in m.

Game_Killer record $19BA at -S9 read 1.27x in the siddump `depth` column and
1.49x per call under `--vice` (cycle 6, historical). `depth_per_call_compare`
reads OUR side once per play call; the original stays at frame resolution.
"""
import fidelity
from fidelity import Voice

KEY = 0x0A9A
FRAMES = 200


def _voice(freqs):
    """One note from row 0; the ADSR key set on row 0, no gate register."""
    v = Voice()
    v.attack_frames = [0]
    v.freq_events = [(i, f) for i, f in enumerate(freqs)
                     if i == 0 or f != freqs[i - 1]]
    v.adsr_events = [(0, KEY)]
    return v


def _triangle(n, period, lo, hi):
    half = period // 2
    out = []
    for i in range(n):
        ph = i % period
        up = ph if ph <= half else period - ph
        out.append(lo + (hi - lo) * up // half)
    return out


def test_call_reading_matches_a_same_speed_triangle():
    m = 4
    a = [_voice(_triangle(FRAMES, 12, 4000, 4400))]
    calls = [_voice(_triangle(FRAMES * m, 12 * m, 4000, 4400))]
    call = fidelity.depth_per_call_compare(a, calls, FRAMES, {KEY}, m)
    assert abs(call["depth_call_ratio"] - 1.0) < 0.05
    assert call["depth_call_instruments"] == 1


def test_call_reading_reports_what_frame_sampling_understates():
    m = 4
    a = [_voice(_triangle(FRAMES, 8, 4000, 4400))]
    calls = _triangle(FRAMES * m, 8 * m, 4000, 4400)
    # siddump -m4 prints one row per frame; phase 1 of each frame lands on a
    # narrow part of the cycle.
    frame = fidelity.depth_compare(a, [_voice(calls[1::m])], FRAMES, {KEY})
    call = fidelity.depth_per_call_compare(a, [_voice(calls)], FRAMES,
                                           {KEY}, m)
    assert frame["depth_ratio"] < 0.9
    assert call["depth_call_ratio"] > 0.95
    assert call["depth_call_ratio"] > frame["depth_ratio"]


def test_keys_are_prefixed_and_refusals_pass_through():
    a = [_voice(_triangle(FRAMES, 12, 4000, 4400))]
    c = [_voice(_triangle(FRAMES * 3, 36, 4000, 4400))]
    assert fidelity.depth_per_call_compare(a, c, FRAMES, None, 3) \
        == {"depth_call_refusal": "no-population"}
    assert fidelity.depth_per_call_compare(a, c, FRAMES, set(), 3) \
        == {"depth_call_refusal": "gated"}
    r = fidelity.depth_per_call_compare(a, c, FRAMES, {KEY}, 3)
    assert set(r) == {"depth_call_ratio", "depth_call_orig",
                      "depth_call_ours", "depth_call_instruments"}


def test_the_call_axis_is_charged_in_calls(monkeypatch):
    seen = {}
    real = fidelity._depth_compare_sided

    def spy(*args):
        seen["args"] = args
        return real(*args)
    monkeypatch.setattr(fidelity, "_depth_compare_sided", spy)
    a = [_voice(_triangle(FRAMES, 12, 4000, 4400))]
    c = [_voice(_triangle(FRAMES * 5, 60, 4000, 4400))]
    fidelity.depth_per_call_compare(a, c, FRAMES, {KEY}, 5)
    args = seen["args"]
    assert args[2:4] == (FRAMES, FRAMES * 5)       # own lengths
    assert args[5:7] == (1, fidelity.vice_skip_span(5))
    assert args[8:10] == (1, 5)                    # per_frame orig, ours


def test_depth_per_call_declines_when_the_trace_fails(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("no -m")
    monkeypatch.setattr(fidelity, "run_siddump", boom)
    assert fidelity.depth_per_call([], tmp_path / "x.sid", 10, 0, "siddump",
                                   {KEY}, 3) == {}


def test_depth_per_call_traces_one_call_a_row_over_m_windows(monkeypatch,
                                                              tmp_path):
    seen = {}

    def fake(sid, seconds, sub, exe, calls=1, **k):
        seen.update(seconds=seconds, calls=calls)
        return [_voice(_triangle(seconds * 50, 36, 4000, 4400))]
    monkeypatch.setattr(fidelity, "run_siddump", fake)
    r = fidelity.depth_per_call([_voice(_triangle(500, 12, 4000, 4400))],
                                tmp_path / "x.sid", 10, 0, "siddump",
                                {KEY}, 3)
    assert seen == {"seconds": 30, "calls": 1}
    assert "depth_call_ratio" in r
