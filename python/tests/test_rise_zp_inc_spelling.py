"""Effect bit $02's chromatic rise in its zero-page spelling, and the emitter
limit it runs into.

`detect._find_effect_routines` recognised the rise only as Warhawk spells it,
`INC abs,X` (`FE`). Spellbound $E2FF is the same block with the note index
held zero-page, so the increment is `INC zp,X` (`F6`); the probe read the
routine as absent there. The zero-page spelling is now a fallback, consulted
only where the `FE` one matched nothing.

What the fallback must NOT do is reach Las_Vegas_Video_Poker $537B: the same
head (`AND #$02 / BEQ / LDA counter / AND #$03 / BNE`) followed by three
`DEC abs,X` -- a FALL of three semitones every four counter steps, not a rise.
The increment opcode is the whole discriminator, which is why the test below
pins the corpus set exactly.

Detecting it moves no emitted byte: Spellbound's only bit-$02 record ($11,
effect $56) also arpeggiates, and the rise is an `elif` on the arpeggio in
`goatwriter/wavetable.py`, where the limit and its measurement are written.
Measured at be0aeb1 + the v0.5.510 merge (historical): the original's (0,-5)
pair climbs to +60 semitones over each 281-frame note; ours alternates
(0,-5) at +0 throughout.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g import detect as detect_mod                            # noqa: E402
from h2g.convert import _detect_tables, convert                 # noqa: E402
from h2g.detect import _effect_byte_address                     # noqa: E402
from h2g.search import search_file                              # noqa: E402
from h2g.sidfile import load_sid                                # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"

ABS_SPELLING = ("Bump_Set_Spike", "Kentilla", "Thrust", "Warhawk")
ZP_SPELLING = ("Spellbound",)


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    _, det = _detect_tables(sid, lambda *a, **k: None)
    return sid, det


def _rise_at(sid, det, inc):
    addr, zp = _effect_byte_address(sid, det)
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    any_load = "A5 ??" if zp else "AD ?? ??"
    return search_file(
        sid.data, f"{load} 29 02 F0 ?? {any_load} 29 03 D0 ?? {inc}")


@needs_corpus
def test_spellbound_reads_the_rise_in_its_zero_page_spelling():
    sid, det = _det("Spellbound")
    # The fallback's precondition: the absolute spelling finds nothing here.
    assert _rise_at(sid, det, "FE") == -1
    at = _rise_at(sid, det, "F6")
    assert sid.to_address(at) == 0xE2FF
    assert sid.data[at + 12:at + 14] == bytes([0xF6, 0xAD])  # INC $AD,X
    assert det.effect_rise is True


@needs_corpus
@pytest.mark.parametrize("name", ABS_SPELLING)
def test_the_absolute_spelling_files_still_read_it(name):
    sid, det = _det(name)
    assert _rise_at(sid, det, "FE") >= 1
    assert det.effect_rise is True


@needs_corpus
def test_the_corpus_rise_set_is_exactly_the_five_inc_files():
    got = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _, det = _det(path.stem)
        except Exception:                                      # noqa: BLE001
            continue
        if det.effect_rise:
            got.add(path.stem)
    assert got == set(ABS_SPELLING + ZP_SPELLING)


@needs_corpus
def test_las_vegas_video_poker_falls_and_is_not_a_rise():
    sid, det = _det("Las_Vegas_Video_Poker")
    addr, zp = _effect_byte_address(sid, det)
    assert not zp
    at = search_file(sid.data, f"AD {addr & 0xFF:02X} {addr >> 8:02X} "
                     "29 02 F0 ?? AD ?? ?? 29 03 D0 ??")
    assert sid.to_address(at) == 0x537B
    # DEC $54CC,X three times: the head matches, the increment does not.
    assert sid.data[at + 14:at + 23] == bytes([0xDE, 0xCC, 0x54] * 3)
    assert det.effect_rise is False


@needs_corpus
def test_spellbounds_rise_arp_record_keeps_the_arp_and_loses_the_rise():
    """Record $11 at -S1, the shape that falls through the arpeggio branch
    to the rise's `elif`: the -5 interval ($7B) is there and no PORTAUP is.
    (At the preset -S5 the arpeggio branch returns before the `elif`.)"""
    from h2g.goatwriter import (FORMAT_GTS5, WAVECMD_PORTAUP,
                                _wavetable_entries)
    sid, det = _det("Spellbound")
    assert det.effect_rise and det.effect_arp
    rec = det.instr_start + 0x11 * det.instr_stride
    assert sid.data[rec + 7] == 0x56
    table = []
    left, right = _wavetable_entries(sid, det, 0x11, True, FORMAT_GTS5,
                                     table, 1, budget=32)
    assert 0x7B in right
    assert WAVECMD_PORTAUP not in left
    assert table == []


@needs_corpus
def test_detecting_spellbounds_rise_moves_no_emitted_byte(monkeypatch):
    """The emitter limit, pinned: record $11 sets the arpeggio too, and a
    rise+arp record takes the arpeggio shape and loses the rise. A change
    that emits the stair must update this test and the comment beside the
    rise branch in goatwriter/wavetable.py, with a measurement."""
    if not PRESETS.is_file():
        pytest.skip("presets.json not generated")
    from fidelity import _preset_opts
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, "Spellbound.sid")
    path = str(CORPUS / "Spellbound.sid")
    seen = []
    with_rise = convert(path, log=seen.append, **opts)
    assert any("Instrument effect byte" in m and "rise" in m for m in seen)

    real = detect_mod._find_effect_routines

    def no_rise(sid, det):
        return (False,) + tuple(real(sid, det))[1:]

    monkeypatch.setattr(detect_mod, "_find_effect_routines", no_rise)
    without = convert(path, log=lambda *a, **k: None, **opts)
    assert with_rise == without
