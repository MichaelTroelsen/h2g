"""Bit $10's undivided clock where the INIT primes the outer gate's cell.

Task pitch-seq-init-primed-outer-cell. Dragons_Lair_Part_II and
Kings_of_the_Beach_ingame carry the classic outer-gated play routine
(tests/test_pitch_seq_flat_clock_outer.py), but their init stores the subtune's
skip into the outer cell AND into the gate's `LDA #imm` reload operand:

    Dragons_Lair_Part_II   CC25  LDA $C4F7,X / STA $C06A / STA $C502
    Kings_of_the_Beach     977F  LDA $9437,X / STA $9440 / STA $90CC

so the first outer value is that subtune's skip, not the file's byte. Both
also index their tables by what the init makes of the subtune number
(Dragons_Lair's dispatch sends subtune 0 to entry 9 and subtune 1 to entry 7;
Kings_of_the_Beach's skip table starts at 112 where `find_song_speeds` reads
the immediate's 3), so the rates are read off the init RUN (`_init_cells`).
Knucklebusters stores the same cells from a song event, not its init, and is
declined.
"""
import dataclasses
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                        # noqa: E402

import fidelity                                                # noqa: E402
from h2g import goatwriter as G                                # noqa: E402
from h2g.convert import _detect_tables                         # noqa: E402
from h2g.sidfile import load_sid                               # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")

A = G.arpeggio

# stem -> per subtune the (frames, skip) the init leaves, measured with
# `siddump -w<outer>,<inner>,<speed>,<phase>` (speed cell + 1, outer on frame 0).
INIT_RATES = {
    "Dragons_Lair_Part_II": ((2, 3), (3, 1), (2, 110), (2, 2), (2, 126),
                             (2, 8), (5, 8), (2, 4), (3, 3), (2, 8)),
    "Kings_of_the_Beach_ingame": ((3, 112), (3, 8), (2, 8), (3, 8), (2, 3),
                                  (2, 8), (2, 1)),
}
# stem -> (the skip table the init loads from, the outer cell)
PRIMER = {"Dragons_Lair_Part_II": (0xC4F7, 0xC502),
          "Kings_of_the_Beach_ingame": (0x9437, 0x9440)}


def _tables(stem):
    return _detect_tables(load_sid(str(CORPUS / f"{stem}.sid")),
                          lambda *a, **k: None)


def _patched(sid, addr, new):
    data = bytearray(sid.data)
    at = sid.to_offset(addr)
    data[at:at + len(new)] = bytes(new)
    return dataclasses.replace(sid, data=bytes(data))


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INIT_RATES))
def test_the_primed_clock_is_read_with_the_rates_the_init_leaves(stem):
    sid, det = _tables(stem)
    clock = A._pitch_seq_flat_clock(sid, det)
    assert clock is not None and clock.primed and clock.outer is not None
    assert clock.init_rates == INIT_RATES[stem]
    assert A._pitch_seq_any_clock(sid, det) == clock
    speeds = G.find_song_speeds(sid, det)
    for sub, rate in enumerate(INIT_RATES[stem]):
        assert A._pitch_seq_rates(clock, speeds, sub) == rate
        assert A._pitch_seq_rate_read(clock, *rate, sub)
    # past the last subtune nothing is read, and the walks decline it
    past = len(INIT_RATES[stem])
    assert A._pitch_seq_rates(clock, speeds, past) == (None, None)
    assert not A._pitch_seq_rate_read(clock, None, None, past)


@needs_corpus
def test_no_other_file_reads_a_primed_clock_and_knucklebusters_is_declined():
    primed = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        if det is None:
            continue
        clock = A._pitch_seq_flat_clock(sid, det)
        if clock is not None and clock.primed:
            primed.add(path.stem)
            assert clock.init_rates and any(clock.init_rates)
        elif clock is not None:
            assert clock.init_rates == (), path.stem
    assert primed == set(INIT_RATES)
    # Knucklebusters stores the cells from a song event: its init does not.
    sid, det = _tables("Knucklebusters")
    assert det.pitch_seq is not None
    assert A._pitch_seq_flat_clock(sid, det) is None
    # ... although the bytes of the idiom ARE in the file, off the init's
    # path, which is what `_init_reach` is for
    m = A.OUTER_GATE.search(sid.data)
    assert m is not None
    assert A._init_primes_outer(sid, m.group(1),
                                sid.to_address(m.start() + 6)) is None


@needs_corpus
@pytest.mark.parametrize("stem", sorted(PRIMER))
def test_the_primer_is_found_only_on_a_path_the_init_runs(stem):
    sid, det = _tables(stem)
    table, outer = PRIMER[stem]
    m = A.OUTER_GATE.search(sid.data)
    cell = m.group(1)
    imm = sid.to_address(m.start() + 6)
    assert cell[0] | cell[1] << 8 == outer
    assert A._init_primes_outer(sid, cell, imm) == table
    reach = A._init_reach(sid)
    assert sid.to_offset(sid.init_addr) in reach
    # the loaded table sits behind an `LDA table,X` the init executes
    at = next(p for p in reach if sid.data[p] == 0xBD
              and sid.data[p + 1] | sid.data[p + 2] << 8 == table)
    assert at + 3 in reach and at + 6 in reach
    # the same bytes off the init's path (the init's first instruction made
    # an `RTS`): the idiom is in the file, as it is in Knucklebusters' song
    # event, and the init does not run it
    dead = _patched(sid, sid.init_addr, [0x60])
    assert A._init_reach(dead) == {sid.to_offset(sid.init_addr)}
    assert A._init_primes_outer(dead, cell, imm) is None
    assert A._pitch_seq_outer_flat_clock(dead, det) is None
    # the same bytes with the store to the OUTER cell aimed at another cell
    # are no primer (Dragons_Lair stores the immediate first, Kings the cell)
    store = next(q for q in (at + 3, at + 6)
                 if sid.data[q + 1] | sid.data[q + 2] << 8 == outer)
    other = _patched(sid, sid.to_address(store + 1), [0x00, 0x03])
    assert A._init_primes_outer(other, cell, imm) is None
    clock = A._pitch_seq_outer_flat_clock(other, det)
    assert clock is not None and not clock.primed    # the file's byte is it
    # a primer that stores the outer cell but not the immediate is no primer
    # either, and its store is a writer the clock does not read
    imm_store = next(q for q in (at + 3, at + 6) if q != store)
    one = _patched(sid, sid.to_address(imm_store), [0xEA, 0xEA, 0xEA])
    assert A._init_primes_outer(one, cell, imm) is None
    assert A._pitch_seq_outer_flat_clock(one, det) is None


@needs_corpus
def test_a_second_writer_besides_the_primer_declines_the_clock():
    """Primed, the outer cell has exactly three writers: the gate's `DEC` and
    reload `STA`, and the init's primer. A fourth, planted in dead bytes at
    the file's end, is a first value this does not read."""
    sid, det = _tables("Kings_of_the_Beach_ingame")
    assert A._pitch_seq_outer_flat_clock(sid, det) is not None
    bad = _patched(sid, sid.to_address(len(sid.data) - 3), [0x8D, 0x40, 0x94])
    assert A._pitch_seq_outer_flat_clock(bad, det) is None


@needs_corpus
def test_the_init_run_reads_the_cells_the_player_finds():
    sid, _ = _tables("Dragons_Lair_Part_II")
    for sub, (frames, skip) in enumerate(INIT_RATES["Dragons_Lair_Part_II"]):
        mem, read = A._init_cells(sid, sub)
        assert read(0xC502) == skip and read(0xC06A) == skip, sub
        assert read(0xC501) + 1 == frames, sub
    # the dispatch is the point: subtune 2 reads table entry 1, not 2
    mem, read = A._init_cells(sid, 2)
    assert read(0xC502) == 110
    sid, _ = _tables("Kings_of_the_Beach_ingame")
    mem, read = A._init_cells(sid, 0)
    assert read(0x9440) == 112 and read(0x90CC) == 112
    assert read(0x943F) == 2 and mem[0x9441] == 2


@needs_corpus
def test_an_init_run_that_cannot_happen_returns_none_not_a_guess():
    sid, det = _tables("Kings_of_the_Beach_ingame")
    assert A._init_cells(sid, 0) is not None
    # an opcode the interpreter does not model (illegal $02) at `LDA #2`
    assert A._init_cells(_patched(sid, 0x9774, [0x02, 0x00]), 0) is None
    # a read outside the image and the init's own writes: `LDA $D412`
    assert A._init_cells(_patched(sid, 0x977F, [0xAD, 0x12, 0xD4]), 0) is None
    # no `RTS`: the entry `JMP`s to itself
    assert A._init_cells(_patched(sid, 0x906D, [0x4C, 0x6D, 0x90]), 0) is None
    # with no subtune's init runnable the clock is declined, not read blind
    bad = _patched(sid, 0x906D, [0x4C, 0x6D, 0x90])
    assert A._pitch_seq_outer_flat_clock(bad, det) is None


def test_the_first_outer_value_of_a_primed_clock_is_the_skip():
    """Frames 2, skip 3, inner starting at 0: a primed clock fetches on its
    first call (outer 3 -> 2), the file's byte (outer 1 -> 0) would not."""
    clock = A.PitchSeqClock(divider=0, divider_reload=0, phase=2,
                            phase_reload=2, outer=1, inner=0, primed=True)
    plain = dataclasses.replace(clock, primed=False)
    calls = A._pitch_seq_calls(clock, 2, 3)
    primed = [next(calls)[1] for _ in range(8)]
    calls = A._pitch_seq_calls(plain, 2, 3)
    unprimed = [next(calls)[1] for _ in range(8)]
    assert primed[0] is True and unprimed[0] is False
    # by hand: outer 3,2,1,0 then the reload call (3, inner not stepped);
    # inner 0 -> 1 (reload) -> 0 -> 1 on the three calls that do not underflow
    assert primed == [True, False, False, True, False, True, False, False]
    assert unprimed == [False, True, False, True, False, False, True, False]


def _dump_cells(path, subtune, cells, seconds):
    out = subprocess.run(
        [str(fidelity.SIDDUMP), str(path), f"-a{subtune}", f"-t{seconds}",
         f"-v{fidelity.PAL_FLAG}", "-w" + ",".join(f"{c:04x}" for c in cells)],
        capture_output=True, text=True, timeout=300,
        stdin=subprocess.DEVNULL).stdout
    rows = {}
    for line in out.splitlines():
        c = line.split("|")
        if len(c) >= 8:
            try:
                rows[int(c[1])] = tuple(int(x, 16) for x in c[6].split())
            except ValueError:
                continue
    return rows


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("stem", sorted(INIT_RATES))
def test_the_primed_clock_is_re_measured_against_the_original(stem):
    """`siddump -w<outer>,<inner>,<speed>,<phase>` over EVERY subtune, 20 s:
    the cell values on frame 0 are the init's (outer = skip, speed = frames -
    1), the simulated phase equals the phase cell on every frame, and the
    simulated fetches are exactly the frames where `outer != 0 and inner ==
    speed`. A tune that ends freezes the outer cell -- compared up to its last
    move, as test_pitch_seq_flat_clock_outer.py does."""
    sid, det = _tables(stem)
    clock = A._pitch_seq_flat_clock(sid, det)
    speeds = G.find_song_speeds(sid, det)
    m = G.OUTER_GATE.search(sid.data)
    g = G.SPEED_GATE.match(sid.data, m.end())
    (lo, hi), _ = A._pitch_seq_phase_block(sid)
    word = lambda b: b[0] | b[1] << 8                          # noqa: E731
    cells = (word(m.group(1)), word(g.group(1)), word(g.group(2)), lo | hi << 8)
    checked = 0
    for sub in range(max(sid.subtunes, 1)):
        frames, skip = A._pitch_seq_rates(clock, speeds, sub)
        assert A._pitch_seq_rate_read(clock, frames, skip, sub), (stem, sub)
        rows = _dump_cells(CORPUS / f"{stem}.sid", sub, cells, 20)
        assert rows[0][0] == skip and rows[0][2] == frames - 1, (stem, sub)
        moves = [f for f in range(1, len(rows)) if rows[f][0] != rows[f - 1][0]]
        if not moves:
            continue                                    # a stopped subtune
        assert rows[0][3] == A._pitch_seq_advance(
            clock, (clock.divider, clock.phase))[1], (stem, sub)
        calls = A._pitch_seq_calls(clock, frames, skip)
        for frame in range(1, moves[-1] + 1):
            _seen, fetched, after = next(calls)
            outer, inner, speed, phase = rows[frame]
            assert after[1] == phase, (stem, sub, frame)
            assert fetched == (outer != 0 and inner == speed), (stem, sub, frame)
        checked += 1
    assert checked >= 5, stem


@needs_corpus
@pytest.mark.parametrize("stem", sorted(INIT_RATES))
def test_the_conversion_consumes_the_primed_clock(stem):
    """`pitch_seq=True` changes the bytes of a file whose clock is read
    (without a clock `pitch_seq_phases` is empty and the option is inert)."""
    import json
    from h2g.convert import convert
    doc = json.loads((pathlib.Path(fidelity.__file__).resolve().parent.parent
                      / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{stem}.sid")
    path = str(CORPUS / f"{stem}.sid")
    quiet = lambda *a, **k: None                               # noqa: E731
    on = bytes(convert(path, quiet, **{**opts, "pitch_seq": True}))
    off = bytes(convert(path, quiet, **{**opts, "pitch_seq": False}))
    assert on != off
