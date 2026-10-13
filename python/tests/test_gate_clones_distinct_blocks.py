"""A gate-phase clone is only made for a block the record's other clones lack.

`nibble-gate-clones-identical-blocks` (opened by ik-kentilla-gate-long-half):
`nibble_gate_phase_split_plan` cloned a record once per minority gate residue
and asked only whether the residue's block differed from the RECORD's, so
residues that laid out one and the same block each got a clone of their own.
Warhawk's record $11 got four six-entry clones (instruments 29-32, wavetable
pointers 232/238/244/250) with byte-identical programs; a fifth residue
(`10 r26`) then found no wavetable room and stayed on the record's block.
Sharing one clone frees that room: Warhawk is 36 bytes shorter, and that
fifth residue's note plays the gate-phase block it was always meant to.
International_Karate and Kentilla clone by entering into the record's block
(one pointer already) and do not move.
"""
import pathlib
import sys
from collections import defaultdict

import pytest

from corpus import needs_corpus
from test_nibble_gate_step_lead import _converted

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import songview                                              # noqa: E402
from h2g.goatwriter import arpeggio as _arpeggio             # noqa: E402


def _pointers_by_program(sng):
    song = songview.parse_sng(sng)
    out = defaultdict(set)              # (name, program) -> {wave pointer}
    for ins in song.instruments:
        if not ins.name or ins.wave_ptr == 0:
            continue
        prog = tuple((l, r) for _i, l, r, *_ in
                     songview.wave_program(song, ins.wave_ptr, 400))
        out[(ins.name, prog)].add(ins.wave_ptr)
    return out


@needs_corpus
@pytest.mark.parametrize("name", ["Warhawk", "International_Karate",
                                  "Kentilla"])
def test_one_record_never_has_two_pointers_to_one_program(name):
    sng, _m = _converted(name)
    split = {k: v for k, v in _pointers_by_program(sng).items()
             if len(v) > 1}
    assert not split, {k[0]: sorted(v) for k, v in split.items()}


@needs_corpus
def test_warhawk_record_11_gets_one_gate_clone():
    sng, _m = _converted("Warhawk")
    song = songview.parse_sng(sng)
    ptrs = {i.wave_ptr for i in song.instruments
            if i.name.startswith("11:")}
    assert len(ptrs) == 2, ptrs         # the record's own + one shared clone


def test_block_of_merges_residues_with_one_block():
    pat = [0x70, 1, 0, 0] * 4 + [0xFF, 0, 0, 0]
    tracks = [[0, 0xFF, 0]] + [[0xFF, 0]] * 2
    residues = {(0, 0, 0): {0: 1, 1: 2, 2: 3, 3: 3}}
    kw = dict(tracks=tracks, patterns=[pat], residues=residues,
              phases={1: 0}, records={1}, first_clone=2, factor=None)
    sep = _arpeggio._note_phase_split(**kw)
    one = _arpeggio._note_phase_split(**kw, block_of=lambda rec, r: "same")
    assert sep is not None and len(sep.clones) == 3
    assert one is not None and len(one.clones) == 1
    assert one.clones[0][1] == 2
