"""Mega_Apocalypse's bit-6 rest zeroes the voice's envelope; its preset must say so.

The player's rest branch (`$4B91`) stores 0 to $D406 and $D405 and drops the
gate, so a note sounding when the rest lands stops dead. Without
`rest_envelope_silence` the KEYOFF alone leaves the record's release nibble to
play out: at 23.06 s the original zeroes voices 2 and 3 (ctrl $00, ADSR $0000)
and is digitally silent until 26.9 s, while ours rings -34 -> -57 dB for the
same 3.5 s (QUEUE dip-mega-apocalypse-17, aud second 23 = .16).
"""
import json
import os
from pathlib import Path

import pytest

from fidelity import _preset_opts
from h2g.convert import convert
from h2g.patterns import CMD_SETSR, GT_KEYOFF
from songview import parse_sng

CORPUS = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"
MEGA = os.path.join(CORPUS, "Mega_Apocalypse.sid")
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"
NAME = "Mega_Apocalypse.sid"


def _silencing_rests(sng: bytes) -> int:
    """Rows that are a KEYOFF carrying `CMD_SETSR $00` -- the spelling of the
    player's zeroed envelope pair on a rest."""
    n = 0
    for p in parse_sng(sng).patterns:
        for i in range(0, len(p) - 3, 4):
            if p[i] == GT_KEYOFF and p[i + 2] == CMD_SETSR and p[i + 3] == 0:
                n += 1
    return n


def test_the_preset_records_rest_envelope_silence():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    assert doc["songs"][NAME].get("rest_envelope_silence") is True
    assert _preset_opts(doc, NAME)["rest_envelope_silence"] is True


@pytest.mark.skipif(not os.path.exists(MEGA), reason="corpus not present")
def test_the_preset_conversion_zeroes_the_envelope_on_its_rests():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, NAME)
    on = _silencing_rests(bytes(convert(MEGA, log=lambda _m: None, **opts)))
    opts["rest_envelope_silence"] = False
    off = _silencing_rests(bytes(convert(MEGA, log=lambda _m: None, **opts)))
    assert off == 0
    assert on >= 1
