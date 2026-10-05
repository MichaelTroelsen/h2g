"""Crazy_Comets' `$7F` sounds the constant `$2003` its SFX-only cell holds.

The note fetch `$50E5 ASL / TAY / LDA $540F,Y` has no bound, so the pattern
byte `$7F` (Y = `$FE`) reads `$550D`/`$550E`, two bytes past the 96-entry
table: `03 20` in the file, `$2003`, nearest entry 59 (B-4). `past_table_notes`
declines it because absolute writers name the cell -- but every one of them
is the sound-effect engine's, behind a guard music never opens, so during
music the cell keeps its load-time value. `patterns.SFX_DORMANT_CELLS`
records that reading and `patterns.sfx_dormant_notes` applies it; this file
re-derives every claim in the record from the player's bytes, so a different
image cannot silently inherit it.

Measured (C:/t/crazy-comets-7f, 600 s siddump of subtune 0 under presets):
the original writes `$2003` 130 times on voice 0 and 78 on voice 2, none on
voice 1, starting at 10 and 2 note onsets; the conversion sounds `$20DC` (its
B-4) at each, 7 frames later (the tune's startup lag, the same offset as the
note before), and writes the clamp's G#7 `$DD0E` on no frame where it wrote
it 164 + 96 times before.
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

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ARKIV = REPO_ROOT / "arkiv" / "Crazy_Comets.sid"
RIPS = [pytest.param(ARKIV, id="arkiv"),
        pytest.param(CORPUS / "Crazy_Comets.sid", id="corpus",
                     marks=needs_corpus)]

CELL = 0x550D
GUARD = 0x550A
WRITERS = {0x53A1, 0x53AB, 0x551C, 0x553B}
GRAMMAR = dict(slides=True, status_bit6=True)
G_SHARP_7 = 0x60 + 0x5C
B_4 = 0x60 + 59


def _load(path):
    sid = load_sid(str(path))
    return sid, detect(sid, log=lambda m: None)


def _at(sid, addr, n):
    o = sid.to_offset(addr)
    return bytes(sid.data[o:o + n])


def _operand_sites(sid, opcodes, target):
    """Addresses of every `op lo hi` in the file with `op` in `opcodes` and
    operand `target`."""
    d = sid.data
    return {sid.to_address(i) for i in range(len(d) - 2)
            if d[i] in opcodes and (d[i + 1] | d[i + 2] << 8) == target}


def _abs_targets_in(sid, lo, hi):
    """Sites of a `JMP abs` / `JSR abs` whose target is inside lo..hi."""
    d = sid.data
    return {sid.to_address(i) for i in range(len(d) - 2)
            if d[i] in (0x4C, 0x20) and lo <= (d[i + 1] | d[i + 2] << 8) <= hi}


@pytest.mark.parametrize("path", RIPS)
def test_the_byte_lands_on_2003_two_bytes_past_the_table(path):
    sid, det = _load(path)
    ft = det.freq_table
    assert (ft.addr, ft.length) == (0x540F, 96)
    assert ft.addr + 2 * 0x7F == CELL
    assert _at(sid, CELL, 2) == b"\x03\x20"
    # The fetch: `ASL / TAY / LDA $550B / BPL / LDA $540F,Y`, no transpose
    # ($550B is $FF while no effect runs: `$5380 LDY #$FF / LDA $550A / BMI
    # / INY / STY $550B`, so the BPL is not taken during music).
    assert _at(sid, 0x50E5, 10) == bytes.fromhex(
        "0A" "A8" "AD0B55" "1021" "B90F54")
    assert _at(sid, 0x5380, 11) == bytes.fromhex(
        "A0FF" "AD0A55" "3001" "C8" "8C0B55")
    # Nearest entry to $2003 in the player's own table is 59.
    assert patterns.sfx_dormant_notes(sid, det) == {0x7F: 59}


@pytest.mark.parametrize("path", RIPS)
def test_the_static_rule_declines_it_so_only_the_record_moves_it(path):
    sid, det = _load(path)
    assert 0x7F not in patterns.past_table_notes(sid, det)
    assert 0x7F not in patterns.past_table_rests(sid, det)
    assert patterns.cell_writer_sites(sid, CELL) == WRITERS
    assert patterns.SFX_DORMANT_CELLS[sid.name][0x7F] == (GUARD, WRITERS)


@pytest.mark.parametrize("path", RIPS)
def test_every_writer_of_the_cell_is_behind_the_sfx_guard(path):
    sid, _ = _load(path)
    # $5396 BIT $550A / BPL $539C / RTS: bit 7 set means no effect running.
    assert _at(sid, 0x5396, 6) == b"\x2C\x0A\x55\x10\x01\x60"
    # $539C BVC $53A1 / JSR $5514 / DEC $550D / BPL $539B(RTS) /
    # LDA $5513 / AND #$0F / STA $550D -- straight line from the guard.
    assert _at(sid, 0x539C, 18) == bytes.fromhex(
        "5003" "201455" "CE0D55" "10F5" "AD1355" "290F" "8D0D55")
    # No absolute jump or call lands inside that run except the guard's own
    # fall-through, and none into the SFX start past its entry.
    assert not _abs_targets_in(sid, 0x539C, 0x53AD)
    assert not _abs_targets_in(sid, 0x5515, 0x553D)
    # The SFX start $5514 has one caller, the guarded JSR at $539E, and runs
    # straight to $553B STA $550E (no RTS, JMP or branch on the way).
    assert _operand_sites(sid, {0x20, 0x4C}, 0x5514) == {0x539E}
    o = sid.to_offset(0x5514)
    body = sid.data[o:sid.to_offset(0x553E)]
    assert body[0x551C - 0x5514:0x551C - 0x5514 + 3] == b"\x8D\x0D\x55"
    assert body[0x553B - 0x5514:0x553B - 0x5514 + 3] == b"\x8D\x0E\x55"
    pc = 0
    while pc < len(body):
        op = body[pc]
        assert op not in (0x60, 0x4C, 0x6C, 0x40), hex(0x5514 + pc)
        assert op & 0x1F != 0x10, hex(0x5514 + pc)       # no branch
        pc += 1 if op in (0x0A, 0xA8) else (3 if op in (0x8D, 0xAD, 0xB9)
                                            else 2)
    assert pc == len(body)


@pytest.mark.parametrize("path", RIPS)
def test_music_never_opens_the_guard(path):
    sid, _ = _load(path)
    assert sid.data[sid.to_offset(GUARD)] == 0xFF
    # Every writer shape naming the guard byte (none indexed reaches it:
    # `_operand_sites` over all writer opcodes, $5508..$550A).
    for a in (GUARD - 2, GUARD - 1):
        assert not _operand_sites(
            sid, patterns._ABS_INDEXED_WRITER_OPCODES, a), hex(a)
    assert _operand_sites(sid, patterns._ABS_WRITER_OPCODES, GUARD) == {
        0x53BF, 0x5524, 0x60E0}
    # $53BF STX after LDX #$00 ... DEX: writes $FF, closing the guard.
    assert _at(sid, 0x53B6, 2) == b"\xA2\x00"
    assert _at(sid, 0x53BE, 4) == b"\xCA\x8E\x0A\x55"
    # $5524 is inside the guarded SFX start (previous test).
    # $60E0 follows $60DE ORA #$40, reached only through $5009 JMP $60DE,
    # which only init's SFX branch calls: $6100 CMP #$02 / BCS / JMP $5000
    # (music) / SEC / SBC #$02 / JSR $5009.
    assert _at(sid, 0x60DE, 5) == b"\x09\x40\x8D\x0A\x55"
    assert _operand_sites(sid, {0x20, 0x4C}, 0x60DE) == {0x5009}
    callers = _operand_sites(sid, {0x20, 0x4C}, 0x5009)
    if sid.init_addr == 0x5000:
        # The arkiv rip is music only (2 subtunes, init straight into
        # $5000 JMP $60A7, file ends at $60FF): nothing calls $5009 at all.
        assert (sid.subtunes, callers) == (2, set())
    else:
        assert (sid.init_addr, callers) == (0x6100, {0x610A})
        assert _at(sid, 0x6100, 13) == bytes.fromhex(
            "C902" "B003" "4C0050" "38" "E902" "200950")


def _patched(sid, at, blob):
    data = bytearray(sid.data)
    data[at:at + len(blob)] = blob
    return replace(sid, data=bytes(data))


def test_the_record_is_declined_when_the_image_disagrees():
    sid, det = _load(ARKIV)
    assert patterns.sfx_dormant_notes(sid, det) == {0x7F: 59}
    end = len(sid.data) - 3
    # A writer the reading did not account for: `STA $550D`.
    assert patterns.sfx_dormant_notes(
        _patched(sid, end, b"\x8D\x0D\x55"), det) == {}
    # An indexed one reaching the cell with X = 2: `STA $550B,X`.
    assert patterns.sfx_dormant_notes(
        _patched(sid, end, b"\x9D\x0B\x55"), det) == {}
    # A plain store to $550B cannot reach the cell, and changes nothing.
    assert patterns.sfx_dormant_notes(
        _patched(sid, end, b"\x8D\x0B\x55"), det) == {0x7F: 59}
    # A recorded writer gone (`STA $550D` at $53AB turned into a load).
    assert patterns.sfx_dormant_notes(
        _patched(sid, sid.to_offset(0x53AB), b"\xAD"), det) == {}
    # The guard open at load: the SFX engine would run.
    assert patterns.sfx_dormant_notes(
        _patched(sid, sid.to_offset(GUARD), b"\x7F"), det) == {}
    # A zero cell is no pitch to sound.
    assert patterns.sfx_dormant_notes(
        _patched(sid, sid.to_offset(CELL), b"\x00\x00"), det) == {}
    # The pitch is read off the cell, not recorded: $0700 is entry 32.
    assert patterns.sfx_dormant_notes(
        _patched(sid, sid.to_offset(CELL), b"\x00\x07"), det) == {0x7F: 32}
    # Another tune's name never borrows the record.
    assert patterns.sfx_dormant_notes(replace(sid, name="Commando"), det) == {}


@pytest.mark.parametrize("path", RIPS)
def test_only_pattern_1b_row_0_moves_from_g_sharp_7_to_b_4(path, monkeypatch):
    sid, det = _load(path)
    real = patterns.sfx_dormant_notes
    moved = {}
    for i in range(det.pattern_used):
        monkeypatch.setattr(patterns, "sfx_dormant_notes", real)
        on = patterns.decode_entry(sid, det, i, **GRAMMAR)
        monkeypatch.setattr(patterns, "sfx_dormant_notes", lambda s, d: {})
        off = patterns.decode_entry(sid, det, i, **GRAMMAR)
        assert (on is None) == (off is None), i
        if on is None:
            continue
        assert len(on) == len(off), i
        for k in range(0, len(on), 4):
            if on[k] != off[k]:
                assert (off[k], on[k]) == (G_SHARP_7, B_4), (i, k // 4)
                assert on[k + 1:k + 4] == off[k + 1:k + 4], (i, k // 4)
                moved.setdefault(i, []).append(k // 4)
    assert moved == {0x1B: [0]}


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(fidelity.SIDDUMP_RT).exists(),
                    reason="tools/siddump-rt not built (see its README)")
def test_the_original_sounds_2003_during_music():
    # 60 s covers voice 0's first $7F note (frame 2689): the cell is not
    # changed by anything the music runs before it.
    tr = fidelity.run_siddump(CORPUS / "Crazy_Comets.sid", 60, 0,
                              exe=fidelity.SIDDUMP_RT)
    assert (2689, 0x2003) in tr[0].freq_events
    assert not any(x == 0x2003 for _, x in tr[1].freq_events)
