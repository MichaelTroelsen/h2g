"""The `$83` arpeggio block's frame arithmetic above -S1 (`goatwriter.drums._arp_block`).

A step on wavetable call `c` was charged to frame `(c + 1) // multiplier`, which
is the frame the call is in only if the row's tick 0 is the FIRST call of a
frame. The packed player's tick 0 is play call `1 + row_calls * r`
(player.s:573-620), a note's wavetable starts on the call after it, and the
harness samples a frame's LAST call -- so the residue of tick 0 in its frame
(`o`) decides which wavetable calls are sampled, and rows that are not whole
frames (Lion_Heart: 8 calls at -S3) walk `o` through every value.

The tests here simulate the player's call grid independently of `_arp_block`
(call `n` is in frame `n // m`, the sample is the call with `n % m == m - 1`)
and read the block back through it.

Measured at -t 180 under presets, per call (-m1) and lag-aligned to the original,
Lion_Heart (the only file with `$83` arpeggios above -S1), voice 1, the most
common arpeggio shape from the attack, the original's against ours:

    before   orig 0 0 4 0 4 0 4 0 4 0   ours 0 0 0 4 0 4 0 4 0 4   (36 attacks)
    after    orig 0 0 4 0 4 0 4 0 4 0   ours 0 0 4 0 4 0 4 0 4 0   (39 attacks)
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import goatwriter as G                              # noqa: E402

OFFSETS = [0, 5, 11]
# One waveform entry, so the body is one call and the rest is the tail.
SOURCE = [(0x41, 0), (0xFF, 0), (0x00, 0)]
START = 10


def _note(step: int) -> int:
    return (G.WAVE_NOTE_BASE + OFFSETS[step % len(OFFSETS)]) & 0xFF


def _read(mult: int, residue: int, rows_before: int = 5):
    """{attack-relative frame k: the right byte the sample sees}, for a note
    whose tick 0 is song call `n0` with `n0 % mult == residue`."""
    left, right = G._arp_block(SOURCE, OFFSETS, mult, START)
    tail = right[-1] - START          # first tail entry's index in the block
    n0 = rows_before * mult + residue
    attack = (n0 + 1) // mult         # the first audible call is tick 0 + 1
    seen = {}
    for c in range(0, 40 * mult):
        n = n0 + 1 + c
        if n % mult != mult - 1:
            continue
        entry = c if c < tail else tail + (c - tail) % (len(left) - 1 - tail)
        seen[n // mult - attack] = right[entry]
    return seen


@pytest.mark.parametrize("mult", range(1, 11))
def test_every_sampled_call_reads_the_step_of_its_frame_whatever_the_rows_residue(mult):
    """Attack-relative frame `k` reads step `k + 1` (the -S1 convention: call
    `c` is frame `c + 1`), for every residue of the row's tick 0 in its frame."""
    for residue in range(mult):
        seen = _read(mult, residue)
        for k, byte in seen.items():
            if k < 1:
                continue            # the body's own call, before the cycle
            assert byte == _note(k + 1), (mult, residue, k)


def test_the_earlier_shift_read_one_frame_late_on_most_residues():
    """The property above is not vacuous: charging call `c` to
    `(c + 1) // m` -- the arithmetic before this -- misreads a sampled call on
    all but one residue of tick 0 at -S3."""
    mult = 3
    bad = 0
    for residue in range(mult):
        n0 = 5 * mult + residue
        attack = (n0 + 1) // mult
        for c in range(1, 40 * mult):
            n = n0 + 1 + c
            if n % mult == mult - 1:
                k = n // mult - attack
                bad += (c + 1) // mult != k + 1
    assert bad > 0


def test_minus_s1_is_untouched():
    """At -S1 `hold - 1` is 0: the block is the one `(c + 1) // 1` built."""
    left, right = G._arp_block(SOURCE, OFFSETS, 1, START)
    tail = START + 1
    assert right[0] == G.WAVE_NOTE_BASE
    # call 0 is frame 1 less the head -> step 0; tail call c is frame c + 1
    assert [r - G.WAVE_NOTE_BASE for r in right[1:-1]] == [
        OFFSETS[(c + 1) % 3] for c in range(1, 4)]
    assert right[-1] == tail
