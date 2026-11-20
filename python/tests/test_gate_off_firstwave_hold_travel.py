"""`gate_off_firstwave_instruments` keeps the wave program's `$85` closing travel.

`build_sng` passed `hold_travel=False` to the byte-code wave program whenever
`gate_off_firstwave_instruments` was non-empty, on the ground that the next
note's init call opens at the previous tail's pitch (the reason a REAL
firstwave, gate ON, must drop it: Auf_Wiedersehen_Monty melody .99 -> .69).
A gate-OFF firstwave does not name an attack on that frame, and the original
shows the same thing there: its frame before an attack holds the previous
tail's pitch with the gate clear (I_Ball voice 1 frames 35-37,
`O[10/5704 10/5704 10/5704] 11/5000`). So the option dropped the closing
travel's `note + 2` tail -- `10 02` became `10 00` in the drum records' last
wavetable entry, the tail played the pattern's note (5002 where the original
holds 5704) -- and I_Ball's `pitch_cents_agreement` fell .7635 -> .6962 and
`loud_ratio` .9425 -> .9087 in exchange for gate .8146 -> .9963 and wave
.8959 -> .9451 (v0.5.666).

What this pins: the option moves firstwave bytes and no wavetable entry on
I_Ball, a -S1 wave-program file whose preset does not name the option. A real
firstwave (`real_firstwave_instruments`) and `no_test_restart` still switch
the travel off, as before.
"""
import json
import pathlib
import sys
import warnings

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
EVERY = tuple(range(1, 63))


def _opts(name: str) -> dict:
    if not PRESETS.exists():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = fidelity._preset_opts(doc, name)
    opts.pop("gate_off_firstwave_instruments", None)
    return opts


def _wtbl(name: str, **extra) -> list:
    opts = _opts(f"{name}.sid")
    opts.update(extra)
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda _m: None, **opts)
    return songview.parse_sng(sng).tables["WTBL"]


@needs_corpus
def test_gate_off_firstwave_leaves_i_ball_closing_travel_in_place():
    off = _wtbl("I_Ball")
    on = _wtbl("I_Ball", gate_off_firstwave_instruments=EVERY)
    assert on == off
    # the tail the option used to drop: the drum records' last entry is the
    # triangle, gate off, at note +2 (`10 02`), not the pattern's note
    assert (0x10, 0x02) in on


@needs_corpus
def test_a_real_firstwave_still_drops_the_closing_travel():
    base = _wtbl("I_Ball")
    real = _wtbl("I_Ball", real_firstwave_instruments=EVERY)
    assert real != base
