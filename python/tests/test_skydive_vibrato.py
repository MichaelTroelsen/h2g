"""The skydive's alternate frames carry the vibrato (`goatwriter.skydive`).

A wavetable command runs instead of the voice's vibrato on its frame, so the
program 7.ppppppp built (`F2 k` down, `F1 k` back up) held the vibrato at the
note for the whole fall while the original kept vibrating: 5_Title_Tunes
subtune 1's in-window bend was 49840 in the original against 24738 ours.

The global-triangle vibrato is a pure function of the play-entry counter the
skydive itself tests, `note + fold(counter & 7) * (interval >> (byte + 1))`,
so the frequency the original writes on every frame of a window is known in
advance, and every frame of the program can be one portamento command of the
difference to the frame before. Hunter_Patrol voice 1, frames 298-324 (siddump
of the original): the stores `67A1 66DA 654C 6413 ...` carry the low bytes of
the vibrato frames between them, `6AA1 69DA 684C 6913 ...`.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (WAVECMD_PORTADOWN,     # noqa: E402
                                      WAVECMD_PORTAUP)
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# Hunter_Patrol's G-6: `$684C` in the original's table, `$6853` in
# Goattracker's (note index 79), unit `$C7` -- the `$18E`, `$255`, `$C7` of the
# siddump above are 2, 3 and 1 of it.
G6 = S.SkydiveVibrato(counter=0, base=0x684C, step=0xC7, anchor=0x6853)


def test_the_oscillator_folds_the_counter_to_a_triangle():
    assert [S.vibrato_phase(c) for c in range(16)] == [0, 1, 2, 3, 3, 2, 1, 0] * 2


def test_every_frame_of_a_window_is_the_originals_vibrato_under_the_falling_byte():
    """Phase 1, 4 stores, counter 0 on frame 0. Frame 0 and the last are
    Goattracker's note; a store frame is the note's high byte less j over the
    low byte of the vibrato written that frame; every other frame is the
    vibrato -- in the ORIGINAL's table: `6813 69DA 67A1 6AA1 66DA 6913 654C`
    are the first stores and vibrato frames of Hunter_Patrol's siddump."""
    assert S.skydive_targets(1, 4, G6) == [
        0x6853,                    # 0: Goattracker's note
        0x6813,                    # 1: store 0, vibrato 1 ($6913) under $68
        0x69DA,                    # 2: vibrato 2
        0x67A1,                    # 3: store 1, vibrato 3 ($6AA1) under $67
        0x6AA1,                    # 4: vibrato 3
        0x66DA,                    # 5: store 2, vibrato 2 ($69DA) under $66
        0x6913,                    # 6: vibrato 1
        0x654C,                    # 7: store 3, vibrato 0 ($684C) under $65
        0x6853]                    # 8: back on Goattracker's note


class _Rows:
    """A speed table that hands out one row per distinct magnitude."""

    def __init__(self):
        self.rows = {}

    def __call__(self, magnitude):
        return self.rows.setdefault(magnitude, len(self.rows) + 1)

    def magnitude(self, index):
        return next(m for m, i in self.rows.items() if i == index)


def _play(program, rows, multiplier=1, first=None):
    """The frequency after every play call of `program` (gplay.c:520-725:
    a note step sets the frequency, a portamento command moves it, nothing
    else runs on a command frame)."""
    freq, out = None, []
    for left, right in program:
        if left == 0xFF:
            break
        assert left != 0x00 or right == 0x00, "a step that leaves the vibrato running"
        assert left == 0x00 or left >= 0xF0, "a delay runs the row's vibrato"
        if left == 0x00:
            freq = 0x6853
        else:
            assert right != 0, "speed 0 is the byte before the table, not a speed"
            move = rows.magnitude(right)
            freq += move if left == WAVECMD_PORTAUP else -move
            assert left in (WAVECMD_PORTAUP, WAVECMD_PORTADOWN)
        out.append(freq)
    return out


def test_the_program_walks_the_targets_one_command_a_frame():
    rows = _Rows()
    prog = S.skydive_program(1, 4, True, None, vib=G6, speed_row=rows)
    assert _play(prog, rows) == S.skydive_targets(1, 4, G6)
    assert prog[-1] == (0xFF, 0x00)
    assert len(prog) == 9 + 1


def test_a_frame_that_moves_nothing_is_a_row_of_speed_zero():
    """Counter 7 puts the oscillator at its low point on frame 1, where
    store 0 is the note itself: a zero move, which must still be a command
    (a delay would run the row's vibrato), against a speed row that holds 0."""
    rows = _Rows()
    vib = S.SkydiveVibrato(counter=7, base=0x6853, step=0xC7)
    prog = S.skydive_program(1, 3, True, None, vib=vib, speed_row=rows)
    assert 0 in rows.rows
    assert _play(prog, rows) == S.skydive_targets(1, 3, vib)


@pytest.mark.parametrize("multiplier", [2, 3])
def test_above_s1_a_frame_is_the_same_movement_in_multiplier_calls(multiplier):
    """Only a frame's last call is sampled, so how the movement divides is
    free, but it has to add up: after every frame's last call the voice is on
    that frame's target, the remainder spread over the calls."""
    rows = _Rows()
    prog = S.skydive_program(0, 5, True, None, multiplier, vib=G6,
                             speed_row=rows)
    calls = _play(prog, rows, multiplier)
    targets = S.skydive_targets(0, 5, G6)
    first = multiplier - S.skydive_row_offset(multiplier)
    ends = []
    at = first
    ends.append(at - 1)
    for _ in targets[1:]:
        at += multiplier
        ends.append(at - 1)
    assert [calls[e] for e in ends] == targets
    assert len(calls) == ends[-1] + 1


def test_the_held_program_is_still_the_one_without_a_vibrato():
    """No `vib`: the pitch-independent pairs of 7.ppppppp, unchanged."""
    got = S.skydive_program(1, 4, True, lambda k: 0x40 + k)
    assert got == [(0x00, 0x00), (0x00, 0x00), (0x00, 0x00),
                   (0xF2, 0x41), (0xF1, 0x41),
                   (0xF2, 0x42), (0xF1, 0x42),
                   (0xF2, 0x43), (0xF1, 0x43),
                   (0xFF, 0x00)]


@needs_corpus
def test_the_oscillator_counter_is_the_skydives_in_every_file_that_carries_one():
    seen = {}
    for name in ("Hunter_Patrol", "Gremlins", "5_Title_Tunes",
                 "Master_of_Magic", "Zoids", "One_Man_and_his_Droid",
                 "Last_V8", "Last_V8_C128_version"):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = detect(sid, lambda *a, **k: None)
        seen[name] = (S.triangle_counter(sid), det.skydive.counter)
    assert all(a == b and a is not None for a, b in seen.values()), seen
    # the classic-vibrato files have no such oscillator to read
    for name in ("Formula_1_Simulator", "Proteus"):
        assert S.triangle_counter(load_sid(str(CORPUS / f"{name}.sid"))) is None


@needs_corpus
def test_hunter_patrols_unit_is_the_one_the_originals_trace_shows():
    sid = load_sid(str(CORPUS / "Hunter_Patrol.sid"))
    assert S.window_vibrato(sid, 2, 79, 0) == G6
    assert S.window_vibrato(sid, 2, 79, 3).counter == 3
    # a record that stores 15 or more shifts the interval to nothing
    assert S.window_vibrato(sid, 15, 79, 0) is None
    assert S.window_vibrato(sid, None, 79, 0) is None
    det = detect(sid, lambda *a, **k: None)
    shifts = S.skydive_vibrato_shifts(sid, det, S.skydive_records(sid, det, 64))
    # the records whose byte is 188, 255, 55 ... have no vibrato to carry
    assert shifts == {4: 2, 43: 8}


def _converted(name, **extra):
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


@needs_corpus
def test_hunter_patrol_carries_what_the_wavetable_has_room_for(monkeypatch):
    """The carried program is pitch-specific, so one is laid out where the
    held layout leaves room and the other rows keep the held program."""
    _sng, lines = _converted("Hunter_Patrol")
    log = [m for m in lines if m.startswith("Skydive (bit $02)")][0]
    assert "14 window row(s)" in log and "carrying the vibrato" in log, log
    monkeypatch.setattr(S, "CARRY_VIBRATO", False)
    _sng, lines = _converted("Hunter_Patrol")
    assert not any("carrying" in m for m in lines)


@needs_corpus
def test_a_budget_of_nothing_carries_nothing():
    with S.vibrato_carry(True, (0, 0)):
        _sng, lines = _converted("Hunter_Patrol")
    assert not any("carrying" in m for m in lines)


@needs_corpus
def test_a_compilation_keeps_every_player_the_carried_programs_would_cost_it(
        monkeypatch):
    """5_Title_Tunes is five players behind one dispatch, appended into one
    255-row wavetable. Carrying its subtune 1's windows without a limit
    needed 269 rows and left players 2-4 out (the log: `wave table needs 269
    rows > 255`); converted held to what the held layout leaves over it keeps
    all five, and still carries."""
    # The table this is about is the one before `goatwriter.dead_blocks`
    # dropped the blocks of the records no pattern names (that arm: see
    # test_dead_blocks.py).
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    import h2g.convert as C
    sng, lines = _converted("5_Title_Tunes")
    assert sng[C.HEADER_LEN] == 5
    assert any("carried programs held to" in m for m in lines), lines[:3]
    assert any(m.startswith("[player 1] Skydive") and "carrying the vibrato" in m
               for m in lines), [m for m in lines if "Skydive" in m]
    assert not any("NOT APPENDED" in m for m in lines)
    # the unlimited conversion is the one that loses them
    with S.vibrato_carry(True, (255, 255)):
        sng, lines = _converted("5_Title_Tunes")
    assert sng[C.HEADER_LEN] < 5
    assert any("NOT APPENDED" in m for m in lines)


def _windows(trace, nframes):
    """{voice: [(first store frame, last store frame)]} of the ORIGINAL's
    windows -- runs of frames two apart whose gated high byte sits below the
    one the note attacked with (tests/test_skydive.py's `_store_frames`)."""
    out = {}
    for vi, v in enumerate(trace):
        fq = fidelity.register_timeline(v.freq_events, nframes)
        wf = fidelity.register_timeline(v.wf_events, nframes)
        onset, stores = 0, []
        for f in range(1, nframes):
            if wf[f] & 1 and not wf[f - 1] & 1:
                onset = fq[f] >> 8
            hi = fq[f] >> 8
            if wf[f] & 1 and hi < onset and onset - hi <= 0x20:
                stores.append(f)
        runs = []
        for f in stores:
            if runs and f - runs[-1][1] <= 2:
                runs[-1][1] = f
            else:
                runs.append([f, f])
        out[vi] = [tuple(r) for r in runs]
    return out


def _window_frames(name, sub, seconds, tmp_path, monkeypatch):
    """({voice: {tag: (frames within $40 of the original, frames exactly
    equal)}}, {voice: frames in the original's windows}) for the conversion
    with the carried programs and without them, through gt2reloc and
    siddump, lag-aligned."""
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / f"{name}.sid", seconds, sub)
    windows = _windows(orig, n)

    def measure(tag):
        sng, _ = _converted(name)
        work = tmp_path / tag
        work.mkdir()
        packed = fidelity.pack_sid(sng, work)
        assert packed is not None and packed.exists(), tag
        ours = fidelity.run_siddump(packed, seconds, sub)
        lag = fidelity.startup_lag(orig, ours)[0]
        out = {}
        for vi in range(3):
            fo = fidelity.register_timeline(orig[vi].freq_events, n)
            fu = fidelity.register_timeline(ours[vi].freq_events, n + lag)
            frames = [f for lo, hi in windows[vi] for f in range(lo, hi + 1)]
            out[vi] = (sum(abs(fu[f + lag] - fo[f]) <= 0x40 for f in frames),
                       sum(fu[f + lag] == fo[f] for f in frames))
        return out

    carried = measure("carried")
    monkeypatch.setattr(S, "CARRY_VIBRATO", False)
    held = measure("held")
    total = {vi: sum(hi - lo + 1 for lo, hi in windows[vi]) for vi in range(3)}
    return carried, held, total


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_packed_window_follows_the_originals_frequency_on_every_frame(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump, 30 s of Hunter_Patrol: on every frame
    from a window's first store to its last, the frequency (not only the
    high byte) is the original's -- the stores AND the vibrato frames between
    them. The held program agrees on the stores' high byte and sits at the
    note between them, up to `$255` off, and is never exactly equal.

    The wavetable's own end has room for ONE carried program here, which two
    windows of voice 2 share (frames 300-320 and 516-536 at lag 7; 30 s holds
    three a voice, 21 frames each). Voice 1's has none there, and gets the
    rows of Hunter_Patrol's duplicate instrument blocks instead
    (`note_rise.reclaimable_holes`, `skydive.reusable_runs`): before that it
    stayed on the held program (`carried[0] == held[0]`, 25 frames of 63)."""
    # The table this is about is the one before `goatwriter.dead_blocks`
    # dropped the blocks of the records no pattern names (that arm: see
    # test_dead_blocks.py).
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    carried, held, total = _window_frames("Hunter_Patrol", 0, 30, tmp_path,
                                          monkeypatch)
    assert total[0] >= 63 and total[1] >= 63, total
    assert carried[1][1] == 42, (carried, held, total)      # 2 windows x 21
    assert held[1][1] == 0 and held[0][1] == 0, (carried, held, total)
    assert carried[0][1] == 42, (carried, held, total)      # voice 1: the rows
    assert carried[0][0] >= held[0][0] + 20, (carried, held, total)
    assert carried[1][0] >= held[1][0] + 20, (carried, held, total)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_packed_note_row_window_follows_the_originals_frequency(
        tmp_path, monkeypatch):
    """Zoids subtune 2, 15 s: the one window (35 stores from frame 413, on
    the note row, GT 9's own wave program merged in) is the original's
    frequency on all 63 frames of it; held, on none.

    With Zoids' tie windows off: the layout that places them holds this
    program (the table has room for one carried program beside the held one
    they jump into, tests/test_skydive_tie_window.py), and this pins the
    carried program itself."""
    monkeypatch.setattr(S, "SKYDIVE_TIE_NEXT_COMMANDS", frozenset())
    carried, held, total = _window_frames("Zoids", 2, 15, tmp_path,
                                          monkeypatch)
    assert total[0] == 63, total
    assert carried[0] == (63, 63), (carried, held, total)
    assert held[0][1] == 0 and held[0][0] < 63, (carried, held, total)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_above_s1_a_carried_window_is_the_originals_frequency_call_for_call(
        tmp_path, monkeypatch):
    """One_Man_and_his_Droid packs at -S2 and has no room for a carried
    program beside its held one (100 steps against 47 free rows), so the
    held programs are swapped for a one-step no-op here to leave the room,
    and the three rows that ask for a carried program get it. Packed at -S2
    and traced at -m2, thirty seconds: the five windows those rows open (43
    frames each, and the 9 the thirty seconds cut off) are the original's
    frequency on every frame; the windows on the other rows, which now hold
    the no-op, are on none of them."""
    seconds, n = 30, 30 * 50
    real = S.skydive_program

    def only_carried(phase, writes, alt, speed_index, multiplier=1, vib=None,
                     speed_row=None):
        if vib is None:
            return [(0x00, 0x80), (0xFF, 0x00)]
        return real(phase, writes, alt, speed_index, multiplier, vib=vib,
                    speed_row=speed_row)
    monkeypatch.setattr(S, "skydive_program", only_carried)
    sng, lines = _converted("One_Man_and_his_Droid")
    assert any("carrying the vibrato on 3 row(s)" in m for m in lines), lines
    orig = fidelity.run_siddump(CORPUS / "One_Man_and_his_Droid.sid", seconds, 0)
    windows = _windows(orig, n)
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=2)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, seconds + 1, 0, calls=2)
    lag = fidelity.startup_lag(orig, ours)[0]
    exact = []
    for vi in (0, 1):
        fo = fidelity.register_timeline(orig[vi].freq_events, n)
        fu = fidelity.register_timeline(ours[vi].freq_events, n + lag)
        exact += [sum(fu[f + lag] == fo[f] for f in range(lo, hi + 1))
                  for lo, hi in windows[vi]]
    assert sorted(e for e in exact if e) == [9, 43, 43, 43, 43], exact


@needs_corpus
def test_carrying_never_costs_a_note_row_program_its_place(monkeypatch):
    """Zoids has 252 of 255 wavetable rows: its row window and its two
    note-row windows fit exactly. A carried program four rows longer than the
    held one still fits as a row program, but then the note-row program does
    not -- and a carried program that costs another its place is refused, so
    the layout keeps both note rows.

    With Zoids' tie windows off (they hold the note-row program, see
    tests/test_skydive_tie_window.py)."""
    # The table this is about is the one before `goatwriter.dead_blocks`
    # dropped the blocks of the records no pattern names (that arm: see
    # test_dead_blocks.py).
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    monkeypatch.setattr(S, "SKYDIVE_TIE_NEXT_COMMANDS", frozenset())
    real = S.skydive_program

    def padded(phase, writes, alt, speed_index, multiplier=1, vib=None,
               speed_row=None):
        prog = real(phase, writes, alt, speed_index, multiplier, vib=vib,
                    speed_row=speed_row)
        return prog[:-1] + [(0x00, 0x80)] * 4 + prog[-1:] if vib else prog
    monkeypatch.setattr(S, "skydive_program", padded)
    _sng, lines = _converted("Zoids")
    log = [m for m in lines if m.startswith("Skydive (bit $02)")][0]
    assert "on the note row: 2 row(s), 1 program(s)" in log, log
    assert "carrying the vibrato on 0 row(s) and 2 on the note row" in log, log
