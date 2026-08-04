"""SIDId player identification.

Reads the SIDId signature database (`sidid.cfg`, the JC64/Cadaver format also
used by the SIDM2 project) and reports which player engines a SID file matches.

This is independent of `detect.py`. `detect.py` recognises the handful of
Hubbard player variants this converter can actually rip and, crucially, extracts
table addresses from the matched code. SIDId recognises ~1470 player engines by
name only. Running both is useful precisely because they disagree: a file SIDId
calls `Rob_Hubbard` that `detect.py` cannot place is a gap in our signature
chains, and a file SIDId names as something else entirely is one we should not
be converting at all.

Database format
---------------
Blank-line separated entries. The first line is the player name; the remaining
lines are alternative signatures::

    Rob_Hubbard
    BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48 ...
    2C ?? ?? 30 ?? 70 ?? B9 ?? ?? 8D 00 D4 ...

A signature is space-separated 2-hex-digit bytes, `??` for a single-byte
wildcard, and `&&` joining sub-sequences that must *all* be present (order
independent). An entry matches if **any** of its signature lines matches -- the
same "try each known fingerprint" shape `detect.py` uses.

Name lines are told apart from signature lines by content, not position: a line
whose every token is a hex byte, `??` or `&&` is a signature. Position alone is
unreliable because signatures begin with tokens like `BD` and `0A` that look
like names.

Matching is done with compiled `re` patterns over the raw bytes rather than
`search.py`'s byte-at-a-time loop: the database holds a few thousand signatures,
and a pure-Python scan of each against every file is orders of magnitude too
slow.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

_TOKEN = re.compile(r"^(?:[0-9A-Fa-f]{2}|\?\?|&&)$")

# Checked in order; first that exists wins. Override with H2G_SIDID_CFG.
DEFAULT_CFG_PATHS = (
    Path(r"C:\Users\mit\claude\c64server\SIDM2\tools\sidid.cfg"),
)


class SidIdError(Exception):
    pass


@dataclass
class Entry:
    name: str
    # One list per alternative signature; each holds the AND-joined segments.
    alternatives: List[List[re.Pattern]] = field(default_factory=list)

    def matches(self, data: bytes) -> bool:
        return any(all(seg.search(data) for seg in alt) for alt in self.alternatives)


@dataclass
class Database:
    entries: List[Entry]
    path: Path

    def identify(self, data: bytes) -> List[str]:
        return [e.name for e in self.entries if e.matches(data)]


def _is_signature_line(line: str) -> bool:
    tokens = line.split()
    return bool(tokens) and all(_TOKEN.match(t) for t in tokens)


def _compile_segment(tokens: Sequence[str]) -> Optional[re.Pattern]:
    if not tokens:
        return None
    parts = []
    for t in tokens:
        if t == "??":
            parts.append(b".")
        else:
            parts.append(re.escape(bytes([int(t, 16)])))
    # DOTALL so a wildcard also matches 0x0A, which is just another data byte.
    return re.compile(b"".join(parts), re.DOTALL)


def _compile_signature(line: str) -> Optional[List[re.Pattern]]:
    """Split on && into segments that must all be present."""
    segments, current = [], []
    for t in line.split():
        if t == "&&":
            seg = _compile_segment(current)
            if seg is not None:
                segments.append(seg)
            current = []
        else:
            current.append(t)
    seg = _compile_segment(current)
    if seg is not None:
        segments.append(seg)
    return segments or None


def load_database(path: os.PathLike | str | None = None) -> Database:
    if path is None:
        env = os.environ.get("H2G_SIDID_CFG")
        candidates = [Path(env)] if env else list(DEFAULT_CFG_PATHS)
        for c in candidates:
            if c.is_file():
                path = c
                break
        else:
            raise SidIdError(
                "sidid.cfg not found; set H2G_SIDID_CFG to its location")
    path = Path(path)
    if not path.is_file():
        raise SidIdError(f"sidid.cfg not found: {path}")

    entries: List[Entry] = []
    current: Optional[Entry] = None
    for raw in path.read_text(encoding="latin-1").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _is_signature_line(line):
            if current is None:
                continue  # signature before any name; skip rather than guess
            sig = _compile_signature(line)
            if sig:
                current.alternatives.append(sig)
        else:
            current = Entry(name=line)
            entries.append(current)

    # An entry with no signatures can never match; drop it so counts mean
    # "signatures we could actually test".
    entries = [e for e in entries if e.alternatives]
    if not entries:
        raise SidIdError(f"no usable entries parsed from {path}")
    return Database(entries=entries, path=path)


def find_database(path: os.PathLike | str | None = None) -> Optional[Database]:
    """load_database, but None instead of raising when unavailable."""
    try:
        return load_database(path)
    except SidIdError:
        return None
