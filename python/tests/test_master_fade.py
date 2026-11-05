"""master_fade: a $D418 volume derived from an orderlist POSITION (Sanxion).

The player's `$B0E6` routine writes volume = $84 - (voice 1's orderlist
position) for the fifteen positions $76..$84, so the tune fades from $E to 0
over its last 46 s. The read is from the player (`detect.find_master_fade`);
the expected levels are the trace of `$D418` against `$B514` (py65 run of
init/play, C:/t/sanxion-aud-dip-330/trace65.out): position $76 -> E ... $84 -> 0.
"""
import contextlib
import io
import json
from pathlib import Path

import pytest

import fidelity as F
from corpus import CORPUS, needs_corpus
from h2g import patterns as P
from h2g.convert import _master_fade_positions, convert
from h2g.detect import detect, find_master_fade
from h2g.sidfile import load_sid

REPO = Path(__file__).resolve().parents[2]
SANXION = CORPUS / "Sanxion.sid"


def _flat(track):
    out, rep = [], 1
    for b in track:
        if b == 0xFF:
            break
        if 0xD0 <= b < 0xE0:
            rep = b - 0xCF
        elif b < 0xD0:
            out += [b] * rep
            rep = 1
    return out


def _sanxion(fade):
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(F._preset_opts(doc, "Sanxion.sid"), master_fade=fade)
    return parse_sng(convert(str(SANXION), log=lambda m: None, **opts))


def _levels(song):
    """{pattern: level} for every row carrying a CMD_SETMASTERVOL."""
    return {p: pat[4 * r + 3]
            for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4) if pat[4 * r + 2] == P.CMD_SETMASTERVOL}


@needs_corpus
def test_the_shape_reads_base_and_voice_from_the_player():
    """SABOTAGE TARGET: returning None, or the wrong voice, from find_master_fade."""
    assert find_master_fade(load_sid(str(SANXION))) == (0x84, 1)


@needs_corpus
def test_no_other_corpus_file_has_the_shape():
    got = {p.stem: find_master_fade(load_sid(str(p)))
           for p in sorted(CORPUS.glob("*.sid"))}
    assert {k: v for k, v in got.items() if v is not None} == {
        "Sanxion": (0x84, 1)}


@needs_corpus
def test_the_option_off_writes_no_volume_command():
    assert _levels(_sanxion(False)) == {}


@needs_corpus
def test_the_fade_steps_down_one_level_per_position():
    """SABOTAGE TARGET: short-circuiting `_apply_orderlist_master_fades` (or
    passing `fades=None`) leaves no D0v, so the first assertion fails."""
    song = _sanxion(True)
    levels = _levels(song)
    assert sorted(levels.values()) == list(range(15))     # E..0, once each
    flat = _flat(song.tracks[1])
    # The 15 fading plays are consecutive, in order, followed by the six
    # plays of the pattern the original ends on (Hubbard positions $85..$8A).
    at = flat.index(next(p for p in flat if p in levels))
    run = flat[at:at + 15]
    assert [levels[p] for p in run] == list(range(14, -1, -1))
    assert len(flat) - (at + 15) == 6 + 1                  # + the silent park
    assert all(p not in levels for p in flat[:at])
    # Voices 0 and 2 carry none: the position is voice 1's.
    for v in (0, 2):
        assert not set(_flat(song.tracks[v])) & set(levels)


@needs_corpus
def test_a_fading_pattern_is_a_copy_of_the_one_it_replaces():
    off, on = _sanxion(False), _sanxion(True)
    levels = _levels(on)
    for p in levels:
        pat = list(on.patterns[p])
        pat[2] = pat[3] = 0
        assert any(list(q) == pat for i, q in enumerate(on.patterns)
                   if i not in levels), "a fade copy matches no ordinary pattern"
    assert len(on.patterns) >= len(off.patterns) + 15
    assert len(on.patterns) <= P.MAX_PATTERNS


def test_positions_are_the_flat_index_and_only_the_last_fifteen():
    track = [5] * 20 + [0xFF, 0xFD]
    marks = _master_fade_positions([[1], list(track), [2]], (18, 1), 0xFE)
    assert marks[0] == {} and marks[2] == {}
    assert marks[1] == {at: 18 - at for at in range(4, 19)}      # 14..0
    assert max(marks[1].values()) == 14 and min(marks[1].values()) == 0


def test_copies_survive_pack_repeats_and_skip_a_taken_command_column():
    pats = [[0x60, 1, 0, 0, 0xBD, 0, 0, 0], [0x60, 1, 0x01, 5, 0xBD, 0, 0, 0]]
    track = [0, 0, 0, 1, 1]
    moved = {i: i for i in range(5)}
    new = list(track)
    n = P._apply_orderlist_master_fades(new, moved, {0: 3, 1: 2, 2: 1, 3: 0,
                                                    4: 9}, pats, {})
    assert n == 3                                  # the two on pattern 1 are taken
    assert new[:3] == [2, 3, 4] and new[3:] == [1, 1]
    assert [pats[i][3] for i in (2, 3, 4)] == [3, 2, 1]
    assert P.pack_repeats(new[:3]) == new[:3]      # distinct: never folded


def test_only_sanxion_ships_the_option():
    import json                                             # noqa: PLC0415
    from pathlib import Path                                # noqa: PLC0415
    import fidelity                                         # noqa: PLC0415
    doc = json.loads((Path(__file__).resolve().parents[2] / "presets.json")
                     .read_text(encoding="utf-8"))
    on = sorted(name for name in doc["songs"]
                if fidelity._preset_opts(doc, name).get("master_fade"))
    assert on == ["Sanxion.sid"]
