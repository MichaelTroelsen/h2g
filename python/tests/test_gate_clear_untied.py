"""An UNTIED landing on a gate-clear record, pinned at the bytes it emits.

`gate_clear_records` (patterns.py) and the record's LEGATO firstwave
(instruments.py, `gate_clear_firstwave`) were both measured on Chimera, where
every landing on record 8 is a tie. Nothing in the corpus lands untied on a
gate-clear record, so the LEGATO bit's untied consequence is unmeasured.

What this file pins, and what it does not:

* The event decoder: with no tie carried in (`gate_hold` False, so
  `pending_tie` stays False), a gate-clear record changes nothing -- the
  landing is a plain attack row, exactly as without the rule.
* The instrument: LEGATO is a property of the RECORD, not of any event.
  Chimera's record 8 carries it in the converted song whether or not a given
  landing is tied, so an untied landing on that record gets it too. That is
  the mechanism behind "an untied landing closes a unit late"; the timing
  (3 frames, one tick) is measured in tests/test_gate_clear_untied_timing.py.
"""

import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from h2g.goatwriter.constants import GATETIMER_LEGATO        # noqa: E402
from h2g.patterns import _build_raw_pattern                  # noqa: E402

# Two events, record 0 then record 1 (gate-clear in the synthetic table below),
# then the terminator. Wait 0 throughout.
UNTIED = bytes([0, 0,
                0x80, 0x00, 0x30,
                0x80, 0x01, 0x32,
                0xFF])


def _rows(events):
    return [events[k:k + 4] for k in range(0, len(events) - 4, 4)]


def test_an_untied_landing_on_a_gate_clear_record_is_a_plain_attack():
    # gate_hold False and no no_adsr: nothing carries into the second event,
    # so the gate-clear rule has no tie to cancel and the row must be unchanged.
    plain = _rows(_build_raw_pattern(UNTIED, 2, tie=True, gate_hold=False))
    split = _rows(_build_raw_pattern(UNTIED, 2, tie=True, gate_hold=False,
                                     gate_clear_records=frozenset({1})))
    assert [r[2] for r in split] == [0, 0]
    assert split == plain


@needs_corpus
def test_the_legato_bit_is_on_the_record_so_an_untied_landing_shares_it():
    # Converted Chimera: record 8 is gate-clear and carries LEGATO. Nothing in
    # the instrument writer knows whether a landing on it is tied, so every
    # event on that record -- untied ones included -- is read with the bit.
    import json
    import h2g.convert as C
    import songview
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Chimera.sid")
    song = songview.parse_sng(
        C.convert(str(CORPUS / "Chimera.sid"), log=lambda m: None, **opts))
    rec8 = [i for i in song.instruments if i.gatetimer & GATETIMER_LEGATO]
    assert rec8, "no LEGATO record in converted Chimera"
    assert any(i.firstwave == 0x10 for i in rec8)
