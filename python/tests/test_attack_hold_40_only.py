"""A short note on an exactly-`$40` record keeps its fixed pitch to its end.

`_attack_hold_records` named only `$44` records (Sanxion 13), so the held-attack
program -- the fixed pitch looping instead of the played note coming back --
never existed for a record that is exactly `$40` (`fixed_attack_only`,
Lightforce 6). The player's gate is the same one: the `$40` handler yields the
frequency to a duration-gated vibrato (`_fixed_pitch_yield_field`), and a note
shorter than the gate is never written again.

No corpus note qualifies -- Lightforce plays record 6 only as four 16-row notes
(and Knucklebusters' record 13 only as notes that run on into the next) -- so
the property is shown on a copy of Lightforce whose record-6 pattern (pattern
10, file bytes `8F 06 1A 0F 1A 0F 1A 0F 1A FF`) has its waits cut. Original,
siddump-rt -m1, voice 3 from frame 897, wait 2 (measured at 7afbe58):

    04E2 09C4 x9 04E2 09C4     the note keeps `$09C4` to the next attack

and the conversion before this change: `04E2 09C5 x4 04E2 04E2 04F4 0506 ...`
(the played note comes back and Goattracker's vibrato runs). After: `04E2
09C5 x9 04E2 09C5`. Frames 0-11 of the 16 onsets agree within 2 units 104 of
192 before, 192 of 192 after (wait 1: 160 -> 192).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import goatwriter as G                              # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import note_passes as NP                 # noqa: E402

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
NOTE = 0xA6
PATTERN = bytes.fromhex("8f061a0f1a0f1a0f1aff")


def _det(name):
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


def _block(i, hold, multiplier=1):
    sid, det = _det("Lightforce")
    return G._wavetable_entries(sid, det, i, True, G.FORMAT_GTS5,
                                [(0, 0)] * 16, multiplier, start=7,
                                budget=200, two_stage=True,
                                hold_attack=hold)


def _short_lightforce(tmp_path, wait):
    raw = (CORPUS / "Lightforce.sid").read_bytes()
    assert raw.count(PATTERN) == 1
    new = bytes([0x80 | wait, 6, 0x1A] + [wait, 0x1A] * 3 + [0xFF])
    path = tmp_path / "LightforceShort.sid"
    path.write_bytes(raw.replace(PATTERN, new))
    return path


def _convert(path):
    opts = dict(fidelity._preset_opts(json.loads(PRESETS.read_text()),
                                      "Lightforce.sid"))
    opts.pop("pack", None)
    log = []
    sng = convert(str(path), log=log.append, **opts)
    return sng, "\n".join(map(str, log))


@needs_corpus
def test_a_40_only_record_is_an_attack_hold_record():
    sid, det = _det("Lightforce")
    got = NP._attack_hold_records(sid, det, det.instr_used, 1, True, True)
    assert 6 in got
    # Every record named is either `$44` with a vibrato byte or exactly $40.
    for i in got:
        effect = sid.data[det.instr_start + i * det.instr_stride + 7]
        assert (effect & 0x44) == 0x44 or effect == 0x40, (i, effect)
        assert sid.data[det.instr_start + i * det.instr_stride
                        + det.vibrato_offset]


@needs_corpus
def test_the_44_record_is_still_named():
    sid, det = _det("Sanxion")
    assert 13 in NP._attack_hold_records(sid, det, det.instr_used, 1, True,
                                         True)


@needs_corpus
def test_a_40_only_record_without_the_options_is_not_named():
    sid, det = _det("Lightforce")
    assert 6 not in NP._attack_hold_records(sid, det, det.instr_used, 1,
                                            True, False)
    assert NP._attack_hold_records(sid, det, det.instr_used, 1, False,
                                   True) == []


@needs_corpus
def test_held_block_loops_on_the_fixed_note_where_the_plain_one_ends():
    """The held program does not end on the played note: its last entry
    jumps back to the entry that writes the fixed note."""
    plain = _block(6, False)
    held = _block(6, True)
    assert plain[1][-2] == 0x00 and plain[0][-1] == 0xFF
    assert held != plain
    assert held[1][-2] == NOTE
    assert held[0][-1] == 0xFF
    # Jump target: absolute position of the looping entry (start 7, 1-based).
    assert held[1][-1] == 7 + len(held[0]) - 2


@needs_corpus
def test_lightforce_as_shipped_places_nothing():
    """Every record-6 note is 16 rows, past the gate of 3: no corpus byte
    moves, which the corpus byte-hash under presets confirmed (95 files, 6
    refused, 89 compared, 0 moved at 7afbe58)."""
    _, log = _convert(CORPUS / "Lightforce.sid")
    assert "Attack pitch held" not in log


@needs_corpus
@pytest.mark.parametrize("wait", [1, 2])
def test_short_record_6_notes_get_the_held_program(tmp_path, wait):
    sng, log = _convert(_short_lightforce(tmp_path, wait))
    assert "Attack pitch held.......: 4 short note(s)" in log, log
    base = _convert(CORPUS / "Lightforce.sid")[0]
    assert sng != base


@needs_corpus
def test_a_long_record_6_note_is_left_alone(tmp_path):
    """Wait 4 is 5 rows, past the gate of 3: the gate opens and the vibrato
    starts from the played note, which is what the restore block says."""
    _, log = _convert(_short_lightforce(tmp_path, 4))
    assert "Attack pitch held" not in log, log


@needs_corpus
@pytest.mark.parametrize("effect", [0x41, 0x60, 0x48])
def test_a_record_with_a_second_bit_is_not_named(effect):
    """Only exactly `$40` has a measured emission (`fixed_attack_only`);
    Delta_Mix-E-Load 23 (`$60`) and Trans-Atlantic 15 (`$41`) are not seen
    playing, so a second bit declines."""
    sid, det = _det("Lightforce")
    sid.data = bytearray(sid.data)
    sid.data[det.instr_start + 6 * det.instr_stride + 7] = effect
    assert 6 not in NP._attack_hold_records(sid, det, det.instr_used, 1,
                                            True, True)
