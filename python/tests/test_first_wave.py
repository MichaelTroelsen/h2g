"""Record byte +8, the waveform Goattracker writes on a note's first frame.

Every instrument this tool has ever written carries `$09` there -- testbit plus
gate. The testbit holds the oscillator's phase accumulator and the noise LFSR at
zero, so that frame is silent, and it is one frame of every note. Hubbard's
players write 4273 such frames across 12 of the 83 corpus files; conversions
write 9179 across 79, so most of ours are invented.

`--no-test-restart` writes the record's own waveform with the gate on instead,
which is what the player's first frame actually holds (Commando's noise record
traces `81 80 80 80 80`). It is **off by default and deliberately not in
`presets.json`'s `always` block**, because the measurement went the other way:
`wave` rises 69.8% -> 73.9% corpus-wide and `melody` falls 79.6% -> 63.9%. The
testbit frame is what makes a re-struck note retrigger.

Two readings of that are pinned here, because both were tried:

* `$FF` -- gate on, waveform untouched -- scored `wave` 99.5% on Commando while
  losing 79 notes. A per-frame agreement *rewards* losing notes: fewer attacks
  means fewer transitions to disagree about. That number was not fidelity.
* the own-waveform form keeps the note count (Commando's three voices give 139,
  105, 216 collapsed attacks against the original's 140, 105, 217) and still
  costs melody, so it is the honest form of a change that is still not a win.
"""
from pathlib import Path

from h2g.convert import convert
from h2g.detect import Detection
from h2g.goatwriter import (FIRSTWAVE_GATE_ONLY, FIRSTWAVE_TESTBIT,
                            _write_instruments)
from h2g.sidfile import SidFile

import presets

COMMANDO = Path(__file__).resolve().parents[2] / "Commando.sid"

STRIDE = 8
INSTR_AT = 0x40
FIRSTWAVE = 8       # byte +8 of a 9-byte record
RECORD = 25         # ...followed by the 16-byte name


def _sid(waveforms) -> SidFile:
    data = bytearray(INSTR_AT + (len(waveforms) + 1) * STRIDE)
    for i, wf in enumerate(waveforms):
        data[INSTR_AT + i * STRIDE + 2] = wf
    return SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                   released="r", load_addr=0x1000, subtunes=1)


def _records(waveforms, **kw):
    n = len(waveforms)
    out = bytearray()
    _write_instruments(out, _sid(waveforms),
                       Detection(instr_start=INSTR_AT, instr_used=n,
                                 instr_stride=STRIDE, track_lo=1, track_hi=2,
                                 pattern_lo=3, pattern_hi=4, pattern_used=0,
                                 read_track_version=0),
                       n, [0] * (n + 1), lead=0, **kw)
    return [out[1 + i * RECORD + FIRSTWAVE] for i in range(n)]


def test_the_default_is_the_testbit_byte_the_tool_has_always_written():
    assert _records([0x41, 0x81, 0x15]) == [FIRSTWAVE_TESTBIT] * 3


def test_the_flag_writes_the_records_own_waveform_with_the_gate_on():
    """What the player's first frame holds. Below $FE a firstwave is assigned to
    the waveform and forces the gate on (gplay.c:355-363), so one byte buys both
    a real attack and no silent frame."""
    assert _records([0x41, 0x80, 0x15, 0x21],
                    no_test_restart=True) == [0x41, 0x81, 0x15, 0x21]


def test_the_gate_only_form_is_named_but_not_what_the_flag_writes():
    """$FF sets the gate and leaves the waveform alone. It scored `wave` 99.5%
    on Commando by losing 79 notes, so it is not what the flag does -- the
    constant stays because the docstring above is about it."""
    assert FIRSTWAVE_GATE_ONLY == 0xFF
    assert FIRSTWAVE_GATE_ONLY not in _records([0x41], no_test_restart=True)


def test_a_waveform_that_already_gates_is_left_alone():
    assert _records([0x41], no_test_restart=True) == [0x41]


def test_the_fixture_is_byte_exact_because_the_flag_is_off_by_default():
    assert len(convert(str(COMMANDO), log=lambda m: None)) == 15193


def test_the_flag_reaches_the_output_and_is_excluded_from_always_on_purpose():
    plain = convert(str(COMMANDO), log=lambda m: None)
    changed = convert(str(COMMANDO), log=lambda m: None, no_test_restart=True)
    assert changed != plain, "an option that reaches nothing is the worse bug"
    assert "no_test_restart" in presets.EXCLUDED_FROM_ALWAYS
    assert "no_test_restart" not in presets.FIXED
