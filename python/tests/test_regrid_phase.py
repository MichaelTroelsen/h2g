"""`regrid_phase`: the extra frame goes on the ROWS the original puts it on.

IK+'s play routine runs two counters per call (`$E056`): an outer one that
underflows every 113 calls and skips the inner counter's decrement, and the
inner one (reload 2) whose reload call is a row step unless the outer counter
reads 0. A row is 3 calls and lasts 4 whenever an outer underflow falls inside
it -- 204 rows in the first pass, at frames fixed by the counters' power-on
values. Emulated from the file image, that lands on 539 of 539 voice-0 and 975
of 975 voice-1 attacks of a 180 s siddump of the original, frame for frame
(`C:/t/ik-plus-sub99-priority/model7.py`).

`regrid` spends the same debt as evenly spread pairs per PATTERN, which keeps
the rate and gives up the phase: a pattern played at four phases needs four
pairs. Measured at 5b64289, the first pass's rows start on the original's frame
21.2% of the time and drift up to 30 frames; with `regrid_phase` 99.4% and
never more than 1 frame (`C:/t/ik-plus-sub99-priority/rowtime.py`).
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


def _pattern(rows, cmd_at=None):
    p = []
    for r in range(rows):
        p += [0x60 + r, 1, 0, 0]
    p += [GT_END_PATTERN, 0, 0, 0]
    if cmd_at is not None:
        p[cmd_at * 4 + 2], p[cmd_at * 4 + 3] = 1, 0x20     # a portamento cell
    return p


def _sched(total, fours):
    return [BASE + 1 if i in fours else BASE for i in range(total)]


def _tempos(pattern):
    return {r: pattern[r * 4 + 3] for r in range(len(pattern) // 4)
            if pattern[r * 4 + 2] == CMD_SETTEMPO}


def test_a_repeat_whose_plays_differ_is_unrolled_into_one_clone_per_phase():
    patterns = [_pattern(8)]
    tracks = [[GT_REPEAT + 1, 0, GT_ORDER_RESTART, 0], [], []]
    # play 1 lengthens its row 2, play 2 its row 5 (global row 13)
    sched = _sched(16, {2, 13})
    written, done = regrid_phase_tempos(patterns, tracks, [BASE],
                                        lambda k, rows: sched)
    assert done == [0] and written == 2
    assert tracks[0][:2] == [1, 2] and tracks[0][2:] == [GT_ORDER_RESTART, 0]
    assert _tempos(patterns[0]) == {}, "the shared original is never written"
    assert _tempos(patterns[1]) == {2: BASE + 1, 3: BASE}
    assert _tempos(patterns[2]) == {5: BASE + 1, 6: BASE}


def test_plays_at_the_same_row_keep_one_clone_and_the_repeat_byte():
    patterns = [_pattern(8)]
    tracks = [[GT_REPEAT + 1, 0, GT_ORDER_RESTART, 0], [], []]
    sched = _sched(16, {2, 10})                      # row 2 of each play
    written, done = regrid_phase_tempos(patterns, tracks, [BASE],
                                        lambda k, rows: sched)
    assert done == [0]
    assert tracks[0] == [GT_REPEAT + 1, 1, GT_ORDER_RESTART, 0]
    assert _tempos(patterns[1]) == {2: BASE + 1, 3: BASE}
    assert len(patterns) == 2


def test_a_play_with_no_lengthened_row_keeps_its_original_pattern():
    patterns = [_pattern(8), _pattern(8)]
    tracks = [[0, 1, GT_ORDER_RESTART, 0], [], []]
    sched = _sched(16, {12})                         # only the second play
    regrid_phase_tempos(patterns, tracks, [BASE], lambda k, rows: sched)
    assert tracks[0][0] == 0 and tracks[0][1] == 2
    assert _tempos(patterns[1]) == {}


def test_an_occupied_command_column_moves_the_pair_not_the_command():
    patterns = [_pattern(12, cmd_at=2)]
    tracks = [[0, GT_ORDER_RESTART, 0], [], []]
    sched = _sched(12, {2})
    regrid_phase_tempos(patterns, tracks, [BASE], lambda k, rows: sched)
    clone = patterns[1]
    assert (clone[2 * 4 + 2], clone[2 * 4 + 3]) == (1, 0x20), "the portamento stays"
    pair = _tempos(clone)
    assert sorted(pair.values()) == [BASE, BASE + 1] and 2 not in pair


def test_a_subtune_with_no_schedule_is_left_alone():
    patterns = [_pattern(8)]
    tracks = [[0, GT_ORDER_RESTART, 0], [], []]
    written, done = regrid_phase_tempos(patterns, tracks, [BASE],
                                        lambda k, rows: None)
    assert (written, done) == (0, [])
    assert tracks[0] == [0, GT_ORDER_RESTART, 0] and len(patterns) == 1


@needs_corpus
def test_step_durations_reads_ik_plus_gate_and_declines_a_player_without_one():
    dur = step_durations(load_sid(str(CORPUS / "IK_plus.sid")), 7616)
    assert len(dur) == 7616 and set(dur) == {3, 4}
    fours = [i for i, d in enumerate(dur) if d == 4]
    assert len(fours) == 204 and fours[:3] == [36, 74, 111]
    # 113 calls per underflow, 3 per row: every 37 or 38 rows
    assert {b - a for a, b in zip(fours, fours[1:])} == {37, 38}
    assert step_durations(load_sid(str(REPO_ROOT / "Commando.sid")), 100) is None


def _row_starts_ik_plus(regrid_phase):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "IK_plus.sid")
    opts["regrid_phase"] = regrid_phase
    sng = songview.parse_sng(convert(str(CORPUS / "IK_plus.sid"),
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


def _exact_share(starts):
    dur = step_durations(load_sid(str(CORPUS / "IK_plus.sid")), len(starts))
    ideal = [0]
    for d in dur:
        ideal.append(ideal[-1] + d)
    n = min(len(starts), len(ideal))
    off = [starts[i] - ideal[i] for i in range(n)]
    return sum(1 for x in off if x == 0) / n, max(abs(x) for x in off)


@needs_corpus
def test_ik_plus_rows_start_on_the_originals_frame_with_regrid_phase():
    share, worst = _exact_share(_row_starts_ik_plus(True))
    assert share > 0.99 and worst <= 1, (share, worst)


@needs_corpus
def test_ik_plus_rows_do_not_without_it():
    # the pattern-global schedule: 21.2% exact, drifting up to 30 frames
    share, worst = _exact_share(_row_starts_ik_plus(False))
    assert share < 0.3 and worst > 10, (share, worst)
