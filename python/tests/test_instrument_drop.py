"""`drop_unnamed_instruments`: no instrument record that no pattern names.

Knucklebusters' source record 27 -- $00 $00, pulse width $000, an EMPTY
wavetable block -- was written as instrument 28 (name prefix `1D:`, which is
record + 2, see goatwriter._write_instruments) and is named by no pattern.
The option drops it and every other such slot, keeps instrument 1 (both
players start every voice on it: gplay.c:62, player.s:621), and renumbers the
instrument columns -- the tempo-duty / phase / drum clones appended after the
source records included.
"""
import json
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus          # noqa: E402
import fidelity as F                             # noqa: E402
from h2g.convert import convert                  # noqa: E402
from h2g.instrument_drop import (                # noqa: E402
    drop_unnamed_instruments, named_instruments)
from songview import parse_sng                   # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
KNUCKLE = "Knucklebusters.sid"
# Record 27's name prefix: `{record + 2:02X}` in _write_instruments.
RECORD_27 = f"{27 + 2:02X}:"


def _quiet(_msg):
    pass


def _presets():
    return json.loads(PRESETS.read_text(encoding="utf-8"))


def _convert(name, **extra):
    opts = F._preset_opts(_presets(), name)
    opts.update(extra)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return convert(str(CORPUS / name), log=_quiet, **opts)


def _rows(song):
    """(pattern, row, instrument) for every non-zero instrument column."""
    for p, body in enumerate(song.patterns):
        for r in range(0, len(body), 4):
            if body[r + 1]:
                yield p, r // 4, body[r + 1]


def _record(song, number):
    i = song.instruments[number - 1]
    return (i.ad, i.sr, i.wave_ptr, i.pulse_ptr, i.filt_ptr, i.vib_ptr,
            i.vib_delay, i.gatetimer, i.firstwave, i.name)


def _assert_same_music(before: bytes, after: bytes):
    """Everything but the dropped slots is the same, row for row."""
    a, b = parse_sng(before), parse_sng(after)
    assert a.tracks == b.tracks
    assert a.tables == b.tables
    assert len(a.patterns) == len(b.patterns)
    assert [len(p) for p in a.patterns] == [len(p) for p in b.patterns]
    for pa, pb in zip(a.patterns, b.patterns):
        for r in range(0, len(pa), 4):
            assert (pa[r], pa[r + 2], pa[r + 3]) == (pb[r], pb[r + 2], pb[r + 3])
            assert (pa[r + 1] == 0) == (pb[r + 1] == 0)
    n = len(a.instruments)
    for (p, r, ins_a), (_, _, ins_b) in zip(_rows(a), _rows(b)):
        if ins_a <= n:
            assert _record(a, ins_a) == _record(b, ins_b), (p, r, ins_a, ins_b)
    # Instrument 1 survives, unnamed or not.
    assert _record(a, 1) == _record(b, 1)
    # Exactly the named records survive, in order.
    named = named_instruments(before)
    kept = [k for k in range(1, n + 1) if k == 1 or k in named]
    assert [_record(a, k) for k in kept] == \
        [_record(b, k) for k in range(1, len(b.instruments) + 1)]


@needs_corpus
def test_knucklebusters_carries_no_instrument_for_record_27():
    off = _convert(KNUCKLE)
    on = _convert(KNUCKLE, drop_unnamed_instruments=True)
    names_off = [i.name for i in parse_sng(off).instruments]
    names_on = [i.name for i in parse_sng(on).instruments]
    # The control: without the option the slot is there and named by nothing.
    assert names_off.index("1D:00-00-00") + 1 == 28
    assert 28 not in named_instruments(off)
    assert not any(n.startswith(RECORD_27) for n in names_on), names_on
    # 29 written, GT 27-29 (records 26-28) named by no pattern.
    assert len(names_off) - len(names_on) == 3
    _assert_same_music(off, on)


@needs_corpus
def test_option_is_the_drop_applied_to_the_finished_bytes():
    off = _convert(KNUCKLE)
    assert _convert(KNUCKLE, drop_unnamed_instruments=True) == \
        drop_unnamed_instruments(off)


@needs_corpus
@pytest.mark.parametrize("name", ["Human_Race.sid", "Hunter_Patrol.sid",
                                  "Sanxion.sid", "Zoids.sid"])
def test_clones_after_the_records_are_renumbered_not_dropped(name):
    """Files whose clones (appended after the source records) sit above a
    dropped record: each clone keeps its bytes and its rows follow it."""
    off = _convert(name)
    on = _convert(name, drop_unnamed_instruments=True)
    a = parse_sng(off)
    assert len(a.instruments) > len(parse_sng(on).instruments)
    _assert_same_music(off, on)


def test_instrument_1_is_kept_and_dangling_stays_dangling():
    """A synthetic GTS5: 4 instruments, patterns name 3 and a dangling $09."""
    blob = bytearray(0x64)
    blob[0:4] = b"GTS5"
    blob += bytes([1, 0, 0, 0, 0, 0, 0])               # 1 subtune, 3 tracks
    blob.append(4)
    for k in range(1, 5):
        blob += bytes([k] * 9) + bytes(16)
    blob += bytes([0, 0, 0, 0])                         # four empty tables
    blob.append(1)
    blob.append(3)
    blob += bytes([0x60, 3, 0, 0, 0x61, 0, 0, 0, 0x62, 9, 0, 0])
    out = drop_unnamed_instruments(bytes(blob))
    song = parse_sng(out)
    assert [i.ad for i in song.instruments] == [1, 3]
    assert song.patterns[0][1::4] == [2, 0, 7]


def test_nothing_to_drop_is_byte_identical():
    blob = bytearray(0x64)
    blob[0:4] = b"GTS2"
    blob += bytes([1, 0, 0, 0, 0, 0, 0])
    blob.append(2)
    blob += bytes(25) * 2
    blob += bytes([0, 0, 0])
    blob += bytes([1, 1, 0x60, 2, 0, 0])
    assert drop_unnamed_instruments(bytes(blob)) == bytes(blob)


def test_commando_fixture_is_why_it_is_off_by_default():
    """The fixture carries instrument 13, named by no pattern: the option
    would move it, which is why it waits for presets.json's `always` block."""
    ref = (REPO / "Commando.sng").read_bytes()
    assert 13 not in named_instruments(ref)
    assert len(parse_sng(drop_unnamed_instruments(ref)).instruments) == \
        len(parse_sng(ref).instruments) - 1
