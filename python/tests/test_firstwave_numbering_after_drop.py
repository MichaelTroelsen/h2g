"""`real_firstwave_instruments` numbers instruments PRE-drop, as written.

`drop_unnamed_instruments` runs last, on the finished bytes, and renumbers
the instrument columns. The preset's instrument numbers are therefore the
numbers the writer assigned, not the ones songview shows afterwards.
5_Title_Tunes is the one shipped preset where the two differ: record 4 is
dropped, so the preset's (1, 2, 3, 5, 6, 8) are (1, 2, 3, 4, 5, 7) in the
file a person opens.
"""
import json
from pathlib import Path

from corpus import CORPUS, needs_corpus

import fidelity as F
from h2g import instrument_drop as D
from h2g.convert import convert
from h2g.goatwriter import FIRSTWAVE_TESTBIT

PRESETS = Path(__file__).resolve().parents[2] / "presets.json"
NAME = "5_Title_Tunes.sid"


def _convert(**extra) -> bytes:
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, NAME)
    opts.update(extra)
    return convert(str(CORPUS / NAME), log=lambda m: None, **opts)


def _real_records(blob: bytes) -> set:
    at = D._layout(blob)[0]
    # Skips tie_restart's legato clones and decoys (gatetimer bit 6, appended past the written records since v0.5.516's adoption):
    # they are copies, not records the drop renumbers.
    rec = lambda k: blob[at + 1 + (k - 1) * D._RECORD_LEN:]
    return {k for k in range(1, blob[at] + 1)
            if rec(k)[8] != FIRSTWAVE_TESTBIT and not rec(k)[7] & 0x40}


@needs_corpus
def test_the_preset_numbers_are_pre_drop_and_land_renumbered():
    blob = _convert()
    # Pre-drop 1, 2, 3, 5, 6, 8 (compact_instruments: lead 0, so 1 is a real
    # record) become 1, 2, 3, 4, 5, 7 once record 4 is dropped.
    assert _real_records(blob) == {1, 2, 3, 4, 5, 7}


@needs_corpus
def test_reading_the_preset_as_post_drop_numbers_would_move_the_bytes():
    shipped = _convert()
    as_post_drop = _convert(real_firstwave_instruments=(1, 2, 3, 4, 5, 7))
    assert shipped != as_post_drop
