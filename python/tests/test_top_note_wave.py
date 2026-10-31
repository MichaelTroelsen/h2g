"""A note above Goattracker's note column is played from the wavetable.

Spellbound's sweep ends on `00 5F`: entry 95 of the player's 96-entry table
(`$FD2E`). The note column stops at index 92, so the decoder clamped it and
the conversion played `$DD0E`. `_build_raw_pattern` now records the rows
(`top_rows`), `convert_patterns` files them under the slice's note column
(`top_cols`), and `past_table_wave` points each row at a copy of its wave
program pinned to the entry.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W  # noqa: E402
from h2g import patterns as P  # noqa: E402
from h2g.goatwriter.appending import _Song, _parse_song  # noqa: E402
from h2g.goatwriter.constants import HEADER_LEN  # noqa: E402

CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")


# --- the decoder -----------------------------------------------------------

def _events(stream: bytes, **kw):
    top: dict = {}
    events = P._build_raw_pattern(bytes([0, 0]) + stream, 2, top_rows=top, **kw)
    return events, top


def test_the_decoder_records_each_entry_above_92_and_clamps_the_note():
    # wait 0 notes $5C, $5D, $5E, $5F, $5B, then the terminator.
    events, top = _events(bytes([0, 0x5C, 0, 0x5D, 0, 0x5E, 0, 0x5F, 0, 0x5B, 0xFF]))
    notes = [events[k] for k in range(0, len(events) - 4, 4)]
    assert notes == [0xBC, 0xBC, 0xBC, 0xBC, 0xBB]
    assert top == {1: 1, 2: 2, 3: 3}          # not $5C itself, not $5B


def test_asking_for_the_record_moves_no_byte():
    stream = bytes([0, 0x5F, 0, 0x30, 0xFF])
    got, _ = _events(stream)
    assert got == P._build_raw_pattern(bytes([0, 0]) + stream, 2)


def test_a_shifted_table_that_puts_the_note_past_95_is_not_recorded():
    # note_base 2: $5F would be index 97, which no wave step can name.
    _, top = _events(bytes([0, 0x5F, 0xFF]), note_base=2)
    assert top == {}


def test_note_column_drops_the_ending_rows():
    assert P.note_column([0x60, 0, 0, 0, 0xFF, 0, 0, 0]) == (0x60,)


def test_a_column_two_slices_share_with_different_records_is_in_dispute():
    cols: dict = {}
    five_c = [0xBC, 0, 0, 0, 0xFF, 0, 0, 0]
    P._record_top(cols, five_c, {}, 0, 1)                  # raw $5C: no record
    P._record_top(cols, five_c, {0: 3}, 0, 1)              # raw $5F
    assert cols[(0xBC,)] is None
    assert W.top_rows_of(cols) == {}
    # A transposed variant holding a top note is unknown, not empty.
    cols = {}
    P._record_top(cols, five_c, None, 0, 1)
    assert cols[(0xBC,)] is None
    P._record_top(cols := {}, [0x60, 0, 0, 0, 0xFF, 0, 0, 0], None, 0, 1)
    assert cols[(0x60,)] == frozenset()


# --- the pass --------------------------------------------------------------

def _det():
    return SimpleNamespace(freq_table=SimpleNamespace(length=96), note_base=0)


def _song(rows, wave, trans=0):
    rec = bytearray(25)
    rec[2] = 1
    pat = bytearray(b for row in rows for b in row)
    order = ([0xF0 + trans] if trans else []) + [0, 0xFF, 0]
    return _Song(b"GTS5", b"GTS5" + bytes(HEADER_LEN - 4), [bytes(order)] * 3,
                 [rec], [list(wave), [], [], []], [pat])


def _top(song, deltas):
    return {P.note_column(song.patterns[0]): deltas}


@pytest.fixture(autouse=True)
def _cell(monkeypatch):
    monkeypatch.setattr(W, "_cell_entry", lambda sid, det, index: 0)


_PROGRAM = [(0x11, 0x00), (0x03, 0x80), (0x11, 0x7B), (0xFF, 1)]   # note, hold, -5


def test_a_top_row_points_at_a_copy_pinned_to_the_entry():
    song = _song([[0x60 + 92, 1, 0, 0], [0x60 + 40, 1, 0, 0]], _PROGRAM)
    changed = W.retarget_mixed_steps(song, None, _det(), None, None,
                                     _top(song, {0: 3}))
    assert changed
    wave = song.tables[0]
    assert wave[:4] == _PROGRAM                           # the original, untouched
    # 92 + 3 = 95, and the -5 step is 90: every relative step absolute.
    assert wave[4:] == [(0x11, 0x80 | 95), (0x03, 0x80), (0x11, 0x80 | 90),
                        (0xFF, 5)]
    assert list(song.patterns[0][0:4]) == [0x60 + 92, 1, 8, 5]
    assert list(song.patterns[0][4:8]) == [0x60 + 40, 1, 0, 0]   # not touched


def test_without_a_record_the_same_row_is_left_alone():
    song = _song([[0x60 + 92, 1, 0, 0]], _PROGRAM)
    assert W.retarget_mixed_steps(song, None, _det()) is False
    assert W.retarget_mixed_steps(song, None, _det(), None, None, {}) is False
    assert len(song.tables[0]) == 4


def test_the_orderlist_transpose_is_added_to_the_entry():
    song = _song([[0x60 + 80, 1, 0, 0]], _PROGRAM, trans=-2)
    W.retarget_mixed_steps(song, None, _det(), None, None, _top(song, {0: 2}))
    # 80 - 2 = 78 is where the column puts it; the record adds 2.
    assert song.tables[0][4] == (0x11, 0x80 | 80)


def test_a_row_with_its_command_column_taken_stays_on_the_clamp():
    song = _song([[0x60 + 92, 1, 3, 0]], _PROGRAM)       # CMD_TONEPORTA
    log: list = []
    assert W.retarget_mixed_steps(song, None, _det(), log.append, None,
                                  _top(song, {0: 3})) is False
    assert "command column in use" in log[0]
    assert list(song.patterns[0][0:4]) == [0x60 + 92, 1, 3, 0]


def test_the_note_the_voice_keeps_is_the_column_note_not_the_entry():
    # A later pointer row with no note of its own plays the voice's note: 92.
    rows = [[0x60 + 92, 1, 0, 0], [0, 0, 8, 1]]
    song = _song(rows, [(0x11, 0x00), (0xFF, 1)])
    walked = [r for _t, _p, _b, rr in W._walk(song, _top(song, {0: 3}))
              for r in rr]
    assert sorted({(r[2], r[4]) for r in walked}) == [(92, 0), (95, 3)]


def test_a_held_file_is_not_touched():
    assert "Commando" in W.HELD


# --- the corpus ------------------------------------------------------------

def _convert(name, **override):
    import json
    import fidelity as F
    from h2g.convert import convert
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    lines: list = []
    blob = convert(str(CORPUS / name), log=lines.append,
                   **{**F._preset_opts(doc, name), **override})
    return blob, lines


@pytest.mark.skipif(not (CORPUS / "Spellbound.sid").exists(),
                    reason="the Hubbard corpus is not on this machine")
def test_spellbound_plays_the_sweep_top_from_a_pinned_program():
    blob, lines = _convert("Spellbound.sid")
    song = _parse_song(blob)
    wave = song.tables[0]
    # Every top row points at a program whose first step is the absolute
    # entry 93, 94 or 95 -- and the sweep's own top row is 95.
    pointed, entries = 0, set()
    for pat in song.patterns:
        for k in range(0, len(pat) - 3, 4):
            nt, _ins, cmd, data = pat[k:k + 4]
            if nt == 0xBC and cmd & 0x0F == 8:
                assert 0x80 | 93 <= wave[data - 1][1] <= 0x80 | 95
                entries.add(wave[data - 1][1] & 0x7F)
                pointed += 1
    assert pointed == 16 and 95 in entries
    assert any("Past-table wave split" in m and "16 note row(s)" in m
               for m in lines)


@pytest.mark.skipif(not (CORPUS / "Commando.sid").exists(),
                    reason="the Hubbard corpus is not on this machine")
def test_commando_keeps_the_clamp():
    # The held arm: presets.json lifts the hold for the corpus rip
    # (`release_held_stored_wave`, user decision 2026-10-31); the fixture,
    # converted without presets, keeps it.
    blob, lines = _convert("Commando.sid", release_held_stored_wave=False)
    assert not any("Past-table wave split" in m for m in lines)
