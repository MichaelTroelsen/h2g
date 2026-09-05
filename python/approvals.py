#!/usr/bin/env python3
"""Does the build shipping NOW still carry a human's approval?

    python approvals.py <sid_dir> -t 60          # writes build/approvals.json

`approved.json` is hand-written, sha-pinned, and no tool writes it. This
module reads it and asks, for each approved tune, whether the current
conversion INHERITS the verdict -- and writes the answer to
build/approvals.json, which abpage.py shows and presets.py consults.

A build inherits when all three hold, on the same window and alignment:

  1. NO FARTHER FROM THE ORIGINAL: its `aud`/`loud` against the original are
     at least the approved render's, within the NOISE FLOOR the calibration
     measured (a change smaller than that is not a change).
  2. CLOSE TO WHAT WAS APPROVED: its `aud`/`loud` against the APPROVED RENDER
     are at least the CLOSENESS FLOOR -- the least agreement between two
     renders a listener called the same. It must sound like the thing the
     person said yes to, not merely score as well.
  3. NOTHING STRUCTURAL REGRESSED that the listener could have heard: the
     attack count no farther from the original's than the approved build's,
     `melody`/`sequence` within FIDELITY_MARGIN, `len` inside +-5 s. These
     are `presets.fidelity_better`'s guards, reused.

Two rules that are the point rather than details:

* Inheritance NEVER CREATES an approval. A tune nobody signed off is not
  assessed. The metric bounds how much a change moved; it is not evidence
  the result is right.
* Criterion 2 is always against the HUMAN-APPROVED render, never the last
  inherited build, so small steps cannot walk away from the verdict.

Without build/sound_calibration.json the status is `uncalibrated` and nothing
inherits: the thresholds are measured, never typed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F                       # noqa: E402
import sound                               # noqa: E402
from h2g import __version__                # noqa: E402
from h2g.convert import convert            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIDELITY_MARGIN = 0.02      # presets.FIDELITY_MARGIN; imported lazily below to avoid a cycle
LENGTH_TOLERANCE = 5.0      # fidelity.LENGTH_TOLERANCE


def approved_tunes() -> dict:
    path = ROOT / "approved.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {n: a for n, a in (doc.get("tunes") or {}).items()
            if a.get("approved") and a.get("sng_sha256")}


def load_calibration() -> dict | None:
    path = ROOT / "build" / "sound_calibration.json"
    if not path.exists():
        return None
    cal = json.loads(path.read_text(encoding="utf-8"))
    if not cal.get("pass") or cal.get("closeness_floor") is None:
        return None
    return cal


def load_approvals_json() -> dict:
    path = ROOT / "build" / "approvals.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("tunes") or {}
    except (OSError, ValueError):
        return {}


# ---- the decision ---------------------------------------------------------
def inherit(approved_vs_orig: dict, current_vs_orig: dict,
            current_vs_approved: dict, structure: dict, cal: dict | None,
            margin: float = FIDELITY_MARGIN, same_sha: bool = False) -> dict:
    evidence = {"aud_vs_orig": [approved_vs_orig.get("aud"), current_vs_orig.get("aud")],
                "loud_vs_orig": [approved_vs_orig.get("loud"), current_vs_orig.get("loud")],
                "aud_vs_approved": current_vs_approved.get("aud"),
                "loud_vs_approved": current_vs_approved.get("loud"),
                "attacks": [structure.get("approved_attacks"), structure.get("attacks"),
                            structure.get("orig_attacks")],
                "melody": [structure.get("approved_melody"), structure.get("melody")],
                "sequence": [structure.get("approved_sequence"), structure.get("sequence")],
                "length_delta": structure.get("length_delta")}
    if same_sha:
        return {"status": "exact", "failed": [], "listener_should_check": None,
                "evidence": evidence}
    if cal is None:
        return {"status": "uncalibrated", "failed": [], "listener_should_check": None,
                "evidence": evidence}
    floor, close = float(cal["noise_floor"]), float(cal["closeness_floor"])
    failed, margins = [], {}

    def need(name, value, bound):
        """A criterion fails when `value < bound`; its margin is how near it came."""
        if value is None:
            failed.append(name)
            return
        margins[name] = value - bound
        if value < bound:
            failed.append(name)

    # 1. No farther from the original, within the noise floor.
    for k in ("aud", "loud"):
        need(f"{k}_vs_orig", current_vs_orig.get(k),
             (approved_vs_orig.get(k) or 0.0) - floor)
    # 2. Close to what was approved.
    for k in ("aud", "loud"):
        need(f"{k}_vs_approved", current_vs_approved.get(k), close)
    # 3. Nothing structural regressed. Attacks: two-sided against the
    # original's count, as presets.fidelity_better reads it.
    a, ap, o = structure.get("attacks"), structure.get("approved_attacks"), structure.get("orig_attacks")
    if a is not None and ap is not None and a < ap:
        if o is None or abs(a - o) >= abs(ap - o):
            failed.append("attacks")
    for k in ("melody", "sequence"):
        cur, was = structure.get(k), structure.get(f"approved_{k}")
        if cur is not None and was is not None and cur < was - margin:
            failed.append(k)
    ld = structure.get("length_delta")
    if ld is not None and abs(ld) > LENGTH_TOLERANCE:
        failed.append("length")

    status = "stale" if failed else "inherited"
    nearest = min(margins, key=margins.get) if margins else None
    return {"status": status, "failed": failed,
            "listener_should_check": (failed[0] if failed else nearest),
            "evidence": evidence}


def record(stem: str, approved_sha: str, current_sha: str, verdict: dict,
           previous: dict | None, version: str) -> dict:
    """One build/approvals.json entry. `since` and `builds_inherited` persist
    across runs: the count moves only when the sha does."""
    inherited = verdict["status"] == "inherited"
    if previous and previous.get("status") == "inherited" and inherited:
        since = previous.get("since", version)
        n = previous.get("builds_inherited", 0) + (
            1 if previous.get("current_sha") != current_sha else 0)
    else:
        since, n = version, (1 if inherited else 0)
    return {"approved_sha": approved_sha, "current_sha": current_sha,
            "status": verdict["status"], "since": since, "builds_inherited": n,
            "evidence": verdict["evidence"], "failed": verdict["failed"],
            "listener_should_check": verdict["listener_should_check"]}


# ---- plumbing ------------------------------------------------------------
def _structure_of(orig_trace, trace, seconds: int) -> dict:
    got = F.compare(orig_trace, trace)
    return {"attacks": sum(len(v.attacks) for v in trace),
            "orig_attacks": sum(len(v.attacks) for v in orig_trace),
            "melody": got["melody"], "sequence": got["sequence"],
            "length_delta": F.length_compare(orig_trace, trace, seconds).get("length_delta")}


def assess(stem: str, sid: Path, approved_sha: str, doc: dict, seconds: int,
           cal: dict | None, gt2reloc: str, siddump: str, workdir: Path,
           current_sng: bytes | None = None,
           approved_sng: Path | None = None) -> tuple[dict, str]:
    """(verdict, current sha). `approved_sng` is the .sng the listener heard;
    `listen.py` keeps it as build/listen/<stem>.h2g.sng when its sha matches."""
    name = f"{stem}.sid"
    opts = F._preset_opts(doc, name)
    mult = F._preset_multiplier(doc, name)
    cur = current_sng if current_sng is not None else convert(str(sid), log=lambda m: None, **opts)
    cur_sha = hashlib.sha256(cur).hexdigest()
    same = cur_sha == approved_sha
    if approved_sng is None:
        cand = ROOT / "build" / "listen" / f"{stem}.h2g.sng"
        if cand.exists() and hashlib.sha256(cand.read_bytes()).hexdigest() == approved_sha:
            approved_sng = cand
    if same:
        return inherit({}, {}, {}, {}, cal, same_sha=True), cur_sha
    if approved_sng is None:
        v = inherit({}, {}, {}, {}, None)
        v["failed"] = ["approved .sng not on disk -- re-stage it with listen.py"]
        return v, cur_sha
    sub = F.resolve_subtune(sid, "auto")
    orig_trace = F.run_siddump(sid, seconds, sub, siddump)

    def packed_of(blob: bytes, tag: str):
        b, _ = F.legalise_restarts(blob)
        # `pack_sid` writes `workdir / "a.sng"` and does NOT create the
        # directory (fidelity.py:752), so the caller must. Without this the
        # first real assessment dies with FileNotFoundError on `<tag>/a.sng`
        # -- which no test caught, because they inject a fake `convert_at`
        # and never reach this path.
        (workdir / tag).mkdir(parents=True, exist_ok=True)
        return F.pack_sid(b, workdir / tag, gt2reloc, mult)
    p_cur = packed_of(cur, "cur")
    p_app = packed_of(approved_sng.read_bytes(), "app")
    if p_cur is None or p_app is None:
        v = inherit({}, {}, {}, {}, None)
        v["failed"] = ["gt2reloc refused a side"]
        return v, cur_sha
    t_cur = F.run_siddump(p_cur, seconds, sub, siddump, calls=mult)
    t_app = F.run_siddump(p_app, seconds, sub, siddump, calls=mult)
    s_cur, s_app = _structure_of(orig_trace, t_cur, seconds), _structure_of(orig_trace, t_app, seconds)
    structure = dict(s_cur, approved_attacks=s_app["attacks"],
                     approved_melody=s_app["melody"], approved_sequence=s_app["sequence"])
    lag = 0.02 * F.startup_lag(orig_trace, t_cur)[0]
    app_vs_orig = sound.compare_sids(sid, p_app, seconds, sub, sub, prior_s=lag)
    cur_vs_orig = sound.compare_sids(sid, p_cur, seconds, sub, sub, prior_s=lag)
    cur_vs_app = sound.compare_sids(p_app, p_cur, seconds, sub, sub)
    return inherit(app_vs_orig, cur_vs_orig, cur_vs_app, structure, cal), cur_sha


def recover_approved_sng(stem: str, sid: Path, version: str, approved_sha: str,
                         workdir: Path, gt2reloc: str, multiplier: int,
                         convert_at=None) -> bytes | None:
    """The approved `.sng` rebuilt from history, or None.

    **THE PLAN'S STEP 5 PRESCRIBES THIS WRONGLY AND THE PRESCRIPTION IS A
    SILENT NO-OP.** It says `sound_calibrate.convert_at(...)` "reproduces it,
    and its sha must equal `sng_sha256`". `convert_at` RETURNS
    `F.pack_sid(...)` -- a packed `.sid` -- whose sha256 can never equal an
    `sng_sha256`, so a literal implementation would recover nothing, always,
    and report every approval unrecoverable. Read from the source rather than
    from the step: `convert_at` writes the intermediate `.sng` to
    `workdir / f"{stem}.{sha}.sng"` on its way, and THAT is the artefact the
    listener heard.

    So this calls `convert_at` for its side effect, then reads the `.sng` it
    left. A None return means one of three things and they are not the same:
    the version does not resolve to a commit, the historical tree refused the
    file, or the bytes came back with a different sha -- in which case
    `approved.json`'s `version` field is PROVENANCE ONLY and the build cannot
    be recovered, which is the outcome Step 5 says to record as `stale`.
    """
    if convert_at is None:                      # injected by the tests
        import sound_calibrate as SC            # noqa: PLC0415 -- avoids a cycle
        convert_at, resolve = SC.convert_at, SC.resolve_version_sha
    else:
        import sound_calibrate as SC            # noqa: PLC0415
        resolve = SC.resolve_version_sha
    sha = resolve(version)
    if not sha:
        return None
    if convert_at(version, sid, workdir, gt2reloc, multiplier) is None:
        return None
    sng = workdir / f"{sid.stem}.{sha}.sng"
    if not sng.exists():
        return None
    blob = sng.read_bytes()
    return blob if hashlib.sha256(blob).hexdigest() == approved_sha else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="approvals")
    p.add_argument("sid_dir")
    p.add_argument("-t", "--seconds", type=int, default=60)
    p.add_argument("--recover", action="store_true",
                   help="rebuild any approved .sng missing from build/listen/ "
                        "from the version approved.json names, and keep it when "
                        "the sha matches")
    p.add_argument("--presets", default=str(ROOT / "presets.json"))
    p.add_argument("-o", "--output", default=str(ROOT / "build" / "approvals.json"))
    p.add_argument("--gt2reloc", default=F.GT2RELOC)
    p.add_argument("--siddump", default=F.SIDDUMP)
    p.add_argument("--workdir", default=None)
    args = p.parse_args(argv)
    doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))
    cal = load_calibration()
    workdir, _ = F.make_workdir(args.workdir)
    previous = load_approvals_json()
    tunes = {}
    for stem, a in approved_tunes().items():
        sid = Path(args.sid_dir) / f"{stem}.sid"
        if not sid.exists():
            continue
        approved_sng = None
        if args.recover:
            kept = ROOT / "build" / "listen" / f"{stem}.h2g.sng"
            have = (kept.exists()
                    and hashlib.sha256(kept.read_bytes()).hexdigest() == a["sng_sha256"])
            if not have and a.get("version"):
                blob = recover_approved_sng(
                    stem, sid, a["version"], a["sng_sha256"], Path(workdir),
                    args.gt2reloc, F._preset_multiplier(doc, f"{stem}.sid"))
                if blob is not None:
                    kept.parent.mkdir(parents=True, exist_ok=True)
                    kept.write_bytes(blob)
                    approved_sng = kept
                    print(f"  {stem:32} recovered from {a['version']}", file=sys.stderr)
                else:
                    print(f"  {stem:32} NOT recoverable at {a['version']} "
                          f"-- version is provenance only", file=sys.stderr)
        verdict, cur_sha = assess(stem, sid, a["sng_sha256"], doc, args.seconds, cal,
                                  args.gt2reloc, args.siddump, Path(workdir),
                                  approved_sng=approved_sng)
        tunes[stem] = record(stem, a["sng_sha256"], cur_sha, verdict,
                             previous.get(stem), __version__)
        print(f"  {stem:32} {tunes[stem]['status']}"
              + (f"  ({', '.join(verdict['failed'])})" if verdict["failed"] else ""),
              file=sys.stderr)
    out = {"generator": f"h2g {__version__} approvals.py", "head": F.git_label(ROOT),
           "seconds": args.seconds, "calibrated": cal is not None, "tunes": tunes}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(tunes)} tune(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
