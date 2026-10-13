"""Under `no_test_restart` Tarzan's waveform program starts on the init call,
one frame before the pitch; the gate-off firstwave starts it on the pitch frame.

`player.s` mt_newnoteinit writes only `$D404` on the note-init call; the note's
frequency and the wavetable's first step arrive on the NEXT call. With
`no_test_restart` the firstwave is the record's waveform with the gate SET, so
the init call is already a gated frame at the frequency the voice still holds
(a "stale-pitch" rise), and the wavetable program -- laid out for a firstwave
that took its first step -- begins one call early: Tarzan's voice-2 drum
`11 81 11 10` plays as `[11 stale] 81 11 10` against the original's pitch frame
`11`, `81`, `11`, `10`. `gate_off_firstwave_instruments` spends the init call on
the waveform with the gate CLEAR and keeps the testbit layout, so the program's
first step is the pitch frame's, as in the original.

Measured at 0421071 (v0.5.533), -t 60, Tarzan.sid, lag-aligned, program start =
the first waveform change within [attack-2, attack+3], relative to the attack:

    voice 2, shipped (no_test_restart)   ours -1 on 435 of 436 paired attacks,
                                         the original 0 on 435
    voice 2, gate-off 1..63              ours  0 on 498 of 499, the original 0
    voice 1, gate-off                    wf window [a-1, a+6) equal on 112 of 116

Historical figures; the tests assert the property, not the counts. Both arms
are forced explicitly so a later `presets.json` decision for Tarzan (the
`ntr-rfw-preset-redecide-at-fixed-lag` question) cannot turn the contrast into
a tautology.
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
NAME = "Tarzan.sid"
SECONDS = 20
EVERY = tuple(range(1, 64))

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _timeline(events, n):
    return fidelity.register_timeline(events, n)


def pitch_frame(freq, f):
    """The frame an attack's PITCH lands on: f+1 when the rise at f carries
    the previous frame's frequency and the frequency changes on f+1."""
    if f >= 1 and freq[f] == freq[f - 1] and freq[f + 1] != freq[f]:
        return f + 1
    return f


def program_start(wf, h):
    """Offset from `h` of the first waveform change in [h-2, h+3], else None."""
    for k in range(h - 2, h + 4):
        if wf[k] != wf[k - 1]:
            return k - h
    return None


def _starts(orig, ours, lag):
    """Counter of (original start, our start) over every paired attack of one
    voice, ours moved to its pitch frame, plus the number of stale rises."""
    n = max([e[0] for e in orig.wf_events + ours.wf_events] + [0]) + 30
    wa, wb = _timeline(orig.wf_events, n), _timeline(ours.wf_events, n)
    fb = _timeline(ours.freq_events, n)
    oa = set(orig.attack_frames)
    out, stale = collections.Counter(), 0
    for f in ours.attack_frames:
        p = pitch_frame(fb, f)
        stale += p != f
        if p - lag in oa:
            out[(program_start(wa, p - lag), program_start(wb, p))] += 1
    return out, stale


@pytest.fixture(scope="module")
def traces(tmp_path_factory):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    base = fidelity._preset_opts(doc, NAME)
    assert doc["songs"][NAME].get("multiplier", 1) == 1
    arms = {
        "ntr": dict(base, no_test_restart=True, real_firstwave_instruments=(),
                    gate_off_firstwave_instruments=()),
        "gate_off": dict(base, no_test_restart=False,
                         real_firstwave_instruments=(),
                         gate_off_firstwave_instruments=EVERY),
    }
    sub, our_sub, _ = fidelity.resolve_pair(CORPUS / NAME, "auto")
    orig = fidelity.run_siddump(CORPUS / NAME, SECONDS, sub)
    out = {}
    for arm, opts in arms.items():
        work = tmp_path_factory.mktemp(arm)
        sng, _ = fidelity.legalise_restarts(
            convert(str(CORPUS / NAME), log=lambda m: None, **opts))
        packed = fidelity.pack_sid(sng, work)
        assert packed is not None and packed.exists()
        ours = fidelity.run_siddump(packed, SECONDS, our_sub)
        out[arm] = (ours, fidelity.startup_lag(orig, ours)[0])
    return orig, out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_no_test_restart_starts_the_program_one_frame_before_the_pitch(traces):
    orig, arms = traces
    ours, lag = arms["ntr"]
    starts, stale = _starts(orig[1], ours[1], lag)
    paired = sum(starts.values())
    assert paired > 100, starts
    # The original's program starts on the attack; ours starts a frame early.
    assert starts[(0, -1)] >= 0.95 * paired, starts
    assert stale >= 0.8 * len(ours[1].attack_frames), (stale, starts)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_gate_off_firstwave_starts_the_program_on_the_pitch_frame(traces):
    orig, arms = traces
    ours, lag = arms["gate_off"]
    starts, stale = _starts(orig[1], ours[1], lag)
    paired = sum(starts.values())
    assert paired > 100, starts
    assert starts[(0, 0)] >= 0.98 * paired, starts
    assert stale == 0, stale
    assert starts[(0, -1)] == 0, starts


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_gate_off_firstwave_reproduces_the_drum_waveform_window(traces):
    """Voice 1 (the C-4 drum): waveform frames [attack-1, attack+6) equal the
    original's, lag-aligned, on almost every paired attack."""
    orig, arms = traces
    ours, lag = arms["gate_off"]
    o, u = orig[0], ours[0]
    n = max(e[0] for e in o.wf_events + u.wf_events) + 30
    wa, wb = _timeline(o.wf_events, n), _timeline(u.wf_events, n)
    oa = set(o.attack_frames)
    paired = [f for f in u.attack_frames if f - lag in oa]
    assert len(paired) > 20
    exact = sum(wb[f - 1:f + 6] == wa[f - lag - 1:f - lag + 6]
                for f in paired)
    assert exact >= 0.9 * len(paired), (exact, len(paired))
