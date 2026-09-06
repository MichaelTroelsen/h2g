"""Group the worktrees so a human is asked only about the few holding unique work.

Read-only: reports, changes nothing, deletes nothing.

WHY IT GROUPS RATHER THAN LISTS. The open task asks for "a decision per
worktree: land the work, discard it, or leave it" over 44 of them. That is not
one sitting's question, and CLAUDE.md's warning applies -- "none of this should
be recovered by guesswork" -- so the first pass must be mechanical.

TWO MEASUREMENT TRAPS, both hit while writing this, both worth stating because
the obvious version of each is wrong:

  * `git rev-list master..HEAD` COUNTS the divergence, not the work. These
    branches were cut from an old master, so it reports "147 files changed,
    40980 deletions" for a branch whose actual contribution is one commit.
    `git cherry` is the right instrument: it compares PATCHES, marking `-` for
    a change already upstream and `+` for one that is not. A branch whose
    commits are all `-` has landed, however different its shas look.
  * "has uncommitted changes" is not the same as "holds work". A worktree dirty
    only in `runs.jsonl`, `whats-next.md` or `build/` holds session noise. One
    dirty in `python/h2g/` holds something only it has. Splitting those is the
    difference between a triage that narrows and one that re-lists.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(r"C:/Users/mit/claude/h2g")

# Paths that are session bookkeeping rather than work worth a decision.
NOISE = re.compile(r"^(\.claude/tasks/|build/|whats-next\.md|todo\.md|"
                   r"graphify-out/|docs/(FIDELITY|QUEUE|SURVEY|CHANGELOG)\.md)")


def git(*a, cwd=ROOT):
    try:
        return subprocess.run(["git"] + list(a), cwd=str(cwd),
                              capture_output=True, text=True,
                              timeout=45).stdout.strip()
    except Exception:                                          # noqa: BLE001
        return ""


def worktrees():
    out, cur = [], {}
    for line in git("worktree", "list", "--porcelain").splitlines():
        if not line.strip():
            if cur:
                out.append(cur)
                cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    if cur:
        out.append(cur)
    return out


def main() -> int:
    wts = worktrees()
    if len(wts) < 2:
        print("no linked worktrees")
        return 0

    rows = []
    for w in wts[1:]:
        p = pathlib.Path(w.get("worktree", ""))
        branch = (w.get("branch") or "").replace("refs/heads/", "") or "(detached)"
        if not p.exists():
            rows.append(("GONE", p, branch, "path missing", []))
            continue

        status = [l for l in git("status", "--porcelain", cwd=p).splitlines()
                  if l.strip()]
        # porcelain is TWO status columns then the path; slicing at 3 ate the
        # first character of every path ("ython/h2g/goatwriter.py").
        paths = [l[2:].strip() for l in status]
        real = [x for x in paths if not NOISE.match(x)]

        # PATCH-equivalence, not commit count: `-` means already upstream.
        unique = []
        if w.get("HEAD"):
            for line in git("cherry", "master", w["HEAD"], cwd=p).splitlines():
                if line.startswith("+"):
                    unique.append(line.split()[-1])

        if real:
            rows.append(("WORK", p, branch,
                         "%d source path(s) uncommitted%s"
                         % (len(real), ", %d unlanded commit(s)" % len(unique)
                            if unique else ""), real[:4]))
        elif unique:
            subj = [git("log", "-1", "--format=%s", c, cwd=p)[:58]
                    for c in unique[:2]]
            rows.append(("WORK", p, branch,
                         "%d unlanded commit(s)" % len(unique), subj))
        elif paths:
            rows.append(("NOISE", p, branch,
                         "%d path(s), all bookkeeping" % len(paths), paths[:3]))
        else:
            rows.append(("EMPTY", p, branch, "clean, nothing unlanded", []))

    print("%d linked worktree(s)\n" % (len(wts) - 1))
    for bucket, head in (("WORK", "HOLDS WORK -- needs a decision"),
                         ("NOISE", "BOOKKEEPING ONLY -- prunable, nothing lost"),
                         ("EMPTY", "EMPTY -- prunable"),
                         ("GONE", "PATH MISSING -- `git worktree prune`")):
        sel = [r for r in rows if r[0] == bucket]
        if not sel:
            continue
        print("%s (%d)" % (head, len(sel)))
        for _, p, branch, why, detail in sel:
            print("   %-38s %s" % (p.name, why))
            for d in detail:
                print("        %s" % d)
        print()

    work = sum(1 for r in rows if r[0] == "WORK")
    prunable = sum(1 for r in rows if r[0] in ("NOISE", "EMPTY", "GONE"))
    print("A HUMAN IS NEEDED FOR %d of %d; %d are prunable with nothing lost."
          % (work, len(rows), prunable))
    if work:
        print("  Recover with `git diff > x.patch` or a scratch branch -- "
              "NEVER `git stash`: it is shared across worktrees and has "
              "already returned another task's diff in this repo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
