"""`tie_compare`'s one-sided counts carry their reasons: silent and firstwave.

Task pre-attack-frame-swallows-arp-tie (at be0aeb1): 452 of Zoids voice 2's
452 orig-only ties fall on the frame before our attack. That frame is our
note-init call -- `FIRSTWAVE_TESTBIT` ($09), no frequency written -- and the
original steps its octave arpeggio on it into a voice whose envelope it has
already zeroed (ADSR $0000 two frames before every attack). Nobody hears
either side. The fixtures below are that note, transcribed from the siddump
traces (orig frames 836-848, our frames lag-aligned onto them).
"""
import fidelity

V = fidelity.Voice


def _zoids_orig(adsr_zeroed=True, shift=0):
    """G-3 struck at 836, released at 837, arp G-4/G-3/G-4 every 4 frames,
    and -- if `adsr_zeroed` -- the player's ADSR $0000 at 845; D-3 at 848."""
    s = shift
    adsr = [(836 + s, 0x070A), (848 + s, 0x070A)]
    if adsr_zeroed:
        adsr.insert(1, (845 + s, 0x0000))
    return V(attacks=["G-3", "D-3"], attack_frames=[836 + s, 848 + s],
             ties=3, tie_frames=[839 + s, 843 + s, 847 + s],
             wf_events=[(836 + s, 0x41), (837 + s, 0x80), (839 + s, 0x40),
                        (848 + s, 0x41)],
             adsr_events=adsr)


def _zoids_ours():
    """The conversion: $09 on 835 and 847, attacks on 836 and 848, and the
    arp's 847 step missing because the note-init call writes no frequency."""
    return V(attacks=["G-3", "D-3"], attack_frames=[836, 848],
             ties=2, tie_frames=[839, 843],
             wf_events=[(835, 0x09), (836, 0x41), (837, 0x81), (839, 0x40),
                        (847, 0x09), (848, 0x41)],
             adsr_events=[(835, 0x070A)])


def test_the_zoids_pre_attack_tie_is_on_our_firstwave_and_silent_in_the_original():
    got = fidelity.tie_compare([_zoids_orig()], [_zoids_ours()], 900)
    assert (got["tie_same_frame"], got["tie_orig_only"], got["tie_ours_only"]) == (2, 1, 0)
    assert got["tie_orig_only_firstwave"] == 1
    assert got["tie_orig_only_silent"] == 1
    v = got["tie_voices"][0]
    assert (v["orig_only_firstwave"], v["orig_only_silent"]) == (1, 1)


def test_an_audible_release_is_not_called_silent():
    # IK_plus's face: the same firstwave frame, but the original never zeroes
    # its ADSR, so release $A (1.5 s) is still sounding at 847.
    got = fidelity.tie_compare([_zoids_orig(adsr_zeroed=False)], [_zoids_ours()], 900)
    assert got["tie_orig_only_firstwave"] == 1
    assert got["tie_orig_only_silent"] == 0


def test_the_original_is_read_at_its_own_frame_under_a_lag():
    orig = _zoids_orig(shift=-7)        # the original 7 frames earlier
    got = fidelity.tie_compare([orig], [_zoids_ours()], 900, lag=7)
    assert (got["tie_same_frame"], got["tie_orig_only"]) == (2, 1)
    assert got["tie_orig_only_silent"] == 1
    assert got["tie_orig_only_firstwave"] == 1
    # And the audible control stays audible under the same lag.
    loud = fidelity.tie_compare([_zoids_orig(False, -7)], [_zoids_ours()], 900, lag=7)
    assert loud["tie_orig_only_silent"] == 0


def test_a_test_bit_frame_not_followed_by_our_attack_is_not_firstwave():
    ours = _zoids_ours()
    ours.attack_frames = [836]          # no attack at 848: 847 is no note init
    got = fidelity.tie_compare([_zoids_orig()], [ours], 900)
    assert got["tie_orig_only"] == 1
    assert got["tie_orig_only_firstwave"] == 0


def test_a_shared_silent_tie_is_not_counted_as_one_sided():
    ours = _zoids_ours()
    ours.tie_frames = [839, 843, 847]   # we step the arp on 847 too
    got = fidelity.tie_compare([_zoids_orig()], [ours], 900)
    assert got["tie_orig_only"] == 0
    assert got["tie_orig_only_silent"] == 0 and got["tie_orig_only_firstwave"] == 0


def test_our_tie_after_our_envelope_died_is_counted_silent():
    ours = _zoids_ours()
    ours.adsr_events = [(835, 0x070A), (845, 0x0000)]
    ours.tie_frames = [839, 843, 846]   # 846: released, ADSR zeroed at 845
    got = fidelity.tie_compare([_zoids_orig()], [ours], 900)
    assert got["tie_ours_only"] == 1 and got["tie_ours_only_silent"] == 1
    loud = _zoids_ours()
    loud.tie_frames = [839, 843, 846]   # release $A still sounding at 846
    assert fidelity.tie_compare([_zoids_orig()], [loud], 900)["tie_ours_only_silent"] == 0


def test_the_split_moves_no_existing_figure_and_needs_the_waveform():
    full = fidelity.tie_compare([_zoids_orig()], [_zoids_ours()], 900)
    bare = fidelity.tie_compare(
        [V(attacks=["G-3"], ties=3, tie_frames=[839, 843, 847])],
        [V(attacks=["G-3"], ties=2, tie_frames=[839, 843])], 900)
    for k in ("tie_agreement", "tie_same_frame", "tie_ours_only", "tie_orig_only"):
        assert full[k] == bare[k]
    # No waveform events: the gate cannot be seen, so nothing is silent and
    # no frame is a firstwave.
    assert (bare["tie_orig_only_silent"], bare["tie_ours_only_silent"],
            bare["tie_orig_only_firstwave"]) == (0, 0, 0)


def test_audible_frames_spans_attack_to_envelope_zero():
    aud = fidelity.audible_frames(_zoids_orig(), 900)
    assert not any(aud[:836])           # before the first gate edge
    assert all(aud[836:846])            # struck 836, released 837, zeroed 845
    assert not any(aud[846:848])        # 847 is the tie nobody hears
    assert aud[848]
    assert fidelity.audible_frames(V(), 900) is None
