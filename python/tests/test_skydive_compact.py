"""The skydive program in a third of the rows, and the table made room for it
(`goatwriter.skydive`: `skydive_compact_calls`, `compact_wave_tail`).

Last_V8 and its C128 version were declined for the wavetable alone ("124 / 122
wavetable step(s) past MAX_TABLELEN"): 217 of 255 rows in use, and the 30-store
fall of a 31-tick note needs a step for every call of every frame at -S2. Two
things make it fit, each tried only after the layout before it failed, so a
file the plain layout fits (Master_of_Magic, One_Man_and_his_Droid, every -S1
file) keeps its bytes:

* the held alternating program steps ONE `F2` of the frame's whole movement
  on the first call of a fall frame and leaves the rest still, and a note
  frame is a relative-note-0 step on its first and last call with the calls
  between a delay that folds into the last step (3 rows a pair of frames at
  -S2, not 4);
* the identical programs at the end of the table are one copy (thirteen drum
  records are the same 5 rows), 60 rows freed.

Measured at -t 180 under presets (siddump, lag-aligned, frames on which the
original's gated high byte sits below its note's): Last_V8 voice 0 74/238 ->
184/238 (every skydive window of it; the 54 left are a drop that is not a
store and a pitch the converter has wrong with or without the program),
Last_V8_C128_version 72/238 -> 128/238 (its note table is tuned a hair
differently from Goattracker's, so a window on some notes reads one high byte
up).
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_MAX_TABLELEN)

import test_skydive_multispeed as M                          # noqa: E402

NOTE = (0x00, 0x00)


def _speeds():
    """A speed_index that names rows 1.. in order of first use, and the
    table it built."""
    table = []

    def index(k):
        entry = S.skydive_speed(k)
        if entry not in table:
            table.append(entry)
        return table.index(entry) + 1
    return index, table


def _replay(entries, table, note, calls_per_frame, first_calls):
    """The voice's frequency after each frame of a program, a frame being
    `calls_per_frame` calls (the first `first_calls`). Vibrato ticks are
    ignored: both programs are compared on what they WRITE."""
    freq, out, call = note, [], 0
    steps = S.instrument_calls(entries, 1)
    assert steps is not None
    ends = []
    edge = first_calls
    while edge <= len(steps):
        ends.append(edge)
        edge += calls_per_frame
    for i, step in enumerate(steps, 1):
        if step is not None:
            left, right = step
            if left == 0xF2:
                hi, lo = table[right - 1]
                freq -= hi << 8 | lo
            elif left == 0xF1:
                hi, lo = table[right - 1]
                freq += hi << 8 | lo
            else:
                assert (left, right) == NOTE, step
                freq = note
        if i in ends:
            out.append(freq)
    return out


def test_a_still_run_ending_on_the_note_step_is_one_delay_entry():
    calls = [NOTE, None, None, NOTE, None, NOTE]
    plain = S._compress(calls)
    folded = S._compress(calls, fold_apply=True)
    # the same calls, read the way the player reads them
    assert (S.instrument_calls(folded, 1) == S.instrument_calls(plain, 1)
            == [NOTE, None, None, NOTE, None, NOTE])
    assert folded == [NOTE, (0x02, 0x00), (0x01, 0x00), (0xFF, 0x00)]
    assert len(plain) - len(folded) == 2
    # not on by default: a program laid out before this keeps its bytes
    assert S._compress(calls) == plain
    # a run longer than a delay entry holds is split before the step
    long_run = [None] * 20 + [NOTE]
    got = S._compress(long_run, fold_apply=True)
    assert S.instrument_calls(got, 1) == S.instrument_calls(
        S._compress(long_run), 1)
    assert len(got) == 3                       # 5 still, 15 still + step, stop


def test_the_compact_program_is_three_rows_a_pair_of_frames_at_s2():
    index, table = _speeds()
    got = S.skydive_program(2, 4, True, index, 2, compact=True)
    assert got[:7] == [NOTE] * 7                      # frames 0-3, 1 + 6 calls
    # F2 of the whole movement, one still
    # call folded into the step before the note, then the step
    assert got[7:10] == [(0xF2, 0x01), (0x01, 0x00), NOTE]
    assert got[10:13] == [(0xF2, 0x02), (0x01, 0x00), NOTE]
    assert got[13:16] == [(0xF2, 0x03), (0x01, 0x00), NOTE]
    assert got[-1] == (0xFF, 0x00)
    assert table == [(1, 0), (2, 0), (3, 0)]           # the -S1 rates
    whole = S.skydive_program(2, 30, True, index, 2, compact=True)
    plain = S.skydive_program(2, 30, True, lambda k: 0x40 + k, 2)
    assert len(plain) == 124 and len(whole) == 95, (len(plain), len(whole))


def test_compact_is_not_asked_for_at_s1_or_for_the_holding_program():
    index = lambda k: 0x40 + k                               # noqa: E731
    for args in ((1, 5, True, index, 1), (0, 5, False, index, 2)):
        assert (S.skydive_program(*args, compact=True)
                == S.skydive_program(*args))


@pytest.mark.parametrize("phase,writes", [(0, 5), (1, 9), (2, 30)])
def test_compact_and_plain_leave_the_voice_in_the_same_place_at_every_frame(
        phase, writes):
    """What siddump samples is the last call of a frame. Replaying both
    programs call by call (vibrato ticks aside): the same frequency at the
    end of every frame -- the fall `$100 * k` below the note on a store,
    exactly the note between."""
    note = 0x4D28
    m, first = 2, 1
    idx, table = _speeds()
    compact = S.skydive_program(phase, writes, True, idx, m, compact=True)
    got = _replay(compact, table, note, m, first)

    plain_table = []

    def plain_index(k):
        entry = S.skydive_speed(k, m)
        if entry not in plain_table:
            plain_table.append(entry)
        return plain_table.index(entry) + 1
    plain = S.skydive_program(phase, writes, True, plain_index, m)
    want = _replay(plain, plain_table, note, m, first)
    assert got == want
    # and it is what the original's block stores: k high bytes down on the
    # k-th store
    fall = [note - 0x100 * k for k in range(1, writes)]
    assert [f for f in got if f != note] == fall


def test_the_tail_programs_are_shared_and_the_starts_follow():
    drum = [(0x00, 0x00), (0x00, 0x00), (0x01, 0x00), (0xFF, 0x00),
            (0xFF, 0x00)]
    other = [(0x41, 0x00)] * 3 + [(0xFF, 0x00)] * 2
    entries = other + drum + drum + other + drum
    starts = [1, 6, 11, 16, 21]
    got = S.compact_wave_tail(entries, starts, [])
    assert got is not None
    new_entries, new_starts = got
    assert new_entries == other + drum
    assert new_starts == [1, 6, 6, 1, 6]
    # every record still reads the program it had
    for old, new in zip(starts, new_starts):
        assert new_entries[new - 1:new + 4] == entries[old - 1:old + 4]


def test_a_tail_something_else_points_into_is_not_rebuilt():
    drum = [(0x00, 0x00), (0x01, 0x00), (0xFF, 0x00)]
    entries = [(0x41, 0x00), (0xFF, 0x00)] + drum + drum
    starts = [1, 3, 6]
    assert S.compact_wave_tail(entries, starts, []) is not None
    # a pattern's CMD_SETWAVEPTR / an arpeggio start at row 6
    assert S.compact_wave_tail(entries, starts, [6]) is None
    # a jump from before the tail into it
    jumpy = [(0x41, 0x00), (0xFF, 0x03)] + drum + drum
    assert S.compact_wave_tail(jumpy, starts, []) is None
    # a jump to a row inside the tail moves with the rows: refused; to 0 is a
    # stop and stays
    looped = [(0x41, 0x00), (0xFF, 0x00)] + [(0x00, 0x00), (0xFF, 0x03)] * 2
    assert S.compact_wave_tail(looped, [1, 3, 5], []) is None


def test_a_table_with_nothing_to_share_is_left_alone():
    entries = [(0x41, 0x00), (0xFF, 0x00), (0x11, 0x00), (0xFF, 0x00)]
    assert S.compact_wave_tail(entries, [1, 3], []) is None


@needs_corpus
@pytest.mark.parametrize("name,steps", [("Last_V8", 95),
                                        ("Last_V8_C128_version", 98)])
def test_both_last_v8s_fit_in_compact_form_in_a_shared_table(name, steps):
    sng, lines = M._converted(name)
    (msg,) = M._sky(lines)
    assert "not emitted" not in msg, msg
    assert f"{steps} wavetable step(s)" in msg, msg
    assert "compact (3 rows a pair of frames)" in msg, msg
    assert "60 row(s) made by sharing identical programs" in msg, msg
    import songview
    song = songview.parse_sng(sng)
    wt = song.tables["WTBL"]
    assert len(wt) <= GT_MAX_TABLELEN
    assert len({p[r + 3] for p in song.patterns for r in range(0, len(p), 4)
                if p[r + 2] == CMD_SETWAVEPTR}) >= 1


@needs_corpus
def test_every_instrument_still_plays_the_program_it_had(monkeypatch):
    """Sharing moves instrument starts and nothing else: read back from the
    song, each instrument's program (up to its stop) is the one the layout
    without sharing gave it."""
    import songview

    def programs(sng):
        song = songview.parse_sng(sng)
        wt = song.tables["WTBL"]
        out = []
        for ins in song.instruments:
            at = ins.wave_ptr
            prog = []
            while at and at <= len(wt):
                prog.append(wt[at - 1])
                if wt[at - 1][0] == 0xFF:
                    break
                at += 1
            out.append(prog)
        return out, len(wt)

    shared, size = programs(M._converted("Last_V8")[0])
    monkeypatch.setattr(S, "compact_wave_tail", lambda *a, **k: None)
    unshared, plain_size = programs(M._converted("Last_V8")[0])
    assert shared == unshared
    assert plain_size == 217 and size == 217 - 60 + 95


@needs_corpus
def test_the_instrument_records_are_written_with_the_shared_starts(monkeypatch):
    """The starts `compact_wave_tail` returns are the ones the instrument
    records carry. (Last_V8's used instruments sit ahead of the shared tail,
    so a plan that moved them is faked: record 1 is sent to row 2.)"""
    import songview
    real = S.compact_wave_tail

    def moved(entries, starts, pointers):
        got = real(entries, starts, pointers)
        assert got is not None
        shared, new = got
        return shared, [2] + new[1:]
    monkeypatch.setattr(S, "compact_wave_tail", moved)
    sng, lines = M._converted("Last_V8")
    assert "sharing identical programs" in M._sky(lines)[0]
    assert songview.parse_sng(sng).instruments[0].wave_ptr == 2


@needs_corpus
def test_the_other_s2_files_keep_their_bytes_and_their_plain_layout():
    for name in ("Master_of_Magic", "One_Man_and_his_Droid"):
        _sng, lines = M._converted(name)
        (msg,) = M._sky(lines)
        assert "compact" not in msg and "sharing" not in msg, msg


@needs_corpus
@M.needs_siddump
@M.needs_gt2reloc
def test_last_v8s_falls_name_the_originals_high_byte_frame_for_frame(
        tmp_path, monkeypatch):
    """Last_V8, packed at -S2 and traced at -m2, 90 s: the four 28-store
    windows (frames 3527, 3783, 4039, 4295) read the original's high byte on
    every store; without the plan, almost none."""
    seconds = 90
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "Last_V8.sid", seconds, 0)
    stores = {f: hi for f, hi in M._store_frames(orig, n)[0].items()
              if f >= 3500}
    assert len(stores) >= 100, len(stores)

    def agree(sub):
        sng, _ = M._converted("Last_V8")
        work = tmp_path / sub
        work.mkdir()
        packed = fidelity.pack_sid(sng, work, multiplier=2)
        assert packed is not None and packed.exists(), sub
        ours = fidelity.run_siddump(packed, seconds + 1, 0, calls=2)
        lag = fidelity.startup_lag(orig, ours)[0]
        fq = fidelity.register_timeline(ours[0].freq_events, n + lag)
        return sum(fq[f + lag] >> 8 == hi for f, hi in stores.items())

    assert agree("emitted") == len(stores)
    monkeypatch.setattr(S, "skydive_plan", lambda *a, **k: None)
    assert agree("without") <= len(stores) // 10
