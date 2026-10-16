"""A pulse-only free note after a LEGATO CLONE of its own record is taken.

The pulse-only variant is correct only where the channel just held the
record the row names (`free_note_variants`: the original sweeps the new
record's rate over the running width; pointer 0 carries on the held
instrument's program). A legato clone of a record carries its pulse pointer
unchanged, so a channel holding clone 28 of instrument 2 runs instrument 2's
own program -- but the walk compared instrument NUMBERS and declined "follows
another instrument". `same_pulse` (clone -> base) closes that.
Measured at 881bbe1 under presets (C:/t/delta-new-rows-kept-full-start):
Delta patterns $B4/$B5 row 11 held 28 (clone of 2); corpus movers Delta,
Knucklebusters, Nineteen, Shockway_Rider (one declined row each taken).
"""
import json
import pathlib

from h2g.convert import convert
from h2g.goatwriter import note_passes as NP

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60


def _pat():
    return [NOTE, 28, 0, 0,          # the channel holds 28, a clone of 5
            NOTE + 1, 5, 0, 0,       # flagged, names 5
            NOTE + 2, 0, 0, 0]


def test_a_clone_of_the_record_counts_as_the_record():
    out, variants, declined = NP.free_note_variants(
        [_pat()], {(0, 1)}, None, {5: 12}, 30, pulse_only={5},
        same_pulse={28: 5})
    assert variants == [(5, 30)] and not declined
    assert out[0][4:8] == [NOTE + 1, 30, 0, 0]


def test_without_the_map_the_row_still_declines():
    _out, variants, declined = NP.free_note_variants(
        [_pat()], {(0, 1)}, None, {5: 12}, 30, pulse_only={5})
    assert not variants and declined == {(0, 1)}


def test_a_clone_of_another_record_still_declines():
    _out, variants, declined = NP.free_note_variants(
        [_pat()], {(0, 1)}, None, {5: 12}, 30, pulse_only={5},
        same_pulse={28: 6})
    assert not variants and declined == {(0, 1)}


def _free_line(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    lines = []
    convert(str(CORPUS / name), log=lines.append,
            **fidelity._preset_opts(doc, name))
    free = [ln for ln in lines if ln.startswith("Free note (bit 7)")]
    assert len(free) == 1, lines
    return free[0]


@needs_corpus
def test_nineteen_takes_its_row_after_a_legato_clone():
    # Was "0 flagged note row(s) on 0 variant(s) ..., 1 kept the full start
    # (1 follows another instrument)".
    assert "1 flagged note row(s) on 1 variant(s)" in _free_line(
        "Nineteen.sid")


@needs_corpus
def test_delta_keeps_two_declines_and_names_them():
    line = _free_line("Delta.sid")
    assert "137 flagged note row(s)" in line, line
    assert ("2 kept the full start (1 follows an unsettled instrument; "
            "1 last row, successor entered holding another instrument)"
            ) in line, line
