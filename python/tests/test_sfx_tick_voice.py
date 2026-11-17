"""The bit-$80 drum's tick on the voice the player writes it to
(`goatwriter.sfx_tick_voice`).

Thundercats' sfx block stores to the voice-3 registers by absolute address
whichever voice's record carries bit $80, so record `$0E` (effect `$A0`, played
on voice 1 alone) ticks VOICE 3 and leaves voice 1 on its own waveform. These
pin the reading (a record the sfx voice never plays), the stretch it is live
on, the rest rows that become clicks, the click program's lattice, and the
conversion that ships it.
"""
import json
import os

import pytest

from h2g.goatwriter.constants import (CMD_SETAD, CMD_SETSR, CMD_SETTEMPO,
                                      GT_FIRST_NOTE, GT_KEYOFF, GT_REST)
from h2g.goatwriter.sfx_rest_click import sfx_rest_click_entries
from h2g.goatwriter.sfx_tick_voice import (click_pattern, live_spans, plays,
                                           stray_drum_record, tick_entries,
                                           tick_rows)

CORPUS = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"
PRESETS = os.path.join(os.path.dirname(__file__), "..", "..", "presets.json")

N = GT_FIRST_NOTE + 27            # any legal note
STRAY, OTHER, CLONE = 13, 4, 30


def _row(note, ins=0, cmd=0, data=0):
    return [note, ins, cmd, data]


def _pattern(*rows):
    return [b for r in rows for b in r] + [0xFF, 0, 0, 0]


def test_a_record_is_stray_only_where_the_sfx_voice_never_plays_it():
    voices = {13: {0: 16}, 2: {2: 800, 0: 1}, 5: {0: 8, 2: 2}, 7: {}}
    assert stray_drum_record(voices, 13, 2)
    # one row on the sfx voice keeps the record's own hit: a wavetable is per
    # instrument
    assert not stray_drum_record(voices, 2, 2)
    assert not stray_drum_record(voices, 5, 2)
    assert not stray_drum_record(voices, 7, 2)
    assert not stray_drum_record(voices, 99, 2)
    assert not stray_drum_record(None, 13, 2)


def test_the_stretch_runs_from_the_stray_note_to_the_next_other_instrument():
    pats = [_pattern(_row(N, STRAY), _row(GT_REST), _row(GT_KEYOFF)),
            _pattern(_row(GT_REST), _row(N, OTHER), _row(GT_REST))]
    # pattern 0 twice, then pattern 1: rows 0-2, 3-5, 6-8
    track = [0xD1, 0, 1, 0xFF, 0]
    ps, total = plays(track, pats)
    assert total == 9
    assert [(p[0], p[3]) for p in ps] == [(1, 0), (1, 3), (2, 6)]
    # the rest keeps the record live; the note on $04 in pattern 1 ends it
    assert live_spans(track, pats, {STRAY}) == [(0, 7)]
    assert live_spans(track, pats, {OTHER}) == [(7, 9)]


def test_only_rest_rows_inside_the_stretch_become_clicks():
    rest = _pattern(_row(GT_KEYOFF, 0, CMD_SETTEMPO, 8), _row(GT_REST),
                    _row(GT_KEYOFF, 0, CMD_SETSR, 0), _row(GT_REST))
    notes = _pattern(_row(N, OTHER), _row(GT_REST), _row(GT_KEYOFF))
    pats = [rest, notes]
    track = [0, 1, 0, 0xFF, 0]
    # rows 0-3 are entry 0, 4-6 entry 1 (a note, then a key-off), 7-10 entry 2
    assert tick_rows(track, pats, [(4, 12)]) == {1: {2}, 2: {0, 2}}
    # a rest outside the stretch is left alone; the note row never is a rest
    assert tick_rows(track, pats, [(7, 8)]) == {2: {0}}
    assert tick_rows(track, pats, [(0, 12)]) == {0: {0, 2}, 1: {2}, 2: {0, 2}}
    assert tick_rows(track, pats, []) == {}


def test_a_repeated_entry_is_kept_only_where_every_play_agrees():
    rest = _pattern(_row(GT_KEYOFF), _row(GT_REST))
    pats = [rest]
    track = [0xD2, 0, 0xFF, 0]              # three plays, rows 0-5
    assert tick_rows(track, pats, [(0, 6)]) == {1: {0}}
    assert tick_rows(track, pats, [(2, 6)]) == {}       # the first play is out


def test_a_click_row_names_the_clone_on_the_previous_note_and_drops_the_rests_silence():
    pat = _pattern(_row(N, OTHER), _row(GT_REST),
                   _row(GT_KEYOFF, 0, CMD_SETSR, 0),
                   _row(GT_REST, 0, CMD_SETAD, 0), _row(GT_REST),
                   _row(N + 2, OTHER))
    new = click_pattern(pat, {2}, CLONE, None)
    assert new[8:12] == [N, CLONE, 0, 0]          # the previous note's pitch
    assert new[12:16] == [GT_REST, 0, 0, 0]       # SETAD $00 went too
    assert new[:8] == pat[:8] and new[20:] == pat[20:]
    assert pat[8:12] == [GT_KEYOFF, 0, CMD_SETSR, 0]     # a copy
    # a rest at row 0 with nothing carried still names a legal note
    first = click_pattern(_pattern(_row(GT_KEYOFF, 0, CMD_SETTEMPO, 8)),
                          {0}, CLONE, None)
    assert GT_FIRST_NOTE <= first[0] < GT_KEYOFF
    assert first[1:4] == [CLONE, CMD_SETTEMPO, 8]       # the clock stays


@pytest.mark.parametrize("m", [1, 2, 3])
@pytest.mark.parametrize("period", [6, 8])
def test_the_tick_program_hits_on_its_own_first_frame_where_the_rest_click_waits_one(
        m, period):
    """`sfx_rest_click`'s program holds frame 0 and hits on frame 1 (the sfx
    voice's own record reads the counter before its fetch steps it); a stray
    record's hit is on the fetch frame itself. Same loop, minus the lead."""
    left, right, loop = tick_entries(0x48, period, m)
    rl, rr, rloop = sfx_rest_click_entries(0x48, period, m)
    assert loop == 0 and left[0] == 0x81
    assert (left, right) == (rl[rloop:], rr[rloop:])
    assert rl[0] != 0x81 and rl[rloop] == 0x81


@pytest.mark.skipif(not os.path.exists(os.path.join(CORPUS, "Thundercats.sid"))
                    or not os.path.exists(PRESETS),
                    reason="corpus or presets.json absent")
def test_thundercats_ticks_voice_3_for_the_record_voice_1_plays():
    import songview
    from fidelity import _preset_opts
    from h2g.convert import convert
    from h2g.tracks import instrument_voices
    opts = _preset_opts(json.load(open(PRESETS)), "Thundercats.sid")
    assert opts.get("sfx_drum")
    song = songview.parse_sng(convert(os.path.join(CORPUS, "Thundercats.sid"),
                                      log=lambda m: None, **opts))
    wave = song.tables["WTBL"]
    rec = next(i for i in song.instruments
               if i.name.startswith("0E:") and (i.ad, i.sr) != (0, 0))
    voices = instrument_voices(song.tracks, song.patterns)
    assert set(voices[rec.number]) == {0}, "record $0E is voice 1's alone"

    def block(i):
        out = []
        for left, right in wave[i.wave_ptr - 1:]:
            out.append((left, right))
            if left == 0xFF:
                break
        return out

    # voice 1 keeps the waveform the player leaves on it: no hit in its program
    assert not any(e == (0x81, 0xC9) for e in block(rec))
    # one click clone of it, AD/SR 0, silent first frame, hit on the first call
    clones = [i for i in song.instruments
              if i.name.startswith("0E:") and (i.ad, i.sr) == (0, 0)]
    assert len(clones) == 1
    c = clones[0]
    assert c.firstwave == 0x08 and (c.vib_ptr, c.pulse_ptr) == (0, 0)
    assert block(c)[0] == (0x81, 0xC9) and block(c)[-1][0] == 0xFF
    # and it is played on voice 3 only, over the rest rows of the stretch
    assert set(voices[c.number]) == {2}
    rows = [(pn, k // 4) for pn, p in enumerate(song.patterns)
            for k in range(1, len(p), 4) if p[k] == c.number]
    assert len(rows) == 1 and rows[0][1] == 0, "the rest row 0 of one copy"
    # that copy is the 33-row rest pattern, played eight times in a row
    track = next(t for t in song.tracks if rows[0][0] in t)
    played = [p for p in plays(track, song.patterns)[0] if p[2] == rows[0][0]]
    assert len(played) == 8


@pytest.mark.skipif(not os.path.exists(os.path.join(CORPUS, "Thundercats.sid"))
                    or not os.path.exists(PRESETS),
                    reason="corpus or presets.json absent")
def test_without_the_reading_the_hit_is_back_on_the_record_and_no_tick_voice(
        monkeypatch):
    """The short circuit: say no record is stray and Thundercats is what it
    was -- the hit in `$0E`'s own program (voice 1), no clone, no click."""
    import songview
    import h2g.goatwriter.wavetable as wavetable
    import h2g.goatwriter.sfx_tick_voice as tick
    from fidelity import _preset_opts
    from h2g.convert import convert
    monkeypatch.setattr(wavetable, "stray_drum_record", lambda *a: False)
    monkeypatch.setattr(tick, "stray_drum_record", lambda *a: False)
    opts = _preset_opts(json.load(open(PRESETS)), "Thundercats.sid")
    song = songview.parse_sng(convert(os.path.join(CORPUS, "Thundercats.sid"),
                                      log=lambda m: None, **opts))
    wave = song.tables["WTBL"]
    rec = next(i for i in song.instruments if i.name.startswith("0E:"))
    assert (0x81, 0xC9) in wave[rec.wave_ptr - 1:rec.wave_ptr + 6]
    assert sum(1 for i in song.instruments
               if i.name.startswith("0E:") and (i.ad, i.sr) == (0, 0)) == 0
