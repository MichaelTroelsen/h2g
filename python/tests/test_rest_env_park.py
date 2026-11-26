"""`--rest-wave-silence` beside `--rest-envelope-silence`: the park program
zeroes SR on the park's own call and one call BEFORE the park
(`goatwriter.rest_park.REST_PARK_ENV_PROGRAM`), and the rest's first hold row
carries the AD half (`rest_park_pass`'s `_hold_sr_to_ad`).

The player's rest handler writes the stored waveform `$08` and zeroes SR and
AD on ONE call (Thundercats `$EE38`: `STA $D406,Y / STA $D405,Y / LDA #$08 /
JMP $EEA4`; Auf_Wiedersehen_Monty `$E543`). A wavetable program runs one row
per CALL (gplay.c `WAVEEXEC`), so the writes cannot share one; the order and
the placement were measured (2026-11-15, task thundercats-wave-9865-9848-and-
auf-wiedersehen, `fidelity.py -t 180 --sound`, rest_wave_silence added to the
shipped preset of the two files):

* the park FIRST in the program put it on call 0, the row's own call, and at
  -S3 a rest that starts on the grid's last call lands the park a frame
  before the original's: 41 of 119 voice-1 parks of Thundercats, wave .9865
  -> .9848. SR first puts the park on call 1 (wave .9865 flat, hold 1.000).
* SR and AD both in the program put a `$Fx` command row on a TICK-N call,
  and gplay.c:711-712 sends a command row to PULSEEXEC, skipping that call's
  tick-N effects: one vibrato step lost per rest, Auf travel .9383 -> .9350.
  SR alone in the program and the AD on the first hold row keeps travel at
  .9383 exactly.
* three pattern rows (park, SR, AD) pushed the regrid tempo pair one row
  later, one Auf attack arrived a frame early (onset_timing_early 0 -> 1).

The AD half on the hold row sits a whole row (4 frames at IK_plus' tempo)
after the park, and `adsr` compares the $D405/$D406 PAIR frame by frame, so
the pair disagrees for those frames. A rest whose live instrument has NO
vibrato pointer has no vibrato step for the third row to cost, so it takes
`REST_PARK_ENV_FULL_PROGRAM` (SR, park, AD) and its hold row carries nothing;
a rest on a vibrato instrument, or on one the walk cannot name, keeps the
two-row program and the hold-row AD (measured 2026-11-16, task
rest-park-ad-zero-placement-ik-plus-bangkok-i-ball, `fidelity.py -t 180
--sound`, both rest options on, against the hold-row AD for every rest:
IK_plus adsr .9323 -> .9436, Bangkok_Knights .9411 -> .9511, Thundercats
.9787 -> .9881; the AD in the program for EVERY rest instead cost
Auf_Wiedersehen_Monty, IK_plus and I_Ball travel_ratio .9383 -> .9350,
.9834 -> .9773 and .7207 -> .7179, which this split keeps flat).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g.goatwriter import rest_park as RP  # noqa: E402
from h2g import patterns as P  # noqa: E402

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"

KEYOFF, NO_NOTE = P.GT_KEYOFF, P.GT_NO_NOTE
SETWAVE, SETWAVEPTR = P.CMD_SETWAVE, P.CMD_SETWAVEPTR
SETSR, SETAD = P.CMD_SETSR, P.CMD_SETAD

ENV_PROGRAM_BYTES = bytes([0xF6, 0xE8, 0xFF])


def _pat(*rows):
    return [b for row in rows for b in row] + [0xFF, 0, 0, 0]


class Voice:
    """gplay.c's WAVEEXEC for the three row kinds the program uses."""

    def __init__(self, table, ptr):
        self.table, self.ptr = table, ptr
        self.wave, self.sr, self.ad = 0x41, 0xB7, 0x07

    def call(self):
        if not self.ptr:
            return
        wave, param = self.table[self.ptr - 1]
        if 0xE0 <= wave <= 0xEF:
            self.wave = wave & 0xF
        elif 0xF0 <= wave <= 0xFE:
            if wave & 0xF == SETSR:
                self.sr = param
            elif wave & 0xF == SETAD:
                self.ad = param
        self.ptr += 1
        if self.table[self.ptr - 1][0] == 0xFF:
            self.ptr = self.table[self.ptr - 1][1]


def test_the_env_program_zeroes_sr_then_parks_one_row_per_call():
    prog = RP.REST_PARK_ENV_PROGRAM
    assert bytes(b for row in prog for b in row[:1]) == ENV_PROGRAM_BYTES
    v = Voice(list(prog), 1)
    seen = []
    for _ in range(4):
        v.call()
        seen.append((v.wave, v.sr, v.ad))
    assert seen[0] == (0x41, 0x00, 0x07), "call 0: SR alone, the park not yet"
    assert seen[1] == (0x08, 0x00, 0x07), "call 1: the park"
    assert v.ptr == 0, "the program stops, nothing rewrites the two"
    assert seen[1] == seen[3]


def test_the_full_program_zeroes_sr_parks_then_zeroes_ad():
    prog = RP.REST_PARK_ENV_FULL_PROGRAM
    assert bytes(b for row in prog for b in row[:1]) == bytes(
        [0xF6, 0xE8, 0xF5, 0xFF])
    v = Voice(list(prog), 1)
    seen = []
    for _ in range(4):
        v.call()
        seen.append((v.wave, v.sr, v.ad))
    assert seen[0] == (0x41, 0x00, 0x07), "call 0: SR alone"
    assert seen[1] == (0x08, 0x00, 0x07), "call 1: the park, as without the AD"
    assert seen[2] == (0x08, 0x00, 0x00), "call 2: the AD"
    assert v.ptr == 0 and seen[2] == seen[3]


def _song():
    entries = [(0x41, 0x00), (0xFF, 0x01)]
    starts = {1: 1}
    pats = [_pat((0x60, 1, 0, 0),
                 (KEYOFF, 0, SETWAVE, 0x08),
                 (NO_NOTE, 0, SETSR, 0))]
    return pats, [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]], entries, starts


def test_the_plan_appends_the_env_program_only_when_asked():
    pats, tracks, entries, starts = _song()
    plain, rows = RP.rest_park_plan(pats, tracks, entries, starts)
    assert rows[len(entries):] == list(RP.REST_PARK_PROGRAM)
    env, rows = RP.rest_park_plan(pats, tracks, entries, starts, envelope=True)
    assert rows[len(entries):] == list(RP.REST_PARK_ENV_PROGRAM)
    park = len(entries) + 1
    assert env[0][4 + 2:4 + 4] == [SETWAVEPTR, park]
    assert env[0][8 + 2:8 + 4] == [SETAD, 0],         "the program has the SR; the hold row carries the AD"
    assert plain[0][4 + 2:4 + 4] == [SETWAVEPTR, park]
    assert plain[0][8 + 2:8 + 4] == [SETSR, 0], "no envelope option: unchanged"


def test_program_stop_with_the_envelope_gives_a_wait_zero_rest_its_sr_back():
    """A rest with no hold row carries only the park on row 0; cleared, it is
    the envelope option's own spelling again (SETSR on row 0)."""
    entries = [(0x41, 0x00), (0xFF, 0x01)]
    starts = {1: 0, 2: 1}
    pats = [_pat((0x60, 2, 0, 0)),
            _pat((0x60, 1, 0, 0), (KEYOFF, 0, SETWAVE, 0x08))]
    tracks = [[0, 1, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    new, _ = RP.rest_park_plan(pats, tracks, entries, starts,
                               only=frozenset({2}), envelope=True)
    assert new[1][4 + 2:4 + 4] == [SETSR, 0]
    plain, _ = RP.rest_park_plan(pats, tracks, entries, starts,
                                 only=frozenset({2}))
    assert plain[1][4 + 2:4 + 4] == [0, 0], "no envelope option, no SETSR"


def test_the_combined_rest_filler_rows_carry_no_stale_data_byte():
    """The SETWAVE is row 0's one-shot; the hold rows past the two commands
    must not print `00 $08`."""
    from h2g.goatwriter import CMD_SETTEMPO  # noqa: F401  (import order)
    from test_rest_envelope import _decode, _rows
    rows = _rows(_decode([0x44], rest_keyoff=True, rest_wave=True,
                         rest_envelope=True))
    assert rows[0] == (KEYOFF, 0, SETWAVE, 0x08)
    assert rows[1] == (NO_NOTE, 0, SETSR, 0)
    assert rows[2] == (NO_NOTE, 0, 0, 0), "two command rows, not three"
    assert rows[3] == (NO_NOTE, 0, 0, 0)
    assert rows[4] == (NO_NOTE, 0, 0, 0)


def _convert(name, **extra):
    from h2g.convert import convert
    import fidelity as F
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, name)
    opts.update(extra)
    return convert(str(CORPUS / name), log=lambda *a, **k: None, **opts)


@pytest.mark.skipif(not (CORPUS / "Thundercats.sid").exists(),
                    reason="corpus absent")
def test_thundercats_both_options_ship_the_env_program_and_one_option_does_not():
    both = _convert("Thundercats.sid", rest_wave_silence=True)
    assert ENV_PROGRAM_BYTES in both, \
        "the park program that zeroes SR and AD is in the wavetable"
    assert bytes([0xF6, 0xE8, 0xF5, 0xFF]) in both, \
        "...and the one with the AD as a third row, for the no-vibrato rests"
    alone = _convert("Thundercats.sid", rest_wave_silence=True,
                     rest_envelope_silence=False)
    assert ENV_PROGRAM_BYTES not in alone
    shipped = _convert("Thundercats.sid")
    assert ENV_PROGRAM_BYTES not in shipped, \
        "the option is off in the shipped preset: nothing moves"


def _two_class_song():
    """Instrument 1 has no vibrato pointer, instrument 2 has one; each plays
    a note then rests with one hold row."""
    entries = [(0x41, 0x00), (0xFF, 0x01)]
    starts = {1: 1, 2: 1}
    pats = [_pat((0x60, 1, 0, 0), (KEYOFF, 0, SETWAVE, 0x08),
                 (NO_NOTE, 0, SETSR, 0)),
            _pat((0x60, 2, 0, 0), (KEYOFF, 0, SETWAVE, 0x08),
                 (NO_NOTE, 0, SETSR, 0))]
    return pats, [[0, 1, 0xFF, 0], [0xFF, 0], [0xFF, 0]], entries, starts


def test_a_rest_on_an_instrument_without_vibrato_takes_the_ad_in_the_program():
    pats, tracks, entries, starts = _two_class_song()
    new, rows = RP.rest_park_plan(pats, tracks, entries, starts,
                                  envelope=True, vib=frozenset({2}))
    f1 = len(entries) + 1
    full = f1 + len(RP.REST_PARK_ENV_PROGRAM)
    assert rows[len(entries):] == (list(RP.REST_PARK_ENV_PROGRAM)
                                   + list(RP.REST_PARK_ENV_FULL_PROGRAM))
    assert new[0][4 + 2:4 + 4] == [SETWAVEPTR, full], "instrument 1: full"
    assert new[0][8 + 2:8 + 4] == [0, 0], "the hold row carries nothing"
    assert new[1][4 + 2:4 + 4] == [SETWAVEPTR, f1], "instrument 2: SR + park"
    assert new[1][8 + 2:8 + 4] == [SETAD, 0], "...and the AD on the hold row"


def test_only_the_program_a_rest_takes_is_appended():
    pats, tracks, entries, starts = _two_class_song()
    one = [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    new, rows = RP.rest_park_plan([pats[0]], one, entries, starts,
                                  envelope=True, vib=frozenset({2}))
    assert rows[len(entries):] == list(RP.REST_PARK_ENV_FULL_PROGRAM)
    assert new[0][4 + 2:4 + 4] == [SETWAVEPTR, len(entries) + 1]
    new, rows = RP.rest_park_plan([pats[1]], one, entries, starts,
                                  envelope=True, vib=frozenset({2}))
    assert rows[len(entries):] == list(RP.REST_PARK_ENV_PROGRAM)


def test_a_rest_on_an_unnamed_instrument_keeps_the_hold_row_ad():
    """A pattern entered holding two different instruments (voice 0 holds 1,
    voice 1 holds 2), one of them with vibrato, may be on the vibrato one:
    the layout with no extra `$Fx` row on a tick-N call is the one it gets.
    Had neither vibrato, the third row would cost nothing on either."""
    entries = [(0x41, 0x00), (0xFF, 0x01)]
    pats = [_pat((0x60, 1, 0, 0)), _pat((0x60, 2, 0, 0)),
            _pat((KEYOFF, 0, SETWAVE, 0x08), (NO_NOTE, 0, SETSR, 0))]
    tracks = [[0, 2, 0xFF, 0], [1, 2, 0xFF, 0], [0xFF, 0]]
    new, rows = RP.rest_park_plan(pats, tracks, entries, {1: 1, 2: 1},
                                  envelope=True, vib=frozenset({2}))
    assert rows[len(entries):] == list(RP.REST_PARK_ENV_PROGRAM)
    assert new[2][2:4] == [SETWAVEPTR, len(entries) + 1]
    assert new[2][4 + 2:4 + 4] == [SETAD, 0]
    new, rows = RP.rest_park_plan(pats, tracks, entries, {1: 1, 2: 1},
                                  envelope=True, vib=frozenset())
    assert rows[len(entries):] == list(RP.REST_PARK_ENV_FULL_PROGRAM)


def test_vibrato_instruments_reads_the_speed_table_pointer():
    out = bytearray(1 + 3 * 25)
    out[1 + 1 * 25 + 5] = 3
    out[1 + 2 * 25 + 8] = 0x09
    assert RP.vibrato_instruments(bytes(out), 0, 3) == frozenset({2})
