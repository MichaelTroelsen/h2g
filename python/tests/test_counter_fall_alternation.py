"""The alternating record of bit $02's counter-started fall, emitted as
wavetable loops of a few dip sizes (`goatwriter.counter_fall.alternation_*`).

Mega_Apocalypse record `$0B` (GT 10, `$09F9`, threshold 31, vibrato byte
`$2D`): from the threshold every odd frame of the voice's counter puts the
voice `n * $100` under its note and the vibrato block puts it back on the
next frame, `n` the store's own count. The 288-frame note at frame 3745 has
227 reversals in the original and had 52 in ours. The exact schedule is two
wavetable steps a store (228 for that note); what is emitted is a three-row
loop a dip SIZE (`F2 size / F3 00 / FF`), the rows pointed at the loop of
their own size.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import counter_fall as C                 # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      CMD_VIBRATO, GT_WAVE_JUMP,
                                      WAVECMD_PORTADOWN)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

MEGA = CORPUS / "Mega_Apocalypse.sid"


def _converted(name="Mega_Apocalypse", **extra):
    import h2g.convert as Cv
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = Cv.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


# --- the dips ----------------------------------------------------------------

def test_the_first_store_moves_nothing_so_the_dips_start_at_the_second():
    assert C.alternation_dips(40, 31, set()) == [33, 35, 37, 39]
    assert C.fall_stores(40, 31) == [31, 33, 35, 37, 39]


def test_the_dips_stop_with_the_counters_first_lap():
    dips = C.alternation_dips(400, 31, set())
    assert dips[0] == 33 and dips[-1] == 255 and len(dips) == 112


def test_a_fetch_frame_on_a_store_declines_the_note():
    assert C.alternation_dips(60, 31, {33}) is None
    assert C.alternation_dips(60, 31, {32, 96}) == [33, 35, 37, 39, 41, 43,
                                                    45, 47, 49, 51, 53, 55,
                                                    57, 59]


# --- the rows ----------------------------------------------------------------

def test_the_rows_of_a_288_frame_note_alternate_between_dip_and_step_back():
    dips = C.alternation_dips(288, 31, {96, 192})
    rows = C.alternation_rows(dips, 1, 3)
    # the first dip is call 34: row 11, one tick in
    assert (rows[0].e, rows[0].kind, rows[0].delay, rows[0].n) == (11, 'E',
                                                                   1, 1)
    assert [r.kind for r in rows[1:5]] == ['D', 'S', 'D', 'S']
    assert [r.e for r in rows[:3]] == [11, 12, 13]
    # a row that opens on a dip follows one that ended on a step back
    assert all(r.after_balanced for r in rows if r.kind == 'D')
    assert not any(r.after_balanced for r in rows[2:] if r.kind == 'S')
    # n grows by 1.5 a row; the last row holds the 112th dip
    assert rows[-1].n >= 110


def test_a_row_ends_on_the_step_back_only_when_its_last_call_is_one():
    rows = C.alternation_rows([33, 35, 37, 39, 41, 43], 1, 3)
    kinds = {r.e: (r.kind, r.after_balanced) for r in rows}
    assert kinds[12] == ('D', True)        # row 11 ended on a step back
    assert kinds[13] == ('S', False)       # row 12 ended on a dip


# --- the sizes ---------------------------------------------------------------

def test_quantize_levels_returns_the_values_when_there_are_few():
    assert C.quantize_levels([3, 3, 9, 20], 5) == [3, 9, 20]


def test_quantize_levels_clusters_in_log_space():
    got = C.quantize_levels(list(range(1, 113)), 6)
    assert len(got) == 6 and got == sorted(got)
    # geometric: each size at least a quarter larger than the one before
    assert all(b >= 1.25 * a for a, b in zip(got, got[1:])), got
    assert got[0] <= 2 and got[-1] >= 70


def test_quantize_levels_keeps_a_lone_far_value_apart():
    got = C.quantize_levels([2] * 50 + [3] * 50 + [100], 2)
    assert got[-1] == 100


def test_nearest_level_is_nearest_in_log_space():
    assert C.nearest_level([2, 8, 32], 3) == 0     # 3/2 < 8/3
    assert C.nearest_level([2, 8, 32], 5) == 1     # 8/5 < 5/2
    assert C.nearest_level([2, 8, 32], 100) == 2


def test_a_loop_is_dip_tie_jump_and_a_size_over_127_dips_the_other_way():
    speeds = []

    def index(h):
        speeds.append(h)
        return len(speeds)
    assert C.alternation_loop(5, index, 40) == [
        (WAVECMD_PORTADOWN, 1), (0xF3, 0), (GT_WAVE_JUMP, 40)]
    assert speeds == [5]
    assert C.alternation_loop(200, index, 9)[0][0] == 0xF1   # up 56 = down 200
    assert speeds[-1] == 56


# --- the rows of an orderlist ------------------------------------------------

def _fake(rows=100, unusable=(), fetches=(), number=10, lag=1, frames=3,
          own=0):
    pat = []
    for r in range(rows):
        cmd = (15, 3) if r in unusable else (CMD_VIBRATO, 5)
        pat += [189, 0, cmd[0], cmd[1]]
    seg = C._Segment(0, 0, rows, number, frames, lag, set(fetches), [])
    lap = [(0, r, 0, 7, 0) for r in range(rows)]
    return seg, {0: lap}, [pat], {number: 31}, {number: own}


def test_the_asks_point_the_entry_then_every_row_at_a_size():
    seg, rows, pats, thr, own = _fake()
    asks, levels, declined, notes = C.alternation_asks(
        [seg], rows, pats, thr, own, 100)
    assert notes == 1 and not declined
    got = asks[(0, 7)][0]
    assert got[11][:2] == ('alt', 'E') and got[11][3] == 1
    assert got[12][1] == 'D' and got[13][1] == 'S'
    assert set(got) == set(range(11, 86))
    assert {k[2] for k in got.values()} == set(levels)
    assert len(levels) <= C.ALTERNATION_LEVELS


def test_a_size_changes_only_on_a_row_after_a_step_back():
    seg, rows, pats, thr, own = _fake()
    asks, levels, _d, _n = C.alternation_asks([seg], rows, pats, thr, own,
                                              100)
    got = asks[(0, 7)][0]
    size = [got[r][2] for r in sorted(got)]
    kinds = [got[r][1] for r in sorted(got)]
    changes = [i for i in range(1, len(size)) if size[i] != size[i - 1]]
    assert changes, "one size all the way is not the schedule"
    assert all(kinds[i] == 'D' for i in changes), changes
    assert size == sorted(size)


def test_a_row_with_another_command_is_left_alone():
    seg, rows, pats, thr, own = _fake(unusable={20, 21})
    asks, _l, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100)
    got = asks[(0, 7)][0]
    assert 20 not in got and 21 not in got and 19 in got and 22 in got


def test_the_entry_waits_for_a_row_that_can_take_it():
    seg, rows, pats, thr, own = _fake(unusable={11})
    asks, _l, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100)
    got = asks[(0, 7)][0]
    assert 11 not in got and got[12][:2] == ('alt', 'D')


def test_a_one_tick_row_cannot_start_on_a_step_back():
    """Rows of one call: the dip is call 34, row 34. Where that row is taken
    the next opens on the step back, which with nothing before it would lift
    the voice above its note: the entry is the row after, a dip."""
    seg, rows, pats, thr, own = _fake(rows=300, frames=1, unusable={34})
    asks, _l, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100)
    got = asks[(0, 7)][0]
    assert 34 not in got and 35 not in got
    assert got[36][:2] == ('alt', 'D')


def test_a_note_with_no_dip_is_left_to_the_swell():
    seg, rows, pats, thr, own = _fake(rows=11)         # 33 frames: no dip
    asks, levels, declined, notes = C.alternation_asks(
        [seg], rows, pats, thr, own, 100)
    assert asks == {} and levels == [] and notes == 0
    assert declined == {"too few dips": 1}


def test_a_fetch_on_a_store_frame_declines_the_note():
    seg, rows, pats, thr, own = _fake(fetches={33})
    asks, _l, declined, notes = C.alternation_asks([seg], rows, pats, thr,
                                                   own, 100)
    assert asks == {} and notes == 0
    assert declined == {"a fetch frame on a store": 1}


def test_without_room_for_one_size_nothing_is_taken():
    seg, rows, pats, thr, own = _fake()
    asks, levels, declined, notes = C.alternation_asks(
        [seg], rows, pats, thr, own, 4)
    assert asks == {} and levels == [] and declined == {"wavetable full": 1}


def test_the_sizes_shrink_to_the_room():
    seg, rows, pats, thr, own = _fake()
    _a, levels, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 14)
    assert 1 <= len(levels) <= 4          # 3 rows a size, 2 for the entry


def test_a_row_before_the_instruments_own_program_ends_is_not_taken():
    seg, rows, pats, thr, own = _fake(own=40)           # 40 calls: row 13
    asks, _l, _d, _n = C.alternation_asks([seg], rows, pats, thr, own, 100)
    got = asks[(0, 7)][0]
    assert min(got) >= 14


# --- Mega_Apocalypse, end to end ---------------------------------------------

@needs_corpus
def test_mega_apocalypse_emits_the_alternation_and_the_swell_loops_still_fit():
    sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m]
    assert len(said) == 1, lines
    assert "55 emitted on" in said[0] and "dip size(s)" in said[0], said[0]
    swell = [m for m in lines if m.startswith("Expanding vibrato loops")]
    assert swell and "table full" not in swell[0], swell
    import songview
    song = songview.parse_sng(sng)
    wt = song.tables["WTBL"]
    assert len(wt) <= 255
    # each size's loop: F2 size, F3 00, jump back to its first row
    loops = [i for i in range(len(wt) - 2)
             if wt[i][0] == WAVECMD_PORTADOWN and wt[i + 1] == (0xF3, 0)
             and wt[i + 2] == (GT_WAVE_JUMP, i + 1)]
    assert len(loops) >= 5, loops
    speeds = song.tables["STBL"]
    sizes = sorted(speeds[wt[i][1] - 1][0] for i in loops)
    assert sizes == sorted(set(sizes)) and sizes[0] <= 2 and sizes[-1] >= 60


@needs_corpus
def test_the_288_frame_notes_rows_point_at_the_loops_from_the_first_dip():
    import songview
    sng, _ = _converted()
    song = songview.parse_sng(sng)
    wt = song.tables["WTBL"]
    first = {i + 1 for i in range(len(wt) - 2)
             if wt[i][0] == WAVECMD_PORTADOWN and wt[i + 1] == (0xF3, 0)
             and wt[i + 2] == (GT_WAVE_JUMP, i + 1)}
    into = first | {a + 1 for a in first}
    entry = {i + 1 for i in range(len(wt) - 1)
             if wt[i][0] <= 0x0F and wt[i + 1][0] == GT_WAVE_JUMP
             and wt[i + 1][1] in first}
    hits = 0
    for track in song.tracks:
        rows = list(S._lap_rows(track, song.patterns))
        for a, (p, r, _t) in enumerate(rows):
            n, ins, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
            if ins == 10 and n < 0xBD:           # a GT 10 note row
                cmds = [song.patterns[q][4 * s + 2:4 * s + 4]
                        for q, s, _u in rows[a:a + 96]]
                ptr = [c[1] for c in cmds if c[0] == CMD_SETWAVEPTR]
                if len(ptr) > 40 and set(ptr) & (into | entry):
                    hits += 1
                    # no row of the run points at a swell loop (F4 rows)
                    assert all(wt[d - 1][0] != 0xF4 for d in ptr
                               if d in into | entry), ptr
    assert hits >= 3


@needs_corpus
def test_with_the_alternation_off_mega_converts_as_it_did(monkeypatch):
    """No note taken -> the bytes the swell alone gives. 3dd7d6f19319 at
    0d0f6ec; f5958c98a448 since the swell's pattern split, which moves this
    sha and nothing else: with the split off too it is 3dd7d6f19319 again
    (`test_with_the_split_and_the_alternation_off_mega_converts_as_it_did`);
    bb50807c38f5 since a remainder's loop block ends in a jump onto the
    speed's F4 entry instead of carrying a pair of its own
    (`_expanding_vibrato_loop_cost`): the wavetable layout and the pointers
    into it move, and the program every row runs does not
    (`test_remainder_blocks_run_what_a_loop_of_their_own_ran`)."""
    import hashlib
    import h2g.goatwriter.note_passes as NP
    # Mega's tied landings are legato clones since ca85ac7's
    # tie-restart-mega-phantoms-note-start; this pin is the arm without them.
    monkeypatch.setattr(NP, "legato_tie_family", lambda sid, det: False)
    monkeypatch.setattr(C, "ALTERNATION_MIN_DIPS", 10 ** 6)
    sng, lines = _converted()
    # Re-pinned by the -S1 slide frames (wave-program-slide-frames-0797-family):
    # Mega's $09F9/$07E7 slide frames are now semitone counts; with
    # note_pitches=None in convert() the old sha comes back.
    # Re-pinned (e6e990305c3b) by the drop of the pulse and filter rows only a
    # dropped record reaches (instrument_drop._drop_dead_blocks).
    assert hashlib.sha1(sng).hexdigest()[:12] == "e6e990305c3b"
    assert any("not emitted" in m for m in lines), lines


@needs_corpus
def test_every_alternating_note_of_the_corpus_is_counted_or_emitted():
    _sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "alternating" in m][0]
    assert "385 alternating note(s) on instrument(s) [10, 13]" in said
    assert "55 emitted" in said and "330 too few dips" in said


def _reversals(freqs):
    n, last = 0, 0
    for a, b in zip(freqs, freqs[1:]):
        if a == b:
            continue
        s = 1 if b > a else -1
        if last and s != last:
            n += 1
        last = s
    return n


def _packed(sng, tmp_path, tag):
    """(ours' voice-0 frequency timeline, the original's, the startup lag)."""
    work = tmp_path / tag
    work.mkdir()
    packed = fidelity.pack_sid(sng, work)
    assert packed is not None and packed.exists(), tag
    ours = fidelity.run_siddump(packed, 92, 0)
    orig = fidelity.run_siddump(MEGA, 90, 0)
    lag = fidelity.startup_lag(orig, ours)[0]
    return (fidelity.register_timeline(ours[0].freq_events, 4600),
            fidelity.register_timeline(orig[0].freq_events, 4500), lag)


NOTE = 3745          # the 288-frame note on voice 0, in the original's frames


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_288_frame_note_reverses_as_often_as_the_original(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump, 90 s: the 288-frame note on voice 0 at
    frame 3745 has 227 reversals in the original. Ours has at least 200 (232
    measured), and 52 with the alternation off."""
    fu, fo, lag = _packed(_converted()[0], tmp_path, "emitted")
    assert 200 <= _reversals(fo[NOTE + 2:NOTE + 288]) <= 230
    assert _reversals(fu[NOTE + lag + 2:NOTE + lag + 288]) >= 200
    monkeypatch.setattr(C, "ALTERNATION_MIN_DIPS", 10 ** 6)
    fu, fo, lag = _packed(_converted()[0], tmp_path, "held")
    assert _reversals(fu[NOTE + lag + 2:NOTE + lag + 288]) <= 80


def _lows(f, lo, hi, off):
    return {t for t in range(lo, hi)
            if f[t + off] < f[t + off - 1] and f[t + off] < f[t + off + 1]}


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_dips_fall_on_the_originals_frames(tmp_path):
    """The dips are on the odd frames of the counter, so their PHASE is part
    of the schedule: of the 103 frames from the note's 40th to its 250th on
    which the original is lower than both neighbours, 95 are such frames in
    ours at the startup lag (7) and 8 one frame off."""
    fu, fo, lag = _packed(_converted()[0], tmp_path, "emitted")
    lo, hi = NOTE + 40, NOTE + 250
    want = _lows(fo, lo, hi, 0)
    assert len(want) >= 95
    assert len(want & _lows(fu, lo, hi, lag)) >= 0.85 * len(want)
    assert len(want & _lows(fu, lo, hi, lag + 1)) <= 0.2 * len(want)
    assert len(want & _lows(fu, lo, hi, lag - 1)) <= 0.2 * len(want)
