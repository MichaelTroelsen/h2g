"""bold_parity_gate must resolve its HEAD baseline from the repo that owns
the edited file, so a git worktree (whose CLAUDE_PROJECT_DIR is the main
checkout) does not fall back to the absolute odd check.

Builds a throwaway repo with a main checkout and a linked worktree; the
committed file has an ODD prose `**` count. An unchanged file must pass in
both; an edit that flips parity must fire in the worktree.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOK = pathlib.Path(__file__).resolve().parent / "bold_parity_gate.py"
REAL_ROOT = HOOK.parents[2]
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def sh(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def run_hook(path, project_dir):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_input": {"file_path": str(path)}}),
        capture_output=True, text=True, env=env, cwd=str(project_dir))


def _fixture(tmp):
    main = pathlib.Path(tmp) / "main"
    main.mkdir()
    # the hook's TOOL lives under CLAUDE_PROJECT_DIR (the main checkout)
    (main / "python/tools").mkdir(parents=True)
    (main / "python/tools/bold_parity.py").write_bytes(
        (REAL_ROOT / "python/tools/bold_parity.py").read_bytes())
    (main / "docs").mkdir()
    (main / "docs/X.md").write_text("one **bold and an unclosed marker **x\n"
                                    "and **odd\n", encoding="utf-8")
    sh(["git", "init", "-q"], main)
    sh(GIT + ["add", "-A"], main)
    sh(GIT + ["commit", "-qm", "c"], main)
    wt = pathlib.Path(tmp) / "wt"
    sh(GIT + ["worktree", "add", "-q", str(wt)], main)
    return main, wt


def test_fixture_file_is_odd():
    with tempfile.TemporaryDirectory() as tmp:
        main, _ = _fixture(tmp)
        tool = main / "python/tools/bold_parity.py"
        r = subprocess.run([sys.executable, str(tool),
                            str(main / "docs/X.md")], capture_output=True)
        assert r.returncode == 1


def test_unchanged_odd_file_passes_in_worktree_and_main():
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = _fixture(tmp)
        assert run_hook(main / "docs/X.md", main).returncode == 0
        r = run_hook(wt / "docs/X.md", main)
        assert r.returncode == 0, r.stderr


def test_parity_flip_fires_in_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        main, wt = _fixture(tmp)
        f = wt / "docs/X.md"
        f.write_text(f.read_text(encoding="utf-8") + "and **more\n",
                     encoding="utf-8")
        r = run_hook(f, main)
        assert r.returncode == 2 and "changed the PROSE" in r.stderr, r.stderr
