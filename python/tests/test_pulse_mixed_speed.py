"""A triangle step an integer speed misses by over 5% is laid as a MIX of the
two speeds either side of it (`pulse._mixed_legs`)
(`kentilla-triangle-speed-per-call-rounds-at`).

Kentilla's rate-$10 records step 16 a tick behind an outer gate of 10 at -S10:
11 calls a tick, 16 / 11 = 1.4545 a call, which `_lattice_legs` rounded to 1
(31% slow). Records 12-16 and 21 kept 3716 pulse-width mismatched frames over
600 s (re-taken at 841cf3d); laid as a mix they keep 356 (record 16's, whose
tied notes the original reseeds and ours does not, are the rest).
"""
import sys
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import detect                                 # noqa: E402
from h2g.goatwriter import pulse as P                         # noqa: E402
from h2g.sidfile import load_sid                              # noqa: E402

KENTILLA = "Kentilla.sid"
RATE = Fraction(16, 11)


def _quiet(*_a, **_k):
    pass


def _widths(entries, loop, calls):
    """Width after each call of a Goattracker pulse program (gplay.c:872-902):
    a set row spends its call; a modulation row (t, spd) adds spd for t calls;
    the program then jumps back to entry `loop` (0-based)."""
    out, ptr, width = [], 0, 0
    while len(out) < calls:
        if ptr >= len(entries):
            ptr = loop
        a, b = entries[ptr]
        ptr += 1
        if a >= 0x80:
            width = ((a & 0x0F) << 8) | b
            out.append(width)
            continue
        spd = b - 256 if b >= 128 else b
        for _ in range(a):
            width = (width + spd) & 0xFFF
            out.append(width)
    return out[:calls]


def _speeds(rows):
    return {(b - 256 if b >= 128 else b) for a, b in rows if a < 0x80}


# --- the rate ----------------------------------------------------------------

def test_the_exact_rate_of_kentillas_rate_10_is_sixteen_elevenths():
    assert P._tri_exact_rate(16, 1, 10, 10) == RATE
    assert P._tri_table_speed(16, 1, 10, 10) == 1, "the integer it rounded to"


def test_a_rate_within_five_percent_of_an_integer_keeps_the_integer():
    # 32 / 11 = 2.909 -> 3, 3.1% off (Kentilla record 2).
    assert P._tri_mixed_rate(32, 1, 10, 10) is None
    assert P._tri_mixed_rate(16, 1, 10, 10) == RATE
    assert P._tri_mixed_rate(48, 1, 10, 10) == Fraction(48, 11)   # 4.36 -> 4


def test_an_integer_rate_and_a_rate_under_one_or_over_127_are_not_mixed():
    assert P._tri_mixed_rate(4, 1, 1, None) is None       # exactly 4
    assert P._tri_mixed_rate(1, 4, 1, None) is None       # 0.25 a call
    assert P._tri_mixed_rate(0xE0 + 1, 1, 1, None) is None  # 225: spelled


# --- the rows ----------------------------------------------------------------

@pytest.mark.parametrize("calls,travel,lo", [
    (1056, 1536, 1), (1936, 2816, 1), (446, 1536, 3), (300, 301, 1),
    (300, 599, 1), (130, 130 * 5 + 3, 5)])
def test_a_mixed_leg_plays_exactly_its_travel_in_exactly_its_calls(
        calls, travel, lo):
    rows = P._mixed_rows(+1, calls, travel, lo)
    assert _speeds(rows) <= {lo, lo + 1}
    assert all(0 < t <= 127 for t, _ in rows)
    assert sum(t for t, _ in rows) == calls
    assert sum(t * s for t, s in rows) == travel
    down = P._mixed_rows(-1, calls, travel, lo)
    assert sum(t * (s - 256 if s >= 128 else s) for t, s in down) == -travel


def test_a_mixed_leg_stays_near_the_straight_line():
    rows = P._mixed_rows(+1, 1056, 1536, 1)
    w = _widths([P._setrow(0)] + rows, 1, 1056)
    for k, x in enumerate(w, start=1):
        assert abs(x - 1536 * k / 1056) < 64, k


def test_a_run_never_exceeds_one_table_row_and_rows_are_few():
    rows = P._mixed_rows(+1, 1056, 1536, 1)
    assert len(rows) <= 2 * (1056 // 100 + 1), rows


def test_legs_land_on_the_lattice_turns_and_the_loop_closes():
    turns = P._tri_turns(0x300, 16, 8, 14)
    entries, loop = P._mixed_legs(0x300, RATE, *turns)
    first_top, bottom, top = turns
    assert first_top == top
    signed = lambda rows: sum(t * (s - 256 if s >= 128 else s)
                              for t, s in rows if t < 0x80)
    assert 0x300 + signed(entries[1:loop]) == top, "the first ascent"
    assert signed(entries[loop:]) == 0, "one lap returns where it started"
    w = _widths(entries, loop, 6000)
    assert w[0] == 0x300 and max(w) == top and min(w[2500:]) == bottom


def test_a_leg_too_short_for_two_integer_speeds_declines():
    # 300 units cannot be walked at 126 or 127 a call in a whole number of calls
    assert P._mixed_leg(+1, 300, Fraction(1263, 10)) is None


# --- the engine --------------------------------------------------------------

@needs_corpus
def test_kentillas_rate_10_records_sweep_at_16_elevenths_a_call():
    sid = load_sid(str(CORPUS / KENTILLA))
    det = detect(sid, _quiet)
    plain, ploop = P._pulse_program(sid, det, 12, True, 10)
    mixed, mloop = P._pulse_program(sid, det, 12, True, 10, frac=True)
    assert _speeds(plain) == {1, -1}
    assert _speeds(mixed) == {1, 2, -1, -2}
    top = P._tri_turns(0x300, 16, 8, 14)[0]
    w = _widths(mixed, mloop, 6000)
    reached = w.index(top) + 1
    assert abs((top - 0x300) / reached - float(RATE)) < 0.01, reached


@needs_corpus
def test_kentillas_table_takes_the_mixed_records_and_is_smaller():
    sid = load_sid(str(CORPUS / KENTILLA))
    det = detect(sid, _quiet)
    nrec = 27
    usage = [1] * nrec
    kw = dict(lead=1, usage=usage)
    mixed, _ = P._pulse_layout(sid, det, nrec + 1, True, 10, **kw)
    with P.stair_enabled(False):
        plain, _ = P._pulse_layout(sid, det, nrec + 1, True, 10, **kw)
    assert len(mixed) <= 255
    assert len(mixed) < len(plain)
    assert _speeds(mixed) & {2, -2}
    assert not _speeds(plain) & {2, -2}


@needs_corpus
def test_a_record_that_would_overflow_the_table_keeps_its_integer_slew(
        monkeypatch):
    sid = load_sid(str(CORPUS / KENTILLA))
    det = detect(sid, _quiet)
    real = P._lay_out_pulse

    def full(programs, statics, lead, share, order=None, reserve_for=None):
        out = real(programs, statics, lead, share, order, reserve_for)
        mixed = any(2 in _speeds(p[0]) for p in programs)
        return out[:2] + ((1 if mixed else out[2]),) + out[3:]
    monkeypatch.setattr(P, "_lay_out_pulse", full)
    entries, _ = P._pulse_layout(sid, det, 28, True, 10, lead=1,
                                 usage=[1] * 27)
    assert not _speeds(entries) & {2, -2}


@needs_corpus
def test_a_record_the_song_never_sounds_keeps_its_integer_slew():
    """Its rows are table room a played record could use."""
    sid = load_sid(str(CORPUS / KENTILLA))
    det = detect(sid, _quiet)
    nrec = 27
    programs = [P._pulse_program(sid, det, i, True, 10) for i in range(nrec)]
    statics = [P._pulse_program(sid, det, i, False, 10)[0]
               for i in range(nrec)]
    entries, starts, dropped, _, _ = P._lay_out_pulse(programs, statics, 1,
                                                      share=True)
    assert not dropped
    usage = [1] * nrec
    usage[25] = 0
    out, _, _ = P._mixed_trials(sid, det, True, 10, None, programs, statics,
                                1, True, entries, starts, usage)
    assert out[25] == programs[25], "record 25 sounds nothing"
    assert out[12] != programs[12], "record 12 is played"


@needs_corpus
def test_the_stair_keeps_a_record_it_took():
    """Last_V8's record 1 (rate $79: step 96 every 26 ticks) is a held stair:
    set rows and speed-0 holds. The mix is asked about it too (1.846 a call
    at -S2, 8% off its integer) and must leave it, or the stair's holds
    would turn back into a slew."""
    sid = load_sid(str(CORPUS / "Last_V8.sid"))
    det = detect(sid, _quiet)
    nrec = 33
    # notes sounded per record, as `pulse_usage` reads them off the song
    usage = [324, 540, 480, 160, 118, 112, 128, 32, 69, 29, 11, 4, 0, 1, 1, 4,
             64, 48, 34]
    entries, starts = P._pulse_layout(sid, det, nrec + 1, True, 2, lead=1,
                                      usage=usage)
    assert P._tri_mixed_rate(*P._tri_step_delay(det, sid.data[
        det.instr_start + 1 * det.instr_stride + 6]), 2, None) is not None
    # starts[0] is the lead instrument's; record 1 is starts[2]
    block = entries[starts[2] - 1:starts[3] - 1]
    assert any(t < 0x80 and s == 0 for t, s in block), block
    assert not _speeds(block) - {0}, "no mixed speeds in a stair"
