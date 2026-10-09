"""The six `$1003` files resolve their classic vibrato byte, so the two-update
dwell their counter holds reaches the converter (classic-vibrato-period-dwell-
family; figures historical, v0.5.520 base, -t 180, presets).

Mozart's dwell was wired at v0.5.518, but the other six dwelling files
(Go_Go_Dash, Lakers_vs_Celtics, Lion_Heart, Pacific_Coast, Radio_ACE,
Sun_Never_Shines) emitted no classic vibrato at all: their split is

    147B  LDA $1A5B,X / BNE / JMP / STA $1492      ; patch the LDA #imm below
    1491  LDA #imm   / PHA                         ; the split

with no `LDA record+n,Y` in front of it, because the byte comes from a
per-voice cell whose writer is itself a patched `LDA #imm` fed from the
instrument record (`LDA $1B50,X / STA $12FF ... LDA #imm / STA $1A5B,X`), and
is overridden for one event by the pattern command `$86 nn`. The record offset
read two patches back is +5, the same as every other file. The override is not
emitted (35 `$86` in Go_Go_Dash's patterns, 13 in Radio_ACE, 25 in
Sun_Never_Shines, 1 in Pacific_Coast, none in Lakers_vs_Celtics and
Lion_Heart).

Corpus byte-hash under presets: 89 compared, 6 refused in both arms, exactly
these six move; Commando.sng byte-identical. FIDELITY (-t 180, the six plus
Mozart): reversal_ratio Go_Go_Dash 0.018 -> 0.273, Lakers 0.001 -> 0.370,
Lion_Heart 0.556 -> 1.007, Pacific_Coast 0.002 -> 0.119, Radio_ACE 0.000 ->
0.425, Sun_Never_Shines 0.000 -> 0.506; Mozart unmoved.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import h2g.goatwriter.vibrato as vibrato_mod                  # noqa: E402
from h2g.convert import convert                               # noqa: E402
from h2g.detect import (Detection, _find_vibrato_site,        # noqa: E402
                        _patched_split_record_offset, detect)
from h2g.sidfile import load_sid                              # noqa: E402

SIX = ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart", "Pacific_Coast",
       "Radio_ACE", "Sun_Never_Shines")

# --- a synthetic player carrying exactly the spelling -----------------------

BASE = 0x1000


class _Sid:
    """Just what `_patched_split_record_offset` reads: bytes, and a flat
    address <-> index map at $1000."""

    def __init__(self, data):
        self.data = bytes(data)

    def to_address(self, i):
        return BASE + i

    def to_offset(self, a):
        return a - BASE


def _player(record_addr=0x1205, cell=(0x5B, 0x1A), imm_op_of_split=0x21,
            lda_cell=0xBD, bne=0xD0, jmp=0x4C, writer_lda=0xBD):
    d = bytearray(0x300)
    # the split: LDA cell,X / BNE +3 / JMP / STA split-operand / ... LDA #0 / PHA
    d[0x10:0x13] = bytes([lda_cell, *cell])
    d[0x13:0x15] = bytes([bne, 0x03])
    d[0x15:0x18] = bytes([jmp, 0x00, 0x12])
    d[0x18:0x1B] = bytes([0x8D, BASE + imm_op_of_split & 0xFF,
                          (BASE + imm_op_of_split) >> 8])
    d[0x20:0x23] = bytes([0xA9, 0x00, 0x48])                # LDA #imm / PHA
    # the writer: LDA record,X / STA writer-operand ... LDA #imm / STA cell,X
    d[0x40:0x43] = bytes([writer_lda, record_addr & 0xFF, record_addr >> 8])
    d[0x43:0x46] = bytes([0x8D, 0x4B, 0x10])                # operand idx 0x4B
    d[0x4A:0x4C] = bytes([0xA9, 0x00])
    d[0x4C:0x4F] = bytes([0x9D, *cell])
    return _Sid(d)


DET = Detection(instr_start=0x200, instr_stride=16)


def test_the_synthetic_player_reads_the_record_two_patches_back():
    assert _patched_split_record_offset(_player(), DET, 0x22) == 5


@pytest.mark.parametrize("kw", [
    dict(lda_cell=0xB9),                 # LDA abs,Y is not the per-voice cell
    dict(bne=0xF0),                      # not the `BNE +3 / JMP` guard
    dict(jmp=0x20),                      # JSR is not the guard's JMP
    dict(imm_op_of_split=0x30),          # patches something other than the split
    dict(writer_lda=0xB9),               # the writer is not patched from LDA abs,X
    dict(record_addr=0x1100),            # reads below the table: negative offset
    dict(record_addr=0x1240),            # reads past the 16-byte record
])
def test_an_unfamiliar_spelling_reads_nothing(kw):
    assert _patched_split_record_offset(_player(**kw), DET, 0x22) is None


def test_a_split_not_preceded_by_an_immediate_reads_nothing():
    sid = _player()
    data = bytearray(sid.data)
    data[0x20] = 0xA5                    # LDA zp, not LDA #imm
    assert _patched_split_record_offset(_Sid(data), DET, 0x22) is None


# --- the corpus --------------------------------------------------------------

def _detections():
    out = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            out[path.stem] = detect(load_sid(str(path)), lambda *a: None)
        except Exception:                                  # noqa: BLE001
            continue
    return out


@needs_corpus
def test_exactly_the_six_resolve_through_the_patched_split_and_at_plus_5():
    """The rescue is consulted only where the record read found nothing: it
    resolves these six and no other file, and every file the primary read
    resolved still resolves through it (offset unchanged)."""
    via_rescue, via_primary = set(), set()
    for name, det in _detections().items():
        if det.vibrato_offset is None:
            continue
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        site = _find_vibrato_site(sid, det)
        assert site is not None and site[0] == det.vibrato_offset
        if _patched_split_record_offset(sid, det, site[1]) is not None:
            via_rescue.add(name)
        else:
            via_primary.add(name)
    assert via_rescue == set(SIX)
    assert len(via_primary) == 55
    for name in SIX:
        assert _detections_one(name).vibrato_offset == 5


def _detections_one(name):
    return detect(load_sid(str(CORPUS / f"{name}.sid")), lambda *a: None)


@needs_corpus
@pytest.mark.parametrize("name", SIX)
def test_the_six_read_the_dwell_the_census_found(name):
    det = _detections_one(name)
    assert det.vibrato_dwell is True
    assert det.vibrato_shift_extra == 0


def _entry_calls(name):
    seen = []
    real = vibrato_mod._classic_vibrato_entry

    def spy(byte, multiplier, row_calls=0, gate_skip=None, dwell=False,
            depth_extra=0):
        entry = real(byte, multiplier, row_calls, gate_skip=gate_skip,
                     dwell=dwell, depth_extra=depth_extra)
        seen.append((byte, gate_skip, dwell, depth_extra, entry))
        return entry

    vibrato_mod._classic_vibrato_entry = spy
    try:
        convert(str(CORPUS / f"{name}.sid"), log=lambda *a: None,
                fmt="gts5", vibrato=True, effects=True)
    finally:
        vibrato_mod._classic_vibrato_entry = real
    return seen


@needs_corpus
@pytest.mark.parametrize("name", SIX)
def test_the_converter_builds_dwelling_entries_with_no_outer_gate(name):
    seen = _entry_calls(name)
    assert seen, name
    assert {(g, dw, ex) for _, g, dw, ex, _ in seen} == {(None, True, 0)}
    assert any(e is not None for *_, e in seen), name


@needs_corpus
@pytest.mark.parametrize("name, cell", [
    ("Go_Go_Dash", 0x1ACE), ("Lion_Heart", 0x1ACE), ("Pacific_Coast", 0x1ACE),
    ("Radio_ACE", 0x1ACE), ("Sun_Never_Shines", 0x1ACE),
    # Lakers_vs_Celtics keeps a leftover `LDA #$02 / STA $D02C` between the
    # subtraction loop's JMP and the compare ($152B), which the gate shapes
    # skip past.
    ("Lakers_vs_Celtics", 0x1AF6),
])
def test_the_six_read_the_four_frame_age_gate_of_their_loop(name, cell):
    gate = _detections_one(name).vibrato_gate
    assert gate is not None, name
    assert (gate.form, gate.gate, gate.cell) == ("counter", 4, cell)
