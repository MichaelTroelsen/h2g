"""`regrid_unshare_rest`: voice 0 gets its own copy of a rest-only pattern it
shares with another voice, so `regrid`'s compensation can be paid during a long
voice-0 rest.

`regrid_tempos` writes only into patterns voice 0 ALONE plays (`exclusive`), so
a rest pattern all three voices open on carried nothing. Nineteen (aud 0.8885,
weakest 8 s starting at second 119): voice 0 plays shared pattern 0 (32 rows)
for 21 s, the original's 3.0268-frame row accrues ~9 frames in that time, ours
delivers none, and the next exclusive pattern repays it in one 24-call burst
(attack lag ours-original 6 -> -3 -> +6 frames against one global audio lag).
"""
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO                      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_KEYOFF, GT_REST,  # noqa: E402
                          _is_rest_only, regrid_tempos)

ROOT = pathlib.Path(__file__).resolve().parents[2]
D = 0.0268                                   # frames a row owed (Nineteen)


def _notes(rows):
    return [0x30, 1, 0, 0] * rows + [GT_END_PATTERN, 0, 0, 0]


def _rest(rows):
    out = [GT_KEYOFF, 0, CMD_SETTEMPO, 3] + [GT_REST, 0, 0, 0] * (rows - 1)
    return out + [GT_END_PATTERN, 0, 0, 0]


def _case():
    """Voice 0: notes (1), rest x6 (0), notes (2). Voices 1 and 2 open on the
    same rest pattern 0 and then play notes of their own."""
    pats = [_rest(32), _notes(64), _notes(64), _notes(32)]
    tracks = [[1, 0xD5, 0, 2, 0xFF, 0], [0, 3, 0xFF, 0], [0, 3, 0xFF, 0]]
    return pats, tracks


def _sets(pat, base=3):
    return sum(1 for r in range(len(pat) // 4)
               if pat[r * 4 + 2] == CMD_SETTEMPO and pat[r * 4 + 3] == base + 1)


def test_rest_only_is_recognised():
    assert _is_rest_only(_rest(32))
    assert not _is_rest_only(_notes(32))
    assert not _is_rest_only([GT_END_PATTERN, 0, 0, 0])          # no rows at all
    assert not _is_rest_only([GT_REST, 1, 0, 0, GT_END_PATTERN, 0, 0, 0])


def test_off_by_default_leaves_a_shared_rest_pattern_unpaid():
    pats, tracks = _case()
    before = copy.deepcopy(pats)
    regrid_tempos(pats, tracks, [3], [D], 1, per_play=True, full_debt=True)
    assert tracks[0][2] == 0 and len(pats) == 4
    assert pats[0] == before[0]                       # shared: nothing written


def test_voice_zero_gets_a_private_rest_copy_that_pays():
    pats, tracks = _case()
    orig_rest = list(pats[0])
    regrid_tempos(pats, tracks, [3], [D], 1, per_play=True, full_debt=True,
                  unshare_rest=True)
    assert len(pats) == 5
    assert tracks[0] == [1, 0xD5, 4, 2, 0xFF, 0]      # only voice 0 repointed
    assert tracks[1] == [0, 3, 0xFF, 0] and tracks[2] == [0, 3, 0xFF, 0]
    assert pats[0] == orig_rest                       # the shared one untouched
    assert _sets(pats[4]) >= 1                        # the copy carries a pair
    assert pats[4][0:4] == orig_rest[0:4]             # row 0 clock kept


def test_a_note_bearing_shared_pattern_is_not_copied():
    pats = [_notes(32), _notes(64)]
    tracks = [[0, 1, 0xFF, 0], [0, 0xFF, 0], [0xFF, 0]]
    regrid_tempos(pats, tracks, [3], [D], 1, per_play=True, full_debt=True,
                  unshare_rest=True)
    assert len(pats) == 2 and tracks[0][0] == 0


def test_the_pattern_budget_is_respected():
    from h2g.patterns import MAX_PATTERNS
    pats, tracks = _case()
    pats += [_notes(8)] * (MAX_PATTERNS - len(pats))
    regrid_tempos(pats, tracks, [3], [D], 1, per_play=True, full_debt=True,
                  unshare_rest=True)
    assert len(pats) == MAX_PATTERNS and tracks[0][2] == 0


@needs_corpus
def test_nineteen_pays_into_its_voice_zero_rest():
    from h2g.convert import convert
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    import fidelity                                         # noqa: PLC0415
    opts = fidelity._preset_opts(doc, "Nineteen.sid")
    opts["regrid_unshare_rest"] = True
    logs = []
    got = convert(str(CORPUS / "Nineteen.sid"), log=logs.append, **opts)
    opts["regrid_unshare_rest"] = False
    base = convert(str(CORPUS / "Nineteen.sid"), log=lambda m: None, **opts)
    assert got != base
    line = next(m for m in logs if m.startswith("Re-grid"))
    assert " in 21 pattern(s)" in line, line


def test_only_nineteen_ships_the_option():
    import fidelity                                         # noqa: PLC0415
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    on = sorted(name for name in doc["songs"]
                if fidelity._preset_opts(doc, name).get("regrid_unshare_rest"))
    assert on == ["Nineteen.sid"]
