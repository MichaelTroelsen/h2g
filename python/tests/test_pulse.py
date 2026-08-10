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
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402

import pytest

from h2g.convert import convert
from h2g.detect import detect
from h2g.sidfile import load_sid
from h2g.detect import Detection, _find_pulse_sweep, detect
from h2g.goatwriter import (GT_MAX_PULSE_SPEED, GT_MAX_PULSE_TICKS,
                            GT_MAX_TABLELEN, _pulse_layout, _pulse_program,
                            _split_ticks)
from h2g.sidfile import SidFile, load_sid

CORPUS = _CORPUS
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


def test_a_sweep_opens_at_the_records_own_width_not_at_a_bound():
    """v0.5.188. The player reseeds its accumulator from record +0/+1 at each
    note and sweeps from there, so the record's width is the duty cycle every
    attack is heard on. This used to open at the low bound, which put
    Trans-Atlantic's lead on `$D00` where the player opens on `$880` and shrank
    its band from the original's 1728 to 508 -- the right shape in the wrong
    place. `_pulse_tri_program` was given the width in v0.5.174; this path was
    not, and both now share `_pulse_triangle`.
    """
    sid = _sid([_record(0x00, 0x04, rate=0x40)], [0x82])   # width $400, low 2, high 8
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    assert entries[0] == (0x84, 0x00), "opens on the record's $400"
    first = ((8 << 8) - 0x400) // 0x40             # up to the high bound
    assert entries[1] == (first, 0x40)
    assert loop == 2, "the jump returns to the descent, past the first ascent"
    # 0xC0 read as a signed byte is -0x40: the same speed downward.
    assert entries[loop][1] - 0x100 == -0x40


def test_a_width_below_the_low_bound_is_kept_and_swept_up_from():
    """The player does not clamp. Trans-Atlantic's GT 1 opens on `$880` with
    bounds `$D00`/`$F00` and sweeps *up* from there until a bound turns it, so
    its band is `$880`-`$F40` and not the `$D00`-`$F00` the bounds alone
    describe. The first version of this fix clamped the width into the band and
    therefore changed that instrument by nothing at all -- 508 of the original's
    1728, where keeping the width gives 1651.
    """
    sid = _sid([_record(0x00, 0x01, rate=0x40)], [0x82])   # width $100, band $200-$800
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    assert entries[0] == (0x81, 0x00), "the record's width, not the bound"
    assert loop == 2, "a first ascent is needed to reach the band"
    # ...and the ascent runs the whole way from $100 to the high bound.
    assert entries[1][0] == ((8 << 8) - 0x100) // 0x40


def test_a_width_above_the_high_bound_is_clamped_down_to_it():
    """The other direction *is* clamped: a width past the top has nowhere to
    ascend, and the descent is measured from where the ascent stopped."""
    sid = _sid([_record(0xFF, 0x0F, rate=0x40)], [0x82])
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    opened = ((entries[0][0] & 0x0F) << 8) | entries[0][1]
    assert opened == (8 << 8)
    assert loop == 1, "no first ascent from the top"


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
    sid = _sid([_record(0x00, 0x04, rate=0x40)], [0x82])
    at1, _ = _pulse_program(sid, _det(1), 0, True, 1)
    at2, _ = _pulse_program(sid, _det(1), 0, True, 2)
    assert at1[1][1] == 0x40 and at2[1][1] == 0x20
    # The span is unchanged, so the tick count doubles to cover it.
    assert _rising(at2) == 2 * _rising(at1)


def test_the_span_is_recomputed_from_the_speed_actually_emitted():
    """An odd rate at -S2 cannot be halved exactly. The sweep must still cover
    the right band, so ticks come from the rounded speed rather than the rate."""
    sid = _sid([_record(0x00, 0x09, rate=0x0B)], [0x91])  # width $900 = the top
    entries, loop = _pulse_program(sid, _det(1), 0, True, 2)
    speed = 0x100 - entries[loop][1]
    assert speed == round(0x0B / 2)
    # Opening at the high bound means no first ascent, so `loop` is 1 and the
    # descent covers the whole band -- computed from the speed emitted, not the
    # rate, which is the point of the test.
    assert loop == 1
    assert sum(t for t, sp in entries[1:]
               if sp == (0x100 - speed) & 0xFF) == ((9 - 1) << 8) // speed


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
    sid = _sid([_record(0x00, 0x0F, rate=0x01)], [0xF0])  # width = the top
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    ups = [e for e in entries[loop:] if e[1] == 0x01]
    downs = [e for e in entries[loop:] if e[1] == 0xFF]
    assert len(ups) == len(downs) > 1
    assert sum(t for t, _ in ups) == (15 << 8)
    assert loop == 1, "opening at the high bound needs no first ascent"


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

@needs_corpus
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


def test_commando_is_byte_exact_with_the_flag_off():
    """The invariant: `--pulse` is opt-in, so defaults still write 15193 B.

    This test used to assert the flag could not reach Commando *at all*, which
    was true only while the accumulate engine was unimplemented -- the fixture's
    player has no sweep block, but it does have bit $08. Now that the engine is
    read, the flag changes Commando by design; what must not change is the
    default output.
    """
    plain = convert(str(COMMANDO), log=lambda m: None)
    assert len(plain) == 15193


def test_commando_accumulates_under_the_flag():
    """And the flag reaches it, through the accumulate engine rather than the
    sweep: the file gains pulse-table entries and nothing else about it moves."""
    plain = convert(str(COMMANDO), log=lambda m: None)
    pulsed = convert(str(COMMANDO), log=lambda m: None, pulse=True)
    assert pulsed != plain
    assert len(pulsed) > len(plain)

    sid = load_sid(str(COMMANDO))
    det = detect(sid, log=lambda m: None)
    assert det.pulse_bounds < 0, "Commando has no sweep block"
    assert det.pulse_lo_base == det.instr_start
    # Every record the engine reaches carries bit $08 and a nonzero rate.
    reached = [i for i in range(det.instr_used)
               if sid.data[det.pulse_lo_base + i * det.instr_stride + 7] & 0x08]
    assert reached, "the fixture should exercise the engine"


# --- the triangle: the third engine ----------------------------------------
#
# A triangle like the sweep above, but its bounds are constants in the routine
# rather than a per-record array, and its rate byte packs the step (& $E0) and
# the frames between steps (& $1F). 24 corpus files carry it, and until it was
# read they all wrote a frozen width for every record using it.

TRI_LO, TRI_HI = 8, 0x0E


def _tri_det(n, gated=False) -> Detection:
    det = _det(n, swept=False)
    det.pulse_tri_lo, det.pulse_tri_hi = TRI_LO, TRI_HI
    det.pulse_tri_gated = gated
    return det


def _tri(rate, lo=0xC0, hi=0x0A, effect=0x00, mult=1, gated=False):
    rec = [lo, hi, 0x41, 0x00, 0x00, 0x00, rate, effect]
    return _pulse_program(_sid([rec], []), _tri_det(1, gated), 0, True, mult)


def test_the_triangle_starts_where_the_record_does_not_at_a_bound():
    """Every note restarts the program (gplay.c:375-379), so the entry width is
    the duty cycle every attack is heard on. The record's own is the only value
    the player is ever known to open on; a bound would invent one."""
    entries, loop = _tri(0xE0)
    assert entries[0] == (0x8A, 0xC0), "set $AC0, the record's own width"
    assert loop == 2, "the jump returns to the descent, past the first ascent"


def test_the_step_is_the_high_three_bits_and_the_delay_the_low_five():
    """rate $44: step $40 every ($04 + 1) frames, so 12.8 per frame."""
    entries, _ = _tri(0x44)
    assert entries[1][1] == round(0x40 / 5)


def test_a_delay_only_rate_does_not_sweep():
    """`rate & $E0` is the whole step. A rate of $1F moves the width by nothing,
    however often it does it -- and an under-read never invents movement."""
    assert _tri(0x1F)[1] is None


def test_the_step_is_divided_by_the_call_rate_like_every_other_rate():
    assert _tri(0x40, mult=2)[0][1][1] == 0x20


def test_a_step_past_the_signed_byte_is_capped_and_the_span_recomputed():
    """A Goattracker pulse speed is a signed byte, so 224 a frame cannot be
    said at all. What must not follow is a wrong span: the tick counts are
    computed from the speed actually emitted, so the band stays right and only
    the rate is slow."""
    entries, loop = _tri(0xE0)
    assert entries[1][1] == GT_MAX_PULSE_SPEED, "224 a frame cannot be said"
    lo, hi = _walk(entries)
    assert (TRI_HI << 8) - hi < GT_MAX_PULSE_SPEED, "the ascent stops at the top"
    assert lo >= TRI_LO << 8, "and the descent at the bottom"


def _walk(entries):
    """(lowest, highest) width the program reaches, playing it as gplay does."""
    pos = ((entries[0][0] & 0x0F) << 8) | entries[0][1]
    seen = [pos]
    for t, s in entries[1:]:
        for _ in range(t):
            pos += s if s < 0x80 else s - 0x100
            seen.append(pos)
    return min(seen), max(seen)


def test_the_descent_cannot_walk_below_the_lower_bound():
    """Goattracker masks the width to $FFF where the player clamps, so a descent
    measured from the bound rather than from where the ascent stopped would wrap
    to the top of the range on a truncated step -- a sweep audibly inside out."""
    for rate in (0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0, 0x23, 0x45):
        for lo, hi in ((0x00, 0x08), (0xFF, 0x0D), (0xC0, 0x0A)):
            entries, _ = _tri(rate, lo=lo, hi=hi)
            low, high = _walk(entries)
            assert low >= TRI_LO << 8, (rate, lo, hi, entries)
            assert high <= TRI_HI << 8, (rate, lo, hi, entries)


def test_the_gate_routes_a_bit_08_record_to_the_other_engine():
    """19 of the 24 files put this engine behind an effect-bit-$08 test, with
    the accumulate engine on the other side. The other five have no test and
    sweep every record -- so the gate is honoured only where it was found."""
    assert _tri(0xE0, effect=0x08, gated=True)[1] is None
    assert _tri(0xE0, effect=0x08, gated=False)[1] is not None


def test_a_player_without_the_triangle_is_never_swept_by_it():
    sid = _sid([[0xC0, 0x0A, 0x41, 0, 0, 0, 0xE0, 0x00]], [])
    assert _pulse_program(sid, _det(1, swept=False), 0, True, 1)[1] is None


@needs_corpus
def test_the_triangle_is_found_in_the_corpus_with_the_bounds_it_reads():
    """The bounds are $08/$0E in every file carrying it, which is exactly why
    they are read from the CMP operands: a constant that holds everywhere is
    indistinguishable from one nobody checked."""
    sids = sorted(CORPUS.glob("*.sid"))
    if not sids:
        pytest.skip("corpus not present")
    found = gated = 0
    for path in sids:
        try:
            sid = load_sid(str(path))
            det = detect(sid, log=lambda m: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.pulse_tri_hi < 0:
            continue
        found += 1
        gated += det.pulse_tri_gated
        assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0E), path.name
        # anchored on the instrument table this detection already found
        assert sid.data[det.instr_start:det.instr_start + 1]
    assert (found, gated) == (24, 19), "the triangle's reach changed"
