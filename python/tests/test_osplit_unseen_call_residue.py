"""osplit-vice-sweep-after-ff-oracle: the blind frames left after the `$FF`
oracle fix are a genuine VICE/siddump disagreement, not a stale low byte.

Last_V8 (voice 0, frame 2035), Last_V8_C128_version (same) and Monty_on_the_Run
(voice 1, frames 1763 and 1771) keep 1, 1 and 2 blind frames at -t 45 on the
shipped `-S2` conversion (0d18fce). The dump holds `$FFEE` and `$0F6E` in the
frame. The conversion slides the voice down `$80` per play call, two calls a
frame, and siddump at `-m2` prints one row per frame -- the registers after the
LAST call -- so it never holds the other call's value. Traced one call per
row (`run_siddump(..., calls=1)` over twice the seconds) the unseen call is
`$0FEE`: the true pair is `$0F6E`/`$0FEE`, a slide step, not an octave.

Why that frame is blind rather than refuted: `$0F6E >> 3` is `$01ED`, and a
member with low byte `$EE` and high byte `$01` is `$01EE`, one unit off, inside
the k = 3 tolerance of `_octave_verdict`. The next frames' `$0E6E`, `$0D6E`,
`$0C6E` do not share it, so only the first step of each slide stays blind.
Nothing in the dump or in siddump's per-frame rows can say which; only a
per-call trace names `$0FEE`. These tests pin that diagnosis in three places.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity
import vicetrace as VT

N = VT.PAL_LINES_PER_FRAME
EXT = 0xFFEE                      # the dump's print of the unseen call's $0FEE
STEPS = [0x0F6E, 0x0E6E, 0x0D6E, 0x0C6E]   # what siddump -m2 prints per frame


def _frame_open():
    return [0x106E] * 273 + [EXT] * 39


def _frame_slide(w):
    """Last_V8 frames 2035-2038: the previous frame's unseen call, this
    frame's seen call, then this frame's unseen call."""
    return [EXT] * 119 + [w] * 154 + [EXT] * 39


def _trace():
    frames = [_frame_open()] + [_frame_slide(w) for w in STEPS]
    return [VT.Sample(voices=[VT.VoiceLine(freq=f), VT.VoiceLine(),
                              VT.VoiceLine()])
            for fr in frames for f in fr]


def _siddump_rows():
    """siddump at -m2: frame 0 holds `$106E`, then one slide step a frame."""
    v = fidelity.Voice()
    v.freq_events = [(0, 0x106E)] + [(i, w) for i, w in enumerate(STEPS)]
    return [v, fidelity.Voice(), fidelity.Voice()]


def test_the_dump_alone_cannot_tell_a_slide_step_from_a_three_octave_pair():
    # the coincidence: ext $FFEE against $0F6E reads as $01EE, 1 off $0F6E >> 3
    assert (0x0F6E >> 3) == 0x01ED
    assert VT._octave_verdict(EXT, 0x0F6E) is None
    # the slide's later steps share no such coincidence and are refuted
    for w in STEPS[1:]:
        assert VT._octave_verdict(EXT, w) is False
    # the value the unseen call really writes is no octave of anything here
    assert VT._octave_verdict(0x0FEE, 0x0F6E) is False


def test_siddump_at_m2_leaves_the_first_slide_step_blind():
    """The shipped path: the oracle holds only `$0F6E`..`$0C6E`, none with low
    byte `$EE`, so nothing is rebuilt. One frame blind, none counted."""
    trace = _trace()
    oracle = _siddump_rows()
    fixed = fidelity.vice_oracle_samples(trace, oracle)
    assert {s.voices[0].freq for s in fixed} == {0x106E, EXT, *STEPS}
    got = fidelity.vice_octave_split(trace, trace, orig_keyed_by=oracle,
                                     our_keyed_by=oracle)
    for side in ("orig", "our"):
        assert got[f"{side}_octave_split_frames"] == 0
        assert got[f"{side}_octave_split_blind_frames"] == 1


def test_an_oracle_that_names_the_unseen_call_refutes_the_frame():
    """Give the oracle the value a per-call trace holds (`$0FEE`) and the
    `$FFEE` samples are rebuilt, the pair reads `$0FEE`/`$0F6E`, and the frame
    is refuted instead of blind. Counted stays 0."""
    trace = _trace()
    v = fidelity.Voice()
    v.freq_events = [(0, 0x0FEE)]
    oracle = [v, fidelity.Voice(), fidelity.Voice()]
    fixed = fidelity.vice_oracle_samples(trace, oracle)
    assert 0x0FEE in {s.voices[0].freq for s in fixed}
    assert EXT not in {s.voices[0].freq for s in fixed[N:]}
    got = fidelity.vice_octave_split(trace, trace, orig_keyed_by=oracle,
                                     our_keyed_by=oracle)
    for side in ("orig", "our"):
        assert got[f"{side}_octave_split_frames"] == 0
        assert got[f"{side}_octave_split_blind_frames"] == 0
