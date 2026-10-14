"""Attack lateness: how long after the gate rises the envelope first moves.

Every register column in `fidelity.py` compares what was WRITTEN. None reads
what the chip DID, so an envelope that starts a note two hundred rasterlines
late scores the same as one that starts on time, provided the same ADSR and
control bytes land in the same frame. That is how `--max-hard-restart` -- which
takes a late-attack class from "almost every note" to "almost none" on Monty,
Thing_on_a_Spring and Last_V8 -- never moved a column and so was never selected
by the preset search (task adsr-attack-delay-fix-candidates, cycle 7).

The reading is ENV3, the envelope generator's output on voice 3, which VICE's
`dump` device prints on every rasterline. Only voice 3 has an ENV3 register, so
each of the three voices is swapped onto voice 3 in turn: ours by exchanging
two orderlists in the .sng, the original by patching its voice-offset table
(`00 07 0E`, the three voices' register-block offsets).

A **rise** is a gate 0 -> 1 edge on the swapped-in voice; its **delay** is the
number of rasterlines to the first ENV3 increase while the gate is up. A rise is
**late** when that delay is `LATE_LINES` or more. 100 lines is a threshold read
off the measured split, not a chip constant: prompt notes sit at a few lines
and late ones cluster near 200 (median 203-207 on Gerry, Monty, Thing and
Last_V8), so nothing real lives near the line. The attack nibbles whose OWN
period is that long (13 and up: 186, 310 and 496 lines) are excluded rather
than scored (`SLOW_ATTACK`).

Measured, not assumed (adsr-attack-delay-fix-candidates, 60 s windows): the
original is prompt almost everywhere (Rasputin 0/293 late, Gerry 0/169, Thing
0/301, Last_V8 0/228, Commando 0/201) and late only where the SID forces it
(Delta, Pandora, Sanxion), so a late ours is a converter defect only where the
original is not.
"""
from __future__ import annotations

import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import vicetrace

LATE_LINES = 100
"""A first-increase delay at or past this many rasterlines is 'late'."""

FALL_WINDOW = 3000
"""A rise whose gate stays up longer than this many lines is not read."""

DRUM_WINDOW = 936
"""A rise followed by noise within this many lines is a drum tick, not a tone."""

WARMUP_LINES = 400
"""Rises in the first lines are the player's own startup, not a note."""

SLOW_ATTACK = 13
"""Attack nibbles from here up have an own period past LATE_LINES."""

VOICE_TABLE = bytes([0x00, 0x07, 0x0E])

_ENV3 = re.compile(r"ENV3:\s+([0-9a-f]{2})")


# --------------------------------------------------------------------------
# the reading, on arrays
# --------------------------------------------------------------------------
@dataclass
class Rise:
    line: int          # rasterline of the gate 0 -> 1 edge
    kind: str          # "tone" | "drum" | "noise"
    env_before: int    # ENV3 on the line before the edge
    delay: int | None  # lines to the first increase, None = never up in gate
    attack: int        # attack nibble in force when the envelope first moved


def find_rises(ctrl: list[int], env: list[int], adsr: list[int]) -> list[Rise]:
    """Every readable gate rise of one voice's per-rasterline trace."""
    n = min(len(ctrl), len(env), len(adsr))
    out: list[Rise] = []
    for r in range(1, n):
        if not ((ctrl[r] & 1) and not (ctrl[r - 1] & 1)):
            continue
        if r < WARMUP_LINES or r + FALL_WINDOW >= n:
            continue
        fall = next((k for k in range(r, r + FALL_WINDOW)
                     if not ctrl[k] & 1), None)
        if fall is None:
            continue
        if ctrl[r] & 0x80:
            kind = "noise"
        elif any((ctrl[k] & 0xFE) == 0x80 for k in range(r, r + DRUM_WINDOW)):
            kind = "drum"
        else:
            kind = "tone"
        up = next((k for k in range(r, fall + 1) if env[k] > env[k - 1]), None)
        at = (adsr[min(r + up, n - 1)] >> 12) & 15 if up is not None else \
            (adsr[r] >> 12) & 15
        out.append(Rise(r, kind, env[r - 1], None if up is None else up - r, at))
    return out


@dataclass
class Stats:
    """One side's tone rises, reduced."""
    rises: int = 0          # tone rises found
    measured: int = 0       # ... with a delay and room to rise
    late: int = 0           # ... delay >= LATE_LINES
    median: int | None = None
    p90: int | None = None
    never_up: int = 0       # gate fell before the envelope moved
    saturated: int = 0      # ENV3 was already $FF at the edge
    slow: int = 0           # excluded: the attack nibble's own period is long
    drums: int = 0
    delays: list[int] = field(default_factory=list, repr=False)

    @property
    def late_fraction(self) -> float | None:
        return self.late / self.measured if self.measured else None


def summarise(rises: list[Rise]) -> Stats:
    s = Stats()
    for r in rises:
        if r.kind == "drum":
            s.drums += 1
        if r.kind != "tone":
            continue
        s.rises += 1
        if r.env_before >= 255:
            s.saturated += 1
        elif r.delay is None:
            s.never_up += 1
        elif r.attack >= SLOW_ATTACK:
            s.slow += 1
        else:
            s.measured += 1
            s.delays.append(r.delay)
    s.late = sum(1 for d in s.delays if d >= LATE_LINES)
    if s.delays:
        ds = sorted(s.delays)
        s.median = int(statistics.median(ds))
        s.p90 = ds[min(len(ds) - 1, int(0.9 * len(ds)))]
    return s


def merge(per_voice: list[Stats]) -> Stats:
    """Pool the three voices' stats (delays concatenated, not averaged)."""
    out = Stats()
    for s in per_voice:
        for k in ("rises", "measured", "late", "never_up", "saturated",
                  "slow", "drums"):
            setattr(out, k, getattr(out, k) + getattr(s, k))
        out.delays += s.delays
    if out.delays:
        ds = sorted(out.delays)
        out.median = int(statistics.median(ds))
        out.p90 = ds[min(len(ds) - 1, int(0.9 * len(ds)))]
    return out


def lateness_delta(orig: Stats, ours: Stats) -> float | None:
    """Ours' late fraction minus the original's, in points; None if either is
    unread. Positive means we start more notes late than the SID did."""
    a, b = orig.late_fraction, ours.late_fraction
    if a is None or b is None:
        return None
    return 100.0 * (b - a)


# --------------------------------------------------------------------------
# putting voice v on voice 3
# --------------------------------------------------------------------------
def swap_sng_voice(sng: bytes, v: int) -> bytes:
    """Exchange voice `v`'s orderlist with voice 3's in every subtune.

    Layout (GTS2 and GTS5 share it up to the tables): 4 magic, three 32-byte
    names, a subtune count, then per subtune three orderlists of
    `[length, entries..., restart]`, the entries ending in `$FF`.
    """
    if v == 2:
        return sng
    p = 4 + 32 * 3
    n = sng[p]
    p += 1
    out = bytearray(sng[:p])
    for _ in range(n):
        lists = []
        for _ch in range(3):
            ln = sng[p]
            chunk = bytes(sng[p:p + ln + 2])
            if len(chunk) != ln + 2 or chunk[-2] != 0xFF:
                raise ValueError("orderlist does not end in $FF at its length")
            lists.append(chunk)
            p += ln + 2
        order = [0, 1, 2]
        order[v], order[2] = 2, v
        for ch in order:
            out += lists[ch]
    out += sng[p:]
    if len(out) != len(sng):
        raise ValueError("voice swap changed the .sng length")
    return bytes(out)


def voice_table_hits(raw: bytes) -> list[int]:
    return [i for i in range(len(raw) - 2) if raw[i:i + 3] == VOICE_TABLE]


def swap_sid_voice(raw: bytes, v: int, hit: int = 0) -> bytes:
    """The original with voice `v` driven through voice 3's registers.

    Patches the `00 07 0E` voice-offset table. Raises IndexError when the file
    has no such table or fewer than `hit + 1` of them.
    """
    if v == 2:
        return raw
    pos = voice_table_hits(raw)[hit]
    tab = [0, 7, 14]
    tab[v], tab[2] = tab[2], tab[v]
    out = bytearray(raw)
    out[pos:pos + 3] = bytes(tab)
    return bytes(out)


# --------------------------------------------------------------------------
# tracing
# --------------------------------------------------------------------------
@dataclass
class Trace:
    ctrl: list[list[int]]   # [voice][line]
    adsr3: list[int]
    env3: list[int]


def trace(sid: Path, seconds: float, subtune: int, scratch: Path,
          exe: str = vicetrace.VSID) -> Trace:
    """One VICE dump, every voice's CTRL plus voice 3's ADSR and ENV3."""
    # unique per file: the three voices of a side are traced concurrently
    txt = scratch / f"{sid.parent.name}_{sid.stem}.vdump.txt"
    samples = vicetrace.run(sid, seconds, subtune, exe, out=txt)
    try:
        env = [int(m.group(1), 16)
               for m in _ENV3.finditer(txt.read_text(encoding="utf-8",
                                                     errors="replace"))]
    finally:
        txt.unlink(missing_ok=True)
    n = min(len(samples), len(env))
    return Trace(
        ctrl=[[s.voices[v].ctrl for s in samples[:n]] for v in range(3)],
        adsr3=[s.voices[2].adsr for s in samples[:n]],
        env3=env[:n])


def rises_on_voice3(t: Trace) -> list[Rise]:
    return find_rises(t.ctrl[2], t.env3, t.adsr3)


def _edges(ctrl: list[int]) -> int:
    return sum(1 for a, b in zip(ctrl, ctrl[1:]) if (b & 1) and not (a & 1))


# A swapped voice must show the unswapped run's voice-v gate edges on voice 3.
# Writes land a few cycles apart when the voices trade places, so an edge on a
# line boundary can fall one line either side: the count is compared, not the
# lines, with this much slack.
SWAP_SLACK = 2


def swap_verified(identity: Trace, swapped: Trace, v: int) -> bool:
    """Did the swap really put voice `v` on voice 3?

    A patch that hit the wrong table, or an orderlist swap the player did not
    follow, leaves voice 3 playing voice 3: its edge count then differs from
    voice v's in the unswapped run (unless the two are identical, in which case
    nothing is lost by calling it verified).
    """
    return abs(_edges(swapped.ctrl[2]) - _edges(identity.ctrl[v])) <= SWAP_SLACK


@dataclass
class SideReading:
    stats: Stats
    voices: dict[int, Stats]
    unswapped: list[int]            # voices whose swap did not verify


def read_side(variants: dict[int, "Path | None"], seconds: float, subtune: int,
              scratch: Path, exe: str = vicetrace.VSID,
              alternatives: dict[int, list[Path]] | None = None,
              jobs: int = 1) -> SideReading:
    """Trace voice 3 of the identity file, then voices 1 and 2 swapped in.

    `variants[v]` is the file with voice v on voice 3 (variants[2] the file
    itself). `alternatives[v]` lists further candidates for v, tried in order
    if the first does not verify (an original with several voice tables).
    `jobs` > 1 runs the side's three first traces at once (one vsid each).
    """
    first = {v: variants.get(v) for v in (0, 1, 2)}
    todo = [v for v in (0, 1, 2) if first[v] is not None]
    if jobs > 1:
        with ThreadPoolExecutor(max_workers=min(jobs, 4)) as pool:
            futs = {v: pool.submit(trace, first[v], seconds, subtune, scratch, exe)
                    for v in todo}
            traced = {v: f.result() for v, f in futs.items()}
    else:
        traced = {v: trace(first[v], seconds, subtune, scratch, exe) for v in todo}
    ident = traced[2]
    per: dict[int, Stats] = {2: summarise(rises_on_voice3(ident))}
    bad: list[int] = []
    for v in (0, 1):
        got = traced.get(v)
        if got is not None and not swap_verified(ident, got, v):
            got = None
        for c in (alternatives or {}).get(v, []) if got is None else []:
            t = trace(c, seconds, subtune, scratch, exe)
            if swap_verified(ident, t, v):
                got = t
                break
        if got is None:
            bad.append(v)
            continue
        per[v] = summarise(rises_on_voice3(got))
    return SideReading(merge(list(per.values())), per, bad)


@dataclass
class FileReading:
    file: str
    orig: SideReading | None = None
    ours: SideReading | None = None
    error: str | None = None
    options: dict = field(default_factory=dict)

    @property
    def delta(self) -> float | None:
        if self.orig is None or self.ours is None:
            return None
        return lateness_delta(self.orig.stats, self.ours.stats)


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------
def _cell(s: Stats) -> str:
    if not s.measured:
        return "-"
    return f"{s.late}/{s.measured} ({s.median})"


def report(readings: list[FileReading], seconds: float, forced: dict | None = None,
           ) -> str:
    out = [
        "# Attack lateness", "",
        f"ENV3 read per rasterline from VICE over {seconds:g} s, each voice "
        f"swapped onto voice 3. A tone rise is **late** when the envelope's "
        f"first increase follows the gate by at least {LATE_LINES} lines; "
        "`late/n (median delay in lines)`. `delta` is ours' late fraction "
        "minus the original's, in points: positive is a converter defect, "
        "zero or negative is the SID's own lateness or none. A `-` is a side "
        "with no readable rise; `unswapped` lists voices whose swap did not "
        "verify and which are NOT in that side's figures.", ""]
    if forced:
        out += [f"Ours converted with the preset plus `{forced}`.", ""]
    out += ["| File | orig | ours | delta | unswapped (orig / ours) |",
            "|---|---|---|---|---|"]
    errs = []
    for r in readings:
        if r.error:
            errs.append(f"- {r.file}: {r.error}")
            continue
        d = r.delta
        out.append(
            f"| {r.file} | {_cell(r.orig.stats)} | {_cell(r.ours.stats)} | "
            f"{'-' if d is None else f'{d:+.0f}'} | "
            f"{r.orig.unswapped or '-'} / {r.ours.unswapped or '-'} |")
    if errs:
        out += ["", "Not read:", *errs]
    read = [r for r in readings if r.delta is not None]
    if read:
        worse = [r for r in read if r.delta >= 10]
        out += ["", f"{len(read)} file(s) read; ours starts at least 10 points "
                f"more notes late than the original on {len(worse)}: "
                + (", ".join(r.file for r in worse) or "none") + "."]
    return "\n".join(out) + "\n"
