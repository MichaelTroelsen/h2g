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
    `pulse_phase` forced on (Last_V8 does not ship it): 5 instruments lose
    their phase entries and, of those, 3 are degraded all the way to pointer
    0 (the static pair does not fit either) -- and the file still converts
    and carries CMD_SETPULSEPTR on the instruments that kept their phase.
    """
    lines = _forced_pulse_phase_logs("Last_V8.sid")
    full = [l for l in lines if "PULSE TABLE FULL UNDER --pulse-phase --" in l]
    assert len(full) == 1, lines
    assert "5 INSTRUMENT(S) LOSE THEIR PHASE ENTRIES" in full[0], full[0]
    assert "3 SET NO WIDTH AT ALL" in full[0], full[0]
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
