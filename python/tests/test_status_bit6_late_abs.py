"""The bit-6 test spelled with an absolute,X first store and a late BIT.

Zoolook $40DA (and eight more corpus files, byte for byte the same fetch):

    40DA  B1 B2     LDA ($B2),Y     ; the status byte
    40DC  9D C7 44  STA $44C7,X
    40DF  8D D6 44  STA $44D6       ; the scratch copy...
    40E2  29 1F     AND #$1F
    40E4  9D C4 44  STA $44C4,X     ; the wait counter
    40E7  ...       8D 18 D4        ; the volume, no pattern read
    40F6  2C D6 44  BIT $44D6       ; ...tested for bit 6 FIRST
    40F9  70 3E     BVS $4139       ; DEC $44D3,X -- the gate mask

`$43C0 LDA $44CA,X / AND $44D3,X / STA $D404,Y` writes the waveform through
that mask every frame, so a `$4x` event is a rest: the gate is off for its
whole length. STATUS_BIT6_SHAPE needs the BIT adjacent and the late spelling
a zero-page first store, so neither read these nine; their rests decoded as
HOLD rows and the note before each rest rang through it. Zoolook voice 3,
`03 n14 | 4B` at frame 716 (-t 90, presets with drum_gate_off): the original
gates off at 724 and is silent from 725 to its next note at 758; ours held
the gate to 756 -- 32 frames sounding over the original's silence.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import detect as D                                  # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter.constants import GT_KEYOFF               # noqa: E402
from h2g.patterns import _build_raw_pattern                  # noqa: E402
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

LATE_ABS = ("Chain_Reaction.sid", "Delta.sid", "Devils_Galop.sid",
            "Formula_1_Simulator.sid", "Master_of_Magic.sid", "Proteus.sid",
            "Thing_on_a_Spring.sid", "Zoids.sid", "Zoolook.sid")


def _quiet(*_a, **_k):
    pass


def _fetch(between: bytes, bit_cell: bytes = b"\xd6\x44") -> bytes:
    # LDA ($B2),Y / STA $44C7,X / STA $44D6 / AND #$1F / STA $44C4,X,
    # then `between`, then BIT cell / BVS
    return (bytes([0x00, 0xB1, 0xB2, 0x9D, 0xC7, 0x44, 0x8D, 0xD6, 0x44,
                   0x29, 0x1F, 0x9D, 0xC4, 0x44]) + between
            + bytes([0x2C]) + bit_cell + bytes([0x70, 0x3E, 0xEA, 0xEA,
                                                0xEA, 0xEA]))


VOLUME = bytes([0xA9, 0x4F, 0x38, 0xED, 0xC0, 0x44, 0xC9, 0x0F, 0x90, 0x02,
                0xA9, 0x0F, 0x8D, 0x18, 0xD4])            # Zoolook $40E7


def test_finds_the_bit_past_the_volume_code():
    assert D._status_bit6_bvs(_fetch(VOLUME)) == 14 + len(VOLUME) + 4


def test_must_test_the_cell_it_stored():
    assert D._status_bit6_bvs(_fetch(VOLUME, b"\xd7\x44")) == -1


def test_refuses_a_bit_after_the_operand_read():
    assert D._status_bit6_bvs(_fetch(bytes([0xC8, 0xB1, 0xB2]))) == -1


def test_refuses_a_bit_beyond_the_window():
    assert D._status_bit6_bvs(
        _fetch(bytes([0xEA]) * (D.STATUS_BIT6_LATE_WINDOW + 1))) == -1


@needs_corpus
def test_the_spelling_reaches_exactly_nine_files_none_read_before():
    """A fallback: nothing an earlier spelling reads is touched (Sanxion
    carries this fetch too, but the primary shape reads its other engine
    first and still decides), and the nine it adds are named."""
    reached = set()
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        i = search_file(data, D.STATUS_BIT6_LATE_ABS_SHAPE)
        if i < 1:
            continue
        late = D._late_bit6_bvs(data, i, data[i + 6:i + 8],
                                len(D.STATUS_BIT6_LATE_ABS_SHAPE.split()))
        z = search_file(data, D.STATUS_BIT6_ZP_SHAPE)
        s = search_file(data, D.STATUS_BIT6_LATE_SHAPE)
        t = search_file(data, D.STATUS_BIT6_TWICE_SHAPE)
        earlier = (search_file(data, D.STATUS_BIT6_SHAPE) >= 1
                   or (z >= 1 and data[z + 5] == data[z + 11])
                   or s >= 1
                   or (t >= 1 and data[t + 6:t + 8] == data[t + 17:t + 19]))
        if not earlier:
            assert D._status_bit6_bvs(data) == late, path.name
            if late >= 0:
                reached.add(path.name)
    assert reached == set(LATE_ABS)


@needs_corpus
@pytest.mark.parametrize("name", LATE_ABS)
def test_every_bvs_lands_on_a_dec_of_the_gate_cell(name):
    """The premise the KEYOFF stands on, read off each file's bytes: the
    rest branch starts by decrementing a cell (`DE abs,X` / `CE abs`),
    the gate mask its waveform write ANDs with."""
    sid = load_sid(str(CORPUS / name))
    d = sid.data
    at = D._status_bit6_bvs(d)
    rel = d[at] - 256 if d[at] > 127 else d[at]
    target = at + 1 + rel
    assert d[target] in (0xDE, 0xCE), hex(d[target])
    cell = d[target + 1:target + 3]
    # ...AND cell(,X) / STA $D404,Y somewhere in the player
    assert (search_file(d, f"3D {cell[0]:02X} {cell[1]:02X} 99 04 D4") >= 1
            or search_file(d, f"2D {cell[0]:02X} {cell[1]:02X}") >= 1), name
    assert D.detect(sid, _quiet).status_bit6


@needs_corpus
def test_zoolook_bvs_is_the_hand_read_rest():
    sid = load_sid(str(CORPUS / "Zoolook.sid"))
    at = D._status_bit6_bvs(sid.data)
    assert at == sid.to_offset(0x40FA)
    assert sid.data[sid.to_offset(0x4139):sid.to_offset(0x4139) + 3] \
        == bytes([0xDE, 0xD3, 0x44])               # DEC $44D3,X


@needs_corpus
def test_zoolook_bass_rest_is_a_keyoff():
    """Pattern 3 at $49B2, `85 05 14 | 01 14 | 03 20 | 03 14 | 4B | ...`:
    the fifth event is the rest. Rows 0-15 are the four notes (6 + 2 + 4 +
    4 ticks), and row 16 is where the rest begins."""
    sid = load_sid(str(CORPUS / "Zoolook.sid"))
    det = D.detect(sid, _quiet)
    ev = _build_raw_pattern(sid.data, sid.to_offset(0x49B2),
                            status_bit6=det.status_bit6, rest_keyoff=True,
                            rest_instrument=True)
    rows = [ev[i:i + 4] for i in range(0, len(ev), 4)]
    notes = [i for i, r in enumerate(rows[:17]) if r[0] < GT_KEYOFF - 2]
    assert notes == [0, 6, 8, 12]
    assert rows[16][0] == GT_KEYOFF


@needs_corpus
def test_zoolook_converts_with_its_rests_keyed_off():
    """Through `convert` under the shipped presets: before the spelling
    Zoolook's song carried one KEYOFF (a `$FE` park), after it one per
    rest in every pattern a voice plays."""
    doc = json.loads((REPO_ROOT / "presets.json").read_text())
    sys.path.insert(0, str(REPO_ROOT / "python"))
    import fidelity
    from songview import parse_sng
    opts = fidelity._preset_opts(doc, "Zoolook.sid")
    song = parse_sng(convert(str(CORPUS / "Zoolook.sid"), log=_quiet, **opts))
    keyoffs = sum(p[i] == GT_KEYOFF for p in song.patterns
                  for i in range(0, len(p), 4))
    assert keyoffs > 20
