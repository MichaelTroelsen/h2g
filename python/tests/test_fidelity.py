"""The fidelity harness: what counts as a note event, and how two traces compare.

`fidelity.py` is the only thing in this repo that measures whether a
conversion *sounds* like its source rather than whether it parses. Everything
it reports rests on one distinction -- which of siddump's note cells is a
struck note -- so that is what these tests pin down, against rows captured
verbatim from `siddump.exe`.

siddump prints a bare note (`E-7 D8`) only after a gate rising edge:
siddump.c:376-380 sets `prevchn[c].note = -1` on keyoff->keyon, and :409
prints the bare form only when that flag is set. A parenthesised note
(`(F#1 92)`) is the same voice moving to a different pitch without
re-triggering, and `(+ 0034)` is a frequency slide inside one note. Counting
all three as "notes" -- which a `grep -oE "[A-G]#?-[0-9]"` over the dump does
-- conflates a re-struck note with a vibrato cycle, and that conflation is
what made an early measurement read as a 7x re-trigger defect.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

import fidelity

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Verbatim siddump output: header, a first frame (all three voices attack), a
# parenthesised note change, two slides, and unchanged cells.
DUMP = """Load address: $5000 Init address: $5FB2 Play address: $5012
Calling initroutine with subtune 0
Calling playroutine for 100 frames, starting from frame 0
Middle C frequency is $1168

| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | AF58  E-7 D8  15 0DFB 180 | 0000  C-0 80  43 0FC4 200 | 03A9  A-1 95  41 099F 180 | 0000 00 Off F |
|     1 | 0303 (F#1 92) 80 .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... 196 | .... .. ... . |
|     3 | ....  ... ..  .. .... CE0 | 1D12 (- 0034) .. .... 140 | 05CE (F-2 9D) 41 .... 1C0 | .... .. ... . |
|     5 | ....  ... ..  .. .... D40 | 1D12 (+ 0034) .. .... 1C0 | ....  ... ..  .. .... 240 | .... .. ... . |
|     6 | 4E20  D-6 CA  41 .... C80 | 1D46 (+ 0034) .. .... 200 | ....  ... ..  .. .... 280 | .... .. ... . |
"""


def test_only_bare_notes_count_as_attacks():
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.attacks == ["E-7", "D-6"]      # frames 0 and 6
    assert v1.attacks == ["C-0"]             # frame 0 only
    assert v2.attacks == ["A-1"]


def test_a_parenthesised_note_is_a_tie_not_an_attack():
    v0, _, v2 = fidelity.parse_dump(DUMP)
    assert v0.ties == 1                      # (F#1 92)
    assert v2.ties == 1                      # (F-2 9D)
    assert "F#1" not in v0.attacks


def test_a_frequency_delta_is_a_slide():
    _, v1, _ = fidelity.parse_dump(DUMP)
    assert v1.slides == 3                    # (- 0034), (+ 0034), (+ 0034)
    assert v1.ties == 0


def test_attack_frames_are_recorded():
    v0 = fidelity.parse_dump(DUMP)[0]
    assert v0.attack_frames == [0, 6]


def test_header_and_rule_rows_are_not_frames():
    # The header row also starts with '|' and has the right field count.
    assert sum(len(v.attacks) + v.ties + v.slides
               for v in fidelity.parse_dump(DUMP)) == 4 + 2 + 3


def test_waveform_writes_are_recorded_per_voice():
    # The WF column is the 2 chars after the 9-char note field in all four
    # note formats; '..' means "not written this frame" and is not an event.
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.wf_events == [(0, 0x15), (1, 0x80), (6, 0x41)]
    assert v1.wf_events == [(0, 0x43)]
    assert v2.wf_events == [(0, 0x41), (3, 0x41)]


def test_register_timeline_carries_the_register_forward():
    # siddump prints a row only on change; between writes the chip keeps
    # playing the latched value, and skipped frames (2, 4, 5) inherit it.
    v0 = fidelity.parse_dump(DUMP)[0]
    assert fidelity.register_timeline(v0.wf_events, 8) == \
        [0x15, 0x80, 0x80, 0x80, 0x80, 0x80, 0x41, 0x41]


# --- the rest of the row: ADSR, pulse width, and the global filter cell -----
#
# siddump prints five register groups per frame and the harness used to read
# two fields out of three of them. These pin the other seven, and above all
# the one property they share: a field printed as dots is the chip *holding*
# its last value, so every one of them has to carry forward.

def test_adsr_writes_are_recorded_per_voice():
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.adsr_events == [(0, 0x0DFB)]
    assert v1.adsr_events == [(0, 0x0FC4)]
    assert v2.adsr_events == [(0, 0x099F)]


def test_pulse_writes_are_recorded_per_voice():
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.pulse_events == [(0, 0x180), (3, 0xCE0), (5, 0xD40), (6, 0xC80)]
    assert v1.pulse_events == [(0, 0x200), (3, 0x140), (5, 0x1C0), (6, 0x200)]
    assert v2.pulse_events == \
        [(0, 0x180), (1, 0x196), (3, 0x1C0), (5, 0x240), (6, 0x280)]


def test_the_global_cell_is_read():
    # ' 0000 00 Off F ' on frame 0, dots on every later frame in DUMP.
    f = fidelity.parse_dump(DUMP).filter
    assert f.cutoff_events == [(0, 0x0000)]
    assert f.ctrl_events == [(0, 0x00)]
    assert f.passband_events == [(0, 0)]      # 'Off'
    assert f.volume_events == [(0, 0xF)]


# A filter sweep: cutoff moving frame by frame, the $D417 byte and the
# passband changing once each, and the master volume ducking. Written in
# siddump's exact column widths (siddump.c:451-467) -- note 'Hi ' is padded
# to three characters in siddump's own table, so the cell reads 'Hi  '.
FILTER_DUMP = """| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | AF58  E-7 D8  15 0DFB 180 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 0800 F1 Low F |
|     1 | ....  ... ..  .. 0A08 ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 0A00 .. ... . |
|     2 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 0C00 .. Hi  . |
|     4 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | .... 04 ... 8 |
"""


def test_every_global_field_is_read_independently():
    f = fidelity.parse_dump(FILTER_DUMP).filter
    assert f.cutoff_events == [(0, 0x0800), (1, 0x0A00), (2, 0x0C00)]
    assert f.ctrl_events == [(0, 0xF1), (4, 0x04)]
    assert f.passband_events == [(0, 1), (2, 4)]   # 'Low', then 'Hi '
    assert f.volume_events == [(0, 0xF), (4, 0x8)]


def test_the_passband_name_round_trips_to_its_register_bits():
    # The index is ($D418 >> 4) & 7, so the name is the register value.
    assert fidelity.FILTER_PASSBAND[4] == "Hi"
    assert fidelity.FILTER_PASSBAND[0] == "Off"
    assert len(fidelity.FILTER_PASSBAND) == 8


def test_a_held_register_is_not_a_zero():
    # The whole point of the parse contract. Frames 3 and 5+ print no cutoff
    # at all; the filter is still open at $0C00, not closed.
    f = fidelity.parse_dump(FILTER_DUMP).filter
    assert fidelity.register_timeline(f.cutoff_events, 6) == \
        [0x0800, 0x0A00, 0x0C00, 0x0C00, 0x0C00, 0x0C00]
    assert fidelity.register_timeline(f.volume_events, 6) == \
        [0xF, 0xF, 0xF, 0xF, 0x8, 0x8]
    assert fidelity.register_timeline(f.passband_events, 6) == \
        [1, 1, 4, 4, 4, 4]


def test_adsr_and_pulse_carry_forward_the_same_way():
    v0 = fidelity.parse_dump(FILTER_DUMP)[0]
    assert fidelity.register_timeline(v0.adsr_events, 5) == \
        [0x0DFB, 0x0A08, 0x0A08, 0x0A08, 0x0A08]
    assert fidelity.register_timeline(v0.pulse_events, 5) == \
        [0x180] * 5


def test_a_silent_voice_contributes_no_events():
    v1 = fidelity.parse_dump(FILTER_DUMP)[1]
    assert v1.wf_events == v1.adsr_events == v1.pulse_events == []


def test_collapsed_merges_consecutive_repeats_only():
    v = fidelity.Voice(attacks=["B-4", "B-4", "B-4", "E-4", "B-4"])
    assert v.collapsed == ["B-4", "E-4", "B-4"]


def _voices(*seqs):
    return [fidelity.Voice(attacks=list(s)) for s in seqs]


def test_identical_traces_score_one():
    a = _voices(["C-4", "E-4"], ["G-3"], [])
    got = fidelity.compare(a, _voices(["C-4", "E-4"], ["G-3"], []))
    assert got["melody"] == 1.0 and got["sequence"] == 1.0
    assert got["retrigger_ratio"] == 1.0


def test_disjoint_traces_score_zero():
    got = fidelity.compare(_voices(["C-4"], [], []), _voices(["G-7"], [], []))
    assert got["melody"] == 0.0
    assert got["pitch_jaccard"] == 0.0


def test_a_retriggered_hold_costs_sequence_but_not_melody():
    """The defect the harness exists to tell apart from a wrong note.

    Striking one held note eight times plays the same music badly; playing
    eight different notes plays different music. Both would look identical to
    a raw event count, so melody (collapsed) and sequence (not) must diverge.
    """
    orig = _voices(["B-4"], [], [])
    ours = _voices(["B-4"] * 8, [], [])
    got = fidelity.compare(orig, ours)
    assert got["melody"] == 1.0
    assert got["sequence"] < 0.5
    assert got["retrigger_ratio"] == 8.0


def test_a_voice_silent_in_both_does_not_dilute_the_score():
    two_voices = fidelity.compare(_voices(["C-4"], ["G-3"]),
                                  _voices(["C-4"], ["A-3"]))
    plus_silent = fidelity.compare(_voices(["C-4"], ["G-3"], []),
                                   _voices(["C-4"], ["A-3"], []))
    assert two_voices["melody"] == plus_silent["melody"]
    # ... and a voice the original plays counts even when ours is silent.
    dropped = fidelity.compare(_voices(["C-4"], ["G-3", "A-3"], []),
                               _voices(["C-4"], [], []))
    assert dropped["melody"] < 1.0


def test_a_loud_voice_outweighs_a_sparse_one():
    """Weighting is by the original's attack count, so the voice carrying the
    tune decides the score rather than one playing two notes."""
    orig = _voices(["C-4"] * 20, ["G-3"], [])
    melody_wrong = fidelity.compare(orig, _voices(["A-7"] * 20, ["G-3"], []))
    sparse_wrong = fidelity.compare(orig, _voices(["C-4"] * 20, ["A-7"], []))
    assert melody_wrong["melody"] < sparse_wrong["melody"]


# --- waveform-class agreement ----------------------------------------------

def _wf_voice(*events):
    return fidelity.Voice(wf_events=list(events))


def _wf_voices(*event_lists):
    vs = [_wf_voice(*e) for e in event_lists]
    return vs + [fidelity.Voice()] * (3 - len(vs))


def test_a_trace_against_itself_has_full_wave_agreement():
    a = _wf_voices([(0, 0x41), (5, 0x81)], [(0, 0x21)])
    got = fidelity.wave_compare(a, _wf_voices([(0, 0x41), (5, 0x81)], [(0, 0x21)]),
                                nframes=10)
    assert got["wave"] == 1.0


def test_the_gate_bit_is_not_a_timbre():
    # $41 (gated pulse) and $40 (released pulse) are the same class: note
    # length is the attack metrics' job, not this one's.
    got = fidelity.wave_compare(_wf_voices([(0, 0x41)]),
                                _wf_voices([(0, 0x40)]), nframes=4)
    assert got["wave"] == 1.0


def test_a_combined_waveform_is_its_own_class():
    # $51 (tri+pulse) matches neither pure triangle nor pure pulse.
    tri_pulse = _wf_voices([(0, 0x51)])
    assert fidelity.wave_compare(tri_pulse, _wf_voices([(0, 0x41)]),
                                 nframes=2)["wave"] == 0.0
    assert fidelity.wave_compare(tri_pulse, _wf_voices([(0, 0x11)]),
                                 nframes=2)["wave"] == 0.0
    assert fidelity.wave_compare(tri_pulse, _wf_voices([(0, 0x51)]),
                                 nframes=2)["wave"] == 1.0


def test_an_invented_noise_tick_costs_agreement_and_is_counted():
    """The Phase-0 signal: our fabricated wavetable opens a note on a frame
    of noise where the original plays pulse throughout."""
    orig = _wf_voices([(0, 0x41)])
    ours = _wf_voices([(0, 0x81), (1, 0x41)])   # noise tick, then pulse
    got = fidelity.wave_compare(orig, ours, nframes=4)
    assert got["wave"] == 0.75                  # 1 of 4 frames disagrees
    assert got["orig_noise_frames"] == 0
    assert got["our_noise_frames"] == 1


def test_frames_silent_on_both_sides_do_not_inflate_agreement():
    # Both sides drop to class 0 at frame 2, so only frames 0-1 are counted:
    # a long shared silence must not drown out a real timbre disagreement.
    orig = _wf_voices([(0, 0x41), (2, 0x00)])
    ours = _wf_voices([(0, 0x21), (2, 0x00)])
    got = fidelity.wave_compare(orig, ours, nframes=6)
    assert got["wave_frames"] == 2
    assert got["wave"] == 0.0
    # ... but one side selecting a waveform against silence is a disagreement.
    half = fidelity.wave_compare(_wf_voices([(0, 0x41)]),
                                 _wf_voices([(0, 0x41), (2, 0x00)]), nframes=4)
    assert half["wave"] == 0.5


def test_noise_frames_are_counted_over_all_frames_per_side():
    # Carry-forward: noise latched at frame 1 persists to nframes.
    got = fidelity.wave_compare(_wf_voices([(0, 0x41), (1, 0x81)]),
                                _wf_voices([(0, 0x41)]), nframes=5)
    assert got["orig_noise_frames"] == 4
    assert got["our_noise_frames"] == 0


def test_wave_is_none_when_no_frames_are_counted():
    got = fidelity.wave_compare(_wf_voices(), _wf_voices(), nframes=5)
    assert got["wave"] is None


def test_wave_nframes_defaults_to_the_last_write_seen():
    got = fidelity.wave_compare(_wf_voices([(0, 0x41)]),
                                _wf_voices([(0, 0x41), (9, 0x21)]))
    assert got["wave_frames"] == 10
    assert got["wave"] == 0.9


# --- envelope, duty cycle and filter ---------------------------------------
#
# The three dimensions the report gained once parse_dump stopped discarding
# them. Each answers a differently shaped question, and the shape is the
# design: ADSR is an agreement percentage because both sides always have an
# envelope; pulse and filter are one-sided counts because the failures they
# watch are a dimension one side moves and the other does not.


def _adsr_voices(*event_lists):
    vs = [fidelity.Voice(adsr_events=list(e)) for e in event_lists]
    return vs + [fidelity.Voice()] * (3 - len(vs))


def test_adsr_agreement_carries_the_register_forward():
    # One write each, held for the whole window: agreement is total, and the
    # frames between writes are counted rather than skipped.
    same = fidelity.adsr_compare(_adsr_voices([(0, 0x0F00)]),
                                 _adsr_voices([(0, 0x0F00)]), 10)
    assert same["adsr"] == 1.0 and same["adsr_frames"] == 10


def test_a_wrong_sustain_nibble_costs_every_frame_it_is_held():
    """The v0.5.71 defect, in miniature: $0FFE against $0FFF is one nibble,
    and it is the level the note holds at for its whole length."""
    got = fidelity.adsr_compare(_adsr_voices([(0, 0x0FFF)]),
                                _adsr_voices([(0, 0x0FFE)]), 20)
    assert got["adsr"] == 0.0
    assert got["adsr_frames"] == 20


def test_a_hard_restart_frame_costs_only_that_frame():
    # Goattracker writes $0F00 for one frame before each note; the original
    # never does. That is a single frame of disagreement, not a whole note's.
    orig = _adsr_voices([(0, 0x1234)])
    ours = _adsr_voices([(0, 0x1234), (4, 0x0F00), (5, 0x1234)])
    assert fidelity.adsr_compare(orig, ours, 10)["adsr"] == 0.9


def test_a_voice_with_no_envelope_on_either_side_is_not_counted():
    # The same rule wave_compare uses for class 0: a voice no player ever
    # gave an envelope is not evidence either way...
    got = fidelity.adsr_compare(_adsr_voices([(0, 0x0F00)]),
                                _adsr_voices([(0, 0x0F00)]), 8)
    assert got["adsr_frames"] == 8          # one voice, not three
    # ...but one side having an envelope against the other's silence is a
    # disagreement, not an exemption.
    half = fidelity.adsr_compare(_adsr_voices([(2, 0x0F00)]),
                                 _adsr_voices([]), 4)
    assert half["adsr_frames"] == 2 and half["adsr"] == 0.0


def test_adsr_is_none_when_neither_side_ever_set_an_envelope():
    assert fidelity.adsr_compare(_adsr_voices(), _adsr_voices(), 50)["adsr"] is None


def _wf_at(*event_lists):
    return ([fidelity.Voice(wf_events=list(e),
                            attack_frames=[f for f, w in e if w & 0x01])
             for e in event_lists]
            + [fidelity.Voice()] * (3 - len(event_lists)))


def test_the_startup_lag_is_the_difference_in_first_attack_frames():
    """gt2reloc's player spends a few frames initialising before its first
    note. Commando's first attacks are at frame 8 where the original's are at
    1, and that constant was charged to the converter: `wave` read 65% for a
    file whose waveforms agree 92% of the time once aligned."""
    o = _wf_at([(1, 0x41)])
    u = _wf_at([(8, 0x41)])
    assert fidelity.startup_lag(o, u) == (7, 7)


def test_an_alignment_shift_recovers_the_agreement_it_was_charged_for():
    o = _wf_at([(1, 0x41), (11, 0x81), (13, 0x41)])
    u = _wf_at([(8, 0x41), (18, 0x81), (20, 0x41)])
    lag, _ = fidelity.startup_lag(o, u)
    assert fidelity.wave_compare(o, u, nframes=40)["wave"] < 1.0
    assert fidelity.wave_compare(o, u, nframes=40, lag=lag)["wave"] == 1.0


def test_a_lag_too_large_to_be_a_latency_is_reported_not_applied():
    """Chimera's raw lag is 438 frames -- 8.8 s, an opening one side does not
    have. Absorbing that into an alignment would hide a real defect and throw
    away a third of the window, so the applied lag is clamped and the raw one
    kept."""
    o = _wf_at([(1, 0x41)])
    u = _wf_at([(439, 0x41)])
    lag, raw = fidelity.startup_lag(o, u)
    assert (lag, raw) == (fidelity.MAX_STARTUP_LAG, 438)


def test_a_conversion_that_starts_early_shifts_the_other_way():
    o = _wf_at([(5, 0x41)])
    u = _wf_at([(3, 0x41)])
    assert fidelity.startup_lag(o, u) == (-2, -2)


def test_noise_counts_are_taken_before_the_shift():
    """`noise` is a one-sided count over each side's own window. Shifting one
    of them would drop `lag` frames from that side's total alone, so the count
    would move with the alignment rather than with the conversion."""
    o = _wf_at([(0, 0x81)])
    u = _wf_at([(0, 0x81)])
    for lag in (0, 5):
        got = fidelity.wave_compare(o, u, nframes=20, lag=lag)
        assert got["orig_noise_frames"] == got["our_noise_frames"] == 20


def test_a_side_that_never_attacks_gets_no_lag():
    assert fidelity.startup_lag(_wf_at([(1, 0x41)]), _wf_at()) == (0, 0)


def _pulse_voices(*event_lists):
    vs = [fidelity.Voice(pulse_events=list(e)) for e in event_lists]
    return vs + [fidelity.Voice()] * (3 - len(vs))


def test_a_frozen_duty_cycle_reads_as_no_movement():
    """The v0.5.73 defect: one 'set pulse width' per instrument and stop,
    against a player writing $D402/$D403 every frame."""
    orig = _pulse_voices([(f, 0x800 + f * 0x10) for f in range(10)])
    ours = _pulse_voices([(0, 0x800)])
    got = fidelity.pulse_compare(orig, ours, 10)
    assert got["orig_pulse_changes"] == 9
    assert got["our_pulse_changes"] == 0


def test_rewriting_the_same_width_is_not_a_sweep():
    # Counted off the expanded timeline, not the event list: a player that
    # writes the same value every frame has not moved the duty cycle.
    ours = _pulse_voices([(f, 0x800) for f in range(10)])
    assert fidelity.pulse_compare(_pulse_voices([(0, 0x800)]), ours,
                                  10)["our_pulse_changes"] == 0


def test_pulse_movement_is_counted_per_voice():
    got = fidelity.pulse_compare(
        _pulse_voices([(0, 0x100), (1, 0x200)], [(0, 0x100)]),
        _pulse_voices([(0, 0x100)], [(0, 0x100), (2, 0x300), (3, 0x400)]), 5)
    assert [v["orig_pulse_changes"] for v in got["pulse_voices"]] == [1, 0, 0]
    assert [v["our_pulse_changes"] for v in got["pulse_voices"]] == [0, 2, 0]


def test_the_same_sweep_in_half_sized_steps_doubles_the_count_not_the_span():
    """Why `pspan` exists beside `pul`, in the one case that produced it.

    A Goattracker pulse speed is a signed byte, so a player step of 224 a frame
    is emitted as 127 twice. The sound is the same sweep; the count reads it as
    twice the movement. `pul` alone would score v0.5.174's third pulse engine
    as a large regression -- 5_Title_Tunes went 3/236 to 338/236 -- for a band
    that in fact came out slightly narrower than the original's.
    """
    coarse = _pulse_voices([(f, 0x800 + f * 0x100) for f in range(5)])
    fine = _pulse_voices([(f, 0x800 + f * 0x80) for f in range(9)])
    got = fidelity.pulse_compare(coarse, fine, 9)
    assert got["our_pulse_changes"] == 2 * got["orig_pulse_changes"]
    assert got["pulse_span"] == 1.0, "the band is the same one, either way"


def test_the_leading_zero_goattracker_writes_is_not_part_of_the_band():
    """Goattracker writes $D402/$D403 on every frame from the first call, so
    our timeline opens on $000 where the player's opens on a real width. Left
    in, that is a spurious jump on all three voices of every file -- it read as
    3.96x the original's band on Commando for a sweep that covers less."""
    orig = _pulse_voices([(0, 0x180), (5, 0x200)])
    ours = _pulse_voices([(0, 0x000), (3, 0x180), (5, 0x200)])
    got = fidelity.pulse_compare(orig, ours, 10)
    assert got["orig_pulse_span"] == got["our_pulse_span"] == 0x80
    assert got["pulse_span"] == 1.0


def test_a_frozen_duty_cycle_has_no_span_at_all():
    got = fidelity.pulse_compare(
        _pulse_voices([(f, 0x800 + f * 0x10) for f in range(10)]),
        _pulse_voices([(0, 0x800)]), 10)
    assert got["pulse_span"] == 0.0


def test_pulse_span_is_none_when_the_original_never_moves_the_width():
    """A ratio needs a denominator. `-` in the column, never a division."""
    got = fidelity.pulse_compare(_pulse_voices([(0, 0x800)]),
                                 _pulse_voices([(f, f * 0x10)
                                                for f in range(5)]), 5)
    assert got["pulse_span"] is None


# --- `pphase`: where in the band a note OPENS -----------------------------
#
# `pul` says whether the duty cycle moves and `pspan` says how far it gets;
# neither says where a note starts. The player's accumulator free-runs and is
# never reseeded, so its notes open all over the sweep, while Goattracker
# reloads the pulse pointer from the instrument and opens every note on the
# record's own width. On 5_Title_Tunes instrument 5 the per-note TRAVEL is
# already 0.83x of the original's -- the right size -- while the original
# opens on 5 buckets and we open on 1. That is a phase error, and until this
# column no dimension could see it.

def _phase_voice(pulse_events, attacks):
    return fidelity.Voice(pulse_events=list(pulse_events),
                          attack_frames=list(attacks),
                          attacks=["C-4"] * len(attacks))


def _phase_voices(*pairs):
    vs = [_phase_voice(p, a) for p, a in pairs]
    return vs + [fidelity.Voice()] * (3 - len(vs))


# A free-running sweep: the width climbs steadily and notes fall all over it.
_FREE = [(f, 0x800 + f * 0x100) for f in range(8)]
# The same band, restarted at every note: each note opens on $800.
_RESET = [(0, 0x800), (1, 0x900), (2, 0x800), (3, 0x900),
          (4, 0x800), (5, 0x900), (6, 0x800), (7, 0x900)]
_ATTACKS = [0, 2, 4, 6]


def test_pphase_sees_a_sweep_that_opens_every_note_on_the_same_width():
    """The defining case, and the one no other pulse column can register."""
    got = fidelity.pulse_compare(_phase_voices((_FREE, _ATTACKS)),
                                 _phase_voices((_RESET, _ATTACKS)), 8)
    assert got["orig_pulse_phases"] == 4, "the original opens on four buckets"
    assert got["our_pulse_phases"] == 1, "we open on one"
    assert got["pulse_phase"] == 0.25


def test_pphase_is_read_one_frame_after_the_attack():
    """Matching instrmap's `at onset`: the note's own instrument load writes
    the width on the attack frame itself, so the frame AFTER it is the first
    the pulse program actually governs. Reading the attack frame would report
    the width the note was triggered with, not the one it plays."""
    pulse = [(0, 0x800), (1, 0xB00)]
    # $B00 // $100 == 11, the frame-after value; the attack frame holds $800,
    # which would bucket to 8.
    assert fidelity._onset_phases(_phase_voice(pulse, [0]),
                                  fidelity.register_timeline(pulse, 4), 4) == {0xB}
    # It reaches the row through pulse_compare's per-voice record. The summed
    # `orig_pulse_phases` is 0 here rather than 1, because one bucket is not a
    # phase to reproduce and the population rule drops the voice -- which is
    # the behaviour the test below pins.
    got = fidelity.pulse_compare(_phase_voices((pulse, [0])),
                                 _phase_voices((pulse, [0])), 4)
    assert got["pulse_voices"][0]["orig_pulse_phases"] == 1
    assert got["orig_pulse_phases"] == 0


def test_pphase_ignores_the_voices_whose_original_never_varies():
    """The population rule. A voice opening every note on one width has no
    phase to reproduce and ours reproduces it exactly, so counting it would
    add a free 1/1 and dilute the voices that sweep -- four of
    5_Title_Tunes' seven instruments are that case."""
    flat = ([(0, 0x800)], _ATTACKS)
    without = fidelity.pulse_compare(_phase_voices((_FREE, _ATTACKS)),
                                     _phase_voices((_RESET, _ATTACKS)), 8)
    with_flat = fidelity.pulse_compare(
        _phase_voices((_FREE, _ATTACKS), flat),
        _phase_voices((_RESET, _ATTACKS), flat), 8)
    assert with_flat["pulse_phase"] == without["pulse_phase"] == 0.25
    # ... and the flat voice is still reported per voice, just not scored.
    assert with_flat["pulse_voices"][1]["orig_pulse_phases"] == 1


def test_pphase_takes_no_startup_lag_correction():
    """`onset`'s rule: each side is read at its OWN attack frames, so the
    packed player's 3-8 frame latency cancels. Shifting our whole side --
    pulse writes and attacks together -- must not move the score, and a
    version that subtracted a lag here would manufacture the very error the
    column exists to detect."""
    base = fidelity.pulse_compare(_phase_voices((_FREE, _ATTACKS)),
                                  _phase_voices((_FREE, _ATTACKS)), 20)
    k = 5
    shifted = _phase_voices(([(f + k, v) for f, v in _FREE],
                             [a + k for a in _ATTACKS]))
    lagged = fidelity.pulse_compare(_phase_voices((_FREE, _ATTACKS)),
                                    shifted, 20)
    assert base["pulse_phase"] == lagged["pulse_phase"] == 1.0


def test_pphase_is_none_when_no_voice_varies_its_onset():
    """A ratio needs a denominator, the same rule `pspan` follows."""
    flat = ([(0, 0x800)], _ATTACKS)
    got = fidelity.pulse_compare(_phase_voices(flat), _phase_voices(flat), 8)
    assert got["pulse_phase"] is None


def test_the_travel_can_be_right_while_the_phase_is_wrong():
    """Why this is a column and not a note on `pspan`. Both sides move the
    width by exactly $100 between the frames each note covers -- identical
    travel, identical span -- and only the opening point differs."""
    got = fidelity.pulse_compare(_phase_voices((_FREE, _ATTACKS)),
                                 _phase_voices((_RESET, _ATTACKS)), 8)
    assert got["pulse_phase"] == 0.25, "the phase collapses"
    assert got["our_pulse_changes"] == got["orig_pulse_changes"] == 7


def test_pspan_is_reported_per_voice_as_well_as_for_the_file():
    """The file-level ratio said 0.47x on 5_Title_Tunes and could not say
    which instrument was at fault -- the gap `gate_census_by_voice` closed
    for the gate, closed here for the pulse."""
    wide = [(f, 0x800 + f * 0x100) for f in range(5)]     # span $400
    narrow = [(f, 0x800 + f * 0x40) for f in range(5)]    # span $100
    got = fidelity.pulse_compare(_pulse_voices(wide, wide),
                                 _pulse_voices(wide, narrow), 5)
    per = got["pulse_voices"]
    assert per[0]["pulse_span"] == 1.0, "voice 1 matches"
    assert per[1]["pulse_span"] == 0.25, "voice 2 is the narrow one"
    assert per[0]["orig_pulse_span"] == 0x400
    assert per[1]["our_pulse_span"] == 0x100
    # and the per-voice spans still sum to the file-level pair
    assert sum(v["our_pulse_span"] for v in per) == got["our_pulse_span"]
    assert sum(v["orig_pulse_span"] for v in per) == got["orig_pulse_span"]


def _filt(cutoff=(), ctrl=(), passband=(), volume=()):
    return fidelity.FilterState(cutoff_events=list(cutoff),
                                ctrl_events=list(ctrl),
                                passband_events=list(passband),
                                volume_events=list(volume))


def test_a_filter_needs_both_a_routed_voice_and_a_passband():
    """$D417's low nibble routes voices in; $D418's bits 4-6 pick which
    output reaches the mixer. A voice routed with the passband Off is not
    filtered, it is inaudible -- so neither half alone counts as filtering."""
    routed_only = _filt(ctrl=[(0, 0xF1)])
    band_only = _filt(passband=[(0, 1)])
    both = _filt(ctrl=[(0, 0xF1)], passband=[(0, 1)])
    n = 10
    assert fidelity.filter_compare(routed_only, routed_only, n)["orig_filtered_frames"] == 0
    assert fidelity.filter_compare(band_only, band_only, n)["orig_filtered_frames"] == 0
    assert fidelity.filter_compare(both, both, n)["orig_filtered_frames"] == 10


def test_resonance_alone_does_not_count_as_routing():
    # $F0 is full resonance with no voice routed: the high nibble of $D417 is
    # not routing, and siddump prints both halves as one byte.
    res = _filt(ctrl=[(0, 0xF0)], passband=[(0, 1)])
    assert fidelity.filter_compare(res, res, 5)["orig_filtered_frames"] == 0


def test_an_invented_filter_is_one_sided():
    """v0.5.72's rejected reader: 497 cutoff writes against an original that
    writes the cutoff once. Nothing on the original's side can disagree with
    that, which is why it is a count and not a percentage."""
    orig = _filt(cutoff=[(0, 0x0800)])
    ours = _filt(cutoff=[(f, 0x400 + f * 8) for f in range(50)],
                 ctrl=[(0, 0xF1)], passband=[(0, 1)])
    got = fidelity.filter_compare(orig, ours, 50)
    assert got["orig_filtered_frames"] == 0 and got["our_filtered_frames"] == 50
    assert got["orig_cutoff_changes"] == 0 and got["our_cutoff_changes"] == 49
    assert got["cutoff_sweep"] is None      # nothing to be a ratio of


def test_the_same_sweep_in_finer_steps_is_the_same_sweep():
    """Why travel exists beside the write count. Both sides run the cutoff
    from $0400 to $0800; ours takes twice as many steps, so it writes twice
    as often and goes exactly as far."""
    orig = _filt(cutoff=[(2 * i, 0x400 + i * 0x80) for i in range(9)])
    ours = _filt(cutoff=[(i, 0x400 + i * 0x40) for i in range(17)])
    got = fidelity.filter_compare(orig, ours, 20)
    assert got["our_cutoff_changes"] == 2 * got["orig_cutoff_changes"]
    assert got["cutoff_sweep"] == 1.0
    assert got["our_cutoff_range"] == got["orig_cutoff_range"] == 0x400


def test_an_overshooting_sweep_shows_up_as_travel_not_as_writes():
    """Deep_Strike's shape: Goattracker's filter table steps for a fixed tick
    count where the player's sweep is bounded by its own counter, so ours
    covers three times the ground in the same number of writes."""
    orig = _filt(cutoff=[(f, 0x400 + f * 0x10) for f in range(10)])
    ours = _filt(cutoff=[(f, 0x400 + f * 0x30) for f in range(10)])
    got = fidelity.filter_compare(orig, ours, 10)
    assert got["our_cutoff_changes"] == got["orig_cutoff_changes"]
    assert got["cutoff_sweep"] == 3.0


def test_a_held_cutoff_travels_nowhere():
    held = _filt(cutoff=[(0, 0x0800)], ctrl=[(0, 0xF1)], passband=[(0, 1)])
    got = fidelity.filter_compare(held, held, 100)
    assert got["our_cutoff_travel"] == 0 and got["our_filtered_frames"] == 100
    assert got["cutoff_sweep"] is None


# --- how the three reach the report ----------------------------------------


def test_the_new_columns_are_in_the_table_and_the_summary():
    rows = [_row("Good.sid", "measured", 1.0, 50, 50)]
    rows[0].update(adsr=0.5, adsr_frames=100,
                   orig_pulse_changes=100, our_pulse_changes=60,
                   orig_filtered_frames=0, our_filtered_frames=40,
                   orig_cutoff_changes=10, our_cutoff_changes=30,
                   orig_cutoff_travel=450, our_cutoff_travel=900,
                   cutoff_sweep=2.0,
                   orig_pulse_span=400, our_pulse_span=300, pulse_span=0.75)
    text = fidelity.report(rows, _Args())
    assert ("| vib | depth | drift | wave | onset | noise | nrun | hold | gate | tail | adsr |"
            in text)
    # adsr | pul | pspan | pphase | filt | cut -- `pphase` sits between the
    # span and the filter, so this fragment moves when it is added and the
    # test is the record that it did.
    assert "| 50% | 60/100 | 0.75x | 1.00x | 40/0 ! | 2.00x |" in text
    assert "mean ADSR agreement: **50%**" in text
    assert "pulse-width changes, ours/original: **60/100**" in text
    assert "filtered frames, ours/original: **40/0**" in text
    assert "1** file(s) filter where the original never does" in text
    # ... and both sides of the two filter columns get a table of their own,
    # because the raw travel figures are two numbers and concern only the
    # files where either side filters at all.
    assert "## Filter: does the cutoff move like the original's?" in text
    assert "| 900/450 |" in text


def test_a_row_without_the_register_metrics_still_renders():
    """Rows predating these columns, and rows that never got as far as a
    trace, must not take the report down with them."""
    bare = _row("Old.sid", "measured", 1.0, 10, 10)
    for key in list(bare):
        if "pulse" in key or "filter" in key or "cutoff" in key or key == "adsr":
            del bare[key]
    text = fidelity.report([bare, _row("Bad.sid", "not converted")], _Args())
    assert "| Old.sid |" in text and "| Bad.sid |" in text
    assert "## Filter:" not in text         # nothing filtered, no section


def test_legalise_restarts_only_touches_out_of_range_positions():
    """greloc.c:244 refuses to pack a song whose restart position is >= the
    track's length, which is exactly what tracks.py emits for a `$FE` byte."""
    blob = bytearray(4 + 32 * 3)
    blob.append(1)                       # one subtune
    for restart in (0xFD, 0x01):         # illegal, then legal
        blob += bytes([3, 0x00, 0x01, 0xFF, restart])
    blob += bytes([2, 0x00, 0xFF, 0x00])  # already legal
    fixed_blob, count = fidelity.legalise_restarts(bytes(blob))
    assert count == 1
    assert fixed_blob[105] == 0x00       # the $FD became 0
    assert fixed_blob[110] == 0x01       # the legal one is untouched


def test_the_commando_fixture_needs_patching_to_pack():
    """The byte-exact reference output carries the illegal restart, so the
    harness patches before packing rather than reporting the file unpackable.
    If this ever fails, the converter itself has been fixed -- see
    SNG2SID-FIDELITY.md and update this test rather than deleting it."""
    _, count = fidelity.legalise_restarts((REPO_ROOT / "Commando.sng").read_bytes())
    assert count == 3


# --- what gt2reloc exports -------------------------------------------------

def _sng(*subtunes):
    """A .sng header carrying `subtunes`, each a triple of orderlist lengths.

    build_sng stores `len(track) - 1` for a track that ends `[..., $FF,
    restart]`, so a voice greloc sees as length n is stored as n+1.
    """
    blob = bytearray(4 + 32 * 3)
    blob.append(len(subtunes))
    for voices in subtunes:
        for n in voices:
            blob.append(n + 1)
            blob += bytes(n) + bytes([0xFF, 0x00])
    return bytes(blob)


def test_song_lengths_reads_greloc_lengths_not_stored_bytes():
    # A voice whose orderlist is only the [$FF, restart] marker is length 0 to
    # greloc (gsong.c:1338-1349), though the .sng stores 1 for it.
    assert fidelity.song_lengths(_sng((4, 0, 2))) == [(4, 0, 2)]


def test_a_subtune_with_an_empty_voice_is_exported_as_a_stub_in_place():
    """greloc.c:653 loops over the original indices, so nothing is renumbered:
    the invalid subtune keeps its slot and is written with songsize 0."""
    exp = fidelity.greloc_export([(1, 1, 0), (2, 2, 2), (3, 3, 3)])
    assert exp["exported"] == 2          # only two subtunes are valid
    assert exp["stub"] == [0]            # index 0 survives as an empty entry
    assert exp["lost"] == [2]            # index 2 >= songs, never written


def test_a_valid_subtune_past_the_exported_count_is_lost_entirely():
    # Two invalid subtunes at the front cost the last two valid ones, which is
    # what happens to Rasputin's subtunes 15 and 16.
    exp = fidelity.greloc_export([(0, 1, 1), (1, 0, 1)] + [(2, 2, 2)] * 4)
    assert exp["exported"] == 4
    assert exp["stub"] == [0, 1]
    assert exp["lost"] == [4, 5]


def test_a_file_with_no_empty_voice_exports_every_subtune():
    exp = fidelity.greloc_export([(1, 1, 1)] * 5)
    assert exp["exported"] == 5
    assert exp["stub"] == [] and exp["lost"] == []


# --- live tools ------------------------------------------------------------
# These need siddump and are the controls for the measurement itself: a file
# against itself must score 1.0, two different tunes near 0.
siddump = os.environ.get("H2G_SIDDUMP", fidelity.SIDDUMP)
needs_siddump = pytest.mark.skipif(not pathlib.Path(siddump).exists(),
                                   reason="siddump not available")


@needs_siddump
def test_a_file_compared_with_itself_is_a_perfect_match(tmp_path):
    sid = REPO_ROOT / "Commando.sid"
    trace = fidelity.run_siddump(sid, 4, 0, siddump)
    assert sum(len(v.attacks) for v in trace) > 0
    got = fidelity.compare(trace, trace)
    assert got["melody"] == 1.0 and got["retrigger_ratio"] == 1.0
    # ... and the same control for the wave metric: siddump plays
    # seconds*50 frames, and a real trace has waveform writes to compare.
    wave = fidelity.wave_compare(trace, trace, nframes=4 * 50)
    assert wave["wave_frames"] > 0
    assert wave["wave"] == 1.0
    assert wave["orig_noise_frames"] == wave["our_noise_frames"]


# --- what a row's status means ---------------------------------------------
# Three ways a row can carry no melody score, and only two of them are the
# converter's fault. Conflating the third with "silent" is what put BMX_Kidz
# -- which matches its original at 95% once the window is long enough to
# reach its first note -- in the bucket labelled "plays something else".


class _Args:
    seconds = 10
    subtune = "auto"
    label = None
    search_subtunes = 3
    register = False
    audio = False


def _row(name, status, melody=None, orig=0, ours=0):
    r = {"file": name, "status": status, "subtune": 0,
         "orig_attacks": orig, "our_attacks": ours, "retrigger_ratio": None,
         "orig_slides": 0, "our_slides": 0, "multiplier": 1,
         "orig_bend": 0, "our_bend": 0, "bend_ratio": None}
    if melody is not None:
        r.update(melody=melody, sequence=melody, pitch_jaccard=melody,
                 retrigger_ratio=1.0, wave=melody, wave_frames=100,
                 orig_noise_frames=0, our_noise_frames=0,
                 adsr=melody, adsr_frames=100,
                 reversal_ratio=1.0, orig_reversals=10, our_reversals=10,
                 orig_oscillation=0.9, our_oscillation=0.9,
                 depth_ratio=1.0, orig_depth=0.05, our_depth=0.05,
                 depth_instruments=2,
                 noise_run_agreement=melody, noise_run_matched=1,
                 noise_run_instruments=1, noise_run_orig_only=0,
                 noise_run_ours_only=0,
                 sound_run_agreement=melody, sound_run_matched=1,
                 sound_run_instruments=1, sound_run_delta=0,
                 release_tail_agreement=melody, release_tail_matched=1,
                 release_tail_instruments=1, release_tail_ours_longer=0,
                 onset_agreement=melody, onset_matched=1,
                 onset_instruments=1, onset_first_matched=1,
                 onset_ours_early=0, onset_ours_late=0,
                 gate=melody, gate_frames=100,
                 gate_ours_ringing=0, gate_ours_silent=0,
                 orig_pulse_changes=0, our_pulse_changes=0,
                 orig_pulse_span=0, our_pulse_span=0,
                 pulse_span=1.0,
                 orig_pulse_phases=0, our_pulse_phases=0,
                 pulse_phase=1.0,
                 orig_ends_at=10.0, ours_ends_at=10.0,
                 length_delta=0.0, length_bounded=False,
                 orig_filtered_frames=0, our_filtered_frames=0,
                 orig_cutoff_changes=0, our_cutoff_changes=0,
                 orig_cutoff_travel=0, our_cutoff_travel=0,
                 cutoff_sweep=1.0, bend_ratio=1.0,
                 # `drift` reports frames per 1000; 0.0 is a real, common
                 # reading (37 corpus files are exact) and None means the fit
                 # had too little matched material, so a synthetic full row
                 # carries the number rather than omitting it.
                 drift_per_1000=0.0, drift_total=0.0, drift_mad=0.0,
                 drift_lag=0.0, drift_span=1000, drift_voices=3)
    return r


def test_a_window_in_which_neither_side_played_is_not_scored():
    # compare() runs before the status is decided, so the row does carry a
    # melody -- 0%, from two empty sequences. The point is that it is not
    # averaged in, not that the number is missing.
    rows = [_row("Good.sid", "measured", 1.0, 50, 50),
            _row("Empty.sid", "window empty", 0.0, 0, 0)]
    text = fidelity.report(rows, _Args())
    # It stays visible in the table...
    assert "| Empty.sid |" in text and "window empty" in text
    # ...but a window with nothing in it must not drag the headline down.
    assert "- measured: **1** of 2" in text
    assert "mean melody similarity: **100%**" in text


def test_a_conversion_that_plays_nothing_is_still_a_defect():
    # The original played; we did not. That is ours, and it is scored 0%.
    rows = [_row("Good.sid", "measured", 1.0, 50, 50),
            _row("Mute.sid", "silent", 0.0, 50, 0)]
    text = fidelity.report(rows, _Args())
    assert "- measured: **2** of 2" in text
    assert "mean melody similarity: **50%**" in text


# --- the multispeed summary names the actual multiplier --------------------
#
# The paragraph used to hardcode "every 2 frames" / "-S2" / "50.125x2 Hz" for
# ANY multiplier > 1, while a few clauses later `-m{traced[0]}` interpolated
# the real rate correctly -- so a multiplier-3 file's own paragraph named -S2
# and -m3 in the same breath (Saboteur_II).


def test_a_multiplier_3_file_is_named_S3_not_the_old_hardcoded_S2():
    row = _row("Saboteur_II.sid", "measured", 1.0, 90, 90)
    row["multiplier"] = 3
    row["traced_calls_per_frame"] = 3
    text = fidelity.report([row], _Args())
    assert "`gt2reloc -S3`" in text
    assert "advances a row every 3 frames" in text
    assert "called 3 times a frame" in text
    assert "50.125x3 Hz" in text
    assert "`-m3`" in text
    # ... and none of the old hardcoded multiplier-2 wording survives (a
    # different section elsewhere in the report uses -S2 as a generic
    # worked example and is not what this guards).
    assert "every 2 frames" not in text
    assert "called twice a frame" not in text


def test_a_multiplier_2_file_still_reads_S2():
    row = _row("Two.sid", "measured", 1.0, 90, 90)
    row["multiplier"] = 2
    row["traced_calls_per_frame"] = 2
    text = fidelity.report([row], _Args())
    assert "`gt2reloc -S2`" in text
    assert "advances a row every 2 frames" in text
    assert "50.125x2 Hz" in text
    assert "`-m2`" in text


def test_a_run_mixing_multipliers_names_each_one_generically():
    two = _row("Two.sid", "measured", 1.0, 50, 50)
    two["multiplier"] = 2
    two["traced_calls_per_frame"] = 2
    three = _row("Three.sid", "measured", 1.0, 50, 50)
    three["multiplier"] = 3
    three["traced_calls_per_frame"] = 3
    text = fidelity.report([two, three], _Args())
    # Both real multipliers are named -- neither is asserted as THE rate.
    assert "-S2" in text and "-S3" in text
    assert "each song its own multiplier" in text
    # The per-file mechanism sentence is generic, not pinned to one number.
    assert "advances a row every `multiplier` frames" in text


# --- the scratch directory -------------------------------------------------
#
# Every file the harness writes has a fixed name -- a.sng, b.sid, o.sid -- so
# two runs sharing a directory overwrite each other between the write and the
# read, and each measures whichever file won the race. Nothing fails; the
# numbers are plausible and about the wrong tune. It has contaminated a real
# A/B in this repo, and this project runs concurrent agents as a matter of
# course, so the default has to be private.


def test_two_runs_never_share_a_scratch_directory():
    a, owned_a = fidelity.make_workdir()
    b, owned_b = fidelity.make_workdir()
    try:
        assert a != b
        assert a.is_dir() and b.is_dir()
        assert owned_a and owned_b
        # The collision is between identically named files, so distinct
        # directories are the whole guarantee.
        (a / "a.sng").write_bytes(b"first")
        (b / "a.sng").write_bytes(b"second")
        assert (a / "a.sng").read_bytes() == b"first"
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def test_a_named_directory_is_used_as_given_and_not_owned(tmp_path):
    """--workdir is the debugging route: it keeps the intermediates, so the
    caller owns them and this script must not delete them."""
    target = tmp_path / "keep" / "me"
    d, owned = fidelity.make_workdir(str(target))
    assert d == target and d.is_dir()
    assert owned is False


def test_the_default_is_unset_so_nothing_inherits_one_path():
    """listen.py takes its default from this constant too. If it named a
    directory, both scripts would default to the same one again."""
    assert fidelity.WORKDIR is None or os.environ.get("H2G_FIDELITY_WORK")


# --- what the run says it compared -----------------------------------------
#
# The repo's standing rule -- a metric that cannot see a change is not
# evidence the change did nothing -- has been applied correctly at least seven
# times and every one of them depended on an author remembering it. These
# tests are what makes it structural: a run states which dimensions it
# computed, and therefore which registers no dimension of it reads.


def test_every_printed_column_has_a_dimension_declaring_its_registers():
    """The registry is only useful if it is complete. A column that exists in
    the table and not in DIMENSIONS is invisible to --baseline, which is the
    exact failure the registry is here to prevent."""
    header = next(line for line in fidelity.report([_row("A.sid", "measured", 1.0)],
                                                   _Args()).splitlines()
                  if line.startswith("| File |"))
    cells = {c.strip() for c in header.split("|")}
    for d in fidelity.DIMENSIONS:
        assert d.column in cells, f"{d.column} is declared but not printed"
    # ... and nothing is printed that no dimension claims, bar the four
    # non-measurements: the file, the two raw attack counts, and the status.
    assert cells - {d.column for d in fidelity.DIMENSIONS} == {
        "", "File", "orig", "ours", "status"}


def test_every_row_has_exactly_as_many_cells_as_the_header():
    """The header is generated and the ROW is hand-built, so the two can
    disagree -- and did. `pphase` was added to DIMENSIONS and to the header,
    the registry test above passed, and every row went out one cell short, so
    the whole table was silently misaligned from `pul` rightwards.

    That is the same shape as the defects CLAUDE.md collects: a guard keyed on
    one half of a pair, green while the other half is wrong. Counting cells
    costs nothing and covers every future column.
    """
    text = fidelity.report([_row("A.sid", "measured", 1.0),
                            _row("B.sid", "measured", 0.5)], _Args())
    lines = text.splitlines()
    i = next(i for i, l in enumerate(lines) if l.startswith("| File |"))

    def cells(line):
        return len(line.strip().strip("|").split("|"))

    want = cells(lines[i])
    assert cells(lines[i + 1]) == want, "the separator row is a different width"
    rows = [l for l in lines[i + 2:] if l.startswith("| A.sid") or l.startswith("| B.sid")]
    assert rows, "no data rows were rendered"
    for r in rows:
        assert cells(r) == want, f"{cells(r)} cells against {want}: {r}"


# --- `len`: the listener's rule, and the only column about LENGTH ---------
#
# "The original and the H2G should have the same length +- 5 seconds."  No
# other dimension enforces it: `drift`, `retrig` and `--pace` all measure the
# rate of a ROW and are satisfied by a conversion that plays the right music
# at the right speed FOREVER. Action Biker reads drift +0.0 and retrig 1.00
# while running three times too long.

def _len_voice(attacks):
    return fidelity.Voice(attack_frames=list(attacks),
                          attacks=["C-4"] * len(attacks))


def _len_side(attacks):
    return [_len_voice(attacks), fidelity.Voice(), fidelity.Voice()]


def test_a_side_still_playing_at_the_window_edge_has_not_stopped():
    # attacks every 50 frames right up to the end: no trailing silence at all
    assert fidelity.stopped_at(_len_side(range(0, 3000, 50)), 60) is None


def test_a_side_that_stops_reports_the_second_it_stopped():
    # last attack at frame 500 = 10 s, then 50 s of silence
    assert fidelity.stopped_at(_len_side(range(0, 501, 50)), 60) == 10.0


def test_a_long_rest_is_not_an_ending_for_either_side():
    """The same rule `original_ended` uses, and for the same reason: a tune
    that pauses mid-way must not be read as over. The trailing silence has to
    beat twice the tune's own largest gap."""
    # a 20 s gap mid-tune, then it resumes and runs to the edge
    attacks = list(range(0, 501, 50)) + list(range(1500, 3000, 50))
    assert fidelity.stopped_at(_len_side(attacks), 60) is None


def test_len_is_the_seconds_ours_runs_past_the_originals_ending():
    orig = _len_side(range(0, 501, 50))            # stops at 10 s
    ours = _len_side(range(0, 1501, 50))           # stops at 30 s
    got = fidelity.length_compare(orig, ours, 60)
    assert got["orig_ends_at"] == 10.0
    assert got["ours_ends_at"] == 30.0
    assert got["length_delta"] == 20.0
    assert got["length_bounded"] is False


def test_len_says_nothing_when_the_original_never_ends():
    """No ending to match means the rule does not apply -- not that it passed."""
    orig = _len_side(range(0, 3000, 50))
    ours = _len_side(range(0, 501, 50))
    assert fidelity.length_compare(orig, ours, 60) == {}


def test_a_conversion_that_never_stops_reports_a_floor_not_a_pass():
    """Ours loops, so where it has not stopped by the window edge all we know
    is a lower bound. It must be reported as a bound and not as a figure."""
    orig = _len_side(range(0, 501, 50))            # stops at 10 s
    ours = _len_side(range(0, 3000, 50))           # never stops
    got = fidelity.length_compare(orig, ours, 60)
    assert got["ours_ends_at"] is None
    assert got["length_bounded"] is True
    assert got["length_delta"] == 50.0             # 60 - 10, a floor
    assert fidelity._fmt_length(got).startswith(">"), "the floor is not marked"
    assert fidelity._fmt_length(got).endswith("!"), "a 50 s surplus is a breach"


def test_action_bikers_case_reports_nothing_rather_than_a_pass():
    """THE case that forces the design. Its original's last attack is at
    59.54 s and the report's window is 60 s, so the surplus is entirely
    OUTSIDE the window and cannot be seen. Scoring that as a pass would be
    exactly the shim this column exists to expose."""
    orig = _len_side([int(59.54 * 50)])
    ours = _len_side(range(0, 3000, 50))
    got = fidelity.length_compare(orig, ours, 60)
    # the original does not even count as stopped -- its tail is under 5 s
    assert got == {} or got["length_delta"] is None
    assert fidelity._fmt_length(got) == "-"


def test_a_conversion_inside_the_tolerance_is_not_flagged():
    orig = _len_side(range(0, 501, 50))            # 10 s
    ours = _len_side(range(0, 651, 50))            # 13 s, +3
    got = fidelity.length_compare(orig, ours, 60)
    assert got["length_delta"] == 3.0
    assert "!" not in fidelity._fmt_length(got)


def test_length_rule_failures_excludes_a_shortened_window_that_passes():
    """The defect this pins: `original_ends` marks every row whose WINDOW was
    shortened, which is a different question from whether the rule was
    BROKEN. Geoff Capes and Kings of the Beach ingame are exactly this case
    -- shortened windows, deltas of +0.16s and +0.92s, nowhere near
    LENGTH_TOLERANCE -- and the old summary bullet counted rows by
    `original_ends` alone, so it named both as FAILing the length rule
    despite `len` reading well inside tolerance for each."""
    passing = [
        {"file": "Geoff_Capes_Strongman_Challenge.sid", "original_ends": 17,
         "length_delta": 0.16, "length_bounded": False},
        {"file": "Kings_of_the_Beach_ingame.sid", "original_ends": 8,
         "length_delta": 0.92, "length_bounded": False},
    ]
    assert fidelity.length_rule_failures(passing) == []


def test_length_rule_failures_names_a_row_that_actually_breaches_tolerance():
    failing = [
        {"file": "Geoff_Capes_Strongman_Challenge.sid", "original_ends": 17,
         "length_delta": 0.16, "length_bounded": False},
        {"file": "Some_Runaway_Loop.sid", "original_ends": 20,
         "length_delta": 12.3, "length_bounded": False},
    ]
    got = fidelity.length_rule_failures(failing)
    assert [r["file"] for r in got] == ["Some_Runaway_Loop.sid"]


def test_summary_bullet_does_not_name_a_passing_shortened_row_as_a_failure():
    """Same claim as the two tests above, read off the actual report text --
    the shape a reader of FIDELITY.md sees."""
    rows = [_row("Geoff_Capes_Strongman_Challenge.sid", "measured", 1.0)]
    rows[0].update(original_ends=17, length_delta=0.16, length_bounded=False)
    rows.append(_row("Kings_of_the_Beach_ingame.sid", "measured", 1.0))
    rows[-1].update(original_ends=8, length_delta=0.92, length_bounded=False)
    text = fidelity.report(rows, _Args())
    assert "FAIL the length rule" not in text
    assert "window shortened" in text or "WINDOW shortened" in text


def test_summary_bullet_names_a_row_that_breaches_the_length_tolerance():
    rows = [_row("Geoff_Capes_Strongman_Challenge.sid", "measured", 1.0)]
    rows[0].update(original_ends=17, length_delta=0.16, length_bounded=False)
    rows.append(_row("Runaway.sid", "measured", 1.0))
    rows[-1].update(original_ends=20, length_delta=12.3, length_bounded=False)
    text = fidelity.report(rows, _Args())
    assert "1 file(s) FAIL the length rule" in text
    assert "Runaway +12.3s" in text
    assert "Geoff_Capes_Strongman_Challenge +" not in text


def test_an_unmeasured_row_is_as_wide_as_a_measured_one():
    """The `not converted` rows go through a different branch that fills the
    table with dashes, and its count was HARDCODED at 21 against a header
    wanting 23 -- so all twelve of them had been two cells short in every
    generated report, and adding a column widened the gap rather than causing
    it. Deriving the count from the header is the fix; this is the test that
    keeps it derived."""
    text = fidelity.report([_row("Fine.sid", "measured", 1.0),
                            {"file": "Broken.sid", "status": "not converted"}],
                           _Args())
    lines = text.splitlines()
    i = next(i for i, l in enumerate(lines) if l.startswith("| File |"))

    def cells(line):
        return len(line.strip().strip("|").split("|"))

    want = cells(lines[i])
    broken = next(l for l in lines if l.startswith("| Broken.sid"))
    assert cells(broken) == want, f"{cells(broken)} against {want}: {broken}"
    assert broken.rstrip().endswith("not converted |")


def test_a_row_records_only_the_dimensions_it_actually_compared():
    full = _row("A.sid", "measured", 0.5)
    assert fidelity.dimensions_present(full) == [d.key for d in fidelity.DIMENSIONS]
    # A file whose voices never select a waveform has no wave score, and a row
    # claiming one it did not compute is the misreading in miniature.
    no_wave = dict(full, wave=None)
    assert "wave" not in fidelity.dimensions_present(no_wave)
    assert "melody" in fidelity.dimensions_present(no_wave)
    # A file that would not convert compared nothing at all: its row carries
    # none of the metric keys, as _measure's first exit leaves it.
    assert fidelity.dimensions_present(
        {"file": "B.sid", "status": "not converted"}) == []


def test_the_registers_no_dimension_reads_are_named():
    """Since v0.5.78 every SID register is read by some dimension: $D402/$D403
    by `pul`, $D405/$D406 by `adsr`, $D415/$D416 by `cut`, $D417 and $D418 by
    `filt`. Those were the five where v0.5.71's envelope, v0.5.72's filter and
    v0.5.73's pulse width landed unseen, which is what the columns were built
    from. Register coverage is not total coverage -- NOT_MEASURED carries what
    is left, including the volume nibble of a register `filt` reads."""
    assert fidelity.registers_unread({d.key for d in fidelity.DIMENSIONS}) == []
    assert any("master volume" in item for item in fidelity.NOT_MEASURED)
    # Losing a dimension re-opens exactly its own registers rather than
    # leaving the account fixed: a run that scored no notes cannot claim to
    # have compared pitch, and one that scored no envelope is blind to
    # $D405/$D406 again. ($D404 stays read either way -- the attack metrics
    # need its gate bit as an edge, which is why note *length* is in
    # NOT_MEASURED rather than here.)
    assert "$D400/$D401" in dict(fidelity.registers_unread({"wave", "noise"}))
    # `adsr` and `tail` both read the envelope pair -- one while the note
    # plays, one after it ends -- so dropping either alone leaves it read.
    assert "$D405/$D406" in dict(fidelity.registers_unread(
        {d.key for d in fidelity.DIMENSIONS
         if d.key not in ("adsr", "release_tail_agreement")}))
    assert len(fidelity.registers_unread(set())) == len(fidelity.SID_REGISTERS)


def test_the_report_states_its_own_reach():
    text = fidelity.report([_row("A.sid", "measured", 1.0, 50, 50)], _Args())
    assert "## What this run compared" in text
    assert "$D405/$D406" in text and "$D415/$D416" in text
    assert "note length" in text


# --- sweeping an option without a hand-picked column list -------------------
#
# Twice a per-song/per-instrument comparison shipped a conclusion read from a
# SUBSET of the scored columns and had to be retracted: v0.5.352/353 read six
# of fourteen keys via `dict.get` and silently skipped the rest, and a
# firstwave sweep on 5_Title_Tunes recommended a combination while never
# printing `pitch`, which fell 1.0000 -> 0.9836 on exactly that combination.
# `sweep_report` cannot repeat that mistake because it does not know the
# column list -- it reads `DIMENSIONS` at call time.


def test_sweep_report_prints_every_declared_dimension():
    text = fidelity.sweep_report([_row("firstwave=0x09", "measured", 1.0),
                                   _row("firstwave=0x00", "measured", 0.5)])
    header = text.splitlines()[0]
    cells = {c.strip() for c in header.split("|")}
    for d in fidelity.DIMENSIONS:
        assert d.column in cells, f"{d.column} is scored but not printed"
    # And every arm actually appears as its own row, not folded away.
    assert "firstwave=0x09" in text and "firstwave=0x00" in text


def test_sweep_report_prints_a_dimension_added_after_this_function_was_written(
        monkeypatch):
    """The regression this whole task is about: a helper that names its own
    columns can go stale the moment a new Dimension is added elsewhere and
    nobody remembers to update the printer. Prove `sweep_report` cannot go
    stale that way -- add a brand-new Dimension the function has never heard
    of, feed it a row carrying that key, and confirm it shows up unasked."""
    fake = fidelity.Dimension("_test_only_marker", "zzmarker",
                               ("$D400/$D401",), "fraction", "test fixture only")
    monkeypatch.setattr(fidelity, "DIMENSIONS", fidelity.DIMENSIONS + (fake,))
    row = _row("arm-A", "measured", 1.0)
    row["_test_only_marker"] = 0.75
    text = fidelity.sweep_report([row])
    header = text.splitlines()[0]
    assert "zzmarker" in {c.strip() for c in header.split("|")}
    assert fidelity._fmt_pct(0.75) in text


def test_sweep_option_calls_measure_once_per_value_and_reports_them_all(
        monkeypatch):
    seen_opts = []

    def fake_measure(sid, workdir, opts, args, multiplier=1):
        seen_opts.append(dict(opts))
        # firstwave 0x00 is the arm the retracted probe would have shipped;
        # its pitch is the column that would have caught it.
        pitch = 0.9836 if opts["firstwave"] == 0x00 else 1.0
        row = _row(f"firstwave={opts['firstwave']:#x}", "measured", 1.0)
        row["pitch_jaccard"] = pitch
        return row

    monkeypatch.setattr(fidelity, "measure", fake_measure)
    text = fidelity.sweep_option(pathlib.Path("Fake.sid"), pathlib.Path("."),
                                 _Args(), "firstwave", [0x09, 0x00],
                                 base_opts={"filters": True})

    # measure() saw both arms, with the fixed option carried through.
    assert [o["firstwave"] for o in seen_opts] == [0x09, 0x00]
    assert all(o["filters"] is True for o in seen_opts)
    # And the report is not a hand-picked subset: `pitch` -- the very column
    # the real firstwave sweep omitted -- is visible and shows the drop.
    header = text.splitlines()[0]
    assert "pitch" in {c.strip() for c in header.split("|")}
    assert "98%" in text and "100%" in text


# --- A/B against a previous run --------------------------------------------


def _ab(name, sha="aaa", **kw):
    r = {"file": name, "status": "measured", "seconds": 10, "subtune": 0,
         "options": {"filters": True}, "multiplier": 1, "output_sha": sha,
         "melody": 0.80, "sequence": 0.80, "pitch_jaccard": 0.80,
         "retrigger_ratio": 1.0, "our_slides": 5, "wave": 0.60,
         "our_noise_frames": 0}
    r.update(kw)
    r["dimensions"] = fidelity.dimensions_present(r)
    return r


def test_an_invisible_change_is_printed_as_a_result():
    """The whole point. The converter's output changed and no dimension
    moved, which is a finding -- not the flat table that has been read as a
    null result more often than anything else in this project."""
    text, code = fidelity.compare_runs([_ab("A.sid", "old")], [_ab("A.sid", "new")])
    assert code == 0
    assert "No dimension this report measures can see this change" in text
    # ... and it says where the change can have gone instead.
    assert "$D405/$D406" in text and "$D402/$D403" in text


def test_subtune_content_shas_matches_songview_reachable_patterns():
    """The independence property that makes this worth having: derived from
    the .sng bytes directly, cross-checked against songview's own reader
    rather than sharing code with it."""
    import songview
    from h2g.convert import convert as _convert

    sng = _convert(str(REPO_ROOT / "Commando.sid"), log=lambda m: None)
    shas = fidelity.subtune_content_shas(sng)
    song = songview.parse_sng(sng)
    assert shas is not None
    assert len(shas) == song.subtunes
    # Determinism: the same bytes must always hash the same way.
    assert shas == fidelity.subtune_content_shas(sng)


def test_subtune_content_shas_returns_none_on_a_malformed_blob():
    assert fidelity.subtune_content_shas(b"") is None
    assert fidelity.subtune_content_shas(b"GTS5" + b"\x00" * 4) is None


def test_a_change_outside_the_traced_subtune_is_named_not_hidden():
    """The Star_Paws regression this exists to catch: bytes moved in a
    subtune '--baseline' never traced, and the old verdict read as though
    nothing useful could be said about it."""
    old = _ab("A.sid", "old", subtune=0,
              subtune_shas=["aaa", "bbb", "ccc"])
    new = _ab("A.sid", "new", subtune=0,
              subtune_shas=["aaa", "bbb", "DIFFERENT"])
    text, code = fidelity.compare_runs([old], [new])
    assert code == 0
    assert "No dimension this report measures can see this change" in text
    assert "subtune(s) 2 differ" in text
    assert "**NOT** the traced subtune (0)" in text


def test_a_change_inside_the_traced_subtune_says_so_plainly():
    old = _ab("A.sid", "old", subtune=1,
              subtune_shas=["aaa", "bbb"])
    new = _ab("A.sid", "new", subtune=1,
              subtune_shas=["aaa", "DIFFERENT"])
    text, _ = fidelity.compare_runs([old], [new])
    assert "INCLUDING the traced one (1)" in text


def test_a_baseline_without_subtune_shas_falls_back_rather_than_guesses():
    """A row from before this field existed must not be read as 'nothing in
    any subtune changed' -- that would be worse than the old message."""
    old = _ab("A.sid", "old", subtune=0)  # _ab does not set subtune_shas
    assert "subtune_shas" not in old
    new = _ab("A.sid", "new", subtune=0, subtune_shas=["aaa"])
    text, _ = fidelity.compare_runs([old], [new])
    assert "per-subtune diff unavailable" in text


def test_an_inert_change_is_told_apart_from_an_invisible_one():
    """Two readings of one flat table, and this repo has shipped the second
    believing the first twice. Identical bytes mean the change reached
    nothing; changed bytes mean it reached the output and was not measured."""
    text, code = fidelity.compare_runs([_ab("A.sid", "same")], [_ab("A.sid", "same")])
    assert code == 0
    assert "This change reaches nothing" in text
    assert "No dimension this report measures can see" not in text


def test_a_baseline_without_hashes_refuses_to_guess_which_it_was():
    old = _ab("A.sid")
    del old["output_sha"]
    text, code = fidelity.compare_runs([old], [_ab("A.sid", "new")])
    assert "cannot say whether" in text
    assert "reaches nothing" not in text


def test_movement_below_the_printed_precision_is_not_silence():
    """A report that prints 50% either way looks like a no-op to a reader
    diffing two tables. The raw values moved, and the mode says so."""
    text, code = fidelity.compare_runs(
        [_ab("A.sid", "old", melody=0.5000)],
        [_ab("A.sid", "new", melody=0.5004)])
    assert code == 0
    assert "below the precision the report prints" in text
    assert "50% -> 50% !" in text          # marked as invisible in the table


def test_a_baseline_traced_at_other_settings_is_refused():
    """A 10 s run against a 20 s one is two statements about different music.
    Nothing about the delta between them is meaningful."""
    text, code = fidelity.compare_runs([_ab("A.sid", seconds=10)],
                                       [_ab("A.sid", "new", seconds=20)])
    assert code == 2
    assert "## Refused" in text and "seconds 10 -> 20" in text
    # A different subtune is the same class of mismatch.
    _, code2 = fidelity.compare_runs([_ab("A.sid", subtune=0)],
                                     [_ab("A.sid", "new", subtune=3)])
    assert code2 == 2


def test_a_baseline_missing_a_field_is_old_rather_than_incomparable():
    """Refusing every saved run the first time a field is added would make
    the mode useless exactly when a baseline is most valuable."""
    old = _ab("A.sid", "old")
    del old["seconds"]
    _, code = fidelity.compare_runs([old], [_ab("A.sid", "new")])
    assert code == 0


def test_an_option_difference_is_named_as_the_change_under_test():
    """FIDELITY-TOOL-IMPROVEMENTS.md §4 asks for a hard failure on any
    settings difference. Conversion options are the deliberate exception: an
    option A/B is what the mode is mostly for, and naming the difference
    answers the hazard that refusing it would have answered."""
    base = _ab("A.sid", "old")
    base["options"] = dict(base["options"], filters=False)
    text, code = fidelity.compare_runs([base], [_ab("A.sid", "new")])
    assert code == 0
    assert "`filters` False -> True on 1 file(s)" in text


def test_identical_bytes_that_measure_differently_are_the_harness_moving():
    text, _ = fidelity.compare_runs([_ab("A.sid", "same", melody=0.80)],
                                    [_ab("A.sid", "same", melody=0.60)])
    assert "convert to identical bytes and still moved" in text


def test_a_partly_blind_change_says_how_many_files_it_could_not_see():
    """The case that actually occurs. Reporting only the file that moved
    reproduces the misreading at a smaller scale: two files could not be
    seen at all."""
    base = [_ab("A.sid", "old"), _ab("B.sid", "old"), _ab("C.sid", "old")]
    new = [_ab("A.sid", "new", melody=0.90), _ab("B.sid", "new"),
           _ab("C.sid", "new")]
    text, code = fidelity.compare_runs(base, new)
    assert code == 0
    assert "2 of the 3 file(s) whose converted output changed moved no number" in text


def test_a_file_that_stops_converting_is_movement():
    """A change that costs three files their conversion must not read as
    quiet just because a row with no numbers has no numbers to move."""
    gone = {"file": "A.sid", "status": "not converted", "seconds": 10,
            "subtune": 0, "options": {}, "multiplier": 1, "dimensions": []}
    text, code = fidelity.compare_runs([_ab("A.sid", "old")], [gone])
    assert code == 0
    assert "## Status changes" in text
    assert "reaches nothing" not in text


def test_files_present_in_only_one_run_are_reported():
    text, _ = fidelity.compare_runs([_ab("A.sid", "old"), _ab("Gone.sid", "old")],
                                    [_ab("A.sid", "old"), _ab("New.sid", "old")])
    assert "only in the current run (1): New.sid" in text
    assert "only in the baseline (1): Gone.sid" in text


# --- provenance ------------------------------------------------------------


def test_the_label_names_the_commit_the_measurement_was_taken_from():
    """--label was free text and optional, so a run could not say which tree
    it came from. Several commits share one version during a branch's life,
    and a dirty tree shares its version with the commit it is not."""
    got = fidelity.git_label()
    head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short",
                           "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip("not a git checkout")
    assert got.split("-dirty")[0] == head.stdout.strip()
    assert got in (head.stdout.strip(), head.stdout.strip() + "-dirty")


def test_a_run_is_labelled_or_unlabelled_but_never_mislabelled(monkeypatch):
    """git not answering is not a reason to fail a measurement, and it is
    also not a reason to invent a provenance for one."""
    def boom(*a, **kw):
        raise OSError("no git here")
    monkeypatch.setattr(fidelity.subprocess, "run", boom)
    assert fidelity.git_label() is None


# --- bend: the half of a pitch question a count cannot answer ---------------
#
# `slides` counts frames on which the frequency moved. Two conversions that
# bend the same note over the same frames score identically there whether each
# step is the player's or ten times it -- which is exactly the reading that had
# to be settled when v0.5.83 corrected the slide dialect's byte order.

def test_bend_sums_the_magnitudes_siddump_printed():
    v = fidelity.Voice()
    v.bend = 20
    assert fidelity._bend_travel(v) == 20


def test_bend_is_parsed_from_the_bend_lines_not_the_frequency_column():
    # Two frames of movement and one note change. Differencing the frequency
    # column would score the note change too; taking siddump's own `(+ xxxx)`
    # cannot, because it does not print one there.
    dump = chr(10).join([
        "|     0 | 1000  C-4 41  41 0000 800 | ....  ... ..  .. .... ... "
        "| ....  ... ..  .. .... ... | .... .. ... . |",
        "|     1 | 100A (+ 000A) .. .... ... | ....  ... ..  .. .... ... "
        "| ....  ... ..  .. .... ... | .... .. ... . |",
        "|     2 | 1014 (+ 000A) .. .... ... | ....  ... ..  .. .... ... "
        "| ....  ... ..  .. .... ... | .... .. ... . |",
        "|     3 | 2000  G-5 41  41 .... ... | ....  ... ..  .. .... ... "
        "| ....  ... ..  .. .... ... | .... .. ... . |",
    ])
    got = fidelity.parse_dump(dump)
    voices = got[0] if isinstance(got, tuple) else got
    assert fidelity._bend_travel(voices[0]) == 20, "the two bends, not the jump"
    assert voices[0].slides == 2


def test_a_held_note_contributes_no_travel():
    v = fidelity.Voice()
    assert fidelity._bend_travel(v) == 0


def test_bend_sees_a_step_size_change_that_slides_cannot():
    # Same frames moved on both sides, ten times the distance. `slides` is
    # equal; `bend` is 10x. This is the case the dimension exists for.
    def voice(step):
        v = fidelity.Voice()
        v.slides = 4
        v.bend = 4 * step
        return v
    orig = [voice(10), fidelity.Voice(), fidelity.Voice()]
    ours = [voice(100), fidelity.Voice(), fidelity.Voice()]
    out = fidelity.compare(orig, ours)
    assert out["our_slides"] == out["orig_slides"]
    assert out["bend_ratio"] == 10.0


def test_a_tie_is_not_a_bend():
    # A tie is a note change the player did not re-gate, and siddump prints it
    # in its own form -- so it never reaches the bend total.
    dump = ("|     0 | 1000 (C-4 41) .. .... ... | ....  ... ..  .. .... ... "
            "| ....  ... ..  .. .... ... | .... .. ... . |")
    got = fidelity.parse_dump(dump)
    voices = got[0] if isinstance(got, tuple) else got
    assert voices[0].ties == 1 and fidelity._bend_travel(voices[0]) == 0


# --- --vice: shared silence must not inflate the score ----------------------

def test_shared_silence_leaves_both_numerator_and_denominator():
    """The graded form of `wave_compare`'s "skip frames silent in both".

    v0.5.131 dropped a frame only when both whole histograms were silent, so
    a frame in which one side flickered for a few rasterlines -- both sides
    silent at the boundary -- was scored as a *full agreement* instead of
    being dropped. That is the inflation the original rule exists to prevent;
    it lifted Bangkok_Knights from 2.3% to 14.8% and was most of what was
    first attributed to the finer trace.
    """
    from collections import Counter
    # both sides silent all frame: nothing to compare
    num, w = fidelity._graded_agreement(
        Counter({0: 312}), Counter({0: 312}), 0, 0, "overlap")
    assert (num, w) == (0.0, 0.0)

    # one side flickers for 12 lines; 300 lines of silence are shared and must
    # not be credited. The frame is worth 12/312 of a frame, agreeing on none.
    num, w = fidelity._graded_agreement(
        Counter({0: 300, 0x40: 12}), Counter({0: 312}), 0, 0, "overlap")
    assert w == pytest.approx(12 / 312)
    assert num == pytest.approx(0.0)

    # a genuinely shared waveform still scores its share
    num, w = fidelity._graded_agreement(
        Counter({0x40: 312}), Counter({0x40: 200, 0x10: 112}), 0x40, 0x10,
        "overlap")
    assert w == pytest.approx(1.0)
    assert num == pytest.approx(200 / 312)


def test_the_non_graded_rules_reproduce_siddumps_own_arithmetic():
    """`--vice-reduce last` must equal siddump's rule on the same values.

    This is what makes the trace resolution and the reduction rule separable:
    run the finer trace under the coarser rule and the difference is the
    resolution alone. Without it the two effects were reported as one.
    """
    from collections import Counter
    # both silent at the boundary -> dropped, whatever happened mid-frame
    assert fidelity._graded_agreement(
        Counter({0: 300, 0x40: 12}), Counter({0: 312}), 0, 0, "last") == (0.0, 0.0)
    # differing at the boundary -> counted, scored 0
    assert fidelity._graded_agreement(
        Counter({0x40: 312}), Counter({0x10: 312}), 0x40, 0x10,
        "last") == (0.0, 1.0)


# --- v0.5.200: the release nibble the player never lets you hear -------------

def test_a_release_tail_is_read_on_the_gate_off_frame():
    """v0.5.200 took the minimum over the whole gap and that was the bug.

    A minimum cannot depend on which frame the player writes on -- but it also
    cannot tell this note's cut from the *next note's* preparation. On Commando,
    records 3 and 4 hold their release for two frames and then see a zero that
    belongs to the following note; records 1, 7 and 12 never zero in the gap at
    all yet reach 0 somewhere later in it. So the gap reduction scored all seven
    instruments as cut, the writer zeroed all seven releases, and the drums lost
    their tails. Widening a window is not automatically the safer reduction.
    """
    # Three notes so the middle one is bounded. Its release is $F on the
    # gate-off frame and only drops to 0 two frames later -- the next note's
    # setup, which this must not read.
    wf = [(0, 0x41), (3, 0x40), (6, 0x41), (9, 0x40), (12, 0x41), (15, 0x40)]
    adsr = [(0, 0x295F), (11, 0x2950), (12, 0x295F)]
    v = fidelity.Voice(freq_events=[(0, 0x1000)], wf_events=wf,
                       adsr_events=adsr, pulse_events=[],
                       attack_frames=[0, 6, 12])
    assert fidelity.release_tails([v], 20) == {0x2950: {0xF: 1}}
    # ...and a genuine cut, written on the gate-off frame, reads as one
    cut = [(0, 0x295F), (9, 0x2950)]
    v2 = fidelity.Voice(freq_events=[(0, 0x1000)], wf_events=wf,
                        adsr_events=cut, pulse_events=[],
                        attack_frames=[0, 6, 12])
    assert fidelity.release_tails([v2], 20) == {0x2950: {0x0: 1}}


def test_the_key_masks_out_the_release_it_measures():
    """The first version keyed on the whole ADSR pair, so emitting a zero
    release moved every one of our keys from $295F to $2950, nothing was shared
    with the original, and the column reported "nothing to compare" for exactly
    the change it exists to measure."""
    a = fidelity.release_tails([_tail_voice(0x0)], 20)
    b = fidelity.release_tails([_tail_voice(0xF)], 20)
    assert set(a) == set(b), "the instrument must be the same key either side"
    assert fidelity.release_tail_agreement(
        [_tail_voice(0x0)], [_tail_voice(0xF)], 20)[
            "release_tail_agreement"] == 0.0
    assert fidelity.release_tail_agreement(
        [_tail_voice(0x0)], [_tail_voice(0x0)], 20)[
            "release_tail_agreement"] == 1.0


def _tail_voice(release, pair=0x2950):
    """Three notes so the middle one is bounded, with a constant ADSR."""
    p = pair | release
    return fidelity.Voice(
        freq_events=[(0, 0x1000)],
        wf_events=[(0, 0x41), (3, 0x40), (6, 0x41), (9, 0x40),
                   (12, 0x41), (15, 0x40)],
        adsr_events=[(0, p)], pulse_events=[], attack_frames=[0, 6, 12])


def test_a_run_or_a_gap_touching_the_window_edge_is_dropped():
    """Same rule as noise_runs: a length or a gap cut by the window is a fact
    about the window."""
    v = fidelity.Voice(freq_events=[(0, 0x1000)],
                       wf_events=[(0, 0x41), (3, 0x40)],
                       adsr_events=[(0, 0x295F)], pulse_events=[],
                       attack_frames=[0])
    assert fidelity.release_tails([v], 12) == {}, "opens at frame 0"


def test_an_instrument_only_one_side_plays_is_absent_not_wrong():
    got = fidelity.release_tail_agreement(
        [_tail_voice(0x0, 0x2950)], [_tail_voice(0x0, 0x1230)], 20)
    assert got["release_tail_instruments"] == 0
    assert got["release_tail_agreement"] is None


def _oscillating_voice(note_len, half, nnotes=40, adsr=0x0F00,
                       amp_per_half=0x40, base=0x2000):
    """`nnotes` notes of `note_len` frames, each a triangle of half-period
    `half`. The true reversal count per note is `floor(note_len / half) - 1`.
    """
    vals, atk = [], []
    for i in range(nnotes):
        atk.append(i * note_len)
        for f in range(note_len):
            phase, pos = (f // half) % 2, f % half
            step = amp_per_half / half
            vals.append(base + round(step * (pos if phase == 0 else half - pos)))
    v = fidelity.Voice()
    v.attack_frames = atk
    v.freq_events = [(f, vals[f]) for f in range(len(vals))]
    v.adsr_events = [(0, adsr)]
    return v, len(vals)


def _reversals(note_len, half):
    v, n = _oscillating_voice(note_len, half)
    return fidelity.reversals_by_instrument([v], n).get(0x0F00, 0)


def test_reversal_counting_is_exact_on_long_notes():
    """The counter itself is sound: against a synthetic triangle whose reversal
    count is known, one long note reads the true count at every rate."""
    v, n = _oscillating_voice(600, 4, nnotes=1)
    got = fidelity.reversals_by_instrument([v], n)[0x0F00]
    assert got == (600 // 4) - 1


def test_reversal_counting_is_amplitude_independent():
    """Down to a single frequency unit of excursion -- so a `vib` move is never
    an amplitude artefact."""
    counts = {amp: fidelity.reversals_by_instrument(
        [_oscillating_voice(600, 4, nnotes=1, amp_per_half=amp)[0]], 600)[0x0F00]
        for amp in (1, 2, 4, 0x40, 0x400)}
    assert len(set(counts.values())) == 1, counts


def test_reversal_step_function():
    """**`vib` is a STEP function of the rate on short notes, not proportional.**

    Reversals per note are `floor(L / p) - 1`, so a rate change registers only
    where it carries the note across a whole half-cycle boundary. This is why
    One_on_One_Jordan_vs_Bird read x2.057 at ebc9d1a for entries that each move
    by at most x1.333 -- see the `vib` Dimension's comment. If this test starts
    failing, the counter changed and every `vib` figure ever published moved
    with it.
    """
    # a x1.333 rate change (half-period 4 -> 3), at several note lengths
    assert _reversals(600, 3) / _reversals(600, 4) == pytest.approx(1.336, abs=0.01)
    assert _reversals(64, 3) / _reversals(64, 4) == pytest.approx(1.333, abs=0.01)
    # short notes: the same rate change reads far larger
    assert _reversals(10, 3) / _reversals(10, 4) > 1.9
    assert _reversals(12, 3) / _reversals(12, 4) > 1.4
    # and the attack skip is NOT the cause -- the effect survives it, which is
    # what refutes the {a-1, a, a+1} dead-band hypothesis
    assert _reversals(600, 4) > 0


# --- depth: the OTHER half of the vibrato question --------------------------
#
# `vib` counts pitch reversals, i.e. the rate. The corpus defect it cannot see
# is a swing that reverses at the right moments and travels a third of the
# distance -- ACE_II reads `vib` 1.09x with its lead swinging 1.5% of pitch
# against the original's 5.6%. Same shape as `slides`/`bend` and `filt`/`cut`:
# prefer a travel measure whenever the change is to a step *size*.


def _osc(n_cycles, amp, half=4, base=0x1000, drift=0):
    """A triangle of known peak-to-peak `amp`, optionally sliding under it."""
    out, up, cur = [], True, float(base)
    step = amp / half
    for _ in range(2 * n_cycles + 2):
        for _ in range(half):
            cur += (step if up else -step) + drift / (2 * half)
            out.append(int(round(cur)))
        up = not up
    return out


def test_a_swing_is_measured_at_its_real_peak_to_peak():
    swings = fidelity.vibrato_swings(_osc(4, 400))
    assert swings, "a four-cycle triangle must yield readings"
    for swing, centre in swings:
        assert abs(swing - 400) <= 2, swing
        assert 0x0E00 < centre < 0x1200


def test_a_slide_under_the_vibrato_cancels_out():
    """Three turning points rather than two, so a linear drift subtracts
    exactly. The two-point reading would report `amp + drift`, which is how a
    portamento gets counted as vibrato depth."""
    flat = fidelity.vibrato_swings(_osc(6, 400))
    sliding = fidelity.vibrato_swings(_osc(6, 400, drift=600))
    assert flat and sliding
    assert abs(fidelity._median([s for s, _ in flat])
               - fidelity._median([s for s, _ in sliding])) <= 4


def test_only_interior_cycles_are_measured():
    """A cycle cut by the note boundary understates its own swing, so it is
    dropped -- the rule `noise_runs` applies to the window edge."""
    # Two turning points is one half-cycle and not enough: nothing is emitted.
    assert fidelity.vibrato_swings([0, 10, 20, 10, 0, 10, 20]) == []
    assert len(fidelity.vibrato_swings(_osc(2, 400))) < 4


def test_a_pure_slide_has_no_swing_at_all():
    assert fidelity.vibrato_swings(list(range(0x1000, 0x1100, 4))) == []


def _fq_voice(attacks, freqs, adsr):
    """One voice: gate-edge attacks at `attacks`, a frequency per frame."""
    return fidelity.Voice(
        attacks=["C-4"] * len(attacks), attack_frames=list(attacks),
        freq_events=[(f, v) for f, v in enumerate(freqs)],
        adsr_events=[(0, adsr)])


def test_depth_is_segmented_on_gate_edges_and_not_on_note_names():
    """siddump prints the *nearest* note, which flickers while a vibrato runs.
    Segmenting on the printed name chops one note into fragments shorter than
    a cycle -- the first attempt at this measurement found one measurable note
    in 3000 frames that way. Here a single 80-frame note carries ten cycles
    and must be read as one segment."""
    seg = _osc(10, 400)
    v = _fq_voice([0], seg, 0x0A0A)
    got = fidelity.oscillation_depths([v, fidelity.Voice(), fidelity.Voice()],
                                      len(seg), {0x0A0A})
    assert 0x0A0A in got
    assert 0.08 < got[0x0A0A] < 0.11        # 400 / ~0x1000


def test_depth_reports_a_shallow_swing_as_shallow():
    """The defect the column exists for: the same rate, a third of the
    distance. `pitch_motion_compare` reads 1.00x on this pair."""
    deep, shallow = _osc(10, 900), _osc(10, 300)
    orig = [_fq_voice([0], deep, 0x0A0A), fidelity.Voice(), fidelity.Voice()]
    ours = [_fq_voice([0], shallow, 0x0A0A), fidelity.Voice(), fidelity.Voice()]
    n = min(len(deep), len(shallow))
    assert fidelity.pitch_motion_compare(orig, ours, n)["reversal_ratio"] == 1.0
    got = fidelity.depth_compare(orig, ours, n, {0x0A0A})
    assert 0.30 < got["depth_ratio"] < 0.37
    assert got["depth_instruments"] == 1


def test_depth_declines_rather_than_measuring_the_wrong_population():
    """A depth over every oscillating note is worthless -- it picks up
    portamento slides and drum sweeps and reports 273% and 397% depths, with
    by-multiplier medians all at about 1.0. So no population means no
    measurement, not a fallback to the unrestricted reading."""
    seg = _osc(10, 400)
    v = [_fq_voice([0], seg, 0x0A0A), fidelity.Voice(), fidelity.Voice()]
    assert fidelity.depth_compare(v, v, len(seg), None) == {}
    assert fidelity.depth_compare(v, v, len(seg), set()) == {}
    # ...and an instrument outside the population is not measured either.
    assert fidelity.depth_compare(v, v, len(seg), {0x0B0B}) == {}


def test_a_release_rewritten_by_cut_release_still_joins():
    """`--cut-release` zeroes the release nibble on our side only, so an
    exact-only population filter would drop every instrument it touched --
    the trap `paired_keys` and `stamp_for` already exist for."""
    seg = _osc(10, 400)
    orig = [_fq_voice([0], seg, 0x0A0C), fidelity.Voice(), fidelity.Voice()]
    ours = [_fq_voice([0], seg, 0x0A00), fidelity.Voice(), fidelity.Voice()]
    got = fidelity.depth_compare(orig, ours, len(seg), {0x0A0C})
    assert got.get("depth_instruments") == 1
    assert abs(got["depth_ratio"] - 1.0) < 0.01


def test_depth_is_a_declared_dimension_reading_the_frequency_registers():
    d = next(d for d in fidelity.DIMENSIONS if d.key == "depth_ratio")
    assert d.column == "depth" and d.kind == "ratio"
    assert d.reads == ("$D400/$D401",)
    # Present in a row only when it was actually computed -- a file whose
    # player has no vibrato routine must not claim the column.
    row = _row("A.sid", "measured", 1.0)
    assert "depth_ratio" in fidelity.dimensions_present(row)
    assert "depth_ratio" not in fidelity.dimensions_present(
        dict(row, depth_ratio=None))


# --- the `scored against a subtune of ours` line ------------------------------
#
# This line asserted the BENIGN cause outright -- "because our numbering shifts
# when a subtune is dropped" -- and that sentence is why Action Biker, Samantha
# Fox Strip Poker and Spellbound shipped `.sng`s whose subtunes played in the
# wrong ORDER for the life of the converter (fixed in f63caa1). The report was
# not silent about them; it named them and then told the reader they were fine.
# `--search-subtunes` cannot distinguish the two causes, because it keeps
# whichever of ours matches best either way, so the line must not pretend it
# can. These pin the wording rather than the mechanism, deliberately: the
# mechanism is a search that is working as designed.

def _report_args():
    """The fields `report()` actually reads, derived from its source rather than
    guessed -- `args.label`, `args.seconds`, `args.subtune` and a `pair` it takes
    through `getattr`. Kept as a helper so a new read shows up as one failure here
    instead of four."""
    import argparse
    return argparse.Namespace(label=None, seconds=60, subtune="auto", pair=None)


def _real_row():
    """One REAL measured row, not a fabricated one.

    `report()` walks every column, so a hand-built dict fails on whichever key
    was added last (it failed here first on `retrigger_ratio`) and would go on
    failing for every column added after. Taking a row the harness actually
    emitted keeps these tests about the WORDING they pin. `build/fidelity.json`
    is gitignored, so a fresh checkout skips rather than fails.
    """
    import json
    p = pathlib.Path(fidelity.__file__).resolve().parent.parent / "build" / "fidelity.json"
    if not p.exists():
        pytest.skip("build/fidelity.json absent; run fidelity.py to generate it")
    doc = json.loads(p.read_text(encoding="utf-8"))
    rows = doc if isinstance(doc, list) else (doc.get("rows") or doc.get("songs") or [])
    real = next((r for r in rows if r.get("status") == "measured"), None)
    if real is None:
        pytest.skip("no measured row in build/fidelity.json")
    return dict(real)


def _note_for(matched_delta):
    row = _real_row()
    row["matched_subtune"] = row.get("subtune", 0) + matched_delta
    text = fidelity.report([row], _report_args())
    return next((ln for ln in text.splitlines()
                 if "subtune of" in ln and "ours" in ln), "")


def _shifted_note(monkeypatch):
    return _note_for(1)


def test_the_shifted_subtune_line_does_not_assert_the_benign_cause(monkeypatch):
    line = _shifted_note(monkeypatch)
    assert line, "the shifted-subtune line did not render for a shifted row"
    # The exact clause that made the defect read as normal.
    assert "because our numbering shifts when a subtune is dropped" not in line


def test_the_shifted_subtune_line_names_the_defect_cause(monkeypatch):
    line = _shifted_note(monkeypatch)
    low = line.lower()
    assert "wrong order" in low, "the line must name the wrong-order defect"
    assert "defect" in low
    assert "diagnose" in low, "the line must point at the tool that separates the two"


def test_the_shifted_subtune_line_still_names_the_files(monkeypatch):
    # Whatever else it says, it has to stay actionable.
    row = _real_row()
    assert row["file"] in _shifted_note(monkeypatch)


def test_no_shifted_line_when_every_correspondence_is_the_identity():
    # The state the corpus is in today: f63caa1 took this to zero files, and a
    # zero must render nothing at all rather than an empty warning.
    assert _note_for(0) == ""


# --- _preset_opts: an int option must survive the generic loop -------------
#
# `_preset_opts`'s generic loop used to coerce every option it did not
# recognise with `bool()`. That is silently wrong for an int option: bool(4)
# is True, and convert() then reads it as 1. `hard_restart_frames: 4` reached
# a conversion that way and produced a byte-identical .sng until it was
# hand-added to `_PER_SONG_OPTS` to dodge the loop entirely -- which meant the
# *next* int option would need the same manual rescue. The fix reads the
# option's own annotation off inspect.signature(convert) instead of guessing,
# so a brand-new int option works the first time, with nothing added to
# `_PER_SONG_OPTS`.


def _convert_with_new_int_option(new_int_default=0):
    """A stand-in for h2g.convert.convert carrying one extra int option that
    _preset_opts has never heard of and _PER_SONG_OPTS does not name."""
    def fake_convert(sid_path, log=print,
                      brand_new_int_option: int | None = new_int_default):
        return b""
    return fake_convert


def test_a_new_int_option_is_forwarded_as_an_int_not_a_bool(monkeypatch):
    monkeypatch.setattr(fidelity, "convert", _convert_with_new_int_option())
    assert "brand_new_int_option" not in fidelity._PER_SONG_OPTS
    doc = {"always": {}, "songs": {"a.sid": {"brand_new_int_option": 4}}}
    opts = fidelity._preset_opts(doc, "a.sid")
    assert opts["brand_new_int_option"] == 4, (
        "an int option must arrive as the int itself, not bool(4) == True "
        f"(== 1) -- got {opts['brand_new_int_option']!r}")
    assert opts["brand_new_int_option"] is not True
    assert type(opts["brand_new_int_option"]) is int


def test_a_new_int_option_absent_from_both_blocks_keeps_its_own_default(
        monkeypatch):
    monkeypatch.setattr(fidelity, "convert",
                        _convert_with_new_int_option(new_int_default=7))
    doc = {"always": {}, "songs": {}}
    opts = fidelity._preset_opts(doc, "a.sid")
    # Not False (bool(None)), and not silently missing: convert()'s own
    # default for the parameter, read off its signature.
    assert opts["brand_new_int_option"] == 7
    assert opts["brand_new_int_option"] is not False


def test_a_new_int_option_can_also_be_set_from_the_always_block(monkeypatch):
    monkeypatch.setattr(fidelity, "convert", _convert_with_new_int_option())
    doc = {"always": {"brand_new_int_option": 12}, "songs": {}}
    opts = fidelity._preset_opts(doc, "a.sid")
    assert opts["brand_new_int_option"] == 12


def test_wants_int_distinguishes_int_from_bool():
    assert fidelity._wants_int(int)
    assert fidelity._wants_int(int | None)
    assert not fidelity._wants_int(bool)
    assert not fidelity._wants_int(str)


def test_hard_restart_frames_still_arrives_as_a_real_int():
    """The regression this whole fix is about, against the real convert()."""
    doc = {"always": {}, "songs": {"a.sid": {"hard_restart_frames": 4}}}
    opts = fidelity._preset_opts(doc, "a.sid")
    assert opts["hard_restart_frames"] == 4
    assert opts["hard_restart_frames"] is not True


# --- gate census, split by voice --------------------------------------------

def test_gate_census_tags_each_record_with_its_voice():
    """`gate_runs`/`gate_census` operate per voice; the record must say which
    one, or a per-voice question (which this task exists because of --
    Auf Wiedersehen Monty's gate reads 48.06% / 56.90% / 15.08% across its
    three voices) cannot be asked of the census at all."""
    # Voice 0: one long original release (frames 2-5) we never release in --
    # `held`. Voice 1: untouched (no release either side).
    orig = _wf_voices([(0, 0x41), (2, 0x40), (6, 0x41)])
    ours = _wf_voices([(0, 0x41)])
    recs = fidelity.gate_census(orig, ours, nframes=8)
    assert [r["kind"] for r in recs] == ["held"]
    assert recs[0]["voice"] == 1
    assert recs[0]["frames"] == 4


def test_gate_census_by_voice_reproduces_the_file_level_totals():
    """Summing the per-voice split back up must reproduce the un-split
    table's numbers -- it is the same reduction one level finer, not a
    second measurement. Three voices, three different kinds, by construction:
    voice 0 gets a `held` run, voice 1 a `matched` release, voice 2 a `short`
    one, and a fourth run gives voice 0 a second `held` run so a kind can
    have more than one voice contributing to it."""
    orig = [
        # v0: two rests (frames 2-3, 5-6)
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (4, 0x41),
                                   (5, 0x40), (7, 0x41)]),
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (6, 0x41)]),  # v1: one rest
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (6, 0x41)]),  # v2: one rest
    ]
    ours = [
        fidelity.Voice(wf_events=[(0, 0x41)]),                          # never lets go: both held
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (5, 0x41)]),    # releases most of it: matched
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (3, 0x41)]),    # releases briefly: short
    ]
    recs = fidelity.gate_census(orig, ours, nframes=8)
    kinds = sorted((r["voice"], r["kind"]) for r in recs)
    assert kinds == [(1, "held"), (1, "held"), (2, "matched"), (3, "short")]

    by_voice = fidelity.gate_census_by_voice(recs)
    # Reproduction check: summed back across voices, per kind, matches a
    # plain (non-split) reduction over the same records.
    from collections import Counter
    plain_frames = Counter()
    for r in recs:
        plain_frames[r["kind"]] += r["frames"] - r["ours_off"]
    split_frames = Counter()
    for v in by_voice:
        for k, cell in by_voice[v].items():
            split_frames[k] += cell["frames"]
    assert split_frames == plain_frames
    # And voice 0's two `held` runs stay attributed to voice 0, not folded
    # into a file-wide bucket -- the actual per-voice question this task is
    # about.
    assert by_voice[1]["held"]["runs"] == 2
    assert by_voice[2]["matched"]["runs"] == 1
    assert by_voice[3]["short"]["runs"] == 1


def test_gate_census_report_by_voice_section_sums_to_the_top_table():
    """The report's own tables must agree with each other: the "By voice"
    section's runs, summed over voices for a given kind, equal the runs the
    top (file-level) table prints for that same kind -- the exact property
    the task asks for ("reproduces the file-level totals when summed")."""
    orig = [
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (4, 0x41),
                                   (5, 0x40), (7, 0x41)]),
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (6, 0x41)]),
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (6, 0x41)]),
    ]
    ours = [
        fidelity.Voice(wf_events=[(0, 0x41)]),
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (5, 0x41)]),
        fidelity.Voice(wf_events=[(0, 0x41), (2, 0x40), (3, 0x41)]),
    ]
    rows = [{"file": "synthetic.sid",
            "gate_census": fidelity.gate_census(orig, ours, nframes=8)}]
    report = fidelity.gate_census_report(rows)

    import re
    # crude but exact: parse "| held | N | ... |" out of the top table --
    # anchored to line start so it cannot match a "By voice" row instead
    # (those start with "| <voice> | held | ...").
    top_held = int(re.search(r"^\| held \| (\d+) \|", report, re.M).group(1))
    assert top_held == 2
    # Sum the by-voice section's `held` rows.
    by_voice_held = sum(int(n) for n in
                        re.findall(r"^\| \d+ \| held \| (\d+) \|", report,
                                   re.M))
    assert by_voice_held == top_held
    assert "## By voice" in report
    assert "## Where the held ones are" in report
    # The held-runs table must now say *which voice*, not just which file.
    held_section = report.split("## Where the held ones are", 1)[1]
    assert "voice" in held_section.splitlines()[2]  # header row names it


# --- `adsr` on gated-off frames: measured, and the drop REFUTED -------------
#
# The standing proposal was to drop frames where BOTH sides are gated off,
# on the argument that AD governs nothing while the gate is off. Censused
# over all 83 convertible files at -t 60: of 249886 disagreeing frames, 78395
# (31.4%) are gated off on both sides -- and 49000 of THOSE (62.5%) differ in
# the RELEASE nibble. Gate-off starts the release phase, which is still
# sounding, so those are audible. Dropping them would flatter the column by
# discarding a real difference, the v0.5.200 shape. Only 11.8% of the total
# deficit is genuinely unhearable. The split is reported, not acted on.

def _adsr_pair(orig_adsr, ours_adsr, orig_wf, ours_wf, n=4):
    a = [fidelity.Voice(adsr_events=[(0, orig_adsr)], wf_events=[(0, orig_wf)]),
         fidelity.Voice(), fidelity.Voice()]
    b = [fidelity.Voice(adsr_events=[(0, ours_adsr)], wf_events=[(0, ours_wf)]),
         fidelity.Voice(), fidelity.Voice()]
    return fidelity.adsr_compare(a, b, n)


def test_a_gated_off_disagreement_is_counted_and_split_by_release():
    """Both gated off ($40 = waveform selected, gate bit clear) and the
    release nibble differs: counted, and counted as AUDIBLE."""
    got = _adsr_pair(0x2401, 0x2402, 0x40, 0x40)
    assert got["adsr_gated_off"] == 4
    assert got["adsr_gated_off_audible"] == 4


def test_a_gated_off_disagreement_sharing_a_release_is_inaudible():
    """Same release nibble, different attack/decay: counted as gated off and
    NOT as audible -- this is the only part of the deficit the original
    proposal was right about, and corpus-wide it is 11.8% of it."""
    got = _adsr_pair(0x2401, 0x9401, 0x40, 0x40)
    assert got["adsr_gated_off"] == 4
    assert got["adsr_gated_off_audible"] == 0


def test_a_disagreement_with_either_side_gated_on_is_not_counted_off():
    got = _adsr_pair(0x2401, 0x2402, 0x41, 0x40)
    assert got["adsr_gated_off"] == 0, "one side is gated ON"


def test_the_score_itself_is_unchanged_by_the_gate_split():
    """The counts are reported, never subtracted: a gated-off disagreement is
    still a disagreement in `adsr`. If this ever fails, someone has turned the
    census into a denominator change -- which the corpus refutes."""
    got = _adsr_pair(0x2401, 0x2402, 0x40, 0x40)
    assert got["adsr"] == 0.0, "the gated-off frames were dropped from the score"
    assert got["adsr_frames"] == 4


def test_the_length_probe_factor_is_above_two_so_a_loop_is_separable():
    """Action Biker's original ends at 59.54s and ours looped with a period of
    61.44s, so anything at or below 2x cannot separate them."""
    import fidelity as F
    assert F.LENGTH_PROBE_FACTOR > 2


def test_an_original_still_sounding_at_the_edge_is_not_scored_as_passing():
    """`-` is the column declining, never a pass. A tune that plays past the
    probe window keeps declining rather than being given a number."""
    import fidelity as F

    class V:
        def __init__(self, frames):
            self.attack_frames = frames

    # attacks right up to the edge of a 60s window, and no trailing silence
    dense = [V([f for f in range(0, 60 * 50, 10)]), V([]), V([])]
    assert F.original_ended(dense, 60) is None
    assert F.stopped_at(dense, 60) is None


def test_a_tune_that_stops_just_before_the_window_edge_is_invisible_to_it():
    """The blind spot the probe exists to cover: stopping 0.46s before the
    trace does looks identical to playing on, from inside that window."""
    import fidelity as F

    class V:
        def __init__(self, frames):
            self.attack_frames = frames

    # last attack at 59.54s of a 60s window, evenly spaced before it
    frames = list(range(0, int(59.54 * 50), 25))
    side = [V(frames), V([]), V([])]
    assert F.stopped_at(side, 60) is None, "invisible at the run's own window"
    # and visible once the window is long enough for the silence to show
    assert F.stopped_at(side, 180) is not None, "visible at the probe window"


# --- melody is collapsed, and the docs must say so ---------------------------
#
# `melody` reads `.collapsed` (consecutive repeats removed), not `.attacks`.
# A probe that read `.attacks` instead could not reproduce the report and
# misdiagnosed a real 0.000 as its own bug rather than the file's. These pin
# the implementation to the description so the two documents (module
# docstring, Dimension registry, generated-report template) cannot drift
# from the code or from each other again.

def test_melody_is_computed_from_the_collapsed_sequence():
    """The implementation `compare()` actually has -- read from source so a
    future rewrite that switches the field back to `.attacks` fails here."""
    import inspect
    src = inspect.getsource(fidelity.compare)
    assert '"melody": _ratio(a.collapsed, b.collapsed)' in src
    assert '"sequence": _ratio(a.attacks, b.attacks)' in src


def test_melody_documentation_says_collapsed_and_what_that_hides():
    """Every place `fidelity.py` describes the `melody` column must call out
    that it is collapsed, and that collapsing makes it blind to a re-struck
    note -- the fact a probe reading `.attacks` instead cannot reproduce."""
    module_doc = fidelity.__doc__
    assert "melody similarity" in module_doc
    melody_bullet_start = module_doc.index("melody similarity")
    melody_bullet = module_doc[melody_bullet_start:melody_bullet_start + 600]
    assert "collapsed" in melody_bullet
    assert "re-struck" in melody_bullet

    dim = next(d for d in fidelity.DIMENSIONS if d.key == "melody")
    assert dim.column == "melody"
    assert "collapsed" in dim.of
    assert "re-struck" in dim.of

    # The generated-report template lives in the module as a literal string
    # table; search the whole module source for the melody bullet rather than
    # one function, since which function builds the report may itself move.
    import pathlib
    module_src = pathlib.Path(fidelity.__file__).read_text(encoding="utf-8")
    idx = module_src.index("**melody** -- similarity of the attack sequence")
    template_bullet = module_src[idx:idx + 400]
    assert "collapsed" in template_bullet
    assert "re-struck" in template_bullet
