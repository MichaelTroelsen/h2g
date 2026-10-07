"""The attack's own counter step is `h = m (O + 1) / O` calls, not one frame.

Opened by nibble-gate-stall-phase (3b1c66d): International_Karate and
Kentilla (O 10, -S10) stretch the base note of their 11-call one-step
halves, ours the other note. The exact ten-half cycle the original's frames
make is capped out (`NIBBLE_GATE_MAX_HALVES`), so these records keep the
evenly spread 11-call halves -- and those were on the right lattice but a
call early: the phased shapes put the first run after a frame-0 lead of `m`
calls where the attack's passing call, like every later one, lasts `h`
(`call_phase.nibble_gate_step_lead`). One call moves which sampled half the
gate's skipped frame lengthens.

Measured at 6e467ff + the cycle-6 merge (C:/t/ik-kentilla-gate-long-half,
abnote.py: each original note paired with ours by voice and onset, its frame
sequence compared over the frames both hold it):

    International_Karate 120 s, one-step `$5800`   exact 0/51  -> 51/51
    Kentilla 120 s, one-step `$0C00`/`$090A`       exact 4/86  -> 52/86
    Warhawk 120 s, gate-agnostic                   exact 35/421 -> 421/421
    Proteus 120 s, gate-agnostic                   exact 155/517 -> 517/517

Kentilla's other 34 are the wavetable budget, not this: its records 6, 12,
13 and 14 are emitted in a 5-entry budget (a full table), where the phased
9-entry shape does not fit and the unphased loop -- the alternation from the
attack -- stands (C:/t/ik-kentilla-gate-long-half/shape_log.py; the 34 are
exactly the notes whose first interval call is +11, not +22).
"""
import math
import pathlib
import sys
from collections import Counter
from itertools import groupby

import pytest

from corpus import CORPUS, needs_corpus
from test_call_rate import wave_timeline

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import (_nibble_gate_shape,              # noqa: E402
                            _wavetable_entries, entry_gate,
                            fixed_arp_period, nibble_arp_counter_gated,
                            nibble_gate_step_lead, outer_gate_skip)
from h2g.goatwriter import call_phase as _call_phase         # noqa: E402
from h2g.goatwriter import wavetable as _wavetable           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda *a: None)


@needs_corpus
@pytest.mark.parametrize("name, m, gate", [
    ("International_Karate", 10, 10), ("Kentilla", 10, 10),
    ("Warhawk", 7, 7), ("Proteus", 7, 7), ("Las_Vegas_Video_Poker", 4, 4)])
def test_the_lead_is_the_whole_counter_step(name, m, gate):
    """h - m: one call at each file's preset multiplier, O read off the file."""
    sid, det = _det(name)
    assert outer_gate_skip(sid, 0) == gate
    assert nibble_gate_step_lead(sid, det, m, gate, False) == m // gate


@needs_corpus
def test_no_lead_where_any_precondition_fails():
    sid, det = _det("International_Karate")
    assert nibble_gate_step_lead(sid, det, 10, 10, True) == 0   # firstwave
    assert nibble_gate_step_lead(sid, det, 10, None, False) == 0
    # h = 15 * 11 / 10 = 16.5 calls: a spread cycle, not a whole step
    assert nibble_gate_step_lead(sid, det, 15, 10, False) == 0
    assert nibble_gate_step_lead(sid, det, 20, 10, False) == 2


@needs_corpus
def test_no_lead_without_the_entry_gate():
    """Bump_Set_Spike (-S5, O 5): h = 6 is whole and its counter is gated,
    but the play address enters below the gate, so nothing anchors our
    lattice to the original's frames (`startup_phase`'s precondition)."""
    sid, det = _det("Bump_Set_Spike")
    assert outer_gate_skip(sid, 0) == 5
    assert nibble_arp_counter_gated(sid, det.arp_nibble_period)
    assert not entry_gate(sid)
    assert nibble_gate_step_lead(sid, det, 5, 5, False) == 0


@needs_corpus
def test_no_lead_where_the_counter_is_not_behind_the_gate(monkeypatch):
    """Chicken_Song's nibble counter steps on every call; with the entry
    gate forced, only the counter's own reading keeps the lead at 0."""
    sid, det = _det("Chicken_Song")
    assert not nibble_arp_counter_gated(sid, det.arp_nibble_period)
    monkeypatch.setattr(_call_phase, "entry_gate", lambda s: True)
    assert nibble_gate_step_lead(sid, det, 10, 10, False) == 0


def _note_runs(left, right, calls):
    timeline = wave_timeline(left, right, first=6, calls=calls)
    notes = [n for _, _, n in timeline]
    waves = [w for _, w, _ in timeline]
    runs, at = [], 0
    for n, g in groupby(notes):
        k = len(list(g))
        runs.append((n, at, k))
        at += k
    return runs, waves


@needs_corpus
@pytest.mark.parametrize("name, rec, m, gate, ticked", [
    ("International_Karate", 7, 10, 10, False),
    ("International_Karate", 9, 10, 10, True),
    ("Kentilla", 8, 10, 10, False),
    ("Warhawk", 15, 7, 7, True),
    ("Warhawk", 23, 7, 7, False),
])
def test_every_half_boundary_is_on_the_lattice_from_the_onset(name, rec, m,
                                                              gate, ticked):
    """Per call through gplay's wavetable loop: every note change is a whole
    number of counter steps (`h` calls) after the onset, the first one
    included -- one call early, and the frame sampling puts the gate's long
    half on the other note. The ticked record's noise tick starts on the
    lattice too: the attack's step is the frame-0 waveform's."""
    sid, det = _det(name)
    h = m * (gate + 1) // gate
    left, right = _wavetable_entries(sid, det, rec, True, "gts5", [], m,
                                     budget=255, start=6, gate_skip=gate,
                                     arp_phase=1)
    runs, waves = _note_runs(left, right, 12 * h)
    assert len(runs) >= 6, runs
    starts = [at for _, at, _ in runs[1:]]
    assert all(at % h == 0 for at in starts), (starts, left, right)
    assert all(k == h for _, _, k in runs[2:-1]), runs
    assert runs[0][0] == 0x00 and runs[0][2] >= h, runs    # lead: base note
    assert waves[:h] == [left[0]] * h
    if ticked:
        assert waves[h] != left[0] and waves[h] & 0x80, (waves[:2 * h], left)


@needs_corpus
def test_a_gate_shaped_record_keeps_its_bytes(monkeypatch):
    """Where `_nibble_gate_shape` lays the original's own frames (LVVP, the
    gate a multiple of the period) its first run already starts on the
    original's frame: the step lead is not applied, and every such record's
    bytes are what they are with the lead forced to 0."""
    sid, det = _det("Las_Vegas_Video_Poker")
    per = det.arp_nibble_period
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    seen = 0
    for rec in range(32):
        at = det.instr_start + rec * det.instr_stride + 7
        if at >= len(sid.data) or not (sid.data[at] & 4 and sid.data[at] >> 4):
            continue
        for gp in range(period * 4 // math.gcd(period, 4)):
            if _nibble_gate_shape(sid, det, sid.data[at] >> 4, 4, 4,
                                  gp) is None:
                continue
            kw = dict(budget=255, start=6, gate_skip=4, arp_phase=gp % period,
                      arp_gate_phase=gp)
            real = _wavetable_entries(sid, det, rec, True, "gts5", [], 4, **kw)
            with monkeypatch.context() as mp:
                mp.setattr(_wavetable, "nibble_gate_step_lead",
                           lambda *a, **k: 0)
                none = _wavetable_entries(sid, det, rec, True, "gts5", [], 4,
                                          **kw)
            assert real == none, (rec, gp)
            seen += 1
    assert seen >= 4, seen


# -- against the original, both traced ---------------------------------

def _timeline(ev, n):
    out, cur, ev, k = [None] * n, None, sorted(ev), 0
    for f in range(n):
        while k < len(ev) and ev[k][0] <= f:
            cur = ev[k][1]
            k += 1
        out[f] = cur
    return out


def _notes(tr, n, gated):
    """{(voice, attack frame): (kind, frame sequence: True = not the first
    gated frame's value)} of the two-valued arpeggio notes. `gated` reads a
    note to its gate's fall; otherwise to the next attack (at most 60 frames)
    or the first frame holding a third value -- Warhawk and Proteus drop the
    gate a frame after the attack and arpeggiate on through the release."""
    got = {}
    for vi, voice in enumerate(tr):
        fq, wf = _timeline(voice.freq_events, n), _timeline(voice.wf_events, n)
        starts = [f for f in range(1, n) if wf[f] is not None and wf[f] & 1
                  and not ((wf[f - 1] or 0) & 1)] + [n]
        for a0, b in zip(starts, starts[1:]):
            a = a0 + 1 if wf[a0] & 8 else a0
            if gated:
                e = a
                while e < b and (wf[e] or 0) & 1:
                    e += 1
            else:
                e, two = a, []
                while e < min(b, a + 60):
                    if fq[e] not in two:
                        if len(two) == 2:
                            break
                        two.append(fq[e])
                    e += 1
            seg = fq[a:e]
            vals = set(seg)
            if len(vals) != 2 or e - a < 6:
                continue
            b0 = seg[0]
            o = (vals - {b0}).pop()
            ratio = max(b0, o) / min(b0, o)
            if ratio < 1.05:
                continue                    # a two-valued vibrato
            kind = "oct" if abs(ratio - 2) < 0.02 else "one"
            got[(vi, a0)] = (kind, tuple(v != b0 for v in seg))
    return got


def _paired(orig, ours):
    lag = Counter(u[1] - o[1] for o in orig for u in ours
                  if u[0] == o[0] and abs(u[1] - o[1]) <= 12).most_common(1)
    lag = lag[0][0] if lag else 0
    tally = Counter()
    for (v, f), (kind, seq) in orig.items():
        mate = ours.get((v, f + lag))
        if mate is None:
            continue
        k = min(len(seq), len(mate[1]))
        tally[(kind, "exact" if seq[:k] == mate[1][:k] else "differ")] += 1
    return tally


def _converted(name):
    import json
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None, **opts)
    return sng, fidelity._preset_multiplier(doc, f"{name}.sid")


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name, seconds, gated, floors", [
    # one-step exact floors; base (the m-call lead) read 0, 0 and 28
    ("International_Karate", 120, True, {"one": 51}),
    ("Warhawk", 60, False, {"one": 121, "oct": 33}),
    ("Proteus", 60, False, {"one": 159, "oct": 79}),
])
def test_every_paired_note_plays_the_originals_frames(tmp_path, name,
                                                      seconds, gated, floors):
    """Subtune 0: each two-valued arpeggio note of the original, paired with
    ours on its voice at the modal lag, carries the same frame sequence --
    the long half on the note the original stretches, on every note."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    n = seconds * 50
    orig = _notes(fidelity.run_siddump(CORPUS / f"{name}.sid", seconds, 0,
                                       calls=1), n, gated)
    sng, m = _converted(name)
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    got = _paired(orig, _notes(fidelity.run_siddump(packed, seconds, 0,
                                                    calls=m), n, gated))
    for kind, floor in floors.items():
        assert got[(kind, "differ")] == 0, (name, got)
        assert got[(kind, "exact")] >= floor, (name, got)
