"""`fixed_arp_phases` leaves out every `CMD_TONEPORTA` row, not only the tie.

A slide (`CMD_TONEPORTA` with a nonzero speed) skips the new-note init that
loads the waveptr in both players, as a tie does (player.s `cmp #TONEPORTA /
beq mt_nonewnoteinit`; gplay.c `newcommand != CMD_TONEPORTA`), so its residue
is never a block's attack. The vote therefore skips the whole command, whatever
its parameter. Synthetic only: the converter emits no slide on a walked row in
the corpus, so the corpus byte-hash is expected to move nothing.
"""
import pathlib
import sys
from types import SimpleNamespace

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter import arpeggio as A                      # noqa: E402
from h2g.goatwriter import primitives as P                    # noqa: E402
from h2g.goatwriter import tempo as T                         # noqa: E402
from h2g.goatwriter.constants import CMD_TONEPORTA, GT_FIRST_NOTE  # noqa: E402

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


def test_a_slide_with_a_speed_casts_no_vote(parity_counter):
    """Instrument 1 attacks once on residue 0 (row 0) and is slid into twice
    on residue 1 (rows 1 and 3, `CMD_TONEPORTA $10`): the slides must not vote,
    so the only vote is residue 0."""
    pattern = _rows([NOTE, 1, 0, 0],
                    [NOTE + 2, 0, CMD_TONEPORTA, 0x10],
                    [0x00, 0, 0, 0],
                    [NOTE + 4, 0, CMD_TONEPORTA, 0x10])
    tracks = [[0, 0xFF, 0x00], [], []]
    assert A.fixed_arp_phases(parity_counter, None, tracks, [pattern]) == {1: 0}


def test_a_tie_and_a_slide_both_cast_no_vote(parity_counter):
    """Mixed tie (`$00`) and slide (`$10`) rows on residue 1 leave instrument
    1 with only its residue-0 attack."""
    pattern = _rows([NOTE, 1, 0, 0],
                    [NOTE + 2, 0, CMD_TONEPORTA, 0x00],
                    [NOTE + 4, 0, CMD_TONEPORTA, 0x10])
    tracks = [[0, 0xFF, 0x00], [], []]
    assert A.fixed_arp_phases(parity_counter, None, tracks, [pattern]) == {1: 0}
