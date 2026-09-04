"""A noise-run measure that does not anchor on an attack.

Every other reading of the drum in this project asks what the waveform is at
`a + k` for a gate-edge attack `a`. That anchor moves when the run's *length*
changes, so two settings get measured on different populations and their
agreement rates are not comparable -- shortening the drum's noise tick shifts
five corpus instruments' runs from `a+1` to `a+0`. Four boundary errors in one
session came from this.

A run's length does not depend on where the run begins, which is what makes this
measure able to settle the question the attack-anchored ones could not.
"""
from collections import Counter

import fidelity as F


def _voices(*event_lists):
    vs = [F.Voice(wf_events=list(wf), adsr_events=list(ad))
          for wf, ad in event_lists]
    return vs + [F.Voice()] * (3 - len(event_lists))


def test_a_run_is_measured_by_its_length_not_its_position():
    """The same two-frame run, one frame apart, is the same measurement."""
    early = _voices(([(1, 0x41), (2, 0x81), (4, 0x41)], [(1, 0x0A99)]))
    late = _voices(([(1, 0x41), (3, 0x81), (5, 0x41)], [(1, 0x0A99)]))
    assert F.noise_runs(early, 12) == F.noise_runs(late, 12)
    assert F.noise_runs(early, 12)[0x0A99] == Counter({2: 1})


def test_run_length_is_the_thing_that_distinguishes():
    one = _voices(([(1, 0x41), (2, 0x81), (3, 0x41)], [(1, 0x0A99)]))
    two = _voices(([(1, 0x41), (2, 0x81), (4, 0x41)], [(1, 0x0A99)]))
    assert F.noise_runs(one, 12)[0x0A99] == Counter({1: 1})
    assert F.noise_runs(two, 12)[0x0A99] == Counter({2: 1})


def test_a_run_cut_by_the_window_is_dropped():
    """Its length is a fact about the window, not about the tune. A run touching
    either edge would otherwise report whatever the trace length allowed."""
    at_start = _voices(([(0, 0x81), (3, 0x41)], [(0, 0x0A99)]))
    at_end = _voices(([(1, 0x41), (8, 0x81)], [(1, 0x0A99)]))
    assert F.noise_runs(at_start, 12) == {}
    assert F.noise_runs(at_end, 12) == {}


def test_attribution_is_the_adsr_at_the_runs_midpoint():
    """Not its start: the ADSR pair identifies the instrument, and the midpoint
    is inside the note however the run sits within it."""
    v = _voices(([(1, 0x41), (2, 0x81), (6, 0x41)],
                 [(0, 0x0111), (2, 0x0A99)]))
    assert list(F.noise_runs(v, 12)) == [0x0A99]


def test_several_runs_of_one_instrument_are_tallied():
    v = _voices(([(1, 0x41), (2, 0x81), (4, 0x41), (6, 0x81), (8, 0x41)],
                 [(1, 0x0A99)]))
    assert F.noise_runs(v, 14)[0x0A99] == Counter({2: 2})


def test_agreement_counts_only_instruments_both_sides_sound():
    """A conversion that drops an instrument's noise entirely is *absent* here,
    not a disagreement -- that is what the one-sided `noise` count is for. This
    answers the narrower question: given that we sound it, for as long?"""
    orig = _voices(([(1, 0x41), (2, 0x81), (4, 0x41)], [(1, 0x0A99)]))
    same = _voices(([(1, 0x41), (5, 0x81), (7, 0x41)], [(1, 0x0A99)]))
    short = _voices(([(1, 0x41), (2, 0x81), (3, 0x41)], [(1, 0x0A99)]))
    silent = _voices(([(1, 0x41)], [(1, 0x0A99)]))

    got = F.noise_run_agreement(orig, same, 12)
    assert (got["noise_run_matched"], got["noise_run_instruments"]) == (1, 1)
    assert got["noise_run_agreement"] == 1.0

    got = F.noise_run_agreement(orig, short, 12)
    assert (got["noise_run_matched"], got["noise_run_instruments"]) == (0, 1)

    got = F.noise_run_agreement(orig, silent, 12)
    assert got["noise_run_instruments"] == 0
    assert got["noise_run_agreement"] is None
    assert got["noise_run_orig_only"] == 1


def test_a_side_sounding_noise_the_other_never_does_is_named_not_scored():
    orig = _voices(([(1, 0x41)], [(1, 0x0A99)]))
    ours = _voices(([(1, 0x41), (2, 0x81), (4, 0x41)], [(1, 0x0A99)]))
    got = F.noise_run_agreement(orig, ours, 12)
    assert got["noise_run_ours_only"] == 1
    assert got["noise_run_agreement"] is None


def test_the_first_frame_of_every_run_is_spent_on_a_waveform_below_ten():
    """Why our noise runs are one frame short, as a property rather than a file.

    A note's first frame carries `FIRSTWAVE_TESTBIT` unless `no_test_restart`
    is set. That byte is BELOW $10, so it selects no waveform at all -- and
    everything the instrument then does starts on frame 1. A run the player
    holds for N frames therefore reaches the chip as N-1.

    Measured on Action_Biker at v0.5.453: 62 runs of 11 against the original's
    12, `our_noise_frames` 682 against 744 -- a deficit of exactly 62, one
    frame per run -- and setting `no_test_restart` takes the agreement 0.0 ->
    1.0 with the frame count landing exactly on 744.

    The `< 0x10` assertion is the load-bearing one: it is what makes the frame
    silent to `noise_compare`, and it is also what siddump needs in order to
    name an attack at all, which is why removing the frame trades the run
    length for `melody`. A test on the byte's VALUE alone would not say that.
    """
    from h2g.goatwriter import FIRSTWAVE_GATE_ONLY, FIRSTWAVE_TESTBIT

    # $09 -- gate plus the test bit, waveform nibble zero.
    assert FIRSTWAVE_TESTBIT < 0x10, (
        "the test-restart frame must select no waveform: that is what costs a "
        "run its first frame, and what lets siddump name the attack")
    # $FF -- all four select bits plus the test bit. AUDIBLY silent too (the
    # test bit holds the oscillator in reset and the select bits AND to
    # silence), but its VALUE is >= $10, so siddump sees a waveform and cannot
    # use the frame as a note boundary. THAT asymmetry is the whole trade:
    # both settings sound the same and only one is visible to the instrument.
    assert FIRSTWAVE_GATE_ONLY >= 0x10, (
        "the no_test_restart replacement is >= $10, which is why removing the "
        "test frame fixes the run length and blinds `melody`")
    assert FIRSTWAVE_TESTBIT != FIRSTWAVE_GATE_ONLY
    # Neither is noise, so `noise_compare` counts neither on either setting --
    # the frame is lost to the run regardless of which byte occupies it.
    assert not (FIRSTWAVE_TESTBIT & 0x80)
