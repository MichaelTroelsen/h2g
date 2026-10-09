"""A drum record that also sets the arpeggio bit never sweeps, whatever its nibble.

Warhawk `$0F09` (record 6, `+7 = $05`: drum `$01` + arpeggio `$04`, nibble 0)
and Proteus's identical record are played by the original with a frequency that
never moves: 82 and 100 notes in 60 s, `0F82` on every frame of the note (depth
0), where the conversion swept them `$0300`. The player does not skip the drum
block for them. It runs it -- `$1366` writes the gate-off waveform and
decrements `$15B1,X` -- and then the arpeggio block at `$13CD` runs and writes
`$D400`/`$D401` from the note table **on every frame**, a nibble of zero
included (`$13DB STA $13F5` makes the nibble the operand of the `SBC` at
`$13F4`, so zero subtracts zero; `$140A STA $D401,Y` is unconditional). The
sweep is overwritten before the chip is sampled.

`wavetable._wavetable_entries` cleared `arp` for a zero nibble (nothing to
alternate) and so reached the drum-only shape, sweep included. It now keeps the
drum's noise tick and gate-off, and drops the sweep, for exactly that case.
Figures here are historical (measured at 9d1ff22 + this change); the
assertions are the mechanism.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter import FORMAT_GTS5                          # noqa: E402
from h2g.goatwriter.constants import WAVECMD_PORTADOWN          # noqa: E402
from h2g.goatwriter.wavetable import _drum_entries              # noqa: E402


def _entries(sweep):
    return _drum_entries(0x41, FORMAT_GTS5, [], 7, 43, sustain=0, budget=200,
                         tick_frames=1, note_rows=4, row_calls=16,
                         gate_skip=7, sweep=sweep)


def test_sweep_flag_removes_only_the_sweep():
    swept_l, swept_r = _entries(True)
    flat_l, flat_r = _entries(False)
    assert WAVECMD_PORTADOWN in swept_l
    assert WAVECMD_PORTADOWN not in flat_l
    # The attack, the tick and the gate-off waveform are shared; the flat shape
    # ends in the stop right after the gate-off entry.
    k = flat_l.index(0xFF)
    assert swept_l[:k] == flat_l[:k] and swept_r[:k] == flat_r[:k]
    assert 0x40 in flat_l[:k]            # the record's waveform, gate released


def test_sweep_defaults_on():
    import inspect
    assert inspect.signature(_drum_entries).parameters["sweep"].default is True


def _converted(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng[0] if isinstance(sng, tuple) else sng


def _wave_of(song, ad, sr):
    ins = [i for i in song.instruments
           if (i.ad, i.sr) == (ad, sr) and not i.gatetimer & 0x40]
    assert len(ins) == 1, [(i.number, i.adsr) for i in song.instruments]
    wt = song.tables["WTBL"]
    k = ins[0].wave_ptr - 1
    left = []
    while wt[k][0] != 0xFF:
        left.append(wt[k][0])
        k += 1
    return left


@needs_corpus
@pytest.mark.parametrize("name, ad, sr", [
    ("Warhawk", 0x0F, 0x09), ("Proteus", 0x0F, 0x09), ("Kentilla", 0x0F, 0x0F)])
def test_drum_plus_zero_nibble_arp_record_does_not_sweep(name, ad, sr):
    sys.path.insert(0, str(PYTHON_ROOT))
    import songview
    left = _wave_of(songview.parse_sng(_converted(name)), ad, sr)
    assert WAVECMD_PORTADOWN not in left, left
    assert 0x40 in left, left            # still the drum's gate-off waveform


@needs_corpus
@pytest.mark.parametrize("name, ad, sr", [
    ("Warhawk", 0x0F, 0x0A), ("Proteus", 0x09, 0x0A)])
def test_drum_only_record_still_sweeps(name, ad, sr):
    """Control: the same player's `+7 = $01` record has no arpeggio bit, so
    nothing overwrites its sweep (original: depth `$0300`)."""
    sys.path.insert(0, str(PYTHON_ROOT))
    import songview
    left = _wave_of(songview.parse_sng(_converted(name)), ad, sr)
    assert WAVECMD_PORTADOWN in left, left


@needs_corpus
def test_the_records_are_what_the_docstring_says():
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    for name, ad, sr in (("Warhawk", 0x0F, 0x09), ("Proteus", 0x0F, 0x09)):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = detect(sid, lambda m: None)
        assert det.effect_drum and det.effect_arp and not det.arp_fixed_up
        recs = [bytes(sid.data[det.instr_start + i * det.instr_stride:
                               det.instr_start + (i + 1) * det.instr_stride])
                for i in range(8)]
        hit = [r for r in recs if (r[3], r[4]) == (ad, sr)]
        assert len(hit) == 1 and hit[0][7] == 0x05, hit
