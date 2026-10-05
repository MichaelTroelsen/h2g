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
    8-bit and unaffected. `parse` repairs `.pulse` and `.adsr` by continuity
    (`repair_sign_extension`); `.freq` stays raw for
    `fidelity.vice_freq_repair`, which has siddump as an oracle.
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


def vsid_timeout(seconds: float) -> float:
    """Wall-clock ceiling for one vsid dump of `seconds` of tune.

    A flat 300 s killed Thrust's 400 s trace, so a window reaching its only
    octave trill (328.7 s) could not be taken at all: the ceiling scales with
    the window, 300 s being the floor it always was.
    """
    return max(300.0, 3.0 * seconds)


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
        capture_output=True, timeout=vsid_timeout(seconds), stdin=subprocess.DEVNULL)
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
    _repair_pulse_adsr(samples)
    return samples


def repair_sign_extension(raw: list[int], attacks: list[int]) -> list[int]:
    """Rebuild the high bytes the dump's sign extension destroyed, by continuity.

    A corrupt run is a maximal stretch of `sign_extended` samples. The true
    high byte only changes when the low byte wraps `$FF -> $00`, which ends a
    run, so a run takes the lower of its neighbours' high bytes (they agree or
    differ by one). Neighbours on the far side of a gate rise (`attacks`) are
    another note and are ignored; a run with no anchor takes the nearest
    correct sounding sample, else 0. Neighbours differing by more than one
    (a jump inside a note) take the high byte nearest the straight line between
    them. `fidelity.vice_freq_repair` is the frequency version, which also has
    siddump as an oracle; pulse and ADSR have none under `--vice`, so this is
    continuity alone.
    """
    n = len(raw)
    out = list(raw)
    atk = sorted(set(attacks))
    i = 0
    while i < n:
        if not sign_extended(raw[i]):
            i += 1
            continue
        s = i
        while i < n and sign_extended(raw[i]):
            i += 1
        e = i
        note_start, note_end = 0, n
        for a in atk:
            if a <= s:
                note_start = a
            else:
                note_end = a
                break
        before = raw[s - 1] if s - 1 >= note_start else None
        after = raw[e] if e < note_end else None
        if before is not None and after is not None:
            hb, ha = before >> 8, after >> 8
            if abs(hb - ha) <= 1:
                his = [min(hb, ha)] * (e - s)
            else:
                lo_h, hi_h = min(hb, ha), max(hb, ha)
                his = []
                for k in range(s, e):
                    t = (k - (s - 1)) / (e - (s - 1))
                    target = before + (after - before) * t
                    lo = raw[k] & 0xFF
                    his.append(min(range(lo_h, hi_h + 1),
                                   key=lambda h: abs(((h << 8) | lo) - target)))
        elif before is not None:
            his = [before >> 8] * (e - s)
        elif after is not None:
            his = [after >> 8] * (e - s)
        else:
            j = s - 1
            while j >= 0 and (sign_extended(raw[j]) or not raw[j]):
                j -= 1
            k = e
            while k < n and (sign_extended(raw[k]) or not raw[k]):
                k += 1
            cands = [(s - j, j)] if j >= 0 else []
            if k < n:
                cands.append((k - e + 1, k))
            his = [(raw[min(cands)[1]] >> 8) if cands else 0] * (e - s)
        for k, h in zip(range(s, e), his):
            out[k] = (h << 8) | (raw[k] & 0xFF)
    return out


def _repair_pulse_adsr(samples: list[Sample]) -> None:
    """Repair `.pulse` and `.adsr` in place, voice by voice. `.freq` is left
    raw: `fidelity.vice_freq_repair` repairs it against siddump."""
    for vi in range(max((len(s.voices) for s in samples), default=0)):
        idx = [i for i, s in enumerate(samples) if vi < len(s.voices)]
        if not idx:
            continue
        atk, prev = [], 0
        for p, i in enumerate(idx):
            g = samples[i].voices[vi].ctrl & 1
            if g and not prev:
                atk.append(p)
            prev = g
        for attr in ("pulse", "adsr"):
            raw = [getattr(samples[i].voices[vi], attr) for i in idx]
            if not any(sign_extended(x) for x in raw):
                continue
            for i, val in zip(idx, repair_sign_extension(raw, atk)):
                setattr(samples[i].voices[vi], attr, val)


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
OCTAVE_MAX_SHIFT = 3          # 2^k with k <= 3: up to +36 semitones (Devils_Galop's
                              # arp is +24, a ratio of 4). Not a ratio of 3:2.


def _octave_verdict(a: int, b: int,
                    whole: frozenset[int] | set[int] = frozenset()) -> bool | None:
    """Is one dumped freq (about) 2^k times the other, k = 1..OCTAVE_MAX_SHIFT:
    True, False, or None when the dump cannot say.

    k > 1 is a trill across more than one octave: Devils_Galop's ticked arp is
    +24 semitones, `$106E` against `$41B8` (dumped `$FFB8`), a ratio of 4 that
    a ratio-2 test read as no octave at all. Such a pair reads None, not True,
    while one member is sign-extended, so the dump alone shows it as blind;
    `fidelity.vice_oracle_samples` rebuilds the member where siddump saw it.

    A `sign_extended` value's high byte is destroyed, and nothing in the dump
    can recover it: VICE prints a freq whose low byte has bit 7 set as `$FFxx`
    EVERY time (`sign_extended`), so no sighting of the same value elsewhere
    in the trace is whole. Its low byte can still REFUTE an octave -- no high
    byte makes it one -- but a match proves nothing, since the high byte that
    makes it an octave is the one it was rebuilt to have. Through v0.5.496 such a
    pair was accepted on that match alone: Formula_1_Simulator's held A#3
    `$0F82` (dumped `$FF82`) against its own one-call drops `$0F02`/`$0D02`
    rebuilt as `$0782`, half of `$0F02` within 1, and put 32 false frames on
    ours at -t 180 (siddump reads `$0F82`). So a pair with a sign-extended
    member is None unless its low byte refutes it, and so is a pair of two
    (a low-byte match admitted `$FFFD`/`$FFFC`, a ~1-unit wobble). Both are
    blindnesses of the dump, not of the octave test; the oracle that could
    settle them is siddump's high byte (`fidelity.vice_freq_repair`).

    `whole` names values that LOOK sign-extended but whose `$FF` high byte
    siddump confirmed (`fidelity.vice_oracle_repair`): a slide past `$FF80`
    is really there. Without it such a value stays None for ever, however
    many times the oracle read it -- Last_V8's top-of-slide `$FFFD`/`$FFFC`,
    which siddump also prints `FFFD`/`FFFC`, kept 17 frames blind at -t 45
    (be0aeb1).
    """
    ea = sign_extended(a) and a not in whole
    eb = sign_extended(b) and b not in whole
    if any(x < OCTAVE_MIN_FREQ for x, e in ((a, ea), (b, eb)) if not e):
        return False
    if ea and eb:
        return None
    if ea or eb:
        ext, whole = (a, b) if ea else (b, a)
        lo = ext & 0xFF
        for k in range(1, OCTAVE_MAX_SHIFT + 1):
            for want in (whole << k, whole >> k):
                # an octave above $8000 is not a 16-bit freq: Devils_Galop's
                # `$817D` "matched" `$FFFA` as `$102FA` (16 frames through
                # v0.5.496)
                if want > 0xFFFF:
                    continue
                real = ((want >> 8) << 8) | lo
                # the table's rounding error sits on the LARGER member: it
                # grows with k when `want` is the larger, and shrinks to
                # ~1 unit when `want` is the smaller (Formula_1's `$FF82`
                # against `$0E02` read `$0380` -> `$0382`, 2 off, as an
                # octave pair two octaves down: it must stay refuted)
                tol = 3 + (1 << (k - 1)) - 1 if want > whole else max(1, 3 >> (k - 1))
                if abs(real - want) <= tol:
                    return None
        return False
    lo_v, hi_v = sorted((a, b))
    if lo_v == 0:
        return False
    # k octaves is a ratio of 2^k; the rounding of the player's note table
    # doubles with each one, so the tolerance scales with it.
    return any(abs(hi_v - (lo_v << k)) <= ((2 << (k - 1)) + (hi_v >> 10))
               for k in range(1, OCTAVE_MAX_SHIFT + 1))


def _octave_partner(a: int, b: int) -> bool:
    """True only when the dump shows one freq is (about) 2^k times the other --
    `_octave_verdict` is True, never None."""
    return _octave_verdict(a, b) is True


def octave_split_frames(samples: list, voices: int = 3,
                        minority: int = OCTAVE_MINORITY_LINES,
                        blind: list[int] | None = None,
                        first: list[int | None] | None = None,
                        whole: list[set[int]] | None = None) -> list[int]:
    """Per voice: frames that hold a note and its octave in two halves.

    All of: exactly two freq values (silent lines are not values) an octave
    apart and at least `OCTAVE_MIN_FREQ`; the rarer on >= `minority` of the 312
    lines; and **two or more value changes** counted from the previous frame's
    last line. The last one is what separates a trill from an ordinary
    once-a-frame toggle: a player writing `b U b U` a frame apart, at a write
    line of 133, reads 133/179 lines in every frame -- the same hist -- but
    changes value once a frame, where a per-call loop at `-S2` changes twice
    (a b | a b), whatever the frame's phase against the loop.

    A frame of that shape whose interval the dump cannot read
    (`_octave_verdict` None: a sign-extended member) is not counted; pass a
    list as `blind` to have those frames tallied into it per voice instead of
    lost silently.

    Pass a list as `first` to have, per voice, the index of the first frame
    that is counted (None where none is): an osplit of 0 is a statement about
    the window only if the trace reaches the frame where the shape first
    plays -- Thrust's only octave trill starts at 328.7 s.

    `whole`, per voice, is the set of sample indices whose freq siddump
    confirmed (`fidelity.vice_oracle_repair`). A value in a frame is read as
    whole -- not sign-extended -- only when EVERY sample of it in that frame
    is confirmed, so one unconfirmed `$FFxx` sample keeps the frame blind.
    """
    counts = [0] * voices
    if blind is not None:
        blind[:] = [0] * voices
    if first is not None:
        first[:] = [None] * voices
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
                if min(na, nb) >= minority and changes >= 2:
                    ok: set[int] = set()
                    seen = whole[v] if whole is not None and v < len(whole) else None
                    if seen:
                        for val in (fa, fb):
                            if sign_extended(val) and all(
                                    start + i in seen
                                    for i, f in enumerate(seq) if f == val):
                                ok.add(val)
                    verdict = _octave_verdict(fa, fb, ok)
                    if verdict is True:
                        counts[v] += 1
                        if first is not None and first[v] is None:
                            first[v] = start // n
                    elif verdict is None and blind is not None:
                        blind[v] += 1
            last = [f for f in seq if f]
            prev = last[-1] if last else 0
    return counts
