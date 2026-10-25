"""`sound.py`: the rendered-audio measure.

Synthetic signals only. Every test here has an answer known before the
measurement is taken -- identity is 1.0, a scaled copy is the same timbre at
a known level, an injected delay is recovered -- because the metric will later
decide whether a human approval survives a change, and a metric that is not
pinned on cases with a known answer cannot be trusted with that.
"""
import json
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


# --------------------------------------------------------------------------
# `window_s`: a prefix of the ALIGNED overlap. The pair below differs only in
# 2.5-4 s of a 6 s signal, so a 2 s prefix sees identical material and reads
# exactly 1.0 (the gap is there because a frame is 2048 samples wide -- a
# difference starting AT 2.0 s reaches 16 frames of a 2 s prefix and reads
# 0.9936, measured), the whole reads under it, and a window past the end is
# the whole. All three matter: the first alone passes on a slice from the wrong
# end, the second alone on a window that is ignored.
# --------------------------------------------------------------------------
def _pair_differing_in(t0, t1, seconds=6.0, hz_other=880.0):
    a = _sine(seconds)
    b = a.copy()
    i0, i1 = int(t0 * RATE), int(t1 * RATE)
    b[i0:i1] = _sine(seconds, hz=hz_other)[i0:i1]
    return a, b


def test_window_s_scores_a_prefix_of_the_overlap_and_none_scores_the_whole():
    a, b = _pair_differing_in(2.5, 4.0)
    fa, fb = sound.features(a, RATE), sound.features(b, RATE)
    prefix = sound.compare_features(fa, fb, 0, window_s=2.0)
    whole = sound.compare_features(fa, fb, 0)
    beyond = sound.compare_features(fa, fb, 0, window_s=1000.0)
    assert prefix["aud"] == pytest.approx(1.0, abs=1e-9), (
        "the first 2 s are identical on both sides; a prefix that sees the "
        "880 Hz stretch is not a prefix")
    assert whole["aud"] < 0.9
    assert beyond == whole, "a window past the overlap's end is the whole overlap"
    # and the prefix is that many frames, not some other count
    assert prefix["sound_frames"] == int(2.0 / fa.hop_s)


def test_window_s_is_cut_after_alignment_not_before():
    """`b` is delayed 0.2 s. Aligned, its first 2 s of material are the
    original's first 2 s and the prefix scores clean; scored at lag 0 the same
    prefix compares the tone against 0.2 s of silence and reads lower. If the
    cut were taken on either side's own timeline before the lag was applied,
    the two would not separate this way."""
    a, b = _pair_differing_in(2.5, 4.0)
    delayed = np.concatenate([np.zeros(int(0.2 * RATE), dtype=np.float32), b])
    fa, fb = sound.features(a, RATE), sound.features(delayed, RATE)
    lag = sound.align(fa, fb, prior_s=0.0, window_s=0.5)
    assert abs(lag * fa.hop_s - 0.2) <= 2 * fa.hop_s
    aligned = sound.compare_features(fa, fb, lag, window_s=2.0)
    unaligned = sound.compare_features(fa, fb, 0, window_s=2.0)
    assert aligned["aud"] > 0.99
    assert unaligned["aud"] < aligned["aud"] - 0.05


def test_prefix_keeps_both_slices_aligned_under_a_negative_lag():
    """`_overlap` under a negative lag starts `a` late and `b` at 0; the prefix
    must cut both at the same length from their own starts."""
    sa, sb = sound._overlap(sound.features(_sine(1.0), RATE),
                            sound.features(_sine(1.0), RATE), -10)
    pa, pb = sound._prefix(sa, sb, 50)
    assert (pa.start, pa.stop) == (10, 60)
    assert (pb.start, pb.stop) == (0, 50)
    # a window past the end leaves the overlap as it was
    assert sound._prefix(sa, sb, 10 ** 9) == (sa, sb)


def test_compare_wavs_passes_window_s_through(tmp_path):
    a, b = _pair_differing_in(2.5, 4.0)
    _write(tmp_path / "a.wav", a)
    _write(tmp_path / "b.wav", b)
    prefix = sound.compare_wavs(tmp_path / "a.wav", tmp_path / "b.wav", window_s=2.0)
    whole = sound.compare_wavs(tmp_path / "a.wav", tmp_path / "b.wav")
    assert prefix["aud"] == pytest.approx(1.0, abs=1e-9)
    assert whole["aud"] < 0.9


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


def test_content_key_carries_the_power_on_delay(tmp_path):
    """SABOTAGE TARGET: drop the delay from `content_key`'s hash and the two
    delays give one key -- a render made under a random/other delay (every
    render cached before `listen.SIDPLAYFP_POWER_ON_DELAY`) would be served
    as a hit under the current one."""
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    d = sound.listen.SIDPLAYFP_POWER_ON_DELAY
    assert sound.content_key(sid, d) != sound.content_key(sid, d + 1)
    assert sound.content_key(sid) == sound.content_key(sid, d)
    # and the key is not the bare-bytes sha a pre-flag render was named by
    import hashlib
    bare = hashlib.sha1(sid.read_bytes()).hexdigest()[:12]
    assert sound.content_key(sid) != bare


def test_render_cached_returns_none_when_the_renderer_fails(tmp_path):
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"x")
    assert sound.render_cached(sid, 1, 0, "orig", cache=tmp_path / "c",
                               renderer=lambda *a, **k: False) is None


# --------------------------------------------------------------------------
# `render_repeat`: a FRESH render every call, because the noise floor is the
# render's reproducibility. sidplayfp's power-on delay is random by default
# (`--delay=<n>` fixes it; listen.render_sidplayfp did not pass it through
# v0.5.491 -- `listen.SIDPLAYFP_POWER_ON_DELAY`, pinned in test_listen.py),
# so two renders of one .sid differed -- and `render_cached`, by design, can
# never see that: its second ask for the same bytes is free. The repeat
# render is still the only thing that MEASURES the floor, flag or no flag.
# --------------------------------------------------------------------------
def test_render_repeat_renders_fresh_every_call_and_numbers_the_results(tmp_path):
    """SABOTAGE TARGET: make `render_repeat` return the existing renders
    without rendering (a cache hit) and the second call's count stays at 1."""
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    r = _fake_renderer({"Tune": _sine(0.5)})
    first = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c", renderer=r)
    second = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c", renderer=r)
    assert r.calls == ["Tune.sid", "Tune.sid"], "every call renders again"
    key = sound.content_key(sid)
    assert [p.name for p in first] == [f"repeat.{key}.s0.t1.r1.wav"]
    assert [p.name for p in second] == [f"repeat.{key}.s0.t1.r1.wav",
                                        f"repeat.{key}.s0.t1.r2.wav"]
    assert all(p.exists() for p in second)
    # and the cached render of the same bytes is a different file, untouched
    c = sound.render_cached(sid, 1, 0, "orig", cache=tmp_path / "c", renderer=r)
    assert c.name == f"orig.{key}.s0.t1.wav" and c not in second


def test_render_repeat_keeps_only_the_newest_and_a_failed_render_adds_nothing(tmp_path):
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    r = _fake_renderer({"Tune": _sine(0.5)})
    for _ in range(4):
        have = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c",
                                   renderer=r, keep=3)
    assert [p.name.rsplit(".", 2)[1] for p in have] == ["r2", "r3", "r4"]
    assert not (tmp_path / "c" / f"repeat.{sound.content_key(sid)}.s0.t1.r1.wav").exists()
    # a failed render: what was there is returned, nothing is added or removed
    got = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c",
                              renderer=lambda *a, **k: False, keep=3)
    assert got == have
    # numbering continues from the highest on disk, not from the count
    have = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c",
                               renderer=r, keep=3)
    assert have[-1].name.endswith(".r5.wav")


def test_render_repeat_keys_on_content_like_render_cached(tmp_path):
    sid = tmp_path / "Tune.sid"
    sid.write_bytes(b"PSID-bytes-1")
    r = _fake_renderer({"Tune": _sine(0.5)})
    a = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c", renderer=r)
    sid.write_bytes(b"PSID-bytes-2")
    b = sound.render_repeat(sid, 1, 0, "repeat", cache=tmp_path / "c", renderer=r)
    assert a[0].name != b[0].name and len(b) == 1


def test_compare_sids_scores_the_two_renders(tmp_path):
    o, u = tmp_path / "O.sid", tmp_path / "U.sid"
    o.write_bytes(b"orig"), u.write_bytes(b"ours")
    r = _fake_renderer({"O": _sine(1.0), "U": _sine(1.0, amp=0.25)})
    got = sound.compare_sids(o, u, 1, 0, 0, cache=tmp_path / "c", renderer=r)
    assert got["aud"] > 0.99
    assert got["loud_ratio"] == pytest.approx(0.5, rel=0.02)
    assert len(got["sound_cache"]) == 2


def test_compare_sids_passes_window_s_through_without_moving_the_cache_key(tmp_path):
    o, u = tmp_path / "O.sid", tmp_path / "U.sid"
    o.write_bytes(b"orig"), u.write_bytes(b"ours")
    a, b = _pair_differing_in(2.5, 4.0)
    r = _fake_renderer({"O": a, "U": b})
    prefix = sound.compare_sids(o, u, 6, 0, 0, cache=tmp_path / "c", renderer=r,
                                window_s=2.0)
    whole = sound.compare_sids(o, u, 6, 0, 0, cache=tmp_path / "c", renderer=r)
    assert prefix["aud"] == pytest.approx(1.0, abs=1e-9)
    assert whole["aud"] < 0.9
    assert prefix["sound_cache"] == whole["sound_cache"]
    assert r.calls == ["O.sid", "U.sid"], "the window is scoring, not rendering"


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


def test_a_supplied_prior_is_used_not_searched_around():
    """v0.5.459. `align(a, b, prior_s=X)` with no window returns X's hop.

    It used to score every hop within one frame of the prior on `aud` and
    return the best, which made the published `aud` a maximum over alignments
    -- the fit CLAUDE.md forbids for `startup_lag`. Removed after its own A/B:
    37 of 89 corpus rows sat AT the window bound, and `loud`, which is not the
    objective, got worse at the chosen hop on 18.

    The prior here is DELIBERATELY WRONG -- zero against a real 0.1 s delay --
    so the assertion is not satisfiable by accident: a searching
    implementation moves off it, and the check below proves a search would
    have, on this exact construction.
    """
    rate = 44100
    t = np.arange(int(rate * 1.0)) / rate
    x = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    delay = int(0.1 * rate)
    y = np.concatenate([np.zeros(delay, dtype=np.float32), x])[:len(x)]
    a, b = sound.features(x, rate), sound.features(y, rate)

    assert sound.align(a, b, prior_s=0.0) == 0

    # The fire check, in the test rather than beside it: some hop inside the
    # old window scores better on `aud` than the prior does, so the removed
    # search WOULD have returned a different answer here.
    span = int(math.ceil(sound.PRIOR_WINDOW_S / a.hop_s))
    at_prior = sound.compare_features(a, b, 0).get("aud")
    better = [lag for lag in range(-span, span + 1)
              if lag and (sound.compare_features(a, b, lag).get("aud") or -1)
              > at_prior]
    assert better, "vacuous: no hop beat the prior, so nothing was removed here"


def test_an_idle_floor_above_silence_db_scores_aud_as_music():
    """The v0.5.401 Las_Vegas render (sound.py's module doc, measured at
    v0.5.488): the music stops half-way and the packed player's resting
    output -- DC plus a faint residual, -52 dB -- carries on. That is above
    SILENCE_DB, so the tail frames count as `both` sounding, and once
    peak-normalised the residual scores `aud` like music while `loud_ratio`
    collapses. True digital silence in the same tail scores 0, which is what
    makes this a blind spot rather than the rule the test above pins."""
    music = _sine(seconds=4.0, hz=440.0, amp=0.15)
    half = len(music) // 2
    idle = (0.0019 + _sine(seconds=2.0, hz=469.0, amp=0.0022)).astype(np.float32)
    ours = np.concatenate([music[:half], idle])
    fo, fu = sound.features(music, RATE), sound.features(ours, RATE)
    h = len(fo.rms_db) // 2 + 20          # past the 2048-sample window that straddles the join

    def tail(f):
        return sound.Features(f.logmel[h:], f.rms_db[h:], f.hop_s)

    assert -53.0 < fu.rms_db[h:].max() < -51.0
    assert (fu.rms_db[h:] > sound.SILENCE_DB).all(), "the idle floor is sounding"
    got = sound.compare_features(tail(fo), tail(fu), 0)
    assert got["sound_frames"] == len(fo.rms_db) - h
    assert got["aud"] > 0.7, got                # the blindness: 0.744 measured
    assert got["loud_ratio"] < 0.05, got        # what actually sees it: 0.023
    zeros = np.concatenate([music[:half], np.zeros(len(idle), dtype=np.float32)])
    silent = sound.compare_features(tail(fo), tail(sound.features(zeros, RATE)), 0)
    assert silent["aud"] < 0.01, silent         # digital silence scores 0


# ---- superseded `ours` renders --------------------------------------------

def _cache(tmp_path, names):
    d = tmp_path / "audio"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"RIFF" + bytes(64))
    return d


def test_render_key_of_reads_the_cache_name_and_nothing_else():
    assert sound.render_key_of("ours.0ef54321942e.s0.t180.wav") == "0ef54321942e"
    assert sound.render_key_of("orig.41aadd62f943.s3.t60.wav") == "41aadd62f943"
    assert sound.render_key_of("repeat.41aadd62f943.s0.t60.1.wav") is None
    assert sound.render_key_of("notes.txt") is None


def test_superseded_renders_names_only_ours_files_with_a_dead_key(tmp_path):
    """orig.* is keyed on the original and valid forever; repeat.* is per
    original; a foreign name is left alone. Only an `ours` render whose key no
    reader can produce is superseded."""
    d = _cache(tmp_path, ["ours.aaaaaaaaaaaa.s0.t180.wav", "ours.aaaaaaaaaaaa.s0.t60.wav",
                          "ours.bbbbbbbbbbbb.s0.t180.wav", "orig.cccccccccccc.s0.t180.wav",
                          "repeat.cccccccccccc.s0.t60.1.wav", "ours.weird.wav"])
    got = [p.name for p in sound.superseded_renders(d, {"aaaaaaaaaaaa"})]
    assert got == ["ours.bbbbbbbbbbbb.s0.t180.wav"]


def test_live_keys_from_fidelity_reads_the_rows_sound_cache(tmp_path):
    j = tmp_path / "fidelity.json"
    j.write_text(json.dumps([
        {"file": "a.sid", "sound_cache": ["orig.111111111111.s0.t180.wav",
                                          "ours.222222222222.s0.t180.wav"]},
        {"file": "b.sid", "status": "not converted"},
    ]), encoding="utf-8")
    assert sound.live_keys_from_fidelity(j) == {"222222222222"}


def test_prune_superseded_moves_never_deletes_and_dry_run_moves_nothing(tmp_path):
    d = _cache(tmp_path, ["ours.aaaaaaaaaaaa.s0.t180.wav", "ours.bbbbbbbbbbbb.s0.t180.wav"])
    q = tmp_path / "quarantine"
    got = sound.prune_superseded(d, {"aaaaaaaaaaaa"}, q, dry_run=True)
    assert [p.name for p in got] == ["ours.bbbbbbbbbbbb.s0.t180.wav"]
    assert sorted(p.name for p in d.iterdir()) == ["ours.aaaaaaaaaaaa.s0.t180.wav",
                                                   "ours.bbbbbbbbbbbb.s0.t180.wav"]
    got = sound.prune_superseded(d, {"aaaaaaaaaaaa"}, q, dry_run=False)
    assert [p.name for p in got] == ["ours.bbbbbbbbbbbb.s0.t180.wav"]
    assert [p.name for p in d.iterdir()] == ["ours.aaaaaaaaaaaa.s0.t180.wav"]
    assert [p.name for p in q.iterdir()] == ["ours.bbbbbbbbbbbb.s0.t180.wav"]


def test_prune_refuses_while_a_calibration_build_cannot_be_rebuilt(tmp_path, monkeypatch, capsys):
    """An unreproducible calibration build's render cannot be told from a
    superseded one, and the next calibration run would pay a cold re-render
    for it -- so nothing moves. An unrecoverable APPROVED build is reported
    and not protected: no reader can construct its key, so its render is
    unreachable already."""
    d = _cache(tmp_path, ["ours.aaaaaaaaaaaa.s0.t180.wav", "ours.bbbbbbbbbbbb.s0.t180.wav"])
    j = tmp_path / "fidelity.json"
    j.write_text(json.dumps([{"file": "a.sid", "sound_cache": ["ours.aaaaaaaaaaaa.s0.t180.wav"]}]),
                 encoding="utf-8")
    (tmp_path / "presets.json").write_text('{"always": {}, "songs": {}}', encoding="utf-8")
    monkeypatch.setattr(sound, "live_keys_from_history", lambda *a: (set(), ["X.sid 0.5.1"]))
    monkeypatch.setattr(sound, "live_keys_from_approvals", lambda *a: (set(), []))
    args = [str(tmp_path), "--fidelity-json", str(j), "--presets", str(tmp_path / "presets.json"),
            "--cache", str(d), "--quarantine", str(tmp_path / "q"), "--workdir", str(tmp_path / "w"),
            "--apply"]
    assert sound._prune_main(args) == 2
    assert "REFUSING" in capsys.readouterr().out
    assert len(list(d.iterdir())) == 2
    monkeypatch.setattr(sound, "live_keys_from_history", lambda *a: (set(), []))
    monkeypatch.setattr(sound, "live_keys_from_approvals", lambda *a: (set(), ["Y 0.5.2"]))
    assert sound._prune_main(args) == 0
    out = capsys.readouterr().out
    assert "NOT protected" in out and "moved 1 superseded" in out
    assert [p.name for p in d.iterdir()] == ["ours.aaaaaaaaaaaa.s0.t180.wav"]


def test_blocked_features_match_the_unblocked_form(monkeypatch):
    # Blocks change only the memory peak (6 GB -> ~130 MB a render). A short
    # block forces several of them plus a ragged last one; the matrix multiply
    # sums in a different order per block shape, so equality is to rounding.
    monkeypatch.setattr(sound, "FEATURE_BLOCK", 37)
    rng = np.random.default_rng(1)
    x = (_sine(3.0, 440.0) + 0.1 * rng.standard_normal(3 * RATE)).astype(np.float32)
    a, b = sound.features(x, RATE), sound.features_reference(x, RATE)
    assert a.logmel.shape == b.logmel.shape and a.rms_db.shape == b.rms_db.shape
    assert len(a.rms_db) > 3 * 37
    np.testing.assert_allclose(a.logmel, b.logmel, rtol=0, atol=1e-9)
    np.testing.assert_array_equal(a.rms_db, b.rms_db)
    assert a.hop_s == b.hop_s


# --- per-second agreement (aud_timeline) ---------------------------------

def _synthetic(seconds: int, seed: int, hop_s: float = 0.01):
    rng = np.random.default_rng(seed)
    n = int(seconds / hop_s)
    return (rng.uniform(-60.0, 0.0, size=(n, 8)).astype(np.float64),
            np.full(n, -20.0), hop_s)


def _feat(logmel, rms, hop_s):
    return sound.Features(logmel, rms, hop_s)


def test_per_second_weighted_mean_matches_aud():
    lm_a, rms_a, h = _synthetic(12, 1)
    lm_b, rms_b, _ = _synthetic(12, 2)
    # uneven weights: a second silent on both sides, one silent on one side only
    rms_a[300:400] = -90.0
    rms_b[300:400] = -90.0
    rms_b[500:560] = -90.0
    # half a second of shared silence inside a second that otherwise sounds
    rms_a[800:850] = -90.0
    rms_b[800:850] = -90.0
    # and a second whose agreement differs: b copies a there
    lm_b[700:800] = lm_a[700:800]
    got = sound.compare_features(_feat(lm_a, rms_a, h), _feat(lm_b, rms_b, h), 0)
    ps, w = got["per_second"], got["per_second_frames"]
    assert len(ps) == len(w) == 12
    assert ps[3] is None and w[3] == 0          # shared silence carries no weight
    assert len({round(v, 3) for v in ps if v is not None}) > 3
    weighted = (sum(v * c for v, c in zip(ps, w) if v is not None)
                / sum(c for v, c in zip(ps, w) if v is not None))
    assert weighted == pytest.approx(got["aud"], abs=1e-6)
    assert sum(w) == got["sound_frames"]


def _timeline(differ: range | None, seconds: int = 60):
    lm_a, rms_a, h = _synthetic(seconds, 3)
    lm_b = lm_a.copy()
    if differ is not None:
        lo, hi = differ.start * 100, differ.stop * 100
        lm_b[lo:hi] = _synthetic(seconds, 4)[0][lo:hi]
    return sound.compare_features(_feat(lm_a, rms_a, h),
                                  _feat(lm_b, rms_a.copy(), h), 0)["per_second"]


_REAL_PAIRS = {  # per-second `aud` (3 dp) of sound_calibrate.KNOWN_BAD pairs from
    # convert_at + render_cached at 60 s and 180 s (whole render), probe 2026-10-25
    ('W_A_R', '0.5.399', '60'): [
        0.691, 0.713, 0.676, 0.708, 0.712, 0.694, 0.686, 0.681, 0.676, 0.692, 0.686,
        0.690, 0.681, 0.677, 0.673, 0.680, 0.695, 0.690, 0.689, 0.714, 0.716, 0.711,
        0.718, 0.588, 0.540, 0.553, 0.539, 0.527, 0.552, 0.564, 0.629, 0.753, 0.752,
        0.717, 0.727, 0.701, 0.712, 0.719, 0.631, 0.605, 0.612, 0.607, 0.592, 0.591,
        0.543, 0.549, 0.562, 0.524, 0.532, 0.547, 0.515, 0.536, 0.527, 0.510, 0.588,
        0.632, 0.640, 0.653, 0.648, 0.635],
    ('W_A_R', '0.5.399', 'whole'): [
        0.691, 0.713, 0.676, 0.708, 0.712, 0.694, 0.686, 0.681, 0.676, 0.692, 0.686,
        0.690, 0.681, 0.677, 0.673, 0.680, 0.695, 0.690, 0.689, 0.714, 0.716, 0.711,
        0.718, 0.588, 0.540, 0.553, 0.539, 0.527, 0.552, 0.564, 0.629, 0.753, 0.752,
        0.717, 0.727, 0.701, 0.712, 0.719, 0.631, 0.605, 0.612, 0.607, 0.592, 0.591,
        0.543, 0.549, 0.562, 0.524, 0.532, 0.547, 0.515, 0.536, 0.527, 0.510, 0.588,
        0.632, 0.640, 0.653, 0.648, 0.635, 0.651, 0.788, 0.892, 0.882, 0.880, 0.878,
        0.879, 0.881, 0.871, 0.857, 0.855, 0.850, 0.851, 0.857, 0.864, 0.867, 0.889,
        0.903, 0.896, 0.905, 0.905, 0.911, 0.911, 0.909, 0.887, 0.889, 0.913, 0.904,
        0.898, 0.880, 0.867, 0.860, 0.889, 0.890, 0.889, 0.883, 0.884, 0.874, 0.860,
        0.861, 0.835, 0.837, 0.839, 0.842, 0.856, 0.854, 0.871, 0.873, 0.885, 0.850,
        0.826, 0.814, 0.895, 0.901, 0.901, 0.880, 0.899, 0.900, 0.895, 0.886, 0.881,
        0.860, 0.858, 0.886, 0.893, 0.888, 0.893, 0.883, 0.876, 0.866, 0.864, 0.896,
        0.902, 0.887, 0.876, 0.874, 0.859, 0.857, 0.870, 0.898, 0.896, 0.844, 0.843,
        0.833, 0.826, 0.819, 0.809, 0.846, 0.837, 0.821, 0.817, 0.806, 0.822, 0.861,
        0.887, 0.892, 0.895, 0.883, 0.882, 0.857, 0.863, 0.852, 0.873, 0.883, 0.882,
        0.881, 0.875, 0.862, 0.839, 0.849, 0.861, 0.855, 0.846, 0.867, 0.864, 0.877,
        0.892, 0.894, 0.887, 0.894],
    ('W_A_R', '0.5.400', '60'): [
        0.858, 0.829, 0.695, 0.679, 0.705, 0.706, 0.699, 0.712, 0.715, 0.715, 0.675,
        0.639, 0.632, 0.624, 0.644, 0.649, 0.624, 0.597, 0.583, 0.592, 0.601, 0.605,
        0.617, 0.873, 0.898, 0.900, 0.892, 0.883, 0.889, 0.906, 0.904, 0.894, 0.886,
        0.889, 0.887, 0.892, 0.898, 0.901, 0.905, 0.908, 0.905, 0.898, 0.890, 0.885,
        0.889, 0.888, 0.878, 0.885, 0.874, 0.866, 0.891, 0.882, 0.876, 0.882, 0.886,
        0.891, 0.893, 0.871, 0.886, 0.893],
    ('W_A_R', '0.5.400', 'whole'): [
        0.858, 0.829, 0.695, 0.679, 0.705, 0.706, 0.699, 0.712, 0.715, 0.715, 0.675,
        0.639, 0.632, 0.624, 0.644, 0.649, 0.624, 0.597, 0.583, 0.592, 0.601, 0.605,
        0.617, 0.873, 0.898, 0.900, 0.892, 0.883, 0.889, 0.906, 0.904, 0.894, 0.886,
        0.889, 0.887, 0.892, 0.898, 0.901, 0.905, 0.908, 0.905, 0.898, 0.890, 0.885,
        0.889, 0.888, 0.878, 0.885, 0.874, 0.866, 0.891, 0.882, 0.876, 0.882, 0.886,
        0.891, 0.893, 0.871, 0.886, 0.893, 0.882, 0.882, 0.871, 0.876, 0.876, 0.879,
        0.889, 0.897, 0.888, 0.896, 0.895, 0.888, 0.892, 0.892, 0.902, 0.891, 0.888,
        0.890, 0.895, 0.880, 0.884, 0.889, 0.887, 0.889, 0.891, 0.890, 0.894, 0.889,
        0.887, 0.893, 0.892, 0.892, 0.888, 0.887, 0.885, 0.880, 0.883, 0.880, 0.896,
        0.903, 0.895, 0.897, 0.896, 0.897, 0.896, 0.895, 0.896, 0.898, 0.889, 0.853,
        0.839, 0.829, 0.896, 0.899, 0.894, 0.892, 0.894, 0.890, 0.889, 0.902, 0.898,
        0.896, 0.867, 0.890, 0.888, 0.885, 0.899, 0.853, 0.895, 0.893, 0.891, 0.880,
        0.876, 0.885, 0.894, 0.899, 0.897, 0.878, 0.885, 0.891, 0.893, 0.849, 0.848,
        0.843, 0.833, 0.819, 0.828, 0.845, 0.840, 0.838, 0.807, 0.841, 0.872, 0.884,
        0.887, 0.889, 0.897, 0.893, 0.895, 0.882, 0.889, 0.892, 0.888, 0.894, 0.891,
        0.884, 0.892, 0.896, 0.886, 0.889, 0.888, 0.890, 0.895, 0.891, 0.887, 0.896,
        0.889, 0.892, 0.892, 0.888],
    ('Action_Biker', '0.5.371', '60'): [
        0.866, 0.808, 0.847, 0.817, 0.859, 0.810, 0.843, 0.825, 0.882, 0.858, 0.828,
        0.840, 0.837, 0.832, 0.855, 0.843, 0.836, 0.850, 0.847, 0.851, 0.830, 0.883,
        0.841, 0.861, 0.878, 0.832, 0.838, 0.834, 0.813, 0.831, 0.833, 0.845, 0.839,
        0.838, 0.839, 0.849, 0.859, 0.843, 0.852, 0.839, 0.852, 0.861, 0.872, 0.834,
        0.873, 0.856, 0.850, 0.843, 0.848, 0.838, 0.864, 0.828, 0.852, 0.861, 0.882,
        0.850, 0.825, 0.845, 0.835, 0.809],
    ('Action_Biker', '0.5.371', 'whole'): [
        0.866, 0.808, 0.847, 0.817, 0.859, 0.810, 0.843, 0.825, 0.882, 0.858, 0.828,
        0.840, 0.837, 0.832, 0.855, 0.843, 0.836, 0.850, 0.847, 0.851, 0.830, 0.883,
        0.841, 0.861, 0.878, 0.832, 0.838, 0.834, 0.813, 0.831, 0.833, 0.845, 0.839,
        0.838, 0.839, 0.849, 0.859, 0.843, 0.852, 0.839, 0.852, 0.861, 0.872, 0.834,
        0.873, 0.856, 0.850, 0.843, 0.848, 0.838, 0.864, 0.828, 0.852, 0.861, 0.882,
        0.850, 0.825, 0.845, 0.835, 0.809, 0.784, 0.718, 0.843, 0.864, 0.857, 0.848,
        0.846, 0.852, 0.852, 0.882, 0.873, 0.879, 0.876, 0.873, 0.870, 0.878, 0.874,
        0.883, 0.873, 0.871, 0.869, 0.875, 0.868, 0.866, 0.877, 0.865, 0.862, 0.868,
        0.869, 0.862, 0.866, 0.870, 0.882, 0.866, 0.847, 0.868, 0.874, 0.869, 0.871,
        0.873, 0.875, 0.871, 0.870, 0.881, 0.877, 0.872, 0.873, 0.876, 0.859, 0.871,
        0.858, 0.841, 0.826, 0.835, 0.824, 0.829, 0.823, 0.830, 0.828, 0.816, 0.812,
        0.813, 0.825, 0.820, 0.821, 0.814, 0.838, 0.846, 0.853, 0.866, 0.844, 0.845,
        0.854, 0.860, 0.847, 0.846, 0.860, 0.852, 0.846, 0.846, 0.852, 0.848, 0.837,
        0.851, 0.858, 0.847, 0.817, 0.827, 0.837, 0.831, 0.818, 0.824, 0.824, 0.836,
        0.843, 0.853, 0.852, 0.838, 0.837, 0.835, 0.839, 0.843, 0.832, 0.823, 0.828,
        0.834, 0.840, 0.846, 0.843, 0.837, 0.842, 0.839, 0.838, 0.846, 0.854, 0.863,
        0.844, 0.846, 0.856, 0.861],
    ('Action_Biker', '0.5.372', '60'): [
        0.967, 0.967, 0.957, 0.968, 0.970, 0.965, 0.960, 0.957, 0.967, 0.963, 0.959,
        0.965, 0.962, 0.966, 0.967, 0.963, 0.965, 0.959, 0.961, 0.969, 0.962, 0.963,
        0.951, 0.969, 0.961, 0.964, 0.965, 0.969, 0.963, 0.968, 0.963, 0.972, 0.970,
        0.969, 0.957, 0.971, 0.958, 0.966, 0.964, 0.964, 0.963, 0.970, 0.965, 0.967,
        0.961, 0.963, 0.969, 0.966, 0.956, 0.967, 0.966, 0.965, 0.959, 0.956, 0.968,
        0.968, 0.961, 0.966, 0.963, 0.968],
    ('Action_Biker', '0.5.372', 'whole'): [
        0.967, 0.967, 0.957, 0.968, 0.970, 0.965, 0.960, 0.957, 0.967, 0.963, 0.959,
        0.965, 0.962, 0.966, 0.967, 0.963, 0.965, 0.959, 0.961, 0.969, 0.962, 0.963,
        0.951, 0.969, 0.961, 0.964, 0.965, 0.969, 0.963, 0.968, 0.963, 0.972, 0.970,
        0.969, 0.957, 0.971, 0.958, 0.966, 0.964, 0.964, 0.963, 0.970, 0.965, 0.967,
        0.961, 0.963, 0.969, 0.966, 0.956, 0.967, 0.966, 0.965, 0.959, 0.956, 0.968,
        0.968, 0.961, 0.966, 0.963, 0.968, 0.975, 0.771, 0.844, 0.855, 0.852, 0.862,
        0.847, 0.850, 0.846, 0.862, 0.847, 0.831, 0.842, 0.858, 0.846, 0.863, 0.860,
        0.854, 0.854, 0.848, 0.863, 0.855, 0.856, 0.846, 0.857, 0.848, 0.849, 0.835,
        0.860, 0.849, 0.853, 0.855, 0.858, 0.857, 0.860, 0.855, 0.862, 0.854, 0.858,
        0.852, 0.855, 0.859, 0.858, 0.854, 0.858, 0.851, 0.833, 0.860, 0.849, 0.856,
        0.852, 0.864, 0.848, 0.852, 0.846, 0.864, 0.849, 0.830, 0.843, 0.859, 0.831,
        0.813, 0.827, 0.853, 0.855, 0.851, 0.861, 0.853, 0.854, 0.846, 0.859, 0.848,
        0.847, 0.833, 0.859, 0.849, 0.855, 0.861, 0.862, 0.850, 0.851, 0.853, 0.860,
        0.852, 0.848, 0.850, 0.852, 0.839, 0.837, 0.858, 0.856, 0.855, 0.857, 0.852,
        0.861, 0.855, 0.864, 0.853, 0.858, 0.852, 0.857, 0.856, 0.857, 0.856, 0.858,
        0.855, 0.853, 0.838, 0.854, 0.853, 0.854, 0.851, 0.866, 0.852, 0.854, 0.844,
        0.860, 0.846, 0.846, 0.831],
}


def _located(series):
    return sound.locate_stretch(series)


def test_real_bad_build_deficit_is_located_inside_20_60_s_on_both_windows():
    for win in ("60", "whole"):
        got = _located(_REAL_PAIRS[("W_A_R", "0.5.399", win)])
        assert got["kind"] == "located" and 20 <= got["start"] <= 60, got


def test_real_good_builds_and_uniform_deficit_have_no_time_in_the_deficit():
    for key in (("W_A_R", "0.5.400", "60"), ("W_A_R", "0.5.400", "whole")):
        got = _located(_REAL_PAIRS[key])
        assert got["start"] is None or not 20 <= got["start"] <= 60, (key, got)
    # a build whose whole series is flat has nothing to place in time
    for key in (("Action_Biker", "0.5.371", "60"), ("Action_Biker", "0.5.371", "whole"),
                ("Action_Biker", "0.5.372", "60"), ("Action_Biker", "0.5.372", "whole")):
        got = _located(_REAL_PAIRS[key])
        assert got["kind"] == "flat" and got["start"] is None, (key, got)


def test_scatter_is_not_inflated_by_a_deficit_filling_half_the_window():
    # MAD about the global median reads 0.076 here; the rolling one stays ~0.013
    sc = sound.second_scatter(_REAL_PAIRS[("W_A_R", "0.5.399", "60")])
    assert sc < 0.02


def test_first_dip_located():
    ps = _timeline(range(40, 50))
    assert ps[39] == pytest.approx(1.0) and ps[40] < 0.9
    got = sound.locate_stretch(ps)
    assert got["kind"] == "located" and got["start"] == 40
    assert sound.first_dip(ps) == 40


def test_no_dip_is_none():
    assert sound.first_dip(_timeline(None)) is None
    assert sound.locate_stretch(_timeline(None))["kind"] == "flat"
    # scatter alone, however large, is not a stretch
    rng = np.random.default_rng(7)
    noisy = list(0.85 + rng.normal(0, 0.02, 120))
    assert sound.first_dip(noisy) is None


def test_silent_seconds_are_never_part_of_a_stretch():
    ps = [0.9] * 30
    for i in range(10, 18):
        ps[i] = 0.3
    ps[13] = None
    got = sound.locate_stretch(ps)
    assert got["kind"] == "located" and not (got["start"] <= 13 < got["start"] + 8)
    assert sound.locate_stretch([None] * 5)["kind"] == "short"
    assert sound.locate_stretch([0.9] * 3)["kind"] == "short"
