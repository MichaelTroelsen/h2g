#!/usr/bin/env python3
"""Run the converter over a directory of .sid files and emit a Markdown report.

Usage:
    python survey.py <sid_dir> [-o REPORT.md] [--sng-dir DIR]

Runs detection and full conversion on every .sid found, recording which
detection stage failed so the report says *why* a file is unconvertible, not
just that it is. Nothing is written unless --sng-dir is given.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from h2g import __version__
from h2g.detect import detect
from h2g.goatwriter import (DEFAULT_FORMAT, FORMATS, MAX_INSTRUMENTS,
                            build_sng)
from h2g.patterns import (GT_DEFAULT_ROWS, GT_MAX_ROWS, ConversionAbort,
                          convert_patterns, reindex_tracks)
from h2g.sidfile import SidFormatError, load_sid
from h2g.tracks import convert_tracks

VERSION_NAMES = {
    0: "Warhawk", 1: "Last V8", 2: "Auf Wiedersehen Monty", 3: "Samantha Fox",
    4: "ACE 2", 5: "Battle of Britain", 6: "Mega Apocalypse", 7: "IK+",
}


@dataclass
class Result:
    path: Path
    name: str = ""
    author: str = ""
    released: str = ""
    subtunes: int = 0          # what the PSID header claims
    subtunes_emitted: int = 0  # how many actually reach the .sng after trimming
    load_addr: int = 0
    ok: bool = False
    out_size: int = 0
    patterns: int = 0
    instruments: int = 0
    version: int = 0xFF
    found: dict = field(default_factory=dict)
    stage: str = ""
    error: str = ""


def survey_one(path: Path, sng_dir: Path | None,
               max_rows: int = GT_DEFAULT_ROWS,
               terminate_patterns: bool = False,
               fmt: str = DEFAULT_FORMAT) -> Result:
    r = Result(path=path)

    try:
        sid = load_sid(str(path))
    except SidFormatError as exc:
        r.stage, r.error = "header", str(exc)
        return r
    except Exception as exc:  # noqa: BLE001 - report anything, don't abort the sweep
        r.stage, r.error = "header", f"{type(exc).__name__}: {exc}"
        return r

    r.name, r.author, r.released = sid.name, sid.author, sid.released
    r.subtunes, r.load_addr = sid.subtunes, sid.load_addr

    try:
        det = detect(sid, log=lambda m: None)
    except Exception as exc:  # noqa: BLE001
        r.stage, r.error = "detect", f"{type(exc).__name__}: {exc}"
        return r

    r.version = det.read_track_version
    r.instruments = det.instr_used + 1 if det.instr_used >= 0 else 0
    r.found = {
        "instr": det.instr_start > 0,
        "tracks": det.track_lo > 0 and det.track_hi > 0,
        "patterns": det.pattern_lo > 0 and det.pattern_hi > 0,
        "version": det.read_track_version != 0xFF,
    }

    if not det.can_convert:
        missing = [k for k in ("tracks", "patterns") if not r.found[k]]
        r.stage = "detect"
        r.error = "no player detected (missing: " + ", ".join(missing) + ")"
        return r

    try:
        tracks = convert_tracks(sid, det, log=lambda m: None)
    except Exception as exc:  # noqa: BLE001
        r.stage, r.error = "tracks", f"{type(exc).__name__}: {exc}"
        return r

    # convert_tracks drops the trailing run of unusable subtunes, so this is
    # frequently smaller than the PSID header's claim -- that is the count the
    # .sng actually carries, and the one worth reporting.
    r.subtunes_emitted = len(tracks) // 3

    try:
        new_patterns, track_index = convert_patterns(
            sid, det, log=lambda m: None, max_rows=max_rows,
            terminate_patterns=terminate_patterns)
        tracks = reindex_tracks(tracks, track_index)
    except ConversionAbort as exc:
        r.stage, r.error = "patterns", str(exc)
        return r
    except Exception as exc:  # noqa: BLE001
        r.stage, r.error = "patterns", f"{type(exc).__name__}: {exc}"
        return r

    try:
        sng = build_sng(sid, det, tracks, new_patterns, fmt=fmt)
    except Exception as exc:  # noqa: BLE001
        r.stage, r.error = "write", f"{type(exc).__name__}: {exc}"
        return r

    r.ok, r.out_size, r.patterns = True, len(sng), len(new_patterns)
    if sng_dir:
        sng_dir.mkdir(parents=True, exist_ok=True)
        (sng_dir / (path.stem + ".sng")).write_bytes(sng)
    return r


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").strip() or "-"


def build_report(results: list[Result], sid_dir: Path,
                 max_rows: int = GT_DEFAULT_ROWS) -> str:
    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]

    lines: list[str] = []
    lines.append("# H2G conversion survey — Rob Hubbard SID corpus")
    lines.append("")
    lines.append(f"- Converter: `h2g` **{__version__}**")
    lines.append(f"- Corpus: `{sid_dir}`")
    lines.append(f"- Files tested: **{len(results)}**")
    note = " (original VB6 behaviour)" if max_rows == GT_DEFAULT_ROWS else \
           f" (raised from {GT_DEFAULT_ROWS}; Goattracker's limit is {GT_MAX_ROWS})"
    lines.append(f"- Pattern slicing: **{max_rows} rows**{note}")
    pct = (100.0 * len(ok) / len(results)) if results else 0.0
    lines.append(f"- Converted: **{len(ok)}** ({pct:.0f}%) — Failed: **{len(bad)}**")
    lines.append("")
    lines.append("> \"Converted\" means the converter produced a `.sng` without erroring. "
                 "It does **not** mean the output is musically correct. Only the "
                 "repo's own `Commando.sid` is verified byte-exact against the "
                 "original VB6 tool; note that the corpus copy of `Commando.sid` is a "
                 "*different rip* (4165 B / 19 subtunes vs the repo's 4222 B / 3 "
                 "subtunes), so its row here is not comparable to that fixture.")
    lines.append("")
    rows_arg = "" if max_rows == GT_DEFAULT_ROWS else f" --max-rows {max_rows}"
    lines.append(f"Regenerate with: `python survey.py \"{sid_dir}\" "
                 f"-o SURVEY.md{rows_arg}`")
    lines.append("")

    # --- failure breakdown -------------------------------------------------
    by_stage: dict[str, int] = {}
    for r in bad:
        by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
    if by_stage:
        lines.append("## Failure breakdown by stage")
        lines.append("")
        lines.append("| Stage | Files | Meaning |")
        lines.append("|---|---:|---|")
        meanings = {
            "header": "PSID/RSID header rejected",
            "detect": "no known player fingerprint matched",
            "tracks": "orderlist decode failed (usually unknown track-read version)",
            "patterns": "pattern decode/slicing hit a Goattracker limit",
            "write": "serialization error",
        }
        for stage, count in sorted(by_stage.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {stage} | {count} | {meanings.get(stage, '-')} |")
        lines.append("")

    # --- player version distribution --------------------------------------
    by_ver: dict[int, int] = {}
    for r in ok:
        by_ver[r.version] = by_ver.get(r.version, 0) + 1
    if by_ver:
        lines.append("## Detected player variant (successful conversions)")
        lines.append("")
        lines.append("| Version | Player family | Files |")
        lines.append("|---:|---|---:|")
        for ver, count in sorted(by_ver.items()):
            label = VERSION_NAMES.get(ver, "unknown")
            shown = "none" if ver == 0xFF else str(ver)
            lines.append(f"| {shown} | {label} | {count} |")
        lines.append("")

    # --- computed findings -------------------------------------------------
    suspect = [r for r in ok if r.instruments > MAX_INSTRUMENTS]
    lines.append("## Findings")
    lines.append("")
    lines.append(f"- **{len(ok)}/{len(results)} produced output.** The ceiling is "
                 "structural: detection only recognises 16 hard-coded game "
                 "fingerprints, so anything outside that set is unconvertible by "
                 "construction.")
    cap = [r for r in bad if r.stage == "patterns"]
    if cap:
        lines.append(f"- **{len(cap)} failures are capacity, not comprehension.** These "
                     "files detect cleanly (all four passes green) and fail only "
                     "because the tune exceeds a Goattracker limit — 208 patterns or a "
                     "255-byte orderlist. They are the most recoverable group: "
                     "splitting the orderlist across subtunes would convert them.")
    if suspect:
        names = ", ".join(f"`{r.path.name}`" for r in sorted(suspect, key=lambda x: x.path.name))
        lines.append(f"- **{len(suspect)} conversions report more than "
                     f"{MAX_INSTRUMENTS} instruments** ({names}), which the writer then "
                     "clamps. Hubbard tunes do not plausibly use that many, so the "
                     "waveform-sniffing table-end heuristic is over-reading past the "
                     "real instrument table. Output is written but the instrument set "
                     "should be treated as unreliable — see the flag in the table below.")
    crashes = [r for r in bad if "IndexError" in r.error or r.stage == "crash"]
    if crashes:
        names = ", ".join(f"`{r.path.name}`" for r in crashes)
        lines.append(f"- **{len(crashes)} files crash on an unguarded read** ({names}) — "
                     "an extracted address landed outside the data section and was "
                     "dereferenced without a range check.")
    lines.append("")

    # --- successes ---------------------------------------------------------
    lines.append(f"## Converted ({len(ok)})")
    lines.append("")
    lines.append("| File | Title | Player | Ver | Subtunes | Instr | Patterns | "
                 ".sng bytes | Flag |")
    lines.append("|---|---|---|---:|---|---:|---:|---:|---|")
    for r in sorted(ok, key=lambda x: x.path.name.lower()):
        flag = "instr over-read" if r.instruments > MAX_INSTRUMENTS else ""
        subs = str(r.subtunes_emitted)
        if r.subtunes_emitted != r.subtunes:
            subs += f" (hdr {r.subtunes})"
        lines.append(
            f"| `{r.path.name}` | {_md_escape(r.name)} | "
            f"{VERSION_NAMES.get(r.version, 'unknown')} | {r.version} | {subs} | "
            f"{r.instruments} | {r.patterns} | {r.out_size} | {flag} |"
        )
    lines.append("")
    lines.append("`Player`/`Ver` are the detected Hubbard player-engine variant and its "
                 "track-read version number. `Subtunes` is how many actually reach the "
                 "`.sng`; where that differs from the PSID header's claim the header "
                 "value follows in brackets, and the gap is subtunes whose orderlist "
                 "pointers resolve outside the file (the track table has no length "
                 "field, so the header routinely over-claims).")
    lines.append("")

    # --- failures ----------------------------------------------------------
    lines.append(f"## Not converted ({len(bad)})")
    lines.append("")
    lines.append("| File | Title | Stage | Player | Sub (hdr) | Instr? | Trk? | Pat? | Reason |")
    lines.append("|---|---|---|---|---:|:-:|:-:|:-:|---|")
    tick = {True: "y", False: "-"}
    for r in sorted(bad, key=lambda x: (x.stage, x.path.name.lower())):
        f = r.found
        cols = (tick[f.get("instr", False)], tick[f.get("tracks", False)],
                tick[f.get("patterns", False)])
        player = VERSION_NAMES.get(r.version, "-") if f.get("version") else "-"
        lines.append(
            f"| `{r.path.name}` | {_md_escape(r.name)} | {r.stage} | {player} | "
            f"{r.subtunes} | {cols[0]} | {cols[1]} | {cols[2]} | {_md_escape(r.error)} |"
        )
    lines.append("")
    lines.append("`Player` is the detected player variant, or `-` when the "
                 "player-version pass found nothing. `Sub (hdr)` is the PSID header's "
                 "subtune claim — these files produce no `.sng`, so there is no emitted "
                 "count to compare it against.")
    lines.append("")
    lines.append("Columns `Instr?`/`Trk?`/`Pat?` show which of the three table-locating "
                 "detection passes found their target. A file with tables found but no "
                 "`Player` has a recognisable data layout and an unrecognised "
                 "player loop.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="survey")
    parser.add_argument("sid_dir", help="directory of .sid files (searched recursively)")
    parser.add_argument("-o", "--output", default="SURVEY.md", help="report path")
    parser.add_argument("--sng-dir", help="also write converted .sng files here")
    parser.add_argument("--format", choices=FORMATS, default=DEFAULT_FORMAT,
                        help="output .sng format (default: %(default)s)")
    parser.add_argument("--terminate-patterns", action="store_true",
                        help="append an explicit ENDPATT row to each pattern slice")
    parser.add_argument("--max-rows", type=int, default=GT_DEFAULT_ROWS,
                        metavar="N",
                        help="pattern-slicing length, 1..{GT_MAX_ROWS} (default: %(default)s)")
    args = parser.parse_args(argv)

    sid_dir = Path(args.sid_dir)
    if not sid_dir.is_dir():
        print(f"error: not a directory: {sid_dir}", file=sys.stderr)
        return 1

    paths = sorted(sid_dir.rglob("*.sid"), key=lambda p: p.name.lower())
    if not paths:
        print(f"error: no .sid files under {sid_dir}", file=sys.stderr)
        return 1

    sng_dir = Path(args.sng_dir) if args.sng_dir else None
    results = []
    for path in paths:
        try:
            results.append(survey_one(path, sng_dir, args.max_rows,
                                      args.terminate_patterns))
        except Exception:  # noqa: BLE001 - a crash must not kill the sweep
            r = Result(path=path, stage="crash", error=traceback.format_exc(limit=1))
            results.append(r)

    Path(args.output).write_text(
        build_report(results, sid_dir, args.max_rows), encoding="utf-8")
    ok = sum(1 for r in results if r.ok)
    print(f"{ok}/{len(results)} converted -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
