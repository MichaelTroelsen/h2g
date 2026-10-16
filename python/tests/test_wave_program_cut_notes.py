"""A slide frame a note can END on stays on the note, under a written firstwave.

Opened as real-firstwave-stale-init-mid-slide by wave-program-slide-frames-
0797-family. The packed player's note-init call writes the waveform alone
(`player.s` `jmp mt_loadregswaveonly`), so under a real firstwave
(`real_firstwave_instruments`, `no_test_restart`) the next note's gate rises
on the pitch the previous one LEFT -- and a harness, or a listener, names the
attack from it. The -S1 slide frames write a quantised `note - sum`
(`_slide_semitones`), so a note cut on one of them leaves a pitch a semitone
or two off the note and the next attack is named after it.

Auf_Wiedersehen_Monty `$0F26`-family record 4 (`slide $41 $01C0 / ...`) is
played on notes of one row (three frames: init, the noise, the first slide
frame) as well as longer ones. Nine of its attacks were named C-4 where the
original has D-4, and the voice's melody went 0.9876 -> 0.9830. The frame is
declined (it writes the note) when a note of the instrument ends on it; the
deeper frames are not, because a note that reaches them has already left the
note's pitch and the bounce back up would be a reversal the original does not
make.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter.wave_program import (  # noqa: E402
    SLIDE_CUT_SHARE, _cut_share)
from h2g.patterns import (GT_END_PATTERN, GT_FIRSTNOTE, GT_NO_NOTE,  # noqa: E402
                          GT_ORDER_RESTART, median_played_durations,
                          played_duration_histograms)

BASE = 0x00
MONTY = "Auf_Wiedersehen_Monty"
# Monty record 4 as the converter reads it at the start of the song: notes of
# 1, 4, 7 and 8 rows at three play calls a row, played on two pitches.
PITCHES = {48: 45, 50: 32}
SPANS = {1: 23, 4: 38, 7: 8, 8: 8}


def _entries(i, spans, pitches=PITCHES, row_calls=3, written=True):
    from h2g.convert import _detect_tables
    from h2g.goatwriter.wave_program import _wave_program_entries
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{MONTY}.sid")),
                              lambda *a, **k: None)
    got = _wave_program_entries(sid, det, i, [], "gts5", 1, 60,
                                written=written, hold_travel=False,
                                pitches=pitches, spans=spans,
                                row_calls=row_calls)
    assert got is not None
    return list(zip(*got))


# -- the share ----------------------------------------------------------------

def test_a_note_is_cut_on_the_call_it_ends_on():
    # one row of three calls is calls 0, 1, 2: it ends on call 2
    assert _cut_share({1: 23, 4: 38}, 3, 2, 2) == pytest.approx(23 / 61)
    assert _cut_share({1: 23, 4: 38}, 3, 3, 3) == 0.0
    assert _cut_share({1: 23, 4: 38}, 3, 11, 11) == pytest.approx(38 / 61)


def test_a_wider_entry_covers_each_of_its_calls():
    # at -S2 an entry plus its hold is two calls: either one is the last
    assert _cut_share({1: 1}, 3, 1, 2) == 1.0
    assert _cut_share({1: 1}, 3, 3, 4) == 0.0


@pytest.mark.parametrize("spans,row_calls", [(None, 3), ({}, 3), ({1: 5}, 0),
                                             ({1: 0}, 3)])
def test_unknown_lengths_cut_nothing(spans, row_calls):
    assert _cut_share(spans, row_calls, 0, 99) == 0.0


def test_any_ending_note_is_enough():
    assert SLIDE_CUT_SHARE == 0.0


# -- the distribution ---------------------------------------------------------

def test_the_histogram_is_what_the_median_reduces():
    n, hold, end = GT_FIRSTNOTE, GT_NO_NOTE, GT_END_PATTERN
    # instrument 2: a note two rows long, then the pattern's last event, which
    # runs on to the pattern's end (3 rows) and into the successor's first
    # event -- the same pattern, via the restart, whose first row is an event
    patterns = [[n, 2, 0, 0, hold, 0, 0, 0, n + 2, 0, 0, 0,
                 hold, 0, 0, 0, hold, 0, 0, 0, end, 0, 0, 0]]
    tracks = [[0, GT_ORDER_RESTART, 0]]
    hist = played_duration_histograms(tracks, patterns)
    assert hist == {2: {2: 1, 3: 1}}
    # the median is the lower middle of that, as it always was
    assert median_played_durations(tracks, patterns) == {2: 2}
    assert median_played_durations(tracks, patterns, histograms=True) == hist


# -- the emitted block --------------------------------------------------------

@needs_corpus
def test_the_first_slide_frame_a_note_ends_on_stays_on_the_note():
    got = _entries(4, SPANS)
    # entry 1 is the first slide frame: init call 0, the noise call 1, this
    # call 2 -- the last call of a one-row note
    assert got[1] == (0x41, BASE)
    # the deeper frames are still the quantised counts: a note that reaches
    # them is past the note's pitch, and a bounce up to it would reverse
    assert got[2][1] not in (BASE, 0x80) and got[3][1] not in (BASE, 0x80)


@needs_corpus
def test_without_the_lengths_it_is_the_quantised_block():
    got = _entries(4, None)
    assert got[1] == (0x41, 0x7E)           # -2 semitones
    assert got[2:4] == [(0x40, 0x7D), (0x40, 0x7C)]


@needs_corpus
def test_no_note_ending_there_leaves_the_frame_alone():
    assert _entries(4, {4: 38, 7: 8, 8: 8}) == _entries(4, None)


@needs_corpus
def test_a_frame_in_the_middle_of_the_run_is_left_quantised():
    # notes end on the SECOND slide frame (call 3): declining it would write
    # the note between two shifted frames, a reversal on every longer note
    assert _entries(4, {1: 5}, row_calls=1) == _entries(4, None)
    got = _entries(4, {1: 4}, row_calls=4)    # ends on call 3
    assert got == _entries(4, None)


@needs_corpus
def test_the_row_in_calls_places_the_end():
    # the same one-row note at two calls a row ends on call 1, the noise
    # frame, and no slide frame is touched
    assert _entries(4, {1: 23}, row_calls=2) == _entries(4, None)


# -- where the lengths reach the block ------------------------------------------

def _spans_seen(monkeypatch, **over):
    from h2g.convert import convert
    from h2g.goatwriter import wavetable
    import fidelity
    doc = json.loads((PYTHON_ROOT.parent / "presets.json")
                     .read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, f"{MONTY}.sid")
    opts.update(over)
    seen = []
    real = wavetable._wave_program_entries

    def spy(*a, **k):
        seen.append(k.get("spans"))
        return real(*a, **k)
    monkeypatch.setattr(wavetable, "_wave_program_entries", spy)
    convert(str(CORPUS / f"{MONTY}.sid"), lambda *a, **k: None, **opts)
    return seen


@needs_corpus
def test_a_written_firstwave_hands_the_block_its_lengths(monkeypatch):
    seen = _spans_seen(monkeypatch)
    assert seen and any(seen)


@needs_corpus
def test_a_test_bit_firstwave_hands_it_none(monkeypatch):
    # the next note's init frame is silent there: nothing to protect, so the
    # block is byte-for-byte the one it always was
    seen = _spans_seen(monkeypatch, real_firstwave_instruments=(),
                       no_test_restart=False)
    assert seen and not any(seen)
