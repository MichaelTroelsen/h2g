"""A record setting bit $80 and bit $10 plays the arpeggio between the drum hits.

Nineteen's `$B4` record (task nineteen-voice-2-s-final-450-frames): the
original's six-frame cycle is `C#6 drum, C#5, -, F#5, C#5, -`; the drum-only
loop held the played note on the four frames between hits, so the +5 step
never sounded.
"""
import json
from pathlib import Path

import pytest

import fidelity as F
from h2g.convert import convert
from h2g.goatwriter import _sfx_drum_entries, _sfx_drum_pitch_seq_entries

ROOT = Path(__file__).resolve().parents[2]
NINETEEN = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob/Nineteen.sid")


def test_arpeggio_fills_the_frames_between_hits():
    notes = [0x00, 0x05, 0x00]            # cell value -> semitone step
    phases = (1, 0, 2)                    # cell on frames 1, 2, 3 (and repeating)
    left, right, loop = _sfx_drum_pitch_seq_entries(0x41, 0x48, 6, notes, phases)
    assert loop == 1
    # frame 0 = played note, then 6 frames: drum on 1 and 7, arpeggio between
    assert len(left) == 1 + 6
    assert left[1] == 0x81                            # the hit
    steps = [right[f] for f in range(2, 7)]
    assert steps == [notes[phases[(f - 1) % 3]] for f in range(2, 7)]
    assert 0x05 in steps                                      # the +5 step sounds
    plain_left, plain_right, _ = _sfx_drum_entries(0x41, 0x48, 6)
    assert 0x05 not in plain_right                            # what it replaces


def test_period_not_a_multiple_unrolls_to_the_lcm():
    notes = [0x00, 0x05, 0x00]
    left, right, loop = _sfx_drum_pitch_seq_entries(0x41, 0x48, 4, notes,
                                                    (1, 0, 2))
    assert len(left) == 1 + 12                                # lcm(4, 3)
    assert [i for i, w in enumerate(left) if w == 0x81] == [1, 5, 9]


def test_declined_above_s1_and_on_bad_cell():
    assert _sfx_drum_pitch_seq_entries(0x41, 0x48, 6, [0, 5, 0], (1, 0, 2),
                                       multiplier=3) is None
    assert _sfx_drum_pitch_seq_entries(0x41, 0x48, 6, [0, 5], (1, 0, 2)) is None


@pytest.mark.skipif(not NINETEEN.exists(), reason="corpus file absent")
def test_nineteen_record_carries_the_step():
    from songview import parse_sng
    doc = json.load(open(ROOT / "presets.json"))
    opts = F._preset_opts(doc, "Nineteen.sid")
    s = parse_sng(convert(str(NINETEEN), log=lambda m: None, **opts))
    wt = s.tables["WTBL"]
    ins = next(i for i in s.instruments if i.name.startswith("10:") and i.firstwave)
    at = ins.wave_ptr - 1
    rows = wt[at:at + 8]
    assert rows[:8] == [(0x41, 0x00), (0x81, 0xC9), (0x41, 0x00), (0x41, 0x00),
                        (0x41, 0x05), (0x41, 0x00), (0x41, 0x00), (0xFF, 0x55)]
