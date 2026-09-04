#!/usr/bin/env python3
"""The rendered-audio measure: does our conversion SOUND like the original?

Every other column of FIDELITY.md reads SID registers through siddump. This
reads the WAV `sidplayfp` renders from each side, so it sees what those
cannot: timbre, filter movement, envelope shape and the volume nibble.

Two numbers, deliberately separated:

* `aud`  -- timbre. Log-mel spectrogram per side (64 bands, 20 Hz-8 kHz,
  2048-point FFT, 128-sample hop, ~345 frames/s), each frame peak-normalised
  so level cancels, then a per-frame L1 distance in dB over SPEC_RANGE_DB,
  averaged over the frames either side sounds. 1.0 is identical.
* `loud` -- level. Per-frame RMS in dB; `loud` is the envelope agreement over
  LOUD_RANGE_DB and `loud_ratio` the overall level of ours over the original's
  (1.0 is the same level). The first instrument in this repo that reads the
  master-volume nibble.

Shared silence carries no weight (`_graded_agreement`'s rule): a rest both
sides keep is not agreement. A frame silent on one side only scores 0.

**Alignment is estimated from the loudness envelope, never fitted to the
score.** `align` cross-correlates the two RMS envelopes inside a bounded
window around a prior (the packed player's startup lag, when the caller has
it) and returns the lag that maximises envelope correlation -- not the lag
that maximises `aud`, which could only ever raise it.

Blind spots, stated so nobody reads a number here as a listening test: it
does not know which side is WRONG; it cannot see a right note at the wrong
time beyond the alignment window (`drift` and `len` do); and a change that
removes events can raise it, the same trap as `wave` (section 7.eee), so it
is read beside both sides' attack counts.

numpy is a HARNESS dependency only. `python/h2g/` stays stdlib.
"""
from __future__ import annotations

import hashlib
import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

N_FFT = 2048
# THE HOP IS THE NOISE FLOOR. Measured at v0.5.453 and changed 512 -> 128 on
# the strength of it. `aud` compares log-mel frames on a fixed grid, and
# `align` can only correct by a WHOLE hop -- so two renders whose time origins
# differ by less than one hop carry a residue no alignment can remove, and
# that residue IS what sound_calibrate.py's shift check measures. Proved
# rather than argued: shifting a real render by an EXACT multiple of the hop
# moves `aud` by **0.0000** on all four approved tunes, while the 3 ms and
# 20 ms shifts the calibration uses (0.26 and 1.72 hops at the old 512) moved
# it by up to 0.0343.
#
# So the floor scales with the grid, and it does:
#
#     HOP  512 (11.61 ms)  floor 0.0343      HOP  128 (2.90 ms)  floor 0.0069
#     HOP  256 ( 5.80 ms)  floor 0.0143      HOP   64 (1.45 ms)  floor 0.0052
#
# 128 is the knee, and the reason is DETECTION POWER rather than any
# threshold: the three documented fixes sound_calibrate.py tests against move
# `aud` by 0.005 to 0.019, which a 0.0343 floor cannot see at all. It is not
# a metric change bought with a score change -- over the 89 cached corpus
# pairs, `aud` moves by a mean of **+0.0007** and is flat (|d| <= 0.005) on
# **84 of 89**, so the columns say what they said before at four times the
# time resolution. The cost is CPU: featurise-plus-compare over the corpus
# goes 31 s -> 119 s, against a corpus pass whose 15m46s is dominated by
# rendering.
HOP = 128
N_MELS = 64
F_MIN, F_MAX = 20.0, 8000.0
SILENCE_DB = -60.0      # a frame below this RMS is silent
SPEC_RANGE_DB = 60.0    # the dynamic range a log-mel frame is read over
LOUD_RANGE_DB = 40.0    # the range an envelope difference is scored over


@dataclass
class Features:
    logmel: np.ndarray   # [T, N_MELS], dB, per-frame peak at 0
    rms_db: np.ndarray   # [T]
    hop_s: float


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    """16-bit PCM to float32 in [-1, 1], channels averaged."""
    with wave.open(str(path), "rb") as w:
        nch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: {8 * width}-bit PCM, expected 16")
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if nch > 1:
        pcm = pcm.reshape(-1, nch).mean(axis=1)
    return pcm, rate


def _hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10.0 ** (np.asarray(m) / 2595.0) - 1.0)


def _mel_filterbank(rate: int) -> np.ndarray:
    """[N_MELS, N_FFT // 2 + 1] triangular filters, HTK mel scale."""
    edges = _mel_to_hz(np.linspace(_hz_to_mel(F_MIN), _hz_to_mel(F_MAX), N_MELS + 2))
    bins = np.floor((N_FFT + 1) * edges / rate).astype(int)
    fb = np.zeros((N_MELS, N_FFT // 2 + 1))
    for m in range(N_MELS):
        lo, mid, hi = bins[m], bins[m + 1], bins[m + 2]
        if mid == lo:
            mid += 1
        if hi <= mid:
            hi = mid + 1
        fb[m, lo:mid] = (np.arange(lo, mid) - lo) / (mid - lo)
        fb[m, mid:hi] = (hi - np.arange(mid, hi)) / (hi - mid)
    return fb


def features(samples: np.ndarray, rate: int) -> Features:
    x = np.asarray(samples, dtype=np.float32)
    if len(x) < N_FFT:
        x = np.pad(x, (0, N_FFT - len(x)))
    n = 1 + (len(x) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(N_FFT)[None, :]
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    mel = power @ _mel_filterbank(rate).T
    logmel = 10.0 * np.log10(mel + 1e-12)
    logmel = logmel - logmel.max(axis=1, keepdims=True)       # level cancels
    rms = np.sqrt(np.mean(x[idx] ** 2, axis=1))
    rms_db = 20.0 * np.log10(rms + 1e-9)
    return Features(logmel, rms_db, HOP / rate)


def _sounding(f: Features) -> np.ndarray:
    return f.rms_db > SILENCE_DB


def align(a: Features, b: Features, prior_s: float = 0.0,
          window_s: float = 0.5) -> int:
    """Hops to delay `a` by so its envelope lines up with `b`'s.

    Bounded search around `prior_s`; objective is the normalised
    cross-correlation of the baseline-removed envelopes, clipped at
    SILENCE_DB so a long rest does not dominate -- with `b` extended by
    SILENCE_DB beyond its own recorded extent, so a candidate lag that would
    slide the compared window off either end of `b` is scored against real
    silence there, not against a shortened window.

    RETRACTED from a first version that subtracted each side's own MEAN
    before correlating, per-signal, which is the textbook normalisation for
    this kind of search. It fails outright on a sustained, un-faded tone --
    a real corpus case (a note that starts the instant the packed player's
    startup lag ends): such a tone's envelope has no variance anywhere
    inside its own extent, so subtracting ITS OWN mean drives it to
    (numerically) the zero vector, discarding the one fact the envelope
    carries -- that it is uniformly loud -- and leaving the search to pick a
    lag from floating-point noise. Measured on exactly that construction (a
    plain 440 Hz tone against a copy delayed by 0.2 s): the old form
    returned a lag translating to 0.49 s, 20x its own 2-hop tolerance, and
    every re-run inside the same bounded window landed on a different wrong
    answer as the noise pattern shifted. Subtracting the fixed SILENCE_DB
    floor instead keeps a uniformly-loud signal uniformly large (not zeroed
    by its own constancy), and padding `b` with real silence rather than
    cropping the window is what lets that constant signal anchor against
    `b`'s onset at all: cropping (the first version's other habit) discards
    precisely the tail of `a` that would otherwise line up with the padding.
    Re-run on the same construction this returns 0.197 s, within tolerance,
    and the corpus case this exists for -- delayed, unfading onsets -- is
    exactly what a per-signal mean would fail hardest on.

    Negative means `b` is the late one.
    """
    ea = np.maximum(a.rms_db, SILENCE_DB) - SILENCE_DB
    eb = np.maximum(b.rms_db, SILENCE_DB) - SILENCE_DB
    n = len(ea)
    prior = int(round(prior_s / a.hop_s))
    span = int(math.ceil(window_s / a.hop_s))
    if n < 4:
        return prior
    pad = span + n + 1
    eb_p = np.pad(eb, (pad, pad), constant_values=0.0)
    ea_norm = float(np.linalg.norm(ea))
    best, best_lag = -np.inf, prior
    for lag in range(prior - span, prior + span + 1):
        start = pad + lag
        y = eb_p[start: start + n]
        denom = ea_norm * float(np.linalg.norm(y))
        c = float(np.dot(ea, y) / denom) if denom > 0 else 0.0
        if c > best:
            best, best_lag = c, lag
    return best_lag


def _overlap(a: Features, b: Features, lag: int):
    """The frame ranges of `a` and `b` that coincide once `a` is delayed by `lag`."""
    if lag >= 0:
        n = min(a.logmel.shape[0], b.logmel.shape[0] - lag)
        return slice(0, n), slice(lag, lag + n)
    n = min(a.logmel.shape[0] + lag, b.logmel.shape[0])
    return slice(-lag, -lag + n), slice(0, n)


def compare_features(a: Features, b: Features, lag_hops: int) -> dict:
    """Score two aligned feature sets.

    THE BAND DENOMINATOR IS THE BANDS THAT SOUND, NOT ALL 64 -- and the plan
    this module was transcribed from (`docs/superpowers/plans/
    2026-09-01-ab-fidelity-automation.md`, prose at :234 and code at :391-394)
    says `np.mean(..., axis=1)` over all of them. RETRACTED, on the plan's own
    stated rule: its docstring for this module reads "Shared silence carries no
    weight (`_graded_agreement`'s rule): a rest both sides keep is not
    agreement", and the all-bands mean breaks exactly that rule one level down.
    Each frame is peak-normalised, so a harmonically sparse signal -- a sine, or
    a SID voice -- leaves most of a 64-band spectrum at the `-SPEC_RANGE_DB`
    floor on BOTH sides, where it contributes perfect agreement it has not
    earned. Measured on the plan's own 440 Hz-vs-880 Hz case: **53 of 64 bands
    per frame, 82.8% of all band-frames, are shared floor**; the 11 live bands
    disagree by a mean of 33.2 dB, which diluted over 64 bands is 5.706 dB and
    reads `aud` 0.9049 -- above the plan's own `< 0.9` assertion for two tones
    an octave apart. Over the live bands it reads 0.447.

    Neither test that must read exactly 1.0 can be affected, which is why this
    is safe as well as right: the peak normalisation makes a scaled copy's
    log-mel identical to its original's, so identity and half-amplitude are
    band-for-band equal and score 1.0 whatever the denominator counts.

    A frame silent on ONE side still scores 0 outright (the `both` mask), and a
    frame silent on both still leaves numerator and denominator alike (`either`)
    -- the frame-level rules are the plan's and are unchanged.
    """
    sa, sb = _overlap(a, b, lag_hops)
    la, lb = a.logmel[sa], b.logmel[sb]
    ra, rb = a.rms_db[sa], b.rms_db[sb]
    on_a, on_b = ra > SILENCE_DB, rb > SILENCE_DB
    either = on_a | on_b
    n = int(either.sum())
    if n == 0:
        return {"aud": None, "loud": None, "loud_ratio": None, "sound_frames": 0}
    both = on_a & on_b
    # Timbre: per-frame L1 in dB over the read range, 0 where one side is silent.
    la_c = np.maximum(la, -SPEC_RANGE_DB)
    lb_c = np.maximum(lb, -SPEC_RANGE_DB)
    live = (la > -SPEC_RANGE_DB) | (lb > -SPEC_RANGE_DB)
    n_live = live.sum(axis=1)
    d = (np.sum(np.abs(la_c - lb_c) * live, axis=1)
         / np.maximum(n_live, 1) / SPEC_RANGE_DB)
    agree = np.where(both, 1.0 - np.minimum(d, 1.0), 0.0)
    aud = float(agree[either].mean())
    # Level: envelope distance, and the overall ratio over frames both sound.
    ra_c = np.maximum(ra, SILENCE_DB)
    rb_c = np.maximum(rb, SILENCE_DB)
    ld = np.minimum(np.abs(ra_c - rb_c) / LOUD_RANGE_DB, 1.0)
    loud = float(np.where(both, 1.0 - ld, 0.0)[either].mean())
    ratio = (float(10.0 ** ((rb_c[both].mean() - ra_c[both].mean()) / 20.0))
             if both.any() else 0.0)
    return {"aud": aud, "loud": loud, "loud_ratio": ratio, "sound_frames": n}


def compare_wavs(a: Path, b: Path, prior_s: float = 0.0) -> dict:
    """`a` is the original, `b` ours. Aligns on the envelope, then scores."""
    xa, ra = read_wav_mono(a)
    xb, rb = read_wav_mono(b)
    if ra != rb:
        raise ValueError(f"sample rates differ: {ra} vs {rb}")
    fa, fb = features(xa, ra), features(xb, rb)
    lag = align(fa, fb, prior_s=prior_s)
    got = compare_features(fa, fb, lag)
    got["sound_lag_ms"] = round(1000.0 * lag * fa.hop_s, 1)
    return got


def content_key(path: Path) -> str:
    """sha1[:12] of a file's bytes -- the cache key for a render of it."""
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:12]


import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import listen  # noqa: E402  -- the renderer, so both sides use one engine

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "build" / "audio"


def render_cached(sid: Path, seconds: int, subtune: int, tag: str,
                  cache: Path = AUDIO_DIR,
                  renderer=listen.render_sidplayfp) -> Path | None:
    """The WAV of `sid`, rendered once per distinct set of bytes.

    Keyed on CONTENT, never on a version or a path: a `.sng` that converts
    identically on two commits is one render, and one that changed is a new
    one however it is named. That is the same rule `approved.json` keys its
    verdicts by, and for the same reason.
    """
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{tag}.{content_key(sid)}.s{subtune}.t{seconds}.wav"
    if out.exists() and out.stat().st_size > listen.EMPTY_WAV:
        return out
    ok = renderer(Path(sid), out, seconds, subtune)
    if not ok or not out.exists() or out.stat().st_size <= listen.EMPTY_WAV:
        out.unlink(missing_ok=True)
        return None
    return out


def compare_sids(orig: Path, ours: Path, seconds: int, sub_orig: int,
                 sub_ours: int, prior_s: float = 0.0,
                 cache: Path = AUDIO_DIR,
                 renderer=listen.render_sidplayfp) -> dict:
    """Render both sides with ONE renderer and score them.

    A pair split across two emulators would measure the emulators; the
    `renderer` is a single callable for exactly that reason (listen.py's
    `pick_renderer` rule). A failed render names its side rather than
    scoring a silent WAV against music.
    """
    a = render_cached(orig, seconds, sub_orig, "orig", cache, renderer)
    if a is None:
        return {"sound_failed": "orig"}
    b = render_cached(ours, seconds, sub_ours, "ours", cache, renderer)
    if b is None:
        return {"sound_failed": "ours"}
    got = compare_wavs(a, b, prior_s=prior_s)
    got["sound_cache"] = [a.name, b.name]
    return got
