"""The instrument byte's mask is the player's SHIFT COUNT, not a constant.

`patterns.py` masked a pattern's instrument byte with `& 0x7F` for the life of
the project. The players do not mask at all -- they shift: a stride-8 record is
reached with `LDA cell,X / ASL A / ASL A / ASL A / TAX` (Mega_Apocalypse
$4BA2), and three shifts of an eight-bit accumulator discard bits 5, 6 and 7
BEFORE the multiply. So byte `$41` indexes record 1, not 65.

Pinned here as the arithmetic and as its REACH, because a decode path shared by
78 classic files is exactly where a wrong widening does damage quietly.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import convert  # noqa: E402
from h2g.patterns import _instrument_mask  # noqa: E402


def test_the_mask_is_the_bits_the_shift_leaves():
    """Three ASLs keep five bits; four keep four."""
    assert _instrument_mask(8) == 0x1F
    assert _instrument_mask(16) == 0x0F
    # ...and it is derived, not a lookup: any power of two answers.
    assert _instrument_mask(4) == 0x3F
    assert _instrument_mask(32) == 0x07


def test_a_stride_with_no_shift_behind_it_keeps_the_old_constant():
    """A stride that is not a power of two has no ASL sequence to count, so
    the historical 0x7F is kept rather than a mask being invented for it."""
    assert _instrument_mask(7) == 0x7F
    assert _instrument_mask(0) == 0x7F
    assert _instrument_mask(-1) == 0x7F


@needs_corpus
def test_the_mask_changes_mega_apocalypse_and_the_file_still_converts():
    """The reach, pinned on the one file that has a byte the mask discards.

    72 of 78 classic players carry the same three-ASL shape, but only
    Mega_Apocalypse has a pattern byte setting bit $20 or $40 -- so this is
    the single file where `& 0x7F` and `& 0x1F` differ, and the corpus
    byte-hash for the change moved exactly it. Asserted as a DIFFERENCE rather
    than as a fixed sha, so it survives an unrelated emitter change while still
    failing if the mask stops being applied.
    """
    sid = CORPUS / "Mega_Apocalypse.sid"
    if not sid.exists():
        pytest.skip("Mega_Apocalypse.sid absent")
    import h2g.patterns as PA

    live = PA._instrument_mask
    with_derived = convert(str(sid), log=lambda *a, **k: None)
    PA._instrument_mask = lambda stride: 0x7F
    try:
        with_constant = convert(str(sid), log=lambda *a, **k: None)
    finally:
        PA._instrument_mask = live
    assert with_derived != with_constant, (
        "the mask no longer reaches the one corpus file that exercises it")
