"""`startup_lag` anchors our side on the frame its first note's PITCH lands.

GoatTracker's init call for a new note (`player.s` mt_newnoteinit) writes
`$D404` alone and skips mt_waveexec, so frequency and pulse width arrive one
call later. With the default `$09` firstwave that call is below `$10` and
siddump prints no attack on it. With a gated real waveform as the firstwave
(`real_firstwave_instruments`, `no_test_restart`) it is the attack siddump
prints, at the frequency the voice already held, one frame before the
original's attack, which carries its own pitch. Anchored on that gate rise the
lag came out one frame short for every such file: 5_Title_Tunes read 4, and
at 4 every gate fall and every pitch change of voices 1 and 2 sat one frame
late against the original's; at 5 all of them land on its frame.
"""
import collections
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _voice(freq, wf):
    """A Voice from per-frame freq and waveform lists (sparse, as siddump
    prints them), with its attacks where siddump would print them."""
    v = fidelity.Voice()
    for f, (fr, w) in enumerate(zip(freq, wf)):
        if not f or fr != freq[f - 1]:
            v.freq_events.append((f, fr))
        if not f or w != wf[f - 1]:
            v.wf_events.append((f, w))
        prev = wf[f - 1] if f else 0
        if w >= 0x10 and w & 1 and (not prev & 1 or prev < 0x10):
            v.attack_frames.append(f)
            v.attacks.append("C-4")
    return v


def _three(v):
    return [v, fidelity.Voice(), fidelity.Voice()]


# --- the signal ---------------------------------------------------------------

def test_a_stale_pitch_attack_is_anchored_on_the_frame_the_pitch_lands():
    """Ours: gate on at frame 7 at the frequency already held ($0000), the
    note's pitch at 8 -- Monty's and 5_Title_Tunes' first attacks exactly."""
    v = _voice([0] * 8 + [0x2BDD] * 6, [0] * 7 + [0x41] * 7)
    assert v.attack_frames == [7]
    assert fidelity.pitched_attack_frame(v) == 8


def test_an_attack_that_writes_its_pitch_is_taken_as_it_stands():
    v = _voice([0] * 2 + [0x2BD6] * 6, [0] * 2 + [0x41] * 6)
    assert fidelity.pitched_attack_frame(v) == 2


def test_an_arpeggio_starting_on_the_next_frame_does_not_move_the_attack():
    """Ninja's original voice 1: $0000 -> $684C on the attack, $4E20 a frame
    later. The attack wrote its pitch; the next frame's change is the
    arpeggio, and a rule keyed on the next frame alone would move it."""
    v = _voice([0] * 2 + [0x684C] + [0x4E20] * 4, [0] * 2 + [0x11] * 5)
    assert fidelity.pitched_attack_frame(v) == 2


def test_a_restrike_of_the_held_pitch_is_not_moved():
    v = _voice([0x1000] * 8, [0] * 3 + [0x41] * 5)
    assert fidelity.pitched_attack_frame(v) == 3


def test_a_one_frame_note_is_not_moved_past_its_own_gate():
    """The pitch changes on the next frame but the gate has fallen: that is
    the next note's business, not this attack's pitch."""
    v = _voice([0] * 4 + [0x2000] * 3, [0] * 3 + [0x41, 0x40, 0x40, 0x40])
    assert fidelity.pitched_attack_frame(v) == 3


def test_an_attack_on_frame_zero_has_no_frame_before_it():
    v = _voice([0x303, 0xAF58, 0xAF58], [0x15, 0x15, 0x15])
    assert v.attack_frames == [0]
    assert fidelity.pitched_attack_frame(v) == 0


def test_the_lag_is_taken_between_the_two_pitched_frames():
    orig = _three(_voice([0] * 2 + [0x2BD6] * 10, [0] * 2 + [0x41] * 10))
    ours = _three(_voice([0] * 8 + [0x2BDD] * 4, [0] * 7 + [0x41] * 5))
    assert fidelity.startup_lag(orig, ours) == (6, 6)


def test_the_originals_attack_is_never_moved():
    """Bangkok_Knights' voice 1 loads C#4's $126E the frame before its gate
    and plays its drum's $486E the frame after: by the frequencies alone that
    is the stale shape, and moving it took the file's lag 6 -> 5. The
    mechanism is GoatTracker's init call, so only our side is read for it."""
    bk = _voice([0x126E] * 3 + [0x486E, 0x96E, 0x96E], [0] * 2 + [0x11, 0x81, 0x41, 0x41])
    assert bk.attack_frames == [2]
    assert fidelity.pitched_attack_frame(bk) == 3     # the shape is stale ...
    ours = _three(_voice([0] * 8 + [0x1271] + [0x49C5] * 3,
                         [0] * 8 + [0x11, 0x81, 0x41, 0x41]))
    assert fidelity.startup_lag(_three(bk), ours) == (6, 6)   # ... and unmoved


def test_voices_without_freq_events_keep_the_first_gate_estimate():
    """Hand-built voices carrying only waveforms (every older startup_lag
    test) have no frequency to read, so nothing is stale."""
    o = [fidelity.Voice(wf_events=[(1, 0x41)], attack_frames=[1])]
    u = [fidelity.Voice(wf_events=[(8, 0x41)], attack_frames=[8])]
    assert fidelity.startup_lag(o, u) == (7, 7)


# --- a real_firstwave file, measured ----------------------------------------

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

SECONDS = 30
# 5_Title_Tunes' shipped real-firstwave set, pinned here so a later preset
# decision cannot quietly turn this into a `$09` file.
REAL_FIRSTWAVE = (1, 2, 3, 5, 6, 8)


def _edges(t, rise):
    return [i for i in range(1, len(t))
            if (t[i] & 1) != (t[i - 1] & 1) and bool(t[i] & 1) == rise]


def _changes(t):
    return [i for i in range(1, len(t)) if t[i] != t[i - 1]]


def _census(a, b, w=3):
    sb, out = set(b), collections.Counter()
    for e in a:
        out[next((d for d in sorted(range(-w, w + 1), key=abs)
                  if e + d in sb), None)] += 1
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_five_title_tunes_falls_and_pitches_land_on_the_originals_frames(
        tmp_path):
    from h2g.convert import convert
    name = "5_Title_Tunes.sid"
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    assert doc["songs"][name].get("multiplier", 1) == 1
    opts = fidelity._preset_opts(doc, name)
    opts["real_firstwave_instruments"] = REAL_FIRSTWAVE
    opts["gate_off_firstwave_instruments"] = ()
    sub, our_sub, _ = fidelity.resolve_pair(CORPUS / name, "auto")
    sng, _ = fidelity.legalise_restarts(
        convert(str(CORPUS / name), log=lambda m: None, **opts))
    packed = fidelity.pack_sid(sng, tmp_path)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / name, SECONDS, sub)
    ours = fidelity.run_siddump(packed, SECONDS, our_sub)

    first_gate = (min(min(v.attack_frames) for v in ours if v.attack_frames)
                  - min(min(v.attack_frames) for v in orig if v.attack_frames))
    lag, raw = fidelity.startup_lag(orig, ours)
    assert lag == raw
    # Every one of our first attacks is the stale-pitch init call; none of
    # the original's is.
    for o, u in zip(orig, ours):
        assert fidelity.pitched_attack_frame(u) == min(u.attack_frames) + 1
        assert fidelity.pitched_attack_frame(o) == min(o.attack_frames)
    assert lag == first_gate + 1

    n = SECONDS * 50

    def census(at):
        out = []
        for a, b in zip(orig[1:], ours[1:]):   # voices 1 and 2: no arpeggio
            ta, tb = fidelity._aligned(
                fidelity.register_timeline(a.wf_events, n),
                fidelity.register_timeline(b.wf_events, n), at)
            fa, fb = fidelity._aligned(
                fidelity.register_timeline(a.freq_events, n),
                fidelity.register_timeline(b.freq_events, n), at)
            out.append((_census(_edges(ta, False), _edges(tb, False)),
                        _census(_changes(fa), _changes(fb))))
        return out

    for fall, pitch in census(lag):
        assert sum(fall.values()) > 50 and sum(pitch.values()) > 50
        assert fall.most_common(1)[0][0] == 0 and fall[0] >= sum(fall.values()) - 1
        assert set(pitch) == {0}, pitch
    # And the first-gate estimate is one frame off on both.
    for fall, pitch in census(first_gate):
        assert fall.most_common(1)[0][0] == 1
        assert set(pitch) == {1}, pitch


# --- the lag is a property of the player, not of the firstwave spelling ------

@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name", ["Commando.sid", "Delta.sid"])
def test_the_lag_does_not_move_with_the_firstwave_spelling(name, tmp_path):
    """`no_test_restart` and `real_firstwave_instruments` change only the
    init call's `$D404` byte; the player's latency is the same. Anchored on
    the first gate rise the lag dropped by exactly one with either, so an
    A/B of the option compared its two arms at two alignments (BACKLOG
    `startup-lag-perturbed-by-no-test-restart`: Delta's 32.5 -> 84.2% `gate`
    gain was that artefact). Anchored on the pitch the four spellings agree.
    Delta is multispeed (-S2), traced a frame per row as the harness does."""
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    base = fidelity._preset_opts(doc, name)
    m = doc["songs"].get(name, {}).get("multiplier", 1)
    sub, our_sub, _ = fidelity.resolve_pair(CORPUS / name, "auto")
    orig = fidelity.run_siddump(CORPUS / name, 20, sub)
    first = min(min(v.attack_frames) for v in orig if v.attack_frames)
    every = tuple(range(1, 33))
    arms = {
        "testbit": dict(no_test_restart=False, real_firstwave_instruments=(),
                        gate_off_firstwave_instruments=()),
        "no_test_restart": dict(no_test_restart=True,
                                real_firstwave_instruments=(),
                                gate_off_firstwave_instruments=()),
        "real_firstwave": dict(no_test_restart=False,
                               real_firstwave_instruments=every,
                               gate_off_firstwave_instruments=()),
        "gate_off": dict(no_test_restart=False, real_firstwave_instruments=(),
                         gate_off_firstwave_instruments=every),
    }
    got = {}
    for arm, over in arms.items():
        sng, _ = fidelity.legalise_restarts(
            convert(str(CORPUS / name), log=lambda x: None, **{**base, **over}))
        work = tmp_path / arm
        work.mkdir()
        packed = fidelity.pack_sid(sng, work, fidelity.GT2RELOC, m)
        assert packed is not None and packed.exists(), arm
        ours = fidelity.run_siddump(packed, 20, our_sub, calls=m)
        gate = min(min(v.attack_frames) for v in ours if v.attack_frames)
        got[arm] = (gate - first, fidelity.startup_lag(orig, ours)[0])
    lags = {lag for _, lag in got.values()}
    assert len(lags) == 1, got
    lag = lags.pop()
    # The two gated-firstwave spellings rise one frame before their pitch;
    # the testbit and the gate-cleared one rise on it.
    assert got["testbit"][0] == got["gate_off"][0] == lag, got
    assert got["no_test_restart"][0] == got["real_firstwave"][0] == lag - 1, got
