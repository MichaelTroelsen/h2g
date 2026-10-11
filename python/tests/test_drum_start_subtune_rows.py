"""The drum sweep's length is counted in the START subtune's rows.

Bump_Set_Spike plays its `$0F0C` drum (instrument 1) at 10 calls a row in
subtune 0, the tune, and at 8 in subtune 1. The sweep is sized from the row
(`wavetable._drum_duration_steps`) and one wavetable serves both subtunes, so
the file-wide shortest row -- right for the gatetimer, where a value too large
stops the song -- gave the tune 13 steps where its rows leave room for 17:
`$3DC` against the original's `$500` (traced at 120 s, presets, v0.5.524).

Two mechanisms, one helper each:

* `tracks.start_subtune_row_calls` / `InstrumentRowCalls.start_rows`: the row
  each instrument is played at in the start subtune, carried beside the
  shortest-row dict the safety bounds read;
* `wavetable._record_row_calls`: prefers it, falls back to the shortest row and
  then to the file's.

It is declined where the start subtune's tempo is not the player's own gate
unit (`convert._drum_start_group`): Rasputin's gate says 2 frames a unit
(`[4, 4]` calls at `-S2`) and its subtune opens `$FE 02`, rows of 3 frames
(`[6, 5]`). The original's drum counter still steps in the gate's unit and its
sweep reads `$0300` on every record; the formula gives `$0400` on the shortest
row and `$0500` on the start subtune's, so a row that is not the unit is not
sized by. Figures are historical (v0.5.524, 120 s, presets).

A clone of the record per row length would be exact, and Bump_Set_Spike has no
room: its wavetable is 255 of 255.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter.constants import WAVECMD_PORTADOWN          # noqa: E402
from h2g.goatwriter.primitives import _gate_calls               # noqa: E402
from h2g.goatwriter.wavetable import _record_row_calls          # noqa: E402
from h2g.convert import _drum_start_group                       # noqa: E402
from h2g.tracks import (InstrumentRowCalls,                     # noqa: E402
                        instrument_row_calls, start_subtune_row_calls)

END = 0xFF


def _pattern(*rows):
    """Rows of (note, instrument); the 4-byte rows Goattracker stores."""
    out = []
    for note, instr in rows:
        out += [note, instr, 0, 0]
    return out + [END, 0, 0, 0]


def _song():
    # Two subtunes, three voices each. Instrument 5 is played by both, 6 only
    # by subtune 1, 7 only by subtune 0; voice 2 of subtune 1 opens on a row
    # naming no instrument, so it plays instrument 1 unnamed.
    patterns = [
        _pattern((0x40, 5), (0x41, 7)),        # 0
        _pattern((0x40, 5)),                   # 1
        _pattern((0x40, 5)),                   # 2
        _pattern((0x40, 6), (0x41, 5)),        # 3
        _pattern((0x40, 5)),                   # 4
        _pattern((0x40, 0), (0x41, 6)),        # 5: no instrument on row 0
    ]
    tracks = [[0, END, 0], [1, END, 0], [2, END, 0],
              [3, END, 0], [4, END, 0], [5, END, 0]]
    return tracks, patterns


def test_start_rows_are_the_start_subtunes_alone():
    tracks, patterns = _song()
    assert start_subtune_row_calls(tracks, patterns, [10, 8], 0) == {
        5: 10, 7: 10}
    assert start_subtune_row_calls(tracks, patterns, [10, 8], 1) == {
        5: 8, 6: 8, 1: 8}


def test_an_unnamed_first_row_charges_instrument_one():
    tracks, patterns = _song()
    assert 1 not in start_subtune_row_calls(tracks, patterns, [10, 8], 0)
    assert start_subtune_row_calls(tracks, patterns, [10, 8], 1)[1] == 8


@pytest.mark.parametrize("start_group, tempos, tracks_cut", [
    (2, [10, 8], 0),            # past the last subtune
    (-1, [10, 8], 0),
    (0, [], 0),                 # no tempo list
    (0, [10, 8], 3),            # a split shifted the numbering
])
def test_declines_where_the_numbering_does_not_line_up(start_group, tempos,
                                                       tracks_cut):
    tracks, patterns = _song()
    if tracks_cut:
        tracks = tracks[:tracks_cut]
    assert start_subtune_row_calls(tracks, patterns, tempos, start_group) == {}


def test_the_safety_dict_is_unchanged_and_start_rows_ride_beside_it():
    tracks, patterns = _song()
    plain = instrument_row_calls(tracks, patterns, [10, 8])
    both = instrument_row_calls(tracks, patterns, [10, 8], start_group=0)
    assert isinstance(both, InstrumentRowCalls)
    assert dict(both) == dict(plain)
    assert plain.start_rows == {}
    assert both.start_rows == {5: 10, 7: 10}
    # the shortest row: instrument 5 is played at 10 and 8
    assert both[5] == 8 and both[7] == 10


class _Sid:
    def __init__(self, start_song):
        self.start_song = start_song


@pytest.mark.parametrize("start_song, tempos, units, want", [
    (1, [10, 8], [10, 8], 0),           # the gate's own rows: the start subtune
    (2, [10, 8], [10, 8], 1),
    (1, [10, 8], None, 0),              # forced tempo: no gate list, same
    (1, [6, 5], [4, 4], None),          # Rasputin: an opening $FE rewrote it
    (2, [4, 5], [4, 4], None),
    (3, [10, 8], [10, 8], None),        # a start song past the subtunes
    (0, [10, 8], [10, 8], 0),           # an unreadable header reads as 1
    (1, [], None, None),
])
def test_drum_start_group(start_song, tempos, units, want):
    assert _drum_start_group(_Sid(start_song), tempos, units) == want


def test_record_row_calls_order():
    both = InstrumentRowCalls({3: 8, 4: 8})
    both.start_rows = {3: 10}
    assert _record_row_calls(both, 3, 99) == 10      # the start subtune's
    assert _record_row_calls(both, 4, 99) == 8       # else the shortest
    assert _record_row_calls(both, 5, 99) == 99      # else the file's
    assert _record_row_calls({3: 8}, 3, 99) == 8     # a plain dict has no start
    assert _record_row_calls(None, 3, 99) == 99


def _converted(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng[0] if isinstance(sng, tuple) else sng


def _sweep(song, number):
    """(AD, SR, CMD_PORTADOWN entries, their speed index) of an instrument."""
    ins = song.instruments[number - 1]
    wt = song.tables["WTBL"]
    k = ins.wave_ptr - 1
    steps = []
    while wt[k][0] != 0xFF:
        if wt[k][0] == WAVECMD_PORTADOWN:
            steps.append(wt[k][1])
        k += 1
    return ins.ad, ins.sr, steps


@needs_corpus
def test_bump_set_spike_tune_sweep_is_sized_by_its_own_rows():
    import songview
    s = songview.parse_sng(_converted("Bump_Set_Spike"))
    ad, sr, steps = _sweep(s, 1)
    assert (ad, sr) == (0x0F, 0x0C)
    # 10-call rows in the start subtune, 8 in subtune 1 (the shortest, which
    # gave 13): a typical note of 4 rows leaves (4 - 2) * 10 calls less one
    # working frame.
    assert len(steps) == 2 * 10 - _gate_calls(3, 9), steps
    assert len(set(steps)) == 1


@needs_corpus
@pytest.mark.parametrize("number, ad, sr", [(2, 0x09, 0x09),
                                            (4, 0x0A, 0x09),
                                            (10, 0x0F, 0x0F)])
def test_rasputin_keeps_the_shortest_row(number, ad, sr):
    """Declined, so its bytes stay: 8 steps of `$0080` on the 5-call row.

    (4 - 2) * 5 - 2 = 8. The start subtune's own 6-call row would give 10
    and the original's `$0300` is 6 -- the row that would size it is the
    gate's 4, which `convert` does not carry for a subtune an opening `$FE`
    rewrote (an open follow-up, not a property worth pinning at 8).
    """
    import songview
    s = songview.parse_sng(_converted("Rasputin"))
    got_ad, got_sr, steps = _sweep(s, number)
    assert (got_ad, got_sr) == (ad, sr)
    assert len(steps) == 2 * 5 - 2, steps
