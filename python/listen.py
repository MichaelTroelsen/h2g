#!/usr/bin/env python3
"""Stage a listening pass: the files to play, and what to listen for.

`fidelity.py` measures note attacks. It is blind to everything that is not an
attack -- the digi rest fix (v0.5.46) changed 66 rows of Off the Cuff and moved
the report by zero percent -- so a number from it is a floor on how wrong a
conversion is, never a ceiling. The only instrument that catches the rest is a
person listening, and this script exists because that has been done exactly
once in the project's life, on one file.

    python listen.py --from-json build/fidelity.json          # one per band
    python listen.py --files Delta.sid Commando.sid <sid_dir>

For each chosen tune it writes, into `build/listen/`:

    <name>.original.wav   the .sid as Hubbard wrote it
    <name>.h2g.wav        our conversion, packed back to a .sid by gt2reloc
    <name>.h2g.sng        the same conversion for opening in GoatTracker
    LISTENING.md          what the measurement says, and what it cannot say

The two WAVs are rendered by the same emulator at the same settings, so a
difference in them is a difference in the music. Play them back to back.

The point is not to re-derive the score by ear. It is to catch what the score
cannot see: an instrument with the wrong attack, a voice an octave out, a
tempo that drifts, a pattern that repeats where the original moves on. The
per-file notes below each say what the numbers predict, so that a listen can
*disagree* with them -- which is the outcome worth having.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fidelity import (_preset_opts, _preset_multiplier, legalise_restarts,
                      make_workdir, pack_sid, run_siddump, GT2RELOC, SIDDUMP,
                      WORKDIR)
from h2g import __version__
from h2g.convert import convert

SID2WAV = r"C:\Users\mit\claude\c64server\SIDM2\tools\SID2WAV.EXE"

# The bands FIDELITY.md reports, and what a listener is being asked to decide
# in each. Ordered worst-first: the interesting listening is at the bottom of
# the corpus, not the top.
BANDS = [
    ("plays something else", -0.01, 0.50,
     "Is this the same piece of music at all, or has the ripper found the "
     "wrong data? A wrong tune and a badly converted tune sound nothing alike."),
    ("recognisable", 0.50, 0.80,
     "The notes are broadly right. Is what is wrong *musical* (missing "
     "ornament, wrong instrument, dropped voice) or *structural* (a pattern "
     "repeating, a section missing)?"),
    ("close", 0.80, 0.95,
     "Would a listener who knows the tune notice? This band is where the "
     "measurement is least trustworthy, because everything it can see is "
     "nearly right."),
    ("plays the same music", 0.95, 1.01,
     "The notes match. Does it still sound wrong -- timbre, envelope, "
     "filter, tempo? Anything heard here is invisible to every check in the "
     "repo."),
]


# SID2WAV is version 1.8, from 1997, and predates RSID entirely: it answers
# `ERROR: Could not determine file format` on one and renders nothing. **18 of
# the 95 corpus files are RSID** -- After_8, Arcade_Classics, BMX_Kidz,
# Chimera, I_Ball, Kings_of_the_Beach_intro, Last_V8, Last_V8_C128_version,
# Mega_Apocalypse, Mr_Meaner, Off_the_Cuff, One_on_One, Powerplay_Hockey,
# Ricochet, Rikky, Rock_Tells_the_Tale, Skate_or_Die_intro, Tarzan -- and that
# set includes all four NTSC files and Skate_or_Die_intro, the one v0.5.63
# fixed, so the only check covering the unmeasured region could not reach the
# files this project changed most.
#
# VICE's vsid reads both. The one thing that matters in the invocation is that
# it must run **without `-warp`**: warp suppresses the sound device's output
# whatever `-soundwarpmode` says, and that is what produced the 44-byte
# header-only file in three earlier attempts. `-soundwarpmode 1` does not
# rescue it -- tested. Rendering is therefore realtime, which is why this is a
# fallback rather than the default.
VSID = r"C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\vsid.exe"
PAL_CYCLES_PER_SECOND = 985248
# A WAV header with no samples. The failure this fallback exists to avoid, and
# the shape a silent success takes here.
EMPTY_WAV = 64


def render_vsid(sid: Path, out: Path, seconds: int, subtune: int,
                exe: str = VSID) -> bool:
    """One .sid to one WAV via VICE, for the files SID2WAV cannot read.

    `-tune` is 1-based like sid2wav's `-o`, and `-limitcycles` is what makes it
    terminate -- without it vsid plays forever.
    """
    out.unlink(missing_ok=True)
    try:
        subprocess.run([exe, "-console", "-sounddev", "wav",
                        "-soundarg", str(out),
                        "-limitcycles", str(seconds * PAL_CYCLES_PER_SECOND),
                        "-tune", str(subtune + 1), str(sid)],
                       capture_output=True, timeout=seconds * 6 + 120,
                       stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return out.exists() and out.stat().st_size > EMPTY_WAV


def _sid2wav_can_read(sid: Path, exe: str = SID2WAV) -> bool:
    """True if SID2WAV recognises this file at all -- i.e. it is not an RSID.

    Read from the magic rather than by running it: `RSID` is the only thing in
    the corpus it refuses, and a header test costs nothing where a trial
    render costs a realtime pass.
    """
    try:
        with open(sid, "rb") as fh:
            return fh.read(4) != b"RSID"
    except OSError:
        return False


def render(sid: Path, out: Path, seconds: int, subtune: int,
           exe: str = SID2WAV) -> bool:
    """One .sid to one 16-bit 44.1 kHz WAV. sid2wav's -o is 1-based."""
    out.unlink(missing_ok=True)
    try:
        subprocess.run([exe, "-16", f"-t{seconds}", f"-o{subtune + 1}",
                        str(sid), str(out)],
                       capture_output=True, timeout=300,
                       stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        pass
    if out.exists() and out.stat().st_size > EMPTY_WAV:
        return True
    # SID2WAV refused it -- an RSID, in every corpus case. VICE reads those.
    return render_vsid(sid, out, seconds, subtune)


def pick(rows: list[dict], per_band: int) -> list[tuple[str, dict]]:
    """One representative per band: the median score, not the extreme.

    The extremes teach the least -- the worst file is usually broken in a way
    already understood, and the best is the fixture. A file at the middle of
    its band is the one whose band membership is actually in question. Files
    the original barely plays are skipped where there is an alternative,
    because a tune with six notes cannot be judged by ear either.
    """
    out = []
    for label, lo, hi, _ in BANDS:
        got = [r for r in rows
               if r.get("status") in ("measured", "silent")
               and not r.get("traced_subtune_dropped")
               and lo <= r.get("melody", -1) < hi]
        if not got:
            continue
        meaty = [r for r in got if r.get("orig_attacks", 0) >= 20] or got
        meaty.sort(key=lambda r: r["melody"])
        mid = len(meaty) // 2
        # Walk outward from the median so per_band > 1 stays near the middle.
        order = sorted(range(len(meaty)), key=lambda i: abs(i - mid))
        for i in order[:per_band]:
            out.append((label, meaty[i]))
    return out


def listen_notes(r: dict, orig, ours) -> list[str]:
    """What the numbers predict, in the terms a listener would use.

    Every line is derived from a measurement, so a listen that disagrees with
    one is a finding: either the metric is blind to something or it is wrong.
    """
    notes = []
    rr = r.get("retrigger_ratio")
    if rr and rr >= 1.25:
        notes.append(
            f"**Re-striking.** We play {rr:.2f} attacks per original attack, so "
            "expect notes hammered where the original holds them -- a stutter "
            "or machine-gun quality on sustained notes.")
    elif rr and rr <= 0.8:
        notes.append(
            f"**Under-striking.** Only {rr:.2f} attacks per original attack: "
            "notes that should be re-struck are being held instead, which "
            "sounds like a missing rhythm rather than a wrong one.")

    o_slides = sum(v.slides for v in orig)
    u_slides = sum(v.slides for v in ours)
    if o_slides >= 20 and u_slides < o_slides // 4:
        notes.append(
            f"**No pitch movement.** The original slides {o_slides} times and "
            f"we slide {u_slides}: vibrato, portamento and drum pitch-sweeps "
            "are the things to listen for missing.")

    o_ties = sum(v.ties for v in orig)
    u_ties = sum(v.ties for v in ours)
    if o_ties >= 20 and u_ties < o_ties // 4:
        notes.append(
            f"**No legato.** {o_ties} note changes without a re-trigger in the "
            f"original, {u_ties} in ours -- every note is re-attacked, so "
            "phrases that should flow will sound detached.")

    pj = r.get("pitch_jaccard")
    if pj is not None and pj < 0.6:
        notes.append(
            f"**Wrong pitches, not just wrong order.** Only {100 * pj:.0f}% of "
            "the distinct notes played are shared, so listen for an octave "
            "error or a transpose rather than a rhythmic fault.")

    silent = [i + 1 for i, v in enumerate(ours) if not v.attacks
              and orig[i].attacks]
    if silent:
        notes.append(
            f"**Voice {', '.join(map(str, silent))} silent.** The original "
            "plays it and we do not, so something is missing outright rather "
            "than merely wrong.")

    if not notes:
        notes.append(
            "The measurement finds nothing to flag. Anything heard here is "
            "something no check in the repo can see -- report it, it is the "
            "reason this pass exists.")
    return notes


def select_names(files, stage_all: bool, presets: str) -> list[str]:
    """Which tunes to stage, from `--files` and `--all`.

    `--all` reads the song list out of `presets.json` rather than the corpus
    directory, because that list is exactly the tunes that *convert*: reading
    the directory would queue the twelve files no player is detected in and
    render a silent conversion side for each, which looks like a fidelity
    catastrophe rather than an absent player.

    The two combine rather than compete -- `--files X --all` is every song
    plus X, which is how a tune outside the presets (a second rip, a file
    under test) joins a full pass.
    """
    names = list(files)
    if not stage_all:
        return names
    try:
        doc = json.loads(Path(presets).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"--all needs {presets}; run presets.py first") from exc
    songs = doc.get("songs") or {}
    if not songs:
        raise ValueError(f"{presets} records no songs")
    return sorted(set(names) | set(songs), key=str.lower)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="listen", description=__doc__.splitlines()[0])
    p.add_argument("sid_dir", nargs="?", help="directory holding the originals")
    p.add_argument("--from-json", help="a fidelity.py --json run, used to pick "
                                       "representatives and to state the numbers")
    p.add_argument("--files", nargs="+", default=[], help="stage these instead")
    p.add_argument("--all", action="store_true",
                   help="stage every tune `--presets` records, which is every "
                        "one that converts. The whole corpus at -t 120 is "
                        "about 1.7 GB and a couple of hours; --files is the "
                        "way to stage the handful a question is about")
    p.add_argument("-n", "--per-band", type=int, default=1)
    p.add_argument("-t", "--seconds", type=int, default=30,
                   help="how much to render (default 30: long enough to reach "
                        "a second section, short enough to sit through)")
    p.add_argument("-a", "--subtune", type=int, default=0)
    p.add_argument("-o", "--outdir", default=str(Path(__file__).resolve().parent.parent
                                                 / "build" / "listen"))
    p.add_argument("--presets", default=str(Path(__file__).resolve().parent.parent
                                            / "presets.json"))
    p.add_argument("--sid2wav", default=SID2WAV)
    p.add_argument("--gt2reloc", default=GT2RELOC)
    p.add_argument("--siddump", default=SIDDUMP)
    # Shares fidelity.py's scratch layout, and so its collision: a.sng/b.sid
    # are fixed names, and staging a listening pass while a measurement runs
    # would have both writing them. Default is a private directory per run.
    p.add_argument("--workdir", default=WORKDIR)
    args = p.parse_args(argv)

    if not Path(args.sid2wav).exists():
        print(f"error: sid2wav not found: {args.sid2wav}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    if args.from_json:
        rows = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    chosen: list[tuple[str, dict]] = []
    try:
        names = select_names(args.files, args.all, args.presets)
    except ValueError as exc:
        p.error(str(exc))
    if names:
        by_name = {r["file"]: r for r in rows}
        chosen = [("named", by_name.get(f, {"file": f})) for f in names]
    elif rows:
        chosen = pick(rows, args.per_band)
    else:
        p.error("give --from-json (to pick by band), --files or --all")

    sid_dir = Path(args.sid_dir) if args.sid_dir else None
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    workdir, owned_workdir = make_workdir(args.workdir)
    doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))

    lines = [
        "# Listening pass",
        "",
        f"Staged by `python/listen.py` (h2g {__version__}), {args.seconds} s of "
        f"subtune {args.subtune}, rendered by `SID2WAV` at 44.1 kHz/16-bit.",
        "",
        "Play `<name>.original.wav` and `<name>.h2g.wav` back to back. Both "
        "come from the same emulator at the same settings, so every difference "
        "is a difference in the music.",
        "",
        "**The numbers below are not the question.** `FIDELITY.md` compares "
        "note *attacks* and nothing else; it cannot hear an envelope, a "
        "filter, a tempo or a timbre, and it scored zero change for a fix that "
        "rewrote 66 rows of one file. Each entry says what the measurement "
        "predicts so that a listen can contradict it. A contradiction is the "
        "useful outcome.",
        "",
    ]

    staged = 0
    for label, r in chosen:
        name = r["file"]
        src = (sid_dir / name) if sid_dir else Path(name)
        if not src.exists():
            print(f"  {name:44} missing", file=sys.stderr)
            continue
        stem = name[:-4] if name.lower().endswith(".sid") else name

        try:
            sng = convert(str(src), log=lambda m: None, **_preset_opts(doc, name))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:44} not converted", file=sys.stderr)
            lines += [f"## {stem} — *{label}*", "",
                      f"Does not convert: `{type(exc).__name__}: {exc}`", ""]
            continue
        sng_out = outdir / f"{stem}.h2g.sng"
        sng_out.write_bytes(sng)

        # The multiplier is not optional here, as it is in fidelity.py. siddump
        # ignores the PSID speed field, so a trace is identical with and without
        # -S; a *render* is not. Packed at -S1 a tune whose player wants two
        # calls per frame plays at half speed, which is what a listener hears
        # first and what the attack metric can never report. Reported by ear on
        # Formula_1_Simulator, where every staged file had multiplier 2.
        multiplier = _preset_multiplier(doc, name)
        packed = pack_sid(legalise_restarts(sng)[0], workdir, args.gt2reloc,
                          multiplier)
        if packed is None:
            print(f"  {name:44} not packed", file=sys.stderr)
            lines += [f"## {stem} — *{label}*", "",
                      "`gt2reloc` refused this conversion, so there is nothing "
                      "to render. The `.sng` is staged; open it in GoatTracker.",
                      ""]
            continue
        ours_sid = outdir / f"{stem}.h2g.sid"
        shutil.copyfile(packed, ours_sid)

        # Both sides through one renderer. Where the original is an RSID only
        # VICE can read it, and gt2reloc always writes a PSID -- so a naive
        # fallback would put sid2wav on one side of the pair and vsid on the
        # other. Two emulations differ in level and filter enough to colour a
        # listening judgement, which is the one thing this staging exists to
        # support.
        ok_a = render(src, outdir / f"{stem}.original.wav", args.seconds,
                      args.subtune, args.sid2wav)
        both_vice = ok_a and not _sid2wav_can_read(src, args.sid2wav)
        render_pair = render_vsid if both_vice else render
        if both_vice:
            print(f"  {name:44} rendered by VICE (RSID)", file=sys.stderr)
        ok_b = render_pair(ours_sid, outdir / f"{stem}.h2g.wav", args.seconds,
                           args.subtune)

        orig = run_siddump(src, args.seconds, args.subtune, args.siddump)
        ours = run_siddump(ours_sid, args.seconds, args.subtune, args.siddump)

        band = next((b for b in BANDS if b[0] == label), None)
        lines += [f"## {stem} — *{label}*", ""]
        if band:
            lines += [f"> {band[3]}", ""]
        if r.get("melody") is not None:
            lines.append(
                f"Measured: melody **{100 * r['melody']:.0f}%**, retrigger "
                f"**{r['retrigger_ratio']:.2f}**, pitch overlap "
                f"**{100 * r['pitch_jaccard']:.0f}%** "
                f"({r['orig_attacks']} attacks in the original, "
                f"{r['our_attacks']} in ours).")
            lines.append("")
        if multiplier > 1:
            lines += [f"Packed at `-S{multiplier}`: this player wants "
                      f"{multiplier} calls per frame, so the CIA stub runs the "
                      f"tune at {50 * multiplier} Hz. Rate is the one thing "
                      f"`FIDELITY.md` cannot check at all -- siddump ignores "
                      f"the PSID speed field -- so if this sounds slow or fast "
                      f"against the original, say so.", ""]
        for note in listen_notes(r, orig, ours):
            lines += [f"- {note}"]
        lines += [""]
        if not (ok_a and ok_b):
            lines += ["*(One or both renders failed; the `.sid` files are "
                      "staged, play them directly.)*", ""]
        staged += 1
        print(f"  {name:44} staged ({label})", file=sys.stderr)

    lines += [
        "## What to write down",
        "",
        "For each tune, one line: *does it sound like the same piece of "
        "music*, and *what is the first thing that sounds wrong*. The second "
        "is the valuable half — it is the only channel in this project that "
        "reports defects the attack comparison is structurally blind to.",
        "",
    ]
    (outdir / "LISTENING.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"staged {staged} tune(s) -> {outdir}", file=sys.stderr)
    if owned_workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
