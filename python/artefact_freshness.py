"""Is `build/fidelity.json` stale, and why.

CLAUDE.md: "A score is either historical ... or live, and someone has
re-checked it and says so." Checking that by hand means remembering a
`git diff --name-only <label>..HEAD -- python/h2g/` incantation and eyeballing
the result -- and eyeballing it wrong is exactly how a pure version bump
(v0.5.475 -> v0.5.478, __init__.py only) gets misreported as a stale corpus
artefact demanding a ~25-minute regeneration for nothing.

THE PREDICATE IS EMISSION-CHANGING COMMITS, NOT COMMITS. Three things make the
artefact stale relative to HEAD:

  1. A committed change under `python/h2g/` other than `__init__.py` (the
     version stamp `bump_version.py` writes on every commit, whether or not
     conversion behaviour moved).
  2. The working tree being dirty under `python/h2g/` right now -- a dirty
     emitter invalidates any regeneration just as much as a committed change
     would, so it is checked even though it is not "a commit" at all.
  3. Nothing outside `python/h2g/` counts, however large the diff -- a
     docs-only or harness-only commit cannot have changed what the converter
     emits.

`check_freshness()` is the whole rule and is pure: it takes the already-listed
changed and dirty paths and returns a verdict, so the tests below drive it
without invoking git at all. `main()` is the only part that shells out, and it
always passes `-C <root>` / `cwd=` -- never relies on the process's cwd
(CLAUDE.md: a `git diff --stat` run from the wrong directory once printed an
empty diffstat, which reads exactly like "nothing changed").
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

H2G_PREFIX = "python/h2g/"
INIT_FILE = "python/h2g/__init__.py"
DIRTY_SUFFIX = "-dirty"

# THE ASYMMETRY (measured at c2cb76a): a docstring-only edit to
# python/h2g/tracks.py -- 36 changed lines, 0 of them code -- makes this tool
# report STALE, while tests/test_commando.py (the byte-exact fixture) still
# passes: no emitted byte moved. This tool keys on PATHS, which can only ever
# answer "did a file under python/h2g/ change", never "did an emitted byte
# change" -- only the corpus byte-hash (or the fixture) can answer that, and
# that is the expensive check this tool exists to let you skip.
#
# So the two verdicts are NOT equally certain:
#   NOT STALE -- exact.    No file under python/h2g/ moved, so no emitted
#                           byte can have moved either. Trust it outright.
#   STALE     -- an upper bound only. A file under python/h2g/ moved, which
#                           MAY or may not have changed a byte. Confirm with
#                           the corpus byte-hash check, or with
#                           tests/test_commando.py, before believing bytes
#                           actually moved -- or regenerating on the strength
#                           of this verdict alone.
UPPER_BOUND_NOTE = (
    "STALE is a CONSERVATIVE UPPER BOUND, not a certainty: a file under "
    "python/h2g/ changed, but that does not prove any emitted byte moved "
    "(a comment or docstring edit changes no output -- measured at "
    "c2cb76a). Confirm with the corpus byte-hash check, or with "
    "tests/test_commando.py (the byte-exact fixture), before trusting this "
    "verdict as more than 'go check' -- or call check_freshness(..., "
    "confirmed_unchanged=True) once you already have."
)
EXACT_GUARANTEE_NOTE = (
    "NOT STALE is exact, not a guess: no file under python/h2g/ changed, "
    "so no emitted byte can have changed. This verdict needs no further "
    "confirmation."
)
# Why this override exists, and why it is opt-in rather than a heuristic:
# check_freshness cannot itself tell a docstring edit from a code edit --
# doing so from the diff would trade a sound bound for a guess (CLAUDE.md:
# "do not add a heuristic that tries to tell a docstring edit from a code
# edit and downgrade the verdict on its own"). The only trustworthy source
# for "no byte actually moved despite a path changing" is a check this
# module does NOT run itself (the corpus byte-hash, or
# tests/test_commando.py) -- so the downgrade is only ever offered to a
# caller who states, explicitly, that they already ran one of those and it
# came back clean. The override never fires on its own.
OVERRIDE_NOTE = (
    "override: confirmed_unchanged=True -- caller states the corpus "
    "byte-hash check (or tests/test_commando.py) already showed no emitted "
    "byte moved, so this STALE upper bound is downgraded to NOT STALE. "
    "This is a caller-asserted fact that check_freshness cannot verify "
    "itself -- it does not re-run either check."
)


@dataclass
class FreshnessResult:
    stale: bool
    reasons: list = field(default_factory=list)
    emission_changed: list = field(default_factory=list)
    version_only_changed: list = field(default_factory=list)
    dirty_emitter_files: list = field(default_factory=list)
    overridden: bool = False


def check_freshness(changed_files, dirty_files, confirmed_unchanged=False):
    """Pure verdict. No git call here -- both arguments are plain path lists.

    changed_files: paths that differ between the artefact's commit and HEAD,
        REPO-WIDE (e.g. `git diff --name-only <label>..HEAD` with no
        pathspec). The function itself does the python/h2g/ scoping -- that
        scoping is part of the rule under test, not a precondition of it.
    dirty_files: paths currently uncommitted in the working tree, also
        repo-wide (e.g. `git status --porcelain` with no pathspec).
    confirmed_unchanged: explicit, caller-driven override. Pass True only
        when the caller has ALREADY confirmed -- via the corpus byte-hash
        check, or tests/test_commando.py -- that no emitted byte actually
        moved despite a python/h2g/ path changing. Downgrades an otherwise-
        STALE verdict to NOT STALE and records that it did so
        (result.overridden). Never inferred; always caller-asserted. See
        OVERRIDE_NOTE for why this is opt-in rather than a heuristic.
    """
    h2g_changed = sorted(p for p in changed_files if p.startswith(H2G_PREFIX))
    emission_changed = sorted(p for p in h2g_changed if p != INIT_FILE)
    version_only_changed = sorted(p for p in h2g_changed if p == INIT_FILE)

    h2g_dirty = sorted(p for p in dirty_files if p.startswith(H2G_PREFIX))
    dirty_emitter_files = sorted(p for p in h2g_dirty if p != INIT_FILE)
    dirty_version_only = sorted(p for p in h2g_dirty if p == INIT_FILE)

    reasons = []
    stale = False

    if emission_changed:
        stale = True
        reasons.append(
            "emission-changing commit(s) touched python/h2g/: "
            + ", ".join(emission_changed))
    elif version_only_changed:
        reasons.append(
            "only __init__.py changed under python/h2g/ since the artefact's "
            "commit (%s) -- a version bump, not emission-changing"
            % ", ".join(version_only_changed))
    else:
        reasons.append(
            "no committed changes under python/h2g/ since the artefact's commit")

    if dirty_emitter_files:
        stale = True
        reasons.append(
            "working tree is dirty under python/h2g/: "
            + ", ".join(dirty_emitter_files))
    elif dirty_version_only:
        reasons.append(
            "only __init__.py is dirty under python/h2g/ (%s) -- a version "
            "bump, not emission-changing" % ", ".join(dirty_version_only))
    else:
        reasons.append("working tree is clean under python/h2g/")

    overridden = False
    if stale and confirmed_unchanged:
        stale = False
        overridden = True
        reasons.append(OVERRIDE_NOTE)

    # EXACT_GUARANTEE_NOTE claims "no file under python/h2g/ changed" -- true
    # only when nothing was ever stale. An overridden verdict DID have a path
    # change (that's what was overridden), so it gets OVERRIDE_NOTE above and
    # nothing more: printing EXACT_GUARANTEE_NOTE on top would put a false
    # claim next to a true one.
    if stale:
        reasons.append(UPPER_BOUND_NOTE)
    elif not overridden:
        reasons.append(EXACT_GUARANTEE_NOTE)

    return FreshnessResult(
        stale=stale,
        reasons=reasons,
        emission_changed=emission_changed,
        version_only_changed=version_only_changed,
        dirty_emitter_files=dirty_emitter_files,
        overridden=overridden,
    )


def parse_label(label):
    """('665939c-dirty', True) or ('20bc88d', False). Pure string parsing."""
    if label.endswith(DIRTY_SUFFIX):
        return label[: -len(DIRTY_SUFFIX)], True
    return label, False


def artefact_commit_from_rows(rows):
    """The single commit `build/fidelity.json`'s rows were built at.

    Raises ValueError if the rows disagree or none carry a label -- that is a
    finding in itself (the artefact was not built at one coherent commit),
    not something to silently pick a majority for.
    """
    labels = {r.get("label") for r in rows if r.get("label")}
    if not labels:
        raise ValueError("no row in build/fidelity.json carries a 'label'")
    if len(labels) > 1:
        raise ValueError(
            "build/fidelity.json rows disagree on label: %s -- it was not "
            "built at one commit" % ", ".join(sorted(labels)))
    return parse_label(labels.pop())


def _repo_root():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return env
    # python/artefact_freshness.py -> repo root is the parent of python/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(root, *args):
    out = subprocess.run(
        ["git", "-C", root] + list(args),
        capture_output=True, text=True, check=True)
    return out.stdout


def _git_diff_names(root, a, b):
    return [l for l in _git(root, "diff", "--name-only", "%s..%s" % (a, b)).splitlines()
            if l.strip()]


def _git_status_names(root):
    names = []
    for line in _git(root, "status", "--porcelain").splitlines():
        if not line.strip():
            continue
        name = line[3:]
        if " -> " in name:  # rename: "old -> new"
            name = name.split(" -> ", 1)[1]
        names.append(name)
    return names


def _git_head(root):
    return _git(root, "rev-parse", "HEAD").strip()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Explicit, caller-driven override (see check_freshness's docstring and
    # OVERRIDE_NOTE): only a caller who has ALREADY run the corpus byte-hash
    # check or tests/test_commando.py and confirmed no byte moved should
    # pass this. It is never inferred from the diff.
    confirmed_unchanged = "--confirmed-unchanged" in argv

    root = _repo_root()
    fidelity_path = os.path.join(root, "build", "fidelity.json")

    try:
        with open(fidelity_path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        print("cannot read %s: %s" % (fidelity_path, exc), file=sys.stderr)
        return 2

    rows = data if isinstance(data, list) else data.get("rows", [])
    try:
        commit, artefact_was_dirty = artefact_commit_from_rows(rows)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    head = _git_head(root)
    changed = _git_diff_names(root, commit, head)
    dirty = _git_status_names(root)

    result = check_freshness(changed, dirty, confirmed_unchanged=confirmed_unchanged)

    print("build/fidelity.json built at %s%s, HEAD is %s"
          % (commit, " (tree was dirty at build time)" if artefact_was_dirty else "", head))
    if artefact_was_dirty:
        print("note: the artefact's own commit is approximate -- it was built "
              "from a dirty tree, so this diff is against the nearest commit, "
              "not the exact tree measured.")
    for reason in result.reasons:
        print("  - " + reason)
    # Never print a bare verdict: STALE is a conservative upper bound (an
    # emitter path changed; may or may not have changed emitted bytes) and
    # NOT STALE is exact (no emitter path changed, so no byte can have
    # changed). The asymmetry is real and the wording must say so every time.
    if result.stale:
        print("STALE (upper bound -- unconfirmed; see note above. Pass "
              "--confirmed-unchanged once the corpus byte-hash check or "
              "tests/test_commando.py has confirmed no byte moved.)")
    elif result.overridden:
        print("NOT STALE (downgraded from STALE by --confirmed-unchanged; "
              "see override note above)")
    else:
        print("NOT STALE (exact)")

    return 1 if result.stale else 0


if __name__ == "__main__":
    sys.exit(main())
