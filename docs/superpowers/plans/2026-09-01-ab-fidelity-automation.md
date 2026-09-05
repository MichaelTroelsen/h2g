# A/B Fidelity Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fewer listening sessions — an audio-domain measure of the rendered sound, human approvals that survive changes the measure can vouch for, a preset search that respects approvals by measurement instead of a hand-written veto list, and a ranked queue of causes that `/whattask` reads as a source.

**Architecture:** A new numpy module `python/sound.py` renders both sides with `sidplayfp` (cached by content sha under `build/audio/`) and scores log-mel timbre (`aud`) and RMS loudness (`loud`); `fidelity.py` gains those two `Dimension`s behind `--sound`. `python/approvals.py` computes whether the current build inherits a hand-written `approved.json` verdict, writing `build/approvals.json`, which `abpage.py` and `presets.py` read. `python/fidelity_queue.py` turns report rows, censuses, refusals and stale approvals into `docs/QUEUE.md`. Thresholds are never typed: `python/sound_calibrate.py` measures them into `build/sound_calibration.json`.

**Tech Stack:** Python 3.10+, numpy (harness only — `python/h2g/` stays stdlib), `sidplayfp` via `listen.render_sidplayfp`, `gt2reloc` via `fidelity.pack_sid`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-ab-fidelity-automation-design.md`

## Global Constraints

- **`python/h2g/` is not touched by any task.** Corpus byte-hash must read `MOVED 0` on every commit except Task 7's presets regeneration, where each moved file is named.
- **Existing `fidelity.py --audio` is SIDM2's onset-jitter tool and is NOT this work.** The new flag is `--sound`; the module is `python/sound.py`; the columns are `aud` and `loud`. Never reuse the `audio` row key.
- **`approved.json` is never written by a tool.** Tools write `build/approvals.json` only.
- **No threshold is a typed constant.** `approvals.py` refuses to inherit (status `uncalibrated`) when `build/sound_calibration.json` is absent.
- **Every commit:** run `python python/bump_version.py "<short description>"` before staging; run `graphify update .` after code changes; from `python/`, run `python survey.py <sid_dir> -o ../docs/SURVEY.md --legal-restart --gt2reloc` and `python presets.py <sid_dir> -o ../presets.json` (the structural pass; `--fidelity` only in Task 7). Commit messages end with the session's attribution block. **Commits happen only when the user has said to** — each task ends at a commit-ready state and its final step waits for that go-ahead.
- **Corpus:** `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files, 83 converting). Scratch: `C:/t`. Prefix every scratch file `ab_`.
- **Run tests from `python/`:** `python -m pytest tests/<file>.py -q`. The whole suite is 1695 passed / 2 skipped at HEAD `be759f0` and must not lose one.
- Renders need `sidplayfp` at `listen.SIDPLAYFP` and the C64 ROMs in `sidplayfp.ini` for RSIDs (README § Listening).
- `python/tools/siddump-rt/siddump.exe` is gitignored; a fresh worktree must copy it in before any fidelity run.

## Shared check: the corpus byte-hash

Save as `C:/t/ab_bytehash.py`. Run it from `python/` after every task: `python C:/t/ab_bytehash.py`. It converts every corpus file through the shipped presets on the working tree and on a clean `git archive HEAD` export and reports converted / refused / moved. Expected on every task but Task 7: `moved 0`.

```python
import hashlib, json, os, shutil, subprocess, sys, tarfile, io
from pathlib import Path
REPO = Path(r"C:/Users/mit/claude/h2g")
CORPUS = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
SCRATCH = Path(r"C:/t/ab_bytehash_export")

def export_head():
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    blob = subprocess.run(["git", "archive", "HEAD"], cwd=REPO, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(blob)).extractall(SCRATCH)
    shutil.copy(REPO / "python/tools/siddump-rt/siddump.exe", SCRATCH / "python/tools/siddump-rt/siddump.exe")

def hashes(pyroot: Path) -> dict:
    code = (
        "import json,hashlib,sys\nfrom pathlib import Path\n"
        "sys.path.insert(0,%r)\nimport fidelity as F\nfrom h2g.convert import convert\n"
        "doc=json.loads(Path(%r).read_text(encoding='utf-8'))\nout={}\n"
        "for p in sorted(Path(%r).rglob('*.sid')):\n"
        "    try: out[p.name]=hashlib.sha1(convert(str(p),log=lambda m:None,**F._preset_opts(doc,p.name))).hexdigest()[:12]\n"
        "    except Exception as e: out[p.name]='ERR '+type(e).__name__\n"
        "print(json.dumps(out))\n"
    ) % (str(pyroot), str(REPO / "presets.json"), str(CORPUS))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=pyroot)
    if r.returncode:
        sys.exit(r.stderr)
    return json.loads(r.stdout)

export_head()
old, new = hashes(SCRATCH / "python"), hashes(REPO / "python")
assert old.keys() == new.keys()
errs = [f for f, h in new.items() if h.startswith("ERR")]
assert len(errs) < 20, f"too many conversion errors to trust this: {errs}"
moved = [f for f in new if new[f] != old[f]]
print(f"converted {len(new) - len(errs)}  refused {len(errs)}  compared {len(new)}  moved {len(moved)}")
for f in moved:
    print("  MOVED", f, old[f], "->", new[f])
```

The `assert len(errs) < 20` is the rule that a probe wrapping `convert()` must assert its own success rate (CLAUDE.md): 12 of 95 corpus files refuse today, so 20 is headroom, not a target.

---

### Task 1: `sound.py` — features, alignment, and `compare_wavs`

**Files:**
- Create: `python/sound.py`
- Test: `python/tests/test_sound.py`

**Interfaces:**
- Consumes: nothing from this plan. numpy; stdlib `wave`.
- Produces:
  - `read_wav_mono(path: Path) -> tuple[np.ndarray, int]` — float32 samples in [-1, 1], sample rate.
  - `features(samples: np.ndarray, rate: int) -> Features` — `Features(logmel: np.ndarray[T, 64], rms_db: np.ndarray[T], hop_s: float)`.
  - `align(a: Features, b: Features, prior_s: float = 0.0, window_s: float = 0.5) -> int` — hops to delay `a` by so it lines up with `b` (negative: delay `b`).
  - `compare_features(a: Features, b: Features, lag_hops: int) -> dict` with keys `aud`, `loud`, `loud_ratio`, `sound_frames` (float|None, float|None, float|None, int).
  - `compare_wavs(a: Path, b: Path, prior_s: float = 0.0) -> dict` — the above plus `sound_lag_ms`.
  - `SILENCE_DB = -60.0`, `SPEC_RANGE_DB = 60.0`, `LOUD_RANGE_DB = 40.0` (module constants; these define the units of the columns, not thresholds — every decision threshold comes from Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_sound.py
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
    assert abs(f.hop_s - 512 / RATE) < 1e-9


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_sound.py -q`
Expected: `ModuleNotFoundError: No module named 'sound'`

- [ ] **Step 3: Write `python/sound.py`**

```python
#!/usr/bin/env python3
"""The rendered-audio measure: does our conversion SOUND like the original?

Every other column of FIDELITY.md reads SID registers through siddump. This
reads the WAV `sidplayfp` renders from each side, so it sees what those
cannot: timbre, filter movement, envelope shape and the volume nibble.

Two numbers, deliberately separated:

* `aud`  -- timbre. Log-mel spectrogram per side (64 bands, 20 Hz-8 kHz,
  2048-point FFT, 512-sample hop, ~86 frames/s), each frame peak-normalised
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
HOP = 512
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
    cross-correlation of the mean-removed envelopes, clipped at SILENCE_DB so
    a long rest does not dominate. Negative means `b` is the late one.
    """
    ea = np.maximum(a.rms_db, SILENCE_DB)
    eb = np.maximum(b.rms_db, SILENCE_DB)
    ea, eb = ea - ea.mean(), eb - eb.mean()
    prior = int(round(prior_s / a.hop_s))
    span = int(math.ceil(window_s / a.hop_s))
    best, best_lag = -np.inf, prior
    for lag in range(prior - span, prior + span + 1):
        if lag >= 0:
            x, y = ea[: len(ea) - lag] if lag else ea, eb[lag: lag + len(ea)]
        else:
            x, y = ea[-lag: -lag + len(eb)], eb[: len(eb) + lag]
        n = min(len(x), len(y))
        if n < 4:
            continue
        x, y = x[:n], y[:n]
        denom = float(np.linalg.norm(x) * np.linalg.norm(y))
        c = float(np.dot(x, y) / denom) if denom > 0 else 0.0
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
    d = np.mean(np.abs(la_c - lb_c), axis=1) / SPEC_RANGE_DB
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_sound.py -q`
Expected: `10 passed`

If `test_a_scaled_copy_...` fails on `loud_ratio`: the ratio is over frames both sound; check `SILENCE_DB` is not excluding the quieter copy (0.25 amplitude sine is about -15 dBFS, well above -60).

- [ ] **Step 5: Byte-hash and commit-ready**

Run: `cd python && python C:/t/ab_bytehash.py` — expected `moved 0`.
Run: `python -m pytest tests/ -q` — expected `1705 passed, 2 skipped` (1695 + 10).
Then, on the user's go-ahead: `python python/bump_version.py "sound.py: the rendered-audio measure, aud and loud"`, `graphify update .`, regenerate `SURVEY.md`/`presets.json` per Global Constraints, `git add python/sound.py python/tests/test_sound.py` plus the bumped files, commit.

---

### Task 2: `sound.py` — cached renders and `compare_sids`

**Files:**
- Modify: `python/sound.py` (append)
- Test: `python/tests/test_sound.py` (append)

**Interfaces:**
- Consumes: `listen.render_sidplayfp(sid, out, seconds, subtune, exe=listen.SIDPLAYFP, mute=())`, `sound.compare_wavs`, `sound.content_key`.
- Produces:
  - `AUDIO_DIR = ROOT / "build" / "audio"` where `ROOT = Path(__file__).resolve().parent.parent`.
  - `render_cached(sid: Path, seconds: int, subtune: int, tag: str, cache: Path = AUDIO_DIR, renderer=listen.render_sidplayfp) -> Path | None` — `cache / f"{tag}.{content_key(sid)}.s{subtune}.t{seconds}.wav"`, rendered only on a miss; `None` when the renderer fails.
  - `compare_sids(orig: Path, ours: Path, seconds: int, sub_orig: int, sub_ours: int, prior_s: float = 0.0, cache: Path = AUDIO_DIR, renderer=listen.render_sidplayfp) -> dict` — `compare_wavs` result plus `sound_cache: [orig_wav_name, ours_wav_name]`, or `{"sound_failed": "<side>"}` when a render fails.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/test_sound.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_sound.py -q -k "render_cached or compare_sids"`
Expected: 5 failures, `AttributeError: module 'sound' has no attribute 'render_cached'`

- [ ] **Step 3: Append to `python/sound.py`**

```python
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
```

Note the `tag` for a packed conversion is `"ours"` and for an approved render (Task 5) `"approved"`; the key makes the tag cosmetic — the same bytes under two tags are two files but one measurement.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_sound.py -q`
Expected: `15 passed`

- [ ] **Step 5: A real render, once, by hand**

Run from `python/` (needs `sidplayfp` and the corpus):
```
python -c "from pathlib import Path; import sound; print(sound.compare_sids(Path(r'C:/Users/mit/claude/h2g/Commando.sid'), Path(r'C:/Users/mit/claude/h2g/Commando.sid'), 10, 0, 0))"
```
Expected: `aud` 1.0, `loud` 1.0, `loud_ratio` 1.0, `sound_lag_ms` 0.0, and two identical-keyed files under `build/audio/` (same content, tags `orig` and `ours`). Time the call: this is the per-render cost the corpus pass multiplies by 166.

- [ ] **Step 6: Byte-hash and commit-ready**

`python C:/t/ab_bytehash.py` → `moved 0`. Full suite `1710 passed`. Add `build/audio/` to `.gitignore` (beside `build/listen`). Then, on go-ahead, bump (`"sound.py: cached renders keyed on content"`), graphify update, regenerate, commit `python/sound.py python/tests/test_sound.py .gitignore`.

---

### Task 3: `aud` and `loud` as report columns behind `--sound`

**Files:**
- Modify: `python/fidelity.py` — `DIMENSIONS` (after the `drift_per_1000` entry, ~line 3743), `SID_REGISTERS`/`NOT_MEASURED` neighbourhood (~3356-3400), `_measure` (insert immediately before `if args.register:` at ~line 4565), `main()` argparse (~line 6997, beside `--audio`), and the report's column-description bullets (find the `* **depth** --` bullet in `report()` and add two after it).
- Modify: `python/tests/test_fidelity.py` (append)
- Modify: `README.md` § *Fidelity* (the column list) and `docs/FIDELITY.md` (regenerated, Step 7).

**Interfaces:**
- Consumes: `sound.compare_sids(orig, ours, seconds, sub_orig, sub_ours, prior_s, cache, renderer)`; `_measure`'s locals `local_orig`, `packed`, `sub`, `row`, `seconds`, and `lag` (frames; set only in the non-`--vice` branch).
- Produces: row keys `aud`, `loud`, `loud_ratio`, `sound_lag_ms`, `sound_frames`, `sound_failed`; `AUDIO = "rendered audio"`; two `Dimension`s with keys `aud` and `loud`; CLI flag `--sound`.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/test_fidelity.py`:

```python
def test_the_sound_dimensions_read_rendered_audio_not_a_register():
    """They are the first columns computed from a WAV rather than from
    siddump, and the registry has to say so: `registers_read` must not gain a
    fake register, and `What this run compared` must name the audio."""
    keys = {d.key for d in fidelity.DIMENSIONS}
    assert {"aud", "loud"} <= keys
    aud = next(d for d in fidelity.DIMENSIONS if d.key == "aud")
    assert aud.reads == (fidelity.AUDIO,)
    assert aud.column == "aud" and aud.kind == "fraction"
    loud = next(d for d in fidelity.DIMENSIONS if d.key == "loud")
    assert loud.reads == (fidelity.AUDIO,)
    # The sentinel is not a SID register, so it must not appear as one.
    assert fidelity.AUDIO not in dict(fidelity.SID_REGISTERS)
    assert fidelity.registers_unread(keys) == []


def test_a_row_without_sound_prints_a_dash_and_says_why():
    """`--sound` is on demand. A row measured without it, or one whose render
    failed, reports the column absent rather than 0 -- an absent dimension
    recommends nothing."""
    row = _row("A.sid", "measured", 0.9)
    row.pop("aud", None)
    row.pop("loud", None)
    text = fidelity.report([row], _Args())
    line = next(l for l in text.splitlines() if l.startswith("| A.sid"))
    cols = [c.strip() for c in line.strip("|").split("|")]
    header = next(l for l in text.splitlines() if l.startswith("| File"))
    hcols = [c.strip() for c in header.strip("|").split("|")]
    assert cols[hcols.index("aud")] == "-"
    assert cols[hcols.index("loud")] == "-"
    assert "aud" not in fidelity.dimensions_present(row)


def test_the_sound_columns_are_described_in_the_report():
    text = fidelity.report([_row("A.sid", "measured", 1.0, 50, 50)], _Args())
    assert "* **aud** --" in text and "* **loud** --" in text
    assert "removes events" in text     # the 7.eee blind spot, stated
```

If `_row` does not accept `aud`/`loud` keys already, extend its fixture dict with `aud=0.9, loud=0.9` so `test_a_row_records_only_the_dimensions_it_actually_compared` keeps passing (it asserts a full row lists every dimension).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_fidelity.py -q -k sound`
Expected: 3 failures, `AttributeError: module 'fidelity' has no attribute 'AUDIO'`

- [ ] **Step 3: Add the sentinel and the Dimensions**

In `python/fidelity.py`, directly above `DIMENSIONS = (`:

```python
# Not a SID register: the two columns below are computed from the WAV that
# `sidplayfp` renders, not from siddump. Declared as their `reads` so `What
# this run compared` can say "rendered audio" honestly, and kept OUT of
# SID_REGISTERS so `registers_unread` does not report a register that does
# not exist.
AUDIO = "rendered audio"
```

Append to the `DIMENSIONS` tuple, after the `drift_per_1000` entry:

```python
    Dimension("aud", "aud", (AUDIO,), "fraction",
              "per-frame agreement of the rendered sound's log-mel spectrum, "
              "level removed -- timbre, filter, envelope shape. Absent unless "
              "the run was taken with --sound; both-silent frames carry no "
              "weight; it rises when events are removed, so read it beside "
              "the attack counts"),
    Dimension("loud", "loud", (AUDIO,), "fraction",
              "per-frame agreement of the rendered loudness envelope -- the "
              "first column that reads the master-volume nibble; `loud_ratio` "
              "in --json is our overall level over the original's"),
```

- [ ] **Step 4: Compute them in `_measure` and add the flag**

In `_measure`, immediately before `if args.register:`:

```python
    if getattr(args, "sound", False):
        # The rendered sound, both sides through one emulator. Prior for the
        # envelope alignment is the packed player's startup lag where the
        # trace measured one; the WAV alignment is still estimated from the
        # envelope inside a bounded window, never fitted to the score.
        import sound  # noqa: PLC0415 -- numpy, harness only
        prior = 0.02 * row.get("startup_lag", 0)
        row.update(sound.compare_sids(
            local_orig, packed, seconds, sub,
            row.get("matched_subtune", sub), prior_s=prior))
```

In `main()`'s parser, beside `--audio`:

```python
    p.add_argument("--sound", action="store_true",
                   help="also render both sides with sidplayfp and score the "
                        "SOUND: aud (timbre) and loud (level). Cached under "
                        "build/audio/ by content; the first corpus pass "
                        "renders 166 WAVs. Not SIDM2's --audio, which "
                        "measures onset jitter.")
```

In `report()`, after the `* **depth** --` bullet:

```python
        "* **aud** -- per-frame agreement of the rendered sound's log-mel "
        "spectrum with the level removed: timbre, filter movement, envelope "
        "shape -- what no register column can see. Both sides are rendered "
        "by `sidplayfp` at identical settings and aligned on their loudness "
        "envelopes inside a bounded window. Frames both sides spend silent "
        "carry no weight. It **rises when a change removes events**, exactly "
        "as **wave** does, so read it beside **retrig** and the two attack "
        "counts. `-` is a run taken without `--sound`, or a render that failed.",
        "* **loud** -- per-frame agreement of the rendered loudness envelope; "
        "the only column that reads the master-volume nibble. `--json` also "
        "carries `loud_ratio`, our overall level over the original's.",
```

- [ ] **Step 5: Run the tests**

Run: `cd python && python -m pytest tests/test_fidelity.py -q`
Expected: all pass (the registry/header test at ~line 1031 picks up the two new columns automatically; if it fails on the header, the column list in `report()` is built from `DIMENSIONS` and needs no edit — check the `_row` fixture instead).

- [ ] **Step 6: One file, for real**

Run from `python/`:
```
python fidelity.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob/Commando.sid" -t 60 --sound --presets ../presets.json --json C:/t/ab_commando_sound.json -o C:/t/ab_commando_sound.md
```
Expected: the row carries `aud`, `loud`, `sound_lag_ms`; `sound_lag_ms` is within one frame (±20 ms) of `startup_lag * 20`. If it is not, the envelope alignment and the attack-based lag disagree — record both in the run notes; do not change either.

- [ ] **Step 7: First corpus pass and the regenerated report**

Run from `python/` (long — background it):
```
python fidelity.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" -t 60 --sound --presets ../presets.json -o ../docs/FIDELITY.md --json ../build/fidelity.json
```
Expected: `docs/FIDELITY.md` gains `aud` and `loud` columns; *What this run compared* lists both with `rendered audio`; the byte-hash still reads `moved 0` (no converter change). Record the wall-clock time of this pass in the commit message — it is the number Task 7's cost argument rests on.

- [ ] **Step 8: README and commit-ready**

Add the two column bullets to README § *Fidelity — does it play like the original?* (mirror the `report()` text), and a sentence under `--audio`'s existing mention distinguishing `--sound`. Full suite green; byte-hash `moved 0`. On go-ahead: bump (`"aud and loud: the rendered sound as two report columns, behind --sound"`), graphify update, regenerate, commit `python/fidelity.py python/tests/test_fidelity.py README.md docs/FIDELITY.md build/fidelity.json`.

---

### Task 4: `sound_calibrate.py` — thresholds measured, not typed

**Files:**
- Create: `python/sound_calibrate.py`
- Test: `python/tests/test_sound_calibrate.py`
- Create (generated): `docs/SOUND-CALIBRATION.md`, `build/sound_calibration.json`

**Interfaces:**
- Consumes: `sound.read_wav_mono`, `sound.features`, `sound.align`, `sound.compare_features`, `sound.compare_sids`, `sound.render_cached`, `fidelity.pack_sid`, `fidelity.legalise_restarts`, `fidelity._preset_opts`, `fidelity.resolve_subtune`, `h2g.convert.convert`, `build/fidelity.json` rows (for check 5), `approved.json`.
- Produces:
  - Pure functions: `shift_movement(samples, rate, shifts_s: list[float]) -> float` (largest movement of `aud`/`loud` under the shifts), `noise_floor(movements: list[float]) -> float` (their max), `closeness_floor(pairs: list[dict]) -> float` (min over pairs of `min(aud, loud)`), `worse_by(bad: dict, good: dict) -> float` (`good["aud"] - bad["aud"]`), `rank_in_corpus(rows: list[dict], names: list[str]) -> dict[str, tuple[int, int]]`.
  - `build/sound_calibration.json`: `{"version", "head", "seconds", "noise_floor", "closeness_floor", "checks": {...}, "pass": bool}`.
  - `resolve_version_sha(version: str) -> str` — `git log --format=%h --grep=^v<version>: -n1`.
  - `convert_at(version: str, sid: Path, workdir: Path) -> Path` — exports `git archive <sha>` to `workdir/<sha>/`, converts `sid` there with that tree's `presets.json`, packs with the CURRENT `gt2reloc`, returns the packed `.sid`.

- [ ] **Step 1: Write the failing tests (pure functions only)**

```python
# python/tests/test_sound_calibrate.py
"""The calibration's reductions. The checks that render are exercised by hand
(Step 6); what is pinned here is that each number in
build/sound_calibration.json is the reduction the doc says it is."""
import numpy as np
import pytest

import sound
import sound_calibrate as C

RATE = 44100


def _sine(seconds=2.0, hz=440.0, amp=0.5):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_shift_movement_is_small_for_an_inaudible_shift():
    """48 rasterlines is 3 ms and one frame is 20 ms; the alignment absorbs
    both, so the score moves by less than a point."""
    m = C.shift_movement(_sine(), RATE, [0.003, 0.02])
    assert 0.0 <= m < 0.01


def test_noise_floor_is_the_largest_movement_seen():
    assert C.noise_floor([0.001, 0.004, 0.002]) == 0.004


def test_closeness_floor_is_the_least_agreement_a_human_called_the_same():
    pairs = [{"aud": 0.95, "loud": 0.90}, {"aud": 0.97, "loud": 0.99}]
    assert C.closeness_floor(pairs) == 0.90


def test_worse_by_is_signed_good_minus_bad():
    assert C.worse_by({"aud": 0.4}, {"aud": 0.9}) == pytest.approx(0.5)


def test_rank_in_corpus_places_a_name_among_the_rows():
    rows = [{"file": "A.sid", "aud": 0.9}, {"file": "B.sid", "aud": 0.5},
            {"file": "C.sid", "aud": 0.7}, {"file": "D.sid", "aud": None}]
    assert C.rank_in_corpus(rows, ["C"]) == {"C": (2, 3)}   # 2nd of 3 measured


def test_resolve_version_sha_matches_the_commit_subject_convention():
    """Every commit here is `vX.Y.Z: ...`; the resolver greps that prefix."""
    assert C.resolve_version_sha("0.5.446") == "be759f0"
    assert C.resolve_version_sha("9.9.999") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_sound_calibrate.py -q`
Expected: `ModuleNotFoundError: No module named 'sound_calibrate'`

- [ ] **Step 3: Write `python/sound_calibrate.py`**

```python
#!/usr/bin/env python3
"""Calibrate the rendered-audio measure on cases with a known answer.

    python sound_calibrate.py <sid_dir> -t 60 -o ../docs/SOUND-CALIBRATION.md \
        --json ../build/sound_calibration.json --from-json ../build/fidelity.json

Nothing in `sound.py` decides anything until this has run: the two numbers
every decision downstream uses -- the NOISE FLOOR (how much the score moves
under a shift nobody can hear) and the CLOSENESS FLOOR (how far apart two
renders a listener called the same can read) -- are measured here, never
typed. The doc this writes is a regenerated artefact, not prose.

Five checks:
  1 identity      -- a render against itself is 1.0 / 1.0 / ratio 1.0
  2 shift         -- 48 rasterlines (3 ms) and one frame (20 ms) of delay
                     must move the score under a point; the largest movement
                     seen IS the noise floor
  3 inaudible     -- ACE_II at v0.5.368 against v0.5.369: approved.json's own
                     note calls that change inaudible, so the agreement
                     between those two renders bounds the closeness floor
  4 known-bad     -- builds history shows were wrong (Las Vegas silence and
                     Samantha Fox at 3x, both pre-v0.5.402; Human Race on
                     the wrong clock pre-v0.5.330) must score below their
                     fixed builds by more than the noise floor
  5 approved rank -- the approved tunes should sit in the corpus's upper
                     half on `aud`; if one does not, the doc says which of
                     (metric, approval) to check and picks neither

The v0.5.177 half-speed Last_V8 audition the spec listed under check 4 is a
siddump TRACE trap (calls per frame), not a render: sidplayfp plays a packed
.sid at its own multispeed, so there is no wrong-rate WAV to score. Left out
and said so here.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F                      # noqa: E402
import sound                              # noqa: E402
from h2g import __version__               # noqa: E402
from h2g.convert import convert           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RASTERLINES_48_S = 48 * 63 / 985248.0     # PAL cycles per line / cycles per second
FRAME_S = 0.02

INAUDIBLE_PAIRS = [("ACE_II.sid", "0.5.368", "0.5.369")]
KNOWN_BAD = [("Las_Vegas.sid", "0.5.401", "0.5.402"),
             ("Samantha_Fox_Strip_Poker.sid", "0.5.401", "0.5.402"),
             ("Human_Race.sid", "0.5.329", "0.5.330")]


# ---- pure reductions ------------------------------------------------------
def shift_movement(samples: np.ndarray, rate: int, shifts_s: list[float]) -> float:
    """Largest movement of aud/loud when one side is delayed by each shift."""
    a = sound.features(samples, rate)
    worst = 0.0
    for s in shifts_s:
        d = np.concatenate([np.zeros(int(round(s * rate)), dtype=np.float32), samples])
        b = sound.features(d, rate)
        got = sound.compare_features(a, b, sound.align(a, b))
        worst = max(worst, abs(1.0 - (got["aud"] or 0.0)), abs(1.0 - (got["loud"] or 0.0)))
    return worst


def noise_floor(movements: list[float]) -> float:
    return max(movements) if movements else 0.0


def closeness_floor(pairs: list[dict]) -> float:
    """The least agreement between two renders a human called the same."""
    return min(min(p["aud"], p["loud"]) for p in pairs)


def worse_by(bad: dict, good: dict) -> float:
    return (good.get("aud") or 0.0) - (bad.get("aud") or 0.0)


def rank_in_corpus(rows: list[dict], names: list[str]) -> dict[str, tuple[int, int]]:
    scored = sorted(((r["aud"], r["file"][:-4]) for r in rows
                     if r.get("aud") is not None), reverse=True)
    order = [n for _, n in scored]
    return {n: (order.index(n) + 1, len(order)) for n in names if n in order}


# ---- history --------------------------------------------------------------
def resolve_version_sha(version: str) -> str:
    r = subprocess.run(["git", "log", "--format=%h", f"--grep=^v{version}:", "-n1"],
                       cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip()


def convert_at(version: str, sid: Path, workdir: Path, gt2reloc: str,
               multiplier: int) -> Path | None:
    """Convert `sid` with the tree AS IT WAS at `version`, pack with today's
    gt2reloc. The archive is the export the byte-hash recipe uses."""
    sha = resolve_version_sha(version)
    if not sha:
        return None
    tree = workdir / sha
    if not tree.exists():
        tree.mkdir(parents=True)
        blob = subprocess.run(["git", "archive", sha], cwd=ROOT,
                              capture_output=True, check=True).stdout
        tarfile.open(fileobj=io.BytesIO(blob)).extractall(tree)
    out = workdir / f"{sid.stem}.{sha}.sng"
    r = subprocess.run([sys.executable, "-m", "h2g", str(sid), "-o", str(out), "-q",
                        "--presets", str(tree / "presets.json")],
                       cwd=tree / "python", capture_output=True, text=True)
    if r.returncode or not out.exists():
        return None
    blob, _ = F.legalise_restarts(out.read_bytes())
    return F.pack_sid(blob, workdir / sha, gt2reloc, multiplier)


# ---- driver ---------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sound_calibrate")
    p.add_argument("sid_dir")
    p.add_argument("-t", "--seconds", type=int, default=60)
    p.add_argument("-o", "--output", default=str(ROOT / "docs" / "SOUND-CALIBRATION.md"))
    p.add_argument("--json", default=str(ROOT / "build" / "sound_calibration.json"))
    p.add_argument("--from-json", default=str(ROOT / "build" / "fidelity.json"),
                   help="a --sound run of the corpus, for check 5")
    p.add_argument("--presets", default=str(ROOT / "presets.json"))
    p.add_argument("--gt2reloc", default=F.GT2RELOC)
    p.add_argument("--workdir", default=None)
    args = p.parse_args(argv)

    sid_dir = Path(args.sid_dir)
    doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))
    workdir, _ = F.make_workdir(args.workdir)
    workdir = Path(workdir)
    checks: dict = {}
    approved = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))["tunes"]
    names = [n for n in approved if (sid_dir / f"{n}.sid").exists()]

    # 1 + 2: identity and shift, over every approved tune's original.
    idents, moves = {}, []
    for n in names:
        sid = sid_dir / f"{n}.sid"
        sub = F.resolve_subtune(sid, "auto")
        wav = sound.render_cached(sid, args.seconds, sub, "orig")
        if wav is None:
            continue
        x, rate = sound.read_wav_mono(wav)
        f = sound.features(x, rate)
        idents[n] = sound.compare_features(f, f, 0)
        moves.append(shift_movement(x, rate, [RASTERLINES_48_S, FRAME_S]))
    checks["identity"] = idents
    checks["shift"] = {"movements": moves, "noise_floor": noise_floor(moves)}

    # 3: the pair a listener called inaudible.
    pairs = []
    for name, v_old, v_new in INAUDIBLE_PAIRS:
        sid = sid_dir / name
        mult = F._preset_multiplier(doc, name)
        a = convert_at(v_old, sid, workdir, args.gt2reloc, mult)
        b = convert_at(v_new, sid, workdir, args.gt2reloc, mult)
        if a and b:
            sub = F.resolve_subtune(sid, "auto")
            got = sound.compare_sids(a, b, args.seconds, sub, sub)
            got.update(file=name, versions=[v_old, v_new])
            pairs.append(got)
    checks["inaudible"] = pairs
    closeness = closeness_floor(pairs) if pairs else None

    # 4: known-bad builds against their fixes.
    bad = []
    for name, v_bad, v_good in KNOWN_BAD:
        sid = sid_dir / name
        mult = F._preset_multiplier(doc, name)
        sub = F.resolve_subtune(sid, "auto")
        pb = convert_at(v_bad, sid, workdir, args.gt2reloc, mult)
        pg = convert_at(v_good, sid, workdir, args.gt2reloc, mult)
        if not (pb and pg):
            bad.append({"file": name, "error": "could not build both versions"})
            continue
        gb = sound.compare_sids(sid, pb, args.seconds, sub, sub)
        gg = sound.compare_sids(sid, pg, args.seconds, sub, sub)
        bad.append({"file": name, "versions": [v_bad, v_good],
                    "bad": gb.get("aud"), "good": gg.get("aud"),
                    "worse_by": worse_by(gb, gg),
                    "seen": worse_by(gb, gg) > checks["shift"]["noise_floor"]})
    checks["known_bad"] = bad

    # 5: where the approved tunes sit.
    rows = []
    if Path(args.from_json).exists():
        rows = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
    ranks = rank_in_corpus(rows, names)
    checks["approved_rank"] = {n: {"rank": r, "of": t, "upper_half": r <= t / 2}
                               for n, (r, t) in ranks.items()}

    passed = (all(abs(1 - v["aud"]) < 1e-6 for v in idents.values())
              and checks["shift"]["noise_floor"] < 0.01
              and closeness is not None
              and all(b.get("seen") for b in bad))
    out = {"version": __version__, "head": F.git_label(ROOT), "seconds": args.seconds,
           "noise_floor": checks["shift"]["noise_floor"],
           "closeness_floor": closeness, "checks": checks, "pass": passed}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    Path(args.output).write_text(render_doc(out), encoding="utf-8")
    print(f"wrote {args.output} and {args.json}: pass={passed}", file=sys.stderr)
    return 0 if passed else 1


def render_doc(out: dict) -> str:
    c = out["checks"]
    lines = ["# Sound calibration", "",
             f"Generated by `python/sound_calibrate.py` (h2g {out['version']}, "
             f"{out['head']}), {out['seconds']} s renders. **PASS**" if out["pass"]
             else f"Generated by `python/sound_calibrate.py` (h2g {out['version']}, "
                  f"{out['head']}), {out['seconds']} s renders. **FAIL** -- nothing "
                  "downstream may inherit an approval on these numbers.",
             "",
             "The two numbers every decision uses, measured here and typed nowhere:", "",
             f"* **noise floor** = `{out['noise_floor']:.4f}` -- the largest movement of "
             "`aud`/`loud` under a 3 ms (48 rasterline) and a 20 ms (one frame) delay "
             "of one side. A change smaller than this is not a change.",
             f"* **closeness floor** = `{out['closeness_floor']}` -- the least agreement "
             "between two renders a listener called the same (check 3). A build at "
             "least this close to an approved render sounds like what was approved.",
             "", "## 1. Identity", "", "| tune | aud | loud | ratio |", "|---|---:|---:|---:|"]
    for n, v in c["identity"].items():
        lines.append(f"| {n} | {v['aud']:.4f} | {v['loud']:.4f} | {v['loud_ratio']:.3f} |")
    lines += ["", "## 2. Inaudible shift", "",
              f"Movements per tune: {', '.join(f'{m:.4f}' for m in c['shift']['movements'])}",
              "", "## 3. A change a listener called inaudible", "",
              "| file | versions | aud | loud |", "|---|---|---:|---:|"]
    for pr in c["inaudible"]:
        lines.append(f"| {pr['file']} | {' -> '.join(pr['versions'])} | "
                     f"{pr['aud']:.4f} | {pr['loud']:.4f} |")
    lines += ["", "## 4. Known-bad builds", "",
              "| file | bad -> good | aud bad | aud good | worse by | seen? |",
              "|---|---|---:|---:|---:|---|"]
    for b in c["known_bad"]:
        if "error" in b:
            lines.append(f"| {b['file']} | - | - | - | - | {b['error']} |")
        else:
            lines.append(f"| {b['file']} | {' -> '.join(b['versions'])} | {b['bad']:.3f} | "
                         f"{b['good']:.3f} | {b['worse_by']:+.3f} | "
                         f"{'yes' if b['seen'] else 'NO -- a blind spot; name it in the Dimension'} |")
    lines += ["", "## 5. Where the approved tunes sit", "",
              "| tune | rank | of | upper half? |", "|---|---:|---:|---|"]
    for n, v in c["approved_rank"].items():
        lines.append(f"| {n} | {v['rank']} | {v['of']} | "
                     f"{'yes' if v['upper_half'] else 'no -- check the metric on this file with --sound and the approval note; this doc picks neither'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `cd python && python -m pytest tests/test_sound_calibrate.py -q`
Expected: `6 passed`

- [ ] **Step 5: Confirm the version shas resolve**

Run from `python/`:
```
python -c "import sound_calibrate as C; print([C.resolve_version_sha(v) for v in ('0.5.368','0.5.369','0.5.401','0.5.402','0.5.329','0.5.330')])"
```
Expected: six non-empty short shas. If any is empty, the commit subject for that version does not start with `vX.Y.Z:` — find it with `git log --oneline | grep 0.5.NNN` and put the sha in a `VERSION_SHAS` override dict at the top of the module rather than loosening the grep.

- [ ] **Step 6: Run the calibration for real**

Run from `python/` (background it; it builds six historical trees and renders ~14 WAVs):
```
python sound_calibrate.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" -t 60
```
Expected: `docs/SOUND-CALIBRATION.md` and `build/sound_calibration.json` written; `pass=True`. If check 4 reports `NO` for a file, that is a **finding**: add the blind spot to the `aud` Dimension description in `fidelity.py` before continuing, and record it in the commit message. Do not adjust the metric to make the check pass.

- [ ] **Step 7: Commit-ready**

Byte-hash `moved 0`; full suite green. `build/sound_calibration.json` is committed (it is an input to Task 5, like `build/fidelity.json`). On go-ahead: bump (`"sound_calibrate: the noise floor and the closeness floor are measured"`), graphify update, regenerate, commit `python/sound_calibrate.py python/tests/test_sound_calibrate.py docs/SOUND-CALIBRATION.md build/sound_calibration.json`.

---

### Task 5: `approvals.py` — an approval the current build can inherit

**Files:**
- Create: `python/approvals.py`
- Test: `python/tests/test_approvals.py`
- Create (generated): `build/approvals.json`

**Interfaces:**
- Consumes: `approved.json` (`{"tunes": {stem: {"approved", "sng_sha256", ...}}}`), `build/sound_calibration.json` (`noise_floor`, `closeness_floor`), `sound.compare_sids`, `sound.render_cached`, `fidelity.pack_sid`, `fidelity.legalise_restarts`, `fidelity._preset_opts`, `fidelity._preset_multiplier`, `fidelity.resolve_subtune`, `fidelity.run_siddump`, `fidelity.compare`, `fidelity.length_compare`, `h2g.convert.convert`, `presets.FIDELITY_MARGIN`.
- Produces:
  - `inherit(approved_vs_orig: dict, current_vs_orig: dict, current_vs_approved: dict, structure: dict, cal: dict | None, margin: float = 0.02) -> dict` — pure. `structure = {"attacks": int, "orig_attacks": int, "approved_attacks": int, "melody": float, "approved_melody": float, "sequence": float, "approved_sequence": float, "length_delta": float | None}`. Returns `{"status": "exact" | "inherited" | "stale" | "uncalibrated", "failed": [criterion...], "listener_should_check": str | None, "evidence": {...}}`.
  - `assess(stem: str, sid: Path, approved_sha: str, doc: dict, seconds: int, cal: dict | None, gt2reloc: str, siddump: str, workdir: Path, current_sng: bytes | None = None) -> dict` — renders/traces and calls `inherit`; `current_sng` lets `presets.py` pass a candidate instead of the shipped conversion.
  - CLI: `python approvals.py <sid_dir> -t 60` writes `build/approvals.json`: `{"generator", "head", "seconds", "tunes": {stem: record}}` where `record = {"approved_sha", "current_sha", "status", "since", "builds_inherited", "evidence", "failed", "listener_should_check"}`.
  - `load_approvals_json() -> dict` for `abpage.py`.

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_approvals.py
"""Whether a build inherits a human approval. Pure logic on fixture records;
the render/trace plumbing is exercised by hand in Task 5 step 6."""
import json

import pytest

import approvals as AP

CAL = {"noise_floor": 0.005, "closeness_floor": 0.90}


def _structure(**kw):
    s = {"attacks": 100, "orig_attacks": 100, "approved_attacks": 100,
         "melody": 0.95, "approved_melody": 0.95,
         "sequence": 0.95, "approved_sequence": 0.95, "length_delta": None}
    s.update(kw)
    return s


def _vs(aud=0.90, loud=0.90):
    return {"aud": aud, "loud": loud}


def test_the_same_bytes_are_exact():
    got = AP.inherit(_vs(), _vs(), {"aud": 1.0, "loud": 1.0}, _structure(), CAL,
                     same_sha=True)
    assert got["status"] == "exact" and got["failed"] == []


def test_a_build_no_farther_from_the_original_and_close_to_the_approved_inherits():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.92, 0.91), {"aud": 0.96, "loud": 0.95},
                     _structure(), CAL)
    assert got["status"] == "inherited" and got["failed"] == []


def test_farther_from_the_original_than_the_noise_floor_is_stale():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.88, 0.90), {"aud": 0.97, "loud": 0.97},
                     _structure(), CAL)
    assert got["status"] == "stale"
    assert "aud_vs_orig" in got["failed"]


def test_within_the_noise_floor_is_not_farther():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.897, 0.90), {"aud": 0.97, "loud": 0.97},
                     _structure(), CAL)
    assert got["status"] == "inherited"


def test_not_close_enough_to_the_approved_render_is_stale():
    """Scoring as well as the approved build is not enough: it has to SOUND
    like what the person said yes to."""
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.95, 0.95), {"aud": 0.80, "loud": 0.97},
                     _structure(), CAL)
    assert got["status"] == "stale" and "aud_vs_approved" in got["failed"]


def test_a_structural_regression_the_listener_could_hear_is_stale():
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(attacks=80), CAL)
    assert got["status"] == "stale" and "attacks" in got["failed"]
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(melody=0.90), CAL)
    assert "melody" in got["failed"]
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(length_delta=7.0), CAL)
    assert "length" in got["failed"]


def test_attacks_may_move_closer_to_the_originals_count():
    """Fewer attacks is not a regression when the original has fewer: the
    two-sided guard from presets.fidelity_better, not ours-against-ours."""
    got = AP.inherit(_vs(), _vs(0.95, 0.95), {"aud": 0.99, "loud": 0.99},
                     _structure(attacks=97, approved_attacks=100, orig_attacks=96), CAL)
    assert "attacks" not in got["failed"]


def test_no_calibration_means_no_inheritance():
    got = AP.inherit(_vs(), _vs(0.99, 0.99), {"aud": 0.99, "loud": 0.99},
                     _structure(), None)
    assert got["status"] == "uncalibrated"


def test_listener_should_check_names_the_criterion_nearest_its_bound():
    got = AP.inherit(_vs(0.90, 0.90), _vs(0.899, 0.95), {"aud": 0.91, "loud": 0.99},
                     _structure(), CAL)
    assert got["status"] == "inherited"
    assert got["listener_should_check"] in ("aud_vs_approved", "aud_vs_orig")


def test_inheritance_never_creates_an_approval(tmp_path, monkeypatch):
    """A tune with no human verdict is not assessed at all."""
    monkeypatch.setattr(AP, "ROOT", tmp_path)
    (tmp_path / "approved.json").write_text(json.dumps({"tunes": {}}), encoding="utf-8")
    assert AP.approved_tunes() == {}


def test_the_record_shape_is_stable():
    rec = AP.record("Tune", "abc", "abc",
                    AP.inherit(_vs(), _vs(), {"aud": 1.0, "loud": 1.0}, _structure(), CAL,
                               same_sha=True), previous=None, version="0.5.447")
    assert set(rec) == {"approved_sha", "current_sha", "status", "since",
                        "builds_inherited", "evidence", "failed", "listener_should_check"}
    assert rec["since"] == "0.5.447" and rec["builds_inherited"] == 0


def test_builds_inherited_counts_up_only_while_the_sha_keeps_moving():
    first = AP.record("T", "a", "b", {"status": "inherited", "failed": [],
                                      "listener_should_check": None, "evidence": {}},
                      previous=None, version="1")
    same = AP.record("T", "a", "b", {"status": "inherited", "failed": [],
                                     "listener_should_check": None, "evidence": {}},
                     previous=first, version="2")
    moved = AP.record("T", "a", "c", {"status": "inherited", "failed": [],
                                      "listener_should_check": None, "evidence": {}},
                      previous=same, version="3")
    assert (first["builds_inherited"], same["builds_inherited"], moved["builds_inherited"]) == (1, 1, 2)
    assert moved["since"] == "1"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_approvals.py -q`
Expected: `ModuleNotFoundError: No module named 'approvals'`

- [ ] **Step 3: Write `python/approvals.py`**

```python
#!/usr/bin/env python3
"""Does the build shipping NOW still carry a human's approval?

    python approvals.py <sid_dir> -t 60          # writes build/approvals.json

`approved.json` is hand-written, sha-pinned, and no tool writes it. This
module reads it and asks, for each approved tune, whether the current
conversion INHERITS the verdict -- and writes the answer to
build/approvals.json, which abpage.py shows and presets.py consults.

A build inherits when all three hold, on the same window and alignment:

  1. NO FARTHER FROM THE ORIGINAL: its `aud`/`loud` against the original are
     at least the approved render's, within the NOISE FLOOR the calibration
     measured (a change smaller than that is not a change).
  2. CLOSE TO WHAT WAS APPROVED: its `aud`/`loud` against the APPROVED RENDER
     are at least the CLOSENESS FLOOR -- the least agreement between two
     renders a listener called the same. It must sound like the thing the
     person said yes to, not merely score as well.
  3. NOTHING STRUCTURAL REGRESSED that the listener could have heard: the
     attack count no farther from the original's than the approved build's,
     `melody`/`sequence` within FIDELITY_MARGIN, `len` inside +-5 s. These
     are `presets.fidelity_better`'s guards, reused.

Two rules that are the point rather than details:

* Inheritance NEVER CREATES an approval. A tune nobody signed off is not
  assessed. The metric bounds how much a change moved; it is not evidence
  the result is right.
* Criterion 2 is always against the HUMAN-APPROVED render, never the last
  inherited build, so small steps cannot walk away from the verdict.

Without build/sound_calibration.json the status is `uncalibrated` and nothing
inherits: the thresholds are measured, never typed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F                       # noqa: E402
import sound                               # noqa: E402
from h2g import __version__                # noqa: E402
from h2g.convert import convert            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIDELITY_MARGIN = 0.02      # presets.FIDELITY_MARGIN; imported lazily below to avoid a cycle
LENGTH_TOLERANCE = 5.0      # fidelity.LENGTH_TOLERANCE


def approved_tunes() -> dict:
    path = ROOT / "approved.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {n: a for n, a in (doc.get("tunes") or {}).items()
            if a.get("approved") and a.get("sng_sha256")}


def load_calibration() -> dict | None:
    path = ROOT / "build" / "sound_calibration.json"
    if not path.exists():
        return None
    cal = json.loads(path.read_text(encoding="utf-8"))
    if not cal.get("pass") or cal.get("closeness_floor") is None:
        return None
    return cal


def load_approvals_json() -> dict:
    path = ROOT / "build" / "approvals.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("tunes") or {}
    except (OSError, ValueError):
        return {}


# ---- the decision ---------------------------------------------------------
def inherit(approved_vs_orig: dict, current_vs_orig: dict,
            current_vs_approved: dict, structure: dict, cal: dict | None,
            margin: float = FIDELITY_MARGIN, same_sha: bool = False) -> dict:
    evidence = {"aud_vs_orig": [approved_vs_orig.get("aud"), current_vs_orig.get("aud")],
                "loud_vs_orig": [approved_vs_orig.get("loud"), current_vs_orig.get("loud")],
                "aud_vs_approved": current_vs_approved.get("aud"),
                "loud_vs_approved": current_vs_approved.get("loud"),
                "attacks": [structure.get("approved_attacks"), structure.get("attacks"),
                            structure.get("orig_attacks")],
                "melody": [structure.get("approved_melody"), structure.get("melody")],
                "sequence": [structure.get("approved_sequence"), structure.get("sequence")],
                "length_delta": structure.get("length_delta")}
    if same_sha:
        return {"status": "exact", "failed": [], "listener_should_check": None,
                "evidence": evidence}
    if cal is None:
        return {"status": "uncalibrated", "failed": [], "listener_should_check": None,
                "evidence": evidence}
    floor, close = float(cal["noise_floor"]), float(cal["closeness_floor"])
    failed, margins = [], {}

    def need(name, value, bound):
        """A criterion fails when `value < bound`; its margin is how near it came."""
        if value is None:
            failed.append(name)
            return
        margins[name] = value - bound
        if value < bound:
            failed.append(name)

    # 1. No farther from the original, within the noise floor.
    for k in ("aud", "loud"):
        need(f"{k}_vs_orig", current_vs_orig.get(k),
             (approved_vs_orig.get(k) or 0.0) - floor)
    # 2. Close to what was approved.
    for k in ("aud", "loud"):
        need(f"{k}_vs_approved", current_vs_approved.get(k), close)
    # 3. Nothing structural regressed. Attacks: two-sided against the
    # original's count, as presets.fidelity_better reads it.
    a, ap, o = structure.get("attacks"), structure.get("approved_attacks"), structure.get("orig_attacks")
    if a is not None and ap is not None and a < ap:
        if o is None or abs(a - o) >= abs(ap - o):
            failed.append("attacks")
    for k in ("melody", "sequence"):
        cur, was = structure.get(k), structure.get(f"approved_{k}")
        if cur is not None and was is not None and cur < was - margin:
            failed.append(k)
    ld = structure.get("length_delta")
    if ld is not None and abs(ld) > LENGTH_TOLERANCE:
        failed.append("length")

    status = "stale" if failed else "inherited"
    nearest = min(margins, key=margins.get) if margins else None
    return {"status": status, "failed": failed,
            "listener_should_check": (failed[0] if failed else nearest),
            "evidence": evidence}


def record(stem: str, approved_sha: str, current_sha: str, verdict: dict,
           previous: dict | None, version: str) -> dict:
    """One build/approvals.json entry. `since` and `builds_inherited` persist
    across runs: the count moves only when the sha does."""
    inherited = verdict["status"] == "inherited"
    if previous and previous.get("status") == "inherited" and inherited:
        since = previous.get("since", version)
        n = previous.get("builds_inherited", 0) + (
            1 if previous.get("current_sha") != current_sha else 0)
    else:
        since, n = version, (1 if inherited else 0)
    return {"approved_sha": approved_sha, "current_sha": current_sha,
            "status": verdict["status"], "since": since, "builds_inherited": n,
            "evidence": verdict["evidence"], "failed": verdict["failed"],
            "listener_should_check": verdict["listener_should_check"]}


# ---- plumbing ------------------------------------------------------------
def _structure_of(orig_trace, trace, seconds: int) -> dict:
    got = F.compare(orig_trace, trace)
    return {"attacks": sum(len(v.attacks) for v in trace),
            "orig_attacks": sum(len(v.attacks) for v in orig_trace),
            "melody": got["melody"], "sequence": got["sequence"],
            "length_delta": F.length_compare(orig_trace, trace, seconds).get("length_delta")}


def assess(stem: str, sid: Path, approved_sha: str, doc: dict, seconds: int,
           cal: dict | None, gt2reloc: str, siddump: str, workdir: Path,
           current_sng: bytes | None = None,
           approved_sng: Path | None = None) -> tuple[dict, str]:
    """(verdict, current sha). `approved_sng` is the .sng the listener heard;
    `listen.py` keeps it as build/listen/<stem>.h2g.sng when its sha matches."""
    name = f"{stem}.sid"
    opts = F._preset_opts(doc, name)
    mult = F._preset_multiplier(doc, name)
    cur = current_sng if current_sng is not None else convert(str(sid), log=lambda m: None, **opts)
    cur_sha = hashlib.sha256(cur).hexdigest()
    same = cur_sha == approved_sha
    if approved_sng is None:
        cand = ROOT / "build" / "listen" / f"{stem}.h2g.sng"
        if cand.exists() and hashlib.sha256(cand.read_bytes()).hexdigest() == approved_sha:
            approved_sng = cand
    if same:
        return inherit({}, {}, {}, {}, cal, same_sha=True), cur_sha
    if approved_sng is None:
        v = inherit({}, {}, {}, {}, None)
        v["failed"] = ["approved .sng not on disk -- re-stage it with listen.py"]
        return v, cur_sha
    sub = F.resolve_subtune(sid, "auto")
    orig_trace = F.run_siddump(sid, seconds, sub, siddump)

    def packed_of(blob: bytes, tag: str):
        b, _ = F.legalise_restarts(blob)
        return F.pack_sid(b, workdir / tag, gt2reloc, mult)
    p_cur = packed_of(cur, "cur")
    p_app = packed_of(approved_sng.read_bytes(), "app")
    if p_cur is None or p_app is None:
        v = inherit({}, {}, {}, {}, None)
        v["failed"] = ["gt2reloc refused a side"]
        return v, cur_sha
    t_cur = F.run_siddump(p_cur, seconds, sub, siddump, calls=mult)
    t_app = F.run_siddump(p_app, seconds, sub, siddump, calls=mult)
    s_cur, s_app = _structure_of(orig_trace, t_cur, seconds), _structure_of(orig_trace, t_app, seconds)
    structure = dict(s_cur, approved_attacks=s_app["attacks"],
                     approved_melody=s_app["melody"], approved_sequence=s_app["sequence"])
    lag = 0.02 * F.startup_lag(orig_trace, t_cur)[0]
    app_vs_orig = sound.compare_sids(sid, p_app, seconds, sub, sub, prior_s=lag)
    cur_vs_orig = sound.compare_sids(sid, p_cur, seconds, sub, sub, prior_s=lag)
    cur_vs_app = sound.compare_sids(p_app, p_cur, seconds, sub, sub)
    return inherit(app_vs_orig, cur_vs_orig, cur_vs_app, structure, cal), cur_sha


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="approvals")
    p.add_argument("sid_dir")
    p.add_argument("-t", "--seconds", type=int, default=60)
    p.add_argument("--presets", default=str(ROOT / "presets.json"))
    p.add_argument("-o", "--output", default=str(ROOT / "build" / "approvals.json"))
    p.add_argument("--gt2reloc", default=F.GT2RELOC)
    p.add_argument("--siddump", default=F.SIDDUMP)
    p.add_argument("--workdir", default=None)
    args = p.parse_args(argv)
    doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))
    cal = load_calibration()
    workdir, _ = F.make_workdir(args.workdir)
    previous = load_approvals_json()
    tunes = {}
    for stem, a in approved_tunes().items():
        sid = Path(args.sid_dir) / f"{stem}.sid"
        if not sid.exists():
            continue
        verdict, cur_sha = assess(stem, sid, a["sng_sha256"], doc, args.seconds, cal,
                                  args.gt2reloc, args.siddump, Path(workdir))
        tunes[stem] = record(stem, a["sng_sha256"], cur_sha, verdict,
                             previous.get(stem), __version__)
        print(f"  {stem:32} {tunes[stem]['status']}"
              + (f"  ({', '.join(verdict['failed'])})" if verdict["failed"] else ""),
              file=sys.stderr)
    out = {"generator": f"h2g {__version__} approvals.py", "head": F.git_label(ROOT),
           "seconds": args.seconds, "calibrated": cal is not None, "tunes": tunes}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(tunes)} tune(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `cd python && python -m pytest tests/test_approvals.py -q`
Expected: `12 passed`

- [ ] **Step 5: Confirm the approved `.sng`s are on disk**

The approved render is the `.sng` the listener heard. `listen.py` writes `build/listen/<stem>.h2g.sng`; `assess` uses it only when its sha256 equals `approved.json`'s. Check which of the four approved tunes still have theirs:
```
python -c "import approvals as AP, hashlib; from pathlib import Path
for s,a in AP.approved_tunes().items():
    p=AP.ROOT/'build'/'listen'/f'{s}.h2g.sng'; print(s, p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==a['sng_sha256'])"
```
For any `False`: the approved `.sng` must be rebuilt from history via `sound_calibrate.convert_at(a["version"], sid, workdir, ...)`.

> **CORRECTED — DO NOT HASH `convert_at`'S RETURN VALUE.** This step used to read "`convert_at(...)` reproduces it, and its sha must equal `sng_sha256`". That is wrong and it is a SILENT no-op rather than a loud failure: `convert_at` returns `F.pack_sid(...)`, **a packed `.sid`**, whose sha256 can never equal an `sng_sha256` — so a literal implementation recovers nothing, always, and reports every approval unrecoverable while looking like it ran. The document contradicted itself: § "the module" above already specifies correctly that `convert_at` "returns the packed `.sid`", and that line is the one to trust.
>
> Read the artefact off disk instead. `convert_at` writes the intermediate `.sng` to **`workdir / f"{sid.stem}.{sha}.sng"`** on its way to packing, and THAT is the file the listener heard and the one `sng_sha256` names. So call `convert_at` for its SIDE EFFECT and hash the `.sng` it leaves behind. `approvals.recover_approved_sng` already does exactly this and its docstring records why.
>
> A `None` return means one of THREE things and they must not be collapsed: the version does not resolve to a commit, the historical tree refused the file, or the bytes came back with a different sha. Only the third is the `stale` case this step describes.

If the recovered `.sng`'s sha does not equal `sng_sha256`, the approval's `version` field is provenance only and the build cannot be recovered; record that tune as `stale` with `failed: ["approved .sng not recoverable"]`. Add a `--recover` flag to `approvals.py main()` that tries `convert_at` for each missing one and copies the recovered `.sng` to `build/listen/<stem>.h2g.sng` when the sha matches.

- [ ] **Step 6: Run it for real**

Run from `python/`: `python approvals.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" -t 60`
Expected: four lines, one per approved tune, each `exact`, `inherited` or `stale` with its failed criteria — never `uncalibrated` (Task 4 ran). `build/approvals.json` written. Note ACE_II's status: it is the tune Task 7 resolves.

- [ ] **Step 7: Commit-ready**

Byte-hash `moved 0`; suite green. `build/approvals.json` is committed (abpage reads it; a fresh checkout must see the same three states the commit measured). On go-ahead: bump (`"approvals.py: a build inherits a human approval by measurement, or is stale by a named criterion"`), graphify update, regenerate, commit `python/approvals.py python/tests/test_approvals.py build/approvals.json`.

---

### Task 6: `abpage.py` — three approval states

**Files:**
- Modify: `python/abpage.py:238-273` (`approval_badge`), `python/abpage.py:2712-2760` (`index`'s `verdict`), `page()` call sites at ~2658 and ~3245, `main()` at ~3192.
- Test: `python/tests/test_abpage.py` (append)

**Interfaces:**
- Consumes: `approvals.load_approvals_json() -> {stem: record}`.
- Produces: `approval_badge(name, appr, version, shas=None, inherited=None)`; `index(..., inherited=None)`; `page(..., inherited=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/test_abpage.py`:

```python
APPR = {"Tune": {"approved": True, "sng_sha256": "aaa", "version": "0.5.400", "at": "2026-08-20"}}


def test_badge_is_inherited_when_the_build_inherits():
    rec = {"Tune": {"status": "inherited", "approved_sha": "aaa", "current_sha": "bbb",
                    "since": "0.5.447", "builds_inherited": 2, "failed": [],
                    "listener_should_check": "aud_vs_approved", "evidence": {}}}
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "bbb"}, inherited=rec)
    assert 'class="approval inherited"' in html
    assert "since 0.5.447" in html and "2 build" in html


def test_badge_is_stale_and_names_what_to_listen_for():
    rec = {"Tune": {"status": "stale", "approved_sha": "aaa", "current_sha": "bbb",
                    "since": "0.5.447", "builds_inherited": 0,
                    "failed": ["aud_vs_approved"], "listener_should_check": "aud_vs_approved",
                    "evidence": {}}}
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "bbb"}, inherited=rec)
    assert 'class="approval stale"' in html
    assert "aud_vs_approved" in html


def test_badge_falls_back_to_the_sha_rule_without_an_assessment():
    """No build/approvals.json, or a tune it does not cover: the old two
    states, unchanged."""
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "bbb"}, inherited={})
    assert 'class="approval stale"' in html
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "aaa"}, inherited={})
    assert 'class="approval yes"' in html


def test_index_shows_three_states():
    rec = {"Tune": {"status": "inherited", "approved_sha": "aaa", "current_sha": "bbb",
                    "since": "0.5.447", "builds_inherited": 1, "failed": [],
                    "listener_should_check": None, "evidence": {}}}
    html = A.index(["Tune"], {}, "0.5.448", APPR, {"Tune": "bbb"}, inherited=rec)
    assert 'class="i">inherited' in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_abpage.py -q -k "badge or three_states"`
Expected: `TypeError: approval_badge() got an unexpected keyword argument 'inherited'`

- [ ] **Step 3: Extend `approval_badge`**

Replace the body after the `not approved` return with:

```python
    at, was = a.get("at", ""), str(a.get("version", ""))
    note = md(a.get("note", "")) if a.get("note") else ""
    want, now = a.get("sng_sha256"), (shas or {}).get(name)
    rec = (inherited or {}).get(name)
    if want and now and want != now:
        # The conversion has changed. build/approvals.json, when it covers
        # this tune, says whether the change is one the measure can vouch for.
        if rec and rec.get("status") == "inherited":
            return ('<div class="approval inherited"><b>Human approved &mdash; '
                    'inherited by measurement</b><span>Signed off %s at %s; the '
                    '<code>.sng</code> has changed since %s (%d build%s) and every '
                    'build stayed no farther from the original than the approved '
                    'render, and within the calibrated closeness of it. Nearest '
                    'criterion: <code>%s</code>.%s</span></div>'
                    % (at, was, rec.get("since", "?"), rec.get("builds_inherited", 0),
                       "" if rec.get("builds_inherited", 0) == 1 else "s",
                       rec.get("listener_should_check") or "-",
                       (" " + note) if note else ""))
        why = ""
        if rec and rec.get("failed"):
            why = (" What to listen for: <code>%s</code> (failed: %s)."
                   % (rec.get("listener_should_check") or rec["failed"][0],
                      ", ".join(rec["failed"])))
        return ('<div class="approval stale"><b>Approved &mdash; but the '
                'conversion has changed since</b><span>Signed off %s at %s, '
                'and the <code>.sng</code> no longer matches the one that was '
                'heard. The verdict does not cover what this page plays.%s%s'
                '</span></div>' % (at, was, why, (" " + note) if note else ""))
    return ('<div class="approval yes"><b>Human approved</b>'
            '<span>Signed off %s at %s.%s</span></div>'
            % (at, was or version.lstrip("v"), (" " + note) if note else ""))
```

with the signature `def approval_badge(name: str, appr: dict, version: str, shas: dict | None = None, inherited: dict | None = None) -> str:`. Add a `.approval.inherited` CSS rule beside `.approval.yes` in the page stylesheet (same colours as `yes` with a dashed border, so the state is visibly different).

- [ ] **Step 4: Extend `index` and the call sites**

`index(names, rows, version, appr=None, shas=None, survey=None, inherited=None)`; in its `verdict(n)`:

```python
        want, now_sha = a.get("sng_sha256"), shas.get(n)
        if want and now_sha and want != now_sha:
            rec = (inherited or {}).get(n)
            if rec and rec.get("status") == "inherited":
                return '<span class="i">inherited</span>'
            return '<span class="s">stale</span>'
        return '<span class="y">approved</span>'
```

`page(...)` gains `inherited: dict | None = None` and passes it to `approval_badge(name, approval or {}, version, now_shas, inherited=inherited)`. In `main()`, after `appr = approvals()`:

```python
    import approvals as AP
    inherited = AP.load_approvals_json()
```
and pass `inherited=inherited` to every `page(...)` and the `index(...)` call. Add a `.i` CSS class beside `.y`/`.s` in the index stylesheet.

- [ ] **Step 5: Run the tests**

Run: `cd python && python -m pytest tests/test_abpage.py -q`
Expected: all pass (the existing badge tests still pass because `inherited` defaults to `None`).

- [ ] **Step 6: Build the pages and look**

Run from `python/`: `python abpage.py` then open `build/listen/index.html`. Expected: the approval column shows `approved` / `inherited` / `stale` per `build/approvals.json`; a stale tune's page names the criterion.

- [ ] **Step 7: Commit-ready**

Byte-hash `moved 0`; suite green. README § *`abpage.py`*: one paragraph on the third state and where it comes from. On go-ahead: bump (`"abpage: an approval is exact, inherited or stale, and a stale one says what to listen for"`), graphify update, regenerate, commit `python/abpage.py python/tests/test_abpage.py README.md`.

---

### Task 7: `presets.py` — the search respects approvals by measurement

**Files:**
- Modify: `python/presets.py` — `FIDELITY_VETOED` (~336), `fidelity_better` (~707), `tune_by_fidelity` (~1060-1258), `build_parser` (~1261), `main` (~1395-1470).
- Test: `python/tests/test_presets.py` (append), `python/tests/test_gate_criterion.py` (the `_state` helper widens; existing tests unchanged).
- Modify: `README.md` § *Per-song presets*, `CLAUDE.md` (the `FIDELITY_VETOED` / "Forcing one option" paragraphs), `H2G-CONVERSION-METHOD.md` § 7 (new entry).
- Regenerated in this task's commit: `presets.json`, `docs/FIDELITY.md`, `build/fidelity.json`, `build/approvals.json`, `build/search_refusals.json`.

**Interfaces:**
- Consumes: `approvals.assess(stem, sid, approved_sha, doc, seconds, cal, gt2reloc, siddump, workdir, current_sng=...)`, `approvals.approved_tunes()`, `approvals.load_calibration()`, `sound.compare_sids`, `fidelity.length_compare`.
- Produces: `fidelity_better(cand, ref, margin, sound_floor=None)` reading `cand[9]` (`aud`, float|None) and `cand[10]` (`length_delta`, float|None); `tune_by_fidelity(..., refusals: list | None = None, approved: dict | None = None, cal: dict | None = None, doc: dict | None = None)`; `--refusals PATH` (default `<output dir>/build/search_refusals.json`); `build/search_refusals.json` = `{"generator", "head", "refusals": [{"song", "combination", "criterion", "value", "bound"}]}`.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/test_presets.py`:

```python
import presets


def _state(melody=0.9, seq=0.9, attacks=100, noise=(0, 0, 0, 0), osc=1.0,
           onset=0.5, hold=0.5, gate=0.4, orig_attacks=100, aud=None, length=None):
    return (melody, seq, attacks, noise, osc, onset, hold, gate, orig_attacks, aud, length)


def test_the_sound_veto_refuses_a_render_that_moved_away_from_the_original():
    """A veto, not an acceptor: `aud` rewards deleted events the way `wave`
    does, so a gain on it never selects -- but a loss past the calibrated
    noise floor refuses whatever melody says."""
    ref = _state(gate=0.40, aud=0.90)
    cand = _state(gate=0.85, aud=0.85)
    assert not presets.fidelity_better(cand, ref, sound_floor=0.01)
    assert presets.fidelity_better(_state(gate=0.85, aud=0.895), ref, sound_floor=0.01)


def test_a_better_sound_alone_selects_nothing():
    assert not presets.fidelity_better(_state(aud=0.99), _state(aud=0.50), sound_floor=0.01)


def test_the_sound_veto_is_inert_without_a_floor_or_a_reading():
    ref = _state(gate=0.40, aud=0.90)
    assert presets.fidelity_better(_state(gate=0.85, aud=0.50), ref)          # no floor
    assert presets.fidelity_better(_state(gate=0.85, aud=None), ref, sound_floor=0.01)


def test_the_length_veto_refuses_a_tune_that_no_longer_ends_with_the_original():
    ref = _state(gate=0.40, length=0.5)
    assert not presets.fidelity_better(_state(gate=0.85, length=7.0), ref)
    assert presets.fidelity_better(_state(gate=0.85, length=-3.0), ref)
    assert presets.fidelity_better(_state(gate=0.85, length=None), ref)


def test_the_old_eight_and_nine_tuple_shapes_still_work():
    """test_gate_criterion.py builds 8-tuples; the two new slots are absent
    there, and an absent dimension recommends nothing and vetoes nothing."""
    assert presets.fidelity_better((0.9, 0.9, 100, (0, 0, 0, 0), 1.0, 0.5, 0.5, 0.85),
                                   (0.9, 0.9, 100, (0, 0, 0, 0), 1.0, 0.5, 0.5, 0.40))


def test_no_approval_kind_veto_remains():
    """Approval vetoes are computed now (approvals.assess); only structural
    ones -- a search that compared the wrong music -- stay hand-written."""
    assert "hard_restart_frames" not in presets.FIDELITY_VETOED.get("ACE_II.sid", set())
    assert "ACE_II.sid" not in presets.FIDELITY_VETOED


def test_a_refusal_is_a_record(tmp_path):
    refusals = []
    presets.refuse(refusals, "X.sid", {"two_stage": True}, "aud_vs_approved", 0.71, 0.83)
    assert refusals == [{"song": "X.sid", "combination": "two_stage",
                         "criterion": "aud_vs_approved", "value": 0.71, "bound": 0.83}]
    out = tmp_path / "r.json"
    presets.write_refusals(out, refusals, "0.5.447", "abc1234")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["refusals"] == refusals and doc["head"] == "abc1234"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_presets.py -q -k "sound or length or tuple or approval_kind or refusal"`
Expected: `TypeError: fidelity_better() got an unexpected keyword argument 'sound_floor'` and `AttributeError: ... 'refuse'`, and the veto test failing on the ACE_II entry.

- [ ] **Step 3: The two vetoes in `fidelity_better`**

Change the signature to `def fidelity_better(cand: tuple, ref: tuple, margin: float = FIDELITY_MARGIN, sound_floor: float | None = None) -> bool:` and, immediately after the `keeps_notes = (...)` assignment, add:

```python
    # TWO VETOES ADDED AT v0.5.44x, AND ONLY TWO. "Any one improving" is a
    # sound acceptance rule and an unsound replacement rule (CLAUDE.md), and
    # the last time this function grew five vetoes it refused the candidate
    # it was built to protect. Each bound here is MEASURED: the sound floor
    # comes from build/sound_calibration.json, the length tolerance is the
    # listener's own rule.
    def slot(state, i):
        return state[i] if len(state) > i else None

    # 1. The rendered sound may not move AWAY from the original by more than
    # the calibrated noise floor. Never an acceptor -- `aud` rewards deleted
    # events exactly as `wave` does (section 7.eee).
    if sound_floor is not None:
        c_aud, r_aud = slot(cand, 9), slot(ref, 9)
        if c_aud is not None and r_aud is not None and c_aud < r_aud - sound_floor:
            return False
    # 2. The conversion must still end with the original, +-5 s.
    c_len = slot(cand, 10)
    if c_len is not None and abs(c_len) > 5.0:
        return False
```

(`5.0` is `fidelity.LENGTH_TOLERANCE`; import it at the top of `presets.py` as `from fidelity import LENGTH_TOLERANCE` if `fidelity` is importable there without a cycle — it is imported lazily inside `tune_by_fidelity` today, so define `LENGTH_TOLERANCE = 5.0` beside `FIDELITY_MARGIN` with a comment naming its source.)

- [ ] **Step 4: Refusal records**

Add near `prune_inert`:

```python
def refuse(refusals: list | None, song: str, combination: dict, criterion: str,
           value, bound) -> None:
    """A measured NO is a record, not an absence. presets.json cannot tell a
    missing entry from a refused one; build/search_refusals.json can."""
    if refusals is None:
        return
    refusals.append({"song": song,
                     "combination": " ".join(sorted(k for k, v in combination.items() if v)) or "default",
                     "criterion": criterion, "value": value, "bound": bound})


def write_refusals(path: Path, refusals: list, version: str, head: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generator": f"h2g {version} presets.py", "head": head,
                                "refusals": refusals}, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 5: The final-winner checks in `tune_by_fidelity`**

Extend the signature: `def tune_by_fidelity(sid_path, base, multiplier, siddump, gt2reloc, seconds, log=lambda m: None, refusals=None, approved=None, cal=None, doc=None) -> dict:`. The per-candidate `play()` tuple stays as it is (nine slots). After the `hard_restart_frames` pass and before `prune_inert`, add the checks that run ONCE per song rather than per candidate — one extra render, not thirty-one:

```python
    # THE FINAL-WINNER CHECKS. Rendering every candidate would multiply the
    # 8-minute corpus search by the render cost; the two vetoes and the
    # approval question are asked of the WINNER against the DEFAULT instead.
    # A winner that fails is refused whole and the song keeps what the
    # previous run recorded (the `search failed` rule), with the criterion
    # written to build/search_refusals.json.
    def sound_and_length(extra: dict):
        blob = convert(str(sid_path), log=lambda m: None, **base, **FIXED, **extra)
        blob, _ = F.legalise_restarts(blob)
        packed = F.pack_sid(blob, workdir, gt2reloc, multiplier)
        if packed is None:
            return None, None, blob
        dump = _dump(packed, ours_sub)
        lag = 0.02 * F.startup_lag(orig, dump)[0]
        import sound                                    # noqa: PLC0415
        snd = sound.compare_sids(local, packed, seconds, sub, ours_sub, prior_s=lag)
        ln = F.length_compare(orig, dump, seconds).get("length_delta")
        return snd.get("aud"), ln, blob

    if out:
        r_aud, _, _ = sound_and_length({})
        c_aud, c_len, winner_blob = sound_and_length(out)
        floor = (cal or {}).get("noise_floor")
        if not fidelity_better(ref + (c_aud, c_len), ref + (r_aud, None),
                               margin=-1.0, sound_floor=floor):
            # margin=-1 disables the acceptance terms: only the vetoes speak.
            crit = "length" if (c_len is not None and abs(c_len) > LENGTH_TOLERANCE) else "aud_vs_orig"
            refuse(refusals, sid_path.name, out, crit,
                   c_len if crit == "length" else c_aud,
                   LENGTH_TOLERANCE if crit == "length" else (r_aud or 0) - (floor or 0))
            log(f"    {sid_path.name}: {' '.join(sorted(out))} refused -- {crit}")
            return {}
        # An approved tune: the winner must INHERIT the human verdict.
        a = (approved or {}).get(sid_path.stem)
        if a and doc is not None:
            import approvals as AP                        # noqa: PLC0415
            verdict, _ = AP.assess(sid_path.stem, sid_path, a["sng_sha256"], doc, seconds,
                                   cal, gt2reloc, siddump, workdir, current_sng=winner_blob)
            if verdict["status"] not in ("exact", "inherited"):
                crit = verdict["failed"][0] if verdict["failed"] else verdict["status"]
                ev = verdict["evidence"]
                refuse(refusals, sid_path.name, out, crit,
                       ev.get(crit) if not isinstance(ev.get(crit), list) else ev.get(crit)[-1],
                       (cal or {}).get("closeness_floor"))
                log(f"    {sid_path.name}: {' '.join(sorted(out))} refused -- "
                    f"{crit} (approval would not be inherited)")
                return {}
```

Note `margin=-1.0`: with `plays_more = cand[0] >= ref[0] + margin` always true, the call reduces to the vetoes. State that in a comment; it is deliberate, not a trick.

- [ ] **Step 6: `main()` plumbing and the veto entry**

In `build_parser()` add `parser.add_argument("--refusals", default=None, help="where to write build/search_refusals.json (default: <output dir>/build/search_refusals.json)")`. In `main()`, before the song loop:

```python
    refusals: list = []
    import approvals as AP                                # noqa: PLC0415
    approved, cal = (AP.approved_tunes(), AP.load_calibration()) if args.fidelity else ({}, None)
    if args.fidelity and cal is None:
        print("  no sound calibration: approvals cannot be inherited and every "
              "approved tune's winner will be refused -- run sound_calibrate.py first",
              file=sys.stderr)
```
pass `refusals=refusals, approved=approved, cal=cal, doc=carried_doc` into `tune_by_fidelity` (where `carried_doc` is the previous presets document `main` already loads to build `carried`; if it only keeps the `songs` dict, load the file once more here), and after the loop:

```python
    if args.fidelity:
        rpath = Path(args.refusals) if args.refusals else Path(args.output).resolve().parent / "build" / "search_refusals.json"
        write_refusals(rpath, refusals, __version__, F.git_label(Path(args.output).resolve().parent))
        print(f"  {len(refusals)} refusal(s) -> {rpath}", file=sys.stderr)
```

Delete the `"ACE_II.sid": {"hard_restart_frames"}` entry from `FIDELITY_VETOED`, keeping its comment block rewritten as: *"ACE_II's frame pair was vetoed here from v0.5.407 to v0.5.44x because it invalidated a human approval. That question is computed now (`approvals.assess`, called on every approved tune's winner) and the answer is in build/search_refusals.json — an entry here is only ever for a search that compared the wrong music."*

- [ ] **Step 7: Run the tests**

Run: `cd python && python -m pytest tests/test_presets.py tests/test_gate_criterion.py tests/test_onset_criterion.py tests/test_hard_restart.py tests/test_search_matches_report.py -q`
Expected: all pass.

- [ ] **Step 8: The search, diffed before adoption**

Run from `python/` (background; ~8 min plus one render per song — record the time):
```
python presets.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" --fidelity -t 60 -o C:/t/ab_presets_candidate.json --refusals C:/t/ab_refusals.json
```
Then diff `C:/t/ab_presets_candidate.json` against `presets.json` per song (a 20-line script: load both, print every song whose entry differs, key by key). Expected: ACE_II either gains `hard_restart_frames: 3` (its winner inherited) or appears in `ab_refusals.json` with the criterion that refused it; no song LOSES a carried setting (`regrid`, `rest_envelope_silence`, `real_firstwave_instruments`, `pulse_phase`). Read `ab_refusals.json` in full. **Adopt only if the diff is exactly what the refusals explain.** Then copy the candidate to `presets.json` and the refusals to `build/search_refusals.json`.

- [ ] **Step 9: Regenerate the artefacts on the adopted presets**

From `python/`:
```
python fidelity.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" -t 60 --sound --presets ../presets.json -o ../docs/FIDELITY.md --json ../build/fidelity.json
python approvals.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" -t 60
python survey.py "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob" -o ../docs/SURVEY.md --legal-restart --gt2reloc
```
Byte-hash: this is the one commit where `moved > 0` is expected — name every moved file in the commit message and match each to a presets diff line.

- [ ] **Step 10: Docs and commit-ready**

README § *Per-song presets*: the two vetoes, the final-winner rule and its cost, `build/search_refusals.json`. CLAUDE.md: rewrite the `FIDELITY_VETOED`/ACE_II sentences in the "Forcing one option" and "A search that fails" paragraphs to point at `approvals.py`; add one bullet: *a measured refusal is written to `build/search_refusals.json` — read it before calling a missing preset entry a decision*. H2G-CONVERSION-METHOD.md § 7: one entry, "the search respects approvals by measurement". On go-ahead: bump (`"presets: the search respects approvals by measurement, and a refusal is a record"`), graphify update, commit code + tests + docs + `presets.json docs/FIDELITY.md docs/SURVEY.md build/fidelity.json build/approvals.json build/search_refusals.json`.

---

### Task 8: `fidelity_queue.py` — the derived queue

**Files:**
- Create: `python/fidelity_queue.py`
- Test: `python/tests/test_queue.py`
- Create (generated): `docs/QUEUE.md`, `build/queue.json`
- Modify: `CLAUDE.md` (graphify/whattask paragraph: `docs/QUEUE.md` is a `/whattask` source), `README.md` § *Fidelity* (one paragraph).

**Interfaces:**
- Consumes: `build/fidelity.json` rows (keys `file`, `aud`, `loud`, `length_delta`, `length_bounded`, `onset_census`, `hold_census`, every `Dimension` key), `build/approvals.json`, `build/search_refusals.json`, `.claude/tasks/whattask.json` (r), `.claude/tasks/runs.jsonl` (r), previous `build/queue.json`, `fidelity.DIMENSIONS`, `fidelity.ONSET_KINDS`, `fidelity.HOLD_KINDS`.
- Produces:
  - `entries_from(rows, approvals, refusals, prior: dict, plan: dict, runs: dict, version: str) -> list[dict]`; each entry `{"id", "tier", "source", "cause", "files", "tag", "evidence", "verify", "first_seen", "last_seen", "already_tracked", "already_refuted"}`.
  - Pure tier builders, each `-> list[dict]`: `stale_approvals(approvals)`, `length_failures(rows)`, `refusal_entries(refusals)`, `voice_deficits(rows)` (needs `aud_voices` — see Step 3 note), `census_buckets(rows)`, `column_outliers(rows)`.
  - `slug(*parts) -> str`; `annotate(entries, plan, runs) -> None`; `carry_seen(entries, prior, version) -> None`; `closed_since(prior, entries) -> list[dict]`; `render(entries, closed, meta) -> str`.
  - CLI: `python fidelity_queue.py --from-json ../build/fidelity.json -o ../docs/QUEUE.md --json ../build/queue.json`.

- [ ] **Step 1: Write the failing tests**

```python
# python/tests/test_queue.py
"""The derived queue: causes ranked by tier, never a weighted scalar."""
import json

import fidelity_queue as Q


def _row(name, **kw):
    r = {"file": name, "status": "measured", "melody": 0.9, "aud": 0.8, "gate": 0.7}
    r.update(kw)
    return r


def test_slug_is_stable_and_kebab():
    assert Q.slug("Refusal", "aud vs approved", "ACE_II") == "refusal-aud-vs-approved-ace-ii"
    assert Q.slug("Refusal", "aud vs approved", "ACE_II") == Q.slug("Refusal", "aud vs approved", "ACE_II")


def test_stale_approvals_are_tier_1_and_user_tagged():
    appr = {"ACE_II": {"status": "stale", "failed": ["aud_vs_approved"],
                       "listener_should_check": "aud_vs_approved", "evidence": {"aud_vs_approved": 0.7}}}
    (e,) = Q.stale_approvals(appr)
    assert e["tier"] == 1 and e["tag"] == "[user]" and e["files"] == ["ACE_II"]
    assert "aud_vs_approved" in e["verify"]


def test_length_failures_are_tier_2():
    rows = [_row("A.sid", length_delta=7.5, length_bounded=False),
            _row("B.sid", length_delta=1.0, length_bounded=False),
            _row("C.sid", length_delta=12.0, length_bounded=True)]
    got = Q.length_failures(rows)
    assert [e["files"] for e in got] == [["A"], ["C"]]
    assert all(e["tier"] == 2 and e["tag"] == "[main]" for e in got)


def test_refusals_carry_their_margin():
    refs = [{"song": "X.sid", "combination": "two_stage", "criterion": "aud_vs_orig",
             "value": 0.80, "bound": 0.81}]
    (e,) = Q.refusal_entries(refs)
    assert e["tier"] == 3 and e["evidence"]["margin"] == -0.01 and e["files"] == ["X"]


def test_census_buckets_group_by_cause_across_files():
    rows = [_row("A.sid", onset_census=[{"kind": "phase", "effect": 0x01}, {"kind": "match"}]),
            _row("B.sid", onset_census=[{"kind": "phase", "effect": 0x01}]),
            _row("C.sid", onset_census=[{"kind": "flat", "effect": 0x80}])]
    got = Q.census_buckets(rows)
    top = got[0]
    assert top["tier"] == 5 and sorted(top["files"]) == ["A", "B"]
    assert top["cause"].startswith("onset phase")
    assert len(got) == 4        # two causes x (subagent confirm, main fix)


def test_column_outliers_use_the_corpus_spread():
    rows = [_row(f"F{i}.sid", gate=0.7) for i in range(10)] + [_row("Bad.sid", gate=0.1)]
    got = Q.column_outliers(rows)
    assert [e["files"] for e in got] == [["Bad"]]
    assert got[0]["tier"] == 6 and "gate" in got[0]["cause"]


def test_entries_are_ordered_by_tier_then_files_reached():
    e1 = {"id": "a", "tier": 5, "files": ["A"]}
    e2 = {"id": "b", "tier": 5, "files": ["A", "B", "C"]}
    e3 = {"id": "c", "tier": 2, "files": ["Z"]}
    assert [e["id"] for e in Q.ordered([e1, e2, e3])] == ["c", "b", "a"]


def test_annotate_marks_tracked_and_refuted_without_dropping():
    entries = [{"id": "x", "files": ["Commando"], "cause": "column pitch outlier", "tier": 6}]
    plan = {"tasks": [{"id": "commando-voice-1-plays-g-sharp-7", "source": "", "title": "",
                       "verify": "Commando voice 1 ... pitch ..."}]}
    runs = {"some-run": {"outcome": "done", "evidence": "Commando ... origin shift refuted ... pitch"}}
    Q.annotate(entries, plan, runs)
    assert entries[0]["already_tracked"] == "commando-voice-1-plays-g-sharp-7"
    assert entries[0]["already_refuted"] == "some-run"
    assert len(entries) == 1


def test_first_and_last_seen_persist_and_closed_are_reported():
    prior = {"entries": [{"id": "old", "first_seen": "0.5.440", "last_seen": "0.5.446"},
                         {"id": "keep", "first_seen": "0.5.441", "last_seen": "0.5.446"}]}
    entries = [{"id": "keep"}, {"id": "new"}]
    Q.carry_seen(entries, prior, "0.5.447")
    assert entries[0]["first_seen"] == "0.5.441" and entries[0]["last_seen"] == "0.5.447"
    assert entries[1]["first_seen"] == "0.5.447"
    assert [c["id"] for c in Q.closed_since(prior, entries)] == ["old"]


def test_render_has_one_table_per_tier_and_a_provenance_line():
    entries = [{"id": "a", "tier": 2, "source": "length", "cause": "runs long", "files": ["A"],
                "tag": "[main]", "evidence": {"length_delta": 7.5}, "verify": "ends within 5 s",
                "first_seen": "0.5.447", "last_seen": "0.5.447",
                "already_tracked": None, "already_refuted": None}]
    text = Q.render(entries, [], {"version": "0.5.447", "head": "abc1234", "seconds": 60})
    assert "Generated by `python/fidelity_queue.py` (h2g 0.5.447, abc1234)" in text
    assert "## Tier 2" in text and "| `a` |" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_queue.py -q`
Expected: `ModuleNotFoundError: No module named 'fidelity_queue'`

- [ ] **Step 3: Write `python/fidelity_queue.py`**

```python
#!/usr/bin/env python3
"""The report's misses as a ranked queue of CAUSES.

    python fidelity_queue.py --from-json ../build/fidelity.json \
        -o ../docs/QUEUE.md --json ../build/queue.json

`/whattask` reads docs/QUEUE.md as a source beside todo.md. Nothing here
writes the plan.

An entry is a cause, not a file: the onset census turned "18% disagree" into
`$01 x19, $04 x11, $80 x6` and the `$0A` bucket was a mechanism within the
session -- that is the shape reproduced here. Six sources; THE TIER IS THE
RANK, chosen for what each means rather than fitted:

  1 stale approvals   -- a human verdict the tool could not carry forward;
                         nothing else can close these            [user]
  2 length failures   -- `len` outside +-5 s, or unbounded         [main]
  3 search refusals   -- a measured gain refused by a criterion    [main]
  4 voice deficits    -- one voice's `aud` well below the others   [main]
  5 census buckets    -- onset/hold kinds by cause, corpus-wide    [subagent] + [main]
  6 column outliers   -- a file far below the corpus median        lowest: a lead

Within a tier: files reached first (a shared cause is one fix), then gap.
Never a weighted scalar across tiers.

Dedupe is by ANNOTATION: an entry a plan task already names is marked
`already_tracked`, one a done run record already refuted `already_refuted`.
Neither drops it -- the reader decides -- so a regeneration cannot re-propose
a refuted cause without saying it was refuted.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F                       # noqa: E402
from h2g import __version__                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAG = {1: "[user]", 2: "[main]", 3: "[main]", 4: "[main]", 6: "[main]"}
MAD_MULTIPLE = 3.0      # a convention (robust outlier rule), stated rather than fitted


def slug(*parts) -> str:
    s = "-".join(str(p) for p in parts).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _stem(name: str) -> str:
    return name[:-4] if name.endswith(".sid") else name


# ---- tiers --------------------------------------------------------------
def stale_approvals(approvals: dict) -> list[dict]:
    out = []
    for stem, rec in approvals.items():
        if rec.get("status") != "stale":
            continue
        check = rec.get("listener_should_check") or (rec.get("failed") or ["?"])[0]
        out.append({"id": slug("listen", stem), "tier": 1, "source": "build/approvals.json",
                    "cause": f"approval stale: {', '.join(rec.get('failed') or [])}",
                    "files": [stem], "tag": TAG[1],
                    "evidence": {k: rec.get("evidence", {}).get(k) for k in rec.get("failed") or []},
                    "verify": (f"Re-stage {stem} with listen.py --voices and listen for "
                               f"`{check}`; then either re-approve (update approved.json's "
                               "sng_sha256 by hand) or record the defect the ear found.")})
    return out


def length_failures(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        d, b = r.get("length_delta"), r.get("length_bounded")
        if d is None or (abs(d) <= F.LENGTH_TOLERANCE and not b):
            continue
        stem = _stem(r["file"])
        out.append({"id": slug("length", stem), "tier": 2, "source": "fidelity.json length_delta",
                    "cause": "runs long past the original's ending" if d > 0 else "ends early",
                    "files": [stem], "tag": TAG[2],
                    "evidence": {"length_delta": d, "length_bounded": bool(b)},
                    "verify": (f"{stem}'s `len` inside +-{F.LENGTH_TOLERANCE:.0f} s with "
                               "`length_bounded` false, regenerated in docs/FIDELITY.md.")})
    return out


def refusal_entries(refusals: list[dict]) -> list[dict]:
    out = []
    for x in refusals:
        stem = _stem(x["song"])
        margin = (None if x.get("value") is None or x.get("bound") is None
                  else round(float(x["value"]) - float(x["bound"]), 4))
        out.append({"id": slug("refused", x["combination"], x["criterion"], stem), "tier": 3,
                    "source": "build/search_refusals.json",
                    "cause": f"{x['combination']} refused by {x['criterion']}",
                    "files": [stem], "tag": TAG[3],
                    "evidence": {"value": x.get("value"), "bound": x.get("bound"), "margin": margin},
                    "verify": (f"Either {stem} adopts `{x['combination']}` with `{x['criterion']}` "
                               "no longer failing (regenerate presets with --fidelity and read "
                               "build/search_refusals.json), or the refusal is recorded as right "
                               "with the mechanism named.")})
    return out


def voice_deficits(rows: list[dict]) -> list[dict]:
    """A voice whose `aud` sits well below the file's others.

    Needs the per-voice readings `fidelity.py --sound-voices` stores as
    `aud_voices: [v0, v1, v2]`; a row without them contributes nothing.
    """
    out = []
    for r in rows:
        vs = r.get("aud_voices")
        if not vs or len([v for v in vs if v is not None]) < 2:
            continue
        good = [v for v in vs if v is not None]
        med = statistics.median(good)
        for i, v in enumerate(vs):
            if v is not None and v < med - 0.2:
                stem = _stem(r["file"])
                out.append({"id": slug("voice", stem, i), "tier": 4, "source": "fidelity.json aud_voices",
                            "cause": f"voice {i} sounds unlike the original where the others do not",
                            "files": [stem], "tag": TAG[4],
                            "evidence": {"aud_voices": vs, "instruments": r.get("voice_instruments", {}).get(str(i))},
                            "verify": (f"{stem} voice {i}'s `aud` within 0.1 of the file's other "
                                       "voices, with the instrument it plays named from "
                                       "instrument_stamps and its effect bits read.")})
    return out


def census_buckets(rows: list[dict]) -> list[dict]:
    """Onset and hold census records grouped by (column, kind, effect byte)."""
    buckets: dict[tuple, dict] = defaultdict(lambda: {"files": set(), "n": 0})
    for r in rows:
        stem = _stem(r["file"])
        for col, key in (("onset", "onset_census"), ("hold", "hold_census")):
            for rec in r.get(key) or []:
                if rec.get("kind") in ("match",):
                    continue
                k = (col, rec.get("kind"), rec.get("effect"))
                buckets[k]["files"].add(stem)
                buckets[k]["n"] += 1
    out = []
    for (col, kind, eff), b in buckets.items():
        cause = f"{col} {kind}" + (f" with effect ${eff:02X}" if isinstance(eff, int) else "")
        files = sorted(b["files"])
        base = {"tier": 5, "source": f"fidelity.json {col}_census", "cause": cause,
                "files": files, "evidence": {"instruments": b["n"], "files": len(files)}}
        out.append(dict(base, id=slug("census", col, kind, eff, "confirm"), tag="[subagent]",
                        verify=(f"The {b['n']} instrument(s) in this bucket share ONE cause, "
                                "shown by reading the record bytes of each; or the bucket is split "
                                "and the split written into the census.")))
        out.append(dict(base, id=slug("census", col, kind, eff, "fix"), tag="[main]",
                        verify=(f"The `{col}` column's `{kind}` count falls on every file in this "
                                "bucket and rises on none, corpus A/B, with the emitter change "
                                "named.")))
    return out


def column_outliers(rows: list[dict]) -> list[dict]:
    out = []
    measured = [r for r in rows if r.get("status") == "measured"]
    for d in F.DIMENSIONS:
        if d.kind != "fraction":
            continue
        vals = [(r, d.value(r)) for r in measured if d.value(r) is not None]
        if len(vals) < 8:
            continue
        xs = [v for _, v in vals]
        med = statistics.median(xs)
        mad = statistics.median(abs(x - med) for x in xs) or 0.0
        if mad == 0.0:
            continue
        for r, v in vals:
            if v < med - MAD_MULTIPLE * mad:
                stem = _stem(r["file"])
                out.append({"id": slug("outlier", d.column, stem), "tier": 6,
                            "source": f"fidelity.json {d.key}",
                            "cause": f"{d.column} far below the corpus", "files": [stem],
                            "tag": TAG[6],
                            "evidence": {d.column: v, "median": med, "mad": mad},
                            "verify": (f"{stem}'s `{d.column}` within {MAD_MULTIPLE:.0f} MAD of the "
                                       "corpus median, or its cause named -- run "
                                       f"`fidelity.py {stem}.sid --diagnose` FIRST: six harness "
                                       "defects have looked exactly like this.")})
    return out


# ---- ordering, annotation, persistence ------------------------------------
def ordered(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e["tier"], -len(e.get("files", [])), e["id"]))


def annotate(entries: list[dict], plan: dict, runs: dict) -> None:
    tasks = plan.get("tasks") or []
    for e in entries:
        e.setdefault("already_tracked", None)
        e.setdefault("already_refuted", None)
        col = e["cause"].split()[0].lower()
        for t in tasks:
            text = " ".join(str(t.get(k, "")) for k in ("id", "title", "source", "verify")).lower()
            if any(f.lower() in text for f in e["files"]) and col in text:
                e["already_tracked"] = t["id"]
                break
        for rid, r in runs.items():
            if r.get("outcome") != "done":
                continue
            ev = str(r.get("evidence", "")).lower()
            if any(f.lower() in ev for f in e["files"]) and col in ev and "refut" in ev:
                e["already_refuted"] = rid
                break


def carry_seen(entries: list[dict], prior: dict, version: str) -> None:
    seen = {p["id"]: p for p in (prior or {}).get("entries", [])}
    for e in entries:
        e["first_seen"] = seen.get(e["id"], {}).get("first_seen", version)
        e["last_seen"] = version


def closed_since(prior: dict, entries: list[dict]) -> list[dict]:
    now = {e["id"] for e in entries}
    return [p for p in (prior or {}).get("entries", []) if p["id"] not in now]


def entries_from(rows, approvals, refusals, prior, plan, runs, version) -> list[dict]:
    entries = (stale_approvals(approvals) + length_failures(rows) + refusal_entries(refusals)
               + voice_deficits(rows) + census_buckets(rows) + column_outliers(rows))
    entries = ordered(entries)
    annotate(entries, plan, runs)
    carry_seen(entries, prior, version)
    return entries


# ---- output --------------------------------------------------------------
TIER_NAMES = {1: "Stale approvals -- a listen is the only thing that closes these",
              2: "Length rule failures", 3: "Search refusals",
              4: "Voice deficits in the rendered sound", 5: "Census buckets",
              6: "Column outliers -- leads, not findings"}


def render(entries: list[dict], closed: list[dict], meta: dict) -> str:
    out = ["# Fidelity queue", "",
           f"Generated by `python/fidelity_queue.py` (h2g {meta['version']}, {meta['head']}), "
           f"from a {meta['seconds']} s run. {len(entries)} entries. `/whattask` reads this as a "
           "source; nothing here writes the plan.", ""]
    for tier in sorted(TIER_NAMES):
        es = [e for e in entries if e["tier"] == tier]
        out += [f"## Tier {tier}: {TIER_NAMES[tier]}", ""]
        if not es:
            out += ["(none)", ""]
            continue
        out += ["| id | files | cause | tag | evidence | verify | seen | tracked / refuted |",
                "|---|---|---|---|---|---|---|---|"]
        for e in es:
            out.append("| `%s` | %s | %s | %s | %s | %s | %s -> %s | %s |" % (
                e["id"], ", ".join(e["files"]), e["cause"], e["tag"],
                json.dumps(e["evidence"], default=str), e["verify"].replace("|", "\\|"),
                e["first_seen"], e["last_seen"],
                " / ".join(x or "-" for x in (e.get("already_tracked"), e.get("already_refuted")))))
        out.append("")
    if closed:
        out += ["## Closed since last run", ""] + [f"- `{c['id']}` (last seen {c.get('last_seen')})"
                                                   for c in closed] + [""]
    return "\n".join(out)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _runs(path: Path) -> dict:
    last = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r.get("id")] = r
    return last


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fidelity_queue")
    p.add_argument("--from-json", default=str(ROOT / "build" / "fidelity.json"))
    p.add_argument("-o", "--output", default=str(ROOT / "docs" / "QUEUE.md"))
    p.add_argument("--json", default=str(ROOT / "build" / "queue.json"))
    args = p.parse_args(argv)
    rows = _load_json(Path(args.from_json), [])
    rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
    seconds = next((r.get("seconds") for r in rows if r.get("seconds")), 60)
    approvals = _load_json(ROOT / "build" / "approvals.json", {}).get("tunes", {})
    refusals = _load_json(ROOT / "build" / "search_refusals.json", {}).get("refusals", [])
    prior = _load_json(Path(args.json), {})
    plan = _load_json(ROOT / ".claude" / "tasks" / "whattask.json", {})
    runs = _runs(ROOT / ".claude" / "tasks" / "runs.jsonl")
    entries = entries_from(rows, approvals, refusals, prior, plan, runs, __version__)
    closed = closed_since(prior, entries)
    meta = {"version": __version__, "head": F.git_label(ROOT), "seconds": seconds}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({**meta, "entries": entries, "closed": closed},
                                          indent=2, default=str) + "\n", encoding="utf-8")
    Path(args.output).write_text(render(entries, closed, meta), encoding="utf-8")
    print(f"wrote {args.output}: {len(entries)} entries, {len(closed)} closed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Note on tier 4:** `voice_deficits` reads `aud_voices`, which nothing writes yet. Add to Task 3's `_measure` hook, under a `--sound-voices` flag, three more `compare_sids` calls with the packed conversion rendered per voice (`renderer=lambda s, o, sec, sub: listen.render_sidplayfp(s, o, sec, sub, mute=tuple(v for v in (1, 2, 3) if v != voice + 1))`), storing `row["aud_voices"] = [v0, v1, v2]`. Do that as Step 3b of this task, with one test in `test_fidelity.py` asserting the key's shape; it is three renders per file and stays off by default like `--sound`.

- [ ] **Step 4: Run the tests**

Run: `cd python && python -m pytest tests/test_queue.py -q`
Expected: `10 passed`. If `test_census_buckets_group_by_cause_across_files` counts 3 rather than 4, a `match` record leaked into a bucket — the `kind in ("match",)` skip is the fix, not the test.

- [ ] **Step 5: Generate the queue for real**

From `python/`: `python fidelity_queue.py`
Expected: `docs/QUEUE.md` with tiers 1-6 (tier 4 empty until a `--sound-voices` run exists), `build/queue.json`. Read tier 1: it must list exactly the tunes `build/approvals.json` marks `stale`. Read tier 6 against `docs/FIDELITY.md` by eye for three entries — each must be genuinely far below the column's median.

- [ ] **Step 6: Docs and commit-ready**

CLAUDE.md: in the *Regenerate the generated artefacts* bullet add `python fidelity_queue.py` after the fidelity regeneration, and in the *Say, for every proposed task* section add one sentence: `/whattask` lists `docs/QUEUE.md` as a source. README § *Fidelity*: one paragraph on the queue and its six tiers. Byte-hash `moved 0`; suite green. On go-ahead: bump (`"fidelity_queue: the report's misses as a ranked queue of causes"`), graphify update, regenerate, commit `python/fidelity_queue.py python/tests/test_queue.py docs/QUEUE.md build/queue.json CLAUDE.md README.md` (plus the Task 3b `fidelity.py`/`test_fidelity.py` change).

---

### Task 9: `drift` as an acceptance term — gated

**Files:**
- Modify: `python/presets.py` (`fidelity_better`, `tune_by_fidelity`'s `play()` tuple), `python/tests/test_presets.py` (append).
- Modify: `README.md` § `--regrid`, `CLAUDE.md` (the `--regrid` paragraph's "`fidelity_better` cannot select it" sentences).

**Gate — check before writing a line:** the plan task `regrid-could-be-searchable-from-repeated-attack-run-length-without-a-trace` must be `outcome: "done"` in `.claude/tasks/runs.jsonl`, with its evidence showing `FIDELITY.md`'s `drift` column and `--pace`'s integrated drift agreeing on the 13 files `presets.json` records `regrid: true` for. If it is not, STOP this task and say so: the term would select `--regrid` on an instrument never checked against the one the 13 adoptions were made on.

**Interfaces:**
- Consumes: `fidelity.pitch_drift(...)` or whatever function produces the row's `drift_per_1000` (find it: `grep -n "drift_per_1000" python/fidelity.py` → the function whose dict carries it; call it exactly as `_measure` does).
- Produces: `fidelity_better` reads `cand[11]` / `ref[11]` (`drift_per_1000`, float|None); `play()` computes it for every candidate.

- [ ] **Step 1: Write the failing tests**

```python
def _state12(drift=None, **kw):
    return _state(**kw) + (drift,)


def test_drift_closer_to_zero_selects_when_nothing_else_moves():
    ref = _state12(drift=-9.3)
    assert presets.fidelity_better(_state12(drift=-1.6), ref)
    assert presets.fidelity_better(_state12(drift=0.0), ref)


def test_drift_is_compared_in_log_space_so_sign_does_not_matter():
    """A drift of +2 and -2 are the same size of wrong; -1.6 beats +9.3."""
    assert presets.fidelity_better(_state12(drift=1.6), _state12(drift=-9.3))
    assert not presets.fidelity_better(_state12(drift=-9.3), _state12(drift=1.6))


def test_drift_cannot_buy_a_melody_loss():
    assert not presets.fidelity_better(_state12(melody=0.85, drift=0.0), _state12(drift=-9.3))


def test_an_absent_drift_recommends_nothing():
    assert not presets.fidelity_better(_state12(drift=None), _state12(drift=-9.3))
```

- [ ] **Step 2: Run to verify they fail** — `cd python && python -m pytest tests/test_presets.py -q -k drift` → the first assertion fails (`False` returned).

- [ ] **Step 3: The term**

In `fidelity_better`, after the existing acceptance terms and before the final `return`, add:

```python
    # `drift` closer to zero, everything else held: what makes --regrid
    # searchable. Log-distance, because +2 and -2 are the same size of wrong
    # (CLAUDE.md, "compare a ratio in log space"). Gated on the drift-vs-pace
    # agreement task having closed -- see the plan; the term must never be
    # enabled on an instrument unchecked against the one the 13 hand
    # adoptions were made on.
    c_d, r_d = slot(cand, 11), slot(ref, 11)
    drift_closer = (c_d is not None and r_d is not None
                    and math.log1p(abs(c_d)) < math.log1p(abs(r_d)) - 1e-9)
```
and include `drift_closer` in the `keeps_notes and (...)` acceptance disjunction. In `play()`, append the row's `drift_per_1000` as the twelfth slot (compute it with the same call `_measure` uses; it needs no lag). In `main()`, leave `regrid` OUT of `FIDELITY_TOGGLES` — that is the user's cost decision (`regrid-is-not-in-fidelity-toggles-so-the-search-never-walks-it`); this task makes the term exist and proves it with tests.

- [ ] **Step 4: Run the tests** — `tests/test_presets.py tests/test_gate_criterion.py tests/test_onset_criterion.py` all pass.

- [ ] **Step 5: Docs and commit-ready**

README § `--regrid` and CLAUDE.md's `--regrid` paragraph: replace "`fidelity_better` cannot select it" with "`fidelity_better` reads `drift` since v0.5.45x; `regrid` joins `FIDELITY_TOGGLES` only by the user's decision, because it doubles the walk". Byte-hash `moved 0` (the toggle is not walked). On go-ahead: bump (`"fidelity_better reads drift, so --regrid is selectable the day it is walked"`), graphify update, regenerate, commit.

---

## Self-review against the spec

**Spec coverage.** §1 metric → Tasks 1-3 (columns, `--sound`, cache, alignment, silence rule, blind spots in descriptions, `AUDIO` sentinel). §2 approvals → Task 5 (three criteria, never creates, always against the human sha, `listener_should_check`, `build/approvals.json`) and Task 6 (three states on the page). §3 acceptance → Task 7 (two vetoes, computed approval check, refusals file, ACE_II veto deleted) and Task 9 (`drift`, gated). §4 queue → Task 8 (six tiers, cause-grouped, annotation dedupe, persistence, `/whattask` source). §5 validation → Task 4 (five checks, thresholds into JSON, Last_V8 dropped with the reason), tests named per task, byte-hash on every task, rollout order = task order, docs in each task. Spec's per-voice diagnostic (`--audio-voices`) is `--sound-voices` in Task 8 step 3b.

**Deviations from the spec, all deliberate:** flag `--sound` not `--audio` (the latter exists and is SIDM2's); module `sound.py`, calibrator `sound_calibrate.py` and queue `fidelity_queue.py` as separate files rather than `fidelity.py` flags (it is 7000 lines); calibration doc named `SOUND-CALIBRATION.md`; the search applies the vetoes and the inheritance check to the **final winner** rather than every candidate (one render per song, not thirty-one); Last_V8 removed from check 4. The spec is amended to match.

**Type consistency.** `compare_sids(orig, ours, seconds, sub_orig, sub_ours, prior_s=, cache=, renderer=)` is called that way in Tasks 3, 4, 5, 7. `inherit(approved_vs_orig, current_vs_orig, current_vs_approved, structure, cal, margin=, same_sha=)` matches its tests and `assess`. `fidelity_better` slot indices: 8 `orig_attacks` (existing), 9 `aud`, 10 `length_delta`, 11 `drift_per_1000`; `_state` helpers in Tasks 7 and 9 build exactly that. `record(stem, approved_sha, current_sha, verdict, previous, version)` matches its tests. `refuse(refusals, song, combination: dict, criterion, value, bound)` and `write_refusals(path, refusals, version, head)` match theirs.
