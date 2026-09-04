"""`_count_instruments`' two end conditions, pinned at the seam each owns.

Two independent defects lived in this loop and both are easy to reintroduce,
because each looks like a tidy-up of the other:

  * WAVEFORMS carried only gate-SET waveforms, so a record whose `+2` byte
    selects a waveform with the gate CLEAR terminated the table. Chimera's
    `$10` sits mid-table with ten ordinary records after it -- the table is 19
    records and was read as 8.

  * The end-of-file peek advanced before crediting the record it had just
    validated, so it demanded `stride - 2` more bytes than a record occupies.
    The right question is whether THIS record is complete.

The second is the dangerous one, because the two corpus files whose instrument
table abuts the end of the file want OPPOSITE answers, and a fix that reads the
`+2` byte alone gets one of them right and the other catastrophically wrong --
it emitted a record out of truncated bytes and the conversion died with an
IndexError. The suite was green; the corpus byte-hash is what caught it. So
these tests are built on synthetic tables that reproduce both shapes exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g import detect as D  # noqa: E402

STRIDE = 8


def _table(waveforms, tail=b"", start=0):
    """A stride-8 instrument table whose records carry the given `+2` bytes."""
    out = bytearray()
    for w in waveforms:
        rec = bytearray(STRIDE)
        rec[2] = w
        out += rec
    return bytes(out) + tail


def _count(data, start=0):
    return D._count_instruments(data, start, STRIDE, lambda *a, **k: None)


# ---------------------------------------------------------------- WAVEFORMS

def test_a_gate_clear_waveform_mid_table_does_not_end_the_table():
    # Chimera's shape: $10 at index 8 with ordinary records after it.
    data = _table([0x41, 0x41, 0x41, 0x81, 0x41, 0x41, 0x41, 0x11,
                   0x10, 0x81, 0x11, 0x41], tail=bytes([0, 0, 0x0A, 0, 0, 0, 0, 0]))
    assert _count(data) == 12


def test_every_gate_clear_form_is_accepted():
    for w in (0x10, 0x20, 0x40, 0x80):
        data = _table([0x41, w, 0x41], tail=bytes([0, 0, 0x0A, 0, 0, 0, 0, 0]))
        assert _count(data) == 3, f"${w:02X} terminated the table"


def test_a_genuine_non_waveform_still_ends_the_table():
    # The set must not have been widened into "accept anything".
    data = _table([0x41, 0x41], tail=bytes([0, 0, 0x0A, 0, 0, 0, 0, 0]))
    assert _count(data) == 2


# ------------------------------------------------------- end-of-file rule

def test_a_complete_record_at_the_very_end_of_the_file_is_counted():
    # Confuzion's shape: the last record ends exactly at EOF.
    data = _table([0x41, 0x81, 0x41])
    assert len(data) % STRIDE == 0
    assert _count(data) == 3


def test_a_record_one_byte_short_is_not_counted():
    # Action_Biker's shape: the `+2` byte is readable, the record is not whole.
    data = _table([0x41, 0x81, 0x41])[:-1]
    assert data[2 + 2 * STRIDE] == 0x41, "the third record's +2 byte is still readable"
    assert _count(data) == 2


def test_truncation_is_measured_per_record_not_per_waveform_byte():
    # Every truncation from one byte short up to the whole record must refuse
    # that record and keep the ones before it -- the seam the IndexError came
    # from, swept rather than sampled.
    full = _table([0x41, 0x81, 0x41])
    for missing in range(1, STRIDE + 1):
        assert _count(full[:len(full) - missing]) == 2, f"missing={missing}"


def test_a_start_past_the_end_returns_zero_rather_than_indexing():
    assert _count(_table([0x41]), start=10_000) == 0
