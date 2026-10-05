"""osplit-siddump-oracle: a sign-extended octave member is counted where
siddump's frame names its high byte, and stays blind where it does not.

The VICE dump prints Devils_Galop's `$41B8` as `$FFB8`; against the whole
`$106E` that pair is +24 semitones, and `vicetrace._octave_verdict` reads it
None (blind) because the high byte that makes it an octave is destroyed.
`fidelity.vice_oracle_samples` rebuilds the member from siddump's own trace of
the same side -- the `_oracle_freq` step `vice_freq_repair` uses -- but only
where siddump holds that low byte within one frame of the sample. These tests
pin both outcomes in ONE `vice_octave_split` call, so the confirmed count and
the still-blind count cannot be traded for each other.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity
import vicetrace as VT

N = VT.PAL_LINES_PER_FRAME


def _split(a, b, na=156):
    return [a] * na + [b] * (N - na)


def _trace(v0, v1, frames):
    """Two voices, each a per-frame list of 312 freqs."""
    return [VT.Sample(voices=[VT.VoiceLine(freq=x), VT.VoiceLine(freq=y),
                              VT.VoiceLine()])
            for fr in range(frames) for x, y in zip(v0[fr], v1[fr])]


def _voice(*events):
    v = fidelity.Voice()
    v.freq_events = list(events)
    return v


def test_a_confirmed_voice_counts_and_an_unseen_voice_stays_blind():
    """Voice 0: siddump holds `$41B8`, so `$FFB8` is rebuilt and the pair is a
    4:1 octave trill -- counted. Voice 1: the same dumped pair, but siddump
    holds `$0000` there, so no high byte is named and the frames stay blind."""
    pair = [_split(0x106E, 0xFFB8)] * 4
    trace = _trace(pair, pair, 4)
    oracle = [_voice((0, 0x41B8)), _voice((0, 0x0000)), fidelity.Voice()]
    got = fidelity.vice_octave_split(trace, trace, orig_keyed_by=oracle,
                                     our_keyed_by=oracle)
    for side in ("orig", "our"):
        assert got[f"{side}_octave_split_frames"] == 3        # voice 0, frames 1-3
        assert got[f"{side}_octave_split_blind_frames"] == 3  # voice 1, frames 1-3
    # and the per-voice split is what it says: the repair touched voice 0 only
    fixed = fidelity.vice_oracle_samples(trace, oracle)
    assert {s.voices[0].freq for s in fixed} == {0x106E, 0x41B8}
    assert {s.voices[1].freq for s in fixed} == {0x106E, 0xFFB8}
    assert VT.octave_split_frames(fixed) == [3, 0, 0]


def test_the_oracle_confirms_only_within_one_of_siddumps_frames():
    """siddump holds `$41B8` on frames 0-3 and `$0000` from frame 4. A sample
    is rebuilt from frames f-1..f+1 only, so frames 0-4 are confirmed and
    5-7 stay `$FFB8`: frames 1-4 count, frames 5-7 are blind."""
    pair = [_split(0x106E, 0xFFB8)] * 8
    quiet = [[0] * N] * 8
    trace = _trace(pair, quiet, 8)
    oracle = [_voice((0, 0x41B8), (4, 0x0000)), fidelity.Voice(),
              fidelity.Voice()]
    assert fidelity.vice_frame_offset(trace, oracle) == 0
    got = fidelity.vice_octave_split(trace, trace, our_keyed_by=oracle)
    assert got["our_octave_split_frames"] == 4
    assert got["our_octave_split_blind_frames"] == 3
    assert got["our_octave_first_frame"] == 1
    # the side given no oracle reads the whole window blind
    assert got["orig_octave_split_frames"] == 0
    assert got["orig_octave_split_blind_frames"] == 7


def test_the_oracle_unblinds_a_vibrato_by_refuting_it_not_by_counting_it():
    """Devils_Galop's shipped conversion at -t 45 (be0aeb1): all 76 blind
    frames were pairs of two sign-extended members -- vibrato and slide
    steps such as `$FFC0`/`$FFD2`, which siddump holds as `$13C0`/`$13D2`.
    The oracle must take them out of `blind` as NOT an octave; a repair that
    unblinded them by counting would read a trill where a vibrato plays."""
    pair = [_split(0xFFC0, 0xFFD2)] * 6
    quiet = [[0] * N] * 6
    trace = _trace(pair, quiet, 6)
    held = [(f, 0x13C0 if f % 2 else 0x13D2) for f in range(6)]
    oracle = [_voice(*held), fidelity.Voice(), fidelity.Voice()]
    got = fidelity.vice_octave_split(trace, trace, our_keyed_by=oracle)
    assert got["orig_octave_split_blind_frames"] == 5
    assert got["our_octave_split_blind_frames"] == 0
    assert got["our_octave_split_frames"] == 0
    fixed = fidelity.vice_oracle_samples(trace, oracle)
    assert {s.voices[0].freq for s in fixed} == {0x13C0, 0x13D2}


def _top_of_slide(frames):
    return [_split(0xFFFD, 0xFFFC)] * frames


def test_a_confirmed_ff_high_byte_is_read_whole_not_blind():
    """Last_V8's shipped conversion at -t 45 (be0aeb1): 17 frames stayed blind
    after the oracle because the pair was `$FFFD`/`$FFFC` -- the top of a
    slide, which siddump ALSO prints `FFFD`/`FFFC`. The oracle named the high
    byte `$FF`; reading it still as damage kept the frame blind for ever. A
    ratio-1 pair is no octave: neither counted nor blind."""
    quiet = [[0] * N] * 5
    trace = _trace(_top_of_slide(5), quiet, 5)
    held = [(f, 0xFFFC if f % 2 else 0xFFFD) for f in range(5)]
    oracle = [_voice(*held), fidelity.Voice(), fidelity.Voice()]
    got = fidelity.vice_octave_split(trace, trace, our_keyed_by=oracle)
    assert got["orig_octave_split_blind_frames"] == 4      # no oracle: blind
    assert got["our_octave_split_blind_frames"] == 0
    assert got["our_octave_split_frames"] == 0
    samples, confirmed = fidelity.vice_oracle_repair(trace, oracle)
    assert samples[0].voices[0].freq == 0xFFFD              # value unchanged
    assert len(confirmed[0]) == 5 * N and not confirmed[1]


def test_a_confirmed_ff_octave_counts_and_one_unseen_sample_keeps_it_blind():
    """`$FFC0` is a whole octave of `$7FE0`. Confirmed on every sample it is
    counted; with ONE of its samples outside `whole` the frame stays blind,
    because that sample's `$FF` may be damage."""
    frames = [VT.Sample(voices=[VT.VoiceLine(freq=f), VT.VoiceLine(),
                                VT.VoiceLine()])
              for _ in range(3) for f in _split(0x7FE0, 0xFFC0)]
    ff = {i for i, s in enumerate(frames) if s.voices[0].freq == 0xFFC0}
    assert VT.octave_split_frames(frames) == [0, 0, 0]
    assert VT.octave_split_frames(frames, whole=[ff, set(), set()]) == [2, 0, 0]
    blind: list[int] = []
    one_short = ff - {2 * N - 1}                           # frame 1's last line
    assert VT.octave_split_frames(frames, blind=blind,
                                  whole=[one_short, set(), set()]) == [1, 0, 0]
    assert blind == [1, 0, 0]
