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
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fidelity import (_preset_opts, _preset_multiplier, legalise_restarts,
                      make_workdir, pack_sid, resolve_subtune, run_siddump,
                      GT2RELOC, SIDDUMP, WORKDIR)
from h2g import __version__
from h2g.convert import convert

SID2WAV = r"C:\Users\mit\claude\c64server\SIDM2\tools\SID2WAV.EXE"
# libsidplayfp's own frontend. sid2wav is a 1997 build of the same lineage;
# this is the current one, and the only renderer here that reads the whole
# corpus with one engine. Needs the C64 ROMs in sidplayfp.ini for RSIDs.
SIDPLAYFP = r"C:\Users\mit\Downloads\sidplayfp-2.15.2-32bit-mmx\sidplayfp.exe"

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
# Where fidelity.py --json writes by convention (see CLAUDE.md's regeneration
# order). Consulted automatically by `--all`/`--files` when `--from-json` was
# not given, so that `pair_subtunes` can recover `matched_subtune` instead of
# guessing -- see the docstring there. A hazard artefact: read-only, and a
# fresh checkout has none, which is why every use of this path is guarded by
# `.exists()` rather than assumed.
DEFAULT_FIDELITY_JSON = Path(__file__).resolve().parent.parent / "build" / "fidelity.json"
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


def render_sidplayfp(sid: Path, out: Path, seconds: int, subtune: int,
                     exe: str = SIDPLAYFP, mute: tuple = ()) -> bool:
    """One .sid to one WAV via libsidplayfp's own frontend.

    The preferred renderer, and the only one that reads the whole corpus with
    one engine. `SID2WAV` is version 1.8 from 1997: it refuses every RSID (18
    of the 95 corpus files) and **fades the last seconds out**, which quietly
    corrupts the end of any comparison. VICE's `vsid` reads everything but is
    driven by `-limitcycles`, which overshot a 20 s request by 1.76 s in
    testing, so its output is not the length asked for.

    `-fo0` is the fade-off that sid2wav has no switch for; `-o<n>` is 1-based
    like sid2wav's; `-p16 -m -f44100` fixes the format the rest of the harness
    assumes.

    **RSID files need the C64 ROMs.** Without them libsidplayfp runs the tune
    with no KERNAL and dies on an illegal instruction, having written a 44-byte
    header -- so a missing ROM looks exactly like a tune that renders silence.
    Point `Kernal Rom` / `Basic Rom` / `Chargen Rom` in `sidplayfp.ini` at
    VICE's `C64/` directory; the file-size check below is what turns the
    failure into a fallback rather than a silent empty pair.
    """
    out.unlink(missing_ok=True)
    # `-u<n>` mutes a voice, 1-based like `-o`. It silences the emulator's
    # OUTPUT and does not touch what the play routine writes, which is why a
    # solo render can be compared against the full mix at all -- see the
    # sum check in tests and the --voices note in main().
    mutes = [f"-u{v}" for v in mute]
    try:
        subprocess.run([exe, f"-t{seconds}", "-f44100", "-p16", "-m", "-fo0",
                        f"-o{subtune + 1}", *mutes, f"-w{out}", str(sid)],
                       capture_output=True, timeout=seconds * 6 + 120,
                       stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return out.exists() and out.stat().st_size > EMPTY_WAV


class Choice(NamedTuple):
    """What `pick_renderer` decided: the callable, the reason, the engine.

    `engine` is here so the staged `LISTENING.md` can name the renderer that
    actually ran. It used to assert `SID2WAV` from a fixed string, true when
    written and wrong from v0.5.308 -- and a listening pass is the one artefact
    whose renderer a reader has to be able to trust, since the whole point is
    that a difference heard is a difference in the music. The fallback is per
    *pair*, so a pass can legitimately use more than one engine and the header
    reports what ran rather than what was preferred.
    """
    render: object
    why: str
    engine: str


def pick_renderer(sid: Path, args, probe_dir: Path | None = None) -> Choice:
    """One renderer for both sides of a pair, and the reason for it.

    Chosen by trying the preferred engine on the *original* -- the harder of
    the two, since `gt2reloc` always writes a PSID and the original may be an
    RSID. Returning one callable is what makes it impossible to render the two
    sides with different emulations, which was reachable before by fallback.

    **`probe_dir` must be private to the run.** The probe is a fixed filename,
    and the first draft put it in the output directory -- which two sharded
    passes share, so they raced on it and one shard silently staged nothing.
    That is the same defect `make_workdir` was added for in v0.5.66, reached
    by a different route.
    """
    # `--subtune auto` is per file, so the probe resolves it here rather than
    # reading a raw "auto" out of args and handing it to a `-o` switch.
    sub = resolve_subtune(sid, getattr(args, "subtune", 0))
    if Path(args.sidplayfp).exists():
        out = (probe_dir or Path(args.outdir)) / "_probe.wav"
        if render_sidplayfp(sid, out, 1, sub, args.sidplayfp):
            out.unlink(missing_ok=True)
            return Choice(lambda s, o, sec, sub, mute=(): render_sidplayfp(
                s, o, sec, sub, args.sidplayfp, mute), "", "sidplayfp")
        out.unlink(missing_ok=True)
        why = "sidplayfp refused it (C64 ROMs configured?)"
    else:
        why = ""
    if _sid2wav_can_read(sid, args.sid2wav):
        return Choice(lambda s, o, sec, sub, mute=(): (
            not mute and render(s, o, sec, sub, args.sid2wav)),
            (why and why + ", using sid2wav"), "sid2wav")
    # A fallback that cannot mute must REFUSE a per-voice render. Returning
    # the full mix would stage three identical "solo" files that look like
    # three voices and are one -- a listening pass cannot survive that.
    return Choice(lambda s, o, sec, sub, mute=(): (
        not mute and render_vsid(s, o, sec, sub)),
        "rendered by VICE (RSID)", "vsid")


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


def split_notes(text: str) -> tuple[str, dict[str, str], str]:
    """A LISTENING.md as (preamble, {tune: section}, closing section)."""
    parts = re.split(r"(?m)^(## .+)$", text)
    head, out, tail = parts[0], {}, ""
    for title, body in zip(parts[1::2], parts[2::2]):
        name = title[3:].split(" —")[0].strip()
        if name.lower().startswith("what to write"):
            tail = title + body
        else:
            out[name] = title + body
    return head, out, tail


def trace_json(orig, ours, seconds: int, mult_o: int, mult_b: int,
               sub_o: int = 0, sub_b: int = 0) -> dict:
    """Both sides' register events, in the shape the A/B page's panel reads.

    Sparse by construction -- these are siddump's own change events, so a
    register held for 3000 frames costs one entry. A 120 s pair comes to tens
    of KB where a per-frame table would be megabytes.

    `freq` is dropped: the panel says *which capabilities are used*, and
    frequency is the one register that changes on nearly every frame, so it
    would dominate the file while answering nothing the panel asks.
    """
    def side(tr, mult):
        return {
            "mult": mult,
            "voices": [{"wf": v.wf_events, "adsr": v.adsr_events,
                        "pulse": v.pulse_events} for v in tr],
            "filter": {"cutoff": tr.filter.cutoff_events,
                       "ctrl": tr.filter.ctrl_events,
                       "passband": tr.filter.passband_events,
                       "volume": tr.filter.volume_events},
        }

    return {"seconds": seconds, "frames": seconds * 50,
            "sub_orig": sub_o, "sub_ours": sub_b,
            "orig": side(orig, mult_o), "ours": side(ours, mult_b)}


def merge_notes(outdir: Path) -> int:
    """Fold a sharded run's LISTENING.part*.md into one LISTENING.md.

    Every `listen.py` run writes the whole document, so shards sharing an
    output directory would leave only the last one's notes -- and `abpage.py`
    reads that file for each tune's "what to listen for", so the loss is
    silent and looks like tunes that were never staged. Sharded runs therefore
    write parts, and this joins them.

    An existing LISTENING.md is merged in rather than replaced, so staging a
    few more tunes into a directory does not discard the notes already there.

    **The header comes from a part, never from the file already there.** The
    preamble states the version, the window, the subtune and the renderer, so
    a header carried over from a previous pass describes a run that no longer
    exists -- and `_policy_header` is written precisely so that whichever part
    supplies it, the claim is true of this run. Preferring the existing file's
    published `h2g 0.5.306, 30 s of subtune 0, rendered by SID2WAV` over a
    0.5.316 / 120 s / `startSong` / `sidplayfp` pass: the same drift v0.5.311
    fixed for the single-process path, reintroduced by the sharded one because
    the old file was first in the merge order and `head or h` keeps the first.
    Sections still merge in that order, so a re-staged tune's notes replace
    the stale ones; only the two whole-document fields take the last writer.
    """
    parts = sorted(outdir.glob("LISTENING.part*.md"))
    if not parts:
        return 0
    head, merged, tail = "", {}, ""
    for src in [outdir / "LISTENING.md"] + parts:
        if not src.exists():
            continue
        h, secs, t = split_notes(src.read_text(encoding="utf-8"))
        head = h or head
        tail = t or tail
        merged.update(secs)
    body = "".join(merged[k] for k in sorted(merged, key=str.lower))
    (outdir / "LISTENING.md").write_text(head + body + tail, encoding="utf-8")
    for src in parts:
        src.unlink()
    return len(merged)


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


def _load_fidelity_rows(path: Path) -> list[dict]:
    """Rows from a fidelity.py --json run, or [] if there is nothing to read.

    `path` is a hazard artefact this script only ever reads -- another lane
    regenerates it, and a fresh checkout has none at all -- so both "the file
    is missing" and "the file is not valid JSON" are the ordinary case, not
    an error worth stopping the run for.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def resolve_matched_subtunes(rows: list[dict], from_json_given: bool,
                             default_path: Path = DEFAULT_FIDELITY_JSON) -> dict[str, int]:
    """The `{file: matched_subtune}` map `pair_subtunes` falls back to.

    An explicit `--from-json` run already is the source of truth: `rows` is
    read as given and `default_path` is never even opened, so a stale or
    absent `build/fidelity.json` cannot second-guess a run that named its own
    data. Only when no `--from-json` was given -- the `--all`/`--files`-alone
    case this function exists for -- does it fall back to whatever already
    sits at `default_path`, via `_load_fidelity_rows`, which turns "missing"
    and "unreadable" both into "nothing recovered" rather than an error.
    """
    sub_rows = rows if from_json_given else _load_fidelity_rows(default_path)
    return {r["file"]: r["matched_subtune"] for r in sub_rows
            if "matched_subtune" in r}


def pair_subtunes(src: Path, row: dict, requested, matched=None) -> tuple[int, int]:
    """Which subtune to render, per side of the pair.

    The original's is its own `startSong`, the same rule `fidelity.py` traces
    by: it is not 0 in seven corpus files, and staging subtune 0 for those
    invites a listening verdict about music the conversion was never compared
    against -- Samantha Fox Strip Poker's subtune 0 is a one-note stub scoring
    5% where its real one scores 89%.

    Ours can be a *different index for the same tune*, because a subtune whose
    orderlist gt2reloc drops shifts every later one down. A `fidelity.py` row
    that searched for the counterpart records it as `matched_subtune`, and
    `row` carries it whenever `--from-json` named a row for this file.

    `matched` is the fallback for when it did not: `--all`/`--files` without
    `--from-json` stage a bare `{"file": f}`, so `row` alone has nothing to
    give. `main` passes the same field recovered from `build/fidelity.json`
    when that file exists, and `row`'s own value wins if both are present --
    an explicit `--from-json` row is a claim about *this* run, a leftover
    fidelity.json is a claim about some previous one.

    Absent BOTH, this returns `sub_orig` for both sides -- correct for all
    but three corpus files today, and wrong by coincidence rather than by
    rule: before f63caa1 the same fallback silently staged different music for
    Action Biker, Samantha Fox and Spellbound, and nothing here can tell that
    case apart from a genuine identity pairing. `main` counts how often this
    branch is taken and says so, because a listener who hears a mismatch
    should not have to re-derive that this is where it would come from.
    """
    sub_orig = resolve_subtune(src, requested)
    if "matched_subtune" in row:
        return sub_orig, int(row["matched_subtune"])
    if matched is not None:
        return sub_orig, int(matched)
    return sub_orig, sub_orig


def document_header(args, engines, rendered_subtunes, shard=None) -> list[str]:
    """The preamble of `LISTENING.md`, written from what the run actually did.

    Every fact here was once a constant, and one of them went stale silently:
    the line said `SID2WAV` for four versions after v0.5.308 moved the staging
    to `sidplayfp`, so the artefact that exists to make a listener trust "every
    difference is a difference in the music" was naming the wrong emulator. A
    header derived from `engines` cannot drift from the run that produced it.

    It also states the *subtune*, for the same reason: it is per file now, and
    a pass that renders one number for every tune has to say which -- seven
    corpus files name something other than 0 as their own `startSong`.

    **A shard counts nothing.** `merge_notes` publishes one part's header for
    the whole document, so a count taken over one shard's tunes would be
    published as a count over the whole pass. Under `--shard` the same two
    facts are therefore stated as the policy rather than as totals, which
    stays true whichever part wins the merge. Which part that is was not
    always a part at all: until v0.5.317 the merge preferred the header of the
    LISTENING.md already in the directory, so this guarantee held for every
    header except the one actually published.
    """
    if shard:
        return _policy_header(args)
    if len(engines) > 1:
        named = ", ".join(f"`{n}` ({c})" for n, c in engines.most_common())
        engine_note = (
            f"rendered by {named} -- the choice is made per *pair*, so each "
            "comparison is internally consistent, but two tunes rendered by "
            "different engines are not comparable with each other")
    elif engines:
        engine_note = f"rendered by `{next(iter(engines))}`"
    else:
        engine_note = "nothing rendered"
    subs = {o for _, o, _ in rendered_subtunes} | {u for _, _, u in rendered_subtunes}
    if args.subtune != "auto":
        sub_note = f"subtune {args.subtune}"
    elif subs == {0}:
        sub_note = "subtune 0, which is every file's own `startSong` here"
    else:
        n = sum(1 for _, o, u in rendered_subtunes if o or u != o)
        sub_note = (f"each file's own subtune (PSID `startSong`; {n} of "
                    f"{len(rendered_subtunes)} are not 0)")
    return [
        "# Listening pass",
        "",
        f"Staged by `python/listen.py` (h2g {__version__}), {args.seconds} s "
        f"of {sub_note}, {engine_note} at 44.1 kHz/16-bit mono.",
        "",
        "Play `<name>.original.wav` and `<name>.h2g.wav` back to back. Both "
        "sides of a pair come from the same emulator at the same settings, so "
        "every difference within a pair is a difference in the music.",
        "",
        "**The numbers below are not the question.** `FIDELITY.md` compares "
        "note *attacks* and nothing else; it cannot hear an envelope, a "
        "filter, a tempo or a timbre, and it scored zero change for a fix that "
        "rewrote 66 rows of one file. Each entry says what the measurement "
        "predicts so that a listen can contradict it. A contradiction is the "
        "useful outcome.",
        "",
    ]


def _policy_header(args) -> list[str]:
    """The header for a shard: the same claims, stated without totals.

    Written separately rather than as branches inside `document_header`, so
    that the counted form cannot acquire a count the merge would misreport.
    """
    sub_note = ("each file's own subtune (PSID `startSong`)"
                if args.subtune == "auto" else f"subtune {args.subtune}")
    return [
        "# Listening pass",
        "",
        f"Staged by `python/listen.py` (h2g {__version__}), {args.seconds} s "
        f"of {sub_note}, at 44.1 kHz/16-bit mono. Each pair is rendered by one "
        f"engine -- `sidplayfp` where it reads the original, otherwise the "
        f"fallback named beside that tune below.",
        "",
        "Play `<name>.original.wav` and `<name>.h2g.wav` back to back. Both "
        "sides of a pair come from the same emulator at the same settings, so "
        "every difference within a pair is a difference in the music.",
        "",
        "**The numbers below are not the question.** `FIDELITY.md` compares "
        "note *attacks* and nothing else; it cannot hear an envelope, a "
        "filter, a tempo or a timbre, and it scored zero change for a fix that "
        "rewrote 66 rows of one file. Each entry says what the measurement "
        "predicts so that a listen can contradict it. A contradiction is the "
        "useful outcome.",
        "",
    ]


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
    p.add_argument("--traces-only", action="store_true",
                   help="skip rendering and write only <name>.trace.json, the "
                        "register data the A/B page's panel reads. Two siddump "
                        "runs a tune against eight renders, for when the WAVs "
                        "are already staged.")
    p.add_argument("--voices", action="store_true",
                   help="also stage each voice alone, both sides: six extra "
                        "renders a tune (V1/V2/V3 x original/ours) via "
                        "sidplayfp's -u. Per song on demand -- it quadruples "
                        "render time and disk, and the full corpus is already "
                        "1.7 GB. A renderer that cannot mute refuses rather "
                        "than staging the full mix three times.")
    p.add_argument("-n", "--per-band", type=int, default=1)
    p.add_argument("-t", "--seconds", type=int, default=30,
                   help="how much to render (default 30: long enough to reach "
                        "a second section, short enough to sit through)")
    p.add_argument("-a", "--subtune", default="auto",
                   help="which subtune to render: a number, or 'auto' (the "
                        "default) for each file's own PSID `startSong`. It is "
                        "not 0 in seven corpus files, and Samantha Fox Strip "
                        "Poker's subtune 0 is a one-note stub -- staging that "
                        "against a correct conversion invites a listening "
                        "verdict about the wrong music")
    p.add_argument("-o", "--outdir", default=str(Path(__file__).resolve().parent.parent
                                                 / "build" / "listen"))
    p.add_argument("--presets", default=str(Path(__file__).resolve().parent.parent
                                            / "presets.json"))
    p.add_argument("--shard", default=None, metavar="I/N",
                   help="stage only every Nth tune, starting at I (0-based), "
                        "so a pass can be split across processes. Each shard "
                        "writes its notes to LISTENING.part<I>.md rather than "
                        "to LISTENING.md, because otherwise the last shard to "
                        "finish would be the only one whose notes survived; "
                        "run --merge-notes afterwards. The whole corpus at "
                        "-t 120 is about 95 minutes serially and 16 across six")
    p.add_argument("--merge-notes", action="store_true",
                   help="combine the LISTENING.part*.md a sharded run left "
                        "into one LISTENING.md, and delete the parts")
    p.add_argument("--sidplayfp", default=SIDPLAYFP,
                   help="libsidplayfp's frontend, the preferred renderer: one "
                        "engine for the whole corpus, no fade-out, and it "
                        "reads the RSIDs sid2wav refuses")
    p.add_argument("--sid2wav", default=SID2WAV)
    p.add_argument("--gt2reloc", default=GT2RELOC)
    p.add_argument("--siddump", default=SIDDUMP)
    # Shares fidelity.py's scratch layout, and so its collision: a.sng/b.sid
    # are fixed names, and staging a listening pass while a measurement runs
    # would have both writing them. Default is a private directory per run.
    p.add_argument("--workdir", default=WORKDIR)
    args = p.parse_args(argv)

    # sidplayfp is preferred but sid2wav and vsid still stand behind it, so
    # requiring only that *some* renderer exists is what lets a machine with
    # one of them stage a pass.
    if not any(Path(x).exists() for x in (args.sidplayfp, args.sid2wav, VSID)):
        print("error: no renderer found. Tried sidplayfp "
              f"({args.sidplayfp}), sid2wav ({args.sid2wav}) and vsid "
              f"({VSID}).", file=sys.stderr)
        return 1

    if args.merge_notes:
        n = merge_notes(Path(args.outdir))
        print(f"merged notes for {n} tune(s) -> {Path(args.outdir)/'LISTENING.md'}"
              if n else "no LISTENING.part*.md to merge", file=sys.stderr)
        return 0 if n else 1

    rows: list[dict] = []
    if args.from_json:
        rows = json.loads(Path(args.from_json).read_text(encoding="utf-8"))

    # `matched_subtune` recovers the subtune correspondence `pair_subtunes`
    # otherwise has to guess at (see its docstring and `resolve_matched_subtunes`).
    matched_subtunes = resolve_matched_subtunes(rows, bool(args.from_json))
    if not args.from_json and matched_subtunes:
        print(f"note: recovered matched_subtune for {len(matched_subtunes)} "
              f"file(s) from {DEFAULT_FIDELITY_JSON} (no --from-json given)",
              file=sys.stderr)

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

    shard = None
    if args.shard:
        try:
            shard = tuple(int(x) for x in args.shard.split("/"))
            index, count = shard
        except ValueError:
            p.error(f"--shard {args.shard}: expected I/N")
        if not 0 <= index < count:
            p.error(f"--shard {args.shard}: I must be in 0..N-1")
        # Sliced off the list every shard builds, so the union of 0/N..N-1/N
        # is exactly the unsharded pass and no two overlap.
        chosen = chosen[index::count]
        print(f"shard {index}/{count}: {len(chosen)} tune(s)", file=sys.stderr)

    sid_dir = Path(args.sid_dir) if args.sid_dir else None
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    workdir, owned_workdir = make_workdir(args.workdir)
    doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))

    # The header is assembled *after* the loop, from what the run actually
    # did. Both of the facts it states -- the renderer and the subtune -- are
    # per file now, and stating either from a constant is how it came to claim
    # `SID2WAV` for a pass that v0.5.308 had moved to `sidplayfp`.
    engines: Counter[str] = Counter()
    rendered_subtunes: list[tuple[str, int, int]] = []
    lines: list[str] = []

    staged = 0
    # Tunes paired by the sub_orig == sub_ours coincidence rather than a
    # measured correspondence -- see pair_subtunes. Reported once at the end
    # rather than per file, so the assumption is visible without repeating
    # the same line 80 times.
    paired_by_identity: list[str] = []
    for label, r in chosen:
        name = r["file"]
        src = (sid_dir / name) if sid_dir else Path(name)
        if not src.exists():
            print(f"  {name:44} missing", file=sys.stderr)
            continue
        stem = name[:-4] if name.lower().endswith(".sid") else name

        sub_orig, sub_ours = pair_subtunes(src, r, args.subtune,
                                          matched_subtunes.get(name))
        if "matched_subtune" not in r and name not in matched_subtunes:
            paired_by_identity.append(name)
        rendered_subtunes.append((stem, sub_orig, sub_ours))

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

        # Both sides through one renderer, which is the one thing this staging
        # exists to support: two emulations differ in level and filter enough
        # to colour a listening judgement. `pick_renderer` returns a single
        # callable used for both sides, so the pair can never be split.
        if getattr(args, "traces_only", False):
            # No renderer is chosen at all: picking one probes with a 1 s
            # render, which is exactly the cost this mode exists to avoid.
            render_pair, why = (lambda *a, **k: True), ""
        else:
            choice = pick_renderer(src, args, workdir)
            render_pair, why = choice.render, choice.why
            engines[choice.engine] += 1
            if why:
                print(f"  {name:44} {why}", file=sys.stderr)
        skip_renders = getattr(args, "traces_only", False)
        ok_a = skip_renders or render_pair(
            src, outdir / f"{stem}.original.wav", args.seconds, sub_orig)
        ok_b = skip_renders or render_pair(
            ours_sid, outdir / f"{stem}.h2g.wav", args.seconds, sub_ours)

        # Each voice alone, both sides. `-u` is 1-based, so soloing voice v
        # mutes the other two. The A/B page reads these when its voice
        # selector is used; without them it plays the full mix as before, so
        # staging without --voices costs nothing and loses nothing.
        if getattr(args, "voices", False) and not getattr(args, "traces_only", False):
            solo_ok = 0
            for v in (1, 2, 3):
                others = tuple(x for x in (1, 2, 3) if x != v)
                solo_ok += bool(render_pair(
                    src, outdir / f"{stem}.v{v}.original.wav",
                    args.seconds, sub_orig, others))
                solo_ok += bool(render_pair(
                    ours_sid, outdir / f"{stem}.v{v}.h2g.wav",
                    args.seconds, sub_ours, others))
            if solo_ok < 6:
                print(f"  {name:44} per-voice: {solo_ok}/6 rendered "
                      f"({choice.engine} cannot mute)", file=sys.stderr)

        orig = run_siddump(src, args.seconds, sub_orig, args.siddump)
        ours = run_siddump(ours_sid, args.seconds, sub_ours, args.siddump)

        # The register panel's data. Written beside the pair so `abpage.py`
        # can build the panel without re-tracing anything.
        (outdir / f"{stem}.trace.json").write_text(
            json.dumps(trace_json(orig, ours, args.seconds, 1, multiplier,
                                  sub_orig, sub_ours),
                       separators=(",", ":")), encoding="utf-8")

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
        if sub_orig or sub_ours != sub_orig:
            lines += [f"Rendered at subtune **{sub_orig}** of the original"
                      + (f" against **{sub_ours}** of ours (our numbering "
                         f"shifted when a subtune was dropped)"
                         if sub_ours != sub_orig else "")
                      + ", the PSID header's own `startSong`.", ""]
        if name in paired_by_identity:
            lines += ["*No measured subtune correspondence was available "
                      "for this pairing (no `--from-json` row, and no "
                      f"`{DEFAULT_FIDELITY_JSON.name}` at the default "
                      "location); both sides were staged at the same index "
                      "on the assumption that gt2reloc dropped nothing "
                      "ahead of it. If this sounds like two different "
                      "pieces of music, that assumption is the first thing "
                      "to check.*", ""]
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

    lines = document_header(args, engines, rendered_subtunes, shard) + lines
    lines += [
        "## What to write down",
        "",
        "For each tune, one line: *does it sound like the same piece of "
        "music*, and *what is the first thing that sounds wrong*. The second "
        "is the valuable half — it is the only channel in this project that "
        "reports defects the attack comparison is structurally blind to.",
        "",
    ]
    notes = (outdir / f"LISTENING.part{shard[0]}.md") if shard else (outdir / "LISTENING.md")
    notes.write_text("\n".join(lines), encoding="utf-8")
    print(f"staged {staged} tune(s) -> {outdir}", file=sys.stderr)
    if paired_by_identity:
        print(f"note: {len(paired_by_identity)} tune(s) paired by identity "
              "(sub_orig == sub_ours assumed, no measured correspondence "
              "found) -- see LISTENING.md for which", file=sys.stderr)
    if shard:
        print(f"notes -> {notes.name}; run --merge-notes when every shard is "
              f"done", file=sys.stderr)
    if owned_workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
