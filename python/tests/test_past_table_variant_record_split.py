"""Which corpus files still send a relative wave step past Goattracker's note
table after `pin_past_table_wave_notes`, under presets -- counted WITHOUT the
pass's own predicate.

The question `past-table-variant-record-split` asked ("12 files' relative wave
steps serve both in-table and past-note-95 notes: split them so each note reads
its own cell") was answered by two earlier changes:
`retarget_mixed_steps` (a pinned copy of the wave program per overflowing note
row, reached by CMD_SETWAVEPTR or an instrument clone) and `_split_patterns`
(a pattern copy per orderlist visit that disagrees).
`test_past_table_split.test_no_note_row_is_left_on_a_layout_dependent_cell`
counts what is left with `_split_key`, which is built on `_pin_target`: break
`_pin_target` and it reads zero for every file. This file counts with the
orderlist walk and the wave program alone, so it cannot be fooled that way:

* a (note row, orderlist visit) is OVERFLOWING when the wave program it
  starts has a relative step (right < $80, left < $F0) whose note + right
  indexes 96 or more;
* every converting file the pass touches, except Commando, has none;
* Commando is HELD by name (`past_table_wave.HELD`, a user decision on the
  byte-exact fixture), so it keeps its rows on the relative step. That test
  fails the day the hold is lifted, because the bytes change.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W                       # noqa: E402
from h2g.goatwriter.appending import _parse_song           # noqa: E402
from test_past_table_split import _corpus_convert          # noqa: E402

_ELEVEN = ["5_Title_Tunes.sid", "Crazy_Comets.sid", "Formula_1_Simulator.sid",
           "Gerry_the_Germ.sid", "Nineteen.sid", "One_Man_and_his_Droid.sid",
           "Star_Paws.sid", "Thing_on_a_Spring.sid",
           "Trans-Atlantic_Balloon_Challenge.sid", "Saboteur_II.sid",
           "Rock_Tells_the_Tale.sid"]
_PINNED_IN_PLACE = ["Human_Race.sid", "Master_of_Magic.sid",
                    "Phantoms_of_the_Asteroid.sid"]


def _overflowing_visits(blob: bytes) -> int:
    """(note row, orderlist visit) pairs that still play a relative wave step
    past the 96-note table. No `_pin_target`, no `_split_key`."""
    song = _parse_song(blob)
    wave = song.tables[0]
    n = 0
    for visits in W._reach(song).values():
        for start, note, _instr in visits:
            for step in W._program(wave, start):
                left, right = wave[step - 1]
                if left < W._WAVE_CMD and right < W._KEEP \
                        and (note + right) & 0x7F >= W.GT_NOTES:
                    n += 1
                    break
    return n


@pytest.mark.parametrize("name", _ELEVEN + _PINNED_IN_PLACE)
def test_no_visit_plays_a_relative_wave_step_past_the_table(name):
    _out, seen = _corpus_convert(name)
    assert seen and any(a != b for b, a, _s, _d in seen), "the pass never edited"
    assert all(_overflowing_visits(a) == 0 for _b, a, _s, _d in seen)


@pytest.mark.parametrize("name", _ELEVEN)
def test_the_unsplit_conversion_does_overflow(name):
    """The measure has power: before the pass the same files read past the
    table, so a zero above is the pass's doing and not the walk's blindness."""
    _out, seen = _corpus_convert(name)
    assert any(_overflowing_visits(b) > 0 for b, _a, _s, _d in seen)


def test_commando_is_held_and_keeps_its_relative_steps():
    _out, seen = _corpus_convert("Commando.sid")
    assert "Commando" in W.HELD
    assert seen and all(a == b for b, a, _s, _d in seen), "the held file was edited"
    assert any(_overflowing_visits(a) > 0 for _b, a, _s, _d in seen)
