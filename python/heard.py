"""Heard-instrument agreement: does our conversion play each note's instrument
the way the original does, over its first frames?

`fidelity.py`'s melody asks whether the right notes sound. This asks how each
one is played: a note starts at a gate rise, and its instrument is what the
voice does frame by frame from there -- control byte, pitch relative to the
note, envelope at the start -- plus the hard-restart tail before the next note.
The ideas are MagPlaySID's (`MagPlay.Transcribe.Music`), re-implemented here;
no code is copied. The traces come from `tools/magplay-rt`, which records
every SID write per play call, so a multispeed side is read at its real call
rate rather than sampled once a frame.

Each paired note is scored on every attribute independently (`diffs`). Three
are known-equivalent, not defects:

* `testpre` -- GoatTracker's `$09` gate+test frame before the attack.
* `sr_rel` / `tail_env` -- the deliberate envelope cut
  (`goatwriter/instruments.py`).
* `gated_tick` -- the drum's noise frame written with the gate on above -S1,
  where the original clears it: `wavetable._drum_tick_noise`'s rule, kept
  because a gate-off tick there releases the voice before the SID's ADSR delay
  has let its attack start.

`instr` is the share of original notes whose paired note differs in none of
`CORE`.

Sharpened with four more of MagPlaySID's rules (todo.md, 2026-10-29), each
re-implemented, none copied, each pinned by a test in `tests/test_heard.py`
that fails with its code removed:

1. Pitch is held in four forms per frame (relative to the note, absolute
   semitone, offset from the note's frequency, raw frequency) and two frames
   agree if ANY form matches. `pitch` now means "differs in every form" -- the
   real defect. `pitch_rel` is new and KNOWN: the relative form differs
   somewhere but no frame differs in every form, which is how two sides that
   name a note after different frames of it (a fixed-frequency drum frame, a
   pitch set up in the release) disagree without playing differently.
2. No pitch is read on a silent frame (test bit, or no waveform: it takes the
   next frame's pitch) or after the gate went off, and the note is named only
   after its gated frames. A frame silent on one side only is not compared for
   pitch (`wave` ignores the test bit, so the two sides' frames can still agree).
3. A restrike (gate on at most 2 frames, off at most 2, waveform running and
   envelope unchanged) continues the note instead of starting a new one --
   unless it falls on the side's row grid (its shortest row, a fifth or more of
   its rise gaps): rows of two to four frames play real notes that close.
4. A gate-off inside the note's first row (all but the row's last 2 frames, the
   row length being each side's most common gap between note starts) belongs
   to the instrument: the note is compared up to gate-off plus its SID release
   time, or up to the first silent frame after it. A gate-off at the row's end
   is the tune's note-off, so the note is compared only up to it; that is the
   `gate` versus `tail_len` split.

Not done: telling vibrato from a slide (rule 5, optional).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAGPLAY_RT = Path(os.environ.get(
    "H2G_MAGPLAY",
    HERE / "tools" / "magplay-rt" / "bin" / "Release" / "net8.0" / "magplay-rt.exe"))
LISTEN = HERE.parent / "build" / "listen"

K = 6          # frames of each note's program compared
TAIL = 4       # longest hard-restart tail
C0 = 0x0112    # PAL C-0, a reference only: tuning is fitted per side

RESTRIKE = 2   # longest gate-on and gate-off of a restrike, in frames
# SID release times in ms, indexed by the release nibble (datasheet values)
RELEASE_MS = (6, 24, 48, 72, 114, 168, 204, 240, 300, 750, 1500, 2400,
              3000, 9000, 15000, 24000)

CORE = ("gate", "wave", "ad", "sr_hi", "pitch")
KNOWN = ("testpre", "sr_rel", "tail_env", "gated_tick", "pitch_rel")
ATTRS = CORE + KNOWN + ("tail_len",)


def trace(sid: Path, seconds: float, song: int, out: Path,
          exe: Path = MAGPLAY_RT) -> dict:
    """Run magplay-rt (song 1-based, 0 = the file's start song) and load it."""
    subprocess.run([str(exe), str(sid), str(seconds), str(song), str(out)],
                   check=True, capture_output=True, text=True)
    return json.loads(out.read_text(encoding="utf-8"))


def frames(tr: dict, mult: int) -> tuple[list[list[int]], list[list[bool]]]:
    """End-of-frame $D400-$D418 and, per voice, whether its gate rose in that
    frame -- including off and on again inside one call."""
    regs = [0] * 0x19
    st, rose = [], []
    r = [False] * 3
    for i, w in enumerate(tr["writes"]):
        for k in range(0, len(w), 3):
            reg, val = w[k + 1], w[k + 2]
            if reg < 0x15 and reg % 7 == 4 and (val & 1) and not (regs[reg] & 1):
                r[reg // 7] = True
            if reg < 0x19:
                regs[reg] = val
        if (i + 1) % mult == 0:
            st.append(list(regs))
            rose.append(r)
            r = [False] * 3
    return st, rose


def _freq(f: list[int], b: int) -> int:
    return f[b] | (f[b + 1] << 8)


def tuning(st: list[list[int]]) -> float:
    """The side's detune from C0's grid in semitones: the circular mean of the
    fractional part of every gated tonal frame."""
    s = c = 0.0
    n = 0
    for f in st:
        for v in range(3):
            b = 7 * v
            fr, ctl = _freq(f, b), f[b + 4]
            if fr >= 0x100 and (ctl & 1) and (ctl & 0x70) and not (ctl & 0x88):
                x = 12 * math.log2(fr / C0)
                a = 2 * math.pi * (x - round(x))
                s += math.sin(a)
                c += math.cos(a)
                n += 1
    return 0.0 if n < 16 else math.atan2(s, c) / (2 * math.pi)


def semi(fr: int, tune: float) -> int | None:
    return None if fr < 0x40 else round(12 * math.log2(fr / C0) - tune)


def silent(ctl: int) -> bool:
    """No sound this frame: the test bit holds the oscillator, or no waveform."""
    return bool(ctl & 0x08) or not (ctl & 0xF0)


def release_frames(sr: int) -> int:
    """Play frames (20 ms) a release lasts."""
    return (RELEASE_MS[sr & 15] + 19) // 20


def restruck(st: list[list[int]], rises: list[int], v: int,
             grid: int | None = None) -> set[int]:
    """The rises that strike an earlier note again instead of starting one. A
    rise a whole number of `grid` frames (the side's shortest row) after the
    last is a note on a row, however briefly the one before it sounded."""
    b = 7 * v
    falls = [i for i in range(1, len(st))
             if (st[i - 1][b + 4] & 1) and not (st[i][b + 4] & 1)]
    found: set[int] = set()
    for n in range(1, len(rises)):
        before, rise = rises[n - 1], rises[n]
        if before in found:
            continue
        # >>> rule 3: restrike
        # >>> rule 3b: a strike on a row is a note
        if grid and (rise - before) % grid == 0:
            continue
        # <<< rule 3b
        gone = [f for f in falls if before < f < rise]
        if len(gone) != 1:
            continue
        fall = gone[0]
        if fall - before > RESTRIKE or rise - fall > RESTRIKE:
            continue
        env = (st[before][b + 5], st[before][b + 6])
        if (all(not silent(st[f][b + 4]) and (st[f][b + 5], st[f][b + 6]) == env
                for f in range(fall, rise))
                and (st[rise][b + 5], st[rise][b + 6]) == env):
            found.add(rise)
        # <<< rule 3
    return found


def rise_frames(rose: list[list[bool]], v: int) -> list[int]:
    return [i for i in range(len(rose)) if rose[i][v]]


def shortest_row(rises: list[list[int]]) -> int | None:
    """The shortest gap between two rises that is a fifth or more of the gaps
    of two frames or longer: the side's finest row."""
    gaps = Counter(y - x for rs in rises for x, y in zip(rs, rs[1:]) if 2 <= y - x <= 64)
    total = sum(gaps.values())
    return min((g for g, n in gaps.items() if n * 5 >= total), default=None)


def note_starts(st: list[list[int]], rose: list[list[bool]], v: int,
                grid: int | None = None) -> tuple[list[int], list[int]]:
    """Voice `v`'s note starts and each one's `$09`-style pre-frames. A note is
    anchored on the first frame after its rise that carries a waveform, so a
    `$09` frame before the attack is counted as `testpre` rather than shifting
    the note."""
    b = 7 * v
    rises = rise_frames(rose, v)
    skip = restruck(st, rises, v, grid)
    starts, pre = [], []
    for i in (i for i in rises if i not in skip):
        j = i
        while (j < len(st) - 1 and j - i < 2 and not (st[j][b + 4] & 0xF0)
               and (st[j][b + 4] & 0x08)):
            j += 1
        starts.append(j)
        pre.append(j - i)
    return starts, pre


def row_length(starts: list[list[int]]) -> int:
    """A side's row length in frames: the most common gap between note starts."""
    gaps = Counter(y - x for ss in starts for x, y in zip(ss, ss[1:]) if 2 <= y - x <= 64)
    return min(gaps, key=lambda g: (-gaps[g], g)) if gaps else K


def _named(st: list[list[int]], b: int, lo: int, hi: int,
           tune: float) -> tuple[int | None, int]:
    """The tonal pitch held longest in frames lo..hi-1 and its frequency."""
    best, bfr, bl, i = None, 0, 0, lo
    while i < hi:
        fr, ctl, j = _freq(st[i], b), st[i][b + 4], i
        while j < hi and _freq(st[j], b) == fr:
            j += 1
        if ((ctl & 0x70) and not (ctl & 0x88) and j - i > bl
                and semi(fr, tune) is not None):
            best, bfr, bl = semi(fr, tune), fr, j - i
        i = j
    return best, bfr


def notes(st: list[list[int]], rose: list[list[bool]], v: int,
          tune: float, row: int | None = None, grid: int | None = None) -> list[dict]:
    """Voice `v`'s notes. `row` is the side's row length in frames (default:
    estimated from this voice alone); `grid` its shortest row, which a restrike
    cannot fall on (default: none)."""
    b = 7 * v
    starts, pre = note_starts(st, rose, v, grid)
    if row is None:
        row = row_length([starts])
    in_first = min(K, max(row - 2, min(row, 4)))
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(st)
        tail = 0
        while tail < TAIL and e - 1 - tail > s and not (st[e - 1 - tail][b + 4] & 1):
            tail += 1
        if tail >= TAIL or e - 1 - tail <= s:
            tail = 0
        snd = e - tail
        g = next((i for i in range(s + 1, snd) if not (st[i][b + 4] & 1)), None)
        # >>> rule 4: the window the note is compared over
        if g is not None and g - s < in_first:
            end = min(snd, s + K, g + release_frames(st[g][b + 6]))  # rule 4a
            sil = next((i for i in range(g, end) if silent(st[i][b + 4])), None)  # rule 4b
            if sil is not None:
                end = sil
        else:
            end = min(snd, s + K, g if g is not None else snd)  # rule 4c
        end = max(end, s + 1)
        # <<< rule 4
        # >>> rule 2b: pitch is read only while the gate is on
        gate_end = g if g is not None else snd
        # <<< rule 2b
        held, hfr = _named(st, b, s, gate_end, tune)
        if held is None:
            held, hfr = _named(st, b, s, snd, tune)
        first = semi(_freq(st[s], b), tune)
        if held is None:
            held, hfr = first, _freq(st[s], b)
        # >>> rule 1: pitch forms
        forms: list[tuple | None] = []
        for k in range(s, end):
            fr = _freq(st[k], b)
            p = semi(fr, tune)
            forms.append(None if k >= gate_end else  # rule 2b
                         (None if p is None or held is None else p - held,
                          p, fr - hfr, fr))
        # <<< rule 1
        # >>> rule 2a: a silent frame takes the next frame's pitch
        for i in range(len(forms) - 1, -1, -1):
            if silent(st[s + i][b + 4]):
                forms[i] = forms[i + 1] if i + 1 < len(forms) else None
        # <<< rule 2a
        prog = [(st[s + i][b + 4], None if f is None else f[0], f)
                for i, f in enumerate(forms)]
        quiet = st[snd] if tail else None
        out.append(dict(start=s, testpre=pre[n], held=held, first=first,
                        ad=st[s][b + 5], sr=st[s][b + 6], prog=prog, tail=tail,
                        tailenv=None if quiet is None else (quiet[b + 5] << 8) | quiet[b + 6]))
    return out


def best_lag(on: list[list[dict]], bn: list[list[dict]],
             lags: range = range(-2, 16)) -> int:
    """The lag (our start minus the original's) at which most notes coincide."""
    a = {(v, n["start"]) for v, ns in enumerate(on) for n in ns}
    best = (0, -1)
    for lag in lags:
        hit = sum((v, n["start"] - lag) in a for v, ns in enumerate(bn) for n in ns)
        if hit > best[1]:
            best = (lag, hit)
    return best[0]


def pair(on: list[dict], bn: list[dict], lag: int,
         slack: int = 2) -> tuple[list[tuple[dict, dict | None]], list[dict]]:
    """Each original note to the nearest unused one of ours within `slack`
    frames after `lag`; returns the pairs and our unpaired (invented) notes."""
    used, pairs = set(), []
    bstarts = [n["start"] - lag for n in bn]
    for a in on:
        cand = [(abs(bs - a["start"]), k) for k, bs in enumerate(bstarts)
                if abs(bs - a["start"]) <= slack and k not in used]
        if cand:
            k = min(cand)[1]
            used.add(k)
            pairs.append((a, bn[k]))
        else:
            pairs.append((a, None))
    return pairs, [bn[k] for k in range(len(bn)) if k not in used]


def gated_tick(a: dict, b: dict, multiplier: int) -> bool:
    """Our gate differs from the original's only on frame 1, a noise frame the
    original writes gate-off and we write gated, above -S1."""
    k = min(len(a["prog"]), len(b["prog"]))
    if multiplier <= 1 or k < 2:
        return False
    ga = [a["prog"][i][0] & 1 for i in range(k)]
    gb = [b["prog"][i][0] & 1 for i in range(k)]
    return (bool(a["prog"][1][0] & 0x80) and ga[1] == 0 and gb[1] == 1
            and ga[0] == gb[0] and ga[2:] == gb[2:])


def diffs(a: dict, b: dict, multiplier: int = 1) -> set[str]:
    """Every attribute on which our note `b` differs from the original's `a`."""
    out = set()
    if b["testpre"] and not a["testpre"]:
        out.add("testpre")
    k = min(len(a["prog"]), len(b["prog"]))
    if any((a["prog"][i][0] & 1) != (b["prog"][i][0] & 1) for i in range(k)):
        out.add("gated_tick" if gated_tick(a, b, multiplier) else "gate")
    if any((a["prog"][i][0] & 0xF6) != (b["prog"][i][0] & 0xF6) for i in range(k)):
        out.add("wave")
    if a["ad"] != b["ad"]:
        out.add("ad")
    if (a["sr"] >> 4) != (b["sr"] >> 4):
        out.add("sr_hi")
    if (a["sr"] & 15) != (b["sr"] & 15):
        out.add("sr_rel")
    # >>> rule 1: a frame agrees if any form of its pitch does
    both = [(a["prog"][i][2], b["prog"][i][2]) for i in range(k)
            if a["prog"][i][2] is not None and b["prog"][i][2] is not None
            # >>> rule 2a: a frame silent on one side only has no pitch to compare
            # (wave and gate say what differs there)
            and silent(a["prog"][i][0]) == silent(b["prog"][i][0])
            # <<< rule 2a
            ]
    if any(not any(x == y for x, y in zip(fa, fb)) for fa, fb in both):
        out.add("pitch")
    elif any(fa[0] != fb[0] for fa, fb in both):
        out.add("pitch_rel")
    # <<< rule 1
    if a["tail"] != b["tail"]:
        out.add("tail_len")
    elif a["tail"] and a["tailenv"] != b["tailenv"]:
        out.add("tail_env")
    return out


def compare(orig: dict, ours: dict, mult_o: int, mult_b: int) -> dict:
    """Pair the two traces' notes and count each attribute's differences."""
    so, ro = frames(orig, mult_o)
    sb, rb = frames(ours, mult_b)
    to, tb = tuning(so), tuning(sb)
    grid_o = shortest_row([rise_frames(ro, v) for v in range(3)])
    grid_b = shortest_row([rise_frames(rb, v) for v in range(3)])
    row_o = row_length([note_starts(so, ro, v, grid_o)[0] for v in range(3)])
    row_b = row_length([note_starts(sb, rb, v, grid_b)[0] for v in range(3)])
    on = [notes(so, ro, v, to, row_o, grid_o) for v in range(3)]
    bn = [notes(sb, rb, v, tb, row_b, grid_b) for v in range(3)]
    lag = best_lag(on, bn)
    c = Counter()
    for v in range(3):
        pairs, inv = pair(on[v], bn[v], lag)
        c["invented"] += len(inv)
        for a, b in pairs:
            c["notes"] += 1
            if b is None:
                c["missing"] += 1
                continue
            ds = diffs(a, b, mult_b)
            c.update(ds)
            if not ds & set(CORE):
                c["match"] += 1
    n = c["notes"]
    return dict(lag=lag, instr=c["match"] / n if n else None,
                **{k: c[k] for k in ("notes", "match", "missing", "invented") + ATTRS})


def _sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def _cached_trace(sid: Path, seconds: float, song: int, runs: Path) -> dict:
    """A trace keyed by the file's bytes, window and song, so a rebuilt
    conversion is never read through a stale trace."""
    out = runs / f"{sid.stem}.{_sha(sid)}.s{song}.t{seconds:g}.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    return trace(sid, seconds, song, out)


def staged_pairs(listen: Path, corpus: Path) -> list[tuple[str, Path, int, Path, int, int, int, float]]:
    """(name, original, its song, ours, its song, mult_o, mult_b, seconds) for
    every pair `listen.py` staged."""
    import extra_pages
    out = []
    for t in sorted(listen.glob("*.trace.json")):
        name = t.name[:-len(".trace.json")]
        d = json.loads(t.read_text(encoding="utf-8"))
        src = extra_pages.EXTRA_PAGES.get(name, {}).get("source", name + ".sid")
        orig, ours = corpus / src, listen / f"{name}.h2g.sid"
        if orig.exists() and ours.exists():
            out.append((name, orig, d["sub_orig"] + 1, ours, d["sub_ours"] + 1,
                        d["orig"]["mult"], d["ours"]["mult"], d["seconds"]))
    return out


def report(rows: list[dict]) -> str:
    tot = Counter()
    for r in rows:
        tot.update({k: r[k] for k in ("notes", "match", "missing", "invented") + ATTRS})
    n = tot["notes"] or 1
    lines = ["# Heard-instrument census", "",
             f"{len(rows)} staged pairs, {tot['notes']} original notes. "
             f"**instr {tot['match'] / n:.3f}**: the share whose paired note "
             f"differs in none of {', '.join(CORE)} over its first {K} frames. "
             f"Known-equivalent, not counted against it: {', '.join(KNOWN)}. "
             "See `python/heard.py`.", "",
             "| attribute | notes | share | songs |", "|---|---|---|---|"]
    for k in ATTRS + ("missing", "invented"):
        songs = sum(1 for r in rows if r[k])
        lines.append(f"| {k}{' (known)' if k in KNOWN else ''} | {tot[k]} "
                     f"| {100 * tot[k] / n:.1f}% | {songs} |")
    lines += ["", "| song | notes | instr | lag | " + " | ".join(ATTRS) + " |",
              "|---|---|---|---|" + "---|" * len(ATTRS)]
    for r in sorted(rows, key=lambda r: (r["instr"] is None, r["instr"] or 0)):
        ins = "-" if r["instr"] is None else f"{r['instr']:.3f}"
        lines.append(f"| {r['name']} | {r['notes']} | {ins} | {r['lag']} | "
                     + " | ".join(str(r[k]) for k in ATTRS) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("corpus", type=Path, help="directory of the original .sid files")
    ap.add_argument("--listen", type=Path, default=LISTEN,
                    help="listen.py's staging directory (default build/listen)")
    ap.add_argument("--runs", type=Path, default=HERE.parent / "build" / "heard",
                    help="trace cache (default build/heard)")
    ap.add_argument("-t", "--seconds", type=float, default=180)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("-o", "--output", type=Path, default=HERE.parent / "build" / "heard_census.md")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    if not MAGPLAY_RT.exists():
        print(f"no {MAGPLAY_RT}: build python/tools/magplay-rt (see its README)",
              file=sys.stderr)
        return 2
    args.runs.mkdir(parents=True, exist_ok=True)
    jobs = staged_pairs(args.listen, args.corpus)
    if not jobs:
        print(f"no staged pairs in {args.listen}", file=sys.stderr)
        return 1

    def one(j):
        name, orig, so, ours, sb, mo, mb, secs = j
        s = min(args.seconds, secs)
        r = compare(_cached_trace(orig, s, so, args.runs),
                    _cached_trace(ours, s, sb, args.runs), mo, mb)
        return dict(name=name, **r)

    with ThreadPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(one, jobs))
    args.output.write_text(report(rows), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    tot_n = sum(r["notes"] for r in rows)
    print(f"{len(rows)} pairs, {tot_n} notes, instr "
          f"{sum(r['match'] for r in rows) / max(tot_n, 1):.3f} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
