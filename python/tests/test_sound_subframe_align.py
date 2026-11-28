"""`sound.align(..., subframe=True)`: the sub-frame remainder of a multispeed
file's startup lag, estimated from the loudness envelopes.

Measured at v0.5.685 on Las_Vegas_Video_Poker (`-S4`): `startup_lag` is 5 whole
frames (34 hops) but the packed player's real onsets trail that by 0.82 frame
(40 hops), because the trace groups a frame's `-S` calls and a note starts at
call `c` of them. `aud` read .9184 at the prior and .9484 at the envelope's
lag, and the envelope lag is the same from a +-1 frame window to a +-0.5 s one.
C:/t/listen-r2-las-vegas-video-poker/census_lag2.py is the corpus A/B.
"""
import math

import numpy as np
import pytest

import sound

RATE = 44100
HOP_FRAMES = 0.02  # one PAL frame, the prior's unit


def _gated_tone(seconds=3.0, period=0.25, duty=0.6, hz=330.0):
    """A tone gated on and off, so the loudness envelope has edges to find."""
    t = np.arange(int(seconds * RATE)) / RATE
    gate = ((t % period) < period * duty).astype(np.float32)
    return (0.4 * np.sin(2 * math.pi * hz * t) * gate).astype(np.float32)


def _delay(x, seconds):
    n = int(round(seconds * RATE))
    return np.concatenate([np.zeros(n, dtype=np.float32), x])[:len(x)]


def _pair(extra_s):
    x = _gated_tone()
    return (sound.features(x, RATE),
            sound.features(_delay(x, 5 * HOP_FRAMES + extra_s), RATE))


def test_the_default_still_uses_the_whole_frame_prior():
    a, b = _pair(0.7 * HOP_FRAMES)
    prior = 5 * HOP_FRAMES
    assert sound.align(a, b, prior_s=prior) == int(round(prior / a.hop_s))


def test_subframe_finds_the_remainder_the_prior_cannot_carry():
    extra = 0.7 * HOP_FRAMES
    a, b = _pair(extra)
    prior = 5 * HOP_FRAMES
    at_prior = sound.align(a, b, prior_s=prior)
    found = sound.align(a, b, prior_s=prior, subframe=True)
    want = (prior + extra) / a.hop_s
    assert abs(found - want) <= 1.0
    assert found > at_prior
    # and it is the better alignment on the objective it was not fitted to
    assert (sound.compare_features(a, b, found)["aud"]
            > sound.compare_features(a, b, at_prior)["aud"] + 0.01)
    assert (sound.compare_features(a, b, found)["loud"]
            > sound.compare_features(a, b, at_prior)["loud"])


def test_subframe_is_bounded_by_one_frame_around_the_prior():
    """A delay a whole second past the prior is NOT chased: the search is the
    prior's own +-PRIOR_WINDOW_S, so it cannot wander to a better-scoring hop."""
    a, b = _pair(1.0)
    prior = 5 * HOP_FRAMES
    found = sound.align(a, b, prior_s=prior, subframe=True)
    span = int(math.ceil(sound.PRIOR_WINDOW_S / a.hop_s))
    centre = int(round(prior / a.hop_s))
    assert centre - span <= found <= centre + span


def test_subframe_without_a_prior_is_the_wide_search_it_always_was():
    a, b = _pair(0.0)
    assert (sound.align(a, b, subframe=True)
            == sound.align(a, b, subframe=False))


def test_compare_wavs_threads_the_flag_to_the_alignment(tmp_path):
    import wave

    x = _gated_tone()
    y = _delay(x, 5 * HOP_FRAMES + 0.7 * HOP_FRAMES)
    for name, s in (("a.wav", x), ("b.wav", y)):
        pcm = np.clip(s * 32767, -32768, 32767).astype("<i2").tobytes()
        with wave.open(str(tmp_path / name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
    plain = sound.compare_wavs(tmp_path / "a.wav", tmp_path / "b.wav",
                               prior_s=5 * HOP_FRAMES)
    sub = sound.compare_wavs(tmp_path / "a.wav", tmp_path / "b.wav",
                             prior_s=5 * HOP_FRAMES, subframe=True)
    assert sub["sound_lag_ms"] > plain["sound_lag_ms"] + 5.0
    assert sub["aud"] > plain["aud"]


def test_aud_voices_columns_passes_subframe_only_when_asked():
    import fidelity

    seen = []

    def fake(*a, **kw):
        seen.append(dict(kw))
        return {"aud": 0.9}

    fidelity.aud_voices_columns("o", "p", 10, 0, 0, [0, 1, 2], prior_s=0.1,
                                compare=fake)
    assert all("subframe" not in kw for kw in seen) and len(seen) == 3
    seen.clear()
    fidelity.aud_voices_columns("o", "p", 10, 0, 0, [0, 1, 2], prior_s=0.1,
                                compare=fake, subframe=True)
    assert all(kw.get("subframe") is True for kw in seen) and len(seen) == 3
