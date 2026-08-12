"""The waveform a note *opens* on, which no other column could see.

`wave` averages per-frame agreement over the whole trace, so a wrong opening
frame on an instrument with 43 notes is a rounding error against 3000 frames.
`nrun` compares the lengths of noise runs and is deliberately
position-independent, so a run that is right but starts a frame early scores
perfect. Between them they missed, for as long as both emitters existed, that
`_wave_program_entries` and `_two_stage_entries` opened on the effect where the
player opens on the record's own waveform -- Trans-Atlantic's GT 3 playing
`noise tri pulse` against an original's `tri noise tri pulse`, with `wave` at
63% either way.
"""
from collections import Counter

import fidelity as F


def _voices(*event_lists):
    vs = [F.Voice(wf_events=list(wf), adsr_events=list(ad),
                  attack_frames=list(at))
          for wf, ad, at in event_lists]
    return vs + [F.Voice()] * (3 - len(event_lists))


def test_the_shape_is_the_waveform_class_from_the_attack():
    v = _voices(([(0, 0x11), (1, 0x81), (2, 0x11), (3, 0x41)],
                 [(0, 0x0729)], [0]))
    assert F.onset_shapes(v, 8) == {0x0729: Counter({(0x10, 0x80, 0x10, 0x40): 1})}


def test_the_gate_bit_is_ignored_exactly_as_wave_ignores_it():
    """A second notion of 'class' is how two columns start telling different
    stories about one register, so this shares `wave_compare`'s reduction."""
    gated = _voices(([(0, 0x41), (1, 0x41), (2, 0x41), (3, 0x41)],
                     [(0, 0x0A09)], [0]))
    ungated = _voices(([(0, 0x40), (1, 0x40), (2, 0x40), (3, 0x40)],
                       [(0, 0x0A09)], [0]))
    assert F.onset_shapes(gated, 8) == F.onset_shapes(ungated, 8)


def test_a_note_whose_window_runs_past_the_trace_is_dropped():
    """What that would measure is the distance to the end of the window."""
    v = _voices(([(0, 0x41)], [(0, 0x0A09)], [0, 6]))
    shapes = F.onset_shapes(v, 8)
    assert sum(shapes[0x0A09].values()) == 1     # the attack at 6 needs 6..9


def test_the_key_is_the_adsr_after_the_attack_not_on_it():
    """The attack frame can still hold a hard restart's envelope, which is the
    player's transition and not the instrument -- instrmap.py's rule."""
    v = _voices(([(0, 0x41)], [(0, 0x0000), (1, 0x0A09)], [0]))
    assert list(F.onset_shapes(v, 8)) == [0x0A09]


def test_the_measured_register_is_not_in_the_attribution_key():
    """$D404 is measured and $D405/$D406 is the key. Keying a measurement on
    the register containing it is what made `tail` report 'nothing to compare'
    for the one change it was built for."""
    a = _voices(([(0, 0x41)], [(0, 0x0A09)], [0]))
    b = _voices(([(0, 0x81)], [(0, 0x0A09)], [0]))
    # Different waveforms, same instrument key -- so they are comparable.
    assert set(F.onset_shapes(a, 8)) == set(F.onset_shapes(b, 8))
    assert F.onset_agreement(a, b, 8)["onset_instruments"] == 1
    assert F.onset_agreement(a, b, 8)["onset_matched"] == 0


def test_ours_missing_the_originals_first_frame_is_EARLY():
    """**The direction this column exists to report, and it is easy to write
    backwards.** `ours == orig[1:]` means we never played the original's first
    frame: we are a frame ahead of it. That is the real defect on
    Trans-Atlantic's GT 3 -- the original opens `tri noise tri pulse` and we
    open `noise tri pulse ...` because our wavetable began on the effect
    instead of on the record's own waveform.
    """
    orig = _voices(([(0, 0x11), (1, 0x81), (2, 0x11), (3, 0x41)],
                    [(0, 0x0729)], [0]))
    ours = _voices(([(0, 0x81), (1, 0x11), (2, 0x41), (3, 0x81)],
                    [(0, 0x0729)], [0]))
    got = F.onset_agreement(orig, ours, 8)
    assert got["onset_ours_early"] == 1
    assert got["onset_ours_late"] == 0
    assert got["onset_matched"] == 0


def test_ours_with_an_extra_leading_frame_is_LATE():
    """The mirror, so the two cannot both be satisfied by one implementation."""
    orig = _voices(([(0, 0x81), (1, 0x11), (2, 0x41), (3, 0x81)],
                    [(0, 0x0729)], [0]))
    ours = _voices(([(0, 0x11), (1, 0x81), (2, 0x11), (3, 0x41)],
                    [(0, 0x0729)], [0]))
    got = F.onset_agreement(orig, ours, 8)
    assert got["onset_ours_late"] == 1
    assert got["onset_ours_early"] == 0


def test_an_instrument_only_we_play_is_absent_rather_than_wrong():
    """`melody` already reports a dropped or invented instrument; counting it
    here too would let one defect move two columns."""
    orig = _voices(([(0, 0x41)], [(0, 0x0A09)], [0]))
    ours = _voices(([(0, 0x41)], [(0, 0x0B08)], [0]))
    got = F.onset_agreement(orig, ours, 8)
    assert got["onset_instruments"] == 0
    assert got["onset_agreement"] is None


def test_the_first_frame_is_reported_beside_the_whole_shape():
    """A fix that corrects the opening frame and leaves the rest shifted moves
    one of these and not the other, which is worth being able to see."""
    orig = _voices(([(0, 0x11), (1, 0x81), (2, 0x11), (3, 0x41)],
                    [(0, 0x0729)], [0]))
    ours = _voices(([(0, 0x11), (1, 0x41), (2, 0x41), (3, 0x41)],
                    [(0, 0x0729)], [0]))
    got = F.onset_agreement(orig, ours, 8)
    assert got["onset_first_matched"] == 1
    assert got["onset_matched"] == 0


def test_it_needs_no_startup_lag_correction():
    """Each side is read at its *own* attack frames, so the packed player's
    3-8 frame latency cancels by construction. Passing a lag in would move our
    reads off our own attacks and manufacture the phase error this detects --
    which is what the first wiring of this column did."""
    orig = _voices(([(0, 0x41), (1, 0x81)], [(0, 0x0A09)], [0]))
    shifted = _voices(([(5, 0x41), (6, 0x81)], [(5, 0x0A09)], [5]))
    assert (F.onset_shapes(orig, 16)[0x0A09]
            == F.onset_shapes(shifted, 16)[0x0A09])
    assert F.onset_agreement(orig, shifted, 16)["onset_agreement"] == 1.0
