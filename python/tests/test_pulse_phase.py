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
    vib = gw.index("vib_ptrs = _vibrato_command_pass(det, patterns, vib_ptrs, lead, log)")
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
    with `force`) and as `ticks_per_row`, and the plan it returned.
    Returns (calls_per_frame seen, plans, multiplier, ticks_per_row seen)."""
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
    ticks: list = []
    plans: list = []
    real = C.collect_pulse_phases

    def spy(*a, **kw):
        seen.append(kw.get("calls_per_frame"))
        ticks.append(kw.get("ticks_per_row"))
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
    return seen, plans, doc["songs"][name].get("multiplier", 1), ticks


def test_the_triangle_walk_steps_engine_ticks_and_the_bounds_walk_frames():
    """FLIPPED (task triangle-walk-on-engine-ticks). This test used to be
    `test_the_triangle_walk_stays_on_our_calls_and_the_bounds_walk_on_
    frames` and pinned, AS SHIPPED, the triangle walk on OUR CALLS
    (`calls_per_frame=1`, a row = `tempo` sweep ticks) -- a clock its own
    docstring already called wrong: "The triangle sweep's counter runs
    inside the multispeed core" was read off Game_Killer's bucket-paired
    onsets, and the players refute it (goatwriter.PulsePhaseSim). The
    sweep runs once per ENGINE tick in the voice loop, never on the voice's
    fetch tick, and a row is the inner gate's reload + 1 ticks,
    `frames_for(g)`. That is what ships now: convert.py hands the walk
    `ticks_per_row` (per group, `_triangle_ticks_per_row`), and the walk
    steps a triangle sim by it and does not consult `calls_per_frame`.
    One_Man_and_his_Droid (`-S2`, tempo 4) gets [2]. The bounds half is
    unchanged and still measured ($756 planned where Saboteur_II held $2B0
    before it ran once a frame): Saboteur_II (`-S3`) gets
    `calls_per_frame` 3, and its per-voice sims never read `ticks_per_row`
    -- dropping it changes nothing in its plan.
    `test_rasputins_triangle_sweep_ticks_once_per_engine_tick` is the
    measurement the flip rests on."""
    seen_t, _, mult_t, ticks_t = _walk_calls_per_frame("One_Man_and_his_Droid.sid")
    seen_b, plans_b, mult_b, _ = _walk_calls_per_frame("Saboteur_II.sid")
    assert mult_t == 2 and mult_b == 3, (mult_t, mult_b)
    assert ticks_t == [[2]], ("triangle engine off the engine-tick clock", ticks_t)
    assert seen_b == [mult_b], ("bounds engine off the frame clock", seen_b)
    # the bounds walk does not read ticks_per_row: dropping it moves no plan
    from h2g import convert as C
    real = C.collect_pulse_phases

    def no_ticks(*a, **kw):
        kw["ticks_per_row"] = None
        return real(*a, **kw)
    C.collect_pulse_phases = no_ticks
    try:
        _, plans_nb, _, _ = _walk_calls_per_frame("Saboteur_II.sid")
    finally:
        C.collect_pulse_phases = real
    assert plans_b[0] is not None and plans_nb == plans_b, "bounds walk reads ticks_per_row"
    src = (PYTHON_ROOT / "h2g" / "convert.py").read_text(encoding="utf-8")
    assert "calls_per_frame=multiplier if bounds_sims else 1)" in src, (
        "the bounds seam moved; the triangle engine's clock is ticks_per_row, "
        "never the multiplier")
    # read once into `tri_ticks` since task triangle-table-rate-and-first-
    # step-under-an-outer-gate, which also divides the phase table's rate by it
    assert "tri_ticks = _triangle_ticks_per_row(" in src, (
        "convert.py no longer reads the engine-tick clock")
    assert "ticks_per_row=tri_ticks," in src, (
        "convert.py no longer hands the walk the engine-tick clock")


def _trace_original(name: str, seconds: int):
    """siddump's trace of the ORIGINAL at -m1, the harness's own calling
    convention (calibration, auto subtune). Skips where it cannot run."""
    import shutil
    import tempfile
    import fidelity as F
    corpus, doc = _corpus_and_presets()
    sid = corpus / name
    if not sid.exists() or not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip(f"{name} or siddump not available here")
    wd = Path(tempfile.mkdtemp(prefix="tri_clock_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(sid, local)
        cal, _ = F.table_calibration(sid, F._preset_opts(doc, name))
        sub = F.resolve_subtune(sid, "auto")
        voices = F.run_siddump(local, seconds, sub, F.SIDDUMP, cal)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    return voices, seconds * 50


def _walk_capture(name: str, force: int | None = None,
                  keep_start: bool = False, per_record: bool = False) -> dict:
    """What the walk was handed and what it planned: {seen, ticks, plan,
    tempos, sims}. `force` puts a triangle walk back on the CALL clock it
    shipped on before the engine-tick fix -- `calls_per_frame=force` AND
    `ticks_per_row=None`, since the walk prefers the ticks where given --
    and back on each record's own (+1, 0) start with the fitted preroll
    (`voice_seeds=None`, `preroll=None`, task triangle-direction-per-voice-
    from-the-image), so `force=1` is the pre-fix walk exactly."""
    import fidelity
    from h2g import convert as C
    corpus, doc = _corpus_and_presets()
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    got: dict = {"seen": [], "ticks": []}
    real = C.collect_pulse_phases

    def spy(patterns, tracks, tempos, sims, *a, **kw):
        got["seen"].append(kw.get("calls_per_frame"))
        got["ticks"].append(kw.get("ticks_per_row"))
        got["seeds"] = kw.get("voice_seeds")
        got["preroll"] = kw.get("preroll")
        if force is not None:
            kw["calls_per_frame"] = force
            kw["ticks_per_row"] = None
            if not keep_start:
                kw["voice_seeds"] = kw["preroll"] = None
        if per_record:
            # the shipped clock, each record's own (+1, 0), the fitted preroll
            kw["voice_seeds"] = kw["preroll"] = None
        got["tempos"] = list(tempos)
        got["sims"] = {n: s.clone() for n, s in sims.items()}
        got["plan"] = real(patterns, tracks, tempos, sims, *a, **kw)
        return got["plan"]
    C.collect_pulse_phases = spy
    try:
        C.convert(str(corpus / name), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases = real
    assert got["seen"] and got["plan"] is not None, f"no plan on {name}"
    return got


def _tri_orbit(width: int, step: int, lo: int, hi: int) -> set:
    """Every width the player's sweep can store starting from `width`, in
    either direction -- its own arithmetic, a second reader beside
    PulsePhaseSim so a mutated sim cannot move this filter with it: `ADC
    step / ADC #$00 / AND #$0F` then `CMP #hi` (Rasputin $C28F-$C29F), the
    SBC leg down to `CMP #lo`, 12 bits, turning on EQUALITY."""
    out: set = set()
    for down in (False, True):
        w = width
        for _ in range(64):
            out.add(w)
            if not down:
                w = (w + step) & 0xFFF
                down = (w >> 8) == hi
            else:
                w = (w - step) & 0xFFF
                down = (w >> 8) != lo
    return out


def _first_pass_widths(plan, track: int) -> list[int]:
    """The walk's planned opening widths on `track`, in play order."""
    out: list[int] = []
    for ti, pos, rows in sorted(plan[1], key=lambda x: (x[0], x[1])):
        if ti == track:
            out += [rows[r][1][0] & 0xFFF for r in sorted(rows)]
    return out


def _fetch_widths(voice, nframes: int, orbit: set) -> list[int]:
    """The original's width AT each attack frame -- the value the note fetch
    writes from the record, before any sweep tick (`pphase` reads f+1, which
    is a tick later or not depending on the outer gate) -- kept where it is
    on a sweeping record's orbit."""
    import fidelity as F
    t = F.register_timeline(voice.pulse_events, nframes)
    return [t[f] for f in voice.attack_frames if f < nframes and t[f] in orbit]


def test_rasputins_triangle_sweep_ticks_once_per_engine_tick():
    """THE CLOCK, measured against the trace. Rasputin's sweep ($C270-$C2D4)
    runs in the voice loop once per ENGINE tick and never on the voice's
    fetch tick; a row is the inner gate's reload + 1 = 2 ticks
    (`frames_for(0)`); the outer gate at the play entry ($C012 `DEC $C53A /
    BPL / LDA $C539 / STA $C53A / JMP $C3C5`, reloaded by the `$FE` track
    command, `$FE 02` at the start of subtune 0) skips whole ticks, which is
    why a row is 3 frames = 6 of our calls at -S2 and why neither our calls
    nor the original's frames is the sweep's clock.

    FLIPPED with task triangle-walk-on-engine-ticks: the walk now SHIPS
    on this clock (`ticks_per_row` [2, 2] from convert.py's
    `_triangle_ticks_per_row`), so the SHIPPED plan is the one asserted
    exact -- every one of the 269 sweeping notes voice 0 fetches in 180 s,
    at exactly the width the original's fetch writes. The clock it
    replaced, our calls (`calls_per_frame=1`, 6 ticks a row), planned 48
    of them (924e4bd, re-taken at 26111a5; bound at a quarter) and is now
    reached only by forcing it. The forced call clock at 6 // 2 = 3 calls
    a tick is the same walk by a different road, kept as a second reader
    (forcing also drops the image's voice state, which on Rasputin is the
    (+1, 0) a fresh sim starts on anyway). The direction is not what costs
    anything here -- voice 0 plays one sweeping record in the window -- so
    this file isolates the clock.
    "Rasputin dwells on buckets 12 and 9" describes the opening stretch of
    the original's sequence, not a mechanism: the note rhythm samples a
    22-tick orbit ($880-$E00 in $80 steps) at 2 ticks a row, 1 on a fetch
    row, and over the window the 269 fetch widths spread 10/54/34/58/47/56/10
    across buckets 8-14 -- every one of which the tick-clock plan hits."""
    from h2g.detect import detect
    from h2g.goatwriter import find_song_speeds
    from h2g.sidfile import load_sid
    name = "Rasputin.sid"
    voices, nframes = _trace_original(name, 180)
    corpus, _ = _corpus_and_presets()
    sid = load_sid(str(corpus / name))
    ticks = find_song_speeds(sid, detect(sid, lambda *a, **k: None)).frames_for(0)
    shipped = _walk_capture(name)
    tempo = shipped["tempos"][0]
    assert (ticks, tempo, shipped["ticks"]) == (2, 6, [[2, 2]]), (
        ticks, tempo, shipped["ticks"])
    assert tempo % ticks == 0
    orbit: set = set()
    for s in shipped["sims"].values():
        orbit |= _tri_orbit(s.width, s.step, s.lo, s.hi)
    orig = _fetch_widths(voices[0], nframes, orbit)
    assert len(orig) == 269, len(orig)
    on_ticks = _first_pass_widths(_walk_capture(name, tempo // ticks)["plan"], 0)
    as_shipped = _first_pass_widths(shipped["plan"], 0)
    on_calls = _first_pass_widths(_walk_capture(name, 1)["plan"], 0)

    def exact(plan: list[int]) -> int:
        return sum(1 for a, b in zip(orig, plan) if a == b)
    assert exact(as_shipped) == len(orig), (exact(as_shipped), len(orig))
    assert exact(on_ticks) == len(orig), (exact(on_ticks), len(orig))
    assert exact(on_calls) <= len(orig) // 4, exact(on_calls)


def test_game_killers_bucket_pairing_did_not_place_the_triangle_clock():
    """RETIRES `test_game_killers_onsets_put_the_triangle_sweep_on_the_call_
    clock`, whose conclusion -- "the triangle sweep's counter runs inside
    the multispeed core" -- the player refutes. Game_Killer's PSID speed
    flag is 0 (one call a frame) and its play entry IS an outer gate
    ($0826 `DEC $0C8C / BPL / LDA #$09 / STA $0C8C / RTS`, one frame in ten
    skipped) in front of a single pass over three voices: there is no core
    loop, and -S9 is our packer's factor for its 20/9-frame row. A row is
    `frames_for(0)` = 2 engine ticks, so the tick clock is 20 // 2 = 10 of
    our calls.

    The retired measurement is re-taken below and still reads what it read
    -- bucket-paired over every onset in bucket >= 8, the call clock at
    0.615 and the frame clock at 0.21 -- because it paired onsets of any
    instrument that sits at $8xx (voice 0's accumulate record among them)
    against the sweeping records' plan, and compared buckets, not widths.
    Under the exact metric (`_fetch_widths` against the plan, first 200)
    the shipped sim matches the original on NO clock: 27, 43 and 34 of 200
    at 1, 9 and 10 calls (924e4bd). What it misses there is the DIRECTION:
    `LDA $0C78,X` is per voice, voice 0 carries it across GT 3 and GT 8,
    and the image holds $0C78 = 1 -- voice 0 opens descending -- where the
    sim starts every record ascending. Carried per voice from the image,
    on the tick clock, a scratch walk plans 570 of 570 of the emulated
    original's first-pass fetch widths (goatwriter.PulsePhaseSim).

    The tick clock now SHIPS (task triangle-walk-on-engine-ticks), so the
    three clocks below are forced CALL clocks (`_walk_capture`'s `force`
    drops `ticks_per_row` and the image's voice state): 1 is the pre-fix
    walk, 10 is the tick clock by another road with a per-record
    direction. The exact-metric bound holds on all three -- the clock alone
    does not rescue a per-record direction. The per-VOICE direction now
    ships, and the shipped walk plans every emulated fetch width
    (`test_the_shipped_triangle_walk_plans_every_emulated_fetch_width`)."""
    import fidelity as F
    from h2g.detect import PULSE_TRI_SHAPE, detect
    from h2g.goatwriter import find_song_speeds
    from h2g.search import search_file
    from h2g.sidfile import load_sid
    name = "Game_Killer.sid"
    voices, nframes = _trace_original(name, 90)
    corpus, _ = _corpus_and_presets()
    sid = load_sid(str(corpus / name))
    speeds = find_song_speeds(sid, detect(sid, lambda *a, **k: None))
    assert (sid.speed, sid.play_addr) == (0, 0x0826), (sid.speed, sid.play_addr)
    play = sid.to_offset(sid.play_addr)
    assert bytes(sid.data[play:play + 11]) == bytes.fromhex("CE8C0C1006A9098D8C0C60")
    assert (speeds.frames_for(0), speeds.skip_for(0)) == (2, 9)
    off = search_file(sid.data, PULSE_TRI_SHAPE)
    direction = sid.data[off + 19] | (sid.data[off + 20] << 8)
    assert sid.data[off + 18] == 0xBD and direction == 0x0C78   # LDA dir,X
    assert sid.data[sid.to_offset(direction)] == 1, "voice 0 no longer opens descending"

    # the retired metric, re-taken
    t = F.register_timeline(voices[0].pulse_events, nframes)
    buckets = [t[f + 1] // F.PULSE_PHASE_BUCKET for f in voices[0].attack_frames
               if f + 1 < nframes]
    buckets = [b for b in buckets if b >= 8]
    plans = {c: _walk_capture(name, c) for c in (1, 9, 10)}
    shipped = _walk_capture(name)
    assert plans[1]["tempos"] == [20]
    assert shipped["ticks"] == [[2]], shipped["ticks"]
    # the shipped walk is 10 calls a tick on this -S9 file: forced to 10
    # with the image's voice state put back, it plans the same widths
    ten_voiced = _walk_capture(name, 10, keep_start=True)
    assert (_first_pass_widths(shipped["plan"], 0)
            == _first_pass_widths(ten_voiced["plan"], 0)), (
        "the shipped walk is not 10 calls a tick on this -S9 file")

    def paired(plan) -> float:
        mine = [w // F.PULSE_PHASE_BUCKET for w in _first_pass_widths(plan, 0)]
        mine = [b for b in mine if b >= 8]
        n = min(200, len(mine))
        return sum(1 for i in range(n) if buckets[i] == mine[i]) / n
    on_calls, on_frames = paired(plans[1]["plan"]), paired(plans[9]["plan"])
    assert on_calls >= 0.5 and on_frames <= 0.35, (on_calls, on_frames)

    # the exact metric: no clock rescues a sim whose direction is per record
    orbit: set = set()
    for s in plans[1]["sims"].values():
        orbit |= _tri_orbit(s.width, s.step, s.lo, s.hi)
    orig = _fetch_widths(voices[0], nframes, orbit)
    assert len(orig) >= 200, len(orig)
    for c, got in plans.items():
        plan = _first_pass_widths(got["plan"], 0)
        exact = sum(1 for a, b in zip(orig[:200], plan) if a == b)
        assert exact <= 50, (c, exact)


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
        if det.pulse_tri_hi < 0:
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


def test_build_pulse_phase_table_degrades_instead_of_refusing_last_v8():
    """`build_pulse_phase_table` used to return None outright once one
    instrument's phase set overflowed `GT_MAX_TABLELEN`, and convert.py's
    caller reverted the WHOLE expansion -- Last_V8 shipped with no
    CMD_SETPULSEPTR at all rather than losing only instrument 7 and 9's
    sweeps. Pinned here at the exact counts measured against the corpus with
    `pulse_phase` forced on (Last_V8 does not ship it): 18 instruments lose
    their phase entries and, of those, 16 are degraded all the way to
    pointer 0 (the static pair does not fit either) -- and the file still
    converts and carries CMD_SETPULSEPTR on the instruments that kept their
    phase.

    **The figures were 5 and 3 until task triangle-walk-on-engine-ticks**,
    on the triangle walk's CALL clock (a row = tempo 4 sweep ticks). The
    walk now steps `frames_for` = 2 ENGINE ticks a row (`ticks_per_row`,
    see `test_the_triangle_walk_steps_engine_ticks_and_the_bounds_walk_
    frames`), so each record's notes open on more distinct phases and the
    table overflows harder: 18 and 16, measured at 26111a5 + that change.
    Those are exactly the counts this docstring used to attribute to the
    rejected FRAME clock (`calls_per_frame=multiplier`) -- on this `-S2`,
    tempo-4 file the frame clock is also 2 ticks a row, so it was this
    clock all along. The assertion this test exists for is unchanged: a
    partial table ships instead of none.

    **And 12 and 10 since task triangle-table-rate-and-first-step-under-an-
    outer-gate**: the triangle legs now ramp to the sweep's ORBIT
    (`goatwriter._tri_orbit_bounds`) rather than to the routine's nibbles,
    and the orbit's bottom is the first lattice width in the low nibble,
    not `lo_v` -- shorter legs, fewer split tick entries, so fewer records
    overflow: instrument 2 (speed 2) spans 672 ticks where it spanned 768,
    6 entries a leg where it took 7, and the four planned records' blocks
    total 410 entries against 423 (C:/t/triangle-table-rate/probes/
    lastv8_entries.py). Measured at 26111a5 + that change; its rate half does not
    reach this file (`_triangle_calls_per_tick` is None: 4 calls / 2 ticks
    is the multiplier).
    """
    lines = _forced_pulse_phase_logs("Last_V8.sid")
    full = [l for l in lines if "PULSE TABLE FULL UNDER --pulse-phase --" in l]
    assert len(full) == 1, lines
    assert "12 INSTRUMENT(S) LOSE THEIR PHASE ENTRIES" in full[0], full[0]
    assert "10 SET NO WIDTH AT ALL" in full[0], full[0]
    assert any("FALLING BACK TO A STATIC WIDTH" in l for l in lines), lines
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


def _game_killer_forced_capture() -> dict:
    """Game_Killer under its preset with `pulse_phase` forced: the walk's
    plan, the phase table `build_pulse_phase_table` returned, the count of
    CMD_SETPULSEPTR rows either side of `budget_pulse_phase_commands`, the
    sims, and the legalised .sng -- one in-process conversion."""
    import fidelity as F
    from h2g import convert as C
    from h2g import goatwriter as G
    corpus, doc = _corpus_and_presets()
    name = "Game_Killer.sid"
    if not (corpus / name).exists():
        import pytest
        pytest.skip(f"{name} not in the corpus here")
    kwargs = F._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    got: dict = {}
    real_c, real_t = C.collect_pulse_phases, C.build_pulse_phase_table
    real_b = G.budget_pulse_phase_commands

    def spy_c(patterns, tracks, tempos, sims, *a, **kw):
        got["sims"] = {n: s.clone() for n, s in sims.items()}
        got["plan"] = real_c(patterns, tracks, tempos, sims, *a, **kw)
        return got["plan"]

    def spy_t(*a, **kw):
        got["table"] = real_t(*a, **kw)
        return got["table"]

    def spy_b(patterns, command, *a, **kw):
        out = real_b(patterns, command, *a, **kw)
        got["budget"] = tuple(
            sum(1 for p in ps for r in G.pattern_rows(p) if r[2] == command)
            for ps in (patterns, out))
        return out
    C.collect_pulse_phases, C.build_pulse_phase_table = spy_c, spy_t
    G.budget_pulse_phase_commands = spy_b
    try:
        raw = C.convert(str(corpus / name), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases, C.build_pulse_phase_table = real_c, real_t
        G.budget_pulse_phase_commands = real_b
    assert got.get("plan") and got.get("table"), "no phase plan or table"
    got["sng"], _ = F.legalise_restarts(raw)
    got["multiplier"] = F._preset_multiplier(doc, name)
    return got


def _gt_pulse_walk(entries, ptr: int, calls: int) -> list[int]:
    """The width after each call from a freshly set pulse pointer, as
    player.s's `mt_pulseexec` steps it (GoatTracker 2.77, player.s:1100-1190):
    a left byte >= $80 SETS hi/lo and advances; otherwise it loads the
    time on an idle counter, adds the signed speed EVERY call, and advances
    when the time runs out; a left $FF after the current row is a jump."""
    time, w, out = 0, 0, []
    for _ in range(calls):
        left, right = entries[ptr - 1]
        if time == 0 and left >= 0x80:
            w = ((left & 0x0F) << 8) | right
            done = True
        else:
            if time == 0:
                time = left
            w = (w + (right - 0x100 if right >= 0x80 else right)) & 0xFFF
            time -= 1
            done = time == 0
        if done:
            nxt = entries[ptr]
            ptr = nxt[1] if nxt[0] == 0xFF else ptr + 1
        out.append(w)
    return out


def test_game_killers_packed_notes_open_on_the_planned_width():
    """THE PLAN REACHES THE PACKED PLAYER. Between the walk and the trace
    sit `build_pulse_phase_table`, `apply_pulse_phase`,
    `budget_pulse_phase_commands`, gt2reloc at -S9 and player.s; on
    Game_Killer none of them loses a phase. siddump -m1 on the -S9 file is
    one row per PLAY CALL, so the width on each voice-0 attack call is the
    phase entry's SET (the ramp starts on the next call, 22 a call -- $E0
    per engine tick of 10 calls; 25, per frame, until task
    triangle-table-rate-and-first-step-under-an-outer-gate), and
    the sequence of those widths is the walk's planned sequence: 550 of
    the 564 orbit widths in 180 s at 924e4bd (a note with no command opens
    on its record's own entry, also on the orbit and not in the plan). The budget drops none of the 489 command rows.

    So the gap between the plan and `pphase` on this file is not here: it
    is the walk's clock and direction (the plan itself) and the f+1
    reading of a per-call ramp -- patterns.collect_pulse_phases has the
    decomposition."""
    import difflib
    import shutil
    import tempfile
    import fidelity as F
    got = _game_killer_forced_capture()
    if not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip("siddump not available here")
    assert got["budget"][0] == got["budget"][1] >= 450, got["budget"]
    entries, _, index = got["table"]
    for (num, w, d), at in index.items():
        assert entries[at - 1] == (0x80 | (w >> 8), w & 0xFF), (num, hex(w), d, entries[at - 1])
    plan = _first_pass_widths(got["plan"], 0)
    mult = got["multiplier"]
    assert mult == 9, mult
    wd = Path(tempfile.mkdtemp(prefix="gk_reach_"))
    try:
        packed = F.pack_sid(got["sng"], wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no file"
        seconds = 180
        tr = F.run_siddump(packed, seconds * mult, 0, F.SIDDUMP, calls=1)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    n = seconds * mult * 50
    t = F.register_timeline(tr[0].pulse_events, n)
    widths = set(plan)
    calls = [q for q in tr[0].attack_frames if q + 1 < n and t[q] in widths]
    shipped = [t[q] for q in calls]
    assert len(shipped) >= 500, len(shipped)
    m = difflib.SequenceMatcher(None, plan, shipped, autojunk=False)
    matched = sum(b.size for b in m.get_matching_blocks())
    assert matched >= 0.95 * len(shipped), (matched, len(shipped), len(plan))
    assert {abs(t[q + 1] - t[q]) for q in calls[:100]} == {22}, (
        "the ramp no longer starts on the call after the SET at 22 a call")


def _orig_ticks_to_top(w: int, direction: int, step: int, lo: int, hi: int) -> int:
    """Engine ticks the ORIGINAL takes from (w, direction) to first store a
    width in the top nibble -- the player's own `ADC step` / `CMP #hi`,
    `SBC step` / `CMP #lo` on equality, 12 bits: a second reader beside
    PulsePhaseSim and the phase table."""
    n = 0
    while (w >> 8) != hi:
        if direction > 0:
            w = (w + step) & 0xFFF
        else:
            w = (w - step) & 0xFFF
            if (w >> 8) == lo:
                direction = +1
        n += 1
    return n


def test_the_triangle_table_legs_reach_the_orbit_top_at_the_tick_rate():
    """REWRITES `test_the_triangle_table_holds_bucket_14_for_two_calls_at_
    most` (924e4bd), which pinned the table half of Game_Killer's f+1 loss
    and asked to be rewritten as the fix's test. Task triangle-table-rate-
    and-first-step-under-an-outer-gate.

    The original turns on the first width whose nibble reaches the bound
    and stores it: GT 3/GT 8 step $E0 a tick and orbit $8E0..$E20, so the
    up leg goes $D40 -> $E20 in one engine tick. The table's legs used to
    ramp to `hi_v` = $E00 at 25 a call ($E0 divided per FRAME, by 9): a leg
    from $D40 topped out at $DEF and the ($E20, down) entry left bucket 14
    two calls after its SET -- 0 packed f+1 readings in bucket 14 against
    the original's 55 in 180 s. Now the legs ramp to the ORBIT
    (`_tri_orbit_bounds`) at $E0 per ENGINE tick of 10 calls
    (`_triangle_calls_per_tick`, 20 calls / 2 ticks a row): 22 a call. So
    every entry first reaches bucket 14 within one call of 10 x the ticks
    the original takes, and the band stays within one call's step of the
    orbit. Packed and traced at -m9 (one sample a frame, what `pphase`
    reads), voice 0's f+1 readings put 20 attacks in bucket 14
    (26111a5 + this change; the original's 55 re-read here), and the
    frame-paired f+1 bucket agreement on the 585 sweeping notes went
    0.617 -> 0.747 -- by the attack's call in its frame: 2 (189 notes)
    0.402 -> 0.513, 5 (167) 0.701 -> 0.898, 8 (133) 0.880 -> 1.000
    (C:/t/triangle-table-rate/reach_base.txt, reach_edit.txt). A hold
    before the first step was measured and NOT shipped: 4 calls reads
    0.774 overall but trades call 8 down to 0.481 for call 2 up to 1.000,
    a constant fitted on one file (reach_hold4.txt, hold5, hold9)."""
    import shutil
    import tempfile
    import fidelity as F
    got = _game_killer_forced_capture()
    entries, _, index = got["table"]
    sims = got["sims"]
    assert {(s.step, s.delay, s.lo, s.hi) for s in sims.values()} == {(0xE0, 1, 8, 14)}
    orbit: set = set()
    for s in sims.values():
        orbit |= _tri_orbit(s.width, s.step, s.lo, s.hi)
    top, bottom = max(orbit), min(orbit)
    assert (top, bottom) == (0xE20, 0x8E0), (hex(top), hex(bottom))
    assert any(w == 0xE20 for (_, w, _) in index), "no planned note opens at the top"
    speed, calls_per_tick = 22, 10
    for (num, w, d), at in index.items():
        seq = _gt_pulse_walk(entries, at, 240)
        assert seq[0] == w, (num, hex(w), d, hex(seq[0]))
        assert abs(((seq[1] - seq[0] + 0x800) & 0xFFF) - 0x800) == speed, (num, hex(w), d)
        first14 = next(k for k, x in enumerate(seq) if x >> 8 == 0xE)
        want = calls_per_tick * _orig_ticks_to_top(w, d, 0xE0, 8, 14)
        assert abs(first14 - want) <= 1, (num, hex(w), d, first14, want)
        assert top - speed <= max(seq) <= top + speed, (num, hex(w), d, hex(max(seq)))
        assert bottom - speed <= min(seq) <= bottom + speed, (num, hex(w), d, hex(min(seq)))

    # the packed trace, one sample a frame: bucket 14 one frame after an attack
    if not Path(F.SIDDUMP).exists():
        import pytest
        pytest.skip("siddump not available here")
    seconds, mult = 180, got["multiplier"]
    orig, nframes = _trace_original("Game_Killer.sid", seconds)
    wd = Path(tempfile.mkdtemp(prefix="gk_b14_"))
    try:
        packed = F.pack_sid(got["sng"], wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no file"
        ours = F.run_siddump(packed, seconds, 0, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)

    def in14(v) -> int:
        t = F.register_timeline(v.pulse_events, nframes)
        return sum(1 for f in v.attack_frames if f + 1 < nframes and t[f + 1] >> 8 == 0xE)
    assert in14(orig[0]) == 55, in14(orig[0])
    assert in14(ours[0]) >= 15, ("bucket 14 no longer sounds one frame after "
                                 "an attack", in14(ours[0]))


def test_the_triangle_table_divides_per_engine_tick_only_under_an_outer_gate():
    """`convert._triangle_calls_per_tick` is `tempo / ticks_per_row`, the
    ratio most groups agree on (the first group's on a tie), and None
    where it is the multiplier -- so the rate changes only where an outer
    gate skips frames: Game_Killer 20/2 at -S9, Rasputin 6/2 and 5/2 at
    -S2, Ninja 4/3 at -S1; Gerry_the_Germ's one 3/2 group is outvoted.
    `_phase_sweep_params` on Game_Killer's GT 3: 22 a call at 10 calls a
    tick, 25 per frame, and the orbit $8E0..$E20 either way."""
    from fractions import Fraction
    corpus, _ = _corpus_and_presets()
    from h2g import convert as C
    from h2g.detect import detect
    from h2g.goatwriter import _phase_sweep_params
    from h2g.sidfile import load_sid
    tpt = C._triangle_calls_per_tick
    assert tpt([20], [2], 9) == 10
    assert tpt([6, 5], [2, 2], 2) == 3
    assert tpt([4], [3], 1) == Fraction(4, 3)
    assert tpt([3, 3, 3, 3, 3, 4, 3], [3, 3, 2, 3, 3, 4, 3], 1) is None
    assert tpt([4, 4, 4], [2, 2, 2], 2) is None
    assert tpt([4], None, 2) is None and tpt([], [2], 2) is None
    path = corpus / "Game_Killer.sid"
    if not path.exists():
        import pytest
        pytest.skip("Game_Killer.sid not in the corpus here")
    sid = load_sid(str(path))
    det = detect(sid, lambda *a, **k: None)
    rec = 2                  # record 2: GT 3 under the preset's layout, $9C0
    assert _phase_sweep_params(sid, det, rec, 9, 10)[1:] == (22, 0x8E0, 0xE20, False)
    assert _phase_sweep_params(sid, det, rec, 9)[1:] == (25, 0x8E0, 0xE20, False)


# --- the engine-tick clock, synthetic (task triangle-walk-on-engine-ticks) ---

def _tick_walk_fixture():
    """5_Title_Tunes' sim (step $40, delay 2) on one voice, two notes on
    record 2 at rows 0 and 1 of a 4-row pattern; voices 2 and 3 play an
    empty pattern (a `00` restart operand would make pattern 0 sound on all
    three and decline the group). Same shape as test_pulse.py's
    `test_the_triangle_walk_honours_calls_per_frame_too`."""
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g.goatwriter import PulsePhaseSim
    from h2g.patterns import GT_NO_NOTE

    def pattern(rows):
        out: list = []
        for note, instr in rows:
            out += [GT_NO_NOTE if note is None else note, instr, 0, 0]
        return out + [0xFF, 0, 0, 0]
    pats = [pattern([(0x70, 2), (0x72, 0), (None, 0), (None, 0)]),
            pattern([(None, 0)] * 4)]
    tracks = [[0, 0xFF, 0x00], [1, 0xFF, 0x01], [1, 0xFF, 0x01]]
    return pats, tracks, (lambda: PulsePhaseSim(0x900, 0x40, 2, 8, 0xE))


def test_the_triangle_walk_steps_ticks_per_row_and_skips_the_fetch_tick():
    """A row is `ticks_per_row[g]` sweep ticks for a triangle sim, the
    first skipped on a note row (the player jumps past the sweep on the
    voice's fetch tick), and `calls_per_frame` is not consulted. After
    the 7-tick preroll the counter is at 1 and the first note opens at
    $A00; 4 ticks a row with the fetch tick skipped is 3 sweep ticks = 1
    step ($A40) -- 4 unskipped would be 2 steps ($A80), and the call clock
    (tempo 8) 3 steps ($AC0)."""
    from h2g.patterns import collect_pulse_phases
    pats, tracks, sim = _tick_walk_fixture()
    want = [(0, 0, {0: (2, (0xA00, +1)), 1: (2, (0xA40, +1))})]
    for cpf in (1, 3):
        got = collect_pulse_phases([list(p) for p in pats], [list(t) for t in tracks],
                                   [8], {2: sim()}, calls_per_frame=cpf,
                                   ticks_per_row=[4])
        assert got is not None and got[1] == want, (cpf, got)
    on_calls = collect_pulse_phases([list(p) for p in pats], [list(t) for t in tracks],
                                    [8], {2: sim()})
    assert on_calls[1] == [(0, 0, {0: (2, (0xA00, +1)), 1: (2, (0xAC0, +1))})]
    try:
        collect_pulse_phases(pats, tracks, [8], {2: sim()}, ticks_per_row=[4, 4])
    except ValueError:
        pass
    else:
        raise AssertionError("a tick list the wrong length was accepted")


def test_the_bounds_walk_ignores_ticks_per_row():
    """The bounds engine's clock is the original's frame (`calls_per_frame`,
    Saboteur_II); `ticks_per_row` is the triangle engine's alone. Tempo 8
    at 3 calls a frame plans the free note 4 steps past the seed
    (test_pulse.py's `test_the_bounds_walk_runs_on_the_originals_frame_
    clock`) whatever tick count is passed beside it."""
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g.goatwriter import PulseBoundsSim
    from h2g.patterns import GT_NO_NOTE
    from h2g.patterns import collect_pulse_phases
    pat: list = []
    for note, instr in ((0x70, 2), (None, 0), (0x72, 0), (None, 0)):
        pat += [GT_NO_NOTE if note is None else note, instr, 0, 0]
    pat += [0xFF, 0, 0, 0]
    for ticks in (None, [1], [5]):
        tracks = [[0, 0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]]
        got = collect_pulse_phases([list(pat)], tracks, [8],
                                   {2: PulseBoundsSim(0x080, 0x54, 0x0, 0xF)},
                                   free_rows={0: frozenset({2})},
                                   calls_per_frame=3, ticks_per_row=ticks)
        assert got is not None
        assert got[1] == [(0, 0, {2: (2, (0x080 + 4 * 0x54, +1))})], (ticks, got)


def test_triangle_ticks_per_row_is_per_group_and_falls_back_to_subtune_0():
    """convert.py's `_triangle_ticks_per_row`: `frames_for(k)` per group
    where the groups still number the header's subtunes, subtune 0's for a
    subtune whose reload is unreadable, subtune 0's for every group once a
    split has shifted the numbering (the tempo derivation's own rule), and
    None -- the walk's call clock -- where subtune 0 has none."""
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g import convert as C
    from h2g.goatwriter import SongSpeeds
    real = C.find_song_speeds
    try:
        C.find_song_speeds = lambda sid, det: SongSpeeds((2, 3, None), 0, 0)
        assert C._triangle_ticks_per_row(None, None, 3, 3) == [2, 3, 2]
        assert C._triangle_ticks_per_row(None, None, 4, 3) == [2, 2, 2, 2]
        C.find_song_speeds = lambda sid, det: SongSpeeds((None, 3), 0, 0)
        assert C._triangle_ticks_per_row(None, None, 2, 2) is None
        C.find_song_speeds = lambda sid, det: None
        assert C._triangle_ticks_per_row(None, None, 1, 1) is None
    finally:
        C.find_song_speeds = real


# --- the triangle's per-VOICE start (task triangle-direction-per-voice-from-the-image)

# Where each original fetches a voice's note and which cell holds the voice's
# current record, read off the disassembly (C:/t/triangle-sim-model/
# dis_gk_full.txt; player_emu.py): the fetch PC runs with X = the voice.
_FETCH_READING = {
    "Game_Killer.sid": (0x089D, 0x0C66),
    "5_Title_Tunes.sid": (0x0C7A, 0x1040),
}


def _emulated_fetches(name: str, frames: int) -> list:
    """[(voice, record + 1, width)] of every note fetch in the ORIGINAL, in
    play order, by running its init and `frames` play calls under py65 --
    the width the voice's pulse registers hold at the end of the fetch
    frame, which the fetch tick does not sweep. A second reader beside
    siddump (whose attack frames are the gate's, not the fetch's)."""
    import pytest
    mpu_mod = pytest.importorskip("py65.devices.mpu6502")
    corpus, _ = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus here")
    raw = path.read_bytes()
    hlen = raw[7] | (raw[6] << 8)
    load, body = raw[8] << 8 | raw[9], raw[hlen:]
    if load == 0:
        load, body = body[0] | (body[1] << 8), body[2:]
    init, play = raw[0x0A] << 8 | raw[0x0B], raw[0x0C] << 8 | raw[0x0D]
    fetch_pc, instr = _FETCH_READING[name]
    mem = bytearray(65536)
    mem[load:load + len(body)] = body
    m = mpu_mod.MPU(memory=mem)
    sent = 0xFFF0
    seen: list = []

    def call(addr: int) -> None:
        m.sp = 0xFD
        mem[0x1FF], mem[0x1FE] = (sent - 1) >> 8, (sent - 1) & 0xFF
        m.pc, m.a, m.x, m.y = addr, 0, 0, 0
        for _ in range(2_000_000):
            if m.pc == sent:
                return
            if m.pc == fetch_pc:
                seen.append(m.x)
            m.step()
        raise AssertionError(f"{name}: runaway at ${m.pc:04X}")
    call(init)
    out: list = []
    for _ in range(frames):
        seen.clear()
        call(play)
        for v in sorted(set(seen)):
            w = mem[0xD402 + 7 * v] | ((mem[0xD403 + 7 * v] & 0x0F) << 8)
            out.append((v, mem[instr + v] + 1, w))
    return out


def _voice_plan(plan, track: int) -> list:
    """The walk's first-pass (instrument, width) on `track`, in play order."""
    out: list = []
    for ti, pos, rows in sorted(plan[1], key=lambda x: (x[0], x[1])):
        if ti == track:
            out += [(rows[r][0], rows[r][1][0] & 0xFFF) for r in sorted(rows)]
    return out


def test_the_shipped_triangle_walk_plans_every_emulated_fetch_width():
    """THE DIRECTION AND THE COUNTER ARE PER VOICE, AND THE IMAGE SEEDS
    THEM. Against the py65-emulated originals' fetches on the sweeping
    records, paired in order with the walk's first pass: Game_Killer voice 0
    plans all 570 (393 with each record starting (+1, 0) and the fitted
    7-tick preroll -- the walk the tick clock alone shipped), 5_Title_Tunes
    voice 2 all 192 (96). Game_Killer's `$0C78` = 1 opens voice 0
    descending and it carries one direction across GT 3 and GT 8;
    5_Title_Tunes voice 2 opens descending with its counter at 1, three
    ticks before its first fetch."""
    for name, frames, voice, whole, per_record in (
            ("Game_Killer.sid", 9000, 0, 570, 393),
            ("5_Title_Tunes.sid", 9000, 2, 192, 96)):
        shipped = _walk_capture(name)
        before = _walk_capture(name, per_record=True)
        recs = set(shipped["sims"])
        orig = [(n, w) for v, n, w in _emulated_fetches(name, frames)
                if v == voice and n in recs]
        plan = _voice_plan(shipped["plan"], voice)
        assert len(plan) == whole and len(orig) >= whole, (name, len(plan), len(orig))
        assert sum(1 for a, b in zip(orig, plan) if a == b) == whole, name
        old = _voice_plan(before["plan"], voice)
        assert sum(1 for a, b in zip(orig, old) if a == b) == per_record, name


def test_convert_hands_the_walk_the_images_voice_state():
    """convert.py `_triangle_start`: each voice's (direction, counter) from
    the image cells the sweep names, and the speed gate's byte as the ticks
    before the first fetch -- each file's first-fetch tick under py65
    (C:/t/triangle-voice-seeds/probe_cells.txt). The bounds engine gets
    neither (Saboteur_II)."""
    want = {
        "Game_Killer.sid": ([(-1, 0), (+1, 0), (+1, 0)], 1),
        "5_Title_Tunes.sid": ([(+1, 0), (+1, 0), (-1, 1)], 3),
        "Rasputin.sid": ([(+1, 0)] * 3, 0),
        "One_Man_and_his_Droid.sid": ([(+1, 0)] * 3, 0),
        "Saboteur_II.sid": (None, None),
    }
    for name, (seeds, preroll) in want.items():
        got = _walk_capture(name)
        assert (got["seeds"], got["preroll"]) == (seeds, preroll), (
            name, got["seeds"], got["preroll"])


def test_the_triangle_direction_and_counter_carry_per_voice_across_records():
    """Two sweeping records on one voice share ONE direction and ONE delay
    counter, the first seeded from `voice_seeds`, and the second record's
    first note opens on the carried direction. Record 2 ($900, step $40,
    delay 2) and record 3 ($D00, step $40, delay 1), one note each on rows
    0, 1 and 2 (2, 3, 3), 2 ticks a row, voice 0 seeded (-1, 3), no
    preroll: row 0 opens (900, -); its one unskipped tick takes the counter
    3 -> 2; record 3 takes (-, 2) and opens (D00, -); its tick takes 2 -> 1,
    no step; row 2 opens (D00, -) again. Per record (no seeds) record 3
    starts (+, 0): (D00, +), then a step on its first tick, (D40, +)."""
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g.goatwriter import PulsePhaseSim
    from h2g.patterns import GT_NO_NOTE, collect_pulse_phases
    pat: list = []
    for note, instr in ((0x70, 2), (0x72, 3), (0x74, 3), (None, 0)):
        pat += [GT_NO_NOTE if note is None else note, instr, 0, 0]
    pat += [0xFF, 0, 0, 0]
    rest: list = [GT_NO_NOTE, 0, 0, 0] * 4 + [0xFF, 0, 0, 0]

    def walk(**kw):
        tracks = [[0, 0xFF, 0x00], [1, 0xFF, 0x01], [1, 0xFF, 0x01]]
        sims = {2: PulsePhaseSim(0x900, 0x40, 2, 8, 0xE),
                3: PulsePhaseSim(0xD00, 0x40, 1, 8, 0xE)}
        got = collect_pulse_phases([list(pat), list(rest)], tracks, [4], sims,
                                   ticks_per_row=[2], **kw)
        assert got is not None
        return got[1]
    seeds = [(-1, 3), (+1, 0), (+1, 0)]
    assert walk(voice_seeds=seeds, preroll=0) == [
        (0, 0, {0: (2, (0x900, -1)), 1: (3, (0xD00, -1)), 2: (3, (0xD00, -1))})]
    assert walk(preroll=0) == [
        (0, 0, {0: (2, (0x900, +1)), 1: (3, (0xD00, +1)), 2: (3, (0xD40, +1))})]
    # `preroll` None is the fitted constant, for a caller with no player
    from h2g.patterns import PULSE_PHASE_PREROLL
    assert walk(voice_seeds=seeds) == walk(voice_seeds=seeds,
                                           preroll=PULSE_PHASE_PREROLL)
    assert walk(voice_seeds=seeds, preroll=3) != walk(voice_seeds=seeds, preroll=0)


def test_the_counter_cell_reads_as_the_players_dec_bpl():
    """`DEC cnt,X / BPL skip`: a cell of 1..$80 waits that many ticks, 0 and
    $81..$FF step on the next one -- so $80 is 128, never -128."""
    sys.path.insert(0, str(PYTHON_ROOT))
    from h2g.goatwriter import PulsePhaseSim, pulse_tri_counter_seed
    for cell in (0, 1, 2, 0x1F, 0x7F, 0x80, 0x81, 0xFF):
        sim = PulsePhaseSim(0x900, 0x40, 1, 8, 0xE)
        sim._dcnt = pulse_tri_counter_seed(cell)
        waited = 0
        while sim.width == 0x900:
            sim.advance(1)
            waited += 1
        # the player: DEC until the result is negative, as a byte
        c, ticks = cell, 0
        while True:
            c = (c - 1) & 0xFF
            ticks += 1
            if c >= 0x80:
                break
        assert waited == ticks, (hex(cell), waited, ticks)
