"""The classic vibrato's free-running phase where the update writes its swing
from the FIRST frame (h2g.vibrato_phase, "Early classes"): a duration-gated
update -- Zoolook's `$4263 LDA $44C7,X / AND #$1F / CMP #$03 / BCC`, the
dialect `detect.VibratoGate(form="duration")` names -- has no age to wait for,
so the swing shows on frame 1, ahead of the note's second pattern row, and a
class is the note's own instrument, not a chain the second row starts.

Pinned apart from any trace (the original's side was read off siddump of
Zoolook at v0.5.685, `fidelity.py -t 180`, and is quoted where it is used):

* `first_active` names the frame a player's swing first shows (4 behind
  ACE_II's age gate, 1 behind Zoolook's duration gate, None elsewhere);
* the counter model reproduces the original's direction sequence on a note,
  which it did not before the new-song call stopped counting as an update
  (the first call runs none of it: Zoolook's initial instrument carries a
  vibrato byte, so one extra step put every note of the first 93 s a frame
  ahead); and
* every note a class takes sits, frame for frame, on the original's offset
  in gplay.c's wavetable loop (`vp.simulate`), and with the dialect gate shut
  the pass returns the blob unchanged.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import convert as convert_module                    # noqa: E402
from h2g import detect                                       # noqa: E402
from h2g import unison_vibrato as uv                         # noqa: E402
from h2g import vibrato_phase as vp                          # noqa: E402
from h2g.goatwriter import HEADER_LEN                        # noqa: E402
from h2g.instrument_drop import _RECORD_LEN, _layout         # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from h2g.vibrato_hold import _read_tables                    # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ZOOLOOK = CORPUS / "Zoolook.sid"
ACE_II = CORPUS / "ACE_II.sid"
COMMANDO = CORPUS / "Commando.sid"
CALLS = 3                                  # Zoolook packs at -S3


def sign(x):
    return (x > 0) - (x < 0)


def _detected(path):
    sid = load_sid(str(path))
    return sid, detect.detect(sid, lambda m: None)


@pytest.fixture(scope="module")
def seam():
    """`(blob, sid, det)`: Zoolook's finished bytes where the pass is called."""
    doc = json.load(open(REPO_ROOT / "presets.json"))
    opts = fidelity._preset_opts(doc, ZOOLOOK.name)
    opts["vibrato_phase"] = True
    caught = []
    real = convert_module.phase_classic_vibrato

    def spy(blob, sid, det, multiplier, log=None):
        caught.append((bytes(blob), sid, det))
        return real(blob, sid, det, multiplier, log)

    convert_module.phase_classic_vibrato = spy
    try:
        convert_module.convert(str(ZOOLOOK), log=lambda m: None, **opts)
    finally:
        convert_module.phase_classic_vibrato = real
    return caught[0]


@needs_corpus
def test_first_active_names_the_dialect():
    sid, det = _detected(ZOOLOOK)
    assert det.vibrato_gate.form == "duration"
    assert vp.first_active(sid, det) == vp.EARLY_FIRST_ACTIVE == 1
    sid, det = _detected(ACE_II)
    assert vp.first_active(sid, det) == vp.FIRST_ACTIVE == 4
    sid, det = _detected(COMMANDO)
    assert vp.first_active(sid, det) is None
    # Chain_Reaction carries the dialect too and its counter model has not
    # been read against the original (EARLY_VERIFIED): the gate stays shut
    sid, det = _detected(CORPUS / "Chain_Reaction.sid")
    assert vp._duration_gate(sid, det)
    assert vp.first_active(sid, det) is None


@needs_corpus
def test_the_counter_model_follows_the_originals_triangle(seam):
    """Voice 0's first vibrating note of Zoolook (fetch frame 1, record `$0B`,
    byte `$11`: bound 2, shift 1): siddump of the original reads the pitch
    moving `++--++--+` on frames 2-10 (the frame-1 value is the swing's first,
    the frame-0 one the fetch's own)."""
    blob, sid, det = seam
    notes = vp.note_phases(blob, sid, det)
    assert len(notes) == 568
    assert {n["first"] for n in notes} == {1}
    first = notes[0]
    assert first["place"] == (0, 1, 0, 0) and first["frame"] == 1
    offs = first["offsets"]
    steps = [sign(offs[j] - offs[j - 1]) for j in range(2, first["life"])]
    assert steps == [1, 1, -1, -1, 1, 1, -1, -1, 1]


def _covered(blob, out):
    """`{place: instrument number the output names}` for every note row whose
    instrument column the pass changed."""
    changed = {}
    pos_in = pos_out = HEADER_LEN + 1
    ia, _ta, _pa, pats_in = _layout(blob)
    ib, _tb, _pb, pats_out = _layout(out)
    for v in range(3):
        n_in, n_out = blob[pos_in], out[pos_out]
        order_in = bytes(blob[pos_in + 1:pos_in + n_in + 2])
        order_out = bytes(out[pos_out + 1:pos_out + n_out + 2])
        pos_in += n_in + 2
        pos_out += n_out + 2
        ein = uv._rows(order_in, pats_in, blob)
        eout = uv._rows(order_out, pats_out, out)
        for (i, _p, repeat, _t, rows_in), (_i2, _p2, _r2, _t2, rows_out) in zip(
                ein, eout):
            for play in range(repeat):
                for r, (a, b) in enumerate(zip(rows_in, rows_out)):
                    if a[1] != b[1]:
                        changed[(v, i, play, r)] = b[1]
    return changed


@needs_corpus
def test_a_class_sits_on_the_originals_offset_frame_for_frame(seam):
    blob, sid, det = seam
    out = vp.phase_classic_vibrato(blob, sid, det, CALLS)
    assert out != blob
    notes = {n["place"]: n for n in vp.note_phases(blob, sid, det)}
    count = blob[_layout(blob)[0]]
    # a row that names a clone; the pass also names the base record on the
    # next note of a clone's note that names nothing (`respell`)
    changed = {p: c for p, c in _covered(blob, out).items() if c > count}
    # three clones, the cap of `EARLY_MAX_CLONES`; the notes lost to a repeat
    # whose plays name different classes and the tied ones keep the record's
    # own vibrato
    assert len(changed) >= 150
    assert set(changed.values()) == set(
        range(count + 1, count + vp.EARLY_MAX_CLONES + 1))
    ia, ta, pa, _pats = _layout(out)
    wtbl, _p, _f, stbl = _read_tables(out, ta, pa)
    for place, clone in changed.items():
        note = notes[place]
        rec = out[ia + 1 + (clone - 1) * _RECORD_LEN:
                  ia + 1 + clone * _RECORD_LEN]
        shift = uv._vibrato_byte(bytes(rec[9:_RECORD_LEN])) & 7
        assert rec[5] == 0                 # no instrument vibrato of its own
        calls = CALLS * note["life"] + 1
        swing = vp.simulate(wtbl, stbl, rec[2], calls, shift)
        # the note's call 0 runs no wavetable row: frame j's last call is
        # program call 3 j + 1
        for j in range(1, note["life"]):
            assert swing[CALLS * j + 1] == note["offsets"][j], (place, j)


@needs_corpus
def test_the_duration_gate_is_load_bearing(seam, monkeypatch):
    """Short-circuited -- the dialect not read -- the pass returns the bytes it
    was given; and the clone cap changes what it writes."""
    blob, sid, det = seam
    on = vp.phase_classic_vibrato(blob, sid, det, CALLS)
    assert on != blob
    monkeypatch.setattr(vp, "_duration_gate", lambda s, d: False)
    assert vp.phase_classic_vibrato(blob, sid, det, CALLS) == blob
    monkeypatch.undo()
    monkeypatch.setattr(vp, "EARLY_MAX_CLONES", 1)
    one = vp.phase_classic_vibrato(blob, sid, det, CALLS)
    assert one != on and one != blob
