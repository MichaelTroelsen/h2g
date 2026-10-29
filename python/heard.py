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

CORE = ("gate", "wave", "ad", "sr_hi", "pitch")
KNOWN = ("testpre", "sr_rel", "tail_env", "gated_tick")
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


def notes(st: list[list[int]], rose: list[list[bool]], v: int,
          tune: float) -> list[dict]:
    """Voice `v`'s notes. A note is anchored on the first frame after its rise
    that carries a waveform, so a `$09` frame before the attack is counted as
    `testpre` rather than shifting the note."""
    b = 7 * v
    starts, pre = [], []
    for i in (i for i in range(len(st)) if rose[i][v]):
        j = i
        while (j < len(st) - 1 and j - i < 2 and not (st[j][b + 4] & 0xF0)
               and (st[j][b + 4] & 0x08)):
            j += 1
        starts.append(j)
        pre.append(j - i)
    out = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(st)
        tail = 0
        while tail < TAIL and e - 1 - tail > s and not (st[e - 1 - tail][b + 4] & 1):
            tail += 1
        if tail >= TAIL or e - 1 - tail <= s:
            tail = 0
        snd = e - tail
        # named after the tonal pitch it holds longest
        best, bl, i = None, 0, s
        while i < snd:
            fr, ctl, j = _freq(st[i], b), st[i][b + 4], i
            while j < snd and _freq(st[j], b) == fr:
                j += 1
            if ((ctl & 0x70) and not (ctl & 0x88) and j - i > bl
                    and semi(fr, tune) is not None):
                best, bl = semi(fr, tune), j - i
            i = j
        first = semi(_freq(st[s], b), tune)
        held = best if best is not None else first
        prog = []
        for k in range(s, min(snd, s + K)):
            p = semi(_freq(st[k], b), tune)
            prog.append((st[k][b + 4], None if p is None or held is None else p - held))
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
    if any(a["prog"][i][1] != b["prog"][i][1] for i in range(k)):
        out.add("pitch")
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
    on = [notes(so, ro, v, to) for v in range(3)]
    bn = [notes(sb, rb, v, tb) for v in range(3)]
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
