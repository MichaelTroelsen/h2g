"""Pandora `$0C99`'s last slide is a net rise, and the -S1 slide frames carry it.

Opened as pandora-0c99-net-rise-slide by wave-program-slide-frames-0797-family
(figures historical, `-t 180`, presets, siddump; re-measured at 7b18636).

Record 6 of Pandora's wave program is `set $81 $40 / slide $41 $0480 / $0300 /
$0395 / slide $40 $0140 / $0020 / slide $16 $C880 / hold`. The player
subtracts each operand from a 16-bit accumulator, so the sixth slide's
`-$C880` is a RISE of `$3780` and the sum ends at `$D4F5` -- a net rise of
`$2B0B`. The original reads, from the note `$1168`:

    1168 4068 0CE8 09E8 0653 0513 04F3 3C73 3C73 ...

and ours, at -S1, reads the same frames within a semitone's quantisation:

    1168 41B8 0D0A 09C5 0685 052D 04E2 3E08 3E08 ...

The net-rise branch (`_slide_goals`' modular delta) is therefore correct. The
264.7-cent mean error the opening task measured over the instrument is NOT the
branch: 162 of the 168 notes are this shape and read 40 cents mean; the other
six (86% of the summed error) are three tied 4-frame rows followed by a REST,
where the original's interpreter skips the program (`$F72C: LDA $F94B,X / AND
#$40 / BNE`) and holds `09E8` -- inaudibly, the rest zeroes the envelope --
while ours runs the program on to `3E08`. That is `--rest-wave-silence`'s
question (docs/OPTIONS.md), not this one.
"""
import math
import pathlib
import re
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter.primitives import _note_freq  # noqa: E402
from h2g.goatwriter.wave_program import _slide_semitones  # noqa: E402

NOTE = 48                 # the GT note nearest Pandora's $1168
SUMS = [0x0480, 0x0780, 0x0B15, 0x0C55, 0x0C75, 0xD4F5]   # running sums
COUNTS = [-5, -10, -17, -21, -22, +22]


def _target(total: int) -> int:
    s = total & 0xFFFF
    return _note_freq(NOTE) + (-s if s < 0x8000 else 0x10000 - s)


def test_the_net_rise_takes_a_positive_count_each_frame_its_own():
    assert [_slide_semitones({NOTE: 100}, t) for t in SUMS] == COUNTS


def test_the_net_rise_lands_within_a_quarter_tone_of_the_accumulator():
    # the last frame: note $1168 - $D4F5 (mod $10000) is $3C73 in the
    # original; the whole-semitone count stands within 50 cents of it
    k = _slide_semitones({NOTE: 100}, SUMS[-1])
    cents = 1200 * math.log2(_note_freq(NOTE + k) / _target(SUMS[-1]))
    assert k > 0 and abs(cents) < 50, (k, cents)


def test_a_sum_at_8000_is_already_a_rise():
    # the player's subtraction is modular: $8000 is -(-$8000) -- a rise, and
    # $7FFF is a fall that takes the note to or below zero (declined)
    assert _slide_semitones({NOTE: 100}, 0x8000) > 0
    assert _slide_semitones({NOTE: 100}, 0x7FFF) == 0


@needs_corpus
def test_pandora_record_6_carries_the_rise_at_s1():
    from h2g.convert import _detect_tables
    from h2g.goatwriter.wave_program import _wave_program_entries
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / "Pandora.sid")),
                              lambda *a, **k: None)
    speed: list = []
    got = _wave_program_entries(sid, det, 6, speed, "gts5", 1, 60,
                                hold_travel=True, pitches={NOTE: 100})
    assert got is not None
    rights = list(got[1])
    # set, five falling slides, the rising slide, the restore on the same
    # count, the stop -- and no travel entry after it
    assert [r - 0x80 if r & 0x40 else r for r in rights[2:8]] == COUNTS
    assert rights[7] == rights[8] == 0x16 and not speed


@needs_corpus
def test_the_player_skips_the_program_on_a_rest_row():
    # The residual error on `$0C99` is the rest, not the slide: the
    # interpreter's gate reads the row's status bit 6 (`$F94B,X AND #$40`)
    # before its own program flag. Pinned on the bytes so a retraction of
    # this reading has to touch the test.
    data = (CORPUS / "Pandora.sid").read_bytes()
    assert re.search(rb"\xBD\x4B\xF9\x29\x40\xD0.\xAD\xA1\xF9\x29\x01\xF0",
                     data, re.DOTALL)
