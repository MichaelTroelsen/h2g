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
