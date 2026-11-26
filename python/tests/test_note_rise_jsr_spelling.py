"""Bit $02's window-less rise, spelled through the player's store wrappers.

Phantoms_of_the_Asteroid $E2FE is Game_Killer's block (`detect.NOTE_RISE_SHAPE`)
with two spelling differences, which is why the shape missed it and the file
read `note_rise` None: a dead `LDA ticks,X / CMP #$14` between the length test
and the counter (its flags are overwritten by the next `LDA`, so there is no
ticks-left window), and the store as `JSR $F046` (`INC $E6 / STA $D401,Y /
DEC $E6`) instead of `STA $D401,Y`. siddump of the original, voice 0 from frame
1729: the odd frames read `28EB 29A2 2A10 2B59 ...` over the vibrato's
`27A2 27EB 2759 2710` on the even ones, the high byte rising $01 a store. A
write log of the player shows the second `D401` store (`hi=27` then `hi=28`)
on exactly those frames.

Measured under presets at -t 180, before -> after (the task
listen-sub99-phantoms-of-the-asteroid, historical): tiefr 64% -> 86%, tie
0.67x -> 0.89x, travel 0.89x -> 0.99x, bend 1.21x -> 1.13x, vib 0.75 -> 1.00,
depth 0.78x -> 0.90x, cents 96% -> 97%.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import detect as D                                  # noqa: E402
from h2g.detect import NoteRise, detect                      # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

NAME = "Phantoms_of_the_Asteroid"


def _det(sid):
    return detect(sid, lambda *a, **k: None)


@needs_corpus
def test_the_jsr_spelling_is_read_as_a_note_rise():
    sid = load_sid(str(CORPUS / f"{NAME}.sid"))
    det = _det(sid)
    assert det.note_rise == NoteRise(counter=0xE465, min_length=0x11, step=1)
    assert det.skydive is None and not det.effect_rise
    assert D.note_rise_rest_carries_on(sid, det) is True


@needs_corpus
def test_the_wrapper_must_store_to_d401():
    """The JSR's target is read, not assumed: point the shape's `JSR $F046`
    at the wrapper for `$D400` (`$F03E`) and the block is not this one."""
    sid = load_sid(str(CORPUS / f"{NAME}.sid"))
    data = bytearray(sid.data)
    at = D.search_file(bytes(data), "AD 63 E4 " + D.NOTE_RISE_JSR_SHAPE)
    assert at >= 1
    jsr = at + 3 + D.JSR_AT_STORE
    assert data[jsr:jsr + 2] == bytes([0x46, 0xF0])
    data[jsr:jsr + 2] = bytes([0x3E, 0xF0])
    sid.data = bytes(data)
    assert _det(sid).note_rise is None


@needs_corpus
def test_only_phantoms_carries_the_spelling():
    hits = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if D.search_file(sid.data, "AD ?? ?? " + D.NOTE_RISE_JSR_SHAPE) >= 1:
            hits.append(path.stem)
    assert hits == [NAME]


@needs_corpus
def test_the_rise_is_emitted_for_phantoms_and_not_without_the_shape(
        monkeypatch):
    import json
    import fidelity
    import h2g.convert as C
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{NAME}.sid")
    path = str(CORPUS / f"{NAME}.sid")

    lines = []
    C.convert(path, log=lines.append, **opts)
    assert any(l.startswith("Note rise (bit $02)") for l in lines)

    monkeypatch.setattr(D, "_note_rise_jsr_block", lambda *a, **k: -1)
    short = []
    C.convert(path, log=short.append, **opts)
    assert not any(l.startswith("Note rise (bit $02)") for l in short)
