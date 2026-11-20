"""`drum_held` at a speed gate of 3 (Bump_Set_Spike, International_Karate).

At gate 2 the noise is one frame, or two where call `f + 2` (f = the row's
fetch) is the outer gate's withheld call. At gate 3 the noise is `gate - 1 = 2`
frames, or **3 where `f + 2` or `f + 3` is withheld**: the noise runs from the
call after the fetch to the call before the next fetch, and a withheld call
inside the unit makes the unit one call longer (Bump_Set_Spike 346 of 346 held
notes, 703 of 703 plain ones; Thrust 239 of 239 with the withheld call at
`f + 3`; traced at -m1, `tests/test_drum_held_gate3.py::test_original_*`).

A unit one call longer WITHOUT a withheld call between (the speed gate's
fetch waits for the outer counter to leave zero) does not hold the noise:
International_Karate 124 notes of unit 4 read two frames. So the rule is the
withheld call, not the unit's length.
"""
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

BUMP = CORPUS / "Bump_Set_Spike.sid"
KARATE = CORPUS / "International_Karate.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_presets = pytest.mark.skipif(not PRESETS.exists(),
                                   reason="presets.json absent")


def _convert(path, **kw):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, path.name)
    opts.update(kw)
    sng = convert(str(path), log=lambda m: None, **opts)
    return sng[0] if isinstance(sng, tuple) else sng


def test_a_withheld_call_at_f_plus_2_or_3_holds_a_gate_3_note():
    withheld = {13}
    assert drum_held.is_held(11, 3, withheld)          # f + 2
    assert drum_held.is_held(10, 3, withheld)          # f + 3
    assert not drum_held.is_held(12, 3, withheld)      # f + 1: the noise starts late
    assert not drum_held.is_held(9, 3, withheld)       # f + 4 is the next unit's
    assert not drum_held.is_held(11, 3, set())


def test_gate_2_keeps_its_one_call():
    # `f + 2` alone, as before this module knew gate 3.
    assert drum_held.is_held(5, 2, {7})
    assert not drum_held.is_held(5, 2, {8})
    assert not drum_held.is_held(5, 2, {6})


@needs_corpus
def test_the_gate_3_clocks_are_read_off_the_files():
    for path, clock in ((BUMP, (3, 9, 2, 0)), (KARATE, (3, 10, 4, 2))):
        sid = load_sid(str(path))
        det = detect(sid, lambda m: None)
        assert drum_held.held_clock(sid, det) == clock, path.name
        assert drum_held.held_clock(sid, det, (2,)) is None


def _run(rows, calls, at=0):
    """(waveform register, right byte written) on each of the first `calls`
    play calls of the program at row 1 of `rows` (gplay.c:697-720: a delay
    is current for value + 1 calls and its right byte is read on the last;
    a jump costs no call)."""
    out, pos, wait = [], at, 0
    reg = None
    rows = [(left, right) for left, right in rows]

    def note(right):
        return None if right == 0x80 else right        # $80: no pitch write

    while len(out) < calls:
        left, right = rows[pos]
        if left == GT_WAVE_JUMP:
            if right == 0:
                out.append((reg, None))
                continue
            pos = right - 1
            continue
        if left <= 0x0F:
            wait += 1
            out.append((reg, note(right) if wait == left + 1 else None))
            if wait == left + 1:
                wait, pos = 0, pos + 1
            continue
        if left >= 0xF0:
            out.append((reg, None))
            pos += 1
            continue
        reg = left
        out.append((reg, note(right)))
        pos += 1
    return out


def _overlay(rows, gate, multiplier):
    key = drum_held.overlay_key(rows, 1, gate, multiplier)
    assert key is not None
    return list(key[2])


def _held_run(plain, gate, multiplier, calls):
    """The held variant laid after the plain rows, as the writer does (its
    jumps are absolute rows of the whole table), run from its first row."""
    variant = _overlay(plain, gate, multiplier)
    return _run(list(plain) + variant, calls, at=len(plain))


def _assert_only_the_window_moves(plain, held, start, end, noise=0x80):
    """The held program's register and pitch writes equal the plain
    program's everywhere but the window, and the register is the closed noise
    on the window's calls."""
    n = end + 12
    a, b = _run(plain, n), _run(list(plain) + held, n, at=len(plain))
    for call, (x, y) in enumerate(zip(a, b)):
        if start <= call <= end:
            assert y[0] == noise, (call, y)
        else:
            assert x[0] == y[0], (call, x, y)
        assert x[1] == y[1], (call, x, y)


# Bump_Set_Spike's record 1 as the converter lays it at -S3: the noise is
# `81:00 04:80` (calls 3-8), the pulse row `40:00` follows on call 9.
_BUMP = [(0x41, 0x00), (0x01, 0x80), (0x81, 0x00), (0x04, 0x80),
         (0x40, 0x00), (0x01, 0x80), (GT_WAVE_JUMP, 0)]
# ... and the same with the drum sweep laid behind it as command rows.
_SWEEP = _BUMP[:-1] + [(0xF2, 0x07), (0xF2, 0x07), (GT_WAVE_JUMP, 0)]
# International_Karate's record 1 at -S10: the noise runs on through a pitched
# row, then a pulse/pitch loop that is phased by the call grid.
_KARATE = [(0x41, 0x00), (0x09, 0x80), (0x81, 0x00), (0x09, 0x80),
           (0x81, 0x7B), (0x04, 0x80), (0x40, 0x80), (0x03, 0x80),
           (0x40, 0x00), (0x09, 0x80), (0x40, 0x7B), (0x09, 0x80),
           (GT_WAVE_JUMP, 9)]


def test_a_stopping_record_gets_the_frame_put_in_and_its_tail_follows():
    rows = _overlay(_BUMP, 3, 3)
    # `A B C D`, one frame (3 calls) of closed noise, then the plain rows
    # from the pulse row on.
    assert rows == _BUMP[:4] + [(0x80, 0x80), (0x01, 0x80),
                                (GT_WAVE_JUMP, 5)]
    regs = [r for r, _ in _run(_BUMP + rows, 16, at=len(_BUMP))]
    assert regs[3:12] == [0x81] * 6 + [0x80] * 3
    assert regs[12] == 0x40
    # The tail (calls 9 and on in the plain program) moved one frame.
    plain = _run(_BUMP, 16)
    assert [x for x in regs[12:15]] == [r for r, _ in plain[9:12]]


def test_a_sweep_behind_the_noise_is_left_alone():
    # Bump_Set_Spike record 1 (`F2:07` rows behind the pulse row): put the
    # frame in and the sweep, which ours starts a call early and slower than
    # the original's, lands a frame off what it matched -- pitch_cents .8811
    # -> .8644 over the song (v0.5.667, -t 180); written over the pulse row
    # with the waveform put back a call later, .8727. Not taken.
    assert drum_held.overlay_key(_SWEEP, 1, 3, 3) is None


def test_a_looping_record_loses_none_of_its_phase():
    rows = _overlay(_KARATE, 3, 10)
    _assert_only_the_window_moves(_KARATE, rows, 28, 40)
    # The noise starts at call 11 (behind the attack's 11 calls) and, held,
    # runs `gate * multiplier` calls: exactly three frames, whatever phase
    # the note lands on.
    regs = [r for r, _ in _run(_KARATE + rows, 45, at=len(_KARATE))]
    assert [i for i, r in enumerate(regs) if r and r & 0x80] == list(
        range(11, 41))


def test_the_plain_noise_is_left_alone_when_it_already_reaches_the_end():
    long_noise = [(0x41, 0x00), (0x01, 0x80), (0x81, 0x00), (0x0F, 0x80),
                  (0x40, 0x00), (GT_WAVE_JUMP, 0)]
    # 3 + 17 calls of noise > the held window of 9: nothing to add.
    assert drum_held.overlay_key(long_noise, 1, 3, 3) is None


def test_a_delay_behind_the_window_is_declined():
    # A looping record (the overlay's case): the delay that follows the row
    # on the window's last call would keep the noise on.
    cut = _BUMP[:5] + [(0x0F, 0x80), (0x40, 0x00), (GT_WAVE_JUMP, 5)]
    assert drum_held.overlay_key(cut, 1, 3, 3) is not None   # the cut delay
    after = _BUMP[:5] + [(0x01, 0x80), (0x05, 0x80), (0x40, 0x00),
                         (GT_WAVE_JUMP, 5)]
    assert drum_held.overlay_key(after, 1, 3, 3) is None


@needs_corpus
@needs_siddump
def test_original_noise_is_three_frames_where_a_call_after_the_fetch_is_withheld():
    seconds = 60
    sid = load_sid(str(BUMP))
    det = detect(sid, lambda m: None)
    gate, skip, outer0, inner0 = drum_held.held_clock(sid, det)
    trace = fidelity.run_siddump(BUMP, seconds, 0, calls=1)
    frames = seconds * 50
    fetched = drum_unit.fetch_frames(outer0, inner0, gate, skip, frames)
    withheld = drum_held.withheld_calls(outer0, skip, fetched[-1] + 5)
    # siddump frame x is play call x + 1.
    seen = {2: 0, 3: 0}
    for voice in trace:
        events = sorted(voice.wf_events)
        wf, cur, at = [None] * frames, None, 0
        for f in range(frames):
            while at < len(events) and events[at][0] <= f:
                cur = events[at][1]
                at += 1
            wf[f] = cur
        by_call = {f: True for f in fetched}
        for s in range(1, frames - 12):
            if not (wf[s] and wf[s] & 1 and not (wf[s - 1] or 0) & 1):
                continue
            if (s + 1) not in by_call:
                continue
            run = 0
            while s + 1 + run < frames and (wf[s + 1 + run] or 0) & 0x80:
                run += 1
            if run not in (2, 3):
                continue
            seen[run] += 1
            assert (run == 3) == drum_held.is_held(s + 1, gate, withheld), (
                s, run)
    assert seen[2] > 100 and seen[3] > 100, seen


@needs_corpus
@needs_presets
def test_held_notes_point_at_the_overlay_program():
    plain = _convert(BUMP, drum_held=False)
    held = _convert(BUMP, drum_held=True)
    assert plain != held
    song, base = parse_sng(held), parse_sng(plain)
    wave = song.tables["WTBL"]
    assert len(wave) > len(base.tables["WTBL"])
    sid = load_sid(str(BUMP))
    det = detect(sid, lambda m: None)
    gate, skip, outer0, inner0 = drum_held.held_clock(sid, det)
    fetched = drum_unit.fetch_frames(outer0, inner0, gate, skip, 9000)
    withheld = drum_held.withheld_calls(outer0, skip, fetched[-1] + 3)
    new_rows = len(base.tables["WTBL"])
    pointed = 0
    for v in range(3):
        for row, _instr, pat, r in _walk_note_rows(song.tracks[v],
                                                   song.patterns):
            if pat[r + 2] != CMD_SETWAVEPTR or pat[r + 3] <= new_rows:
                continue
            assert drum_held.is_held(fetched[row], gate, withheld), (v, row)
            pointed += 1
    assert pointed > 10, pointed
