"""Wildcard 6502-opcode byte-pattern search (port of SSearchfile, h2g.frm:1243).

Pattern syntax: space-separated 2-hex-digit byte values, or "??" as a
single-byte wildcard, e.g. "BD ?? ?? 99 02 D4".

Returns the 0-based offset into `data` of the first match, or -1.
"""
from __future__ import annotations


def search_file(data: bytes, pattern: str) -> int:
    tokens = pattern.split()
    values = [None if t == "??" else int(t, 16) for t in tokens]
    n = len(values)
    limit = len(data) - n
    i = 1  # matches VB's SSearchfile, which never tests offset 0
    while i <= limit:
        matched = True
        for ix, val in enumerate(values):
            if val is not None and data[i + ix] != val:
                matched = False
                break
        if matched:
            return i
        i += 1
    return -1
