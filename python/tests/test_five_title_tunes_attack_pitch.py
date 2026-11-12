"""5_Title_Tunes: the attack frame carries the NEW note's pitch.

`player.s` mt_newnoteinit writes `$D404` alone and skips mt_waveexec, so a
note's frequency and pulse width are written on the call AFTER the init call.
With a gated real waveform as the firstwave (the shipped
`real_firstwave_instruments` (1, 2, 3, 5, 6, 8) until this entry) the init call
is the attack siddump prints, at the frequency the voice still held: 2370 of the
2370 pitch-different notes opened on the previous note's pitch (heard `instr`
13.6%, gate 75%).

The packed player has no way to write a frequency on that frame (mt_newnoteinit
ends in mt_loadregswaveonly), so the fix is to move the gate onto the pitch's
call, not the pitch onto the gate's: the record's own waveform with the gate
CLEAR as firstwave (`gate_off_firstwave_instruments`) and the wavetable's lead
entry writing gate and pitch together. 5_Title_Tunes' rows are 4 calls
(`max_hard_restart` bound 3), the original gates off for 4 of 8 frames, and the
gate-off firstwave's init call is the fourth off frame, so the gatetimer stays
at the bound untrimmed -- which is why this is `gate_off_firstwave_instruments`
and not `aligned_firstwave` (whose one-call trim leaves the gate 5 on / 3 off).

Pinned here on the shipped preset, measured on the packed song:

* no attack of voices 1 and 2 (no arpeggio) writes a stale pitch;
* our gate falls and pitch changes land on the original's frames at the
  startup lag, with the first gate rise already on it;
* the real-firstwave spelling, forced back, shows the defect (the test would
  otherwise pass whatever the preset said).
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
NAME = "5_Title_Tunes.sid"
SECONDS = 30

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


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


def _stale_attacks(v):
    """Attacks that write the frequency the voice already held and change it
    on the next frame with the gate still on -- `pitched_attack_frame`'s
    signal, counted over every attack rather than the first."""
    n = SECONDS * 50
    fr = fidelity.register_timeline(v.freq_events, n)
    wf = fidelity.register_timeline(v.wf_events, n)
    stale = 0
    for f in v.attack_frames:
        if 1 <= f < n - 1 and fr[f] == fr[f - 1] and fr[f + 1] != fr[f] \
                and wf[f + 1] & 1 and wf[f + 1] >= 0x10:
            stale += 1
    return stale


def _traced(tmp_path, **over):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    assert doc["songs"][NAME].get("multiplier", 1) == 1
    opts = {**fidelity._preset_opts(doc, NAME), **over}
    sub, our_sub, _ = fidelity.resolve_pair(CORPUS / NAME, "auto")
    sng, _ = fidelity.legalise_restarts(
        convert(str(CORPUS / NAME), log=lambda m: None, **opts))
    packed = fidelity.pack_sid(sng, tmp_path)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / NAME, SECONDS, sub)
    ours = fidelity.run_siddump(packed, SECONDS, our_sub)
    return orig, ours


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_shipped_preset_opens_every_note_on_its_own_pitch(tmp_path):
    orig, ours = _traced(tmp_path)
    for v in orig[1:]:
        assert _stale_attacks(v) == 0
    for u in ours[1:]:
        assert len(u.attack_frames) > 50
        assert _stale_attacks(u) == 0

    first_gate = (min(min(v.attack_frames) for v in ours if v.attack_frames)
                  - min(min(v.attack_frames) for v in orig if v.attack_frames))
    lag, raw = fidelity.startup_lag(orig, ours)
    assert lag == raw == first_gate, (lag, raw, first_gate)
    for o, u in zip(orig, ours):
        assert fidelity.pitched_attack_frame(u) == min(u.attack_frames)

    n = SECONDS * 50
    for a, b in zip(orig[1:], ours[1:]):
        ta, tb = fidelity._aligned(
            fidelity.register_timeline(a.wf_events, n),
            fidelity.register_timeline(b.wf_events, n), lag)
        fa, fb = fidelity._aligned(
            fidelity.register_timeline(a.freq_events, n),
            fidelity.register_timeline(b.freq_events, n), lag)
        rise = _census(_edges(ta, True), _edges(tb, True))
        fall = _census(_edges(ta, False), _edges(tb, False))
        pitch = _census(_changes(fa), _changes(fb))
        for c in (rise, fall, pitch):
            assert sum(c.values()) > 50
            assert set(c) == {0}, c


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_real_firstwave_spelling_opens_on_the_previous_pitch(tmp_path):
    """The control: the pre-fix spelling puts the gate on the init call, whose
    frequency is the previous note's -- so the assertion above is not vacuous."""
    _, ours = _traced(tmp_path, real_firstwave_instruments=(1, 2, 3, 5, 6, 8),
                      gate_off_firstwave_instruments=())
    for u in ours[1:]:
        assert _stale_attacks(u) > len(u.attack_frames) // 2, _stale_attacks(u)
