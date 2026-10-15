"""Residue enumeration of the arp and bit-$10 blocks above -S1 (task
instrument-arp-residue-audit-above-s1, runqueue cycle 31).

A note's tick 0 is play call `n0`; its wavetable call `c` is play call
`n0 + 1 + c` (player.s:908-911); the harness samples a frame's LAST call. The
packed player's rows are whole frames only when `row_calls % m == 0` -- the
jmp-gate tunes (Lion_Heart, Saboteur_II, Star_Paws, Rock_Tells: rows of 8 calls
at -S3) walk tick 0 through every residue of its frame. A block built for
whole-frame steps must therefore read the SAME frame sequence at every residue.
`sampled` below is that grid, written independently of the builders.

Findings (corpus, presets, 49 files above -S1, 220 blocks):

* `_pitch_seq_entries`, `_pitch_seq_phased_entries`,
  `_two_stage_pitch_seq_entries`: invariant at every residue in all 17 files
  carrying them (pitch_seq forced where the preset lacks it). The groups they
  emit are `hold` calls from entry 0, and a sample of any call of a group sees
  the same step -- entry 0 is call 1 and a frame's sampled call is entry
  `(m - 2 - res) % m + k * m`, always inside group `k`.
* `_arp_block` (`$83`): invariant except where the SOURCE program is not a
  whole number of frames. Lion_Heart's `41 / 01 / 41` is 4 calls at -S3; the
  tail began on call 4, mid-frame, leaving that frame's first call on the
  body's (head-shifted) step and the rest on the cycle's. FIXED (drums.py pads
  the body to the frame boundary).
* The nibble and fixed duty blocks of the gate-scaled files (Bump_Set_Spike,
  International_Karate, Kentilla, Proteus, Samantha_Fox, Spellbound, Thrust,
  Warhawk, Game_Killer, and Rasputin's `arp_step_calls` clone) step in
  `_gate_calls(m, O)` / clone-step calls, which is not a multiple of `m` BY
  DESIGN: their residue dependence is the gate's own fractional phase, not a
  misaligned block. Not asserted invariant here (see the pins at the bottom).
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import goatwriter as G                                  # noqa: E402
from h2g.detect import Detection, PitchSeq                        # noqa: E402
from h2g.sidfile import SidFile                                   # noqa: E402
from test_call_rate import wave_timeline                          # noqa: E402
from corpus import CORPUS, needs_corpus                           # noqa: E402

START = 10
FRAMES = 24


def sampled(left, right, mult, residue, first=START, frames=FRAMES):
    """[(waveform, note)] the harness reads on frames 0..frames-1 of a note
    whose tick 0 is call `residue` of its frame."""
    calls = wave_timeline(left, right, first=first, calls=(frames + 2) * mult)
    e0 = (mult - 2 - residue) % mult      # first wavetable call on a last call
    return [calls[e0 + k * mult][1:] for k in range(frames)]


def residues_disagree(left, right, mult, first=START, column=1):
    """Residues whose sampled sequence differs from the designed one (1 %
    mult). `column` 1 is the NOTE only: the arp copies the source's waveform
    column verbatim, so a source whose own attack is not whole frames is the
    source's property, not the block's."""
    ref = [x[column] for x in sampled(left, right, mult, 1 % mult, first)]
    return [r for r in range(mult)
            if [x[column] for x in sampled(left, right, mult, r, first)] != ref]


SOURCES = {
    "one_entry": [(0x41, 0)],
    "lion_heart": [(0x41, 0), (0x01, 0), (0x41, 0)],           # 4 calls
    "noise_then_pulse": [(0x81, 0), (0x02, 0x80), (0x41, 0)],  # 5 calls
    "long_delay": [(0x11, 0), (0x05, 0x80), (0x41, 0), (0x41, 0)],
}
OFFSETS = {"trill": [0, 4], "three": [0, 0, 3], "full": [0, 3, 5]}


@pytest.mark.parametrize("mult", range(1, 11))
@pytest.mark.parametrize("src", sorted(SOURCES))
@pytest.mark.parametrize("offs", sorted(OFFSETS))
def test_arp_block_reads_one_frame_sequence_at_every_row_residue(mult, src, offs):
    block = G._arp_block(SOURCES[src], OFFSETS[offs], mult, START)
    assert block is not None
    assert residues_disagree(*block, mult) == []


@pytest.mark.parametrize("mult", range(2, 11))
@pytest.mark.parametrize("src", sorted(SOURCES))
def test_arp_block_tail_starts_on_a_frame_boundary(mult, src):
    """The loop target is a whole number of frames into the block, so the
    wrap lands on the frame structure the first lap had."""
    left, right = G._arp_block(SOURCES[src], [0, 4], mult, START)
    target = right[-1] - START
    calls = sum(1 if b > 0x0F else b + 1 for b in left[:target])
    assert calls % mult == 0, (calls, mult)


def test_lion_heart_source_is_four_calls_and_pads_to_the_frame():
    left, right = G._arp_block(SOURCES["lion_heart"], [0, 0, 3], 3, START)
    # 41, 01(2 calls), 41 = 4 calls, padded by 2 to 6; then 3 offsets x 3 hold
    assert right[-1] - START == 5 and len(left) == 5 + 9 + 1
    assert residues_disagree(left, right, 3) == []


def test_minus_s1_bytes_are_untouched_by_the_padding():
    """`call % 1` is always 0: no -S1 block gains an entry."""
    for src in SOURCES.values():
        left, right = G._arp_block(src, [0, 4], 1, START)
        body = [w for w, _ in src]
        assert len(left) == len(body) + 2 + 1


def _pair_record(pair, frames_per_step):
    STRIDE, INSTR, IDX, PAIRS, BASE = 8, 0x40, 0x100, 0x110, 0x120
    data = bytearray(0x200)
    data[INSTR + 2] = 0x11
    data[INSTR + 7] = 0x10
    data[PAIRS:PAIRS + 2] = bytes(pair)
    sid = SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                  released="r", load_addr=0x1000, subtunes=1)
    det = Detection(instr_start=INSTR, instr_used=1, instr_stride=STRIDE,
                    track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                    pattern_used=0, read_track_version=0)
    det.pitch_seq = PitchSeq(index=IDX, pairs=PAIRS, base=BASE, steps=3,
                             frames_per_step=frames_per_step)
    return sid, det


@pytest.mark.parametrize("mult", range(1, 11))
@pytest.mark.parametrize("fps", [1, 2, 4])
@pytest.mark.parametrize("pair", [(24, 0), (12, 24), (0, 12)])
def test_pitch_seq_entries_read_one_frame_sequence_at_every_residue(mult, fps, pair):
    sid, det = _pair_record(pair, fps)
    left, right = G._pitch_seq_entries(sid, det, 0, 0x11, mult)
    # the block ends where the player's cycle does: loop it on its own start
    left = list(left) + [0xFF]
    right = list(right) + [START]
    assert residues_disagree(left, right, mult) == []


@pytest.mark.parametrize("mult", range(1, 11))
@pytest.mark.parametrize("phases", [(0, 1, 2), (1, 2, 0), (2, 0, 1)])
def test_pitch_seq_phased_entries_read_one_frame_sequence_at_every_residue(mult, phases):
    notes = [G.WAVE_NOTE_BASE, G.WAVE_NOTE_BASE + 12, G.WAVE_NOTE_BASE + 24]
    block = G._pitch_seq_phased_entries(notes, phases, 0x41, mult, START, 255)
    assert block is not None
    left, right = block
    assert residues_disagree(left, right, mult) == []


def _rebased(table, ptr):
    """The table from 1-based row `ptr`, jump targets moved with it, so
    `wave_timeline(first=1)` walks a note that starts there."""
    sub = table[ptr - 1:]
    left = [a for a, _ in sub]
    right = [(b - (ptr - 1)) & 0xFF if a == 0xFF and b else b for a, b in sub]
    return left, right


@needs_corpus
def test_lion_heart_arp_blocks_are_residue_invariant_in_the_converted_song():
    """Every `CMD_SETWAVEPTR` target of the real conversion under its preset
    (the one the audit found misaligned is the first arpeggio of the file)."""
    import json
    from fidelity import _preset_opts
    from h2g.convert import convert
    from songview import parse_sng
    doc = json.load(open(pathlib.Path(__file__).resolve().parents[2]
                         / "presets.json"))
    opts = _preset_opts(doc, "Lion_Heart.sid")
    opts["pack"] = False
    song = parse_sng(convert(str(CORPUS / "Lion_Heart.sid"),
                             log=lambda *a: None, **opts))
    table = song.tables["WTBL"]
    ptrs = sorted({pat[i + 3] for pat in song.patterns
                   for i in range(0, len(pat), 4)
                   if pat[i + 2] == 8 and pat[i + 3]})
    assert len(ptrs) >= 5, ptrs
    bad = [p for p in ptrs
           if residues_disagree(*_rebased(table, p), 3, first=1) != []]
    assert bad == []
