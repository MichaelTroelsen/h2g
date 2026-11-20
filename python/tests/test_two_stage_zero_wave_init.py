"""Trans-Atlantic voice 1: a waveform-$00 two-stage record's init call keeps the gate CLEAR.

The original's stage 1 writes gate, waveform and pitch in ONE call: record
`AD$0A SR$F8`, effect `$14`, plays `00 00 00 00 11 11 11 11 11 00` on `$D404`
(`C:/t/wave-program-window-pandora-trans-atlantic/finding.md`). Ours spent the
init call on `FIRSTWAVE_FREERUN` (`$01`, gate ON, no waveform: `gate_off_firstwave`'s
answer for a record selecting none), so every note opened `01:0000` a frame before
the wavetable's lead entry, and the gate rose one frame early.

Under `two_stage` the firstwave of exactly those records (waveform `$00`, effect
bit `$04`, `det.effect_two_stage`) is `FIRSTWAVE_DRUM_INIT`, as the drum-alone
record's is (tests/test_drum_init_firstwave.py).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import (FIRSTWAVE_DRUM_INIT, FIRSTWAVE_FREERUN,  # noqa: E402
                            adopter_firstwave)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAME = "Trans-Atlantic_Balloon_Challenge.sid"


def _records():
    sid = load_sid(str(CORPUS / NAME))
    det = detect(sid, lambda *a, **k: None)
    out = []
    for i in range(det.instr_used):
        base = det.instr_start + i * det.instr_stride
        out.append((sid, det, base, i))
    return out


@needs_corpus
def test_zero_wave_two_stage_records_take_the_gate_clear_init():
    hit = []
    for sid, det, base, i in _records():
        d = sid.data
        if d[base + 2] == 0x00 and d[base + 7] & 0x04:
            hit.append(i)
            assert adopter_firstwave(d, base, det, False, False,
                                     two_stage=True) == FIRSTWAVE_DRUM_INIT
            # Option off: today's byte (record 18 is also the bit-$80 drum
            # record, which `sfx_drum` already gives `$08`).
            assert adopter_firstwave(d, base, det, False, False,
                                     two_stage=False) == FIRSTWAVE_FREERUN
    # Records 3 and 18 (`AD$0A SR$F8` effect $14, and effect $FD).
    assert hit == [3, 18], hit
    assert FIRSTWAVE_DRUM_INIT & 0x01 == 0, "the init call must not raise the gate"


@needs_corpus
def test_the_written_instruments_carry_it():
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, NAME)
    assert opts["two_stage"] and opts["gate_off_firstwave_instruments"]
    got = {}
    for two_stage in (False, True):
        o = dict(opts, two_stage=two_stage)
        sng = convert(str(CORPUS / NAME), log=lambda m: None, **o)
        got[two_stage] = [i.firstwave for i in songview.parse_sng(sng).instruments]
    on = got[True]
    # With the stage on, no record whose name carries effect byte $14 opens
    # `$01`; the record numbers that did under the old byte now read `$08`.
    sng = convert(str(CORPUS / NAME), log=lambda m: None, **opts)
    names = [i.name for i in songview.parse_sng(sng).instruments]
    zero_two_stage = [k for k, n in enumerate(names) if n.endswith("-14")]
    assert zero_two_stage, names
    for k in zero_two_stage:
        assert on[k] == FIRSTWAVE_DRUM_INIT, (k, names[k], on[k])
