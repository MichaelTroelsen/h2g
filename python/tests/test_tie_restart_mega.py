"""Mega_Apocalypse and Phantoms_of_the_Asteroid: do their ties restart the
instrument? (tie-restart-mega-phantoms-note-start, read at ca85ac7.)

Mega_Apocalypse: yes, and it is the legato-marker family. The note store is
`$4B75 LDA ($FA),Y / STA $5001 / AND #$7F` and `$4BB0 LDA $5001 / BMI $4BF2`
skips pulse, AD, SR and the per-voice sweep seeds; the waveform is stored at
`$4BF2` on every event and status bit 5 is read only at the note's end
(`$4C10`). `note_flag` does not spell it (the NOTE goes to zero page), so the
family was missed although the decoder already reads the bit under
`counter_fall` (`legato_bit7`).

Phantoms_of_the_Asteroid: yes, it is `classic_tie_restart_family`'s block
with its SID writes behind stubs -- but spelling its ties as clones changes no
register the harness scores (siddump -m2 -t180 text identical), so
`classic_tie_restart_family` stays None there. The assertions pin the READING
so a later change to the detector shows up.
"""
from types import SimpleNamespace

from h2g import goatwriter as G
from h2g.detect import detect
from h2g.sidfile import load_sid

from corpus import CORPUS, needs_corpus


def _bytes_at(sid, addr, hexstr):
    want = bytes.fromhex(hexstr)
    off = sid.to_offset(addr)
    return sid.data[off:off + len(want)] == want


@needs_corpus
def test_mega_reads_its_note_start_where_the_family_says():
    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    assert _bytes_at(sid, 0x4B46, "A9FF95DC")                 # mask reload
    assert _bytes_at(sid, 0x4B75, "B1FA8D0150297F")           # flag store
    assert _bytes_at(sid, 0x4BB0, "AD015030")                 # LDA flag / BMI
    assert _bytes_at(sid, 0x4BB5, "BDFB539902D4")             # pulse lo write
    assert _bytes_at(sid, 0x4BF2, "AD5F4FA6E495C6")           # wave, always
    assert _bytes_at(sid, 0x4C10, "2920D0")                   # bit 5: the end
    det = detect(sid, lambda *a, **k: None)
    assert not det.note_flag and det.counter_fall is not None
    assert G.legato_tie_family(sid, det) is True
    assert G.classic_tie_restart_family(sid, det) is None


@needs_corpus
def test_phantoms_is_the_record_block_behind_stubs_and_stays_unread():
    sid = load_sid(str(CORPUS / "Phantoms_of_the_Asteroid.sid"))
    assert _bytes_at(sid, 0xE09D, "A9FF8D39E4")               # mask reload
    assert _bytes_at(sid, 0xE0A2, "B1E8")                     # status fetch
    assert _bytes_at(sid, 0xE10C, "2D39E4205EF0BD67E4204EF0")  # the block
    assert _bytes_at(sid, 0xE150, "2920")                     # bit 5: the end
    assert _bytes_at(sid, 0xF05E, "E6E69904D4")               # ctrl stub
    assert _bytes_at(sid, 0xE208, "9967E4")                   # sweep -> record
    det = detect(sid, lambda *a, **k: None)
    assert G.classic_tie_restart_family(sid, det) is None
    assert G.legato_tie_family(sid, det) is False


def test_the_counter_fall_spelling_needs_the_same_two_shapes():
    det = SimpleNamespace(pattern_dialect="classic", note_flag=False,
                          counter_fall=object())
    store = bytes.fromhex("C8B1FA8D0150297F")                 # STA $5001
    gate = bytes.fromhex("AD01503009BDFB539902D4")            # LDA $5001 / BMI
    other = bytes.fromhex("AD02503009BDFB539902D4")
    pad = bytes(16)
    assert G.legato_tie_family(SimpleNamespace(data=pad + store + pad + gate), det)
    assert not G.legato_tie_family(
        SimpleNamespace(data=pad + store + pad + other), det)
    assert not G.legato_tie_family(
        SimpleNamespace(data=pad + store + pad + gate),
        SimpleNamespace(pattern_dialect="classic", note_flag=False,
                        counter_fall=None))


@needs_corpus
def test_mega_ties_with_bit7_clear_become_legato_clones():
    import json
    import pathlib
    import fidelity
    from h2g.convert import convert
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    lines = []
    convert(str(CORPUS / "Mega_Apocalypse.sid"), log=lines.append, **opts)
    legato = [l for l in lines if l.startswith("Legato tie")]
    assert any("legato clone" in l for l in legato), legato
    # The expanding-vibrato loops are not dropped for the clones' room.
    loops = next(l for l in lines if l.startswith("Expanding vibrato loops"))
    assert " on 42 wavetable loop(s)" in loops, loops
