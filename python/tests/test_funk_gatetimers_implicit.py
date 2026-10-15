"""A funk voice that opens on instrument 1 keeps it; the longer subtunes move.

Every voice starts on instrument 1 with no pattern naming it, so a funk voice
opening on rests runs under record 1 and the funk side cannot take a clone.
`funk_gatetimers.split_funk_gatetimers` then splits the other way: record 1
keeps its low gatetimer, and the longer subtunes' NAMED uses of it take a clone
carrying their own. Naming a clone on the funk voice's row 0 instead is not an
option: the orderlist's restart re-enters that pattern, so row 0 would force
the clone on every loop, where the original keeps whatever instrument the voice
ended on (Gerry_the_Germ subtune 2, frame 5194: vibrato depth $001F in the
original, $007D with row 0 naming the clone).

Gerry_the_Germ lost a further 0.3 (subtune 0) and 0.8 (subtune 3) of `gate` to
record 1's low gatetimer; both are back to the no-funk build's figure (base
9c15f95, -t 180, relative A/B).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from test_funk_gatetimers import (END, gt, named, record, sng,  # noqa: E402
                                  ticks_for)

from h2g.funk_gatetimers import split_funk_gatetimers  # noqa: E402
from h2g.goatwriter.appending import _parse_song  # noqa: E402
from h2g.goatwriter.constants import FUNK_ROW_CALLS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROWS = [3, FUNK_ROW_CALLS]
OPEN = [[0x60, 0, 0, 0], [0x60, 0, 0, 0]]            # opens on instrument 1
NAMES_1 = [[0x60, 1, 0, 0]]


def two(p0, p1, n_records=3):
    """subtune 0 (3 calls) plays p0 on all voices, subtune 1 (funk) plays p1."""
    orders = [[0] + END] * 3 + [[1] + END] * 3
    return sng(orders, [p0, p1], [record(1)] * n_records)


def test_the_funk_side_keeps_record_1_and_the_longer_naming_takes_a_clone():
    out = split_funk_gatetimers(two(NAMES_1, OPEN), ROWS, ticks_for)
    song, cols = named(out)
    assert len(song.instruments) == 4
    assert cols == [[4], [0, 0]]
    assert (gt(out, 1), gt(out, 4)) == (1, 2)
    # The clone is record 1's bytes with only the gatetimer changed.
    old = bytes(_parse_song(two(NAMES_1, OPEN)).instruments[0])
    new = bytes(song.instruments[3])
    assert new[:7] == old[:7] and new[8:] == old[8:]


def test_a_shared_pattern_is_copied_for_the_longer_subtune_only():
    # Pattern 0 is played by both subtunes; the funk one also opens on 1
    # through pattern 1 first.
    p = [[0x60, 1, 0, 0], [0x60, 0, 0, 0]]
    blob = sng([[0] + END] * 3 + [[1, 0] + END] * 3, [p, OPEN],
               [record(1)] * 3)
    out = split_funk_gatetimers(blob, ROWS, ticks_for)
    song, cols = named(out)
    assert len(song.patterns) == 3
    assert cols[0] == [1, 0]                       # the funk side still names 1
    assert cols[2] == [4, 0]                       # the longer subtune: clone
    assert song.tracks[0][0] == 2 and song.tracks[3][1] == 0
    assert (gt(out, 1), gt(out, 4)) == (1, 2)


def test_a_pattern_needing_both_directions_gets_a_copy_for_each():
    # p names 1 and 2; both subtunes play it. The funk one opens on 1 through
    # pattern 1, so 1 moves for the longer side and 2 (played in both) moves
    # for the funk side.
    p = [[0x60, 1, 0, 0], [0x60, 2, 0, 0]]
    blob = sng([[0] + END] * 3 + [[1, 0] + END] * 3, [p, [[0x60, 0, 0, 0]]],
               [record(1)] * 3)
    out = split_funk_gatetimers(blob, ROWS, ticks_for)
    song, cols = named(out)
    assert len(song.patterns) == 4
    funk_copy, long_copy = song.tracks[3][1], song.tracks[0][0]
    assert len({0, funk_copy, long_copy}) == 3
    assert cols[funk_copy] == [1, 4]               # 1 kept, 2 -> its low clone
    assert cols[long_copy] == [5, 2]               # 1 -> its raised clone
    assert (gt(out, 1), gt(out, 2), gt(out, 4), gt(out, 5)) == (1, 2, 1, 2)


def test_nothing_moves_when_the_longer_subtunes_only_open_on_it():
    blob = two(OPEN, OPEN)
    assert split_funk_gatetimers(blob, ROWS, ticks_for) == blob


def test_no_longer_subtune_means_no_change():
    blob = two(NAMES_1, OPEN)
    assert split_funk_gatetimers(blob, [FUNK_ROW_CALLS] * 2, ticks_for) == blob


def test_a_record_that_does_not_fit_leaves_the_file_unchanged():
    lines = []
    blob = two(NAMES_1, OPEN, n_records=62)
    out = split_funk_gatetimers(blob, ROWS, ticks_for, lines.append)
    assert out == blob and any("declined" in m for m in lines)


def test_the_log_names_the_clone():
    lines = []
    split_funk_gatetimers(two(NAMES_1, OPEN), ROWS, ticks_for, lines.append)
    assert len(lines) == 1 and "$01->$04" in lines[0], lines


# ---- the corpus -----------------------------------------------------------

FILES = ["Gerry_the_Germ.sid", "Human_Race.sid", "Auf_Wiedersehen_Monty.sid"]


@pytest.fixture(scope="module")
def conversions():
    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((ROOT / "presets.json").read_text())
    out = {}
    for name in FILES:
        lines = []
        blob = convert(str(CORPUS / name), log=lines.append,
                       **F._preset_opts(doc, name))
        out[name] = (blob, lines)
    return out


@needs_corpus
@pytest.mark.parametrize("name", FILES)
def test_the_corpus_funk_files_keep_record_1_low_and_clone_it_for_the_rest(
        conversions, name):
    blob, lines = conversions[name]
    got = [m for m in lines if m.startswith("Funk gatetimers")]
    assert len(got) == 1 and "$01->$" in got[0], got
    song = _parse_song(blob)
    clone = int(got[0].rsplit("$01->$", 1)[1][:2], 16)
    assert song.instruments[0][7] & 0x3F == ticks_for(FUNK_ROW_CALLS)
    assert song.instruments[clone - 1][7] & 0x3F > ticks_for(FUNK_ROW_CALLS)
    # The clone is record 1 with only the gatetimer different.
    a, b = bytes(song.instruments[0]), bytes(song.instruments[clone - 1])
    assert a[:7] == b[:7] and a[8:] == b[8:]
