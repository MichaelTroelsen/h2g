"""Bit $02's window-less rise on rows of THREE ticks (Crazy_Comets $5509,
Chimera $C661), through `goatwriter.note_rise`.

A store is every second tick and a row is three, so the stores walk across
the row: a row holds one store on tick 0, 1 or 2, or two stores on ticks 0 and
2, and the rows alternate one and two by their parity. Crazy_Comets voice 0 at
frame 481 (siddump; `5C` the note's high byte, DEC):

    5c 5f 5c 61 5b 5e 5a 5c 59 5f 58 61 57 5e 56 5c 55 5f 54 61 53 5e ...

-- the stores `5c 5c 5b 5a 59 58 ...` on every second frame from the third,
the vibrato (`5f 61 5e 5c`) on the frames between. Before this the planner
declined every such row ("rows not two ticks"): 24 in Crazy_Comets, 10 in
Chimera.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus
from test_note_rise import (_agreement, _converted, _run, needs_gt2reloc,
                            needs_siddump)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import note_rise as R                    # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      WAVECMD_PORTAUP)


def test_a_row_of_three_flips_the_store_phase_with_the_rows_parity():
    """`base + first + a * frames`: odd frames move the counter's parity with
    the row, even frames never do."""
    three = [R.store_phase(0x10, 3, a, 3) for a in range(6)]
    assert three[0::2] == [three[0]] * 3 and three[1::2] == [three[1]] * 3
    assert {three[0], three[1]} == {1, 2}
    two = [R.store_phase(0x10, 3, a, 2) for a in range(6)]
    assert len(set(two)) == 1


def test_the_stores_of_a_note_walk_across_rows_of_three():
    """Store k on tick `phase + 2k` (+ the lag): one store on tick 1, two on
    ticks 0 and 2, alternating by row -- phase 1 starts on a pair, phase 2 on
    a single, and Crazy_Comets' phase 2 with the one-tick lag starts with
    two singles (store 0, the pair's other half, is not emitted)."""
    assert R.store_rows(1, 0, 3, 6, 99) == {
        1: [(1, 0), (2, 2)], 2: [(3, 1)], 3: [(4, 0), (5, 2)], 4: [(6, 1)],
        5: [(7, 0), (8, 2)]}
    assert R.store_rows(2, 0, 3, 6, 99) == {
        1: [(1, 1)], 2: [(2, 0), (3, 2)], 3: [(4, 1)], 4: [(5, 0), (6, 2)],
        5: [(7, 1)]}
    cc = R.store_rows(2, 1, 3, 6, 99)
    assert cc[1] == [(1, 2)] and cc[2] == [(2, 1)] and cc[3] == [(3, 0), (4, 2)]
    # rows of two keep their one store a row: Game_Killer's rows 2..17
    gk = R.store_rows(2, 0, 2, 18, 17)
    assert gk == {k + 1: [(k, 0)] for k in range(1, 17)}
    # the byte caps the sweep, and a store landing past the note is dropped
    assert max(k for v in R.store_rows(2, 0, 3, 40, 5).values()
               for k, _h in v) == 4
    assert R.store_rows(1, 1, 3, 1, 99) == {}


@needs_corpus
def test_a_row_of_three_ticks_of_nine_calls_is_declined(monkeypatch):
    """No corpus file has one; the guard is the property that a delay of 16
    cannot be written. Crazy_Comets forced to 9 calls a tick (27 a row)."""
    real = R.note_rise_plan

    def wrapped(*a, **k):
        a = list(a)
        a[9] = 27                                   # row_calls
        # ... and every subtune's own row too (`subtune_row_calls`, which
        # the plan reads before the file-wide one)
        k["subtune_row_calls"] = tuple(27 for _ in k.get(
            "subtune_row_calls", ()))
        return real(*a, **k)
    monkeypatch.setattr(R, "_gate_calls", lambda m, g: 9)
    monkeypatch.setattr(R, "note_rise_plan", wrapped)
    _sng, lines, _ = _converted("Crazy_Comets")
    log = [m for m in lines if "Note rise (bit $02)" in m]
    assert len(log) == 1 and "none taken" in log[0], log
    assert "a delay past $0F" in log[0], log


def _program(ticks, t, row_ticks=3, values=None):
    """{call: step} of the program storing on `ticks` (an int or a tuple),
    the speed-table index of a store being 0x40 + its value."""
    key = ticks if isinstance(ticks, int) else tuple(ticks)
    vs = values if values is not None else (
        (1,) if isinstance(key, int) else tuple(range(1, len(key) + 1)))
    v = vs[0] if isinstance(key, int) else tuple(vs)
    entries, starts = R.note_rise_entries({key: [v]}, t, 1, 1,
                                          lambda k: 0x40 + k, row_ticks)
    return _run(entries, starts[(key, v)]), entries


def test_a_row_of_three_fits_a_wavetable_delay_only_to_eight_calls_a_tick():
    """A delay is $00-$0F: the gap from a row's first store to its last call
    is `2 * t - 2` calls at three ticks, so t = 9 would need a delay of 16.
    A row of two never does (t <= 16)."""
    assert all(R.delays_fit(3, t) for t in range(1, 9))
    assert not any(R.delays_fit(3, t) for t in range(9, 17))
    assert all(R.delays_fit(2, t) for t in range(1, 17))


@pytest.mark.parametrize("t", [1, 2, 8])
def test_a_row_of_three_puts_the_note_before_every_step_and_on_its_last_call(t):
    last = 3 * t - 1
    for ticks, steps in (((0,), {0}), ((1,), {t}), ((2,), {2 * t}),
                         ((0, 2), {0, 2 * t})):
        prog, _ = _program(ticks, t)
        got_steps = {c for c, s in prog.items() if s != "note"}
        assert got_steps == steps, (t, ticks, prog)
        for c in steps:
            if c:
                assert prog.get(c - 1) == "note", (t, ticks, c, prog)
        if last not in steps:
            assert prog[last] == "note", (t, ticks, prog)


def test_a_row_of_three_at_one_call_a_tick_is_these_programs():
    cmd = (WAVECMD_PORTAUP,)
    for ticks, want in (
            ((0,), {0: cmd + (0x41,), 1: "note", 2: "note"}),
            ((1,), {0: "note", 1: cmd + (0x41,), 2: "note"}),
            ((2,), {1: "note", 2: cmd + (0x41,)}),
            ((0, 2), {0: cmd + (0x41,), 1: "note", 2: cmd + (0x42,)})):
        prog, _ = _program(ticks, 1)
        assert prog == want, (ticks, prog)


def test_a_row_of_two_programs_are_unchanged():
    """The two-tick rows (Game_Killer, Battle_of_Britain) keep the layout
    their byte-hashes were taken on: store on the first tick -> step, note on
    the second tick's first call and again on the row's last call; on the
    second -> note, step, note."""
    for t in (2, 10):
        a, ea = _program(0, t, row_ticks=2)
        b, eb = _program(1, t, row_ticks=2)
        assert a == {0: (WAVECMD_PORTAUP, 0x41), t: "note", 2 * t - 1: "note"}
        assert b == {t - 1: "note", t: (WAVECMD_PORTAUP, 0x41),
                     2 * t - 1: "note"}
        assert R.program_cost(0, t) == (2, 3) and R.program_cost(1, t) == (3, 2)
    # one-call ticks, second tick: the step IS the row's last call -> no tail
    c, ec = _program(1, 1, row_ticks=2)
    assert c == {0: "note", 1: (WAVECMD_PORTAUP, 0x41)} and R.tail_entries(
        1, 1, 2) == []


def test_a_pair_program_shares_the_tail_of_a_single_that_ends_on_the_same_tick():
    entries, starts = R.note_rise_entries(
        {2: [1, 2], (0, 2): [(1, 2), (2, 3)]}, 1, 1, 1, lambda k: k, 3)
    # tick 2 is the row's last call at one call a tick: no tail at all, every
    # program stops by itself, so the layout is just the programs
    assert R.tail_entries(2, 1, 3) == []
    assert len(entries) == 2 * R.program_cost(2, 1, 3)[0] + 2 * len(
        R.program_entries((0, 2), 1, WAVECMD_PORTAUP, (1, 2), 1, 3))
    # and tick 0 (a tail of two notes and a stop) is shared by its values
    entries0, _ = R.note_rise_entries({0: [1, 2, 3]}, 1, 1, 1, lambda k: k, 3)
    assert len(entries0) == 3 + 3 * 2


def _pointer_programs(song, numbers):
    """[[(wavetable program of each pointer row of a note)]] for every note of
    GT instrument in `numbers`, one lap of each orderlist: per note the list
    of (row offset from the note, {call: step}) for its pointer rows."""
    import songview
    from h2g.goatwriter import skydive as S
    wt, stbl = song.tables["WTBL"], song.tables["STBL"]
    out = []
    for track in song.tracks:
        rows = list(S._lap_rows(track, song.patterns))
        current, note_at, hits = 0, None, []
        for a, (p, r, _t) in enumerate(rows):
            n, i, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
            if i:
                current = i
            if 0x60 <= n <= 0xBC:
                if note_at is not None and hits:
                    out.append(hits)
                note_at, hits = ((a, current) if current in numbers else None), []
            elif cmd == CMD_SETWAVEPTR and note_at:
                prog = _run(wt, dat)
                hits.append((a - note_at[0],
                             {c: stbl[s[1] - 1][0] for c, s in prog.items()
                              if s != "note"}))
        if note_at is not None and hits:
            out.append(hits)
    return out


@needs_corpus
@pytest.mark.parametrize("name,rows,numbers", [
    ("Crazy_Comets", 300, {11, 16, 19, 23}),
    ("Chimera", 70, {10, 11, 18}),
])
def test_the_rows_of_a_note_alternate_one_store_and_two(name, rows, numbers):
    """Per note, the pointer rows read in order alternate a single store with
    a pair on calls 0 and 2, and the stores' values run one after another
    (every value is programmed: 46 of 46 and 34 of 34 at this tree)."""
    import songview
    sng, lines, _ = _converted(name)
    song = songview.parse_sng(sng)
    assert not any("rows not two" in m for m in lines), lines
    assert sum(int(m.split("Note rise (bit $02).....: ")[1].split(" ")[0])
               for m in lines if "Note rise (bit $02)" in m
               and "store row(s)" in m) >= rows, lines
    notes = _pointer_programs(song, numbers)
    assert notes
    consecutive = alternating = 0
    for hits in notes:
        for (j1, p1), (j2, p2) in zip(hits, hits[1:]):
            if j2 != j1 + 1 or j1 == 1 or (j2, p2) == hits[-1] and len(p2) == 1:
                # a hole (a mixed or occupied row); or the note's first row,
                # where store 0 (the note's own byte, nothing to emit) is the
                # other half of what would be a pair; or a single last row,
                # which is Chimera's carried-on note cut at its last kept
                # store with a tail (note_rise.py `clipped`, the 51 values
                # that fit) and so not a pair like the rows before it
                continue
            consecutive += 1
            alternating += (len(p1) == 1) != (len(p2) == 1)
        for _j, prog in hits:
            assert len(prog) in (1, 2), prog
            if len(prog) == 2:
                assert sorted(prog) == [0, 2], prog   # ticks 0 and 2, 1 call each
    # 646 of 649 in Crazy_Comets at this tree; the others are a note's last
    # row, which keeps only the stores that fall inside the note
    assert consecutive >= 40 and alternating >= 0.98 * consecutive, (
        consecutive, alternating)
    # values: the stores of a note in order are one more each
    steps = gaps = 0
    for hits in notes:
        vals = [v for _j, prog in hits for _c, v in sorted(prog.items())]
        for a, b in zip(vals, vals[1:]):
            steps += 1
            gaps += b != a + 1
    assert steps >= 100 and gaps <= steps // 10, (steps, gaps)


@needs_corpus
def test_the_rows_of_three_ticks_are_still_declined_for_other_lengths():
    """Rows of four ticks (and one) are not placed: only 2 and 3."""
    assert R.NOTE_RISE_ROW_TICKS == (2, 3)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_crazy_comets_falling_stores_land_on_the_originals_frames(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump at -S1, 60 s: of the frames voice 0 sits
    1 to $20 below its note's high byte in the notes of the `$0FFF` record
    (160 measured, 384 at -t 180), ours reads the same high byte at the
    startup lag on all of them; without the plan on none."""
    def keep(hi, onset):
        return 1 <= onset - hi <= 0x20
    emitted = _agreement("Crazy_Comets", 1, 60, 0x0FF, keep, tmp_path, "emit")
    total, same = emitted[0]
    assert total >= 100 and same >= 0.95 * total, emitted
    monkeypatch.setattr(R, "note_rise_plan", lambda *a, **k: None)
    without = _agreement("Crazy_Comets", 1, 60, 0x0FF, keep, tmp_path, "none")
    assert without[0][1] <= total // 20, (emitted, without)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_chimeras_rising_stores_land_on_the_originals_frames(
        tmp_path, monkeypatch):
    """The same for the rising block: of the frames voice 1 sits 3 to $20
    above its note's high byte in the notes of the `$0F0F` record, ours reads
    the same byte on over 90% (116 of 124 measured at 90 s; the 8 missing
    are 4 pairs of consecutive frames on which the original holds one store
    byte for two, which one store per two ticks cannot match); without the
    plan none.
    Voice 2 holds a different, steady effect under the same AD and is the
    same with or without."""
    def keep(hi, onset):
        return 3 <= hi - onset <= 0x20
    emitted = _agreement("Chimera", 1, 90, 0x0F0, keep, tmp_path, "emit")
    total, same = emitted[1]
    assert total >= 100 and same >= 0.9 * total, emitted
    monkeypatch.setattr(R, "note_rise_plan", lambda *a, **k: None)
    without = _agreement("Chimera", 1, 90, 0x0F0, keep, tmp_path, "none")
    assert without[1][1] <= total // 20, (emitted, without)
    assert without[2] == emitted[2], (emitted, without)


@needs_corpus
def test_crazy_comets_rise_leaves_the_past_table_split_its_wavetable_rows():
    """Crazy_Comets' wavetable has 120 free entries; the rise wants 117 for
    all 46 store values and the past-table split, which runs on the finished
    song, needs 12 (3 pinned copies of its wave program). Without the room it
    leaves 5 note rows on a relative step past the table, which
    tests/test_past_table_split.py forbids. `convert` builds the song again
    with the shortfall held back, and the rise then kept its lowest 43
    values exact and left the stores above them to the vibrato (spreading
    13 values over the range instead costs 72% of the stores). Since the
    duplicate instrument blocks' rows are reused (`note_rise.
    reclaimable_holes`, tests/test_note_rise_reclaim.py) it keeps all 46
    and the split still has its room."""
    import songview
    sng, lines, _ = _converted("Crazy_Comets")
    rise = [m for m in lines if "Note rise (bit $02)" in m]
    assert len(rise) == 1 and "left to the vibrato" not in rise[0], rise
    assert "46 of 46 store value(s)" in rise[0] and "reused from" in rise[0]
    split = [m for m in lines if m.startswith("Past-table wave split")]
    assert len(split) == 1 and "pinned copy(ies)" in split[0], split
    assert "left on a relative step" not in split[0], split
    assert len(songview.parse_sng(sng).tables["WTBL"]) <= 255


@needs_corpus
def test_chimeras_rise_keeps_every_value_where_the_split_needs_no_room():
    sng, lines, _ = _converted("Chimera")
    rise = [m for m in lines if "Note rise (bit $02)" in m]
    assert len(rise) == 1, rise
    # The notes' own events ask for 34 values and all 34 are exact. The six
    # long notes now also run on through the rest after them
    # (tests/test_note_rise_rest_carry.py), which asks for 29 values above
    # them and has room for 17: the stores above the 51st are left to the
    # vibrato.
    assert "51 of 63 store value(s)" in rise[0], rise
    assert "6 note(s) carried on through the rest after them" in rise[0], rise
