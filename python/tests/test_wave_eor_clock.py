"""Rasputin's EOR toggle on the ORIGINAL'S GATE CLOCK (goatwriter.wave_eor).

The toggle block (`$C35A`) runs on every working call of a note's ticks but
the last and flips on every second one. The calls are counted by the outer
gate, which `$FE nn` restarts: R working calls, then one skipped frame
(`detect.track_fe_restarts_gate`). So the frame of a note's k-th toggle is a
function of where its fetch falls in the gate's cycle, and a fixed loop per
(phase, tick) -- the first emission -- cannot follow it on the segments where
the skip comes often (R = 3 and 5, 5.33 and 4.8 calls to a tick).

These tests pin:

* the clock itself (`gate_tick`, `node_frames`) and the restarts read out of
  the orderlists;
* that the clock names EVERY toggle frame of EVERY toggling record-10 note
  the trace shows (376 of 376 in subtune 0, 180 s);
* the library of cycles the clocked residues jump into, node by node;
* each block's shape (a residue the library holds whole is an entry
  position, anything else a lead and a jump);
* that, residue by residue of the first emission, the clocked one agrees with
  the trace on at least as many frames as the fixed loop did.
"""
import sys

import pytest

from corpus import needs_corpus  # noqa: E402
from test_wave_eor_emit import (KEY, MULT, RASPUTIN, REC10, _calls,  # noqa: E402
                                _convert, _frames, _program, _walk)

from h2g.detect import detect  # noqa: E402
from h2g.goatwriter import _wavetable_entries  # noqa: E402
from h2g.goatwriter import wave_eor as W  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

# subtune 0's restarts at 862f703 .. 1aae7cc: (row, working calls a row,
# R). The closing R = 6 and 2 are past the 180 s window.
RESTARTS0 = [(0, 2, 2), (384, 2, 3), (640, 2, 5), (1792, 2, 10),
             (2304, 2, 60), (3712, 2, 120), (5632, 2, 6), (6720, 2, 2)]


# --- the clock ----------------------------------------------------------------

def test_gate_tick_follows_the_player():
    """Call 0 reads the change (frame 0); calls 1..R follow on the next
    frames; the call after R is skipped."""
    assert [W.gate_tick(3, m) for m in range(9)] == [0, 1, 2, 3, 5, 6, 7, 9, 10]
    assert [W.gate_tick(2, m) for m in range(7)] == [0, 1, 2, 4, 5, 7, 8]
    assert [W.gate_tick(0, m) for m in range(5)] == [0, 1, 2, 3, 4]
    assert W.gate_tick(5, 6) == 7 and W.gate_tick(5, 5) == 5


def test_a_cycle_of_nodes_is_a_cycle_of_the_gate():
    """Toggles are two working calls apart, so over R of them (one cycle,
    for an odd R) the gate skips twice as many frames as it has cycles: R 5
    spends 12 frames on 5 toggles, R 3 spends 8, R 2 spends 3 on each."""
    assert sum(W.node_frames(5, w) for w in range(1, 6)) == 12
    assert sum(W.node_frames(3, w) for w in range(1, 4)) == 8
    assert [W.node_frames(2, w) for w in range(5)] == [3] * 5
    assert [W.node_frames(0, w) for w in range(5)] == [2] * 5
    # periodic in w, and w = 0 reads as R
    assert W.node_frames(5, 0) == W.node_frames(5, 5) == 3
    assert W.node_frames(5, 7) == W.node_frames(5, 2) == 2


@needs_corpus
def test_the_orderlists_restarts_are_read(monkeypatch):
    _blob, seen = _convert(monkeypatch)
    det = seen["args"][1]
    gr = det.gate_restarts
    assert gr["groups"] == 2
    assert gr["restarts"][0] == RESTARTS0
    assert gr["restarts"][1] == [(0, 2, 3)]
    # every voice of a subtune plays the same rows
    assert gr["rows"][:3] == [6848] * 3
    assert W.gate_phase(det, 0, 383) == (2 * 383, 2)
    assert W.gate_phase(det, 0, 384) == (0, 3)
    assert W.gate_phase(det, 0, 400) == (32, 3)
    assert W.gate_phase(det, 1, 5) == (10, 3)


@needs_corpus
def test_the_clock_names_every_toggle_frame(monkeypatch):
    """Each toggling record-10 note, paired in order with the trace's
    attacks: the frames its waveform flips on, counted from the attack, are
    `gate_tick(R, m + c + 2j) - gate_tick(R, m)` for the toggles the block
    makes (L - 1 on counter phase 0, L - 2 on phase 1 -- the note's last
    tick runs none). 376 of 376 at 1aae7cc."""
    sys.path.insert(0, str(RASPUTIN.parents[0]))
    import fidelity as F
    _blob, seen = _convert(monkeypatch)
    det = seen["args"][1]
    tracks, patterns = seen["args"][2], seen["args"][3]
    rows, _ = W._event_rows(tracks, patterns, 0)
    trace = F.run_siddump(RASPUTIN, 180, 0)
    v, key = KEY[REC10]
    n = 180 * 50
    tl_w = F.register_timeline(trace[v].wf_events, n)
    tl_e = F.register_timeline(trace[v].adsr_events, n)
    att = sorted(trace[v].attack_frames)
    notes = [(a, att[j + 1] if j + 1 < len(att) else n)
             for j, a in enumerate(att) if tl_e[a] == key]
    walked = [(k_, key_, length, phase) for ti, key_, k_, gt, _i, length,
              phase, q, _t in _walk(seen) if ti == 0 and gt == REC10
              and not q]
    assert len(walked) == len(notes) >= 416
    checked = 0
    for (a, e), (k_, key_, length, phase) in zip(notes, walked):
        if length < 2 or (length == 2 and phase == 1):
            toggles = 0
        else:
            toggles = length - 1 if phase == 0 else length - 2
        m, R = W.gate_phase(det, 0, rows[(key_, k_)])
        c = 1 if phase == 0 else 2
        want = [W.gate_tick(R, m + c + 2 * j) - W.gate_tick(R, m)
                for j in range(toggles)]
        seq = [tl_w[a + i] for i in range(e - a)]
        got = [i for i in range(1, len(seq))
               if (seq[i] & 0x18) != (seq[i - 1] & 0x18)]
        assert got == want, (a, R, m, length, phase, got, want)
        checked += toggles > 0
    assert checked >= 336


# --- the library --------------------------------------------------------------

def test_every_ring_closes_and_holds_each_node_for_its_frames():
    lib = W.eor_library([(0x41, 0x59)], MULT, 1)
    assert lib.start == 1
    # R 0: one ring of two nodes; R 2: two rings of two; R 3: six; R 5: ten
    assert sorted({R for (_w, R, _s, _x) in lib.nodes}) == [0, 2, 3, 5]
    per = {R: sum(1 for k in lib.nodes if k[1] == R) for R in (0, 2, 3, 5)}
    assert per == {0: 2, 2: 4, 3: 6, 5: 10}
    # 44 entries, one jump a ring: R 2's second ring holds what its first
    # does (all three-frame nodes), so it is the first (49 before it shared)
    assert len(lib.left) == 44
    for (wave, R, s, w), pos in lib.nodes.items():
        # from this node the program alternates the two waveforms, each for
        # the frames the gate gives the toggle that ends it
        want, state, x = [], s, w
        for _ in range(2 * max(R, 1) + 2):
            want += [(0x59 if state else 0x41)] * (W.node_frames(R, x) * MULT)
            state, x = 1 - state, (x + 2) % R if R else 0
        assert _calls(lib.left, lib.right, pos, len(want)) == want, \
            (R, s, w)


def _block(eor, written=False, library=True, rec=10):
    sid = load_sid(str(RASPUTIN))
    det = detect(sid, log=lambda m: None)
    lib = W.eor_library([(0x41, 0x59)], MULT, 1) if library else None
    base = _wavetable_entries(sid, det, rec, True, "gts5", [], MULT,
                              start=60, budget=40)
    return (W.wave_eor_block(sid, det, rec, eor, base, MULT, 60, 40,
                             written=written, library=lib), lib, base)


@needs_corpus
def test_phase_one_enters_the_library_whole():
    eor = W.EorPhase(1, 3, 3, 1)       # R 3, first toggle on call 1 mod 3
    got, lib, _base = _block(eor)
    node = lib.nodes[(0x41, 3, 0, 2)]  # the virtual toggle two calls before
    assert got == node
    # one entry in where the firstwave has already sounded the first call
    assert _block(eor, written=True)[0] == node + 1
    calls = _calls(lib.left, lib.right, got, 12)
    # 3 frames of the first wave, 2 toggled, then 3 again (R 3: 3, 2, 3)
    assert calls == [0x41] * 6 + [0x59] * 4 + [0x41] * 2


@needs_corpus
def test_phase_zero_holds_then_jumps_into_the_node_that_toggles():
    for first in (1, 2):
        eor = W.EorPhase(0, first, 5, 1 if first == 2 else 3)
        (left, right), lib, _b = _block(eor)
        target = lib.nodes[(0x41, 5, 1, eor.pos)]
        assert left[-1] == 0xFF and right[-1] == target
        assert _calls(lib.left + [0] * 10 + left, lib.right + [0] * 10 + right,
                      len(lib.left) + 11, 4 * first)[:2 * first] == \
            [0x41] * (2 * first)
    # written: the firstwave sounded the first call, one call fewer to hold
    (left, right), lib, _b = _block(W.EorPhase(0, 1, 3, 2), written=True)
    assert left == [0x41, 0xFF]


@needs_corpus
def test_a_segments_opening_note_takes_the_short_first_hold():
    """The first row after a restart has no skip behind it: its phase-1
    toggle is two frames in where the cycle would say three. Not a whole
    node, so a lead and a jump."""
    eor = W.EorPhase(1, 2, 3, 2)       # R 3, m = 0
    got, lib, _base = _block(eor)
    assert isinstance(got, tuple)
    assert got[1][-1] == lib.nodes[(0x41, 3, 1, 2)]


@needs_corpus
def test_without_a_library_or_a_record_it_applies_to_the_block_stands():
    eor = W.EorPhase(1, 3, 3, 1)
    got, _lib, base = _block(eor, library=False)
    assert got == base
    # a drum record keeps its own shape whatever the clock says
    got, _lib, base = _block(eor, rec=4)
    assert got == base


# --- against the trace, residue by residue -----------------------------------

@needs_corpus
def test_no_residue_of_the_first_emission_agrees_on_fewer_frames(monkeypatch):
    """The first emission's residues were (phase, tick in calls). Group the
    record-10 notes by that residue and count the frames each emission agrees
    with the trace on, over each note but its last tick (where the original
    holds and a looping block toggles once more). The clock's emission is no
    worse on any group -- the five-call ticks, the groups the fixed loop
    could not follow, go from 0.836 / 0.812 to 0.974 / 0.976 -- and better on
    the whole."""
    sys.path.insert(0, str(RASPUTIN.parents[0]))
    import fidelity as F
    from collections import defaultdict
    _blob, seen = _convert(monkeypatch)
    sid, det = seen["args"][:2]
    tracks, patterns = seen["args"][2], seen["args"][3]
    _phases, residues = W.wave_eor_note_residues(*seen["args"][:6],
                                                 seen["kw"].get("aliases"))
    rows, _ = W._event_rows(tracks, patterns, 0)
    base10 = _wavetable_entries(sid, det, 10, True, "gts5", [], MULT,
                                start=1, budget=40)
    trace = F.run_siddump(RASPUTIN, 180, 0)
    v, key = KEY[REC10]
    n = 180 * 50
    tl_w = F.register_timeline(trace[v].wf_events, n)
    tl_e = F.register_timeline(trace[v].adsr_events, n)
    att = sorted(trace[v].attack_frames)
    notes = [(a, att[j + 1] if j + 1 < len(att) else n)
             for j, a in enumerate(att) if tl_e[a] == key]
    walked = [(key_, k_, length, phase, tempo) for ti, key_, k_, gt, _i,
              length, phase, q, tempo in _walk(seen)
              if ti == 0 and gt == REC10 and not q]
    old = defaultdict(lambda: [0, 0])
    new = defaultdict(lambda: [0, 0])
    for (a, e), (key_, k_, length, phase, tempo) in zip(notes, walked):
        res = residues[key_][k_]
        if length < 2:
            old_res = W.NO_TOGGLE
        elif length == 2:
            old_res = W.EorPhase(0, 0) if phase == 0 else W.NO_TOGGLE
        else:
            old_res = W.EorPhase(phase, int(tempo + 0.5))
        m, R = W.gate_phase(det, 0, rows[(key_, k_)])
        last = W.gate_tick(R, m + 2 * (length - 1)) - W.gate_tick(R, m)
        for tab, r in ((old, old_res), (new, res)):
            if r.family >= 0:
                calls = _program(sid, det, 10, r, base10, MULT * (e - a))
            else:
                # the first emission's own block, laid out where it was
                blk = W.wave_eor_block(sid, det, 10, r, base10, MULT, 1, 40)
                calls = _calls(*blk, 1, MULT * (e - a))
            ours = _frames(calls)
            grp = tab[(old_res.phase, old_res.period)]
            for k in range(min(last, e - a)):
                grp[1] += 1
                grp[0] += (ours[k] & 0xFE) == (tl_w[a + k] & 0xFE)
    assert set(old) == set(new)
    for grp in old:
        assert old[grp][1] == new[grp][1]
        assert new[grp][0] >= old[grp][0], (grp, old[grp], new[grp])
    assert new[(0, 5)][0] / new[(0, 5)][1] >= 0.97
    assert new[(1, 5)][0] / new[(1, 5)][1] >= 0.97
    tot_old = sum(g[0] for g in old.values())
    tot_new = sum(g[0] for g in new.values())
    tot = sum(g[1] for g in new.values())
    assert tot > 3900 and tot_new / tot >= 0.95 and tot_old / tot < 0.90


@needs_corpus
def test_a_foreign_clock_is_declined(monkeypatch):
    """`det.gate_restarts` is read from the orderlists as they were; when the
    finished song has a different number of subtunes (a split or a drop), or
    a voice that plays fewer rows than the original, its rows are not on the
    clock and the first emission's residues stand."""
    _blob, seen = _convert(monkeypatch)
    sid, det = seen["args"][:2]
    args = seen["args"][2:6]
    kw = seen["kw"].get("aliases")
    clocked = W.wave_eor_note_residues(sid, det, *args, kw)[1]
    assert any(r.family >= 0 for rows in clocked.values()
               for r in rows.values())
    saved = det.gate_restarts
    try:
        for bad in (dict(saved, groups=saved["groups"] + 1),
                    dict(saved, rows=[x + 1 for x in saved["rows"]]),
                    None):
            det.gate_restarts = bad
            plain = W.wave_eor_note_residues(sid, det, *args, kw)[1]
            assert all(r.family == -1 for rows in plain.values()
                       for r in rows.values())
    finally:
        det.gate_restarts = saved


# --- the layout ---------------------------------------------------------------

@needs_corpus
def test_a_residue_the_library_holds_whole_starts_inside_the_library():
    """`_wavetable_layout` lays the library right after the leading blocks,
    so that a record whose majority residue is a whole node starts AT that
    node (no entries of its own) and a phase clone of the other kind gets a
    lead and a jump past every record's block."""
    from h2g import goatwriter as G
    from h2g.convert import _detect_tables
    sid = load_sid(str(RASPUTIN))
    sid, det = _detect_tables(sid, lambda *a, **k: None)
    instr_used = G._instruments_used(det, None, 0)
    whole, lead_in = W.EorPhase(1, 3, 3, 1), W.EorPhase(0, 1, 3, 2)
    sinks = []
    entries, rec_starts, _ = G._wavetable_layout(
        sid, det, instr_used, True, G.FORMAT_GTS5, [(0, 0)] * 16, MULT, None,
        0, eor_phases={REC10: whole}, phase_clones=[(REC10, 40, lead_in)],
        phase_clone_starts=sinks)
    lib = W.eor_library([(0x41, 0x59)], MULT, 1)
    assert entries[:len(lib.left)] == list(zip(lib.left, lib.right))
    assert rec_starts[REC10 - 1] == lib.nodes[(0x41, 3, 0, 2)]
    assert len(sinks) == 1 and sinks[0] > len(lib.left)
    at = sinks[0]
    # one frame (two calls) of the wave, then the jump to the toggling node
    assert [e[0] for e in entries[at - 1:at + 2]] == [0x41, 0x41, 0xFF]
    assert entries[at + 1][1] == lib.nodes[(0x41, 3, 1, 2)]
    # the record after it is laid out after the library, not on top of it
    assert rec_starts[REC10] > len(lib.left)
