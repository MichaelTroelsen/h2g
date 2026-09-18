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
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus

from h2g.convert import convert
from h2g.detect import Detection, detect
from h2g.goatwriter import (FIRSTWAVE_GATE_ONLY, FIRSTWAVE_TESTBIT,
                            WAVE_NOTE_ABS, _fixed_attack_note,
                            _write_instruments)
from h2g.sidfile import SidFile, load_sid

import fidelity
import presets
import songview

COMMANDO = Path(__file__).resolve().parents[2] / "Commando.sid"
SANXION = CORPUS / "Sanxion.sid"
PRESETS_JSON = Path(__file__).resolve().parents[2] / "presets.json"

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


# Sanxion voice 2's drum: the original writes noise ($81) on the note's
# second call and forces the frequency to a fixed $41B8 (GT note index 71,
# B-5) on every hit regardless of the pattern's own pitch -- siddump on the
# original names it "(B-5 C7)" ($C7 == WAVE_NOTE_ABS + 71). Four instrument
# records (source indices 0, 4, 12, 13) carry effect byte $44: bit $40 is
# the fixed-attack-pitch effect (`_fixed_attack_note`, `det.fixed_pitch_index`
# is the handler's own operand at file offset 0x6D2) and bit $04 is this
# player's two-stage attack waveform, not an arpeggio
# (`det.effect_two_stage`). Record 0's slot in the fixed-pitch table is byte
# $47 == 71, which is exactly the frequency-table index for $41B8 --
# `_fixed_attack_note` reads it through the handler's operand rather than
# `det.wave_program` (which Sanxion, like Food_Feud, does not have), and
# `_two_stage_entries`' `attack_note` parameter is what turns it into the
# wavetable's absolute-note byte ($80 + 71 == $C7) instead of $00 (the
# pattern's own note under the noise -- the bug this pins against).
@needs_corpus
def test_sanxion_voice2_drum_fixed_attack_note_is_absolute_b5():
    sid = load_sid(str(SANXION))
    det = detect(sid, log=lambda m: None)
    assert det.effect_bit40
    assert det.effect_two_stage
    note = _fixed_attack_note(sid, det, 0)
    assert note == WAVE_NOTE_ABS + 71 == 0xC7


@needs_corpus
def test_sanxion_shipped_preset_wavetable_carries_the_fixed_note():
    """Record 0's own conversion, through the presets this song actually
    ships with (`two_stage` is on for Sanxion in presets.json), has to reach
    the wavetable as $81/$C7 -- not $81/$00, which is the pattern's note
    left under the noise. A regression here means the fix stopped reaching
    the record, not just that `_fixed_attack_note` still computes the byte."""
    doc = json.loads(PRESETS_JSON.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Sanxion.sid")
    assert opts["two_stage"], "Sanxion's shipped preset must keep two_stage on"
    sng = convert(str(SANXION), log=lambda m: None, **opts)
    song = songview.parse_sng(sng)
    hit = next(i for i in song.instruments if i.effect_byte == 0x44
              and i.name.startswith("02:"))
    wp = hit.wave_ptr
    assert song.tables["WTBL"][wp] == (0x81, 0xC7)
