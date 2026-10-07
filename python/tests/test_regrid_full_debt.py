"""`regrid_full_debt`: `--regrid`'s budget pays the whole debt.

Two leaks, both found on Star_Paws (-S2, 256/127 frames a row), where
`--regrid` delivered 124 of the 147.28 calls a pass owes and attacks drifted to
-17 frames (index-paired, voice 2/3, `-t 180`):

* a packed orderlist repeat `$D0+n, P` plays P n+1 times, and the budget walk
  counted it once -- both the debt it raises and the plays a bought row fires;
* a bought row the writer cannot place (command column full of tie cells) was
  debited anyway, so the debt it stood for vanished instead of carrying on.

Off by default, because both corrections move ten -S1 files that ship
`regrid`; see `presets.EXCLUDED_FROM_ALWAYS`.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO                      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_ORDER_RESTART,  # noqa: E402
                          GT_REPEAT, _regrid_order, _regrid_spots,
                          regrid_tempos)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pattern(rows, cmd_at=()):
    out = []
    for r in range(rows):
        out += [0x30, 1, (0x03 if r in cmd_at else 0), 0]
    return out + [GT_END_PATTERN, 0, 0, 0]


def _ups(pattern, base):
    return sum(1 for r in range(len(pattern) // 4)
               if pattern[r * 4 + 2] == CMD_SETTEMPO
               and pattern[r * 4 + 3] == base + 1)


def _delivered(pats, plays, base):
    return sum(_ups(pats[p], base) * n for p, n in plays.items())


# --- the walk ---------------------------------------------------------------

def test_a_packed_repeat_is_counted_once_per_play():
    track = [0xF0, GT_REPEAT + 2, 5, 6, GT_ORDER_RESTART, 0]
    assert _regrid_order(track, 10) == [5, 5, 5, 6]


def test_the_restart_operand_and_a_transpose_are_not_plays():
    track = [0xF3, 1, GT_ORDER_RESTART, 1]
    assert _regrid_order(track, 10) == [1]


def test_without_repeats_the_walk_is_the_one_the_adopters_were_measured_under():
    track = [GT_REPEAT + 2, 5, 6, GT_ORDER_RESTART, 0]
    assert _regrid_order(track, 10, repeats=False) == [5, 6]


# --- the placement ----------------------------------------------------------

def test_placed_pairs_never_overlap_each_other():
    """The copy sees its own writes: a second pair may not land on the first
    pair's restore row (or vice versa)."""
    pat = _pattern(12)
    rows = len(pat) // 4
    placed, _ = _regrid_spots(pat, 5, rows)
    cells = [c for r, _ in placed for c in (r, r + 1)]
    assert len(cells) == len(set(cells)), placed
    assert all(1 <= r <= rows - 3 for r, _ in placed), placed


def test_a_full_command_column_places_nothing_and_says_so():
    pat = _pattern(12, cmd_at=range(12))
    placed, skipped = _regrid_spots(pat, 3, len(pat) // 4)
    assert placed == [] and skipped == 3


def test_the_simulation_does_not_touch_the_pattern():
    pat = _pattern(20)
    before = list(pat)
    _regrid_spots(pat, 4, len(pat) // 4)
    assert pat == before


# --- the budget -------------------------------------------------------------

def _repeat_case():
    # Pattern 0 is shared with voice 1 (never exclusive, so it can only RAISE
    # debt) and played 8 times behind one packed repeat; pattern 1 is voice
    # 0's own and pays.
    pats = [_pattern(12), _pattern(40)]
    tracks = [[GT_REPEAT + 7, 0, 1], [0], []]
    return pats, tracks


def test_the_debt_behind_a_packed_repeat_is_paid():
    pats, tracks = _repeat_case()
    d = 0.1
    regrid_tempos(pats, tracks, [3], [d], 1, full_debt=True)
    debt = d * (13 * 8 + 41)                 # rows counted with ENDPATT
    got = _delivered(pats, {1: 1}, 3)
    assert debt - 1 < got <= debt, (got, debt)


def test_without_full_debt_the_packed_repeat_is_counted_once():
    """The old budget, pinned so the default cannot drift: it sees 13 + 41
    rows and pays 5 calls of a 14.5-call debt."""
    pats, tracks = _repeat_case()
    regrid_tempos(pats, tracks, [3], [0.1], 1)
    assert _delivered(pats, {1: 1}, 3) == 5


def test_packed_and_unpacked_orderlists_get_the_same_compensation():
    pats_a, tracks_a = _repeat_case()
    pats_b = [_pattern(12), _pattern(40)]
    tracks_b = [[0] * 8 + [1], [0], []]
    regrid_tempos(pats_a, tracks_a, [3], [0.1], 1, full_debt=True)
    regrid_tempos(pats_b, tracks_b, [3], [0.1], 1, full_debt=True)
    assert pats_a == pats_b


def _blocked_case():
    # Pattern 0 is voice 0's own but every row carries a tie cell; pattern 1
    # is free. Both exclusive.
    return [_pattern(12, cmd_at=range(12)), _pattern(40)], [[0, 1], [], []]


def test_an_unplaceable_row_carries_its_debt_forward():
    pats, tracks = _blocked_case()
    d = 0.25
    regrid_tempos(pats, tracks, [3], [d], 1, full_debt=True)
    debt = d * (13 + 41)
    got = _delivered(pats, {0: 1, 1: 1}, 3)
    assert _ups(pats[0], 3) == 0
    assert debt - 1 < got <= debt, (got, debt)


def test_without_full_debt_the_unplaceable_rows_are_lost():
    pats, tracks = _blocked_case()
    regrid_tempos(pats, tracks, [3], [0.25], 1)
    # 3 rows bought in pattern 0 and debited, none written; pattern 1 gets
    # only the 10 left.
    assert _delivered(pats, {0: 1, 1: 1}, 3) == 10


# --- end to end -------------------------------------------------------------

STAR_PAWS = CORPUS / "Star_Paws.sid"


def _star_paws_regrid(monkeypatch, full_debt):
    import json
    import copy
    import fidelity
    import h2g.convert as C
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Star_Paws.sid")
    opts.update(regrid=True, regrid_full_debt=full_debt)
    seen = {}
    real = C.regrid_tempos

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None,
            full_debt=False):
        seen["tracks"] = copy.deepcopy(tracks)
        seen["bases"], seen["deficits"], seen["mult"] = bases, deficits, multiplier
        seen["rows"] = [len(p) // 4 for p in patterns]
        r = real(patterns, tracks, bases, deficits, multiplier, log, full_debt)
        seen["out"] = copy.deepcopy(patterns)
        return r

    monkeypatch.setattr(C, "regrid_tempos", spy)
    C.convert(str(STAR_PAWS), log=lambda m: None, **opts)
    order = _regrid_order(seen["tracks"][0], len(seen["rows"]))
    debt = seen["deficits"][0] * seen["mult"] * sum(seen["rows"][p] for p in order)
    plays = {}
    for p in order:
        plays[p] = plays.get(p, 0) + 1
    return debt, _delivered(seen["out"], plays, seen["bases"][0])


@needs_corpus
def test_star_paws_is_paid_in_full(monkeypatch):
    """Measured at 6e467ff: 147 of 147.28 calls a pass (was 124)."""
    debt, got = _star_paws_regrid(monkeypatch, True)
    assert debt - 1 < got <= debt + 1e-9, (got, debt)


@needs_corpus
def test_star_paws_without_full_debt_keeps_the_old_shortfall(monkeypatch):
    debt, got = _star_paws_regrid(monkeypatch, False)
    assert debt - got > 20, (got, debt)


def test_it_is_inert_without_regrid():
    from h2g.convert import convert
    assert (convert(str(ROOT / "Commando.sid"), log=lambda m: None,
                    regrid_full_debt=True)
            == (ROOT / "Commando.sng").read_bytes())
