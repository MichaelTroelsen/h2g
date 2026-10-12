"""A record the player vibrates gets no closing travel at -S2+ either.

Follow-up to test_wave_program_hold_travel.py: that file declined the `$85`
hold's travel for a vibrating record at -S1 only, but `_wave_program_travels`
still emitted it above -S1, so the tail sat on the accumulator where the
player's vibrato re-centres it on the note (Nemesis `$0B09`: -37 0 37 around
the note). Kings_of_the_Beach_intro records 13 and 16 are such records.
"""
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

PORTADOWN, PORTAUP, JUMP = 0xF2, 0xF1, 0xFF


def _entries(name, i, multiplier, budget=80, hold_travel=False):
    from h2g.convert import _detect_tables
    from h2g.goatwriter.wave_program import _wave_program_entries
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                              lambda *a, **k: None)
    got = _wave_program_entries(sid, det, i, [], "gts5", multiplier, budget,
                                hold_travel=hold_travel)
    assert got is not None, (name, i)
    return list(got[0]), list(got[1])


@needs_corpus
@pytest.mark.parametrize("hold_travel", [False, True])
def test_vibrated_record_ends_on_the_note_at_s2(hold_travel):
    left, right = _entries("Kings_of_the_Beach_intro", 16, 2,
                           hold_travel=hold_travel)
    # restore then stop; no portamento between them
    assert left[-1] == JUMP and left[-2] not in (PORTADOWN, PORTAUP)


@needs_corpus
def test_a_record_the_player_does_not_vibrate_keeps_its_travel_at_s2():
    left, _ = _entries("Kings_of_the_Beach_intro", 2, 2)
    assert left[-2] in (PORTADOWN, PORTAUP)
