"""The classic vibrato's swing: centred by `bound >> 1`, free-running phase.

Opened by lvvp-0aa0-and-spellbound-afff (head 3b1c66d): Las_Vegas_Video_Poker's
$0AA0 and $6B9A records vibrate in the original from six equally frequent
start phases and swing about -1..+2 steps, where ours start from one. Measured
by lvvp-vibrato-phase (C:/t/lvvp-vibrato-phase/phase.py, base.txt, 120 s,
original at -m1, ours under presets packed at -S4). Units are the original's
depth `(f(n) - f(n-1)) >> 2`. Phase is (the offset at frame 1, the direction
of the first move).

    $6B9A orig 305 notes  six phases 49..53 each   swing -1..+2 on 303
          ours 305 notes  one phase (0, up) 305    swing -1..+1 on 280
    $0AA0 orig  80 notes  six phases               swing -1..+2 on 56
          ours  84 notes  one phase (0, up) 84     swing -1.5..+1.5 on 82

The mechanism is the player's apply loop. It subtracts `bound >> 1` depths
from the note and then adds `ctr` depths back, so the peak-to-peak is
`bound * depth` and an odd bound is lopsided. Its counter is per voice and
nothing resets it at a note. Goattracker's speed-table vibrato can carry
neither property: it is centred on the note, and `vibtime` is zeroed on every
wavetable note step (gplay.c:723). Both are written beside
`_classic_vibrato_entry` and pinned here. The emitted `rshift` is the one the
`bound * depth` peak-to-peak asks for.
"""
import pathlib
import sys
from collections import Counter

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from h2g.detect import VIBRATO_SHAPES, _shape_matches        # noqa: E402
from h2g.goatwriter import _classic_vibrato_entry            # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")


# (bound cell, counter cell, subtract-loop address, add-loop address), read
# off the disassembly (python/dis6502.py) of each player.
APPLY_LOOPS = {
    "Las_Vegas_Video_Poker": (0x54FA, 0x54DD, 0x522A, 0x5251),
    "Warhawk": (0x15C3, 0x1590, 0x1251, 0x1278),
}


def _bytes_at(sid, addr, n):
    off = sid.to_offset(addr)
    return bytes(sid.data[off:off + n])


@needs_corpus
@pytest.mark.parametrize("name", sorted(APPLY_LOOPS))
def test_the_apply_loop_subtracts_half_the_bound_then_adds_the_counter(name):
    bound, ctr, sub, add = APPLY_LOOPS[name]
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    lo, hi = bound & 0xFF, bound >> 8
    # LDA bound,X / LSR / TAY / DEY / BMI +$16 / SEC
    assert _bytes_at(sid, sub, 9) == bytes(
        [0xBD, lo, hi, 0x4A, 0xA8, 0x88, 0x30, 0x16, 0x38]), name
    # ... freq -= depth ... JMP back to the DEY
    assert _bytes_at(sid, sub + 0x1B, 3) == bytes([0x4C, (sub + 5) & 0xFF,
                                                   (sub + 5) >> 8]), name
    lo, hi = ctr & 0xFF, ctr >> 8
    # LDY ctr,X / DEY / BMI +$16 / CLC ... ADC depth ... JMP back to the DEY
    assert _bytes_at(sid, add, 7) == bytes(
        [0xBC, lo, hi, 0x88, 0x30, 0x16, 0x18]), name
    assert _bytes_at(sid, add + 7, 1) == b"\xAD"
    assert _bytes_at(sid, add + 10, 1) == b"\x6D"            # ADC, not SBC
    assert _bytes_at(sid, add + 0x19, 3) == bytes([0x4C, (add + 3) & 0xFF,
                                                   (add + 3) >> 8]), name
    # The split stores the bound to the cell the subtract loop reads, and
    # the counter update steps the cell the add loop reads.
    # `_shape_matches` returns the index into `sid.data` (the PHA).
    split = min(at for s in VIBRATO_SHAPES for at in _shape_matches(sid.data, s))
    assert sid.data[split + 6:split + 9] == bytes([0x9D, bound & 0xFF, bound >> 8])
    upd = sid.data[split + 15:split + 23]
    assert upd[0] == 0xBD and upd[3] == 0x10 and upd[5] == 0xDE, name
    assert upd[6] | upd[7] << 8 == ctr, name


@needs_corpus
def test_every_classic_vibrato_player_carries_both_loops():
    """Over the corpus files the split matches (61 at lvvp-vibrato-phase):
    each has the subtract loop, then a `DEY / BMI / CLC` add loop after it.
    """
    files = 0
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        hits = [at for s in VIBRATO_SHAPES for at in _shape_matches(data, s)]
        if not hits:
            continue
        files += 1
        at = min(hits)
        window = bytes(data[at:at + 200])
        sub = next((i for i in range(len(window) - 6)
                    if window[i:i + 4] == b"\x4A\xA8\x88\x30"
                    and window[i + 5] == 0x38), -1)
        assert sub >= 0, path.name
        add = next((i for i in range(sub, len(window) - 4)
                    if window[i:i + 2] == b"\x88\x30" and window[i + 3] == 0x18), -1)
        assert add > sub, path.name
    assert files >= 56


def _gt_swing(entry, interval):
    """Peak-to-peak and centre of gplay.c:795-801 over four periods."""
    cmp_value, rshift = entry
    assert cmp_value & 0x80                                  # note-relative
    cmp_value &= 0x7F
    speed = interval >> rshift
    vibtime, freq, seen = 0, 0, [0]
    for _ in range(8 * (cmp_value + 2)):
        if vibtime < 0x80 and vibtime > cmp_value:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        freq += -speed if vibtime & 1 else speed
        seen.append(freq)
    return max(seen) - min(seen), (max(seen) + min(seen)) / 2, speed


@pytest.mark.parametrize("multiplier", [1, 2, 4])
@pytest.mark.parametrize("shift", [0, 1, 2, 3])
@pytest.mark.parametrize("bound", [1, 2, 3, 4, 5, 7, 8, 15])
def test_the_emitted_swing_is_bound_depths_peak_to_peak(bound, shift, multiplier):
    """The player's swing is `bound * depth` (`ctr - (bound >> 1)` depths,
    ctr 0..bound). The emitted entry, run through Goattracker's loop at
    `row_calls` 0, swings the same. The interval is a power of two, so the
    shifts are exact.
    """
    if bound * multiplier < 2:
        pytest.skip("cmp clamps at 0: Goattracker's shortest half-period is "
                    "two calls")
    interval = 1 << 12
    depth = interval >> shift
    entry = _classic_vibrato_entry((bound << 3) | shift, multiplier)
    p2p, centre, speed = _gt_swing(entry, interval)
    assert p2p == bound * depth
    # Goattracker centres on the note (within one step). The player centres
    # on `bound / 2 - (bound >> 1)` depths above it: half a depth for an odd
    # bound. That is the half-depth no speed-table entry can carry.
    assert abs(centre) <= speed
    player = [c - (bound >> 1) for c in range(bound + 1)]
    assert (max(player) + min(player)) / 2 == (bound % 2) / 2


def _start_phases(trace, adsr, frames, shift):
    """{(offset at frame 1, first move)} and {(min, max)} over `adsr`'s notes,
    in the original's depth units, read against the player's own table.
    """
    sid = load_sid(str(CORPUS / "Las_Vegas_Video_Poker.sid"))
    o = sid.to_offset(0x53F9)
    tbl = [sid.data[o + 2 * n] | (sid.data[o + 2 * n + 1] << 8) for n in range(96)]
    import math

    def timeline(ev):
        out, cur, evs, j = [None] * frames, None, sorted(ev), 0
        for f in range(frames):
            while j < len(evs) and evs[j][0] <= f:
                cur = evs[j][1]
                j += 1
            out[f] = cur
        return out

    phases, swings = Counter(), Counter()
    for voice in trace:
        fq, ad, wf = (timeline(voice.freq_events), timeline(voice.adsr_events),
                      timeline(voice.wf_events))
        starts = [f for f in range(1, frames) if wf[f] is not None and wf[f] & 1
                  and not ((wf[f - 1] or 0) & 1)] + [frames]
        for a, b in zip(starts, starts[1:]):
            if ad[a] != adsr or b - a < 8:
                continue
            seg = [x for x in fq[a:min(b, a + 60)] if x]
            mid = (max(seg[1:]) + min(seg[1:])) / 2
            n = min(range(1, 96), key=lambda k: abs(math.log2(tbl[k] / mid)))
            u = (tbl[n] - tbl[n - 1]) >> shift
            r = [round((x - tbl[n]) / u * 2) / 2 for x in seg]
            d = next((1 if y > r[1] else -1 for y in r[1:] if y != r[1]), 0)
            phases[(r[1], d)] += 1
            swings[(min(r[1:]), max(r[1:]))] += 1
    return phases, swings


@needs_corpus
@needs_siddump
def test_the_original_runs_the_phase_freely_and_swings_lopsided():
    """$6B9A (record 6, vibrato byte $1A: bound 3, shift 2) in the original:
    six start phases, none rarer than a tenth of the notes, and a swing of
    -1..+2 depths. That is the property `_classic_vibrato_entry` documents and
    Goattracker cannot reproduce.
    """
    secs = 60
    trace = fidelity.run_siddump(CORPUS / "Las_Vegas_Video_Poker.sid", secs, 0)
    phases, swings = _start_phases(trace, 0x6B9A, secs * 50, 2)
    n = sum(phases.values())
    assert n >= 100
    assert set(phases) == {(-1, 1), (0, -1), (0, 1), (1, -1), (1, 1), (2, -1)}
    assert min(phases.values()) >= n / 10
    assert swings[(-1, 2)] >= 0.95 * n
