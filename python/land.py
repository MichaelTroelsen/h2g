#!/usr/bin/env python3
"""Land the working tree per CLAUDE.md "Every commit", as three commits.

    python python/land.py --message-file MSG [--push] [--jobs 12]

MSG holds the first commit's DESCRIPTION on line 1 (the version prefix is
added here, after bump_version has said what the version is), an optional
body, and the attribution trailer as its last line; the trailer is reused on
the other commits. The sequence, each step a gate:

  1. bump_version; full suite (only test_output_sha may fail); commit 1
  2. survey.py + presets.py; full suite (same rule); commit 2
  3. fidelity.py + fidelity_queue.py; tests/test_output_sha.py passes; commit 3
  4. full suite on the committed tree: nothing fails
  5. graphify update (non-fatal); git push when asked

Exit non-zero at the first step that does not hold and leave the tree exactly
as it stands, so a human can read what happened. Never run two at once.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "python"
CORPUS = r"..\..\c64server\SIDM2\SID\Hubbard_Rob"
LOG = ROOT / "build" / "land.log"
# Paths commit 1 may stage NEW files from; modified tracked files come via -u.
NEW_FILE_ROOTS = ["python/h2g", "python/tests", "python/land.py", "docs", "presets.json",
                  ".claude/tasks", ".gitignore"]
NEVER_STAGE = re.compile(r"(^|/)\.playwright-mcp(/|$)")
SUMMARY_RE = re.compile(r"(?:(\d+) failed, )?(\d+) passed")

t0 = time.time()


def say(msg: str) -> None:
    line = f"[land {time.time() - t0:6.0f}s] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    say("$ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                       capture_output=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(r.stdout)
        f.write(r.stderr)
    if check and r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-15:]
        sys.exit(f"FAILED rc={r.returncode}: {' '.join(cmd)}\n" + "\n".join(tail))
    return r


def git(*args: str, check: bool = True) -> str:
    return run(["git", *args], check=check).stdout.strip()


def suite(label: str, allow_output_sha: bool, jobs: int) -> None:
    r = run([sys.executable, "-m", "pytest", "tests/", "-q", "-n", str(jobs), "--dist", "worksteal",
             "-p", "no:cacheprovider"], cwd=PY, check=False)
    out = r.stdout + r.stderr
    m = None
    for line in reversed(out.splitlines()):
        m = SUMMARY_RE.search(line)
        if m:
            break
    if not m:
        sys.exit(f"{label}: no pytest summary line\n" + "\n".join(out.splitlines()[-15:]))
    failed = int(m.group(1) or 0)
    failures = [l for l in out.splitlines() if l.startswith("FAILED ")]
    say(f"{label}: {failed} failed, {m.group(2)} passed")
    if failed == 0:
        return
    if allow_output_sha and all("tests/test_output_sha.py" in l for l in failures):
        n = re.search(r"(\d+) of 89 files disagree", out)
        say(f"{label}: only test_output_sha failed ({n.group(0) if n else 'pre-refresh'}), allowed here")
        return
    sys.exit(f"{label}: unexpected failures\n" + "\n".join(failures[:20]))


def commit(message: str, label: str) -> str:
    staged = git("diff", "--cached", "--name-only").splitlines()
    if not staged:
        sys.exit(f"{label}: nothing staged")
    bad = [p for p in staged if NEVER_STAGE.search(p)]
    if bad:
        sys.exit(f"{label}: refusing to commit {bad}")
    msg = ROOT / "build" / f"land-{label}.msg"
    msg.write_text(message + "\n", encoding="utf-8")
    git("commit", "-q", "-F", str(msg))
    sha = git("rev-parse", "--short", "HEAD")
    say(f"{label}: committed {sha} ({len(staged)} paths)")
    return sha


def presets_summary() -> str:
    old = json.loads(git("show", "HEAD:presets.json"))
    new = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    songs = sorted(k for k in set(old) | set(new)
                   if k.endswith(".sid") and old.get(k) != new.get(k))
    if not songs:
        return "version stamp only"
    only_bytes = all(
        {kk for kk in set(old.get(s, {})) | set(new.get(s, {}))
         if old.get(s, {}).get(kk) != new.get(s, {}).get(kk)} <= {"bytes"}
        for s in songs)
    names = ", ".join(s[:-4] for s in songs)
    return ("packed sizes of " if only_bytes else "entries of ") + names


def main() -> int:
    ap = argparse.ArgumentParser(prog="land")
    ap.add_argument("--message-file", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--corpus", default=CORPUS)
    a = ap.parse_args()

    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    lines = Path(a.message_file).read_text(encoding="utf-8").rstrip("\n").splitlines()
    if not lines or not lines[0].strip():
        sys.exit("message file: line 1 must be the description")
    description = lines[0].strip()
    trailer = lines[-1].strip() if lines[-1].startswith("Co-Authored-By:") else ""
    body = "\n".join(lines[1:-1] if trailer else lines[1:]).strip("\n")

    # Preflight.
    lock = ROOT / ".claude/tasks/serial.lock"
    if lock.exists() and json.loads(lock.read_text(encoding="utf-8") or "[]"):
        sys.exit("preflight: serial.lock holds a record; a runner is mid-task")
    if git("diff", "--cached", "--name-only"):
        sys.exit("preflight: the index already has staged changes; unstage or commit them first")
    if not git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("preflight: no modified tracked files; nothing to land")
    head0 = git("rev-parse", "--short", "HEAD")
    say(f"landing on {head0}: {description}")

    # 1. bump, suite, commit.
    out = run([sys.executable, "python/bump_version.py", description]).stdout
    m = re.search(r"->\s*(\d+\.\d+\.\d+)", out)
    if not m:
        sys.exit("bump_version printed no version: " + out)
    ver = m.group(1)
    suite("suite-1 (pre-commit)", allow_output_sha=True, jobs=a.jobs)
    git("add", "-u")
    git("add", "--", *NEW_FILE_ROOTS)
    msg1 = f"v{ver}: {description}" + (f"\n\n{body}" if body else "") + (f"\n\n{trailer}" if trailer else "")
    c1 = commit(msg1, "c1")

    # 2. SURVEY/presets, suite, commit.
    run([sys.executable, "survey.py", a.corpus, "-o", "../docs/SURVEY.md", "--legal-restart", "--gt2reloc"], cwd=PY)
    run([sys.executable, "presets.py", a.corpus, "-o", "../presets.json"], cwd=PY)
    summary = presets_summary()
    suite("suite-2 (post-presets)", allow_output_sha=True, jobs=a.jobs)
    git("add", "docs/SURVEY.md", "presets.json")
    c2 = commit(f"Regenerate SURVEY/presets at v{ver} ({summary})" + (f"\n\n{trailer}" if trailer else ""), "c2")

    # 3. FIDELITY/QUEUE, output_sha, commit.
    run([sys.executable, "fidelity.py", a.corpus, "-t", "180", "--presets", "../presets.json", "--sound",
         "--jobs", "16", "--census", "../build/onset_census.md", "--hold-census", "../build/hold_census.md",
         "--depth-census", "../build/depth_census.md", "--json", "../build/fidelity.json",
         "-o", "../docs/FIDELITY.md"], cwd=PY)
    run([sys.executable, "fidelity_queue.py", "--from-json", "../build/fidelity.json",
         "-o", "../docs/QUEUE.md", "--json", "../build/queue.json"], cwd=PY)
    # output_sha must now agree, and so must every live figure the docs quote
    # from the artefact (tests/test_claude_md_figures.py reads build/fidelity.json
    # against CLAUDE.md and docs/LESSONS.md): a figure that moved with the
    # refresh is corrected BEFORE the refresh commit, not found by suite-3 after
    # it (measured at v0.5.654: the drift split 80/9 -> 81/8 stopped the landing
    # one commit too late).
    run([sys.executable, "-m", "pytest", "tests/test_output_sha.py",
         "tests/test_claude_md_figures.py", "-q", "-p", "no:cacheprovider"], cwd=PY)
    git("add", "docs/FIDELITY.md", "docs/QUEUE.md")
    c3 = commit(f"Refresh FIDELITY/QUEUE at v{ver} (-t 180 --presets --sound, censuses)"
                + (f"\n\n{trailer}" if trailer else ""), "c3")

    # 4. suite on the committed tree.
    suite("suite-3 (committed tree)", allow_output_sha=False, jobs=a.jobs)

    # 5. graph, push.
    r = run(["graphify", "update"], check=False)
    say("graphify update rc=%d" % r.returncode)
    if a.push:
        git("push", "-q", "origin", "HEAD")
        say("pushed")
    say(f"landed v{ver}: {c1} {c2} {c3}" + (" (pushed)" if a.push else ""))
    print(f"LANDED v{ver} {c1} {c2} {c3}" + (" PUSHED" if a.push else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
