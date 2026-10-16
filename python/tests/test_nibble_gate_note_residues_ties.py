"""A tied row seeds no GatePhase clone, and is never renamed to one.

`nibble_gate_note_residues` walks every note row, tied or not (its residues
feed `nibble_gate_row_residues`, which the tie placement needs), so its dict
does carry a tied row's residue. `_note_phase_split` is the consumer that turns
residues into clones, and it filters ties twice: the vote (a tied row casts
no vote, so it cannot make a residue `wanted`) and the edit (a tied row is
never renamed to a clone's number). These tests pin both on a hand-built walk
shaped exactly as `nibble_gate_note_residues` returns it: keys
(track, orderlist position, play), values {row: GatePhase}.

Removing the vote filter makes the first test fail (a clone appears from the
tie alone); removing the edit filter makes the second fail (the tied row is
renamed to the clone number).
"""
import pathlib
import sys

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
from h2g.goatwriter import arpeggio as gw_arpeggio            # noqa: E402
from h2g.goatwriter.arpeggio import GatePhase                 # noqa: E402
from h2g.patterns import CMD_TONEPORTA                        # noqa: E402

PERIOD = 4
MAJOR = GatePhase(3, PERIOD)


def _split(pattern_rows, residue_of_row):
    """Run the split on one track playing pattern 0 once, record 1 only."""
    pat = []
    for note, instr, cmd, arg in pattern_rows:
        pat += [note, instr, cmd, arg]
    pat += [0xFF, 0, 0, 0]
    residues = {(0, 0, 0): {r: GatePhase(res, PERIOD)
                            for r, res in residue_of_row.items()}}
    return gw_arpeggio._note_phase_split(
        [[0]], [pat], residues, {1: MAJOR}, {1}, 2, None, "tie test", None,
        factor=None)


def test_a_tied_minority_residue_seeds_no_gate_clone():
    """Row 0 attacks on the majority residue 3; row 1 is a TIE on residue 1
    (a minority only the tie shows); row 2 is an untied note on residue 2,
    the one minority that should earn a clone. The tie must not add residue
    1 to the wanted set: exactly one clone, for residue 2."""
    got = _split([(0x60, 1, 0, 0),
                  (0x61, 0, CMD_TONEPORTA, 0),
                  (0x62, 0, 0, 0)],
                 {0: 3, 1: 1, 2: 2})
    assert got is not None
    assert got.clones == [(1, 2, GatePhase(2, PERIOD))], got.clones
    assert got.edits == {0: {2: (0, 2)}}, got.edits


def test_a_tied_row_is_not_renamed_to_a_clone_it_does_not_own():
    """An untied note on residue 1 (row 1) wants a clone. A tie on residue 1
    (row 2, naming instrument 1 outright) sits on the same residue, but it
    restarts no wavetable, so it keeps its spelling: only row 1 is edited to
    the clone's number 2."""
    got = _split([(0x60, 1, 0, 0),
                  (0x61, 0, 0, 0),
                  (0x62, 1, CMD_TONEPORTA, 0)],
                 {0: 3, 1: 1, 2: 1})
    assert got is not None
    assert got.clones == [(1, 2, GatePhase(1, PERIOD))], got.clones
    assert got.edits == {0: {1: (0, 2)}}, got.edits
