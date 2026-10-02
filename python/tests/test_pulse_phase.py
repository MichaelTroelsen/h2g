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
    hands `collect_pulse_phases` as `calls_per_frame` (or overriding it
    with `force`), and the plan it returned."""
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
        seen.append(kw.get("calls_per_frame"))
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


def test_the_triangle_walk_stays_on_our_calls_and_the_bounds_walk_on_frames():
    """`calls_per_frame` is the multiplier for the bounds engine and 1 for
    the triangle engine, and the second half is MEASURED, not the leftover
    it looked like. When the bounds walk landed (v0.5.488) the 1 was kept
    so the moved set stayed confined to the bounds files, and a task then
    read it as Saboteur_II's defect repeated on the triangle carriers.
    Passing the multiplier for both was tried and measured -- RETRACTED:
    "on Game_Killer (`-S9`) the walk's planned onset buckets agree with the
    original's index-paired 61% over the first 200 sweeping notes on the
    call clock and 21% on the frame clock". The pairing slipped one note;
    paired by note both clocks read at chance (0.135 / 0.215), see
    `test_game_killers_plan_paired_by_note_reads_at_chance_on_both_clocks`.
    The 1 below is therefore pinned as the CURRENT source, not as a
    measured clock. Rasputin and
    One_Man_and_his_Droid read at chance on BOTH. The triangle sweep's
    counter runs inside the multispeed core, `multiplier` ticks a frame;
    the bounds engine's runs once a frame ($756 planned where Saboteur_II
    held $2B0 before it did). Pinned as source at the seam and by capture
    on a carrier of each engine: One_Man_and_his_Droid (`-S2`) gets 1 and
    Saboteur_II (`-S3`) gets 3 -- never the multiplier for both, never 1
    for both, never its square."""
    seen_t, _, mult_t = _walk_calls_per_frame("One_Man_and_his_Droid.sid")
    seen_b, _, mult_b = _walk_calls_per_frame("Saboteur_II.sid")
    assert mult_t == 2 and mult_b == 3, (mult_t, mult_b)
    assert seen_t == [1], ("triangle engine walked on the frame clock", seen_t)
    assert seen_b == [mult_b], ("bounds engine off the frame clock", seen_b)
    src = (PYTHON_ROOT / "h2g" / "convert.py").read_text(encoding="utf-8")
    assert "calls_per_frame=multiplier if bounds_sims else 1)" in src, (
        "the two engines' clocks are no longer the measured pair; read "
        "this test's docstring before changing either")


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
# * **THE PLAN ITSELF DOES NOT PREDICT THE ORIGINAL.** Paired by note, the
#   plan's bucket agrees with the original's 0.135 at the attack frame and
#   0.000 one frame later on the call clock, 0.215 / 0.145 on the frame
#   clock (chance ~0.14 on the seven-bucket band). The packed trace's 0.11
#   is that plan, delivered.
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


def _game_killer_walk(force: int | None = None) -> dict:
    """Convert Game_Killer with `pulse_phase` forced, capturing the plan,
    the table, the bytes, and the ATTACK INDEX of every planned voice-0
    note: its position among the walk's note rows in play order, ties
    (`CMD_TONEPORTA`, no gate retrigger) excluded -- the same count siddump
    makes of the attacks it prints."""
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


def test_game_killers_plan_paired_by_note_reads_at_chance_on_both_clocks():
    """REPLACES `test_game_killers_onsets_put_the_triangle_sweep_on_the_call_clock`,
    whose 0.615 (call clock) against 0.21 (frame clock) was an index slip:
    it paired the plan's i-th entry with the i-th original attack whose
    width a frame on is $800 or more, a list that opens with the static
    $84D note at frame 641 the plan never planned. Paired by note, on
    the first 200 planned notes, the measured figures are:

        clock    at the attack   one frame on
        calls        0.135          0.000
        frames       0.215          0.145         (chance ~0.14)

    so NEITHER clock's plan predicts the original's onsets, and
    `calls_per_frame=1` for the triangle engine is no longer a measured
    choice. Bound: 0.35 everywhere, the old test's own ceiling for "the
    wrong clock". The slip itself is pinned last -- planned note i+1
    against the original's note i one frame on reproduces >= 0.5 --
    because that is the lead the retraction leaves: the sim's phase at the
    NEXT note is what the original holds a frame after THIS one. A sim fix
    that lifts a clock past the ceiling should turn the ceiling into a
    floor, with its own figures."""
    import fidelity as F
    orig, _, walked = _game_killer_traces()
    bucket = F.PULSE_PHASE_BUCKET

    def agreement(notes, col: int, shift: int = 0) -> float:
        pairs = [(orig[i - shift][col] // bucket, w // bucket)
                 for i, (_, (w, _)) in notes if 0 <= i - shift < len(orig)]
        pairs = pairs[:_GK_NOTES]
        assert len(pairs) == _GK_NOTES, len(pairs)
        return sum(a == b for a, b in pairs) / len(pairs)

    frames_walk = _game_killer_walk(force=walked["multiplier"])
    got = {}
    for clock, w in (("calls", walked), ("frames", frames_walk)):
        for col, at in ((1, "attack"), (2, "frame on")):
            got[(clock, at)] = agreement(w["notes"], col)
    assert all(v <= 0.35 for v in got.values()), got
    slip = agreement(walked["notes"], 2, shift=1)
    assert slip >= 0.5, ("the next-note slip no longer reproduces the "
                         "retracted 0.615", slip, got)


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
# this tree, and the records the shared-ramp rescue keeps swept. The first
# four are the task's (docs/LESSONS.md, "The pulse-phase table overflows on
# four VBI carriers"); the next four were found overflowing by the same
# corpus byte-hash. Gremlins 10 (speed 18, off the $600 band's lattice) and
# Gremlins 20, Human_Race 20 / 21 still degrade.
_OVERFLOWING = {
    "Last_V8.sid": (7, 9),
    "Last_V8_C128_version.sid": (7, 9),
    "Master_of_Magic.sid": (14,),
    "Phantoms_of_the_Asteroid.sid": (17,),
    "Battle_of_Britain.sid": (11, 15, 16),
    "Crazy_Comets.sid": (17,),
    "Gremlins.sid": (7,),
    "Human_Race.sid": (23,),
}


def test_one_ramp_per_phase_is_what_overflowed_and_a_merge_has_nothing_to_merge():
    """The cost the rescue removes, pinned at the figures docs/LESSONS.md
    records: Last_V8 instrument 7 asks for 130 rows and 9 for 64 under one
    ramp per phase, Master_of_Magic 14 for 112, Phantoms 17 for 70; shared,
    87 / 43 / 76 / 47. And the cheaper idea the task opened with -- merge
    the phases that land within one speed step of each other -- MEASURED
    inert on all four: their same-direction phases are four speed steps
    apart (the sim moves the width a whole engine step a tick), so no two
    are within one and a merge loses nothing because it merges nothing."""
    from h2g.goatwriter import _phase_block, _phase_sweep_params
    want_rows = {("Last_V8.sid", 7): (130, 87), ("Last_V8.sid", 9): (64, 43),
                 ("Master_of_Magic.sid", 14): (112, 76),
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
    sweeps. Then it degraded instead: with one ramp per phase, 5 instruments
    lose their phase entries and, of those, 3 reach pointer 0 -- still the
    per-phase pass's count, pinned below on `_lay_pulse_phase_table` itself.
    These figures are on the triangle walk's CALL clock; on a frame clock
    (`calls_per_frame=multiplier`, measured and rejected -- see
    `test_the_triangle_walk_stays_on_our_calls_and_the_bounds_walk_on_frames`)
    this `-S2` file's instrument 8 opens on 14 phases instead of 4 and the
    overflow cascades to 18 losing and 16 with no width at all.

    **What ships now is the shared-ramp rescue** (`_phase_block(share=True)`
    plus the reuse of identical static blocks): 247 rows place all four
    phase-tracked records and degrade none, so instruments 7 and 9 sweep.
    """
    import h2g.goatwriter as G
    (sid, det, iu, pulse, mult, phases, _, lead), table = _forced_table_args("Last_V8.sid")
    per_phase = G._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                         None, lead, False)
    assert (per_phase[3], per_phase[4], per_phase[6]) == (5, 3, 2), per_phase[3:]
    lines = _forced_pulse_phase_logs("Last_V8.sid")
    assert not any("PULSE TABLE FULL UNDER --pulse-phase --" in l for l in lines), lines
    assert not any("FALLING BACK TO A STATIC WIDTH" in l for l in lines), lines
    shared = [l for l in lines if "shared ramps --" in l]
    assert shared == ["Pulse phase.............: shared ramps -- 247 table "
                      "row(s) place 4 of 4 phase-tracked record(s), where one "
                      "ramp per phase placed 2 and degraded 5 record(s), 3 to "
                      "pointer 0"], lines
    assert {7, 9} <= {k[0] for k in table[2]}
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
