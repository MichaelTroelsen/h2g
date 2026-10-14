"""Rasputin's EOR toggle ends on the note's last tick (goatwriter.wave_eor).

The original's block does not run on a note's last tick, so the voice holds
the state its last toggle left. A wavetable ring cannot say that -- it
toggles until the next fetch -- and its schedule puts one toggle inside every
last tick. `eor_stop_pass` points the voice at a no-op-then-stop program
(`EOR_STOP_PROGRAM`) with a `CMD_SETWAVEPTR` on the note's last row.

These tests pin the program, the pass's rules on synthetic patterns, the
placement on the converted Rasputin, and -- on the packed song, traced -- that
the toggles inside last ticks are gone.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import wave_eor as W  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETTEMPO, CMD_SETWAVEPTR,  # noqa: E402
                                      CMD_TONEPORTA, CMD_VIBRATO, GT_KEYOFF,
                                      GT_REST)

N = 0x60                      # a note
STOP = 9                      # the stop program's wavetable row in the fixtures
RING = frozenset({3})         # instrument 3 toggles
REST = [GT_REST, 0, 0, 0]


def _pat(*rows):
    out = []
    for r in rows:
        out += r
    return out + [0xFF, 0, 0, 0]


def _run(pats, tracks=None, rings=RING):
    """The pass over `pats` played in order and then a plain note of another
    instrument, so that no pattern ends on an unknown successor; the result
    is `pats`' own."""
    if tracks is not None:
        return W.eor_stop_pass(pats, tracks, rings, STOP)
    tail = _pat([N, 5, 0, 0])
    tracks = [list(range(len(pats) + 1)) + [0xFF, 0]]
    got = W.eor_stop_pass(pats + [tail], tracks, rings, STOP)
    return got if got is pats else got[:len(pats)]


def _cmds(pat):
    return [(pat[4 * k + 2], pat[4 * k + 3]) for k in range(len(pat) // 4)
            if pat[4 * k] != 0xFF]


# --- the program ---------------------------------------------------------------

def test_the_stop_program_is_a_no_op_then_the_stop():
    """A `CMD_SETWAVEPTR` onto an `$FF` row stops the whole song
    (gplay.c:436-445), so the pointer lands on a step that keeps the waveform
    and leaves the pitch, and the stop is the row after it."""
    (l0, r0), (l1, r1) = W.EOR_STOP_PROGRAM
    assert (l0, r0) == (0x00, 0x80)         # waveform kept, pitch untouched
    assert (l1, r1) == (0xFF, 0x00)         # stop
    assert l0 != 0xFF


def test_a_ring_instrument_is_one_that_jumps_back_into_the_cycles():
    ring = [(0x41, 0), (0x59, 0), (0xFF, 1)]              # rows 1-3: the cycle
    own = [(0x41, 0), (0xFF, 0)]                          # rows 4-5: stops
    loop = [(0x41, 0), (0xFF, 4)]                         # rows 6-7: its own loop
    jump_in = [(0x41, 0), (0xFF, 2)]                      # rows 8-9: into the ring
    entries = ring + own + loop + jump_in
    starts = {1: 1, 2: 4, 3: 6, 4: 8, 5: 3}
    got = W.eor_ring_instruments(entries, starts, (1, 3))
    assert got == frozenset({1, 4, 5})


# --- the pass on synthetic patterns ---------------------------------------------

def test_the_last_row_of_a_ring_note_takes_the_pointer():
    pats = [_pat([N, 3, 0, 0], REST, REST, REST, [N + 1, 3, 0, 0], REST)]
    got = _run(pats)
    assert _cmds(got[0]) == [(0, 0), (0, 0), (0, 0), (CMD_SETWAVEPTR, STOP),
                             (0, 0), (CMD_SETWAVEPTR, STOP)]
    # patterns are copied, never edited in place
    assert _cmds(pats[0]) == [(0, 0)] * 6


def test_a_note_of_another_instrument_is_left_alone():
    pats = [_pat([N, 4, 0, 0], REST, REST)]
    assert _run(pats) == pats


def test_a_one_row_note_is_left_alone():
    pats = [_pat([N, 3, 0, 0], [N + 1, 3, 0, 0], REST)]
    got = _run(pats)
    assert _cmds(got[0]) == [(0, 0), (0, 0), (CMD_SETWAVEPTR, STOP)]


def test_the_instrument_is_the_one_the_note_holds():
    """An instrument named earlier and carried (`instr 00`) is the note's."""
    pats = [_pat([N, 3, 0, 0], REST, REST, [N + 1, 0, 0, 0], REST, REST)]
    got = _run(pats)
    assert _cmds(got[0])[2] == (CMD_SETWAVEPTR, STOP)
    assert _cmds(got[0])[5] == (CMD_SETWAVEPTR, STOP)


def test_a_note_before_a_tie_keeps_its_ring():
    """A tie restarts no wavetable: the ring runs on into the tied event, as
    the original's counter does. The tied event itself is left alone too."""
    tie = [N + 2, 3, CMD_TONEPORTA, 0]
    pats = [_pat([N, 3, 0, 0], REST, REST, tie, REST, REST)]
    assert _run(pats) == pats


def test_a_note_at_a_pattern_end_looks_at_the_next_pattern():
    tie = [N + 2, 3, CMD_TONEPORTA, 0]
    a = _pat([N, 3, 0, 0], REST, REST)
    b = _pat(tie, REST)
    c = _pat([N + 3, 3, 0, 0], REST, REST)
    d = _pat([N + 4, 5, 0, 0])
    got = _run([a, b, c, d], tracks=[[0, 1, 2, 3, 0xFF, 0]])
    # a is followed by b, which opens on a tie: untouched
    assert _cmds(got[0]) == [(0, 0)] * 3
    # c is followed by a note of another instrument: stopped on its last row
    assert _cmds(got[2]) == [(0, 0), (0, 0), (CMD_SETWAVEPTR, STOP)]
    # an end the orderlist restarts from is unknown, so it is declined
    got = _run([c], tracks=[[0, 0xFF, 0]])
    assert _cmds(got[0]) == [(0, 0)] * 3
    # `--max-rows` slices a long pattern: the note runs on into the next
    # pattern's leading rest rows, so the slice's last row is not its last
    cut = _pat([N, 3, 0, 0], REST, REST)
    tail = _pat(REST, REST, [N + 1, 5, 0, 0])
    got = _run([cut, tail], tracks=[[0, 1, 0xFF, 0]])
    assert _cmds(got[0]) == [(0, 0)] * 3
    # a pattern two orderlists follow with different heads needs both to say
    # it: here one voice follows `c` with a tie, the other with a note
    got = _run([c, b, d], tracks=[[0, 1, 0xFF, 0], [0, 2, 0xFF, 0]])
    assert _cmds(got[0]) == [(0, 0)] * 3


def test_a_note_before_a_key_off_keeps_its_ring():
    off = [GT_KEYOFF, 0, 0, 0]
    pats = [_pat([N, 3, 0, 0], REST, REST, off, REST)]
    assert _run(pats) == pats


def test_a_busy_column_is_kept():
    pats = [_pat([N, 3, 0, 0], REST, [GT_REST, 0, CMD_SETTEMPO, 4])]
    assert _run(pats) == pats


def test_a_running_effect_is_not_ended_by_the_pointer():
    """The empty column is `CMD_DONOTHING`, which ends a running vibrato
    (gplay.c:403-406); `CMD_SETWAVEPTR` would leave it running."""
    vib = [CMD_VIBRATO, 0x24]
    pats = [_pat([N, 3] + vib, [GT_REST, 0] + vib, REST)]
    assert _run(pats) == pats
    # ...but once an empty column has ended it, the pointer is free
    pats = [_pat([N, 3] + vib, REST, REST)]
    got = _run(pats)
    assert _cmds(got[0])[2] == (CMD_SETWAVEPTR, STOP)
    # a command that sets no effect does not count as one running
    pats = [_pat([N, 3, 0, 0], [GT_REST, 0, CMD_SETTEMPO, 4], REST)]
    got = _run(pats)
    assert _cmds(got[0])[2] == (CMD_SETWAVEPTR, STOP)


def test_nothing_without_rings_or_a_stop_row():
    pats = [_pat([N, 3, 0, 0], REST, REST)]
    tracks = [[0, 0xFF, 0]]
    assert W.eor_stop_pass(pats, tracks, frozenset(), STOP) is pats
    assert W.eor_stop_pass(pats, tracks, RING, 0) is pats


# --- the converted Rasputin ------------------------------------------------------

RASPUTIN = CORPUS / "Rasputin.sid"


@pytest.fixture(scope="module")
def converted():
    """(song bytes, the pass's inputs and result, the log) under presets."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import json

    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, "Rasputin.sid")
    seen = {}
    real = W.eor_stop_pass

    def spy(patterns, tracks, rings, stop, log=None):
        seen["before"], seen["tracks"] = patterns, tracks
        seen["rings"], seen["stop"] = rings, stop
        seen["after"] = real(patterns, tracks, rings, stop, log)
        return seen["after"]
    log = []
    W.eor_stop_pass = spy
    try:
        blob = convert(str(RASPUTIN), log=log.append, **opts)
    finally:
        W.eor_stop_pass = real
    return blob, seen, log


@needs_corpus
def test_rasputin_lays_the_stop_program_behind_the_cycles(converted):
    import songview
    blob, seen, _log = converted
    song = songview.parse_sng(blob)
    left = [l for l, _ in song.tables["WTBL"]]
    right = [r for _, r in song.tables["WTBL"]]
    stop = seen["stop"]
    assert (left[stop - 1], right[stop - 1]) == (0x00, 0x80)
    assert (left[stop], right[stop]) == (0xFF, 0x00)
    # the cycles are the rows just before it, and they end in a jump back
    assert left[stop - 2] == 0xFF and 1 < right[stop - 2] < stop - 2


@needs_corpus
def test_rasputin_every_ring_note_ends_on_the_pointer(converted):
    """Every note of a ring instrument that is two rows or more, and not
    before a tie, has `CMD_SETWAVEPTR stop` on its last row, and no other
    byte of any pattern differs."""
    _blob, seen, log = converted
    before, after = seen["before"], seen["after"]
    stop, rings = seen["stop"], seen["rings"]
    assert rings, "no instrument reaches the cycles"
    changed = 0
    for pb, pa in zip(before, after):
        diff = [k for k in range(len(pb)) if pb[k] != pa[k]]
        assert len(pb) == len(pa)
        for k in diff:
            assert k % 4 in (2, 3)
        rows = sorted({k // 4 for k in diff})
        for r in rows:
            assert (pa[4 * r + 2], pa[4 * r + 3]) == (CMD_SETWAVEPTR, stop)
            assert (pb[4 * r + 2], pb[4 * r + 3]) == (0, 0)
            # a rest row after at least one row of its note
            assert pa[4 * r] == GT_REST and r >= 1
        changed += len(rows)
    line = next(l for l in log if l.startswith("EOR last tick"))
    assert int(line.split(":")[1].split()[0]) == changed >= 200


# --- the packed song, traced -------------------------------------------------------

def _trace_extra(monkeypatch, tmp_path, stop_pass: bool, seconds=60):
    import json

    import fidelity as F
    from test_wave_eor_emit import KEY, MULT, REC10, _convert, _walk
    if not stop_pass:
        monkeypatch.setattr(W, "eor_stop_pass",
                            lambda patterns, *a, **k: patterns)
    blob, seen = _convert(monkeypatch)
    det = seen["args"][1]
    tracks, patterns = seen["args"][2], seen["args"][3]
    rows, _ = W._event_rows(tracks, patterns, 0)
    sng, _patched = F.legalise_restarts(blob)
    tmp_path.mkdir(parents=True, exist_ok=True)
    packed = F.pack_sid(sng, tmp_path, F.GT2RELOC, MULT)
    assert packed is not None
    orig = F.run_siddump(RASPUTIN, seconds, 0)
    ours = F.run_siddump(packed, seconds, 0, calls=MULT)
    lag = F.startup_lag(orig, ours)[0]
    n = seconds * 50
    v, key = KEY[REC10]
    tlo = F.register_timeline(orig[v].wf_events, n)
    tlu = F.register_timeline(ours[v].wf_events, n)
    tle = F.register_timeline(orig[v].adsr_events, n)
    att = sorted(orig[v].attack_frames)
    notes = [(a, att[j + 1] if j + 1 < len(att) else n)
             for j, a in enumerate(att) if tle[a] == key]
    walked = [(k_, key_, length, phase) for ti, key_, k_, gt, _i, length,
              phase, q, _t in _walk(seen) if ti == 0 and gt == REC10
              and not q]
    count = toggles = original = kept = before = 0
    for (a, e), (k_, key_, length, phase) in zip(notes, walked):
        if length < 3 or e + lag + 2 >= n:
            continue
        m, R = W.gate_phase(det, 0, rows[(key_, k_)])
        lo = a + W.gate_tick(R, m + 2 * (length - 1)) - W.gate_tick(R, m)
        count += 1
        for k in range(a + 1, e):
            ts = (tlo[k - 1] & 0xF0, tlo[k] & 0xF0)
            us = (tlu[k - 1 + lag] & 0xF0, tlu[k + lag] & 0xF0)
            if k >= lo:
                original += {0x40, 0x50} == set(ts)
                toggles += {0x40, 0x50} == set(us)
            else:
                before += {0x40, 0x50} == set(ts)
                kept += {0x40, 0x50} == set(us)
    return count, toggles, original, kept, before


@needs_corpus
def test_the_packed_song_toggles_nothing_in_the_last_tick(monkeypatch,
                                                           tmp_path):
    """Packed and traced (60 s of subtune 0): the original toggles 4x<->5x
    on any last-tick frame of its toggling record-10 notes (3 or more rows).
    Without the pass the conversion toggles 70 times inside the last ticks of
    the 97 such notes of the window (208 of 336 in 180 s, at c4eedc4); with
    it 7 (29 of 336): the notes the pass declines (a note a sliced pattern
    carries on, 12 of 278) and the NEXT note's attack landing a frame early
    (a 4x waveform on the tick's last frame, not the ring)."""
    import fidelity as F
    if not pathlib.Path(F.GT2RELOC).exists():
        pytest.skip("gt2reloc not found")
    if not pathlib.Path(F.SIDDUMP).exists():
        pytest.skip("siddump not found")
    with monkeypatch.context() as m:
        count, without, original, kept0, before = _trace_extra(
            m, tmp_path / "a", False)
    with monkeypatch.context() as m:
        count2, with_pass, original2, kept1, before2 = _trace_extra(
            m, tmp_path / "b", True)
    assert count == count2 >= 80
    assert original == original2 == 0
    assert without >= 40, without
    assert with_pass <= without // 4, (without, with_pass)
    # ...and the toggles BEFORE the last tick are the ones it always made:
    # a pointer a row early would cost every note its last real toggle.
    assert before == before2 > 300
    assert kept1 >= 0.97 * before, (kept0, kept1, before)
