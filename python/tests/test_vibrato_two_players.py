"""A file with two copies of the player has the vibrato shape twice.

`search_file` is `SSearchfile`'s port and returns the *first* offset a shape
occurs at. `_find_vibrato` took that one match, tested the `LDA record+n,Y`
behind it, and returned None when it did not resolve into the instrument
record -- so on Powerplay Hockey, whose two copies of the player sit at
`$37FE` and `$45E5`, the routine read the copy the chains did **not** take
its instrument table from and refused the file. § 7.iiiii settled which table
is the right one (the one nearest the pattern pointers, `$4A00`); this pins
that the vibrato search reaches the copy that reads it.

The backward-LDA test was already the discriminator. It had one candidate to
apply to; now it has every match, in shape-priority order.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import (VIBRATO_DEPTH_SHAPES, VIBRATO_SHAPE, VIBRATO_SHAPES,
                        _find_vibrato, _shape_matches, detect)
from h2g.search import search_file
from h2g.sidfile import HLEN, load_sid

POWERPLAY = "Powerplay_Hockey_USA_vs_USSR.sid"


def _first_match_only(sid, det):
    """`_find_vibrato` as it stood before all matches were tried."""
    data = sid.data
    at = -1
    for shape in VIBRATO_SHAPES:
        at = search_file(data, shape)
        if at >= 1:
            break
    if at < 1:
        return None
    if not any(search_file(data, s) >= 1 for s in VIBRATO_DEPTH_SHAPES):
        return None
    for k in range(at - 3, max(0, at - 26), -1):
        if data[k] in (0xB9, 0xBD):
            off = sid.to_offset(data[k + 1] | data[k + 2] << 8) - det.instr_start
            if 0 <= off < det.instr_stride:
                return off
    return None


def test_shape_matches_is_search_files_plural():
    """Same grammar, same 1-based floor; the first element is `search_file`."""
    data = bytes([0x00, 0x48, 0x29, 0x78, 0x11, 0x48, 0x29, 0x78, 0x22])
    assert _shape_matches(data, "48 29 78 ??") == [1, 5]
    assert _shape_matches(data, "48 29 78 ??")[0] == search_file(data, "48 29 78 ??")
    assert _shape_matches(data, "99 99") == []
    # offset 0 is never tested, exactly as SSearchfile never tested it
    assert _shape_matches(bytes([0x48, 0x29]), "48 29") == []


@needs_corpus
def test_shape_matches_agrees_with_search_file_on_every_corpus_file():
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        for shape in VIBRATO_SHAPES:
            hits = _shape_matches(data, shape)
            assert hits == sorted(hits), (path.name, shape)
            first = search_file(data, shape)
            assert (hits[0] if hits else -1) == first, (path.name, shape)


@needs_corpus
def test_powerplays_first_copy_names_the_other_copys_table():
    sid = load_sid(str(CORPUS / POWERPLAY))
    det = detect(sid, log=lambda m: None)

    def addr(off):
        return off + sid.load_addr - HLEN + 1

    hits = _shape_matches(sid.data, VIBRATO_SHAPE)
    assert [addr(h) for h in hits] == [0x37FE, 0x45E5], [hex(addr(h)) for h in hits]

    def back_lda(at):
        for k in range(at - 3, max(0, at - 26), -1):
            if sid.data[k] in (0xB9, 0xBD):
                return addr(k), sid.data[k + 1] | sid.data[k + 2] << 8
        return None, None

    assert back_lda(hits[0]) == (0x37F6, 0x3BA5)
    assert back_lda(hits[1]) == (0x45DD, 0x4A05)
    # $4A00 is the table the chains settled on; $3BA5 belongs to the other copy
    assert addr(det.instr_start) == 0x4A00, hex(addr(det.instr_start))
    assert sid.to_offset(0x3BA5) - det.instr_start == -3675
    assert sid.to_offset(0x4A05) - det.instr_start == 5


@needs_corpus
def test_powerplay_reads_its_vibrato_at_the_same_plus_five_as_everyone_else():
    sid = load_sid(str(CORPUS / POWERPLAY))
    det = detect(sid, log=lambda m: None)
    assert _first_match_only(sid, det) is None, "the old rule refused this file"
    assert _find_vibrato(sid, det) == 5
    assert det.vibrato_offset == 5
    # and the byte it now reads is real data, not an empty column
    records = [sid.data[det.instr_start + i * det.instr_stride + 5]
               for i in range(det.instr_used)
               if det.instr_start + i * det.instr_stride + 5 < len(sid.data)]
    assert any(records), "Powerplay would gain a vibrato with no depth"


@needs_corpus
def test_trying_every_match_moves_exactly_one_corpus_file():
    """Widening a search can rescue a refusal and must disturb nothing else.

    The whole corpus, old rule against new: only Powerplay's offset moves, and
    it moves from None. Every file whose first match already resolved keeps the
    offset it always had, because the first match is still the first candidate.
    """
    moved = {}
    seen = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = detect(sid, log=lambda m: None)
        except Exception:      # noqa: BLE001 -- an unreadable file is not this test's business
            continue
        seen += 1
        old, new = _first_match_only(sid, det), _find_vibrato(sid, det)
        if old != new:
            moved[path.name] = (old, new)
    assert seen >= 90, f"only {seen} files were read"
    assert moved == {POWERPLAY: (None, 5)}, moved
