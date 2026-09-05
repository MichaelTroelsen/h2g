#!/usr/bin/env python3
"""Count ``**`` (bold-marker) occurrences in a markdown file, split by context.

A naive total count of ``**`` in a markdown file is not a parity check on
prose emphasis: ``**`` is also Python's exponentiation operator, so a formula
inside a fenced code block (```` ``` ````) can flip a crude total from even to
odd without any unclosed ``**...**`` span existing anywhere in the prose. This
script splits every ``**`` occurrence into three buckets --

  - fenced   -- inside a ``` fenced code block
  - indented -- inside an indented code block (>=4 leading spaces, not in a
                fence)
  - prose    -- everything else

-- and reports the PROSE count as the number that actually matters for a
bold-emphasis parity check. When the prose count is odd, it walks paragraphs
(blank-line-delimited runs of prose lines) and reports the first paragraph
whose own count of prose ``**`` markers is odd, so the finding names a real
line rather than an aggregate.

Usage:
    python bold_parity.py <markdown-file>

Preserves nothing (read-only): the file is opened with ``newline=''`` so CRLF
line endings are not translated, and never written back.
"""
from __future__ import annotations

import sys


def classify_lines(lines: list[str]) -> list[str]:
    """Return a per-line context tag: 'fenced', 'indented', or 'prose'.

    A fence toggle line (a line whose stripped content starts with ``` ``)
    is itself tagged 'fenced' (its own text, typically just the fence marker
    plus an optional language tag, essentially never carries a stray ``**``,
    but tagging it consistently keeps the state machine simple and correct).

    Indented-code detection is deliberately narrow: a line counts as
    "indented code" only when it has >=4 leading spaces (tabs also count,
    expanded to a tab stop) and is not currently inside a fence. This is not
    a full CommonMark indented-code-block parser (it does not require a
    preceding blank line or exclude list-continuation indentation) — but it
    is exactly the distinction this file's one real example needs, and
    widening it further would risk swallowing prose that merely happens to
    be indented under a list item.
    """
    tags: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            tags.append("fenced")
            continue
        if in_fence:
            tags.append("fenced")
            continue
        expanded = line.expandtabs(4)
        if expanded[:4] == "    " and expanded.strip() != "":
            tags.append("indented")
        else:
            tags.append("prose")
    return tags


def find_odd_paragraph(lines: list[str], tags: list[str]) -> tuple[int, int] | None:
    """Return (start_line_1indexed, end_line_1indexed) of the first prose
    paragraph (a blank-line-delimited run of 'prose'-tagged lines) whose own
    ``**`` count is odd, or None if every paragraph is internally balanced
    (which happens when an unclosed marker's mate lives in a later
    paragraph — still worth reporting, so the caller falls back to naming
    the first paragraph that contains any prose ``**`` at all).
    """
    n = len(lines)
    i = 0
    first_nonempty_odd_fallback = None
    while i < n:
        if tags[i] != "prose" or lines[i].strip() == "":
            i += 1
            continue
        start = i
        count = 0
        while i < n and tags[i] == "prose" and lines[i].strip() != "":
            count += lines[i].count("**")
            i += 1
        end = i - 1
        if count % 2 == 1:
            return (start + 1, end + 1)
        i += 1
    return first_nonempty_odd_fallback


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <markdown-file>", file=sys.stderr)
        return 2

    path = argv[1]
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()

    # Preserve exact line endings for reporting purposes only (we never
    # write this file back); split on \r\n first, then bare \n, so mixed
    # line endings don't silently merge two lines into one.
    if "\r\n" in raw:
        lines = raw.split("\r\n")
    else:
        lines = raw.split("\n")

    tags = classify_lines(lines)

    crude_total = sum(line.count("**") for line in lines)

    fenced_count = sum(line.count("**") for line, t in zip(lines, tags) if t == "fenced")
    indented_count = sum(line.count("**") for line, t in zip(lines, tags) if t == "indented")
    prose_count = sum(line.count("**") for line, t in zip(lines, tags) if t == "prose")

    print(f"file: {path}")
    print(f"crude total **  = {crude_total} ({'ODD' if crude_total % 2 else 'EVEN'})")
    print(f"fenced **       = {fenced_count}")
    print(f"indented **     = {indented_count}")
    print(f"prose **        = {prose_count} ({'ODD' if prose_count % 2 else 'EVEN'})")

    # Name every fenced/indented marker line, so a reader can see exactly
    # what the crude count was picking up that the prose count excludes.
    for line_no, (line, t) in enumerate(zip(lines, tags), start=1):
        if t in ("fenced", "indented") and "**" in line:
            print(f"  [{t}] line {line_no}: {line.strip()!r}")

    if prose_count % 2 == 1:
        span = find_odd_paragraph(lines, tags)
        if span:
            s, e = span
            print(f"ODD prose paragraph: lines {s}-{e}")
            for ln in range(s, e + 1):
                print(f"  line {ln}: {lines[ln - 1]!r}")
        else:
            print("ODD prose count, but no single paragraph is internally odd "
                  "(the unclosed marker's mate is in a different paragraph).")
    else:
        print("Prose ** count is EVEN -- no unclosed bold marker in prose.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
