"""Line-ending guard: snapshot before an edit, compare after.

WHY THIS EXISTS. Line endings in this repo are PER FILE, not per repo:
`python/abpage.py` and `docs/H2G-CONVERSION-METHOD.md` are CRLF, `CLAUDE.md`
and `python/fidelity.py` are LF, and every generated doc is CRLF because a
plain `Path.write_text` on Windows makes it so. CLAUDE.md records this as a
fact to assert BY HAND before every scripted edit -- which works only for as
long as somebody remembers. There is no `.gitattributes`; `core.autocrlf` is
`true`, so git's blob is not a usable baseline (it stores LF and hands back
CRLF), which is why this compares the working file against ITSELF across the
edit rather than against HEAD.

TWO THINGS IT CATCHES, and it is worth being precise because a guard that
overstates its reach is worse than none:

  * A FLIP -- a pure-LF file that comes back pure-CRLF or vice versa. This is
    the whole-file-rewrite failure: `open(p, "w")` without `newline=""`
    translates every line on Windows and the diff then shows every line
    changed, which buries the real edit.
  * A MIX -- a file carrying both endings. Almost always a defect, and there
    is one in the tree right now: `python/tests/test_presets.py` holds 463
    CRLF and 179 bare LF.

WHAT IT DOES NOT CATCH, stated so nobody reads silence as safety: a file
created from scratch has no "before" to compare against, so only the MIX check
applies to it. And a file edited outside Claude Code is invisible here.

It never blocks. A PostToolUse hook fires after the write has already
happened, so blocking would be theatre; it reports on stderr with exit 2,
which is what puts the finding in front of the model that made the edit.
"""
import hashlib
import json
import os
import pathlib
import sys
import tempfile

STATE = pathlib.Path(tempfile.gettempdir()) / "h2g_lineending_snapshots"
WATCH = (".py", ".md", ".json", ".txt", ".ps1", ".c", ".h", ".s", ".inc")


def profile(path: pathlib.Path):
    """(crlf, lone_lf, lone_cr) or None if unreadable."""
    try:
        b = path.read_bytes()
    except OSError:
        return None
    crlf = b.count(b"\r\n")
    return crlf, b.count(b"\n") - crlf, b.count(b"\r") - crlf


def kind(p):
    crlf, lf, _ = p
    if crlf and lf:
        return "MIXED"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    return "EMPTY"


def slot(path: pathlib.Path) -> pathlib.Path:
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / (hashlib.sha1(str(path.resolve()).encode()).hexdigest() + ".json")


def target(data):
    ti = data.get("tool_input") or {}
    for key in ("file_path", "notebook_path", "path"):
        if ti.get(key):
            return pathlib.Path(ti[key])
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:                                          # noqa: BLE001
        return 0                                               # never break the tool
    path = target(data)
    if path is None or path.suffix.lower() not in WATCH:
        return 0

    phase = os.environ.get("H2G_HOOK_PHASE", "post")
    if phase == "pre":
        p = profile(path)
        if p is not None:
            try:
                slot(path).write_text(json.dumps(p))
            except OSError:
                pass
        return 0

    after = profile(path)
    if after is None:
        return 0
    s = slot(path)
    before = None
    if s.exists():
        try:
            before = tuple(json.loads(s.read_text()))
        except (OSError, ValueError):
            before = None
        try:
            s.unlink()
        except OSError:
            pass

    problems = []
    if kind(after) == "MIXED":
        problems.append(
            "MIXED line endings: %d CRLF + %d bare LF. Almost always a defect "
            "-- a partial rewrite that translated some lines and not others."
            % (after[0], after[1]))
    if before is not None and kind(before) != kind(after) and kind(before) != "EMPTY":
        problems.append(
            "line endings FLIPPED %s -> %s across this edit (before %d CRLF / "
            "%d LF, after %d CRLF / %d LF). This repo's endings are per file; "
            "a whole-file rewrite without newline=\"\" translates every line "
            "and buries the real change in the diff."
            % (kind(before), kind(after), before[0], before[1], after[0], after[1]))
    if after[2]:
        problems.append("%d lone CR byte(s) -- neither LF nor CRLF." % after[2])

    if problems:
        sys.stderr.write("LINE-ENDING GUARD on %s\n" % path)
        for p in problems:
            sys.stderr.write("  - %s\n" % p)
        sys.stderr.write("  Re-read the file as bytes and restore its original "
                         "ending before going further.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
