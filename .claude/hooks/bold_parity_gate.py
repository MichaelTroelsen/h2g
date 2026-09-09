"""Run bold_parity on a markdown file after it is edited.

`python/tools/bold_parity.py` was made gate-capable specifically so "a test or
a hook can gate on it" -- that was the task's own verify. Nothing gated on it,
so this closes work already paid for.

Its exit codes: 0 nothing found, 1 an ODD prose `**` count (a real unclosed
bold marker), 2 it could not do its job (bad usage, unreadable file). The
context split is what makes it worth running at all -- a crude count of
`docs/H2G-CONVERSION-METHOD.md` is 2657 (odd) while its PROSE count is 2654
(even), the difference being Python exponentiation inside a code fence.

Scoped to the hand-written docs. GENERATED markdown is excluded deliberately:
its `**` come from a template, a finding there is a bug in the generator rather
than in the file, and flagging it on every regeneration would train everyone to
ignore the hook.

PARITY, NOT ABSOLUTE ODDNESS: some files (docs/LESSONS.md at HEAD) already
carry an odd prose count that predates any edit in this session. Asserting
"prose count is odd -> fire" makes every edit to such a file a false positive,
and the cost isn't just noise -- a reader who sees it fire has to go prove the
odd count predates them, which is exactly the work this gate exists to save.
So the gate compares the edited file's prose parity against the SAME file's
content at HEAD (`git show HEAD:<path>`) and fires only when the edit flipped
the parity (odd<->even), in either direction -- not merely when the current
state is odd. A file not present at HEAD (brand new) has no baseline to diff
against, so there the honest fallback is the absolute check: fire iff the new
file's prose count is odd. Passing silently on a new file would defeat the
gate on the exact files it can most easily still catch.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

# Derived, never hardcoded -- see the note in artefact_guard.py.
ROOT = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR")
                    or pathlib.Path(__file__).resolve().parents[2])
TOOL = ROOT / "python/tools/bold_parity.py"
# Written by survey.py / fidelity.py / fidelity_queue.py / sound_calibrate.py.
GENERATED = {"SURVEY.md", "FIDELITY.md", "QUEUE.md", "SUBTUNES.md",
             "SOUND-CALIBRATION.md", "CHANGELOG.md"}


def _run_tool(path: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), str(path)],
                          capture_output=True, text=True, timeout=60)


def _head_baseline(path: pathlib.Path) -> str | None:
    """Return the file's content at HEAD, or None if it has no HEAD blob
    (a new file that git has never committed) or git itself is unavailable.
    """
    try:
        rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None
    try:
        r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=str(ROOT),
                           capture_output=True, timeout=30)
    except Exception:                                          # noqa: BLE001
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="surrogateescape")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:                                          # noqa: BLE001
        return 0
    ti = data.get("tool_input") or {}
    raw = ti.get("file_path") or ti.get("path")
    if not raw:
        return 0
    path = pathlib.Path(raw)
    if path.suffix.lower() != ".md" or path.name in GENERATED:
        return 0
    if not TOOL.exists() or not path.exists():
        return 0
    try:
        r = _run_tool(str(path))
    except Exception:                                          # noqa: BLE001
        return 0
    if r.returncode == 2:
        sys.stderr.write("BOLD PARITY could not read %s: %s\n"
                         % (path, (r.stderr or "").strip()[:200]))
        return 2
    current_odd = r.returncode == 1

    baseline = _head_baseline(path)
    if baseline is None:
        # No HEAD blob to diff against (new file, or git unavailable) --
        # fall back to the absolute check rather than passing silently.
        if current_odd:
            sys.stderr.write(
                "BOLD PARITY: %s is new (no HEAD baseline) and has an ODD "
                "number of `**` in PROSE -- an unclosed bold marker.\n%s\n"
                % (path.name, (r.stdout or "").strip()))
            return 2
        return 0

    baseline_path = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", suffix=".md", delete=False, encoding="utf-8",
                newline="") as tf:
            tf.write(baseline)
            baseline_path = tf.name
        rb = _run_tool(baseline_path)
    except Exception:                                          # noqa: BLE001
        return 0
    finally:
        if baseline_path:
            try:
                os.unlink(baseline_path)
            except Exception:                                  # noqa: BLE001
                pass
    if rb.returncode == 2:
        # Couldn't even parse the HEAD version -- no reliable baseline,
        # fall back to the absolute check on the current file.
        if current_odd:
            sys.stderr.write(
                "BOLD PARITY: %s -- HEAD baseline unreadable, falling back "
                "to absolute check. ODD `**` in PROSE.\n%s\n"
                % (path.name, (r.stdout or "").strip()))
            return 2
        return 0
    baseline_odd = rb.returncode == 1

    if current_odd != baseline_odd:
        sys.stderr.write(
            "BOLD PARITY: %s -- this edit changed the PROSE `**` parity "
            "(HEAD was %s, now %s). Likely introduced or removed an "
            "unclosed bold marker.\n%s\n"
            % (path.name, "ODD" if baseline_odd else "EVEN",
               "ODD" if current_odd else "EVEN", (r.stdout or "").strip()))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
