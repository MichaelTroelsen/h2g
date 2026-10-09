"""`regrid_prepay`: the per-play ledger may run ahead of the debt, and a trough
no compensating row can be written into is paid for in advance.

`regrid_per_play` keeps the ledger (calls delivered minus owed, voice 0, every
play) at or below zero. That is one-sided: the conversion is never late against
its own debt and so sits early by up to a frame, and a run of plays with no
clean command pair (Star_Paws' patterns 57-64, 31 plays) dives 20 calls with
nothing to pay it until the pattern after. See `patterns._regrid_per_play`.
"""
import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, _regrid_per_play,  # noqa: E402
                          _regrid_spots, regrid_tempos)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pattern(rows, full=False):
    """`full`: every row carries a command, so no pair is free."""
    out = []
    for _ in range(rows):
        out += [0x30, 1, 0x03 if full else 0, 0]
    return out + [GT_END_PATTERN, 0, 0, 0]


def _ledger(pats, order, want, owed_per_row):
    out, led = [], 0.0
    for p in order:
        rows = len(pats[p]) // 4
        got = len(_regrid_spots(pats[p], want[p], rows)[0]) if p in want else 0
        led += got - owed_per_row * rows
        out.append(led)
    return out


def _trough_case():
    """0 and 2 are this voice's own and clean; 1 is a stretch of nine plays of
    a pattern with every command cell taken, which can raise debt and not pay
    it. 0.1 call a row."""
    pats = [_pattern(94), _pattern(17, full=True), _pattern(94), _pattern(94)]
    order = [0, 3, 0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2]
    return pats, order, {0, 2}, 0.1


def test_zero_is_the_per_play_rule_byte_for_byte():
    pats, order, excl, d = _trough_case()
    assert (_regrid_per_play(pats, order, excl, d, prepay=0)
            == _regrid_per_play(pats, order, excl, d))
    assert max(_ledger(pats, order, _regrid_per_play(pats, order, excl, d),
                       d)) <= 1e-9


def test_a_trough_nothing_can_pay_is_met_half_way():
    pats, order, excl, d = _trough_case()
    base = _ledger(pats, order, _regrid_per_play(pats, order, excl, d), d)
    led = _ledger(pats, order, _regrid_per_play(pats, order, excl, d,
                                                prepay=1), d)
    assert min(base) < -10, base
    assert min(led) > min(base) + 3, (min(led), min(base))
    # it runs ahead somewhere, which is the cost, and by less than it saves
    assert max(led) > 1, led
    assert max(led) < -min(led) + 1, led


def test_the_pass_never_delivers_more_than_it_owes():
    pats, order, excl, d = _trough_case()
    for prepay in (1, 2, 5, 12):
        led = _ledger(pats, order, _regrid_per_play(pats, order, excl, d,
                                                    prepay=prepay), d)
        assert led[-1] <= 1e-9, (prepay, led[-1])


def test_with_nothing_to_pay_in_advance_the_ledger_stays_under_the_ceiling():
    """No stretch the clean patterns cannot cover: no window is lifted, the
    ledger runs ahead by up to `prepay` and never past it."""
    pats = [_pattern(94), _pattern(94), _pattern(94)]
    order = [0, 1, 2, 0, 1, 2]
    led = _ledger(pats, order,
                  _regrid_per_play(pats, order, {0, 1, 2}, 0.1, prepay=2), 0.1)
    assert max(led) <= 2 + 1e-9, led
    assert max(led) > 0.5, led
    assert led[-1] <= 1e-9, led


def test_it_is_inert_without_regrid():
    from h2g.convert import convert
    assert (convert(str(ROOT / "Commando.sid"), log=lambda m: None,
                    regrid_prepay=2)
            == (ROOT / "Commando.sng").read_bytes())


def test_regrid_tempos_implies_the_per_play_walk_and_passes_prepay_on():
    """The writer's rows are exactly what `_regrid_per_play` asked for."""
    from h2g.goatwriter import CMD_SETTEMPO
    pats, order, excl, d = _trough_case()
    tracks = [list(order), [3], []]      # 3 is shared with voice 1
    want = _regrid_per_play(pats, order, excl, d, prepay=2)
    plain = _regrid_per_play(pats, order, excl, d)
    assert want != plain
    written = copy.deepcopy(pats)
    regrid_tempos(written, tracks, [3], [d], 1, prepay=2)
    for p in excl:
        ups = sum(1 for r in range(len(written[p]) // 4)
                  if written[p][r * 4 + 2] == CMD_SETTEMPO
                  and written[p][r * 4 + 3] == 4)
        assert ups == len(_regrid_spots(pats[p], want.get(p, 0),
                                        len(pats[p]) // 4)[0]), p


def test_the_command_line_and_a_preset_entry_both_reach_convert(tmp_path,
                                                                monkeypatch):
    import h2g.cli as cli
    seen = {}

    def fake(path, log=None, **kw):
        seen.clear()
        seen.update(kw)
        return b"x"

    monkeypatch.setattr(cli, "convert", fake)
    out = tmp_path / "o.sng"
    sid = str(ROOT / "Commando.sid")
    cli.main([sid, "-o", str(out), "-q", "--regrid", "--regrid-prepay", "3"])
    assert seen["regrid_prepay"] == 3
    cli.main([sid, "-o", str(out), "-q"])
    assert seen["regrid_prepay"] == 0

    presets = tmp_path / "p.json"
    presets.write_text(json.dumps({"always": {}, "songs": {
        "Commando.sid": {"regrid": True, "regrid_prepay": 2}}}))
    cli.main([sid, "-o", str(out), "-q", "--presets", str(presets)])
    assert seen["regrid_prepay"] == 2 and seen["regrid"] is True
    cli.main([sid, "-o", str(out), "-q", "--presets", str(presets),
              "--regrid-prepay", "5"])
    assert seen["regrid_prepay"] == 5


def test_preset_opts_hands_the_integer_through_unchanged():
    import fidelity
    doc = {"always": {}, "songs": {"X.sid": {"regrid": True,
                                             "regrid_prepay": 2}}}
    assert fidelity._preset_opts(doc, "X.sid")["regrid_prepay"] == 2
    assert fidelity._preset_opts({"always": {}, "songs": {"X.sid": {}}},
                                 "X.sid")["regrid_prepay"] == 0


# --- Star_Paws: the file that found it -------------------------------------

def _star_paws_ledger(monkeypatch, **force):
    import fidelity
    import h2g.convert as C
    from h2g.patterns import _regrid_order
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Star_Paws.sid")
    opts["regrid"] = True
    opts.update(force)
    seen = {}
    real = C.regrid_tempos

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None, **kw):
        seen["tracks"] = copy.deepcopy(tracks)
        r = real(patterns, tracks, bases, deficits, multiplier, log, **kw)
        seen.update(out=copy.deepcopy(patterns), base=bases[0],
                    owed=deficits[0] * multiplier)
        return r

    monkeypatch.setattr(C, "regrid_tempos", spy)
    C.convert(str(CORPUS / "Star_Paws.sid"), log=lambda m: None, **opts)
    order = _regrid_order(seen["tracks"][0], len(seen["out"]))
    ups = lambda p: sum(1 for r in range(len(p) // 4)             # noqa: E731
                        if p[r * 4 + 2] == 0xF
                        and p[r * 4 + 3] == seen["base"] + 1)
    led, out = 0.0, []
    for p in order:
        led += ups(seen["out"][p]) - seen["owed"] * (len(seen["out"][p]) // 4)
        out.append(led)
    return out


@needs_corpus
def test_star_paws_trough_is_shallower_and_the_pass_still_ends_owed(monkeypatch):
    """Measured at 82d60ac, `regrid` forced: per-play dives to -23.8 calls
    (patterns 57-64), prepay=2 to -14.8 and rises to +7.3."""
    base = _star_paws_ledger(monkeypatch, regrid_per_play=True)
    led = _star_paws_ledger(monkeypatch, regrid_prepay=2)
    assert min(base) < -20, min(base)
    assert min(led) > -16, min(led)
    assert max(led) < 9, max(led)
    assert led[-1] <= 1e-9, led[-1]
