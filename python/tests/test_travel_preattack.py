"""`travel` ignores register writes before a voice's first gate-on.

Commodore_64_Music_Examples' packed player writes $0640, $FFF8, $F999, ... to
$D400/$D401 on all three voices from frame 2, while the waveform register is
still 0 and no voice has been gated: 79,300 of the 112,800 units by which
`travel` read 1.36x there (1.114x with them dropped from both sides; v0.5.674,
-t 180, historical). Nothing has sounded yet, so none of it is pitch travel.
"""
import pathlib
import sys

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity  # noqa: E402

_DOTS = "|  ....  ... ..  .. .... ... "


def _dump(*voice0_cells: tuple[int, str]) -> str:
    rows = []
    for frame, cell in voice0_cells:
        rows.append(f"|{frame:6d} | {cell} {_DOTS}{_DOTS}| .... .. ... . |")
    return "\n".join(rows)


# frames 2-4: freq writes with no waveform and no attack (a small swing, under
# the note-change cutoff); frame 8: the first attack; 12 and 13: two printed
# bends of 16 each.
LATE_START = _dump(
    (0, "0000  ... ..  .. .... ..."),
    (2, "0640  ... ..  .. .... ..."),
    (3, "0680  ... ..  .. .... ..."),
    (4, "0640  ... ..  .. .... ..."),
    (8, "1000  C-4 41  41 0000 800"),
    (12, "1010 (+ 0010) .. .... ..."),
    (13, "1020 (+ 0010) .. .... ..."),
)

# the same, started at frame 0: nothing precedes the first attack.
NO_PREAMBLE = _dump(
    (0, "1000  C-4 41  41 0000 800"),
    (4, "1010 (+ 0010) .. .... ..."),
    (5, "1020 (+ 0010) .. .... ..."),
)


def _voice(text: str):
    return list(fidelity.parse_dump(text))[0]


def test_writes_before_the_first_attack_are_not_travel():
    v = _voice(LATE_START)
    assert v.attack_frames[0] == 8
    assert fidelity.within_note_travel(v) == 32


def test_the_same_bends_without_a_preamble_read_the_same():
    assert fidelity.within_note_travel(_voice(NO_PREAMBLE)) == 32


def test_a_voice_with_no_attack_keeps_its_travel():
    v = _voice(_dump(
        (0, "0640  ... ..  .. .... ..."),
        (3, "0680  ... ..  .. .... ..."),
    ))
    assert not v.attack_frames
    assert fidelity.within_note_travel(v) == 0x40


def test_a_voice_gated_from_frame_zero_keeps_its_travel_before_the_first_attack():
    # sounding (gate bit set at frame 0) before siddump names any note: the
    # swing 1000 -> 1030 -> 1000 is real pitch travel, 2 x 0x30 = 96 units.
    v = _voice(_dump(
        (0, "1000  ... ..  41 0000 800"),
        (4, "1030  ... ..  .. .... ..."),
        (8, "1000  ... ..  .. .... ..."),
        (20, "2000  C-4 41  41 .... ..."),
    ))
    assert v.wf_events[0] == (0, 0x41)
    assert fidelity.within_note_travel(v) == 96
