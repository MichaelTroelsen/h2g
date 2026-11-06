"""master_fade, the tune-end volume (Confuzion `$08B9`).

The original's end routine is `SEI / LDA #$00 / STA $0BEB / STA $D418 / CLI /
JMP`: `$D418` = 0 once, at call 15650 (siddump, PC hook on every `$D418`
store, all 95 files and every subtune, 600 s). Of the files that convert, only
Confuzion has it; Up_up_and_Away has the same idea ending in RTS and is
refused as no Hubbard player. `convert` writes it as `D00` on the silent park,
in a copy of the silent pattern appended after every other pattern.
"""
import json
from pathlib import Path

import pytest

import fidelity as F
from corpus import CORPUS, needs_corpus
from h2g import patterns as P
from h2g.convert import convert
from h2g.detect import TUNE_END_VOLUME_SHAPE
from h2g.master_fade import park_end_volume
from h2g.search import search_file
from h2g.sidfile import load_sid
from h2g.tracks import SILENT_PATTERN
from songview import parse_sng

REPO = Path(__file__).resolve().parents[2]
CONFUZION = CORPUS / "Confuzion.sid"


def _opts(name, **extra):
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    return dict(F._preset_opts(doc, name), **extra)


def _d00_patterns(song):
    return [i for i, pat in enumerate(song.patterns)
            if any(pat[4 * r + 2] == P.CMD_SETMASTERVOL and pat[4 * r + 3] == 0
                   for r in range(len(pat) // 4))]


def _parked(patterns_n=5):
    """Two subtunes of three voices, each ending on the silent pattern that
    `legalise_restarts` appends: [.., S, 255, position of S]."""
    patterns = [[0x20, 1, 0, 0] * 12 for _ in range(patterns_n)]
    patterns.append(list(SILENT_PATTERN))
    s = len(patterns) - 1
    tracks = [[0, 1, s, 255, 2] for _ in range(6)]
    return tracks, patterns, s


def test_the_park_gets_one_d00_copy_on_one_voice_per_subtune():
    """SABOTAGE TARGET: `park_end_volume` returning 0 without writing."""
    tracks, patterns, s = _parked()
    n_before = len(patterns)
    assert park_end_volume(tracks, patterns) == 2
    assert len(patterns) == n_before + 1            # one shared copy, last
    copy = patterns[-1]
    assert copy[2:4] == [P.CMD_SETMASTERVOL, 0]
    assert copy[:2] == SILENT_PATTERN[:2] and copy[4:] == SILENT_PATTERN[4:]
    assert [t[2] for t in tracks] == [n_before, s, s, n_before, s, s]
    assert patterns[s] == SILENT_PATTERN             # the shared park is intact


def test_nothing_is_written_where_no_park_exists():
    tracks, patterns, s = _parked()
    tracks = [[0, 1, 2, 255, 0] for _ in tracks]     # restarts at 0, not parked
    before = [list(p) for p in patterns]
    assert park_end_volume(tracks, patterns) == 0
    assert patterns == before


def test_no_room_leaves_the_orderlists_alone():
    tracks, patterns, s = _parked()
    while len(patterns) < P.MAX_PATTERNS:
        patterns.append(list(patterns[0]))
    snap = [list(t) for t in tracks]
    logged = []
    assert park_end_volume(tracks, patterns, logged.append) == 0
    assert tracks == snap and "NO ROOM" in logged[0]


@needs_corpus
def test_the_shape_is_confuzions_and_up_up_and_aways_alone():
    """Static census of the shape over the corpus (2026-11-06). Up_up_and_Away
    matches `LDA #0 / STA / STA $D418` too but ends in RTS, so the CLI-ending
    shape is Confuzion's alone."""
    hits = {p.name for p in CORPUS.glob("*.sid")
            if search_file(bytes(load_sid(str(p)).data), TUNE_END_VOLUME_SHAPE) > -1}
    assert hits == {"Confuzion.sid"}


@needs_corpus
def test_confuzion_writes_d00_only_in_the_last_pattern_and_only_when_asked():
    """SABOTAGE TARGET: the `det.tune_end_volume` gate in `convert`, or the
    `_mf_park_end` call itself, removed -- the second assertion fails."""
    off = parse_sng(convert(str(CONFUZION), log=lambda m: None,
                            **_opts("Confuzion.sid", master_fade=False)))
    fade = parse_sng(convert(str(CONFUZION), log=lambda m: None,
                             **_opts("Confuzion.sid", master_fade=True)))
    assert _d00_patterns(off) == []
    last = len(fade.patterns) - 1
    assert _d00_patterns(fade) == [last]
    # exactly one voice of the one subtune enters it, as the entry before the
    # restart marker, and the other two still enter the plain silent pattern
    enters = [t[t.index(255) - 1] for t in fade.tracks]
    assert enters.count(last) == 1
    plain = [e for e in enters if e != last]
    assert len(plain) == 2 and plain[0] == plain[1]
    assert fade.patterns[plain[0]][2:4] == [0, 0]
