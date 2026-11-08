"""The sidplayfp build the harness renders with must not repeat buffer heads.

sidplayfp 2.15.2's frontend (`Mixer::begin`, src/mixer.cpp) copies the samples
its last `doMix` could not fit to the head of the next one-second buffer and
never empties that store: a later boundary that leaves no remainder copies the
same samples AGAIN. The first R samples (R = one engine call, 61-78 seen) of
that second repeat the head of the second before, and the music is R samples
late for good. Which boundaries do it depends on the machine's cycle phase
against the buffer grid, so F3 and F3Z -- the same music packed with a
one-cycle layout difference -- render with lag 0 for 94 s and then 155 samples
apart, and `aud` scores that as music. 2.16.2 empties the store.
C:/t/sidplayfp-getbufsize-overflow-render-fix/finding.md has the evidence.
"""
from pathlib import Path

import numpy as np
import pytest

import listen as L
import sound

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FRAMES = 44100                      # WavFile::open: cfg.bufSize = frequency
HAVE_EXE = Path(L.SIDPLAYFP).exists()
needs_exe = pytest.mark.skipif(not HAVE_EXE, reason="sidplayfp not installed")


def repeated_heads(x: np.ndarray, min_run: int = 24, max_run: int = 512):
    """`(frame, run)` of every run of frames equal to the frames one buffer
    earlier -- the signature of a buffer head written twice. Digital silence
    (a constant run) also repeats and is not a defect; a run of 24 dithered
    music samples repeating by chance is."""
    eq = np.zeros(len(x), dtype=bool)
    eq[FRAMES:] = x[FRAMES:] == x[:-FRAMES]
    edge = np.diff(eq.astype(np.int8), prepend=0, append=0)
    out = []
    for q, e in zip(np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)):
        if min_run <= e - q <= max_run and x[q:e].min() != x[q:e].max():
            out.append((int(q), int(e - q)))
    return out


def _pcm(wav: Path) -> np.ndarray:
    return np.frombuffer(wav.read_bytes()[44:], dtype="<i2")


def _lag(a, b, i, n=8820, rng=400):
    s = a[i:i + n].astype(float)
    seg = b[i - rng:i + n + rng].astype(float)
    size = 1 << (len(seg) + len(s) - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(s, size)),
                     size)[:len(seg) - len(s) + 1]
    return int(np.argmax(c)) - rng


def test_the_detector_sees_a_repeated_head_and_not_a_clean_stream():
    """SABOTAGE TARGET: make `repeated_heads` return [] and the planted repeat
    below goes unseen -- and with it the two renders tests, which would pass
    on any build."""
    rng = np.random.default_rng(1)
    x = rng.integers(-3000, 3000, 4 * FRAMES).astype("<i2")
    assert repeated_heads(x) == []
    x[2 * FRAMES:2 * FRAMES + 70] = x[FRAMES:FRAMES + 70]
    assert repeated_heads(x) == [(2 * FRAMES, 70)]
    x[:] = 0                                   # silence repeats; not a defect
    assert repeated_heads(x) == []


def test_the_build_is_part_of_the_cache_key(tmp_path, monkeypatch):
    """SABOTAGE TARGET: drop `listen.SIDPLAYFP_BUILD` from `content_key` and a
    WAV cached from 2.15.2 is served as a hit for 2.16.2."""
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    new = sound.content_key(sid)
    monkeypatch.setattr(L, "SIDPLAYFP_BUILD", "2.15.2")
    assert sound.content_key(sid) != new


@needs_exe
def test_a_render_repeats_no_buffer_head(tmp_path):
    """SABOTAGE TARGET: point `listen.SIDPLAYFP` at `SIDPLAYFP_2_15_2` -- the
    short-circuit that puts the old build back -- and this fails: Commando's
    sixth second starts with a 62-frame repeat of the fifth's head."""
    wav = tmp_path / "commando.wav"
    assert L.render_sidplayfp(ROOT / "Commando.sid", wav, 12, 0)
    assert repeated_heads(_pcm(wav)) == []


@needs_exe
def test_two_layouts_of_one_tune_stay_in_step(tmp_path):
    """SABOTAGE TARGET: as above. F3 / F3Z (Confuzion packed two ways, one CPU
    cycle apart) render with lag 0 for 85 s and 76 samples apart from 86 s on
    at `-t110` under 2.15.2 (one more repeated head in F3 than in F3Z); under
    2.16.2 the lag is 0 or -1 for the whole of a 307 s render."""
    f3, f3z = HERE / "fixtures" / "F3.sid", HERE / "fixtures" / "F3Z.sid"
    a, b = tmp_path / "f3.wav", tmp_path / "f3z.wav"
    assert L.render_sidplayfp(f3, a, 110, 0)
    assert L.render_sidplayfp(f3z, b, 110, 0)
    x, y = _pcm(a), _pcm(b)
    for second in range(5, 106, 3):
        assert abs(_lag(x, y, second * FRAMES)) <= 1, second
