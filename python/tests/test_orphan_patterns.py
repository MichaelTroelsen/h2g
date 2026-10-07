"""Task `orphan-patterns-after-copy-remap`: `prune` leaves no unplayed pattern.

`convert_patterns(used=...)` prunes against the RAW orderlists. The passes that
run after it (`reindex_tracks`' tempo / fraction / tie copies, pulse phase)
repoint orderlist positions at COPIES appended past the table, so a source
whose every position moved stayed in the table unplayed and cost a pattern
number: at 3b1c66d C64ME reached `build_sng` with 136 patterns, ten of which
no orderlist plays (01 02 03 0A 0B 0D 0E 3A 3B 3E). Measured 2026-10-06 at
6e467ff, under presets: 12 files with `prune` on carried unplayed patterns
(5_Title_Tunes 19, Rasputin 14, C64ME 10, Star_Paws 8, ...);
`patterns.drop_unplayed_patterns` now runs last before the writer.

The renumbering is not meant to move a sound: the 12 movers resolve, per
orderlist position, to the same pattern bytes before and after (checked
outside this file against a base copy). What this file pins is the
mechanism, where a corpus-free test can, and the C64ME property.
"""
import json
import sys
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.convert import convert  # noqa: E402
from h2g.patterns import (GT_COMMAND_FLOOR, GT_ORDER_RESTART,  # noqa: E402
                          PatternList, drop_unplayed_patterns,
                          pattern_references)
from h2g.goatwriter.note_passes import note_bit7_rows  # noqa: E402
import songview  # noqa: E402

C64ME = "Commodore_64_Music_Examples.sid"


def _pat(note):
    return [note, 1, 0, 0]


def test_unreferenced_patterns_are_dropped_and_the_rest_renumbered():
    pats = [_pat(10), _pat(11), _pat(12), _pat(13)]
    tracks = [[0, 1, 3, 3, GT_ORDER_RESTART, 0],
              [3, 0xD2, 1, GT_ORDER_RESTART, 1]]
    tracks, pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == [2]
    assert pats == [_pat(10), _pat(11), _pat(13)]
    # pattern 3 -> 2; the repeat byte and BOTH restart operands are not
    # pattern references and must come through untouched
    assert tracks == [[0, 1, 2, 2, GT_ORDER_RESTART, 0],
                      [2, 0xD2, 1, GT_ORDER_RESTART, 1]]


def test_the_arguments_are_not_edited():
    """The walks and a caller's captures hold these lists: a renumbering
    in place is what failed 11 tests in the first attempt."""
    pats = PatternList([_pat(10), _pat(11), _pat(12)], {0: frozenset(), 2: None})
    tracks = [[0, 2, GT_ORDER_RESTART, 0]]
    pats_before, tracks_before = [list(p) for p in pats], [list(t) for t in tracks]
    out_tracks, out_pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == [1]
    assert out_pats is not pats and out_tracks is not tracks
    assert [list(p) for p in pats] == pats_before and tracks == tracks_before
    assert pats.note_bit7 == {0: frozenset(), 2: None} and pats.decoded == 3
    assert pats.ghosts == ()


def test_a_restart_operand_naming_a_dropped_number_is_not_a_reference():
    pats = [_pat(10), _pat(11), _pat(12)]
    tracks = [[0, 2, GT_ORDER_RESTART, 1]]      # `1` is a position, not a pattern
    tracks, pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == [1]
    assert tracks == [[0, 1, GT_ORDER_RESTART, 1]]
    # ...and one naming a number that IS a kept pattern, which moves:
    # the operand 2 is a position, so it stays 2 though pattern 2 becomes 1
    pats = [_pat(10), _pat(11), _pat(12)]
    tracks = [[0, 2, 2, GT_ORDER_RESTART, 2]]
    tracks, pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == [1]
    assert tracks == [[0, 1, 1, GT_ORDER_RESTART, 2]]


def test_everything_played_changes_nothing():
    pats = [_pat(10), _pat(11)]
    tracks = [[0, 1, GT_ORDER_RESTART, 0]]
    out_tracks, out_pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == []
    assert out_pats == [_pat(10), _pat(11)] and out_tracks == [[0, 1, GT_ORDER_RESTART, 0]]


def test_a_dangling_reference_refuses_the_whole_pass():
    """Renumbering would make an index past the table land on a real pattern."""
    pats = [_pat(10), _pat(11), _pat(12)]
    tracks = [[0, 7, GT_ORDER_RESTART, 0]]
    out_tracks, out_pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == []
    assert len(out_pats) == 3 and out_tracks == [[0, 7, GT_ORDER_RESTART, 0]]


def test_pattern_list_side_tables_follow_the_renumbering():
    pats = PatternList([_pat(10), _pat(11), _pat(12), _pat(13)],
                       {0: frozenset({1}), 1: frozenset({2}), 2: None})
    pats.decoded = 3        # entry 3 is a pass's copy
    tracks = [[0, 2, 3, GT_ORDER_RESTART, 0]]
    tracks, pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == [1]
    assert pats.note_bit7 == {0: frozenset({1}), 1: None}
    assert pats.decoded == 2
    # The dropped decoded pattern stays a candidate for the note-column match
    assert pats.ghosts == (((11,), frozenset({2})),)


def test_a_dropped_decoded_pattern_still_blocks_a_lone_match():
    """Dropping S must not attribute a copy of S to the one pattern T that
    shares its note column: with S present the two disagree, so the copy is
    unattributed; the ghost keeps it that way."""
    s, t, copy = _pat(10), _pat(10), _pat(10)
    known = {0: frozenset({0}), 1: frozenset({1})}
    before = note_bit7_rows([s, t, copy], known, 2)
    assert before[2] is None
    pats = PatternList([s, t, copy], known)
    pats.decoded = 2
    tracks = [[1, 2, GT_ORDER_RESTART, 0]]      # pattern 0 (S) is unplayed
    tracks, pats, dropped = drop_unplayed_patterns(tracks, pats)
    assert dropped == [0]
    after = note_bit7_rows(pats, pats.note_bit7, pats.decoded, pats.ghosts)
    assert after[1] is None
    # ...which is exactly the bug the ghost prevents:
    assert note_bit7_rows(pats, pats.note_bit7, pats.decoded)[1] == frozenset({1})


def _played(s):
    return {int(w[1:], 16) for t in s.tracks
            for kind, w, _ in songview.decode_orderlist(t) if kind == "pattern"}


def _preset_convert(name, **over):
    from fidelity import _preset_opts
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    opts = _preset_opts(doc, name)
    opts.update(over)
    return convert(str(CORPUS / name), log=lambda *a, **k: None, **opts)


@needs_corpus
def test_c64me_no_pattern_is_unplayed_by_every_orderlist():
    s = songview.parse_sng(_preset_convert(C64ME))
    unplayed = sorted(set(range(len(s.patterns))) - _played(s))
    assert unplayed == [], (
        f"{len(unplayed)} of {len(s.patterns)} patterns unplayed: "
        + " ".join(f"{i:02X}" for i in unplayed))


@needs_corpus
def test_c64me_without_prune_still_carries_them():
    """The pass belongs to `prune`: with it off the table is untouched."""
    s = songview.parse_sng(_preset_convert(C64ME, prune=False))
    assert set(range(len(s.patterns))) - _played(s)


@needs_corpus
@pytest.mark.parametrize("name", ["Thanatos.sid", "Delta_Mix-E-Load_loader.sid",
                                  "Star_Paws.sid"])
def test_other_prune_files_that_carried_orphans_are_clean(name):
    s = songview.parse_sng(_preset_convert(name))
    assert set(range(len(s.patterns))) <= _played(s)


def _resolved(sng):
    """Per orderlist position, the pattern BYTES it plays: numbering-free."""
    s = songview.parse_sng(sng)
    out = []
    for t in s.tracks:
        r, operand = [], False
        for b in t:
            if operand:
                r.append(("pos", b))
                operand = False
            elif b == GT_ORDER_RESTART:
                r.append("RST")
                operand = True
            elif b < GT_COMMAND_FLOOR:
                r.append(tuple(s.patterns[b]))
            else:
                r.append(b)
        out.append(r)
    return out, s.instruments, s.tables


@needs_corpus
@pytest.mark.parametrize("name", ["Thanatos.sid", "Star_Paws.sid",
                                  "Knucklebusters.sid", C64ME])
def test_the_drop_moves_numbering_only_not_what_any_position_plays(name):
    """The seam test for `PatternList.ghosts`: with the drop switched off,
    every orderlist position plays the same bytes. Without the ghosts
    reaching `note_bit7_rows`, Thanatos, Star_Paws and Knucklebusters turn
    restarted notes into ties here."""
    from h2g import convert as C
    kept = _resolved(_preset_convert(name))
    real = C.drop_unplayed_patterns
    C.drop_unplayed_patterns = lambda tracks, patterns: (tracks, patterns, [])
    try:
        undropped = _resolved(_preset_convert(name))
    finally:
        C.drop_unplayed_patterns = real
    assert kept == undropped
