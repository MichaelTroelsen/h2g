"""Mega_Apocalypse records 17-20 are never loaded: all four omissions are right.

test_mega_record17.py pins record 17 (the silent power-on instrument). Records
18, 19 and 20 are NOT empty (`80084138491b0300`, `800811284800000a`,
`800815630000000a`), so the reason the converter omits them has to be that the
player never selects them. Measured, py65 harness (init $5822 with A=subtune,
then the IRQ vector at $FFFE each frame), subtune 0, 20000 frames:

* $C9..$CB (the three voices' instrument index) only ever held 0-17, and the
  instrument load at $4C1C ran for records 0-17 only (records 18, 19, 20: 0
  loads). 17 is the reset value, 0-16 came from patterns;
* every read of the record fields ($53FB+8r .. $5402+8r, and the second block
  $54A3+8r..) was for r <= 17;
* the one `LDA $54A8,Y` that is the zero-page "gate" table read of the
  question, at $4C2F, is Y = $C9,X * 8, so it follows the same index and read
  records 0-17 only. The 33335 reads that landed in record 20's $54A8 bytes
  came from $4B01 / $4B06 -- `LDA $554B,X` / `LDA $554E,X`, the per-voice
  pointer tables, which merely sit just past the 21-record table -- never from
  $4C2F, and never on record 20's gate cell ($5548).

The tests below pin the code facts that make this so, without the 20000-frame
trace: the only two writers of the index, the single record-indexed read of
$54A8, the arithmetic that keeps $554B/$554E away from records 18-20's gate
cells, and the converter's own count of what no pattern names.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus          # noqa: E402
import fidelity as F                             # noqa: E402
import songview                                  # noqa: E402
from h2g import detect as D, sidfile             # noqa: E402
from h2g.convert import convert                  # noqa: E402
from h2g.instrument_drop import named_instruments  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
NAME = "Mega_Apocalypse.sid"
SID = CORPUS / NAME

pytestmark = [needs_corpus,
              pytest.mark.skipif(not PRESETS.exists(),
                                 reason="presets.json absent")]

TABLE = 0x53FB        # record 0 (8 bytes a record, 21 records)
RECORDS = 21
GATE = 0x54A8         # LDA $54A8,Y at $4C2F, Y = record * 8


def _image() -> bytearray:
    """The 64K memory image the RSID file loads: header, then 2-byte load
    address, then the player."""
    raw = SID.read_bytes()
    pay = raw[raw[6] << 8 | raw[7]:]
    load = pay[0] | pay[1] << 8
    mem = bytearray(65536)
    mem[load:load + len(pay) - 2] = pay[2:]
    return mem


def _all(mem: bytearray, needle: bytes) -> list:
    out, at = [], mem.find(needle, 0x800)
    while at != -1:
        out.append(at)
        at = mem.find(needle, at + 1)
    return out


def _opts():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    return F._preset_opts(doc, NAME)


def _convert(**override):
    logs = []
    opts = _opts()
    opts.update(override)
    return convert(str(SID), log=logs.append, **opts), logs


def test_records_18_to_20_are_real_data_not_empty_records():
    mem = _image()
    sid = sidfile.load_sid(str(SID))
    det = D.detect(sid, lambda s: None)
    assert det.instr_stride == 8 and det.instr_used == RECORDS
    rec = [bytes(mem[TABLE + r * 8:TABLE + r * 8 + 8]) for r in range(RECORDS)]
    assert rec[17] == bytes(8)
    assert [r.hex() for r in rec[18:21]] == [
        "80084138491b0300", "800811284800000a", "800815630000000a"]


def test_only_two_stores_write_the_instrument_index():
    mem = _image()
    # STA $C9,X is the one spelling that reaches all three voices' $C9..$CB.
    assert _all(mem, bytes.fromhex("95C9")) == [0x4AC8, 0x4B70]
    # $4AC8: the reset loop, LDA #$11 (record 17) / STA $C9,X / DEX / BPL.
    assert bytes(mem[0x4AC6:0x4ACD]).hex() == "a91195c9ca10e6"
    # $4B70: the pattern-stream path. LDA ($FA),Y / BPL $4B70 / ... STA $C9,X:
    # the value is the stream byte with bit 7 clear, i.e. a pattern names it.
    assert bytes(mem[0x4B5F:0x4B63]).hex() == "b1fa100d"
    assert bytes(mem[0x4B70:0x4B72]).hex() == "95c9"


def test_gate_table_is_read_once_by_record_times_8():
    mem = _image()
    # LDA $C9,X / ASL / ASL / ASL / TAY ... LDA $54A8,Y  (one site)
    assert bytes(mem[0x4C1C:0x4C22]).hex() == "b5c90a0a0aa8"
    assert _all(mem, bytes.fromhex("B9A854")) == [0x4C2F]
    # The other $54A8-region readers: the per-voice pointer tables, indexed by
    # the voice X (0-2), not by a record.
    assert bytes(mem[0x4B00:0x4B03]).hex() == "bd4b55"
    assert bytes(mem[0x4B05:0x4B08]).hex() == "bd4e55"


def test_the_voice_pointer_tables_do_not_touch_gate_cells_of_records_18_20():
    mem = _image()
    cells = {r: GATE + r * 8 for r in (18, 19, 20)}
    assert cells == {18: 0x5538, 19: 0x5540, 20: 0x5548}
    # the bases are the operands of the two reads at $4B00 / $4B05
    base_a = mem[0x4B01] | mem[0x4B02] << 8
    base_b = mem[0x4B06] | mem[0x4B07] << 8
    assert (base_a, base_b) == (0x554B, 0x554E)
    touched = {base_a + x for x in range(3)} | {base_b + x for x in range(3)}
    assert touched.isdisjoint(cells.values())
    # They sit past the 21-record gate block: record 20's bytes end at $554F;
    # the tables start inside it, at byte 3 of that record.
    assert min(touched) - GATE == 20 * 8 + 3


def test_no_pattern_names_records_17_to_20_and_they_are_dropped():
    blob, _ = _convert(drop_unnamed_instruments=False)
    count = len(songview.parse_sng(blob).instruments)
    assert count == RECORDS            # GT n is record n-1: 1..21
    named = named_instruments(blob)
    # GT 18..21 are records 17..20: nothing above GT 17 (record 16) is named.
    assert named <= set(range(1, 18)), sorted(named)
    assert set(range(1, count + 1)) - named - {1} == {18, 19, 20, 21}
    final, logs = _convert()
    assert any("Dropped 4 instrument(s) no pattern names: $12, $13, $14, $15"
               in line for line in logs), logs
    assert len(songview.parse_sng(final).instruments) == 17
