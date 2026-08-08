"""Per-frame rates written into per-call tables.

Every rate this converter reads out of a Hubbard player is *per frame*: the
drum sweep decrements the frequency high byte once a frame (Warhawk
$1387-$138D), the chromatic rise steps a semitone every fourth frame ($13A2),
a slide adds its 16-bit step once a frame ($1320), and an instrument's attack
waveform stands for one frame.

Every place Goattracker takes those numbers is *per play call*: speed-table
deltas apply inside the per-call TICKNEFFECTS (gplay.c:748/758) and the
wavetable advances one entry per call (gplay.c:707).

Those units agree only at `gt2reloc -S1`. 33 of the 83 preset corpus songs
pack at -S2 -- a CIA stub calling the player at 100 Hz -- and every one of
those rates ran at twice the player's until v0.5.82.

**Nothing in FIDELITY.md could move on this until v0.5.99.** Stock siddump
calls the play routine `seconds * 50` times whatever the PSID speed field says
(siddump.c:309/325), so in the trace every file behaved as multiplier 1 and a
multiplier-dependent change was invisible by construction. tools/siddump-rt
takes `-m` and the harness now passes the song's multiplier, so the trace does
see the rate -- but what it sees is whether the file lands in *real time*,
which is a different question from whether an edit reached the bytes. The
evidence for reach is still here and in the differential hash: exactly the 33
multiplier-2 songs change bytes, and no multiplier-1 song does.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import Detection
from h2g.goatwriter import (DRUM_SPEED, DRUM_SPEED_PER_FRAME, FORMAT_GTS5,
                            RISE_SHIFT, SPEED_NOTE_RELATIVE, WAVE_MAX_DELAY,
                            _drum_speed, _rate_shift, _rise_speed_index,
                            _wave_hold_byte, _wavetable_entries)
from h2g.patterns import (GT_NO_NOTE, build_speed_table,
                          scale_portamento_data)

DRUM, RISE, ARP = 0x01, 0x02, 0x04
WAVELASTDELAY = 0x0F


def wave_timeline(left, right, first=6, calls=24):
    """Which table entry, waveform and note each play call sees.

    A transcription of gplay.c's WAVEEXEC (:516-717), kept here so the shapes
    are pinned against the loop that consumes them rather than against the
    constant someone read out of gcommon.h. The two disagreed for eleven
    versions: a delay entry is current for `value + 1` calls, not `value`,
    because the advance happens on the call where `wavetime == value` and
    `wavetime` was incremented on each call before it.

    Note also that a delay's right side *is* read -- on that final call the
    code falls through to the note block with the `note` it loaded at the top.
    """
    ltable = {first + k: left[k] for k in range(len(left))}
    rtable = {first + k: right[k] for k in range(len(right))}
    ptr, wavetime, cur_wave, cur_note = first, 0, None, None
    out = []
    for _ in range(calls):
        if not ptr or ptr not in ltable:
            out.append((None, cur_wave, cur_note))
            continue
        wave, note = ltable[ptr], rtable[ptr]
        here = ptr
        if wave > WAVELASTDELAY:
            if wave < 0xE0:
                cur_wave = wave
        elif wavetime != wave:
            wavetime += 1
            out.append((here, cur_wave, cur_note))
            continue
        wavetime = 0
        ptr += 1
        if ltable.get(ptr) == 0xFF:
            ptr = rtable[ptr]
        if note != 0x80:
            cur_note = note
        out.append((here, cur_wave, cur_note))
    return out


def attack_calls(left, right, wave):
    """How many play calls the attack waveform is current for."""
    tl = wave_timeline(left, right, calls=40)
    n = 0
    for _, w, _ in tl:
        if w != wave:
            break
        n += 1
    return n


class _FakeSid:
    """One instrument record, as in test_effects."""

    def __init__(self, effect_byte, wave=0x41):
        record = bytes([0x00, 0x00, wave, 0x00, 0x00, 0x00, 0x00, effect_byte])
        self.data = bytes(8) + record


def _entries(effect_byte, *, effects=False, rise=False, arp=False, drum=False,
             speed_table=None, wave=0x41, multiplier=1):
    det = Detection(instr_start=8, instr_stride=8,
                    effect_rise=rise, effect_arp=arp, effect_drum=drum)
    return _wavetable_entries(_FakeSid(effect_byte, wave), det, 0, effects,
                              FORMAT_GTS5,
                              speed_table if speed_table is not None else [],
                              multiplier)


# --- the drum sweep ---------------------------------------------------------

def test_the_drum_step_is_the_players_step_per_frame_at_1x():
    # 256 units a frame, which is one call at -S1. Unchanged from v0.5.62.
    assert _drum_speed(1) == (0x01, 0x00)
    assert DRUM_SPEED == (0x01, 0x00)
    assert DRUM_SPEED_PER_FRAME == 0x0100


def test_the_drum_step_halves_at_2x():
    # Two calls a frame, so half the step per call is the same sweep per frame.
    assert _drum_speed(2) == (0x00, 0x80)
    assert (_drum_speed(2)[0] << 8 | _drum_speed(2)[1]) * 2 == DRUM_SPEED_PER_FRAME


def test_the_drum_step_never_reaches_zero():
    # A step of zero is a sweep that does not move, which is further from the
    # player than one 1/256th slow. No corpus file asks for this -- the
    # multipliers emitted are 1 and 2 -- but the clamp is what makes that a
    # fact about the corpus rather than about the code.
    assert _drum_speed(1000) == (0x00, 0x01)


# --- the chromatic rise -----------------------------------------------------

def test_the_rise_shift_grows_by_one_per_doubling():
    assert _rate_shift(1) == 0
    assert _rate_shift(2) == 1
    assert _rate_shift(4) == 2


def test_the_rise_shift_rounds_at_3x_and_the_docstring_says_so():
    # log2(3) = 1.58: shift 2 divides by four where three is wanted, and is
    # closer than shift 1's division by two. Recorded, not hidden.
    assert _rate_shift(3) == 2
    assert "at -S3 the rise glides 3/4" in _rise_speed_index.__doc__


def test_the_rise_entry_carries_the_scaled_shift():
    table: list = []
    assert _rise_speed_index("gts5", table, 1) == 1
    assert table == [(SPEED_NOTE_RELATIVE, RISE_SHIFT)]
    table = []
    assert _rise_speed_index("gts5", table, 2) == 1
    assert table == [(SPEED_NOTE_RELATIVE, RISE_SHIFT + 1)]


# --- the attack transient ---------------------------------------------------

def test_no_hold_entry_is_spent_at_1x():
    # A call already is a frame, so the entry would only cost a slot.
    assert _wave_hold_byte(1, 0x41) is None


def test_the_hold_is_the_delay_less_one_because_a_delay_holds_one_call_more():
    # A delay of D is current for D + 1 calls (gplay.c:697-704), and entry 0
    # is itself one call, so a frame of m calls asks entry 1 for m - 2.
    assert _wave_hold_byte(3, 0x41) == 1
    assert _wave_hold_byte(4, 0x41) == 2
    assert _wave_hold_byte(64, 0x41) == WAVE_MAX_DELAY


def test_one_extra_call_is_the_waveform_again_not_a_delay_of_zero():
    # $00 is the editor's empty marker, and 0 is not a delay value. Repeating
    # the attack byte buys the same single call with an unambiguous byte.
    assert _wave_hold_byte(2, 0x41) == 0x41
    assert _wave_hold_byte(2, 0x80) == 0x80


def test_the_attack_lasts_exactly_one_frame_at_every_multiplier():
    # The whole point of the hold entry, checked against gplay's own loop
    # rather than against the byte. Until v0.5.130 every one of these was
    # m + 1 -- 1.5 frames at -S2, where 22 of the 37 multispeed files sit.
    # wave $40 has the gate bit clear and tail $41 sets it, so the two are
    # distinguishable -- with `tail == wave` there is no attack to time.
    for m in (1, 2, 3, 4, 6):
        left, right = _entries(0x00, wave=0x40, multiplier=m)
        assert attack_calls(left, right, 0x40) == m, f"-S{m}"


def test_the_plain_shape_spends_its_repeated_entry_on_the_hold():
    # [wave, tail, tail, stop] -- entries 1 and 2 are the same waveform, so
    # entry 1 is free and the attack keeps its frame at no cost.
    at1 = _entries(0x00)
    at3 = _entries(0x00, multiplier=3)
    assert at1[0][1] == at1[0][2], "entry 1 only repeats entry 2 at 1x"
    assert at3[0][1] == 1 and at3[0][2] == at1[0][2]


def test_the_arpeggio_alternates_once_a_frame_not_once_a_call():
    # The player swaps the note every frame ($13CD). Five entries cannot hold
    # attack + 2x(note, hold) + jump, so the jump loops to entry 0 and the
    # attack entry doubles as the note half's first call -- sound only because
    # `tail` and the attack byte are equal here, as they are in all 45 corpus
    # records that reach this branch.
    for m in (1, 2, 3):
        left, right = _entries(ARP | 0x30, effects=True, arp=True,
                               multiplier=m)
        notes = [n for _, _, n in wave_timeline(left, right, calls=12 * m)]
        runs, prev, length = [], object(), 0
        for n in notes:
            if n == prev:
                length += 1
            else:
                if length:
                    runs.append(length)
                prev, length = n, 1
        runs.append(length)
        # the first run is the entries walked before the loop settles and the
        # last is cut off by the call budget; between them every hold is m
        assert set(runs[1:-1]) == {m}, f"-S{m}: note runs {runs}"


def test_the_arpeggio_holds_the_note_across_its_hold_entry():
    # A delay's right side is read on its final call, so the second hold
    # carries $80 -- "no note change" -- or it drags the arpeggio note back
    # to the base note one call early.
    left, right = _entries(ARP | 0x30, effects=True, arp=True, multiplier=3)
    assert right[3] == 0x80


def test_an_arpeggio_whose_attack_differs_from_its_tail_stays_at_1x_shape():
    # Looping through entry 0 rewrites the attack byte once per cycle. That is
    # a no-op only where it equals `tail`; wave $40 has the gate bit clear and
    # tail $41 sets it, so re-entering would retrigger every cycle.
    at1 = _entries(ARP | 0x30, effects=True, arp=True, wave=0x40)
    at2 = _entries(ARP | 0x30, effects=True, arp=True, wave=0x40,
                   multiplier=2)
    assert at2 == at1


def test_the_rise_shape_keeps_its_tail_rather_than_the_delay():
    # Its entry 2 is a command, so entry 1 is the only place the tail waveform
    # is written. wave $40 has the gate bit clear and tail $41 sets it, so the
    # write is real and the delay must stand down.
    at2 = _entries(RISE, effects=True, rise=True, wave=0x40, multiplier=2)
    assert at2[0][1] == 0x41, "the tail, not a delay"


def test_the_rise_shape_takes_the_hold_when_the_tail_writes_nothing():
    # wave $41 already has the gate bit, so tail == wave and entry 1 is inert.
    at3 = _entries(RISE, effects=True, rise=True, wave=0x41, multiplier=3)
    assert at3[0][1] == 1
    at2 = _entries(RISE, effects=True, rise=True, wave=0x41, multiplier=2)
    assert at2[0][1] == 0x41, "one extra call is the waveform, not a delay"


def test_the_drum_shape_has_no_slot_and_says_so():
    # All five entries are in use, so the drum's attack stays at one call --
    # only its sweep rate is scaled. The alternative would be dropping the
    # sweep, which is the thing the frame is for.
    at2 = _entries(DRUM, effects=True, drum=True, multiplier=2)
    assert at2[0][1] == 0x40, "the gate-off waveform, not a delay"
    assert "no slot for" in _wavetable_entries.__globals__[
        "_drum_entries"].__doc__


# --- slides -----------------------------------------------------------------

def _porta(value):
    # One row: no note, no instrument, CMD_PORTAUP (1), the packed step.
    return [[GT_NO_NOTE, 0, 1, value]]


def test_the_speed_table_holds_the_players_step_at_1x():
    assert build_speed_table(_porta(8), 1) == [(0x00, 0x20)]     # 8*4


def test_the_speed_table_halves_the_step_at_2x():
    # Exact: the table stores the 16-bit step, not the pattern column's eighth
    # of it, so there is nothing to round away.
    assert build_speed_table(_porta(8), 2) == [(0x00, 0x10)]
    assert build_speed_table(_porta(1), 2) == [(0x00, 0x02)]


def test_a_scaled_step_never_becomes_no_movement():
    patterns = _porta(1)
    assert build_speed_table(patterns, 64) == [(0x00, 0x01)]
    # ... and the index still names the entry, rather than reverting to 0,
    # which gplay.c reads as "no parameter".
    assert patterns[0][3] == 1


def test_the_index_is_still_written_and_still_deduplicated():
    patterns = [[GT_NO_NOTE, 0, 1, 8, GT_NO_NOTE, 0, 2, 10,
                 GT_NO_NOTE, 0, 1, 8]]
    assert build_speed_table(patterns, 2) == [(0, 0x10), (0, 0x14)]
    assert [patterns[0][k + 3] for k in range(0, 12, 4)] == [1, 2, 1]


def test_a_zero_parameter_is_still_left_alone_when_scaling():
    patterns = [[GT_NO_NOTE, 0, 3, 0x00]]
    assert build_speed_table(patterns, 2) == []
    assert patterns[0][3] == 0


# --- slides in a GTS2 file --------------------------------------------------
#
# A GTS2 file stores no speed table; its loader rebuilds one from this column
# (gsong.c:311-321), so the column is the only place the rate can be scaled.

def test_the_gts2_column_is_divided_and_the_count_returned():
    patterns = _porta(8)
    assert scale_portamento_data(patterns, 2) == 1
    assert patterns[0][3] == 4


def test_the_gts2_column_never_reaches_zero():
    patterns = _porta(1)
    scale_portamento_data(patterns, 2)
    assert patterns[0][3] == 1, "0 would read as 'no parameter'"


def test_the_gts2_column_leaves_non_table_commands_and_zeros_alone():
    patterns = [[GT_NO_NOTE, 0, 15, 0x08, GT_NO_NOTE, 0, 1, 0x00]]
    assert scale_portamento_data(patterns, 2) == 0
    assert patterns[0][3] == 0x08 and patterns[0][7] == 0x00
