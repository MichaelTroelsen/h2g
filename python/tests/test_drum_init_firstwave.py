"""IK+ voice 2: the drum-alone record's init call keeps the gate CLEAR.

The original opens gate and pitch on ONE frame and sounds the bit-$80 drum on
the next (`ctl 01 81 01 00` at f..f+3, `C:/t/ik-plus-sub99-priority/`). Ours
wrote `$01` -- `gate_off_firstwave`'s answer for a record selecting no
waveform, gate ON -- on the init call, a frame before the wavetable's lead
entry writes the pitch, so the drum sounded at f+2.

The firstwave of exactly those records (effect bit $80 under the `sfx` drum,
record waveform `$00`/`$01`) is `$08` when `sfx_drum` is on; everything else
about every instrument record is unchanged.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import FIRSTWAVE_DRUM_INIT, FIRSTWAVE_FREERUN  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _firstwaves(sfx_drum: bool) -> list:
    from h2g.convert import convert
    name = "IK_plus.sid"
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    opts["sfx_drum"] = sfx_drum
    sng = convert(str(CORPUS / name), log=lambda m: None, **opts)
    return [i.firstwave for i in songview.parse_sng(sng).instruments]


@needs_corpus
def test_ik_plus_drum_alone_records_open_the_init_call_gate_clear():
    off, on = _firstwaves(False), _firstwaves(True)
    assert len(off) == len(on) > 0
    changed = [(a, b) for a, b in zip(off, on) if a != b]
    # Records 8 and 9 (`+2 = $01`, effect `$A0`/`$A4`): two, and only them.
    assert len(changed) == 2, changed
    assert set(changed) == {(FIRSTWAVE_FREERUN, FIRSTWAVE_DRUM_INIT)}
    assert FIRSTWAVE_DRUM_INIT & 0x01 == 0, "the init call must not raise the gate"


@needs_corpus
def test_the_option_off_keeps_the_free_running_firstwave():
    off = _firstwaves(False)
    assert off.count(FIRSTWAVE_FREERUN) >= 2
    assert FIRSTWAVE_DRUM_INIT not in off
