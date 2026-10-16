"""The tie's `CMD_TONEPORTA 00` on the KEYOFF row that opens a continued event
pins the voice to its note on every rest row after it (a command persists
until another comes), so a note-rise store there lasted ONE call, not the
tick -- Game_Killer's $0A9A note at frame 641, whose 8th event read the bare
note at every frame (siddump -m1 per call: `44 34 34 ...` every 20 calls,
against `44 x10, 34 x10` in the note's own rows). `note_rise._release_pins`
puts the note's own command back on that row."""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from h2g.goatwriter import note_rise as R                    # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import CMD_TONEPORTA           # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pattern():
    return [[0, 0, 0, 0, 0, 0, 4, 10, 0xBE, 0, CMD_TONEPORTA, 0, 0xBD, 0, 8, 5]]


def test_the_pin_is_replaced_by_the_notes_command_where_a_rest_row_is_stored():
    out = _pattern()
    n = R._release_pins(out, [((0, 2), (4, 10), [(0, 3)])], {(0, 3): ((1, 0),)},
                        {(0, 2): 1})
    assert n == 1
    assert out[0][10:12] == [4, 10]


def test_nothing_changes_when_no_rest_row_of_the_run_kept_a_store():
    out = _pattern()
    assert R._release_pins(out, [((0, 2), (4, 10), [(0, 3)])], {}, {(0, 2): 1}) == 0
    assert out[0][10:12] == [CMD_TONEPORTA, 0]


def test_a_row_another_play_reaches_keeps_its_pin():
    out = _pattern()
    n = R._release_pins(out, [((0, 2), (4, 10), [(0, 3)])], {(0, 3): ((1, 0),)},
                        {(0, 2): 2})
    assert n == 0 and out[0][10:12] == [CMD_TONEPORTA, 0]


@needs_corpus
def test_game_killers_keyoff_row_after_the_seventh_note_keeps_the_vibrato():
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Game_Killer.sid")
    lines = []
    sng = C.convert(str(CORPUS / "Game_Killer.sid"), log=lines.append, **opts)
    assert any("tie pin(s) released" in line for line in lines), lines
    song = songview.parse_sng(sng)
    rows = list(S._lap_rows(song.tracks[0], song.patterns))
    # the lap's 7 notes of GT instrument 2 are 18 rows each from row 288;
    # row 414 is the KEYOFF that opens the 8th event
    p, r, _t = rows[414]
    note, instr, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
    assert note == 0xBE and instr == 0
    assert (cmd, dat) == (4, 0x0A), (cmd, dat)
