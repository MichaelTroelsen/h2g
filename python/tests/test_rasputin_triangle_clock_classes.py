"""A swept record whose notes sound at more than one clock gets a clone per
clock class (`tri_clock`): Rasputin's record 0, whose one speed ran 43% fast
at R = 2 and 4% slow at R = 120 (`track_set_tick_ratios`' docstring).

Measured at 9a0a452, 310 s, subtune 0, voice 0, the complete legs' ramp per
tempo section (turn frames excluded, so the emitted speed times the
multiplier), original / one speed per record / this change:
R2 82.3 / 122.0 / 86.0, R3 92.2 / 122.0 / 96.0, R5 105.3 / 122.0 / 106.0,
R60 121.3 / 122.0 / 122.0. The same sections over every sweeping frame, holds
counted: original 85.3, 96.0, 105.2, 114.6, 125.7, 127.5 (R2, R3, R5, R10,
R60, R120); ours 81.0, 90.9, 97.2, 116.0, 114.0, 115.0. What is left of that
gap at R5 and above is the turn-frame dilution (`tri-turn-frame-dilution`),
the same 5-9% in the unsplit file.
"""
import json
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import (apply_tempo_duty_edits,          # noqa: E402
                            clock_classes, tri_clock_plan,
                            tri_clock_split_plan, TriClockPlan)
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent
_RAS = "Rasputin.sid"
_SECONDS = 180


def _quiet(*_a, **_k):
    pass


def _ras():
    sid = load_sid(str(CORPUS / _RAS))
    return sid, detect(sid, _quiet)


F = Fraction

# Record 0's clocks and the ticks they sound, as the walk reads them at 9a0a452
# (calls a tick over the multiplier; R = 120, 60, 10, 6/5, 3, 2).
RAS_ITEMS = [(F(1008, 1000), 3000), (F(1017, 1000), 740), (F(1100, 1000), 640),
             (F(1167, 1000), 30), (F(1200, 1000), 450), (F(1333, 1000), 170),
             (F(1500, 1000), 70)]
RAS_OWN = F(1057, 1000)


# --- the classes ---------------------------------------------------------------

def test_notes_the_record_serves_make_no_class():
    items = [(F(1008, 1000), 900), (F(1100, 1000), 100)]
    assert clock_classes(items, RAS_OWN) == []


def test_rasputins_far_clocks_make_three_classes_each_near_its_notes():
    reps = clock_classes(RAS_ITEMS, RAS_OWN)
    assert len(reps) == 3 and reps == sorted(reps)
    for r, _w in RAS_ITEMS:
        best = min(abs(r / c - 1) for c in [RAS_OWN] + reps)
        assert best <= F(7, 100), (r, best)
    assert F(115, 100) < reps[0] < F(125, 100)
    assert F(128, 100) < reps[1] < F(138, 100)
    assert F(142, 100) < reps[2] <= F(150, 100)


def test_near_clocks_share_a_class_and_the_limit_is_honoured():
    near = [(F(1200, 1000), 10), (F(1210, 1000), 10), (F(1195, 1000), 5)]
    assert len(clock_classes(near, RAS_OWN)) == 1
    assert len(clock_classes(RAS_ITEMS, RAS_OWN, limit=1)) == 1
    assert len(clock_classes(RAS_ITEMS, RAS_OWN, limit=2)) == 2


def test_a_class_is_the_weighted_mean_of_its_clocks():
    """Two clocks 4% apart, one four times as heard: the class sits at the
    mean the ticks give, which is how `track_set_tick_ratios` makes a
    record's."""
    items = [(F(120, 100), 400), (F(125, 100), 100)]
    (rep,) = clock_classes(items, RAS_OWN)
    assert rep == F(121, 100)


# --- the plan on Rasputin ---------------------------------------------------------

@needs_corpus
def test_record_zero_has_three_classes_and_record_eleven_none():
    from h2g import convert as C
    import fidelity as F_
    import h2g.goatwriter.build as B
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = F_._preset_opts(doc, _RAS)
    seen = {}
    real = B._gw_tri_clock.tri_clock_plan

    def spy(*a, **k):
        seen["plan"] = real(*a, **k)
        return seen["plan"]
    B._gw_tri_clock.tri_clock_plan = spy
    try:
        C.convert(str(CORPUS / _RAS), log=_quiet, **opts)
    finally:
        B._gw_tri_clock.tri_clock_plan = real
    plan = seen["plan"]
    assert set(plan.classes) == {0}
    assert len(plan.classes[0]) == 3
    # the record's own program is the one it always had
    assert Fraction(103, 100) < plan.own[0] < Fraction(108, 100)
    assert plan.classes[0][0] > plan.own[0]
    heard = {}
    for rec, cls, ticks in plan.notes.values():
        heard[cls] = heard.get(cls, 0) + ticks
    assert set(heard) == {0, 1, 2, 3}
    assert heard[0] > 4 * (heard[1] + heard[2] + heard[3]) / 2


@needs_corpus
def test_the_plan_declines_where_there_is_no_track_set_gate():
    c = load_sid(str(CORPUS / "Commando.sid"))
    p = [0x60, 1, 0, 0, 0xFF, 0, 0, 0]
    assert tri_clock_plan(c, detect(c, _quiet), [[0, 0xFF, 0]] * 3, [p], 0, 1,
                          {}) is None


# --- the split on synthetic orderlists ---------------------------------------------

def _plan(notes):
    """notes: {(track, position, row): (record, class, ticks)}"""
    return TriClockPlan(own={0: F(1)}, classes={0: [F(12, 10), F(14, 10)]},
                        notes=notes)


def _pattern(*rows):
    out = []
    for note, instr in rows:
        out += [note, instr, 0, 0]
    return out + [0xFF, 0, 0, 0]


def test_a_pattern_every_play_of_which_wants_a_class_is_renamed_in_place():
    pats = [_pattern((0x60, 1), (0x62, 0), (0x64, 1))]
    tracks = [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 1, 4), (0, 0, 1): (0, 1, 4),
                  (0, 0, 2): (0, 1, 4)})
    got = tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 62)
    assert got.clones == [(1, 5, 1)]
    assert got.tracks == tracks and len(got.patterns) == 1
    out = apply_tempo_duty_edits(got.patterns, got)
    assert [out[0][4 * k + 1] for k in range(3)] == [5, 0, 5]


def test_a_pattern_played_at_two_classes_is_copied_for_the_minority():
    pats = [_pattern((0x60, 1), (0x62, 1))]
    tracks = [[0, 0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 0, 4), (0, 0, 1): (0, 0, 4)})
    plan.notes.update({(0, 1, 0): (0, 2, 4), (0, 1, 1): (0, 2, 4)})
    got = tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 62)
    assert got.clones == [(1, 5, 2)]
    assert len(got.patterns) == 2
    assert got.tracks[0][:2] == [0, 1]           # the second play is the copy
    out = apply_tempo_duty_edits(got.patterns, got)
    assert [out[0][1], out[0][5]] == [1, 1]
    assert [out[1][1], out[1][5]] == [5, 5]


def test_a_sticky_instrument_is_named_where_the_new_walk_needs_it():
    """Pattern 0 names the swept instrument and is played at class 2; pattern
    1 relies on it (no instrument byte) and is played right after at class 0:
    its first note must name the record again."""
    pats = [_pattern((0x60, 1)), _pattern((0x62, 0))]
    tracks = [[0, 1, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 2, 4), (0, 1, 0): (0, 0, 4)})
    got = tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 62)
    out = apply_tempo_duty_edits(got.patterns, got)
    assert out[0][1] == 5 and out[1][1] == 1


def test_no_room_for_a_clone_number_drops_the_least_heard_class_first():
    pats = [_pattern((0x60, 1), (0x62, 1))]
    tracks = [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 1, 900), (0, 0, 1): (0, 2, 100)})
    got = tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 5)
    # one number, two classes in one play: the play takes the heavier vote
    assert got.clones == [(1, 5, 1)]
    plan2 = _plan({(0, 0, 0): (0, 1, 100), (0, 1, 0): (0, 2, 900)})
    tracks2 = [[0, 0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    got2 = tri_clock_split_plan(tracks2, pats, plan2, {1: 0}, 5, 5)
    assert got2.clones == [(1, 5, 2)]            # class 1 (100 ticks) gave way


def test_a_class_with_no_pulse_room_keeps_the_record():
    pats = [_pattern((0x60, 1))]
    tracks = [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 1, 4)})
    assert tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 62,
                                unavailable={(0, 1)}) is None


def test_a_copy_past_the_pattern_limit_drops_the_class_instead():
    pats = [_pattern((0x60, 1))] * 208
    tracks = [[0, 0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 0, 4), (0, 1, 0): (0, 1, 4)})
    assert tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 62) is None


def test_a_tie_that_would_need_the_instrument_named_declines():
    from h2g.goatwriter.constants import CMD_TONEPORTA
    tie = [0x62, 0, CMD_TONEPORTA, 0, 0xFF, 0, 0, 0]
    pats = [_pattern((0x60, 1)), tie]
    tracks = [[0, 1, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    plan = _plan({(0, 0, 0): (0, 2, 4)})
    assert tri_clock_split_plan(tracks, pats, plan, {1: 0}, 5, 62) is None


# --- the converter -------------------------------------------------------------------

def _convert_ras(lines=None):
    from h2g import convert as C
    import fidelity as F_
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = F_._preset_opts(doc, _RAS)
    sng = C.convert(str(CORPUS / _RAS), log=(lines.append if lines is not None
                                               else _quiet), **opts)
    return sng, doc


@needs_corpus
def test_rasputin_gains_three_clones_of_record_zero_each_with_its_own_speed():
    import songview
    lines = []
    sng, _doc = _convert_ras(lines)
    song = songview.parse_sng(sng)
    sid, det = _ras()
    ptbl = song.tables["PTBL"]
    base = song.instruments[0]
    clones = [i for i in song.instruments[-3:]]
    assert [c.name for c in clones] == [base.name] * 3
    for c in clones:
        assert (c.ad, c.sr, c.wave_ptr, c.vib_ptr, c.firstwave) == (
            base.ad, base.sr, base.wave_ptr, base.vib_ptr, base.firstwave)
        assert c.pulse_ptr != base.pulse_ptr
    speeds = []
    for c in clones:
        # entry 1: the set; entry 2: the first ramp (ticks, speed)
        speeds.append(ptbl[c.pulse_ptr][1])
    # the record's own speed is 61; the classes are slower, in descending order
    own = ptbl[base.pulse_ptr][1]
    assert own == 61
    assert speeds == sorted(speeds, reverse=True) and speeds[0] < own
    # and they are the speeds the class ratios give
    for s, r in zip(speeds, (1.196, 1.321, 1.49)):
        assert abs(s - 128 / (2 * r)) <= 1.5, (s, r)
    assert any(l.startswith("tri clock split: 3 clone(s)") for l in lines)


@needs_corpus
def test_every_other_instrument_and_the_record_itself_keep_their_bytes():
    """The clones are appended: no existing record's bytes move but the
    patterns' instrument columns and the (longer) pulse table."""
    import songview
    sng, _doc = _convert_ras()
    song = songview.parse_sng(sng)
    # 45 before the two clones of the EOR toggle's late first toggle (a note
    # fetched on a skip row of the R 10 and R 60 gates, `clock_residue`)
    assert len(song.instruments) == 47
    assert len(song.tables["PTBL"]) == 54


# --- the measurement --------------------------------------------------------------------

_SECTIONS = [(0, 23, "R2"), (23, 36.7, "R3"), (36.7, 91.9, "R5"),
             (114.5, 171.7, "R60")]


def _leg_rates(trace, nframes: int, band: tuple):
    """{section: (rate, frames)}: voice 0's width travel per frame inside the
    complete legs of the segments starting in each section (the harness's
    `ab` metric, turn frames dropped, holds counted)."""
    import fidelity as F_
    t = F_.register_timeline(trace[0].pulse_events, nframes)
    atk = sorted({a for a in trace[0].attack_frames if a < nframes}) + [nframes - 1]
    out = {name: [0, 0] for _lo, _hi, name in _SECTIONS}
    for a, b in zip(atk, atk[1:]):
        name = next((n for lo, hi, n in _SECTIONS if lo * 50 <= a < hi * 50), None)
        if name is None:
            continue
        lo = a + 2
        if b - lo < 6 or not all(band[0] <= t[f] < band[1] for f in range(lo, b)):
            continue
        if len({t[f] >> 8 for f in range(lo, b)}) < 3:
            continue
        seg = [t[f + 1] - t[f] for f in range(lo, b - 1)]
        nz = [x for x in seg if x]
        if len(nz) < len(seg) / 2 or max(abs(x) for x in nz) > 0x400:
            continue
        turns, last = [], 0
        for i, x in enumerate(seg):
            if x:
                sign = 1 if x > 0 else -1
                if last and sign != last:
                    turns.append(i)
                last = sign
        for t0, t1 in zip(turns, turns[1:]):
            inner = seg[t0:t1][1:-1]
            if inner:
                out[name][0] += sum(abs(x) for x in inner)
                out[name][1] += len(inner)
    return {n: (m / f if f else None, f) for n, (m, f) in out.items()}


@needs_corpus
def test_rasputins_packed_sweep_follows_the_original_in_every_section():
    """Re-taken over 180 s: in each tempo section both sides measure, the
    packed ramp is within 8% of the original's (the shipped one-speed program
    read +48%, +32%, +16% at R = 2, 3, 5)."""
    import fidelity as F_
    sng, doc = _convert_ras()
    if not Path(F_.SIDDUMP).exists() or not Path(F_.GT2RELOC).exists():
        pytest.skip("siddump or gt2reloc not available here")
    mult = doc["songs"][_RAS]["multiplier"]
    sid, det = _ras()
    band = (det.pulse_tri_lo << 8, (det.pulse_tri_hi + 1) << 8)
    opts = F_._preset_opts(doc, _RAS)
    wd = Path(tempfile.mkdtemp(prefix="ras_tri_clock_"))
    try:
        blob, _ = F_.legalise_restarts(sng)
        packed = F_.pack_sid(blob, wd, F_.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        sub = F_.resolve_subtune(CORPUS / _RAS, "auto")
        ours = F_.run_siddump(packed, _SECONDS, sub, F_.SIDDUMP, calls=mult)
        local = wd / "o.sid"
        shutil.copyfile(CORPUS / _RAS, local)
        cal, _ = F_.table_calibration(CORPUS / _RAS, opts)
        orig = F_.run_siddump(local, _SECONDS, sub, F_.SIDDUMP, cal)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    mine = _leg_rates(ours, _SECONDS * 50, band)
    base = _leg_rates(orig, _SECONDS * 50, band)
    compared = 0
    for name in ("R2", "R3", "R5", "R60"):
        (a, na), (b, nb) = mine[name], base[name]
        if na < 8 or nb < 8:
            continue
        compared += 1
        assert abs(a / b - 1) <= 0.08, (name, a, b, mine, base)
    assert compared >= 3, (mine, base)
