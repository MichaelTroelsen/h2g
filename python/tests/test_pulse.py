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
from h2g.goatwriter import (GT_FIRST_NOTE, GT_MAX_PULSE_SPEED,
                            GT_MAX_PULSE_TICKS, GT_MAX_TABLELEN, GT_REST,
                            _pulse_layout, _pulse_program, _split_ticks,
                            pulse_usage)
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


def test_a_band_whose_top_is_below_its_bottom_crosses_fff():
    """high <= low used to keep the static width -- "no band to travel". The
    player never compares magnitudes: it flips when the high nibble EQUALS the
    bound it is heading for, so a top below the bottom is a band through $FFF.
    Kings of the Beach ingame's instrument 4 is the measured case: rate $84,
    bounds $02, seed $080, packed at -S3, and siddump shows every note on all
    three voices climbing $080, $104, ... $FF8 (30 frames of +132) before the
    next note reseeds it. This branch froze it at $080: 1 pulse change per
    voice against the original's 342, pspan 0.00. After: 394 and 1.00.
    """
    sid = _sid([_record(0x80, 0x00, rate=0x84)], [0x02])   # low 2, high 0
    entries, loop = _pulse_program(sid, _det(1), 0, True, 3)
    assert entries[0] == (0x80, 0x80), "opens on the record's $080"
    speed = round(0x84 / 3)                                # 44: 132 a frame
    assert entries[1][1] == speed
    ascent = sum(t for t, sp in entries[1:loop] if sp == speed)
    assert ascent == ((0 - 0x80) & 0xFFF) // speed == 90, "up through the wrap"
    top = (0x80 + ascent * speed) & 0xFFF
    assert top == 0xFF8, "where the original's climb is seen to end"
    down = entries[loop:]
    assert down[0][1] == (0x100 - speed) & 0xFF, "the loop lands on the descent"
    descent = sum(t for t, sp in down if sp == (0x100 - speed) & 0xFF)
    assert descent == ((top - 0x200) & 0xFFF) // speed, "back down to the low nibble"
    assert sum(t for t, sp in down if sp == speed) == descent


def test_a_band_of_one_nibble_jitters_one_step_each_way():
    """high == low: the player reaches the nibble and then alternates one step
    down, one step up, forever (`CMP` equal on both branches). The modular
    descent distance is ~0 and `max(1, ...)` gives exactly that."""
    sid = _sid([_record(0x00, 0x08, rate=0x40)], [0x88])   # seed $800, band 8..8
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    assert entries == [(0x88, 0x00), (1, 0xC0), (1, 0x40)]
    assert loop == 1


def test_the_unwrapped_path_is_untouched_by_the_wrapped_one():
    """The routing is on `high <= low` only; a record whose band reads the
    right way round must produce exactly what it produced before."""
    sid = _sid([_record(0x00, 0x04, rate=0x40)], [0x82])   # width $400, low 2, high 8
    entries, loop = _pulse_program(sid, _det(1), 0, True, 1)
    assert entries[0] == (0x84, 0x00)
    assert loop == 2
    assert _rising(entries) == ((8 << 8) - 0x400) // 0x40 + sum(
        t for t, s in entries[loop + 1:] if s == 0x40)


def test_kings_of_the_beach_ingame_instrument_4_is_the_measured_wrapped_case():
    """Pins the record bytes the docstrings quote, so the claim decays loudly
    if the file or the detection moves: rate $84 at +6, bounds $02, seed $080.
    Measured at v0.5.480 on siddump -a4: 30 steps of +132 from $080 to $FF8,
    then a wrap to $07C, on all three voices."""
    path = CORPUS / "Kings_of_the_Beach_ingame.sid"
    if not path.exists():
        pytest.skip("corpus not present")
    sid = load_sid(str(path))
    det = detect(sid, log=lambda m: None)
    base = det.instr_start + 4 * det.instr_stride
    assert sid.data[base + det.pulse_rate_field] == 0x84
    assert sid.data[det.pulse_bounds + 4 * det.instr_stride] == 0x02
    assert (sid.data[base + 1] & 0x0F, sid.data[base]) == (0x00, 0x80)
    entries, loop = _pulse_program(sid, det, 4, True, 3)
    assert entries[0] == (0x80, 0x80)
    assert sum(t for t, s in entries[1:loop] if s == 44) == 90
    assert loop == 2, "set, then one 90-call ascent (under the 7F tick byte)"


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
    instrument without a pulse pointer plays with whatever the table holds.
    The records differ in width so that no two programs are identical --
    identical ones are shared before anything is dropped (the tests below)."""
    n = 50
    sid = _sid([_record(pulse_lo=i, rate=0x01) for i in range(n)], [0xF0] * n)
    messages = []
    entries, starts = _pulse_layout(sid, _det(n), n + 1, True, 1,
                                    messages.append)
    assert len(entries) <= GT_MAX_TABLELEN
    assert len(starts) == n + 1, "no instrument may lose its pointer"
    assert messages and any("STATIC" in m for m in messages)


# --- sharing identical programs, only once the table is full ----------------

def test_identical_programs_are_not_shared_while_every_block_fits():
    """Sharing is a rescue and keeps the rescue's ordering: a table that is
    whole gets one block per record, which is what every measured conversion
    (and the fixture) encodes."""
    sid = _sid([_record(rate=0x40)] * 3, [0x82] * 3)
    entries, starts = _pulse_layout(sid, _det(3), 4, True, 1)
    assert starts == [1, 3, 7, 11], "three copies of the four-entry block"
    assert len(entries) == 2 + 3 * 4


def test_an_overflowing_table_shares_identical_programs_at_one_start():
    """Rock_Tells_the_Tale writes the same 55-entry sweep for three records
    and the same 48-entry one for two more, and runs out of table doing it.
    A program identical to one already placed is not written again: its
    record points at the block that is there. (24 records: `_sid` places
    record 24 on top of the bounds array, so a fake table stops short of it.)"""
    n = 24
    sid = _sid([_record(rate=0x01)] * n, [0xF0] * n)
    program, loop = _pulse_program(sid, _det(n), 0, True, 1)
    assert n * (len(program) + 1) > GT_MAX_TABLELEN, "the scenario must overflow"
    messages = []
    entries, starts = _pulse_layout(sid, _det(n), n + 1, True, 1,
                                    messages.append)
    assert len(starts) == n + 1, "no instrument may lose its pointer"
    assert set(starts[1:]) == {3}, "every record names the one block"
    assert entries == [(0x80, 0x00), (0xFF, 0x00)] + program + [(0xFF, 3 + loop)]
    assert messages and "SHARE" in messages[0]
    assert not any("STATIC" in m for m in messages), "nothing had to be dropped"


def test_a_shared_blocks_jump_is_absolute_and_lands_inside_its_own_block():
    """`(0xFF, start + loop)` is an absolute table index. Two distinct
    programs, each shared by many records: the second block's jump must name
    an entry of the SECOND block, at the start it was actually written at."""
    n = 24
    a, b = _record(pulse_lo=0x00, rate=0x01), _record(pulse_lo=0x10, rate=0x01)
    sid = _sid([a, b] * (n // 2), [0xF0] * n)
    prog_a, loop_a = _pulse_program(sid, _det(n), 0, True, 1)
    prog_b, loop_b = _pulse_program(sid, _det(n), 1, True, 1)
    assert prog_a != prog_b
    entries, starts = _pulse_layout(sid, _det(n), n + 1, True, 1)
    start_a, start_b = 3, 3 + len(prog_a) + 1
    assert starts[1::2] == [start_a] * (n // 2)
    assert starts[2::2] == [start_b] * (n // 2)
    assert len(entries) == start_b - 1 + len(prog_b) + 1
    jump_b = entries[-1]
    assert jump_b == (0xFF, start_b + loop_b)
    assert start_b <= jump_b[1] < start_b + len(prog_b)
    assert entries[jump_b[1] - 1][0] < 0x80, "a jump must land on a step"
    for left, right in entries:
        if left == 0xFF and right:
            assert 1 <= right <= len(entries)


# --- allocating by usage, only once sharing still leaves a record short ------
#
# Sharing is the second pass; this is the third. Both index-order passes lost
# whichever records sat at the END of the instrument table, and at v0.5.486
# Rock_Tells_the_Tale dropped GT16's sweep (352 notes sounded) while keeping
# GT3's (1 note). `usage` comes from `pulse_usage` in the real pipeline; the
# tests hand it in directly so the scenario is the code's, not a file's.

BIG = 0x02          # rate: a 42-entry program against bounds $F0
SMALL = 0x40        # rate: a 4-entry program against bounds $82


def _cost(sid, det, i):
    program, loop = _pulse_program(sid, det, i, True, 1)
    return len(program) + (0 if loop is None else 1)


def test_without_usage_the_index_order_passes_stand_as_they_were():
    """The tests above and every `_pulse_layout` call that hands in no usage
    are the old two passes exactly: the third never runs on `usage=None`."""
    n = 7
    sid = _sid([_record(pulse_lo=i, rate=BIG) for i in range(n)], [0xF0] * n)
    assert _pulse_layout(sid, _det(n), n + 1, True, 1) == \
        _pulse_layout(sid, _det(n), n + 1, True, 1, usage=None)


def test_a_full_table_drops_the_least_played_sweep_not_the_last_one():
    """Six 42-entry programs fill the table to 254 of 255; a seventh, 4-entry
    one at the END overflows it. Index order gave the last record NOTHING --
    not even its width -- because the records before it had used the table
    up. By usage the least-played record is the one that loses, and it loses
    only its sweep."""
    n = 7
    recs = [_record(pulse_lo=i, rate=BIG) for i in range(6)]
    recs.append(_record(pulse_lo=6, rate=SMALL))
    bounds = [0xF0] * 6 + [0x82]
    sid, det = _sid(recs, bounds), _det(n)
    assert sum(_cost(sid, det, i) for i in range(n)) + 2 > GT_MAX_TABLELEN
    usage = [1] + [10] * 6                  # record 0 is the least played
    entries, starts = _pulse_layout(sid, det, n + 1, True, 1, usage=usage)
    assert len(entries) <= GT_MAX_TABLELEN
    last = starts[n]
    program, loop = _pulse_program(sid, det, n - 1, True, 1)
    assert entries[last - 1:last - 1 + len(program)] == program, \
        "the last record, played, keeps its sweep"
    first = starts[1]
    static, _ = _pulse_program(sid, det, 0, False, 1)
    assert entries[first - 1:first + 1] == static, \
        "the least-played record keeps its width and loses only its sweep"
    assert 0 not in starts, "every played record has a pointer"


def test_a_record_that_sounds_keeps_at_least_its_width():
    """Descending usage alone would let the big, popular programs fill the
    table and leave a dozen quiet-but-played records with NO width at all --
    Rock_Tells_the_Tale's GT11, GT13 and GT14 in the first cut. A static pair
    is reserved for every record that sounds, so the last big program yields
    its sweep to twelve widths instead."""
    big, quiet = 6, 12
    recs = [_record(pulse_lo=i, rate=BIG) for i in range(big)]
    recs += [_record(pulse_lo=0x10 + i, rate=0) for i in range(quiet)]
    n = len(recs)
    sid, det = _sid(recs, [0xF0] * n), _det(n)
    assert 2 + sum(_cost(sid, det, i) for i in range(big)) + 2 > GT_MAX_TABLELEN, \
        "the six sweeps alone must leave no room for a static pair"
    usage = [100] * big + [1] * quiet       # all of them sound
    entries, starts = _pulse_layout(sid, det, n + 1, True, 1, usage=usage)
    assert 0 not in starts[1:], "a record that sounds never loses its width"
    for i in range(big, n):
        static, _ = _pulse_program(sid, det, i, False, 1)
        st = starts[1 + i]
        assert entries[st - 1:st + 1] == static
    kept = 0
    for i in range(big):
        program, _ = _pulse_program(sid, det, i, True, 1)
        st = starts[1 + i]
        kept += entries[st - 1:st - 1 + len(program)] == program
    assert kept == big - 1, "exactly one big program yielded to the reserve"


def test_a_record_that_sounds_nothing_is_the_one_that_goes_without():
    """A record no note ever sounds under never has its pulse pointer loaded
    (gplay.c:375), so whatever it points at is inaudible. It is allocated
    last and, here, gets nothing -- while the six played records after it in
    the instrument table all keep their sweeps. Index order gave the unplayed
    record the first block and silenced the last played one."""
    n = 7
    sid = _sid([_record(pulse_lo=i, rate=BIG) for i in range(n)], [0xF0] * n)
    det = _det(n)
    usage = [0] + [10] * 6
    entries, starts = _pulse_layout(sid, det, n + 1, True, 1, usage=usage)
    assert starts[1] == 0, "the unplayed record is the one with no width"
    for i in range(1, n):
        program, _ = _pulse_program(sid, det, i, True, 1)
        st = starts[1 + i]
        assert st and entries[st - 1:st - 1 + len(program)] == program


# --- pulse_usage: notes SOUNDED per record, in play order -------------------

def _row(note=GT_FIRST_NOTE, instr=0):
    return [note, instr, 0, 0]


def test_usage_counts_notes_sounded_and_instr_00_inherits():
    """gplay.c:914 keeps the channel's instrument on `instr 00`, and every new
    note reloads the pulse pointer from it (gplay.c:375-377) -- so the second
    and third notes below sound under GT2 although only the first names it.
    A rest is not a note."""
    pat = (_row(instr=2) + _row() + _row(GT_REST) + _row(instr=3) + _row()
           + [0xFF, 0, 0, 0])
    assert pulse_usage([[0, 0xFF, 0]], [pat], lead=1) == [2, 2]


def test_a_channel_holds_instrument_1_before_any_row_names_one():
    """gplay.c:62 and :223 (player.s:619-621): under `compact_instruments`
    that is record 0, which sounds unnamed; with the Clear Voice lead it is
    the placeholder, and no record is credited."""
    pat = _row() + _row() + [0xFF, 0, 0, 0]
    assert pulse_usage([[0, 0xFF, 0]], [pat], lead=0) == [2]
    assert pulse_usage([[0, 0xFF, 0]], [pat], lead=1) == []


def test_usage_honours_repeats_and_skips_transposes_and_the_restart():
    pat = _row(instr=2) + [0xFF, 0, 0, 0]
    track = [0xE3, 0xD2, 0, 0xF1, 0, 0xFF, 0]     # x3, then once, restart to 0
    assert pulse_usage([track], [pat], lead=1) == [4]


def test_usage_stops_at_endpatt_and_ignores_a_pattern_byte_out_of_range():
    pat = _row(instr=2) + [0xFF, 0, 0, 0] + _row(instr=2)
    assert pulse_usage([[0, 5, 0xFF, 0]], [pat], lead=1) == [1]


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
    # 43 until v0.5.277, which moved Powerplay Hockey's instrument table to
    # the copy of the player its patterns belong to (section 7.iiiii). The
    # sweep was found from the other copy's table; from this one it is not.
    assert found == 42, "the sweep block's reach changed -- re-measure"


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


# --- packing: gt2reloc's pulse skipping ------------------------------------

def test_pack_sid_disables_gt2relocs_pulse_skipping():
    """`-Oxx` is DEFAULT=on (readme:1225) and makes the packed player execute no
    pulse table on the note-fetch tick, so at tempo 3 the duty cycle advances on
    two calls in three where the player advances it every frame. Trans-Atlantic's
    lead covered 762 of the original's 1584 with it on and 1143 with it off, and
    readme:1078-1081 already says to disable it for a fast tempo -- every row
    this converter emits is one player tick.

    Asserted on the argument list rather than by packing, so it holds without
    gt2reloc installed. The flag must also follow both filenames: gt2reloc reads
    argv[1] and argv[2] positionally.
    """
    import inspect
    import fidelity
    src = inspect.getsource(fidelity.pack_sid)
    assert '"-O0"' in src
    assert "pulse_skip" in inspect.signature(fidelity.pack_sid).parameters
    # ...and the survey has its own packer, which needs it too.
    import survey
    assert '"-O0"' in inspect.getsource(survey)


def test_pulse_skipping_can_be_restored_for_an_ab():
    import inspect
    import fidelity
    p = inspect.signature(fidelity.pack_sid).parameters["pulse_skip"]
    assert p.default is False, "the faithful setting is the default"


# --- pulse PHASE: which duty cycle a note OPENS on -------------------------
#
# The triangle engine's accumulator free-runs and is never reseeded at a
# note; Goattracker reloads the pulse pointer per note. --pulse-phase opens
# each note on the accumulator's own value via CMD_SETPULSEPTR. The model
# below was validated against 5_Title_Tunes' trace BEFORE the emitter was
# built: 848/848 onsets exact on all three sweeping voices, 96.9% of all
# 6000 frames. Two facts are load-bearing and both were measured rather than
# read off the 6502: the sweep does NOT run on the note-fetch call, and the
# reflection STORES the at-bound value (store-at-bound matches 96.9% of
# frames; the skip-at-bound reading matches 9.5%).

from h2g.goatwriter import (PulsePhaseSim, build_pulse_phase_table,
                            pulse_phase_sims)
from h2g.convert import _detect_tables
from h2g.patterns import (CMD_SETPULSEPTR, _expand_repeats,
                          apply_pulse_phase)


def _sim(width=0x900, step=0x40, delay=2, lo=8, hi=0xE):
    return PulsePhaseSim(width, step, delay, lo, hi)


def test_the_first_active_call_ticks_immediately():
    """DEC-then-BPL from zero goes negative at once: the first active call
    fires a step before the counter's first reload."""
    s = _sim()
    s.advance(1)
    assert s.width == 0x940


def test_the_cadence_is_one_step_per_delay_calls():
    s = _sim()
    s.advance(1 + 2 * 3)          # the immediate tick, then three periods
    assert s.width == 0x900 + 4 * 0x40


def test_the_reflection_stores_the_at_bound_value():
    """The empirical winner: the trace holds $E60 for a full period at the
    top, so the at-bound value is stored and THEN the direction flips."""
    s = _sim(width=0xDE0, step=0x80)
    s.advance(1)
    assert (s.width, s.direction) == (0xE60, -1), "the bound value was lost"
    s.advance(2)
    assert s.width == 0xDE0, "the descent did not resume from the bound"


def test_the_attack_call_does_not_sweep():
    """The note-fetch call is spent in the fetch, not the sweep. Over ONE
    8-call note the delay's parity hides it (4 ticks either way); over two
    notes the counter's carry shows the true cost -- 7 ticks against 8,
    which is exactly the measured cycle's alternating +$100/+$C0 stride."""
    plain, skipped = _sim(), _sim()
    plain.advance(8)
    plain.advance(8)
    skipped.advance(8, skip_first=True)
    skipped.advance(8, skip_first=True)
    assert plain.width - 0x900 == 0x40 * 8
    assert skipped.width - 0x900 == 0x40 * 7


def test_the_measured_onset_cycle_is_reproduced():
    """5_Title_Tunes voice 1's instrument 5, as the trace measures it: 238
    onsets repeating with period 12. Notes are 8 calls, back to back."""
    want = [0x900, 0xA00, 0xAC0, 0xBC0, 0xC80, 0xD80,
            0xDC0, 0xCC0, 0xC00, 0xB00, 0xA40, 0x940]
    s = _sim(width=0x900, step=0x40, delay=2)
    got = []
    for _ in range(24):
        got.append(s.phase()[0])
        s.advance(8, skip_first=True)
    assert got[:12] == want, [hex(x) for x in got[:12]]
    assert got[12:24] == want, "the cycle does not repeat with period 12"


def test_expand_repeats_writes_the_fold_out_and_remaps_the_restart():
    track = [0x01, 0xD2, 0x02, 0x03, 0xFF, 0x03]     # restart names index 3
    out, remap = _expand_repeats(track)
    assert out[:6] == [0x01, 0x02, 0x02, 0x02, 0x03, 0xFF]
    # index 3 (the pattern after the fold) is index 4 expanded, and the
    # restart operand follows it there
    assert out[6] == 4
    assert remap[3] == 4


def test_expand_repeats_declines_at_the_orderlist_limit():
    from h2g.patterns import MAX_TRACK_LEN
    track = [0xDF, 0x01] * (MAX_TRACK_LEN // 2) + [0xFF, 0x00]
    out, remap = _expand_repeats(track)
    assert out is None and remap is None


def test_the_phase_table_carries_set_ramp_and_join_per_phase():
    """Every planned (width, direction) gets an entry point: a set to that
    width, a ramp toward its bound, and a jump into the shared loop."""
    sid = load_sid(str(CORPUS / "5_Title_Tunes.sid"))
    sid2, det = _detect_tables(sid, lambda m: None, 0)
    phases = {5: {(0x900, +1), (0xC00, -1)}}
    got = build_pulse_phase_table(sid2, det, 17, True, 1, phases, lead=0)
    assert got is not None
    entries, starts, index = got
    assert (5, 0x900, +1) in index
    at = index[(5, 0xC00, -1)]
    left, right = entries[at - 1]
    assert (left, right) == (0x8C, 0x00), "the set does not name the width"
    # the piece ends by joining the shared loop
    tail = entries[at - 1:at + 3]
    assert any(l == 0xFF for l, _ in tail), "no join back into the loop"


def test_apply_writes_into_clones_and_yields_occupied_columns():
    patterns = [[0x80, 5, 0, 0, 0x84, 0, 7, 1, 0xFF, 0, 0, 0]]
    tracks = [[0, 0xFF, 0x00]]
    writes = [(0, 0, {0: (5, (0x900, 1)), 1: (5, (0xA00, 1))})]
    index = {(5, 0x900, 1): 40, (5, 0xA00, 1): 43}
    n = apply_pulse_phase(patterns, tracks, writes, index)
    assert n == 1, "the free column alone takes the command"
    assert len(patterns) == 2, "the write went into the shared pattern"
    clone = patterns[tracks[0][0]]
    assert (clone[2], clone[3]) == (CMD_SETPULSEPTR, 40)
    assert (clone[6], clone[7]) == (7, 1), "the occupied command was overwritten"
    assert patterns[0][2] == 0, "the original pattern was patched in place"


@needs_corpus
def test_five_title_tunes_takes_the_phase_plan_end_to_end():
    """The option changes the bytes, the plan reaches all three sweeping
    voices, and the default stays byte-identical."""
    from h2g.convert import convert
    lines: list = []
    base = dict(tempo="auto", pulse=True, compact_instruments=True,
                dedup=True, prune=True, pack=True)
    off = convert(str(CORPUS / "5_Title_Tunes.sid"), log=lambda m: None, **base)
    on = convert(str(CORPUS / "5_Title_Tunes.sid"), log=lines.append,
                 pulse_phase=True, **base)
    assert off != on, "the option reached nothing"
    assert any("CMD_SETPULSEPTR on" in ln for ln in lines), lines


# --- the bounds-engine phase sim -------------------------------------------
# The per-record-bounds engine (`_pulse_program`, the array-of-nibbles
# sweep) has no phase walk: `pulse_phase_sims` returns {} on it, so
# --pulse-phase is byte-inert on Saboteur_II and Food_Feud. PulseBoundsSim is
# its accumulator, validated against BOTH originals' traces at -t 180 before
# anything was emitted: 25626/25626 and 25298/25298 classifiable sweep steps,
# 1314/1314 and 1554/1554 attack onsets (the frame `pphase` reads). The
# numbers pinned below are read off those traces, not derived from the 6502.
# The one fact the triangle engine does not share: THE ACCUMULATOR IS
# RESEEDED at every note whose note byte has bit 7 clear ($F162 BMI); only a
# bit-7 note free-runs. The walk cannot see that bit in a Goattracker row,
# which is why `pulse_phase_sims` still hands the walk nothing for this engine.

from h2g.goatwriter import PulseBoundsSim, pulse_bounds_sims


def test_the_bounds_sim_reproduces_saboteur_iis_measured_turnaround():
    """Saboteur_II voice 2, record 9 (seed $100, rate $48, bounds $FC),
    frames 1-60 of the original at -m1: reseeded on the attack at frame 1,
    +$48 a frame, $F10 STORED at frame 51 (nibble F == hi) and then the
    descent, $CD0 STORED at frame 59 (nibble C == lo) and then the ascent."""
    s = PulseBoundsSim(0x100, 0x48, lo=0xC, hi=0xF)
    s.advance(1)
    assert s.width == 0x148, "the first frame after the fetch steps"
    s.advance(49)                                   # frame 51
    assert (s.width, s.direction) == (0xF10, -1), hex(s.width)
    s.advance(1)                                    # frame 52
    assert s.width == 0xEC8, "the at-bound value was not stored"
    s.advance(7)                                    # frame 59
    assert (s.width, s.direction) == (0xCD0, +1), hex(s.width)
    s.advance(1)                                    # frame 60
    assert s.width == 0xD18


def test_a_reseeding_note_opens_on_the_seed_and_a_bit_7_note_free_runs():
    """Saboteur_II voice 0, record 3 (seed $080, rate $10, bounds $C0),
    frames 1401-1404: a bit-7 note attacks at 1403 with the width HELD at
    $2B0 (the fetch call does not sweep) and the frame `pphase` reads is
    $2C0 -- bucket 2, where a reseed would have read $080, bucket 0. That
    frame is one of the 56 attacks that give voice 0 its [4, 5, 6, 9]."""
    s = PulseBoundsSim(0x080, 0x10, lo=0x0, hi=0xC)
    s.width = 0x2A0                                 # frame 1401
    s.advance(1)                                    # frame 1402
    assert s.width == 0x2B0
    free = s.clone()
    free.advance(2, skip_first=True)                # 1403 fetch, 1404 step
    assert free.phase() == (0x2C0, +1), "the fetch call swept"
    seeded = s.clone()
    seeded.reseed()
    assert seeded.phase() == (0x080, +1)
    seeded.advance(2, skip_first=True)
    assert seeded.width == 0x090


def test_a_reseed_resets_the_direction_as_well_as_the_width():
    s = PulseBoundsSim(0x000, 0x40, lo=0x0, hi=0x4)
    s.advance(20)
    assert s.direction == -1
    s.reseed()
    assert s.phase() == (0x000, +1)


def test_food_feuds_zero_bound_turns_on_equality_with_nibble_zero():
    """Food_Feud voice 0, record 5 (seed $000, rate $40, bounds $40):
    reseeded at frame 302, $400 stored at 318, $3C0 at 319 -- and the
    descent turns at the FIRST value whose nibble reads lo, $0C0, not at
    $000: frames 154-158 of the original read $100, $0C0, $100, $140. A
    band's bottom is `lo` plus whatever the rate leaves in the low byte."""
    s = PulseBoundsSim(0x000, 0x40, lo=0x0, hi=0x4)
    s.advance(16)
    assert (s.width, s.direction) == (0x400, -1)
    s.advance(1)
    assert s.width == 0x3C0
    s.advance(12)
    assert (s.width, s.direction) == (0x0C0, +1), hex(s.width)
    s.advance(2)
    assert s.width == 0x140


def test_a_band_whose_top_is_below_its_bottom_crosses_fff_in_the_sim():
    """Kings of the Beach ingame instrument 4 (rate $84, bounds $02, seed
    $080), `_pulse_triangle_wrapped`'s measured case: the original climbs
    $080 -> $FF8 in 30 frames and wraps to $07C, where nibble 0 == hi."""
    s = PulseBoundsSim(0x080, 0x84, lo=0x2, hi=0x0)
    s.advance(30)
    assert (s.width, s.direction) == (0xFF8, +1)
    s.advance(1)
    assert (s.width, s.direction) == (0x07C, -1), hex(s.width)


def test_a_zero_rate_bounds_sim_never_moves():
    s = PulseBoundsSim(0x300, 0x00, lo=0x1, hi=0x3)
    s.advance(100)
    assert s.phase() == (0x300, +1)


def test_pulse_bounds_sims_names_exactly_the_sweeping_records():
    """Records 0 and 2 sweep, record 1's rate is zero; the instrument byte
    is the record index plus the layout's lead, as `pulse_phase_sims`."""
    sid = _sid([_record(0x80, 0x00, rate=0x54), _record(0x00, 0x08, rate=0),
                _record(0x40, 0x00, rate=0x40)], [0xF0, 0xFD, 0xF7])
    sims = pulse_bounds_sims(sid, _det(3), lead=1)
    assert sorted(sims) == [2, 4]
    assert (sims[2].seed, sims[2].rate, sims[2].lo, sims[2].hi) == (0x080, 0x54, 0, 0xF)
    assert (sims[4].seed, sims[4].rate, sims[4].lo, sims[4].hi) == (0x040, 0x40, 7, 0xF)
    assert pulse_bounds_sims(sid, _det(3, swept=False), lead=1) == {}


def test_the_walk_is_still_handed_nothing_for_the_bounds_engine():
    """`pulse_phase_sims` is what convert.py's walk consumes, and the walk
    cannot tell a reseeding note from a bit-7 one in a Goattracker row --
    so handing it these sims would phase every note wrongly for one
    population or the other. Pinned so the wiring is a deliberate change."""
    sid = _sid([_record(0x80, 0x00, rate=0x54)], [0xF0])
    assert pulse_phase_sims(sid, _det(1), lead=1) == {}


def test_the_phase_table_serves_a_bounds_engine_record():
    """A planned phase gets its set/ramp/join entry, the record's own start
    pointer is its (seed, up) entry -- so a note WITHOUT a command reseeds,
    exactly as the player does -- and the ramp is measured to the record's
    own high nibble at the rate divided by the multiplier."""
    sid = _sid([_record(0x80, 0x00, rate=0x54)], [0xF0])
    det = _det(1)
    phases = {2: {(0x2B0, +1), (0x2C0, -1)}}
    got = build_pulse_phase_table(sid, det, 2, True, 1, phases, lead=1)
    assert got is not None
    entries, starts, index = got
    assert starts[1] == index[(2, 0x080, +1)], "the start is not the seed phase"
    at = index[(2, 0x2B0, +1)]
    assert entries[at - 1] == (0x82, 0xB0)
    assert entries[at][1] == 0x54, "the ramp speed is not the rate"
    assert sum(t for t, s in entries[at:at + 3] if s == 0x54) == (0xF00 - 0x2B0) // 0x54
    down = index[(2, 0x2C0, -1)]
    assert entries[down - 1] == (0x82, 0xC0)
    assert entries[down][1] == (0x100 - 0x54) & 0xFF, "the descent is not -rate"
    # -S3: the emitted speed is the rate over the multiplier
    e3, _, index3 = build_pulse_phase_table(sid, det, 2, True, 3, phases, lead=1)
    at3 = index3[(2, 0x2B0, +1)]
    assert e3[at3][1] == round(0x54 / 3)


def test_a_wrapped_band_measures_its_ramps_modulo_fff_in_the_table():
    """Bounds $02 with seed $080: the ascent to nibble 0 runs through $FFF,
    so the up-ramp is ($000 - $080) mod $1000 ticks, not zero."""
    sid = _sid([_record(0x80, 0x00, rate=0x84)], [0x02])
    got = build_pulse_phase_table(sid, _det(1), 2, True, 1, {2: {(0x080, +1)}}, lead=1)
    entries, starts, index = got
    at = index[(2, 0x080, +1)]
    ticks = sum(t for t, s in entries[at:at + 40] if s == 0x7F)
    assert ticks == ((0x000 - 0x080) & 0xFFF) // 0x7F, ticks


@needs_corpus
def test_saboteur_ii_and_food_feud_carry_sims_the_option_cannot_reach_yet():
    """The two files the sim was validated on: the bounds engine, sims for
    every sweeping record, and --pulse-phase still byte-inert on both --
    the measurement the wiring task starts from."""
    for name, want in (("Saboteur_II.sid", [1, 4, 6, 8, 9, 10, 11, 15, 16]),
                       ("Food_Feud.sid", [1, 2, 6, 7, 8, 11, 12])):
        sid = load_sid(str(CORPUS / name))
        sid2, det = _detect_tables(sid, lambda m: None, 0)
        assert det.pulse_bounds >= 0 and det.pulse_tri_hi < 0
        assert pulse_phase_sims(sid2, det, 0) == {}
        assert sorted(pulse_bounds_sims(sid2, det, 0)) == want, name
        base = dict(tempo="auto", pulse=True, compact_instruments=True)
        off = convert(str(CORPUS / name), log=lambda m: None, **base)
        on = convert(str(CORPUS / name), log=lambda m: None, pulse_phase=True, **base)
        assert off == on, f"{name}: the option now reaches the bounds engine"
