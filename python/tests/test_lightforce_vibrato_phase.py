"""Lightforce record 6: why the first vibrato step after the fixed pitch is not
a single value (lightforce-vibrato-phase-after-fixed-pitch).

`tests/test_fixed_attack_only.py` and METHOD 7.NEW read the original as
`09C4 x4` then `04D1 04E2 04F3 0504`, the vibrato "from the played note" and
rising from one depth below it, where ours reads `04E2 04E2 04F4 0506`. That
is HALF the original. Traced at -m1 (siddump-rt `-w`, subtunes 0-5 identical
over the record's span, frames 897-1737, 16 onsets, voice 3):

    onset  frame         vibrato after the 4 fixed frames (frames 5..13)
    even   897 + 112 n   04D1 04E2 04F3 0504 0515 0504 04F3 04E2 04D1   (up first)
    odd    953 + 112 n   0504 04F3 04E2 04D1 04C0 04D1 04E2 04F3 0504   (down first)

The vibrato is the classic `$78/$07` counter (`$F292-$F2B4`): the voice's
counter `$F0B0,X` swings 0..bound (record 6: 5) with its direction in
`$F0B6,X`, and the note is `04C0 + 0x11 * counter`. Nothing resets the counter
at a note: the note-init path (`$F14F-$F24E`) never touches it, and the
fetch frame ends in `JMP $F4CA`, past the update, so the counter holds on that
frame. The update keeps running under the `$40` handler's fixed pitch (which
overrides only the register write): 04,03,02,01,00 on the four fixed frames.

So the phase at the start of a note is the phase the last note left. Record 6's
notes are 56 frames apart, 55 of them with the update running, and the
counter's period is 10 (`2 * bound`): 55 mod 10 = 5, half a period, so
consecutive notes begin in ANTIPHASE (counter 4 falling, then counter 1
rising, and again). The phase is not fixed; no single start phase is right on
more than every other note. Goattracker restarts its vibrato at the note
(gplay.c:723) and has no start phase to seed, so this is the "phase" paragraph
of `_classic_vibrato_entry` again, with the extra fact that here the phase is
perfectly periodic in the note index, not scattered.

The first vibrato step of a record-6 note therefore goes DOWN from the played
note on every other onset (`0504` is the first step of the odd onset only
because the counter was 4 and falling; against the note, `04D1` of the even
one is a rise from one depth below). Nothing was emitted for it, and the
measurement says why (see `test_a_fixed_phase_cannot_be_right_on_both`).
"""
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from dis6502 import decode                                   # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

RT = pathlib.Path(fidelity.SIDDUMP_RT)
needs_rt = pytest.mark.skipif(
    not RT.exists(), reason="tools/siddump-rt not built (see its README)")

WRITES = {"STA", "STX", "STY", "INC", "DEC", "ASL", "LSR", "ROL", "ROR"}
COUNTER = range(0xF0B0, 0xF0B3)        # $F0B0,X  the counter
DIRECTION = range(0xF0B6, 0xF0B9)      # $F0B6,X  its direction
UPDATE = (0xF292, 0xF2B5)              # LDA dir,X ... through the turnaround

ONSETS = [897] + list(range(953, 1738, 56))

# The counter -> frequency map the apply loop computes for record 6:
# note $04E2, depth $11 (the next semitone's interval >> 5), bound 5.
BASE, DEPTH, BOUND = 0x04E2, 0x11, 5


def _freq(counter):
    return BASE - (BOUND >> 1) * DEPTH + counter * DEPTH


def _triangle(start, up, n):
    """The counter walk from `start` (the value just written, direction `up`)."""
    out, c = [], start
    for _ in range(n):
        out.append(c)
        if up:
            c += 1
            if c >= BOUND:
                c, up = BOUND, False
        else:
            c -= 1
            if c <= 0:
                c, up = 0, True
    return out


@needs_corpus
def test_only_the_update_writes_the_counter_and_direction():
    """Static: across the whole play routine `$F0BF-$F4F5` (which holds the
    note-init path `$F14F-$F24E`) the counter and direction cells are written
    by the update alone, so a note start cannot reset the phase."""
    sid = load_sid(str(CORPUS / "Lightforce.sid"))
    a, stores = 0xF0BF, []
    while a < 0xF4F6:
        ins = decode(sid.data, sid.to_offset(a), a)
        assert ins.mnemonic != "???", hex(a)
        if (ins.mnemonic in WRITES and ins.mode in ("abx", "abs", "aby")
                and ins.operand in (*COUNTER, *DIRECTION)):
            stores.append((a, ins.mnemonic, ins.operand))
        a += ins.size
    assert [s[0] for s in stores] == [
        0xF297, 0xF29C, 0xF2A1, 0xF2AC, 0xF2AF, 0xF2B2]
    assert all(UPDATE[0] <= s[0] < UPDATE[1] for s in stores)
    assert not any(0xF14F <= s[0] <= 0xF24E for s in stores)


@needs_corpus
def test_the_update_is_skipped_for_a_record_without_a_vibrato_byte():
    """Static: `$F27B LDA $F61D,Y / BNE / JMP $F329` -- a record whose `+5`
    byte is zero never reaches the update, so the counter FREEZES while such
    an instrument plays (it reads 04 for the whole of 885-896) and the next
    record-6 note inherits it."""
    sid = load_sid(str(CORPUS / "Lightforce.sid"))
    at = sid.to_offset(0xF27B)
    assert bytes(sid.data[at:at + 8]) == bytes(
        [0xB9, 0x1D, 0xF6, 0xD0, 0x03, 0x4C, 0x29, 0xF3])


@needs_corpus
def test_the_fetch_frame_ends_past_the_update():
    """Static: the note-init path `$F24E JMP $F4CA` skips the update (and the
    `$40` handler at `$F4A1`), so the fetch frame advances nothing."""
    sid = load_sid(str(CORPUS / "Lightforce.sid"))
    at = sid.to_offset(0xF24E)
    assert bytes(sid.data[at:at + 3]) == bytes([0x4C, 0xCA, 0xF4])


def _trace(secs=40):
    cells = ["f5ce", "f5cf", "f5d0", "f0b0", "f0b1", "f0b2", "f0b6", "f0b7",
             "f0b8", "f5fc", "f5fd", "f5fe"]
    out = subprocess.run(
        [str(RT), str(CORPUS / "Lightforce.sid"), "-a0", f"-t{secs}",
         "-w" + ",".join(cells)], capture_output=True, text=True).stdout
    freq, ctr, dirn, left, inst = {}, {}, {}, {}, {}
    cur = "0000"
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 7 or not parts[1].strip().isdigit():
            continue
        fr = int(parts[1])
        f = parts[4].split()[0]
        if f != "....":
            cur = f
        w = parts[6].split()
        freq[fr] = int(cur, 16)
        inst[fr] = int(w[2], 16)
        ctr[fr] = int(w[5], 16)
        dirn[fr] = int(w[8], 16)
        left[fr] = int(w[11], 16)
    return freq, ctr, dirn, left, inst


@pytest.fixture(scope="module")
def trace():
    return _trace()


@needs_corpus
@needs_rt
def test_the_counter_holds_on_the_fetch_frame_and_runs_under_the_fixed_pitch(
        trace):
    freq, ctr, dirn, left, inst = trace
    for f0 in ONSETS:
        assert inst[f0] == 6 and left[f0] == 4, f0     # the record, frames=4
        assert ctr[f0] == ctr[f0 - 1], f0              # held on the fetch frame
        assert dirn[f0] == dirn[f0 - 1], f0
        # four fixed frames, the counter walking underneath them
        assert [freq[f0 + i] for i in range(1, 5)] == [0x09C4] * 4, f0
        walk = _triangle(ctr[f0], dirn[f0] == 0, 6)
        assert [ctr[f0 + i] for i in range(1, 6)] == walk[1:6], f0


@needs_corpus
@needs_rt
def test_the_two_onset_phases_alternate_and_are_half_a_period_apart(trace):
    freq, ctr, dirn, left, inst = trace
    even = (4, 0xFF)       # counter 4, falling
    odd = (1, 0x00)        # counter 1, rising
    want_even = [0x04D1, 0x04E2, 0x04F3, 0x0504, 0x0515, 0x0504, 0x04F3,
                 0x04E2, 0x04D1]
    want_odd = [0x0504, 0x04F3, 0x04E2, 0x04D1, 0x04C0, 0x04D1, 0x04E2,
                0x04F3, 0x0504]
    assert len(ONSETS) == 16
    for n, f0 in enumerate(ONSETS):
        state = (ctr[f0], dirn[f0])
        got = [freq[f0 + i] for i in range(5, 14)]
        if n % 2 == 0:
            assert state == even and got == want_even, (n, f0)
        else:
            assert state == odd and got == want_odd, (n, f0)
    # the odd walk is the even walk shifted by half the counter's period
    even_walk = _triangle(4, False, 24)
    odd_walk = _triangle(1, True, 24)
    assert odd_walk[:14] == even_walk[5:19]
    assert [_freq(c) for c in even_walk[5:14]] == want_even
    assert [_freq(c) for c in odd_walk[5:14]] == want_odd
    # ... and the frequency is the counter's, 0x11 per step
    assert all(_freq(c) in (w for w in want_even + want_odd) for c in range(6))
    # 56-frame notes, 55 with the update running: 55 mod (2 * bound) = 5
    assert (56 - 1) % (2 * BOUND) == BOUND


def test_a_fixed_phase_cannot_be_right_on_both():
    """Model, in counter units over frames 5..13 after the onset: the summed
    distance of one fixed start phase from BOTH onset phases. Matching either
    exactly leaves the other half a period off; the centre start Goattracker
    gives (phase 2-3) is worse than matching one, and no phase is zero."""
    def tri(p):
        p %= 2 * BOUND
        return p if p <= BOUND else 2 * BOUND - p

    def err(ph, a=1, n=9):
        return sum(abs(tri(ph + i) - tri(a + i))
                   + abs(tri(ph + i) - tri(a + BOUND + i)) for i in range(n))

    scores = {ph: err(ph) for ph in range(2 * BOUND)}
    assert min(scores.values()) > 0
    assert scores[1] == scores[6] == min(scores.values())
    assert scores[2] > scores[1] and scores[3] > scores[1]
