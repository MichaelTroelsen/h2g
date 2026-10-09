"""`regrid_per_play`: each compensating row is debited at the play that
delivers it, so the running ledger (calls delivered minus owed, voice 0,
every play) never goes positive at a play boundary.

The budget walk charges a pattern for all its plays at the visit that buys
the row, and a count raised on a later visit fires at the earlier plays too,
so under it the conversion runs late in between. Bangkok_Knights peaked at
+16.90 calls under `regrid_full_debt` (measured at 39b5de2). See
`patterns._regrid_per_play`.
"""
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO                      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, _regrid_order,     # noqa: E402
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


def _ledger(pats, order, base, owed_per_row):
    """delivered - owed after each play of `order`."""
    out, led = [], 0.0
    for p in order:
        led += _ups(pats[p], base) - owed_per_row * (len(pats[p]) // 4)
        out.append(led)
    return out


def _replay_case():
    # Pattern 0 is voice 0's own, played first and last; pattern 1 is shared
    # with voice 1, so it only raises debt. d = 0.1 a row, 41 rows each.
    pats = [_pattern(40), _pattern(40)]
    tracks = [[0, 1, 1, 1, 1, 0], [1], []]
    return pats, tracks


def test_a_raise_at_a_later_visit_is_not_delivered_early():
    """The budget walk buys 2 rows at play 0, raises to 12 at play 5 for
    20.6 calls of debt, and the 12 fire at play 0 too: +7.9 calls there.
    Per play, the raise is refused because play 0 has no room for it."""
    pats, tracks = _replay_case()
    regrid_tempos(pats, tracks, [3], [0.1], 1, full_debt=True)
    assert max(_ledger(pats, _regrid_order(tracks[0], 2), 3, 0.1)) > 7

    pats, tracks = _replay_case()
    regrid_tempos(pats, tracks, [3], [0.1], 1, per_play=True)
    led = _ledger(pats, _regrid_order(tracks[0], 2), 3, 0.1)
    assert max(led) <= 1e-9, led
    assert _ups(pats[0], 3) == 4


def test_a_replay_is_booked_at_every_play_it_fires():
    """Pattern 0 plays twice before pattern 1 pays. Its 4 rows deliver 8
    calls, and pattern 1 is left only what is still owed."""
    pats = [_pattern(40), _pattern(40)]
    tracks = [[0, 0, 1], [], []]
    regrid_tempos(pats, tracks, [3], [0.1], 1, per_play=True)
    led = _ledger(pats, [0, 0, 1], 3, 0.1)
    assert max(led) <= 1e-9, led
    assert -1 < led[-1] <= 1e-9, led


def test_an_unplaceable_row_carries_its_debt_forward():
    pats = [_pattern(12, cmd_at=range(12)), _pattern(40)]
    tracks = [[0, 1], [], []]
    regrid_tempos(pats, tracks, [3], [0.25], 1, per_play=True)
    debt = 0.25 * (13 + 41)
    assert _ups(pats[0], 3) == 0
    assert debt - 1 < _ups(pats[1], 3) <= debt


def test_it_is_inert_without_regrid():
    from h2g.convert import convert
    assert (convert(str(ROOT / "Commando.sid"), log=lambda m: None,
                    regrid_per_play=True)
            == (ROOT / "Commando.sng").read_bytes())


# --- end to end -------------------------------------------------------------

def _corpus_ledger(monkeypatch, name, **force):
    import fidelity
    import h2g.convert as C
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    assert opts.get("regrid"), name
    opts.update(force)
    seen = {}
    real = C.regrid_tempos

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None,
            **kw):
        seen["tracks"] = copy.deepcopy(tracks)
        r = real(patterns, tracks, bases, deficits, multiplier, log, **kw)
        seen.update(out=copy.deepcopy(patterns), base=bases[0],
                    owed=deficits[0] * multiplier)
        return r

    monkeypatch.setattr(C, "regrid_tempos", spy)
    C.convert(str(CORPUS / name), log=lambda m: None, **opts)
    order = _regrid_order(seen["tracks"][0], len(seen["out"]))
    return _ledger(seen["out"], order, seen["base"], seen["owed"])


@needs_corpus
def test_bangkok_knights_is_never_late_at_a_play_boundary(monkeypatch):
    name = "Bangkok_Knights.sid"
    assert max(_corpus_ledger(monkeypatch, name, regrid_full_debt=True)) > 10
    assert max(_corpus_ledger(monkeypatch, name, regrid_per_play=True)) <= 1e-9


@needs_corpus
def test_monty_is_never_late_at_a_play_boundary(monkeypatch):
    name = "Auf_Wiedersehen_Monty.sid"
    assert max(_corpus_ledger(monkeypatch, name, regrid_full_debt=True)) > 1
    assert max(_corpus_ledger(monkeypatch, name, regrid_per_play=True)) <= 1e-9
