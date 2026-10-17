"""The alternating fall past the counter's first lap, as lap-end holds
(`goatwriter.counter_fall_laps`).

Mega_Apocalypse record `$0B` (GT 10, `$09F9`, threshold 31, vibrato gate 19):
the voice's frame counter is a byte, so at frame 255 of a note the stores
stop, the voice HOLDS the last dip (`DE20` x 20 frames on the 288-frame note
at frame 3745: the byte `$4E - 112`) until the vibrato gate, 19 frames into
the next lap, and the odd frames store again from frame 287 with the count
going on (113, 114 ...; a count past 127 is a dip UP, taken modulo 256).
Ours kept alternating at its last size through the gap, or (past the first
lap's rows) not at all.

The holds are on; the later laps' DIPS are an option, off
(`ALTERNATION_LATER_LAPS`): on, the swell's pass has 128 rows fewer to
convert and keeps 39 loops where three older pins want 42 or more.
"""
import json
import pathlib
import re
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import counter_fall as C                 # noqa: E402
from h2g.goatwriter import counter_fall_laps as L            # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_WAVE_JUMP,
                                      WAVECMD_PORTADOWN, WAVECMD_PORTAUP)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
MEGA = CORPUS / "Mega_Apocalypse.sid"

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

TIE = 0xF3


def _converted(**extra):
    import h2g.convert as Cv
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    opts.update(extra)
    sng = Cv.convert(str(MEGA), log=lines.append, **opts)
    return sng, lines


def _speeds():
    seen = []

    def index(high):
        seen.append(high)
        return len(seen)
    return index, seen


# --- the size a count makes -------------------------------------------------

def test_a_count_folds_modulo_256_to_a_size_a_speed_row_can_say():
    assert [L.fall_size(n) for n in (1, 112, 127)] == [1, 112, 127]
    assert L.fall_size(225) == 31          # $4E - 225 is $6D: 31 above
    assert L.fall_size(255) == 1
    assert L.fall_size(256) == 0 and L.fall_size(0) == 0
    assert L.fall_size(257) == 1
    # 128 is $8000, which no speed row says
    assert L.fall_size(128) == 127 and L.fall_size(129) == 127


# --- the hold's program -------------------------------------------------------

def test_a_hold_on_the_tick_after_a_step_back_ties_then_dips_then_jumps():
    index, seen = _speeds()
    got = L.hold_program(112, 1, index, 9)
    assert got == [(TIE, 0), (WAVECMD_PORTADOWN, 1), (GT_WAVE_JUMP, 9)]
    assert seen == [112]


def test_a_count_past_127_dips_up_by_the_complement():
    index, seen = _speeds()
    got = L.hold_program(225, 0, index, 9)
    assert got == [(WAVECMD_PORTAUP, 1), (GT_WAVE_JUMP, 9)]
    assert seen == [31]


def test_a_hold_two_ticks_in_waits_two_calls_and_does_not_tie():
    """The row opens on a dip and a step back: the voice is on its note
    already, so two still calls take their place."""
    index, _s = _speeds()
    got = L.hold_program(52, 2, index, 9)
    assert got == [(1, 0x80), (WAVECMD_PORTADOWN, 1), (GT_WAVE_JUMP, 9)]


def test_a_tied_hold_two_ticks_in_waits_one_call_and_ties_before_it_dips():
    """No dip loop before the row: the swell's offset is on the voice, and
    `F1` is relative to wherever it is."""
    index, seen = _speeds()
    got = L.hold_program(225, 2, index, 9, tied=True)
    assert got == [(0, 0x80), (TIE, 0), (WAVECMD_PORTAUP, 1),
                   (GT_WAVE_JUMP, 9)]
    # nothing before the dip to tie on: tick 0 is the same program
    assert L.hold_program(225, 0, _speeds()[0], 9, tied=True) == \
        L.hold_program(225, 0, _speeds()[0], 9)
    # an odd tick already ties
    assert L.hold_program(112, 1, _speeds()[0], 9, tied=True) == \
        L.hold_program(112, 1, _speeds()[0], 9)


def test_a_hold_that_dips_nothing_is_a_tie_or_a_wait_and_a_jump():
    index, _s = _speeds()
    assert L.hold_program(0, 0, index, 9) == [(GT_WAVE_JUMP, 9)]
    assert L.hold_program(0, 1, index, 9) == [(TIE, 0), (GT_WAVE_JUMP, 9)]
    assert L.hold_program(0, 2, index, 9) == [(GT_WAVE_JUMP, 9)]


def test_hold_rows_counts_what_hold_program_writes():
    assert [L.hold_rows(n, d) for n, d in ((112, 1), (225, 2), (82, 0))] \
        == [3, 3, 2]
    assert L.hold_rows(225, 2, True) == 4


def test_the_still_loop_ties_then_runs_a_portamento_of_nothing_forever():
    """`F2 0` is a wavetable command on every call, which skips the row's
    continuous effect (the swell's `4xy` left the channel on vibrato): a
    stopped program would let it run. Its speed row is a REAL one, zero:
    the packed player reads `mt_speedlefttbl - 1` for index 0."""
    index, seen = _speeds()
    got = L.still_loop(index, 20)
    assert got == [(TIE, 0), (WAVECMD_PORTADOWN, 1), (GT_WAVE_JUMP, 21)]
    assert seen == [0]


# --- the rows of one note ---------------------------------------------------

def _rows(length=288, fetches=(96, 192), gate=19, lag=1, frames=3,
          usable=lambda e: True, rows=96, holds=None, threshold=31,
          later=True):
    saved = L.ALTERNATION_LATER_LAPS
    L.ALTERNATION_LATER_LAPS = later
    try:
        return L.alternation_note_rows(length, threshold, gate,
                                       set(fetches), lag, frames, usable,
                                       rows, holds)
    finally:
        L.ALTERNATION_LATER_LAPS = saved


LONG = dict(length=576, fetches=(96, 192, 288, 384, 480), rows=192)


def _kinds(rows, kinds="XHQ"):
    return [(a.e, a.kind) for a in rows if a.kind in kinds]


def test_the_288_frame_note_holds_from_its_last_dip_to_the_vibrato_gate():
    rows = _rows()
    x = [a for a in rows if a.kind == 'X']
    # the last dip is frame 255: call 256, row 85, one tick in; its count is
    # (255 - 31) / 2 + 1 = 112 (the first store, 31, moves nothing)
    assert [(a.e, a.delay, a.n, a.tied) for a in x] == [(85, 1, 112, False)]
    # held through the rows to the gate: frame 275 is call 276, row 92 tick 0
    assert _kinds(rows, "H") == [(e, 'H') for e in range(86, 92)]
    assert _kinds(rows, "Q") == [(92, 'Q')]
    # nothing of the first lap's loop after the X row
    assert max(a.e for a in rows if a.kind in 'DSE' and not a.fresh) == 84


def test_the_exit_row_is_the_first_whole_row_at_or_after_the_gate():
    """Gate 19 at lag 1 is call 276 = row 92 exactly; gate 20 is call 277,
    mid-row, and the hold carries on to row 93: late, never early."""
    assert _kinds(_rows(gate=19), "Q") == [(92, 'Q')]
    assert _kinds(_rows(gate=20), "Q") == [(93, 'Q')]
    assert _kinds(_rows(gate=17), "Q") == [(92, 'Q')]


def test_a_note_that_ends_inside_the_hold_has_no_exit_row():
    rows = _rows(length=260, rows=87, fetches=())
    assert _kinds(rows, "XH") == [(85, 'X'), (86, 'H')]


def test_a_note_that_ends_with_the_lap_has_no_hold():
    rows = _rows(length=256, rows=86, fetches=())
    assert _kinds(rows) == []


def test_the_second_lap_goes_on_from_the_threshold_with_the_count_going_on():
    rows = _rows(**LONG)
    fresh = [a for a in rows if a.fresh]
    assert all(a.kind in 'DSXHQ' for a in fresh)
    # frame 287 (count 113) is call 288 = row 96, tick 0
    assert (fresh[0].e, fresh[0].kind, fresh[0].delay) == (96, 'D', 0)
    assert fresh[0].n == 114            # the row holds dips 113 and 114
    # a count past 127 is a dip up, emitted as a dip down of the same size
    assert min(a.n for a in fresh if a.kind in 'DS') < 40
    # and the second lap ends in a hold of its own: count 225
    assert [(a.e, a.delay, a.n) for a in rows if a.kind == 'X'] \
        == [(85, 1, 112), (170, 2, 225)]


def test_a_run_after_a_hold_has_no_entry_row_of_its_own():
    rows = _rows(**LONG)
    assert [a.e for a in rows if a.kind == 'E'] == [11]


def test_a_hold_not_in_the_set_is_left_to_the_loop_which_carries_on():
    rows = _rows(**LONG, holds={(225, 2, False)})
    assert [(a.e, a.n) for a in rows if a.kind == 'X'] == [(170, 225)]
    # the first lap's loop runs through the gap: rows 86..95 are loop rows
    kinds = {a.e: a.kind for a in rows}
    assert all(kinds[e] in 'DS' for e in range(86, 96))
    assert not any(a.fresh for a in rows if a.e < 96)
    # ... at the size it had (the dips it makes there are fillers of 112)
    assert {a.n for a in rows if 86 <= a.e < 96} == {112}


def test_a_hold_whose_row_cannot_take_a_program_is_not_made():
    rows = _rows(**LONG, usable=lambda e: e != 85)
    assert [a.e for a in rows if a.kind == 'X'] == [170]
    assert not any(a.kind in 'HQ' and a.e < 100 for a in rows)


def test_a_count_of_128_is_not_held():
    """$8000: no speed row says it. At threshold 171 a lap has 43 stores, so
    the third lap ends on count 3 * 43 - 1 = 128 -- the laps before and after
    it (42, 85, 171) are held and that one is left to the loop."""
    rows = _rows(length=1100, fetches=(), rows=367, threshold=171)
    counts = [a.n for a in rows if a.kind == 'X']
    assert counts == [42, 85, 171], counts
    assert 128 not in counts
    # the lap that is not held runs on as one loop through the gap
    kinds = {a.e: a.kind for a in rows}
    assert all(kinds[e] in 'DS' for e in range(250, 270))


def test_without_a_gate_below_the_threshold_only_the_first_lap_is_read():
    for gate in (None, 31, 200):
        rows = _rows(**LONG, gate=gate)
        assert max(a.e for a in rows) == 85, gate
        assert not _kinds(rows)


def test_a_fetch_frame_on_a_first_lap_store_declines_the_note():
    assert _rows(fetches=(33,)) is None


def test_with_the_later_laps_off_only_the_first_lap_and_the_holds_are_rows():
    rows = _rows(**LONG, later=False)
    assert not any(a.fresh and a.kind in 'DSE' for a in rows)
    assert max(a.e for a in rows if a.kind in 'DSE') == 84
    assert [(a.e, a.delay, a.n, a.tied) for a in rows if a.kind == 'X'] \
        == [(85, 1, 112, False), (170, 2, 225, True)]
    # and a hold with no first-lap rows around it still has its H and Q rows
    assert [a.e for a in rows if a.kind == 'Q'] == [92, 178]


def test_a_hold_past_the_first_lap_ties_first_only_where_nothing_dips_before_it():
    """Two ticks in: tied when the later laps are off (the swell is on the
    voice), not when the lap before it is a run of dips ending balanced."""
    off = [a for a in _rows(**LONG, later=False) if a.kind == 'X']
    on = [a for a in _rows(**LONG, later=True) if a.kind == 'X']
    assert [a.tied for a in off] == [False, True]
    assert [a.tied for a in on] == [False, False]


# --- the asks ----------------------------------------------------------------

def _fake(rows=192, frames=3, lag=1, number=10, fetches=(96, 192, 288, 384,
                                                         480), own=0,
          unusable=()):
    pat = []
    for r in range(rows):
        cmd = (15, 3) if r in unusable else (4, 5)
        pat += [189, 0, cmd[0], cmd[1]]
    seg = C._Segment(0, 0, rows, number, frames, lag, set(fetches), [])
    lap = [(0, r, 0, 7, 0) for r in range(rows)]
    return seg, {0: lap}, [pat], {number: 31}, {number: own}


def _two_notes():
    """A 576-frame note (holds 112@1 and 225@2) and a 288-frame one (112@1):
    the first program is the more used."""
    seg, rows, pats, thr, own = _fake()
    seg2 = C._Segment(1, 0, 96, 10, 3, 1, {96, 192}, [])
    rows[1] = rows[0][:96]
    return [seg, seg2], rows, pats, thr, own


def _keys(asks):
    return {k for byv in asks.values() for rr in byv.values()
            for k in rr.values()}


def test_the_asks_carry_the_holds_the_most_used_first(monkeypatch):
    """With room for both: the shared program, and the second lap's, tied
    (nothing dips before it: the later laps are off)."""
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", 10)
    monkeypatch.setattr(C, "ALTERNATION_ROWS", 40)
    segs, rows, pats, thr, own = _two_notes()
    asks, levels, declined, notes = C.alternation_asks(
        segs, rows, pats, thr, own, 100, {10: 19})
    keys = _keys(asks)
    assert {k for k in keys if k[1] == 'X'} \
        == {('alt', 'X', 112, 1, False), ('alt', 'X', 225, 2, True)}
    assert {('alt', 'H'), ('alt', 'Q')} <= keys
    assert notes == 2 and not declined


def test_the_holds_take_no_more_rows_than_the_budget(monkeypatch):
    """The default pays for the still loop and the one program all three long
    notes share; the second lap's (4 rows) is the next 4."""
    segs, rows, pats, thr, own = _two_notes()
    asks, _lv, _d, _n = C.alternation_asks(segs, rows, pats, thr, own, 100,
                                           {10: 19})
    assert {k for k in _keys(asks) if k[1] == 'X'} \
        == {('alt', 'X', 112, 1, False)}
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", L.STILL_ROWS + 3)
    asks, _lv, _d, _n = C.alternation_asks(segs, rows, pats, thr, own, 100,
                                           {10: 19})
    assert {k for k in _keys(asks) if k[1] == 'X'} \
        == {('alt', 'X', 112, 1, False)}
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", 0)
    asks, _lv, _d, _n = C.alternation_asks(segs, rows, pats, thr, own, 100,
                                           {10: 19})
    assert not {k for k in _keys(asks) if k[1] in 'XHQ'}


def test_no_gates_no_holds():
    seg, rows, pats, thr, own = _fake()
    asks, _lv, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100)
    got = asks[(0, 7)][0]
    assert set(got) == set(range(11, 86))


def test_a_size_changes_only_on_a_row_after_a_step_back_in_a_later_lap_too(
        monkeypatch):
    monkeypatch.setattr(L, "ALTERNATION_LATER_LAPS", True)
    seg, rows, pats, thr, own = _fake()
    asks, _lv, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100,
                                           {10: 19})
    got = asks[(0, 7)][0]
    later = [r for r in sorted(got) if r >= 96]
    assert later, "the second lap's dips are not emitted"
    size = {r: got[r][2] for r in later if got[r][1] in 'DS'}
    kinds = {r: got[r][1] for r in later if got[r][1] in 'DS'}
    rs = sorted(size)
    changes = [r for a, r in zip(rs, rs[1:]) if size[r] != size[a]
               and r - a == 1]
    assert changes, "one size all the way is not the schedule"
    assert all(kinds[r] == 'D' for r in changes), changes


def test_with_the_later_laps_off_no_row_past_the_first_lap_is_a_dip():
    seg, rows, pats, thr, own = _fake()
    asks, _lv, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100,
                                           {10: 19})
    got = asks[(0, 7)][0]
    assert all(got[r][1] in 'HQX' for r in got if r > 85), got


def test_the_rows_and_the_holds_together_stay_inside_the_cap():
    seg, rows, pats, thr, own = _fake()
    asks, levels, _d, _n = C.alternation_asks([seg], rows, pats, thr, own,
                                              100, {10: 19})
    keys = _keys(asks)
    entries = {k for k in keys if k[1] == 'E'}
    holds = {(k[2], k[3], k[4]) for k in keys if k[1] == 'X'}
    cost = (3 * len(levels) + 2 * len(entries) + L.STILL_ROWS
            + sum(L.hold_rows(*h) for h in holds))
    assert holds and cost <= C.ALTERNATION_ROWS


def test_the_holds_are_dropped_before_the_last_size_is():
    """With room for one size and no hold, the loops alone."""
    seg, rows, pats, thr, own = _fake()
    asks, levels, _d, notes = C.alternation_asks([seg], rows, pats, thr, own,
                                                 5, {10: 19})
    assert levels and not {k for k in _keys(asks) if k[1] in 'XHQ'}
    assert notes == 1


def test_a_row_inside_the_hold_that_cannot_take_a_pointer_is_skipped():
    seg, rows, pats, thr, own = _fake(unusable={88})
    asks, _lv, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100,
                                           {10: 19})
    got = asks[(0, 7)][0]
    assert 88 not in got and got[87] == ('alt', 'H') and got[89] == ('alt', 'H')


# --- Mega_Apocalypse, end to end ---------------------------------------------

def _swell_loops(lines):
    swell = [m for m in lines if m.startswith("Expanding vibrato loops")]
    assert len(swell) == 1, swell
    return swell[0], int(re.search(r" on (\d+) wavetable loop",
                                   swell[0]).group(1))


@needs_corpus
def test_mega_apocalypse_writes_the_still_loop_and_the_shared_hold_program(
        monkeypatch):
    import songview
    # The rows these numbers count are the table before
    # `goatwriter.dead_blocks` dropped the dead records' blocks (20 rows
    # lower: "at 98"; test_dead_blocks.py pins that arm).
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m]
    assert len(said) == 1, lines
    # the first lap's end every long note shares, and the final hold of the
    # 1920-frame note a drum silences (`counter_fall.drum_stops`)
    assert ("2 lap-end hold program(s) [(112, 1, False), (245, 2, False)]"
            in said[0]), said[0]
    assert "7 dip size(s)" in said[0], said[0]
    # the record-16 programs share their tails to pay for the hold's rows:
    # 40 steps from row 118 once `[wait][F2][stop]` is the end of a longer
    # one (43 laid one each); the final hold's 3 rows make 43 in all
    assert "43 wavetable step(s) at 118" in said[0], said[0]
    assert "visits disagree" not in said[0], said[0]
    swell, _loops = _swell_loops(lines)
    assert "table full" not in swell, swell
    song = songview.parse_sng(sng)
    wt, st = song.tables["WTBL"], song.tables["STBL"]
    assert len(wt) <= 255
    # the still loop: tie / F2 (a speed row of 0) / jump to the F2
    at = [i for i in range(len(wt) - 2)
          if wt[i] == (TIE, 0) and wt[i + 1][0] == WAVECMD_PORTADOWN
          and st[wt[i + 1][1] - 1] == (0, 0)
          and wt[i + 2] == (GT_WAVE_JUMP, i + 2)]
    assert len(at) == 1, at
    still = at[0] + 2                     # 1-based index of the F2 row
    # the program: tie / F2 112 / jump
    jumps = [i for i in range(len(wt)) if wt[i] == (GT_WAVE_JUMP, still)
             and i != at[0] + 2]
    shapes = set()
    for j in jumps:
        prev = wt[j - 1]
        if prev[0] in (WAVECMD_PORTADOWN, WAVECMD_PORTAUP):
            shapes.add((prev[0], st[prev[1] - 1][0], wt[j - 2]))
    # (and the final hold: two still calls, then F1 11, count 245 = $59)
    assert shapes == {(WAVECMD_PORTADOWN, 112, (TIE, 0)),
                      (WAVECMD_PORTAUP, 11, (1, 0x80))}, shapes


@needs_corpus
def test_the_640_row_notes_first_hold_needs_its_repeats_unrolled(monkeypatch):
    """The 1920-frame note (lap row 6720) runs over a position `$DF` plays 16
    times, each visit with the counter somewhere else: its lap-end rows are
    taken only where every visit asks for the same, which is after the
    repeats are unrolled. Not unrolled, 28 rows are left to the visits."""
    _sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m][0]
    assert "visits disagree" not in said, said
    unrolled = [m for m in lines if "unrolled over" in m]
    assert unrolled and "3 repeated position(s)" in unrolled[0], unrolled
    monkeypatch.setattr(C, "ALTERNATION_UNROLL", False)
    _sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m][0]
    # (28 before the 1920-frame note's final hold, which points 255 more rows)
    assert "31 rows the visits disagree on" in said, said
    assert "1 lap-end hold program(s)" in said      # the two shorter notes'


@needs_corpus
def test_the_swell_loses_no_loop_to_the_alternation_on_mega_apocalypse():
    """Before the holds the swell's pass kept 43 loops (13 swings merged onto
    the nearest, a full table's worth); it keeps at least those, still
    shares, and drops none for a full table."""
    _sng, lines = _converted()
    swell, loops = _swell_loops(lines)
    assert loops >= 43, swell
    assert "table full" not in swell, swell
    assert "on the nearest loop that fits" in swell, swell
    assert L.ALTERNATION_LATER_LAPS is False


@needs_corpus
def test_the_rows_of_the_hold_point_into_the_still_loop_and_the_exit_ties():
    import songview
    sng, _ = _converted()
    song = songview.parse_sng(sng)
    wt = song.tables["WTBL"]
    tie_at = [i + 1 for i in range(len(wt) - 2) if wt[i] == (TIE, 0)
              and wt[i + 2] == (GT_WAVE_JUMP, i + 2)]
    assert len(tie_at) == 1
    exit_ptr, still_ptr = tie_at[0], tie_at[0] + 1
    held = exits = 0
    from h2g.goatwriter import skydive as S
    for track in song.tracks:
        run = 0
        for p, r, _t in S._lap_rows(track, song.patterns):
            cmd, dat = song.patterns[p][4 * r + 2:4 * r + 4]
            if cmd == CMD_SETWAVEPTR and dat == still_ptr:
                run += 1
            else:
                if run >= 6:
                    held += 1
                run = 0
            exits += cmd == CMD_SETWAVEPTR and dat == exit_ptr
    # the three notes that outlast a lap each hold the first lap's end for
    # six whole rows and tie back on the seventh
    assert held >= 3 and exits >= 3, (held, exits)


@needs_corpus
def test_with_the_holds_off_mega_has_none_of_it(monkeypatch):
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", 0)
    _sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m][0]
    assert "lap-end hold" not in said


def _timelines(sng, tmp_path, tag, seconds=300):
    work = tmp_path / tag
    work.mkdir()
    packed = fidelity.pack_sid(sng, work)
    assert packed is not None and packed.exists(), tag
    ours = fidelity.run_siddump(packed, seconds + 2, 0)
    orig = fidelity.run_siddump(MEGA, seconds, 0)
    lag = fidelity.startup_lag(orig, ours)[0]
    n = seconds * 50
    return (fidelity.register_timeline(orig[0].freq_events, n),
            fidelity.register_timeline(ours[0].freq_events, n + 100), lag)


# (frame of the note's fetch on voice 0, laps whose end is held): the
# 288-frame note's, the 576-frame note's first, and with room for the second
# program the 576-frame note's second
NOTES = ((3745, (1,)), (13728, (1,)))
NOTES_BOTH = ((3745, (1,)), (13728, (1, 2)))


def _held_frames(fo, fu, lag, notes=NOTES):
    """(frames compared, frames whose high byte agrees) over the hold
    windows: counter 255 of a lap to 18 of the next (gate 19)."""
    n = m = 0
    for start, laps in notes:
        for lap in laps:
            for d in range(256 * lap - 1, 256 * lap + 19):
                n += 1
                m += (fo[start + d] >> 8) == (fu[start + d + lag] >> 8)
    return n, m


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_held_frames_match_the_originals_high_byte(tmp_path):
    """Through gt2reloc and siddump, 300 s: the 288-frame note's hold (20
    frames of `$DE`) and the 576-frame note's first -- 40 frames -- are the
    original's high byte, every one. Before the holds 1 of 40."""
    fo, fu, lag = _timelines(_converted()[0], tmp_path, "held")
    assert _held_frames(fo, fu, lag) == (40, 40)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_second_lap_hold_ties_first_and_matches_too(tmp_path,
                                                              monkeypatch):
    """With room for the second program (`[wait] [tie] F1 31`, count 225 =
    `$6D`, above the note) the 576-frame note's second hold is the
    original's too: 60 of 60. The swell's pins do not allow the room."""
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", 13)
    monkeypatch.setattr(C, "ALTERNATION_ROWS", 43)
    fo, fu, lag = _timelines(_converted()[0], tmp_path, "both")
    assert _held_frames(fo, fu, lag, NOTES_BOTH) == (60, 60)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_without_the_holds_those_frames_do_not_match(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", 0)
    fo, fu, lag = _timelines(_converted()[0], tmp_path, "loop")
    n, m = _held_frames(fo, fu, lag)
    assert n == 40 and m <= 8, m


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_held_voice_is_on_its_note_again_at_the_gate(tmp_path):
    """The exit row ties back: frame 275 of the 288-frame note is the note
    (`4E`), where the original's vibrato starts from the note too."""
    fo, fu, lag = _timelines(_converted()[0], tmp_path, "exit")
    for d in (275, 276, 277):
        assert fu[3745 + d + lag] >> 8 == 0x4E
    assert fo[3745 + 275] >> 8 == 0x4E


def _reversals(f):
    n, last = 0, 0
    for a, b in zip(f, f[1:]):
        if a != b:
            s = 1 if b > a else -1
            n += bool(last and s != last)
            last = s
    return n


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_with_the_later_laps_on_the_576_frame_note_reverses_as_often(
        tmp_path, monkeypatch):
    """The 576-frame note: 480 reversals in the original, 296 in ours before
    the holds and 288 after them (the first lap's loop only), 480 with the
    later laps' dips and both programs -- which cost the swell three pins and
    the first lap two dip sizes, so they are off."""
    monkeypatch.setattr(L, "ALTERNATION_LATER_LAPS", True)
    monkeypatch.setattr(L, "ALTERNATION_HOLD_ROWS", 13)
    monkeypatch.setattr(C, "ALTERNATION_ROWS", 43)
    fo, fu, lag = _timelines(_converted()[0], tmp_path, "rev")
    start = 13728
    o = _reversals(fo[start + 2:start + 576])
    u = _reversals(fu[start + lag + 2:start + lag + 576])
    assert 470 <= o <= 490
    assert abs(u - o) <= 12, (u, o)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_with_the_later_laps_on_the_held_frames_still_match(
        tmp_path, monkeypatch):
    monkeypatch.setattr(L, "ALTERNATION_LATER_LAPS", True)
    fo, fu, lag = _timelines(_converted()[0], tmp_path, "held-on")
    assert _held_frames(fo, fu, lag) == (40, 40)
