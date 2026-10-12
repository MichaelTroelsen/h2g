"""The per-record-bounds engine turns where the player turns.

`_pulse_program` (the engine `PulseBoundsSim` reads) used to aim each leg at
the bound -- `high << 8` going up, `low << 8` going down -- while the player
turns on the first width of its step lattice whose high nibble EQUALS the
bound (`LDA acc / ADC rate / AND #$0F / CMP bound / BNE`, Saboteur_II
$F297-$F2F0). Saboteur_II's record 10 (seed $160, rate $40, bounds $9F) ran
$901..EFE (1533) where the player runs $9E0..F20 (1344). Passing the record's
rate as the lattice step (`_pulse_triangle(..., step)`, `_tri_turns`,
`_lattice_legs`: the code the triangle engine already shipped) puts the legs
on the player's widths. Census under presets at f75cc7f: 484 bounds-engine
records on 42 files, 0 exact before and 360 after, and every record's span
within one GT speed of the player's after (13 of 484 within half a speed
before, 450 after).

The player's turns are re-derived here by an independent walk (`_player`),
not through `PulseBoundsSim` or `_tri_turns`, so a defect in either cannot
hide in both readers.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                       # noqa: E402
from h2g.detect import Detection, detect                      # noqa: E402
from h2g.goatwriter import PulseBoundsSim, _pulse_program     # noqa: E402
from h2g.goatwriter.pulse import _tri_turns                   # noqa: E402
from h2g.sidfile import SidFile, load_sid                     # noqa: E402

STRIDE, INSTR_AT, BOUNDS_AT, RATE_FIELD = 8, 0x40, 0x100, 6


def _sid(width, rate, bounds) -> SidFile:
    data = bytearray(BOUNDS_AT + 2 * STRIDE + 0x40)
    data[INSTR_AT:INSTR_AT + STRIDE] = bytes(
        [width & 0xFF, width >> 8, 0x41, 0, 0, 0, rate, 0])
    data[BOUNDS_AT] = bounds
    return SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                   released="r", load_addr=0x1000, subtunes=1)


def _det() -> Detection:
    return Detection(instr_start=INSTR_AT, instr_used=1, instr_stride=STRIDE,
                     track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                     pattern_used=0, read_track_version=0,
                     pulse_bounds=BOUNDS_AT, pulse_rate_field=RATE_FIELD)


def _player(width, rate, lo, hi):
    """(first top, bottom, steady top) by the routine's own rule: add (or
    subtract) the rate into 12 bits, turn when the high nibble of the result
    equals the bound being approached."""
    x, out = width, []
    for bound, d in ((hi, +1), (lo, -1), (hi, +1)):
        for _ in range(0x1000 // rate + 3):
            x = (x + d * rate) & 0xFFF
            if x >> 8 == bound:
                break
        else:
            raise AssertionError("never turns")
        out.append(x)
    return tuple(out)


def _play(entries, loop, calls):
    """The widths a GT pulse program holds call by call (gplay.c:872-902)."""
    w, out, i = None, [], 0
    while len(out) < calls:
        if i >= len(entries):
            i = loop
        left, right = entries[i]
        if left >= 0x80:
            w = ((left & 0x0F) << 8) | right
            out.append(w)
        else:
            d = right if right < 0x80 else right - 0x100
            for _ in range(left):
                w = (w + d) & 0xFFF
                out.append(w)
        i += 1
    return out


def _turns(widths):
    """The widths where the program reverses, in order. Directions are read
    off the 12-bit signed difference, so a leg through $FFF is one leg."""
    def sgn(a, b):
        d = ((b - a + 0x800) & 0xFFF) - 0x800
        return (d > 0) - (d < 0)
    out, last = [], 0
    for a, b, c in zip(widths, widths[1:], widths[2:]):
        if b != a:
            last = sgn(a, b)
        if c != b and last and sgn(b, c) != last:
            out.append(b)
    return out


def test_the_lattice_helper_and_the_bounds_sim_are_one_arithmetic():
    """`_tri_turns` is read off `PulsePhaseSim`; the bounds engine's own
    `PulseBoundsSim` must take the same turns from the same seed."""
    for width in range(0, 0x1000, 0x9D):
        for rate in (0x10, 0x24, 0x40, 0x54, 0x84, 0xE0, 0xFF):
            for lo, hi in ((2, 8), (8, 8), (9, 4), (0, 0xF), (3, 0)):
                sim = PulseBoundsSim(width, rate, lo, hi)
                got = []
                for want in (-1, +1, -1):
                    for _ in range(0x1000 // rate + 3):
                        sim.advance(1)
                        if sim.direction == want:
                            break
                    got.append(sim.width)
                assert tuple(got) == _player(width, rate, lo, hi)
                assert _tri_turns(width, rate, lo, hi) == tuple(got)


def test_where_the_speed_is_the_rate_every_turn_is_the_players_width():
    """-S1, rate <= 127: the GT speed is the rate itself, so every turn of
    the program -- first top, bottom and every later top -- is exactly a
    width the player turns on, banded the right way round or wrapped."""
    for width in range(0, 0x1000, 0x53):
        for rate in (0x10, 0x24, 0x40, 0x54, 0x7F):
            for lo, hi in ((2, 8), (8, 8), (9, 4), (0, 0xF), (5, 5), (3, 0)):
                want = _player(width, rate, lo, hi)
                entries, loop = _pulse_program(
                    _sid(width, rate, (hi << 4) | lo), _det(), 0, True, 1)
                got = _turns(_play(entries, loop, 3 * (0x1000 // rate) + 40))
                assert got, (hex(width), rate, lo, hi)
                assert got[0] == want[0], (hex(width), rate, lo, hi, got[:3])
                assert got[1] == want[1], (hex(width), rate, lo, hi, got[:3])
                assert set(got[2::2]) == {want[2]}, (hex(width), rate, lo, hi)
                assert set(got[1::2]) == {want[1]}, (hex(width), rate, lo, hi)


def test_a_record_opening_on_the_top_nibble_steps_up_and_turns_first():
    """Seed $800, band 8..8, rate $40: $840 is still nibble 8, so the player
    turns there at once and jitters $800 / $840 (before: $7C0 / $800)."""
    entries, loop = _pulse_program(_sid(0x800, 0x40, 0x88), _det(), 0, True, 1)
    assert _turns(_play(entries, loop, 20))[:6] == [0x840, 0x800] * 3


def test_a_speed_that_does_not_divide_the_rate_turns_within_half_a_speed():
    """At -S3 a rate of $54 (84) is a GT speed of 28 per call: three calls
    make a frame. The turn is laid at the nearest tick, so it is within half a
    speed of the player's, measured from where the leg actually started."""
    width, rate, lo, hi = 0x080, 84, 0x0, 0xF
    want = _player(width, rate, lo, hi)
    entries, loop = _pulse_program(_sid(width, rate, (hi << 4) | lo), _det(), 0,
                                   True, 3)
    speed = entries[1][1]
    assert speed == 28
    got = _turns(_play(entries, loop, 6000))
    assert abs(got[0] - want[0]) <= speed // 2 + 1
    assert abs(got[1] - want[1]) <= speed // 2 + 1


@needs_corpus
def test_saboteur_iis_records_turn_on_the_players_widths():
    """Census under presets at -S3: records 0, 5, 7, 9 and 14 turn on exactly
    the player's widths, the other four within one speed. RETRACTED: record 10
    ran $901..EFE (1533) before, the player's $9E0..F20 (1344)."""
    path = CORPUS / "Saboteur_II.sid"
    if not path.exists():
        pytest.skip("corpus not present")
    sid = load_sid(str(path))
    det = detect(sid, log=lambda m: None)
    exact = 0
    for i in (0, 3, 5, 7, 8, 9, 10, 14, 15):
        base = det.instr_start + i * det.instr_stride
        rate = sid.data[base + det.pulse_rate_field]
        b = sid.data[det.pulse_bounds + i * det.instr_stride]
        width = ((sid.data[base + 1] & 0x0F) << 8) | sid.data[base]
        want = _player(width, rate, b & 15, b >> 4)
        entries, loop = _pulse_program(sid, det, i, True, 3)
        speed = max(s for t, s in entries[1:] if s < 0x80)
        got = _turns(_play(entries, loop, 3 * 0x1000 // speed + 200))
        assert abs(got[1] - want[1]) <= speed, (i, hex(got[1]), hex(want[1]))
        assert abs(got[2] - want[2]) <= speed, (i, hex(got[2]), hex(want[2]))
        exact += got[1] == want[1] and got[2] == want[2]
    assert exact == 5


@needs_corpus
def test_kings_of_the_beach_ingames_record_4_turns_on_290_and_07c():
    """Rate $84 at -S3 (speed 44, so 132 a frame exactly), seed $080, bounds
    $02: the player climbs through $FFF and turns on $07C, descends to $290
    and turns, and is on those two widths for ever after."""
    path = CORPUS / "Kings_of_the_Beach_ingame.sid"
    if not path.exists():
        pytest.skip("corpus not present")
    sid = load_sid(str(path))
    det = detect(sid, log=lambda m: None)
    assert _player(0x080, 0x84, 2, 0) == (0x07C, 0x290, 0x07C)
    entries, loop = _pulse_program(sid, det, 4, True, 3)
    got = _turns(_play(entries, loop, 2000))
    assert got[:2] == [0x07C, 0x290]
    assert set(got[2::2]) == {0x07C} and set(got[1::2]) == {0x290}
