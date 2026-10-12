"""`_find_instrument_index` must read the array of the player whose instrument
table `detect` found, not of whichever player matches the shape first.

One_on_One_Jordan_vs_Bird carries four players. The shape's FIRST match is a
stride-8 copy at $894F with array $3689 (image `3F 42 88`, init `$04`); the
tune player is stride 16, spells the record multiply `ASL x4`, reads its
instrument table $1228 through the array at $1199 and starts every voice on
`$0F` (siddump subtune 0 frame 0: `0F 0F 0F`). Powerplay_Hockey is the same
story with the cue engine's $3B0E against the tune engine's $4971. Both used
to read the wrong array, and tests/test_init_instrument.py pinned the wrong
values (4 and 11) behind an `IMAGE_AT_SUBTUNE_0` exemption that existed only
to explain why siddump disagreed.

Measured at base 6f346b6 under presets: 95 files, 6 refused in both arms, 89
compared, 0 moved (both files park silence until the first instrument, so
`init_entry_start` declines and the log is the only output that changes).
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g import detect as D
from h2g.sidfile import load_sid


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


def _blob(*, second=None, second_table=0x0220):
    d = bytearray(0x500)
    # first match, 3 shifts: array $0300, table $0450
    d[0x10:0x1D] = _hex("BD 00 03 8E 10 03 0A 0A 0A AA BD 52 04")
    d[0x300:0x303] = bytes((0x3F, 0x42, 0x88))
    tab = bytes(((second_table + 2) & 0xFF, (second_table + 2) >> 8))
    if second == "asl4":
        d[0x40:0x4E] = _hex("BD 80 03 8E 90 03 0A 0A 0A 0A AA BD") + tab
    elif second == "asl3":
        d[0x40:0x4D] = _hex("BD 80 03 8E 90 03 0A 0A 0A AA BD") + tab
    d[0x380:0x383] = bytes((0x0F, 0x08, 0x01))
    d[0x100:0x108] = _hex("A9 0F 9D 80 03 CA 10 F0")      # the init loop
    return _Flat(d)


def _run(sid, table):
    det = D.Detection()
    idx = D._find_instrument_index(sid, det, NUL)
    assert det.initial_instruments == (0x3F, 0x42, 0x88)       # first match
    det.instr_start = table
    D._reconcile_instrument_index(sid, det, NUL, idx)
    return det


def test_a_first_match_that_names_the_found_table_is_left_alone():
    det = _run(_blob(second="asl4"), table=0x0450)
    assert det.initial_instruments == (0x3F, 0x42, 0x88)


@pytest.mark.parametrize("spelling", ["asl4", "asl3"])
def test_the_match_naming_the_found_table_supplies_the_array(spelling):
    det = _run(_blob(second=spelling), table=0x0220)
    assert det.initial_instruments == (0x0F, 0x08, 0x01)
    assert det.init_instrument == 0x0F


def test_no_match_naming_the_table_drops_the_reading():
    det = _run(_blob(second="asl4"), table=0x0999)
    assert det.initial_instruments == ()
    assert det.init_instrument is None


def test_nothing_to_reconcile_without_a_found_table():
    sid = _blob(second="asl4")
    det = D.Detection()
    idx = D._find_instrument_index(sid, det, NUL)
    D._reconcile_instrument_index(sid, det, NUL, idx)          # instr_start -1
    assert det.initial_instruments == (0x3F, 0x42, 0x88)


@needs_corpus
@pytest.mark.parametrize("name, image", [
    ("One_on_One_Jordan_vs_Bird.sid", (0x0F, 0x08, 0x01)),
    ("Powerplay_Hockey_USA_vs_USSR.sid", None),
])
def test_the_tune_players_array_is_read(name, image):
    sid = load_sid(str(CORPUS / name))
    det = D.detect(sid, NUL)
    assert det.init_instrument == 0x0F
    if image is not None:
        assert det.initial_instruments == image


@needs_corpus
def test_every_other_corpus_file_already_read_its_own_players_array():
    """The no-op claim: outside these two the shape's first match names the
    table `detect` located, so the reconcile step changes nothing."""
    odd = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = D.detect(sid, NUL)
        except Exception:
            continue                          # refused: nothing to compare
        if det.instr_start < 0:
            continue
        i = D._windowed_search(sid.data, 0, len(sid.data))(
            D.INSTRUMENT_INDEX_SHAPE)
        if i <= -1:
            continue
        table = D._addr16(sid.data, i + 11, i + 12) - 2
        if table != sid.to_address(det.instr_start):
            odd.append(path.name)
    assert odd == ["One_on_One_Jordan_vs_Bird.sid",
                   "Powerplay_Hockey_USA_vs_USSR.sid"]
