"""I_Ball under `--regrid`: the +25-frame ramp over frames 3500-5000 (-t 180).

Cause, measured at 6f6de05 (`docs/LESSONS.md` is not edited here): voice 0's
orderlist holds `$D7 $28`, pattern 40 (65 rows) packed to play EIGHT times.
The default `--regrid` budget walks one entry per orderlist BYTE, so it sees
that run as one play: it buys 5 compensating rows in pattern 40 and debits 5
calls, while the 8 plays deliver 40. The 35 calls of surplus land inside one
1560-frame stretch, which is the ramp (the original's attacks at 3513..5000
drift from offset 0 to +25 frames and then run flat at -0.75 per 1000 for the
rest of the window). `drift` reads +3.06 for it, a whole-window fit to a
step the file's halves cannot see.

`regrid_full_debt` walks every play (`_regrid_order`, `repeats=True`) and pays
in full: pattern 40 buys 2, voice 0 delivers 133 calls of the 133.07 it owes,
drift reads 0.00 and the offsets sit in 1..6 for the whole window.

These pin the CAUSE (delivery against debt on the real file), not a score.
The default case characterises today's behaviour: it is the thing to flip when
`presets.json` adopts `regrid_full_debt` for I_Ball (that edit is a separate,
main-session task) or when the default budget is corrected.
"""
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO                      # noqa: E402
from h2g.patterns import GT_REPEAT, _regrid_order            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
I_BALL = CORPUS / "I_Ball.sid"


def _ups(pattern, base):
    return sum(1 for r in range(len(pattern) // 4)
               if pattern[r * 4 + 2] == CMD_SETTEMPO
               and pattern[r * 4 + 3] == base + 1)


def _i_ball(monkeypatch, full_debt):
    """(debt in calls, per-pattern delivery in calls, voice 0 track)."""
    import fidelity
    import h2g.convert as C
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "I_Ball.sid")
    opts.update(regrid=True, regrid_full_debt=full_debt,
                regrid_per_play=False, regrid_prepay=0, regrid_park=False)
    seen = {}
    real = C.regrid_tempos

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None, **kw):
        seen["tracks"] = copy.deepcopy(tracks)
        seen["bases"], seen["deficits"], seen["mult"] = bases, deficits, multiplier
        seen["rows"] = [len(p) // 4 for p in patterns]
        r = real(patterns, tracks, bases, deficits, multiplier, log, **kw)
        seen["out"] = copy.deepcopy(patterns)
        return r

    monkeypatch.setattr(C, "regrid_tempos", spy)
    C.convert(str(I_BALL), log=lambda m: None, **opts)
    order = _regrid_order(seen["tracks"][0], len(seen["rows"]))
    debt = (seen["deficits"][0] * seen["mult"]
            * sum(seen["rows"][p] for p in order))
    delivered = {}
    for p in order:
        delivered[p] = (delivered.get(p, 0)
                        + _ups(seen["out"][p], seen["bases"][0]))
    return debt, delivered, seen["tracks"][0]


@needs_corpus
def test_voice_zero_packs_a_pattern_into_an_eight_play_run(monkeypatch):
    _, _, track = _i_ball(monkeypatch, False)
    # `$D7, $28`: GT_REPEAT + 7 -> eight plays of pattern 0x28 (40).
    assert any(a == GT_REPEAT + 7 and b == 0x28
               for a, b in zip(track, track[1:])), track


@needs_corpus
def test_the_default_budget_over_delivers_through_the_packed_run(monkeypatch):
    debt, delivered, _ = _i_ball(monkeypatch, False)
    got = sum(delivered.values())
    # 153 delivered against 133.07 owed, 40 of them from pattern 40 alone.
    assert got - debt > 15, (got, debt)
    assert delivered[0x28] >= 30, delivered


@needs_corpus
def test_full_debt_pays_i_ball_in_full_and_no_run_dominates(monkeypatch):
    debt, delivered, _ = _i_ball(monkeypatch, True)
    got = sum(delivered.values())
    assert debt - 1 < got <= debt + 1e-9, (got, debt)
    assert max(delivered.values()) <= 25, delivered
