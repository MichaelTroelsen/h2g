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
import os
import shutil
import subprocess
import tempfile
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from h2g import __version__
from h2g.convert import (UnsupportedSidError, _detect_tables,
                         check_detection_sound)
from h2g.goatwriter import (DEFAULT_FORMAT, FORMAT_GTS2, FORMATS,
                            GT_MAX_TABLELEN, MAX_INSTRUMENTS,
                            WAVE_ENTRIES_PER_INSTR, build_sng)
from h2g.patterns import (GT_DEFAULT_ROWS, GT_MAX_ROWS, ConversionAbort,
                          command_floor, convert_patterns,
                          referenced_patterns, reindex_tracks)
from h2g.sidfile import SidFormatError, load_sid
from h2g.sidid import Database, find_database
from h2g.tracks import convert_tracks, legalise_restarts

VERSION_NAMES = {
    0: "Warhawk", 1: "Last V8", 2: "Auf Wiedersehen Monty", 3: "Samantha Fox",
    4: "ACE 2", 5: "Battle of Britain", 6: "Mega Apocalypse", 7: "IK+",
    8: "digi engine", 9: "Chain Reaction",
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
    source_format: str = ""   # the input's own header version, e.g. "PSID v2"
    sidid: str = ""           # SIDId player identification, independent of detect()
    dangling: int = 0         # distinct orderlist refs to patterns that don't exist
    dangling_sub0: int = 0    # ...of those, how many are in subtune 0
    voices: int = 3           # voices the player drives; >3 means a sample channel
    subtunes_dropped: int = 0  # subtunes whose orderlist exceeded the 254-byte limit
    gt2reloc: str = ""         # "", "ok" or "fail": does the .sng pack back to .sid?
    sid_bytes: int = 0         # size of the packed .sid, when it packs
    found: dict = field(default_factory=dict)
    stage: str = ""
    error: str = ""


def _dangling(tracks: list, pattern_used: int, floor: int) -> tuple[int, int]:
    """Orderlist references to pattern numbers the pattern table does not hold.

    Returns (distinct dangling refs anywhere, distinct dangling refs in subtune
    0). The split matters because it separates two different faults: subtune 0
    is always real, so a dangling ref there means the *decode* is wrong, while
    dangling refs only in later subtunes mean the PSID header over-claimed its
    subtune count and a bogus pointer is being read as an orderlist.

    reindex_tracks drops these references silently, so nothing downstream
    reveals them. The walk itself is delegated to referenced_patterns, keeping
    the orderlist grammar ($D0-$FE commands, the restart position after $FF)
    defined in exactly one place.
    """
    everywhere = {p for p in referenced_patterns(tracks, floor) if p > pattern_used}
    first = {p for p in referenced_patterns(tracks[:3], floor) if p > pattern_used}
    return len(everywhere), len(first)


# --- packing back to .sid --------------------------------------------------
#
# gt2reloc is the standalone form of Goattracker's F9 packer and writes .sid
# straight from the output extension, so it turns a converted .sng back into
# something a SID player can play -- the other half of a fidelity test against
# the file we converted from. See SNG2SID-FIDELITY.md.
GT2RELOC_ENV = "H2G_GT2RELOC"
GT2RELOC_DEFAULT = r"C:\Users\mit\Downloads\GoatTracker_2.77\win32\gt2reloc.exe"


def find_gt2reloc(explicit=None):
    for candidate in (explicit, os.environ.get(GT2RELOC_ENV), GT2RELOC_DEFAULT):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def pack_to_sid(sng: bytes, exe: str, workdir: str):
    """Pack .sng bytes to .sid. Returns ("ok"|"fail", size).

    Never trust the exit code. gt2reloc reports fatal errors through
    `fopen("CON")` and SDL screen routines that do nothing headless, so a
    refusal is exit 0 with no output and no file -- indistinguishable from
    success at the shell. The written file is the only reliable signal.

    Arguments are passed as bare filenames with the working directory set,
    because gt2reloc strcpy()s argv into a 60-byte buffer before reducing it
    to a basename (gt2reloc.c:144, MAX_FILENAME in gfile.h).
    """
    src, dst = Path(workdir) / "s.sng", Path(workdir) / "s.sid"
    dst.unlink(missing_ok=True)
    src.write_bytes(sng)
    try:
        subprocess.run([exe, "s.sng", "s.sid"], cwd=workdir, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "fail", 0
    return ("ok", dst.stat().st_size) if dst.is_file() else ("fail", 0)


def survey_one(path: Path, sng_dir: Path | None,
               max_rows: int = GT_DEFAULT_ROWS,
               terminate_patterns: bool = False,
               fmt: str = DEFAULT_FORMAT,
               dedup: bool = False,
               prune: bool = False,
               pack: bool = False,
               legal_restart: bool = False,
               sidid_db: Database | None = None,
               gt2reloc: str | None = None,
               workdir: str | None = None) -> Result:
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
    r.source_format = sid.source_format
    if sidid_db is not None:
        names = sidid_db.identify(sid.data)
        r.sidid = ", ".join(names) if names else "(none)"
    r.subtunes, r.load_addr = sid.subtunes, sid.load_addr

    try:
        # Must be convert()'s own detection path, not a bare detect(): a
        # player whose table operands are placeholders until init patches
        # them locates its bases fine and reads no patterns, so a raw
        # detect() reports a tracks-stage failure for a file convert()
        # rescues and converts. See convert._detect_tables.
        sid, det = _detect_tables(sid, log=lambda m: None)
    except Exception as exc:  # noqa: BLE001
        r.stage, r.error = "detect", f"{type(exc).__name__}: {exc}"
        return r

    r.version = det.read_track_version
    r.voices = det.track_voices
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
    floor = command_floor(det.read_track_version)
    r.dangling, r.dangling_sub0 = _dangling(tracks, det.pattern_used, floor)

    # Same soundness gate the converter applies, so the report agrees with what
    # `python -m h2g` actually does rather than counting a refusal as a pass.
    try:
        check_detection_sound(tracks, det.pattern_used, lambda m: None, floor)
    except UnsupportedSidError as exc:
        r.stage, r.error = "tracks", str(exc)
        return r

    try:
        new_patterns, track_index = convert_patterns(
            sid, det, log=lambda m: None, max_rows=max_rows,
            terminate_patterns=terminate_patterns, dedup=dedup,
            used=referenced_patterns(tracks, floor) if prune else None)
        dropped: list[int] = []
        tracks = reindex_tracks(tracks, track_index, pack, floor,
                                dropped=dropped, patterns=new_patterns,
                                max_rows=max_rows)
        r.subtunes_dropped = len(dropped)
        if legal_restart:
            legalise_restarts(tracks)
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
    if gt2reloc and workdir:
        r.gt2reloc, r.sid_bytes = pack_to_sid(sng, gt2reloc, workdir)
    if sng_dir:
        sng_dir.mkdir(parents=True, exist_ok=True)
        (sng_dir / (path.stem + ".sng")).write_bytes(sng)
    return r


def _is_hubbard_player(sidid: str) -> bool:
    """True if SIDId named a Rob Hubbard player engine among its matches.

    A file can match several signatures at once (`Rob_Hubbard,
    (Rob_Hubbard_Digi), Sidplayer`); one Hubbard engine is enough, since that
    is the thing this tool rips. `Companion` or `SidTracker64` alone means
    someone else's editor and therefore a layout no signature here describes.
    """
    return "Rob_Hubbard" in sidid


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").strip() or "-"


def build_report(results: list[Result], sid_dir: Path,
                 max_rows: int = GT_DEFAULT_ROWS,
                 fmt: str = DEFAULT_FORMAT,
                 legal_restart: bool = False) -> str:
    ok = [r for r in results if r.ok]
    # A file whose player SIDId names as someone else's editor is not a failure
    # of this tool -- no Hubbard fingerprint can match it and no new signature
    # would ever bring it in. Reported separately so the failure list stays a
    # list of things that could be fixed.
    out_of_scope = [r for r in results
                    if not r.ok and r.sidid and not _is_hubbard_player(r.sidid)]
    bad = [r for r in results if not r.ok and r not in out_of_scope]

    lines: list[str] = []
    lines.append("# H2G conversion survey — Rob Hubbard SID corpus")
    lines.append("")
    lines.append(f"- Converter: `h2g` **{__version__}**")
    lines.append(f"- Corpus: `{sid_dir}`")
    lines.append(f"- Files tested: **{len(results)}**")
    note = " (original VB6 behaviour)" if max_rows == GT_DEFAULT_ROWS else \
           f" (raised from {GT_DEFAULT_ROWS}; Goattracker's limit is {GT_MAX_ROWS})"
    lines.append(f"- Pattern slicing: **{max_rows} rows**{note}")
    fmt_note = (" (3-table, original VB6 behaviour; note Goattracker's legacy GTS2 "
                "importer overruns its pattern array on the portamento commands this "
                "converter emits — prefer `--format gts5` for files you will open "
                "in Goattracker)"
                if fmt == FORMAT_GTS2 else
                " (modern 4-table format; avoids the GTS2 importer overrun, and is "
                "what Goattracker itself writes)")
    lines.append(f"- Output format: **{fmt.upper()}** (of {'/'.join(f.upper() for f in FORMATS)}){fmt_note}")
    lines.append(
        "- Restart position: **legalised** (`--legal-restart`) — a tune ending "
        "on Hubbard's `$FE` marker loops from the top instead of stopping, "
        "which is what lets `gt2reloc` export it at all"
        if legal_restart else
        "- Restart position: **as the original tool wrote it** — a tune ending "
        "on Hubbard's `$FE` marker stops, at the cost of being unexportable by "
        "`gt2reloc` (`--legal-restart` trades the stop for a loop)")
    reach = len(results) - len(out_of_scope)
    pct = (100.0 * len(ok) / reach) if reach else 0.0
    scope_note = (f" — Out of scope: **{len(out_of_scope)}** (not a Hubbard player)"
                  if out_of_scope else "")
    lines.append(f"- Converted: **{len(ok)}** of {reach} in reach ({pct:.0f}%) — "
                 f"Failed: **{len(bad)}**{scope_note}")
    lines.append("")
    lines.append("> \"Converted\" means the converter produced a `.sng` without erroring. "
                 "It does **not** mean the output is musically correct. Only the "
                 "repo's own `Commando.sid` is verified byte-exact against the "
                 "original VB6 tool; note that the corpus copy of `Commando.sid` is a "
                 "*different rip* (4165 B / 19 subtunes vs the repo's 4222 B / 3 "
                 "subtunes), so its row here is not comparable to that fixture.")
    lines.append("")
    rows_arg = "" if max_rows == GT_DEFAULT_ROWS else f" --max-rows {max_rows}"
    fmt_arg = "" if fmt == DEFAULT_FORMAT else f" --format {fmt}"
    restart_arg = " --legal-restart" if legal_restart else ""
    lines.append(f"Regenerate with: `python survey.py \"{sid_dir}\" "
                 f"-o SURVEY.md{rows_arg}{fmt_arg}{restart_arg}`")
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

    # --- SIDId identification ----------------------------------------------
    # SIDId fingerprints the *player routine* from an independent signature
    # database, so it answers a question detect() cannot: whether a file this
    # tool failed on was ever within reach. H2G only knows Hubbard player
    # engines, so a tune Hubbard merely *composed* -- shipped in someone
    # else's editor -- is unconvertible by construction rather than by
    # omission, and counting those against the tool overstates what is left
    # to fix.
    identified = [r for r in results if r.sidid]
    if identified:
        by_id: dict[str, list[int]] = {}
        for r in identified:
            row = by_id.setdefault(r.sidid, [0, 0])
            row[0 if r.ok else 1] += 1
        lines.append("## SIDId player identification")
        lines.append("")
        lines.append("| SIDId signature | Converted | Not converted | Total | Rate |")
        lines.append("|---|---:|---:|---:|---:|")
        for name, (good, missed) in sorted(
                by_id.items(), key=lambda kv: (-(kv[1][0] + kv[1][1]), kv[0])):
            total = good + missed
            hub = "" if _is_hubbard_player(name) else " *"
            lines.append(f"| `{name}`{hub} | {good} | {missed} | {total} | "
                         f"{100 * good // total}% |")
        lines.append("")
        if any(not _is_hubbard_player(n) for n in by_id):
            lines.append("`*` marks a player routine that is **not** a Rob Hubbard "
                         "engine. Those files are in the corpus because Hubbard "
                         "wrote the music, not the player, so no Hubbard "
                         "fingerprint can match them.")
            lines.append("")

    # --- computed findings -------------------------------------------------
    suspect = [r for r in ok if r.instruments > MAX_INSTRUMENTS]
    lines.append("## Findings")
    lines.append("")
    lines.append(f"- **{len(ok)}/{len(results)} produced output.** The ceiling is "
                 "structural: detection only recognises 17 hard-coded game "
                 "fingerprints, so anything outside that set is unconvertible by "
                 "construction.")
    if out_of_scope:
        names = ", ".join(sorted({r.sidid for r in out_of_scope}))
        lines.append(
            f"- **{len(out_of_scope)} files are not Hubbard-player tunes at all** "
            f"and are listed separately below. SIDId identifies their player as "
            f"{names} — Hubbard wrote the music, someone else wrote the routine, "
            "so no Hubbard fingerprint can match and no new signature would bring "
            f"them in. Excluding them, coverage is **{len(ok)}/{reach} = "
            f"{100 * len(ok) // reach}%** rather than "
            f"{len(ok)}/{len(results)} = {100 * len(ok) // len(results)}%.")
    digi = [r for r in ok if r.voices > 3]
    if digi:
        names = ", ".join(f"`{r.path.name}`" for r in sorted(digi, key=lambda x: x.path.name))
        lines.append(
            f"- **{len(digi)} tunes drive a fourth, sampled voice that is not "
            "converted.** Their player runs four channels; the extra one plays "
            "digi samples, which is what the `(Rob_Hubbard_Digi)` SIDId "
            "signature marks. Goattracker has three voices and no way to carry "
            "sampled playback, so that channel is dropped — the three SID "
            f"voices convert in full. Affected: {names}.")
    over = [r for r in ok if r.subtunes_dropped]
    if over:
        names = ", ".join(f"`{r.path.name}` ({r.subtunes_dropped})"
                          for r in sorted(over, key=lambda x: x.path.name))
        lines.append(
            f"- **{len(over)} files lose a subtune to Goattracker's 254-byte "
            "orderlist limit.** The rest of the tune converts: one over-long "
            "subtune used to abort the whole file, discarding every good "
            "subtune with it. The subtune is dropped rather than truncated, "
            "because cutting one voice short while its neighbours play on "
            "makes it loop early and drift — a subtune that sounds wrong is "
            f"worse than one plainly absent. Affected: {names}.")
    packed = [r for r in ok if r.gt2reloc]
    if packed:
        good = [r for r in packed if r.gt2reloc == "ok"]
        lines.append(
            f"- **{len(good)} of {len(packed)} converted files pack back to a "
            "`.sid`** with `gt2reloc`, the standalone form of Goattracker's F9 "
            "packer. That is what makes a fidelity test possible: the packed "
            "`.sid` can be `siddump`ed against the file it was converted from. "
            "A failure here is not a conversion failure — the `.sng` is fine in "
            "the editor — but it blocks that comparison. See "
            "[`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md)."
            + (" These numbers are with `--legal-restart`; without it "
               "`greloc.c:244` rejects every tune that ends on Hubbard's `$FE` "
               "marker, because the stop it maps to is an out-of-range restart "
               "position." if legal_restart else
               " The known cause is the restart position this converter emits "
               "for a `$FE` track byte, which `greloc.c:244` rejects as out of "
               "range; `--legal-restart` trades that stop for a loop and clears "
               "it."))
    cap = [r for r in bad if r.stage == "patterns"]
    if cap:
        lines.append(f"- **{len(cap)} failures are capacity, not comprehension.** These "
                     "files detect cleanly (all four passes green) and fail only "
                     "because the tune exceeds a Goattracker limit — 208 patterns or a "
                     "255-byte orderlist. They are the most recoverable group: "
                     "splitting the orderlist across subtunes would convert them.")
    if suspect:
        names = ", ".join(f"`{r.path.name}`" for r in sorted(suspect, key=lambda x: x.path.name))
        dropped = sum(r.instruments - MAX_INSTRUMENTS for r in suspect)
        lines.append(f"- **{len(suspect)} tunes carry more than {MAX_INSTRUMENTS} "
                     f"instruments and lose the excess** ({names}) — {dropped} "
                     "instruments dropped in total. The limit is Goattracker's: each "
                     "instrument costs 5 wavetable entries against a 255-entry table "
                     "addressed by a single length byte, so at most "
                     f"{GT_MAX_TABLELEN // WAVE_ENTRIES_PER_INSTR} are representable. "
                     "Patterns referencing a dropped slot play with an undefined "
                     "instrument — see the flag in the table below. Check any entry "
                     "here against the instrument count the log reports: until v0.5.66 "
                     "this list held nine files that were never over the limit (ten "
                     "detected over it, one of which does not convert), because the "
                     "count ran off the end of the records into the table that follows "
                     "them.")
    dangling = [r for r in ok if r.dangling]
    decode_fault = [r for r in dangling if r.dangling_sub0]
    phantom = [r for r in dangling if not r.dangling_sub0]
    if dangling:
        v2 = ", ".join(f"`{r.path.name}`" for r in sorted(decode_fault, key=lambda x: x.path.name)
                       if r.version == 2)
        lines.append(f"- **{len(dangling)} converted files contain orderlist entries that "
                     "point at patterns the file does not have.** `reindex_tracks` drops "
                     "those references silently, so the tune plays with material missing "
                     "rather than failing." + (
                         " There are two distinct causes, separated by whether subtune 0 "
                         "— always a real subtune — is affected."
                         if decode_fault and phantom else ""))
        if decode_fault:
            lines.append(f"  - **{len(decode_fault)} are a decode fault** (dangling refs in "
                         "subtune 0). Most are version-2 players, where a byte with the "
                         "high bit set is a per-voice **transpose command**, not a pattern "
                         "number: the player branches `BPL` past the $FF/$FE checks, then "
                         "`AND #$7F` / `STA transpose,X`, and the stored value is read back "
                         "as `CLC` / `ADC transpose,X` on the note before the "
                         "frequency-table lookup. The track reader groups version 2 with "
                         "versions 0/1/3, which have no such branch, so it emits those "
                         f"command bytes as pattern numbers $80-$FD. Affected: {v2}.")
        if phantom:
            lines.append(f"  - **{len(phantom)} are phantom subtunes** (subtune 0 clean, "
                         "later subtunes dangling). The track table has no length field "
                         "and the PSID header routinely over-claims, so a pointer that "
                         "happens to land inside the file is read as an orderlist. Only "
                         "pointers resolving *outside* the file, and subtunes that play "
                         "no existing pattern at all, are rejected -- a threshold on the "
                         "rest would also discard real subtunes, which run as low as one "
                         "bad reference in a hundred good ones.")
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
    lines.append("| File | Title | Source | SIDId | Player | Ver | Subtunes | Instr | "
                 "Patterns | Dangling | .sng bytes | gt2reloc | Flag |")
    lines.append("|---|---|---|---|---|---:|---|---:|---:|---|---:|:-:|---|")
    for r in sorted(ok, key=lambda x: x.path.name.lower()):
        flags = []
        if r.instruments > MAX_INSTRUMENTS:
            flags.append(f"{r.instruments - MAX_INSTRUMENTS} instr dropped")
        if r.voices > 3:
            flags.append("digi channel dropped")
        if r.subtunes_dropped:
            flags.append(f"{r.subtunes_dropped} subtune(s) too long")
        flag = ", ".join(flags)
        subs = str(r.subtunes_emitted)
        if r.subtunes_emitted != r.subtunes:
            subs += f" (hdr {r.subtunes})"
        reloc = {"ok": "y", "fail": "**n**"}.get(r.gt2reloc, "-")
        dang = "-" if not r.dangling else (
            f"**{r.dangling}** (sub0 {r.dangling_sub0})" if r.dangling_sub0
            else str(r.dangling))
        lines.append(
            f"| `{r.path.name}` | {_md_escape(r.name)} | "
            f"{r.source_format or '-'} | {_md_escape(r.sidid)} | "
            f"{VERSION_NAMES.get(r.version, 'unknown')} | {r.version} | {subs} | "
            f"{r.instruments} | {r.patterns} | {dang} | {r.out_size} | "
            f"{reloc} | {flag} |"
        )
    lines.append("")
    lines.append("`Source` is the input file's own header version — the original "
                 "player-file format, distinct from both the Hubbard engine variant "
                 "and the Goattracker output format. "
                 "`Player`/`Ver` are the detected Hubbard player-engine variant and its "
                 "track-read version number. `Subtunes` is how many actually reach the "
                 "`.sng`; where that differs from the PSID header's claim the header "
                 "value follows in brackets, and the gap is subtunes whose orderlist "
                 "pointers resolve outside the file (the track table has no length "
                 "field, so the header routinely over-claims). "
                 "`Dangling` counts distinct orderlist entries naming a pattern the file "
                 "does not have; those references are dropped, so the affected voice "
                 "plays with material missing. **Bold** marks a count that includes "
                 "subtune 0 — a decode fault rather than a phantom subtune (see "
                 "Findings).")
    lines.append("")

    # --- failures ----------------------------------------------------------
    lines.append(f"## Not converted ({len(bad)})")
    lines.append("")
    lines.append("| File | Title | Source | SIDId | Stage | Player | Sub (hdr) | Instr? | Trk? | Pat? | Reason |")
    lines.append("|---|---|---|---|---|---|---:|:-:|:-:|:-:|---|")
    tick = {True: "y", False: "-"}
    for r in sorted(bad, key=lambda x: (x.stage, x.path.name.lower())):
        f = r.found
        cols = (tick[f.get("instr", False)], tick[f.get("tracks", False)],
                tick[f.get("patterns", False)])
        player = VERSION_NAMES.get(r.version, "-") if f.get("version") else "-"
        lines.append(
            f"| `{r.path.name}` | {_md_escape(r.name)} | {r.source_format or '-'} | "
            f"{_md_escape(r.sidid)} | "
            f"{r.stage} | {player} | "
            f"{r.subtunes} | {cols[0]} | {cols[1]} | {cols[2]} | {_md_escape(r.error)} |"
        )
    lines.append("")
    lines.append("`Source` is the input file's own header version; `-` means the "
                 "header was rejected before it could be read. "
                 "`Player` is the detected player variant, or `-` when the "
                 "player-version pass found nothing. `Sub (hdr)` is the PSID header's "
                 "subtune claim — these files produce no `.sng`, so there is no emitted "
                 "count to compare it against.")
    lines.append("")
    lines.append("Columns `Instr?`/`Trk?`/`Pat?` show which of the three table-locating "
                 "detection passes found their target. A file with tables found but no "
                 "`Player` has a recognisable data layout and an unrecognised "
                 "player loop.")
    lines.append("")

    # --- out of scope ------------------------------------------------------
    if out_of_scope:
        lines.append(f"## Out of scope — not a Hubbard player ({len(out_of_scope)})")
        lines.append("")
        lines.append("Rob Hubbard wrote the **music** in these files; someone else "
                     "wrote the **player routine**. H2G rips Hubbard player engines "
                     "by fingerprinting their code, so there is nothing here for it "
                     "to recognise — these are not failures to fix, and no new "
                     "signature would bring them in. They are listed apart from the "
                     "failures for that reason, and excluded from the rate above.")
        lines.append("")
        lines.append("| File | Title | Source | SIDId | Sub (hdr) |")
        lines.append("|---|---|---|---|---:|")
        for r in sorted(out_of_scope, key=lambda x: (x.sidid, x.path.name.lower())):
            lines.append(
                f"| `{r.path.name}` | {_md_escape(r.name)} | {r.source_format or '-'} | "
                f"{_md_escape(r.sidid)} | {r.subtunes} |")
        lines.append("")
        lines.append("Converting these would mean a different tool: a ripper for each "
                     "of those editors, or the emulate-and-capture approach that "
                     "needs no player knowledge at all.")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="survey")
    parser.add_argument("sid_dir", help="directory of .sid files (searched recursively)")
    parser.add_argument("-o", "--output", default="SURVEY.md", help="report path")
    parser.add_argument("--sng-dir", help="also write converted .sng files here")
    parser.add_argument("--sidid-cfg", metavar="PATH",
                        help="SIDId signature database (sidid.cfg). Defaults to $H2G_SIDID_CFG then a known location; the column is left empty if absent")
    parser.add_argument("--format", choices=FORMATS, default=DEFAULT_FORMAT,
                        help="output .sng format (default: %(default)s)")
    parser.add_argument("--dedup-patterns", action="store_true",
                        help="share byte-identical pattern slices")
    parser.add_argument("--prune-patterns", action="store_true",
                        help="drop patterns that no track's orderlist references")
    parser.add_argument("--pack-repeats", action="store_true",
                        help="collapse repeated patterns into REPEAT commands")
    parser.add_argument("--legal-restart", action="store_true",
                        help="rewrite the out-of-range restart position that "
                             "stands in for Hubbard's 'tune ended' marker, "
                             "which greloc.c:244 refuses to export")
    parser.add_argument("--gt2reloc", metavar="PATH", nargs="?", const="",
                        help="also pack every converted .sng back to .sid with "
                             "gt2reloc and report whether it succeeds. Defaults "
                             f"to ${GT2RELOC_ENV} then a known install path")
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
    sidid_db = find_database(args.sidid_cfg)
    if sidid_db is None:
        print("note: sidid.cfg not found; SIDId column will be empty "
              "(set H2G_SIDID_CFG or pass --sidid-cfg)", file=sys.stderr)
    exe = find_gt2reloc(args.gt2reloc or None) if args.gt2reloc is not None else None
    if args.gt2reloc is not None and not exe:
        print("note: gt2reloc not found; the column will be empty "
              f"(set ${GT2RELOC_ENV} or pass --gt2reloc PATH)", file=sys.stderr)
    workdir = tempfile.mkdtemp(prefix="h2g-reloc-") if exe else None

    results = []
    for path in paths:
        try:
            results.append(survey_one(path, sng_dir, args.max_rows,
                                      args.terminate_patterns,
                                      fmt=args.format,
                                      dedup=args.dedup_patterns,
                                      prune=args.prune_patterns,
                                      pack=args.pack_repeats,
                                      legal_restart=args.legal_restart,
                                      sidid_db=sidid_db,
                                      gt2reloc=exe, workdir=workdir))
        except Exception:  # noqa: BLE001 - a crash must not kill the sweep
            r = Result(path=path, stage="crash", error=traceback.format_exc(limit=1))
            results.append(r)

    if workdir:
        shutil.rmtree(workdir, ignore_errors=True)
    Path(args.output).write_text(
        build_report(results, sid_dir, args.max_rows, args.format,
                     args.legal_restart),
        encoding="utf-8")
    ok = sum(1 for r in results if r.ok)
    print(f"{ok}/{len(results)} converted -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
