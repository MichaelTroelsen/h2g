"""A tied note casts no vote in the nibble counter's phase walks.

Opened by lvvp-gate-phase-per-note-split (6e467ff): `fixed_arp_phases` stopped
counting `CMD_TONEPORTA 00` rows in 86ac533 (a tie restarts no wavetable, so
its residue is never a block's attack), but `nibble_arp_phases` and
`nibble_gate_phases` still did. Las_Vegas_Video_Poker's GT $12, $14 and $15
(18, 20, 21) took residues 1, 0 and 0 from tie rows where every untied note
attacks on residue 3.

Measured at 0421071 (C:/t/gate-majority-counts-tied-notes): corpus byte-hash
under presets, 95 files, 6 refused in both arms, 89 compared, moved exactly
Las_Vegas_Video_Poker (a1822723fc3c -> 847cee7ec1ec); Commando unchanged. The
gate split drops from ten clones to nine and the .sng from 13816 to 13741
bytes; subtune 0's first-two-runs and per-note A/B (120 s) are identical to
the base (321 same / 0 differ, octave 12 / 0).
"""
import pathlib
import sys

import pytest

from corpus import needs_corpus
from test_nibble_gate_phase import _converted, _det

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
from h2g.goatwriter import (CMD_TONEPORTA, fixed_arp_period,   # noqa: E402
                            nibble_arp_phases, nibble_gate_phases)
from h2g.goatwriter import arpeggio as gw_arpeggio             # noqa: E402

LVVP = "Las_Vegas_Video_Poker"


def _ctx():
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    _, got = _converted(LVVP)
    sid, det = _det(LVVP)
    return sid, det, got


@needs_corpus
def test_lvvp_records_whose_only_untied_notes_attack_on_residue_3_take_it():
    sid, det, got = _ctx()
    gate = nibble_gate_phases(sid, det, got["tracks"], got["patterns"],
                              got["gate_skip"])
    assert [gate[g] for g in (18, 20, 21)] == [3, 3, 3], gate
    per = det.arp_nibble_period
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    arp = nibble_arp_phases(sid, det, got["tracks"], got["patterns"])
    assert [arp[g] for g in (18, 20, 21)] == [3 % period] * 3, arp


@needs_corpus
def test_the_old_walk_with_ties_voted_differently_on_those_records(monkeypatch):
    """Control: put the ties back (the walk yielding no command column
    match) and the three records fall off residue 3, so the test above
    reads the tie rule and not the corpus."""
    sid, det, got = _ctx()
    real = gw_arpeggio._walk_note_rows

    def untied_view(track, patterns):
        for row, cur, pat, r in real(track, patterns):
            # hide the tie from the vote: same note row, command column 0
            yield row, cur, [0] * len(pat), r

    monkeypatch.setattr(gw_arpeggio, "_walk_note_rows", untied_view)
    gate = nibble_gate_phases(sid, det, got["tracks"], got["patterns"],
                              got["gate_skip"])
    assert [gate[g] for g in (18, 20, 21)] != [3, 3, 3], gate


@needs_corpus
def test_a_walk_of_only_tied_rows_casts_no_vote_in_either_function(monkeypatch):
    sid, det, got = _ctx()
    real = gw_arpeggio._walk_note_rows

    def all_tied(track, patterns):
        for row, cur, pat, r in real(track, patterns):
            tied = list(pat)
            tied[r + 2], tied[r + 3] = CMD_TONEPORTA, 0
            yield row, cur, tied, r

    monkeypatch.setattr(gw_arpeggio, "_walk_note_rows", all_tied)
    assert nibble_arp_phases(sid, det, got["tracks"], got["patterns"]) == {}
    assert nibble_gate_phases(sid, det, got["tracks"], got["patterns"],
                              got["gate_skip"]) == {}
