"""Exercise artefact_guard.py from a data file.

Two things are under test, and they are separable:

1. MENTION vs INVOCATION -- a generator name sitting inside a string being
   read or written (grep output, a heredoc composing prose, a graphify query)
   must not block; only `python <path ending in generator.py>` (or a
   launcher `./generator.py`) counts.
2. `approvals.py` is a generator now -- it writes build/approvals.json by
   converting the corpus, exactly like fidelity.py/presets.py/survey.py.

Cases 1-2 run against THIS worktree (clean, real ROOT) since they never reach
the dirty-tree check at all -- no segment invokes a generator, or the tree is
clean so nothing blocks regardless.

Cases 3+ need a controlled dirty/clean `python/h2g`, and they must not dirty
THIS repo's actual python/h2g (out of TOUCHES). So they build a throwaway git
repo shaped like this one (python/h2g/foo.py, committed then edited) and run
the hook with that repo as the process cwd -- which is exactly what
`_find_root()`'s `git rev-parse --show-toplevel` resolves from. A
`CLAUDE_PROJECT_DIR` pointing somewhere else (THIS worktree, which is clean)
is set alongside it: if cwd-resolution is reverted to trusting
`CLAUDE_PROJECT_DIR` instead, the guard would read the wrong (clean) tree and
fail to block a genuinely dirty one.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOK = str(pathlib.Path(__file__).with_name("artefact_guard.py"))
GIT = "git"


def run_hook(cmd, cwd=None, extra_env=None):
    env = dict(os.environ)
    env.pop("H2G_ALLOW_DIRTY_ARTEFACT", None)
    if extra_env:
        env.update(extra_env)
    p = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"tool_name": "Bash",
                                         "tool_input": {"command": cmd}}),
                       capture_output=True, text=True, cwd=cwd, env=env)
    return p.returncode


def sh(args, cwd):
    subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def make_fixture_repo(dirty: bool) -> str:
    """A throwaway repo shaped like this one: python/h2g/foo.py, committed,
    then optionally left with an uncommitted edit to it."""
    d = tempfile.mkdtemp(prefix="ag_fixture_")
    sh([GIT, "init", "-q"], d)
    sh([GIT, "config", "user.email", "t@t"], d)
    sh([GIT, "config", "user.name", "t"], d)
    hdir = os.path.join(d, "python", "h2g")
    os.makedirs(hdir, exist_ok=True)
    foo = os.path.join(hdir, "foo.py")
    with open(foo, "w") as f:
        f.write("x = 1\n")
    sh([GIT, "add", "."], d)
    sh([GIT, "commit", "-q", "-m", "init"], d)
    if dirty:
        with open(foo, "a") as f:
            f.write("y = 2  # uncommitted converter edit\n")
    return d


# Some other, clean directory to set CLAUDE_PROJECT_DIR to, so that a test
# reverting cwd-resolution back to trusting the env var reads the WRONG
# (clean) tree instead of the fixture's dirty one.
CLEAN_ELSEWHERE = str(pathlib.Path(__file__).resolve().parents[2])  # this worktree, clean


# (expected_exit, description, command, cwd_or_None, extra_env_or_None) --
# filled in once the fixture repos exist, since the MENTION cases below only
# distinguish the fix from the bug when run against a DIRTY tree: on a clean
# tree, even the old bare-token-match code returns 0, so the case would pass
# either way and prove nothing.
CASES = []


def matrix():
    bad = 0
    total = 0

    # -- Fixture repos: throwaway, shaped like this one's python/h2g, never
    # this repo's actual python/h2g (out of TOUCHES). --
    dirty_repo = make_fixture_repo(dirty=True)
    clean_repo = make_fixture_repo(dirty=False)
    try:
        de = {"CLAUDE_PROJECT_DIR": CLEAN_ELSEWHERE}  # a DIFFERENT, clean root
        CASES.extend([
            # -- MENTIONS against a DIRTY converter. Must still pass (0): a
            # bare-token match (the bug) would see GENERATORS in the string
            # and block a tree the command never actually reads or writes. --
            (0, "grep mention, dirty tree",
             'grep -c skip python/fidelity.py && grep -o find CLAUDE.md',
             dirty_repo, de),
            (0, "heredoc writing approvals.py that merely CONTAINS 'listen.py', dirty tree",
             "python - <<'PY'\n"
             "data = open('python/approvals.py').read()\n"
             "data = data.replace('x', 'a prose mention of listen.py here')\n"
             "open('python/approvals.py', 'w').write(data)\n"
             "PY", dirty_repo, de),
            (0, "orchestrator heredoc composing JSON that mentions presets.json, dirty tree",
             'cat <<\'JSON\' > record.json\n{"note": "regenerated presets.json earlier"}\nJSON',
             dirty_repo, de),
            (0, "graphify query whose question text contains fidelity.py, dirty tree",
             'graphify query "why does fidelity.py disagree with the median"',
             dirty_repo, de),
            (0, "split-string bypass token, now unnecessary but must still pass",
             'python fideli""ty.py --help', dirty_repo, de),

            # -- INVOCATIONS against a CLEAN fixture converter. Must pass (0). --
            (0, "approvals.py invoked, clean fixture tree",
             'python approvals.py /c -t 180 -o ../build/approvals.json',
             clean_repo, de),
            (0, "fidelity.py --help, read-only flag, dirty fixture tree",
             'python fidelity.py --help', dirty_repo, de),

            # -- INVOCATIONS against a DIRTY fixture converter. Must block (2). --
            (2, "approvals.py invoked against a DIRTY fixture converter "
                "(the DoD's exact miss: approvals.py must now block)",
             'python approvals.py /c -t 180 -o ../build/approvals.json',
             dirty_repo, de),
            (2, "fidelity.py regeneration against a DIRTY fixture converter, "
                "cwd-resolved root (not CLAUDE_PROJECT_DIR, which is clean)",
             'python fidelity.py /c -t 180 --json ../build/fidelity.json',
             dirty_repo, de),
        ])

        for want, desc, cmd, cwd, extra_env in CASES:
            total += 1
            got = run_hook(cmd, cwd=cwd, extra_env=extra_env)
            ok = got == want
            bad += not ok
            print("  %s want=%d got=%d  %s" % ("ok  " if ok else "FAIL", want, got, desc))
    finally:
        import shutil
        shutil.rmtree(dirty_repo, ignore_errors=True)
        shutil.rmtree(clean_repo, ignore_errors=True)

    return total, bad


if __name__ == "__main__":
    total, bad = matrix()
    print("\n%d case(s), %d failure(s)" % (total, bad))
    sys.exit(1 if bad else 0)
