"""Bit-7 free notes in a pattern entered with two instruments are split for.

`free_note_variants` respells a flagged note row on a variant of the record
it plays with no attack stage and no pulse reset; it shares
`_respell_on_clones` with the legato tie clones, so a row before its
pattern's first named instrument in a pattern two orderlist positions enter
holding different instruments had no one base and declined "entered with
two instruments". `build_sng` already split such patterns for the legato
ties (`entry_instrument_split`) and now hands it the free-note rows too --
only those that could play a record with an attack to skip
(`free_note_split_rows`, `free_note_record_has_attack`): a row whose every
possible instrument has none declines whichever plays, so splitting for it
would only spend pattern numbers, and its decline now names that reason.

Measured at 6e467ff + the cycle-4 merge, under presets
(C:/t/free-note-two-instrument-entry-declines): Knucklebusters 7 -> 31 free
rows on 2 -> 4 variants (its 10 "entered with two instruments" were $44/$45,
the two slices of original pattern $33, entered holding 11, 18, 19 and 23);
Flash_Gordon 1 -> 2 (pattern $64); Delta's 11 kept, renamed "no two-stage
attack to skip" (patterns $02/$03 are entered holding 1, 2 and 12, records
0, 1 and 11, none with an attack), bytes unchanged. Trace check: siddump-rt
-w on the original's track position ($0943,X / $C2EC,X), pattern offset
($0946,X / $C2EF,X) and instrument ($0955,X / $C2FE,X) shows Knucklebusters
entering original $33 holding indices $0A, $11, $12 and $16 -- GT 11, 18, 19
and 23, the four instruments the split settles its copies on -- and Delta
entering original $01/$02 (GT $02/$03) holding only records without a
two-stage attack ($00, $01, $02 on voice 1, $0B on voice 3).

Since free-note-pulse-only-variant, a record with no attack takes a
pulse-only variant where the channel holds it before the row; the split
here is unchanged (still two-stage records only), so the corpus lines below
carry those rows too, and Delta's 11 and Knucklebusters' 2 rows whose every
entry instrument is a pulse-only record decline "entered with two
instruments" again (C:/t/free-note-pulse-only-variant, 6e467ff plus the
cycle-5 merge).
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.goatwriter import note_passes as NP
from h2g.convert import convert
from h2g.sidfile import load_sid
from h2g.detect import detect

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE, REST = G.GT_FIRST_NOTE, G.GT_REST
END = 0xFF


def _two_entry_song():
    """Pattern 2's flagged rows 0 and 1 play whatever the channel holds:
    5 at position 1 (after pattern 0), 6 at position 3 (after pattern 1).
    Row 2 names 7, so row 3 plays 7 however the pattern is entered."""
    pats = [[NOTE, 5, 0, 0, END, 0, 0, 0],
            [NOTE, 6, 0, 0, END, 0, 0, 0],
            [NOTE, 0, 0, 0, NOTE + 1, 0, 0, 0, NOTE + 2, 7, 0, 0,
             NOTE + 3, 0, 0, 0, REST, 0, 0, 0, END, 0, 0, 0]]
    tracks = [[0, 2, 1, 2, END, 0], [0, END, 0], [0, END, 0]]
    return pats, tracks


# --- which rows are split for --------------------------------------------------

def test_a_row_is_split_for_only_where_it_could_play_an_attack():
    pats, tracks = _two_entry_song()
    rows = {(2, 0), (2, 1), (2, 3)}
    assert NP._entry_instruments(tracks, pats)[2] == {5, 6}
    # Rows 0 and 1 can play 5 or 6; row 3 plays 7 (named on row 2).
    assert G.free_note_split_rows(pats, rows, tracks, {6}) == {(2, 0), (2, 1)}
    assert G.free_note_split_rows(pats, rows, tracks, {7}) == {(2, 3)}
    assert G.free_note_split_rows(pats, rows, tracks, {9}) == set()


def test_the_split_settles_every_free_row():
    pats, tracks = _two_entry_song()
    rows = {(2, 0), (2, 1)}
    starts = {5: 40, 6: 44}
    lines = []
    _, variants, declined = G.free_note_variants(pats, rows, tracks, starts,
                                                 30, log=lines.append)
    assert declined == rows and variants == []
    assert "2 entered with two instruments" in lines[0], lines
    new_tracks, new_pats, copies = G.entry_instrument_split(
        tracks, pats, G.free_note_split_rows(pats, rows, tracks, set(starts)))
    assert copies == {3: 2}
    rows2 = rows | {(3, 0), (3, 1)}
    out, variants, declined = G.free_note_variants(new_pats, rows2, new_tracks,
                                                   starts, 30)
    assert declined == set()
    assert variants == [(5, 30), (6, 31)]
    assert [out[2][1], out[2][5]] == [30, 30]
    assert [out[3][1], out[3][5]] == [31, 31]


def test_two_entries_neither_with_an_attack_name_that_reason():
    """Whichever instrument plays, the row has no attack to skip: the log
    says so rather than blaming the entry."""
    pats, tracks = _two_entry_song()
    lines = []
    _, _, declined = G.free_note_variants(pats, {(2, 0), (2, 1)}, tracks,
                                          {9: 40}, 30, log=lines.append)
    assert declined == {(2, 0), (2, 1)}
    assert "2 no two-stage attack to skip" in lines[0], lines
    assert "entered with two instruments" not in lines[0], lines
    # One of the two cloneable: the entry is still what declines it.
    lines = []
    G.free_note_variants(pats, {(2, 0)}, tracks, {5: 40}, 30,
                         log=lines.append)
    assert "1 entered with two instruments" in lines[0], lines


# --- the corpus ------------------------------------------------------------------

def _preset_convert(name, monkeypatch):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    seen = {}
    real_split, real_free = NP.entry_instrument_split, NP.free_note_variants

    def split(tracks, patterns, rows, **kw):
        got = real_split(tracks, patterns, rows, **kw)
        seen["split"] = (rows, got)
        return got

    def free(patterns, rows, tracks, starts, *a, **kw):
        got = real_free(patterns, rows, tracks, starts, *a, **kw)
        seen["free"] = (patterns, rows, tracks, starts, got)
        seen["pulse_only"] = set(kw.get("pulse_only", ()))
        return got
    monkeypatch.setattr(NP, "entry_instrument_split", split)
    monkeypatch.setattr(NP, "free_note_variants", free)
    lines = []
    convert(str(CORPUS / name), log=lines.append, **F._preset_opts(doc, name))
    return lines, seen


def _free_line(lines):
    got = [ln for ln in lines if ln.startswith("Free note (bit 7)")]
    assert len(got) == 1, lines
    return got[0]


@needs_corpus
def test_knucklebusters_settles_original_33_on_the_traced_instruments(
        monkeypatch):
    lines, seen = _preset_convert("Knucklebusters.sid", monkeypatch)
    line = _free_line(lines)
    assert line.startswith("Free note (bit 7).......: 45 flagged note row(s) "
                           "on 6 variant(s)"), line
    # The two left are in $35/$37, entered holding only pulse-only records.
    assert line.endswith("(2 entered with two instruments; 1 follows another "
                         "instrument)"), line
    _rows, (tracks, patterns, copies) = seen["split"]
    assert sorted(set(copies.values())) == [0x21, 0x44, 0x45]
    entry = NP._entry_instruments(tracks, patterns)
    for source in (0x44, 0x45):
        family = [source] + [c for c, s in copies.items() if s == source]
        assert all(len(entry[p]) == 1 for p in family), \
            {p: entry[p] for p in family}
        # The original enters $33 holding indices $0A, $11, $12, $16
        # (siddump-rt -w0943,0946,0955), compact numbering index + 1.
        assert set().union(*(entry[p] for p in family)) == {11, 18, 19, 23}
    _p, _r, _t, starts, (_out, variants, _declined) = seen["free"]
    assert [b for b, _ in variants
            if b not in seen["pulse_only"]] == [10, 18, 19, 23]


@needs_corpus
def test_flash_gordon_settles_pattern_64(monkeypatch):
    lines, seen = _preset_convert("Flash_Gordon.sid", monkeypatch)
    line = _free_line(lines)
    assert line.startswith("Free note (bit 7).......: 5 flagged note row(s)"), \
        line
    assert "entered with two instruments" not in line, line
    _rows, (_t, _p, copies) = seen["split"]
    assert sorted(set(copies.values())) == [0x64, 0x8F]


@needs_corpus
def test_delta_is_not_split_and_says_why_its_rows_decline(monkeypatch):
    """Its two-entry patterns are entered holding only records with no
    attack (records 0, 1, 11 -- the original holds the same, by trace), so
    nothing is copied for them. All three take pulse-only variants, so the
    11 rows decline for the entry."""
    lines, seen = _preset_convert("Delta.sid", monkeypatch)
    line = _free_line(lines)
    assert line.endswith("11 kept the full start (11 entered with two "
                         "instruments)"), line
    assert not any(ln.startswith("Entry instrument split") for ln in lines), \
        [ln for ln in lines if ln.startswith("Entry")]
    _rows, (_t, _p, copies) = seen["split"]
    assert copies == {}


@needs_corpus
@pytest.mark.parametrize("name", ["Delta.sid", "Knucklebusters.sid",
                                  "Flash_Gordon.sid", "Shockway_Rider.sid"])
def test_every_free_start_is_a_record_with_an_attack(name, monkeypatch):
    """`free_note_record_has_attack` is the record half of
    `free_note_wave_start`: every GT number given a two-stage free start is
    one the split may count on, and every pulse-only one is not (record =
    GT - 1 under compact numbering)."""
    _lines, seen = _preset_convert(name, monkeypatch)
    sid = load_sid(str(CORPUS / name))
    det = detect(sid, log=lambda m: None)
    starts, only = seen["free"][3], seen["pulse_only"]
    assert starts and set(starts) - only and only <= set(starts)
    assert all(G.free_note_record_has_attack(sid, det, g - 1) is (g not in only)
               for g in starts)
