"""osplit-percall-oracle: a conversion at `-S2` makes two play calls a frame and
siddump at `-m2` prints one of them, so a sign-extended `$FFEE` the dump holds
for the OTHER call has no oracle value (Last_V8 frame 2035: `$FFEE`/`$0F6E`,
the unseen call being `$0FEE`). A trace at one call a row names it; the
line-to-call phase and offset are FITTED on the low bytes (`_percall_fit`),
then each corrupt sample is read from its own call and the one before it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity
import vicetrace as VT

L = VT.PAL_LINES_PER_FRAME
HALF = L // 2
NF = 60
UNSEEN = 0x0FEE
SEEN = 0x0F6E
HOT = 2 * 50          # the call holding the unseen value; frame 50


def _values():
    # low bytes < $80: only the planted call is sign-extended by the dump
    v = [0x0800 + ((k * 0x137) % 0x700 & ~0x80) for k in range(2 * NF)]
    v[HOT], v[HOT + 1] = UNSEEN, SEEN
    return v


def _ext(x):
    return (0xFF00 | (x & 0xFF)) if x & 0x80 else x


def _trace(vals, lead=0):
    """Call k writes vals[k] at line `lead + k * HALF`; the dump sign-extends."""
    out = []
    for line in range(NF * L):
        k = (line - lead) // HALF
        x = vals[k] if k >= 0 else 0x0801
        out.append(VT.Sample(voices=[VT.VoiceLine(freq=_ext(x)),
                                     VT.VoiceLine(), VT.VoiceLine()]))
    return out


def _voice(events):
    v = fidelity.Voice()
    v.freq_events = events
    return [v, fidelity.Voice(), fidelity.Voice()]


def _frame_oracle(vals):
    """siddump -m2: one row a frame, the registers after the frame's LAST call."""
    return _voice([(f, vals[2 * f + 1]) for f in range(NF)])


def _percall_oracle(vals, shift=0):
    """siddump -m1 over 2x the seconds: one row a call (`shift` calls late)."""
    return _voice([(k + shift, x) for k, x in enumerate(vals)])


def _blind(trace, frame, percall=None):
    return fidelity.vice_octave_split(
        trace, trace, our_calls_per_frame=2, orig_keyed_by=frame,
        our_keyed_by=frame, our_percall_keyed_by=percall)


def test_the_frame_oracle_alone_leaves_the_unseen_call_blind():
    vals = _values()
    got = _blind(_trace(vals), _frame_oracle(vals))
    assert got["our_octave_split_frames"] == 0
    assert got["our_octave_split_blind_frames"] == 1


def test_a_percall_oracle_names_the_unseen_call_and_refutes_the_frame():
    vals = _values()
    tr = _trace(vals)
    got = _blind(tr, _frame_oracle(vals), _percall_oracle(vals))
    assert got["our_octave_split_frames"] == 0
    assert got["our_octave_split_blind_frames"] == 0
    fixed = fidelity.vice_oracle_samples(tr, _frame_oracle(vals),
                                         _percall_oracle(vals), 2)
    # the repair is $0FEE, not the +-1 window's $0EEE
    assert {s.voices[0].freq for s in
            fixed[50 * L:51 * L]} == {UNSEEN, SEEN}


def test_the_fit_finds_the_phase_and_offset_it_is_given():
    vals = _values()
    for lead, shift in ((0, 0), (37, 0), (0, 3), (60, -2)):
        raw = [s.voices[0].freq for s in _trace(vals, lead)]
        tl = fidelity.register_timeline(
            [(k + shift, x) for k, x in enumerate(vals)], 2 * NF)
        got = fidelity._percall_fit(raw, tl, 2)
        assert got is not None, (lead, shift)
        phase, off = got
        assert off == shift, (lead, shift, got)
        assert abs(((phase - lead) + HALF / 2) % HALF - HALF / 2) < 3


def test_a_percall_trace_that_fits_nothing_repairs_nothing():
    vals = _values()
    other = [0x0900 + ((k * 0x2B) % 0x200 & ~0x80) for k in range(2 * NF)]
    tr = _trace(vals)
    got = _blind(tr, _frame_oracle(vals), _percall_oracle(other))
    assert got["our_octave_split_blind_frames"] == 1


def test_the_fitted_phase_and_offset_carry_the_repair():
    """A call trace running 3 calls late against the dump (the phase is
    fitted in test_the_fit_finds_the_phase_and_offset_it_is_given)."""
    vals = _values()
    tr = _trace(vals)
    frame = _frame_oracle(vals)
    late = _percall_oracle(vals, shift=3)
    assert _blind(tr, frame)["our_octave_split_blind_frames"] == 1
    assert _blind(tr, frame, late)["our_octave_split_blind_frames"] == 0


def test_a_trace_that_fits_only_a_third_of_the_calls_is_not_trusted():
    """The best offset here still agrees on only ~1/3 of the calls (plus the
    planted two), under the 80% bar: nothing is repaired."""
    vals = _values()
    other = [0x0900 + ((k * 0x2B) % 0x200 & ~0x80) for k in range(2 * NF)]
    mixed = [vals[k] if (k % 3 == 0 or k in (HOT, HOT + 1)) else other[k]
             for k in range(2 * NF)]
    raw = [s.voices[0].freq for s in _trace(vals)]
    tl = fidelity.register_timeline(list(enumerate(mixed)), 2 * NF)
    assert fidelity._percall_fit(raw, tl, 2) is None
    fixed, hit = fidelity._oracle_freq_percall(raw, tl, 2)
    assert hit == [] and fixed == raw


def test_the_window_is_the_call_and_the_one_before_it_not_the_next():
    """Call 101 holds `$0EEE`, the same low byte as the unseen `$0FEE` in call
    100: a window reaching forward is ambiguous and would give up (or take the
    wrong octave); the call and its predecessor name `$0FEE` alone."""
    vals = _values()
    vals[HOT + 1] = 0x0EEE
    raw = [s.voices[0].freq for s in _trace(vals)]
    tl = fidelity.register_timeline(list(enumerate(vals)), 2 * NF)
    fixed, hit = fidelity._oracle_freq_percall(raw, tl, 2)
    assert hit and {fixed[i] for i in hit} == {UNSEEN}


def test_a_side_at_one_call_a_frame_ignores_the_percall_oracle():
    vals = _values()
    tr = _trace(vals)
    fixed = fidelity.vice_oracle_samples(tr, _frame_oracle(vals),
                                         _percall_oracle(vals), 1)
    assert fixed == fidelity.vice_oracle_samples(tr, _frame_oracle(vals))
