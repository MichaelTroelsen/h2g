"""Attribute a low gate / wave / instr cell to the notes that cost it.

    python attribute.py Wiz gate
    python attribute.py Bangkok_Knights wave
    python attribute.py 5_Title_Tunes instr

A column's number is a ratio; this prints its numerator's complement as
GROUPS, each miss counted once, keyed by

  * instrument record  the original's ADSR pair at the attack that owns the
                       miss (a siddump trace names no instrument number, the
                       ADSR it writes at the note's start is what tells two
                       instruments apart; heard.py notes carry the same pair);
  * frame offset       frames since that attack (`CAP` and beyond share a
                       bucket); for instr, the first frame of the note's
                       program on which gate, wave or pitch differs, or `head`
                       where only the envelope (ad / sr_hi) does;
  * side               which side differs: for gate, ours sustains / ours
                       silent; for wave, the two waveform classes; for instr,
                       the CORE attributes (or `missing`, a note we did not
                       play).

The per-group counts sum to the column's own miss count, and `verify` refuses
a table that does not. gate and wave are measured with fidelity.py's own
`gate_compare` / `wave_compare` (the real call `measure` makes is captured
and its result is the reference); the miss frames are located by a walk that
uses fidelity's `_aligned`, `register_timeline` and `_release_frames`. instr
reads heard.py's cached traces through `abpage._heard_notes` and pairs and
compares with `heard.pair` / `heard.diffs` / `heard.CORE`, exactly as
`abpage.worst_notes` does; its reference is `notes - match` in
`build/heard.json`.

gate and wave re-run the conversion and siddump for the song (about a
minute); instr only reads the cache. Never writes build/fidelity.json.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

CAP = 32        # offsets of CAP frames or more share one bucket
CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
SCRATCH = Path("C:/t/attribute-tool")
COLUMNS = ("gate", "wave", "instr")


@dataclass(frozen=True)
class Miss:
    """One unit the column charged: a frame (gate, wave) or a note (instr)."""
    voice: int
    at: int            # frame (gate, wave) or note start frame (instr)
    record: str
    offset: str
    side: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.record, self.offset, self.side)


def _record(ad: int, sr: int) -> str:
    return f"AD${ad:02X} SR${sr:02X}"


def _offset(k: int) -> str:
    return f"{CAP}+" if k >= CAP else str(k)


class _Owner:
    """The attack that owns a frame of one original voice, and its record."""

    def __init__(self, voice, nframes: int) -> None:
        import fidelity as F
        self.frames = sorted(voice.attack_frames + voice.unnamed_attack_frames)
        self.adsr = F.register_timeline(voice.adsr_events, nframes)

    def of(self, k: int) -> tuple[str, int]:
        i = bisect_right(self.frames, k) - 1
        if i < 0:
            return "pre-attack", k
        f = self.frames[i]
        v = self.adsr[f] if f < len(self.adsr) else 0
        return _record(v >> 8 & 0xFF, v & 0xFF), k - f


def gate_misses(orig, ours, nframes: int, lag: int = 0) -> list[Miss]:
    """Every frame `fidelity.gate_compare` charges, in its own frame order."""
    import fidelity as F
    out: list[Miss] = []
    for v, (a, b) in enumerate(zip(orig, ours)):
        ta = F.register_timeline(a.wf_events, nframes)
        tb = F.register_timeline(b.wf_events, nframes)
        ta, tb = F._aligned(ta, tb, lag)
        own = _Owner(a, nframes)
        sounded = False
        for k, (x, y) in enumerate(zip(ta, tb)):
            sounded = sounded or bool(x or y)
            if x == 0 and y == 0 and not sounded:
                continue
            ox, oy = not (x & 0x01), not (y & 0x01)
            if not (ox or oy) or (ox and oy):
                continue
            rec, off = own.of(k)
            out.append(Miss(v, k, rec, _offset(off),
                            "ours sustains, orig off" if ox
                            else "ours off, orig sounds"))
    return out


def wave_misses(orig, ours, nframes: int, lag: int = 0) -> list[Miss]:
    """Every frame `fidelity.wave_compare` charges, in its own frame order."""
    import fidelity as F
    out: list[Miss] = []
    for v, (a, b) in enumerate(zip(orig, ours)):
        ta = F.register_timeline(a.wf_events, nframes)
        tb = F.register_timeline(b.wf_events, nframes)
        ta, tb = F._aligned(ta, tb, lag)
        ea, eb = F._aligned(F.register_timeline(a.adsr_events, nframes),
                            F.register_timeline(b.adsr_events, nframes), lag)
        own = _Owner(a, nframes)
        since_off = None
        for k, (x, y, _, sr) in enumerate(zip(ta, tb, ea, eb)):
            cx, cy = x & 0xF0, y & 0xF0
            if y & F.GATE_BIT:
                since_off = None
            elif since_off is None:
                since_off = 0
            else:
                since_off += 1
            if cx == 0 and cy == 0:
                continue
            if (cx == 0 and not x & F.GATE_BIT and since_off is not None
                    and since_off >= F._release_frames(sr & 0x0F)):
                continue
            if cx == cy:
                continue
            rec, off = own.of(k)
            out.append(Miss(v, k, rec, _offset(off),
                            f"orig ${cx:02X} / ours ${cy:02X}"))
    return out


def instr_misses(d: dict) -> list[Miss]:
    """Every note `heard.compare` does not count as an `instr` match.

    `d` is `abpage._heard_notes`: both sides' notes already segmented and
    lag-aligned the way the census did it."""
    import heard as H
    core = set(H.CORE)
    out: list[Miss] = []
    for v in range(3):
        pairs, _ = H.pair(d["on"][v], d["bn"][v], d["lag"])
        for a, b in pairs:
            rec = _record(a["ad"], a["sr"])
            if b is None:
                out.append(Miss(v, a["start"], rec, "-", "missing"))
                continue
            ds = H.diffs(a, b, d["mult_b"])
            hit = ds & core
            if not hit:
                continue
            off, side = "head", "+".join(k for k in H.CORE if k in hit)
            for k in range(min(len(a["prog"]), len(b["prog"]))):
                cut = H.diffs({**a, "prog": a["prog"][:k + 1]},
                              {**b, "prog": b["prog"][:k + 1]}, d["mult_b"])
                if cut & {"gate", "gated_tick", "wave", "pitch"}:
                    off = _offset(k)
                    break
            out.append(Miss(v, a["start"], rec, off, side))
    return out


def group(misses: list[Miss]) -> Counter:
    """Count misses by (record, offset, side); every miss lands in one group."""
    return Counter(m.key for m in misses)


def marginal(groups: Counter, axis: int) -> Counter:
    c: Counter = Counter()
    for key, n in groups.items():
        c[key[axis]] += n
    return c


def verify(groups: Counter, expected: int, what: str) -> int:
    """The group counts must sum to `expected`; returns the sum when they do."""
    total = sum(groups.values())
    if total != expected:
        raise AssertionError(f"{what}: groups sum to {total}, the column's own "
                             f"miss count is {expected}")
    return total


# --------------------------------------------------------------------------
# references: the column's own miss count
# --------------------------------------------------------------------------
def gate_expected(res: dict) -> int:
    return res["gate_ours_ringing"] + res["gate_ours_silent"]


def wave_expected(res: dict) -> int:
    """frames - agreeing frames, per voice as `wave_compare` reports them."""
    return sum(pv["frames"] - round(pv["wave"] * pv["frames"])
               for pv in res["wave_voices"] if pv["frames"])


def instr_expected(row: dict) -> int:
    return row["notes"] - row["match"]


def _row(path: Path, name: str) -> dict:
    rows = json.loads(path.read_text(encoding="utf-8"))
    for r in rows:
        if r.get("name", r.get("file", "")).removesuffix(".sid") == name:
            return r
    raise KeyError(f"{name} not in {path}")


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------
def capture(song: str, seconds: int, scratch: Path) -> dict:
    """Run `fidelity.main` on a scratch copy of `song` under presets.json and
    keep the arguments and result of the gate and wave comparisons it made."""
    import fidelity as F
    src = CORPUS / f"{song}.sid"
    if not src.exists():
        raise SystemExit(f"no {src}")
    scratch.mkdir(parents=True, exist_ok=True)
    sid = scratch / "sid" / src.name
    sid.parent.mkdir(exist_ok=True)
    shutil.copyfile(src, sid)
    work = scratch / "work" / song
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    calls: dict[str, list] = {"gate": [], "wave": []}
    real_g, real_w = F.gate_compare, F.wave_compare

    def spy_g(o, u, nframes, lag=0):
        r = real_g(o, u, nframes, lag=lag)
        calls["gate"].append((o, u, nframes, lag, r))
        return r

    def spy_w(o, u, nframes=None, lag=0):
        r = real_w(o, u, nframes=nframes, lag=lag)
        calls["wave"].append((o, u, nframes, lag, r))
        return r

    F.gate_compare, F.wave_compare = spy_g, spy_w
    jpath = scratch / f"{song}.row.json"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            F.main([str(sid), "-t", str(seconds), "--presets",
                    str(HERE.parent / "presets.json"), "--json", str(jpath),
                    "--workdir", str(work), "--label", "attribute"])
    finally:
        F.gate_compare, F.wave_compare = real_g, real_w
    row = json.loads(jpath.read_text(encoding="utf-8"))[0]
    return {"row": row, "calls": calls}


def pick(calls: list, row: dict, col: str):
    """The comparison `measure` made for the row: three voices, same frames."""
    for o, u, nframes, lag, res in calls:
        if (len(o) == 3 and res[col] == row.get(col)
                and res[f"{col}_frames"] == row.get(f"{col}_frames")):
            return o, u, nframes, lag, res
    raise SystemExit(f"no captured {col} comparison matches the row")


def attribute_fidelity(song: str, col: str, seconds: int, scratch: Path) -> dict:
    got = capture(song, seconds, scratch)
    row = got["row"]
    o, u, nframes, lag, res = pick(got["calls"][col], row, col)
    if col == "gate":
        misses, expected = gate_misses(o, u, nframes, lag), gate_expected(res)
    else:
        misses, expected = wave_misses(o, u, nframes, lag), wave_expected(res)
    ref = json.loads((HERE.parent / "build" / "fidelity.json")
                     .read_text(encoding="utf-8"))
    base = next((r for r in ref if r.get("file") == f"{song}.sid"), None)
    if base is None:
        base_n = None
    elif col == "gate":
        base_n = base["gate_ours_ringing"] + base["gate_ours_silent"]
    else:
        base_n = base["wave_frames"] - round(base["wave"] * base["wave_frames"])
    return dict(column=col, song=song, value=res[col], lag=lag,
                denominator=res[f"{col}_frames"], misses=misses,
                expected=expected, committed=base_n,
                committed_value=None if base is None else base[col])


def attribute_instr(song: str) -> dict:
    import abpage
    d = abpage._heard_notes(song)
    if d is None:
        raise SystemExit(f"{song}: heard traces are not cached")
    row = _row(HERE.parent / "build" / "heard.json", song)
    return dict(column="instr", song=song, value=row["instr"], lag=d["lag"],
                denominator=row["notes"], misses=instr_misses(d),
                expected=instr_expected(row), committed=instr_expected(row),
                committed_value=row["instr"])


def render(r: dict, top: int = 25) -> str:
    groups = group(r["misses"])
    total = verify(groups, r["expected"], f"{r['song']} {r['column']}")
    unit = "notes" if r["column"] == "instr" else "frames"
    L = [f"## {r['song']} {r['column']}",
         "",
         f"column {r['value']:.4f} over {r['denominator']} {unit} (lag {r['lag']}); "
         f"{r['expected']} missed {unit} by the column's own count; "
         f"groups sum to {total} in {len(groups)} groups"
         + (f"; committed count {r['committed']} (value "
            f"{r['committed_value']:.4f})" if r["committed"] is not None else ""),
         ""]
    for title, axis in (("side", 2), ("offset", 1), ("instrument record", 0)):
        m = marginal(groups, axis)
        if axis == 1:
            items = sorted(m.items(), key=lambda kv: (len(kv[0]), kv[0]))
        else:
            items = m.most_common(top if axis == 0 else None)
        L += [f"### by {title}", "", f"| {title} | {r['column']} misses | share |",
              "|---|---|---|"]
        L += [f"| {k} | {n} | {n / total:.1%} |" for k, n in items]
        if axis == 0 and len(m) > top:
            rest = total - sum(n for _, n in items)
            L.append(f"| ({len(m) - top} more records) | {rest} | {rest / total:.1%} |")
        L.append("")
    L += [f"### top {top} groups (record, offset, side)", "",
          "| record | offset | side | misses |", "|---|---|---|---|"]
    shown = 0
    for (rec, off, side), n in groups.most_common(top):
        L.append(f"| {rec} | {off} | {side} | {n} |")
        shown += n
    L.append(f"| ({len(groups) - min(top, len(groups))} more groups) | | | "
             f"{total - shown} |")
    L += ["", f"sum of all groups: {total}", ""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("song", help="corpus name without .sid, e.g. Wiz")
    ap.add_argument("column", choices=COLUMNS)
    ap.add_argument("-t", "--seconds", type=int, default=180)
    ap.add_argument("--scratch", type=Path, default=SCRATCH)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    r = (attribute_instr(args.song) if args.column == "instr"
         else attribute_fidelity(args.song, args.column, args.seconds,
                                 args.scratch))
    text = render(r, args.top)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
