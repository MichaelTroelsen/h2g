"""`call_phase.zp_speed_first_fetch`: the speed counter in zero page
(Samantha_Fox `$E9`) starts at 0, so its first fetch is call 0.

Measured at 9300fa7 (C:/t/samantha-fox-zp-entry-first-fetch, -t 60, presets):
start subtune onset_timing .6576 -> 1.0000, tie_agreement .5487 -> .9077,
wave .9610 -> .9847, gate .9416 -> 1.0; the corpus byte-hash moves that file
alone.
"""
import dataclasses
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables                       # noqa: E402
from h2g.goatwriter import call_phase, constants             # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

NAME = "Samantha_Fox_Strip_Poker.sid"


def _read(name=NAME):
    sid = load_sid(str(CORPUS / name))
    return _detect_tables(sid, lambda *_: None)


def _cell(sid) -> int:
    return constants.SPEED_GATE_ZP.search(sid.data).group(1)[0]


@needs_corpus
def test_samantha_fox_counter_starts_at_zero():
    sid, det = _read()
    assert call_phase.zp_speed_first_fetch(sid, det) == 0


@needs_corpus
@pytest.mark.parametrize("name", ["Spellbound.sid", "Commando.sid", "Thrust.sid"])
def test_files_without_the_zero_page_speed_gate_decline(name):
    sid, det = _read(name)
    if constants.SPEED_GATE_ZP.search(sid.data) is None:
        assert call_phase.zp_speed_first_fetch(sid, det) is None


@needs_corpus
@pytest.mark.parametrize("tail", [
    lambda c: bytes([0x85, c]),         # a second STA zp
    lambda c: bytes([0x8D, c, 0]),      # STA abs
    lambda c: bytes([0xC6, c]),         # a second DEC zp
    lambda c: bytes([0xE6, c]),         # INC zp
], ids=["sta-zp", "sta-abs", "dec-zp", "inc-zp"])
def test_any_other_write_to_the_cell_declines(tail):
    sid, det = _read()
    assert call_phase.zp_speed_first_fetch(sid, det) == 0
    bad = dataclasses.replace(sid, data=sid.data + tail(_cell(sid)))
    assert call_phase.zp_speed_first_fetch(bad, det) is None


@needs_corpus
def test_the_phase_reaches_startup_phase():
    from h2g.goatwriter import tempo
    sid, det = _read()
    speeds = tempo.find_song_speeds(sid, det)
    m = tempo.file_multiplier(sid, speeds, True)
    tempos = [tempo.tempo_command_value(sid, s, speeds, m, True)
              for s in range(max(sid.subtunes, 1))]
    phase = call_phase.startup_phase(sid, det, m, tempos)
    assert (phase.tempo, phase.default, phase.mismatched,
            phase.default_mismatched) == (22, 24, 0, 40)
