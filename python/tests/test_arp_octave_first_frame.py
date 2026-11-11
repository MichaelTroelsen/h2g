"""Where a fixed-octave record raises its FIRST octave, above -S1.

`wavetable._wavetable_entries`' plain (unticked) fixed-arp shape at -S{m} was

    [wave, hold, tail+octave, hold+keep, JUMP entry 0]

which raises on frame 1 and every second frame after, whatever the attack
frame's counter reads. The block's counter is global, the init call does not
run the effect, and the octave is up where the counter is odd: a note
attacking on an ODD frame (`fixed_arp_phases` residue 1) gets its first
octave on frame 2, not frame 1. Last_V8_C128_version record 8 (AD $07, -S2,
voice 0) raised on frames 1, 3, 5 on all 149 of its arpeggiated notes where
the original raises on 2, 4, 6 -- PITCH_OCTAVE on 150 of 164 mismatched notes,
`heard.py` instr .931 -> .994 (C:/t/instr-octave-arpeggio-in-note-missing,
-t 180, presets). The ticked shape (`ticked_arp_entries`) already read the
residue; this one did not.

A residue-1 record takes one frame of base ahead of the same cycle:

    [wave, hold, wave, hold, tail+octave, hold+keep, JUMP entry 2]
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from h2g.convert import convert                              # noqa: E402

UP = 0x0C
JUMP = 0xFF


def _calls(rows, start, n):
    """The note offset (0 or UP) the program leaves on each of `n` calls;
    `start` is the 1-based table index of rows[0], which a jump names."""
    out, k, cur = [], 0, 0
    while len(out) < n:
        left, right = rows[k]
        if left == JUMP:
            k = right - start
            continue
        if right != 0x80:
            cur = right
        out.append(cur)
        k += 1
    return out


def _program(song, number):
    wt = song.tables["WTBL"]
    ins = next(i for i in song.instruments if i.number == number)
    out, k = [], ins.wave_ptr - 1
    while True:
        out.append(tuple(wt[k]))
        if wt[k][0] == JUMP:
            break
        k += 1
    return out, ins.wave_ptr


@needs_corpus
def test_last_v8_record_8_raises_its_first_octave_on_frame_2():
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Last_V8_C128_version.sid")
    assert doc["songs"]["Last_V8_C128_version.sid"]["multiplier"] == 2
    song = songview.parse_sng(
        convert(str(CORPUS / "Last_V8_C128_version.sid"),
                log=lambda m: None, **opts))
    ins = next(i for i in song.instruments if i.ad == 0x07)
    rows, start = _program(song, ins.number)
    # residue 1: the head is one base frame longer, then the loop is entered
    # a frame later (entry 2), not at entry 0
    assert len(rows) == 7 and rows[-1][1] == start + 2, rows
    calls = _calls(rows, start, 16)
    # 2 calls a frame; the original raises on frames 2, 4, 6, 8 (`0 0 1 0 1
    # 0 1` from the attack, tests/test_arp_octave.py's Last_V8 reading)
    frames = [calls[2 * f + 1] for f in range(8)]
    assert [f == UP for f in frames] == [False, False, True, False,
                                         True, False, True, False], frames
    # and the two calls of a frame agree, or a sample of either reads a half
    assert all(calls[2 * f] == calls[2 * f + 1] for f in range(8)), calls
