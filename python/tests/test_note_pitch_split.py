"""A wave-program record played at notes whose blocks differ gets one clone
per note class (`goatwriter.note_pitch_split`).

The player's `>= $80` opcode writes the frequency HIGH byte only, so the pitch
it sounds is `hi:lo(note)`; Go_Go_Dash's drum record 3 (`81 5E 81 13 81 08`)
sounds `0751 0459 0836...` on its last frame, nine of its seventeen notes on
one side of the semitone the traced tuning rounds to and the rest on the
other. One wavetable names one note, so it was right for 136 of the record's
224 hits (instr 92.3 -> 95.7 with the split, heard.py at v0.5.670).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import note_pitch_split as nps           # noqa: E402
from h2g.goatwriter.note_pitch_split import (MAJOR, NotePitch,  # noqa: E402
                                             note_classes, note_residues)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _blocks(table):
    """A `blocks(keys)` over {(record, note or None): block}."""
    def blocks(keys):
        return {k: table[(k[0], None if k[1] is None else k[1].note)]
                for k in keys}
    return blocks


def _shape(left, right):
    return ((0x09, 0x41, 0xFF), (0x00, right, 0x00)) if left else None


def test_the_heaviest_class_keeps_the_record_and_the_minority_gets_a_clone():
    a, b = _shape(1, 0xB0), _shape(1, 0xA0)
    table = {(3, None): a, (3, 40): a, (3, 41): a, (3, 50): b}
    got = note_classes({3: {40: 100, 41: 30, 50: 40}}, 0, 5, _blocks(table))
    assert got == {3: {50: NotePitch(50)}}


def test_a_class_under_the_play_floor_stays_on_the_record():
    a, b = _shape(1, 0xB0), _shape(1, 0xA0)
    table = {(3, None): a, (3, 40): a, (3, 50): b}
    assert note_classes({3: {40: 100, 50: nps.MIN_PLAYS - 1}}, 0, 5,
                        _blocks(table)) == {}
    assert note_classes({3: {40: 100, 50: nps.MIN_PLAYS}}, 0, 5,
                        _blocks(table)) == {3: {50: NotePitch(50)}}


def test_a_block_that_changes_what_the_record_does_is_not_cloned():
    own = ((0x09, 0x41, 0xFF), (0x00, 0xB0, 0x00))
    portamento = ((0x09, 0x02, 0xFF), (0x00, 0x05, 0x00))     # left differs
    table = {(3, None): own, (3, 40): own, (3, 50): portamento}
    assert note_classes({3: {40: 100, 50: 60}}, 0, 5, _blocks(table)) == {}


def test_notes_sharing_a_block_share_one_class():
    a, b = _shape(1, 0xB0), _shape(1, 0xA0)
    table = {(3, None): a, (3, 40): a, (3, 50): b, (3, 51): b}
    got = note_classes({3: {40: 100, 50: 20, 51: 40}}, 0, 5, _blocks(table))
    assert got == {3: {50: NotePitch(51), 51: NotePitch(51)}}


def test_the_walk_names_each_untied_note_by_its_class():
    # One track, one pattern: rows are (note, instrument, command, data).
    pat = [0x60 + 40, 3, 0, 0,
           0x60 + 50, 0, 0, 0,
           0x60 + 50, 0, 0x03, 0,          # tied: no residue
           0x60 + 12, 0, 0, 0,             # a note the record has no class for
           0xFF, 0, 0, 0]
    track = [0, 0xFF, 0]
    res = note_residues([track], [pat], {3: {50: NotePitch(50)}})
    assert res == {(0, 0, 0): {0: MAJOR, 1: NotePitch(50), 3: MAJOR}}


@needs_corpus
def test_go_go_dash_record_3_is_split_and_the_option_off_is_not():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Go_Go_Dash.sid")
    lines = []
    split = convert(str(CORPUS / "Go_Go_Dash.sid"), log=lines.append, **opts)
    assert any("note pitch split: 2 clone(s)" in line for line in lines)
    nps.ENABLED = False
    try:
        lines.clear()
        plain = convert(str(CORPUS / "Go_Go_Dash.sid"), log=lines.append,
                        **opts)
    finally:
        nps.ENABLED = True
    assert not any("note pitch split" in line for line in lines)
    assert split != plain
