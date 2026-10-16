"""Las_Vegas_Video_Poker's tie rows against their record's GATE residue
(lvvp-tie-rows-off-gate-residue).

Through 4f29873 every tie row of a gated nibble record (`arp_gate_phases`)
kept `CMD_TONEPORTA 00` as "gated arpeggio phase", because no walk modelled
where the tie lands on the gate's cycle. `nibble_gate_row_residues` is that
walk (`nibble_gate_note_residues`, keyed by (pattern, row)); a row played on
ONE residue is now free where it lands on the residue of the block it
restarts, and otherwise restarts a block laid out for its `GatePhase`
(`_tie_blocks_wanted`, the wavetable's `tie_blocks`). A row played on several
residues, or on a place the walk cannot model, keeps the old spelling.

Measured at 4f29873 under presets (C:/t/lvvp-tie-rows-off-gate-residue,
HISTORICAL): 28 tie rows, 7 landing on their record's residue 3 (GT $0A and
$13), 21 on $14 and $15 at residues 0, 1, 2; after: 7 free, 6 respelled onto
the 2 blocks the table holds ($14 at 1 and 2), 15 kept (it has no room for
$14 at 0, $15 at 0 and 1). fidelity (-t 180 --sound): tie_orig_only 24 -> 0, tie agreement
+0.34 pp; aud -0.25 pp and loud -0.11 pp, both under aud's 0.0077 floor.
"""
import pathlib
from types import SimpleNamespace

import pytest

from h2g import goatwriter as G
from h2g.goatwriter import arpeggio as GA
from h2g.goatwriter import build as GB
from h2g.goatwriter.arpeggio import GatePhase

from corpus import CORPUS, needs_corpus

TIE = [G.CMD_TONEPORTA, 0x00]
END = [0xFF, 0, 0, 0]
TRACKS = [[0, 0xFF, 0x00]] * 3
PERIOD = SimpleNamespace(on_interval=2, otherwise=1)      # period 4


def _distinct(g, x):
    """Record 1's block differs at every residue but 0."""
    return (x.residue if isinstance(x, GatePhase) else x) != 0


def _verdicts(monkeypatch, rows, pat, gate_skip=4, phase_clones=(),
              own_gate=3):
    monkeypatch.setattr(GA, "arp_row_residues", lambda *a: {})
    monkeypatch.setattr(GA, "nibble_gate_row_residues",
                        lambda sid, det, tracks, patterns, gate: rows)
    sid = SimpleNamespace(data=bytes(64))
    det = SimpleNamespace(instr_start=8, instr_stride=8,
                          arp_nibble_period=PERIOD)
    return GB._tie_phase_verdicts(
        sid, det, {(0, k) for k in range(1, 5)}, TRACKS, [pat], {1: 0, 5: 0},
        0, {1: 3}, {}, {}, {1: own_gate}, list(phase_clones), _distinct,
        gate_skip)


def _pat(live=1):
    return [0x60, live, 0, 0, 0x62, 0, *TIE, 0x64, 0, *TIE, 0x66, 0, *TIE,
            0x68, 0, *TIE, *END]


# --- the verdict ------------------------------------------------------------

def test_a_row_on_one_gate_residue_is_free_or_wants_its_block(monkeypatch):
    rows = {(0, 1): {3}, (0, 2): {1}, (0, 3): {0, 1}, (0, 4): {None}}
    got = _verdicts(monkeypatch, rows, _pat())
    assert (0, 1) not in got                         # lands on its own block
    assert got[(0, 2)] == ("gated arpeggio phase", 1, GatePhase(1, 4))
    assert got[(0, 3)] == ("gated arpeggio phase", 1, None)    # two residues
    assert got[(0, 4)] == ("gated arpeggio phase", 1, None)    # unmodelled


def test_without_a_gate_walk_every_gated_row_is_kept_as_before(monkeypatch):
    rows = {(0, 1): {3}, (0, 2): {1}, (0, 3): {3}, (0, 4): {3}}
    got = _verdicts(monkeypatch, rows, _pat(), gate_skip=None)
    assert got == {(0, k): ("gated arpeggio phase", 1, None)
                   for k in range(1, 5)}


def test_a_row_the_record_does_not_depend_on_is_free(monkeypatch):
    """Record 1's block at residue 0 is the record's own (`_distinct`)."""
    got = _verdicts(monkeypatch, {(0, 1): {0}, (0, 2): {0}, (0, 3): {0},
                                  (0, 4): {0}}, _pat())
    assert got == {}


def test_a_gate_clone_is_the_block_a_row_restarts(monkeypatch):
    """Played on instrument 5, a clone of record 1 laid out at residue 1: a
    row landing on 1 is free, one landing on the record's own residue 3 is
    not (the clone restarts ITS block)."""
    clones = [(1, 5, GatePhase(1, 4))]
    got = _verdicts(monkeypatch, {(0, 1): {1}, (0, 2): {3}, (0, 3): {1},
                                  (0, 4): {3}}, _pat(live=5),
                    phase_clones=clones)
    assert (0, 1) not in got and (0, 3) not in got
    assert got[(0, 2)] == ("gated arpeggio phase", 1, GatePhase(3, 4))
    assert got[(0, 4)] == ("gated arpeggio phase", 1, GatePhase(3, 4))


# --- the block ---------------------------------------------------------------

def test_a_gate_block_is_wanted_once_and_where_none_exists():
    verdicts = {
        (0, 1): ("gated arpeggio phase", 1, GatePhase(1, 4)),
        (0, 2): ("gated arpeggio phase", 1, GatePhase(1, 4)),   # same pair
        (0, 3): ("gated arpeggio phase", 1, GatePhase(2, 4)),
        (0, 4): ("gated arpeggio phase", 1, None),               # several
        (0, 5): ("gated arpeggio phase", 2, GatePhase(1, 4)),   # a clone has it
        (0, 6): ("gated arpeggio phase", 1, GatePhase(3, 4)),   # the record's
    }
    distinct = lambda g, x: x.residue != 3                       # noqa: E731
    got = GB._tie_blocks_wanted(verdicts, {1: 3, 2: 3}, distinct,
                                [(2, 20, GatePhase(1, 4))], {1: 3, 2: 3})
    assert got == [(1, GatePhase(1, 4)), (1, GatePhase(2, 4))]


def test_block_residue_of_is_the_records_in_the_residues_own_kind():
    assert GB._block_residue_of(1, GatePhase(2, 4), {1: 0}, {1: 3}) \
        == GatePhase(3, 4)
    assert GB._block_residue_of(1, 2, {1: 0}, {1: 3}) == 0
    assert GB._block_residue_of(1, GatePhase(2, 4), {1: 0}, {}) is None


def test_a_respelled_gate_row_is_a_block_start(monkeypatch):
    """`_phase_locked_ties` hands a one-residue gated row to `block_start`,
    as an arpeggio-phase row is, and keeps it where that names no block."""
    monkeypatch.setattr(GA, "arp_row_residues", lambda *a: {})
    monkeypatch.setattr(GA, "nibble_gate_row_residues",
                        lambda *a: {(0, 1): {1}, (0, 2): {2}})
    sid = SimpleNamespace(data=bytes(64))
    det = SimpleNamespace(instr_start=8, instr_stride=8,
                          arp_nibble_period=PERIOD)
    respelled: dict = {}
    kept = GB._phase_locked_ties(
        sid, det, {(0, 1), (0, 2)}, TRACKS, [_pat()], {1: 0}, 0, {1: 3},
        {}, {}, {1: 3}, [], _distinct,
        block_start=lambda g, x: 40 if x == GatePhase(1, 4) else 0,
        respelled=respelled, gate_skip=4)
    assert respelled == {(0, 1): 40}
    assert kept == {(0, 2)}


# --- the walk ----------------------------------------------------------------

@needs_corpus
def test_the_row_walk_is_the_note_walk_keyed_by_row():
    sid, det, tracks, patterns, gate = _lvvp()
    res = GA.nibble_gate_row_residues(sid, det, tracks, patterns, gate)
    notes = GA.nibble_gate_note_residues(sid, det, tracks, patterns, gate)
    assert res and notes
    want: dict = {}
    for ti, track in enumerate(tracks):
        from collections import Counter
        seen = Counter()
        for pos, p in GA._orderlist_occurrences(track):
            play = seen[pos]
            seen[pos] += 1
            for r, gp in notes.get((ti, pos, play), {}).items():
                want.setdefault((p, r), set()).add(gp.residue)
    for key, got in res.items():
        if None not in got:
            assert got == want[key], key
    # Subtunes whose reload is not the gate's are marked unmodelled.
    real = GA.outer_gate_skip
    GA.outer_gate_skip = lambda s, sub: gate if sub == 0 else gate + 1
    try:
        part = GA.nibble_gate_row_residues(sid, det, tracks, patterns, gate)
    finally:
        GA.outer_gate_skip = real
    assert any(None in got for got in part.values())
    assert any(None not in got for got in part.values())


def _lvvp():
    import fidelity
    import json
    import h2g.convert as C
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Las_Vegas_Video_Poker.sid")
    got: dict = {}
    real = C.build_sng

    def build(sid, det, tracks, patterns, **kw):
        got.update(sid=sid, det=det, tracks=[list(t) for t in tracks],
                   patterns=[list(p) for p in patterns],
                   gate=kw.get("gate_skip"))
        return real(sid, det, tracks, patterns, **kw)
    C.build_sng = build
    try:
        C.convert(str(CORPUS / "Las_Vegas_Video_Poker.sid"),
                  log=lambda m: None, **opts)
    finally:
        C.build_sng = real
    return (got["sid"], got["det"], got["tracks"], got["patterns"],
            got["gate"])


@needs_corpus
def test_lvvp_gates_its_tie_rows_by_residue():
    """The corpus case: 7 rows free, 6 respelled onto the 2 blocks that fit
    (5 are wanted), 15 kept."""
    import fidelity
    import json
    from h2g.convert import convert
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Las_Vegas_Video_Poker.sid")
    lines: list = []
    convert(str(CORPUS / "Las_Vegas_Video_Poker.sid"), log=lines.append,
            **opts)
    assert any("(15 gated arpeggio phase)" in line for line in lines), lines
    assert any("13 tie row(s) on 4 legato clone(s)" in line
               for line in lines), lines
    assert any("6 tie row(s) restart the block of the residue they land on "
               "(5 block(s) laid out for them)" in line
               for line in lines), lines
    with_off = []
    convert(str(CORPUS / "Las_Vegas_Video_Poker.sid"), log=with_off.append,
            **dict(opts, tie_restart=False))
    assert not any("restart the block of the residue" in line
                   for line in with_off)
