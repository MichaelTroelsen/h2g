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
"""
import json
import os
import pathlib
import subprocess
import sys

# Derived, never hardcoded -- see the note in artefact_guard.py.
ROOT = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR")
                    or pathlib.Path(__file__).resolve().parents[2])
TOOL = ROOT / "python/tools/bold_parity.py"
# Written by survey.py / fidelity.py / fidelity_queue.py / sound_calibrate.py.
GENERATED = {"SURVEY.md", "FIDELITY.md", "QUEUE.md", "SUBTUNES.md",
             "SOUND-CALIBRATION.md", "CHANGELOG.md"}


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
        r = subprocess.run([sys.executable, str(TOOL), str(path)],
                           capture_output=True, text=True, timeout=60)
    except Exception:                                          # noqa: BLE001
        return 0
    if r.returncode == 1:
        sys.stderr.write(
            "BOLD PARITY: %s has an ODD number of `**` in PROSE -- an unclosed "
            "bold marker.\n%s\n" % (path.name, (r.stdout or "").strip()))
        return 2
    if r.returncode == 2:
        sys.stderr.write("BOLD PARITY could not read %s: %s\n"
                         % (path, (r.stderr or "").strip()[:200]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
