"""Refuse a corpus generator invoked without a flag whose absence degrades it
SILENTLY.

The generators in this repo mostly fail loudly. These three do not -- they
produce a plausible artefact that is missing something, which is worse, because
the next reader treats it as a measurement. Each rule below has an instance
that actually happened.

  survey.py without --gt2reloc
      CLAUDE.md: "`--gt2reloc` is what fills the report's pack-back column at
      all -- omit it and the column comes out empty, silently."
  survey.py without --legal-restart
      Without it `greloc.c:244` refuses every tune ending on Hubbard's `$FE`,
      so the column measures the OPTION'S ABSENCE rather than the converter.
  sound_calibrate.py without its positional sid_dir
      Run bare it exits on `error: the following arguments are required:
      sid_dir` and writes NOTHING -- leaving the previous doc on disk, which
      then reads as this run's result. That happened, and the verdict was very
      nearly reported.
  fidelity.py regenerating without --sound, when the artefact HAS aud/loud
      The current `build/fidelity.json` carries `aud` and `loud` on 89 of 95
      rows. A re-run without `--sound` drops both columns -- the ones the
      approvals and calibration machinery read -- and looks like a clean run.
      This one is checked against the artefact rather than hard-coded, so it
      stops applying the day those columns legitimately go away.

Override: H2G_ALLOW_MISSING_FLAG=1.
"""
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(r"C:/Users/mit/claude/h2g")


def artefact_has(col: str) -> bool:
    p = ROOT / "build/fidelity.json"
    if not p.exists():
        return False
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if isinstance(rows, dict):
        rows = rows.get("rows", [])
    return any(r.get(col) is not None for r in rows if isinstance(r, dict))


def positional_after(cmd: str, script: str) -> bool:
    """Is there a non-flag argument after the script name?"""
    m = re.search(re.escape(script) + r"(.*)$", cmd)
    if not m:
        return False
    rest = m.group(1)
    rest = re.sub(r"[|&;>].*$", "", rest)                   # stop at a pipe/redirect
    toks = rest.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("-"):
            # flags that take a value consume the next token
            if t in ("-o", "-t", "-a", "-n", "--json", "--presets", "--output",
                     "--from-json", "--workdir", "--census", "--hold-census",
                     "--baseline", "--shard", "--files", "--gt2reloc",
                     "--siddump", "--sidplayfp", "--sid2wav", "--instrmap"):
                i += 2
                continue
            i += 1
            continue
        return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:                                          # noqa: BLE001
        return 0
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if os.environ.get("H2G_ALLOW_MISSING_FLAG") == "1":
        return 0
    if re.search(r"--help|\s-h\b", cmd):
        return 0

    problems = []

    if re.search(r"\bsurvey\.py\b", cmd):
        if "--gt2reloc" not in cmd:
            problems.append(
                "survey.py without `--gt2reloc`: the pack-back column comes "
                "out EMPTY and says nothing about it.")
        if "--legal-restart" not in cmd:
            problems.append(
                "survey.py without `--legal-restart`: greloc.c:244 refuses "
                "every tune ending on Hubbard's $FE, so the column measures "
                "the option's absence, not the converter.")

    if re.search(r"\bsound_calibrate\.py\b", cmd):
        if not positional_after(cmd, "sound_calibrate.py"):
            problems.append(
                "sound_calibrate.py with no sid_dir: it exits on a required-"
                "argument error and writes NOTHING, leaving the previous "
                "docs/SOUND-CALIBRATION.md on disk to be misread as this "
                "run's result.")

    if re.search(r"\bfidelity\.py\b", cmd) and re.search(r"(-o|--json)\b", cmd):
        if "--sound" not in cmd and artefact_has("aud"):
            problems.append(
                "fidelity.py regenerating without `--sound`, but the current "
                "build/fidelity.json HAS `aud`/`loud`. The re-run would drop "
                "both columns -- which approvals and the sound calibration "
                "read -- and look like a clean result.")

    if not problems:
        return 0
    sys.stderr.write("FLAG GUARD -- a load-bearing flag is missing.\n")
    for p in problems:
        sys.stderr.write("  - %s\n" % p)
    sys.stderr.write("  Deliberate override: H2G_ALLOW_MISSING_FLAG=1.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
