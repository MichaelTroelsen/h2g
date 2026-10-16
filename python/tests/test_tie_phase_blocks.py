"""A tie landing on a counter residue its record's block was not laid for.

`convert(tie_restart=True)` respells a heard tie in the classic no-legato-
marker players as a legato clone that restarts its record's wavetable block
(tests/test_tie_restart.py). A block that carries an arpeggio carries the
counter's residue on a fresh attack, and the counter is global in the
original, so a clone restarting the block laid for another residue puts the
octave out of phase. Until this change `_phase_locked_ties` kept those ties
on `CMD_TONEPORTA 00` (the old spelling, which runs the program on); read at
39b5de2 + the cycle-2 merge (9d1ff22), under presets with the option forced:

    Rasputin 8, Gremlins 5, Geoff_Capes_Strongman_Challenge 2 (all "arpeggio
    phase", one residue each: record 8 at residue 2, record 11 at 1,
    record 8 at 1 -- no phase clone of any of them existed, because the
    split plan votes on untied notes only), Las_Vegas_Video_Poker 6 + 16
    gated, Chimera 477 row-locked.

A row played on ONE residue now restarts a block laid for that residue: a
phase clone's where the plan made one, the record's own where the residue
changes nothing, else one `_wavetable_layout(tie_blocks=...)` lays out beside
the phase clones -- the same `record_entries(phase=residue)` call a phase
clone's block comes from, so a fresh attack at that residue and a tie
landing on it play the same wavetable. HISTORICAL figures.
"""
import json
import pathlib
from types import SimpleNamespace

import pytest

from h2g import goatwriter as G
from h2g.convert import convert
from h2g.goatwriter import arpeggio as GA
from h2g.goatwriter import build as GB
from h2g.goatwriter import note_passes as GN
from h2g.goatwriter import wavetable as GW
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TIE = [G.CMD_TONEPORTA, 0x00]
END = [0xFF, 0, 0, 0]
TRACKS = [[0, 0xFF, 0x00]] * 3


# --- which block a (record, residue) already has --------------------------

def test_a_block_is_found_where_it_was_laid_out():
    clones = [(8, 20, 2)]
    away = lambda g, x: x != 0                      # noqa: E731
    assert GB._tie_block_source(8, 2, 0, away, clones) == "clone"
    assert GB._tie_block_source(8, 0, 0, away, clones) == "record"
    # A residue the record's block does not depend on is the record's.
    assert GB._tie_block_source(8, 1, 0, lambda g, x: False, []) == "record"
    # Another record's clone is not this record's.
    assert GB._tie_block_source(9, 2, 0, away, clones) is None
    assert GB._tie_block_source(8, 1, 0, away, clones) is None
    # No majority residue: nothing says what the record's block is.
    assert GB._tie_block_source(8, 0, None, away, []) is None


def test_only_single_residue_arpeggio_phase_rows_want_a_block():
    verdicts = {
        (0, 1): ("arpeggio phase", 8, 1),
        (0, 2): ("arpeggio phase", 8, 1),          # the same pair: one block
        (0, 3): ("arpeggio phase", 8, None),       # several residues
        (0, 4): ("row-locked arpeggio", 5, None),
        (0, 5): ("gated arpeggio phase", 6, None),
        (0, 6): ("arpeggio phase", 8, 2),          # a clone already has it
        (0, 7): ("arpeggio phase", 9, 1),
    }
    got = GB._tie_blocks_wanted(verdicts, {8: 0, 9: 0},
                                lambda g, x: x != 0, [(8, 20, 2)])
    assert got == [(8, 1), (9, 1)]


# --- the rows: respelled or kept ---------------------------------------------

def _locked(monkeypatch, residues, block_start=None):
    monkeypatch.setattr(GA, "arp_row_residues", lambda *a: residues)
    sid = SimpleNamespace(data=bytes(64))
    det = SimpleNamespace(instr_start=8, instr_stride=8)
    pat = [0x60, 1, 0, 0,  0x62, 0, *TIE,  0x64, 0, *TIE,  0x66, 0, *TIE,
           *END]
    respelled: dict = {}
    kept = GB._phase_locked_ties(
        sid, det, {(0, 1), (0, 2), (0, 3)}, TRACKS, [pat], {1: 0}, 0, {1: 0},
        {}, {}, {}, [], lambda g, x: x != 0, block_start=block_start,
        respelled=respelled)
    return kept, respelled


def test_a_single_residue_row_restarts_the_block_laid_for_it(monkeypatch):
    """Row 1 lands on residue 1 only, and a block exists for it (start 40):
    respelled onto it. Row 2 is played on two residues: no one block, kept.
    Row 3 lands on residue 2, which no block exists for: kept."""
    res = {(0, 1): {1}, (0, 2): {0, 1}, (0, 3): {2}}
    kept, respelled = _locked(monkeypatch, res,
                              lambda g, x: {1: 40}.get(x, 0))
    assert respelled == {(0, 1): 40}
    assert kept == {(0, 2), (0, 3)}


def test_without_a_block_source_every_mismatched_row_is_kept(monkeypatch):
    res = {(0, 1): {1}, (0, 2): {0, 1}, (0, 3): {2}}
    kept, respelled = _locked(monkeypatch, res)
    assert kept == {(0, 1), (0, 2), (0, 3)} and respelled == {}
    kept, respelled = _locked(monkeypatch, res, lambda g, x: 0)
    assert kept == {(0, 1), (0, 2), (0, 3)} and respelled == {}


def test_a_row_at_its_own_residue_never_needed_a_block(monkeypatch):
    kept, respelled = _locked(monkeypatch,
                              {(0, 1): {0}, (0, 2): {0}, (0, 3): {0}},
                              lambda g, x: 99)
    assert kept == set() and respelled == {}


# --- the clones ---------------------------------------------------------------

def test_row_kind_gives_each_tagged_start_a_clone_of_its_own():
    pat = [0x60, 1, 0, 0,  0x62, 0, *TIE,  0x63, 0, *TIE,  0x64, 0, *TIE,
           0x65, 0, *TIE,  *END]
    tags = {1: 40, 2: 50, 3: 40}                    # row 4 is untagged
    phased: dict = {}
    out, clones, declined = G.legato_tie_clones(
        [pat], {(0, 1), (0, 2), (0, 3), (0, 4)}, TRACKS, {1}, 5,
        row_kind=lambda pn, r: tags.get(r), phased=phased)
    assert not declined
    assert clones == [(1, 5), (1, 6), (1, 7)]
    assert phased == {5: 40, 6: 50}
    assert [out[0][4 * r + 1] for r in range(5)] == [1, 5, 6, 5, 7]


def test_row_kind_composes_with_kind():
    """`kind` still splits a base's clones, and `kinds` still reads it back
    for a tagged clone: the hold-the-pulse rule keys on it."""
    pat = [0x60, 1, 0, 0,  0x62, 0, *TIE,  0x63, 2, *TIE,  *END]
    kinds, phased = {}, {}
    out, clones, declined = G.legato_tie_clones(
        [pat], {(0, 1), (0, 2)}, TRACKS, {1, 2}, 5,
        kind=lambda base, held: held == base, kinds=kinds,
        row_kind=lambda pn, r: 40 if r == 1 else None, phased=phased)
    assert not declined
    assert clones == [(1, 5), (2, 6)]
    assert phased == {5: 40}
    assert kinds == {5: True, 6: False}


def test_without_row_kind_nothing_is_tagged():
    pat = [0x60, 1, 0, 0,  0x62, 0, *TIE,  *END]
    phased: dict = {}
    _out, clones, _d = G.legato_tie_clones([pat], {(0, 1)}, TRACKS, {1}, 5,
                                           phased=phased)
    assert clones == [(1, 5)] and phased == {}


# --- the block: the same one a phase clone of that residue gets ---------------

def _convert_capturing(name):
    """convert(name) under presets with the option forced, with the layout's
    keyword arguments of the main call captured (the lists it fills are
    live)."""
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    opts["tie_restart"] = True
    seen: list = []
    real = GB._wavetable_layout

    def spy(*a, **k):
        r = real(*a, **k)
        if k.get("tie_block_starts") is not None:
            seen.append((a, dict(k), r))
        return r

    GB._wavetable_layout = spy
    try:
        lines: list = []
        sng = convert(str(CORPUS / name), log=lines.append, **opts)
    finally:
        GB._wavetable_layout = real
    return sng, lines, seen, real


@needs_corpus
@pytest.mark.parametrize("name, rows, record, residue", [
    ("Rasputin.sid", 8, 8, 2),
    ("Gremlins.sid", 5, 11, 1),
    ("Geoff_Capes_Strongman_Challenge.sid", 2, 8, 1),
])
def test_a_tie_restarts_the_block_of_the_residue_it_lands_on(
        name, rows, record, residue):
    sng, lines, seen, real = _convert_capturing(name)
    assert not any("out of phase" in line for line in lines), lines
    assert any(f"{rows} tie row(s) restart the block of the residue they "
               "land on (1 block(s) laid out for them)" in line
               for line in lines), lines
    args, kw, (entries, starts, _arp) = seen[-1]
    assert kw["tie_blocks"] == [(record, residue)]
    (at,) = kw["tie_block_starts"]
    assert at
    # The block is a phase clone's block at that residue, entry for entry:
    # lay the same table out with a phase clone in its place.
    kw2 = dict(kw)
    kw2["tie_blocks"], kw2["tie_block_starts"] = None, None
    # Rasputin's own EOR phase split (`wave_eor_split_plan`) already lays
    # clones out ahead of the tie block, so the stand-in goes after them.
    kept = list(kw.get("phase_clones") or [])
    kw2["phase_clones"] = kept + [(record, 99, residue)]
    kw2["phase_clone_starts"] = clone_starts = []
    entries2, _starts2, _a2 = real(*args, **kw2)
    # The stand-in clone may enter its record's block rather than lay one out
    # (`_entered_record_block`, every non-tie phase clone); the tie block keeps
    # its own layout, and the two must play the same stream.
    (x,) = clone_starts[len(kept):]
    assert x
    assert GW._same_wave_stream(entries, at, entries2, x)
    own = starts[record - 1] - 1                     # not the record's block
    assert entries[at - 1:at - 1 + 6] != entries[own:own + 6]
    # And a legato clone points at it.
    song = parse_sng(sng)
    legato = [i for i in song.instruments
              if i.wave_ptr == at and i.gatetimer & G.GATETIMER_LEGATO]
    assert legato, [(i.number, i.wave_ptr) for i in song.instruments]
    assert all(i.firstwave == 0 for i in legato)


@needs_corpus
def test_a_table_with_no_room_keeps_the_old_spelling():
    """Las_Vegas_Video_Poker: its tie rows keep the old spelling where the
    full table has no room for the block they need. Through 0421071 record
    $15's ties landed on residue 1, whose block the full table could not hold
    (`tie phase block: 15 at residue 1 has no room in the wavetable`); ties
    then cast no vote (gate-majority-counts-tied-notes), every tie row kept
    the old spelling and no block was asked for. Since
    lvvp-tie-rows-off-gate-residue a gated record's row on ONE gate residue
    is free where it lands on its block's residue (7 rows) or restarts a
    block laid for it (6 rows on the 2 of 5 wanted blocks that fit: $14 at
    1 and 2); the 15 rows left are the three blocks the table has no room
    for ($14 at 0, $15 at 0 and 1). HISTORICAL counts (4f29873)."""
    _sng, lines, seen, _real = _convert_capturing("Las_Vegas_Video_Poker.sid")
    assert any("(15 gated arpeggio phase)" in line for line in lines), lines
    assert any("6 tie row(s) restart the block of the residue they land on "
               "(5 block(s) laid out for them)" in line
               for line in lines), lines
    assert len(seen[-1][1]["tie_blocks"]) == 5
    assert sorted(seen[-1][1]["tie_block_starts"]).count(0) == 3
    nofit = sorted(line for line in lines
                   if line.startswith("tie phase block:")
                   and "has no room" in line)
    assert len(nofit) == 3, nofit
    assert all("GatePhase" in line for line in nofit), nofit


@needs_corpus
def test_chimeras_row_locked_ties_stay_on_the_old_spelling():
    _sng, lines, seen, _real = _convert_capturing("Chimera.sid")
    assert any("(477 row-locked arpeggio)" in line for line in lines), lines
    assert not any("restart the block of the residue" in line
                   for line in lines)
    assert not seen or not seen[-1][1]["tie_blocks"]
