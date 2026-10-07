"""The triangle engine's static program turns where the player turns: on the
first width of the record's step lattice whose high nibble EQUALS the bound
(`goatwriter.pulse._tri_turns`, `_lattice_legs`), not on the bound itself.

The routine adds its step into a 12-bit width and turns when the high nibble
after the step equals $0E going up or $08 going down (`ADC #$00 / AND #$0F /
CMP #$0E / BNE`, Commando $5275-$527C). So Game_Killer's record 2 ($9C0, step
$E0) cycles 8E0..E20 -- 1344 a leg -- where the old table ran 808..DF6 (1518),
a whole nibble too far at the bottom. Census under presets at 6e467ff: 0 of
the 111 triangle records turned on the player's widths before this; 68 do
exactly and all 111 within half a GT speed after it (the rest are speeds that
do not divide the step, e.g. Game_Killer's 22 against 224 a tick).

The player's turns are re-derived here by an independent walk (`_player`), not
through `PulsePhaseSim`, so a defect in the sim cannot hide in both readers.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables                       # noqa: E402
from h2g.goatwriter.pulse import (_pulse_triangle,           # noqa: E402
                                  _pulse_tri_program, _tri_turns,
                                  _tri_step_delay)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
LO, HI = 0x08, 0x0E


def _player(width: int, step: int, lo: int = LO, hi: int = HI):
    """(first top, bottom, steady top) by the routine's own rule: step, then
    turn when the high nibble equals the bound being approached."""
    x, out = width, []
    for bound, d in ((hi, +1), (lo, -1), (hi, +1)):
        for _ in range(0x1000 // step + 2):
            x = (x + d * step) & 0xFFF
            if x >> 8 == bound:
                break
        else:
            raise AssertionError("never turns")
        out.append(x)
    return tuple(out)


def _play(entries, loop, calls):
    """The widths a GT pulse program holds, call by call (gplay.c:872-902): a
    set row sets the width and spends its call, a step row adds its signed
    speed `ticks` times, the end jumps back to `loop`."""
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
    """The widths where the program reverses, in order."""
    out, last = [], 0
    for a, b, c in zip(widths, widths[1:], widths[2:]):
        if b != a:
            last = 1 if b > a else -1
        if c != b and (1 if c > b else -1) != last and last:
            out.append(b)
    return out


def test_game_killers_record_turns_on_8e0_and_e20():
    assert _player(0x9C0, 0xE0) == (0xE20, 0x8E0, 0xE20)
    assert _tri_turns(0x9C0, 0xE0, LO, HI) == (0xE20, 0x8E0, 0xE20)


def test_a_record_opening_in_the_top_nibble_turns_one_step_up_first():
    """Devils_Galop's record 9, $E00 step $80: $E80 is still nibble E, so the
    first step turns it; every later top is $E00."""
    assert _tri_turns(0xE00, 0x80, LO, HI) == (0xE80, 0x880, 0xE00)
    entries, loop = _pulse_triangle(0xE00, LO, HI, 64, 0x80)
    turns = _turns(_play(entries, loop, 400))
    assert turns[:3] == [0xE80, 0x880, 0xE00], [hex(t) for t in turns[:3]]
    assert set(turns[1:]) == {0x880, 0xE00}


def test_tri_turns_agrees_with_the_independent_walk():
    for width in range(0, 0xE00, 0x2A):
        for step in range(0x10, 0x100, 0x10):
            assert _tri_turns(width, step, LO, HI) == _player(width, step), (
                hex(width), step)


def test_where_the_speed_is_the_step_every_turn_is_the_players_width():
    """-S1, delay 1, step <= 127: the GT speed is the step itself, so the
    program's every turn is exactly a width the player turns on."""
    for width in range(0, 0xE00, 0x37):
        for step in (0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70):
            want = _player(width, step)
            entries, loop = _pulse_triangle(width, LO, HI, step, step)
            turns = _turns(_play(entries, loop, 4000))
            assert turns[0] == want[0], (hex(width), step)
            assert set(turns[1:]) == {want[1], want[2]}, (
                hex(width), step, [hex(t) for t in turns[:4]])


def test_every_turn_is_within_half_a_speed_of_the_players():
    """Where the speed does not divide the step, each leg is the tick count
    whose arrival is nearest the player's width, measured from where the last
    leg stopped -- so the error never exceeds half a speed and never grows."""
    for width in range(0, 0xE00, 0x53):
        for step in range(0x20, 0x100, 0x20):
            for speed in (3, 6, 7, 11, 17, 22, 56, 72, 96, 112, 127):
                if speed > step:
                    continue
                want = _player(width, step)
                entries, loop = _pulse_triangle(width, LO, HI, speed, step)
                turns = _turns(_play(entries, loop, 20000))
                assert len(turns) >= 4, (hex(width), step, speed)
                assert 2 * abs(turns[0] - want[0]) <= speed
                for t in turns[1:]:
                    err = min(abs(t - want[1]), abs(t - want[2]))
                    assert 2 * err <= speed, (hex(width), step, speed, hex(t))


def test_without_a_step_the_bounds_engine_keeps_its_edges():
    """`_pulse_program` (the per-record-bounds engine) passes no step and was
    not measured here: its table is byte-for-byte the old one."""
    # ($E00 - $9C0) // 22 = 49 up; ($9C0 + 49*22 - $800) // 22 = 69 a leg.
    assert _pulse_triangle(0x9C0, LO, HI, 22) == (
        [(0x89, 0xC0), (49, 22), (69, 0x100 - 22), (69, 22)], 2)


# --- the measured files, on the corpus ----------------------------------------

# (file, record, the player's (bottom, top), our table's (bottom, top)), from
# the census at 6e467ff under presets.json. Game_Killer's speed 22 cannot say
# 224 a tick exactly; One_Man's 112 and Human_Race's 64 can.
_MEASURED = (
    ("Game_Killer.sid", 2, (0x8E0, 0xE20), (0x8E4, 0xE22)),
    ("Game_Killer.sid", 7, (0x8E0, 0xE20), (0x8E8, 0xE26)),
    ("One_Man_and_his_Droid.sid", 14, (0x8E0, 0xE20), (0x8E0, 0xE20)),
    ("Human_Race.sid", 0, (0x880, 0xE00), (0x880, 0xE00)),
    ("Human_Race.sid", 3, (0x820, 0xE40), (0x820, 0xE40)),
    ("Ninja.sid", 12, (0x880, 0xE00), (0x860, 0xE00)),
    ("Devils_Galop.sid", 9, (0x880, 0xE00), (0x880, 0xE00)),
)


def _mult(doc, name):
    return doc["songs"][name].get("multiplier", 1)


@needs_corpus
def test_the_measured_records_turn_where_the_census_says():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    for name, rec, player, ours in _MEASURED:
        # convert's own reading: Devils_Galop's tables are written by init.
        sid, det = _detect_tables(load_sid(str(CORPUS / name)), lambda *_: None)
        entries, loop = _pulse_tri_program(sid, det, rec, _mult(doc, name))
        base = det.instr_start + rec * det.instr_stride
        width = ((sid.data[base + 1] & 0x0F) << 8) | sid.data[base]
        step, _ = _tri_step_delay(det, sid.data[base + 6])
        first, bottom, top = _player(width, step)
        assert (bottom, top) == player, (name, rec, hex(bottom), hex(top))
        steady = _play(entries, loop, 6000)[3000:]
        assert (min(steady), max(steady)) == ours, (
            name, rec, hex(min(steady)), hex(max(steady)))


@needs_corpus
def test_every_triangle_record_of_the_measured_files_is_within_half_a_speed():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    seen = 0
    for name in sorted({m[0] for m in _MEASURED}):
        # convert's own reading: Devils_Galop's tables are written by init.
        sid, det = _detect_tables(load_sid(str(CORPUS / name)), lambda *_: None)
        assert det.pulse_tri_hi >= 0, name
        for rec in range(det.instr_used):
            got = _pulse_tri_program(sid, det, rec, _mult(doc, name))
            if got is None:
                continue
            entries, loop = got
            speed = max(s for t, s in entries[1:] if t < 0x80 and s < 0x80)
            base = det.instr_start + rec * det.instr_stride
            width = ((sid.data[base + 1] & 0x0F) << 8) | sid.data[base]
            step, _ = _tri_step_delay(det, sid.data[base + 6])
            _, bottom, top = _player(width, step, det.pulse_tri_lo,
                                     det.pulse_tri_hi)
            steady = _play(entries, loop, 30000)[20000:]
            assert 2 * abs(min(steady) - bottom) <= speed, (name, rec)
            assert 2 * abs(max(steady) - top) <= speed, (name, rec)
            seen += 1
    assert seen >= len(_MEASURED), seen
