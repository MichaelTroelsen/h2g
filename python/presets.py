#!/usr/bin/env python3
"""Find the best conversion options for every .sid in a directory.

The converter's output-shaping options are all opt-in, and the right setting is
not the same for every tune: `--max-rows 128` fits some files that 94 cannot,
`--pack-repeats` rescues others from the orderlist limit, and `--prune-patterns`
and `--dedup-patterns` only ever shrink. Rather than pick one compromise for the
whole corpus, this searches the combinations per song and records the winner.

Usage:
    python presets.py <sid_dir> [-o presets.json]

The result feeds back into the converter:
    python -m h2g song.sid --presets presets.json

What "best" means, in priority order:

 1. **Most subtunes that actually play.** An orderlist over Goattracker's
    254-byte limit costs its subtune (see reindex_tracks), and how many are
    lost depends on the options -- so this dominates. A setting that keeps the
    music beats one that saves bytes.
 2. **Most rows actually played.** Rows reached by walking the orderlists, not
    rows stored -- counting storage would punish --prune-patterns for removing
    patterns nothing can reach, and --dedup-patterns for making identical ones
    share.
 3. **Smallest file.** Since (2) is playback, this is a straight tie-break
    between settings carrying identical music, which is what prune and dedup
    are.

Format, tempo, the restart position, slides and effects are not searched:
gts5, `--tempo auto`, `--legal-restart`, `--slides` and `--effects` are simply
correct for anything you intend to open in Goattracker or pack back to a .sid
(the legacy GTS2 importer overruns its pattern array on the portamento
commands this converter emits; an untempo'd file plays at the wrong speed;
greloc.c:244 refuses to export a song whose restart position is out of range,
which is what Hubbard's "tune ended" marker becomes; and `--slides` /
`--effects` fix mis-reads that are gated on detection finding the relevant
routine in the player, a no-op elsewhere). None of them affects whether a
tune converts.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

from h2g import __version__
from h2g.convert import convert
from h2g.goatwriter import FORMAT_GTS5
from h2g.patterns import DEFAULT_TRACK

# Searched per song. Order is irrelevant -- every combination is tried.
MAX_ROWS = (94, 128)
TOGGLES = ("pack", "prune", "dedup")

# Not searched; see the module docstring.
FIXED = {"fmt": FORMAT_GTS5, "tempo": "auto", "legal_restart": True,
         "slides": True, "effects": True}


def _parse(blob: bytes, ntables: int = 4):
    """Tracks and patterns out of a .sng, for scoring."""
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]; pos += 1
        tracks.append(list(blob[pos:pos + n + 1])); pos += n + 1
    ninstr = blob[pos]; pos += 1
    pos += ninstr * 25
    for _ in range(ntables):
        t = blob[pos]; pos += 1; pos += 2 * t
    npatt = blob[pos]; pos += 1
    patterns = []
    for _ in range(npatt):
        rows = blob[pos]; pos += 1
        patterns.append(blob[pos:pos + rows * 4]); pos += rows * 4
    return tracks, patterns


REPEAT, TRANSDOWN, LOOPSONG = 0xD0, 0xE0, 0xFF


def _played_rows(order: list[int], patterns: list[bytes], limit: int = 200000) -> int:
    """Rows an orderlist actually plays, following gplay.c:977-992.

    Counting *stored* rows instead would punish exactly the options that cost
    nothing: --prune-patterns removes patterns no orderlist can reach, and
    --dedup-patterns makes identical ones share, so both shrink the pattern
    table while playing the same music. Measuring playback makes them free,
    which lets the size tie-break pick them up.
    """
    total, ptr, repeat = 0, 0, 0
    while ptr < len(order) and total < limit:
        if order[ptr] == LOOPSONG:
            break
        if TRANSDOWN <= order[ptr] < LOOPSONG:
            ptr += 1
            if ptr >= len(order):
                break
        if REPEAT <= order[ptr] < TRANSDOWN:
            repeat = order[ptr] - REPEAT
            ptr += 1
            if ptr >= len(order):
                break
        num = order[ptr]
        if num < len(patterns):
            total += len(patterns[num]) // 4
        if repeat:
            repeat -= 1
        else:
            ptr += 1
    return total


def _score(blob: bytes) -> tuple[int, int, int]:
    """(playable subtunes, rows played, -bytes) -- bigger is better."""
    tracks, patterns = _parse(blob)
    playable = sum(1 for k in range(0, len(tracks), 3)
                   if any(t != DEFAULT_TRACK for t in tracks[k:k + 3]))
    rows = sum(_played_rows(t, patterns) for t in tracks)
    return playable, rows, -len(blob)


def best_options(sid_path: Path) -> dict | None:
    """Search every combination for one file; None if it never converts."""
    best = None
    for rows in MAX_ROWS:
        for flags in itertools.product((False, True), repeat=len(TOGGLES)):
            opts = dict(zip(TOGGLES, flags), max_rows=rows)
            try:
                blob = convert(str(sid_path), log=lambda m: None, **opts, **FIXED)
            except Exception:  # noqa: BLE001 - a failed combination is just a miss
                continue
            score = _score(blob)
            if best is None or score > best[0]:
                best = (score, opts, len(blob))
    if best is None:
        return None
    score, opts, size = best
    return {
        **{k: opts[k] for k in ("max_rows", *TOGGLES)},
        "bytes": size,
        "subtunes": score[0],
        "rows": score[1],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="presets")
    parser.add_argument("sid_dir", help="directory of .sid files (searched recursively)")
    parser.add_argument("-o", "--output", default="presets.json")
    args = parser.parse_args(argv)

    sid_dir = Path(args.sid_dir)
    if not sid_dir.is_dir():
        print(f"error: not a directory: {sid_dir}", file=sys.stderr)
        return 1

    songs: dict[str, dict] = {}
    paths = sorted(sid_dir.rglob("*.sid"), key=lambda p: p.name.lower())
    for path in paths:
        found = best_options(path)
        if found:
            songs[path.name] = found
        print(f"  {path.name:44} {'-' if not found else found['max_rows']}",
              file=sys.stderr)

    doc = {
        "generator": f"h2g {__version__} presets.py",
        "corpus": str(sid_dir),
        "always": {"format": FIXED["fmt"], "tempo": FIXED["tempo"],
                   # Without this gt2reloc refuses 28 of the 78 outright, so
                   # it belongs with the packing step rather than beside the
                   # searched options.
                   "legal_restart": FIXED["legal_restart"],
                   # The second operand byte of a pitch slide, in the players
                   # that have one; a no-op everywhere else. Correct wherever
                   # it applies, so fixed rather than searched — and emitted
                   # here because fidelity.py reads `always.slides`.
                   "slides": FIXED["slides"],
                   # Same footing as slides: the instrument effect byte's two
                   # decoded bits are gated on detection finding the routine
                   # that reads them, a no-op elsewhere. fidelity.py reads
                   # `always.effects` too.
                   "effects": FIXED["effects"],
                   # The packing step of the conversion. Recorded here rather
                   # than searched: it takes no per-song decision, it just
                   # turns the .sng into something a SID player can play.
                   "gt2reloc": True},
        "criteria": "most playable subtunes, then most rows, then smallest file",
        "songs": songs,
    }
    Path(args.output).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(songs)}/{len(paths)} convertible -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
