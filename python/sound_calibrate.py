#!/usr/bin/env python3
"""Calibrate the rendered-audio measure on cases with a known answer.

    python sound_calibrate.py <sid_dir> -t 60 -o ../docs/SOUND-CALIBRATION.md \
        --json ../build/sound_calibration.json --from-json ../build/fidelity.json

Nothing in `sound.py` decides anything until this has run: the two numbers
every decision downstream uses -- the NOISE FLOOR (how much the score moves
under a shift nobody can hear) and the CLOSENESS FLOOR (how far apart two
renders a listener called the same can read) -- are measured here, never
typed. The doc this writes is a regenerated artefact, not prose.

Five checks:
  1 identity      -- a render against itself is 1.0 / 1.0 / ratio 1.0
  2 shift         -- 48 rasterlines (3 ms) and one frame (20 ms) of delay
                     must move the score under a point; the largest movement
                     seen IS the noise floor
  3 inaudible     -- ACE_II at v0.5.368 against v0.5.369: approved.json's own
                     note calls that change inaudible, so the agreement
                     between those two renders bounds the closeness floor
  4 known-bad     -- builds history shows were wrong (Las Vegas silence and
                     Samantha Fox at 3x, both pre-v0.5.401 -- see the
                     correction below, the plan's own text says pre-402 and
                     that is not where the fix actually landed; Human Race
                     on the wrong clock pre-v0.5.330) must score below
                     their fixed builds by more than the noise floor
  5 approved rank -- the approved tunes should sit in the corpus's upper
                     half on `aud`; if one does not, the doc says which of
                     (metric, approval) to check and picks neither

The v0.5.177 half-speed Last_V8 audition the spec listed under check 4 is a
siddump TRACE trap (calls per frame), not a render: sidplayfp plays a packed
.sid at its own multispeed, so there is no wrong-rate WAV to score. Left out
and said so here.

CORRECTED FROM THE PLAN'S OWN TEXT, TWICE, BOTH CHECKED AGAINST GIT BEFORE
WRITING THIS. First, the plan's KNOWN_BAD table names `Las_Vegas.sid`; the
corpus (and presets.json) file is `Las_Vegas_Video_Poker.sid`. Checked with
`ls` against the corpus directory and grepped in presets.json -- the plan's
spelling does not exist on disk and would have made check 4 silently report
"could not build both versions" for that row rather than a defect in the
metric.

Second, the plan's version pair for Las_Vegas/Samantha_Fox is `0.5.401 ->
0.5.402`; measured (both `presets.json` diffs AND the packed .sng bytes
under a real workdir), THE FIX IS ALREADY IN 0.5.401. `git show
087f192^:presets.json` (087f192 = v0.5.401) reads Las_Vegas's own entry as
`multiplier: 1, bytes: 12444`; `git show 087f192:presets.json` -- v0.5.401
itself -- already reads `multiplier: 4, bytes: 12446`, identical to
`git show 54e22b1:presets.json` (v0.5.402). Samantha_Fox and Spellbound
move on the same commit, the same way (`multiplier` 1->4 and 2->5). And a
real `convert_at` run confirms it operationally, not just from the
presets diff: Las_Vegas's *converted* .sng at 087f192 and 54e22b1 are
byte-identical (sha1 378cb24a9ac44c20d8b21edcd7aa698135e0cd46, both sides,
12444 bytes each before packing). So `0.5.401 -> 0.5.402` is a comparison
of a build against itself for these two files -- it would read `worse_by
0.0` and "seen: false" regardless of what the metric measures, which is
not evidence about the metric. The pair used below is `0.5.400 -> 0.5.401`
(cd1a300 -> 087f192), which is where the multiplier and the byte count
actually move. `0.5.402` remains the right pair for a file the anchoring
fix alone reaches (Spellbound is not in this corpus's approved/known-bad
set) -- 401 already carries the 48-file three-gate change AND the
anchoring change for these two files specifically; nothing in this
project's own commit messages says which of the two sub-changes in 401
was Las_Vegas's, and it does not matter for this check, which only needs
one commit that is bad and one that is good.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F                      # noqa: E402
import sound                              # noqa: E402
from h2g import __version__               # noqa: E402
from h2g.convert import convert           # noqa: E402  -- imported for parity with the plan's declared interface; convert_at below shells out to `python -m h2g` instead so each historical tree runs its OWN converter, not this one

ROOT = Path(__file__).resolve().parent.parent
RASTERLINES_48_S = 48 * 63 / 985248.0     # PAL cycles per line / cycles per second
FRAME_S = 0.02

INAUDIBLE_PAIRS = [("ACE_II.sid", "0.5.368", "0.5.369")]
# **W_A_R IS THE ONLY PAIR HERE THE `aud` COLUMN CAN VALIDATE, ADDED v0.5.469.**
# The three original pairs leave `aud` unexercised: two are EXCLUDED (their good
# build's music ends inside the window, so `loud_ratio` is 0.06-0.07x -- a fact
# about the PAIR, see `comparable`) and Human_Race is seen on `loud` only, with
# `aud` blind to it. A calibration whose only live pair cannot exercise the
# column it calibrates is thin.
#
# v0.5.400 is "the silent park stops pushing W_A_R one pattern past
# Goattracker's limit" -- a PATTERN COUNT fix (209 -> 208), NOT a multiplier
# change, which is why both sides pack at the same -S and render over the same
# span where Las_Vegas and Samantha_Fox do not. Measured at v0.5.469, 60 s,
# through `convert_at` and `sound.compare_sids`:
#
#     bad  (0.5.399)  aud 0.6370  loud 0.7915  loud_ratio 0.5261
#     good (0.5.400)  aud 0.8053  loud 0.8790  loud_ratio 1.5539
#     comparable() -> None;  worse_by aud +0.1683, loud +0.0876
#
# Both ratios sit inside LOUD_RATIO_BAND, though the bad build's 0.526 is close
# to the 0.5 floor -- worth knowing if that band is ever narrowed.
#
# **W_A_R_Preview ON THE SAME COMMIT PAIR IS NOT USABLE and was tested first**:
# it renders byte-identically on both sides (worse_by 0.0000 on aud AND loud),
# so v0.5.400 did not reach it. That is the "a build compared against itself"
# case this module's own header records for 0.5.401 -> 0.5.402; a pair has to
# MOVE before it can validate anything.
#
# ===========================================================================
# CHOOSING THE NEXT PAIR: A FIX IS COMPARABLE WHEN IT IS STRUCTURAL, AND NOT
# WHEN IT CHANGES THE MULTIPLIER.
#
# The rule is stated HERE, beside the table, because this is where the next
# candidate gets picked -- the evidence for it is real but it was scattered
# across three places that a person adding a row does not necessarily read:
# this module's header (grep `multiplier: 1, bytes: 12444`), the W_A_R note
# just above, and `comparable`'s own docstring (grep `quartering the 60 s
# render`). All three figures below are HISTORICAL at the versions named --
# build/sound_calibration.json is currently stamped v0.5.474 at 60 s renders,
# so re-measure before quoting any of them as live.
#
# THREE OUTCOMES, and a candidate has to be checked against all three:
#
#   COMPARABLE -- the fix changes STRUCTURE and both sides still pack at the
#   same -S, so the two renders cover the same span. W_A_R 0.5.399 -> 0.5.400
#   is a pattern-count fix (209 -> 208) and validates the metric:
#   aud 0.6370 -> 0.8053, loud 0.7915 -> 0.8790 (v0.5.469, 60 s).
#
#   INCOMPARABLE -- the fix changes the MULTIPLIER, so the good build repacks
#   at a different -S and the two sides no longer span the same music.
#   Las_Vegas and Samantha_Fox 0.5.400 -> 0.5.401 move multiplier 1->4 and
#   2->5; their good builds render loud_ratio 0.074 and 0.063 because the
#   music ends around 30 s of a 60 s window while the original plays on. The
#   metric is right and the PAIR is unusable. They stay in the table and are
#   reported rather than deleted -- the user's decision, recorded in
#   .claude/tasks/decisions.jsonl under
#   `the-two-incomparable-known-bad-pairs-need-retiring-or-replacing`.
#
#   INERT -- the commit does not reach the file at all, so both sides render
#   byte-identically (W_A_R_Preview on 0.5.399 -> 0.5.400, worse_by 0.0000 on
#   both columns). A pair that cannot move cannot validate anything, and this
#   is the cheapest of the three to test first.
#
# So the check to run on a candidate, in order: does the commit reach the file
# (INERT?), does the multiplier move across it (INCOMPARABLE?), and only then
# is the pair worth rendering. `git show <sha>:presets.json` answers the
# second without rendering anything, which is why it is the second question
# and not the last.
# ===========================================================================
KNOWN_BAD = [("Las_Vegas_Video_Poker.sid", "0.5.400", "0.5.401"),
             ("Samantha_Fox_Strip_Poker.sid", "0.5.400", "0.5.401"),
             ("Human_Race.sid", "0.5.329", "0.5.330"),
             ("W_A_R.sid", "0.5.399", "0.5.400")]


# ---- pure reductions ------------------------------------------------------
def shift_movement(samples: np.ndarray, rate: int, shifts_s: list[float]) -> float:
    """Largest movement of aud/loud when one side is delayed by each shift."""
    a = sound.features(samples, rate)
    worst = 0.0
    for s in shifts_s:
        d = np.concatenate([np.zeros(int(round(s * rate)), dtype=np.float32), samples])
        b = sound.features(d, rate)
        got = sound.compare_features(a, b, sound.align(a, b))
        worst = max(worst, abs(1.0 - (got["aud"] or 0.0)), abs(1.0 - (got["loud"] or 0.0)))
    return worst


def noise_floor(movements: list[float]) -> float:
    return max(movements) if movements else 0.0


def closeness_floor(pairs: list[dict]) -> float:
    """The least agreement between two renders a human called the same."""
    return min(min(p["aud"], p["loud"]) for p in pairs)


def worse_by(bad: dict, good: dict) -> float:
    return (good.get("aud") or 0.0) - (bad.get("aud") or 0.0)


def worse_by_loud(bad: dict, good: dict) -> float:
    """The same margin on `loud`, because `aud` alone missed a real regression.

    Human_Race 0.5.329 -> 0.5.330 reads `worse_by(aud)` **-0.0052** -- the
    version known to be worse scoring better -- while the SAME comparison reads
    `loud` **+0.0136**, twice the noise floor and the right sign. Both builds
    are healthy there (`loud_ratio` 1.037 and 1.053), so this is not a broken
    pair: it is one column blind and its neighbour not. A check that exists to
    catch regressions should fail only when NEITHER column sees one.
    """
    return (good.get("loud") or 0.0) - (bad.get("loud") or 0.0)


# A build whose loudness is nowhere near the original's is not a build this
# check can compare -- see `comparable` below.
LOUD_RATIO_BAND = (0.5, 2.0)


def comparable(bad: dict, good: dict) -> str | None:
    """None if the pair can be compared, else why it cannot.

    **Measured, and it is why two of three pairs "failed".** Samantha_Fox and
    Las_Vegas's *good* builds (v0.5.401, packed at that tree's -S4) render with
    `loud_ratio` **0.063** and **0.074** -- and quartering the 60 s render shows
    why: RMS `[0.201, 0.101, 0.0023, 0.0023]` against the original's steady
    `[0.150, 0.163, 0.169, 0.169]`. The build's music ENDS around 30 s while
    the original plays on, so half the window scores our silence against real
    music. `aud` and `loud` both call that worse, correctly, and the check then
    reported "the fix is worse than the bug".

    That is a statement about the PAIR, not about the metric, and the two must
    not be conflated: a blind spot is something to fix in `aud`, an
    incomparable build is something to fix in `KNOWN_BAD` or in how the build
    is made. Reporting the second as the first is what made this check read as
    a failure of the sound columns for as long as it has.
    """
    for label, got in (("bad", bad), ("good", good)):
        r = got.get("loud_ratio")
        if r is None:
            return f"{label} build has no loud_ratio"
        if not LOUD_RATIO_BAND[0] <= r <= LOUD_RATIO_BAND[1]:
            return (f"{label} build's loudness is {r:.3f}x the original's, "
                    f"outside {LOUD_RATIO_BAND} -- not a comparable render")
    return None


def rank_in_corpus(rows: list[dict], names: list[str]) -> dict[str, tuple[int, int]]:
    scored = sorted(((r["aud"], r["file"][:-4]) for r in rows
                     if r.get("aud") is not None), reverse=True)
    order = [n for _, n in scored]
    return {n: (order.index(n) + 1, len(order)) for n in names if n in order}


# ---- history --------------------------------------------------------------
def resolve_version_sha(version: str) -> str:
    r = subprocess.run(["git", "log", "--format=%h", f"--grep=^v{version}:", "-n1"],
                       cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip()


def convert_at(version: str, sid: Path, workdir: Path, gt2reloc: str,
               multiplier: int) -> Path | None:
    """Convert `sid` with the tree AS IT WAS at `version`, pack with today's
    gt2reloc. The archive is the export the byte-hash recipe uses.

    RETRACTED FROM THE PLAN'S SIGNATURE: `multiplier` is accepted for call-
    site compatibility but IGNORED for packing -- the -S value is read from
    the historical TREE's own `presets.json`, never from the caller's
    (current-HEAD) one. Measured why this matters: Las_Vegas_Video_Poker's
    conversion is byte-identical between v0.5.400 and v0.5.401 (sha1
    378cb24a... both sides, verified in a real workdir) -- the ENTIRE
    v0.5.401 fix for that file is a change to the RECOMMENDED MULTIPLIER
    (presets.json: 1 -> 4), not to the .sng. If both the "bad" and "good"
    packs use today's already-fixed multiplier (4), the two `.sid`s built
    from those byte-identical `.sng`s are ALSO byte-identical -- check 4
    would read `worse_by 0.0` for every version pair, forever, regardless
    of which commits are named, and that reads as "the metric cannot see
    this" when the real cause is that the harness packed the bad build
    correctly. Confirmed by constructing exactly that case first (using
    `F._preset_multiplier(doc, name)` with `doc` = current presets.json, as
    the plan's own `main()` does) and observing `bad == good` to 16
    significant figures on both Las_Vegas and Samantha_Fox before this fix.
    """
    sha = resolve_version_sha(version)
    if not sha:
        return None
    tree = workdir / sha
    if not tree.exists():
        tree.mkdir(parents=True)
        blob = subprocess.run(["git", "archive", sha], cwd=ROOT,
                              capture_output=True, check=True).stdout
        tarfile.open(fileobj=io.BytesIO(blob)).extractall(tree)
    tree_presets = tree / "presets.json"
    out = workdir / f"{sid.stem}.{sha}.sng"
    r = subprocess.run([sys.executable, "-m", "h2g", str(sid), "-o", str(out), "-q",
                        "--presets", str(tree_presets)],
                       cwd=tree / "python", capture_output=True, text=True)
    if r.returncode or not out.exists():
        return None
    blob, _ = F.legalise_restarts(out.read_bytes())
    try:
        hist_doc = json.loads(tree_presets.read_text(encoding="utf-8"))
        hist_mult = F._preset_multiplier(hist_doc, sid.name)
    except (OSError, json.JSONDecodeError):
        hist_mult = multiplier
    return F.pack_sid(blob, workdir / sha, gt2reloc, hist_mult)


# ---- driver ---------------------------------------------------------------
def known_bad_passed(bad: list[dict]) -> bool:
    """Does the KNOWN_BAD suite validate the metric?

    An EXCLUDED pair is REPORTED, NOT COUNTED -- decided by the user and
    recorded in `.claude/tasks/decisions.jsonl`. The pair stays in KNOWN_BAD,
    stays rendered, and keeps its reason in the table; what it no longer does is
    hold the whole suite at FAIL.

    This used to be `all(b["seen"] for b in bad)`, with a comment arguing the
    opposite: "An EXCLUDED pair is not a passing pair ... It reads FAIL until
    KNOWN_BAD names pairs that can be built comparably". That made the criterion
    UNSATISFIABLE for as long as Las_Vegas and Samantha_Fox remain, because
    their v0.5.401 fix is a MULTIPLIER change -- the good build repacks at a
    different -S and its loudness lands at 0.074x and 0.063x of the original,
    which `comparable()` refuses as a RENDER rather than as a result. That is a
    property of the pair, not a metric blind spot, so scoring it reported a
    build problem as a coverage failure. Deleting the two pairs would make this
    green by shrinking the suite, which is gaming an all() rather than measuring
    anything -- so they stay, excluded and visible.

    THE `any(...)` GUARD IS NOT OPTIONAL, and it is the whole subtlety.
    `all()` over an empty sequence is True, so the filter ALONE would report
    PASS the moment every pair is excluded -- validating nothing while reading
    identically to a real pass. At least one COMPARABLE pair must exist and be
    seen. Same shape as a census reporting "0 disagreements" over rows it never
    read.
    """
    comparable_rows = [b for b in bad if not b.get("incomparable")]
    return bool(comparable_rows) and all(b.get("seen") for b in comparable_rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sound_calibrate")
    p.add_argument("sid_dir")
    p.add_argument("-t", "--seconds", type=int, default=60)
    p.add_argument("-o", "--output", default=str(ROOT / "docs" / "SOUND-CALIBRATION.md"))
    p.add_argument("--json", default=str(ROOT / "build" / "sound_calibration.json"))
    p.add_argument("--from-json", default=str(ROOT / "build" / "fidelity.json"),
                   help="a --sound run of the corpus, for check 5")
    p.add_argument("--presets", default=str(ROOT / "presets.json"))
    p.add_argument("--gt2reloc", default=F.GT2RELOC)
    p.add_argument("--workdir", default=None)
    args = p.parse_args(argv)

    sid_dir = Path(args.sid_dir)
    doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))
    workdir, _ = F.make_workdir(args.workdir)
    workdir = Path(workdir)
    checks: dict = {}
    approved = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))["tunes"]
    names = [n for n in approved if (sid_dir / f"{n}.sid").exists()]

    # 1 + 2: identity and shift, over every approved tune's original.
    idents, moves = {}, []
    for n in names:
        sid = sid_dir / f"{n}.sid"
        sub = F.resolve_subtune(sid, "auto")
        wav = sound.render_cached(sid, args.seconds, sub, "orig")
        if wav is None:
            continue
        x, rate = sound.read_wav_mono(wav)
        f = sound.features(x, rate)
        idents[n] = sound.compare_features(f, f, 0)
        moves.append(shift_movement(x, rate, [RASTERLINES_48_S, FRAME_S]))
    checks["identity"] = idents
    checks["shift"] = {"movements": moves, "noise_floor": noise_floor(moves)}

    # 3: the pair a listener called inaudible.
    pairs = []
    for name, v_old, v_new in INAUDIBLE_PAIRS:
        sid = sid_dir / name
        mult = F._preset_multiplier(doc, name)
        a = convert_at(v_old, sid, workdir, args.gt2reloc, mult)
        b = convert_at(v_new, sid, workdir, args.gt2reloc, mult)
        if a and b:
            sub = F.resolve_subtune(sid, "auto")
            got = sound.compare_sids(a, b, args.seconds, sub, sub)
            got.update(file=name, versions=[v_old, v_new])
            pairs.append(got)
    checks["inaudible"] = pairs
    closeness = closeness_floor(pairs) if pairs else None

    # 4: known-bad builds against their fixes.
    bad = []
    for name, v_bad, v_good in KNOWN_BAD:
        sid = sid_dir / name
        mult = F._preset_multiplier(doc, name)
        sub = F.resolve_subtune(sid, "auto")
        pb = convert_at(v_bad, sid, workdir, args.gt2reloc, mult)
        pg = convert_at(v_good, sid, workdir, args.gt2reloc, mult)
        if not (pb and pg):
            bad.append({"file": name, "error": "could not build both versions"})
            continue
        gb = sound.compare_sids(sid, pb, args.seconds, sub, sub)
        gg = sound.compare_sids(sid, pg, args.seconds, sub, sub)
        floor = checks["shift"]["noise_floor"]
        why = comparable(gb, gg)
        row = {"file": name, "versions": [v_bad, v_good],
               "bad": gb.get("aud"), "good": gg.get("aud"),
               "worse_by": worse_by(gb, gg),
               "worse_by_loud": worse_by_loud(gb, gg),
               "loud_ratio": [gb.get("loud_ratio"), gg.get("loud_ratio")],
               "incomparable": why}
        # Either column seeing it is enough; neither is the failure. And an
        # incomparable pair is NEITHER seen nor unseen -- it is excluded, with
        # its reason recorded, because scoring it would report a build problem
        # as a metric blind spot.
        row["seen"] = (why is None
                       and (row["worse_by"] > floor
                            or row["worse_by_loud"] > floor))
        bad.append(row)
    checks["known_bad"] = bad

    # 5: where the approved tunes sit.
    rows = []
    if Path(args.from_json).exists():
        rows = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
    ranks = rank_in_corpus(rows, names)
    checks["approved_rank"] = {n: {"rank": r, "of": t, "upper_half": r <= t / 2}
                               for n, (r, t) in ranks.items()}

    passed = (all(abs(1 - v["aud"]) < 1e-6 for v in idents.values())
              and checks["shift"]["noise_floor"] < 0.01
              and closeness is not None
              and known_bad_passed(bad))
    out = {"version": __version__, "head": F.git_label(ROOT), "seconds": args.seconds,
           "noise_floor": checks["shift"]["noise_floor"],
           "closeness_floor": closeness, "checks": checks, "pass": passed}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    Path(args.output).write_text(render_doc(out), encoding="utf-8")
    print(f"wrote {args.output} and {args.json}: pass={passed}", file=sys.stderr)
    return 0 if passed else 1


def render_doc(out: dict) -> str:
    c = out["checks"]
    lines = ["# Sound calibration", "",
             f"Generated by `python/sound_calibrate.py` (h2g {out['version']}, "
             f"{out['head']}), {out['seconds']} s renders. **PASS**" if out["pass"]
             else f"Generated by `python/sound_calibrate.py` (h2g {out['version']}, "
                  f"{out['head']}), {out['seconds']} s renders. **FAIL** -- nothing "
                  "downstream may inherit an approval on these numbers.",
             "",
             "The two numbers every decision uses, measured here and typed nowhere:", "",
             f"* **noise floor** = `{out['noise_floor']:.4f}` -- the largest movement of "
             "`aud`/`loud` under a 3 ms (48 rasterline) and a 20 ms (one frame) delay "
             "of one side. A change smaller than this is not a change.",
             f"* **closeness floor** = `{out['closeness_floor']}` -- the least agreement "
             "between two renders a listener called the same (check 3). A build at "
             "least this close to an approved render sounds like what was approved.",
             "", "## 1. Identity", "", "| tune | aud | loud | ratio |", "|---|---:|---:|---:|"]
    for n, v in c["identity"].items():
        lines.append(f"| {n} | {v['aud']:.4f} | {v['loud']:.4f} | {v['loud_ratio']:.3f} |")
    lines += ["", "## 2. Inaudible shift", "",
              f"Movements per tune: {', '.join(f'{m:.4f}' for m in c['shift']['movements'])}",
              "", "## 3. A change a listener called inaudible", "",
              "| file | versions | aud | loud |", "|---|---|---:|---:|"]
    for pr in c["inaudible"]:
        lines.append(f"| {pr['file']} | {' -> '.join(pr['versions'])} | "
                     f"{pr['aud']:.4f} | {pr['loud']:.4f} |")
    lines += ["", "## 4. Known-bad builds", "",
              "| file | bad -> good | aud bad | aud good | worse by | seen? |",
              "|---|---|---:|---:|---:|---|"]
    for b in c["known_bad"]:
        if "error" in b:
            lines.append(f"| {b['file']} | - | - | - | - | {b['error']} |")
        else:
            if b.get("incomparable"):
                verdict = f"EXCLUDED -- {b['incomparable']}"
            elif b["seen"]:
                verdict = ("yes" if b["worse_by"] > 0 else
                           f"yes, on `loud` ({b['worse_by_loud']:+.4f}); `aud` "
                           f"does not see it")
            else:
                verdict = "NO -- a blind spot; name it in the Dimension"
            lines.append(f"| {b['file']} | {' -> '.join(b['versions'])} | {b['bad']:.3f} | "
                         f"{b['good']:.3f} | {b['worse_by']:+.3f} | {verdict} |")
    lines += ["", "## 5. Where the approved tunes sit", "",
              "| tune | rank | of | upper half? |", "|---|---:|---:|---|"]
    for n, v in c["approved_rank"].items():
        lines.append(f"| {n} | {v['rank']} | {v['of']} | "
                     f"{'yes' if v['upper_half'] else 'no -- check the metric on this file with --sound and the approval note; this doc picks neither'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
