#!/usr/bin/env python3
"""Bump the patch version and prepend a CHANGELOG entry.

Usage:
    python python/bump_version.py "short description"
    python python/bump_version.py --minor "short description"

The single source of truth is __version__ in python/h2g/__init__.py; this
script rewrites that line and adds a matching CHANGELOG.md section. Run it as
part of every commit (see CLAUDE.md).
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_PY = REPO_ROOT / "python" / "h2g" / "__init__.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

VERSION_RE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bump_version")
    parser.add_argument("description", help="one-line changelog entry")
    parser.add_argument("--minor", action="store_true",
                        help="bump minor and reset patch instead of bumping patch")
    args = parser.parse_args(argv)

    source = INIT_PY.read_text(encoding="utf-8")
    match = VERSION_RE.search(source)
    if not match:
        print(f"error: no __version__ found in {INIT_PY}", file=sys.stderr)
        return 1

    major, minor, patch = (int(g) for g in match.groups())
    old = f"{major}.{minor}.{patch}"
    if args.minor:
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new = f"{major}.{minor}.{patch}"

    INIT_PY.write_text(
        VERSION_RE.sub(f'__version__ = "{new}"', source, count=1), encoding="utf-8"
    )

    today = datetime.date.today().isoformat()
    entry = f"## {new} — {today}\n\n- {args.description}\n\n"
    text = CHANGELOG.read_text(encoding="utf-8")
    marker = "\n## "
    idx = text.find(marker)
    if idx == -1:
        text = text.rstrip() + "\n\n" + entry
    else:
        text = text[:idx + 1] + entry + text[idx + 1:]
    CHANGELOG.write_text(text, encoding="utf-8")

    print(f"{old} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
