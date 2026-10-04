"""The classic clear gate reads the RECORDS' routing mask, not the voices.

`h2g.goatwriter.filters._classic_clearing_instruments`. The classic player's
filter block ends `LDA resctl,Y / STA $D417`, so the voice the filter hears is
the low nibble of whatever record is playing -- record-owned, as the clear
is. The gate is: the union of the routed records' bits 0-2 names exactly one
voice, and an enabled-unrouted record named on ANY voice clears.

The synthetic tests build the three inputs the gate reads by hand; the corpus
tests pin the files the mask reading added at v0.5.508 (the files whose sets
`tests/test_filter.py::CLASSIC_CLEARS` already pinned are not repeated).
"""
from types import SimpleNamespace

import pytest

from corpus import needs_corpus
from h2g.detect import FILTER_ENABLE_BIT
from h2g.goatwriter.filters import _classic_clearing_instruments

STRIDE = 8
BASE = 2            # instr_base: GT instrument = record + 2


def _inputs(records, voices):
    """records: [(resctl, enabled)], voices: [[record, ...] per voice 0-2].

    Record i's resctl at 8i, its step at 8i+1, its status byte at 8i+4.
    Each voice gets one pattern naming its records in order."""
    data = bytearray(STRIDE * (len(records) + 1))
    for i, (resctl, enabled) in enumerate(records):
        data[STRIDE * i] = resctl
        data[STRIDE * i + 4] = FILTER_ENABLE_BIT if enabled else 0
    sid = SimpleNamespace(data=bytes(data))
    det = SimpleNamespace(filter=SimpleNamespace(offset=0, status=4),
                          instr_used=len(records) + 1, instr_stride=STRIDE)
    patterns, tracks = [], []
    for named in voices:
        pat = []
        for rec in named:
            pat += [0x30, rec + BASE, 0, 0]
        pat += [0xFF, 0, 0, 0]
        tracks.append([len(patterns)])
        patterns.append(pat)
    return sid, det, tracks, patterns, BASE


def _gate(records, voices):
    return _classic_clearing_instruments(*_inputs(records, voices))


ROUTE_V0, ROUTE_V1, ROUTE_V2, CLEAR = 0xF1, 0xF2, 0xF4, 0xF0


def test_a_routed_record_played_on_two_voices_routes_one():
    """Deep_Strike's shape: record 0 ($F1) is named on voices 0 AND 1, and
    routes only voice 0 wherever it plays. The voice-naming gate saw two
    filtering voices and refused; the mask names one."""
    got = _gate([(ROUTE_V0, True), (CLEAR, True)], [[0, 1], [0], []])
    assert got == {1}


def test_the_clear_fires_from_a_voice_the_filter_does_not_hear():
    """Nemesis_the_Warlock's shape: voice 1 routes ($F2), the clear is played
    on voice 2 only. The player's write of $00 is the record's, whoever
    plays it; the ORIGINAL clears there (frame 13162 of 900 s)."""
    got = _gate([(ROUTE_V1, True), (CLEAR, True)], [[], [0], [1]])
    assert got == {1}


def test_a_clear_shared_between_voices_still_fires():
    """Food_Feud's shape: clears 1 and 2 are each played on two voices."""
    got = _gate([(ROUTE_V1, True), (CLEAR, True), (CLEAR, True)],
                [[1], [0, 1, 2], [2]])
    assert got == {1, 2}


def test_two_records_routing_two_different_voices_refuse():
    """The union, not any one record: $F1 | $F2 names voices 0 and 1."""
    assert _gate([(ROUTE_V0, True), (ROUTE_V1, True), (CLEAR, True)],
                 [[0], [1], [2]]) == set()


def test_one_record_routing_two_voices_refuses():
    """Lightforce's $F3: a single record naming two voices."""
    assert _gate([(0xF3, True), (CLEAR, True)], [[0], [1], []]) == set()


def test_the_external_input_bit_is_not_a_voice():
    """Bit 3 routes the EXT input: $F9 still routes exactly voice 0."""
    assert _gate([(0xF9, True), (CLEAR, True)], [[0], [1], []]) == {1}


def test_a_clear_named_on_no_voice_is_not_emitted():
    """Pandora's 14: enabled, unrouted, and never in an orderlist."""
    assert _gate([(ROUTE_V2, True), (CLEAR, True), (CLEAR, True)],
                 [[], [], [0, 1]]) == {1}


def test_a_disabled_record_is_neither_routing_nor_clearing():
    """Status bit $20 clear: the player skips the block entirely, so a
    disabled $F1 contributes no voice and a disabled $00 writes nothing."""
    assert _gate([(ROUTE_V2, True), (ROUTE_V0, False), (CLEAR, False),
                  (CLEAR, True)], [[1], [2], [0, 3]]) == {3}


# The files the mask reading added, under shipped presets (v0.5.508, -t 180,
# filtered frames ours old -> new / original): Deep_Strike 8823 -> 2048 /
# 2048, Nineteen 8416 -> 8018 / 8016. Auf_Wiedersehen_Monty's record 14 is
# never struck in 900 s on either side: its bytes move and no register does.
MASK_CLEARS = {
    "Deep_Strike": {1},
    "Nineteen": {14},
    "Auf_Wiedersehen_Monty": {14},
}


@needs_corpus
@pytest.mark.parametrize("stem", sorted(MASK_CLEARS))
def test_the_mask_gate_fires_on_exactly_the_measured_records(stem, monkeypatch):
    from test_filter import _emitter_inputs
    sid, det, tracks, patterns, instr_base = _emitter_inputs(stem, monkeypatch)
    assert det.filter is not None and det.ilv_filter is None
    got = _classic_clearing_instruments(sid, det, tracks, patterns, instr_base)
    assert got == MASK_CLEARS[stem], (stem, got)
    # And the reason: the routed records' union names one voice.
    mask = 0
    for i in range(det.instr_used - 1):
        st = det.filter.status + i * det.instr_stride
        rc = det.filter.offset + i * det.instr_stride
        if rc + 1 < len(sid.data) and sid.data[st] & FILTER_ENABLE_BIT:
            mask |= sid.data[rc] & 0x07
    assert mask in (1, 2, 4), (stem, hex(mask))

