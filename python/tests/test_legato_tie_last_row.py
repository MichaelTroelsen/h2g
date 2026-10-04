"""A legato tie on a pattern's LAST row is cloned too.

`goatwriter.legato_tie_clones` respells a restarting tie as a plain note on a
legato clone and writes the base instrument back on the next row that would
inherit the clone. A tie on the last row has no next row in its pattern, and
used to decline for that alone (Nineteen 2, Trans-Atlantic Balloon Challenge
2 under presets at 42f3f4a). The clone stays latched across the pattern
boundary (gplay.c:912, player.s:1251 `mt_instr`), so the base now goes on
row 0 of every successor pattern whose first note would inherit it
(`note_passes._successor_relatch`) -- taken only where `_entry_instruments`
settles that successor on exactly the base, so no other way into it hears a
different instrument. The orderlists are already written when the pass runs,
so a successor entered with another instrument declines rather than being
copied, and the log names the reason.

The property every test here checks with `_played` is the one the respelling
exists for: walked in play order, a note plays a legato clone exactly where
a tie was respelled onto it -- never one it inherited.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.convert import convert
from h2g.goatwriter import build as B
from h2g.goatwriter import note_passes as NP

from corpus import CORPUS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60
REST = G.GT_REST
END = 0xFF
TIE = (G.CMD_TONEPORTA, 0x00)


def _pat(*rows):
    out = []
    for r in rows:
        out += list(r)
    return out + [END, 0, 0, 0]


def _played(patterns, tracks):
    """(pattern, row) -> set of instruments latched when that note row is
    fetched, walked over every lapped orderlist from instrument 1
    (gplay.c:62/:223, :912)."""
    got: dict = {}
    for track in NP._lapped_tracks(tracks):
        current, repeat, operand = 1, 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if 0xD0 <= b < 0xFF:
                if b < 0xE0:
                    repeat = b - 0xD0 + 1
                continue
            for _ in range(repeat):
                pat = patterns[b]
                for r in range(len(pat) // 4):
                    if pat[4 * r] == END:
                        break
                    if pat[4 * r + 1]:
                        current = pat[4 * r + 1]
                    if G.GT_FIRST_NOTE <= pat[4 * r] <= G.GT_LAST_NOTE:
                        got.setdefault((b, r), set()).add(current)
            repeat = 1
    return got


def _assert_no_inherited_clone(out, tracks, clones, respelled):
    numbers = {c for _, c in clones}
    for (p, r), instrs in _played(out, tracks).items():
        if (p, r) in respelled:
            assert instrs <= numbers, (p, r, instrs)
        else:
            assert not instrs & numbers, \
                f"pattern {p:02X} row {r} inherits clone {instrs & numbers}"


# --- the successor walk ------------------------------------------------------

def test_successors_follow_repeats_skip_transposes_and_lap_the_restart():
    pats = [_pat((REST, 0, 0, 0))] * 4
    # 0, transpose, 1 x2, 2, loop to position 2 (pattern 1); song 2 ends on 3.
    tracks = [[0x00, 0xE3, 0xD1, 0x01, 0x02, 0xFF, 0x02],
              [0x03, 0x00, 0xFF, 0x05]]          # restart out of range: ends
    assert NP._pattern_successors(tracks, len(pats)) == {
        0: {1}, 1: {1, 2}, 2: {1}, 3: {0}}


# --- the respelling ----------------------------------------------------------

def test_a_last_row_tie_whose_successor_names_its_instrument_is_cloned():
    a = _pat((NOTE, 5, 0, 0), (NOTE + 1, 0, *TIE))
    b = _pat((NOTE + 2, 6, 0, 0), (REST, 0, 0, 0))
    tracks = [[0, 1, 0xFF, 0x00]]
    out, clones, declined = G.legato_tie_clones(
        [a, b], {(0, 1)}, tracks, {5}, 20)
    assert clones == [(5, 20)] and declined == set()
    assert out[0][4:8] == [NOTE + 1, 20, 0, 0]
    assert out[1] == b                           # nothing owed
    _assert_no_inherited_clone(out, tracks, clones, {(0, 1)})


def test_a_last_row_tie_relatches_the_base_on_the_successors_row_0():
    a = _pat((NOTE, 5, 0, 0), (NOTE + 1, 0, *TIE))
    b = _pat((REST, 0, 0, 0), (NOTE + 2, 0, 0, 0))    # would inherit the clone
    c = _pat((REST, 0, 0, 0))                          # names and plays nothing
    d = _pat((NOTE + 3, 0, 0, 0))                      # after c: would inherit
    tracks = [[0, 1, 0, 2, 3, 0xFF, 0x00]]
    out, clones, declined = G.legato_tie_clones(
        [a, b, c, d], {(0, 1)}, tracks, {5}, 20)
    assert clones == [(5, 20)] and declined == set()
    assert out[0][4:8] == [NOTE + 1, 20, 0, 0]
    assert out[1][0:4] == [REST, 5, 0, 0]
    assert out[2][0:4] == [REST, 5, 0, 0]
    assert out[3] == d                                 # c already put it back
    _assert_no_inherited_clone(out, tracks, clones, {(0, 1)})


def test_a_successor_entered_holding_another_instrument_declines():
    a = _pat((NOTE, 5, 0, 0), (NOTE + 1, 0, *TIE))
    b = _pat((NOTE + 2, 0, 0, 0))
    x = _pat((NOTE, 7, 0, 0))
    # b is reached after a (holding 5) and after x (holding 7): writing 5 on
    # its row 0 would change what the x entry hears.
    tracks = [[0, 1, 2, 1, 0xFF, 0x00]]
    lines = []
    out, clones, declined = G.legato_tie_clones(
        [a, b, x], {(0, 1)}, tracks, {5}, 20, log=lines.append)
    assert clones == [] and declined == {(0, 1)}
    assert out == [a, b, x]
    assert any("1 last row, successor entered holding another instrument"
               in line for line in lines), lines


def test_a_successor_that_would_pack_past_the_limit_declines(monkeypatch):
    a = _pat((NOTE, 5, 0, 0), (NOTE + 1, 0, *TIE))
    b = _pat((NOTE + 2, 0, 0, 0))
    tracks = [[0, 1, 0xFF, 0x00]]
    monkeypatch.setattr(NP, "packed_pattern_size",
                        lambda rows: G.PACKED_PATTERN_LIMIT + 1)
    lines = []
    out, clones, declined = G.legato_tie_clones(
        [a, b], {(0, 1)}, tracks, {5}, 20, log=lines.append)
    assert declined == {(0, 1)} and out == [a, b]
    assert any("successor would pack past the limit" in line
               for line in lines), lines


def test_two_instrument_entry_still_declines_and_says_why():
    # The tie's own column is empty and nothing before it names one: the
    # pattern plays 5 from one entry and 7 from the other, and with the
    # orderlists already written it cannot be split per entry.
    p = _pat((NOTE + 1, 0, *TIE), (REST, 0, 0, 0))
    x = _pat((NOTE, 5, 0, 0))
    y = _pat((NOTE, 7, 0, 0))
    tracks = [[1, 0, 2, 0, 0xFF, 0x00]]
    lines = []
    out, clones, declined = G.legato_tie_clones(
        [p, x, y], {(0, 0)}, tracks, {5, 7}, 20, log=lines.append)
    assert declined == {(0, 0)} and out == [p, x, y]
    assert any("1 entered with two instruments" in line for line in lines), \
        lines


# --- the corpus ----------------------------------------------------------------

def _preset_opts(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, name)


@pytest.mark.parametrize("name", ["Nineteen.sid",
                                  "Trans-Atlantic_Balloon_Challenge.sid"])
def test_the_corpus_last_row_ties_are_cloned_and_no_note_inherits_one(
        name, monkeypatch):
    if not (CORPUS / name).is_file():
        pytest.skip("corpus absent")
    seen = []
    real = B.legato_tie_clones

    def spy(patterns, rows, tracks, *a, **k):
        res = real(patterns, rows, tracks, *a, **k)
        seen.append((patterns, rows, tracks, res))
        return res

    monkeypatch.setattr(B, "legato_tie_clones", spy)
    convert(str(CORPUS / name), log=lambda s: None, **_preset_opts(name))
    assert len(seen) == 1
    patterns, rows, tracks, (out, clones, declined) = seen[0]
    last_row = {(p, r) for p, r in rows
                if patterns[p][4 * r + 4] == END}
    assert len(last_row) == 2, last_row          # 42f3f4a: 2 in each file
    assert declined == set()
    for p, r in last_row:
        assert out[p][4 * r + 1] in {c for _, c in clones}
        assert out[p][4 * r + 2:4 * r + 4] == [0, 0]
    _assert_no_inherited_clone(out, tracks, clones, rows - declined)
