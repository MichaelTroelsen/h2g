"""The triangle voices an interim model left near chance, re-measured on the
shipped one.

The blocked first pass of triangle-sim-model-fails-on-rasputin-and-one-man
(head 1dde44a) tried an interim model: the tick clock plus per-voice cells
read from the image, still with the 7-call preroll and no KEYOFF fetch and
no lead-in. On the traced subtune it left these voices near chance
(C:/t/triangle-sim-model/reach_check.out, historical): Gremlins v2 9/299,
Phantoms_of_the_Asteroid v0 43/288, Last_V8 v0 10/152 and v2 2/32,
Last_V8_C128_version v2 0/32, Human_Race v1 7/120, Battle_of_Britain v0 20/46.

The model that shipped at 3b1c66d adds the image preroll, the KEYOFF and
instrument-row fetch ticks, the lead-in and the equality turn. Re-measured at
81da71d (exact width at the attack frame, paired by note, presets with
`pulse_phase` forced, first walk, group 0, traced subtune `auto`, 180 s), every
named voice is exact except Human_Race voice 1, which the walk now declines.

ABLATION at 81da71d. Each part of the model was switched off, one at a time,
in a scratch copy of the tree (C:/t/triangle-voices-still-at-chance-under-co/
ablate.py). Each cell is that voice's exact count with that one part removed;
the full model scores the denominator:

| voice | tick clock | voice cell | image dir | preroll | KEYOFF fetch | lead-in |
|---|---|---|---|---|---|---|
| Gremlins v2 /299 | 299 | 9 | 15 | 299 | 64 | 299 |
| Phantoms v0 /288 | 38 | 94 | 288 | 288 | 25 | 43 |
| Last_V8 v0 /152 | 16 | 14 | 30 | 152 | 6 | 5 |
| Last_V8 v2 /32 | 4 | 16 | 32 | 32 | 32 | 32 |
| Last_V8_C128 v2 /32 | 2 | 32 | 32 | 16 | 3 | 2 |
| Battle_of_Britain v0 /46 | 6 | 16 | 41 | 46 | 16 | 41 |

Five of the six voices need the KEYOFF fetch or the lead-in, which the interim
model lacked. Last_V8 v2 needs neither; why the interim model missed it was
not traced, because interim model.py is not the shipped code. Removing the
instrument-row
fetch or the equality turn moves none of these voices. Those two parts have
their own carriers, Zoids and Commando, in test_pulse_phase.py's
`_EXACT_WIDTHS`.

HUMAN_RACE IS THE RESIDUAL, and its cause is one mechanism. Subtune 0 voice 1
sweeps image instrument 1 (record 0) before its first instrument byte while
voice 0 sounds that same record. Width is per RECORD and direction is per
VOICE, so on that tick both voices step record 0. The original's trace shows
this: frame 0 is $800 on both voices, and at frame 1 voice 1 reads $880 and
voice 0 reads $900, which is two $80 steps on one record in one tick, X=1
then X=0. The walk does not model a record that two voices sweep, so it
declines voice 1. Voice 0's record-0 notes then miss the steps voice 1 added:
all 35 of voice 0's misses are on instrument 1, and its 417 instrument-4 notes
are exact. Fixing this is the lockstep walk, task triangle-lockstep-walk. When
that walk lands, the Human_Race figures here are expected to change.
"""
from __future__ import annotations

import collections
import difflib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import (_NOTE_NAMES, _corpus_and_presets,  # noqa: E402
                              _first_walk)

# (file, {voice: (exact, paired)}) on the traced subtune, group 0, 180 s.
_NAMED = [
    ("Gremlins.sid", {2: (299, 299)}),
    ("Phantoms_of_the_Asteroid.sid", {0: (288, 288)}),
    ("Last_V8.sid", {0: (152, 152), 1: (540, 540), 2: (32, 32)}),
    ("Last_V8_C128_version.sid", {0: (152, 152), 1: (540, 540), 2: (32, 32)}),
    ("Human_Race.sid", {0: (422, 457)}),
    # Re-pinned 2026-10-05 (runqueue merge): one-man-restrike-at-attack-856
    # stops the tied-slide restrikes, so more notes pair by name; every pair
    # is still exact. Was {0: (46, 46), 1: (94, 94), 2: (5, 5)}.
    ("Battle_of_Britain.sid", {0: (63, 63), 1: (111, 111), 2: (5, 5)}),
]
_SECONDS = 180
_TRACES: dict = {}


def _trace(name: str):
    import fidelity as F
    if name in _TRACES:
        return _TRACES[name]
    corpus, doc = _corpus_and_presets()
    if not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip("siddump not available here")
    wd = Path(tempfile.mkdtemp(prefix="tri_named_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(corpus / name, local)
        cal, _ = F.table_calibration(corpus / name, F._preset_opts(doc, name))
        trace = F.run_siddump(local, _SECONDS,
                              F.resolve_subtune(corpus / name, "auto"),
                              F.SIDDUMP, cal)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    _TRACES[name] = trace
    return trace


def _pairs(name: str) -> dict:
    """{voice: [(instrument, planned width, original width), ...]} for group 0
    of the first walk against the traced subtune. Notes are paired by name
    (difflib, runs of 8 or more), the same convention as test_pulse_phase's
    `_exact_widths`."""
    import fidelity as F
    from h2g import patterns as P
    cap = _first_walk(name)
    trace = _trace(name)
    nf = _SECONDS * 50
    planned = {(ti, pos, r): ph for ti, pos, rows in cap["plan"][1]
               for r, ph in rows.items()}
    out = {}
    for v in range(3):
        notes, live = [], 0
        for pos, b in enumerate(cap["tracks"][v]):
            if b == P.GT_ORDER_RESTART:
                break
            if b >= P.MAX_PATTERNS or b >= len(cap["patterns"]):
                continue
            pat = cap["patterns"][b]
            for r, kind, instr in P._phase_note_rows(pat, live, {}):
                if instr:
                    live = instr
                if kind != "note" or pat[4 * r + 2] == P.CMD_TONEPORTA:
                    continue
                n = pat[4 * r] - P.GT_FIRSTNOTE
                notes.append((instr, f"{_NOTE_NAMES[n % 12]}{n // 12}",
                              planned.get((v, pos, r))))
        if not any(ph for _, _, ph in notes):
            continue
        t = F.register_timeline(trace[v].pulse_events, nf)
        orig = [(t[f], trace[v].attacks[k])
                for k, f in enumerate(trace[v].attack_frames) if f + 1 < nf]
        sm = difflib.SequenceMatcher(None, [n for _, n, _ in notes],
                                     [o[1] for o in orig], autojunk=False)
        rows = [(notes[m.a + k][0], notes[m.a + k][2][1][0], orig[m.b + k][0])
                for m in sm.get_matching_blocks() if m.size >= 8
                for k in range(m.size) if notes[m.a + k][2] is not None]
        if rows:
            out[v] = rows
    return out


def test_the_named_voices_open_on_the_originals_width():
    """Each named voice's exact/paired count, re-measured. If the walk's
    clock, voice cells, image direction, preroll, KEYOFF fetch or lead-in is
    removed, at least one entry falls (see the ablation table above)."""
    bad = {}
    for name, want in _NAMED:
        got = {v: (sum(p == o for _, p, o in rows), len(rows))
               for v, rows in _pairs(name).items()}
        if got != want:
            bad[name] = (got, want)
    assert not bad, bad


def test_human_races_misses_are_the_record_its_declined_voice_shares():
    """Human_Race subtune 0: voice 1 is not planned (declined: its lead-in
    sweeps record 0 while voice 0 sounds it). Every voice-0 miss is on
    instrument 1, which is that record. The original shows both voices
    stepping record 0 in one tick."""
    pairs = _pairs("Human_Race.sid")
    assert 1 not in pairs, "voice 1 is planned -- the decline has moved"
    miss = collections.Counter(i for i, p, o in pairs[0] if p != o)
    hit = collections.Counter(i for i, p, o in pairs[0] if p == o)
    assert miss == {1: 35}, miss
    assert hit == {1: 5, 4: 417}, hit
    import fidelity as F
    trace = _trace("Human_Race.sid")
    t0, t1 = (F.register_timeline(trace[v].pulse_events, 3) for v in (0, 1))
    assert (t0[0], t1[0]) == (0x800, 0x800), (hex(t0[0]), hex(t1[0]))
    # X=1 steps record 0 by $80 and voice 1 reads it; X=0 steps it again.
    assert (t1[1], t0[1]) == (0x880, 0x900), (hex(t1[1]), hex(t0[1]))
