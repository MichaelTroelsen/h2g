"""Refuse `git stash` mutations. Read-only stash subcommands still work.

WHY, and the evidence is in this repo's object store right now.

CLAUDE.md: "NEVER `git stash` in a fan-out. A worktree is not a whole repo, and
`refs/stash` is one of the refs it does not get its own copy of." Two agents
stashed concurrently to snapshot work before an A/B; one `git stash pop`
returned a SIBLING's diff -- a 47-line `goatwriter.py` change belonging to
another task entirely -- and afterwards `git stash list` was empty while
`git fsck --unreachable` showed 100+ dangling stash-shaped commits.

That is not history. Measured at e28179a: `git stash list` is EMPTY and the
object store holds **92 unreachable commits** whose subjects read `WIP on
worktree-...` and `index on worktree-...`, from `wf_09778b63`, `wf_55f332af`
and others. 45 worktree entries are live, so the conditions that produced them
are unchanged.

The failure is silent in BOTH directions, which is what makes it worth a hard
block rather than a warning: the diagnosis from inside one worktree was wrong
about what had been lost, in both directions, and the recovery was luck.

WHAT IS STILL ALLOWED: `git stash list`, `git stash show`. They read.
"""
import json
import os
import re
import subprocess
import sys

# Derived, never hardcoded -- see the note in artefact_guard.py. It matters
# most here: this guard is ABOUT worktrees, and a hardcoded root would have it
# inspect the main checkout's `refs/stash` rather than the worktree whose
# `git stash` it was invoked to refuse.
ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# `git stash` bare, or with any mutating subcommand. `list` and `show` read.
#
# Anchored at a COMMAND BOUNDARY -- start of string, or after ; && || | -- so
# `echo git stash is forbidden` and `grep 'git stash' CLAUDE.md` are not
# matches. Global options are consumed INCLUDING the ones taking a separate
# argument (`-C <path>`, `-c k=v`), because `git -C /x stash clear` is the same
# hazard and slipped an earlier version of this pattern.
#
# Both of those defects were found by TESTING the pattern, not by reading it:
# the first draft blocked an echo and let `git -C` through.
MUTATES = re.compile(
    r"(?:^|[;&|]|\n)\s*(?:\w+=\S+\s+)*"
    r"git(?:\s+(?:-c\s+\S+|-C\s+\S+|--[a-z-]+(?:=\S+)?|-[a-zA-Z]))*"
    r"\s+stash\b(?!\s+(?:list|show)\b)")


def in_worktree() -> bool:
    """A linked worktree is the dangerous case -- refs/stash is shared."""
    try:
        r = subprocess.run(["git", "rev-parse", "--git-common-dir",
                            "--git-dir"], cwd=ROOT, capture_output=True,
                           text=True, timeout=10)
        common, own = (r.stdout.split() + ["", ""])[:2]
        return bool(common and own and os.path.abspath(common)
                    != os.path.abspath(own))
    except Exception:                                          # noqa: BLE001
        return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:                                          # noqa: BLE001
        return 0
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not MUTATES.search(cmd):
        return 0
    if os.environ.get("H2G_ALLOW_STASH") == "1":
        return 0

    sys.stderr.write(
        "STASH GUARD -- refusing `git stash`.\n"
        "  `refs/stash` is NOT per-worktree: it is shared across every worktree\n"
        "  of this repo, and 45 are live. A concurrent stash/pop has already\n"
        "  returned another task's diff here, and 92 unreachable `WIP on\n"
        "  worktree-...` commits are still in the object store from it.\n"
        "  The failure is silent, and the diagnosis from inside one worktree\n"
        "  was wrong in both directions.\n\n"
        "  Snapshot without touching refs/stash instead:\n"
        "    git diff > /path/x.patch     # then `git apply -R` to restore\n"
        "    cp the file somewhere        # simplest for one or two files\n"
        "    a scratch BRANCH             # for anything you mean to keep\n\n"
        "  `git stash list` and `git stash show` are not blocked.\n"
        "  Deliberate override: H2G_ALLOW_STASH=1.\n")
    if in_worktree():
        sys.stderr.write("  NOTE: this shell is inside a LINKED WORKTREE, "
                         "which is the case that lost work before.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
