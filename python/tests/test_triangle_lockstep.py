"""The triangle pulse walk in LOCKSTEP (`patterns._walk_triangle_group`).

The triangle engine's width is per RECORD and its direction and delay counter
per VOICE (goatwriter.PulsePhaseSim), so a record two voices sweep is stepped
by both, each on its own cell. The walk used to take voices one at a time and
DECLINE what that could not follow -- the whole subtune where a record sounded
on two voices ("a record sounds on two voices of subtune N; the accumulator is
shared and the plan declines the subtune"), a voice whose lead-in swept a
record another voice sounded ("that lead-in is not modelled and the voice is
declined"). Rows are synchronous across a group's voices -- one speed gate,
`frames_for` ticks a row for all three -- so it now walks them together, tick
by tick, X = 2, 1, 0 within each tick: the player's own loop order. Human_Race
subtune 0 is the carrier the order was read off: at frame 1 the original
reads $880 on voice 1 and $900 on voice 0, two $80 steps on record 0 in one
tick, X = 1 then X = 0 (test_triangle_named_voices.py pins that trace).

MEASURED (presets with `pulse_phase` forced, the first walk, 180 s, against
each original's siddump; base = the walk before this change). Exact width at
the attack frame, paired by NOTE (test_pulse_phase's `_exact_widths`: difflib
on note names, runs of 8 or more):

| file | traced/walked | base | lockstep |
|---|---|---|---|
| Human_Race | 0/0 | v0 422/457, v1 declined | v0 457/457, v1 120/120 |
| Chimera | 0/0 | declined | v0 132/132, v1 135/135 (96/135 before record 8's regates) |
| Devils_Galop | auto/0 | declined | v0 551/551, v1 60/60, v2 32/33 |
| Monty_on_the_Run | 0/0 | declined | v0 405/405, v1 60/60, v2 33/33 |
| Ninja | auto/0 | declined | v0 93/93, v1 28/28, v2 102/102 |
| Thing_on_a_Spring | auto/0 | declined | v0 225/225, v1 25/25, v2 871/871 |

The Thing_on_a_Spring row is the walk reading the decoder's event starts
(`event_rows`, task decoder-event-start-rows, merged in the same cycle as this
one). RETRACTED for the merged tree: "Thing_on_a_Spring | auto/0 | declined |
v0 144/225, v1 0/25, v2 871/871" -- that was this walk reading the bytes
alone, and is what it still reads with `_triangle_rows`' `event_rows`
threading removed.

Three of the shortfalls this branch measured were not the walk's, and the
tests below say which; the third is gone since the merge:

* **Chimera v1 and Devils_Galop v2 are pairing slips.** Paired by TIME instead
  -- each planned first-pass note at its fetch tick against the original's
  width on that frame (a tick is a frame on both: no outer gate) -- every one
  is exact (Chimera v1 324 of 324 planned note rows in the window, ties
  included -- 223 without them, the count the name pairing starts from;
  Devils_Galop v2 39 of 40, the one being its tick-0 note, which the
  original never sounds: its frame-0 register is still empty). Voice 1 of
  Chimera plays many notes the original does not attack (no gate edge), so
  the name alignment pairs some planned notes with the wrong attack.
  Chimera's half of it closed once the 49 attacks after record 8's `$10`
  rows stopped being spelt as ties (patterns.record_gate_clear,
  tests/test_gate_clear_record.py): the name pairing reads 135/135 and the
  packed output reaches 135 of 135 (134 of 134 before).
* **Thing_on_a_Spring v0 and v1 were the decoder's, not the walk's.** Voice 0
  holds $8C0 for three frames at 1151-1153 where the bytes-only walk stepped
  on 1153: the original FETCHES there (its ADSR is rewritten on frame 1153,
  the gate stays off), a no-note event with no instrument byte, which
  reached the walk as a plain hold row ("A no-note event with neither is a
  plain hold row here and is not seen" -- task decoder-event-start-rows).
  From there voice 0's counter ran a frame off, and voice 1's 25 notes
  opened on record 0 after voice 0 swept it, one $40 step off. Voice 2,
  which shares nothing with them, is 871 of 871. PROBED before the merge
  (C:/t/triangle-lockstep-walk/probe_tos_fetch.py): marking as fetches the
  hold rows whose frame carries a non-zero ADSR write and no attack in the
  original -- 24 rows on voice 0, 1 on voice 1 -- took the three voices to
  225/225, 25/25 and 871/871. MERGED: the decoder's event starts hand the
  walk 34 hidden fetches here (31 on voice 0, 2 on voice 1, 1 on voice 2),
  the frame-1153 row among them, and reach the same figures;
  `test_thing_on_a_springs_frame_1153_fetch_is_the_decoders` pins that
  carrier.

WHAT IT COSTS THE OUTPUT, forced flag only (no preset of the six ships
`pulse_phase`, so the shipped corpus does not move). The plan's extra writes
take pattern copies and table rows from later subtunes: on Human_Race the
pattern table fills sooner (25 clone drops where there were 17) and record 21
no longer fits the pulse table, so subtune 3 voice 0 and subtune 4 voice 0
lose the phases they shipped. `test_what_reaches_the_packed_output` pins the
reach per voice; capacity is allocated in subtune order, which is where that
gets fixed, not here.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import (_corpus_and_presets,  # noqa: E402
                              _exact_widths)

from h2g.goatwriter import PulsePhaseSim
from h2g.patterns import (GT_NO_NOTE, GT_ORDER_RESTART, GT_REPEAT,
                          collect_pulse_phases)


def _pattern(rows: list) -> list:
    """rows: (note, instr) pairs; a note of None is a hold row."""
    out: list = []
    for note, instr in rows:
        out += [GT_NO_NOTE if note is None else note, instr, 0, 0]
    return out + [0xFF, 0, 0, 0]


def _sim(width=0x900, step=0x40, delay=1):
    return PulsePhaseSim(width, step, delay, 8, 0xE)


_STOP = [GT_ORDER_RESTART, 0x01]       # restart operand past a 1-entry list


# --------------------------------------------------------------------------
# The mechanism, one shape each
# --------------------------------------------------------------------------

def test_the_player_order_within_a_tick_is_x_2_1_0():
    """Voices 0 and 2 both sweep record 2, one tick a row. Tick 0: voice 2
    fetches FIRST and reads $900; voice 0 then steps it to $940. Tick 1:
    voice 2 steps it to $980 and voice 0's fetch reads that. In the order
    0, 1, 2 both notes would open on $940."""
    pat0 = _pattern([(None, 0), (0x70, 2)])     # v0: hold (lead-in), note
    pat2 = _pattern([(0x72, 2), (None, 0)])     # v2: note, hold
    rest = _pattern([(None, 0), (None, 0)])
    tracks = [[0] + _STOP, [1] + _STOP, [2] + _STOP]
    start = [(0, ((2, +1, 0), (0, +1, 0), (2, +1, 0)))]
    got = collect_pulse_phases([pat0, rest, pat2], tracks, [1], {2: _sim()},
                               tri_start=start)
    assert got is not None
    assert sorted(got[1]) == [(0, 0, {1: (2, (0x980, +1))}),
                              (2, 0, {0: (2, (0x900, +1))})], got[1]


def test_two_voices_in_opposite_directions_hold_one_width():
    """Record 2 at $A00 swept by voice 1 DOWN and voice 0 UP, one step a
    tick each: every tick X = 1 takes $40 off and X = 0 puts it back, so
    after four ticks it is still $A00. Tick 4: voice 1 steps it to $9C0
    and voice 0's fetch opens on ($9C0, up); tick 5: voice 1's fetch
    opens on ($9C0, down) -- voice 0 fetched on tick 4 and did not step.
    Walked one voice at a time, voice 0 alone would have opened on $B00."""
    pat0 = _pattern([(None, 0)] * 4 + [(0x70, 2), (None, 0)])
    pat1 = _pattern([(None, 0)] * 5 + [(0x72, 2)])
    tracks = [[0] + _STOP, [1] + _STOP, [GT_ORDER_RESTART, 0x00]]
    start = [(0, ((2, +1, 0), (2, -1, 0), (0, +1, 0)))]
    got = collect_pulse_phases([pat0, pat1], tracks, [1],
                               {2: _sim(0xA00)}, tri_start=start)
    assert got is not None
    assert got[1] == [(0, 0, {4: (2, (0x9C0, +1))}),
                      (1, 0, {5: (2, (0x9C0, -1))})], got[1]


def test_a_voice_the_walk_cannot_plan_still_sweeps_what_it_shares():
    """Voice 1's orderlist folds 16 x 16 plays of a one-row hold pattern,
    256 entries past `MAX_TRACK_LEN`: it cannot be expanded, so it is not
    planned (logged) -- but it is PLAYED, and it sweeps record 2 under its
    lead-in every tick. Voice 0's notes on that record see its steps:
    $940 and $A00, where without voice 1 they would open on $900 and
    $980."""
    pat0 = _pattern([(0x70, 2), (None, 0), (0x72, 0), (None, 0)])
    pat1 = _pattern([(None, 0)])
    tracks = [[0] + _STOP, [GT_REPEAT + 15, 1] * 16 + [GT_ORDER_RESTART, 0],
              [GT_ORDER_RESTART, 0x00]]
    start = [(0, ((2, +1, 0), (2, +1, 0), (0, +1, 0)))]
    logs: list = []
    got = collect_pulse_phases([pat0, pat1], tracks, [1], {2: _sim()},
                               logs.append, tri_start=start)
    assert got is not None
    assert got[1] == [(0, 0, {0: (2, (0x940, +1)), 2: (2, (0xA00, +1))})], got[1]
    assert any("subtune 0 voice 1 cannot expand" in m and "still played" in m
               for m in logs), logs


def test_a_voice_sweeps_on_until_every_planned_voice_is_through():
    """Voice 0 loops a one-row hold under its lead-in (record 2) and is
    through its second pass after two ticks; voice 1's first pass reaches
    its note on record 2 only at row 6. Voice 0 keeps playing meanwhile,
    as the original's would, so the note opens on six of its steps,
    $A80 -- not on the two a walk stopping each voice at its own second
    pass would leave."""
    pat0 = _pattern([(None, 0)])
    pat1 = _pattern([(None, 0)] * 6 + [(0x70, 2)])
    tracks = [[0, GT_ORDER_RESTART, 0x00], [1] + _STOP,
              [GT_ORDER_RESTART, 0x00]]
    start = [(0, ((2, +1, 0), (0, +1, 0), (0, +1, 0)))]
    got = collect_pulse_phases([pat0, pat1], tracks, [1], {2: _sim()},
                               tri_start=start)
    assert got is not None
    assert got[1] == [(1, 0, {6: (2, (0xA80, +1))})], got[1]


def test_the_preroll_runs_in_the_players_order_too():
    """One tick of preroll with voices 2 (up) and 1 (down) both on record 2
    at $DC0. X = 2 first: $E00, whose nibble is the top bound, so voice 2
    turns DOWN; X = 1 then takes it back to $DC0. Voice 2's note on tick 0
    opens on ($DC0, down). In the order 0, 1, 2 voice 1 would go first
    ($D80), voice 2 would reach only $DC0 and never turn: ($DC0, up)."""
    pat1 = _pattern([(None, 0), (None, 0)])
    pat2 = _pattern([(0x70, 2), (None, 0)])
    tracks = [[GT_ORDER_RESTART, 0x00], [0] + _STOP, [1] + _STOP]
    start = [(1, ((0, +1, 0), (2, -1, 0), (2, +1, 0)))]
    got = collect_pulse_phases([pat1, pat2], tracks, [1], {2: _sim(0xDC0)},
                               tri_start=start)
    assert got is not None
    assert got[1] == [(2, 0, {0: (2, (0xDC0, -1))})], got[1]


def test_a_shared_block_lays_the_plain_loop_for_an_off_bound_phase():
    """`_phase_block(share=True)` chains a record's lattice phases into its
    legs only where every phase lands on its bound. A phase that does not
    -- ($080, down) beside lattice phases, the shape the lockstep walk
    gives Human_Race's record 2 -- ran into a chained leg's set rows and
    was snapped onto the lattice ($080 $0C0 $880 ...) where its per-phase
    block plays $080 $0C0 $100 ... So that record lays its per-phase block,
    and every entry plays, call for call, what it plays there."""
    from h2g.goatwriter import pulse as PU
    from test_pulse_phase import _play_pulse_table
    want = {(0x800, +1), (0x880, +1), (0x900, -1), (0xA00, +1),
            (0x080, -1)}
    params = (0x800, 0x40, 0x800, 0xE00, False)
    assert PU._union_kind(want, *params[1:]) is None
    per, per_idx = PU._phase_block(0, 2, want, *params, share=False)
    sh, sh_idx = PU._phase_block(0, 2, want, *params, share=True)
    assert set(per_idx) == set(sh_idx)
    for key in per_idx:
        assert (_play_pulse_table(sh, sh_idx[key], 400)
                == _play_pulse_table(per, per_idx[key], 400)), key
    # and a record whose every phase lands is still chained (shorter)
    lands = want - {(0x080, -1)}
    assert PU._union_kind(lands, *params[1:]) == "chained"
    assert (len(PU._phase_block(0, 2, lands, *params, share=True)[0])
            < len(PU._phase_block(0, 2, lands, *params, share=False)[0]))


def test_where_no_record_is_shared_the_voices_plan_as_if_alone():
    """Three voices on three records, with a lead-in, a KEYOFF and an
    instrument row among them: each voice's plan in the three-voice walk
    is exactly its plan walked with the other two orderlists empty. The
    lockstep changes a plan only through a record two voices sweep."""
    from h2g.patterns import GT_KEYOFF
    pats = [_pattern([(None, 0), (0x70, 2), (GT_KEYOFF, 0), (0x71, 0)]),
            _pattern([(0x72, 3), (None, 0), (None, 3), (0x73, 0)]),
            _pattern([(None, 0), (None, 0), (0x74, 4), (None, 0)])]
    sims = {2: _sim(0x900, 0x40, 2), 3: _sim(0xC00, 0x20, 1),
            4: _sim(0x800, 0x60, 3)}
    start = [(2, ((2, -1, 1), (3, +1, 0), (4, +1, 2)))]
    full = [[v, GT_ORDER_RESTART, 0x00] for v in range(3)]

    def plan(tracks):
        got = collect_pulse_phases(pats, [list(t) for t in tracks], [3],
                                   {n: s.clone() for n, s in sims.items()},
                                   tri_start=start)
        return sorted(got[1]) if got else []
    together = plan(full)
    alone = []
    for v in range(3):
        tracks = [[GT_ORDER_RESTART, 0x00] for _ in range(3)]
        tracks[v] = full[v]
        alone += plan(tracks)
    assert together and together == sorted(alone), (together, alone)
    assert {ti for ti, _, _ in together} == {0, 1, 2}


# --------------------------------------------------------------------------
# The corpus: the declines it lifts, against the originals
# --------------------------------------------------------------------------

_LIFTED = [
    # (file, seconds, subtune traced, group walked, {voice: (exact, paired)})
    ("Human_Race.sid", 180, 0, 0, {0: (457, 457), 1: (120, 120)}),
    ("Chimera.sid", 180, 0, 0, {0: (132, 132), 1: (135, 135)}),
    ("Devils_Galop.sid", 180, None, 0, {0: (551, 551), 1: (60, 60), 2: (32, 33)}),
    ("Monty_on_the_Run.sid", 180, 0, 0, {0: (405, 405), 1: (60, 60), 2: (33, 33)}),
    ("Ninja.sid", 180, None, 0, {0: (93, 93), 1: (28, 28), 2: (102, 102)}),
    # With the decoder's event starts; (144, 225) / (0, 25) by bytes alone.
    ("Thing_on_a_Spring.sid", 180, None, 0,
     {0: (225, 225), 1: (25, 25), 2: (871, 871)}),
]


def test_the_lifted_declines_open_on_the_originals_width():
    """The table in the module docstring, re-measured. Every row was a
    declined subtune or voice before the lockstep; removing it (or walking
    the voices one at a time) moves every row."""
    bad = {}
    for name, seconds, sub, group, want in _LIFTED:
        got = _exact_widths(name, seconds, sub, group)
        if got != want:
            bad[(name, sub)] = (got, want)
    assert not bad, bad


_WALKS: dict = {}


def _walk_args(name: str) -> dict:
    """The first walk convert() makes on `name` (presets, `pulse_phase`
    forced) with its arguments: the per-group ticks a row, `tri_start` and
    the decoder's `event_rows`."""
    if name in _WALKS:
        return _WALKS[name]
    import fidelity
    from h2g import convert as C
    corpus, doc = _corpus_and_presets()
    if not (corpus / name).exists():
        import pytest
        pytest.skip(f"{name} not in the corpus here")
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    cap: dict = {}
    real = C.collect_pulse_phases

    def walk(pats, tracks, tempos, *a, **kw):
        r = real(pats, tracks, tempos, *a, **kw)
        if "plan" not in cap:
            cap.update(patterns=[list(p) for p in pats],
                       tracks=[list(t) for t in tracks], plan=r,
                       tempos=list(tempos), tri_start=kw.get("tri_start"),
                       event_rows=kw.get("event_rows"))
        return r
    C.collect_pulse_phases = walk
    try:
        C.convert(str(corpus / name), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases = real
    assert cap.get("plan"), f"{name}: the walk planned nothing"
    _WALKS[name] = cap
    return cap


def _time_paired(name: str, seconds: int, sub: int, group: int, v: int):
    """[(fetch tick, planned width, the original's width on that frame)]
    for every planned first-pass note of one voice inside the window. A
    tick is taken as a frame -- right only on a player without an outer
    gate whose speed counter ticks once a frame, which both callers are."""
    import fidelity as F
    from h2g import patterns as P
    corpus, doc = _corpus_and_presets()
    if not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip("siddump not available here")
    cap = _walk_args(name)
    ti = 3 * group + v
    track = cap["tracks"][ti]
    songlen = next(k for k, b in enumerate(track) if b == GT_ORDER_RESTART)
    planned = {(t, pos, r): ph for t, pos, rows in cap["plan"][1]
               for r, ph in rows.items()}
    wd = Path(tempfile.mkdtemp(prefix="tri_lockstep_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(corpus / name, local)
        cal, _ = F.table_calibration(corpus / name, F._preset_opts(doc, name))
        trace = F.run_siddump(local, seconds, sub, F.SIDDUMP, cal)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    nf = seconds * 50
    orig = F.register_timeline(trace[v].pulse_events, nf)
    tick, tempo = cap["tri_start"][group][0], cap["tempos"][group]
    out = []
    for npass, pos, r, kind, instr, fetch in P._triangle_rows(
            track, songlen, track[songlen + 1], cap["patterns"],
            cap["event_rows"]):
        if npass or tick >= nf:
            break
        ph = planned.get((ti, pos, r))
        if ph:
            out.append((tick, ph[1][0], orig[tick]))
        tick += tempo
    return out


def test_the_two_note_pairing_slips_are_exact_paired_by_time():
    """Chimera v1 (96/135 by name before record 8's regates, 135/135 since)
    and Devils_Galop v2 (32/33): by TIME
    every planned note row (ties included) opens on the original's width
    on its fetch tick's frame, except Devils_Galop
    v2's tick-0 note, which the original never sounds (no register write
    on frame 0; its first write, $A80 on frame 1, is the sweep's first
    step from the $A40 the plan holds)."""
    chim = _time_paired("Chimera.sid", 180, 0, 0, 1)
    assert len(chim) == 324 and all(p == o for _, p, o in chim), (
        len(chim), [x for x in chim if x[1] != x[2]][:5])
    dg = _time_paired("Devils_Galop.sid", 180, 0, 0, 2)
    miss = [x for x in dg if x[1] != x[2]]
    assert len(dg) == 40 and miss == [(0, 0xA40, 0x000)], (len(dg), miss)


def test_thing_on_a_springs_frame_1153_fetch_is_the_decoders():
    """Thing_on_a_Spring voice 0: the original holds $8C0 a third frame at
    1153 and rewrites the voice's ADSR on that frame with the gate off -- a
    fetch of a no-note event naming no instrument, byte for byte a hold row.

    RETRACTED for the merged tree (this test's former name and premise,
    test_thing_on_a_springs_first_miss_is_an_unseen_fetch): "the plan agrees
    with the original up to frame 1153 ... a fetch of a no-note event, which
    reaches the walk as a hold row" -- the decoder's event starts
    (`event_rows`, task decoder-event-start-rows) now reach `_triangle_rows`,
    and over the 30 s window every planned note of the voice is exact, past
    1153 too. What it pins now is the CARRIER: in that window the rows the
    event starts call a fetch and the bytes do not are exactly the 1153 one
    and a second at 1177 (row 84 of the same pattern), so it is the
    decoder's channel, not the bytes, that the walk spends those ticks
    on."""
    import fidelity as F
    from h2g import patterns as P
    corpus, doc = _corpus_and_presets()
    if not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip("siddump not available here")
    pairs = _time_paired("Thing_on_a_Spring.sid", 30, 0, 0, 0)
    miss = [x for x in pairs if x[1] != x[2]]
    assert len(pairs) == 84 and not miss, (len(pairs), miss[:5])
    assert any(t > 1177 for t, _, _ in pairs)
    cap = _walk_args("Thing_on_a_Spring.sid")
    assert cap["event_rows"], "the walk received no event starts"
    track = cap["tracks"][0]
    songlen = next(k for k, b in enumerate(track) if b == GT_ORDER_RESTART)
    by_event = P._triangle_rows(track, songlen, track[songlen + 1],
                                cap["patterns"], cap["event_rows"])
    by_bytes = P._triangle_rows(track, songlen, track[songlen + 1],
                                cap["patterns"])
    tick, tempo = cap["tri_start"][0][0], cap["tempos"][0]
    hidden = []
    for e, b in zip(by_event, by_bytes):
        assert e[:5] == b[:5]
        if e[0] or tick >= 30 * 50:
            break
        if e[5] != b[5]:
            hidden.append((tick, e[2], e[3], e[5]))
        tick += tempo
    assert hidden == [(1153, 72, "row", True), (1177, 84, "row", True)], hidden
    wd = Path(tempfile.mkdtemp(prefix="tri_lockstep_tos_"))
    try:
        local = wd / "o.sid"
        name = "Thing_on_a_Spring.sid"
        shutil.copyfile(corpus / name, local)
        cal, _ = F.table_calibration(corpus / name, F._preset_opts(doc, name))
        trace = F.run_siddump(local, 30, 0, F.SIDDUMP, cal)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    t = F.register_timeline(trace[0].pulse_events, 1160)
    assert [t[f] for f in (1151, 1152, 1153, 1154)] == [0x8C0] * 3 + [0x900]
    assert (1153, 0x1765) in trace[0].adsr_events
    assert 1153 not in trace[0].attack_frames


# --------------------------------------------------------------------------
# The output: what reaches the packed file, and what the extra writes cost
# --------------------------------------------------------------------------

_REACH = {
    # name: {(group, voice): (reached, paired)} -- see `_reach`
    "Chimera.sid": {(0, 0): (132, 132), (0, 1): (135, 135)},
    # (0, 0) was 225/225 before tie_restart's adoption (v0.5.516): one A-4
    # row (finished note 565, attack frame 5713) now carries no
    # CMD_SETPULSEPTR, yet its packed width $C10 is the planned $C00 plus
    # one table step by this count's own rule -- reached in sound, not in
    # the command the count requires.
    "Thing_on_a_Spring.sid": {(0, 0): (224, 225), (0, 1): (25, 25),
                              (0, 2): (871, 871)},
    # The cost: subtune 0 voice 1 is new, subtunes 2-4 lose what the
    # walk before shipped (120/120, 138/138 and 80/386 reached there).
    "Human_Race.sid": {(0, 0): (455, 457), (0, 1): (120, 120),
                       (1, 1): (216, 216), (2, 1): (108, 120),
                       (3, 0): (0, 138), (4, 0): (0, 386), (4, 1): (0, 264)},
}


def _reach(name: str, seconds: int = 180) -> dict:
    """{(group, voice): (reached, paired)} for the first walk's planned
    first-pass notes in the FINISHED song (presets, `pulse_phase` forced).
    Walk notes are paired with the finished song's note rows, and those
    with our packed trace's attacks (group g traced as our subtune g), by
    note name (difflib, runs of 8 or more). A note REACHES when its
    finished row carries the CMD_SETPULSEPTR naming its phase entry and
    the packed width at the attack is the planned (w, d) plus k table
    steps along d, k in 0..multiplier -- `test_game_killers_planned_
    phases_reach_the_packed_output`'s rule -- on the top 8 bits (the
    packed player writes a low nibble the original never does: $808 for
    a set $800)."""
    import difflib
    import fidelity as F
    from h2g import convert as C
    from h2g import patterns as P
    from songview import parse_sng
    corpus, doc = _corpus_and_presets()
    if (not Path(F.SIDDUMP).exists() or not Path(F.GT2RELOC).exists()
            or not (corpus / name).exists()):
        import pytest
        pytest.skip("siddump, gt2reloc or the file not available here")
    kwargs = F._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    mult = doc["songs"][name].get("multiplier", 1)
    cap: dict = {}
    real_walk, real_table = C.collect_pulse_phases, C.build_pulse_phase_table

    def walk(pats, tracks, *a, **kw):
        r = real_walk(pats, tracks, *a, **kw)
        if "plan" not in cap:
            cap.update(pats=[list(p) for p in pats],
                       tracks=[list(t) for t in tracks], plan=r)
        return r

    def table(*a, **kw):
        r = real_table(*a, **kw)
        cap.setdefault("table", r)
        return r
    C.collect_pulse_phases, C.build_pulse_phase_table = walk, table
    try:
        sng = C.convert(str(corpus / name), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases, C.build_pulse_phase_table = real_walk, real_table
    assert cap.get("plan") and cap.get("table"), f"{name}: no plan shipped"
    entries, _, index = cap["table"]
    song = parse_sng(sng)
    planned = {(ti, pos, r): ph for ti, pos, rows in cap["plan"][1]
               for r, ph in rows.items()}
    names = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-",
             "A#", "B-"]

    def nm(note: int) -> str:
        n = note - P.GT_FIRSTNOTE
        return f"{names[n % 12]}{n // 12}"

    def walk_notes(ti: int) -> list:
        out, live = [], 0
        for pos, b in enumerate(cap["tracks"][ti]):
            if b == GT_ORDER_RESTART:
                break
            if b >= P.MAX_PATTERNS or b >= len(cap["pats"]):
                continue
            pat = cap["pats"][b]
            for r, kind, instr in P._phase_note_rows(pat, live, {}):
                if instr:
                    live = instr
                if kind == "note" and pat[4 * r + 2] != P.CMD_TONEPORTA:
                    out.append((nm(pat[4 * r]), planned.get((ti, pos, r))))
        return out

    def final_notes(ti: int) -> list:
        track, out, i = song.tracks[ti], [], 0
        while i < len(track) and track[i] != GT_ORDER_RESTART:
            b, plays = track[i], 1
            if GT_REPEAT <= b < GT_REPEAT + 16 and i + 1 < len(track):
                plays, b = b - GT_REPEAT + 1, track[i + 1]
                i += 1
            i += 1
            if b >= P.MAX_PATTERNS or b >= len(song.patterns):
                continue
            pat = song.patterns[b]
            for _ in range(plays):
                for r in range(len(pat) // 4):
                    note = pat[4 * r]
                    if note == P.GT_END_PATTERN:
                        break
                    if (P.GT_FIRSTNOTE <= note <= P.GT_LASTNOTE
                            and pat[4 * r + 2] != P.CMD_TONEPORTA):
                        out.append((nm(note), pat[4 * r + 3]
                                    if pat[4 * r + 2] == P.CMD_SETPULSEPTR
                                    else None))
        return out

    def pair(a: list, b: list) -> dict:
        sm = difflib.SequenceMatcher(None, [x[0] for x in a],
                                     [x[0] for x in b], autojunk=False)
        return {m.a + k: m.b + k for m in sm.get_matching_blocks()
                if m.size >= 8 for k in range(m.size)}

    groups = len(song.tracks) // 3
    wd = Path(tempfile.mkdtemp(prefix="tri_lockstep_reach_"))
    try:
        packed = F.pack_sid(sng, wd, multiplier=mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        traces = [F.run_siddump(packed, seconds, g, F.SIDDUMP, calls=mult)
                  for g in range(groups)]
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    nf = seconds * 50
    out = {}
    for g in range(groups):
        for v in range(3):
            wn = walk_notes(3 * g + v)
            if not any(ph for _, ph in wn):
                continue
            fn = final_notes(3 * g + v)
            tr = traces[g][v]
            t = F.register_timeline(tr.pulse_events, nf)
            att = [(tr.attacks[k], t[f])
                   for k, f in enumerate(tr.attack_frames) if f < nf]
            w2f, f2a = pair(wn, fn), pair(fn, att)
            ok = n = 0
            for i, (_, ph) in enumerate(wn):
                if not ph or w2f.get(i) not in f2a:
                    continue
                n += 1
                instr, (w, d) = ph
                at = index.get((instr, w, d))
                if at is None or fn[w2f[i]][1] != at:
                    continue
                spd = entries[at][1] if entries[at][0] < 0x80 else 0
                spd = spd if spd < 0x80 else 0x100 - spd
                got = att[f2a[w2f[i]]][1] >> 4
                ok += any(((w + j * spd * d) & 0xFFF) >> 4 == got
                          for j in range(mult + 1))
            out[(g, v)] = (ok, n)
    return out


def test_what_reaches_the_packed_output():
    """Where the lockstep's plan reaches the finished, packed file, and what
    its extra writes cost (the `_REACH` table). Chimera and
    Thing_on_a_Spring ship every paired planned phase. On Human_Race
    subtune 0 voice 1 -- the voice that used to be declined -- ships all
    120, and subtunes 2, 3 and 4 pay for it: the walk before this change
    reached 120/120, 138/138 and 80/386 there, and the pattern table and
    the pulse table are spent in subtune order. A capacity fix moves the
    Human_Race rows; a walk change moves the others."""
    bad = {}
    for name, want in _REACH.items():
        got = _reach(name)
        if got != want:
            bad[name] = (got, want)
    assert not bad, bad
