"""Instrument-count clamping and table-length safety.

The clamp is not arbitrary and is NOT bounded by Goattracker's MAX_INSTR (64).
Each instrument costs WAVE_ENTRIES_PER_INSTR wavetable entries and the
wavetable's stored length is one byte bounded by MAX_TABLELEN (255), so only
255//5 == 51 instruments are representable at all.

A raw walk of the records used to run past their end into the parallel attack
array and report tables of 56-58, which is what made the clamp look reachable;
detect bounds the count at the records now, and no corpus file counts over the
ceiling. The clamp remains a real limit for a file that genuinely carries more
than 51 records, and it should say so rather than drop them silently.
"""
import pytest

from h2g.detect import Detection
from h2g.goatwriter import (GT_MAX_INSTR, GT_MAX_TABLELEN, MAX_INSTRUMENTS,
                            MAX_REPRESENTABLE_INSTRUMENTS,
                            PULSE_ENTRIES_PER_INSTR, WAVE_ENTRIES_PER_INSTR,
                            _highest_instrument_referenced, _instruments_used,
                            _pulse_layout, _table_length_byte,
                            _write_instruments, build_sng)
from h2g.sidfile import SidFile


def _fake_sid(n_records: int) -> SidFile:
    """A SidFile whose instrument table holds n_records plausible records."""
    # Each record: pulse_lo, pulse_hi, waveform, ad, sr, b5, b6, arp
    table = bytes([0x00, 0x81, 0x81, 0x05, 0x42, 0x97, 0x00, 0x00]) * n_records
    data = bytes(0x80) + table + bytes(0x80)
    return SidFile(path="fake.sid", data=data, name="n", author="a",
                   released="r", load_addr=0x1000, subtunes=1)


def _fake_det(n_records: int) -> Detection:
    return Detection(instr_start=0x80, instr_used=n_records - 1,
                     track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                     pattern_used=0, read_track_version=0)


def test_clamp_is_within_what_the_wavetable_can_address():
    """Guard the invariant: exceeding it corrupts the wavetable length byte."""
    assert MAX_REPRESENTABLE_INSTRUMENTS == GT_MAX_TABLELEN // WAVE_ENTRIES_PER_INSTR
    assert MAX_INSTRUMENTS <= MAX_REPRESENTABLE_INSTRUMENTS
    # MAX_INSTR is NOT the binding limit -- raising the clamp to it would need
    # more wavetable entries than the format can express.
    assert GT_MAX_INSTR * WAVE_ENTRIES_PER_INSTR > GT_MAX_TABLELEN


def test_table_length_refuses_to_wrap():
    assert _table_length_byte(GT_MAX_TABLELEN, "wave") == GT_MAX_TABLELEN
    assert _table_length_byte(0, "wave") == 0
    with pytest.raises(ValueError, match="MAX_TABLELEN"):
        _table_length_byte(GT_MAX_TABLELEN + 1, "wave")
    # The value that would previously have masked to a plausible short table.
    with pytest.raises(ValueError):
        _table_length_byte(52 * WAVE_ENTRIES_PER_INSTR, "wave")


def test_clamped_tables_still_fit():
    entries = MAX_INSTRUMENTS * WAVE_ENTRIES_PER_INSTR
    assert _table_length_byte(entries, "wave") <= GT_MAX_TABLELEN
    pulse = MAX_INSTRUMENTS * PULSE_ENTRIES_PER_INSTR
    assert _table_length_byte(pulse, "pulse") <= GT_MAX_TABLELEN


def _write(n, log=None):
    """Instruments for a fake table of n records, at the static pulse layout."""
    sid, det = _fake_sid(n), _fake_det(n)
    out = bytearray()
    instr_used = _instruments_used(det, log)
    _, starts = _pulse_layout(sid, det, instr_used, False, 1)
    _write_instruments(out, sid, det, instr_used, starts)
    return out, instr_used


def test_oversized_table_is_clamped_and_reported():
    n = 58  # more records than the wavetable can address
    messages = []
    out, written = _write(n, messages.append)

    assert written == MAX_INSTRUMENTS
    assert out[0] == MAX_INSTRUMENTS, "count byte must match what was written"
    assert len(messages) == 1
    assert str(n) in messages[0] and str(n - MAX_INSTRUMENTS) in messages[0]


def test_table_within_limit_is_not_reported():
    messages = []
    _, written = _write(13, messages.append)
    assert written == 13
    assert messages == []


def test_no_log_means_no_crash():
    assert _write(58)[1] == MAX_INSTRUMENTS


def test_highest_instrument_referenced_reads_column_1():
    # rows are note, instrument, cmd, cmdval
    patterns = [[0x60, 7, 0, 0, 0x61, 3, 0, 0], [0x62, 21, 0, 0]]
    assert _highest_instrument_referenced(patterns) == 21
    assert _highest_instrument_referenced([]) == 0
    assert _highest_instrument_referenced([[]]) == 0


def test_dangling_instrument_reference_is_reported():
    n = 58
    messages = []
    # A pattern selecting instrument 55, which the clamp will not have written.
    patterns = [[0x60, 55, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    build_sng(_fake_sid(n), _fake_det(n), [[0x00, 0xFF, 0x00]] * 3,
              patterns, log=messages.append)
    assert any("DANGLING" in m for m in messages), messages


def test_no_dangling_report_when_all_references_exist():
    messages = []
    patterns = [[0x60, 5, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    build_sng(_fake_sid(13), _fake_det(13), [[0x00, 0xFF, 0x00]] * 3,
              patterns, log=messages.append)
    assert not any("DANGLING" in m for m in messages), messages
