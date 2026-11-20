"""A two-stage record whose `+2` is gate alone (`$01`) selects NO waveform.

Tarzan's record 05 (`+2 $01`, effect `$44`) plays the `$15` attack for one
frame and then `$01` -- gate, no waveform -- for the rest of the note. The
second stage went through `_wave_byte(0)` (`$18`, triangle + TEST) and the
caller's `| 1` made it `$19`. That is silent, but `$D404` reads as a selected
triangle: 193 frames of `01` against `19` in subtune 0 (`wave` .9764), plus the
`$18` frames after the gate dropped. `_second_stage_base` returns `$E0` for it,
whose `| 1` is `$E1` -- the packed player writes `$01`
(`primitives._wave_byte`).

Own file: reads no shared fixture. Short-circuit it by making
`_second_stage_base` fall through to `_wave_byte(wave & 0xFE)` for `$01`.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter.constants import WAVE_SILENT_BASE        # noqa: E402
from h2g.goatwriter.primitives import (_second_stage_base,   # noqa: E402
                                       _wave_byte)
from songview import parse_sng                                # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TARZAN = "Tarzan.sid"


def test_gate_alone_second_stage_is_e1_not_the_test_bit_triangle():
    assert _second_stage_base(0x01) | 0x01 == 0xE1
    assert _second_stage_base(0x01) | 0x01 != 0x19


def test_every_other_second_stage_is_unchanged():
    for wave in range(256):
        if wave == 0x01:
            continue
        old = (_wave_byte(wave & 0xFE) if not wave & 0xF0 else wave & 0xFE)
        assert _second_stage_base(wave) == old, hex(wave)
    assert _second_stage_base(0x00) | 0x00 == 0x18      # no gate to carry
    assert _second_stage_base(0x11) | 0x01 == 0x11
    assert _second_stage_base(0x05) | 0x01 == WAVE_SILENT_BASE | 0x05


@needs_corpus
def test_tarzan_record_05_second_stage_selects_no_waveform():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, TARZAN)
    opts["pack"] = False
    song = parse_sng(convert(str(CORPUS / TARZAN), log=lambda m: None, **opts))
    ins = next(i for i in song.instruments if i.name.startswith("07:"))
    wtbl = song.tables["WTBL"]
    prog = []
    at = ins.wave_ptr - 1
    while wtbl[at][0] != 0xFF:
        prog.append(wtbl[at][0])
        at += 1
    assert prog == [0x15, 0xE1], [hex(b) for b in prog]
