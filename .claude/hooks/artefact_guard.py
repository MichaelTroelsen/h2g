"""Refuse to regenerate a corpus artefact from a tree with uncommitted
converter edits.

WHY. CLAUDE.md: "Regenerate AFTER the tree is coherent and the tests pass,
never while another change is half-applied: a run taken mid-edit records a
state that never existed." And for FIDELITY.md: "never from a working tree
with unrelated edits in `h2g/`". Both rules are prose, and prose is what this
project keeps discovering it did not follow -- `build/fidelity.json` shipped
labelled `64c795b-dirty`, which forced CLAUDE.md's own grading pass to caveat
every figure it re-took from it.

WHAT COUNTS AS DIRTY IS NARROW AND DELIBERATE: only `python/h2g/`, the modules
that decide what the converter emits. Edits to `fidelity.py`, a test, or a doc
do NOT block -- they cannot change the conversion, and blocking on them would
make the guard something people route around. `python/h2g/__init__.py` alone
is ignored too: that is the version stamp, which `bump_version.py` writes as
part of the commit sequence the artefacts are regenerated during.

IT ALSO WARNS, WITHOUT BLOCKING, when the tree is dirty ANYWHERE, because the
artefact stamps itself with `git_label` -- which appends `-dirty` for any
uncommitted change at all, converter or not. That is a provenance problem
rather than a correctness one, so it is said rather than enforced.

ESCAPE HATCH: set H2G_ALLOW_DIRTY_ARTEFACT=1. An intentional override is fine;
what this stops is the accidental one.
"""
import json
import os
import re
import subprocess
import sys

# Derived, never hardcoded. A literal path is wrong in exactly the case this
# repo's own rules create: a concurrent agent works in a git WORKTREE, and a
# hardcoded root would make this guard read the main checkout's tree instead of
# the one the tool call is actually touching -- guarding the wrong files while
# reporting success. `CLAUDE_PROJECT_DIR` is what the harness sets; the
# `__file__` fallback covers a bare `python .claude/hooks/...` invocation.
ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The generators whose output is a measurement of conversion behaviour.
GENERATORS = re.compile(
    r"\b(fidelity\.py|presets\.py|survey\.py|sound_calibrate\.py|"
    r"fidelity_queue\.py|listen\.py)\b")

# Reading is not regenerating: these flags mean "consume an existing run".
READ_ONLY = re.compile(r"--from-json|--baseline|--diagnose|--pace|--help|-h\b")


def dirty(paths):
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--"] + paths,
                             cwd=ROOT, capture_output=True, text=True,
                             timeout=20)
    except Exception:                                          # noqa: BLE001
        return []                                              # never block on a git failure
    return [l for l in out.stdout.splitlines() if l.strip()]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:                                          # noqa: BLE001
        return 0
    if data.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not GENERATORS.search(cmd) or READ_ONLY.search(cmd):
        return 0
    if os.environ.get("H2G_ALLOW_DIRTY_ARTEFACT") == "1":
        return 0

    converter = [l for l in dirty(["python/h2g"])
                 if not l.endswith("python/h2g/__init__.py")]
    if converter:
        sys.stderr.write(
            "ARTEFACT GUARD -- refusing to regenerate from a dirty converter.\n"
            "  python/h2g/ has uncommitted edits, so this run would measure a\n"
            "  tree state that never existed and stamp it as if it had:\n")
        for l in converter:
            sys.stderr.write("    %s\n" % l)
        sys.stderr.write(
            "  Commit or stash the converter change first, then re-run.\n"
            "  Deliberate override: set H2G_ALLOW_DIRTY_ARTEFACT=1.\n")
        return 2

    anywhere = dirty(["."])
    if anywhere:
        sys.stderr.write(
            "note: the converter is clean, so the NUMBERS will be valid -- but "
            "%d other path(s) are uncommitted, so `git_label` will stamp this "
            "artefact `-dirty`. Committing first gives it a real sha.\n"
            % len(anywhere))
    return 0


if __name__ == "__main__":
    sys.exit(main())
