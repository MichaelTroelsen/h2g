"""A multi-voice routing union admits the clear of a voice that also sweeps.

`h2g.goatwriter.filters._classic_clearing_instruments`. The one-voice mask gate
(`tests/test_classic_clear_mask.py`) refused every file whose routed records
route more than one voice, as a cross-voice race. Knucklebusters ($F4 | $F2)
and Lightforce ($F4 | $F1 | $F3) are not one: the clear is the NEXT NOTE OF THE
VOICE THAT WAS SWEEPING, so the original's `$D417` goes `$F4 -> $00` when that
note plays and ours must too (Knucklebusters_1: ours kept routing the 48 of
every 96 frames the original has the filter off, `band` 65% -> 98%).
Dragons_Lair_Part_II plays its clear on a voice that names no routed record,
which clears another voice's circuit; admitting it dropped `band` 94% -> 32%.
"""
import pytest

from corpus import needs_corpus
from h2g.goatwriter import filters
from h2g.goatwriter.filters import _classic_clearing_instruments
from test_classic_clear_mask import (CLEAR, ROUTE_V0, ROUTE_V1, ROUTE_V2,
                                     _gate)


def test_the_clear_of_a_sweeping_voice_fires_under_a_two_voice_union():
    """Knucklebusters' shape: record 1 routes voice 2 ($F4), record 2 voice 1
    ($F2), record 0 is the clear; every voice names a routed record AND the
    clear."""
    recs = [(CLEAR, True), (ROUTE_V2, True), (ROUTE_V1, True)]
    assert _gate(recs, [[0, 1], [0, 1, 2], [0, 1]]) == {0}


def test_a_clear_on_a_voice_that_sweeps_nothing_refuses():
    """Dragons_Lair_Part_II's shape: the routed records are on voices 0 and 1,
    the clear is played on voice 2 -- the original lets voices 0/1's own
    writes win, so a Goattracker clear would end a circuit still running."""
    recs = [(ROUTE_V1, True), (ROUTE_V0, True), (CLEAR, True)]
    assert _gate(recs, [[0], [1], [2]]) == set()
    # Any one voice outside the sweeping set is enough to refuse, though
    # voice 0 sweeps AND clears.
    assert _gate(recs, [[0, 2], [1], [2]]) == set()
    # Without the outside voice the same clear fires.
    assert _gate(recs, [[0, 2], [1], []]) == {2}


def test_the_short_circuited_gate_is_the_old_refusal(monkeypatch):
    """With the multi-voice reading off, the two-voice union refuses again."""
    recs = [(CLEAR, True), (ROUTE_V2, True), (ROUTE_V1, True)]
    voices = [[0, 1], [0, 1, 2], [0, 1]]
    assert _gate(recs, voices) == {0}
    monkeypatch.setattr(filters, "CLASSIC_CLEAR_MULTI_VOICE", False)
    assert _gate(recs, voices) == set()


def test_a_one_voice_union_is_untouched_by_the_switch(monkeypatch):
    """Nemesis_the_Warlock's shape: the clear on a voice that routes nothing
    still clears under a one-voice mask, switch or no switch."""
    recs = [(ROUTE_V1, True), (CLEAR, True)]
    voices = [[], [0], [1]]
    assert _gate(recs, voices) == {1}
    monkeypatch.setattr(filters, "CLASSIC_CLEAR_MULTI_VOICE", False)
    assert _gate(recs, voices) == {1}


# Under shipped presets, the three files whose routed union names several voices
# AND which name an enabled clear record somewhere (v0.5.674, `-t 180`):
# Knucklebusters' record 0 and Lightforce's record 2 are admitted,
# Dragons_Lair_Part_II's 23 is refused. Bangkok_Knights' 14 and Delta_Mix's 23
# are never named, so they are empty on either reading.
MULTI_VOICE_CLEARS = {
    "Knucklebusters": {0},
    "Lightforce": {2},
    "Dragons_Lair_Part_II": set(),
    "Bangkok_Knights": set(),
    "Delta_Mix-E-Load_loader": set(),
}


@needs_corpus
@pytest.mark.parametrize("stem", sorted(MULTI_VOICE_CLEARS))
def test_the_multi_voice_gate_fires_on_exactly_the_measured_records(
        stem, monkeypatch):
    from test_filter import _emitter_inputs
    sid, det, tracks, patterns, instr_base = _emitter_inputs(stem, monkeypatch)
    assert det.filter is not None and det.ilv_filter is None
    got = _classic_clearing_instruments(sid, det, tracks, patterns, instr_base)
    assert got == MULTI_VOICE_CLEARS[stem], (stem, got)
    monkeypatch.setattr(filters, "CLASSIC_CLEAR_MULTI_VOICE", False)
    assert _classic_clearing_instruments(
        sid, det, tracks, patterns, instr_base) == set(), stem
