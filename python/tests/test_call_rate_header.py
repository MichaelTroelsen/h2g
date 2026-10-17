"""The packed .sid must call its play routine as often as the original does.

A PSID speed bit means "this subtune runs from CIA 1 timer A", the KERNAL's
$4025 latch unless init writes one: 59.996 Hz on PAL against the VBI's
50.125. gt2reloc drops it (greloc.c:1653-1659), so Confuzion and Human_Race
packed 1.1969x slow -- heard by ear, 2026-10-17 -- while every siddump column
agreed, because siddump calls both sides once a row. `call_rate.py` retimes
the packed bytes; fidelity's `rate` column reads them back.
"""
import json
import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import call_rate as C                                        # noqa: E402
import fidelity as F                                         # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(F.GT2RELOC).exists(), reason="no gt2reloc on this machine")


def packed(songs: int, stub_latch: int | None = None, load: int = 0x1000) -> bytes:
    """A gt2reloc-shaped PSID: header, load address, optional stub, code."""
    h = bytearray(0x7C)
    h[0:4] = b"PSID"
    init = load - C.STUB_LEN if stub_latch is not None else load
    data_load = init
    struct.pack_into(">HHHHHHHI", h, 4, 2, 0x7C, 0, init, load + 3, songs, 1,
                     0xFFFFFFFF if stub_latch is not None else 0)
    body = b""
    if stub_latch is not None:
        s = bytearray(C.STUB)
        s[1], s[6] = stub_latch & 0xFF, stub_latch >> 8
        body = bytes(s)
    return bytes(h) + bytes([data_load & 0xFF, data_load >> 8]) + body + b"\x4C\x00\x20" * 4


def test_vbi_original_keeps_gt2reloc_bytes():
    for b in (packed(3), packed(1, 0x4CC7 // 2)):
        assert C.retime_packed(b, [C.PAL_FRAME] * 3, 1) == b
        assert C.retime_packed(b, [None, None], 2) == b


def test_default_cia_at_s1_sets_only_the_speed_bits():
    b = packed(5)
    got = C.retime_packed(b, [C.CIA_DEFAULT] * 4 + [C.PAL_FRAME], 1)
    assert got[0x12:0x16] == bytes([0, 0, 0, 0x0F])          # Human_Race's $F
    assert got[:0x12] == b[:0x12] and got[0x16:] == b[0x16:]
    assert [C.packed_call_period(got, i) for i in range(5)] == [C.CIA_DEFAULT] * 4 + [C.PAL_FRAME]


def test_multispeed_stub_is_relatched_in_place():
    b = packed(1, 0x4CC7 // 2)                                 # gt2reloc -S2
    assert C.packed_call_period(b, 0) * 2 == C.PAL_FRAME
    got = C.retime_packed(b, [C.CIA_DEFAULT], 2)
    assert len(got) == len(b)
    assert C.packed_call_period(got, 0) == 0x4025 // 2 + 1     # 8211 = 16422/2
    assert C.packed_call_period(got, 0) * 2 == C.CIA_DEFAULT


def test_custom_latch_at_s1_prepends_gt2relocs_stub():
    b = packed(1)
    got = C.retime_packed(b, [0x2663 + 1], 1)
    assert len(got) == len(b) + C.STUB_LEN
    assert int.from_bytes(got[0x0A:0x0C], "big") == 0x1000 - C.STUB_LEN   # init
    assert got[0x7C] | got[0x7D] << 8 == 0x1000 - C.STUB_LEN              # load
    assert got[0x7E + C.STUB_LEN:] == b[0x7E:]                # player follows the stub
    assert C.packed_call_period(got, 0) == 0x2664


def test_mixed_rates_under_one_stub_are_left_for_the_column():
    b = packed(2, 0x4CC7 // 2)
    assert C.retime_packed(b, [C.CIA_DEFAULT, C.PAL_FRAME], 2) == b


@needs_corpus
def test_corpus_header_census():
    """Every corpus PSID with a CIA speed bit, and the rate each reads."""
    cia = {}
    for p in sorted(CORPUS.glob("*.sid")):
        b = p.read_bytes()
        speed = int.from_bytes(b[0x12:0x16], "big")
        if b[:4] == b"PSID" and speed:
            cia[p.name] = speed
    assert cia == {"5_Title_Tunes.sid": 0x4, "Battle_of_Britain.sid": 0x1,
                   "Commodore_64_Music_Examples.sid": 0x7FFF,
                   "Confuzion.sid": 0x1, "Human_Race.sid": 0xF}
    per = lambda n, s: C.original_call_period(CORPUS / n, s)  # noqa: E731
    assert per("Confuzion.sid", 0) == per("Battle_of_Britain.sid", 0) == C.CIA_DEFAULT
    assert [per("Human_Race.sid", s) for s in range(5)] == [C.CIA_DEFAULT] * 4 + [C.PAL_FRAME]
    assert [per("5_Title_Tunes.sid", s) for s in range(5)] == \
        [C.PAL_FRAME, C.PAL_FRAME, C.CIA_DEFAULT, C.PAL_FRAME, C.PAL_FRAME]
    assert per("Commodore_64_Music_Examples.sid", 1) == C.CIA_DEFAULT
    assert per("Commodore_64_Music_Examples.sid", 4) == 0x2664
    assert per("Commando.sid", 0) == C.PAL_FRAME
    assert per("Rikky.sid", 0) is None                                # RSID


@needs_corpus
def test_c64me_timer_write_is_where_init_latch_says():
    """INIT_LATCH's entry was read off these bytes: CMP #$04 / BCC at $08B2,
    then LDA #$26 / LDX #$63 / STX $DC04 / STA $DC05."""
    b = (CORPUS / "Commodore_64_Music_Examples.sid").read_bytes()
    off = int.from_bytes(b[6:8], "big")
    load = b[off] | b[off + 1] << 8
    at = off + 2 + 0x08B2 - load
    assert b[at:at + 4] == bytes([0xC9, 0x04, 0x90, 0x12])
    assert b[at + 10:at + 20] == bytes([0xA9, 0x26, 0xA2, 0x63, 0x8E, 0x04, 0xDC,
                                        0x8D, 0x05, 0xDC])


@needs_corpus
@needs_gt2reloc
@pytest.mark.parametrize("name,mult", [("Confuzion.sid", 1), ("Human_Race.sid", 1),
                                       ("Battle_of_Britain.sid", 2)])
def test_packed_conversion_ticks_at_the_originals_rate(tmp_path, name, mult):
    doc = json.loads((REPO / "presets.json").read_text())
    assert F._preset_multiplier(doc, name) == mult
    sid = CORPUS / name
    sng, _ = F.legalise_restarts(convert(str(sid), log=lambda m: None,
                                         **F._preset_opts(doc, name)))
    plain = F.pack_sid(sng, tmp_path, F.GT2RELOC, mult).read_bytes()
    (tmp_path / "plain.sid").write_bytes(plain)
    fixed = F.pack_sid(sng, tmp_path, F.GT2RELOC, mult, original=sid)
    before = F.call_rate_compare(sid, tmp_path / "plain.sid", 0, 0, mult)
    after = F.call_rate_compare(sid, fixed, 0, 0, mult)
    assert before["call_rate"] == pytest.approx(16422 / 19656)    # 0.8355: slow
    assert F.rate_mismatch(before)
    assert after["call_rate"] == 1.0 and not F.rate_mismatch(after)
    assert after["orig_call_hz"] == after["our_tick_hz"] == 59.996
