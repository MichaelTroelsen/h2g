"""Effect bit $02's EOR dialect (Rasputin $C35A): detected, logged, NOT emitted.

The block EORs `#$18` into the voice's stored waveform every second effect
call on a per-voice counter nothing else writes, so its phase is per note --
and every emission of it measured below the base on Rasputin's `wave` column,
the per-note-correct one included, because of the file's clock drift. The
numbers are at `detect.WAVE_EOR_SHAPE`. These tests pin the reading, its
population and the decline, so emitting it is a decision someone has to make
against that A/B rather than a side effect.
"""
import dataclasses
from pathlib import Path

import pytest

from h2g.detect import (WAVE_EOR_AT_MASK, WAVE_EOR_AT_SAVE, WAVE_EOR_AT_STORE,
                        WAVE_EOR_SHAPE, WaveEor, _find_wave_eor, detect)
from h2g.goatwriter import _wavetable_entries
from h2g.search import search_file
from h2g.sidfile import load_sid

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
RASPUTIN = CORPUS / "Rasputin.sid"

pytestmark = pytest.mark.skipif(not RASPUTIN.is_file(),
                                reason="the corpus is not on this machine")


def _rasputin():
    sid = load_sid(str(RASPUTIN))
    return sid, detect(sid, log=lambda m: None)


def _block_at(sid) -> int:
    """File offset of the block's first byte past the effect-byte load."""
    at = search_file(sid.data, "AD 47 C5 " + WAVE_EOR_SHAPE)
    assert at > 0
    return at + 3


def test_rasputin_carries_the_block_and_its_operands_are_read():
    sid, det = _rasputin()
    assert det.wave_eor == WaveEor(counter=0xC533, reload=0x01, mask=0x18,
                                   wave=0xC518, ticks=0xC512)
    # ...and no other reading of bit $02 claimed the file first.
    assert not det.effect_rise and det.skydive is None
    assert det.wave_alternate < 0 and not det.wave_alternate_noise
    assert det.voice_two_stage_alt < 0
    # The two in-use records that set the bit: 4 (with the drum, bit $01)
    # and 10. Their waveforms toggle $43 <-> $5B and $41 <-> $59.
    recs = {i: sid.data[det.instr_start + 8 * i:det.instr_start + 8 * i + 8]
            for i in range(det.instr_used)}
    bit02 = {i: r for i, r in recs.items() if r[7] & 0x02}
    assert {i: bytes(r).hex() for i, r in bit02.items()} == {
        4: "8001430706000007", 10: "0004410a8900080a"}
    assert [r[2] ^ det.wave_eor.mask for r in bit02.values()] == [0x5B, 0x59]


def test_the_counter_is_written_only_by_the_block():
    """The premise of "free-running": no note fetch, rest or init stores to
    the counter, so its phase at a note is the parity of every effect call
    before it. Every absolute or absolute-X write naming it is inside the
    block (the `DEC` and the reload's `STA`)."""
    sid, det = _rasputin()
    c = det.wave_eor.counter
    lo, hi = c & 0xFF, c >> 8
    writers = {0x8D, 0x9D, 0xCE, 0xDE, 0xEE, 0xFE, 0x8E, 0x8C, 0x99}
    hits = [k - 1 for k in range(1, len(sid.data) - 1)
            if sid.data[k] == lo and sid.data[k + 1] == hi
            and sid.data[k - 1] in writers]
    b = _block_at(sid)
    assert hits == [b + 9, b + 16], [hex(sid.to_address(h)) for h in hits]
    # ...and its bytes in the image start at zero for all three voices.
    o = sid.to_offset(c)
    assert sid.data[o:o + 3] == bytes(3)


def test_a_store_to_another_cell_is_not_the_block():
    sid, det = _rasputin()
    b = _block_at(sid)
    for at in (WAVE_EOR_AT_STORE, WAVE_EOR_AT_SAVE):
        data = bytearray(sid.data)
        data[b + at] ^= 0x01
        other = dataclasses.replace(sid, data=bytes(data))
        assert _find_wave_eor(other, det) is None, at


def test_it_is_a_fallback_behind_every_other_reading_of_the_bit():
    sid, det = _rasputin()
    assert _find_wave_eor(sid, det) is not None
    for change in ({"effect_rise": True}, {"wave_alternate": 5},
                   {"wave_alternate_noise": True},
                   {"voice_two_stage_alt": 5}):
        assert _find_wave_eor(sid, dataclasses.replace(det, **change)) is None, \
            change


def test_the_mask_is_read_from_the_block():
    sid, det = _rasputin()
    b = _block_at(sid)
    data = bytearray(sid.data)
    data[b + WAVE_EOR_AT_MASK] = 0x30
    got = _find_wave_eor(dataclasses.replace(sid, data=bytes(data)), det)
    assert got is not None and got.mask == 0x30


@pytest.mark.parametrize("record,toggled", [(4, 0x5B), (10, 0x59)])
def test_the_block_is_not_emitted(record, toggled):
    """The decline, pinned: neither record's wavetable carries the toggled
    waveform at Rasputin's -S2. Emitting it lowered `wave` on every arm
    measured (`detect.WAVE_EOR_SHAPE`); change this only with a new A/B."""
    sid, det = _rasputin()
    left, _ = _wavetable_entries(sid, det, record, True, "gts5", [], 2,
                                 start=1, budget=40)
    assert toggled not in left


def test_the_population_is_rasputin_only():
    # No `try`: detection raises on none of the 95, and a swallowed error
    # here would read as "not in the population".
    found, seen = [], 0
    for path in sorted(CORPUS.glob("*.sid")):
        seen += 1
        det = detect(load_sid(str(path)), log=lambda m: None)
        if det.wave_eor is not None:
            found.append(path.name)
    assert seen >= 95, seen
    assert found == ["Rasputin.sid"]
