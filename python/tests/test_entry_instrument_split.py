"""A pattern entered holding two instruments is copied per instrument.

`_respell_on_clones` (the legato tie clones) settles the instrument a row
plays from the last instrument the pattern names, else from
`_entry_instruments`. A tie before the pattern's first named instrument in a
pattern two orderlist positions enter holding different instruments has no
one base to clone, and was declined "entered with two instruments" -- the
orderlists are already written when the respell runs. Star_Paws (-S2) at
6e467ff + the cycle-3 merge: 158 tie rows on clones, 18 kept CMD_TONEPORTA
(16 entered with two instruments, all in pattern $34 -- reached at voice 1
holding 15 and at voice 4 holding 9 -- and 2 last-row ties whose successor
is that pattern).

`entry_instrument_split` runs in `build_sng` BEFORE the orderlists are
written: each such pattern gets a byte-identical copy per entry instrument
and each orderlist position is repointed at the copy for the instrument it
enters holding, so nothing plays different bytes and every copy is settled.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.goatwriter import note_passes as NP
from h2g.convert import convert

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE, REST, TIE = G.GT_FIRST_NOTE, G.GT_REST, G.CMD_TONEPORTA
END = 0xFF


def _played(tracks, patterns):
    """Every orderlist expanded to the pattern BYTES it plays, in order,
    repeats honoured, transposes and the restart operand skipped."""
    out = []
    for t in tracks:
        seq, repeat, operand = [], 1, False
        for b in t:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            seq += [tuple(patterns[b])] * repeat
            repeat = 1
        out.append(seq)
    return out


def _two_entry_song():
    """Pattern 2 is a tie with no instrument of its own, entered after
    pattern 0 (holding 5) at position 1 and after pattern 1 (holding 6) at
    position 3. The restart (position 0) names 5 again, so the second lap
    enters each position holding what the first did."""
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, TIE, 0, NOTE + 1, 0, TIE, 0, END, 0, 0, 0]]
    tracks = [[0, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    return pats, tracks


def test_a_pattern_entered_with_two_instruments_gets_a_copy_per_instrument():
    pats, tracks = _two_entry_song()
    keep = ([list(p) for p in pats], [list(t) for t in tracks])
    rows = {(2, 0), (2, 1)}
    assert NP._entry_instruments(tracks, pats)[2] == {5, 6}
    new_tracks, new_pats, copies = G.entry_instrument_split(tracks, pats, rows)
    assert copies == {3: 2}
    assert new_pats[3] == pats[2]
    # Instrument 5 is met first and keeps the number; 6's position moves.
    assert new_tracks[0] == [0, 2, 1, 3, END, 0]
    entry = NP._entry_instruments(new_tracks, new_pats)
    assert entry[2] == {5} and entry[3] == {6}
    assert _played(new_tracks, new_pats) == _played(tracks, pats)
    assert (pats, tracks) == keep, "the arguments must not be touched"


def test_the_split_lets_every_tie_take_a_clone():
    pats, tracks = _two_entry_song()
    rows = {(2, 0), (2, 1)}
    _, _, declined = G.legato_tie_clones(pats, rows, tracks, {5, 6}, 7)
    assert declined == rows
    new_tracks, new_pats, _ = G.entry_instrument_split(tracks, pats, rows)
    rows2 = G.legato_tie_rows(new_pats, {p: frozenset()
                                         for p in range(len(new_pats))})
    assert rows2 == rows | {(3, 0), (3, 1)}
    out, clones, declined = G.legato_tie_clones(
        new_pats, rows2, new_tracks, {5, 6}, 7)
    assert declined == set()
    assert clones == [(5, 7), (6, 8)]
    assert [out[2][1], out[2][5]] == [7, 7]
    assert [out[3][1], out[3][5]] == [8, 8]


def test_a_position_entered_with_two_instruments_stays_on_the_source():
    """A repeat of a pattern that names an instrument enters its second
    pass holding that one: the position has no copy to point at, and every
    position that IS settled moves to a copy of its own -- including one
    entered holding an instrument the mixed position also holds."""
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, TIE, 0, NOTE + 1, 7, 0, 0, END, 0, 0, 0]]
    tracks = [[0, 0xD1, 2, 1, 2, 0, 2, END, 0], [0, END, 0], [0, END, 0]]
    at = NP._position_entries(tracks, pats)
    assert at[(0, 2)] == {5, 7} and at[(0, 4)] == {6} and at[(0, 6)] == {5}
    new_tracks, new_pats, copies = G.entry_instrument_split(
        tracks, pats, {(2, 0)})
    assert copies == {3: 2, 4: 2}
    assert new_tracks[0] == [0, 0xD1, 2, 1, 3, 0, 4, END, 0]
    entry = NP._entry_instruments(new_tracks, new_pats)
    assert entry[2] == {5, 7} and entry[3] == {6} and entry[4] == {5}
    assert _played(new_tracks, new_pats) == _played(tracks, pats)


def test_a_row_after_the_first_named_instrument_needs_no_split():
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 4, 0, 0, NOTE + 1, 0, TIE, 0, END, 0, 0, 0]]
    tracks = [[0, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    got = G.entry_instrument_split(tracks, pats, {(2, 1)})
    assert got == (tracks, pats, {})


def test_the_successor_of_a_last_row_tie_is_split():
    """Pattern 3 ends on a tie, so its clone stays latched into pattern 2,
    whose first note must be re-latched to the base -- possible only where
    pattern 2 is entered holding that base alone."""
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, 0, 0, END, 0, 0, 0],
            [NOTE, 5, 0, 0, NOTE + 1, 0, TIE, 0]]
    tracks = [[3, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    rows = {(3, 1)}
    _, _, declined = G.legato_tie_clones(pats, rows, tracks, {5, 6}, 7)
    assert declined == rows
    new_tracks, new_pats, copies = G.entry_instrument_split(tracks, pats, rows)
    assert copies == {4: 2}
    assert new_tracks[0] == [3, 2, 1, 4, END, 0]
    out, _, declined = G.legato_tie_clones(new_pats, rows, new_tracks,
                                           {5, 6}, 7)
    assert declined == set()
    assert out[2][1] == 5 and out[4][1] == 0
    assert _played(new_tracks, new_pats) == _played(tracks, pats)


def test_a_split_past_max_patt_is_not_made():
    pats, tracks = _two_entry_song()
    got = G.entry_instrument_split(tracks, pats, {(2, 0)}, limit=len(pats))
    assert got[2] == {}
    assert got[0] == tracks and got[1] == pats


def test_a_copy_takes_its_sources_bit7_rows():
    """`note_bit7_rows` leaves a copy unknown where two decoded patterns
    share its note column; a split copy is known to be its source's."""
    rows = {0: frozenset({1}), 1: frozenset(), 2: None}
    assert G.split_bit7_rows(dict(rows), {3: 0, 4: 3}) == {
        **rows, 3: frozenset({1}), 4: frozenset({1})}


# --- the corpus ---------------------------------------------------------------

def _preset_convert(name, monkeypatch):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    seen = {}
    real = NP.entry_instrument_split

    def spy(tracks, patterns, rows, **kw):
        got = real(tracks, patterns, rows, **kw)
        seen.setdefault("calls", []).append((tracks, patterns, got))
        return got
    monkeypatch.setattr(NP, "entry_instrument_split", spy)
    lines = []
    convert(str(CORPUS / name), log=lines.append, **F._preset_opts(doc, name))
    return lines, seen.get("calls", [])


@needs_corpus
# Flash_Gordon and Knucklebusters also split for their bit-7 free notes
# (`free_note_split_rows`, tests/test_free_note_entry_split.py): one copy of
# $64 and six of $44/$45 respectively, beside the legato tie's one.
@pytest.mark.parametrize("name,copied", [("Star_Paws.sid", 1),
                                         ("Flash_Gordon.sid", 2),
                                         ("Knucklebusters.sid", 7)])
def test_no_legato_tie_declines_two_entry_instruments(name, copied,
                                                      monkeypatch):
    lines, calls = _preset_convert(name, monkeypatch)
    legato = [ln for ln in lines if ln.startswith("Legato tie") and "on " in ln
              and "legato clone" in ln]
    assert legato, lines
    assert "entered with two instruments" not in legato[0], legato[0]
    assert "successor entered holding another" not in legato[0], legato[0]
    (tracks, patterns, (new_tracks, new_patterns, copies)), = calls
    assert len(copies) == copied
    assert _played(new_tracks, new_patterns) == _played(tracks, patterns)


@needs_corpus
def test_star_paws_respells_every_tie(monkeypatch):
    lines, _ = _preset_convert("Star_Paws.sid", monkeypatch)
    assert "Legato tie..............: 192 tie row(s) on 4 legato clone(s)" \
        in lines, [ln for ln in lines if "Legato" in ln]
