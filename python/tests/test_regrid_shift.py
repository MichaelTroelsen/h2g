"""A regrid pair its first-choice row cannot take is moved, not dropped.

`regrid_tempos` debits its accumulator before it chooses rows, so a declined
spot is compensation paid for and never delivered (the tie's `CMD_TONEPORTA 00`
was the measured case: Monty, `monty-tie-false-voice3-plus-two`). These pin
where the moved pair may and may not go -- see `patterns._shifted_regrid_spot`.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus
from h2g.goatwriter import CMD_SETTEMPO
from h2g.patterns import (CMD_TONEPORTA, GT_COMMAND_FLOOR, GT_END_PATTERN,
                          GT_ORDER_RESTART, regrid_tempos)

TIE = (CMD_TONEPORTA, 0x00)
SLIDE_DOWN = (2, 0x01)
SET_AD = (5, 0x09)


def _pattern(musical_rows, cmds=None):
    cmds = cmds or {}
    out = []
    for r in range(musical_rows):
        c, p = cmds.get(r, (0, 0))
        out += [0x30, 1, c, p]
    return out + [GT_END_PATTERN, 0, 0, 0]


def _lengthened(pat):
    return [r for r in range(len(pat) // 4)
            if pat[r * 4 + 2] == CMD_SETTEMPO and pat[r * 4 + 3] == 4]


def _run(pat, deficit):
    pats, log = [pat], []
    n = regrid_tempos(pats, [[0], [], []], [3], [deficit], 1, log.append)
    return n, pats[0], log


def test_the_unoccupied_first_choice_is_row_6_of_this_pattern():
    """The geometry the tests below occupy: 12 musical rows, one pair."""
    n, pat, _ = _run(_pattern(12), 0.1)
    assert n == 1 and _lengthened(pat) == [6]


def test_a_tie_on_the_chosen_row_moves_the_pair_instead_of_dropping_it():
    """Row 6 holds the tie. Row 5 would restore onto it; row 7 would inherit
    the tie's running 3XY. Row 4 is the nearest clean pair."""
    n, pat, log = _run(_pattern(12, {6: TIE}), 0.1)
    assert n == 1, "the pair was dropped: its debt is paid and never delivered"
    assert _lengthened(pat) == [4]
    assert pat[5 * 4 + 2:5 * 4 + 4] == [CMD_SETTEMPO, 3]
    assert pat[6 * 4 + 2:6 * 4 + 4] == list(TIE), "the tie was overwritten"
    assert "1 shifted" in log[0] and "skipped" not in log[0], log


def test_a_moved_pair_never_inherits_a_running_slide():
    """0XY resets a channel's effect, 5XY-FXY leave it running underneath, so
    a CMD_SETTEMPO pair straight after a 2XY row would carry the slide through
    two more rows. Row 7 is the nearest free pair and follows the slide."""
    n, pat, _ = _run(_pattern(12, {6: SLIDE_DOWN}), 0.1)
    assert n == 1
    assert _lengthened(pat) == [4], "row 7 would carry the slide on"


def test_a_moved_pair_refuses_a_row_whose_running_effect_cannot_be_known():
    """Rows 0-4 are all one-shot (row 0 is the clock's own CMD_SETTEMPO), so
    what runs under row 5 is whatever the orderlist played before -- a
    position-dependent answer. Row 6 is the nearest clean pair."""
    cmds = {0: (CMD_SETTEMPO, 3), 1: SET_AD, 2: SET_AD, 3: SET_AD, 4: SET_AD}
    n, pat, _ = _run(_pattern(8, cmds), 0.2)
    assert n == 1
    assert _lengthened(pat) == [6]


def test_a_moved_pair_never_restores_onto_the_end_marker():
    """Rows 1-6 are spoken for; the only free row is 7, the last musical one,
    whose restore would be the GT_END_PATTERN row -- what plays after it is
    the orderlist's business. Nothing may be written."""
    cmds = {r: SET_AD for r in range(1, 7)}
    n, pat, log = _run(_pattern(8, cmds), 0.2)
    assert n == 0 and _lengthened(pat) == []
    assert pat[8 * 4:8 * 4 + 4] == [GT_END_PATTERN, 0, 0, 0]
    assert "1 skipped" in log[0], log


def test_a_moved_pair_never_takes_row_0():
    """Row 0 is the subtune's clock (TEMPO_OVERWRITABLE). Rows 2-3 are taken,
    so the only free pair is (0, 1)."""
    n, pat, _ = _run(_pattern(5, {2: SET_AD, 3: SET_AD}), 0.3)
    assert n == 0 and pat[2] == 0


def _ledger_end(name):
    """Delivered minus owed, in calls, over subtune 0's whole voice-0
    orderlist -- `regrid_tempos`' own accumulator, run to the end."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import fidelity
    import h2g.convert as C
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    cap = {}
    real = C.regrid_tempos

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None,
            **kw):
        cap.update(p=patterns, t=tracks, b=bases[0], d=deficits[0],
                   m=multiplier)
        return real(patterns, tracks, bases, deficits, multiplier, log, **kw)

    C.regrid_tempos = spy
    try:
        C.convert(str(CORPUS / name), log=lambda m: None,
                  **fidelity._preset_opts(doc, name))
    finally:
        C.regrid_tempos = real
    assert cap, f"{name} never reached regrid_tempos"
    owed = got = 0.0
    operand = False
    for e in cap["t"][0]:
        if operand:
            operand = False
        elif e == GT_ORDER_RESTART:
            operand = True
        elif e < GT_COMMAND_FLOOR:
            pat = cap["p"][e]
            owed += cap["d"] * (len(pat) // 4) * cap["m"]
            got += sum(1 for r in range(len(pat) // 4)
                       if pat[r * 4 + 2] == CMD_SETTEMPO
                       and pat[r * 4 + 3] == cap["b"] + 1)
    return got - owed


@needs_corpus
def test_monty_and_rikky_deliver_what_their_regrid_budget_owes():
    """At 075a175 (no shifting) these read -16.5 and -22.4 calls short over the
    whole orderlist: 12 and 19 declined spots, Monty's 8 of them on a tie
    cell. Moving the pairs brings them to -2.5 and -0.35."""
    for name in ("Auf_Wiedersehen_Monty.sid", "Rikky.sid"):
        end = _ledger_end(name)
        assert abs(end) <= 3.0, f"{name}: delivered - owed = {end:+.2f} calls"
