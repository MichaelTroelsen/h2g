"""A record a note can end on a slide frame of keeps that frame for the rest.

Opened as keep-auf-wiedersehen-monty-record-4-s by real-firstwave-stale-init-
mid-slide. `_cut_share` declines the quantised first slide frame for every
note of a record as soon as one played note ends on it; Auf_Wiedersehen_Monty
record 4 has 3-frame notes among ~600 longer ones, and the longer ones lost
the frame's travel (travel_ratio 0.9344 -> 0.9308). The record is now split:
its main block keeps the frame (`keep_slide`), a second one declines it, and
`_cut_note_pass` points the notes that can end on it at the second -- only
where every such note can take the pointer.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter.note_passes import (_cut_durations,  # noqa: E402
                                        _cut_note_pass)
from h2g.patterns import (CMD_SETWAVEPTR, GT_END_PATTERN,  # noqa: E402
                          GT_FIRSTNOTE, GT_NO_NOTE)

MONTY = "Auf_Wiedersehen_Monty"
PITCHES = {48: 45, 50: 32}
SPANS = {1: 23, 4: 38, 7: 8, 8: 8}
N, HOLD, END = GT_FIRSTNOTE, GT_NO_NOTE, GT_END_PATTERN


def _entries(spans, **kw):
    from h2g.convert import _detect_tables
    from h2g.goatwriter.wave_program import _wave_program_entries
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{MONTY}.sid")),
                              lambda *a, **k: None)
    got = _wave_program_entries(sid, det, 4, [], "gts5", 1, 60, written=True,
                                pitches=PITCHES, spans=spans, row_calls=3,
                                **kw)
    return list(zip(*got))


# -- which lengths ----------------------------------------------------------------

def test_a_length_is_cut_when_its_last_call_is_in_a_declined_frame():
    # a one-row note at three calls a row ends on call 2
    assert _cut_durations({1: 23, 4: 38}, [(2, 2)], 3) == {1}
    assert _cut_durations({1: 23, 4: 38}, [(2, 2), (11, 11)], 3) == {1, 4}
    assert _cut_durations({1: 23, 4: 38}, [(3, 3)], 3) == set()


@pytest.mark.parametrize("spans,row_calls", [(None, 3), ({}, 3), ({1: 5}, 0)])
def test_unknown_lengths_are_cut_nowhere(spans, row_calls):
    assert _cut_durations(spans, [(0, 99)], row_calls) == set()


# -- the two programs ---------------------------------------------------------------

@needs_corpus
def test_the_declined_frames_are_reported():
    frames = []
    _entries(SPANS, cut_out=frames)
    assert frames == [(2, 2)]


@needs_corpus
def test_keep_slide_is_the_block_without_the_lengths():
    assert _entries(SPANS, keep_slide=True) == _entries(None)
    assert _entries(SPANS, keep_slide=True) != _entries(SPANS)
    frames = []
    _entries(SPANS, keep_slide=True, cut_out=frames)
    assert frames == []


# -- the pointer ----------------------------------------------------------------------

def _pat(*rows):
    out = []
    for r in rows:
        out += list(r)
    return out + [END, 0, 0, 0]


def test_a_short_note_is_pointed_and_a_long_one_is_not():
    # instrument 5: a 1-row note, then a 3-row one, both closed by a note
    pat = _pat((N, 5, 0, 0), (N + 2, 0, 0, 0), (HOLD, 0, 0, 0),
               (HOLD, 0, 0, 0), (N + 4, 6, 0, 0))
    stats = {}
    out = _cut_note_pass([pat], {5: (0x2A, {1})}, [[0]], stats=stats)
    assert out[0][2:4] == [CMD_SETWAVEPTR, 0x2A]
    assert out[0][6:8] == [0, 0]
    assert stats == {5: {"placed": 1, "missed": 0}}
    assert pat[2] == 0                       # a copy, not an edit in place


def test_a_busy_command_column_is_a_miss_not_an_overwrite():
    pat = _pat((N, 5, 0x08, 0x10), (N + 2, 6, 0, 0))
    stats = {}
    out = _cut_note_pass([pat], {5: (0x2A, {1})}, [[0]], stats=stats)
    assert out[0] == pat
    assert stats == {5: {"placed": 0, "missed": 1}}


def test_a_note_running_to_the_patterns_end_is_pointed_when_it_may_be_short():
    pat = _pat((N, 5, 0, 0), (HOLD, 0, 0, 0))
    stats = {}
    out = _cut_note_pass([pat], {5: (0x2A, {3})}, [[0]], stats=stats)
    assert out[0][2:4] == [CMD_SETWAVEPTR, 0x2A]
    # ... and not once it is already longer than any cut length
    pat = _pat((N, 5, 0, 0), (HOLD, 0, 0, 0), (HOLD, 0, 0, 0),
               (HOLD, 0, 0, 0), (HOLD, 0, 0, 0))
    out = _cut_note_pass([pat], {5: (0x2A, {3})}, [[0]])
    assert out[0] == pat


def test_other_instruments_are_left_alone():
    pat = _pat((N, 6, 0, 0), (N + 2, 0, 0, 0))
    assert _cut_note_pass([pat], {5: (0x2A, {1})}, [[0]]) == [pat]


# -- the whole file ---------------------------------------------------------------------

def _convert(**over):
    from h2g.convert import convert
    import fidelity
    doc = json.loads((PYTHON_ROOT.parent / "presets.json")
                     .read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, f"{MONTY}.sid")
    opts.update(over)
    log = []
    got = convert(str(CORPUS / f"{MONTY}.sid"), log.append, **opts)
    return got, log


@needs_corpus
def test_monty_splits_record_5_and_points_its_short_notes():
    _, log = _convert()
    line = [m for m in log if m.startswith("Cut-note programs")]
    assert any("05: 3 note(s) pointed" in m and "missed" not in m
               for m in line), line


@needs_corpus
def test_a_record_that_cannot_be_pointed_whole_stays_whole():
    # the lines for 03 and 07 say so: nothing placed, so the record keeps
    # the declining program for every note (the shape before this pass)
    _, log = _convert()
    assert any("03 stays whole" in m for m in log)


@needs_corpus
def test_a_test_bit_firstwave_plans_no_split():
    # no lengths reach the block there, so there is nothing to split
    _, log = _convert(real_firstwave_instruments=(), no_test_restart=False)
    assert not [m for m in log if m.startswith("Cut-note programs")]


@needs_corpus
def test_one_missed_note_keeps_the_record_whole(monkeypatch):
    # the dry run reports a miss on every record: none may be split, so no
    # second block is laid out and no pointer is written
    from h2g.goatwriter import build
    real = build._cut_note_pass

    def spy(patterns, targets, tracks=None, log=None, stats=None):
        out = real(patterns, targets, tracks, log, stats)
        if log is None and stats is not None:
            for st in stats.values():
                st["missed"] += 1
        return out
    monkeypatch.setattr(build, "_cut_note_pass", spy)
    _, log = _convert()
    assert any("05 stays whole" in m for m in log)
    assert not any("note(s) pointed" in m for m in log)
