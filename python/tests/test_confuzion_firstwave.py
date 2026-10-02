"""Confuzion's noise voice: `real_firstwave_instruments` against `no_test_restart`.

Confuzion's noise is two records, ADSR `$0300` and `$0900`, which under its
preset (`compact_instruments`, so `lead` 0) are GT instruments 2 and 4, and
both sound on the second voice alone. The file-wide flag and the per-instrument
list were measured against each other on that pair (figures, HISTORICAL, beside
`goatwriter._write_instruments`' firstwave byte). Two structural facts carry
that comparison, and both are pinned here because both are what a reader of
the figures has to take on trust:

* naming EVERY instrument is the file-wide flag, byte for byte, on this file --
  so `no_test_restart`'s melody cost on Confuzion lives in the firstwave byte
  (and its wavetable twin) alone, not in any of the flag's other effects;
* naming 2 and 4 rewrites exactly those two records' firstwave byte, to the
  record's own waveform with the gate on, and not one other byte -- the
  wavetable twin (`_wavetable_layout`'s `instrument_written`) changes nothing
  on this file, which is also why removing it is not a mutation these tests
  can see here (the comment beside it cites ACE_II as where it matters).
"""
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus

import fidelity as F
from h2g import goatwriter as G
from h2g.convert import convert
from songview import parse_sng

PRESETS = Path(__file__).resolve().parents[2] / "presets.json"
NAME = "Confuzion.sid"


def _convert(**extra) -> bytes:
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, NAME)
    opts.update(extra)
    return convert(str(CORPUS / NAME), log=lambda m: None, **opts)


@needs_corpus
def test_naming_every_instrument_is_the_file_wide_flag_on_confuzion():
    every = _convert(real_firstwave_instruments=tuple(range(1, 64)))
    flag = _convert(no_test_restart=True)
    assert every == flag, (
        "on Confuzion no_test_restart's bytes are no longer exactly its "
        "firstwave half: the per-instrument isolation measured beside "
        "_write_instruments no longer isolates the whole flag")
    assert every != _convert(), "the arm moved no byte at all"


@needs_corpus
def test_naming_the_two_noise_records_rewrites_only_their_firstwave():
    raw_base, raw_named = _convert(), _convert(real_firstwave_instruments=(2, 4))
    assert len(raw_base) == len(raw_named)
    moved = [k for k, (a, b) in enumerate(zip(raw_base, raw_named)) if a != b]
    assert len(moved) == 2, (
        f"naming 2 and 4 moved {len(moved)} bytes, not their two firstwave "
        "bytes: the wavetable twin (`written=`) now reacts on this file, so "
        "the measured arm is no longer the firstwave byte alone")
    base, named = parse_sng(raw_base), parse_sng(raw_named)
    adsr = {i.number: (i.ad << 8) | i.sr for i in named.instruments}
    assert (adsr[2], adsr[4]) == (0x0300, 0x0900), (
        "GT 2 and 4 are no longer Confuzion's two noise records -- the "
        "measurement's arm names the wrong instruments")
    for b, n in zip(base.instruments, named.instruments):
        assert b.firstwave == G.FIRSTWAVE_TESTBIT
        if n.number in (2, 4):
            assert n.firstwave == 0x81, (n.number, hex(n.firstwave))
        else:
            assert n.firstwave == G.FIRSTWAVE_TESTBIT, (n.number,
                                                        hex(n.firstwave))
    assert named.patterns == base.patterns
    assert named.tracks == base.tracks
