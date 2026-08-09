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

    # Our instrument records, read back out of the file we just wrote, so the
    # mapping is against what shipped rather than what the writer intended.
    q = 4 + 96
    subs = sng[q]; q += 1
    for _ in range(subs * 3):
        n = sng[q]; q += 1; q += n + 1
    ni = sng[q]; q += 1
    recs = []
    for i in range(ni):
        recs.append(list(sng[q:q + 9])); q += 25
    n = sng[q]; q += 1
    wl = list(sng[q:q + n])

    def first_wave(ptr):
        """The waveform this instrument's wavetable opens on."""
        for k in range(ptr - 1, len(wl)):
            if wl[k] == 0xFF:
                return None
            if wl[k] > 0x0F:
                return wl[k] & 0xF0
        return None

    # Both sides keyed by ADSR, which is the natural join: it is a verbatim
    # per-instrument copy of the record (0 of 1635 corpus records differ), so
    # it identifies an instrument where waveform and pulse cannot -- several
    # instruments share a waveform, and a swept pulse has no single value.
    def by_adsr(onsets):
        out = defaultdict(Counter)
        for _, _, w, a, pu, _ in onsets:
            out[a][(w, pu)] += 1
        return out

    o_by, u_by = by_adsr(o_on), by_adsr(u_on)

    lines = [f"# {path.name} — instrument map", "",
             f"Subtune {sub}, {seconds}s, packed at `-S{mult}`. Signatures are "
             "the registers on the frame after each note onset, joined on ADSR "
             "— a verbatim per-instrument copy, and so the one field that "
             "identifies an instrument on both sides.", ""]

    lines.append("## Mapping")
    lines.append("")
    rows, seen = [], set()
    for i, r in enumerate(recs):
        adsr = (r[0] << 8) | r[1]
        seen.add(adsr)
        ow = first_wave(r[2])
        oh, uh = o_by.get(adsr), u_by.get(adsr)
        o_n = sum(oh.values()) if oh else 0
        u_n = sum(uh.values()) if uh else 0
        o_w = _wave_name(oh.most_common(1)[0][0][0]) if oh else "—"
        u_w = _wave_name(uh.most_common(1)[0][0][0]) if uh else "—"
        if not oh and not uh:
            verdict = "unused both sides"
        elif not oh:
            verdict = "**we play it, the original does not**"
        elif not uh:
            verdict = "**the original plays it, we do not**"
        elif o_w != u_w:
            verdict = f"**waveform: {o_w} -> {u_w}**"
        else:
            verdict = "ok"
        rows.append([i + 1, f"`${adsr:04X}`",
                     _wave_name(ow) if ow is not None else "—",
                     o_w, o_n, u_w, u_n, verdict])
    rows_map = rows
    lines += _table(rows, ["GT", "ADSR", "opens on", "orig wave", "orig notes",
                           "our wave", "our notes", "verdict"])

    extra = sorted(set(o_by) - seen)
    if extra:
        lines.append("### Sounded by the original, with no instrument of ours")
        lines.append("")
        lines += _table([[f"`${a:04X}`",
                          _wave_name(o_by[a].most_common(1)[0][0][0]),
                          sum(o_by[a].values())] for a in extra],
                        ["ADSR", "waveform", "notes"])

    lines.append("## Pulse width per instrument")
    lines.append("")
    rows = []
    for i, r in enumerate(recs):
        adsr = (r[0] << 8) | r[1]
        o_p = sorted({p for _, p in o_by.get(adsr, {})})
        u_p = sorted({p for _, p in u_by.get(adsr, {})})
        if not o_p and not u_p:
            continue
        def fmt(xs):
            return " ".join(f"${x*PULSE_BUCKET:03X}" for x in xs) or "—"
        rows.append([i + 1, f"`${adsr:04X}`", fmt(o_p), fmt(u_p),
                     "ok" if set(o_p) == set(u_p)
                     else ("**narrower**" if len(u_p) < len(o_p) else "wider")])
    lines += _table(rows, ["GT", "ADSR", "original", "ours", ""])


    # Counted off the joined mapping, so the index and the per-song tables
    # cannot disagree: a "mismatch" is one instrument whose waveform differs
    # between the two sides, not a pair of set differences that might not
    # correspond to any instrument at all.
    mism = sum(1 for r in rows_map if r[7].startswith("**waveform"))
    only_orig = sum(1 for r in rows_map
                    if r[7].startswith("**the original"))
    only_ours = sum(1 for r in rows_map if r[7].startswith("**we play"))
    summary = {
        "file": path.name,
        "instruments": len(recs),
        "matched": sum(1 for r in rows_map if r[7] == "ok"),
        "waveform_mismatch": mism,
        "only_original": only_orig + len(extra),
        "only_ours": only_ours,
        "unused": sum(1 for r in rows_map if r[7] == "unused both sides"),
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
        print(f"  {path.name:<40} {s['matched']:>3}/{s['instruments']:<3} matched, "
              f"{s['waveform_mismatch']} waveform, "
              f"{s['only_original']} orig-only, {s['only_ours']} ours-only")

    index = ["# Instrument maps", "",
             f"{len(summaries)} song(s), {args.seconds}s each. One row per "
             "instrument, matched between the original and the conversion on "
             "ADSR. *matched* means both sides sound it with the same waveform "
             "class.", ""]
    index += _table(
        [[f"[{s['file']}]({Path(s['file']).stem}.md)", s["instruments"],
          s["matched"], s["waveform_mismatch"], s["only_original"],
          s["only_ours"], s["unused"]] for s in summaries],
        ["song", "instruments", "matched", "waveform differs",
         "only original", "only ours", "unused"])
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")
    print(f"wrote {len(summaries)} map(s) + index to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
