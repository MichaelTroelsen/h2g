"""`regrid_phase`: a lengthened row on a pattern too short for a pair is carried.

I_Ball's orderlist joins its sections through pattern 8, ONE musical row long.
`regrid_phase_tempos` places a lengthened row as a pair (`CMD_SETTEMPO base+1`
on the row, `base` on the next) and needs a pattern of at least 4 rows, so the
original's 4-frame row that lands on pattern 8 was dropped with no count: rows
895, 2239 and 3135 of the 4928-row first pass. Each drop is one frame the row
grid never gets back, so the rows' starts walked 0 -> -1 -> -2 -> -3 frames
from the original's and only 18.2% of them were exact (measured at cb2d3e3,
`regrid_phase` forced, -t 180). The pair now goes to the NEXT play's first row
the guards allow (row 1), a one-row transient instead of a permanent loss:
99.6% exact, never more than 1 frame off.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO, step_durations      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,  # noqa: E402
                          GT_TRANSPOSE_DOWN, MAX_PATTERNS,
                          regrid_phase_tempos)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 3


def _pattern(rows):
    p = []
    for r in range(rows):
        p += [0x60 + r, 1, 0, 0]
    p += [GT_END_PATTERN, 0, 0, 0]
    return p


def _sched(total, fours):
    return [BASE + 1 if i in fours else BASE for i in range(total)]


def _tempos(pattern):
    return {r: pattern[r * 4 + 3] for r in range(len(pattern) // 4)
            if pattern[r * 4 + 2] == CMD_SETTEMPO}


def test_a_lengthened_row_on_a_one_row_pattern_moves_to_the_next_plays_row_1():
    patterns = [_pattern(8), _pattern(1)]
    tracks = [[0, 1, 0, GT_ORDER_RESTART, 0], [], []]
    sched = _sched(17, {8})                  # the one-row pattern's only row
    written, done = regrid_phase_tempos(patterns, tracks, [BASE],
                                        lambda k, rows: sched)
    assert done == [0] and written == 1
    assert _tempos(patterns[1]) == {}, "the short pattern is never written"
    assert tracks[0][0] == 0 and tracks[0][1] == 1, "plays 1 and 2 are as they were"
    clone = tracks[0][2]
    assert clone not in (0, 1)
    assert _tempos(patterns[clone]) == {1: BASE + 1, 2: BASE}


def test_the_carry_pays_exactly_one_frame_per_dropped_row():
    patterns = [_pattern(8), _pattern(1)]
    tracks = [[0, 1, 0, GT_ORDER_RESTART, 0], [], []]
    sched = _sched(17, {8})
    regrid_phase_tempos(patterns, tracks, [BASE], lambda k, rows: sched)
    frames = 0
    for p in (tracks[0][0], tracks[0][1], tracks[0][2]):
        pat = patterns[p]
        tempo = BASE
        for r in range(len(pat) // 4):
            if pat[r * 4] == GT_END_PATTERN:
                break
            if pat[r * 4 + 2] == CMD_SETTEMPO:
                tempo = pat[r * 4 + 3]
            frames += tempo
    assert frames == BASE * 17 + 1


def test_a_carry_with_no_following_play_is_left_undelivered():
    patterns = [_pattern(8), _pattern(1)]
    tracks = [[0, 1, GT_ORDER_RESTART, 0], [], []]
    sched = _sched(9, {8})
    written, done = regrid_phase_tempos(patterns, tracks, [BASE],
                                        lambda k, rows: sched)
    assert written == 0 and tracks[0][:2] == [0, 1]
    assert all(_tempos(p) == {} for p in patterns)


def _row_starts(name, regrid_phase):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name + ".sid")
    opts["regrid_phase"] = regrid_phase
    sng = songview.parse_sng(convert(str(CORPUS / (name + ".sid")),
                                     log=lambda m: None, **opts))
    plays, rep = [], 1
    for b in sng.tracks[0]:
        if b == GT_ORDER_RESTART:
            break
        if GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
            rep = b - GT_REPEAT + 1
        elif b < MAX_PATTERNS:
            plays += [b] * rep
            rep = 1
    starts, frame, tempo = [], 0, None
    for p in plays:
        pat = sng.patterns[p]
        for r in range(len(pat) // 4):
            note, _ins, cmd, dat = pat[r * 4:r * 4 + 4]
            if note == GT_END_PATTERN:
                break
            if cmd == CMD_SETTEMPO and dat < 0x80:
                tempo = dat
            starts.append(frame)
            frame += tempo or 6
    return starts


def _exact_share(name, starts):
    dur = step_durations(load_sid(str(CORPUS / (name + ".sid"))), len(starts))
    ideal = [0]
    for d in dur:
        ideal.append(ideal[-1] + d)
    n = min(len(starts), len(ideal))
    off = [starts[i] - ideal[i] for i in range(n)]
    return sum(1 for x in off if x == 0) / n, max(abs(x) for x in off)


@needs_corpus
def test_i_ball_rows_start_on_the_originals_frame_with_regrid_phase():
    share, worst = _exact_share("I_Ball", _row_starts("I_Ball", True))
    assert share > 0.99 and worst <= 1, (share, worst)


@needs_corpus
def test_i_ball_rows_ramp_without_it():
    # the pattern-global schedule (the shipped regrid_full_debt entry)
    share, worst = _exact_share("I_Ball", _row_starts("I_Ball", False))
    assert share < 0.2 and worst >= 4, (share, worst)


def test_presets_ship_regrid_phase_with_regrid_for_i_ball():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "I_Ball.sid")
    assert opts["regrid"] is True and opts["regrid_phase"] is True
