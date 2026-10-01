"""Per-rasterline SID register traces, read out of VICE.

siddump samples the registers once per frame whatever the call rate, so a tune
packed at `gt2reloc -S5` has four calls in five discarded and every gate edge
inside them with it. `fidelity.py --equal-calls` works around that for the
*sequence* dimensions by stretching the time axis, but the register dimensions
(wave, adsr, pul, filt, cut) compare frame against frame and cannot survive a
stretch. They need a finer trace instead.

VICE ships one. Its `dump` sound device writes the whole SID state on every
rasterline -- **312 samples per PAL frame** against siddump's one:

    vsid -console -sounddev dump -soundarg out.txt -limitcycles N -tune T f.sid

The output is a seven-line block per rasterline:

    FREQ:   1168 0000 0000
    PULSE:  0800 0000 0000
    CTRL:     41   00   00
    ADSR:   0f00 0000 0000
    FILTER: 0000 RES: 00 MODE/VOL: 0f
    ADC: ff ff
    OSC3: 00 ENV3: a4

No timestamps, and none are needed: PAL has 312 rasterlines a frame, so a
block's index divided by 312 is its frame. That also makes the resolution
exactly one rasterline, which is finer than any play call.

`-limitcycles` is in CPU cycles: 985248 a second on PAL, 19656 a frame.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

VSID = os.environ.get(
    "H2G_VSID",
    r"C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\vsid.exe")
PAL_CYCLES_PER_FRAME = 19656
PAL_LINES_PER_FRAME = 312


def sign_extended(value: int) -> bool:
    """True when a dumped 16-bit field's high byte is the dump's `$FF`, not data.

    VICE 3.9's `dump` device prints every 16-bit field as `(hi << 8) |
    (signed char) lo`: measured on Commando.sid (10 s, 156000 samples x 3
    voices), `$FF` is the high byte of EVERY sample whose low byte has bit 7 set
    (260872 of 260872) and of none other. So `.freq`, `.pulse` and `.adsr` are
    only trustworthy when this is False; when True the real high byte is
    destroyed and only the low byte is data. `.ctrl` and the filter fields are
    8-bit and unaffected. `fidelity.vice_freq_repair` reconstructs a frequency
    stream against siddump; nothing reconstructs pulse or adsr.
    """
    return (value >> 8) == 0xFF and bool(value & 0x80)


_HEX = r"([0-9a-f]{2,4})"
FREQ = re.compile(rf"^FREQ:\s+{_HEX}\s+{_HEX}\s+{_HEX}")
PULSE = re.compile(rf"^PULSE:\s+{_HEX}\s+{_HEX}\s+{_HEX}")
CTRL = re.compile(rf"^CTRL:\s+{_HEX}\s+{_HEX}\s+{_HEX}")
ADSR = re.compile(rf"^ADSR:\s+{_HEX}\s+{_HEX}\s+{_HEX}")
FILT = re.compile(rf"^FILTER:\s+{_HEX}\s+RES:\s+{_HEX}\s+MODE/VOL:\s+{_HEX}")


@dataclass
class VoiceLine:
    """One voice's registers at one rasterline."""
    freq: int = 0
    pulse: int = 0
    ctrl: int = 0
    adsr: int = 0


@dataclass
class Sample:
    voices: list = field(default_factory=list)
    cutoff: int = 0
    res: int = 0
    modevol: int = 0


def run(sid: Path, seconds: float, subtune: int = 0, exe: str = VSID,
        out: Path | None = None) -> list[Sample]:
    """Trace `seconds` of `sid`, one Sample per rasterline.

    `subtune` is 0-based here and 1-based to vsid, as everywhere else in this
    project the two conventions meet.
    """
    out = Path(out or r"C:\t\vice_dump.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    cycles = int(seconds * PAL_CYCLES_PER_FRAME * 50)
    subprocess.run(
        [exe, "-console", "-sounddev", "dump", "-soundarg", str(out),
         "-limitcycles", str(cycles), "-tune", str(subtune + 1), str(sid)],
        capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
    return parse(out.read_text(encoding="utf-8", errors="replace")) \
        if out.exists() else []


def parse(text: str) -> list[Sample]:
    samples: list[Sample] = []
    cur = None
    for ln in text.splitlines():
        m = FREQ.match(ln)
        if m:
            if cur is not None:
                samples.append(cur)
            cur = Sample(voices=[VoiceLine(freq=int(g, 16)) for g in m.groups()])
            continue
        if cur is None:
            continue
        m = PULSE.match(ln)
        if m:
            for v, g in zip(cur.voices, m.groups()):
                v.pulse = int(g, 16)
            continue
        m = CTRL.match(ln)
        if m:
            for v, g in zip(cur.voices, m.groups()):
                v.ctrl = int(g, 16)
            continue
        m = ADSR.match(ln)
        if m:
            for v, g in zip(cur.voices, m.groups()):
                v.adsr = int(g, 16)
            continue
        m = FILT.match(ln)
        if m:
            cur.cutoff, cur.res, cur.modevol = (int(g, 16) for g in m.groups())
    if cur is not None:
        samples.append(cur)
    return samples


def gate_edges(samples: list[Sample], voice: int) -> list[int]:
    """Rasterlines on which this voice's gate bit rises.

    The measurement siddump cannot make on a fast-called tune: a gate that
    rises and falls inside one frame leaves no edge in a once-per-frame
    sample, and this sees 312 samples in that frame.
    """
    out, prev = [], 0
    for i, s in enumerate(samples):
        if voice < len(s.voices):
            g = s.voices[voice].ctrl & 1
            if g and not prev:
                out.append(i)
            prev = g
    return out


def frame_of(index: int) -> int:
    return index // PAL_LINES_PER_FRAME


# --- Per-frame reduction ----------------------------------------------------
#
# The compare functions in fidelity.py walk two *frame-indexed* timelines, so a
# 312-samples-a-frame trace has to be reduced before it can feed them. The
# reduction is not a detail: the two sides write at different rasterlines
# within the frame -- Warhawk's player at lines 8-19, our -S2 conversion at
# 119-126 and 274-284 -- so a rasterline-against-rasterline comparison would be
# reporting that offset rather than the music, and every candidate reduction
# has to be judged on how little it moves when that offset changes.
#
# Measured on eight corpus files spanning multipliers 1-6, shifting our side by
# an inaudible 0-48 rasterlines (H2G-CONVERSION-METHOD.md section 7.nn):
#
#     reduction   mean sd   worst range   verdict
#     last         0.18       2.64 pp     what siddump does -- point sampling
#                                         at the frame edge aliases
#     any          0.09       1.67 pp     saturates: 98.8% on Deep_Strike
#                                         where every other rule reads ~75%
#     majority     0.02       0.09 pp     stable, but a hard vote
#     overlap      0.02       0.13 pp     stable and graded -- the default
#
# `overlap` is the share of the frame on which the two sides hold the same
# value, sum_v min(share_a(v), share_b(v)). It is a comparison of two
# distributions rather than of two instants, which is why moving either side
# within the frame barely touches it.

AGREEMENT_MODES = ("overlap", "majority", "last", "any")


@dataclass
class FrameCell:
    """One register's behaviour over one frame, for one voice.

    `hist` maps value -> rasterlines held, so it sums to PAL_LINES_PER_FRAME;
    `last` is the value in force at the frame boundary, which is what a
    once-per-frame sampler reports.
    """
    hist: Counter = field(default_factory=Counter)
    last: int = 0

    @property
    def majority(self) -> int:
        # Ties break on the value, not on Counter order, so the reduction is
        # deterministic across runs and platforms.
        return max(self.hist, key=lambda v: (self.hist[v], v)) if self.hist else 0

    def representative(self, mode: str = "majority") -> int:
        """One value standing for the frame, for the counting dimensions.

        A count -- noise frames, duty-cycle moves, filtered frames, cutoff
        travel -- needs a definite value per frame, so it cannot use the
        graded rule. `majority` is the stable choice; `last` is the one that
        aliases.
        """
        return self.last if mode == "last" else self.majority


def frame_cells(samples: list, pick, voices: int = 3) -> list:
    """[frame][voice] -> FrameCell, for the register `pick` reads off a voice.

    Whole frames only: a trailing partial frame is dropped rather than scored
    against a full one.
    """
    out = []
    for start in range(0, len(samples) - PAL_LINES_PER_FRAME + 1,
                       PAL_LINES_PER_FRAME):
        block = samples[start:start + PAL_LINES_PER_FRAME]
        row = []
        for vi in range(voices):
            h = Counter()
            for smp in block:
                if vi < len(smp.voices):
                    h[pick(smp.voices[vi])] += 1
            lastsmp = block[-1]
            row.append(FrameCell(
                hist=h,
                last=pick(lastsmp.voices[vi]) if vi < len(lastsmp.voices) else 0))
        out.append(row)
    return out


def frame_cells_global(samples: list, pick) -> list:
    """[frame] -> FrameCell for a register that is not per voice ($D415-$D418)."""
    out = []
    for start in range(0, len(samples) - PAL_LINES_PER_FRAME + 1,
                       PAL_LINES_PER_FRAME):
        block = samples[start:start + PAL_LINES_PER_FRAME]
        h = Counter()
        for smp in block:
            h[pick(smp)] += 1
        out.append(FrameCell(hist=h, last=pick(block[-1])))
    return out


def agreement(a: FrameCell, b: FrameCell, mode: str = "overlap") -> float:
    """How much the two sides agree over one frame, in [0, 1].

    `overlap` is graded; the other three return 0.0 or 1.0 and exist so the
    choice can be measured rather than asserted.
    """
    if mode == "last":
        return float(a.last == b.last)
    if mode == "any":
        return float(bool(set(a.hist) & set(b.hist)))
    if mode == "majority":
        return float(a.majority == b.majority)
    na, nb = sum(a.hist.values()), sum(b.hist.values())
    if not na or not nb:
        return 0.0
    return sum(min(a.hist[v] / na, b.hist.get(v, 0) / nb) for v in a.hist)


# --- Octave trill inside one frame ------------------------------------------
#
# A `-S2` fixed-pitch arpeggio emitted as a per-call two-entry wavetable loop
# toggles the voice's frequency between a note and its octave on every play
# call, i.e. every half frame: a 100 Hz trill the once-per-frame siddump reads
# as a steady tone. Only a per-rasterline trace sees it, and only as a frame
# whose 312 lines hold exactly two frequency values an octave apart, split
# close to half and half.

OCTAVE_MINORITY_LINES = 120   # of 312: the -S2 call boundary sits at ~156
OCTAVE_MIN_FREQ = 0x100       # below this an "octave" is 3 against 4, not a note


def _octave_partner(a: int, b: int) -> bool:
    """True when one dumped freq is (about) twice the other.

    `sign_extended` values have a destroyed high byte, so one is rebuilt from
    its partner's where the partner is whole (the tolerance is a flat 3 because a
    wrong high byte leaves only the low byte to test, which passes ~2.7% of
    random pairs; a real octave is off by 1); two sign-extended values are refused outright -- a low-byte
    match admitted `$FFFD`/`$FFFC`, a ~1-unit wobble, as an octave. Both are
    blindnesses of the dump, not of the octave test.
    """
    ea, eb = sign_extended(a), sign_extended(b)
    if ea and eb:
        return False
    if any(x < OCTAVE_MIN_FREQ for x in (a, b) if not sign_extended(x)):
        return False
    if ea or eb:
        ext, whole = (a, b) if ea else (b, a)
        lo = ext & 0xFF
        for want in (2 * whole, whole // 2):
            real = ((want >> 8) << 8) | lo
            if abs(real - want) <= 3:
                return True
        return False
    lo_v, hi_v = sorted((a, b))
    return lo_v > 0 and abs(hi_v - 2 * lo_v) <= 2 + (hi_v >> 10)


def octave_split_frames(samples: list, voices: int = 3,
                        minority: int = OCTAVE_MINORITY_LINES) -> list[int]:
    """Per voice: frames that hold a note and its octave in two halves.

    All of: exactly two freq values (silent lines are not values) an octave
    apart and at least `OCTAVE_MIN_FREQ`; the rarer on >= `minority` of the 312
    lines; and **two or more value changes** counted from the previous frame's
    last line. The last one is what separates a trill from an ordinary
    once-a-frame toggle: a player writing `b U b U` a frame apart, at a write
    line of 133, reads 133/179 lines in every frame -- the same hist -- but
    changes value once a frame, where a per-call loop at `-S2` changes twice
    (a b | a b), whatever the frame's phase against the loop.
    """
    counts = [0] * voices
    n = PAL_LINES_PER_FRAME
    for v in range(voices):
        prev = 0
        for start in range(0, len(samples) - n + 1, n):
            seq = [s.voices[v].freq if v < len(s.voices) else 0
                   for s in samples[start:start + n]]
            h = Counter(f for f in seq if f)
            if len(h) == 2:
                (fa, na), (fb, nb) = h.items()
                chain = ([prev] if prev else []) + [f for f in seq if f]
                changes = sum(1 for x, y in zip(chain, chain[1:]) if x != y)
                if (min(na, nb) >= minority and changes >= 2
                        and _octave_partner(fa, fb)):
                    counts[v] += 1
            last = [f for f in seq if f]
            prev = last[-1] if last else 0
    return counts
