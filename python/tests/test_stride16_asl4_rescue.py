"""The stride-16 players that spell the record multiply `ASL x4` read their
per-voice instrument array through `_reconcile_instrument_index`'s rescue.

`INSTRUMENT_INDEX_SHAPE` (three shifts) matches no byte of After_8,
Kings_of_the_Beach_intro, Mr_Meaner, Off_the_Cuff, Pygmies_Revenge, Rikky and
Rock_Tells_the_Tale, so they read no array and `init_instrument` stayed None.
Their load is the four-shift spelling, and its second `LDA` names exactly the
table `detect` found. The array's file image is `$13 $09 $16` (Kings: `$05 $05
$01`); the player's init writes `$0F`, and siddump holds `0F 0F 0F` in all
three slots at frame 0 of subtunes 0-2 in every one.

Measured at base 40cc8e5 (C:/t/stride16-asl4-index-rescue): under presets the
corpus byte-hash moves nothing (95 files, 6 refused in both arms, 89 compared,
0 moved), and forcing `initial_instrument` on moves none of the seven either --
every one names an instrument on the first row of its first pattern, so there
is no row `apply_initial_instruments` or the entry walk could respell.
"""
import hashlib
import json

import pytest

from corpus import CORPUS, needs_corpus
from h2g import detect as D
from h2g.convert import convert
from h2g.sidfile import load_sid


SEVEN = ["After_8", "Kings_of_the_Beach_intro", "Mr_Meaner", "Off_the_Cuff",
         "Pygmies_Revenge", "Rikky", "Rock_Tells_the_Tale"]
NON_HELD = ["Kings_of_the_Beach_intro", "Off_the_Cuff", "Pygmies_Revenge",
            "Rock_Tells_the_Tale"]


def NUL(*_a, **_k):
    return None


class _Flat:
    """Identity address space: offset == C64 address."""
    def __init__(self, data):
        self.data = bytes(data)

    def to_address(self, off):
        return off

    def to_offset(self, addr):
        return addr


def _hex(s):
    return bytes.fromhex(s.replace(" ", ""))


def _blob(table=0x0220):
    d = bytearray(0x500)
    tab = bytes(((table + 2) & 0xFF, (table + 2) >> 8))
    d[0x40:0x4E] = _hex("BD 80 03 8E 90 03 0A 0A 0A 0A AA BD") + tab
    d[0x380:0x383] = bytes((0x13, 0x09, 0x16))
    d[0x100:0x108] = _hex("A9 0F 9D 80 03 CA 10 F0")      # the init loop
    return _Flat(d)


def _reconcile(sid, table):
    det = D.Detection()
    idx = D._find_instrument_index(sid, det, NUL)
    det.instr_start = table
    D._reconcile_instrument_index(sid, det, NUL, idx)
    return idx, det


def test_an_asl4_only_player_reads_the_array_naming_its_table():
    idx, det = _reconcile(_blob(), table=0x0220)
    assert idx == -1                          # the 3-shift shape matched nothing
    assert det.initial_instruments == (0x13, 0x09, 0x16)
    assert det.init_instrument == 0x0F


def test_an_asl4_load_naming_another_table_is_not_this_players():
    idx, det = _reconcile(_blob(), table=0x0999)
    assert idx == -1
    assert det.initial_instruments == ()
    assert det.init_instrument is None


def test_no_found_table_reads_nothing():
    _idx, det = _reconcile(_blob(), table=-1)
    assert det.initial_instruments == ()
    assert det.init_instrument is None


@needs_corpus
@pytest.mark.parametrize("name", SEVEN)
def test_the_seven_read_the_init_of_their_own_player(name):
    det = D.detect(load_sid(str(CORPUS / (name + ".sid"))), NUL)
    assert det.init_instrument == 0x0F
    assert len(det.initial_instruments) == 3
    assert det.initial_instruments != (0x0F, 0x0F, 0x0F)       # the image


@needs_corpus
def test_no_corpus_file_is_left_with_an_unread_array_it_could_have_read():
    """Everything the shape can name is read: a detected file with no array
    and an ASL4 load naming its table would be a seventh file this missed."""
    left = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = D.detect(sid, NUL)
        except Exception:
            continue
        if det.instr_start < 0 or det.initial_instruments:
            continue
        table = sid.to_address(det.instr_start)
        for i in D._search_all(sid.data, D.INSTRUMENT_INDEX_SHAPE_ASL4):
            if D._addr16(sid.data, i + 12, i + 13) - 2 == table:
                left.append(path.name)
    assert left == []


def _opts(name, forced):
    import pathlib
    from fidelity import _preset_opts
    presets = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    opts = dict(_preset_opts(json.loads(presets.read_text()), name + ".sid"))
    if forced:
        opts["initial_instrument"] = True
    return opts


@needs_corpus
@pytest.mark.parametrize("name", NON_HELD)
def test_the_rescue_moves_no_converted_byte_even_with_the_option_forced(
        name, monkeypatch):
    """The A/B: the same conversion with the rescue switched off, under
    presets, and with `initial_instrument` forced on top of it."""
    path = str(CORPUS / (name + ".sid"))

    def sha(forced):
        return hashlib.sha1(convert(path, log=NUL, **_opts(name, forced))
                            ).hexdigest()

    with_rescue = sha(False)
    with_rescue_forced = sha(True)
    monkeypatch.setattr(D, "_reconcile_instrument_index",
                        lambda *a, **k: None)
    without = sha(False)
    assert with_rescue == without
    assert with_rescue_forced == without
