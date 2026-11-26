"""The classic vibrato's free-running phase at -S1 (h2g.vibrato_phase,
module docstring "At -S1").

At one play call a frame the multispeed design has no free calls for its
zero-speed steps, so a class is a jump into an explicit up/down cycle and a
program that outlives its note starves the next note's slide. Three pieces are
pinned apart from any trace:

* `cycle_rotation` reaches every start state of the original's triangle,
* a class's chain puts the swing on the original's offset from frame 4 on,
  frame for frame, in gplay.c's wavetable loop (`vp.simulate`), and
* Trans-Atlantic_Balloon_Challenge, the one corpus file at -S1 whose clock the
  pass reads, names its clones and stops a program ahead of a tie; with the
  -S1 gate shut or the stop off the bytes differ.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import detect                                       # noqa: E402
from h2g import unison_vibrato as uv                         # noqa: E402
from h2g import vibrato_phase as vp                          # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,       # noqa: E402
                                      SPEED_NOTE_RELATIVE,
                                      WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from h2g.instrument_drop import _layout                      # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TA = CORPUS / "Trans-Atlantic_Balloon_Challenge.sid"
ROW = 3                      # the song's tempo: calls in a row
T_ROW = ROW - 1              # the program time the second row's pointer takes


def triangle_notes(bound: int, shift: int):
    """One synthetic note per start state of the original's triangle, as
    `test_vibrato_phase.triangle_notes`."""
    states = set()
    state = (0, 0)
    for _ in range(4 * bound):
        states.add(state)
        state = uv.step(state[0], state[1], bound)
    notes = []
    for state in sorted(states):
        life = 3 * bound + vp.FIRST_ACTIVE + 4
        offs, st = {}, state
        for j in range(1, life):
            st = uv.step(st[0], st[1], bound)
            offs[j] = st[0] - (bound >> 1)
        notes.append(dict(bound=bound, shift=shift, life=life, offsets=offs))
    return notes


def build(bound: int, shift: int, kept, jump_to_cycle=True):
    """The wavetable `phase_classic_vibrato` lays down at -S1 for a plain
    record: the cycle, the stem and one chain per `(j, A)`."""
    null_row = (vp._WAVECMD_VIBRATO, 1)
    stbl = [(bound - 2, 0), (SPEED_NOTE_RELATIVE, shift)]
    up, down = (WAVECMD_PORTAUP, 2), (WAVECMD_PORTADOWN, 2)
    moves = {1: up, -1: down}
    wtbl = []
    loop_at = len(wtbl) + 1
    wtbl += [up] * bound + [down] * bound + [(0xFF, loop_at)]
    stem = len(wtbl) + 1
    wtbl += vp.stem_rows(kept, 0, T_ROW, null_row) + [(0xFF, loop_at)]
    chains = {}
    for j in range(2 * bound):
        for a in range(-1, 2):
            try:
                rows = vp.chain_rows(kept, 0, a, 1, T_ROW, null_row, moves)
            except vp._Unsupported:
                continue
            chains[(j, a)] = len(wtbl) + 1
            wtbl += rows + [(0xFF, loop_at + (j if jump_to_cycle else 0))]
    return wtbl, stbl, stem, chains


KEPT = {0: (0x41, 0), 1: (0x41, 0x80), 2: (0x41, 0x80)}


@pytest.mark.parametrize("bound", [2, 3, 4, 5])
def test_cycle_rotation_covers_a_period(bound):
    cyc = [1] * bound + [-1] * bound
    for j in range(2 * bound):
        dirs = [cyc[(j + i) % (2 * bound)] for i in range(2 * bound)]
        assert vp.cycle_rotation(bound, dirs) == j
    assert vp.cycle_rotation(bound, [1] * (bound + 1)) is None


@pytest.mark.parametrize("bound", [2, 4])
def test_the_chain_puts_the_swing_on_the_originals_offset(bound):
    """For each start state of the original's triangle (`|A| <= 1` here: the
    table the helper builds holds one-depth moves) the stem and chain a class
    names put the swing on the original's offset from frame 4 on."""
    shift = 2
    wtbl, stbl, stem, chains = build(bound, shift, KEPT)
    done = 0
    for note in triangle_notes(bound, shift):
        cls = vp.classify(note, explicit=True)
        assert cls is not None
        j, a = cls
        if (j, a) not in chains:
            continue
        done += 1
        out = vp.simulate(wtbl, stbl, stem, note["life"] + 2, shift,
                          switch=(T_ROW, chains[(j, a)]))
        for f in range(vp.FIRST_ACTIVE, note["life"] - 1):
            assert out[f] == note["offsets"][f], (bound, j, a, f)
        for f in range(1, vp.FIRST_ACTIVE):
            assert out[f] == 0
    assert done >= bound


def test_the_jump_row_is_what_names_the_rotation():
    """Short-circuited -- every class jumping into the cycle's first row --
    the program no longer reaches the original's triangle."""
    shift, bound = 2, 4
    wtbl, stbl, stem, chains = build(bound, shift, KEPT, jump_to_cycle=False)
    wrong = 0
    for note in triangle_notes(bound, shift):
        j, a = vp.classify(note, explicit=True)
        if (j, a) not in chains:
            continue
        out = vp.simulate(wtbl, stbl, stem, note["life"] + 2, shift,
                          switch=(T_ROW, chains[(j, a)]))
        got = [out[f] for f in range(vp.FIRST_ACTIVE, note["life"] - 1)]
        want = [note["offsets"][f]
                for f in range(vp.FIRST_ACTIVE, note["life"] - 1)]
        wrong += got != want
    assert wrong > 0


def opts_for(name):
    doc = json.load(open(REPO_ROOT / "presets.json"))
    return fidelity._preset_opts(doc, name)


def stops(blob):
    """`CMD_SETWAVEPTR 0` rows of every pattern."""
    _i, _t, _p, pats = _layout(blob)
    return sum(1 for start, nrows in pats for r in range(nrows)
               if blob[start + r * 4] != 0xFF
               and blob[start + r * 4 + 2] == CMD_SETWAVEPTR
               and blob[start + r * 4 + 3] == 0)


@needs_corpus
def test_trans_atlantic_clock_and_phases_are_read():
    sid = load_sid(str(TA))
    det = detect.detect(sid, lambda m: None)
    assert vp._clock_cells(sid, 0) == (109, 2, 3, 112)
    blob = convert(str(TA), log=lambda m: None, **opts_for(TA.name))
    notes = vp.note_phases(blob, sid, det, slides=True)
    assert len(notes) > 250
    # The first vibrating note of voice 0, read off siddump of the original
    # (fetch frame 1552, record `$0A88`): 8912 flat on frames 0-3, then
    # 9036 8974 8912 8850 8788 = +2 +1 0 -1 -2 depths of 62.
    first = notes[0]
    assert first["frame"] == 1552 and first["bound"] == 4
    assert [first["offsets"][j] for j in range(4, 9)] == [2, 1, 0, -1, -2]


@needs_corpus
def test_trans_atlantic_phased_and_stopped():
    opts = opts_for(TA.name)
    base = convert(str(TA), log=lambda m: None,
                   **{**opts, "vibrato_phase": False})
    logs = []
    on = convert(str(TA), log=logs.append, **{**opts, "vibrato_phase": True})
    assert on != base
    said = [x for x in logs if x.startswith("Phased vibrato")]
    assert said and "wavetable chain(s)" in said[0]
    assert stops(base) == 0 and stops(on) >= 3


@needs_corpus
def test_the_s1_gate_and_the_stop_are_load_bearing(monkeypatch):
    opts = {**opts_for(TA.name), "vibrato_phase": True}
    base = convert(str(TA), log=lambda m: None,
                   **{**opts, "vibrato_phase": False})
    on = convert(str(TA), log=lambda m: None, **opts)
    monkeypatch.setattr(vp, "ALLOW_S1", False)
    assert convert(str(TA), log=lambda m: None, **opts) == base
    monkeypatch.setattr(vp, "ALLOW_S1", True)
    monkeypatch.setattr(vp, "STOP_AT_FETCH", False)
    unstopped = convert(str(TA), log=lambda m: None, **opts)
    assert unstopped != on and stops(unstopped) == stops(base)
