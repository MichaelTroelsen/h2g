"""Two `set` opcodes a semitone apart in fewer than a semitone keep their step.

Opened as radio-ace-drum-fall-second-step. Radio_ACE `$1C71` (record 2, the
voice-0 drum, 280 twelve-frame notes) opens `set $81 $30 / slide $41 $00EE /
slide $40 $00D1 / set $80 $4D / set $80 $4C / ...`. The interpreter writes
`$D401` alone, so frames 4 and 5 read `4D4A` and `4C4A` -- a 256-unit fall --
and a wavetable right column names SEMITONES: `$4D00` and `$4C00` are 22 cents
apart and quantise to one note, so the second entry wrote what the first had
and ours stepped once (177 of 465 units a note, voice 0 travel .48). The
second opcode now takes a portamento by the high bytes' difference on its own
entry (`goatwriter.wave_program._subsemitone_set_step`).
"""
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter import wave_program as wp  # noqa: E402
from h2g.goatwriter.constants import (WAVECMD_PORTADOWN,  # noqa: E402
                                      WAVECMD_PORTAUP)
from h2g.goatwriter.primitives import _wave_byte  # noqa: E402

RADIO = "Radio_ACE"


# -- the helper -------------------------------------------------------------------

def test_a_fall_on_the_same_note_is_a_down_portamento_of_the_difference():
    table = []
    got = wp._subsemitone_set_step((0x80, 77, 60), 0x80, 76, 60, table)
    assert got == (WAVECMD_PORTADOWN, 1)
    assert table == [(1, 0)]


def test_a_rise_on_the_same_note_is_an_up_portamento():
    table = []
    assert wp._subsemitone_set_step((0x80, 76, 60), 0x80, 77, 60,
                                    table) == (WAVECMD_PORTAUP, 1)


@pytest.mark.parametrize("prev,wave,arg,note", [
    (None, 0x80, 76, 60),                 # nothing before it
    ((0x80, 77, 60), 0x80, 76, 59),       # a different note: the entry moves
    ((0x80, 77, 60), 0x40, 76, 60),       # a command entry writes no waveform
    ((0x80, 76, 60), 0x80, 76, 60),       # no movement to carry
])
def test_declined_where_the_plain_entry_is_right(prev, wave, arg, note):
    table = []
    assert wp._subsemitone_set_step(prev, wave, arg, note, table) is None
    assert table == []


def test_a_full_speed_table_declines():
    from h2g.goatwriter.constants import GT_MAX_TABLELEN
    table = [(0x7F, i) for i in range(GT_MAX_TABLELEN)]
    assert wp._subsemitone_set_step((0x80, 77, 60), 0x80, 76, 60,
                                    table) is None


def test_short_circuited_it_is_never_taken(monkeypatch):
    monkeypatch.setattr(wp, "SUBSEMITONE_SET_STEP", False)
    assert wp._subsemitone_set_step((0x80, 77, 60), 0x80, 76, 60, []) is None


# -- Radio_ACE record 2 -------------------------------------------------------------

def _record_two():
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{RADIO}.sid")),
                              lambda *a, **k: None)
    table = []
    got = wp._wave_program_entries(sid, det, 2, table, "gts5", 1, 60, start=20,
                                   pitches={43: 280})
    return list(zip(*got)), table


@needs_corpus
def test_radio_ace_drum_falls_a_second_step():
    entries, table = _record_two()
    steps = [(left, right) for left, right in entries
             if left in (WAVECMD_PORTADOWN, WAVECMD_PORTAUP)]
    # frame 5 of the drum, `set $80 $4C` after `set $80 $4D`, 256 units down
    assert (WAVECMD_PORTADOWN, table.index((1, 0)) + 1) in steps
    wave = _wave_byte(0x80)
    # ... on the entry that held the waveform, so the program keeps its length
    assert sum(1 for left, _ in entries if left == wave) >= 1


@needs_corpus
def test_radio_ace_drum_has_one_fewer_waveform_entry_than_the_plain_program(
        monkeypatch):
    with_step, _ = _record_two()
    monkeypatch.setattr(wp, "SUBSEMITONE_SET_STEP", False)
    without, _ = _record_two()
    assert len(with_step) == len(without)
    diff = [(a, b) for a, b in zip(with_step, without) if a != b]
    assert len(diff) == 1
    assert diff[0][0][0] == WAVECMD_PORTADOWN
    assert diff[0][1][0] == _wave_byte(0x80)
