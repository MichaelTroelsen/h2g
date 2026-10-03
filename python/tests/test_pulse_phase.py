"""`pulse_phase`'s `multiplier == 1` gate: why it was kept, what lifted it.

**The gate is LIFTED.** `goatwriter.budget_pulse_phase_commands` runs in
`build_sng` on the finished rows of every pattern, and `test_pattern_budget.py`
holds the budget's own tests and Rasputin's pack. The rest of this docstring
is the measurement that kept the gate until the cause was found, kept as the
record of why a budget and not a wider condition is the repair.

The gate's own comment in `convert.py` justified itself on an UNTESTED worry --
"whether this engine's own sweep steps per call or per frame on a multispeed
player has not been measured, and a wrong reading there would be silent". That
worry may still be true, but it is no longer the reason to keep the gate. The
reason, measured at 0aa0d5c, is much more specific and much harder:

* The gate's real reach is **3 files, not 11.** Of the eleven multispeed files
  that carry this engine, lifting the gate makes only Game_Killer (-S9),
  One_Man_and_his_Droid (-S2) and Rasputin (-S2) emit anything; the other
  eight are declined by a LATER stage anyway and their bytes do not move.
* **Rasputin's conversion then does not PACK.** With the gate lifted and
  `pulse_phase` forced on it, the plan writes `CMD_SETPULSEPTR` on 785 note
  rows across **59 pattern copies**, taking the file to 126 patterns -- and
  `gt2reloc` refuses the result, so the row goes `measured` -> `not packed`.
  That is a hard regression, not a fidelity trade.
* **Game_Killer is the one that would gain, and it gains cleanly**: `pspan`
  0.89 -> 0.91 and `pphase` 0.64 -> 0.91, with every other column unmoved.
* One_Man_and_his_Droid moves bytes and no number, in the traced subtune.

So the gate is doing real work, but it is far broader than the harm it
prevents. Lifting it wants a guard on the pack -- see the task opened for it --
not a wider condition here.

**WHY THE PACK REFUSES -- FOUND at 24b9f1d, after five candidates were
excluded at fd286a5.** `greloc.c`'s `packpattern()` packs each pattern for the
player and returns -1 past **256 bytes**; `gt2reloc` then prints "PATTERN xx
IS TOO COMPLEX (OVER 256 BYTES PACKED)!" to the console that does not exist
headless, writes no file and exits 0. A command/data pair costs two packed
bytes wherever it CHANGES from the previous row, and `CMD_SETPULSEPTR` on
785 note rows changes on almost every one: four of the lifted arm's 127-row
patterns (86, 88, 93, 96) pack to 264-270 bytes, 105 command changes and 53
instrument bytes on top of 127 notes, where the shipped arm's largest is 118.
`test_table_validation.packed_pattern_size` is the replica; its corpus test is
the guard the pack was missing.

Confirmed by intervention rather than by arithmetic alone: with the command
stripped from ONLY those four patterns the lifted file packs (largest 217);
with it stripped from every OTHER pattern and kept on the four, it is still
refused. The three candidates fd286a5 left open -- a renumbered pulse-table
operand, a limit on distinct pattern lengths, the two-byte `$FE nn` orderlist
tempo -- are closed by that: none of them changes when four patterns'
commands do.

The exclusions that stand (fd286a5, lifted arm 29009 bytes against 16558):

    pattern count        126   against MAX_PATTERNS 208        clear
    exectable walk       NO ERRORS -- test_table_validation's
                         own `table_errors()` on the lifted
                         .sng, the replica of gtable.c:1008    clear
    table rows           WTBL 130, PTBL 145, FTBL 2, STBL 4
                         against 255 each                      clear
    orderlist length     229 (longest of six) vs
                         MAX_TRACK_LEN 255                     clear
    total size           29009 bytes, where W_A_R packs at
                         58481 and Gremlins at 52269           clear

So lifting the gate wanted the pulse-phase writer to BUDGET: a pattern's
packed size is knowable from the same rows it writes, and a `CMD_SETPULSEPTR`
that would take a pattern past 256 has to be dropped (the instrument's own
pointer then plays the first phase, which is what every note got before the
option) or the pattern split. It does, now, and it does it LAST -- after
`_vibrato_command_pass` -- because a budget taken where the phase commands
are written drops nothing: those four patterns pack to 217 there and only
cross 256 once the vibrato pass has put its commands on 53-68 more rows.
Rasputin at -S2 packs with 44 commands dropped from those four patterns.
"""
import json
import sys
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent


def test_the_gate_is_lifted_and_the_budget_stands_in_its_place():
    """Pinned as SOURCE rather than behaviour on purpose, as the gate was.

    Every file the gate declined converted identically with `pulse_phase` on
    and off, so a behavioural assertion could not tell the gate from the
    option merely not reaching those files; reading the condition was the
    only check that failed when someone lifted it. The same reasoning now
    runs the other way: the gate must stay OUT, and what replaced it must be
    the budget, called on the finished patterns in `build_sng` after every
    other pass that writes a command column. `test_pattern_budget.py` tests
    the budget's behaviour; this pins the two seams.
    """
    src = (PYTHON_ROOT / "h2g" / "convert.py").read_text(encoding="utf-8")
    assert "and multiplier == 1 and group_tempos):" not in src, (
        "the pulse_phase multiplier gate is back -- Rasputin packs without "
        "it only because goatwriter budgets the packed size; see this "
        "module's docstring and test_pattern_budget.py")
    assert ("if (pulse_phase and pulse and group_tempos\n"
            "            and (det.pulse_tri_hi >= 0 or det.pulse_bounds >= 0)):") in src, (
        "the pulse_phase gate is neither the triangle engine's nor the "
        "bounds engine's; see test_the_bounds_engine_has_a_sim_and_a_walk")
    gw = (PYTHON_ROOT / "h2g" / "goatwriter.py").read_text(encoding="utf-8")
    call = "patterns = budget_pulse_phase_commands(patterns, CMD_SETPULSEPTR, log)"
    assert gw.count(call) == 1, "the budget is not called from build_sng"
    # Last of the command-column writers: the vibrato pass is what takes
    # Rasputin's four patterns across the line, so the budget must follow it.
    vib = gw.index("vib_ptrs = _vibrato_command_pass(det, patterns, vib_ptrs, lead, log,\n"
                   "                                         tracks=tracks)")
    arps = gw.index("patterns = _resolve_arp_pointers(patterns, arp_starts, log)")
    assert vib < arps < gw.index(call)
    assert gw.index(call) < gw.index("_write_instruments(out, sid, det, instr_used, pulse_starts,")


def _corpus_and_presets():
    presets = REPO_ROOT / "presets.json"
    corpus = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
    if not presets.exists() or not corpus.exists():
        import pytest
        pytest.skip("corpus or presets.json not available here")
    sys.path.insert(0, str(PYTHON_ROOT))
    return corpus, json.loads(presets.read_text(encoding="utf-8"))


def _walk_calls_per_frame(name: str, force: int | None = None):
    """Convert `name` with `pulse_phase` forced, capturing what convert.py
    hands `collect_pulse_phases` as (tempos, `calls_per_frame`) -- or
    overriding the latter with `force` -- and the plan it returned."""
    import fidelity
    from h2g import convert as C
    corpus, doc = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        import pytest
        pytest.skip(f"{name} not in the corpus here")
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    seen: list = []
    plans: list = []
    real = C.collect_pulse_phases

    def spy(*a, **kw):
        seen.append((list(a[2]), kw.get("calls_per_frame")))
        if force is not None:
            kw["calls_per_frame"] = force
        r = real(*a, **kw)
        plans.append(r)
        return r
    C.collect_pulse_phases = spy
    try:
        C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases = real
    assert seen, f"the walk was never entered on {name}"
    return seen, plans, doc["songs"][name].get("multiplier", 1)


def test_the_triangle_walk_runs_on_the_originals_ticks_the_bounds_walk_on_frames():
    """The two engines' clocks, each read off its player. The bounds engine
    sweeps once a FRAME: the walk gets our calls a row (the GT tempo) and
    the multiplier to divide them by ($756 planned where Saboteur_II held
    $2B0 before it did). The triangle engine sweeps once a TICK -- a play
    call that passes the player's outer gate -- so the walk gets the
    original's ticks a row (`SongSpeeds.frames_for`) and divides by 1:
    One_Man_and_his_Droid (`-S2`, GT tempo 4) walks 2 ticks a row,
    Game_Killer (`-S9`, GT tempo 20, a frame skipped in ten) 2, Rasputin
    (`-S2`, GT tempos 6 and 5, an outer gate its `$FE nn` moves) 2 and 2.

    RETRACTED, the state this replaces (v0.5.488 to here): the triangle
    walk got the GT tempo with `calls_per_frame` 1 -- the CALL clock --
    pinned as "The triangle sweep's counter runs inside the multispeed
    core, `multiplier` ticks a frame", and "Rasputin and
    One_Man_and_his_Droid read at chance on BOTH". Neither holds: the
    counter sits behind the outer gate (read at 1dde44a, see
    goatwriter.PulsePhaseSim), and on the tick clock with the voice cells
    the three carriers open on the original's width at the attack (pinned
    by `test_the_plan_opens_on_the_originals_width_paired_by_note`)."""
    seen_t, _, mult_t = _walk_calls_per_frame("One_Man_and_his_Droid.sid")
    seen_g, _, mult_g = _walk_calls_per_frame("Game_Killer.sid")
    seen_r, _, mult_r = _walk_calls_per_frame("Rasputin.sid")
    seen_b, _, mult_b = _walk_calls_per_frame("Saboteur_II.sid")
    assert (mult_t, mult_g, mult_r, mult_b) == (2, 9, 2, 3)
    assert seen_t == [([2], 1)], ("triangle engine off the tick clock", seen_t)
    assert seen_g == [([2], 1)], seen_g
    assert seen_r == [([2, 2], 1)], seen_r
    assert seen_b[0][1] == mult_b, ("bounds engine off the frame clock", seen_b)
    src = (PYTHON_ROOT / "h2g" / "convert.py").read_text(encoding="utf-8")
    assert "walk_tempos, calls_per_frame, start = group_tempos, multiplier, None" in src
    assert "walk_tempos, calls_per_frame = frames, 1" in src, (
        "the triangle walk is no longer handed the original's ticks a row; "
        "read this test's docstring before changing either clock")


# --------------------------------------------------------------------------
# Game_Killer: where the planned phase goes between the walk and the packed
# `-S9` trace. Measured at 04fdcb5 + this session's uncommitted tree, under
# `pulse_phase` forced on the shipped preset, `-t 90`, voice 0, the first
# 200 planned notes (attack indices 270-469).
#
# * **NOTHING IS LOST DOWNSTREAM OF THE WALK.** Paired by note -- the walk's
#   own attack index, not a filtered list position -- every one of the 200
#   planned notes opens in the packed trace on its planned width plus
#   0..`multiplier` table ticks along its planned direction (200/200). The
#   set row, the budget (it drops nothing here) and the -S9 table step all
#   deliver the plan.
# * **RETRACTED: "THE PLAN ITSELF DOES NOT PREDICT THE ORIGINAL. Paired by
#   note, the plan's bucket agrees with the original's 0.135 at the attack
#   frame".** That was the CALL-clock plan with a direction and counter
#   cloned into each record, starting up. On the original's TICK clock
#   (two a row) with the per-voice cells seeded from the image -- voice
#   0's `$0C78` reads 01, DOWN -- the first 200 planned notes open on the
#   original's own width at the attack, 200/200; the call clock with the
#   same cells gets 131. The packed trace's 0.11 was the old plan,
#   delivered.
# * **RETRACTED: "the walk's planned onset buckets agree with the original's
#   63% / 61% over the first 100 / 200 sweeping notes on the CALL clock".**
#   That figure paired the plan's i-th note with the i-th original attack
#   whose width one frame on is $800 or more -- and that list opens with an
#   attack at frame 641 (a static $84D instrument, record 2) the plan has
#   no entry for, so every pair compared planned note i+1 with original
#   note i. The 0.615 is real but it is THAT comparison: the sim's phase at
#   the start of the NEXT note matches the original's width one frame after
#   THIS note's attack. A lead for the sim's model, not a clock verdict.
# --------------------------------------------------------------------------

_GK = "Game_Killer.sid"
_GK_SECONDS = 90
_GK_NOTES = 200


def _game_killer_walk(force: int | None = None,
                      tempos: list | None = None) -> dict:
    """Convert Game_Killer with `pulse_phase` forced, capturing the plan,
    the table, the bytes, and the ATTACK INDEX of every planned voice-0
    note: its position among the walk's note rows in play order, ties
    (`CMD_TONEPORTA`, no gate retrigger) excluded -- the same count siddump
    makes of the attacks it prints. `force` overrides `calls_per_frame`
    and `tempos` the steps a row the walk is handed."""
    import fidelity
    from h2g import convert as C
    from h2g import patterns as P
    corpus, doc = _corpus_and_presets()
    path = corpus / _GK
    if not path.exists():
        import pytest
        pytest.skip(f"{_GK} not in the corpus here")
    kwargs = fidelity._preset_opts(doc, _GK)
    kwargs["pulse_phase"] = True
    cap: dict = {}
    real_walk, real_table = C.collect_pulse_phases, C.build_pulse_phase_table

    def walk(pats, tracks, *a, **kw):
        if force is not None:
            kw["calls_per_frame"] = force
        if tempos is not None:
            a = (list(tempos),) + a[1:]
        r = real_walk(pats, tracks, *a, **kw)
        cap.update(patterns=pats, tracks=tracks, plan=r)
        return r

    def table(*a, **kw):
        r = real_table(*a, **kw)
        cap["table"] = r
        return r
    C.collect_pulse_phases, C.build_pulse_phase_table = walk, table
    try:
        cap["sng"] = C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases, C.build_pulse_phase_table = real_walk, real_table
    assert cap.get("plan") and cap.get("table"), "the plan did not ship"
    pats, track = cap["patterns"], cap["tracks"][0]
    planned = {(pos, r): ph for ti, pos, rows in cap["plan"][1] if ti == 0
               for r, ph in rows.items()}
    notes, n, live = [], 0, 0
    for pos, b in enumerate(track):
        if b == P.GT_ORDER_RESTART:
            break
        if b >= P.MAX_PATTERNS or b >= len(pats):
            continue
        for r, kind, instr in P._phase_note_rows(pats[b], live, {}):
            if instr:
                live = instr
            if kind != "note" or pats[b][4 * r + 2] == P.CMD_TONEPORTA:
                continue
            if (pos, r) in planned:
                notes.append((n, planned[(pos, r)]))
            n += 1
    cap["notes"] = notes
    cap["multiplier"] = doc["songs"][_GK].get("multiplier", 1)
    return cap


_GK_TRACES: dict = {}


def _game_killer_traces():
    """(original voice-0 attacks, ours voice-0 attacks, the call-clock walk),
    the attacks as [(frame, width at the attack, width a frame on, note)],
    traced once per session: the original at -m1 on its calibration, ours
    packed and traced at -S9/-m9 the way fidelity.py measures it."""
    if _GK_TRACES:
        return _GK_TRACES["v"]
    import shutil
    import tempfile
    import fidelity as F
    corpus, doc = _corpus_and_presets()
    sid = corpus / _GK
    if (not sid.exists() or not Path(F.SIDDUMP).exists()
            or not Path(F.GT2RELOC).exists()):
        import pytest
        pytest.skip("Game_Killer, siddump or gt2reloc not available here")
    walked = _game_killer_walk()
    nframes = _GK_SECONDS * 50
    wd = Path(tempfile.mkdtemp(prefix="gk_reach_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(sid, local)
        cal, _ = F.table_calibration(sid, F._preset_opts(doc, _GK))
        sub = F.resolve_subtune(sid, "auto")
        orig = F.run_siddump(local, _GK_SECONDS, sub, F.SIDDUMP, cal)
        blob, _ = F.legalise_restarts(walked["sng"])
        packed = F.pack_sid(blob, wd, F.GT2RELOC, walked["multiplier"])
        assert packed is not None, "gt2reloc wrote no .sid"
        ours = F.run_siddump(packed, _GK_SECONDS, sub, F.SIDDUMP,
                             calls=walked["multiplier"])
    finally:
        shutil.rmtree(wd, ignore_errors=True)

    def attacks(trace):
        t = F.register_timeline(trace[0].pulse_events, nframes)
        return [(f, t[f], t[f + 1], trace[0].attacks[k])
                for k, f in enumerate(trace[0].attack_frames) if f + 1 < nframes]
    _GK_TRACES["v"] = (attacks(orig), attacks(ours), walked)
    return _GK_TRACES["v"]


def test_game_killers_planned_phases_reach_the_packed_output():
    """Every planned voice-0 note of the first 200 opens in the packed `-S9`
    trace on its planned width plus 0..`multiplier` ticks of its table
    speed along its planned direction -- the set row's call and the ramp
    calls the player runs before siddump samples the frame. Read with
    player.s in hand: CMD_SETPULSEPTR's `mt_tick0_9` stores the operand in
    `mt_chnpulseptr` (player.s:246-248) as tick-0 FX run AFTER the new-note
    init's own pointer load (player.s:859-861, 903-906); `mt_setpulse` writes the
    row's width and goes to `mt_nextpulsestep` without modulating; the
    following calls run `mt_pulsemod` at the ramp row's speed, 25 a call
    here (`$E0` over 9). So the phase is NOT lost between
    `build_pulse_phase_table`, `budget_pulse_phase_commands` and the table
    step: measured 200 of 200. The pairing is by NOTE (the walk's own
    attack index, checked against the original's note names), not by a
    filtered list position -- see the block comment above for what the
    latter cost."""
    orig, ours, walked = _game_killer_traces()
    entries, _, index = walked["table"]
    mult = walked["multiplier"]
    notes = [(i, ph) for i, ph in walked["notes"] if i < len(ours)][:_GK_NOTES]
    assert len(notes) == _GK_NOTES, len(notes)
    assert all(ours[i][3] == orig[i][3] for i, _ in notes), (
        "our attacks and the original's no longer name the same notes; "
        "the pairing by index is broken")
    missed = []
    for i, (instr, (w, d)) in notes:
        at = index[(instr, w, d)]               # 1-based: the set row
        assert entries[at - 1] == ((0x80 | (w >> 8)) & 0xFF, w & 0xFF), (
            "the phase entry does not set its own width", instr, hex(w), d)
        spd = entries[at][1]                    # the ramp row after it
        spd = spd if spd < 0x80 else 0x100 - spd
        got = ours[i][1]
        k, rem = divmod((got - w) * d, spd)
        if rem or not 0 <= k <= mult:
            missed.append((i, instr, hex(w), d, hex(got)))
    assert not missed, (f"{len(missed)} of {len(notes)} planned phases do not "
                        f"reach the packed trace", missed[:8])


def test_game_killers_plan_opens_on_the_originals_width_on_the_tick_clock():
    """REPLACES `test_game_killers_plan_paired_by_note_reads_at_chance_on_both_clocks`,
    which pinned "NEITHER clock's plan predicts the original's onsets" --
    0.135 at the attack on the call clock, 0.215 on the frame clock,
    under a 0.35 ceiling -- and asked that "a sim fix that lifts a clock
    past the ceiling should turn the ceiling into a floor, with its own
    figures". These are those figures. Paired by note on the first 200
    planned voice-0 notes (attack indices 270-469), the plan the converter
    ships -- the original's tick clock, two ticks a row, with the per-voice
    cells seeded from the image -- opens on the original's EXACT width at
    the attack on 200 of 200. The call clock (the GT tempo, 20 a row) with
    the same cells gets 131 of 200: the cells alone were not the repair.
    (The old ceiling's other arm, the frame clock, divided the GT tempo by
    the multiplier; on ticks it would divide 2 by 9 and is not a clock.)"""
    orig, ours, walked = _game_killer_traces()

    def exact(notes) -> int:
        notes = [(i, ph) for i, ph in notes if i < len(orig)][:_GK_NOTES]
        assert len(notes) == _GK_NOTES, len(notes)
        assert all(ours[i][3] == orig[i][3] for i, _ in notes)
        return sum(orig[i][1] == w for i, (_, (w, _)) in notes)
    assert exact(walked["notes"]) == _GK_NOTES
    calls = exact(_game_killer_walk(tempos=[20])["notes"])
    assert calls < 0.75 * _GK_NOTES, ("the call clock reaches the original "
                                      "too -- the tick clock is no longer "
                                      "what this pins", calls)


# --------------------------------------------------------------------------
# The plan against the ORIGINAL, paired by note, on every carrier the
# corrected model was measured on. Exact width at the attack frame: the
# walk's planned width for each note row in play order against the width
# the original's trace holds on the frame of the same note, the two note
# sequences aligned by name (difflib, runs of 8 or more -- an index
# pairing breaks wherever our conversion and the original differ by a
# note, One_Man's A#3 restrike at attack 856 being one). The walk is the
# FIRST one convert() makes, which is player 0 on a compilation
# (5_Title_Tunes converts players 1-4 after it through PlayerView).
#
# Shipped model (the call clock, a direction and counter per record
# starting up, a 7-call preroll on the first note's instrument, a
# magnitude turn) -> this one, measured on the same windows at this
# change: Game_Killer 245 -> 563 of 563; Rasputin 48 -> 269 of 269;
# One_Man_and_his_Droid at 260 s 199 of 200 (351 -> 735 of 736 at 700 s);
# 5_Title_Tunes 128/128/96 -> 128/128/192 (voice 2 of 192); Gerry_the_Germ
# subtunes 1/3/4/5/6 7/11/4/3/15 -> 288/54/26/40/90; Crazy_Comets subtune
# 0 voice 2 38 -> 41 of 41; Zoids 8 -> 136 of 136; Commando 27 -> 343 of
# 346. Each part of the model has a carrier that needs it: the tick clock
# (Game_Killer, Rasputin, One_Man), the image's cells (Game_Killer voice
# 0), the preroll (5_Title_Tunes voice 2), the KEYOFF fetch (Gerry 3), the
# lead-in (Gerry 4, Crazy_Comets 0), the instrument-row fetch (Zoids), the
# equality turn (Commando).
# --------------------------------------------------------------------------

_EXACT_WIDTHS = [
    # (file, seconds, subtune traced, group walked, {voice: (exact, paired)})
    ("Game_Killer.sid", 180, None, 0, {0: (563, 563)}),
    ("Rasputin.sid", 180, None, 0, {0: (269, 269)}),
    ("One_Man_and_his_Droid.sid", 260, None, 0, {0: (199, 200)}),
    ("5_Title_Tunes.sid", 180, None, 0,
     {0: (128, 128), 1: (128, 128), 2: (192, 192)}),
    ("Gerry_the_Germ.sid", 180, 1, 1, {1: (288, 288)}),
    ("Gerry_the_Germ.sid", 180, 3, 3, {0: (54, 54)}),
    ("Gerry_the_Germ.sid", 180, 4, 4, {0: (26, 26)}),
    ("Gerry_the_Germ.sid", 180, 5, 5, {0: (40, 40)}),
    ("Gerry_the_Germ.sid", 180, 6, 6, {0: (90, 90)}),
    ("Crazy_Comets.sid", 180, 0, 0, {2: (41, 41)}),
    ("Zoids.sid", 180, None, 0, {0: (136, 136)}),
    ("Commando.sid", 180, None, 0, {0: (343, 346)}),
]
_WALKS: dict = {}


def _first_walk(name: str) -> dict:
    """The first walk convert() makes on `name` under its presets with
    `pulse_phase` forced: patterns, tracks as walked, and the plan."""
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

    def walk(pats, tracks, *a, **kw):
        r = real(pats, tracks, *a, **kw)
        if "plan" not in cap:
            cap.update(patterns=pats, tracks=[list(t) for t in tracks], plan=r)
        return r
    C.collect_pulse_phases = walk
    try:
        C.convert(str(corpus / name), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases = real
    assert cap.get("plan"), f"{name}: the walk planned nothing"
    _WALKS[name] = cap
    return cap


_NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-",
               "A#", "B-"]


def _exact_widths(name: str, seconds: int, sub, group: int) -> dict:
    """{voice: (exact, paired)} for one walked group against the original's
    trace of subtune `sub` (`auto` when None) -- see the block above."""
    import difflib
    import shutil
    import tempfile
    import fidelity as F
    from h2g import patterns as P
    corpus, doc = _corpus_and_presets()
    if not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip("siddump not available here")
    cap = _first_walk(name)
    wd = Path(tempfile.mkdtemp(prefix="tri_exact_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(corpus / name, local)
        cal, _ = F.table_calibration(corpus / name, F._preset_opts(doc, name))
        traced = F.resolve_subtune(corpus / name, "auto") if sub is None else sub
        trace = F.run_siddump(local, seconds, traced, F.SIDDUMP, cal)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    nf = seconds * 50
    planned = {(ti, pos, r): ph for ti, pos, rows in cap["plan"][1]
               for r, ph in rows.items()}
    out = {}
    for v in range(3):
        ti = 3 * group + v
        notes, live = [], 0
        for pos, b in enumerate(cap["tracks"][ti]):
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
                notes.append((f"{_NOTE_NAMES[n % 12]}{n // 12}",
                              planned.get((ti, pos, r))))
        if not any(ph for _, ph in notes):
            continue
        t = F.register_timeline(trace[v].pulse_events, nf)
        orig = [(t[f], trace[v].attacks[k])
                for k, f in enumerate(trace[v].attack_frames) if f + 1 < nf]
        sm = difflib.SequenceMatcher(None, [n for n, _ in notes],
                                     [o[1] for o in orig], autojunk=False)
        pairs = [(notes[m.a + k][1], orig[m.b + k][0])
                 for m in sm.get_matching_blocks() if m.size >= 8
                 for k in range(m.size) if notes[m.a + k][1] is not None]
        if pairs:
            out[v] = (sum(w == ph[1][0] for ph, w in pairs), len(pairs))
    return out


def test_the_plan_opens_on_the_originals_width_paired_by_note():
    """The figures in the block above, re-measured: a change to the walk's
    clock, its cells, its preroll, its lead-in, its fetch rows or the sim's
    turn moves at least one of them."""
    bad = {}
    for name, seconds, sub, group, want in _EXACT_WIDTHS:
        got = _exact_widths(name, seconds, sub, group)
        if got != want:
            bad[(name, sub)] = (got, want)
    assert not bad, bad


def test_the_engine_population_and_its_multispeed_share():
    """The numbers the decision rests on, so a corpus change that moves them
    says so instead of leaving the docstring quietly stale.

    Skipped rather than failed where the corpus is not on this machine: a
    figure that cannot be re-measured must not be asserted from memory.
    """
    presets = REPO_ROOT / "presets.json"
    corpus = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
    if not presets.exists() or not corpus.is_dir():
        import pytest
        pytest.skip("corpus or presets.json not available here")
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    doc = json.loads(presets.read_text(encoding="utf-8"))
    engine, multispeed = 0, 0
    for name, entry in doc["songs"].items():
        path = corpus / name
        if not path.exists():
            continue
        try:
            det = detect(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        # The zero-page dialect reseeds at every note and gets no walk
        # (`pulse_phase_sims` returns {} on it), so it is not this
        # population.
        if det.pulse_tri_hi < 0 or det.pulse_tri_per_voice:
            continue
        engine += 1
        if entry.get("multiplier", 1) > 1:
            multispeed += 1
    assert engine == 24, f"the triangle pulse engine reaches {engine} files"
    assert multispeed == 11, (
        f"{multispeed} of them are multispeed; the gate declined exactly "
        "these, and only 3 of them emit anything now it is lifted")



def test_the_bounds_engine_has_a_sim_and_a_walk():
    """The other sweeping engine -- the per-record-bounds array of
    `_pulse_program`, `pulse_bounds >= 0` -- is what `pulse_phase_sims`
    returns {} on. `goatwriter.PulseBoundsSim` is its accumulator, validated
    on both originals' traces (test_pulse.py pins the measured frames), and
    `build_pulse_phase_table` serves its records. The walk is the three
    edits this test used to name as missing, pinned here as seams the way
    the gate itself is: the decoder carries the note byte's bit 7 out beside
    `exits_tied` (`_build_raw_pattern`'s `free_rows` -- the bit that decides
    whether a note reseeds, `$F162 LDA $F59A / BMI` in Saboteur_II);
    `collect_pulse_phases` calls `reseed()` on every other note row; and
    convert.py hands the walk `pulse_bounds_sims` where the triangle builder
    returns nothing -- only on the players carrying the reseed test in the
    spelling the rule was validated on (`pulse_reseed_gated`), since a walk
    that reseeds the other 14 on that bit would be a guess about a player.
    test_pulse.py tests the behaviour; this pins the wiring.
    """
    conv = (PYTHON_ROOT / "h2g" / "convert.py").read_text(encoding="utf-8")
    pats = (PYTHON_ROOT / "h2g" / "patterns.py").read_text(encoding="utf-8")
    gw = (PYTHON_ROOT / "h2g" / "goatwriter.py").read_text(encoding="utf-8")
    assert "class PulseBoundsSim" in gw and "def pulse_bounds_sims" in gw
    assert "sims = pulse_phase_sims(sid, det, lead) or bounds_sims" in conv, (
        "convert.py no longer hands the walk the bounds sims")
    assert "and det.pulse_tri_hi < 0 and pulse_reseed_gated(sid)" in conv, (
        "the bounds sims reach the walk on a player whose reseed test has "
        "not been read; see goatwriter.PULSE_RESEED_GATE")
    assert "free_rows=bool(bounds_sims))" in conv, (
        "convert_patterns is not asked for the bit-7 rows where the walk runs")
    assert ("if sim.RESEEDS and not (r in free and known):\n"
            "                                sim.reseed()") in pats, (
        "the walk no longer reseeds on every note row without the bit")
    assert "if det.pulse_tri_hi < 0:\n        return {}" in gw, (
        "pulse_phase_sims no longer declines the bounds engine: convert.py "
        "takes whichever builder is non-empty, so the triangle model would "
        "run on a reseeding player")


def test_the_bounds_engine_population_and_how_its_players_reseed():
    """42 preset files carry the engine, 23 of them multispeed. All 42 turn
    the sweep the same way (store-at-bound, equality on the high nibble,
    up and down); 28 reseed the accumulator behind Saboteur_II's exact
    `LDA note / BMI` test, 13 behind a differently spelled test (After_8:
    `LDA $1684 / BNE`), and IK_plus writes the register another way. The
    sim's reseed rule was validated on two of the 28, and the walk is
    restricted to the 28 (`pulse_reseed_gated`); a walk that reaches the
    other 14 must read their gate first. The 13 are all digi or ilv
    dialect files, whose decoders carry no bit-7 row out, so even admitted
    they would plan nothing. Re-measured here so the docstring cannot go
    quietly stale."""
    presets = REPO_ROOT / "presets.json"
    corpus = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
    if not presets.exists() or not corpus.is_dir():
        import pytest
        pytest.skip("corpus or presets.json not available here")
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g.detect import detect
    from h2g.goatwriter import PULSE_RESEED_GATE
    from h2g.search import search_file
    from h2g.sidfile import load_sid
    doc = json.loads(presets.read_text(encoding="utf-8"))
    # The shape convert.py gates the walk on (`pulse_reseed_gated`), so the
    # 28 counted here are the 28 the option can reach.
    reseed_bmi = PULSE_RESEED_GATE
    turn = ("48 BD ?? ?? 69 00 29 0F 48 C9 ?? D0 ?? FE",
            "48 BD ?? ?? E9 00 29 0F 48 C9 ?? D0 ?? DE")
    engine = multispeed = bmi = turns = 0
    for name, entry in doc["songs"].items():
        path = corpus / name
        if not path.exists():
            continue
        try:
            sid = load_sid(str(path))
            det = detect(sid, lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.pulse_bounds < 0:
            continue
        engine += 1
        multispeed += entry.get("multiplier", 1) > 1
        bmi += search_file(sid.data, reseed_bmi) > 0
        turns += all(search_file(sid.data, t) > 0 for t in turn)
    assert engine == 42, f"the bounds pulse engine reaches {engine} files"
    assert multispeed == 23, multispeed
    assert turns == engine, "a player turns its sweep some other way"
    assert bmi == 28, f"{bmi} players carry the LDA/BMI reseed gate"


def _forced_pulse_phase_logs(name: str) -> list[str]:
    """Convert `name` from the corpus under its own preset options, with
    `pulse_phase` forced True, and return only the log lines mentioning the
    pulse-phase table. Import is local so the two skip-guarded tests below
    do not require h2g on every collection run."""
    presets = REPO_ROOT / "presets.json"
    corpus = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
    path = corpus / name
    if not presets.exists() or not path.exists():
        import pytest
        pytest.skip("corpus or presets.json not available here")
    sys.path.insert(0, str(PYTHON_ROOT))
    import fidelity
    from h2g.convert import convert
    doc = json.loads(presets.read_text(encoding="utf-8"))
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    logs: list[str] = []
    convert(str(path), log=logs.append, **kwargs)
    return [l for l in logs if "PULSE" in l.upper() and "PHASE" in l.upper()]


def _forced_table_args(name: str) -> tuple:
    """The positional arguments convert.py hands `build_pulse_phase_table`
    on `name` under its own presets with `pulse_phase` forced, and what the
    builder returned."""
    corpus, doc = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        import pytest
        pytest.skip(f"{name} not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    cap: dict = {}
    real = C.build_pulse_phase_table

    def spy(*a, **kw):
        cap["args"] = a
        cap["table"] = real(*a, **kw)
        return cap["table"]
    C.build_pulse_phase_table = spy
    try:
        C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C.build_pulse_phase_table = real
    assert "args" in cap, f"{name} never reached the phase table"
    return cap["args"], cap["table"]


def _play_pulse_table(entries: list, ptr: int, calls: int) -> list:
    """The width the GT pulse table holds after each of `calls` play calls
    from a note that set pointer `ptr` -- gplay.c:856-902 with pulse
    optimization off (`-O0`, what every packing site passes): one jump
    followed at the top of a call, a set row takes the call and advances,
    a modulation row steps once a call for its tick count."""
    pulse = time = 0
    out = []
    for _ in range(calls):
        if ptr:
            if entries[ptr - 1][0] == 0xFF:
                ptr = entries[ptr - 1][1]
            if ptr and not time:
                left, right = entries[ptr - 1]
                if left >= 0x80:
                    pulse = ((left & 0x0F) << 8) | right
                    ptr += 1
                else:
                    time = left
            if ptr and time:
                spd = entries[ptr - 1][1]
                pulse = (pulse + spd - (0x100 if spd >= 0x80 else 0)) & 0xFFF
                time -= 1
                if not time:
                    ptr += 1
        out.append(pulse)
    return out


# The files whose per-phase layout overflows under forced `pulse_phase` at
# this tree, and the records the shared-ramp rescue keeps swept. Master_of_
# Magic and Phantoms are two of the task's four (docs/LESSONS.md, "The
# pulse-phase table overflows on four VBI carriers"); the rest were found
# overflowing by the same corpus byte-hash. Gremlins 10 and 20 and
# Human_Race 20 and 23 still degrade.
#
# **THE OTHER TWO OF THE FOUR, Last_V8 and its C128 version, LEFT this set
# with the triangle walk's tick clock and voice cells**: the plan is now
# the original's (724 of 724 exact attack widths on subtune 0), and it
# opens on more phases -- instrument 8 on 11 where it was 4, 9 on 22 where
# it was 20 -- so that even the shared layout no longer fits. See
# `test_build_pulse_phase_table_degrades_instead_of_refusing_last_v8`.
_OVERFLOWING = {
    "Master_of_Magic.sid": (14,),
    "Phantoms_of_the_Asteroid.sid": (17,),
    "Battle_of_Britain.sid": (11, 15, 16),
    "Crazy_Comets.sid": (17,),
    "Gremlins.sid": (7,),
    "Human_Race.sid": (21,),
}


def test_one_ramp_per_phase_is_what_overflowed_and_a_merge_has_nothing_to_merge():
    """The cost the rescue removes, pinned at the figures docs/LESSONS.md
    records: Last_V8 instrument 7 asks for 130 rows and 9 for 64 under one
    ramp per phase, Master_of_Magic 14 for 112, Phantoms 17 for 70; shared,
    87 / 43 / 76 / 47. Re-measured on the triangle walk's tick clock with
    voice cells: Last_V8 9 now plans 22 phases and asks 70 / 47, and
    Master_of_Magic 14 asks 112 / 75; 7 and Phantoms 17 are unmoved. And the
    cheaper idea the task opened with -- merge
    the phases that land within one speed step of each other -- MEASURED
    inert on all four: their same-direction phases are four speed steps
    apart (the sim moves the width a whole engine step a tick), so no two
    are within one and a merge loses nothing because it merges nothing."""
    from h2g.goatwriter import _phase_block, _phase_sweep_params
    want_rows = {("Last_V8.sid", 7): (130, 87), ("Last_V8.sid", 9): (70, 47),
                 ("Master_of_Magic.sid", 14): (112, 75),
                 ("Phantoms_of_the_Asteroid.sid", 17): (70, 47)}
    for (name, num), (per_phase, shared) in want_rows.items():
        (sid, det, _, _, mult, phases, _, lead), _ = _forced_table_args(name)
        params = _phase_sweep_params(sid, det, num - 1 - lead, mult)
        want_set = set(phases[num]) | {(params[0], +1)}
        got = (len(_phase_block(0, num, want_set, *params)[0]),
               len(_phase_block(0, num, want_set, *params, share=True)[0]))
        assert got == (per_phase, shared), (name, num, got)
        speed = params[1]
        for d in (+1, -1):
            ws = sorted(w for (w, dd) in want_set if dd == d)
            gaps = [b - a for a, b in zip(ws, ws[1:])]
            assert min(gaps) == 4 * speed, (name, num, d, min(gaps), speed)


def test_shared_ramps_play_the_widths_the_per_phase_ramps_played():
    """THE SHARED LAYOUT IS LOSSLESS, measured by playing both tables: for
    every file the rescue reaches, every CMD_SETPULSEPTR target it ships and
    every placed sweeping record's own pointer plays, call for call over
    3200 calls (two full loops of the slowest band here, Last_V8 2's speed
    2), the widths the same phase plays from the per-phase layout built
    with no table limit. Where the rescue degrades nothing (no
    `PULSE TABLE FULL` line), EVERY record's pointer is held to it, so the
    reused static blocks are covered too."""
    import h2g.goatwriter as G
    calls = 3200
    for name, kept in _OVERFLOWING.items():
        (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args(name)
        assert table is not None, name
        entries, starts, index = table
        assert len(entries) <= G.GT_MAX_TABLELEN, (name, len(entries))
        limit = G.GT_MAX_TABLELEN
        G.GT_MAX_TABLELEN = 10 ** 6
        try:
            ref = G._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                           None, lead, False)
        finally:
            G.GT_MAX_TABLELEN = limit
        ref_entries, ref_starts, ref_index = ref[0], ref[1], ref[2]
        assert ref[3] == 0, (name, "the unlimited reference degraded")
        tracked = {k[0] for k in index}
        assert set(kept) <= tracked, (name, sorted(tracked))
        for key, at in index.items():
            assert (_play_pulse_table(entries, at, calls)
                    == _play_pulse_table(ref_entries, ref_index[key], calls)), (name, key)
        logs: list = []
        G.build_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                  logs.append, lead)
        assert any("shared ramps --" in l for l in logs), (name, logs)
        clean = not any("PULSE TABLE FULL" in l for l in logs)
        for k, (a, b) in enumerate(zip(starts, ref_starts)):
            num = k + 1
            if num in tracked or clean:
                assert (_play_pulse_table(entries, a, calls)
                        == _play_pulse_table(ref_entries, b, calls)), (name, num)


def test_build_pulse_phase_table_degrades_instead_of_refusing_last_v8():
    """`build_pulse_phase_table` used to return None outright once one
    instrument's phase set overflowed `GT_MAX_TABLELEN`, and convert.py's
    caller reverted the WHOLE expansion -- Last_V8 shipped with no
    CMD_SETPULSEPTR at all rather than losing only instrument 7 and 9's
    sweeps. Then it degraded instead, and from v0.5.48x the shared-ramp
    rescue placed all four phase-tracked records in 247 rows on the CALL
    clock's plan.

    **ON THE TICK CLOCK WITH VOICE CELLS THE RESCUE NO LONGER FITS.** The
    plan is now the original's -- 724 of 724 exact attack widths on
    subtune 0, against 60 on the call clock -- and it opens instrument 8 on
    11 phases where the call clock planned 4, and 9 on 22 where it planned
    20. One ramp per phase degrades 14 records, 12 of them to pointer 0
    (no width at all), and keeps only instruments 2 and 8; shared, every
    phase-tracked record fits but the static blocks after them do not (16
    degraded, 15 to pointer 0), so the per-phase layout ships. A CAPACITY
    regression on this file under the FORCED flag only -- Last_V8's preset
    does not ship `pulse_phase` -- and the walk is not where it is fixed:
    the table's allocation order is (statics laid after the phase blocks
    starve). Pinned so the next change to either side sees it move."""
    import h2g.goatwriter as G
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args("Last_V8.sid")
    assert {k: len(v) for k, v in phases.items()} == {2: 28, 7: 42, 8: 11, 9: 22}
    per_phase = G._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                         None, lead, False)
    shared = G._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                      None, lead, True)
    assert (per_phase[3], per_phase[4], per_phase[6]) == (14, 12, 2), per_phase[3:]
    assert (shared[3], shared[4], shared[6]) == (16, 15, 4), shared[3:]
    lines = _forced_pulse_phase_logs("Last_V8.sid")
    assert ("*** PULSE TABLE FULL UNDER --pulse-phase -- 14 INSTRUMENT(S) "
            "LOSE THEIR PHASE ENTRIES, 12 SET NO WIDTH AT ALL ***") in lines, lines
    assert not any("shared ramps --" in l for l in lines), lines
    assert table is not None, "the file was refused rather than degraded"
    assert {k[0] for k in table[2]} == {2, 8}
    assert any(l.startswith("Pulse phase.............: CMD_SETPULSEPTR")
               for l in lines), (
        "a partial table must still ship phase commands for the "
        "instruments that kept one -- got:\n" + "\n".join(lines))


def test_gerry_the_germ_has_the_least_headroom_that_has_not_yet_overflowed():
    """Gerry_the_Germ ships `pulse_phase: true` today and, measured at this
    head, converts with the table exactly full enough that NOTHING is
    dropped -- 0 instruments lose their phase entries. This is the file the
    exhaustion instrumentation exists to make visible if a future change
    (more instruments, wider sweeps, `--max-rows`) pushes it over: this test
    is the trip-wire, not a claim that it has tripped."""
    lines = _forced_pulse_phase_logs("Gerry_the_Germ.sid")
    assert not any("PULSE TABLE FULL UNDER --pulse-phase" in l for l in lines), (
        "Gerry_the_Germ now drops a pulse-phase instrument -- re-read the "
        "PTBL headroom figure in docs/LESSONS.md before treating this as a "
        "regression; it may simply mean this file has finally crossed the "
        "line the docstring warned about:\n" + "\n".join(lines))
