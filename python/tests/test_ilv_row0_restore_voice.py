"""ILV "restore": an `A` copy for a majority note whose own command column is
taken may use another voice's empty cell on the SAME row, row 0 included.

Sun_Never_Shines' first note sits on row 0 with the tempo in its column; its
restore used to wait for row 1 (1 late, 1 row on the wrong passband).

SABOTAGE TARGET: make the at-note order `[ptr[2]]` again (filters.py,
`_ilv_routing_walk`) and both tests here fail.
"""
import json
import sys
from pathlib import Path

from corpus import CORPUS, needs_corpus  # noqa: F401
from h2g.convert import convert
from h2g.goatwriter import CMD_SETFILTERPTR
from test_ilv_passband_restore import _BASE, _MAJ, _groups, _pattern, _restore, _walk

REPO = Path(__file__).resolve().parents[2]


def test_a_restore_whose_own_column_is_taken_uses_another_voices_row_0():
    """SABOTAGE TARGET: restrict the at-note order to the note's own voice
    (`[ptr[2]]`) and the copy is late again (Sun_Never_Shines' last row).

    The note's voice holds the tempo on row 0, but voices 1 and 2 have empty
    row-0 cells; an `A` there runs after the note init on the same tick."""
    tempo = (0x0F, 5)
    patterns = [_pattern({0: (0x90, _MAJ) + tempo}), _pattern({}),
                _pattern({})]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    plan, stats = _walk(patterns, _groups(patterns, tracks), "restore",
                        _restore())
    assert plan == {(1, 0): {0: (CMD_SETFILTERPTR, _BASE)}}, plan
    assert (stats["restore_unplaceable"], stats["late_restores"],
            stats["passband_late"]) == (0, 0, 0), stats


@needs_corpus
def test_sun_restore_lands_on_the_notes_own_row():
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = F._preset_opts(doc, "Sun_Never_Shines.sid")
    lines = []
    convert(str(CORPUS / "Sun_Never_Shines.sid"), log=lines.append, **opts)
    line = next(m for m in lines if m.startswith("ILV filter routing"))
    assert ("1 passband restore(s), 0 late, 0 unplaceable at the note, "
            "0 row(s) on the wrong passband") in line, line
