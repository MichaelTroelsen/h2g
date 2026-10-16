"""Mega_Apocalypse's slide fetch stores its first operand byte to ZERO PAGE.

`$4B63 STA $D3,X` / `$4B68 STA $4F62,X`: the `STA abs,X`-only
`SLIDE_OPERAND_SHAPE` never matched, so the second operand byte was decoded as
the NOTE and the real note as the next event's header. Hubbard pattern 21
(voice 0, frames 7015-7105) went out as one 22-row noise event where the
original plays `01 21 03 21 01 21 05 21 07 21 47` on instrument $09B7.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus          # noqa: E402
from h2g import detect as D                      # noqa: E402
from h2g import patterns as P                    # noqa: E402
from h2g.convert import _detect_tables           # noqa: E402
from h2g.sidfile import load_sid                 # noqa: E402

MEGA = CORPUS / "Mega_Apocalypse.sid"


def _read():
    sid = load_sid(str(MEGA))
    img, det = _detect_tables(sid, lambda m: None)
    return (img if img is not None else sid), det


@needs_corpus
def test_mega_zero_page_slide_fetch_is_detected_high_first():
    _, det = _read()
    assert det.slide_operand is True
    assert det.slide_high_first is True


@needs_corpus
def test_mega_pattern_21_keeps_its_notes_after_the_slide():
    """Entry 21 is `27 15 | 97 98 46 95 | 41 | 01 21 | 03 21 ...`: after the
    slide event (`97 98 46 95`) and the rest (`41`), the next note is `$21`."""
    sid, det = _read()
    ev = P.decode_entry(sid, det, 21, slides=True)
    notes = [ev[k] for k in range(0, len(ev), 4) if 96 <= ev[k] <= 188]
    assert 0x21 + 96 in notes
    # the old misreading made the duration bytes the notes (97, 99, 101, 103)
    assert not {97, 99, 101, 103} & set(notes)


def test_primary_shape_still_wins_and_the_fallbacks_are_shape_strings():
    """The zero-page spellings are fallbacks: a file the primary shape
    matches never consults them."""
    assert D.SLIDE_OPERAND_SHAPE != D.SLIDE_OPERAND_ZP_SHAPE
    data = bytes(4) + bytes.fromhex("C8B1FA100D9D0010C8B1FA9D0110")
    assert D._find_slide_operand(data) is True
    zp = bytes(4) + bytes.fromhex("C8B1FA100D95D3C8B1FA9D624F")
    assert D._find_slide_operand(zp) is True
    assert D._find_slide_operand(bytes(40)) is False
