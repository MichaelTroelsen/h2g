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

This is the one place in the repo that makes this comparison. `songview.py`
briefly carried a second, overlapping `--compare` mode (v0.5.243); it was
removed rather than kept beside this tool -- it duplicated the join this
module already makes, and it broke `songview.py`'s own "judges nothing and
scores nothing" premise. See `songview.py`'s docstring.
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

# Frames of each note to profile. Eight covers the drum sweep's whole reach
# (section 7.ii: the player sweeps for W-1 frames, W being 2-9 ticks) and the
# two-frame noise tick, which is what the per-instrument profile is for.
PROFILE_FRAMES = 8

WAVE_NAMES = ((0x80, "noise"), (0x40, "pulse"), (0x20, "saw"), (0x10, "tri"))

# Width of one appended instrument column, and of the whole appended cell.
# Both sides of the dump get the same three columns, so a row of one file can
# be read against the same row of the other.
_INS_W = 4
_CELL = f"{'Ins1':>{_INS_W}} {'Ins2':>{_INS_W}} {'Ins3':>{_INS_W}}"


def annotate_dump(text: str, trace, adsr_to_gt: dict,
                  nframes: int) -> tuple[str, list]:
    """siddump's own table with three instrument columns appended.

    The join is the one the mapping table above uses -- ADSR identifies an
    instrument, being a verbatim per-instrument copy of the record -- applied
    per frame instead of per song. Applied to the *original's* dump this is
    what labels Hubbard's trace with our instrument numbers.

    A note's instrument is decided on the frame *after* its attack and then
    held for the whole note, for the reason `_onsets` samples there: the attack
    frame can still hold a hard restart's ADSR, which is the player's
    transition and not the instrument. Deciding once per note rather than per
    frame also means the column cannot disagree with the tables above it.

    An ADSR no instrument of ours carries gets a lowercase letter instead, in
    first-appearance order; `legend` in the return names them.
    """
    unmatched: dict[int, str] = {}

    def label(adsr: int) -> str:
        hits = adsr_to_gt.get(adsr)
        if hits:
            s = "/".join(str(h) for h in hits)
            return s if len(s) <= _INS_W else f"{hits[0]}+"
        if adsr not in unmatched:
            i = len(unmatched)
            # a..z then a2..z2; a corpus file has never needed the second lap
            unmatched[adsr] = chr(ord("a") + i % 26) + ("" if i < 26
                                                        else str(i // 26 + 1))
        return unmatched[adsr]

    # per-voice, per-frame: the label of the note sounding, and whether the
    # frame is that note's onset
    cols = [[""] * nframes for _ in range(3)]
    onset = [set() for _ in range(3)]
    for vi, v in enumerate(trace):
        adsr = F.register_timeline(v.adsr_events, nframes)
        atk = sorted(v.attack_frames)
        for i, a in enumerate(atk):
            nxt = atk[i + 1] if i + 1 < len(atk) else nframes
            lab = label(adsr[min(a + 1, nframes - 1)])
            onset[vi].add(a)
            for f in range(a, min(nxt, nframes)):
                cols[vi][f] = lab

    out = []
    for line in text.splitlines():
        if line.startswith("+") and line.endswith("+"):
            out.append(line + "-" * (len(_CELL) + 2) + "+")
            continue
        if not line.startswith("|"):
            out.append(line)
            continue
        try:
            frame = int(line.split("|")[1].strip())
        except (ValueError, IndexError):
            out.append(line + " " + _CELL + " |")   # header row
            continue
        if frame >= nframes:
            out.append(line + " " * (len(_CELL) + 2) + "|")
            continue
        cells = []
        for vi in range(3):
            lab = cols[vi][frame] or "."
            if frame in onset[vi]:
                lab = "*" + lab
            cells.append(f"{lab:>{_INS_W}}")
        out.append(line + " " + " ".join(cells) + " |")

    legend = [f"`${a:04X}` = `{n}`" for a, n in
              sorted(unmatched.items(), key=lambda kv: kv[1])]
    return "\n".join(out), legend


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
           gt2reloc: str, siddump: str, dump: bool = True) -> tuple:
    """(markdown lines, summary dict) for one song."""
    nframes = seconds * 50
    sub = F.resolve_subtune(path, "auto")
    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, workdir / "o.sid")

    o_raw: list = []
    orig = F.run_siddump(workdir / "o.sid", seconds, sub, siddump, 0,
                         capture=o_raw)
    sng = F.convert(str(path), log=lambda m: None, **opts)
    sng, _ = F.legalise_restarts(sng)
    packed = F.pack_sid(sng, workdir, gt2reloc, mult)
    u_raw: list = []
    ours = (F.run_siddump(packed, seconds, sub, siddump, calls=mult,
                          capture=u_raw)
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

    # ---- per-instrument profile, read off the original -------------------
    def profile(trace, nframes):
        """ADSR -> the modal register behaviour over a note, from the trace."""
        out = defaultdict(lambda: {"wave": Counter(), "pulse": [],
                                   "freq": [], "gate": Counter(),
                                   "notes": [], "span": []})
        for v in trace:
            adsr = F.register_timeline(v.adsr_events, nframes)
            wf = F.register_timeline(v.wf_events, nframes)
            pul = F.register_timeline(v.pulse_events, nframes)
            frq = F.register_timeline(v.freq_events, nframes)
            atk = sorted(v.attack_frames)
            for i, a in enumerate(atk):
                nxt = atk[i + 1] if i + 1 < len(atk) else nframes
                span = min(nxt, a + 1 + PROFILE_FRAMES, nframes)
                if span <= a + 1:
                    continue
                key = adsr[min(a + 1, nframes - 1)]
                d = out[key]
                d["wave"][tuple(wf[f] & 0xF0
                                for f in range(a + 1, span))] += 1
                seg_p = [pul[f] for f in range(a + 1, span)]
                seg_f = [frq[f] for f in range(a + 1, span)]
                d["pulse"].append((min(seg_p), max(seg_p)))
                # ...and again over the *whole* note. A pulse program is the
                # one thing PROFILE_FRAMES is too short for: a sweep slower
                # than 8 frames would be reported as a narrow band by a window
                # that ends before it turns around.
                whole = [pul[f] for f in range(a + 1, min(nxt, nframes))]
                if whole:
                    d["span"].append((min(whole), max(whole)))
                d["freq"].append(seg_f[0] - min(seg_f))
                # frames until the gate bit clears, if it does
                g = next((f - a for f in range(a + 1, min(nxt, nframes))
                          if not (wf[f] & 0x01)), None)
                d["gate"][g] += 1
                if i < len(v.attacks):
                    d["notes"].append(v.attacks[i])
        return out

    o_prof = profile(orig, nframes)
    u_prof = profile(ours, nframes) if ours else {}

    lines.append("## What the original does, per instrument")
    lines.append("")
    lines.append("One row per instrument of ours, describing the *original's* "
                 "behaviour over the first "
                 f"{PROFILE_FRAMES} frames of each note it sounds. This is the "
                 "spec the `.sng` should meet.")
    lines.append("")
    rows = []
    for i, r in enumerate(recs):
        adsr = (r[0] << 8) | r[1]
        d = o_prof.get(adsr)
        if not d or not d["wave"]:
            continue
        seq, _ = d["wave"].most_common(1)[0]
        seq_s = " ".join(_wave_name(w) if w else "-" for w in seq)
        lo = min(a for a, _ in d["pulse"]); hi = max(b for _, b in d["pulse"])
        fall = sorted(d["freq"])[len(d["freq"]) // 2]
        gate = d["gate"].most_common(1)[0][0]
        rows.append([i + 1, f"`${adsr:04X}`", len(d["notes"]), seq_s,
                     f"${lo:03X}" + (f"-${hi:03X}" if hi != lo else ""),
                     fall, gate if gate is not None else "held"])
    lines += _table(rows, ["GT", "ADSR", "notes", "waveform per frame",
                           "pulse range", "pitch fall", "gate off after"])

    lines.append("## What we wrote, per instrument")
    lines.append("")
    rows = []
    for i, r in enumerate(recs):
        adsr = (r[0] << 8) | r[1]
        blk = []
        for k in range(r[2] - 1, len(wl)):
            blk.append(f"{wl[k]:02X}")
            if wl[k] == 0xFF:
                break
        rows.append([i + 1, f"`${adsr:04X}`",
                     f"`${r[2]:02X}`", " ".join(blk),
                     f"`${r[7]:02X}`", f"`${r[8]:02X}`"])
    lines += _table(rows, ["GT", "ADSR", "wave ptr", "wavetable",
                           "gate timer", "1st frame wave"])

    lines.append("## Pulse width per instrument")
    lines.append("")
    lines.append("*at onset* is the width on the frame after each note begins; "
                 "*over the note* is the band it covers between one note and "
                 "the next. The two answer different questions and a pulse "
                 "program only shows up in the second — a sweep that restarts "
                 "with the note sits on one onset value however far it travels "
                 "afterwards, so an onset-only reading calls a working sweep "
                 "static.")
    lines.append("")
    rows = []
    for i, r in enumerate(recs):
        adsr = (r[0] << 8) | r[1]
        o_p = sorted({p for _, p in o_by.get(adsr, {})})
        u_p = sorted({p for _, p in u_by.get(adsr, {})})
        if not o_p and not u_p:
            continue

        def band(prof):
            """(the band every note of this instrument covers, median travel).

            The verdict is taken from the *median travel within one note*, not
            from the band. A player sweep that free-runs across notes visits
            every phase, so its band is the full sweep however little it moves
            during any one note, while a Goattracker pulse program restarts
            with the note and can only ever show what it covers in that note.
            Comparing bands would score that difference as agreement.
            """
            s = prof.get(adsr, {}).get("span") if prof else None
            if not s:
                return "—", 0
            lo = min(a for a, _ in s); hi = max(b for _, b in s)
            travel = sorted(b - a for a, b in s)
            return (f"${lo:03X}" + (f"-${hi:03X}" if hi != lo else ""),
                    travel[len(travel) // 2])

        def fmt(xs):
            return " ".join(f"${x*PULSE_BUCKET:03X}" for x in xs) or "—"
        o_b, o_w = band(o_prof)
        u_b, u_w = band(u_prof)
        # Judged on the travelled band, not the onset buckets: the onset value
        # is one sample of a moving register and cannot distinguish a static
        # width from a sweep that happens to restart at the same place.
        if not o_w and not u_w:
            verdict = "static both sides" if o_b == u_b else "**width differs**"
        elif o_w and not u_w:
            verdict = "**the original sweeps, we do not**"
        elif u_w and not o_w:
            verdict = "**we sweep, the original does not**"
        else:
            ratio = u_w / o_w
            verdict = ("ok" if 0.75 <= ratio <= 1.33
                       else f"**{ratio:.2f}x the original's travel**")
        rows.append([i + 1, f"`${adsr:04X}`", fmt(o_p), fmt(u_p),
                     o_b, u_b, f"{o_w}/{u_w}", verdict])
    lines += _table(rows, ["GT", "ADSR", "orig at onset", "ours at onset",
                           "orig band", "our band", "travel per note",
                           "verdict"])


    if dump:
        # The evidence, in full, beside the conclusions drawn from it. Folded
        # so the tables stay at the top of the file: a 60s trace is 3000 rows
        # a side, and every reading above is derived from these two tables, so
        # a disputed row can be checked here rather than re-traced.
        #
        # Both dumps carry the mapping in three appended columns, so the
        # tables above can be read *down* the trace: which instrument is
        # sounding, on which voice, on which frame -- on the original's side
        # too, which is the whole point. Frames not covered by any instrument
        # of ours are the gap, and they are visible rather than counted.
        ins = defaultdict(list)
        for i, r in enumerate(recs):
            ins[(r[0] << 8) | r[1]].append(i + 1)
        for label, raw, tr in (("the original", o_raw, orig),
                               ("our conversion", u_raw, ours)):
            if not raw or tr is None:
                continue
            body, legend = annotate_dump(raw[1].rstrip(), tr, ins, nframes)
            lines += ["<details>",
                      f"<summary>Full siddump of {label} "
                      f"({len(raw[1].splitlines())} lines), with the "
                      "instrument sounding on each voice</summary>", ""]
            lines += ["`Ins1`-`Ins3` are the GT instrument sounding on that "
                      "voice, `*` marking the note's onset frame and `.` a "
                      "voice with nothing yet. They are joined on ADSR and "
                      "decided on the frame after the attack, exactly as the "
                      "tables above are.", ""]
            if legend:
                lines += ["Lettered entries are ADSR values no instrument of "
                          "ours carries: " + ", ".join(legend) + ".", ""]
            lines += ["```", f"$ {raw[0]}", body, "```", "", "</details>", ""]

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
    ap.add_argument("--no-dump", action="store_true",
                    help="leave out the full siddump tables. They are included "
                         "by default -- the mapping is derived from them, so "
                         "publishing both means a disputed row can be checked "
                         "in place -- but they are ~3000 rows a side per song")
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
                              work / path.stem, args.gt2reloc, args.siddump,
                              dump=not args.no_dump)
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
