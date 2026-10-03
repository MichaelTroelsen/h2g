"""The outer gate's skipped frame stretches one fixed half of a gated nibble arp.

Opened by the runqueue task formula-1-simulator-reversal-doubles-under-the-
ticked-hold (head 1dde44a): in the original, Formula_1_Simulator's one-step
records always stretch the BASE note on the skipped frame (37/37 notes), and
Las_Vegas_Video_Poker's always the interval (lvvp-0aa0-and-spellbound-afff,
head 3b1c66d: 0A0C base runs {1:1695}, arp {1:1008, 2:1069}). The evenly
spread (2, 3) / 5-and-5 halves kept the rate but put the long half wherever
their own index landed -- LVVP's was inverted on every one-step note.

Re-measured at v0.5.496 on the tree as found (C:/t/nibble-gate-stall-phase,
ab_runs.py, 120 s, original at -m1 against packed conversions under presets):

    F1   one-step notes, long half   orig base 56/56 | before base 36, none 55
                                                     | after  base 91/91
    LVVP one-step notes, long half   orig arp 321    | before base 321 (all
                                                       inverted) | after arp 321
    LVVP octave, long half           orig arp 12     | before arp 7, base 5
                                                     | after  arp 12

Corpus byte-hash under presets (95 files, 6 refused both arms, 89 compared):
moved exactly Formula_1_Simulator and Las_Vegas_Video_Poker; Commando unmoved.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus
from test_call_rate import wave_timeline

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import (BNE, NIBBLE_GATE_MAX_HALVES,     # noqa: E402
                            _nibble_gate_shape, _refined_majority,
                            fixed_arp_period,
                            fixed_arp_up, nibble_arp_counter_test,
                            nibble_arp_phases, nibble_gate_byte,
                            nibble_gate_frames, nibble_gate_phases,
                            nibble_gate_runs, outer_gate_skip)
from h2g.sidfile import load_sid                             # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda *a: None)


# (gate cell's starting byte, counter base, reload O) as the files hold them.
GATE_READINGS = {
    "Formula_1_Simulator": (0, 0, 4),
    "Las_Vegas_Video_Poker": (3, 146, 4),
    "International_Karate": (4, 0, 10),
    "Kentilla": (3, 0, 10),
    "Thrust": (2, 192, 9),
}


@needs_corpus
def test_the_gate_cell_byte_is_read_where_only_the_gate_writes_it():
    for name, (g0, base, gate) in GATE_READINGS.items():
        sid, det = _det(name)
        assert nibble_gate_byte(sid) == g0, name
        assert nibble_arp_counter_test(sid, det.arp_nibble_period)[0] == base
        assert outer_gate_skip(sid, 0) == gate, name
    # A zero-page cell has no byte in the image.
    for name in ("Spellbound", "Samantha_Fox_Strip_Poker"):
        sid, _ = _det(name)
        assert nibble_gate_byte(sid) is None, name


def _long_halves(frames):
    """{half: run lengths} of the interior runs of a frame sequence."""
    runs = []
    for up in frames:
        if runs and runs[-1][0] == up:
            runs[-1][1] += 1
        else:
            runs.append([up, 1])
    out = {True: set(), False: set()}
    for up, n in runs[1:-1]:
        out[up].add(n)
    return out


@pytest.mark.parametrize("name, long_up", [
    ("Formula_1_Simulator", False), ("Las_Vegas_Video_Poker", True)])
def test_every_residue_stretches_the_same_half(name, long_up):
    """O a multiple of the period: from every attack residue the skipped
    frame lengthens the same half -- the base note in F1 (skip_at = 0 + 0),
    the interval in LVVP (146 + 3)."""
    g0, base, gate = GATE_READINGS[name]
    for residue in range(gate):
        halves = _long_halves(nibble_gate_frames(residue, 1, BNE, base + g0,
                                                 gate, 60))
        assert halves[long_up] == {1, 2}, (name, residue, halves)
        assert halves[not long_up] == {1}, (name, residue, halves)


@pytest.mark.parametrize("args, want", [
    # F1 one-step: the long half is the base note's, (1 2 1 1) over 5 frames.
    ((0, 1, BNE, 0, 4), (False, 1, (1, 2, 1, 1))),
    ((1, 1, BNE, 0, 4), (True, 1, (2, 1, 1, 1))),
    ((3, 1, BNE, 0, 4), (False, 1, (1, 1, 1, 2))),
    # LVVP one-step and octave: the interval's; the octave plays 2 then 3.
    ((1, 1, BNE, 149, 4), (True, 1, (1, 2, 1, 1))),
    ((3, 2, BNE, 149, 4), (True, 3, (2, 3))),
    ((2, 2, BNE, 149, 4), (False, 1, (3, 2))),
    # IK one-step, O 10: one long half in ten.
    ((0, 1, BNE, 4, 10), (False, 1, (1, 2, 1, 1, 1, 1, 1, 1, 1, 1))),
])
def test_the_runs_are_the_originals_frames(args, want):
    got = nibble_gate_runs(*args)
    assert got == want
    # The contract: first run then the cycle, repeated, IS the frame model.
    first_up, first, cycle = got
    frames = nibble_gate_frames(*args, 3 * sum(cycle) + first)
    rebuilt, up = [first_up] * first, not first_up
    while len(rebuilt) < len(frames):
        for n in cycle:
            rebuilt += [up] * n
            up = not up
    assert rebuilt[:len(frames)] == frames


def test_no_fixed_half_where_the_reload_is_not_a_multiple_of_the_period():
    """Thrust (O 9), Warhawk (7), Bump_Set_Spike (5): the skip walks round
    the counter, so the long half alternates and no run set is returned."""
    for gate in (5, 7, 9):
        for residue in range(2 * gate):
            assert nibble_gate_runs(residue, 1, BNE, 0, gate) is None
    assert nibble_gate_runs(0, 2, BNE, 0, 10) is None     # IK's octave


@needs_corpus
def test_the_shape_is_capped_at_four_halves():
    """International_Karate's ten-half one-step cycle would cost 21+ entries
    a record and starve later records' own shapes (measured: IK 12, 14, 15,
    16 lost their phased ticks, Kentilla 5 a third of its sweep); it keeps
    its old halves. F1's four-half cycle passes, at -S2 calls."""
    assert NIBBLE_GATE_MAX_HALVES == 4
    sid, det = _det("International_Karate")
    assert len(nibble_gate_runs(0, 1, BNE, 4, 10)[2]) == 10
    assert _nibble_gate_shape(sid, det, 1, 10, 10, 0) is None
    sid, det = _det("Formula_1_Simulator")
    assert _nibble_gate_shape(sid, det, 1, 2, 4, 0) == (False, 2, (2, 4, 2, 2))
    assert _nibble_gate_shape(sid, det, 1, 2, None, 0) is None
    assert _nibble_gate_shape(sid, det, 1, 2, 4, None) is None


def _trace_check(name, seconds):
    """(agree, disagree) of the frame model over every arpeggio note."""
    from itertools import groupby                           # noqa: F401
    sid, det = _det(name)
    per = det.arp_nibble_period
    base, branch = nibble_arp_counter_test(sid, per)
    gate, g0 = outer_gate_skip(sid, 0), nibble_gate_byte(sid)
    n = seconds * 50
    skip, pidx, v, p = [], [], g0, 0
    for _ in range(n):
        v = (v - 1) & 0xFF
        pidx.append(p)
        if v >= 0x80:
            v = gate
            skip.append(True)
        else:
            skip.append(False)
            p += 1
    tr = fidelity.run_siddump(CORPUS / f"{name}.sid", seconds, 0)

    def timeline(ev):
        out, cur, ev = [None] * n, None, sorted(ev)
        k = 0
        for f in range(n):
            while k < len(ev) and ev[k][0] <= f:
                cur = ev[k][1]
                k += 1
            out[f] = cur
        return out
    agree = disagree = 0
    for voice in tr:
        fq, wf = timeline(voice.freq_events), timeline(voice.wf_events)
        starts = [f for f in range(1, n) if wf[f] is not None and wf[f] & 1
                  and not ((wf[f - 1] or 0) & 1)] + [n]
        for a, b in zip(starts, starts[1:]):
            e = a
            while e < b and (wf[e] or 0) & 1:
                e += 1
            vals = set(fq[a:e])
            if len(vals) != 2 or skip[a]:
                continue
            b0 = fq[a]
            o = (vals - {b0}).pop()
            ratio = max(b0, o) / min(b0, o)
            if ratio < 1.05:
                continue                    # a two-valued vibrato
            mask = (per.on_interval if abs(ratio - 2) < 0.02
                    else per.otherwise)
            prev = False
            for f in range(a + 1, e):
                if not skip[f]:
                    prev = fixed_arp_up(mask, branch, base + pidx[f])
                if (fq[f] != b0) == prev:
                    agree += 1
                else:
                    disagree += 1
    return agree, disagree


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name, seconds, floor", [
    ("Formula_1_Simulator", 60, 150), ("Las_Vegas_Video_Poker", 60, 2000),
    ("International_Karate", 120, 400), ("Kentilla", 60, 4000),
    ("Thrust", 60, 60)])
def test_the_frame_model_is_re_measured_against_the_original(name, seconds,
                                                              floor):
    """Every frame after every arpeggio attack in the original, against
    the model `nibble_gate_frames` is: the gate cell starts at
    `nibble_gate_byte`, a skipped call holds the frame before. Measured at
    v0.5.496 (model_check.py): F1 198/0 at 60 s, LVVP 3552/0 (its 73 misses
    there are two-valued vibratos, filtered here), IK 563/0 at 120 s (no
    arpeggio note in its first 60), Kentilla 5354/0, Thrust 75/0."""
    agree, disagree = _trace_check(name, seconds)
    assert disagree == 0 and agree >= floor, (name, agree, disagree)


@pytest.mark.parametrize("counts, period, want", [
    # The plain majority (residue 0, 3 votes) is in the losing class: odd
    # residues hold 4 votes against even's 3, so the refined residue is odd.
    ([3, 2, 0, 2], 2, 1),
    ([3, 2, 0, 0, 0, 2, 0, 0], 4, 1),
    ([0, 2, 0, 2], 2, 1),                 # a tie inside the class: the lower
    ([1, 1, 1, 1], 2, 0),                 # a tie between classes: the lower
    ([0, 0, 5, 0, 0, 0, 6, 0], 4, 6),     # one class, its larger residue
])
def test_the_refined_vote_stays_in_the_arp_walks_class(counts, period, want):
    assert _refined_majority(counts, period) == want


def _converted(name):
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    got = {}
    real = C.build_sng

    def spy(sid, det, tracks, patterns, **kw):
        got["tracks"] = [list(t) for t in tracks]
        got["patterns"] = [list(p) for p in patterns]
        got["gate_skip"] = kw.get("gate_skip")
        got["multiplier"] = kw.get("multiplier")
        return real(sid, det, tracks, patterns, **kw)
    C.build_sng = spy
    try:
        sng = C.convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                        **opts)
    finally:
        C.build_sng = real
    return sng, got


@needs_corpus
@pytest.mark.parametrize("name", ["Formula_1_Simulator",
                                  "Las_Vegas_Video_Poker",
                                  "International_Karate", "Kentilla"])
def test_the_gate_walk_keeps_the_arp_walks_class(name):
    """`nibble_gate_phases` refines `nibble_arp_phases` modulo O and never
    contradicts it modulo the period. F1 and LVVP's lcm IS the period; IK's
    and Kentilla's (period 4, O 10) is 20, where a plain majority over the
    20 residues could leave the class the arp walk voted."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    _, got = _converted(name)
    sid, det = _det(name)
    per = det.arp_nibble_period
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    arp = nibble_arp_phases(sid, det, got["tracks"], got["patterns"])
    gate = nibble_gate_phases(sid, det, got["tracks"], got["patterns"],
                              got["gate_skip"])
    assert gate and set(gate) == set(arp), (gate, arp)
    for instr, r in gate.items():
        assert r % period == arp[instr], (instr, r, arp[instr])
    assert nibble_gate_phases(sid, det, got["tracks"], got["patterns"],
                              None) == {}


@needs_corpus
@pytest.mark.parametrize("name, long_note, floor", [
    ("Formula_1_Simulator", "base", 7), ("Las_Vegas_Video_Poker", "arp", 16)])
def test_the_sng_stretches_the_originals_half(name, long_note, floor):
    """Read back from the .sng (songview, a second reader): every arpeggio
    instrument whose loop is in whole frames carries its long half on the
    half the original stretches, and at least `floor` of them are shaped so
    (F1: its 7 one-step instruments; LVVP: 14 one-step and 2 octave)."""
    import songview
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, got = _converted(name)
    m = got["multiplier"]
    s = songview.parse_sng(sng)
    wt = s.tables["WTBL"]
    left, right = [a for a, _ in wt], [b for _, b in wt]
    shaped = 0
    for ins in s.instruments:
        if not ins.wave_ptr:
            continue
        k, block = ins.wave_ptr - 1, []
        while k < len(left):
            block.append(k)
            if left[k] == 0xFF:
                break
            k += 1
        alts = {right[j] for j in block[:-1] if 0x60 <= right[j] < 0x80}
        if len(alts) != 1:
            continue
        p = ins.wave_ptr
        calls = wave_timeline(left[p - 1:], right[p - 1:], first=p,
                              calls=40 * m + 200)
        notes = [x for _, _, x in calls][m:]
        runs = []
        for x in notes:
            key = "arp" if x in alts else "base"
            if runs and runs[-1][0] == key:
                runs[-1][1] += 1
            else:
                runs.append([key, 1])
        inner = runs[1:-1]
        if not inner or any(n % m for _, n in inner):
            continue                        # not a whole-frame loop
        lo = min(n for _, n in inner)
        longs = {h for h, n in inner if n > lo}
        if not longs:
            continue
        assert longs == {long_note}, (name, ins.number, runs[:12])
        shaped += 1
    assert shaped >= floor, (name, shaped)
