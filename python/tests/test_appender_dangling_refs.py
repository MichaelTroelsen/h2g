"""Every instrument appender numbers its clones below every dangling reference.

`note_passes.clone_number_ceiling` bounded the legato and free-note clones
(tests/test_clone_number_ceiling.py). The other appenders -- the tempo-duty
split, the fixed-arp / pitch-seq / gated-nibble phase splits and the
past-table drum variants -- number from `instr_used + 1` too, capped only by
`TEMPO_DUTY_MAX_CLONE`. A clone numbered onto an instrument byte some
pattern already names satisfies it: every row naming it plays the clone and
the DANGLING warning (`> written_instr`) stops counting it.

Opened by legato-clone-numbers-below-dangling-refs at 6e467ff. Measured at
82d60ac (2026-10-09): under FIXED and under presets no corpus file has any
appended number inside the range of its own input's dangling bytes (0 of 95,
6/9 refused). The hazard is structural, so these tests inject it: each wraps
one plan to hand it a pattern naming a number the plan would take next, and
asserts the plan stays below it.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.goatwriter import arpeggio as AR
from h2g.goatwriter import note_passes as NP
import h2g.goatwriter.build as B
from h2g.convert import convert
import fidelity as F

from corpus import CORPUS, needs_corpus

REPO = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60
END = [0xFF, 0, 0, 0]


# --- the shared seam, synthetic ------------------------------------------

def test_note_phase_split_stops_below_a_dangling_reference():
    """Records 1..3 written, three clones wanted (numbers 4, 5, 6), and a
    pattern no orderlist reaches names 5: only number 4 is below it."""
    rec_rows = []
    res = {}
    row = 0
    for rec in (1, 2, 3):
        # one note at residue 1 (the wanted clone), two at residue 0
        for r in (1, 0, 0):
            rec_rows += [NOTE, rec, 0, 0]
            res[row] = r
            row += 1
    pat = rec_rows + END
    residues = {(0, 0, 0): res}
    phases = {1: 0, 2: 0, 3: 0}
    tracks = [[0, 0xFF], [0xFF], [0xFF]]

    def plan(extra):
        pats = [pat] + extra
        return AR._note_phase_split(tracks, pats, residues, phases,
                                    {1, 2, 3}, 4, factor=None)

    free = plan([])
    assert free is not None
    assert [c[1] for c in free.clones] == [4, 5, 6]
    held = plan([[NOTE, 5, 0, 0] + END])
    assert held is not None
    assert [c[1] for c in held.clones] == [4]
    none = plan([[NOTE, 4, 0, 0] + END])
    assert none is None


# --- the build_sng seam, per appender -------------------------------------

def _injecting(monkeypatch, owner, name, pat_at, used_at, offset, seen):
    """Wrap `owner.name` so the patterns it is handed carry one more pattern
    naming `instr_used + offset`, and record what it returned."""
    real = getattr(owner, name)

    def spy(*a, **k):
        a = list(a)
        used = a[used_at]
        a[pat_at] = list(a[pat_at]) + [[NOTE, used + offset, 0, 0] + END]
        r = real(*a, **k)
        seen.append((used, used + offset, r))
        return r

    monkeypatch.setattr(owner, name, spy)


def _preset(name):
    doc = json.loads((REPO / "presets.json").read_text(encoding="utf-8"))
    return F._preset_opts(doc, name)


def _numbers(result):
    if result is None:
        return []
    if isinstance(result, tuple):                  # past_table_drum_plan
        return [v for _r, v, _b in result[1]]
    return [c[1] for c in result.clones]


# (file, owner, plan, patterns index, instr_used index, offset to dangle)
CASES = [
    ("Rasputin.sid", B, "tempo_duty_split_plan", 3, 6, 2),
    ("Chimera.sid", B, "fixed_arp_phase_split_plan", 3, 6, 2),
    ("Las_Vegas_Video_Poker.sid", B._gw_arpeggio,
     "nibble_gate_phase_split_plan", 3, 6, 2),
    ("Sanxion.sid", B, "past_table_drum_plan", 2, 7, 1),
]


@needs_corpus
@pytest.mark.skipif(not (REPO / "presets.json").exists(),
                    reason="presets.json absent")
@pytest.mark.parametrize("name,owner,plan,pat_at,used_at,offset", CASES)
def test_plan_numbers_no_clone_onto_a_dangling_reference(
        monkeypatch, name, owner, plan, pat_at, used_at, offset):
    opts = _preset(name)
    base = []
    real = getattr(owner, plan)

    def count(*a, **k):
        r = real(*a, **k)
        base.append(_numbers(r))
        return r

    monkeypatch.setattr(owner, plan, count)
    convert(str(CORPUS / name), log=lambda s: None, **opts)
    monkeypatch.undo()
    assert base and base[-1], f"{name}: {plan} made no clones to bound"

    seen = []
    _injecting(monkeypatch, owner, plan, pat_at, used_at, offset, seen)
    convert(str(CORPUS / name), log=lambda s: None, **opts)
    assert seen, f"{plan} never ran"
    used, dangling, result = seen[-1]
    numbers = _numbers(result)
    assert dangling not in numbers, (numbers, dangling)
    assert all(n < dangling for n in numbers), (numbers, dangling)
    assert len(numbers) < len(base[-1]), (numbers, base[-1])


def test_ceiling_is_the_bound_the_appenders_share():
    """The property the appenders rely on: nothing at or past the lowest
    dangling byte, and 63 when none dangles."""
    pats = [[NOTE, 2, 0, 0, NOTE, 9, 0, 0] + END]
    assert NP.clone_number_ceiling(pats, 4) == 8
    assert NP.clone_number_ceiling(pats, 9) == G.GT_MAX_INSTRUMENTS
