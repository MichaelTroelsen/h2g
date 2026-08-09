"""Per-song instrument map, read out of a SID register trace.

Every other instrument-level check in this project reads the *player's own
instrument table* -- the eight bytes per record that `detect` locates -- and
then argues about what they mean. This reads the other end instead: what the
SID registers actually hold on the frame each note begins, in the original and
in our conversion, side by side.

That answers a different question. The table says what the converter *thinks*
an instrument is; the trace says what the tune *sounds* like. Where the two
disagree the trace wins, and where our conversion produces a signature the
original never produces we have invented something.

The dimensions are the ones a Goattracker instrument actually carries, so a
missing row names the field to go and look at:

    ADSR      $D405/$D406 -- should be a verbatim copy of the record, and is:
                             79 of 83 corpus files use no onset value absent
                             from our table.
    waveform  $D404 masked to its class, so gate and test bits do not split
              one instrument into several rows.
    pulse     $D402/$D403, bucketed -- an exact width is a moving target when
              a pulse program is sweeping it.
    filter    $D415-$D418, which is global rather than per voice, so it is
              reported once for the file rather than per onset.

Usage:
    python instrmap.py <sid-or-dir> -o OUTDIR [-t SECONDS] [--presets FILE]

Writes one Markdown file per song plus an index. On demand, not a build
artefact -- it traces two emulations per song and is far too slow for that.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fidelity as F
from h2g.convert import _detect_tables
from h2g.sidfile import load_sid

# Pulse widths are swept, so an exact value would make one instrument look
# like dozens. A 12-bit register in sixteenths is coarse enough to be stable
# and fine enough to tell a narrow pulse from a square.
PULSE_BUCKET = 0x100

WAVE_NAMES = ((0x80, "noise"), (0x40, "pulse"), (0x20, "saw"), (0x10, "tri"))


def _wave_name(w: int) -> str:
    names = [n for bit, n in WAVE_NAMES if w & bit]
    return "+".join(names) if names else f"${w:02X}"


def _onsets(trace, nframes: int) -> list:
    """(voice, frame, waveform class, ADSR, pulse bucket, note) per note start.

    Sampled on the frame *after* the attack: the attack frame itself is where
    a hard restart or a gate-off tick can still be in the registers, and that
    is the player's transition rather than the instrument.
    """
    out = []
    for vi, v in enumerate(trace):
        adsr = F.register_timeline(v.adsr_events, nframes)
        wf = F.register_timeline(v.wf_events, nframes)
        pul = F.register_timeline(v.pulse_events, nframes)
        for i, a in enumerate(v.attack_frames):
            f = min(a + 1, nframes - 1)
            note = v.attacks[i] if i < len(v.attacks) else "?"
            out.append((vi, a, wf[f] & 0xF0, adsr[f],
                        pul[f] // PULSE_BUCKET, note))
    return out


def _table(rows: list, head: list) -> list:
    if not rows:
        return ["_(none)_", ""]
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    out.append("")
    return out


def report(path: Path, opts: dict, mult: int, seconds: int, workdir: Path,
           gt2reloc: str, siddump: str) -> tuple:
    """(markdown lines, summary dict) for one song."""
    nframes = seconds * 50
    sub = F.resolve_subtune(path, "auto")
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, workdir / "o.sid")

    orig = F.run_siddump(workdir / "o.sid", seconds, sub, siddump, 0)
    sng = F.convert(str(path), log=lambda m: None, **opts)
    sng, _ = F.legalise_restarts(sng)
    packed = F.pack_sid(sng, workdir, gt2reloc, mult)
    ours = (F.run_siddump(packed, seconds, sub, siddump, calls=mult)
            if packed is not None else None)

    o_on = _onsets(orig, nframes)
    u_on = _onsets(ours, nframes) if ours else []

    def sigs(onsets):
        c = Counter()
        notes = defaultdict(list)
        for _, _, w, a, p, n in onsets:
            c[(w, a, p)] += 1
            notes[(w, a, p)].append(n)
        return c, notes

    o_sig, o_notes = sigs(o_on)
    u_sig, _ = sigs(u_on)

    # what our instrument table declares, for the ADSR column specifically
    sid0 = load_sid(str(path))
    sid, det = _detect_tables(sid0, lambda m: None)
    declared = {}
    for i in range(det.instr_used):
        b = det.instr_start + i * det.instr_stride
        if b + 4 < len(sid.data):
            declared[(sid.data[b + 3] << 8) | sid.data[b + 4]] = i

    lines = [f"# {path.name} — instrument map", "",
             f"Subtune {sub}, {seconds}s, packed at `-S{mult}`. "
             f"Signatures are the registers on the frame after each note "
             f"onset.", ""]

    lines.append("## What the original plays")
    lines.append("")
    rows = []
    for (w, a, p), n in o_sig.most_common():
        ns = o_notes[(w, a, p)]
        rows.append([_wave_name(w), f"`${a:04X}`", f"`${p * PULSE_BUCKET:03X}`",
                     n, f"{min(ns)}–{max(ns)}" if ns else "—",
                     "yes" if a in declared else "**no**"])
    lines += _table(rows, ["waveform", "ADSR", "pulse~", "notes", "range",
                           "ADSR in our table"])

    lines.append("## What our conversion plays")
    lines.append("")
    rows = [[_wave_name(w), f"`${a:04X}`", f"`${p * PULSE_BUCKET:03X}`", n,
             "yes" if (w, a, p) in o_sig else "**invented**"]
            for (w, a, p), n in u_sig.most_common()]
    lines += _table(rows, ["waveform", "ADSR", "pulse~", "notes",
                           "in the original"])

    # coverage, per dimension
    o_adsr = {a for _, a, _ in o_sig}
    u_adsr = {a for _, a, _ in u_sig}
    o_wave = {w for w, _, _ in o_sig}
    u_wave = {w for w, _, _ in u_sig}
    o_pul = {p for _, _, p in o_sig}
    u_pul = {p for _, _, p in u_sig}

    def cov(o, u, fmt=str):
        miss = sorted(o - u)
        return (f"{len(o & u)}/{len(o)}"
                + (" — missing " + ", ".join(fmt(m) for m in miss[:8])
                   if miss else ""))

    lines.append("## Coverage")
    lines.append("")
    lines += _table([
        ["ADSR", cov(o_adsr, u_adsr, lambda x: f"`${x:04X}`")],
        ["waveform class", cov(o_wave, u_wave, _wave_name)],
        ["pulse bucket", cov(o_pul, u_pul, lambda x: f"`${x*PULSE_BUCKET:03X}`")],
        ["ADSR vs our instrument table",
         cov(o_adsr, set(declared), lambda x: f"`${x:04X}`")],
    ], ["dimension", "covered"])

    # the filter is global, so it gets one row rather than one per onset
    def filt(tr):
        if tr is None:
            return "—"
        f = tr.filter
        cut = {v for _, v in f.cutoff_events}
        ctrl = {v for _, v in f.ctrl_events}
        return (f"{len(cut)} cutoff value(s), {len(ctrl)} control value(s)"
                if cut or ctrl else "unused")

    lines.append("## Filter (global, $D415–$D418)")
    lines.append("")
    lines += _table([["original", filt(orig)], ["ours", filt(ours)]],
                    ["side", "activity"])

    summary = {
        "file": path.name,
        "orig_signatures": len(o_sig),
        "our_signatures": len(u_sig),
        "adsr_missing": len(o_adsr - u_adsr),
        "adsr_not_in_table": len(o_adsr - set(declared)),
        "wave_missing": len(o_wave - u_wave),
        "invented": sum(1 for k in u_sig if k not in o_sig),
    }
    return lines, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="instrmap")
    ap.add_argument("target", help="a .sid file or a directory of them")
    ap.add_argument("-o", "--output", required=True, help="output directory")
    ap.add_argument("-t", "--seconds", type=int, default=60,
                    help="trace length; 60 by default, because a shorter "
                         "window misses instruments a tune introduces late")
    ap.add_argument("--presets", help="presets.json, for per-song options")
    ap.add_argument("--gt2reloc", default=F.GT2RELOC)
    ap.add_argument("--siddump", default=F.SIDDUMP)
    args = ap.parse_args(argv)

    target = Path(args.target)
    files = sorted(target.glob("*.sid")) if target.is_dir() else [target]
    doc = json.load(open(args.presets)) if args.presets else {"songs": {},
                                                              "always": {}}
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(F.make_workdir()[0])

    summaries = []
    for path in files:
        opts = F._preset_opts(doc, path.name)
        mult = F._preset_multiplier(doc, path.name)
        try:
            lines, s = report(path, opts, mult, args.seconds,
                              work / path.stem, args.gt2reloc, args.siddump)
        except Exception as exc:                      # noqa: BLE001
            print(f"  {path.name}: {type(exc).__name__}: {exc}")
            continue
        (out / f"{path.stem}.md").write_text("\n".join(lines), encoding="utf-8")
        summaries.append(s)
        print(f"  {path.name:<40} {s['orig_signatures']:>3} signatures, "
              f"{s['adsr_missing']} ADSR missing, {s['invented']} invented")

    index = ["# Instrument maps", "",
             f"{len(summaries)} song(s), {args.seconds}s each. "
             "*missing* is a register signature the original produces and the "
             "conversion does not; *invented* is the reverse.", ""]
    index += _table(
        [[f"[{s['file']}]({Path(s['file']).stem}.md)", s["orig_signatures"],
          s["our_signatures"], s["adsr_missing"], s["wave_missing"],
          s["invented"]] for s in summaries],
        ["song", "orig sigs", "our sigs", "ADSR missing", "wave missing",
         "invented"])
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")
    print(f"wrote {len(summaries)} map(s) + index to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
