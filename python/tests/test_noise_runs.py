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
