"""Extracted table addresses are validated before use.

Signature matching can match a byte sequence that is not really the player's
table-read instruction, in which case the operand it yields points anywhere.
Per-read bounds checks stop that crashing, but on their own they turn a wholly
bogus detection into a structurally valid, musically empty .sng -- a silent
failure that reads as success. Detection rejects such addresses instead.
"""
import pathlib
import struct

import pytest

from h2g.convert import UnsupportedSidError, convert
from h2g.detect import _base_ok, _span_warn, detect
from h2g.sidfile import load_sid

LOAD_ADDR = 0x1000
COMMANDO_SID = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"


def _make_sid(tmp_path, code: bytes, name="probe.sid", songs=1):
    """Minimal PSID v2 with `code` as its data section.

    Matches what the tool assumes: dataOffset 0x7C, header loadAddress 0, and
    the real load address embedded PRG-style in the first two data bytes.
    """
    header = bytearray(0x7C)
    header[0:4] = b"PSID"
    struct.pack_into(">HHH", header, 4, 2, 0x7C, 0)   # version, dataOffset, loadAddress
    struct.pack_into(">H", header, 0x0E, songs)       # songs
    blob = bytes(header) + struct.pack("<H", LOAD_ADDR) + code
    path = tmp_path / name
    path.write_bytes(blob)
    return path


# Mega Apocalypse pattern fingerprint, so=5: the LO operand sits at match+5,
# the HI operand at match+10. $FFFF resolves far past any small file.
def _pattern_sig(operand: int) -> bytes:
    op = struct.pack("<H", operand)
    return (b"\x4C\x00\x00\xA8\xB9" + op + b"\x85\x00\xB9" + op
            + b"\x85\x00\xA9\x00\x95")


class _Log:
    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        self.lines.append(msg)

    def has(self, needle):
        return any(needle in line for line in self.lines)


def test_base_ok_accepts_in_range():
    log = _Log()
    assert _base_ok("X", 0, 10, log) is True
    assert _base_ok("X", 9, 10, log) is True
    assert log.lines == []


@pytest.mark.parametrize("offset", [-1, -207, 10, 22409])
def test_base_ok_rejects_out_of_range(offset):
    log = _Log()
    assert _base_ok("PATTERN LO", offset, 10, log) is False
    assert log.has("PATTERN LO ADDRESS OUT OF RANGE")


def test_span_warn_only_fires_past_eof():
    log = _Log()
    _span_warn("T", 0, 10, 10, log)      # exactly fits
    _span_warn("T", 5, 0, 10, log)       # empty table
    assert log.lines == []
    _span_warn("T", 5, 10, 10, log)      # overruns
    assert log.has("TABLE EXTENDS PAST EOF")


def test_out_of_range_pattern_table_is_rejected(tmp_path):
    sid_path = _make_sid(tmp_path, _pattern_sig(0xFFFF))
    sid = load_sid(str(sid_path))
    log = _Log()
    det = detect(sid, log)

    assert log.has("PATTERN LO ADDRESS OUT OF RANGE")
    assert det.pattern_lo == -1 and det.pattern_hi == -1
    assert det.pattern_used == -1
    assert not det.can_convert


def test_bogus_detection_fails_loudly_rather_than_emitting_empty_sng(tmp_path):
    """The whole point: refuse, don't emit a valid-looking empty file."""
    sid_path = _make_sid(tmp_path, _pattern_sig(0xFFFF))
    with pytest.raises(UnsupportedSidError):
        convert(str(sid_path), log=lambda m: None)


def test_real_file_produces_no_range_warnings():
    """A genuine detection must not trip any of the new guards."""
    sid = load_sid(str(COMMANDO_SID))
    log = _Log()
    det = detect(sid, log)

    assert not log.has("OUT OF RANGE")
    assert not log.has("EXTENDS PAST EOF")
    assert det.can_convert
    for offset in (det.instr_start, det.track_lo, det.track_hi,
                   det.pattern_lo, det.pattern_hi):
        assert 0 <= offset < len(sid.data)
