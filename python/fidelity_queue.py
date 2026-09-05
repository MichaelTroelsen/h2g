#!/usr/bin/env python3
"""The report's misses as a ranked queue of CAUSES.

    python fidelity_queue.py --from-json ../build/fidelity.json \
        -o ../docs/QUEUE.md --json ../build/queue.json

`/whattask` reads docs/QUEUE.md as a source beside todo.md. Nothing here
writes the plan.

An entry is a cause, not a file: the onset census turned "18% disagree" into
`$01 x19, $04 x11, $80 x6` and the `$0A` bucket was a mechanism within the
session -- that is the shape reproduced here. Six sources; THE TIER IS THE
RANK, chosen for what each means rather than fitted:

  1 stale approvals   -- a human verdict the tool could not carry forward;
                         nothing else can close these            [user]
  2 length failures   -- `len` outside +-5 s, or unbounded         [main]
  3 search refusals   -- a measured gain refused by a criterion    [main]
  4 voice deficits    -- one voice's `aud` well below the others   [main]
  5 census buckets    -- onset/hold kinds by cause, corpus-wide    [subagent] + [main]
  6 column outliers   -- a file far below the corpus median        lowest: a lead

Within a tier: files reached first (a shared cause is one fix), then gap.
Never a weighted scalar across tiers.

Dedupe is by ANNOTATION: an entry a plan task already names is marked
`already_tracked`, one a done run record already refuted `already_refuted`.
Neither drops it -- the reader decides -- so a regeneration cannot re-propose
a refuted cause without saying it was refuted.

Note on tier 4 (`voice_deficits`): it reads `aud_voices`, a per-voice `aud`
reading nothing in this build's `fidelity.py` writes yet (that is Step 3b of
this task's source document, which edits `fidelity.py`/`test_fidelity.py` --
out of this module's grant). So `voice_deficits` is implemented against the
documented shape and will simply find no rows to report until a future run
starts writing `aud_voices` into `build/fidelity.json`.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fidelity as F                       # noqa: E402
from h2g import __version__                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAG = {1: "[user]", 2: "[main]", 3: "[main]", 4: "[main]", 6: "[main]"}
MAD_MULTIPLE = 3.0      # a convention (robust outlier rule), stated rather than fitted

# The report's own column vocabulary (`gate`, `pitch`, `onset`, ...), longest
# first so a search for a substring match cannot be pre-empted by a shorter
# one that happens to occur inside it.
_DIM_COLUMNS = sorted({d.column for d in F.DIMENSIONS}, key=len, reverse=True)


def _cause_keyword(cause: str) -> str:
    """The dimension a cause is about, read from the report's own column
    names rather than assumed to be `cause`'s first word.

    `column_outliers`' and `census_buckets`' causes both open on the column
    name (`"gate far below the corpus"`, `"onset phase"`), so the first word
    usually IS it -- but a cause is free-text prose (`"runs long past the
    original's ending"`, `"column pitch outlier"`), and a fixed word position
    is not a property of every tier's phrasing. Searching the whole string
    for a name this project already tracks is what generalises; the first
    word is kept only as a fallback for a cause that names no dimension at
    all (stale approvals, length and refusal causes), so those tiers keep
    matching the way they always did.
    """
    low = cause.lower()
    for col in _DIM_COLUMNS:
        if col in low:
            return col
    return cause.split()[0].lower()


def slug(*parts) -> str:
    s = "-".join(str(p) for p in parts).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _stem(name: str) -> str:
    return name[:-4] if name.endswith(".sid") else name


# ---- tiers --------------------------------------------------------------
def stale_approvals(approvals: dict) -> list[dict]:
    out = []
    for stem, rec in approvals.items():
        if rec.get("status") != "stale":
            continue
        check = rec.get("listener_should_check") or (rec.get("failed") or ["?"])[0]
        out.append({"id": slug("listen", stem), "tier": 1, "source": "build/approvals.json",
                    "cause": f"approval stale: {', '.join(rec.get('failed') or [])}",
                    "files": [stem], "tag": TAG[1],
                    "evidence": {k: rec.get("evidence", {}).get(k) for k in rec.get("failed") or []},
                    "verify": (f"Re-stage {stem} with listen.py --voices and listen for "
                               f"`{check}`; then either re-approve (update approved.json's "
                               "sng_sha256 by hand) or record the defect the ear found.")})
    return out


def length_failures(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        d, b = r.get("length_delta"), r.get("length_bounded")
        if d is None or (abs(d) <= F.LENGTH_TOLERANCE and not b):
            continue
        stem = _stem(r["file"])
        out.append({"id": slug("length", stem), "tier": 2, "source": "fidelity.json length_delta",
                    "cause": "runs long past the original's ending" if d > 0 else "ends early",
                    "files": [stem], "tag": TAG[2],
                    "evidence": {"length_delta": d, "length_bounded": bool(b)},
                    "verify": (f"{stem}'s `len` inside +-{F.LENGTH_TOLERANCE:.0f} s with "
                               "`length_bounded` false, regenerated in docs/FIDELITY.md.")})
    return out


def refusal_entries(refusals: list[dict]) -> list[dict]:
    out = []
    for x in refusals:
        stem = _stem(x["song"])
        margin = (None if x.get("value") is None or x.get("bound") is None
                  else round(float(x["value"]) - float(x["bound"]), 4))
        out.append({"id": slug("refused", x["combination"], x["criterion"], stem), "tier": 3,
                    "source": "build/search_refusals.json",
                    "cause": f"{x['combination']} refused by {x['criterion']}",
                    "files": [stem], "tag": TAG[3],
                    "evidence": {"value": x.get("value"), "bound": x.get("bound"), "margin": margin},
                    "verify": (f"Either {stem} adopts `{x['combination']}` with `{x['criterion']}` "
                               "no longer failing (regenerate presets with --fidelity and read "
                               "build/search_refusals.json), or the refusal is recorded as right "
                               "with the mechanism named.")})
    return out


def voice_deficits(rows: list[dict]) -> list[dict]:
    """A voice whose `aud` sits well below the file's others.

    Needs the per-voice readings `fidelity.py --sound-voices` stores as
    `aud_voices: [v0, v1, v2]`; a row without them contributes nothing.
    """
    out = []
    for r in rows:
        vs = r.get("aud_voices")
        if not vs or len([v for v in vs if v is not None]) < 2:
            continue
        good = [v for v in vs if v is not None]
        med = statistics.median(good)
        for i, v in enumerate(vs):
            if v is not None and v < med - 0.2:
                stem = _stem(r["file"])
                out.append({"id": slug("voice", stem, i), "tier": 4, "source": "fidelity.json aud_voices",
                            "cause": f"voice {i} sounds unlike the original where the others do not",
                            "files": [stem], "tag": TAG[4],
                            "evidence": {"aud_voices": vs, "instruments": r.get("voice_instruments", {}).get(str(i))},
                            "verify": (f"{stem} voice {i}'s `aud` within 0.1 of the file's other "
                                       "voices, with the instrument it plays named from "
                                       "instrument_stamps and its effect bits read.")})
    return out


def census_buckets(rows: list[dict]) -> list[dict]:
    """Onset and hold census records grouped by (column, kind, effect byte)."""
    buckets: dict[tuple, dict] = defaultdict(lambda: {"files": set(), "n": 0})
    for r in rows:
        stem = _stem(r["file"])
        for col, key in (("onset", "onset_census"), ("hold", "hold_census")):
            for rec in r.get(key) or []:
                if rec.get("kind") in ("match",):
                    continue
                k = (col, rec.get("kind"), rec.get("effect"))
                buckets[k]["files"].add(stem)
                buckets[k]["n"] += 1
    out = []
    for (col, kind, eff), b in buckets.items():
        cause = f"{col} {kind}" + (f" with effect ${eff:02X}" if isinstance(eff, int) else "")
        files = sorted(b["files"])
        base = {"tier": 5, "source": f"fidelity.json {col}_census", "cause": cause,
                "files": files, "evidence": {"instruments": b["n"], "files": len(files)}}
        out.append(dict(base, id=slug("census", col, kind, eff, "confirm"), tag="[subagent]",
                        verify=(f"The {b['n']} instrument(s) in this bucket share ONE cause, "
                                "shown by reading the record bytes of each; or the bucket is split "
                                "and the split written into the census.")))
        out.append(dict(base, id=slug("census", col, kind, eff, "fix"), tag="[main]",
                        verify=(f"The `{col}` column's `{kind}` count falls on every file in this "
                                "bucket and rises on none, corpus A/B, with the emitter change "
                                "named.")))
    return out


def column_outliers(rows: list[dict]) -> list[dict]:
    out = []
    measured = [r for r in rows if r.get("status") == "measured"]
    for d in F.DIMENSIONS:
        if d.kind != "fraction":
            continue
        vals = [(r, d.value(r)) for r in measured if d.value(r) is not None]
        if len(vals) < 8:
            continue
        xs = [v for _, v in vals]
        med = statistics.median(xs)
        mad = statistics.median(abs(x - med) for x in xs)
        if mad == 0.0:
            # A tied majority (most files at one value, a minority away from
            # it) makes the MEDIAN absolute deviation zero even though the
            # corpus plainly has spread -- the deviation itself is what a
            # majority-vs-minority split produces. Population std substitutes
            # only in that case, so a column with genuinely no spread at all
            # (every file identical) is still skipped below rather than
            # reporting a false outlier.
            mad = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        if mad == 0.0:
            continue
        for r, v in vals:
            if v < med - MAD_MULTIPLE * mad:
                stem = _stem(r["file"])
                out.append({"id": slug("outlier", d.column, stem), "tier": 6,
                            "source": f"fidelity.json {d.key}",
                            "cause": f"{d.column} far below the corpus", "files": [stem],
                            "tag": TAG[6],
                            "evidence": {d.column: v, "median": med, "mad": mad},
                            "verify": (f"{stem}'s `{d.column}` within {MAD_MULTIPLE:.0f} MAD of the "
                                       "corpus median, or its cause named -- run "
                                       f"`fidelity.py {stem}.sid --diagnose` FIRST: six harness "
                                       "defects have looked exactly like this.")})
    return out


# ---- ordering, annotation, persistence ------------------------------------
def ordered(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e["tier"], -len(e.get("files", [])), e["id"]))


def annotate(entries: list[dict], plan: dict, runs: dict) -> None:
    tasks = plan.get("tasks") or []
    for e in entries:
        e.setdefault("already_tracked", None)
        e.setdefault("already_refuted", None)
        col = _cause_keyword(e["cause"])
        for t in tasks:
            text = " ".join(str(t.get(k, "")) for k in ("id", "title", "source", "verify")).lower()
            if any(f.lower() in text for f in e["files"]) and col in text:
                e["already_tracked"] = t["id"]
                break
        for rid, r in runs.items():
            if r.get("outcome") != "done":
                continue
            ev = str(r.get("evidence", "")).lower()
            if any(f.lower() in ev for f in e["files"]) and col in ev and "refut" in ev:
                e["already_refuted"] = rid
                break


def carry_seen(entries: list[dict], prior: dict, version: str) -> None:
    seen = {p["id"]: p for p in (prior or {}).get("entries", [])}
    for e in entries:
        e["first_seen"] = seen.get(e["id"], {}).get("first_seen", version)
        e["last_seen"] = version


def closed_since(prior: dict, entries: list[dict]) -> list[dict]:
    now = {e["id"] for e in entries}
    return [p for p in (prior or {}).get("entries", []) if p["id"] not in now]


def entries_from(rows, approvals, refusals, prior, plan, runs, version) -> list[dict]:
    entries = (stale_approvals(approvals) + length_failures(rows) + refusal_entries(refusals)
               + voice_deficits(rows) + census_buckets(rows) + column_outliers(rows))
    entries = ordered(entries)
    annotate(entries, plan, runs)
    carry_seen(entries, prior, version)
    return entries


# ---- output --------------------------------------------------------------
TIER_NAMES = {1: "Stale approvals -- a listen is the only thing that closes these",
              2: "Length rule failures", 3: "Search refusals",
              4: "Voice deficits in the rendered sound", 5: "Census buckets",
              6: "Column outliers -- leads, not findings"}


def render(entries: list[dict], closed: list[dict], meta: dict) -> str:
    out = ["# Fidelity queue", "",
           f"Generated by `python/fidelity_queue.py` (h2g {meta['version']}, {meta['head']}), "
           f"from a {meta['seconds']} s run. {len(entries)} entries. `/whattask` reads this as a "
           "source; nothing here writes the plan.", ""]
    for tier in sorted(TIER_NAMES):
        es = [e for e in entries if e["tier"] == tier]
        out += [f"## Tier {tier}: {TIER_NAMES[tier]}", ""]
        if not es:
            out += ["(none)", ""]
            continue
        out += ["| id | files | cause | tag | evidence | verify | seen | tracked / refuted |",
                "|---|---|---|---|---|---|---|---|"]
        for e in es:
            out.append("| `%s` | %s | %s | %s | %s | %s | %s -> %s | %s |" % (
                e["id"], ", ".join(e["files"]), e["cause"], e["tag"],
                json.dumps(e["evidence"], default=str), e["verify"].replace("|", "\\|"),
                e["first_seen"], e["last_seen"],
                " / ".join(x or "-" for x in (e.get("already_tracked"), e.get("already_refuted")))))
        out.append("")
    if closed:
        out += ["## Closed since last run", ""] + [f"- `{c['id']}` (last seen {c.get('last_seen')})"
                                                   for c in closed] + [""]
    return "\n".join(out)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _runs(path: Path) -> dict:
    last = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r.get("id")] = r
    return last


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fidelity_queue")
    p.add_argument("--from-json", default=str(ROOT / "build" / "fidelity.json"))
    p.add_argument("-o", "--output", default=str(ROOT / "docs" / "QUEUE.md"))
    p.add_argument("--json", default=str(ROOT / "build" / "queue.json"))
    args = p.parse_args(argv)
    rows = _load_json(Path(args.from_json), [])
    rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
    seconds = next((r.get("seconds") for r in rows if r.get("seconds")), 60)
    approvals = _load_json(ROOT / "build" / "approvals.json", {}).get("tunes", {})
    refusals = _load_json(ROOT / "build" / "search_refusals.json", {}).get("refusals", [])
    prior = _load_json(Path(args.json), {})
    plan = _load_json(ROOT / ".claude" / "tasks" / "whattask.json", {})
    runs = _runs(ROOT / ".claude" / "tasks" / "runs.jsonl")
    entries = entries_from(rows, approvals, refusals, prior, plan, runs, __version__)
    closed = closed_since(prior, entries)
    meta = {"version": __version__, "head": F.git_label(ROOT), "seconds": seconds}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({**meta, "entries": entries, "closed": closed},
                                          indent=2, default=str) + "\n", encoding="utf-8")
    Path(args.output).write_text(render(entries, closed, meta), encoding="utf-8")
    print(f"wrote {args.output}: {len(entries)} entries, {len(closed)} closed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
