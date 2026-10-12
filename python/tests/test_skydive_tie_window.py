"""A skydive window on a TIED note opens on the row after the tie.

Zoids' two tied notes (`3 00` on the note row, pattern $26 row 64 at frame
10368 and pattern $27 row 9 at 10584) run the block from the fetch like any
other 16-23 tick note: ticks left are reloaded (`$10C0 STA $144D,X`), but
the tie jumps past the frequency and `savehi` (`$10D5 BIT $145D / BVS
$1116`), so the fall carries on from the note's own high byte. Siddump of
the original, voice 1: stores `37B8 36E6 3542 ...` on 10371, 10373, 10375 ...
35 of them, then the vibrato again on 10440. The tie's command column is
the tie itself, so the pointer goes on the NEXT row, whose `4 09` the
program never lets run (it writes on every call), and the program is a lead
and a wavetable jump into the pairs of a program already placed -- the
wavetable is at 252 of 255 rows, and the pairs `F2 k / F1 k` do not depend
on the note (`share_program_tail`).
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,       # noqa: E402
                                      CMD_TONEPORTA)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

STOP = (0xFF, 0x00)
NOOP = (0x00, 0x00)


def _pairs(n):
    out = []
    for k in range(1, n + 1):
        out += [(0xF2, 0x40 + k), (0xF1, 0x40 + k)]
    return out


def test_the_next_rows_frame_of_store_zero():
    """`phase + lag` counts from the tie row's first call and the next row
    starts `frames` later: Zoids' ties, phase 2 + 1 lag on three-frame rows,
    have store 0 on the pointer row's very first call; phase 1 would be a
    frame before it."""
    assert S.tie_window_phase(2, 1, 3) == 0
    assert S.tie_window_phase(1, 1, 3) == -1
    assert S.tie_window_phase(2, 0, 3) == -1


def test_a_program_that_is_the_tail_of_a_placed_one_needs_no_rows():
    placed = {10 + i: e for i, e in enumerate([(0x41, 0), NOOP] + _pairs(3)
                                              + [STOP])}
    # [NOOP, pairs 1..3, stop] is what row 11 executes
    prog = [NOOP] + _pairs(3) + [STOP]
    assert S.share_program_tail(prog, placed) == ([], 11)


def test_a_longer_program_keeps_its_head_and_jumps_into_the_tail():
    placed = {10 + i: e for i, e in enumerate([(0x41, 0), NOOP] + _pairs(3)
                                              + [STOP])}
    prog = [NOOP, NOOP] + _pairs(3) + [STOP]
    assert S.share_program_tail(prog, placed) == ([NOOP, (0xFF, 11)], None)


def test_the_jump_follows_a_jump_in_a_placed_program():
    """A program that is itself a head and a jump is still a run from its
    first row to the stop (a third window sharing a second's lead)."""
    placed = {10 + i: e for i, e in enumerate([(0x41, 0), NOOP] + _pairs(3)
                                              + [STOP])}
    placed[20] = NOOP                       # [NOOP, jump 11]
    placed[21] = (0xFF, 11)
    prog = [NOOP, NOOP, NOOP] + _pairs(3) + [STOP]
    # the longest run wins: row 11's is [NOOP, pairs] but row 20's, through
    # its jump, is [NOOP, NOOP, pairs], one more entry of the program's head
    assert S.share_program_tail(prog, placed) == ([NOOP, (0xFF, 20)], None)


def test_nothing_in_common_or_too_little_keeps_the_program():
    placed = {10 + i: e for i, e in enumerate([NOOP] + _pairs(3) + [STOP])}
    other = [(0xF2, 0x70), (0xF1, 0x70), STOP]
    assert S.share_program_tail(other, placed) == (other, None)
    # one entry in common saves nothing: a jump costs a row
    one = [NOOP, (0xF2, 0x70), (0xF1, 0x43), (0xF2, 0x70), STOP]
    placed2 = {5: (0xF2, 0x70), 6: STOP}
    assert S.share_program_tail(one, placed2) == (one, None)
    # a placed program with no stop (or a loop) is no tail
    assert S.share_program_tail([NOOP, STOP], {1: NOOP, 2: (0xFF, 1)}) == (
        [NOOP, STOP], None)


def test_only_an_alternating_program_writes_on_every_call():
    """The premise the tie window stands on: the tie leaves its toneporta as
    the command of the pointer row, which is harmless only if the program
    never leaves a call to it. The holding program does (its still calls run
    the continuous effect); the alternating one does not, at any rate."""
    def index(k):
        return k
    for multiplier in (1, 2, 3):
        held = S.skydive_calls(0, 5, False, index, multiplier)
        alt = S.skydive_calls(0, 5, True, index, multiplier)
        assert None in held
        assert None not in alt


def _converted(name, **extra):
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


def _run(wt, start):
    """The entries the wavetable executes from row `start` to its stop."""
    out, at, seen = [], start, set()
    while True:
        assert at not in seen and 1 <= at <= len(wt)
        seen.add(at)
        left, right = wt[at - 1]
        if left == 0xFF:
            if right == 0:
                return out
            at = right
            continue
        out.append((left, right))
        at += 1


@needs_corpus
def test_zoids_points_the_row_after_each_tie_at_the_shared_pairs():
    import songview
    sng, lines = _converted("Zoids")
    song = songview.parse_sng(sng)
    wt, stbl = song.tables["WTBL"], song.tables["STBL"]
    assert len(wt) <= 255

    def index(k):
        return stbl.index((k, 0x00)) + 1
    want = S.skydive_program(0, 35, True, index, 1)[:-1]
    got = {}
    for track in song.tracks:
        rows = list(S._lap_rows(track, song.patterns))
        for a, (p, r, _t) in enumerate(rows):
            if (p, r) in ((0x26, 64), (0x27, 9)):
                # the tie keeps its column ...
                assert song.patterns[p][4 * r + 2:4 * r + 4] == [
                    CMD_TONEPORTA, 0], (p, r)
                # ... and the row after it carries the pointer
                wp, wr, _ = rows[a + 1]
                cell = song.patterns[wp][4 * wr:4 * wr + 4]
                assert cell[2] == CMD_SETWAVEPTR, (wp, wr, cell)
                got[(wp, wr)] = cell[3]
    assert sorted(got) == [(0x26, 65), (0x27, 10)], got
    # one program for both, and it plays the held alternating fall
    assert len(set(got.values())) == 1, got
    assert _run(wt, set(got.values()).pop()) == want
    log = [m for m in lines if m.startswith("Skydive (bit $02)")][0]
    assert "after a tie: 2 row(s), 1 program(s)" in log, log
    # the table has room for one carried program beside the held note-row
    # program the ties jump into: the row window keeps its vibrato, the
    # note-row program does not
    assert "carrying the vibrato on 1 row(s) and 0 on the note row" in log, log


@needs_corpus
def test_a_tie_window_does_not_take_a_row_with_another_command(monkeypatch):
    """Mutation guard: a row after the tie holding anything but the
    continuous effects (here none allowed) keeps its bytes and the log says
    the rows were mixed or occupied."""
    import songview
    monkeypatch.setattr(S, "SKYDIVE_TIE_NEXT_COMMANDS", frozenset())
    sng, lines = _converted("Zoids")
    song = songview.parse_sng(sng)
    for p, r in ((0x26, 65), (0x27, 10)):
        assert song.patterns[p][4 * r + 2] != CMD_SETWAVEPTR, (p, r)
    assert not any("after a tie: 2 row(s)" in m for m in lines)


def _store_frames(trace, nframes):
    """{voice: {frame: high byte}} for the original's skydive stores: a
    carried high byte exactly one below the one two frames earlier, in a
    run of at least four such frames two apart, plus the store before it."""
    out = {}
    for vi, v in enumerate(trace):
        fq = fidelity.register_timeline(v.freq_events, nframes)
        hits = {f for f in range(2, nframes)
                if fq[f] >> 8 == (fq[f - 2] >> 8) - 1 and fq[f - 2] >> 8}
        got = {}
        for f in sorted(hits):
            if f - 2 in hits:
                continue
            g = f
            while g + 2 in hits:
                g += 2
            if (g - f) // 2 + 1 >= 4:
                for x in range(f - 2, g + 1, 2):
                    got[x] = fq[x] >> 8
        out[vi] = got
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_packed_fall_after_a_tie_names_the_originals_high_byte(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump, subtune 0, 220 s: the two windows after
    Zoids' ties (35 stores each, frames 10371 and 10587) read the original's
    high byte on every store frame at the startup lag -- and with the
    pointer refused, on one each."""
    seconds, sub = 220, 0
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "Zoids.sid", seconds, sub)
    stores = {f: hi for f, hi in _store_frames(orig, n)[0].items()
              if 10371 <= f <= 10655}
    assert len(stores) == 70, len(stores)

    def agree(tag):
        sng, _ = _converted("Zoids")
        work = tmp_path / tag
        work.mkdir()
        packed = fidelity.pack_sid(sng, work)
        assert packed is not None and packed.exists(), tag
        ours = fidelity.run_siddump(packed, seconds, sub)
        lag = fidelity.startup_lag(orig, ours)[0]
        fq = fidelity.register_timeline(ours[0].freq_events, n + lag)
        return sum(fq[f + lag] >> 8 == hi for f, hi in stores.items())

    assert agree("emitted") == 70
    monkeypatch.setattr(S, "SKYDIVE_TIE_NEXT_COMMANDS", frozenset())
    assert agree("without") <= 6
