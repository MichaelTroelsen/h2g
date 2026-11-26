"""park_wave: waveform $00 on the silent park (Kings_of_the_Beach_ingame).

The original's `$FE` pattern byte makes the player `JSR` its stop entry
(`$9121 -> $9070`, which stores `$C0` in the flag at `$9443`); the NEXT play
call takes the `$90AB` branch, which runs `LDA #$00 / LDX last / LDY base,X /
STA $D404,Y / DEX / BPL` -- waveform $00 on every voice in one call -- and
the player is then frozen on its pulse/filter tail (`JMP $9336`). The plain
silent park only closes the gate, so each of our voices rings out its release
(11 frames at Kings' SR) against the original's silence: `wave` .9689 with
120 `wave_tail_frames` excused, the 33 charged frames being 11 a voice.

`convert(park_wave=True)` swaps `tracks.WAVE_PARK_PATTERN` in for the park of a
song with `Detection.stop_zeroes_ctrl`.
"""
import json
from pathlib import Path

import pytest

import fidelity as F
from corpus import CORPUS, needs_corpus
from h2g import patterns as P
from h2g.convert import convert
from h2g.detect import STOP_ZEROES_CTRL_SHAPE
from h2g.master_fade import park_end_volume, park_end_wave
from h2g.search import search_file
from h2g.sidfile import load_sid
from h2g.tracks import SILENT_PATTERN, WAVE_PARK_PATTERN
from songview import parse_sng

REPO = Path(__file__).resolve().parents[2]
KINGS = CORPUS / "Kings_of_the_Beach_ingame.sid"


def _opts(name, **extra):
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    return dict(F._preset_opts(doc, name), **extra)


def _parked(patterns_n=5):
    """Two subtunes of three voices, each ending on the silent pattern."""
    patterns = [[0x20, 1, 0, 0] * 12 for _ in range(patterns_n)]
    patterns.append(list(SILENT_PATTERN))
    s = len(patterns) - 1
    tracks = [[0, 1, s, 255, 2] for _ in range(6)]
    return tracks, patterns, s


def _commands(pattern):
    return [pattern[4 * r + 2] for r in range(len(pattern) // 4)]


def test_the_wave_park_writes_the_waveform_on_its_first_free_row_and_again_after_the_pointer_stops():
    cmds = _commands(WAVE_PARK_PATTERN)
    assert cmds[0] == 0                      # row 0's command column is the filter hold's
    assert cmds[1:5] == [P.CMD_SETWAVE, P.CMD_SETPULSEPTR,
                         P.CMD_SETWAVEPTR, P.CMD_SETWAVE]
    assert all(WAVE_PARK_PATTERN[4 * r + 3] == 0 for r in range(5))   # every operand $00
    assert WAVE_PARK_PATTERN[0] == SILENT_PATTERN[0]                   # still a KEYOFF
    assert WAVE_PARK_PATTERN[-4] == P.GT_END_PATTERN


def test_every_parked_voice_is_swapped_to_one_shared_appended_copy():
    """SABOTAGE TARGET: `park_end_wave` returning 0 without writing."""
    tracks, patterns, s = _parked()
    n = len(patterns)
    assert park_end_wave(tracks, patterns) == 6
    assert len(patterns) == n + 1 and patterns[-1] == WAVE_PARK_PATTERN
    assert all(t[2] == n for t in tracks)
    assert patterns[s] == SILENT_PATTERN     # the plain park is intact


def test_nothing_is_written_where_no_park_exists():
    tracks, patterns, s = _parked()
    tracks = [[0, 1, 2, 255, 0] for _ in tracks]
    before = [list(p) for p in patterns]
    assert park_end_wave(tracks, patterns) == 0
    assert patterns == before


def test_no_room_leaves_the_orderlists_alone():
    tracks, patterns, s = _parked()
    while len(patterns) < P.MAX_PATTERNS:
        patterns.append(list(patterns[0]))
    snap = [list(t) for t in tracks]
    logged = []
    assert park_end_wave(tracks, patterns, logged.append) == 0
    assert tracks == snap and "NO ROOM" in logged[0]


def test_the_tune_end_volume_composes_with_the_wave_park():
    """D00 goes on a copy of the pattern the voice parks on: the wave park's
    copy keeps its waveform rows, and the plain park's keeps none."""
    tracks, patterns, s = _parked()
    park_end_wave(tracks, patterns)
    w = tracks[0][2]
    assert park_end_volume(tracks, patterns) == 2
    copy = patterns[tracks[0][2]]
    assert tracks[0][2] != w
    assert copy[2:4] == [P.CMD_SETMASTERVOL, 0]
    assert copy[:2] == WAVE_PARK_PATTERN[:2] and copy[4:] == WAVE_PARK_PATTERN[4:]


@needs_corpus
def test_the_shape_is_the_stop_state_zeroing_block_of_28_files():
    """Static census (2026-11-22): the same 28 files by name, so a spelling
    that stops matching one of them is noticed."""
    hits = {p.stem for p in CORPUS.glob("*.sid")
            if search_file(bytes(load_sid(str(p)).data), STOP_ZEROES_CTRL_SHAPE) > -1}
    assert len(hits) == 28
    assert "Kings_of_the_Beach_ingame" in hits
    assert "Commando" not in hits


@needs_corpus
def test_kings_parks_on_the_wave_pattern_only_when_asked():
    """SABOTAGE TARGET: the `det.stop_zeroes_ctrl` gate in `convert`, or the
    `_mf_park_wave` call itself, removed -- the second assertion fails."""
    off = parse_sng(convert(str(KINGS), log=lambda m: None,
                            **_opts("Kings_of_the_Beach_ingame.sid", park_wave=False)))
    on = parse_sng(convert(str(KINGS), log=lambda m: None,
                           **_opts("Kings_of_the_Beach_ingame.sid", park_wave=True)))
    assert [p for p in off.patterns if p == list(WAVE_PARK_PATTERN)] == []
    assert [p for p in on.patterns if p == list(WAVE_PARK_PATTERN)] != []
    assert on.patterns[-1] == list(WAVE_PARK_PATTERN)     # appended last
    assert len(on.patterns) == len(off.patterns) + 1


@needs_corpus
def test_a_player_without_the_stop_state_block_is_byte_identical():
    """Commando has no such block: the option must not move one byte of it."""
    path = CORPUS / "Commando.sid"
    a = convert(str(path), log=lambda m: None,
                **_opts("Commando.sid", park_wave=False))
    b = convert(str(path), log=lambda m: None,
                **_opts("Commando.sid", park_wave=True))
    assert a == b
