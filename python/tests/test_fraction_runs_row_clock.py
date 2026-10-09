"""`_fraction_runs` places its runs against the player's per-row clock.

Through v0.5.517 `_compensate_fractional_rows` costed an entry on the
restarted gate's own count (`restarted_gate_calls`) but handed
`_fraction_runs` the AVERAGE row `c`, measured each 16-row stretch from zero,
and dealt `|d|` over the stretches in proportion to their rows. Rasputin's
R = 6 clock steps 4, 4, 4, 6, 4, 4, 6 ... calls, so the placement cancelled
an error the player does not make and left the sawtooth about it standing; and
the entry whose last 32 rows each carry a portamento (nowhere to put a run)
handed +6 calls to the next, which could not start correcting before its
row 1. Against the finished .sng the worst gap to the player's clock on voice
2 was 9.0 calls (4.5 frames, frame ~12616, past the 180 s window).

These tests pin the three parts of the answer: the per-row ideal and the
incoming error in the placement, the share dealt per 8-row stretch, and the
untouchable tail split between the dip before it and the carry after it.
"""
import json
import math
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import patterns as P  # noqa: E402
from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO, restarted_gate_calls  # noqa: E402
from h2g.patterns import (GT_NO_NOTE, MAX_PATTERNS,  # noqa: E402
                          _balanced_fraction_d, _compensate_fractional_rows,
                          _fraction_runs)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
END = [0xFF, 0, 0, 0]
CLOCK = (2, 6, 2)                         # Rasputin's R = 6 at -S2
AVERAGE = 2 * 7 / 6 * 2                   # the average row of that clock


def _bar(rows=64, taken_from=None, first=(CMD_SETTEMPO, 5), note=0x75):
    """One note on row 0 and `$BD` holds after it; from row `taken_from` on
    every row carries a portamento, so no run can sit there."""
    out = []
    for r in range(rows):
        out += [note, 3, 0, 0] if r == 0 else [GT_NO_NOTE, 0, 0, 0]
        if taken_from is not None and r >= taken_from:
            out[-2:] = [4, 0]
    out[2:4] = list(first)
    return out + END


def _gaps(track, patterns, clock):
    """Our cumulative calls minus the player's, row by row: a row lasts the
    `CMD_SETTEMPO` value in effect at its tick 0 (gplay.c:325/494)."""
    v, cum, j, out = None, 0, 0, []
    for e in track:
        pat = patterns[e]
        for r in range(0, len(pat), 4):
            if pat[r] == 0xFF:
                break
            if pat[r + 2] == CMD_SETTEMPO:
                v = pat[r + 3]
            cum += v
            j += 1
            out.append(cum - restarted_gate_calls(*clock, j))
    return out


def _run(patterns, track):
    return _compensate_fractional_rows(track, {0: 0}, {0: AVERAGE}, patterns,
                                       {}, clocks={0: CLOCK})


# --- the placement ---------------------------------------------------------

def _trajectory(pattern, runs, run_value, b, ideal_rows, err0):
    act = [b] * len(ideal_rows)
    for k1, n in runs:
        for k in range(k1, k1 + n):
            act[k] = run_value
    err, out = err0, []
    for k in range(len(ideal_rows)):
        err += act[k] - ideal_rows[k]
        out.append(err)
    return out


def test_the_incoming_error_is_corrected_where_it_is_met():
    """Entered 4 calls slow on a flat clock, with 4 rows to take back: the
    first stretch is dealt all four (its end must be back at zero), so the
    error is gone by row 8 -- where the average placement, which measured
    every stretch from zero and dealt the two stretches two each, still
    stands 2 calls out there."""
    pat = _bar(32, first=(CMD_SETTEMPO, 5))
    flat = [5.0] * 32
    new = _fraction_runs(pat, 32, -4, 5, 4, 5.0, flat, 4.0)
    old = _fraction_runs(pat, 32, -4, 5, 4, 5.0)
    t_new = _trajectory(pat, new, 4, 5, flat, 4.0)
    t_old = _trajectory(pat, old, 4, 5, flat, 4.0)
    assert sum(n for _k, n in new) == sum(n for _k, n in old) == 4
    assert t_new[-1] == t_old[-1] == 0.0
    assert t_new[7] == 0.0                      # zero at the first stretch's end
    assert t_old[7] == 2.0
    assert sum(map(abs, t_new)) < sum(map(abs, t_old))


def test_a_run_is_placed_against_the_rows_it_will_cost():
    """Two rows of 7 calls among rows of 5, so 4 calls to add: the run of
    four belongs over them (rows 3-6), where it keeps the gap to the clock
    within 1 call. Placed against the average (5.25 a row) the first
    position that looks as good is rows 6-9, which leaves the gap at -4."""
    pat = _bar(16)
    ideal = [5.0] * 4 + [7.0] * 2 + [5.0] * 10
    runs = _fraction_runs(pat, 16, 4, 5, 6, sum(ideal) / 16, ideal, 0.0)
    flat = _fraction_runs(pat, 16, 4, 5, 6, sum(ideal) / 16)
    assert runs == ((3, 4),) and flat == ((6, 4),)
    worst = lambda r: max(map(abs, _trajectory(pat, r, 6, 5, ideal, 0.0)))
    assert worst(runs) == 1.0 and worst(flat) == 4.0


def test_the_incoming_error_moves_the_run_inside_a_stretch():
    """Entered 2 calls slow, 4 to take back over a stretch whose rows cost
    the player 5 4 4 5 5 6 4 5 against our 5: the run of four starts on row 2
    (the error falls from 2 to 0 over rows 2-5, worst 3 in the stretch's
    sawtooth). Placed as if entered at zero it starts on row 3, and the
    worst is 4."""
    pat = _bar(8)
    ideal = [5.0, 4.0, 4.0, 5.0, 5.0, 6.0, 4.0, 5.0]
    runs = _fraction_runs(pat, 8, -4, 5, 4, 5.0, ideal, 2.0)
    assert runs == ((2, 4),)
    assert max(map(abs, _trajectory(pat, runs, 4, 5, ideal, 2.0))) == 3.0


def test_a_later_stretch_is_placed_after_the_runs_already_made():
    """Two stretches; the first takes a run of one that leaves the second a
    different error to start from. The second's run of two goes on row 9,
    where the gap stays within 1 call; read as if the first had made no run
    it goes on row 8 and the gap reaches 2."""
    pat = _bar(16)
    ideal = [6.0, 4.0, 6.0, 5.0, 4.0, 4.0, 4.0, 6.0,
             5.0, 5.0, 4.0, 5.0, 5.0, 4.0, 5.0, 5.0]
    runs = _fraction_runs(pat, 16, -3, 5, 4, 5.0, ideal, 0.0)
    assert runs == ((4, 1), (9, 2))
    assert max(map(abs, _trajectory(pat, runs, 4, 5, ideal, 0.0))) == 1.0


def test_the_average_path_is_what_it_was():
    """Without `ideal_rows` the answer still depends on the pattern and `d`
    alone, and is the 16-row placement `test_fractional_row_tempo` reads."""
    pat = _bar(64)
    a = _fraction_runs(pat, 64, -6, 5, 4, 16 / 3)
    b = _fraction_runs(pat, 64, -6, 5, 4, 16 / 3)
    assert a == b
    assert all(k2 - k1 <= 16 for k1, k2 in ((k, k + n) for k, n in a))
    assert sum(n for _k, n in a) == 6


# --- the untouchable tail --------------------------------------------------

def test_the_tail_is_split_between_the_dip_and_the_carry():
    """64 rows at b = 5 against a flat 4.667, the last 32 taken: the tail
    drifts +10.67 calls whatever is asked. `d` zeroing the end would be -21
    (dipping to about -10.7 and handing on zero); leaving the tail to the
    next entry -10.7 + 10.7 = -0 + 10.67; the split is -16."""
    pat = _bar(64, taken_from=32)
    ideal = [14 / 3] * 64
    assert _balanced_fraction_d(pat, 64, 5, ideal, 0.0) == -16
    # An incoming error moves it call for call.
    assert _balanced_fraction_d(pat, 64, 5, ideal, 3.0) == -19


def test_without_a_tail_it_is_the_end_of_pattern_rule():
    pat = _bar(64)
    ideal = [14 / 3] * 64
    assert _balanced_fraction_d(pat, 64, 5, ideal, 0.0) == \
        int(round(sum(ideal) - 64 * 5))
    assert _balanced_fraction_d(_bar(64, taken_from=1), 64, 5, ideal,
                                0.0) == 0


def test_a_tail_entry_dips_and_hands_on_half():
    patterns = [_bar(taken_from=32, note=0x75 + k) for k in range(4)]
    track = [0, 1, 2, 3]
    done, left = _run(patterns, track)
    gaps = _gaps(track, patterns, CLOCK)
    assert done == 4
    # Before this the same input read 10 calls worst; each entry now dips by
    # about half its tail and carries about half on, instead of handing the
    # whole of it to the next entry.
    assert max(map(abs, gaps)) <= 8, gaps
    assert min(gaps[:32]) <= -4          # it does dip: that is the design
    assert left == pytest.approx(gaps[-1])


def test_a_free_pattern_stays_within_a_sawtooth_of_the_clock():
    patterns = [_bar(note=0x75 + k) for k in range(4)]
    track = [0, 1, 2, 3]
    done, left = _run(patterns, track)
    gaps = _gaps(track, patterns, CLOCK)
    assert done == 4 and left == 0.0 and gaps[-1] == 0
    assert max(map(abs, gaps)) <= 2, gaps    # 4 against the 16-row stretch


# --- the file --------------------------------------------------------------

def _rasputin_opts():
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    return F._preset_opts(doc, "Rasputin.sid")


def _voice2_gaps(song, raw2):
    """`test_fractional_row_tempo._voice2_clock_error`, keeping every row's
    gap instead of the worst: our cumulative calls against the player's
    clock for the `$FE` in effect (each change restarts the gate's count)."""
    reloads = [r for _at, r in sorted(raw2.items())]
    k, v, ours, seg, j, rep = -1, None, 0.0, 0.0, 0, 1

    def clock(r, rows):
        w = 2 * rows
        return 2 * (w + max(0, (w - 1) // r))

    out = []
    for e in song.tracks[2]:
        if e == 0xFF:
            break
        if 0xD0 <= e <= 0xDF:
            rep = e - 0xD0 + 1
            continue
        if e >= 0xE0:
            continue
        pat = song.patterns[e]
        plays, rep = rep, 1
        for _ in range(plays):
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:
                    break
                if pat[r + 2] == CMD_SETTEMPO:
                    v = pat[r + 3]
                    if r == 0:
                        if k >= 0:
                            seg += clock(reloads[k], j)
                        k += 1
                        j = 0
                ours += v
                j += 1
                out.append(ours - seg - clock(reloads[k], j))
    return out


@needs_corpus
def test_rasputin_voice_2_stays_within_three_frames_of_the_player():
    """The .sng read back by songview, row by row against the restarted
    clock. v0.5.517 read 9.0 calls worst (4.5 frames) with an RMS of 1.17,
    58 rows 4 or more calls out, 15 seven or more and 117 patterns; against
    the row it reads 6.0 (3 frames) with an RMS of 0.74, 21 rows at 4 or more,
    none at 7 and 166 patterns. The two entries that set the worst are the R = 6 pattern whose
    last 32 rows carry a portamento and the one after it: a tail of +10.7
    calls that no run can reach, so half of it is a dip before and half a
    carry after."""
    import songview
    sid, det = _detect_tables(load_sid(str(CORPUS / "Rasputin.sid")),
                              lambda *a, **k: None)
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    blob = convert(str(CORPUS / "Rasputin.sid"), log=lambda *a, **k: None,
                   **_rasputin_opts())
    song = songview.parse_sng(blob)
    gaps = _voice2_gaps(song, raw[2])
    assert gaps and abs(gaps[-1]) <= 1.0, gaps[-1]
    assert max(map(abs, gaps)) <= 6.0, max(map(abs, gaps))
    rms = math.sqrt(sum(g * g for g in gaps) / len(gaps))
    assert rms <= 0.85, rms
    assert sum(1 for g in gaps if abs(g) >= 4) <= 30
    assert sum(1 for g in gaps if abs(g) >= 7) == 0
    # The copies cost patterns: the table has to keep room for what is
    # appended after this pass, and Goattracker's limit is silent.
    assert len(song.patterns) <= MAX_PATTERNS - 16, len(song.patterns)
