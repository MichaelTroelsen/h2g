"""`drum_held`: the second noise frame the outer gate's withheld call holds.

Spellbound's play routine `$E012` (`DEC $C2 / BPL / LDA #$0A / STA $C2 / RTS`)
withholds every 11th call. Traced at -m1 over 120 s, a drum note whose gate
rises on frame `s` keeps its noise two frames exactly when call `s + 3` is
the withheld one (742 of 742 notes on the three voices that run a noise one or
two frames long, no exception), and one frame everywhere else. The converted
wavetable cannot say it -- every pattern cell of the drum rows is played at
every residue -- so `goatwriter/drum_held.py` reads the residue off the
orderlists (`drum_unit.fetch_frames`) and points the held notes' rows at a
copy of the record's program with the noise twice.
"""
import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from h2g.goatwriter import drum_held, drum_unit              # noqa: E402
from h2g.goatwriter.arpeggio import _walk_note_rows          # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,       # noqa: E402
                                      GT_WAVE_JUMP)
from songview import parse_sng                                # noqa: E402

SPELLBOUND = CORPUS / "Spellbound.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_presets = pytest.mark.skipif(not PRESETS.exists(),
                                   reason="presets.json absent")


def _convert(**kw):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, SPELLBOUND.name)
    opts.update(kw)
    sng = convert(str(SPELLBOUND), log=lambda m: None, **opts)
    return sng[0] if isinstance(sng, tuple) else sng


def test_withheld_calls_are_the_outer_counters_underflows():
    # Cleared to 0: the first call underflows; reload 10: every 11th after.
    assert sorted(drum_held.withheld_calls(0, 10, 30)) == [1, 12, 23]
    # Started at the reload: the 11th call is the first.
    assert sorted(drum_held.withheld_calls(10, 10, 30)) == [11, 22]


@needs_corpus
@needs_siddump
def test_original_noise_is_two_frames_where_call_s_plus_3_is_withheld():
    seconds = 120
    frames = seconds * 50
    trace = fidelity.run_siddump(SPELLBOUND, seconds, 0, calls=1)
    withheld = drum_held.withheld_calls(0, 10, frames + 20)
    seen = {1: 0, 2: 0}
    for voice in trace:
        wf = [None] * frames
        cur, events = None, sorted(voice.wf_events)
        at = 0
        for f in range(frames):
            while at < len(events) and events[at][0] <= f:
                cur = events[at][1]
                at += 1
            wf[f] = cur
        for s in range(1, frames - 10):
            if not (wf[s] and wf[s] & 1 and not (wf[s - 1] or 0) & 1):
                continue
            noise = [bool((wf[s + k] or 0) & 0x80) for k in range(1, 8)]
            if not noise[0]:
                continue
            run = 0
            while run < 7 and noise[run]:
                run += 1
            if run not in (1, 2):         # the 7-frame records are another class
                continue
            seen[run] += 1
            assert (run == 2) == ((s + 3) in withheld), (s, run)
    assert seen[1] > 100 and seen[2] > 100, seen


@needs_corpus
def test_the_clock_is_read_off_the_file():
    sid = load_sid(str(SPELLBOUND))
    det = detect(sid, lambda m: None)
    # (gate, skip, outer start, inner start): the outer cell is zero page, so
    # its first value is the init's fill loop (`A2 30 A9 00 95 A0 CA 10 FB`).
    assert drum_held.held_clock(sid, det) == (2, 10, 0, 0)
    assert drum_held._zp_outer_start(sid) == (10, 0)
    broken = copy.copy(sid)
    data = bytearray(sid.data)
    fill = drum_held.ZERO_FILL.search(bytes(data))
    data[fill.start() + 2] = 0xEA        # no longer clears the range
    broken.data = bytes(data)
    assert drum_held._zp_outer_start(broken) is None
    assert drum_held.held_clock(broken, det) is None


def _variant_at(wave, ptr):
    """The seven rows at wavetable row `ptr` (1-based), as (left, right)."""
    return wave[ptr - 1:ptr + 6]


@needs_corpus
@needs_presets
def test_held_notes_point_at_the_two_frame_program():
    plain = _convert(drum_held=False)
    held = _convert(drum_held=True)
    assert plain != held
    song = parse_sng(held)
    wave = song.tables["WTBL"]
    base = parse_sng(plain)
    # The wavetable only grew.
    assert len(wave) > len(base.tables["WTBL"])
    outer0, inner0 = 0, 0
    fetched = drum_unit.fetch_frames(outer0, inner0, 2, 10, 9000)
    withheld = drum_held.withheld_calls(outer0, 10, fetched[-1] + 3)
    pointed = 0
    for v in range(3):
        for row, _instr, pat, r in _walk_note_rows(song.tracks[v],
                                                   song.patterns):
            if pat[r + 2] != CMD_SETWAVEPTR:
                continue
            rows = _variant_at(wave, pat[r + 3])
            if len(rows) < 7:       # a looping program's six rows, table's end
                continue
            a, b, c, d, c2, d2, jump = rows
            # Attack, its delay, the noise, its delay, the noise again with
            # the gate closed, its delay, a jump to the row after the first
            # noise's delay. (Other passes point rows too; theirs differ.)
            if not (0x10 <= a[0] < 0x80 and 1 <= b[0] <= 0x0F
                    and c[0] & 0x81 == 0x81 and d == d2 and 1 <= d[0] <= 0x0F
                    and c2 == (c[0] & 0xFE, c[1])
                    and jump[0] == GT_WAVE_JUMP):
                continue
            # ... and the note is a held one: the call after its fetch's next
            # is the withheld one.
            assert (fetched[row] + 2) in withheld, (v, row)
            pointed += 1
    assert pointed > 100, pointed


@needs_corpus
@needs_presets
def test_a_pattern_is_copied_per_distinct_spelling():
    plain = parse_sng(_convert(drum_held=False))
    held = parse_sng(_convert(drum_held=True))
    assert len(held.patterns) > len(plain.patterns)
    # The same orderlist lengths: the copies repoint, they do not lengthen.
    assert [len(t) for t in held.tracks[:3]] == [len(t) for t in
                                                plain.tracks[:3]]


# Spellbound's record 2 as the converter lays it: `A B C D` then the tail
# `40:80 40:00 09:80 40:74 09:80 FF:<back into itself>`.
_LOOP = [(0x41, 0x00), (0x03, 0x80), (0x81, 0x74), (0x03, 0x80),
         (0x40, 0x80), (0x40, 0x00), (0x09, 0x80), (0x40, 0x74),
         (0x09, 0x80), (GT_WAVE_JUMP, 6)]


def _calls(rows):
    """Play calls the rows take: a wave row one, a delay row `value + 1`."""
    return sum(r[0] + 1 if 1 <= r[0] <= 0x0F else 1 for r in rows)


def test_a_looping_program_takes_the_noise_in_place_of_its_first_tail_row():
    key, c_row = drum_held._shape(_LOOP, 1)
    assert drum_held.is_loop(key) and c_row == 3
    rows = drum_held.variant(key, c_row, _LOOP)
    assert len(rows) == drum_held.variant_rows(key) == 6
    a, b, c, d, n, jump = rows
    assert (a, b, c, d) == tuple(_LOOP[:4])
    # The noise again, gate closed, on the one-call row behind the delay and
    # with that row's own pitch byte, then back to the row after it.
    assert n == (c[0] & 0xFE, _LOOP[4][1]) and n[0] & 0x80
    assert jump == (GT_WAVE_JUMP, c_row + 3)
    # The loop's phase is the call grid's: up to the jump the variant takes
    # the calls the plain program takes to the same row, never a frame more
    # (a second `C D` here put the pitch loop one frame late, Spellbound
    # held notes 503 mismatched pitch frames over 56 notes).
    assert _calls(rows[:5]) == _calls(_LOOP[:5])


def test_a_looping_tail_is_taken_only_where_the_noise_row_stands_alone():
    # The row behind the first tail row is a delay: the noise would be held
    # for the whole delay (Proteus records 11 and 12: wave late on every note).
    delayed = list(_LOOP)
    delayed[5] = (0x0F, 0x80)
    assert drum_held._shape(delayed, 1) is None
    # The first tail row itself a delay.
    delayed = list(_LOOP)
    delayed[4] = (0x07, 0x80)
    assert drum_held._shape(delayed, 1) is None
    # A program that stops is the old seven-row shape.
    stop = _LOOP[:4] + [(0x40, 0x00), (0x41, 0x00), (GT_WAVE_JUMP, 0)]
    key, c_row = drum_held._shape(stop, 1)
    assert not drum_held.is_loop(key)
    assert len(drum_held.variant(key, c_row, stop)) == drum_held.VARIANT_ROWS


@needs_corpus
@needs_presets
def test_spellbounds_held_notes_of_looping_records_point_at_the_in_place_noise():
    held = parse_sng(_convert(drum_held=True))
    wave = held.tables["WTBL"]
    fetched = drum_unit.fetch_frames(0, 0, 2, 10, 9000)
    withheld = drum_held.withheld_calls(0, 10, fetched[-1] + 3)
    pointed = 0
    for v in range(3):
        for row, _instr, pat, r in _walk_note_rows(held.tracks[v],
                                                   held.patterns):
            if pat[r + 2] != CMD_SETWAVEPTR:
                continue
            a, b, c, d, n, jump = wave[pat[r + 3] - 1:pat[r + 3] + 5]
            if not (0x10 <= a[0] < 0x80 and 1 <= b[0] <= 0x0F
                    and c[0] & 0x81 == 0x81 and 1 <= d[0] <= 0x0F
                    and n[0] == c[0] & 0xFE and 0x10 <= n[0] < 0xE0
                    and n[1] == 0x80 and jump[0] == GT_WAVE_JUMP):
                continue
            assert (fetched[row] + 2) in withheld, (v, row)
            pointed += 1
    assert pointed > 50, pointed
