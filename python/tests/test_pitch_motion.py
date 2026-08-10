"""Pitch oscillation and pitch travel, told apart without a threshold.

`slides` and `bend` lump every kind of pitch movement together. On Commando all
of it is vibrato -- turning `--vibrato` off takes the slide count from 245 to
zero, while `--slides` and `--effects` change it by nothing -- so a corpus A/B
that reads "slide count" is mostly ranking vibrato rates. The `-R0` decision in
section 7.hhh was taken on exactly that confusion.

A vibrato reverses and a portamento does not, which separates them with no cutoff
to choose.
"""
import fidelity as F


def _voice(freqs, attacks=(0,)):
    """One voice whose frequency follows `freqs`, attacking on `attacks`."""
    v = F.Voice(freq_events=[(i, f) for i, f in enumerate(freqs)],
                attack_frames=list(attacks))
    return [v, F.Voice(), F.Voice()]


def test_a_clean_slide_has_no_reversals_and_no_oscillation():
    rising = _voice([0x1000 + 0x40 * i for i in range(12)])
    got = F.pitch_motion(rising, 12)
    assert got["reversals"] == 0
    assert got["oscillation"] == 0.0, "every unit of movement got somewhere"


def test_a_vibrato_is_all_reversals_and_almost_all_oscillation():
    """Back and forth about one centre: gross movement, almost no net
    displacement. "Almost" because a wobble stopped mid-swing carries one
    half-cycle of net, which is a smaller share the longer the note runs --
    0.800 over 8 frames, 0.923 over 16, 0.966 over 32. That is the measure being
    honest about a finite window, not a floor to tune."""
    got = F.pitch_motion(_voice([0x1000, 0x1040] * 8), 16)
    assert got["reversals"] == 12
    assert got["oscillation"] > 0.9
    assert got["net"] == 0x40, "one half-swing, however long the note"
    shorter = F.pitch_motion(_voice([0x1000, 0x1040] * 4), 8)
    longer = F.pitch_motion(_voice([0x1000, 0x1040] * 16), 32)
    assert shorter["oscillation"] < got["oscillation"] < longer["oscillation"]


def test_halving_the_oscillator_halves_the_reversals():
    """The property a call-skipping packer changes. Goattracker's vibrato is a
    realtime effect, and gt2reloc's default-on -R skipping drops it on the
    note-fetch tick -- Commando's runs at 48% of the original's rate."""
    fast = _voice([0x1000, 0x1040] * 8)
    slow = _voice([0x1000, 0x1000, 0x1040, 0x1040] * 4)
    a = F.pitch_motion(fast, 16)["reversals"]
    b = F.pitch_motion(slow, 16)["reversals"]
    assert b * 2 <= a + 1, (a, b)


def test_the_measure_needs_no_threshold():
    """A depth of 1 and a depth of 256 read the same rate, so nothing has to be
    decided about how big a wobble counts."""
    shallow = _voice([0x1000, 0x1001] * 8)
    deep = _voice([0x1000, 0x1100] * 8)
    assert (F.pitch_motion(shallow, 16)["reversals"]
            == F.pitch_motion(deep, 16)["reversals"])


def test_note_onsets_are_not_counted_as_reversals():
    """An onset is a large pitch jump in whatever direction the tune goes. Frames
    within one of an attack are skipped -- and unlike a fixed offset, dropping a
    frame here costs one sample of many rather than shifting the measurement."""
    steps = [0x1000, 0x1040, 0x1080, 0x10C0,      # rising
             0x0800, 0x0840, 0x0880, 0x08C0]      # ...new note, way down
    v = _voice(steps, attacks=(0, 4))
    assert F.pitch_motion(v, 8)["reversals"] == 0


def test_a_still_pitch_reports_no_oscillation_rather_than_zero():
    flat = _voice([0x1000] * 10)
    assert F.pitch_motion(flat, 10)["oscillation"] is None


def test_the_comparison_reports_a_rate_ratio_and_both_shares():
    orig = _voice([0x1000, 0x1040] * 8)
    ours = _voice([0x1000, 0x1000, 0x1040, 0x1040] * 4)
    got = F.pitch_motion_compare(orig, ours, 16)
    assert got["reversal_ratio"] < 0.7
    assert got["orig_oscillation"] > 0.9 and got["our_oscillation"] > 0.9


def test_a_ratio_needs_a_denominator():
    still = _voice([0x1000] * 10)
    moving = _voice([0x1000, 0x1040] * 5)
    assert F.pitch_motion_compare(still, moving, 10)["reversal_ratio"] is None
