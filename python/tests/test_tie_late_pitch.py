"""`tie_late_pitch`: the plain wavetable program's third entry at a 3-call row.

A note's own init call runs no wavetable (gplay.c:403-405), so the plain
program's entries 0, 1, 2 play on calls 1, 2, 3 after it -- and at three calls
a row call 3 is the NEXT row's init call. A tie row (`CMD_TONEPORTA 00`) does
not skip the wavetable there, and `cptr->note` is already its new note, so entry
2's `+0` steps the pitch one call before the original's tie lands. Gremlins:
69 of 69 voice-0 ties one tick after their attack read ours +2 frames, the
original +3 (task gremlins-first-pitch-step-early).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import Detection
from h2g.goatwriter import FORMAT_GTS5, _wavetable_entries

KEEP = 0x80       # "no note change" (gplay.c:717-725)


class _FakeSid:
    def __init__(self, effect_byte=0x00, wave=0x41):
        record = bytes([0x00, 0x00, wave, 0x00, 0x00, 0x00, 0x00, effect_byte])
        self.data = bytes(8) + record


def _plain(row_calls, tie_late, multiplier=1, effect_byte=0x00, drum=False):
    det = Detection(instr_start=8, instr_stride=8, effect_drum=drum)
    return _wavetable_entries(_FakeSid(effect_byte), det, 0, True, FORMAT_GTS5,
                              [], multiplier, None, budget=32,
                              row_calls=row_calls, tie_late=tie_late)


def test_off_leaves_the_plain_shape_as_it_was():
    left, right = _plain(3, False)
    assert left == [0x41, 0x41, 0x41, 0xFF, 0xFF]
    assert right == [0, 0, 0, 0, 0]


def test_a_three_call_row_keeps_the_note_on_the_third_call():
    left, right = _plain(3, True)
    assert left == [0x41, 0x41, 0x41, 0xFF, 0xFF]
    assert right == [0, 0, KEEP, 0, 0]


def test_other_row_lengths_are_untouched():
    for calls in (0, 1, 2, 4, 6):
        assert _plain(calls, True) == _plain(calls, False), calls


def test_multispeed_is_untouched():
    assert _plain(3, True, multiplier=2) == _plain(3, False, multiplier=2)


def test_a_record_with_an_effect_keeps_its_own_shape():
    drum = 0x01
    assert (_plain(3, True, effect_byte=drum, drum=True)
            == _plain(3, False, effect_byte=drum, drum=True))
    assert _plain(3, False, effect_byte=drum, drum=True) != _plain(3, False)
