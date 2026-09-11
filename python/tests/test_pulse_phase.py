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
    assert "if pulse_phase and pulse and det.pulse_tri_hi >= 0 and group_tempos:" in src
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
