"""The per-rasterline SID trace, and the blind spot it exists to cover.

siddump samples the registers once per frame whatever the call rate. A tune
packed at `gt2reloc -S5` therefore has four calls in five discarded, and a
gate that rises and falls inside one frame leaves no edge to count -- which
read as the conversion losing 40% of its notes for three versions.

VICE's `dump` sound device writes the whole SID state on every rasterline,
312 samples a PAL frame. Measured both ways on the same packed file:

    siddump, once per frame      52 attacks
    VICE, once per rasterline    87 gate edges
    the original, the same way  102

87 is also what `--equal-calls` predicted from a different direction, so two
methods that share nothing agree. The parsing tests below need no emulator;
the live one is skipped when VICE is absent.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import vicetrace as V                                          # noqa: E402

BLOCK = """FREQ:   1168 2000 0000
PULSE:  0800 0400 0000
CTRL:     41   00   00
ADSR:   0f00 0a05 0000
FILTER: 0400 RES: 09 MODE/VOL: 1f
ADC: ff ff
OSC3: 00 ENV3: a4
"""

GATE_OFF = BLOCK.replace("CTRL:     41   00   00", "CTRL:     40   00   00")


def test_a_block_parses_into_three_voices_and_the_filter():
    s = V.parse(BLOCK)
    assert len(s) == 1
    v = s[0].voices
    assert [x.freq for x in v] == [0x1168, 0x2000, 0]
    assert [x.pulse for x in v] == [0x0800, 0x0400, 0]
    assert [x.ctrl for x in v] == [0x41, 0, 0]
    assert [x.adsr for x in v] == [0x0f00, 0x0a05, 0]
    assert (s[0].cutoff, s[0].res, s[0].modevol) == (0x0400, 0x09, 0x1f)


def test_blocks_are_counted_not_merged():
    assert len(V.parse(BLOCK * 5)) == 5


def test_a_gate_edge_is_a_rise_not_a_level():
    """Two consecutive gated blocks are one note, not two."""
    assert V.gate_edges(V.parse(BLOCK * 3), 0) == [0]


def test_the_gate_must_fall_before_it_can_rise_again():
    s = V.parse(BLOCK + GATE_OFF + BLOCK)
    assert V.gate_edges(s, 0) == [0, 2]


def test_an_edge_inside_one_frame_is_visible():
    """The whole point. Both of these land in frame 0 of 312 rasterlines,
    where a once-per-frame sampler would see at most one."""
    s = V.parse((BLOCK + GATE_OFF) * 4)
    edges = V.gate_edges(s, 0)
    assert len(edges) == 4
    assert all(V.frame_of(i) == 0 for i in edges)


def test_an_ungated_voice_has_no_edges():
    assert V.gate_edges(V.parse(BLOCK * 4), 1) == []


def test_frames_are_312_rasterlines():
    assert V.PAL_LINES_PER_FRAME == 312
    assert V.frame_of(311) == 0 and V.frame_of(312) == 1


@pytest.mark.skipif(not pathlib.Path(V.VSID).exists(), reason="VICE not installed")
def test_the_live_trace_agrees_with_siddump_where_siddump_is_reliable():
    """Commando is multiplier 1, so siddump's frame sample loses nothing and
    the two must agree exactly. That control is what makes the disagreement
    on a multiplier-5 file evidence rather than noise.
    """
    import fidelity as F
    sid = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"
    corpus = pathlib.Path(F.reads_video_flag.__module__ and
                          r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
    src = corpus / "Commando.sid" if (corpus / "Commando.sid").exists() else sid
    samples = V.run(src, 10, 0)
    assert len(samples) == 10 * 50 * V.PAL_LINES_PER_FRAME
    edges = sum(len(V.gate_edges(samples, v)) for v in range(3))
    attacks = sum(len(v.attacks)
                  for v in F.run_siddump(src, 10, 0, F.SIDDUMP, 0))
    assert edges == attacks


# --- the per-frame reduction ------------------------------------------------
#
# The compare functions in fidelity.py walk frame-indexed timelines, so 312
# samples a frame have to be reduced before they can feed one. The reduction
# is not free and it is not arbitrary: the two sides write at different
# rasterlines within the frame, so a rule that depends on *where* in the frame
# a value sits is reporting that offset rather than the music. These pin the
# four rules and the property that decides between them.

def _samples(seq):
    """One frame of samples, `seq` being (value, rasterlines) for voice 0."""
    out = []
    for value, n in seq:
        for _ in range(n):
            s = V.Sample(voices=[V.VoiceLine(ctrl=value), V.VoiceLine(),
                                 V.VoiceLine()])
            out.append(s)
    assert len(out) == V.PAL_LINES_PER_FRAME, len(out)
    return out


def test_a_frame_cell_holds_the_whole_frames_shares_and_its_last_value():
    cells = V.frame_cells(_samples([(0x40, 200), (0x80, 112)]),
                          lambda v: v.ctrl)
    assert len(cells) == 1
    c = cells[0][0]
    assert c.hist == {0x40: 200, 0x80: 112}
    assert c.last == 0x80
    assert c.majority == 0x40


def test_a_partial_trailing_frame_is_dropped_not_scored_short():
    # Scoring 40 rasterlines against a full frame would weight them equally.
    short = _samples([(0x40, 312)]) + _samples([(0x40, 312)])[:40]
    assert len(V.frame_cells(short, lambda v: v.ctrl)) == 1


def test_the_four_rules_read_one_disagreeing_frame_four_ways():
    a = V.frame_cells(_samples([(0x40, 200), (0x80, 112)]), lambda v: v.ctrl)[0][0]
    b = V.frame_cells(_samples([(0x40, 312)]), lambda v: v.ctrl)[0][0]
    assert V.agreement(a, b, "overlap") == pytest.approx(200 / 312)
    assert V.agreement(a, b, "majority") == 1.0   # $40 wins the frame on both
    assert V.agreement(a, b, "any") == 1.0        # $40 occurs on both
    assert V.agreement(a, b, "last") == 0.0       # ...but not at the edge


def test_overlap_is_stable_under_an_inaudible_phase_shift_and_last_is_not():
    """The property the default was chosen on.

    Moving *when* in the frame a side writes changes nothing audible. `last`
    samples one instant, so a write crossing the frame edge flips it outright;
    `overlap` compares two distributions and barely moves. Measured on the
    corpus the same way -- eight files, shifts of 0-48 rasterlines -- `last`
    moves by up to 2.64 points and `overlap` by 0.13; see
    H2G-CONVERSION-METHOD.md section 7.nn.
    """
    ours = _samples([(0x40, 150), (0x80, 162)])
    orig = _samples([(0x80, 312)])
    o = V.frame_cells(orig, lambda v: v.ctrl)[0][0]
    base = {m: V.agreement(V.frame_cells(ours, lambda v: v.ctrl)[0][0], o, m)
            for m in V.AGREEMENT_MODES}
    # the same frame with the two runs swapped end to end: identical shares,
    # different instant at the boundary
    shifted = _samples([(0x80, 162), (0x40, 150)])
    now = {m: V.agreement(V.frame_cells(shifted, lambda v: v.ctrl)[0][0], o, m)
           for m in V.AGREEMENT_MODES}
    assert now["overlap"] == base["overlap"], "overlap must not see the phase"
    assert now["majority"] == base["majority"]
    assert now["last"] != base["last"], "last is the rule that aliases"


def test_the_counting_dimensions_take_the_majority_not_the_edge():
    # A count needs a definite value per frame, so it cannot use the graded
    # rule; `majority` is the stable one and `last` is the one that aliases.
    c = V.frame_cells(_samples([(0x40, 200), (0x80, 112)]), lambda v: v.ctrl)[0][0]
    assert c.representative() == 0x40
    assert c.representative("last") == 0x80


def test_a_global_register_reduces_the_same_way():
    frames = V.frame_cells_global(_samples([(0x40, 312)]), lambda s: s.cutoff)
    assert len(frames) == 1 and frames[0].hist == {0: 312}


# --- the dump's sign extension (task vicetrace-freq-hi-byte-reads-ff) --------
# VICE 3.9 prints a 16-bit field as (hi << 8) | (signed char) lo, so a low byte
# with bit 7 set arrives with an $FF high byte whatever the register held.

FF_BLOCK = BLOCK.replace("FREQ:   1168 2000 0000", "FREQ:   ff2b ff57 ff03")


def test_sign_extended_flags_ff_hi_with_lo_bit7():
    assert V.sign_extended(0xFFD0) and V.sign_extended(0xFF80)


def test_sign_extended_is_false_for_honest_values():
    assert not V.sign_extended(0x0DD0)   # real hi, lo >= $80
    assert not V.sign_extended(0xFF2B)   # lo < $80 cannot be sign extension
    assert not V.sign_extended(0x1168)


def test_parse_keeps_the_dumped_value_and_sign_extended_marks_it_untrustworthy():
    v = V.parse(BLOCK.replace("1168", "ffd0"))[0].voices[0]
    assert v.freq == 0xFFD0 and V.sign_extended(v.freq)


def _blk(pulse: str, adsr: str) -> str:
    return (BLOCK.replace("0800 0400", f"{pulse} 0400")
            .replace("0f00 0a05", f"{adsr} 0a05"))


def test_parse_repairs_an_ff_high_byte_pulse_sweep_crossing_lo_7f_to_80():
    # true pulse $087E, $087F, $0880, $0881: the dump prints $0880 as ff80
    s = V.parse("".join(_blk(p, "0f00") for p in ("087e", "087f", "ff80", "0881")))
    assert [x.voices[0].pulse for x in s] == [0x087E, 0x087F, 0x0880, 0x0881]


def test_parse_repairs_an_ff_high_byte_adsr():
    # true ADSR $0BF0 is printed fff0; neighbours say AD stays $0B
    s = V.parse("".join(_blk("0800", a) for a in ("0b00", "fff0", "0b00")))
    assert [x.voices[0].adsr for x in s] == [0x0B00, 0x0BF0, 0x0B00]


def test_parse_leaves_freq_raw_for_the_siddump_oracle():
    s = V.parse(BLOCK.replace("1168", "ffd0") * 3)
    assert s[1].voices[0].freq == 0xFFD0


def test_ff_hi_with_low_lo_is_not_called_sign_extension():
    v = V.parse(FF_BLOCK)[0].voices
    assert [x.freq for x in v] == [0xFF2B, 0xFF57, 0xFF03]
    assert not any(V.sign_extended(x.freq) for x in v)


def _frames(per_frame_freqs):
    """One Sample per rasterline; `per_frame_freqs` is a list of frames, each
    a list of 312 voice-0 freq values."""
    out = []
    for frame in per_frame_freqs:
        for f in frame:
            out.append(V.Sample(voices=[V.VoiceLine(freq=f), V.VoiceLine(),
                                        V.VoiceLine()]))
    return out


def _split(a, b, na):
    return [a] * na + [b] * (312 - na)


def test_a_half_and_half_octave_frame_is_counted_on_its_voice():
    # the first frame has no predecessor to count a boundary change against
    frames = _frames([_split(0x1168, 0x22D0, 156)] * 4)
    assert V.octave_split_frames(frames) == [3, 0, 0]


def test_a_once_a_frame_toggle_at_mid_frame_is_not_a_trill():
    """The original's own player: one write a frame at line 133, hist 133/179
    in every frame -- the false positive that put 537 on Last_V8's original."""
    a, b = 0x1168, 0x22D0
    toggle = [_split(a, b, 133), _split(b, a, 133)] * 4
    assert V.octave_split_frames(_frames(toggle)) == [0, 0, 0]


def test_a_steady_frame_and_a_note_change_are_not_octave_splits():
    steady = _split(0x1168, 0x1168, 156)
    # a note change late in the frame: a minor share below the threshold
    change = _split(0x1168, 0x22D0, 311 - 200)
    assert V.octave_split_frames(_frames([steady, change])) == [0, 0, 0]


def test_a_non_octave_pair_is_not_counted():
    fifth = _split(0x1168, 0x1A2C, 156)   # 3:2
    assert V.octave_split_frames(_frames([fifth])) == [0, 0, 0]


def test_the_minority_threshold_is_120_lines():
    assert V.octave_split_frames(_frames([_split(0x1168, 0x22D0, 120)] * 2)) == [1, 0, 0]
    assert V.octave_split_frames(_frames([_split(0x1168, 0x22D0, 119)] * 2)) == [0, 0, 0]


def test_three_values_in_one_frame_are_not_a_two_value_frame():
    fr = [0x1168] * 100 + [0x22D0] * 100 + [0x1234] * 112
    assert V.octave_split_frames(_frames([fr])) == [0, 0, 0]


def test_a_sign_extended_member_is_rebuilt_from_its_whole_partner():
    # 0x22D0 is whole; its half 0x1168 dumps as 0x1168 (lo < $80) but 0x0DD0/2..
    # use 0x1BA0 (lo >= $80) whose octave 0x3740 is whole: 0xFFA0 is the dump.
    assert V._octave_partner(0xFFA0, 0x3740)
    assert not V._octave_partner(0xFFA0, 0x3A40)
    # two damaged values are refused, and a tiny pair is not a note
    assert not V._octave_partner(0xFFFD, 0xFFFC)
    assert not V._octave_partner(0x0003, 0x0006)


def test_silent_lines_are_not_a_value():
    fr = [0] * 100 + _split(0x1168, 0x22D0, 106)[:212]
    assert V.octave_split_frames(_frames([fr])) == [0, 0, 0]
