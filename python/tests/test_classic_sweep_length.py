"""The classic filter sweep lasts the voice's note, not one $7F-call row.

`_filter_entries` wrote `[params, set-cutoff, (7F, step), STOP]` for every
classic record. The player adds its step every frame the voice's record is
current, so the row was too long where the next note comes soon (Sanxion: the
original's sweep runs 6 frames, ours 127) and too short where it does not
(Tarzan at frame 3495: the original wraps and sweeps on, ours held $79 for 65
frames). `classic_sweep_calls` reads the gaps between a voice's notes off the
orderlists and `_best_sweep_length` picks the length that errs least.

Measured at the base 5c5e0c0 (presets, -t 180, `cutoff_sweep`, ours/original
travel; base -> this change): Sanxion 1.909 -> 1.100, Food_Feud 1.208 ->
1.101, Tarzan 1.231 -> 1.203, Knucklebusters 1.275 -> 1.272, ACE_II 0.957 ->
1.023, Lightforce 1.158 -> 1.147; Deep_Strike 1.026 -> 0.893, Nemesis_the_
Warlock 1.942 -> 0.500 and Thundercats 1.038 -> 1.085 move away.
"""
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.detect import detect
from h2g.goatwriter import (CMD_TONEPORTA, FILT_MODULATE, FILT_SET_CUTOFF,
                            FILT_SET_PARAMS, FILT_STOP, MAX_INSTRUMENTS,
                            _best_sweep_length, _filter_entries, _sweep_rows,
                            classic_sweep_calls)
from h2g.sidfile import load_sid
from h2g.tracks import InstrumentRowCalls
from test_filter_absent_four import gt_filter_calls

REPO = Path(__file__).resolve().parents[2]
NOTE, REST, END = 0x60, 0xBD, 0xFF


# --- the row split ------------------------------------------------------------

def test_no_length_is_the_one_row_every_earlier_version_wrote():
    assert _sweep_rows(5, None) == [(FILT_MODULATE, 5), (FILT_STOP, 0)]
    assert _sweep_rows(5, 0) == [(FILT_MODULATE, 5), (FILT_STOP, 0)]


@pytest.mark.parametrize("calls,rows", [
    (1, [1]), (6, [6]), (127, [127]), (128, [127, 1]),
    (300, [127, 127, 46]), (508, [127] * 4)])
def test_a_length_splits_into_7f_rows(calls, rows):
    """SABOTAGE TARGET: `min(calls, FILT_MODULATE)` -> `FILT_MODULATE` rounds
    every length up to a whole row."""
    got = _sweep_rows(3, calls)
    assert got == [(n, 3) for n in rows] + [(FILT_STOP, 0)]


@pytest.mark.parametrize("calls", [1, 6, 12, 96, 127, 128, 300, 508])
@pytest.mark.parametrize("per_call", [3, 0xFD])
def test_the_table_steps_exactly_that_many_calls(calls, per_call):
    """Run through a transcription of player.s' filter step: the cutoff moves
    on `calls` calls after the set-cutoff call and then holds."""
    table = [(FILT_SET_PARAMS | 0x10, 0xF4), (FILT_SET_CUTOFF, 0x20)]
    table += _sweep_rows(per_call, calls)
    got = gt_filter_calls(table, 1, calls + 40)
    assert got[0] == 0x20             # params and set-cutoff share one call
    moved = [i for i in range(1, len(got)) if got[i] != got[i - 1]]
    assert len(moved) == calls, (len(moved), calls)
    assert got[-1] == (0x20 + calls * per_call) & 0xFF
    assert got[-1] == got[-2]                   # and it holds


# --- the choice -----------------------------------------------------------------

def test_a_record_whose_notes_all_restart_it_sweeps_the_longest_gap():
    assert _best_sweep_length([(96, False), (128, False), (64, False)]) == 128


def test_stops_pull_the_length_down_to_where_the_player_stopped():
    """SABOTAGE TARGET: drop the overshoot term and every length becomes the
    longest gap, i.e. Sanxion's 6-call sweep runs 127 again."""
    assert _best_sweep_length([(6, True)] * 5 + [(128, False)]) == 6
    assert _best_sweep_length([(20, True)]) == 20


def test_no_gaps_say_nothing():
    assert _best_sweep_length([]) is None


# --- the walk ---------------------------------------------------------------------

def _pattern(rows):
    flat = []
    for note, ins, cmd in rows:
        flat += [note, ins, cmd, 0]
    return flat + [END, 0, 0, 0]


def _voice(*rows):
    return [_pattern(rows)], [[0, END, 0]]


def test_a_sweep_runs_to_the_next_unfiltered_note():
    # record 2 (instrument 3) at row 0, an unfiltered instrument 4 at row 4,
    # then a last note whose own gap is unknown
    patterns, tracks = _voice(
        (NOTE, 3, 0), (REST, 0, 0), (REST, 0, 0), (REST, 0, 0),
        (NOTE, 4, 0), (REST, 0, 0), (REST, 0, 0), (REST, 0, 0))
    got = classic_sweep_calls(tracks, patterns, {2}, 1, 6)
    assert got == {2: 24}                       # 4 rows x 6 calls


def test_the_start_subtunes_row_is_the_row():
    patterns, tracks = _voice((NOTE, 3, 0), (REST, 0, 0), (NOTE, 4, 0),
                              (REST, 0, 0))
    rows = InstrumentRowCalls({3: 4})
    rows.start_rows = {3: 6}
    assert classic_sweep_calls(tracks, patterns, {2}, 1, 8, rows) == {2: 12}
    rows.start_rows = {}
    assert classic_sweep_calls(tracks, patterns, {2}, 1, 8, rows) == {2: 8}


def test_a_tie_strikes_nothing():
    """SABOTAGE TARGET: counting `CMD_TONEPORTA` notes as strikes cuts the
    gap at the tie."""
    patterns, tracks = _voice((NOTE, 3, 0), (REST, 0, 0), (NOTE, 3, CMD_TONEPORTA),
                              (REST, 0, 0), (NOTE, 4, 0), (REST, 0, 0))
    assert classic_sweep_calls(tracks, patterns, {2}, 1, 5) == {2: 20}


def test_the_instrument_is_inherited_across_rows():
    patterns, tracks = _voice((NOTE, 3, 0), (REST, 0, 0), (NOTE, 0, 0),
                              (REST, 0, 0), (NOTE, 4, 0), (REST, 0, 0))
    # two filtered strikes (gaps 2 and 2, the second stopped) -> 2 rows x 5
    assert classic_sweep_calls(tracks, patterns, {2}, 1, 5) == {2: 10}


def test_a_filtered_follower_does_not_stop_the_sweep():
    """SABOTAGE TARGET: `nxt not in filtered` -> `True` makes every gap a
    stop, and a record replaced by another filtered record is cut short."""
    patterns, tracks = _voice((NOTE, 3, 0), (REST, 0, 0), (REST, 0, 0),
                              (REST, 0, 0), (NOTE, 3, 0), (REST, 0, 0),
                              (NOTE, 5, 0), (REST, 0, 0))
    assert classic_sweep_calls(tracks, patterns, {2}, 1, 4) == {2: 8}
    assert classic_sweep_calls(tracks, patterns, {2, 4}, 1, 4) == {2: 16}


# --- the corpus --------------------------------------------------------------------

def _det(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda m: None)


@needs_corpus
def test_tarzans_first_record_sweeps_as_long_as_it_is_told():
    sid, det = _det("Tarzan")
    n = min(det.instr_used + 1, MAX_INSTRUMENTS)
    plain, ptrs = _filter_entries(sid, det, n, multiplier=1)
    sized, _ = _filter_entries(sid, det, n, multiplier=1,
                               sweep_calls={min(ptrs): 300})
    first = plain[:4]
    assert first[2][0] == FILT_MODULATE and first[3] == (FILT_STOP, 0)
    step = first[2][1]
    assert sized[:6] == first[:2] + [(127, step), (127, step), (46, step),
                                     (FILT_STOP, 0)]


@needs_corpus
def test_a_table_the_sized_sweeps_overflow_is_the_old_table():
    """SABOTAGE TARGET: drop the rebuild in `_filter_entries` and Star_Paws
    (52 of 64 entries at one row each) loses its later records."""
    sid, det = _det("Star_Paws")
    n = min(det.instr_used + 1, MAX_INSTRUMENTS)
    plain, ptrs = _filter_entries(sid, det, n, multiplier=1)
    huge, hptrs = _filter_entries(sid, det, n, multiplier=1,
                                  sweep_calls={i: 508 for i in ptrs})
    assert (huge, hptrs) == (plain, ptrs)


@needs_corpus
def test_sanxions_sweep_is_six_calls_in_the_conversion():
    """At the seam, under the shipped presets: the original's sweep runs 6
    frames before its record gives way."""
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    blob = convert(str(CORPUS / "Sanxion.sid"), log=lambda m: None,
                   **F._preset_opts(doc, "Sanxion.sid"))
    ftbl = parse_sng(blob).tables["FTBL"]
    assert (6, 28) in ftbl and (FILT_MODULATE, 28) not in ftbl, ftbl


def test_commando_is_untouched():
    ref = (REPO / "Commando.sng").read_bytes()
    assert convert(str(REPO / "Commando.sid"), log=lambda m: None,
                   filters=True) == ref
