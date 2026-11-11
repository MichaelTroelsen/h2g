"""A command-table rest after a releasing note opens on a KEYOFF.

Hollywood or Bust `$0599 LDA $0974,X / BMI skip / LDA $0971,X / CMP #$02 /
BNE skip / LDA $0977,X / AND #$FE / STA $D404,Y`: every event, rests included,
clears the gate when its duration counter reaches 2 -- except a note whose bit
7 (legato) is set. A note followed by a rest therefore releases two frames
before the REST begins, and ours, which turned the rest into plain hold rows,
rode the gate to the next note's hard restart: voice 1 of subtune 2 holds 22
gate frames where the original holds 10 (a 12-frame note, then a 12-frame
rest), `o14>u2 s+12` on the 12 runs that carry all 168 of the song's gate
misses (gate .97, FIDELITY.md at v0.5.659).

The first two tests are synthetic bytes and need no corpus.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.patterns import (GT_END_PATTERN, GT_KEYOFF,          # noqa: E402
                          GT_NO_NOTE, _build_raw_pattern_cmdtable)

NOTE = 0x60 + 0x30


def _pattern(note_byte: int, with_rest: bool = True, *, keyoff: bool):
    data = bytearray(0x100)
    data[0x10:0x12] = bytes([3, 6])          # duration table: 3 and 6 frames
    body = [0x00, note_byte]                 # a 3-frame note
    if with_rest:
        body.append(0x41)                    # bit 6: a 6-frame rest
    body.append(0xFF)
    data[0x40:0x40 + len(body)] = bytes(body)
    return _build_raw_pattern_cmdtable(bytes(data), 0x40, 0x10, [0] * 16, 0, 3,
                                       rest_keyoff=keyoff)


def test_rest_after_a_note_opens_on_a_keyoff():
    ev = _pattern(0x30, keyoff=True)
    assert ev == [NOTE, 0, 0, 0,
                  GT_KEYOFF, 0, 0, 0,
                  GT_NO_NOTE, 0, 0, 0,
                  GT_END_PATTERN, 0, 0, 0]


def test_off_or_legato_keeps_the_plain_hold():
    plain = [NOTE, 0, 0, 0, GT_NO_NOTE, 0, 0, 0, GT_NO_NOTE, 0, 0, 0,
             GT_END_PATTERN, 0, 0, 0]
    assert _pattern(0x30, keyoff=False) == plain
    # bit 7: the player's counter == 2 release skips the note, so the gate
    # rides the rest to its own end
    assert _pattern(0xB0, keyoff=True) == plain


def test_without_a_rest_nothing_changes():
    assert _pattern(0x30, with_rest=False, keyoff=True) == _pattern(
        0x30, with_rest=False, keyoff=False)


def test_hollywood_or_bust_rests_carry_the_keyoff():
    import json
    import fidelity
    from corpus import CORPUS
    from h2g.convert import convert
    from songview import parse_sng
    if not (CORPUS / "Hollywood_or_Bust.sid").exists():
        pytest.skip("needs the corpus")
    root = pathlib.Path(__file__).resolve().parents[2]
    opts = fidelity._preset_opts(
        json.loads((root / "presets.json").read_text(encoding="utf-8")),
        "Hollywood_or_Bust.sid")

    def keyoffs(**kw):
        sng = parse_sng(convert(str(CORPUS / "Hollywood_or_Bust.sid"),
                                log=lambda m: None, **dict(opts, **kw)))
        return sum(pat[r] == GT_KEYOFF for pat in sng.patterns
                   for r in range(0, len(pat) - 3, 4))

    assert keyoffs() > 0
    assert keyoffs(rest_keyoff=False) == 0
