"""Seeding the reset-site literal into the files with no instrument-array image
moves no byte, so none of them is widened.

`reset_idiom_census.py` found 15 reset-idiom files whose `Detection.
initial_instruments` was empty, so `tracks.apply_initial_instruments` returned
before `_initial_for`. Seven of them (After_8, Kings_of_the_Beach_intro,
Mr_Meaner, Off_the_Cuff, Pygmies_Revenge, Rikky, Rock_Tells_the_Tale) have
since been rescued by `_reconcile_instrument_index`'s ASL4 spelling. The eight
left are pinned here: Food_Feud, Go_Go_Dash, Lakers_vs_Celtics, Lion_Heart,
Mega_Apocalypse, Pacific_Coast, Radio_ACE and Sun_Never_Shines.

Measured at 9300fa7 (task reset-site-no-image-initial-instrument), under the
shipped presets with `initial_instrument` forced on, seeding the census
literal as both `init_instrument` and the image: the converted bytes are
identical for all eight, because in each of them every voice's first
orderlist pattern names an instrument before its first note
(`tracks._first_sounding_row` is None, or the pattern holds no note), so
`apply_initial_instruments` repoints no orderlist step. Food_Feud parks
silence until the first instrument (`pre_instrument_silence`), which skips
the pass altogether. Mega_Apocalypse's literal `$11` selects an all-zero
record besides.

This test fails the day a pattern in one of these files starts on a note with
no instrument -- the day seeding would start to matter and the question
should be asked again.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reset_idiom_census as R                    # noqa: E402
from corpus import CORPUS, needs_corpus           # noqa: E402
from fidelity import _preset_opts                 # noqa: E402
import h2g.convert as cv                          # noqa: E402
from h2g import detect as D, sidfile, tracks      # noqa: E402

PRESETS = Path(__file__).resolve().parents[2] / "presets.json"

SKIPPED_BY_SILENCE = ("Food_Feud",)
SEEDED = ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart", "Mega_Apocalypse",
          "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines")
NO_IMAGE = SKIPPED_BY_SILENCE + SEEDED


def _literal(path):
    c = R.census_file(path)
    assert len(c.sites) == 1 and c.sites[0].strict, (path.stem, c.sites)
    return c.sites[0].imm


def _opts(name):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, name + ".sid")
    opts["initial_instrument"] = True
    return opts


@needs_corpus
@pytest.mark.parametrize("name", NO_IMAGE)
def test_premise_no_image_and_no_init_literal(name):
    sid = sidfile.load_sid(str(CORPUS / (name + ".sid")))
    det = D.detect(sid, lambda _m: None)
    assert det.initial_instruments == ()
    assert det.init_instrument is None


@needs_corpus
@pytest.mark.parametrize("name", NO_IMAGE)
def test_seeding_the_literal_moves_no_byte(name, monkeypatch):
    path = CORPUS / (name + ".sid")
    lit = _literal(path)
    opts = _opts(name)
    base = cv.convert(str(path), log=lambda _m: None, **opts)

    real_detect_tables = cv._detect_tables
    real_apply = cv.apply_initial_instruments
    seen = {"calls": 0, "fixed": 0, "starts": []}

    def seeded(sid, log, engine=0):
        sid, det = real_detect_tables(sid, log, engine)
        det.init_instrument = lit
        det.initial_instruments = (lit, lit, lit)
        return sid, det

    def spy(tr, pa, det, log=None, instr_base=2):
        seen["calls"] += 1
        seen["starts"] = [tracks._initial_for(det, v, instr_base)
                          for v in range(3)]
        seen["ceiling"] = min(det.instr_used + instr_base - 1, 50)
        seen["base"] = instr_base
        n = real_apply(tr, pa, det, log, instr_base=instr_base)
        seen["fixed"] += n
        return n

    monkeypatch.setattr(cv, "_detect_tables", seeded)
    monkeypatch.setattr(cv, "apply_initial_instruments", spy)
    got = cv.convert(str(path), log=lambda _m: None, **opts)

    if name in SKIPPED_BY_SILENCE:
        assert seen["calls"] == 0        # pre_instrument_silence skips the pass
    else:
        assert seen["calls"] == 1
        # the seed names a record the writer keeps, at every voice
        assert seen["starts"] == [lit + seen["base"]] * 3
        assert seen["base"] <= seen["starts"][0] <= seen["ceiling"]
        assert seen["fixed"] == 0        # no orderlist step needed a copy
    assert got == base
