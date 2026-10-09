"""A slide event entered with the gate open is tied at a pattern boundary too.

Inside a pattern `_build_raw_pattern` ties "a slide event that follows a tied
note": row 0 is `CMD_TONEPORTA 0` (no gate-off, no attack) and the HOLD rows
carry the slide. `_tie_step` -- the same rule at a pattern boundary -- declined
every row 0 whose command column was taken, so a pattern OPENING on a slide
event was struck as a fresh note.

Knucklebusters subtune 0 voice 0 holds one E-5 for 768 frames: pattern $11 ends
on tied notes, then $1F/$21/$1F/$21 open on `E-4` slide-up events whose
note byte carries bit 7 (no instrument start, so the gate stays open and the
original shows no gate edge). The conversion put a gate-off and a fresh attack
at the head of each of those patterns -- 516 attacks on voice 0 against the
original's 493 at -t 600, the 23 extra all `E-4` at 18054, 18102, 18150 and
18198 and the three groups after.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                    # noqa: E402

import h2g.convert                                         # noqa: E402,F401
from h2g.patterns import (CMD_TONEPORTA, GT_NO_NOTE,       # noqa: E402
                          _apply_boundary_ties)

NOTE = 0x64
HOLD = [GT_NO_NOTE, 0x00]


def _slide_pattern(cmd=1, data=0x20, hold_cmd=None, hold_data=None):
    hc = cmd if hold_cmd is None else hold_cmd
    hd = data if hold_data is None else hold_data
    return [NOTE, 0x01, cmd, data,
            *HOLD, hc, hd,
            *HOLD, hc, hd,
            0xFF, 0, 0, 0]


@pytest.mark.parametrize("cmd", [1, 2])
def test_a_slide_event_with_a_hold_row_ties_and_the_hold_row_keeps_the_slide(cmd):
    patterns = [_slide_pattern(cmd)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 1
    assert track == [1] and len(patterns) == 2, "the tie must land on a copy"
    assert patterns[1][:4] == [NOTE, 0x01, CMD_TONEPORTA, 0]
    assert patterns[1][6:8] == [cmd, 0x20] and patterns[1][10:12] == [cmd, 0x20], \
        "the hold rows must keep carrying the slide"
    assert patterns[0] == _slide_pattern(cmd), "the shared pattern was patched"


def test_a_slide_with_no_hold_row_keeps_the_old_reading():
    """`wait` 0: no hold row can carry the slide, as inside the pattern."""
    patterns = [[NOTE, 0x01, 1, 0x20, 0xFF, 0, 0, 0]]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert track == [0] and len(patterns) == 1


def test_a_hold_row_with_a_different_command_is_left_alone():
    patterns = [_slide_pattern(1, 0x20, hold_cmd=2, hold_data=0x20)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert track == [0] and len(patterns) == 1


def test_a_hold_row_with_a_different_step_is_left_alone():
    patterns = [_slide_pattern(1, 0x20, hold_data=0x21)]
    assert _apply_boundary_ties([0], {0: 0}, {0}, patterns, {}) == 0


def test_a_tempo_in_the_command_column_is_still_left_alone():
    patterns = [[NOTE, 0x01, 0x0F, 6, *HOLD, 0x0F, 6, 0xFF, 0, 0, 0]]
    assert _apply_boundary_ties([0], {0: 0}, {0}, patterns, {}) == 0
    assert len(patterns) == 1


@needs_corpus
def test_knucklebusters_voice_0_holds_its_e5():
    """-t 600 trace, v0.5.522: voice 0 attacks 516 -> 493 (the original's)."""
    import fidelity as F
    import songview as S
    from h2g.convert import convert

    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    path = CORPUS / "Knucklebusters.sid"
    blob = convert(str(path), log=lambda m: None,
                   **F._preset_opts(doc, path.name))
    song = S.parse_sng(blob)
    tied_slides = [k for k, p in enumerate(song.patterns)
                   if len(p) >= 8 and p[0] < 0xBC and p[2:4] == [CMD_TONEPORTA, 0]
                   and p[4] == GT_NO_NOTE and p[6] in (1, 2)]
    assert tied_slides, "no pattern opens on a tie with the slide on its hold row"
