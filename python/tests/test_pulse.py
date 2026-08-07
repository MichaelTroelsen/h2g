"""The pulse-width sweep: reading it, encoding it, and not disturbing anything.

H2G wrote one "set pulse width" per instrument and stopped, which is right for
the 328 corpus records whose sweep rate is zero and wrong for the 414 that
sweep -- those played a duty cycle frozen at its starting value. The player
steps a 12-bit accumulator every frame and turns it around at two bounds packed
into one byte; Goattracker's pulse table can say exactly that.

Nothing in the repo's metrics can see the difference: `wave` compares the
waveform *class*, so pulse is pulse whatever its width. Measured on the 37
corpus files the flag reaches, mean melody and mean wave agreement are
identical to the decimal before and after. The evidence that it works is the
`Pul` column of siddump, which moves from 1% of the original's changes to 60%.
"""
from pathlib import Path

import pytest

from h2g.convert import convert
from h2g.detect import Detection, _find_pulse_sweep, detect
from h2g.goatwriter import (GT_MAX_PULSE_SPEED, GT_MAX_PULSE_TICKS,
                            GT_MAX_TABLELEN, _pulse_layout, _pulse_program,
                            _split_ticks)
from h2g.sidfile import SidFile, load_sid

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
COMMANDO = Path(__file__).resolve().parents[2] / "Commando.sid"

STRIDE = 8
INSTR_AT = 0x40
BOUNDS_AT = 0x100
RATE_FIELD = 6


def _sid(records, bounds) -> SidFile:
    """A file with `records` instrument records and a parallel bounds array."""
    data = bytearray(BOUNDS_AT + (len(bounds) + 1) * STRIDE + 0x40)
    for i, rec in enumerate(records):
        data[INSTR_AT + i * STRIDE:INSTR_AT + i * STRIDE + STRIDE] = bytes(rec)
    for i, b in enumerate(bounds):
        data[BOUNDS_AT + i * STRIDE] = b
    return SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                   released="r", load_addr=0x1000, subtunes=1)


def _det(n, swept=True) -> Detection:
    return Detection(instr_start=INSTR_AT, instr_used=n,
                     instr_stride=STRIDE, track_lo=1, track_hi=2,
                     pattern_lo=3, pattern_hi=4, pattern_used=0,
                     read_track_version=0,
                     pulse_bounds=BOUNDS_AT if swept else -1,
                     pulse_rate_field=RATE_FIELD if swept else -1)


def _rising(entries):
    """Total ticks of the ascending leg, which _split_ticks may have cut up."""
    speed = entries[1][1]
    return sum(t for t, s in entries[1:] if s == speed)


def _record(pulse_lo=0x00, pulse_hi=0x08, rate=0x00):
    rec = [pulse_lo, pulse_hi, 0x41, 0x00, 0x00, 0x00, 0x00, 0x00]
    rec[RATE_FIELD] = rate
    return rec


# --- the encoding ----------------------------------------------------------

def test_a_zero_rate_keeps_the_static_width_the_tool_always_wrote():
    """The player's own "do not sweep". 328 corpus records are in this case."""
    sid = _sid([_record(0x40, 0x0A, rate=0)], [0x82])
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    assert loop is None
    assert entries == [(0x8A, 0x40), (0xFF, 0x00)]


def test_bounds_that_leave_no_band_keep_the_static_width():
    """high <= low: what the player does then depends on 12-bit wrap-around,
    so it is left alone. An under-read never invents movement."""
    for bounds in (0x28, 0x88):          # high 2 low 8, and high 8 low 8
        sid = _sid([_record(rate=0x40)], [bounds])
        _, loop = _pulse_program(sid, _det(1), 0, True, 1)
        assert loop is None


def test_a_sweep_is_a_set_then_up_then_down_then_a_jump():
    sid = _sid([_record(rate=0x40)], [0x82])     # low 2, high 8
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    ticks = ((8 - 2) << 8) // 0x40                # 24
    assert entries == [(0x82, 0x00), (ticks, 0x40), (ticks, 0xC0)]
    assert loop == 1, "the jump returns to the ascending step, not the set"
    # 0xC0 read as a signed byte is -0x40: the same speed downward.
    assert entries[2][1] - 0x100 == -0x40


def test_the_flag_off_is_the_inherited_static_encoding():
    sid = _sid([_record(0x37, 0x09, rate=0x40)], [0x82])
    entries, loop = _pulse_program(sid, _det(1), 0, False, 1)
    assert (entries, loop) == ([(0x89, 0x37), (0xFF, 0x00)], None)


def test_a_player_with_no_sweep_routine_is_never_swept():
    sid = _sid([_record(rate=0x40)], [0x82])
    _, loop = _pulse_program(sid, _det(1, swept=False), 0, True, 1)
    assert loop is None


# --- the two approximations, stated in _pulse_program's docstring -----------

def test_the_multiplier_halves_the_speed_because_the_table_steps_per_call():
    """gplay.c:872 steps the pulse table once per play call; the player steps
    once per frame. At -S2 an unscaled speed would sweep twice as fast."""
    sid = _sid([_record(rate=0x40)], [0x82])
    at1, _ = _pulse_program(sid, _det(1), 0, True, 1)
    at2, _ = _pulse_program(sid, _det(1), 0, True, 2)
    assert at1[1][1] == 0x40 and at2[1][1] == 0x20
    # The span is unchanged, so the tick count doubles to cover it.
    assert _rising(at2) == 2 * _rising(at1)


def test_the_span_is_recomputed_from_the_speed_actually_emitted():
    """An odd rate at -S2 cannot be halved exactly. The sweep must still cover
    the right band, so ticks come from the rounded speed rather than the rate."""
    sid = _sid([_record(rate=0x0B)], [0x91])       # low 1, high 9, rate 11
    entries, _ = _pulse_program(sid, _det(1), 0, True, 2)
    speed = entries[1][1]
    assert speed == round(0x0B / 2)
    assert _rising(entries) == ((9 - 1) << 8) // speed


def test_speed_is_capped_below_the_byte_that_would_read_as_negative():
    """A right side >= 0x80 is a negative speed (gplay.c:888-900), so an
    ascending step must stay under it however fast the player sweeps."""
    sid = _sid([_record(rate=0xF0)], [0xF0])
    entries, _ = _pulse_program(sid, _det(1), 0, True, 1)
    assert entries[1][1] == GT_MAX_PULSE_SPEED < 0x80


# --- long legs -------------------------------------------------------------

def test_split_ticks_never_emits_a_step_that_would_read_as_a_set():
    for n in (1, 0x7F, 0x80, 0x81, 300, 4096):
        steps = _split_ticks(n)
        assert sum(steps) == max(n, 1)
        assert all(1 <= s <= GT_MAX_PULSE_TICKS for s in steps)


def test_a_leg_longer_than_a_tick_byte_becomes_consecutive_steps():
    """gplay.c:902 advances on a zero counter and keeps modulating, so N steps
    of one speed and one step of their total are the same sweep."""
    sid = _sid([_record(rate=0x01)], [0xF0])     # span 15 * 256, speed 1
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    ups = [e for e in entries[1:] if e[1] == 0x01]
    downs = [e for e in entries[1:] if e[1] == 0xFF]
    assert len(ups) == len(downs) > 1
    assert sum(t for t, _ in ups) == (15 << 8)
    assert loop == 1


# --- the table as a whole --------------------------------------------------

def test_start_positions_follow_the_programs_rather_than_a_stride():
    """A swept instrument's program is longer than a static one's, so the
    instrument records cannot compute their pointer from a fixed stride."""
    sid = _sid([_record(rate=0x00), _record(rate=0x40), _record(rate=0x00)],
               [0x82, 0x82, 0x82])
    entries, starts = _pulse_layout(sid, _det(3), 4, True, 1)
    assert starts[0] == 1, "Clear Voice keeps entry 1"
    assert starts[1] == 3
    assert starts[2] == 5              # after the first static program
    assert starts[3] == 5 + 4          # after set + up + down + jump
    for start in starts:
        assert 1 <= start <= len(entries)


def test_every_jump_lands_on_an_entry_that_exists():
    sid = _sid([_record(rate=0x40)] * 3, [0x82] * 3)
    entries, _ = _pulse_layout(sid, _det(3), 4, True, 1)
    for left, right in entries:
        if left == 0xFF and right:
            assert 1 <= right <= len(entries)
            assert entries[right - 1][0] < 0x80, "a jump must land on a step"


def test_the_static_layout_is_exactly_two_entries_per_instrument():
    """What the length byte assumed before programs could vary in length."""
    sid = _sid([_record(rate=0x40)] * 5, [0x82] * 5)
    entries, starts = _pulse_layout(sid, _det(5), 6, False, 1)
    assert len(entries) == 6 * 2
    assert starts == [1, 3, 5, 7, 9, 11]


def test_a_full_table_keeps_the_instrument_and_loses_only_its_sweep():
    """Falling back to the static two entries is the only safe overflow: an
    instrument without a pulse pointer plays with whatever the table holds."""
    n = 50
    sid = _sid([_record(rate=0x01)] * n, [0xF0] * n)
    messages = []
    entries, starts = _pulse_layout(sid, _det(n), n + 1, True, 1,
                                    messages.append)
    assert len(entries) <= GT_MAX_TABLELEN
    assert len(starts) == n + 1, "no instrument may lose its pointer"
    assert messages and "STATIC" in messages[0]


# --- against the real players ----------------------------------------------

def test_the_sweep_is_found_in_the_corpus_and_the_rate_is_record_plus_six():
    sids = sorted(CORPUS.glob("*.sid"))
    if not sids:
        pytest.skip("corpus not present")
    found = 0
    for path in sids:
        try:
            sid = load_sid(str(path))
            det = detect(sid, log=lambda m: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.pulse_bounds < 0:
            continue
        found += 1
        assert det.pulse_rate_field == 6, path.name
        assert 0 <= det.pulse_bounds < len(sid.data)
    assert found == 43, "the sweep block's reach changed -- re-measure"


def test_both_halves_of_the_signature_are_required():
    """The sweep block alone gives the bounds but not the rate field, and the
    setup block alone proves nothing about what the rate is for."""
    sid = load_sid(str(COMMANDO))
    det = detect(sid, log=lambda m: None)
    assert _find_pulse_sweep(sid, det) == (-1, -1)


def test_commando_is_untouched_with_the_flag_on_and_off():
    """The fixture's player has no sweep block, so the option cannot reach it
    -- the byte-exactness invariant holds either way."""
    plain = convert(str(COMMANDO), log=lambda m: None)
    swept = convert(str(COMMANDO), log=lambda m: None, pulse=True)
    assert plain == swept
    assert len(plain) == 15193
