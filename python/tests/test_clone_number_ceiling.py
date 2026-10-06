"""Legato clones (and the -S>1 decoy) are numbered below every dangling reference.

`goatwriter.legato_tie_clones` appends its clones from `written + 1` upward.
An instrument byte some pattern names above `written` dangles only because
nothing sits at its number yet: a clone given that number satisfies it, so
every row naming it plays the clone and build_sng's DANGLING warning stops
counting it. `note_passes.clone_number_ceiling` caps the numbers one below
the lowest such byte.

Opened by greloc-multispeed-legato-slip at 8586101 (Ricochet under FIXED:
references $20 with 24 written). Re-measured at 075a175 under FIXED it was
already happening, on bytes in patterns no orderlist reaches: Ricochet's
decoy 17 and clone 24 sat on dangling $11 and $18, Kings_of_the_Beach_ingame's
decoy 6 on dangling $6, Arcade_Classics/Skate_or_Die_intro clone 12 and
BMX_Kidz clone 14 likewise. Under presets no file is affected (corpus
byte-hash: 0 of 89 move). Figures HISTORICAL (2026-10-06, 075a175).
"""
import re

from h2g import goatwriter as G
from h2g.goatwriter import note_passes as NP
import h2g.goatwriter.build as B
from h2g.convert import convert
from presets import FIXED

from corpus import CORPUS, needs_corpus

NOTE = 0x60
END = [0xFF, 0, 0, 0]


def _tie(instr):
    return [NOTE, instr, G.CMD_TONEPORTA, 0x00]


def _rest():
    return [G.GT_REST, 0, 0, 0]


def test_ceiling_is_one_below_the_lowest_dangling_reference():
    pats = [[NOTE, 1, 0, 0, NOTE, 5, 0, 0] + END,
            [NOTE, 12, 0, 0, NOTE, 9, 0, 0] + END]
    assert NP.clone_number_ceiling(pats, 5) == 8
    assert NP.clone_number_ceiling(pats, 9) == 11
    assert NP.clone_number_ceiling(pats, 12) == G.GT_MAX_INSTRUMENTS


def test_ceiling_never_exceeds_the_goattracker_limit():
    pats = [[NOTE, 1, 0, 0, NOTE, 0xF0, 0, 0] + END]
    assert NP.clone_number_ceiling(pats, 1) == G.GT_MAX_INSTRUMENTS
    assert NP.clone_number_ceiling([[NOTE, 3, 0, 0] + END], 3) \
        == G.GT_MAX_INSTRUMENTS


def _synthetic():
    # Records 1..5 written; pattern 0 ties on instruments 1, 2 and 3 (each
    # named by a note row first, so the tie's instrument is settled), and
    # pattern 1 -- the kind of unreached garbage Ricochet carries -- names
    # instrument 7, which does not exist.
    p0 = ([NOTE, 1, 0, 0] + _tie(0) + _rest()
          + [NOTE, 2, 0, 0] + _tie(0) + _rest()
          + [NOTE, 3, 0, 0] + _tie(0) + _rest() + END)
    p1 = [NOTE, 7, 0, 0] + END
    rows = {(0, 1), (0, 4), (0, 7)}
    return [p0, p1], rows


def test_without_a_ceiling_a_clone_lands_on_the_dangling_number():
    """The hazard itself: the default bound numbers the second clone 7."""
    pats, rows = _synthetic()
    _, clones, _ = G.legato_tie_clones(pats, rows, None, {1, 2, 3}, 6)
    assert [c for _, c in clones] == [6, 7, 8]


def test_with_the_ceiling_no_clone_takes_a_dangling_number():
    pats, rows = _synthetic()
    ceiling = NP.clone_number_ceiling(pats, 5)
    assert ceiling == 6
    out, clones, declined = G.legato_tie_clones(
        pats, rows, None, {1, 2, 3}, 6, last_number=ceiling)
    assert clones == [(1, 6)]
    assert declined == {(0, 4), (0, 7)}
    # The declined ties keep their old spelling.
    assert out[0][4 * 4 + 2:4 * 4 + 4] == [G.CMD_TONEPORTA, 0x00]
    assert out[1] == pats[1]


def _refs(patterns):
    return {p[k] for p in patterns for k in range(1, len(p), 4) if p[k]}


@needs_corpus
def test_build_sng_numbers_no_clone_or_decoy_onto_a_reference(monkeypatch):
    """The seam: build_sng passes the ceiling. Kings_of_the_Beach_ingame
    (not held) under FIXED is -S3 with 5 records and an unreached pattern
    naming $6; at 075a175 its decoy took number 6. Every clone number, and
    the decoy's, must be one no input pattern already names."""
    seen = []
    real = B.legato_tie_clones

    def spy(patterns, rows, tracks, cloneable, first_number, last_number=0,
            log=None):
        out = real(patterns, rows, tracks, cloneable, first_number,
                   last_number, log=log)
        seen.append((_refs(patterns), [c for _, c in out[1]]))
        return out

    monkeypatch.setattr(B, "legato_tie_clones", spy)
    lines = []
    convert(str(CORPUS / "Kings_of_the_Beach_ingame.sid"), log=lines.append,
            **dict(FIXED, legal_restart=True))
    assert seen, "legato_tie_clones never ran"
    (refs, clones), = seen
    assert 6 in refs                       # the dangling byte is still there
    assert not set(clones) & refs, (clones, sorted(refs))
    decoys = [int(m.group(1)) for x in lines
              if (m := re.search(r"decoy legato record (\d+)", x))]
    assert not set(decoys) & refs, (decoys, sorted(refs))
    assert any("below dangling instrument $6" in x for x in lines), lines
