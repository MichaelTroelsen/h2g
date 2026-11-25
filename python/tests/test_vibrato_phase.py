"""The classic vibrato's free-running phase, one instrument clone a note
(h2g.vibrato_phase).

ACE_II voice 0's notes start the original's vibrato triangle in all eight
phases (a pattern replayed later swings the other way round) and Goattracker
restarts `vibtime` at every pitch write. `vibrato_phase` puts a note in the
original's phase with zero-speed `$F4` steps and one move (module docstring);
these tests pin the three pieces apart from any trace:

* the row clock reproduces the measured fetch frames `(8 * r + 1) // 3 + 2`
  of ACE_II (the 107 voice-0 attacks of siddump's first 60 s fall on them),
* every one of the eight rotations of the triangle is reached by a class's
  program, frame for frame, in gplay.c's wavetable loop (`vp.simulate`), and
* the converted ACE_II names the clones and the `CMD_SETWAVEPTR` rows, and
  the option off leaves the bytes alone.
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
from h2g.goatwriter.constants import (SPEED_NOTE_RELATIVE,   # noqa: E402
                                      WAVECMD_PORTADOWN, WAVECMD_PORTAUP)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ACE = CORPUS / "ACE_II.sid"
CALLS = 3
STEP = vp._WAVECMD_VIBRATO


def triangle_notes(bound: int, shift: int):
    """One synthetic note per start state of the original's triangle: the
    swing on each frame after the fetch, from the update `uv.step` carries
    (the fetch frame does not step)."""
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


def build_table(bound: int, shift: int, kept):
    """A wavetable and speed table holding the shared loop, the two stems and
    every class's chain -- what `phase_classic_vibrato` lays down for a record
    whose program is `kept`, built the same way."""
    t_a = vp.FIRST_ACTIVE * CALLS
    t_l = t_a + CALLS
    t_row = 7
    stbl = [(bound - 2, 0),                         # null
            (SPEED_NOTE_RELATIVE | (bound - 2), shift),   # step
            (SPEED_NOTE_RELATIVE, shift),                 # one depth
            (SPEED_NOTE_RELATIVE, shift - 1)]             # two depths
    null_row, step_row = (STEP, 1), (STEP, 2)
    moves = {1: (WAVECMD_PORTAUP, 3), -1: (WAVECMD_PORTADOWN, 3),
             2: (WAVECMD_PORTAUP, 4), -2: (WAVECMD_PORTADOWN, 4)}
    wtbl = []
    tail = {t - t_l: row for t, row in kept.items() if t >= t_l}
    loop_at = len(wtbl) + 1
    wtbl += vp._held_rows(tail, 0, step_row, 0, CALLS, loop_at)
    stems = {}
    for nb in (0, vp.STEM_NULLS):
        stems[nb] = len(wtbl) + 1
        wtbl += vp.stem_rows(kept, nb, t_row, null_row)
        wtbl.append((0xFF, loop_at))
    chains = {}
    for n in range(2 * bound):
        for a in range(-2, 3):
            nb, n2 = (0, n) if n <= len(vp.free_calls(kept, t_row, t_a)) \
                else (vp.STEM_NULLS, n - vp.STEM_NULLS)
            try:
                rows = vp.chain_rows(kept, n2, a, CALLS, t_row, null_row,
                                     moves)
            except vp._Unsupported:
                continue
            chains[(n, a)] = (nb, len(wtbl) + 1)
            wtbl += rows
            wtbl.append((0xFF, loop_at))
    return wtbl, stbl, stems, chains, t_row


@pytest.mark.parametrize("bound,shift", [(4, 2), (3, 3)])
def test_every_rotation_is_reached_frame_for_frame(bound, shift):
    """For each start state of the original's triangle, the stem and chain a
    class names put the swing on the original's offset from frame 4 on."""
    kept = {0: (0x41, 0), 3: (0x43, 0x80)}
    wtbl, stbl, stems, chains, t_row = build_table(bound, shift, kept)
    seen = set()
    for note in triangle_notes(bound, shift):
        cls = vp.classify(note)
        assert cls is not None
        n, a = cls
        seen.add(n)
        nb, chain = chains[(n, a)]
        out = vp.simulate(wtbl, stbl, stems[nb], 3 * (note["life"] - 1) + 3,
                          shift, switch=(t_row, chain))
        for j in range(vp.FIRST_ACTIVE, note["life"] - 1):
            assert out[CALLS * j + CALLS - 1] == note["offsets"][j], (
                bound, n, a, j)
        for j in range(1, vp.FIRST_ACTIVE):
            assert out[CALLS * j + CALLS - 1] == 0
    assert seen == set(range(2 * bound))


def test_the_chain_is_what_names_the_rotation():
    """Short-circuited -- every class on rotation 0 -- the program no longer
    reaches the original's triangle: the rotation search is load-bearing."""
    kept = {0: (0x41, 0), 3: (0x43, 0x80)}
    wtbl, stbl, stems, chains, t_row = build_table(4, 2, kept)
    wrong = 0
    for note in triangle_notes(4, 2):
        n, a = vp.classify(note)
        nb, chain = chains[(0, a)] if (0, a) in chains else chains[(n, a)]
        out = vp.simulate(wtbl, stbl, stems[nb], 3 * (note["life"] - 1) + 3,
                          2, switch=(t_row, chain))
        got = [out[CALLS * j + CALLS - 1]
               for j in range(vp.FIRST_ACTIVE, note["life"] - 1)]
        want = [note["offsets"][j]
                for j in range(vp.FIRST_ACTIVE, note["life"] - 1)]
        wrong += got != want
    assert wrong > 0


def test_rotation_search_covers_a_period():
    for bound in (2, 3, 4, 5):
        g = vp.gt_directions(bound - 2, 8 * bound)
        for n in range(2 * bound):
            assert vp.rotation(bound, g[n:n + 2 * bound]) is not None
        assert vp.rotation(bound, [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]) is None


@needs_corpus
def test_row_clock_reproduces_ace_ii_fetch_frames():
    sid = load_sid(str(ACE))
    cells = vp._clock_cells(sid, 0)
    assert cells == (0, 0, 2, 3)
    frames = vp.fetch_frames(cells, 300)
    assert frames == [(8 * r + 1) // 3 + 2 for r in range(300)]


@needs_corpus
def test_ace_ii_notes_start_in_all_eight_phases():
    sid = load_sid(str(ACE))
    det = detect.detect(sid, lambda m: None)
    blob = convert(str(ACE), log=lambda m: None, **opts_for("ACE_II.sid"))
    notes = vp.note_phases(blob, sid, det)
    assert len(notes) > 500
    rots = {vp.classify(n)[0] for n in notes if n["bound"] == 4}
    assert rots == set(range(8))
    # The first vibrating notes, read off siddump's first 60 s of the
    # original (voice 0, frames 365 ...): phases (offset on frame 4, 5...).
    first = [(n["frame"], n["offsets"][4], n["offsets"][5]) for n in notes[:5]]
    assert first == [(365, 2, 1), (386, -2, -1), (450, 0, -1), (471, 0, 1),
                     (482, 2, 1)]


def opts_for(name):
    doc = json.load(open(REPO_ROOT / "presets.json"))
    return fidelity._preset_opts(doc, name)


@needs_corpus
def test_ace_ii_option_off_is_inert_and_on_names_the_clones():
    # ACE_II's preset sets the option (adopted v0.5.678): the shipped file
    # is the option-on one, and "base" is the option off.
    opts = opts_for("ACE_II.sid")
    shipped = convert(str(ACE), log=lambda m: None, **opts)
    base = convert(str(ACE), log=lambda m: None,
                   **{**opts, "vibrato_phase": False})
    logs = []
    on = convert(str(ACE), log=logs.append, **{**opts, "vibrato_phase": True})
    assert shipped == on
    assert on != base and len(on) > len(base)
    said = [x for x in logs if x.startswith("Phased vibrato")]
    assert said and "wavetable chain(s)" in said[0]
    # One `CMD_SETWAVEPTR` row per covered note, none in the base song.
    from h2g.instrument_drop import _layout
    for blob, expect in ((base, False), (on, True)):
        _i, _t, _p, pats = _layout(blob)
        n = sum(1 for start, nrows in pats for r in range(nrows)
                if blob[start + r * 4 + 2] == 8
                and blob[start + r * 4] != 0xFF)
        assert (n > 100) == expect
