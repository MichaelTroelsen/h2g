"""The bit-$80 drum's hit on a rest of its record (`goatwriter.sfx_rest_click`).

Thundercats' sfx block writes `$81` to `$D412` absolutely, past the gate mask
a bit-6 rest sets, one frame into the rest (the rest's fetch zeroes the
counter, `$EDCC-$EDD1`): a gate edge under the rest's ADSR `$0000`, which a
Goattracker KEYOFF masks. These pin the program's lattice, the row rewrite and
what qualifies, and the conversion that ships it.
"""
import json
import os

import pytest

from h2g.goatwriter.constants import (CMD_SETAD, CMD_SETSR, CMD_TONEPORTA,
                                      GT_KEYOFF, GT_REST)
from h2g.goatwriter.drums import _sfx_drum_entries
from h2g.goatwriter.sfx_rest_click import (click_rests,
                                           sfx_rest_click_entries)

CORPUS = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"
PRESETS = os.path.join(os.path.dirname(__file__), "..", "..", "presets.json")

D2, E2 = 0x60 + 27, 0x60 + 28        # GT note bytes
DRUM, CLONE, OTHER = 1, 16, 2


@pytest.mark.parametrize("m", [1, 2, 3])
@pytest.mark.parametrize("period", [6, 8])
def test_the_click_program_is_the_drums_lattice_with_the_gate_off(m, period):
    """Same entries, same delays, same loop -- so the hit lands on the rest's
    second frame exactly as the drum's lands on a note's -- with every held
    frame `$E8` (waveform `$08`, gate off) instead of the record's own
    waveform with the gate on, so each `$81` is a gate EDGE."""
    left, right, loop = sfx_rest_click_entries(0x48, period, m)
    dl, dr, dloop = _sfx_drum_entries(0x08, 0x48, period, m)
    assert (right, loop) == (dr, dloop)
    assert len(left) == len(dl)
    for a, b in zip(left, dl):
        assert a == (0xE8 if b == 0xE9 else b)
    assert 0xE8 in left and 0xE9 not in left
    assert left[loop] == 0x81          # the loop opens on the hit


def _row(note, ins=0, cmd=0, data=0):
    return [note, ins, cmd, data]


def _pattern(*rows):
    return [b for r in rows for b in r] + [0xFF, 0, 0, 0]


def test_a_drum_rest_becomes_a_note_on_the_clone():
    pat = _pattern(_row(D2, DRUM), _row(GT_REST),
                   _row(GT_KEYOFF, 0, CMD_SETSR, 0), _row(GT_REST, 0, CMD_SETAD, 0),
                   _row(E2), _row(GT_REST))
    (new,), placed, used = click_rests([pat], {}, {DRUM: CLONE})
    assert (placed, used) == (1, {DRUM})
    # the previous note's pitch, so the $08 frames restore its frequency
    assert new[8:12] == [D2, CLONE, 0, 0]
    # the envelope writes are the clone's own $0000 now
    assert new[12:16] == [GT_REST, 0, 0, 0]
    # and the next note names the drum again
    assert new[16:20] == [E2, DRUM, 0, 0]
    assert pat[8] == GT_KEYOFF, "changed patterns are copies"


@pytest.mark.parametrize("why,rows", [
    ("no envelope zeroing on the rest",
     [_row(D2, DRUM), _row(GT_KEYOFF), _row(E2)]),
    ("rest runs to the pattern's end",
     [_row(D2, DRUM), _row(GT_KEYOFF, 0, CMD_SETSR, 0), _row(GT_REST)]),
    ("toneportamento after it keeps the clone's program",
     [_row(D2, DRUM), _row(GT_KEYOFF, 0, CMD_SETSR, 0),
      _row(E2, 0, CMD_TONEPORTA, 1)]),
    ("live instrument is not a drum",
     [_row(D2, OTHER), _row(GT_KEYOFF, 0, CMD_SETSR, 0), _row(E2)]),
    ("no note before it in the pattern",
     [_row(GT_KEYOFF, 0, CMD_SETSR, 0), _row(E2, DRUM)]),
])
def test_what_does_not_qualify_is_left_alone(why, rows):
    pat = _pattern(*rows)
    (new,), placed, _used = click_rests([pat], {0: {DRUM}}, {DRUM: CLONE})
    assert placed == 0 and new is pat, why


def test_an_unknown_entry_instrument_is_left_alone():
    pat = _pattern(_row(GT_REST), _row(D2), _row(GT_KEYOFF, 0, CMD_SETSR, 0),
                   _row(E2))
    (new,), placed, _ = click_rests([pat], {0: {DRUM, OTHER}}, {DRUM: CLONE})
    assert placed == 0 and new is pat


@pytest.mark.skipif(not os.path.exists(os.path.join(CORPUS, "Thundercats.sid"))
                    or not os.path.exists(PRESETS),
                    reason="corpus or presets.json absent")
def test_thundercats_ships_the_click_on_its_drum_record_only():
    import songview
    from fidelity import _preset_opts
    from h2g.convert import convert
    doc = json.load(open(PRESETS))
    opts = _preset_opts(doc, "Thundercats.sid")
    assert opts.get("sfx_drum") and opts.get("rest_envelope_silence")
    song = songview.parse_sng(convert(os.path.join(CORPUS, "Thundercats.sid"),
                                      log=lambda m: None, **opts))
    clones = [i for i in song.instruments
              if (i.ad, i.sr, i.firstwave) == (0, 0, 0x08)
              and i.name == "02:00-01-80"]
    assert len(clones) == 1, "one clone, of record $02 (effect $80)"
    c = clones[0]
    w = song.tables["WTBL"]
    block = w[c.wave_ptr - 1:]
    assert (0x81, 0xC9) in block[:block.index(next(e for e in block
                                                   if e[0] == 0xFF))]
    # record $0E (effect $A0) plays on voice 1, so its hit belongs to voice 3
    # and no clone of it is made
    assert not any(i.name.startswith("0E:") and (i.ad, i.sr) == (0, 0)
                   for i in song.instruments)
    named = sum(1 for p in song.patterns for k in range(1, len(p), 4)
                if p[k] == c.number)
    assert named == 2


@pytest.mark.skipif(not os.path.exists(os.path.join(CORPUS, "Thundercats.sid")),
                    reason="corpus absent")
def test_without_sfx_drum_nothing_is_clicked():
    from h2g.convert import convert
    import songview
    song = songview.parse_sng(convert(os.path.join(CORPUS, "Thundercats.sid"),
                                      log=lambda m: None, fmt="gts5",
                                      rest_keyoff=True, status_bit6=True,
                                      rest_envelope_silence=True))
    assert not any((i.ad, i.sr, i.firstwave) == (0, 0, 0x08)
                   for i in song.instruments)
