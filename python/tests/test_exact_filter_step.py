"""A classic filter sweep keeps the player's per-FRAME step (`goatwriter.exact_step`).

The Goattracker filter table steps once per play CALL and the classic player
adds its record byte once per FRAME. At `-S3` Knucklebusters' record 1 steps
-19 a frame = -6.33 a call, which `_filter_step_per_call` rounds to -6: the sweep
runs 1 step a frame behind the original's for all 48 frames of its length, and
`cfrm` (slack 0x200, zero at 0x2200 off) reads 33% on Knucklebusters_1 with
every sweep entered on the right frame. Measured at a3792d2, -t 180, presets:
Knucklebusters_1 cfrm 33% -> 80%, Knucklebusters_3 68% -> 77%, the start song
unchanged.

**Two gates keep it off where it measured worse.** (1) `phase_free`: every
sweep-to-next-note gap of the record is a whole number of frames. The start
song's records 19/20 are struck every 28 calls = 9.33 frames, so their strikes
land on call phase 15, 16 or 17 in turn; an exact slope then scores the 1-2
call lead of two strikes in three, and the rounded slope's drift happens to
cancel part of it (cfrm .773 -> .677 on that subtune when forced). (2)
`DRIFT_FLOOR`: the rounded step must have drifted 32 cutoff steps by the end of
the sweep, the span in which `cfrm` gives credit; Lightforce's 21-frame records
15/16 gained cfrm but their exact travel pushed `cut` 1.046 -> 1.098.
"""
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.goatwriter import exact_step
from h2g.goatwriter.classic_filter_stop import SweepLengths
from h2g.goatwriter.constants import FILT_MODULATE


def _signed(b):
    return b - 256 if b >= 0x80 else b


@pytest.mark.parametrize("step,mult", [(0xED, 3), (0x1C, 3), (0xF0, 3),
                                       (0x1F, 3), (0x05, 2), (0x0F, 2)])
@pytest.mark.parametrize("window", exact_step.EXACT_STEP_WINDOWS)
def test_rows_keep_the_frames_total(step, mult, window):
    """Whole frames of `calls` travel exactly frames * step, whatever the window."""
    frames = 48
    rows = exact_step.exact_step_rows(step, mult, frames * mult, window)
    assert all(0 < n <= FILT_MODULATE for n, _ in rows)
    assert sum(n for n, _ in rows) == frames * mult
    assert sum(n * _signed(s) for n, s in rows) == frames * _signed(step)


def test_a_part_frame_runs_the_rounded_speed():
    rows = exact_step.exact_step_rows(0xED, 3, 3 * 6 + 2, 2)
    assert sum(n for n, _ in rows) == 3 * 6 + 2
    assert sum(n * _signed(sp) for n, sp in rows) == 6 * -19 + 2 * -6


def _sweeps(calls, gaps):
    s = SweepLengths(calls)
    s.gaps = gaps
    return s


def test_phase_free_reads_whole_frame_gaps():
    s = _sweeps({1: 144, 19: 84}, {1: [144, 144], 19: [28, 56, 84]})
    assert exact_step.phase_free(s, 1, 3)
    assert not exact_step.phase_free(s, 19, 3)
    assert not exact_step.phase_free(s, 7, 3)           # no gaps recorded
    assert not exact_step.phase_free({1: 144}, 1, 3)    # a plain dict has none


def test_wanted_needs_all_three():
    s = _sweeps({1: 144, 19: 84, 4: 42, 6: 144, 7: 144},
                {1: [144], 19: [28], 4: [42], 6: [36, 72], 7: [12]})
    # rec 1: step -19 at -S3 rounds to -6 (-18): 48 frames x 1 = 48 >= 32
    assert exact_step.wanted(s, 1, 0xED, 3, (-6) & 0xFF)
    # strikes off the frame grid
    assert not exact_step.wanted(s, 19, 0x1C, 3, 9)
    # a 14-frame sweep drifts only 14 steps
    assert not exact_step.wanted(s, 4, 0xED, 3, (-6) & 0xFF)
    # the multiplier divides the step: nothing to keep
    assert not exact_step.wanted(s, 6, 0x0F, 3, 5)
    # multiplier 1 never has a fractional step
    assert not exact_step.wanted(s, 7, 0xED, 1, 0xED)


def test_flags_off_keep_the_old_gates():
    s = _sweeps({1: 144}, {1: [28]})
    old = exact_step.PHASE_GATE
    try:
        exact_step.PHASE_GATE = False
        assert exact_step.phase_free(s, 1, 3)
    finally:
        exact_step.PHASE_GATE = old


# ---- the corpus ----------------------------------------------------------

PRESETS = Path(__file__).resolve().parents[2] / "presets.json"


def _filter_table(stem, monkeypatch, on):
    """(entries, pointers, sweep_calls) of the last `_filter_entries` call."""
    from fidelity import _preset_opts
    from h2g.convert import convert
    import h2g.goatwriter.build as build
    if on is not None:
        monkeypatch.setattr(exact_step, "EXACT_FRAME_STEP", on)
    doc = json.loads(PRESETS.read_text())
    seen = {}
    real = build._filter_entries

    def spy(*a, **k):
        r = real(*a, **k)
        seen["last"] = (r, k.get("sweep_calls"))
        return r
    monkeypatch.setattr(build, "_filter_entries", spy)
    out = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                  **_preset_opts(doc, f"{stem}.sid"))
    (entries, pointers), sweep = seen["last"]
    return out, entries, pointers, sweep


def _modulation_travel(entries, start):
    """Signed travel of the program at 1-based `start`, up to its FILT_STOP."""
    total = 0
    for left, right in entries[start - 1:]:
        if left == 0xFF:
            break
        if 0 < left <= FILT_MODULATE:
            total += left * _signed(right)
    return total


@needs_corpus
def test_knucklebusters_record_one_travels_the_players_total(monkeypatch):
    """Record 1 ($ED = -19 a frame, 144 calls = 48 frames at -S3): the set row
    carries the first frame's step, the modulation rows the other 47."""
    _o, e_on, p_on, _s = _filter_table("Knucklebusters", monkeypatch, True)
    _o, e_off, p_off, _s = _filter_table("Knucklebusters", monkeypatch, False)
    assert _modulation_travel(e_on, p_on[1]) == 47 * -19
    # the rounded one: (144 - 3) calls of -6
    assert _modulation_travel(e_off, p_off[1]) == 141 * -6


@needs_corpus
def test_the_start_songs_records_stay_rounded(monkeypatch):
    """Records 19 and 20 are struck on a 28-call grid: not phase free, so
    their rows are the rounded single speed with the flag on or off."""
    _o, e_on, p_on, s_on = _filter_table("Knucklebusters", monkeypatch, True)
    _o, e_off, p_off, _s = _filter_table("Knucklebusters", monkeypatch, False)
    assert not exact_step.phase_free(s_on, 19, 3)
    assert not exact_step.phase_free(s_on, 20, 3)
    for rec in (19, 20):
        n_on = _modulation_travel(e_on, p_on[rec])
        n_off = _modulation_travel(e_off, p_off[rec])
        assert n_on == n_off, rec


@needs_corpus
@pytest.mark.parametrize("stem", ["Food_Feud", "Deep_Strike"])
def test_files_without_a_wanted_record_do_not_move(stem, monkeypatch):
    on = _filter_table(stem, monkeypatch, True)[0]
    off = _filter_table(stem, monkeypatch, False)[0]
    assert on == off


@needs_corpus
def test_knucklebusters_bytes_depend_on_the_flag(monkeypatch):
    on = _filter_table("Knucklebusters", monkeypatch, True)[0]
    off = _filter_table("Knucklebusters", monkeypatch, False)[0]
    assert on != off


@needs_corpus
def test_the_shipped_default_is_the_exact_step(monkeypatch):
    """No flag touched: a plain conversion is the flag-on one, not the old table."""
    default = _filter_table("Knucklebusters", monkeypatch, None)[0]
    on = _filter_table("Knucklebusters", monkeypatch, True)[0]
    off = _filter_table("Knucklebusters", monkeypatch, False)[0]
    assert default == on != off
