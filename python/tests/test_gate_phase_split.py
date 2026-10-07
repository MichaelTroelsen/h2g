"""The gated nibble counter's residue, split per note.

Opened by nibble-gate-stall-phase (head 3b1c66d): `nibble_gate_phases` gives
each RECORD one residue modulo lcm(P, O), so every note of a record stretches
the half its majority stretches. Las_Vegas_Video_Poker (-S4, O 4, 3-frame
rows) attacks on residues 1 and 3 by row, and the original's one-step first
runs were `base1/arp1` on 82 of 321 notes (ours 1) and its octave's
`base3/arp3` on 5 of 12 (ours 0).

Re-measured at 6e467ff plus the uncommitted cycle-5 merge
(C:/t/lvvp-gate-phase-per-note-split, ab_runs.py / ab_notes.py, subtune 0,
120 s, original at -m1 against the packed conversion under presets):

    first two runs   orig  base1/arp2 239, base1/arp1 82, oct base1/arp3 7,
                           oct base3/arp3 5
                     before base1/arp2 320, base1/arp1 1,  oct base1/arp3 12
                     after  base1/arp2 239, base1/arp1 82, oct 7 / 5
    paired per note  before one 238 same / 83 differ, oct 7 / 5
                     after  one 321 same / 0, oct 12 / 0

The wavetable was 249 of 255 entries before the split; the ten clones cost 3
(`_entered_record_block`). Corpus byte-hash under presets: 95 files, 6
refused in both arms, 89 compared, moved exactly Las_Vegas_Video_Poker.
"""
import json
import pathlib
import sys
from collections import Counter
from itertools import groupby

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from h2g.goatwriter import arpeggio as gw_arpeggio           # noqa: E402
from h2g.goatwriter import (GatePhase, _entered_record_block,  # noqa: E402
                            _orderlist_occurrences, _refined_majority,
                            _same_wave_stream, fixed_arp_period,
                            nibble_gate_note_residues, nibble_gate_phases)

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

LVVP = "Las_Vegas_Video_Poker"

# LVVP's one-step record GT $02 at its majority residue 3, laid out at entry
# 14 (the .sng's own bytes): base1 arp2 | base1 arp1 base1 arp2, the loop
# entered at entry 18.
ONE_STEP = [(0x41, 0x00), (0x02, 0x80), (0x41, 0x7D), (0x06, 0x80),
            (0x41, 0x00), (0x02, 0x80), (0x41, 0x7D), (0x02, 0x80),
            (0x41, 0x00), (0x02, 0x80), (0x41, 0x7D), (0x06, 0x80),
            (0xFF, 18)]
# Its octave record GT $0E at residue 3, at entry 146: base1 arp3 | base2 arp3.
OCTAVE = [(0x41, 0x00), (0x02, 0x80), (0x41, 0x74), (0x0A, 0x80),
          (0x41, 0x00), (0x06, 0x80), (0x41, 0x74), (0x0A, 0x80),
          (0xFF, 150)]


def _table(at, block):
    return [(0x00, 0x00)] * (at - 1) + block


def test_a_residue_whose_block_is_a_later_entry_of_the_records_takes_none():
    """Residue 1's block is the record's from its fifth entry (base1 arp1
    base1 arp2 ...): the clone points there and takes no entries."""
    entries = _table(14, ONE_STEP)
    clone = ([l for l, _ in ONE_STEP[4:12]] + [0xFF],
             [r for _, r in ONE_STEP[4:12]] + [1])
    assert _entered_record_block(clone, entries, 14) == 18


def test_a_residue_needing_a_prefix_gets_the_prefix_and_a_jump():
    """The octave at residue 1 is base3 arp3 | base2 arp3: one extra
    `41/00 02/80` frame of base, then the record's loop from entry 150."""
    entries = _table(146, OCTAVE)
    clone = ([0x41, 0x02, 0x41, 0x06, 0x41, 0x0A, 0x41, 0x06, 0xFF],
             [0x00, 0x80, 0x00, 0x80, 0x74, 0x80, 0x00, 0x80, 5])
    assert _entered_record_block(clone, entries, 146) == (
        [0x41, 0x02, 0xFF], [0x00, 0x80, 150])


def test_a_block_the_record_never_plays_is_left_whole():
    entries = _table(146, OCTAVE)
    clone = ([0x41, 0x02, 0x41, 0x06, 0xFF],
             [0x00, 0x80, 0x73, 0x80, 1])         # a different interval
    assert _entered_record_block(clone, entries, 146) is None


def test_the_stream_check_follows_jumps_and_stops():
    t = [(0x41, 0), (0x02, 0x80), (0xFF, 1)]
    u = [(0x41, 0), (0x02, 0x80), (0x41, 0), (0x02, 0x80), (0xFF, 3)]
    assert _same_wave_stream(t, 1, u, 1)          # the same ring, unrolled
    assert not _same_wave_stream(t, 1, u, 2)      # one entry out of step
    stop = [(0x41, 0), (0xFF, 0)]
    assert _same_wave_stream(stop, 1, [(0x41, 0), (0xFF, 0)], 1)
    assert not _same_wave_stream(stop, 1, t, 1)   # one stops, one loops


def _converted(name, split=True):
    """(sng, the plan build_sng took or None, build_sng's input tracks and
    patterns, multiplier) under presets."""
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    got = {"plans": []}
    real_plan = gw_arpeggio.nibble_gate_phase_split_plan
    real_build = C.build_sng

    def plan(*a, **kw):
        out = real_plan(*a, **kw) if split else None
        got["plans"].append(real_plan(*a, **kw))
        return out

    def build(sid, det, tracks, patterns, **kw):
        got["tracks"] = [list(t) for t in tracks]
        got["patterns"] = [list(p) for p in patterns]
        got["multiplier"] = kw.get("multiplier")
        got["gate_skip"] = kw.get("gate_skip")
        got["sid"], got["det"] = sid, det
        return real_build(sid, det, tracks, patterns, **kw)
    gw_arpeggio.nibble_gate_phase_split_plan = plan
    C.build_sng = build
    try:
        sng = C.convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                        **opts)
    finally:
        gw_arpeggio.nibble_gate_phase_split_plan = real_plan
        C.build_sng = real_build
    return sng, got


@needs_corpus
def test_the_per_note_walk_is_the_majority_walk():
    """`nibble_gate_note_residues`, folded by the sticky instrument, votes
    exactly `nibble_gate_phases`' majority: the same walk, keyed by note."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    _sng, got = _converted(LVVP)
    sid, det = got["sid"], got["det"]
    tracks, patterns, gate = got["tracks"], got["patterns"], got["gate_skip"]
    per = det.arp_nibble_period
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    residues = nibble_gate_note_residues(sid, det, tracks, patterns, gate)
    mod = period * gate // __import__("math").gcd(period, gate)
    votes: dict = {}
    for ti, track in enumerate(tracks):
        cur, seen = 0, Counter()
        for pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            play = seen[pos]
            seen[pos] += 1
            res = residues.get((ti, pos, play), {})
            pat = patterns[p]
            for k in range(len(pat) // 4):
                if pat[4 * k] == 0xFF:
                    break
                if pat[4 * k + 1]:
                    cur = pat[4 * k + 1]
                if k in res and cur:
                    assert res[k].period == period
                    votes.setdefault(cur, [0] * mod)[res[k].residue] += 1
    want = nibble_gate_phases(sid, det, tracks, patterns, gate)
    assert want and {g: _refined_majority(c, period)
                     for g, c in votes.items()} == want
    # Residues 1 and 3 both carry notes: the split has something to do.
    assert {r for c in votes.values() for r in range(mod) if c[r]} >= {1, 3}


@needs_corpus
def test_the_lvvp_clones_enter_their_records_blocks():
    """Every planned clone gets a wave pointer of its own (none is renamed
    onto its record's block), and the table grows only by the octave's
    prefix and jump: 3 entries."""
    import songview
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, got = _converted(LVVP)
    plan = got["plans"][-1]
    assert plan is not None and len(plan.clones) >= 10
    assert all(isinstance(res, GatePhase) for _r, _c, res in plan.clones)
    s = songview.parse_sng(sng)
    # The plan numbers clones from `instr_used + 1`, before the unnamed
    # records are dropped and the numbers close up; the clones stay the last
    # instruments, in plan order, and their records sit below the drop.
    ptr = {ins.number: ins.wave_ptr for ins in s.instruments}
    last = max(ptr)
    for k, (record, _clone, res) in enumerate(plan.clones):
        mine = ptr[last - len(plan.clones) + 1 + k]
        assert mine and mine != ptr[record], (record, res, mine)
    flat = songview.parse_sng(_converted(LVVP, split=False)[0])
    assert len(s.tables["WTBL"]) - len(flat.tables["WTBL"]) == 3


@needs_corpus
@pytest.mark.parametrize("name", ["Bump_Set_Spike", "Thrust", "Warhawk"])
def test_a_split_the_table_cannot_hold_moves_no_byte(name):
    """These three plan gate clones (the plan is not empty) whose blocks the
    full wavetable cannot hold; the dry layout finds them first, so the
    conversion is byte for byte the one without the split."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, got = _converted(name)
    assert got["plans"] and got["plans"][0] is not None
    assert sng == _converted(name, split=False)[0]


def _first_runs(tr, n):
    """{voice: {attack frame: (kind, first two run lengths)}} of the
    two-valued arpeggio notes (ab_runs.py's reading)."""
    def timeline(ev):
        out, cur, ev, k = [None] * n, None, sorted(ev), 0
        for f in range(n):
            while k < len(ev) and ev[k][0] <= f:
                cur = ev[k][1]
                k += 1
            out[f] = cur
        return out
    got = []
    for voice in tr:
        fq, wf = timeline(voice.freq_events), timeline(voice.wf_events)
        starts = [f for f in range(1, n) if wf[f] is not None and wf[f] & 1
                  and not ((wf[f - 1] or 0) & 1)] + [n]
        notes = {}
        for a0, b in zip(starts, starts[1:]):
            a = a0 + 1 if wf[a0] & 8 else a0
            e = a
            while e < b and (wf[e] or 0) & 1:
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
            notes[a0] = (kind, tuple(len(list(g)) for _k, g
                                     in groupby(seg))[:2])
        got.append(notes)
    return got


def _paired(orig, ours):
    tally = Counter()
    for v in range(3):
        lag = max(range(-12, 13),
                  key=lambda d: sum(f + d in ours[v] for f in orig[v]))
        for f, note in orig[v].items():
            mate = next((ours[v][g] for g in (f + lag, f + lag - 1,
                                              f + lag + 1) if g in ours[v]),
                        None)
            tally["unpaired" if mate is None
                  else "same" if mate == note else "differ"] += 1
    return tally


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_every_lvvp_note_opens_on_the_originals_runs(tmp_path):
    """Subtune 0, 60 s: each two-valued arpeggio note of the original, paired
    with ours on the same voice, opens on the same first two runs -- 185
    one-step and 7 octave notes, 43 + 3 of them wrong without the split
    (measured at 6e467ff + merge; the window here is the test's, half the
    task's 120 s). The original carries both kinds of first run, so a test
    agreeing everywhere is not one where every note is the majority's."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    seconds = 60
    n = seconds * 50
    orig = _first_runs(fidelity.run_siddump(CORPUS / f"{LVVP}.sid", seconds,
                                            0, calls=1), n)
    kinds = Counter(note for v in orig for note in v.values())
    assert kinds[("one", (1, 1))] and kinds[("one", (1, 2))]
    assert kinds[("oct", (1, 3))] and kinds[("oct", (3, 3))]
    out = {}
    for split in (True, False):
        sng, got = _converted(LVVP, split=split)
        m = got["multiplier"]
        wd = tmp_path / ("split" if split else "flat")
        wd.mkdir()
        packed = fidelity.pack_sid(sng, wd, multiplier=m)
        out[split] = _paired(orig, _first_runs(
            fidelity.run_siddump(packed, seconds, 0, calls=m), n))
    assert out[True]["differ"] == 0 and out[True]["unpaired"] == 0, out
    assert out[True]["same"] >= 190, out
    assert out[False]["differ"] > 0, out          # the split is what did it
