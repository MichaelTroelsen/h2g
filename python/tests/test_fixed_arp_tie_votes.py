"""`fixed_arp_phases` votes only the notes that restart a wavetable.

A row carrying `CMD_TONEPORTA 00` (a tie) skips the new-note init that loads
the waveptr -- player.s:832-835 `cmp #TONEPORTA / beq mt_nonewnoteinit`
ahead of `lda mt_inswaveptr-1,y`, gplay.c:354 -- so the block runs on from
the note before and the tie's residue is never a block's attack. Through
v0.5.513 ties voted in every record's majority; `pitch_seq_phases` and
`_note_phase_split` already left them out.

The corpus A/B of the untied-only vote (tie-votes-in-fixed-arp-phases, under
presets via `fidelity._preset_opts`): converted 89, refused 6, compared 95,
moved 0. Three records change residue -- Chimera GT 5 and GT 8 (0 -> 2) and
Game_Killer GT 8 (5 -> 1) -- and none of their blocks reads it.
"""
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.detect import detect                                 # noqa: E402
from h2g.goatwriter import arpeggio as A                      # noqa: E402
from h2g.goatwriter import primitives as P                    # noqa: E402
from h2g.goatwriter import tempo as T                         # noqa: E402
from h2g.goatwriter.constants import CMD_TONEPORTA, GT_FIRST_NOTE  # noqa: E402
from h2g.sidfile import load_sid                              # noqa: E402

NOTE = GT_FIRST_NOTE + 24
END = [0xFF, 0x00, 0x00, 0x00]


@pytest.fixture
def parity_counter(monkeypatch):
    """A `$01` mask counting from 0 on the attack of row 0, one frame a row:
    row `k`'s residue is `k % 2`."""
    monkeypatch.setattr(A, "fixed_arp_counter_base", lambda sid, det: 0)
    monkeypatch.setattr(A, "fixed_arp_first_fetch", lambda sid, det: 0)
    monkeypatch.setattr(P, "fixed_arp_mask", lambda sid, det: (0x01,))
    monkeypatch.setattr(T, "find_song_speeds", lambda sid, det: SimpleNamespace(
        frames_for=lambda g: 1))
    return SimpleNamespace(subtunes=1)


def _rows(*rows):
    return [b for r in rows for b in r] + END


def test_a_tied_note_casts_no_vote(parity_counter):
    """Instrument 1 attacks once on residue 0 and is tied into twice on
    residue 1: the tie-inclusive majority was 1, the block's attack is 0."""
    pattern = _rows([NOTE, 1, 0, 0],                     # row 0: attack
                    [NOTE + 2, 0, CMD_TONEPORTA, 0x00],  # row 1: tie
                    [0x00, 0, 0, 0],
                    [NOTE + 4, 0, CMD_TONEPORTA, 0x00])  # row 3: tie
    tracks = [[0, 0xFF, 0x00], [], []]
    assert A.fixed_arp_phases(parity_counter, None, tracks, [pattern]) == {1: 0}


def test_a_record_named_only_on_tie_rows_gets_no_residue(parity_counter):
    """Instrument 2 is named on a tie row only: its block never restarts, so
    it casts no vote and takes no residue (a reader falls back to 0)."""
    pattern = _rows([NOTE, 1, 0, 0],
                    [NOTE + 2, 2, CMD_TONEPORTA, 0x00],
                    [NOTE + 4, 0, CMD_TONEPORTA, 0x00])
    tracks = [[0, 0xFF, 0x00], [], []]
    assert A.fixed_arp_phases(parity_counter, None, tracks, [pattern]) == {1: 0}


def test_the_instrument_stays_sticky_across_a_tie(parity_counter):
    """Instrument 1 is named on a row with no note; row 1's tie (residue 1)
    and row 3's (residue 1) are skipped, and row 2's plain note -- still
    under instrument 1 -- is the only vote: residue 0, where the
    tie-inclusive majority was 1."""
    pattern = _rows([0x00, 1, 0, 0],
                    [NOTE, 0, CMD_TONEPORTA, 0x00],
                    [NOTE + 2, 0, 0, 0],
                    [NOTE + 4, 0, CMD_TONEPORTA, 0x00])
    tracks = [[0, 0xFF, 0x00], [], []]
    assert A.fixed_arp_phases(parity_counter, None, tracks, [pattern]) == {1: 0}


def _build_inputs(name):
    """(sid, det, tracks, patterns) as `build_sng` receives them under the
    shipped preset."""
    import fidelity
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, name)
    got = {}
    real = C.build_sng

    def spy(sid, det, tracks, patterns, **kw):
        got["tracks"] = [list(t) for t in tracks]
        got["patterns"] = [list(p) for p in patterns]
        return real(sid, det, tracks, patterns, **kw)
    C.build_sng = spy
    try:
        C.convert(str(CORPUS / name), log=lambda *a, **k: None, **opts)
    finally:
        C.build_sng = real
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, lambda *a, **k: None), got["tracks"], got["patterns"]


@needs_corpus
def test_chimeras_tie_row_records_take_their_attacks_residue():
    """GT 5 ($0060) and GT 8 ($BF00) play almost only tie rows. Their tie
    rows spread evenly over the eight residues (198 x7 and 193; 60/48
    alternating), so the tie-inclusive majority was the lowest, 0. Every
    untied attack of GT 5 (6 of 6) and the plurality of GT 8's (16 of 52)
    is on residue 2 -- the residue every $0060/$BF00 chain of the original
    attacks on (tie-chain-counter-base, siddump at -t 180)."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sid, det, tracks, patterns = _build_inputs("Chimera.sid")
    phases = A.fixed_arp_phases(sid, det, tracks, patterns)
    assert (phases.get(5), phases.get(8)) == (2, 2), phases


@needs_corpus
def test_game_killers_record_8_takes_the_lower_of_its_untied_tie():
    """Game_Killer GT 8: residues 1 and 5 tie 97:97 among its untied notes
    and the lower wins; the four tie rows on residue 5 took it to 5."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sid, det, tracks, patterns = _build_inputs("Game_Killer.sid")
    phases = A.fixed_arp_phases(sid, det, tracks, patterns)
    assert phases.get(8) == 1, phases
