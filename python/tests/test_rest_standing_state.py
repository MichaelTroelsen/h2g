"""A bit-6 rest's parked `$08` depends on the record STANDING on its voice.

IK+ `$E388` re-stores a record's waveform on every frame when the record's
effect byte (+7) has bit `$04`, so the `$08` a rest parks in the voice's stored
waveform lasts one frame after such a record and the whole rest after any
other (measured in `docs/LESSONS.md`; `detect.rest_wave_rewrite_records`).
A rest reads no operand, so which record stands is state the voice's previous
pattern left behind, and a rests-only pattern several voices share is reached
under different records. The state is therefore the orderlist POSITION's, not
the pattern's: `tracks.rest_entry_records` walks it and gives each class of
positions its own pattern copy, as `stored_wave_copies` does for the waveform.

The pattern-level tests build the byte streams by hand; the walk's tests stand
in for `decode_entry` with a table of `(rests before the first named
instrument, record standing at the end)`, which is all the walk reads.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g.goatwriter import rest_park as _rp  # noqa: E402,F401  (import order)
from h2g import patterns as P  # noqa: E402
from h2g import tracks as T  # noqa: E402

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"

EXEMPT = frozenset({4})
KW = dict(status_bit6=True, rest_keyoff=True, rest_wave=True)


def _rows(ev):
    return [tuple(ev[k:k + 4]) for k in range(0, len(ev), 4)]


def _parks(rows):
    """Rows that write the parked waveform."""
    return [r for r in rows if r[2] == P.CMD_SETWAVE and r[3] == P.REST_SILENT_WAVE]


# A named event (record `rec`, one note) then a 4-row rest, then the terminator.
def _named(rec):
    return bytes([0, 0, 0x80, rec, 0x30, 0x43, 0xFF])


REST_ONLY = bytes([0, 0, 0x43, 0xFF])


def test_a_rest_after_a_rewritten_record_parks_nothing():
    rows = _rows(P._build_raw_pattern(_named(4), 2, rest_wave_exempt=EXEMPT, **KW))
    assert _parks(rows) == []


def test_a_rest_after_any_other_record_parks_as_ever():
    rows = _rows(P._build_raw_pattern(_named(3), 2, rest_wave_exempt=EXEMPT, **KW))
    assert len(_parks(rows)) == 1


def test_no_exempt_set_is_the_old_emission_byte_for_byte():
    for rec in (3, 4):
        old = P._build_raw_pattern(_named(rec), 2, **KW)
        new = P._build_raw_pattern(_named(rec), 2, rest_wave_exempt=frozenset(),
                                   rest_entry_record=rec, **KW)
        assert old == new


def test_the_carried_in_record_decides_a_rest_before_any_instrument():
    def parks(entry):
        ev = P._build_raw_pattern(REST_ONLY, 2, rest_wave_exempt=EXEMPT,
                                  rest_entry_record=entry, **KW)
        return len(_parks(_rows(ev)))
    assert parks(None) == 1     # nothing standing: parked, as before
    assert parks(3) == 1
    assert parks(4) == 0


def test_the_pattern_reports_its_unnamed_rests_and_the_record_it_leaves():
    out = []
    P._build_raw_pattern(REST_ONLY, 2, record_exit=out, **KW)
    assert out == [(1, None)]
    out = []
    P._build_raw_pattern(_named(3), 2, record_exit=out, **KW)
    assert out == [(0, 3)]


def test_a_rest_after_a_named_event_in_the_same_pattern_is_not_an_unnamed_rest():
    # Rest, then an event naming record 3, then a rest: one unnamed rest.
    data = bytes([0, 0, 0x43, 0x80, 0x03, 0x30, 0x43, 0xFF])
    out = []
    P._build_raw_pattern(data, 2, record_exit=out, **KW)
    assert out == [(1, 3)]


# --- the walk ---------------------------------------------------------------

def _walk(monkeypatch, shape, tracks, **kw):
    """`tracks.rest_entry_records` with `decode_entry` replaced by `shape`."""
    def fake(sid, det, entry, slides=False, status_bit6=False, record_exit=None):
        record_exit.append(shape[entry])
        return []
    monkeypatch.setattr(T, "decode_entry", fake)
    det = SimpleNamespace(read_track_version=0, track_fd_transpose=False)
    kw.setdefault("exempt", EXEMPT)
    kw.setdefault("first", 50)
    kw.setdefault("limit", 0xF0)
    return T.rest_entry_records(None, det, tracks, **kw)


# 1: names record 4 (rewritten); 2: names record 2 (not); 5: rests only.
SHAPE = {1: (0, 4), 2: (0, 2), 5: (1, None)}
END = [0xFF, 0]


def test_a_shared_rests_only_pattern_is_split_by_the_record_each_voice_holds(monkeypatch):
    # Voices 0 and 2 reach pattern 5 holding record 4, voice 1 holding 2.
    tracks = [[1, 5] + END, [2, 5] + END, [1, 5] + END]
    entries, copies = _walk(monkeypatch, SHAPE, tracks)
    assert entries == {5: 4}                # the larger class keeps the number
    assert copies == [(5, 2)]               # the other gets a copy, record 2
    assert tracks[0][1] == 5 and tracks[2][1] == 5
    assert tracks[1][1] == 50               # rewritten in place to the copy
    assert tracks[1][0] == 2                # nothing else touched


def test_a_tie_keeps_the_exempt_side(monkeypatch):
    tracks = [[1, 5] + END, [2, 5] + END]
    entries, copies = _walk(monkeypatch, SHAPE, tracks)
    assert entries == {5: 4} and copies == [(5, 2)]
    assert tracks[1][1] == 50 and tracks[0][1] == 5


def test_a_pattern_every_voice_reaches_alike_gets_no_copy(monkeypatch):
    tracks = [[1, 5] + END, [1, 5] + END]
    entries, copies = _walk(monkeypatch, SHAPE, tracks)
    assert entries == {5: 4} and copies == []
    assert tracks == [[1, 5] + END, [1, 5] + END]


def test_no_copy_at_or_past_the_limit_the_position_keeps_the_majority(monkeypatch):
    tracks = [[1, 5] + END, [2, 5] + END, [1, 5] + END]
    entries, copies = _walk(monkeypatch, SHAPE, tracks, first=0x20, limit=0x20)
    assert entries == {5: 4} and copies == []
    assert tracks[1][1] == 5


def test_a_position_reached_under_both_classes_by_a_loop_counts_as_exempt(monkeypatch):
    # The orderlist restarts at position 1: pass 1 reaches pattern 5 holding
    # record 4 (from pattern 1), pass 2 holding record 2 (pattern 2, last).
    tracks = [[1, 5, 2, 0xFF, 1]]
    entries, copies = _walk(monkeypatch, SHAPE, tracks)
    assert entries == {5: 4} and copies == []


def test_a_transpose_variant_is_read_through_its_origin(monkeypatch):
    # Pattern 60 is a variant of 5 (tracks name it after fold_transposes).
    tracks = [[1, 60] + END, [2, 60] + END]
    entries, copies = _walk(monkeypatch, SHAPE, tracks, origin={60: 5})
    assert entries == {5: 4} and copies == [(5, 2)]


def test_a_pattern_that_names_its_own_record_first_needs_no_entry(monkeypatch):
    shape = {1: (0, 4), 7: (0, 3)}          # no unnamed rests anywhere
    tracks = [[1, 7] + END]
    entries, copies = _walk(monkeypatch, shape, tracks)
    assert entries == {} and copies == []


# --- the file ---------------------------------------------------------------

def _need_corpus():
    if not CORPUS.exists() or not PRESETS.exists():
        pytest.skip("corpus or presets not present")


def _convert(name, **extra):
    import json
    from fidelity import _preset_opts
    from h2g.convert import convert
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, name)
    opts.update(extra)
    lines = []
    out = convert(str(CORPUS / name), log=lines.append, **opts)
    return out, lines


def test_ik_plus_splits_its_shared_rest_pattern_under_the_option():
    _need_corpus()
    out, lines = _convert("IK_plus.sid", rest_wave_silence=True)
    note = [ln for ln in lines if ln.startswith("Rest entry records")]
    assert len(note) == 1 and "1 copy(ies)" in note[0], note


def test_the_option_off_reads_no_standing_record():
    _need_corpus()
    out, lines = _convert("IK_plus.sid")
    assert not [ln for ln in lines if ln.startswith("Rest entry records")]
    _on, _ = _convert("IK_plus.sid", rest_wave_silence=True)
    assert out != _on


def test_ik_plus_parks_fewer_rests_and_builds_the_copy_when_the_records_are_read():
    from unittest import mock
    import songview as S
    _need_corpus()
    on, _ = _convert("IK_plus.sid", rest_wave_silence=True)
    with mock.patch("h2g.convert.rest_wave_rewrite_records",
                    lambda sid, det: frozenset()):
        blind, lines = _convert("IK_plus.sid", rest_wave_silence=True)
    assert not [ln for ln in lines if ln.startswith("Rest entry records")]

    def parked(blob):
        song = S.parse_sng(blob)
        return sum(1 for pat in song.patterns
                   for r in range(0, len(pat) - 3, 4)
                   if pat[r] == P.GT_KEYOFF
                   and pat[r + 2] in (P.CMD_SETWAVE, P.CMD_SETWAVEPTR))
    assert parked(on) < parked(blind)
    assert len(S.parse_sng(on).patterns) > len(S.parse_sng(blind).patterns)
