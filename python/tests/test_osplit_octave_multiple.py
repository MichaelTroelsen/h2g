"""osplit-octave-multiple-and-window: `vicetrace._octave_verdict` accepts a
ratio of 2^k (k <= OCTAVE_MAX_SHIFT), not only 2, and `fidelity.vice_octave_split`
rebuilds a sign-extended freq from siddump's own trace of the same side where
siddump saw it.

Devils_Galop's ticked arp is +24 semitones: `$106E` against `$41B8`, which the
VICE dump prints as `$FFB8`. A ratio-2 test read the pair as no octave at all,
so osplit read 0 with the arp disabled.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fidelity
import vicetrace as VT

N = VT.PAL_LINES_PER_FRAME


def _frames(per_frame):
    return [VT.Sample(voices=[VT.VoiceLine(freq=f), VT.VoiceLine(), VT.VoiceLine()])
            for fr in per_frame for f in fr]


def _split(a, b, na):
    return [a] * na + [b] * (N - na)


def test_a_two_octave_pair_of_whole_values_is_an_octave_multiple():
    assert VT._octave_verdict(0x106E, 0x41B8) is True
    assert VT._octave_verdict(0x41B8, 0x106E) is True
    assert VT._octave_partner(0x106E, 0x41B8)


def test_three_octaves_pass_and_four_do_not():
    assert VT.OCTAVE_MAX_SHIFT == 3
    assert VT._octave_verdict(0x0200, 0x1000) is True      # 8x
    assert VT._octave_verdict(0x0200, 0x2000) is False     # 16x


def test_non_power_of_two_ratios_stay_refused():
    assert VT._octave_verdict(0x1168, 0x1A2C) is False     # 3:2
    assert VT._octave_verdict(0x1168, 0x3498) is False     # 3x
    assert VT._octave_verdict(0x1168, 0x45A0 + 0x400) is False


def test_a_sign_extended_double_octave_is_blind_not_counted():
    # $FFB8 is $41B8 damaged; its low byte agrees with 4 * $106E, which proves
    # nothing (the high byte is the one the rebuild gave it)
    assert VT._octave_verdict(0x106E, 0xFFB8) is None
    assert not VT._octave_partner(0x106E, 0xFFB8)
    # and a low byte that no 2^k of the partner has still refutes it
    assert VT._octave_verdict(0x106E, 0xFF90) is False


def test_formula_1s_old_refutations_survive_the_wider_test():
    assert VT._octave_verdict(0xFF82, 0x0F02) is None
    assert not VT._octave_partner(0xFF82, 0x0F02)
    assert VT._octave_verdict(0xFFA0, 0x3A40) is False


def test_a_four_to_one_frame_is_counted_on_its_voice():
    frames = _frames([_split(0x106E, 0x41B8, 156)] * 4)
    assert VT.octave_split_frames(frames) == [3, 0, 0]


# --- the siddump oracle -----------------------------------------------------

def _devils_trace(frames=4):
    """A voice-0 trace whose halves are $106E and the dumped $41B8 ($FFB8);
    the frame closes on $FFB8, as siddump's does."""
    return _frames([_split(0x106E, 0xFFB8, 156)] * frames)


def _voice(value, frames):
    v = fidelity.Voice()
    v.freq_events = [(0, value)]
    return v


def test_without_the_oracle_the_pair_is_blind():
    got = fidelity.vice_octave_split(_devils_trace(), _devils_trace())
    assert got["our_octave_split_frames"] == 0
    assert got["our_octave_split_blind_frames"] == 3


def test_with_the_oracle_the_pair_is_counted():
    oracle = [_voice(0x41B8, 4), fidelity.Voice(), fidelity.Voice()]
    got = fidelity.vice_octave_split(_devils_trace(), _devils_trace(),
                                     orig_keyed_by=oracle, our_keyed_by=oracle)
    assert got["our_octave_split_frames"] == 3
    assert got["our_octave_split_blind_frames"] == 0
    assert got["orig_octave_split_frames"] == 3
    assert got["our_octave_first_frame"] == 1


def test_an_oracle_that_never_saw_the_value_repairs_nothing():
    # siddump holds $0000 on the voice: no frame has low byte $B8
    oracle = [_voice(0x0000, 4), fidelity.Voice(), fidelity.Voice()]
    fixed = fidelity.vice_oracle_samples(_devils_trace(), oracle)
    assert [s.voices[0].freq for s in fixed] == [s.voices[0].freq
                                                 for s in _devils_trace()]


def test_the_oracle_names_a_non_octave_and_the_frame_is_not_counted():
    """Formula_1's held $0F82 dumps as $FF82; siddump saw $0F82, so against
    the whole $0F02 it is a 1.0x pair: neither counted nor blind."""
    held = _frames([_split(0xFF82, 0x0F02, 156)] * 4)
    oracle = [_voice(0x0F82, 4), fidelity.Voice(), fidelity.Voice()]
    got = fidelity.vice_octave_split(held, held, our_keyed_by=oracle,
                                     orig_keyed_by=oracle)
    assert got["our_octave_split_frames"] == 0
    assert got["our_octave_split_blind_frames"] == 0


def test_the_oracle_step_is_the_one_vice_freq_repair_uses():
    raw = [0x106E] * 300 + [0xFFB8] * 12 + [0x106E] * 300
    out, stats = fidelity.vice_freq_repair(raw, [], [0x41B8], 0)
    assert out[300] == 0x41B8 and stats["by_oracle"] == 12
    fixed, hit = fidelity._oracle_freq(raw, [0x41B8], 0)
    assert hit == list(range(300, 312)) and fixed[305] == 0x41B8


def test_an_oracle_with_two_high_bytes_for_one_low_byte_is_not_guessed():
    """$41B8 and $11B8 both within a frame of frame 0: one low byte, two high
    bytes, so frame 0's damaged samples stay damaged."""
    raw = [0xFFB8] * 4
    assert fidelity._oracle_freq(raw, [0x41B8, 0x11B8], 0) == (raw, [])
    # one high byte in reach is repaired
    assert fidelity._oracle_freq(raw, [0x41B8, 0x41B8], 0)[1] == [0, 1, 2, 3]


def test_the_column_documents_the_window_that_reaches_the_arps():
    """The arps first play at ~1818 (Monty, Devils_Galop) and ~2080 (Warhawk);
    a `-t 45` run is 2250 frames. Measured under --vice -t 45: window 2249."""
    dim = next(d for d in fidelity.DIMENSIONS if d.key == "octave_split")
    assert "-t 45" in dim.of and "2250" in dim.of
    assert "~1818" in dim.of and "~2080" in dim.of
