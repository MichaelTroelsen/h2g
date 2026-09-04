"""`sound.py`: the rendered-audio measure.

Synthetic signals only. Every test here has an answer known before the
measurement is taken -- identity is 1.0, a scaled copy is the same timbre at
a known level, an injected delay is recovered -- because the metric will later
decide whether a human approval survives a change, and a metric that is not
pinned on cases with a known answer cannot be trusted with that.
"""
import math
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

import sound

RATE = 44100


def _sine(seconds=2.0, hz=440.0, amp=0.5, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * math.pi * hz * t)).astype(np.float32)


def _write(path: Path, samples: np.ndarray, rate=RATE):
    pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def test_read_wav_mono_round_trips_a_sine(tmp_path):
    s = _sine(0.5)
    _write(tmp_path / "a.wav", s)
    got, rate = sound.read_wav_mono(tmp_path / "a.wav")
    assert rate == RATE
    assert got.shape == s.shape
    assert np.max(np.abs(got - s)) < 1e-3


def test_features_have_one_row_per_hop_and_64_bands():
    f = sound.features(_sine(1.0), RATE)
    assert f.logmel.shape[1] == 64
    assert f.logmel.shape[0] == f.rms_db.shape[0]
    # 128 samples = 2.90 ms. The value is load-bearing rather than incidental:
    # it sets the noise floor sound_calibrate.py measures (see HOP's own
    # comment), so a change here must be made deliberately and re-measured.
    assert sound.HOP == 128
    assert abs(f.hop_s - 128 / RATE) < 1e-9


def test_identity_scores_one():
    f = sound.features(_sine(), RATE)
    got = sound.compare_features(f, f, 0)
    assert got["aud"] == pytest.approx(1.0, abs=1e-6)
    assert got["loud"] == pytest.approx(1.0, abs=1e-6)
    assert got["loud_ratio"] == pytest.approx(1.0, abs=1e-6)


def test_a_scaled_copy_is_the_same_timbre_at_a_known_level():
    """`aud` is timbre and `loud` is level: halving the amplitude must leave
    `aud` at 1.0 and put `loud_ratio` at 0.5 -- otherwise the two columns
    measure one quantity twice."""
    a = sound.features(_sine(amp=0.5), RATE)
    b = sound.features(_sine(amp=0.25), RATE)
    got = sound.compare_features(a, b, 0)
    assert got["aud"] == pytest.approx(1.0, abs=1e-3)
    assert got["loud_ratio"] == pytest.approx(0.5, rel=0.02)
    assert got["loud"] < 1.0


def test_a_different_pitch_is_a_different_timbre():
    a = sound.features(_sine(hz=440.0), RATE)
    b = sound.features(_sine(hz=880.0), RATE)
    assert sound.compare_features(a, b, 0)["aud"] < 0.9


def test_both_silent_frames_carry_no_weight():
    """Two silent files agree about nothing: the column is absent, not 1.0.
    This is `_graded_agreement`'s rule from the register columns."""
    z = sound.features(np.zeros(RATE, dtype=np.float32), RATE)
    got = sound.compare_features(z, z, 0)
    assert got["aud"] is None and got["loud"] is None
    assert got["sound_frames"] == 0


def test_a_frame_silent_on_one_side_counts_fully_against():
    a = sound.features(_sine(), RATE)
    z = sound.features(np.zeros_like(_sine()), RATE)
    got = sound.compare_features(a, z, 0)
    assert got["aud"] == pytest.approx(0.0, abs=1e-6)
    assert got["sound_frames"] == a.logmel.shape[0]


def test_align_recovers_an_injected_delay():
    s = _sine(2.0)
    delayed = np.concatenate([np.zeros(int(0.2 * RATE), dtype=np.float32), s])
    a, b = sound.features(s, RATE), sound.features(delayed, RATE)
    lag = sound.align(a, b, prior_s=0.0, window_s=0.5)
    assert abs(lag * a.hop_s - 0.2) <= 2 * a.hop_s


def test_align_is_bounded_by_its_window():
    """The search is bounded so that it cannot fit a lag to maximise the score:
    a delay outside the window is NOT found, by design."""
    s = _sine(2.0)
    delayed = np.concatenate([np.zeros(int(1.0 * RATE), dtype=np.float32), s])
    a, b = sound.features(s, RATE), sound.features(delayed, RATE)
    lag = sound.align(a, b, prior_s=0.0, window_s=0.5)
    assert abs(lag * a.hop_s) <= 0.5 + a.hop_s


def test_compare_wavs_aligns_then_scores(tmp_path):
    s = _sine(2.0)
    _write(tmp_path / "a.wav", s)
    _write(tmp_path / "b.wav", np.concatenate([np.zeros(int(0.1 * RATE), dtype=np.float32), s]))
    got = sound.compare_wavs(tmp_path / "a.wav", tmp_path / "b.wav")
    assert got["aud"] > 0.98
    assert abs(got["sound_lag_ms"] - 100.0) < 25.0


def _fake_renderer(samples_by_name: dict):
    """A renderer that writes a synthetic WAV keyed by the .sid's stem, and
    counts how often it was asked -- the cache's whole contract is that the
    second ask for the same bytes is free."""
    calls = []

    def render(sid, out, seconds, subtune, exe="", mute=()):
        calls.append(sid.name)
        _write(Path(out), samples_by_name[sid.stem])
        return True
    render.calls = calls
    return render


def test_render_cached_keys_on_content_and_renders_once(tmp_path):
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    r = _fake_renderer({"Tune": _sine(0.5)})
    a = sound.render_cached(sid, 1, 0, "orig", cache=tmp_path / "c", renderer=r)
    b = sound.render_cached(sid, 1, 0, "orig", cache=tmp_path / "c", renderer=r)
    assert a == b and a.exists()
    assert r.calls == ["Tune.sid"]
    assert sound.content_key(sid) in a.name and ".s0.t1.wav" in a.name


def test_render_cached_re_renders_when_the_bytes_change(tmp_path):
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    r = _fake_renderer({"Tune": _sine(0.5)})
    a = sound.render_cached(sid, 1, 0, "ours", cache=tmp_path / "c", renderer=r)
    sid.write_bytes(b"PSID-bytes-2")
    b = sound.render_cached(sid, 1, 0, "ours", cache=tmp_path / "c", renderer=r)
    assert a != b and len(r.calls) == 2


def test_render_cached_returns_none_when_the_renderer_fails(tmp_path):
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"x")
    assert sound.render_cached(sid, 1, 0, "orig", cache=tmp_path / "c",
                               renderer=lambda *a, **k: False) is None


def test_compare_sids_scores_the_two_renders(tmp_path):
    o, u = tmp_path / "O.sid", tmp_path / "U.sid"
    o.write_bytes(b"orig"), u.write_bytes(b"ours")
    r = _fake_renderer({"O": _sine(1.0), "U": _sine(1.0, amp=0.25)})
    got = sound.compare_sids(o, u, 1, 0, 0, cache=tmp_path / "c", renderer=r)
    assert got["aud"] > 0.99
    assert got["loud_ratio"] == pytest.approx(0.5, rel=0.02)
    assert len(got["sound_cache"]) == 2


def test_compare_sids_names_the_failed_side(tmp_path):
    o, u = tmp_path / "O.sid", tmp_path / "U.sid"
    o.write_bytes(b"orig"), u.write_bytes(b"ours")

    def only_orig(sid, out, seconds, subtune, exe="", mute=()):
        if sid.stem == "U":
            return False
        _write(Path(out), _sine(1.0))
        return True
    got = sound.compare_sids(o, u, 1, 0, 0, cache=tmp_path / "c", renderer=only_orig)
    assert got == {"sound_failed": "ours"}


def test_a_whole_hop_shift_is_invisible_and_a_sub_hop_shift_is_not():
    """The noise floor IS the hop, and this is the measurement that says so.

    `align` corrects by a whole hop, so two renders offset by an exact
    multiple of one align perfectly and `aud` must read exactly 1.0. Offset
    them by HALF a hop and no integer lag can fix it -- the residue is what
    sound_calibrate.py's shift check reports as the floor, and it is why HOP
    was taken from 512 to 128 (floor 0.0343 -> 0.0069) at v0.5.453.

    Pinning both halves matters: the first alone would pass on a metric that
    ignored time entirely, and the second alone would pass on one that was
    merely noisy.
    """
    s = _sine(2.0)
    a = sound.features(s, RATE)

    whole = np.concatenate([np.zeros(sound.HOP, dtype=np.float32), s])
    b = sound.features(whole, RATE)
    got = sound.compare_features(a, b, sound.align(a, b))
    assert got["aud"] == pytest.approx(1.0, abs=1e-9), (
        "an exact one-hop offset must be perfectly correctable")

    half = np.concatenate([np.zeros(sound.HOP // 2, dtype=np.float32), s])
    c = sound.features(half, RATE)
    got_half = sound.compare_features(a, c, sound.align(a, c))
    assert got_half["aud"] < 1.0, (
        "a half-hop offset is not representable as an integer lag, so it must "
        "leave a residue -- if this passes, the metric has stopped reading time")
