"""A file can carry two copies of one player, with a table from each.

Powerplay Hockey has the engine twice: one at `$36xx` with instruments at
`$3BA0`, driving nine short game cues whose orderlists sit at `$3C66`; and
one at `$43F0` with instruments at `$4A00`, driving the tune the PSID header
starts on, whose orderlists and patterns are at `$4B40`/`$4B4A`. The two
copies are the same code at different bases -- `$4574 LDA $4A03,X /
STA $D405,Y` against `$3779 LDA $3BA3,X / STA $D405,Y`.

The instrument chain took whichever store-shape matched first, which is the
cue engine's, while the orderlist and pattern chains matched the other copy.
Right notes, wrong instruments: `adsr` 0% with not one envelope pair shared
with the original, and the four columns keyed by instrument -- `onset`,
`nrun`, `hold`, `tail` -- all reporting nothing to compare.

Picking the table nearest the pattern pointers instead takes that file from
melody 72% to 99%, `adsr` 0% to 99.9%, `retrig` 1.76 to 1.01, and moves no
other file in the corpus.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables  # noqa: E402
from h2g.detect import _nearest_table, _search_all  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

SHAPE = "BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48"


def _cpu(sid, off):
    return off - sid.to_offset(sid.load_addr) + sid.load_addr


def test_search_all_finds_every_match_not_just_the_first():
    data = b"\x00" + b"\xBD\x01\x02" * 3
    hits = _search_all(data, "BD ?? ??")
    assert len(hits) == 3
    assert hits == sorted(hits)


def test_search_all_is_bounded():
    data = b"\x00" + b"\xBD\x01\x02" * 50
    assert len(_search_all(data, "BD ?? ??", limit=4)) == 4


def test_one_match_is_left_alone():
    """A file with a single copy of the player cannot be moved by this."""
    data = b"\x00" + b"\xBD\x00\x10" + b"\x99\x02\xD4"
    assert _nearest_table(data, "BD ?? ??", 0x20, sid=None) == -1


@needs_corpus
def test_powerplay_takes_the_engine_that_owns_the_patterns():
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Powerplay_Hockey_USA_vs_USSR.sid")),
        lambda *a, **k: None)
    assert _cpu(sid, det.instr_start) == 0x4A00
    # The other copy is real and is the one the chain used to take.
    hits = _search_all(sid.data, SHAPE)
    assert len(hits) >= 2
    addrs = {sid.data[i + 1] | (sid.data[i + 2] << 8) for i in hits}
    assert 0x3BA0 in addrs and 0x4A00 in addrs
    # And it is nearer the patterns, which is the whole rule.
    assert (abs(sid.to_offset(0x4A00) - det.pattern_lo)
            < abs(sid.to_offset(0x3BA0) - det.pattern_lo))


@needs_corpus
def test_the_chosen_table_holds_the_envelopes_the_original_sounds():
    """The check that made this a reading rather than a plausible move.

    Traced, the original sounds $0A9B, $0AA9, $0AC9 and $0CF7. None of the
    four appears at any offset of any record in the table the chain used;
    all four are at `+3`/`+4` of records in the one it takes now.
    """
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Powerplay_Hockey_USA_vs_USSR.sid")),
        lambda *a, **k: None)
    pairs = set()
    for i in range(det.instr_used):
        o = det.instr_start + i * det.instr_stride
        pairs.add((sid.data[o + 3] << 8) | sid.data[o + 4])
    assert {0x0A9B, 0x0AA9, 0x0AC9, 0x0CF7} <= pairs


@needs_corpus
def test_it_moves_no_other_corpus_file():
    """Every other file has one match of its winning shape, or the nearest
    is the one already chosen."""
    moved = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:
            continue
        if det.instr_start < 0 or det.pattern_lo < 0:
            continue
        hits = _search_all(sid.data, SHAPE)
        if len(hits) < 2:
            continue
        near = _nearest_table(sid.data, SHAPE, det.pattern_lo, sid)
        if near >= 0 and sid.to_offset(near) != det.instr_start:
            moved.append(path.name)
    assert moved == [], moved
