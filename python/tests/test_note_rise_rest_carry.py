"""The note rise runs on through the rest after a note (Chimera $C2FF).

Chimera voice 1 from its attack at frame 440 (siddump, -S1, rows of 3 ticks):
the rise's stores `$10 $11 ... $20 $21` land on every second frame to frame 505
(`$21`) and then do NOT stop where the converter's note ends. The event at
row 22 (frame 506) is a bit-6 event -- no operand, no note, the converter's
KEYOFF with no instrument -- and the player's rise tests the duration of the
event it is in, not the note's, and steps a byte that only a NOTE fetch resets
(`detect.note_rise_rest_carries_on`):

    503 20F0  504 01F0  505 21F7  506 21F7  507 2205  508 0205  509 23FE ...
                              ^^^^^^^^^ the fetch tick of the event: it writes
                        the gate off and runs no effect, so every register
                        holds -- not a second store, and not an outer gate's
                        skip (the IRQ calls the play routine once a frame)

on to `$40` at frame 567, 21 rows later. Until this the planner ended the note
at the KEYOFF row, so the twelve high-byte frames `note-rise-row-parity` left
(`21 21` at frames 505-506 and five more pairs) were the first two frames of a
186-store tail ours never played: 12 of 186 in the narrow window, 198 of 558
in the full one.
"""
import dataclasses
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus
from test_note_rise import (_agreement, _converted, needs_gt2reloc,
                            needs_siddump)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import h2g.detect as D                                       # noqa: E402
from h2g.goatwriter import note_rise as R                    # noqa: E402
from h2g.goatwriter.constants import (CMD_TONEPORTA,         # noqa: E402
                                      GT_KEYOFF, GT_REST)
from h2g.sidfile import load_sid                             # noqa: E402

NOTE = 0x60


def _old_store_rows(phase, lag, frames, length, kcap):
    """store_rows as it was before `skips` (v0.5.538)."""
    stores = {}
    for k in range(1, kcap):
        tick = phase + 2 * k
        if tick >= length * frames:
            break
        j, half = divmod(tick + lag, frames)
        if j >= length:
            break
        stores.setdefault(j, []).append((k, half))
    return stores


def test_store_rows_without_skips_is_what_it_was():
    for phase in (1, 2):
        for lag in (0, 1):
            for frames in (2, 3):
                for length in (1, 2, 5, 22, 40):
                    for kcap in (1, 3, 34, 128):
                        assert (R.store_rows(phase, lag, frames, length, kcap)
                                == _old_store_rows(phase, lag, frames, length,
                                                   kcap)), (phase, lag, frames,
                                                            length, kcap)


def test_a_store_due_on_a_skipped_tick_is_not_executed_and_the_values_shift():
    """Ticks 1 3 5 7 9 11 of a 4-row note of 3 ticks are stores 0 .. 5. With
    tick 5 a fetch tick (no effect runs) store 2 does not happen, the byte is
    not stepped, and tick 7 stores what tick 5 would have: every k after it is
    one tick later."""
    def walk(stores):
        return sorted((3 * j + half, k) for j, v in stores.items()
                      for k, half in v)
    assert walk(R.store_rows(1, 0, 3, 4, 99)) == [(3, 1), (5, 2), (7, 3),
                                                  (9, 4), (11, 5)]
    assert walk(R.store_rows(1, 0, 3, 4, 99, {5})) == [(3, 1), (7, 2), (9, 3),
                                                       (11, 4)]


def test_a_skipped_tick_that_is_not_a_store_tick_changes_nothing():
    assert (R.store_rows(1, 0, 3, 22, 99, {66})
            == R.store_rows(1, 0, 3, 22, 99))
    assert (R.store_rows(1, 1, 3, 22, 99, {66, 132})
            == R.store_rows(1, 1, 3, 22, 99))


def _song(spec):
    """(patterns, rows) for one pattern of 4-byte rows; `spec` is a list of
    (note, instrument) per row."""
    pat = []
    for note, instr in spec:
        pat += [note, instr, 0, 0]
    return [pat], [(0, r, 0) for r in range(len(spec))]


def _note_then(*events):
    """A note of 22 rows, then each (note, instrument, rows) event."""
    spec = [(NOTE, 5)] + [(GT_REST, 0)] * 21
    for note, instr, rows in events:
        spec += [(note, instr)] + [(GT_REST, 0)] * (rows - 1)
    spec += [(NOTE, 6)]
    return _song(spec)


def test_the_rise_runs_through_a_keyoff_event_long_enough_for_the_rise():
    patterns, rows = _note_then((GT_KEYOFF, 0, 22))
    assert R.continuation(rows, patterns, 0, 22, 17) == [(22, 22)]
    # the same event, one row too short for min_length 17 (dur = rows - 1)
    patterns, rows = _note_then((GT_KEYOFF, 0, 17))
    assert R.continuation(rows, patterns, 0, 22, 17) == []
    patterns, rows = _note_then((GT_KEYOFF, 0, 18))
    assert R.continuation(rows, patterns, 0, 22, 17) == [(22, 18)]


def test_it_chains_through_each_event_and_stops_at_the_first_that_does_not():
    patterns, rows = _note_then((GT_KEYOFF, 0, 20), (GT_KEYOFF, 0, 20),
                                (GT_KEYOFF, 0, 3), (GT_KEYOFF, 0, 20))
    assert R.continuation(rows, patterns, 0, 22, 17) == [(22, 20), (42, 20)]


def test_an_event_that_starts_something_ends_the_note_as_before():
    # a new note, an instrument change on the KEYOFF, a rest row that names an
    # instrument: each is a fetch that resets the byte or changes the record
    for event in ((NOTE, 0, 22), (GT_KEYOFF, 7, 22), (GT_REST, 7, 22)):
        patterns, rows = _note_then(event)
        assert R.continuation(rows, patterns, 0, 22, 17) == [], event


def test_a_lap_that_ends_inside_the_event_carries_nothing():
    patterns, rows = _song([(NOTE, 5)] + [(GT_REST, 0)] * 21
                           + [(GT_KEYOFF, 0)] + [(GT_REST, 0)] * 20)
    assert R.continuation(rows, patterns, 0, 22, 17) == []


def test_an_event_longer_than_the_duration_field_is_not_a_continuation():
    patterns, rows = _note_then((GT_KEYOFF, 0, 40))
    assert R.continuation(rows, patterns, 0, 22, 17) == []


def _info(**kw):
    base = dict(chosen=list(range(1, 35)), kbase=34, edited=87, cut=0, over=0,
                carried=192, placed=114)
    base.update(kw)
    return base


def test_the_longer_plan_must_keep_the_notes_own_values_exact():
    base = _info(carried=0, placed=0)
    assert R._extension_pays(_info(chosen=list(range(1, 52))), base)
    # spread over the range: the notes' own values are not 1 .. kbase
    assert not R._extension_pays(_info(chosen=list(range(2, 53))), base)
    assert not R._extension_pays(_info(chosen=list(range(1, 30))), base)


def test_the_longer_plan_may_not_lose_rows_or_cut_more():
    base = _info(carried=0, placed=0)
    ext = _info(chosen=list(range(1, 52)))
    assert R._extension_pays(ext, base)
    assert not R._extension_pays(dict(ext, edited=86), base)
    assert not R._extension_pays(dict(ext, cut=1), base)
    assert not R._extension_pays(dict(ext, over=1), base)


def test_the_longer_plan_must_place_half_of_what_it_carries_on():
    base = _info(carried=0, placed=0)
    ext = _info(chosen=list(range(1, 52)))
    assert R._extension_pays(dict(ext, carried=192, placed=96), base)
    assert not R._extension_pays(dict(ext, carried=192, placed=95), base)
    # Crazy_Comets: 256 asked, 10-16 placed -- its rests are shared rows
    assert not R._extension_pays(dict(ext, carried=256, placed=16), base)


@needs_corpus
def test_the_five_rise_players_carry_the_byte_through_a_bit6_event():
    for name in ("Chimera", "Crazy_Comets", "Game_Killer",
                 "Battle_of_Britain", "Human_Race"):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = D.detect(sid, lambda *a, **k: None)
        assert det.note_rise is not None, name
        assert D.note_rise_rest_carries_on(sid, det), name


@needs_corpus
def test_a_player_without_the_block_carries_nothing():
    sid = load_sid(str(CORPUS / "Commando.sid"))
    det = D.detect(sid, lambda *a, **k: None)
    assert det.note_rise is None
    assert not D.note_rise_rest_carries_on(sid, det)


@needs_corpus
def test_a_store_to_savehi_in_the_bit6_branch_says_no():
    """Chimera's branch target is $C2FF; a `STA $C656,X` planted there is a
    fetch that resets the byte, and the rise then starts over at the event."""
    sid = load_sid(str(CORPUS / "Chimera.sid"))
    det = D.detect(sid, lambda *a, **k: None)
    bvs = D._status_bit6_bvs(sid.data)
    rel = sid.data[bvs] - 256 if sid.data[bvs] > 127 else sid.data[bvs]
    target = bvs + 1 + rel
    buf = bytearray(sid.data)
    buf[target + 10:target + 13] = bytes([0x9D, 0x56, 0xC6])
    planted = dataclasses.replace(sid, data=bytes(buf))
    assert D.note_rise_rest_carries_on(sid, det)
    assert not D.note_rise_rest_carries_on(planted, det)


@needs_corpus
def test_a_status_byte_the_rise_does_not_read_says_no():
    """The status byte is stored into the duration array the rise tests; if
    the player stored it elsewhere the new event's length would not count."""
    sid = load_sid(str(CORPUS / "Chimera.sid"))
    det = D.detect(sid, lambda *a, **k: None)
    i = D.search_file(sid.data, D.STATUS_BIT6_SHAPE)
    assert i >= 1
    buf = bytearray(sid.data)
    buf[i + 3] ^= 0x01                      # STA dur,X -> a neighbouring array
    other = dataclasses.replace(sid, data=bytes(buf))
    assert not D.note_rise_rest_carries_on(other, det)


@needs_corpus
def test_chimeras_six_long_notes_are_carried_on_and_nothing_else_is():
    rises = {}
    for name in ("Chimera", "Crazy_Comets", "Game_Killer",
                 "Battle_of_Britain", "Human_Race"):
        _sng, lines, _ = _converted(name)
        rises[name] = [m for m in lines if "Note rise (bit $02)" in m]
    assert len(rises["Chimera"]) == 1
    assert "6 note(s) carried on through the rest after them" in rises["Chimera"][0]
    for name in ("Crazy_Comets", "Game_Killer", "Battle_of_Britain",
                 "Human_Race"):
        assert rises[name] and not any("carried on" in m for m in rises[name]), (
            name, rises[name])


@needs_corpus
def test_chimeras_carried_on_stores_take_the_keyoff_row_and_the_rows_after_it():
    """Each of the six notes: the KEYOFF row (row 22 of the note, whose
    `CMD_TONEPORTA 00` would pin the voice against the step) takes the pair
    for stores 32 and 33 on calls 0 and 2, the hold rows after it carry on one
    store after another, and the last row kept has a tail that puts the voice
    back on its note."""
    import songview
    from test_note_rise_rows import _pointer_programs
    sng, _lines, _ = _converted("Chimera")
    song = songview.parse_sng(sng)
    notes = _pointer_programs(song, {10, 11})
    carried = [hits for hits in notes if any(j >= 22 for j, _p in hits)]
    assert len(carried) == 6, [len(h) for h in notes]
    for hits in carried:
        by_row = dict(hits)
        assert by_row[22] == {0: 32, 2: 33}, by_row[22]
        assert by_row[23] == {1: 34}, by_row[23]
        beyond = [(j, p) for j, p in hits if j >= 22]
        assert [j for j, _p in beyond] == list(range(22, 35)), beyond
        last = beyond[-1][1]
        assert 2 not in last, last           # a row-final store has no tail
        vals = [v for _j, p in beyond for _c, v in sorted(p.items())]
        # 51 of the 63 values fit; the 51st sat on the last tick of a row whose
        # tail would have put the voice back, and went with it
        assert vals == list(range(32, 51)), vals


def _keep_rise(lo, hi):
    return lambda h, onset: lo <= h - onset <= hi


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_chimeras_stores_past_the_notes_end_land_on_the_originals_frames(
        tmp_path, monkeypatch):
    """-t 180, voice 1, AD>>4 = $0F0, packed through gt2reloc. The narrow
    window (stores 3 to $20 above the note) is the 186 frames
    `note-rise-row-parity` measured at 174; the six that remain are the
    original's fetch tick of the bit-6 event (frame 506: the registers hold,
    where ours steps back to its note). The whole rise to $40 reads 84% where
    it read 64%."""
    narrow = _agreement("Chimera", 1, 180, 0x0F0, _keep_rise(3, 0x20),
                        tmp_path, "narrow")[1]
    wide = _agreement("Chimera", 1, 180, 0x0F0, _keep_rise(3, 0x7F),
                      tmp_path, "wide")[1]
    assert narrow[0] == 186 and narrow[1] >= 180, narrow
    assert wide[0] >= 550 and wide[1] >= 0.8 * wide[0], wide
    monkeypatch.setattr(R, "note_rise_rest_carries_on", lambda *a, **k: False)
    without = _agreement("Chimera", 1, 180, 0x0F0, _keep_rise(3, 0x7F),
                         tmp_path, "without")[1]
    assert without[0] == wide[0] and without[1] <= 0.7 * wide[0], (wide, without)
