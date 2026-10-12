"""Under tie_restart a two-entry pattern is split only for HEARD restarts.

`entry_instrument_split` copies a pattern per entry instrument so its tie rows
settle. In the classic restart family (`tie_restart`) a settled tie whose
restart writes what the voice already holds stays CMD_TONEPORTA
(`_restart_heard`), so a copy made for such rows buys nothing and costs a
pattern: Action_Biker at max_rows 94 (the 6e467ff figure; presets raise it to
128 since v0.5.514) carried one copy of pattern $12 whose rows all ended
quiet. `build_sng` rebuilds without those copies (`_heard_splits`,
`_RetrySplit`).
"""
import json
import pathlib

from h2g import goatwriter as G
from h2g.goatwriter import build as GB
from h2g.convert import convert

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE, TIE, END = G.GT_FIRST_NOTE, G.CMD_TONEPORTA, 0xFF


def _song():
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, TIE, 0, NOTE + 1, 0, TIE, 0, END, 0, 0, 0]]
    tracks = [[0, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    rows = {(2, 0), (2, 1)}
    return pats, tracks, rows


def test_a_copy_with_a_heard_row_is_kept():
    pats, tracks, rows = _song()
    nt, np_, copies = G.entry_instrument_split(tracks, pats, rows)
    assert copies == {3: 2}
    assert GB._heard_splits({(3, 0)}, rows, copies, nt, np_) == {2}
    assert GB._heard_splits({(2, 1)}, rows, copies, nt, np_) == {2}


def test_a_copy_whose_rows_are_all_quiet_is_dropped():
    pats, tracks, rows = _song()
    nt, np_, copies = G.entry_instrument_split(tracks, pats, rows)
    assert GB._heard_splits(set(), rows, copies, nt, np_) == set()
    # a heard row that was never a split candidate does not keep it
    assert GB._heard_splits({(0, 0)}, rows, copies, nt, np_) == set()


def test_only_restricts_the_patterns_copied():
    pats, tracks, rows = _song()
    assert G.entry_instrument_split(tracks, pats, rows,
                                    only=frozenset())[2] == {}
    assert G.entry_instrument_split(tracks, pats, rows,
                                    only=frozenset({2}))[2] == {3: 2}


def test_a_heard_last_row_keeps_its_successors_copy():
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, 0, 0, END, 0, 0, 0],
            [NOTE, 5, 0, 0, NOTE + 1, 0, TIE, 0]]
    tracks = [[3, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    rows = {(3, 1)}
    nt, np_, copies = G.entry_instrument_split(tracks, pats, rows)
    assert copies == {4: 2}
    assert GB._heard_splits({(3, 1)}, rows, copies, nt, np_) == {2}
    assert GB._heard_splits(set(), rows, copies, nt, np_) == set()


def _convert(name, **over):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = dict(fidelity._preset_opts(doc, name), **over)
    lines = []
    out = convert(str(CORPUS / name), log=lines.append, **opts)
    return lines, out


@needs_corpus
def test_action_biker_quiet_copy_is_gone_at_max_rows_94():
    lines, _ = _convert("Action_Biker.sid", max_rows=94, tie_restart=True)
    assert not [ln for ln in lines if "Entry instrument" in ln]


@needs_corpus
def test_thing_on_a_spring_heard_copies_stay():
    lines, _ = _convert("Thing_on_a_Spring.sid", tie_restart=True)
    assert [ln for ln in lines if "Entry instrument split" in ln
            and "of 05, 08" in ln]
