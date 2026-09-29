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

**ROOT CAUSE, FOUND (not worked around by parsing differently): VICE 3.9's
`dump` sound device itself sign-extends the low byte of every 16-bit field it
prints** -- `(hi << 8) | (signed char) lo` in its own C, so whenever the true
low byte has bit 7 set, the printed high byte reads back as `ff` no matter
what the true high byte was. Confirmed directly off a live trace: running
`vicetrace.run` on `Commando.sid` (v0.5.492 corpus) for 2 seconds gives 31200
`FREQ` blocks, of which 27767 carry at least one `ff` word, e.g.
`FREQ:   0116 2141 ffa9` -- a real `$xxA9` printing with hi `ff` regardless of
what `xx` was. This is a property of the dump driver, present on both an
original `.sid` and one this converter packed; `vicetrace.parse` does not
introduce it. `parse()` is deliberately a FAITHFUL reader of the dump text --
it must not repair the corruption, only report it, so the corruption stays
visible to whatever reads `.freq`/`.pulse`/`.adsr` next
(`fidelity.vice_freq_repair`, for `.freq` only). The `freq_is_corrupt`-named
tests below pin that.
"""
import pathlib
import sys
import threading
from unittest import mock

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


# --- the sign-extended FREQ/PULSE/ADSR hi byte ------------------------------
#
# vicetrace-freq-hi-byte-reads-ff: VICE 3.9's dump driver prints the wrong
# high byte for any 16-bit field whose true low byte is >= $80 -- see the
# module docstring's ROOT CAUSE note. These pin that `parse()` reports the
# corruption verbatim (never repairs it) and that `freq_is_corrupt` names
# the exact predicate the driver's own bug obeys.

# One rasterline's worth of the seven-line block `vicetrace.parse` reads,
# corrupted exactly as VICE 3.9 corrupts it: three real voice-0 frequencies
# used by the task that pinned this ($2BA9, $57A9, $03A9 -- three different
# true high bytes sharing low byte $A9) all print as `FREQ: ffa9 ...`.
CORRUPT_BLOCK = """FREQ:   ffa9 0800 0000
PULSE:  0800 0000 0000
CTRL:     41   00   00
ADSR:   0f00 0000 0000
FILTER: 0000 RES: 00 MODE/VOL: 0f
ADC: ff ff
OSC3: 00 ENV3: a4
"""


def test_parse_reports_the_corrupted_freq_hi_byte_verbatim():
    """`parse()` must not repair the sign extension -- it hands back exactly
    the corrupted `0xFFA9`, three real high bytes ($2B, $57, $03) all
    printing the same way and none of them recoverable from this block
    alone. A parse that "helpfully" reconstructed a high byte here would be
    guessing, and would hide the defect from `fidelity.vice_freq_repair`,
    which needs to know a value IS corrupt before it can fix it."""
    s = V.parse(CORRUPT_BLOCK)
    assert len(s) == 1
    assert s[0].voices[0].freq == 0xFFA9
    assert V.freq_is_corrupt(s[0].voices[0].freq)


def test_parse_leaves_an_uncorrupted_freq_alone():
    """The negative case: `BLOCK`'s own `$1168` has low byte $68, bit 7
    clear, so VICE never sign-extends it and `freq_is_corrupt` must not
    flag it."""
    s = V.parse(BLOCK)
    assert s[0].voices[0].freq == 0x1168
    assert not V.freq_is_corrupt(s[0].voices[0].freq)


def test_freq_is_corrupt_is_hi_ff_and_lo_bit7_set():
    """Pin the exact predicate VICE's own bug applies, over every low byte --
    not just the sampled cases above -- so a change to this function is
    caught even where no fixture happens to exercise it."""
    for lo in range(0x100):
        assert V.freq_is_corrupt(0xFF00 | lo) == bool(lo & 0x80), hex(lo)
    # the predicate must key off the low byte, not merely "hi == 0xff"
    assert V.freq_is_corrupt(0xFF80)
    assert not V.freq_is_corrupt(0xFF7F)


def test_freq_is_corrupt_matches_the_documented_zoolook_measurements():
    """`fidelity.vice_freq_repair`'s docstring records specific values
    measured frame-by-frame against siddump on Zoolook's original at
    v0.5.485: `$0D6D` prints `0d6d` (not corrupt), `$0E33` prints `0e33`
    (not corrupt), and `$0DD0` prints `ffd0`, `$1BA1` prints `ffa1`, `$52BC`
    prints `ffbc` (all corrupt). Pin those exact values so a change to the
    predicate is checked against the same evidence the docstring cites."""
    for v in (0x0D6D, 0x0E33):
        assert not V.freq_is_corrupt(v), hex(v)
    for lo in (0xD0, 0xA1, 0xBC):              # the shared low byte in each pair
        assert V.freq_is_corrupt(0xFF00 | lo), hex(lo)


def test_pulse_and_adsr_fields_are_equally_unrepaired_by_parse():
    """The same corruption reaches `.pulse` and `.adsr` (16-bit fields too),
    and nothing downstream repairs those the way `fidelity.vice_freq_repair`
    repairs `.freq` -- `parse()` must not treat them any differently."""
    block = """FREQ:   0000 0000 0000
PULSE:  ffd0 0000 0000
CTRL:     41   00   00
ADSR:   ffbc 0000 0000
FILTER: 0000 RES: 00 MODE/VOL: 0f
"""
    s = V.parse(block)[0]
    assert s.voices[0].pulse == 0xFFD0
    assert s.voices[0].adsr == 0xFFBC
    assert V.freq_is_corrupt(s.voices[0].pulse)
    assert V.freq_is_corrupt(s.voices[0].adsr)


def test_ctrl_is_an_8_bit_field_never_subject_to_this():
    """`CTRL` prints two hex digits (`_HEX` matches 2-4), so it cannot carry
    the 16-bit sign-extension defect; this is the field the module docstring
    names as trustworthy straight off the dump."""
    s = V.parse(CORRUPT_BLOCK)[0]
    assert s.voices[0].ctrl == 0x41


# --- octave_split_frames -----------------------------------------------------
#
# The sub-frame check of a per-CALL arpeggio toggle under `-S2`: does a frame
# carry two FREQ low bytes an octave apart, split near the half-frame line
# count rather than lopsidedly? Adapted from
# `C:/t/ticked-fixed-arp-at-s2-is-a-/vice_probe.py`.

def _voice_samples(voice0_lows: list[int]) -> list:
    """One `Sample` per rasterline, voice 0's FREQ low byte set from
    `voice0_lows` (hi byte 0, so nothing here is `freq_is_corrupt`),
    voices 1-2 silent at 0."""
    out = []
    for lo in voice0_lows:
        out.append(V.Sample(voices=[V.VoiceLine(freq=lo),
                                     V.VoiceLine(freq=0),
                                     V.VoiceLine(freq=0)]))
    return out


def test_octave_split_frames_is_zero_for_a_steady_note():
    """One value all frame long is not a split of anything."""
    samples = _voice_samples([0x40] * V.PAL_LINES_PER_FRAME)
    total, per_voice = V.octave_split_frames(samples)
    assert total == 0 and per_voice == [0, 0, 0]


def test_octave_split_frames_counts_an_even_octave_split_near_half_frame():
    """156/156 lines, exactly at the call boundary this task is about, and
    the two values are an octave apart (0x80 == 2*0x40 mod 256)."""
    half = V.PAL_LINES_PER_FRAME // 2
    lows = [0x40] * half + [0x80] * (V.PAL_LINES_PER_FRAME - half)
    samples = _voice_samples(lows)
    total, per_voice = V.octave_split_frames(samples)
    assert total == 1 and per_voice == [1, 0, 0]


def test_octave_split_frames_counts_the_wrap_around_octave_direction():
    """The octave relation is checked both ways on purpose: sorting the two
    distinct values ascending does not put the one that is `2*other mod 256`
    on a fixed side when the doubling wraps past $FF. Here 0x81*2 & 0xFF ==
    0x02 -- the SMALLER sorted value is double the LARGER's wraparound, the
    opposite pairing from the plain case above -- so a predicate checking only
    `hi == (lo*2) & 0xFF` misses it."""
    half = V.PAL_LINES_PER_FRAME // 2
    lows = [0x02] * half + [0x81] * (V.PAL_LINES_PER_FRAME - half)
    samples = _voice_samples(lows)
    total, per_voice = V.octave_split_frames(samples)
    assert total == 1 and per_voice == [1, 0, 0]


def test_octave_split_frames_ignores_a_lopsided_split():
    """A minority under SPLIT_MINORITY_LINES is an ordinary one-line-early
    register write settling, not a per-call toggle -- must not count."""
    lows = [0x40] * (V.PAL_LINES_PER_FRAME - 10) + [0x80] * 10
    samples = _voice_samples(lows)
    total, per_voice = V.octave_split_frames(samples)
    assert total == 0 and per_voice == [0, 0, 0]


def test_octave_split_frames_ignores_a_non_octave_two_value_split():
    """Two values split evenly but not an octave apart (a slide, not an
    arpeggio) must not count."""
    half = V.PAL_LINES_PER_FRAME // 2
    lows = [0x40] * half + [0x41] * (V.PAL_LINES_PER_FRAME - half)
    samples = _voice_samples(lows)
    total, per_voice = V.octave_split_frames(samples)
    assert total == 0 and per_voice == [0, 0, 0]


def test_octave_split_frames_reads_the_low_byte_even_when_corrupt():
    """The classifier reads only `freq & 0xFF`, which VICE's sign-extension
    defect never touches -- it only forces the HIGH byte to `$FF` when the
    low byte's own bit 7 is set (`freq_is_corrupt`). A frame built entirely
    from raw words `freq_is_corrupt` calls corrupt (hi forced to `$FF` for
    both values here, since both low bytes have bit 7 set) must classify
    identically to the same low bytes with a clean high byte -- proof this
    needs no `fidelity.vice_freq_repair`."""
    lo, hi = 0xC0, 0x80                     # 0x80 == (0xC0 * 2) & 0xFF
    half = V.PAL_LINES_PER_FRAME // 2
    lows = [lo] * half + [hi] * (V.PAL_LINES_PER_FRAME - half)
    clean = _voice_samples(lows)
    corrupt = [V.Sample(voices=[V.VoiceLine(freq=0xFF00 | v),
                                 V.VoiceLine(freq=0), V.VoiceLine(freq=0)])
               for v in lows]
    assert all(V.freq_is_corrupt(s.voices[0].freq) for s in corrupt)
    assert V.octave_split_frames(clean) == V.octave_split_frames(corrupt)


# --- vicetrace-fixed-dump-path: per-call dump path, not a shared fixed one --

def test_run_default_dump_path_is_unique_per_call():
    """Two calls with no explicit `out` must not both target the old fixed
    `C:/t/vice_dump.txt` -- each gets its own path, so concurrent callers
    never share a dump file."""
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(pathlib.Path(cmd[cmd.index("-soundarg") + 1]))
        return mock.Mock()

    with mock.patch.object(V.subprocess, "run", side_effect=fake_run):
        V.run(pathlib.Path("dummy1.sid"), 0.01)
        V.run(pathlib.Path("dummy2.sid"), 0.01)

    assert len(seen) == 2
    assert seen[0] != seen[1]
    assert all(p != pathlib.Path(r"C:\t\vice_dump.txt") for p in seen)


def test_concurrent_calls_do_not_collide_on_the_dump_path():
    """Two `run()` calls from two threads, each faking `vsid` by writing its
    own distinct block to whatever `-soundarg` path it was given, must each
    read back its own content -- proof the two never wrote the same file."""
    blocks = {
        "a": BLOCK,
        "b": BLOCK.replace("1168", "2222"),
    }
    results = {}
    paths_used = []
    lock = threading.Lock()

    def fake_run(cmd, **kwargs):
        out_path = pathlib.Path(cmd[cmd.index("-soundarg") + 1])
        sid_path = pathlib.Path(cmd[-1])
        key = sid_path.stem
        with lock:
            paths_used.append(out_path)
        out_path.write_text(blocks[key], encoding="utf-8")
        return mock.Mock()

    def worker(key):
        results[key] = V.run(pathlib.Path(f"{key}.sid"), 0.01)

    # Patch once around both threads: two overlapping per-thread patches of
    # the same global restore each other's mock and leak it into later tests.
    threads = [threading.Thread(target=worker, args=(k,)) for k in blocks]
    with mock.patch.object(V.subprocess, "run", side_effect=fake_run):
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert paths_used[0] != paths_used[1]
    assert results["a"][0].voices[0].freq == 0x1168
    assert results["b"][0].voices[0].freq == 0x2222


def test_octave_split_frames_drops_a_trailing_partial_frame():
    lows = ([0x40] * (V.PAL_LINES_PER_FRAME // 2)
            + [0x80] * (V.PAL_LINES_PER_FRAME - V.PAL_LINES_PER_FRAME // 2))
    samples = _voice_samples(lows + lows[:10])   # ten extra rasterlines
    total, _ = V.octave_split_frames(samples)
    assert total == 1


def test_the_envelope_gate_is_immune_to_the_dump_adsr_sign_extension():
    """`depth`'s envelope gate reads the dump's ADSR raw under `--vice`
    (`fidelity.Voice.env_adsr_events`), unrepaired. That is sound only if
    `fidelity.envelope_silent` gives the same verdict on the printed word
    as on the true one, for every true word and both gate states -- pinned
    exhaustively, together with the predicate VICE's own bug applies."""
    import fidelity
    for true in range(0x10000):
        printed = (0xFF00 | (true & 0xFF)) if true & 0x80 else true
        assert V.freq_is_corrupt(printed) == bool(true & 0x80)
        for ctrl in (None, 0x40, 0x41):
            assert fidelity.envelope_silent(printed, ctrl) == \
                fidelity.envelope_silent(true, ctrl), (hex(true), ctrl)
