"""`--vice` depth stops a note where its envelope died, as siddump's does.

`_vice_pitch_voices` used to carry the frequency and the attack keys only, so
`oscillation_depths` had no gate to read and the `--vice` reading counted
every cycle a player swept on a silenced voice (BMX_Kidz's rest record).
It now carries the dump's waveform register (`wf_events`) and ADSR pair
(`env_adsr_events` -- `adsr_events` stays the instrument KEYS), indexed by
the voice's own axis, and `envelope_zero_frame` charges a release in frames
on a call axis (`per_frame`).
"""
import pytest

import fidelity
import vicetrace as V

L = V.PAL_LINES_PER_FRAME
PHASE = 12


def _trace(calls, m, phase=PHASE):
    """Voice 0 of a synthetic VICE trace. `calls[k]` is `(freq, ctrl, adsr)`
    standing for the whole of play call `k` of a side making `m` calls a
    frame; lines before `phase` belong to call 0, as in the real dump."""
    period = L / m
    nframes = -(-len(calls) // m)
    out = []
    for i in range(nframes * L):
        k = min(max(0, int((i - phase) // period)), len(calls) - 1)
        f, c, a = calls[k]
        out.append(V.Sample(voices=[V.VoiceLine(freq=f, ctrl=c, adsr=a),
                                    V.VoiceLine(), V.VoiceLine()]))
    return out


def _tri(n, amp, base=0x1000):
    """`n` calls of a triangle of half-amplitude `amp` about `base`, period 4
    (peak-to-peak 2*amp: `vibrato_swings` reports `2 * amp / base`)."""
    return [base + (0, amp, 0, -amp)[k % 4] for k in range(n)]


def _note(parts):
    """`parts` is `[(freqs, ctrl, adsr), ...]` -> the per-call list."""
    return [(f, c, a) for freqs, c, a in parts for f in freqs]


OPEN, CLOSED = 0x41, 0x40
ADSR = 0x0A78                                     # release nibble 8: 300 ms


# --- the reader carries the envelope ----------------------------------------

def test_the_reader_carries_the_dumps_gate_and_adsr_beside_the_keys():
    calls = _note([([0x1000] * 10, OPEN, ADSR), ([0x1000] * 2, CLOSED, ADSR),
                   ([0x1000] * 8, CLOSED, 0x0000)])
    v = fidelity.vice_pitch_voices(_trace(calls, 1), calls_per_frame=1)[0]
    # the gate and the pair, written where they CHANGE, on the voice's axis
    assert v.wf_events == [(0, OPEN), (10, CLOSED)]
    assert v.env_adsr_events == [(0, ADSR), (12, 0x0000)]
    # ...and `adsr_events` is still one KEY per attack, never the register
    assert v.adsr_events == [(0, ADSR)]
    assert v.attack_frames == [0]


def test_the_reader_indexes_the_envelope_by_call_not_by_frame():
    """Three calls a frame: the gate drops on call 9 (frame 3), and the event
    says call 9, because that is the axis `freq_events` is on."""
    calls = _note([([0x1000, 0x1010, 0x1000] * 3, OPEN, ADSR),
                   ([0x1000, 0x1010, 0x1000] * 3, CLOSED, ADSR)])
    v = fidelity.vice_pitch_voices(_trace(calls, 3), calls_per_frame=3)[0]
    assert v.wf_events == [(0, OPEN), (9, CLOSED)]
    assert v.env_adsr_events == [(0, ADSR)]


def test_the_frame_reduction_carries_the_frame_closing_envelope():
    calls = _note([([0x1000] * 4, OPEN, ADSR), ([0x1000] * 4, CLOSED, ADSR)])
    v = fidelity.vice_pitch_voices(_trace(calls, 1), reduce="last")[0]
    assert v.wf_events == [(0, OPEN), (4, CLOSED)]
    assert v.env_adsr_events == [(0, ADSR)]


# --- per_frame --------------------------------------------------------------

def test_a_release_is_charged_in_frames_on_a_call_axis():
    """Release nibble 8 is 300 ms = 15 frames. Gate drops on entry 10: audible
    through entry 24 at one entry a frame, through 54 at three."""
    n = 200
    wf = [OPEN] * 10 + [CLOSED] * (n - 10)
    adsr = [ADSR] * n
    assert fidelity.envelope_zero_frame(wf, adsr, 0, n) == 25
    assert fidelity.envelope_zero_frame(wf, adsr, 0, n, per_frame=3) == 55
    assert fidelity.envelope_zero_frame(wf, adsr, 0, n, per_frame=10) == 160


def test_a_zero_pair_under_an_open_gate_still_cuts_the_next_entry():
    n = 50
    adsr = [ADSR] * 12 + [0] * (n - 12)
    assert fidelity.envelope_zero_frame([OPEN] * n, adsr, 0, n, per_frame=3) == 13


# --- the depth reading ------------------------------------------------------

KEYS = {ADSR}


def _bmx_like(tail_amp, audible_amp=400):
    """One note at one call a frame: vibrato under an open gate, the gate
    drops and AD = SR = 0 is written, and the sweep goes on at `tail_amp` on
    a voice the chip has silenced -- BMX_Kidz's rest record."""
    return _note([(_tri(24, audible_amp), OPEN, ADSR),
                  (_tri(2, audible_amp), CLOSED, ADSR),
                  (_tri(60, tail_amp), CLOSED, 0x0000)])


def test_a_silent_tail_on_one_side_does_not_move_the_vice_ratio():
    orig = _trace(_bmx_like(2000), 1)
    ours = _trace(_bmx_like(0), 1)
    got = fidelity.vice_pitch_compare(orig, ours, KEYS)
    assert got["depth_ratio"] == pytest.approx(1.0, abs=0.05), got
    old = fidelity.vice_pitch_compare(orig, ours, KEYS, audible_only=False)
    assert old["depth_ratio"] < 0.5, old


def test_a_zeroed_pair_under_an_open_gate_cuts_the_note_from_the_dumps_adsr():
    """The gate never drops: the player writes AD = SR = 0 and the voice dies
    in 6 ms. Only the dump's own pair can say so -- the instrument key at the
    attack is the pair as it was THEN, and never reads zero."""
    def side(tail_amp):
        return _trace(_note([(_tri(20, 400), OPEN, ADSR),
                             (_tri(60, tail_amp), OPEN, 0x0000)]), 1)

    got = fidelity.vice_pitch_compare(side(2000), side(0), KEYS)
    assert got["depth_ratio"] == pytest.approx(1.0, abs=0.05), got
    old = fidelity.vice_pitch_compare(side(2000), side(0), KEYS,
                                      audible_only=False)
    assert old["depth_ratio"] < 0.5, old


def test_the_vice_reading_ignores_the_silent_tail_at_reduce_last_too():
    orig = _trace(_bmx_like(2000), 1)
    ours = _trace(_bmx_like(0), 1)
    got = fidelity.vice_pitch_compare(orig, ours, KEYS, reduce="last")
    assert got["depth_ratio"] == pytest.approx(1.0, abs=0.05), got
    old = fidelity.vice_pitch_compare(orig, ours, KEYS, reduce="last",
                                      audible_only=False)
    assert old["depth_ratio"] < 0.5, old


def _release_tail(m):
    """Ours at `m` calls a frame: flat while the gate is open, then the gate
    drops (release 8 = 15 frames = 15 * m calls) and the voice sweeps shallow
    for the first 15 CALLS of the release, deeper for the rest of it (still
    audible), and far deeper after the envelope has run out."""
    f = 15 * m
    return _note([([0x1000] * (10 * m), OPEN, ADSR),
                  (_tri(15, 100), CLOSED, ADSR),           # release, shallow
                  (_tri(f - 15, 400), CLOSED, ADSR),       # release, deep
                  (_tri(6 * f, 1600), CLOSED, ADSR)])      # silent


def test_a_multiplier_conversions_release_is_charged_in_its_own_calls():
    """At -S3 the release is 45 calls, not 15: cutting at 15 would keep only
    the shallow cycles (depth 0.049), cutting at 45 keeps the deep ones
    (0.195), not cutting at all adds the silent 0.78 sweep."""
    orig = _trace(_note([([0x1000] * 5 + _tri(120, 400), OPEN, ADSR)]), 1)
    ours = _trace(_release_tail(3), 3)
    got = fidelity.vice_pitch_compare(orig, ours, KEYS, our_calls_per_frame=3)
    assert got["our_depth"] == pytest.approx(2 * 400 / 0x1000, rel=0.1), got
    whole = fidelity.vice_pitch_compare(orig, ours, KEYS,
                                        our_calls_per_frame=3,
                                        audible_only=False)
    assert whole["our_depth"] > 0.3, whole


def test_the_depth_ratio_reaches_the_sided_reader_with_each_sides_own_rate(
        monkeypatch):
    seen = []
    real = fidelity.oscillation_depths

    def spy(voices, nframes, keys=None, skip_radius=1, audible_only=True,
            per_frame=1):
        seen.append((nframes, per_frame))
        return real(voices, nframes, keys, skip_radius, audible_only, per_frame)

    monkeypatch.setattr(fidelity, "oscillation_depths", spy)
    orig = _trace(_note([(_tri(30, 400), OPEN, ADSR)]), 1)
    ours = _trace(_note([(_tri(90, 400), OPEN, ADSR)]), 3)
    fidelity.vice_pitch_compare(orig, ours, KEYS, our_calls_per_frame=3)
    assert seen == [(30, 1), (90, 3)], seen


def test_the_release_nibble_survives_the_dumps_sign_extension():
    """The dump prints SR = $F8 as `fff8`, high byte destroyed. Release is the
    low byte's nibble and a pair is zero only if the low byte is, so the cut
    is the same on a corrupt pair as on the true one."""
    n = 80
    wf = [OPEN] * 10 + [CLOSED] * (n - 10)
    true = fidelity.envelope_zero_frame(wf, [0x0AF8] * n, 0, n)
    dump = fidelity.envelope_zero_frame(wf, [0xFFF8] * n, 0, n)
    assert true == dump == 25


def test_a_voice_with_no_envelope_events_is_still_read_whole():
    """A hand-built voice (no `wf_events`) keeps the pre-gate reading."""
    v = fidelity.Voice(attack_frames=[0],
                       freq_events=[(i, f) for i, f in enumerate(_tri(60, 400))],
                       adsr_events=[(0, ADSR)])
    got = fidelity.oscillation_depths([v], 60, KEYS)
    assert got[ADSR] == pytest.approx(2 * 400 / 0x1000, rel=0.1)
