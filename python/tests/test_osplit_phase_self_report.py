"""osplit-phase-self-report: the osplit column says when its geometry makes the
trill uncountable (predicted minority < OCTAVE_MINORITY_LINES)."""
import fidelity
import vicetrace as VT


def _frames(per_call, calls, nframes=6, phase=0):
    """Samples whose voice 0 writes `per_call[k % len]` at line phase+k*L."""
    n = VT.PAL_LINES_PER_FRAME
    period = n / calls
    out = []
    for line in range(nframes * n):
        k = int((line - phase) // period) if line >= phase else -1
        f = per_call[k % len(per_call)] if k >= 0 else 0x1000
        out.append(VT.Sample(voices=[VT.VoiceLine(freq=f), VT.VoiceLine(), VT.VoiceLine()]))
    return out


def test_formula_matches_measured_s3_range():
    # measured -S3 phase w=64..82 -> 126..144 lines (L = 104)
    assert fidelity.octave_predicted_minority(3, 64) == 144
    assert fidelity.octave_predicted_minority(3, 82) == 126
    assert fidelity.octave_predicted_minority(3, 64 + 104) == 144  # modulo L


def test_even_calls_are_always_half_a_frame():
    for w in (0, 17, 90):
        assert fidelity.octave_predicted_minority(2, w) == 156
        assert fidelity.octave_predicted_minority(4, w) == 156


def test_s5_floor_is_124_8_and_never_below_120():
    L = 312 / 5
    worst = min(fidelity.octave_predicted_minority(5, w * 0.5) for w in range(0, 125))
    assert abs(worst - 124.8) < 1e-9 and worst >= VT.OCTAVE_MINORITY_LINES
    assert abs(fidelity.octave_predicted_minority(5, 0) - 2 * L) < 1e-9


def test_s3_late_phase_is_flagged_and_early_phase_is_not():
    a, b = 0x1168, 0x08B4
    late = _frames([a, b, a], 3, phase=95)   # w=95 -> min(199, 113) = 113
    early = _frames([a, b, a], 3, phase=70)  # w=70 -> 144-ish, clear
    got = fidelity.vice_octave_split(early, late, our_calls_per_frame=3)
    assert got["our_octave_floor_blind"] is True
    assert got["our_octave_predicted_minority"] < VT.OCTAVE_MINORITY_LINES
    ok = fidelity.vice_octave_split(early, early, our_calls_per_frame=3)
    assert ok["our_octave_floor_blind"] is False


def test_cell_names_the_blind_side():
    row = {"our_octave_split_frames": 0, "orig_octave_split_frames": 0,
           "our_octave_floor_blind": True, "orig_octave_floor_blind": False}
    assert fidelity._fmt_osplit(row) == "0/0 (floor ours)"
    row["orig_octave_floor_blind"] = True
    assert fidelity._fmt_osplit(row) == "0/0 (floor ours+orig)"
    row["our_octave_floor_blind"] = False
    row["orig_octave_floor_blind"] = False
    assert fidelity._fmt_osplit(row) == "0/0"


def test_no_writes_means_no_claim():
    quiet = _frames([0x1168], 3)
    got = fidelity.vice_octave_split(quiet, [], our_calls_per_frame=3)
    assert got["our_octave_floor_blind"] is False


def test_floor_reports_median_and_minimum_over_a_drifting_phase():
    # writes at lines 64, 174, 303 -> w mod 104 = 64, 70, 95 -> 144, 138, 113
    starts, vals = [0, 64, 174, 303], [0x1000, 0x1168, 0x08B4, 0x1168]
    freq = [0] * 450
    for k, st in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else 450
        freq[st:end] = [vals[k]] * (end - st)
    samples = [VT.Sample(voices=[VT.VoiceLine(freq=f), VT.VoiceLine(), VT.VoiceLine()])
               for f in freq]
    assert fidelity.vice_octave_floor(samples, 3) == (138, 113)


def test_one_call_a_frame_makes_no_geometry_claim():
    assert fidelity.vice_octave_floor(_frames([0x1168, 0x08B4], 1), 1) == (None, None)
