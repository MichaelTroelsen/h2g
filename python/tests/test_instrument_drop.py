"""`drop_unnamed_instruments`: no instrument record that no pattern names.

Knucklebusters' source record 27 -- $00 $00, pulse width $000, an EMPTY
wavetable block -- was written as instrument 28 (name prefix `1D:`, which is
record + 2, see goatwriter._write_instruments) and is named by no pattern.
The option drops it and every other such slot, keeps instrument 1 (both
players start every voice on it: gplay.c:62, player.s:621), and renumbers the
instrument columns -- the tempo-duty / phase / drum clones appended after the
source records included.
"""
import json
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus          # noqa: E402
import fidelity as F                             # noqa: E402
from h2g.convert import convert                  # noqa: E402
from h2g.instrument_drop import (                # noqa: E402
    drop_unnamed_instruments, named_instruments)
from songview import parse_sng                   # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
KNUCKLE = "Knucklebusters.sid"
# Record 27's name prefix: `{record + 2:02X}` in _write_instruments.
RECORD_27 = f"{27 + 2:02X}:"


def _quiet(_msg):
    pass


def _presets():
    return json.loads(PRESETS.read_text(encoding="utf-8"))


def _convert(name, **extra):
    opts = F._preset_opts(_presets(), name)
    # presets.json's always block turns the drop on since v0.5.495; every
    # test here compares an explicit off control against an explicit on.
    opts["drop_unnamed_instruments"] = False
    opts.update(extra)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return convert(str(CORPUS / name), log=_quiet, **opts)


def _rows(song):
    """(pattern, row, instrument) for every non-zero instrument column."""
    for p, body in enumerate(song.patterns):
        for r in range(0, len(body), 4):
            if body[r + 1]:
                yield p, r // 4, body[r + 1]


def _canon(tab, ptr):
    """The pulse / filter program entered at `ptr`, rows renamed by first
    visit: two layouts of the same program compare equal, a program that
    differs (a row, a jump target) does not."""
    if not ptr:
        return None
    ids, order, stack = {}, [], [ptr]
    while stack:
        r = stack.pop()
        if r == 0 or r in ids or not 1 <= r <= len(tab):
            continue
        ids[r] = len(ids)
        order.append(r)
        stack.append(tab[r - 1][1] if tab[r - 1][0] == 0xFF else r + 1)
    return tuple((l, ids.get(rt, -1) if rt else 0) if l == 0xFF
                 else (l, rt, ids.get(r + 1, -2))
                 for r in order for l, rt in [tab[r - 1]])


def _wprog(song, ptr):
    """The wavetable program entered at `ptr`, relocation-normalised: rows
    numbered in the order they are reached, jump targets by that number, a
    pulse / filter pointer by the program it enters. The blocks of the dropped
    records go with them (`goatwriter.dead_blocks`), so the rows of the others
    move and their programs do not."""
    if not ptr:
        return ()
    wave = song.tables["WTBL"]
    num, order, i = {ptr: 0}, [ptr], 0
    while i < len(order):
        left, right = wave[order[i] - 1]
        i += 1
        succ = [] if left == 0xFF else [order[i - 1] + 1]
        if left in (0xFF, 0xF8) and right:
            succ.append(right)
        for t in succ:
            if 1 <= t <= len(wave) and t not in num:
                num[t] = len(order)
                order.append(t)
    out = []
    for r in order:
        left, right = wave[r - 1]
        if left in (0xFF, 0xF8) and right:
            right = ("->", num.get(right, -1))
        elif 0xF0 <= left <= 0xFE:
            right = _operand(song, left & 0xF, right)
        out.append((left, right))
    return tuple(out)


def _operand(song, cmd, data):
    """A pattern or wavetable command operand, a pulse / filter / wave
    pointer replaced by the program it enters."""
    if data and cmd == 8:
        return ("W", _wprog(song, data))
    if data and cmd == 9:
        return ("P", _canon(song.tables["PTBL"], data))
    if data and cmd == 0x0A:
        return ("F", _canon(song.tables["FTBL"], data))
    return data


def _record(song, number):
    i = song.instruments[number - 1]
    return (i.ad, i.sr, _wprog(song, i.wave_ptr),
            _canon(song.tables["PTBL"], i.pulse_ptr),
            _canon(song.tables["FTBL"], i.filt_ptr), i.vib_ptr,
            i.vib_delay, i.gatetimer, i.firstwave, i.name)


def _assert_same_music(before: bytes, after: bytes):
    """Everything but the dropped slots is the same, row for row. The pulse
    and filter tables are compared by the programs the pointers enter: the
    drop removes the rows only a dropped record reaches."""
    a, b = parse_sng(before), parse_sng(after)
    assert a.tracks == b.tracks
    assert a.tables["STBL"] == b.tables["STBL"]
    # The wavetable shrinks too (the blocks of the dropped records go); what
    # each kept record and each CMD_SETWAVEPTR plays is compared below.
    assert len(b.tables["WTBL"]) <= len(a.tables["WTBL"])
    assert len(a.patterns) == len(b.patterns)
    assert [len(p) for p in a.patterns] == [len(p) for p in b.patterns]
    for pa, pb in zip(a.patterns, b.patterns):
        for r in range(0, len(pa), 4):
            assert (pa[r], pa[r + 2], _operand(a, pa[r + 2], pa[r + 3])) == \
                (pb[r], pb[r + 2], _operand(b, pb[r + 2], pb[r + 3]))
            assert (pa[r + 1] == 0) == (pb[r + 1] == 0)
    n = len(a.instruments)
    for (p, r, ins_a), (_, _, ins_b) in zip(_rows(a), _rows(b)):
        if ins_a <= n:
            assert _record(a, ins_a) == _record(b, ins_b), (p, r, ins_a, ins_b)
    # Instrument 1 survives, unnamed or not.
    assert _record(a, 1) == _record(b, 1)
    # Exactly the named records survive, in order.
    named = named_instruments(before)
    kept = [k for k in range(1, n + 1) if k == 1 or k in named]
    assert [_record(a, k) for k in kept] == \
        [_record(b, k) for k in range(1, len(b.instruments) + 1)]


@needs_corpus
def test_knucklebusters_carries_no_instrument_for_record_27():
    off = _convert(KNUCKLE)
    on = _convert(KNUCKLE, drop_unnamed_instruments=True)
    names_off = [i.name for i in parse_sng(off).instruments]
    names_on = [i.name for i in parse_sng(on).instruments]
    # The control: without the option the slot is there and named by nothing.
    assert names_off.index("1D:00-00-00") + 1 == 28
    assert 28 not in named_instruments(off)
    assert not any(n.startswith(RECORD_27) for n in names_on), names_on
    # 29 written, GT 27-29 (records 26-28) named by no pattern.
    assert len(names_off) - len(names_on) == 3
    _assert_same_music(off, on)


@needs_corpus
def test_option_is_the_drop_applied_to_the_finished_bytes(monkeypatch):
    """The records go in the finished bytes; their wavetable blocks, earlier,
    in the build (`goatwriter.dead_blocks`), which is switched off here so
    the records' drop is seen alone."""
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    off = _convert(KNUCKLE)
    assert _convert(KNUCKLE, drop_unnamed_instruments=True) == \
        drop_unnamed_instruments(off)


@needs_corpus
@pytest.mark.parametrize("name", ["Human_Race.sid", "Hunter_Patrol.sid",
                                  "Sanxion.sid", "Zoids.sid"])
def test_clones_after_the_records_are_renumbered_not_dropped(name,
                                                             monkeypatch):
    """Files whose clones (appended after the source records) sit above a
    dropped record: each clone keeps its bytes and its rows follow it."""
    if name == "Hunter_Patrol.sid":
        # The rows its dead blocks free let 3 more skydive programs in
        # (speed table rows too), so on and off are no longer one song; the
        # renumbering is what is under test here.
        import h2g.goatwriter.dead_blocks as DB
        monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    off = _convert(name)
    on = _convert(name, drop_unnamed_instruments=True)
    a = parse_sng(off)
    assert len(a.instruments) > len(parse_sng(on).instruments)
    _assert_same_music(off, on)


def test_instrument_1_is_kept_and_dangling_stays_dangling():
    """A synthetic GTS5: 4 instruments, patterns name 3 and a dangling $09."""
    blob = bytearray(0x64)
    blob[0:4] = b"GTS5"
    blob += bytes([1, 0, 0, 0, 0, 0, 0])               # 1 subtune, 3 tracks
    blob.append(4)
    for k in range(1, 5):
        blob += bytes([k] * 9) + bytes(16)
    blob += bytes([0, 0, 0, 0])                         # four empty tables
    blob.append(1)
    blob.append(3)
    blob += bytes([0x60, 3, 0, 0, 0x61, 0, 0, 0, 0x62, 9, 0, 0])
    out = drop_unnamed_instruments(bytes(blob))
    song = parse_sng(out)
    assert [i.ad for i in song.instruments] == [1, 3]
    assert song.patterns[0][1::4] == [2, 0, 7]


def test_nothing_to_drop_is_byte_identical():
    blob = bytearray(0x64)
    blob[0:4] = b"GTS2"
    blob += bytes([1, 0, 0, 0, 0, 0, 0])
    blob.append(2)
    blob += bytes(25) * 2
    blob += bytes([0, 0, 0])
    blob += bytes([1, 1, 0x60, 2, 0, 0])
    assert drop_unnamed_instruments(bytes(blob)) == bytes(blob)


def test_commando_fixture_is_why_it_is_off_by_default():
    """The fixture carries instrument 13, named by no pattern: the option
    would move it, which is why it waits for presets.json's `always` block."""
    ref = (REPO / "Commando.sng").read_bytes()
    assert 13 not in named_instruments(ref)
    assert len(parse_sng(drop_unnamed_instruments(ref)).instruments) == \
        len(parse_sng(ref).instruments) - 1


# --- the pulse and filter blocks of dropped records ------------------------

def _tables_song(records, wave=(), pulse=(), filt=(), rows=(), fmt=b"GTS5"):
    """A synthetic song: `records` are (pulse_ptr, filter_ptr) pairs, record
    k's AD byte is k; `rows` are (instrument, command, data) pattern rows."""
    blob = bytearray(0x64)
    blob[0:4] = fmt
    blob += bytes([1, 0, 0, 0, 0, 0, 0])
    blob.append(len(records))
    for k, (p, f) in enumerate(records, 1):
        blob += bytes([k, 0, 0, p, f]) + bytes(20)
    for tab in (wave, pulse, filt) + ((() ,) if fmt == b"GTS5" else ()):
        blob.append(len(tab))
        blob += bytes(l for l, _ in tab) + bytes(r for _, r in tab)
    blob.append(1)
    blob.append(len(rows))
    for ins, cmd, data in rows:
        blob += bytes([0x60, ins, cmd, data])
    return bytes(blob)


def _pulse_ptrs(song):
    return [i.pulse_ptr for i in song.instruments]


def test_pulse_rows_only_a_dropped_record_reaches_are_removed():
    # record 2 is named by nothing; its block is rows 4-6, jumping to 4.
    pulse = [(0x81, 0x00), (0x02, 0x10), (0xFF, 1),
             (0x82, 0x00), (0x03, 0x20), (0xFF, 4),
             (0x83, 0x00), (0xFF, 7)]
    blob = _tables_song([(1, 0), (4, 0), (7, 0)], pulse=pulse,
                        rows=[(1, 0, 0), (3, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == [(0x81, 0), (0x02, 0x10), (0xFF, 1),
                                  (0x83, 0), (0xFF, 4)]
    assert _pulse_ptrs(out) == [1, 4]


def test_a_block_a_kept_record_shares_stays():
    pulse = [(0x81, 0x00), (0x02, 0x10), (0xFF, 1)]
    blob = _tables_song([(1, 0), (2, 0)], pulse=pulse, rows=[(1, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    # record 2 enters record 1's block part way; nothing is removed.
    assert out.tables["PTBL"] == pulse


def test_a_surviving_jump_is_retargeted_past_removed_rows():
    pulse = [(0x81, 0), (0xFF, 0), (0x82, 0), (0x83, 0), (0xFF, 4)]
    blob = _tables_song([(1, 0), (3, 0), (4, 0)], pulse=pulse,
                        rows=[(1, 0, 0), (3, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == [(0x81, 0), (0xFF, 0), (0x83, 0), (0xFF, 3)]
    assert _pulse_ptrs(out) == [1, 3]


def test_a_set_pulse_ptr_command_keeps_its_block_and_is_renumbered():
    pulse = [(0x81, 0), (0xFF, 0), (0x82, 0), (0xFF, 0), (0x83, 0), (0xFF, 0)]
    # record 2 (block 3-4) is dropped; a pattern's CMD_SETPULSEPTR names it.
    blob = _tables_song([(1, 0), (3, 0)], pulse=pulse, rows=[(1, 9, 3)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == pulse
    # without the command the block goes, and a SETPULSEPTR to the block
    # behind it follows its rows down.
    blob = _tables_song([(1, 0), (3, 0)], pulse=pulse, rows=[(1, 9, 5)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == [(0x81, 0), (0xFF, 0), (0x83, 0), (0xFF, 0)]
    assert out.patterns[0][3] == 3


def test_a_wavetable_set_pulse_ptr_row_keeps_its_block_and_is_renumbered():
    pulse = [(0x81, 0), (0xFF, 0), (0x83, 0), (0xFF, 0), (0x85, 0), (0xFF, 0)]
    wave = [(0xF9, 5), (0xFF, 0)]
    blob = _tables_song([(1, 0), (3, 0)], wave=wave, pulse=pulse,
                        rows=[(1, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    # record 2's rows 3-4 go; the wavetable row naming row 5 keeps 5-6.
    assert out.tables["PTBL"] == [(0x81, 0), (0xFF, 0), (0x85, 0), (0xFF, 0)]
    assert out.tables["WTBL"][0] == (0xF9, 3)


def test_filter_rows_only_a_dropped_record_reaches_are_removed():
    filt = [(0x80, 0x10), (0xFF, 0), (0x80, 0x20), (0xFF, 0)]
    blob = _tables_song([(0, 1), (0, 3)], filt=filt,
                        rows=[(1, 0, 0), (1, 0x0A, 3)])
    out = parse_sng(drop_unnamed_instruments(blob))
    # the command names row 3, which therefore stays; nothing to remove.
    assert out.tables["FTBL"] == filt
    blob = _tables_song([(0, 1), (0, 3)], filt=filt, rows=[(1, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["FTBL"] == [(0x80, 0x10), (0xFF, 0)]


def test_rows_no_record_reaches_are_left_as_written():
    pulse = [(0x81, 0), (0xFF, 0), (0x99, 0), (0xFF, 0)]
    blob = _tables_song([(1, 0), (0, 0)], pulse=pulse, rows=[(1, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == pulse


def test_gts2_without_a_speed_table_is_rewritten_too():
    pulse = [(0x81, 0), (0xFF, 0), (0x82, 0), (0xFF, 0)]
    blob = _tables_song([(1, 0), (3, 0)], pulse=pulse, rows=[(1, 0, 0)],
                        fmt=b"GTS2")
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == [(0x81, 0), (0xFF, 0)]


@needs_corpus
@pytest.mark.parametrize("name", ["Knucklebusters.sid", "Lion_Heart.sid",
                                  "Sanxion.sid"])
def test_the_drop_shrinks_the_pulse_table_and_keeps_every_program(name):
    off = _convert(name)
    on = _convert(name, drop_unnamed_instruments=True)
    a, b = parse_sng(off), parse_sng(on)
    assert len(b.tables["PTBL"]) < len(a.tables["PTBL"])
    _assert_same_music(off, on)


def test_a_kept_block_that_jumps_into_a_dropped_records_block_keeps_it():
    # record 1 (row 1) jumps to row 3, where dropped record 2 also enters.
    pulse = [(0x81, 0), (0xFF, 3), (0x82, 0), (0xFF, 0)]
    blob = _tables_song([(1, 0), (3, 0)], pulse=pulse, rows=[(1, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == pulse


def test_a_wavetable_pulse_row_keeps_a_block_a_dropped_record_also_enters():
    pulse = [(0x81, 0), (0xFF, 0), (0x82, 0), (0xFF, 0)]
    wave = [(0xF9, 3), (0xFF, 0)]
    blob = _tables_song([(1, 0), (3, 0)], wave=wave, pulse=pulse,
                        rows=[(1, 0, 0)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == pulse
    assert out.tables["WTBL"] == wave


def test_pulse_and_filter_pointers_are_renumbered_by_their_own_tables():
    # dropped record 2 owns 2 pulse rows and 5 filter rows.
    pulse = [(0x81, 0), (0xFF, 0), (0x82, 0), (0xFF, 0), (0x83, 0), (0xFF, 0)]
    filt = [(0x80, 1), (0xFF, 0), (0x80, 2), (0x00, 3), (0x00, 4), (0xFF, 0),
            (0x80, 5), (0xFF, 0)]
    blob = _tables_song([(1, 1), (3, 3), (5, 7)], pulse=pulse, filt=filt,
                        rows=[(1, 0, 0), (3, 0x0A, 7), (3, 9, 5)])
    out = parse_sng(drop_unnamed_instruments(blob))
    assert out.tables["PTBL"] == [(0x81, 0), (0xFF, 0), (0x83, 0), (0xFF, 0)]
    assert out.tables["FTBL"] == [(0x80, 1), (0xFF, 0), (0x80, 5), (0xFF, 0)]
    assert [(i.pulse_ptr, i.filt_ptr) for i in out.instruments] == \
        [(1, 1), (3, 3)]
    assert (out.patterns[0][6], out.patterns[0][7]) == (0x0A, 3)
    assert (out.patterns[0][10], out.patterns[0][11]) == (9, 3)
