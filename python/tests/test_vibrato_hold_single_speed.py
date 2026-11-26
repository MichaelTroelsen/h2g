"""The frame-held vibrato at the player rate (`vibrato_hold` on a multiplier-1 song).

I_Ball packs at `-S1` with rows of 3 calls. The instrument vibrato Goattracker
runs is a continuous effect, and the packed player runs none on tick 0 of a row
(`REALTIMEOPTIMIZATION`, player.s:982-987), so one call in three holds the pitch
where the original's vibrato moves every frame (`15EB 1727 1863 1727 15EB 14AF
1373 14AF`, a step of $13C a frame; ours `15EE 173C 173C 15EE 14A0 14A0 1352`).
`travel` read 0.72x and `depth` 0.82x for that alone: packing with `-R0` (no
tick-0 skip) and an entry that skips the row compensation reads 1.06x on both.

A wavetable command row `$F4 nn` is not an effect and runs on every call, so the
held program of `h2g.vibrato_hold` reaches the original's one-step-a-frame
without touching the packer. It was gated off below a multiplier of 2; that
gate is gone, and the first step is the original's own gate (`counter < 4`)
rather than the instrument vibrato's delay, which counted from a different
call (C:/t/listen-sub99-i-ball).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import vibrato_hold as vh                           # noqa: E402
from h2g.convert import convert                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
STEP = (vh._WAVECMD_VIBRATO, 10)


def run_program(rows, start, calls):
    """Which calls execute a `$F4` row, by gplay.c's wavetable loop: a delay row
    `d` holds `d + 1` calls, any other row one, `$FF` jumps for free."""
    ptr, wavetime, hits = start, 0, []
    for call in range(calls):
        left, right = rows[ptr - 1]
        if left <= 0x0F:
            if left != wavetime:
                wavetime += 1
                continue
        elif left == vh._WAVECMD_VIBRATO:
            hits.append(call)
        wavetime = 0
        ptr += 1
        if rows[ptr - 1][0] == 0xFF:
            ptr = rows[ptr - 1][1]
    return hits


def test_a_one_call_lattice_steps_every_call_from_the_first():
    """Three firstwave rows, then a step on every call: the loop is the step row
    and a jump back to it, and the jump costs no call."""
    events = {0: (0x11, 0x00), 1: (0x11, 0x80), 2: (0x11, 0x80)}
    rows = vh._held_rows(events, 3, STEP, 4, 1, 1)
    assert rows[-1][0] == 0xFF
    hits = run_program(rows, 1, 40)
    assert hits == list(range(4, 40))


def _preset_opts(on):
    doc = json.loads(PRESETS.read_text())
    return dict(fidelity._preset_opts(doc, "I_Ball.sid"), vibrato_hold=on)


def _convert(on):
    lines = []
    blob = convert(str(CORPUS / "I_Ball.sid"), log=lines.append,
                   **_preset_opts(on))
    return songview.parse_sng(blob), lines


@needs_corpus
def test_i_ball_takes_its_vibrato_records_as_held_programs():
    off, _ = _convert(False)
    on, lines = _convert(True)
    assert any("Frame-held vibrato" in m and "every 1 calls" in m
               for m in lines)
    assert [i for i in off.instruments if i.vib_ptr]
    assert not [i for i in on.instruments if i.vib_ptr]
    assert [(i.ad, i.sr) for i in off.instruments] == \
        [(i.ad, i.sr) for i in on.instruments]
    assert off.patterns == on.patterns


@needs_corpus
def test_i_ball_steps_every_call_from_the_original_gate():
    """`$0999`'s held program first steps on call 4 (the gate `counter $E564,X <
    4` is four frames from the note) and on every call after it."""
    on, _ = _convert(True)
    wave = on.tables["WTBL"]
    held = [i for i in on.instruments if i.adsr == "$0999" and i.wave_ptr]
    assert held
    for rec in held:
        hits = run_program(wave, rec.wave_ptr, 60)
        assert hits[0] == 4, (rec.number, hits[:4])
        assert hits == list(range(4, 60)), rec.number
