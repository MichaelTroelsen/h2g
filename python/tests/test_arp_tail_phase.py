"""The `$83` arpeggio block's tail continues the cycle the body started
(`goatwriter.drums._arp_block`).

The body charges wavetable call `c` to frame `(c + 1 + shift) // m` LESS
`ARP_HEAD_FRAMES`, clamped at 0; the tail charged the same frame WITHOUT the
head. So at the seam between them the cycle jumped `ARP_HEAD_FRAMES` steps -- a
whole number of laps in a 2-step cycle (2 mod 2 = 0, which is why nothing in
the 2-step measurements ever showed it) and a rotation by two in a 3-step one.

Measured at -t 180 on Go_Go_Dash (-S4, arpeggio forced on; presets leave it off),
voice 2, the 22 original attacks whose shape is a 3-step arpeggio
(`0 0 5 11 0 5 ...`), phase of ours against the original, in frames:

    unheaded tail   +1 on 22 of 22
    headed tail      0 on 22 of 22        (tail head 1: +2 on 22 of 22)

The model below is independent of `_arp_block`: the original reads step
`max(0, k + 1 - ARP_HEAD_FRAMES)` of the cycle on attack-relative frame `k`
(call `c` is frame `c + 1` at -S1), and the sampled call of each frame is the
one with `n % m == m - 1` whatever the row's residue.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import goatwriter as G                              # noqa: E402

START = 10
CYCLES = {"trill": [0, 5], "three": [0, 5, 11], "lion_heart": [0, 0, 3],
          "four": [0, 3, 7, 10]}


def _body(entries: int):
    return [(0x41, 0)] * entries


def _read_all(source, offsets, mult, residue, frames=40):
    """{attack-relative frame k: right byte the sample sees}, k >= 1."""
    left, right = G._arp_block(source, offsets, mult, START)
    tail = right[-1] - START
    n0 = 5 * mult + residue
    attack = (n0 + 1) // mult
    seen = {}
    for c in range(0, frames * mult):
        n = n0 + 1 + c
        if n % mult != mult - 1:
            continue
        entry = c if c < tail else tail + (c - tail) % (len(left) - 1 - tail)
        k = n // mult - attack
        if k >= 1:
            seen[k] = right[entry]
    return seen


@pytest.mark.parametrize("mult", range(1, 11))
@pytest.mark.parametrize("entries", [1, 2, 3, 5])
@pytest.mark.parametrize("cycle", sorted(CYCLES))
def test_the_cycle_has_no_seam_between_body_and_tail(mult, entries, cycle):
    offsets = CYCLES[cycle]
    for residue in range(mult):
        seen = _read_all(_body(entries), offsets, mult, residue)
        assert seen
        for k, byte in seen.items():
            want = offsets[max(0, k + 1 - G.ARP_HEAD_FRAMES) % len(offsets)]
            assert byte == (G.WAVE_NOTE_BASE + want) & 0xFF, (
                mult, entries, cycle, residue, k)


@pytest.mark.parametrize("mult", [1, 3, 4])
def test_a_three_step_cycle_reads_each_step_once_per_lap_after_the_head(mult):
    """The shape the originals show, from the attack: the head holds step 0
    (frames 0 and 1), then a -> b -> 0 -> a ... in order, a step per frame --
    the Go_Go_Dash `0 0 5 11 0 5` with the base pitch subtracted."""
    offsets = [0, 5, 11]
    seen = _read_all(_body(1), offsets, mult, 1 % mult)
    steps = [seen[k] - G.WAVE_NOTE_BASE for k in range(1, 13)]
    first = G.ARP_HEAD_FRAMES - 1                 # frame 1 is still step 0
    assert steps[:first] == [0] * first
    ring = steps[first:]
    assert ring[:6] == [5, 11, 0, 5, 11, 0], ring


def test_a_two_step_cycle_is_what_the_unheaded_tail_could_not_show():
    """With the head an even number of frames, 2-step blocks are byte-identical
    to the unheaded arithmetic -- the reason the defect sat unseen."""
    left, right = G._arp_block(_body(1), [0, 5], 1, START)
    unheaded = [(G.WAVE_NOTE_BASE + [0, 5][(c + 1) % 2]) & 0xFF
                for c in range(1, 3)]
    assert G.ARP_HEAD_FRAMES % 2 == 0
    assert right[1:-1] == unheaded
