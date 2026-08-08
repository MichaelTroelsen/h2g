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
