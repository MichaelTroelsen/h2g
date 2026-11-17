"""The tabled alternation restarts its toggle on a REST (`rest_wave_restart`,
an opt-in per-song option: off writes no byte).

W_A_R `$E4F7 STA $E93F,X` zeroes the per-voice counter whose low bit picks
the waveform (`$E763 LDA $E93F,X / AND #$01`), and it does so in the fetch a
rest shares with a note: the bit-6 test (`$E512 BVS $E552`) comes after it. A
Goattracker KEYOFF leaves the previous note's wavetable program running in
whatever phase it was in, so across a rest ours toggled opposite to the
original for the whole span to the next event -- W_A_R voice 2's `10 80 10 80`
against `80 10 80 10` for 280 frames, and Knucklebusters voice 1's `10 10 10
80` slips that ours never made. `CMD_SETWAVEPTR` on the KEYOFF row is the
restart.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
import fidelity as F                                         # noqa: E402
import songview                                              # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import rest_wave_restart as RW           # noqa: E402
from h2g.goatwriter import _wave_alternate_entries           # noqa: E402
from h2g.goatwriter.constants import (CMD_SETTEMPO,           # noqa: E402
                                      CMD_SETWAVEPTR, GT_KEYOFF,
                                      WAVE_NOTE_KEEP)

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"


def _run(entries, pointer, calls, held=0x00):
    """The waveform on each of `calls` play calls from a pointer, as
    gplay.c:697-745 steps it: a waveform entry is one call, a delay entry
    `value + 1` calls holding what is set, a jump costs none."""
    out, ptr, wait, cur = [], pointer, 0, held
    while len(out) < calls:
        left, right = entries[ptr - 1]
        if left <= 0x0F:
            out.append(cur)
            if wait != left:
                wait += 1
                continue
            wait = 0
        else:
            cur = left
            out.append(cur)
        ptr += 1
        if entries[ptr - 1][0] == 0xFF:
            ptr = entries[ptr - 1][1]
    return out


def _table(multiplier=1):
    left, right = _wave_alternate_entries(0x11, 0x81, multiplier, start=1,
                                          budget=16)
    return list(zip(left, right))


def test_the_block_is_the_notes_shape_with_no_pitch_of_its_own():
    table = _table()
    # lead 11, then the pair 11 / 81 looping
    assert table == [(0x11, 0), (0x11, 0), (0x81, 0), (0xFF, 2)]
    block = RW.restart_block(table, 1, delay=1)
    assert block == [(0x00, WAVE_NOTE_KEEP), (0x11, WAVE_NOTE_KEEP),
                     (0xFF, 2)]
    # a gated half BEFORE the loop target (the drum-gate shape) is frame 1's
    # and keeps its note
    gated = [(0x15, 0), (0x01, 0x80), (0x15, 0), (0x01, 0), (0x80, 0xB4),
             (0x01, 0xB4), (0x14, 0), (0x01, 0), (0xFF, 5)]
    assert RW.restart_block(gated, 1, delay=0) == [
        (0x15, WAVE_NOTE_KEEP), (0x01, 0x80), (0x15, 0), (0x01, 0),
        (0xFF, 5)]
    assert RW.restart_block(table, 1, delay=0)[0] == (0x11, WAVE_NOTE_KEEP)


@pytest.mark.parametrize("multiplier", [1, 3, 4])
def test_a_restart_sounds_the_players_shape_from_the_rest(multiplier):
    """Frame 0 the record's waveform, frame 1 the same, then the alternate on
    every other frame (`tri tri noi tri noi`), whatever the multiplier."""
    table = _table(multiplier)
    start = 1
    block = RW.restart_block(table, start, delay=0)
    entries = table + block
    ptr = len(table) + 1
    calls = _run(entries, ptr, 7 * multiplier, held=0x81)
    frames = [calls[k * multiplier] for k in range(7)]
    assert frames == [0x11, 0x11, 0x81, 0x11, 0x81, 0x11, 0x81]
    # ...and whatever was playing before does not matter: that is the point.
    again = _run(entries, ptr, 7 * multiplier, held=0x11)
    assert [again[k * multiplier] for k in range(7)] == frames


def test_a_delay_holds_the_waveform_already_set():
    table = _table()
    entries = table + RW.restart_block(table, 1, delay=2)
    calls = _run(entries, len(table) + 1, 6, held=0x81)
    assert calls[:2] == [0x81, 0x81]
    assert calls[2:5] == [0x11, 0x11, 0x81]


def _record(effect, alt, wave=0x11):
    return bytes([0, 0, wave, 0, 0, 0, 0, effect])


class _Det:
    wave_alternate = 8
    instr_start = 0
    instr_stride = 9


def test_only_a_record_whose_program_is_the_alternation_is_named():
    table = _table()
    data = bytearray(18)
    data[0:8] = _record(0x02, 0x81)      # record 0 (GT 1): bit $02
    data[9:17] = _record(0x02, 0x81)     # record 1 (GT 2): bit $02
    data[8], data[17] = 0x81, 0x81
    sid = type("S", (), {"data": bytes(data)})()
    # record 0 has the program, record 1 has no wave start at all
    assert RW.alternating_records(sid, _Det, table, [1, 0], 2, 0) == {1: 1}
    # the bit is clear: nothing to restart
    clear = bytearray(data)
    clear[7] = 0
    sid0 = type("S", (), {"data": bytes(clear)})()
    assert RW.alternating_records(sid0, _Det, table, [1, 0], 2, 0) == {}
    # an alternate that equals the record's own waveform alternates with itself
    flat = [(0x11, 0), (0x11, 0), (0x11, 0), (0xFF, 2)]
    assert RW.alternating_records(sid, _Det, flat, [1, 0], 2, 0) == {}


def test_a_keyoff_row_with_a_free_column_gets_the_pointer_and_nothing_else():
    table = _table()
    data = bytearray(9)
    data[0:8] = _record(0x02, 0x81)
    data[8] = 0x81
    sid = type("S", (), {"data": bytes(data)})()
    NOTE = 0x60
    pattern = [NOTE, 1, 0, 0,
               0xBD, 0, 0, 0,
               GT_KEYOFF, 0, 0, 0,           # free: written
               NOTE, 1, 0, 0,
               GT_KEYOFF, 0, CMD_SETTEMPO, 5,    # taken: left alone
               0xFF, 0, 0, 0]
    pats, tracks, written, entries = RW.rest_wave_restarts(
        sid, _Det, [[0, 0xFF, 0]], [pattern], table, [1], 1, 0, delay=0)
    assert written == 1
    assert pats[0][4 * 2 + 2:4 * 2 + 4] == [CMD_SETWAVEPTR, len(table) + 1]
    assert pats[0][4 * 4 + 2:4 * 4 + 4] == [CMD_SETTEMPO, 5]
    assert entries[len(table):] == RW.restart_block(table, 1, delay=0)


def _sng(name, **extra):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, name)
    opts["pack"] = False
    opts.update(extra)
    import inspect
    sig = inspect.signature(convert).parameters
    opts = {k: v for k, v in opts.items() if k in sig}
    return songview.parse_sng(convert(str(CORPUS / name), log=lambda s: None,
                                      **opts))


def _restart_rows(song):
    n = 0
    for pat in song.patterns:
        for r in range(0, len(pat) - 3, 4):
            if pat[r] == GT_KEYOFF and pat[r + 2] == CMD_SETWAVEPTR:
                n += 1
    return n


@needs_corpus
@pytest.mark.parametrize("name, rows", [("W_A_R.sid", 6),
                                        ("W_A_R_Preview.sid", 2),
                                        ("Knucklebusters.sid", 3)])
def test_the_named_songs_restart_on_their_rests(name, rows):
    """Pattern rows written with the option on (the converter's log counts
    them per orderlist position: 6 / 4 / 168). The pointers name a block in
    the wavetable whose lead carries no pitch."""
    song = _sng(name, rest_wave_restart=True)
    # rest_two_stage writes the same KEYOFF + CMD_SETWAVEPTR shape on its own
    # records (W_A_R_Preview, Zoolook), so count against the option-off build.
    assert _restart_rows(song) - _restart_rows(
        _sng(name, rest_wave_restart=False)) == rows
    wtbl = song.tables["WTBL"]
    ptrs = {pat[r + 3] for pat in song.patterns
            for r in range(0, len(pat) - 3, 4)
            if pat[r] == GT_KEYOFF and pat[r + 2] == CMD_SETWAVEPTR}
    assert ptrs
    for p in ptrs:
        # either a block of ours (every row up to its jump carries no pitch)
        # or, where the table had no room, the record's own start
        k, block = p - 1, []
        while wtbl[k][0] != 0xFF:
            block.append(wtbl[k])
            k += 1
        assert block, "a pointer on a jump names nothing"
        own = p in {i.wave_ptr for i in song.instruments}
        first = next(r for lft, r in block if lft > 0x0F)
        assert first == WAVE_NOTE_KEEP or own,             "the fetch frame's write carries no pitch of its own"


@needs_corpus
def test_a_file_without_the_alternation_is_untouched():
    name = "Commando.sid" if (CORPUS / "Commando.sid").exists()         else "Rasputin.sid"
    assert _restart_rows(_sng(name, rest_wave_restart=True)) == 0


@needs_corpus
@pytest.mark.parametrize("name", ["W_A_R.sid", "W_A_R_Preview.sid",
                                  "Knucklebusters.sid", "Zoolook.sid"])
def test_the_option_off_writes_no_restart_row(name):
    """SABOTAGE TARGET: build_sng running the pass without the flag writes
    rows here. Off is the default and reproduces the bytes before the option.
    The shipped conversion writes restart rows exactly where presets.json
    carries the key (W_A_R and W_A_R_Preview since v0.5.670)."""
    shipped = F._preset_opts(json.loads(PRESETS.read_text(encoding="utf-8")),
                             name).get("rest_wave_restart", False)
    # Measured against the option-off build: rest_two_stage writes the same
    # row shape on its own records, so an absolute count is not this pass's.
    off = _restart_rows(_sng(name, rest_wave_restart=False))
    assert (_restart_rows(_sng(name)) > off) == bool(shipped)
    assert _restart_rows(_sng(name, rest_wave_restart=True)) > off
