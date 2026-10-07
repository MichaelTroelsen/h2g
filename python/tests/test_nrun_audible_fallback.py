"""`noise_run_agreement`'s audible-noise fallback (task nrun-gate-off-fallback).

The gate-AND `noise_runs` is blind to a drum burst written under a CLOSED gate
(Kentilla, Proteus, Warhawk: `$41` attack, `$80` for 1-3 frames, `$40`; ours
plays the same burst `$81`), so the column declined those three files. The
same predicate made the PRIMARY reading moved 35 of 89 files (24 up, 3 down) at
3b1c66d and was refused. The fallback consults it ONLY where the gate-AND pairs
no instrument: a rescue may save a file that reads nothing and must never
disturb one that reads correctly.

Corpus A/B (89 preset songs, -t 180): see the task's evidence; the three files
above are the only movers.
"""
from collections import Counter

import fidelity


def _voice(wf, adsr):
    return fidelity.Voice(wf_events=list(wf), adsr_events=list(adsr))


def _side(wf, adsr):
    return [_voice(wf, adsr), fidelity.Voice(), fidelity.Voice()]


KEY = [(0, 0x0FDA)]          # a real Proteus/Warhawk key: release nibble $A
KEY_B = [(0, 0x0A09)]        # a second, different instrument key


def test_fallback_scores_a_file_whose_only_noise_is_under_a_closed_gate():
    orig = _side([(1, 0x41), (2, 0x80), (3, 0x40)], KEY)
    ours = _side([(1, 0x41), (2, 0x81), (3, 0x40)], KEY)
    assert fidelity.noise_runs(orig, 12) == {}          # the gate-AND sees none
    got = fidelity.noise_run_agreement(orig, ours, 12)
    assert got["noise_run_audible_fallback"] is True
    assert (got["noise_run_instruments"], got["noise_run_matched"]) == (1, 1)
    assert got["noise_run_agreement"] == 1.0
    assert got["noise_run_orig_only"] == 0 and got["noise_run_ours_only"] == 0


def test_fallback_can_still_disagree_on_length():
    """It scores, it does not rubber-stamp: a three-frame burst against a
    one-frame one pairs the key and reads 0/1."""
    orig = _side([(1, 0x41), (2, 0x80), (5, 0x40)], KEY)     # 3 audible frames
    ours = _side([(1, 0x41), (2, 0x81), (3, 0x40)], KEY)     # 1 frame
    got = fidelity.noise_run_agreement(orig, ours, 12)
    assert got["noise_run_audible_fallback"] is True
    assert (got["noise_run_instruments"], got["noise_run_matched"]) == (1, 0)
    assert got["noise_run_agreement"] == 0.0


def test_fallback_is_not_consulted_where_the_gate_and_already_pairs_a_key():
    """Both classes on one file: key A is gated on both sides (the primary
    reading pairs it), key B is a gate-off burst on the original and gated on
    ours. The audible reading would pair BOTH keys; the column must keep the
    primary's single instrument, exactly as it read before the fallback."""
    wf_o = [(1, 0x81), (3, 0x40), (5, 0x41), (6, 0x80), (7, 0x40)]
    wf_u = [(1, 0x81), (3, 0x40), (5, 0x41), (6, 0x81), (7, 0x40)]

    def side(wf):
        # same voice carries two instruments: key A for the first note,
        # key B (latched at frame 4) for the second
        return [_voice(wf, [(0, 0x0FDA), (4, 0x0A09)]),
                fidelity.Voice(), fidelity.Voice()]
    orig, ours = side(wf_o), side(wf_u)
    primary = fidelity.paired_keys(fidelity.noise_runs(orig, 12),
                                   fidelity.noise_runs(ours, 12))
    audible = fidelity.paired_keys(fidelity.noise_audible_runs(orig, 12),
                                   fidelity.noise_audible_runs(ours, 12))
    assert len(primary) == 1 and len(audible) == 2      # the two readings differ
    got = fidelity.noise_run_agreement(orig, ours, 12)
    assert got["noise_run_audible_fallback"] is False
    assert got["noise_run_instruments"] == 1


def test_fallback_that_pairs_nothing_leaves_the_column_declined():
    orig = _side([(1, 0x41), (2, 0x80), (3, 0x40)], KEY)
    quiet = _side([(1, 0x41), (3, 0x40)], KEY)           # ours sounds no noise
    got = fidelity.noise_run_agreement(orig, quiet, 12)
    assert got["noise_run_audible_fallback"] is False
    assert got["noise_run_instruments"] == 0 and got["noise_run_agreement"] is None
    assert got["noise_run_orig_gate_off_runs"] == 1     # the blindness is still recorded


def test_audible_runs_clip_to_the_release_and_drop_window_edges():
    # Release nibble 1 is 24 ms = 2 frames: a 6-frame `$80` stretch from the
    # gate drop is audible for 2.
    assert fidelity.noise_audible_runs(
        _side([(1, 0x41), (2, 0x80), (8, 0x40)], [(0, 0x0F01)]), 12) \
        == {0x0F01: Counter({2: 1})}
    # A SELECT latched on noise long after the release is silence.
    assert fidelity.noise_audible_runs(
        _side([(1, 0x41), (2, 0x40), (5, 0x80), (8, 0x40)], [(0, 0x0F00)]), 12) == {}
    # A voice never seen gated says nothing about being audible.
    assert fidelity.noise_audible_runs(
        _side([(1, 0x80), (3, 0x40)], KEY), 12) == {}
    # A run touching the last frame is cut by the window and dropped.
    assert fidelity.noise_audible_runs(_side([(1, 0x41), (2, 0x81)], KEY), 12) == {}
    # With no gate-off tail it IS the gate-AND reading (a gated run, then `$40`).
    side = _side([(1, 0x41), (2, 0x81), (5, 0x40)], KEY)
    assert fidelity.noise_audible_runs(side, 12) == fidelity.noise_runs(side, 12)


def test_the_report_names_the_files_the_fallback_rescued():
    from test_fidelity import _Args, _row
    res = _row("Rescued.sid", "measured", 1.0, 50, 50)
    res.update(wave=0.9, wave_frames=100, orig_noise_frames=90, our_noise_frames=80,
               noise_run_instruments=4, noise_run_matched=3, noise_run_agreement=0.75,
               noise_run_orig_only=0, noise_run_ours_only=0,
               noise_run_orig_edge_runs=0, noise_run_orig_edge_frames=0,
               noise_run_ours_edge_runs=0, noise_run_ours_edge_frames=0,
               noise_run_orig_gate_off_runs=40, noise_run_orig_gate_off_frames=88,
               noise_run_ours_gate_off_runs=0, noise_run_ours_gate_off_frames=0,
               noise_run_audible_fallback=True)
    plain = _row("Plain.sid", "measured", 1.0, 50, 50)
    plain.update(wave=0.9, wave_frames=100, orig_noise_frames=90, our_noise_frames=80,
                 noise_run_instruments=2, noise_run_matched=2, noise_run_agreement=1.0,
                 noise_run_orig_only=0, noise_run_ours_only=0,
                 noise_run_audible_fallback=False)
    text = fidelity.report([res, plain], _Args())
    line = next(l for l in text.splitlines() if "AUDIBLE" in l and "`nrun` read" in l)
    assert "**1** file(s)" in line
    assert "Rescued.sid (3/4 instrument(s) agree)" in line
    assert "Plain.sid" not in line
    # a rescued file is no longer a declined one
    assert not any("`nrun` declined" in l and "Rescued.sid" in l
                   for l in text.splitlines())
    d = next(x for x in fidelity.DIMENSIONS if x.key == "noise_run_agreement")
    assert "Rescued by a fallback, only where the gate-AND pairs no key" in d.of
