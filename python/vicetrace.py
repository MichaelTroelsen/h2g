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

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

VSID = r"C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\vsid.exe"
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
