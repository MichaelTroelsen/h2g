"""Thrust's instrument 26 holds each octave half for its period at -S3.

Instrument 26 (`1B:00-80-C5`, effect C5, ADSR $0F0B) is a drum+arp record
whose noise tick did not fit: attack `$41`, tail `$40` (gate off), an octave
nibble. Until `gateoff_nibble_arp_entries` (54d3b74) it fell to the -S1
per-call loop `4100 4000 4074 FFF2`, so at -S3 the octave toggled on every
play call. The original's octave record masks its counter with `#$02` and
the counter is gated (`OUTER_GATE_RTS`, reload 9), so a half is 2 counter
steps = 2 * 3 * 10/9 = 20/3 of our calls (`$08A0 DEC $0CD9 / BPL / LDA #$09
/ STA $0CD9 / RTS / INC $0CEA`). Measured at d52a1bf over 400 s
(osplit-minority-at-s3): the original alternates every 2 frames (run lengths
{1:48, 2:810, 3:208, 4:2}), ours every call ({1:7370, 2:155}); osplit read
1822/0 on voice 2 inside the $0F0B window (frames 16435-18992).
Re-measured at v0.5.510 (be0aeb1, presets, `fidelity.py --vice -t 400`,
C:/t/thrust-instr26-percall-octave/r2): osplit 0/0 (blind 1/0), and 2081/0
with `gateoff_nibble_arp_entries` disabled; ours runs {1:58, 2:954, 3:198}
frames ({6:570, 7:576} calls) against the original's unchanged
{1:48, 2:810, 3:208, 4:2}, $0F0B still on voice 2 (frames 16433-18993).

This pins the record END TO END -- `convert` under presets, then the .sng's
own wave program run through gplay's WAVEEXEC (`test_call_rate.wave_timeline`)
-- so a caller that hands the shape the wrong multiplier or gate, or loses the
call site, fails here even where the unit tests of the shape still pass.
The record's six-half exact cycle needs nine entries in a five-entry slot of
a full table, so it takes `gateoff_nibble_arp_budget_pair`'s (7, 6); whether
it should take room from other records is nibble-per-call-shape-above-s1's
open decision, not asserted here.
"""
import json
import pathlib
import sys
from fractions import Fraction

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                                # noqa: E402
import songview                                                # noqa: E402
from h2g.convert import convert                                # noqa: E402
from h2g.detect import detect                                  # noqa: E402
from h2g.goatwriter import (file_multiplier, find_song_speeds,  # noqa: E402
                            nibble_arp_half_cycle)
from h2g.sidfile import load_sid                               # noqa: E402
from test_call_rate import wave_timeline                       # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
OCTAVE_DOWN = 0x74          # wavetable relative note: 12 semitones down


def _runs(xs):
    runs = []
    for x in xs:
        if runs and runs[-1][0] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    return runs


def _program(sng, number):
    """(instrument, wave_ptr, left, right) of instrument `number`'s wave
    program, read up to and including its jump."""
    s = songview.parse_sng(sng)
    ins = next(i for i in s.instruments if i.number == number)
    w = s.tables["WTBL"]
    left, right, p = [], [], ins.wave_ptr
    while True:
        l, r = w[p - 1]
        left.append(l)
        right.append(r)
        if l == 0xFF:
            return ins, ins.wave_ptr, left, right
        p += 1


@needs_corpus
def test_thrust_instr26_alternates_at_the_players_half_not_per_call():
    path = CORPUS / "Thrust.sid"
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(path), log=lambda m: None,
                  **fidelity._preset_opts(doc, "Thrust.sid"))
    ins, ptr, left, right = _program(sng, 26)
    assert ins.name == "1B:00-80-C5" and (ins.ad, ins.sr) == (0x0F, 0x0B)

    sid = load_sid(str(path))
    det = detect(sid, lambda *a, **k: None)
    speeds = find_song_speeds(sid, det)
    m = file_multiplier(sid, speeds, True)
    skip = speeds.skip_for(0)
    assert (m, skip) == (3, 9)
    cyc = nibble_arp_half_cycle(sid, det, 0x0C, m, skip)
    exact = Fraction(sum(cyc), len(cyc))
    assert exact == Fraction(2 * 3 * 10, 9), cyc

    # The jump returns past the attack: the gate is asserted once a note.
    assert left[0] == 0x41 and left[-1] == 0xFF and right[-1] == ptr + 1
    calls = wave_timeline(left, right, first=ptr, calls=40 * 13)
    assert [w for _, w, _ in calls] == [0x41] + [0x40] * (len(calls) - 1)
    runs = _runs([n for _, _, n in calls])[:-1]       # last run is cut off
    assert len(runs) >= 60
    assert {n for n, _ in runs} == {0x00, OCTAVE_DOWN}
    assert runs[0][0] == 0x00
    lengths = [k for _, k in runs]
    # Never per call: every half spans at least two frames' worth of calls.
    assert min(lengths) >= 2 * m, lengths[:12]
    # The pair the five-entry slot allows, base half the longer, and its
    # rate within half a call of the player's 20/3.
    assert lengths == [7, 6] * (len(lengths) // 2) + [7] * (len(lengths) % 2)
    assert abs(Fraction(sum(lengths[:2]), 2) - exact) <= Fraction(1, 2)
