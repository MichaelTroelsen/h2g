"""`_regrid_per_play`'s repair: a pass that ends a call or more short is
re-spent by lowering one pattern and refilling the others.

The forward pass is greedy. A pattern bought at its first visit and replayed
later spends the room of every play from the first on, so the patterns first
played in between are left nothing: Star_Paws was paid 135 of 147.28 calls
(measured at 39b5de2). See `patterns._regrid_per_play`.
"""
import copy
import inspect
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, _regrid_order,     # noqa: E402
                          _regrid_per_play, _regrid_spots)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pattern(rows):
    return [0x30, 1, 0, 0] * rows + [GT_END_PATTERN, 0, 0, 0]


def _ledger(pats, order, want, owed_per_row):
    """delivered - owed after each play, delivery counted as the writer
    places it (`_regrid_spots`), not as `want` asks for it."""
    out, led = [], 0.0
    for p in order:
        rows = len(pats[p]) // 4
        got = len(_regrid_spots(pats[p], want[p], rows)[0]) if p in want else 0
        led += got - owed_per_row * rows
        out.append(led)
    return out


def _replay_block():
    """Pattern 3 is a shared 101-row backlog, played once. Patterns 0-2 are
    this voice's own and play twice in a row, 0 1 2 0 1 2, so pattern 0's
    replay is delivered after 1 and 2 have been passed."""
    pats = [_pattern(40), _pattern(40), _pattern(40), _pattern(100)]
    order = [3, 0, 1, 2, 0, 1, 2]
    return pats, order, {0, 1, 2}, 0.15


def test_the_bare_pass_leaves_a_replayed_block_short():
    pats, order, excl, d = _replay_block()
    led = _ledger(pats, order, _regrid_per_play(pats, order, excl, d,
                                                repair=False), d)
    assert led[-1] < -9, led


def test_the_repair_pays_it_within_one_call_and_is_never_late():
    pats, order, excl, d = _replay_block()
    led = _ledger(pats, order, _regrid_per_play(pats, order, excl, d), d)
    assert -1 < led[-1] <= 1e-9, led
    assert max(led) <= 1e-9, led


def test_a_pass_already_within_a_call_is_left_alone():
    pats = [_pattern(40), _pattern(40)]
    order = [0, 0, 1]
    args = (pats, order, {0, 1}, 0.1)
    bare = _regrid_per_play(*args, repair=False)
    led = _ledger(pats, order, bare, 0.1)
    assert -1 < led[-1] <= 1e-9, led
    assert _regrid_per_play(*args) == bare


def test_the_repair_cannot_pay_what_nothing_can_carry():
    """No exclusive pattern: nothing to lower and nothing to raise."""
    pats = [_pattern(40), _pattern(40)]
    assert _regrid_per_play(pats, [0, 1, 0], set(), 0.1) == {}


def test_regrid_per_play_is_off_by_default():
    from h2g.convert import convert
    assert inspect.signature(convert).parameters["regrid_per_play"].default is False
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    blocks = [doc["always"]]  # per-song adopters are allowed (v0.5.594)
    assert not any(b.get("regrid_per_play") for b in blocks)


def test_it_is_inert_on_the_fixture():
    from h2g.convert import convert
    assert (convert(str(ROOT / "Commando.sid"), log=lambda m: None,
                    regrid=True, regrid_per_play=True)
            == (ROOT / "Commando.sng").read_bytes())


# --- end to end -------------------------------------------------------------

def _corpus_ledger(monkeypatch, name):
    import fidelity
    import h2g.convert as C
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    opts.update(regrid=True, regrid_per_play=True)
    seen = {}
    real = C.regrid_tempos

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None, **kw):
        seen["tracks"] = copy.deepcopy(tracks)
        r = real(patterns, tracks, bases, deficits, multiplier, log, **kw)
        seen.update(out=copy.deepcopy(patterns), base=bases[0],
                    owed=deficits[0] * multiplier)
        return r

    monkeypatch.setattr(C, "regrid_tempos", spy)
    C.convert(str(CORPUS / name), log=lambda m: None, **opts)
    order = _regrid_order(seen["tracks"][0], len(seen["out"]), True)
    from h2g.goatwriter import CMD_SETTEMPO
    led, out = 0.0, []
    for p in order:
        pat = seen["out"][p]
        ups = sum(1 for r in range(len(pat) // 4)
                  if pat[r * 4 + 2] == CMD_SETTEMPO
                  and pat[r * 4 + 3] == seen["base"] + 1)
        led += ups - seen["owed"] * (len(pat) // 4)
        out.append(led)
    return out


@needs_corpus
def test_star_paws_delivers_its_owed_calls_within_one(monkeypatch):
    """135 of 147.28 before the repair (39b5de2); 147 after."""
    led = _corpus_ledger(monkeypatch, "Star_Paws.sid")
    assert -1 < led[-1] <= 1e-9, led[-1]
    assert max(led) <= 1e-9


@needs_corpus
def test_a_file_the_bare_pass_pays_within_a_call_is_not_moved(monkeypatch):
    """Arcade_Classics ends 0.3 calls short from the bare pass, which is
    within a call, so the repair must hand back exactly the same schedule
    (it could still shave area off the ledger, and must not)."""
    import fidelity
    import h2g.convert as C
    import h2g.patterns as P
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Arcade_Classics.sid")
    opts.update(regrid=True, regrid_per_play=True)
    real, seen = P._regrid_per_play, []

    def spy(patterns, order, exclusive, owed, **kw):
        bare = real(patterns, order, exclusive, owed, repair=False)
        seen.append(bare == real(patterns, order, exclusive, owed))
        return bare

    monkeypatch.setattr(P, "_regrid_per_play", spy)
    C.convert(str(CORPUS / "Arcade_Classics.sid"), log=lambda m: None, **opts)
    assert seen and all(seen), seen


@needs_corpus
@pytest.mark.parametrize("name", ["I_Ball.sid", "Bangkok_Knights.sid",
                                  "Trans-Atlantic_Balloon_Challenge.sid"])
def test_other_files_the_bare_pass_left_short_are_paid(monkeypatch, name):
    led = _corpus_ledger(monkeypatch, name)
    assert -1 < led[-1] <= 1e-9, (name, led[-1])
    assert max(led) <= 1e-9
