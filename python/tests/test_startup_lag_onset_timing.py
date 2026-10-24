"""`onset_timing` reads our gate rises, so it must take back the frame
`startup_lag`'s pitched anchor added.

Pygmies_Revenge at v0.5.596: startup_lag 6 (our first note anchored on the
frame its PITCH lands, 24, one after its gate rise, 23). Every one of its
1455 paired notes then read one frame early (onset_timing 0.0, offset -1),
because `onset_timing_compare` compared our GATE rises against that
pitch-anchored lag. 97% of ours' notes carry a stale pitch on the gate frame
(226/233, 756/771, 452/453 per voice) and the original's do not (2, 4, 0), so
the gate leads the pitch by a frame on every note: against the lag the gate
rises give (5) all notes agree.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402


def _voice(freq, wf):
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


N = 120


def _notes(starts, gate_lead, pitches=None):
    """A voice striking at `starts`, 4 frames gated per note. With `gate_lead`
    the gate rises on the frame the voice still holds the previous pitch and
    the note's own pitch lands the frame after (GoatTracker's firstwave init);
    without, gate and pitch land together (the original's player)."""
    freq, wf = [0x1000] * N, [0] * N
    for k, s in enumerate(starts):
        pitch = 0x2000 + 0x100 * (k + 1)
        for f in range(s, N):
            if f >= s + (1 if gate_lead else 0):
                freq[f] = pitch
        for f in range(s, s + 4):
            wf[f] = 0x41
    return _voice(freq, wf)


ORIG_STARTS = [2, 12, 22, 32, 42, 52]


def _orig(): return [_notes(ORIG_STARTS, False), fidelity.Voice(), fidelity.Voice()]
def _ours(lead, off=5): return [_notes([s + off for s in ORIG_STARTS], lead),
                                fidelity.Voice(), fidelity.Voice()]


def test_the_fixture_has_the_shape_it_claims():
    o, u = _orig(), _ours(True)
    assert o[0].attack_frames == ORIG_STARTS
    assert u[0].attack_frames == [s + 5 for s in ORIG_STARTS]
    assert fidelity.pitched_attack_frame(u[0]) == ORIG_STARTS[0] + 6
    assert fidelity.pitched_attack_frame(o[0]) == ORIG_STARTS[0]


def test_gate_leading_pitch_reads_the_pitch_lag_and_zero_offset():
    o, u = _orig(), _ours(True)
    lag, _ = fidelity.startup_lag(o, u)
    assert lag == 6
    r = fidelity.onset_timing_compare(o, u, N, lag=lag)
    assert r["onset_timing"] == 1.0
    assert r["onset_timing_early"] == 0 and r["onset_timing_late"] == 0
    assert r["onset_timing_offset"] == 0


def test_pitch_anchor_shift_is_one_for_a_stale_first_note():
    assert fidelity.pitch_anchor_shift(_ours(True)) == 1


def test_pitch_anchor_shift_is_zero_when_the_gate_carries_the_pitch():
    assert fidelity.pitch_anchor_shift(_ours(False)) == 0


def test_pitch_anchor_shift_is_zero_with_no_attacks():
    assert fidelity.pitch_anchor_shift([fidelity.Voice()] * 3) == 0


def test_without_a_stale_pitch_the_column_is_untouched():
    o, u = _orig(), _ours(False)
    lag, _ = fidelity.startup_lag(o, u)
    assert lag == 5
    r = fidelity.onset_timing_compare(o, u, N, lag=lag)
    assert r["onset_timing"] == 1.0 and r["onset_timing_paired"] == len(ORIG_STARTS)


def test_a_real_one_frame_gate_shift_is_still_seen():
    """Shift ours' gate AND pitch one frame later than the lag says: the
    column must still call that late, whatever the anchor."""
    o = _orig()
    u = _ours(True)
    r = fidelity.onset_timing_compare(o, u, N, lag=6 - 1)
    assert r["onset_timing"] == 0.0 and r["onset_timing_late"] == len(ORIG_STARTS)


def test_the_old_reading_is_what_the_correction_removes():
    """Pre-fix behaviour, spelled out: the pitch lag against gate rises is
    all-early. This is the cause the module docstring names."""
    o, u = _orig(), _ours(True)
    gate_vs_pitch_lag = fidelity.onset_timing_compare(
        o, u, N, lag=fidelity.startup_lag(o, u)[0] + fidelity.pitch_anchor_shift(u))
    assert gate_vs_pitch_lag["onset_timing"] == 0.0
    assert gate_vs_pitch_lag["onset_timing_early"] == len(ORIG_STARTS)
