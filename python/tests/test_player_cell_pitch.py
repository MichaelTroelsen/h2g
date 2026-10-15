"""The Last V8's pattern byte `$7C` sounds `$6001`, not the clamp's G#7.

Pattern `$12` (`$89F9`) is `BF 0D 7C 7F...`: instrument `$0D` (wave `$17`,
vibrato shift 1, skydive) on the note byte `$7C`. The note fetch has no bound,
so Y = `$F8` reads `$843B + $F8 = $8533/$8534`, which are not table entries but
two scratch variables: `$81BD STA $8533` (the effect byte of the record being
run) and `$8272 STA $8534` (the pulse step `$851A & $E0`). The cell is
written, so `patterns.past_table_notes` declines it; it is written live, so
`SFX_DORMANT_CELLS` cannot take it. `patterns.PLAYER_CELL_PITCH` records the
measurement instead and `patterns.player_cell_notes` applies it; this file
re-derives the record from the player's bytes and from siddump.

Measured (C:/t/last-v8-frame-6407-octave, siddump -w850e,8533,8534 of subtune 0
to 600 s): the byte is fetched by voice 0 at frames 6400, 13312, 20224 and
27136 (the song's 6912-frame loop), `$8533/$8534` are `01 60` at each and the
original writes `$6001`; the C128 rip does the same at 6401 and 13313.
Subtunes 1 and 2 never fetch a byte at or above `$60`. The clamp sounded G#7
(`$DD0E`); the nearest entry of the player's own table to `$6001` is 78
(`$6270`, F#6 +43 cents). Under presets Last_V8 melody 0.99947 -> 1.0,
pitch_jaccard 0.9556 -> 1.0, travel_ratio 1.0945 -> 0.8667.
"""
import pathlib
import sys
from dataclasses import replace

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity  # noqa: E402
from h2g import patterns  # noqa: E402
from h2g.detect import detect  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

RIPS = [pytest.param("Last_V8.sid", "The Last V8", 6400, id="c64"),
        pytest.param("Last_V8_C128_version.sid",
                     "The Last V8 (C128 version)", 6401, id="c128")]

BYTE = 0x7C
CELL = 0x8533
WRITERS = {0x81BD, 0x8272}
GRAMMAR = dict(slides=True, status_bit6=True)
CLAMP = 0x60 + 0x5C
NEAREST = 78
SIDDUMP_RT = pathlib.Path(fidelity.SIDDUMP_RT)


def _load(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, log=lambda m: None)


def _at(sid, addr, n):
    o = sid.to_offset(addr)
    return bytes(sid.data[o:o + n])


def _patched(sid, at, blob):
    data = bytearray(sid.data)
    data[at:at + len(blob)] = blob
    return replace(sid, data=bytes(data))


@needs_corpus
@pytest.mark.parametrize("name,psid,first", RIPS)
def test_the_byte_lands_on_the_scratch_variables_past_the_table(
        name, psid, first):
    sid, det = _load(name)
    ft = det.freq_table
    assert sid.name == psid
    assert (ft.addr, ft.length) == (0x843B, 96)
    assert ft.addr + 2 * BYTE == CELL
    # The writers: `STA $8533` at $81BD (the record's effect byte) and
    # `STA $8534` at $8272 (the pulse step, `AND #$E0` before the `ADC`).
    assert patterns.cell_writer_sites(sid, CELL) == WRITERS
    assert _at(sid, 0x81BD, 3) == bytes.fromhex("8D3385")
    assert _at(sid, 0x8272, 3) == bytes.fromhex("8D3485")
    assert _at(sid, 0x826D, 8) == bytes.fromhex("AD1A85" "29E0" "8D3485")
    # The fetch: `ASL / TAY / LDA $843B,Y`, with the `$8538` transpose test
    # in front of it (negative: the fetch is plain).
    assert _at(sid, 0x8100, 10) == bytes.fromhex(
        "0A" "A8" "AD3885" "1021" "B93B84")
    # The pattern: instrument $0D on $7C, then 63-tick holds.
    assert _at(sid, 0x89F9, 11) == bytes.fromhex("BF0D7C7F7F7F7F7F7F7FFF")
    assert patterns.player_cell_notes(sid, det) == {BYTE: NEAREST}


@needs_corpus
@pytest.mark.parametrize("name,psid,first", RIPS)
def test_the_static_rules_decline_it_so_only_the_record_moves_it(
        name, psid, first):
    sid, det = _load(name)
    assert BYTE not in patterns.past_table_notes(sid, det)
    assert BYTE not in patterns.past_table_rests(sid, det)
    assert BYTE not in patterns.sfx_dormant_notes(sid, det)
    assert patterns.PLAYER_CELL_PITCH[sid.name][BYTE] == (0x6001, WRITERS)


@needs_corpus
def test_the_record_is_declined_when_the_image_disagrees():
    sid, det = _load("Last_V8.sid")
    assert patterns.player_cell_notes(sid, det) == {BYTE: NEAREST}
    end = len(sid.data) - 3
    # A writer the measurement did not account for: `STA $8533`.
    assert patterns.player_cell_notes(
        _patched(sid, end, b"\x8D\x33\x85"), det) == {}
    # An indexed one reaching the cell with X = 2: `STA $8531,X`.
    assert patterns.player_cell_notes(
        _patched(sid, end, b"\x9D\x31\x85"), det) == {}
    # A plain store to $8531 cannot reach the cell, and changes nothing.
    assert patterns.player_cell_notes(
        _patched(sid, end, b"\x8D\x31\x85"), det) == {BYTE: NEAREST}
    # A recorded writer gone (`STA $8534` at $8272 turned into a load).
    assert patterns.player_cell_notes(
        _patched(sid, sid.to_offset(0x8272), b"\xAD"), det) == {}
    # The pitch is the record's, not the file's: another tune's name never
    # borrows it.
    assert patterns.player_cell_notes(replace(sid, name="Commando"), det) == {}


@needs_corpus
@pytest.mark.parametrize("name,psid,first", RIPS)
def test_only_pattern_12_row_0_moves_from_g_sharp_7_to_f_sharp_6(
        name, psid, first, monkeypatch):
    sid, det = _load(name)
    real = patterns.player_cell_notes
    moved = {}
    for i in range(det.pattern_used):
        monkeypatch.setattr(patterns, "player_cell_notes", real)
        on = patterns.decode_entry(sid, det, i, **GRAMMAR)
        monkeypatch.setattr(patterns, "player_cell_notes", lambda s, d: {})
        off = patterns.decode_entry(sid, det, i, **GRAMMAR)
        assert (on is None) == (off is None), i
        if on is None:
            continue
        assert len(on) == len(off), i
        for k in range(0, len(on), 4):
            if on[k] != off[k]:
                assert (off[k], on[k]) == (CLAMP, 0x60 + NEAREST), (i, k // 4)
                assert on[k + 1:k + 4] == off[k + 1:k + 4], (i, k // 4)
                moved.setdefault(i, []).append(k // 4)
    assert moved == {0x12: [0]}


@needs_corpus
@pytest.mark.skipif(not SIDDUMP_RT.exists(),
                    reason="tools/siddump-rt not built (see its README)")
@pytest.mark.parametrize("name,psid,first", RIPS)
def test_the_original_sounds_6001_at_each_fetch(name, psid, first):
    # 275 s covers the first two fetches (6400/6401 and 13312/13313): the
    # cell is the same both laps, and the clamp's $DD0E is nowhere.
    tr = fidelity.run_siddump(CORPUS / name, 275, 0, exe=str(SIDDUMP_RT))
    events = dict(tr[0].freq_events)
    assert events[first] == 0x6001
    assert events[first + 6912] == 0x6001
    assert 0xDD0E not in events.values()
