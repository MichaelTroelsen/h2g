"""Per-note phase clones for the outer-gated flat clocks, where room exists.

Task pitch-seq-room-aware-phase-clones. `_pitch_seq_outer_flat_clock` reads
bit $10's clock on 24 classic outer-gated files, and `pitch_seq_phase_split_plan`
was None for all of them: with the clones on, 12 existing tests failed
(Star_Paws lost its entry-instrument split, Saboteur_II left rows past the
table, Lightforce's and Shockway_Rider's free-note passes moved) and
Chain_Reaction's clones logged "has no block of its own". Two checks now make
them land only where there is room:

* `build._phase_split_displaces_passes` -- the entry-instrument split and the
  free-note respell stand down beside ANY phase split, so a file on which
  either would change a byte keeps the record's majority phase;
* a dry `_wavetable_layout` of the plan, which names the clones the
  wavetable has no block for, and the plan is made again without them.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.goatwriter import note_passes as NP
from h2g.convert import _detect_tables, convert
from h2g.sidfile import load_sid

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE, TIE, END = G.GT_FIRST_NOTE, G.CMD_TONEPORTA, 0xFF
SPLIT = "pitch phase split: "


def _log(name, monkeypatch=None):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    lines = []
    convert(str(CORPUS / name), log=lines.append, **F._preset_opts(doc, name))
    return lines


def _plan(lines):
    return [ln for ln in lines
            if ln.startswith(SPLIT) and ln[len(SPLIT):].split(" ")[1]
            == "clone(s)" and "[" in ln]


# --- the corpus ---------------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("name", ["Trans-Atlantic_Balloon_Challenge.sid",
                                  "Chain_Reaction.sid", "Zoolook.sid",
                                  "After_8.sid", "Rock_Tells_the_Tale.sid",
                                  "Thundercats.sid"])
def test_the_clones_land_where_no_pass_stands_down_and_the_table_has_room(name):
    lines = _log(name)
    assert len(_plan(lines)) == 1, lines
    assert not any("has no block of its own" in ln for ln in lines), lines
    assert not any("not splitting" in ln for ln in lines), lines


@needs_corpus
@pytest.mark.parametrize("name,kept", [
    ("Star_Paws.sid", "Entry instrument split"),
    ("Lightforce.sid", "Free note (bit 7)"),
    ("Shockway_Rider.sid", "Free note (bit 7)"),
    ("Saboteur_II.sid", "Free note (bit 7)"),
    ("Nineteen.sid", "Free note (bit 7)")])
def test_a_file_whose_standing_down_pass_has_work_keeps_the_majority_phase(
        name, kept):
    lines = _log(name)
    assert any(ln.startswith(SPLIT + "not splitting") for ln in lines), lines
    assert not _plan(lines), lines
    assert any(ln.startswith(kept) for ln in lines), (kept, lines)


@needs_corpus
def test_clones_the_wavetable_has_no_block_for_are_dropped_before_numbering():
    """Mr_Meaner: 7 clones planned, 4 with no block (records 01 and 0F's
    second and third residues); the plan is made again without them, so no
    instrument is numbered, copied and renamed for nothing."""
    lines = _log("Mr_Meaner.sid")
    dropped = [ln for ln in lines if ln.startswith(SPLIT) and
               "wavetable has no room for stay on their record" in ln]
    assert len(dropped) == 1 and dropped[0].startswith(SPLIT + "4 clone(s)")
    plan, = _plan(lines)
    assert plan.startswith(SPLIT + "3 clone(s)"), plan
    assert not any("has no block of its own" in ln for ln in lines), lines


@needs_corpus
def test_the_divided_and_zero_page_clocks_are_not_room_aware():
    """Food_Feud's divided clock and Mega_Apocalypse's zero-page one plan once,
    as they always did."""
    for name, outer in [("Food_Feud.sid", False), ("Mega_Apocalypse.sid", False),
                        ("Trans-Atlantic_Balloon_Challenge.sid", True)]:
        sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                                  lambda *a, **k: None)
        assert G.pitch_seq_outer_gated(sid, det) is outer, name


# --- the dry questions are no calls of the passes -----------------------------

def _two_entry_song():
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, TIE, 0, NOTE + 1, 0, TIE, 0, END, 0, 0, 0]]
    tracks = [[0, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    return pats, tracks


def test_entry_split_has_work_agrees_with_the_pass_and_is_no_call_of_it(
        monkeypatch):
    pats, tracks = _two_entry_song()
    called = []
    real = NP.entry_instrument_split
    monkeypatch.setattr(NP, "entry_instrument_split",
                        lambda *a, **k: called.append(1) or real(*a, **k))
    assert NP.entry_split_has_work(tracks, pats, {(2, 0)}) is True
    assert NP.entry_split_has_work(tracks, pats, set()) is False
    assert called == []
    assert bool(real(tracks, pats, {(2, 0)})[2]) is True


def test_free_note_has_work_agrees_with_the_pass_and_is_no_call_of_it(
        monkeypatch):
    pat = [NOTE, 5, 0, 0, NOTE + 1, 0, 0, 0, NOTE + 2, 6, 0, 0, END, 0, 0, 0]
    called = []
    real = NP.free_note_variants
    monkeypatch.setattr(NP, "free_note_variants",
                        lambda *a, **k: called.append(1) or real(*a, **k))
    assert NP.free_note_has_work([pat], {(0, 1)}, None, {5: 12}, 30) is True
    assert NP.free_note_has_work([pat], {(0, 1)}, None, {}, 30) is False
    assert NP.free_note_has_work([pat], set(), None, {5: 12}, 30) is False
    assert called == []
    assert real([pat], {(0, 1)}, None, {5: 12}, 30)[1] == [(5, 30)]
