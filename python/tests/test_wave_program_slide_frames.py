"""The -S1 wave program's slide frames sound the original's offsets.

Opened as wave-program-slide-frames-0797-family by mega-ins03-arp-last-step-hold.
Mega_Apocalypse `$09F9` (GT ins03, `set $81 $30 / slide $10 $0200 / slide $40
$03C0 / set $80 x8 / hold`) reads `note-$0200` then `note-$05C0` on its two
slide frames in the original; at -S1 an opcode is ONE wavetable entry, so
there is no spare call for a portamento beside it
(`_wave_program_travels`) and ours sounded the bare note twice. The right
column can still say a NOTE relative to the pattern's, so the frame is
written as the whole-semitone count that best stands for `note - sum`
(`_slide_semitones`), chosen against the notes the instrument is played at
(`patterns.played_note_weights`).

The same count is the restore's, so the tail stands where the last slide
frame put it instead of jumping back to the note for a frame and then
travelling (Nemesis `0CC8`: 5 reversals in the original, 331 with the
slides and the old restore).
"""
import math
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter.primitives import _note_freq  # noqa: E402
from h2g.goatwriter.wave_program import (  # noqa: E402
    SLIDE_SEMITONE_MAX_CENTS, SLIDE_SEMITONE_SHARE, _slide_semitones)

KEEP, BASE = 0x80, 0x00


def _nearest_semitone(note: int, total: int) -> int:
    """The shift an independent brute force picks for one pitch."""
    goal = _note_freq(note) - total
    return min(range(-48, 49),
               key=lambda k: (abs(math.log2(_note_freq(note + k) / goal))
                              if 0 <= note + k <= 95 else math.inf))


def _entries(name, i, pitches, multiplier=1, hold_travel=True):
    from h2g.convert import _detect_tables
    from h2g.goatwriter.wave_program import _wave_program_entries
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                              lambda *a, **k: None)
    speed: list = []
    got = _wave_program_entries(sid, det, i, speed, "gts5", multiplier, 60,
                                hold_travel=hold_travel, pitches=pitches)
    assert got is not None, (name, i)
    return list(zip(*got)), speed


# -- the choice of count ------------------------------------------------------

@pytest.mark.parametrize("note,total", [(51, 0x200), (51, 0x5C0),
                                        (49, 0x600), (49, 0xC40),
                                        (56, 0x1240), (70, 0x400)])
def test_one_pitch_gets_its_nearest_semitone(note, total):
    got = _slide_semitones({note: 100}, total)
    assert got == _nearest_semitone(note, total) != 0
    # ... and that is within a quarter-tone of the original's pitch
    err = abs(math.log2(_note_freq(note + got) / (_note_freq(note) - total)))
    assert err * 1200 <= 50


def test_mega_09F9_s_two_slide_frames():
    # the bytes the conversion carries: `$7E` is -2, `$7A` is -6
    assert [_slide_semitones({51: 1034}, t) for t in (0x200, 0x5C0)] == [-2, -6]


@pytest.mark.parametrize("pitches,total", [
    (None, 0x200), ({}, 0x200),
    ({51: 100}, 0), ({51: 100}, 0x10000),     # a zero sum is the note itself
    ({51: 0}, 0x200),                         # never played
    ({0: 100}, 0x200),                        # takes the pitch below zero
    ({20: 50, 80: 50}, 0x200),                # no one count stands for both
])
def test_it_declines_where_a_count_would_not_be_the_slide(pitches, total):
    assert _slide_semitones(pitches, total) == 0


def test_a_dominant_pitch_outweighs_its_strays():
    # Mega `$07E7`: 870 plays on note 49 and 128 on note 51
    k = _slide_semitones({49: 870, 51: 128}, 0x600)
    assert k == _nearest_semitone(49, 0x600)


def test_a_split_instrument_is_declined():
    # Nemesis `$08F8`: ~half its plays on a low pitch, the rest on a high
    # one it actually sounds at. The count right for the low half is 390
    # cents wrong for the other (mean error over its notes 31 -> 244 when it
    # was written), so no count stands.
    assert _slide_semitones({48: 49, 70: 51}, 0x4C0) == 0
    assert _slide_semitones({48: 90, 70: 10}, 0x4C0) != 0


def test_the_bounds():
    assert SLIDE_SEMITONE_MAX_CENTS == 100 and SLIDE_SEMITONE_SHARE == 0.75


def test_a_net_rise_takes_a_positive_count():
    # a sum at or above $8000 is a net rise (the player's subtraction is
    # modular): I_Ball `$0797`'s second slide ends above the note
    assert _slide_semitones({50: 100}, 0xFD80) > 0


# -- the distribution -----------------------------------------------------------

def test_played_note_weights_follow_transpose_repeat_and_instrument():
    from h2g.patterns import GT_FIRSTNOTE, played_note_weights
    n = GT_FIRSTNOTE
    # pattern 0: instrument 3 on its first row, a second note inherits it
    # (the column is sticky); pattern 1 names none and inherits across the
    # pattern boundary.
    patterns = [[n + 5, 3, 0, 0, n + 7, 0, 0, 0, 0xFF, 0, 0, 0],
                [n + 9, 0, 0, 0, 0xFF, 0, 0, 0]]
    # orderlist: pattern 0 once, then TRANSUP 2 + REPEAT x3 + pattern 1
    tracks = [[0, 0xF2, 0xD2, 1, 0xFF, 0]]
    got = played_note_weights(tracks, patterns)
    assert got == {3: {5: 1, 7: 1, 11: 3}}, got


# -- the emitted block ----------------------------------------------------------

@needs_corpus
def test_mega_record_2_slide_frames_and_restore():
    got, speed = _entries("Mega_Apocalypse", 2, {51: 1034})
    assert got[:4] == [(0x11, 0x00), (0x81, 0xC2), (0x10, 0x7E), (0x40, 0x7A)]
    # the restore is the last slide's count, and nothing travels after it
    assert got[-2:] == [(0x40, 0x7A), (0xFF, 0x00)] and not speed


@needs_corpus
def test_mega_record_6_has_its_own_counts():
    got, speed = _entries("Mega_Apocalypse", 6, {49: 870, 51: 128})
    assert got[2:4] == [(0x41, 0x79), (0x40, 0x6D)] and got[-2][1] == 0x6D
    assert not speed


@needs_corpus
def test_no_distribution_is_todays_block():
    got, speed = _entries("Mega_Apocalypse", 2, None)
    assert got[2:4] == [(0x10, BASE), (0x40, BASE)]
    # the old restore on the note, then the closing travel
    assert got[-3][1] == BASE and got[-2][0] == 0xF2 and speed


@needs_corpus
def test_the_restore_stays_on_the_note_without_the_closing_travel():
    # a song with a real or gate-off firstwave (`hold_travel` False) keeps
    # the slide frames but not a shifted tail: the next note's init call
    # would open at it
    got, speed = _entries("Mega_Apocalypse", 2, {51: 1034}, hold_travel=False)
    assert got[2:4] == [(0x10, 0x7E), (0x40, 0x7A)]
    assert got[-2:] == [(0x40, BASE), (0xFF, 0x00)] and not speed


@needs_corpus
@pytest.mark.parametrize("multiplier", [2, 3])
def test_above_s1_nothing_changes(multiplier):
    # a portamento rides beside the opcode there (`_wave_program_travels`)
    assert (_entries("Mega_Apocalypse", 2, {51: 1034}, multiplier)
            == _entries("Mega_Apocalypse", 2, None, multiplier))


@needs_corpus
def test_a_declined_deeper_frame_stays_where_the_last_one_put_the_voice():
    # Nemesis `0CC8` at a pitch ($0860) its first two sums leave above zero
    # and its third ($0B15) does not: frames 1-2 are counts, frame 3 onward
    # and the restore KEEP the frequency instead of bouncing up to the note,
    # and no travel follows.
    got, speed = _entries("Nemesis_the_Warlock", 1, {36: 100})
    rights = [r for _l, r in got]
    assert rights[2] not in (BASE, KEEP) and rights[3] not in (BASE, KEEP)
    assert rights[4:-1] == [KEEP] * 5 and not speed
    assert got[-1] == (0xFF, 0x00)


@needs_corpus
def test_a_record_the_player_vibrates_is_left_to_its_chain():
    # Nemesis `0B09` is `_gated_slide_chain`'s: the distribution does not
    # reach it, at any count
    assert (_entries("Nemesis_the_Warlock", 11, {24: 100})
            == _entries("Nemesis_the_Warlock", 11, None))
