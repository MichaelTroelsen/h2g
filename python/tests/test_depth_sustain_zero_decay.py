"""`envelope_zero_frame`'s third rule: an open gate at sustain nibble 0.

Any pair whose sustain nibble is 0 climbs through its attack, decays to $00
and freezes there (reSID envelope.h:137-141, 173-178), so `depth` must stop
counting cycles a player sweeps after that. Measured on the corpus at
v0.5.509, 81da71d, -t 180 under presets.json (C:/t/depth-sustain-zero-decay/r2;
historical figures): 53 of the 473 vibrato-population
keys, in 37 of 81 files, have sustain nibble 0; 5824 of the original's 40408
population notes are keyed on one; the rule moves the stop of 33 of them
(363 frames) and 34 of ours (431 frames), in Mozart, Wiz and Zoolook, and
moves one `depth` row: Mozart 1.4866x/9i -> 1.4175x/8i.
"""
import fidelity

N = 400
OPEN, SHUT = 0x41, 0x40


def test_the_decay_bound_is_reSIDs_cycle_count_rounded_up():
    # 756 period-units from $FF to $00: the exponential divider's six legs.
    assert fidelity.SID_DECAY_UNITS == (162 * 1 + 39 * 2 + 28 * 4 + 12 * 8
                                        + 8 * 16 + 6 * 30)
    # AD $09: attack 0 (9 cycles/step), decay 9 (977): 255*9 + 756*977
    # + 0x8000 = 773675 cycles, / 19656 = 39.36 -> 40 frames.
    assert fidelity._decay_to_zero_frames(0x09) == 40
    # AD $46 (Mozart's key): 255*149 + 756*267 + 0x8000 = 272615 -> 14.
    assert fidelity._decay_to_zero_frames(0x46) == 14
    # Never 0, and the release nibble's slot (low byte) is not an input.
    assert fidelity._decay_to_zero_frames(0x00) == 3


def _resid_cycles(ad: int, c0: int) -> int:
    """Cycles from a gate rise to the envelope's freeze at $00, sustain 0,
    from level $00 with the rate counter at `c0` -- stepped the way reSID's
    EnvelopeGenerator::clock() steps (envelope.h:93-180): the delay-bug wrap
    at 0x8000, attack one step per rate period, decay one step per
    `exponential_counter_period` rate periods, that period switched on the
    level just reached. Independent of SID_DECAY_UNITS on purpose."""
    p_a = fidelity.SID_RATE_PERIOD[ad >> 4]
    p_d = fidelity.SID_RATE_PERIOD[ad & 0x0F]
    cyc = (p_a - c0) if c0 < p_a else (0x8000 - c0 + p_a)
    cyc += 254 * p_a                                # level 1 .. $FF
    level, exp = 0xFF, 1
    switch = {0x5D: 2, 0x36: 4, 0x1A: 8, 0x0E: 16, 0x06: 30}
    while level:
        cyc += p_d * exp
        level -= 1
        exp = switch.get(level, exp)
    return cyc


def test_the_bound_covers_resids_stepping_for_every_ad_byte():
    frame = fidelity.PAL_FRAME_CYCLES
    for ad in range(256):
        p_a = fidelity.SID_RATE_PERIOD[ad >> 4]
        # The rate counter at a gate rise is below the release period that
        # was latched (<= 31251); the worst case wraps from just at p_a.
        worst = max(_resid_cycles(ad, c) for c in (0, p_a - 1, p_a, 31250))
        best = min(_resid_cycles(ad, c) for c in (0, p_a - 1, p_a, 31250))
        bound = fidelity._decay_to_zero_frames(ad)
        assert bound * frame >= worst, (hex(ad), bound, worst)
        # ... and loose by no more than the wrap, one attack step (the bound
        # charges the first step on top of the wrap) and a rounding frame.
        assert bound * frame - best <= 0x8000 + p_a + frame, \
            (hex(ad), bound, best)


def test_an_open_gate_at_sustain_zero_goes_silent_after_attack_and_decay():
    # 0x0900: AD $09, sustain 0 -> frames 0..39 charged, 40 silent.
    assert fidelity.envelope_zero_frame([OPEN] * N, [0x0900] * N, 0, N) == 40
    # Counted from the segment's own start, not from frame 0.
    assert fidelity.envelope_zero_frame([OPEN] * N, [0x0900] * N, 100, N) \
        == 140
    # A segment shorter than the decay is not cut.
    assert fidelity.envelope_zero_frame([OPEN] * N, [0x0900] * N, 0, 30) == 30


def test_a_non_zero_sustain_never_dies_under_an_open_gate():
    assert fidelity.envelope_zero_frame([OPEN] * N, [0x0910] * N, 0, N) == N


def test_raising_the_sustain_mid_decay_drops_the_bound():
    """A decay still above the new level stops there and sounds."""
    adsr = [0x0900] * 20 + [0x0910] * (N - 20)
    assert fidelity.envelope_zero_frame([OPEN] * N, adsr, 0, N) == N


def test_an_ad_write_restarts_the_bound_at_the_new_rates():
    # AD $0A written at 30 (decay 10: 77 frames) -> 30..106 charged.
    adsr = [0x0900] * 30 + [0x0A00] * (N - 30)
    assert fidelity.envelope_zero_frame([OPEN] * N, adsr, 0, N) == 107
    # A pair written 0x0000 is read by the pair-zero rule first: frame 31.
    adsr = [0x0900] * 30 + [0x0000] * (N - 30)
    assert fidelity.envelope_zero_frame([OPEN] * N, adsr, 0, N) == 31
    # AD $00 with a non-zero release nibble is not pair zero: 30 + 3.
    adsr = [0x0900] * 30 + [0x0005] * (N - 30)
    assert fidelity.envelope_zero_frame([OPEN] * N, adsr, 0, N) == 33


def test_a_release_nibble_write_leaves_an_open_gate_bound_alone():
    adsr = [0x0900] * 30 + [0x0909] * (N - 30)
    assert fidelity.envelope_zero_frame([OPEN] * N, adsr, 0, N) == 40


def test_a_gate_that_rises_again_restarts_the_bound():
    # Open 0..9, released 10..19 (release 9: 38 frames, not run out), open
    # again from 20: the bound is 20 + 40 - 1, so 60 is the first silent
    # frame -- not 40, which the first rise alone would give.
    wf = [OPEN] * 10 + [SHUT] * 10 + [OPEN] * (N - 20)
    assert fidelity.envelope_zero_frame(wf, [0x0909] * N, 0, N) == 60


def _tail_voice(audible_amp, tail_amp, adsr=0x0900, n=200):
    """One note under an open gate at sustain 0: vibrato of `audible_amp`
    for the first 40 frames (the decay bound of AD $09), `tail_amp` after."""
    out, cur, up = [], 0x1000, True
    for f in range(n):
        amp = audible_amp if f < 40 else tail_amp
        if f and f % 4 == 0:
            up = not up
        cur += (amp // 4) if up else -(amp // 4)
        out.append(cur)
    return fidelity.Voice(
        attacks=["C-4"], attack_frames=[0],
        freq_events=list(enumerate(out)),
        wf_events=[(0, OPEN)], adsr_events=[(0, adsr)]), n


def test_depth_ignores_cycles_swept_after_a_sustain_zero_decay():
    v, n = _tail_voice(400, 2000)
    side = [v, fidelity.Voice(), fidelity.Voice()]
    got = fidelity.oscillation_depths(side, n, {0x0900})
    assert 0.08 < got[0x0900] < 0.11, got          # 400 / ~0x1000
    ungated = fidelity.oscillation_depths(side, n, {0x0900},
                                          audible_only=False)
    assert ungated[0x0900] > 0.3, ungated          # the tail's 2000
    # The same note at sustain 1 never dies, so the tail is audible.
    v1, _ = _tail_voice(400, 2000, adsr=0x0910)
    held = fidelity.oscillation_depths([v1, fidelity.Voice(),
                                        fidelity.Voice()], n, {0x0910})
    assert held[0x0910] > 0.3, held
