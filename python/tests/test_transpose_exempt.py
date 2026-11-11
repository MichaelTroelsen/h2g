"""The `$FD nn` players do not transpose every record (transpose_exempt.py).

Lakers_vs_Celtics read 93.24% melody and Pacific_Coast 95.47% at v0.5.660, each
with a constant interval off on whole phrases -- voice 0 +2 x24 and voice 1 -2
x52 / -5 x5 on Lakers, voice 1 +5 / +3 on Pacific_Coast. The offset equalled a
transpose our own orderlist carried, and the player adds it only when the
note's record has flag bit 0 CLEAR (Lakers $1277 `LDA $1AE9 / AND #$01 / BNE
raw`); records 0, 1 and 2 have it set. Goattracker's transpose is per voice and
covers every note, so the exempt notes are lowered in a pattern copy per
(pattern, transpose).

Measured at 64c8265 + this change, `fidelity.py -t 180 --presets --sound`:
Lakers_vs_Celtics melody 93.24 -> 99.63, Pacific_Coast 95.47 -> 99.98; the
corpus byte-hash moves exactly those two of 95 (89 converted, 6 refused, all
refusals unchanged).
"""
import json
import pathlib
import sys
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity as F  # noqa: E402
import songview  # noqa: E402
from h2g import convert as C  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_FIRSTNOTE,  # noqa: E402
                          GT_ORDER_RESTART, GT_TRANSPOSE_UP, decode_entry,
                          lower_exempt_notes)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks, exempt_transpose_copies  # noqa: E402
from h2g.transpose_exempt import exempt_records  # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"
LAKERS = "Lakers_vs_Celtics.sid"
PACIFIC = "Pacific_Coast.sid"


def _quiet(*_a, **_k):
    pass


def _row(note, instr):
    return [GT_FIRSTNOTE + note, instr, 0, 0]


def test_lower_exempt_notes_moves_only_exempt_records_notes():
    events = (_row(24, 2) + _row(26, 3) + _row(28, 4)
              + [GT_END_PATTERN, 0, 0, 0])
    # instr_base 2: instruments 2 and 3 are records 0 and 1.
    got = lower_exempt_notes(events, frozenset({0, 1}), 2, 5)
    assert got == (_row(19, 2) + _row(21, 3) + _row(28, 4)
                   + [GT_END_PATTERN, 0, 0, 0])
    assert events[0] == GT_FIRSTNOTE + 24            # the source is untouched


def test_lower_exempt_notes_leaves_a_note_it_would_push_out_of_range():
    low = _row(3, 2)
    assert lower_exempt_notes(low, frozenset({0}), 2, 5) == low
    assert lower_exempt_notes(low, frozenset({0}), 2, -5) == _row(8, 2)


def test_an_unnamed_instrument_is_never_exempt():
    events = _row(24, 0)
    assert lower_exempt_notes(events, frozenset({0}), 2, 3) == events


@needs_corpus
def test_exempt_records_read_from_the_players_own_flag_table():
    got = {}
    for name in ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                 "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines",
                 "Commando"):
        sid, det = _detect_tables(load_sid(str(CORPUS / (name + ".sid"))),
                                  _quiet)
        got[name] = sorted(exempt_records(sid, det))
    assert got["Lakers_vs_Celtics"] == [0, 1, 2]
    assert got["Pacific_Coast"] == [0, 1, 2]
    assert got["Go_Go_Dash"] == [0, 2, 6, 18]
    # No `$FD nn` orderlist transpose, no reading of the flag.
    assert got["Commando"] == []


def _copies(name):
    sid, det = _detect_tables(load_sid(str(CORPUS / name)), _quiet)
    tracks = convert_tracks(sid, det, _quiet)
    before = [list(t) for t in tracks]
    det.transpose_exempt = exempt_records(sid, det)
    first = det.pattern_used + 1
    copies = exempt_transpose_copies(sid, det, tracks, _quiet,
                                     instr_base=2, first=first, limit=0xE0)
    return sid, det, before, tracks, copies, first


@needs_corpus
@pytest.mark.parametrize("name, copies, positions",
                         [(LAKERS, 7, 19), (PACIFIC, 5, 10)])
def test_only_transposed_positions_of_mixed_patterns_are_rewritten(
        name, copies, positions):
    sid, det, before, tracks, got, first = _copies(name)
    assert len(got) == copies, got
    changed = [(a, b) for t0, t1 in zip(before, tracks)
               for a, b in zip(t0, t1) if a != b]
    assert len(changed) == positions
    for src, number in changed:
        assert src <= det.pattern_used and number >= first
        assert got[number - first][0] == src
    # every copy sits under a non-zero transpose, and lowering by it makes the
    # exempt notes sound the raw pitch once the orderlist adds it back
    for src, transpose in got:
        assert transpose
        events = decode_entry(sid, det, src, False, False, None, False, 2)
        lowered = lower_exempt_notes(events, det.transpose_exempt, 2, transpose)
        moved = [k for k in range(0, len(events) - 3, 4)
                 if lowered[k] != events[k]]
        assert moved
        for k in moved:
            assert events[k + 1] - 2 in det.transpose_exempt
            assert lowered[k] + transpose == events[k]


@needs_corpus
def test_without_an_exempt_record_nothing_is_copied(monkeypatch):
    sid, det = _detect_tables(load_sid(str(CORPUS / LAKERS)), _quiet)
    tracks = convert_tracks(sid, det, _quiet)
    det.transpose_exempt = frozenset()
    assert exempt_transpose_copies(sid, det, tracks, _quiet, first=60,
                                   limit=0xE0) == []


def _pacific_voice_1(monkeypatch=None):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    if monkeypatch is not None:
        monkeypatch.setattr(C, "exempt_records",
                            lambda _sid, _det: frozenset())
    blob = C.convert(str(CORPUS / PACIFIC), log=_quiet,
                     **F._preset_opts(doc, PACIFIC))
    song = songview.parse_sng(blob)
    return doc, [n[3] for n in
                 songview.planned_notes(song.patterns, song.tracks[1])]


@needs_corpus
@pytest.mark.skipif(not Path(F.SIDDUMP).exists(), reason="siddump.exe not built")
@pytest.mark.parametrize("short_circuited", [False, True])
def test_pacific_coast_voice_1_names_equal_the_originals_attacks(
        tmp_path, monkeypatch, short_circuited):
    """The planned names of voice 1 (577 attacks in the first 180 s) are the
    original's, note for note. With `exempt_records` short-circuited to the
    empty set the same conversion is off by the transpose on the phrases from
    frame 4226 -- the +5 / +3 the entry measured."""
    doc, plan = _pacific_voice_1(monkeypatch if short_circuited else None)
    local = tmp_path / PACIFIC
    local.write_bytes((CORPUS / PACIFIC).read_bytes())
    cal, _ = F.table_calibration(CORPUS / PACIFIC, F._preset_opts(doc, PACIFIC))
    tr = F.run_siddump(local, 180, 0, F.SIDDUMP, cal)
    orig = [tr[1].attacks[k] for k, f in enumerate(tr[1].attack_frames)
            if f + 1 < 180 * 50]
    assert len(orig) == 577, "the trace length moved; re-measure"
    if short_circuited:
        assert plan[:len(orig)] != orig
        assert sum(a != b for a, b in zip(plan, orig)) >= 100
    else:
        assert plan[:len(orig)] == orig
