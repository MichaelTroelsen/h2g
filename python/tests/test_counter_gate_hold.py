"""Effect bit $40's fixed attack pitch stands until a counter vibrato gate opens.

The `$40` handler hands the frequency to the vibrato once its countdown runs
out on a record whose vibrato byte is set (`_fixed_pitch_yield_field`: `LDA
field,Y / BNE out` skips the `LDA note,X` restore), and a counter (dialect A)
vibrato does not write until frame `gate`. Nothing writes in between, so the
original holds the fixed pitch to frame `gate` and the vibrato then runs from
the played note -- a pure wavetable form: hold, then restore the note on the
gate's own call (`goatwriter._counter_gate_restore_call`).

Measured on the originals (siddump -t180, onsets whose frame 1 is the fixed
pitch, C:/t/counter-gate-fixed-attack-holds-to-the-g, 2026-10-03): Nemesis
record 0 (gate 3) leaves D#5 on frame 3 for all 58 such notes, where the
conversion left it on frame 2; Wiz record 8 (gate 4) leaves A-5 on frame 4
for all 123, where the conversion left it on frame 2. After this change both
conversions leave it on the original's frame (58 and 59 + 64).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import json

import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import detect
from h2g.goatwriter import (_counter_gate_restore_call, _effect_call_list,
                            _two_stage_entries)
from h2g.sidfile import load_sid
from test_call_rate import wave_timeline

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _notes_by_call(left, right, calls=40):
    """The note byte current on each call 1..calls (index 0 is call 1)."""
    return [note for _, _, note in wave_timeline(left, right, first=1,
                                                 calls=calls)]


@pytest.mark.parametrize("multiplier", [1, 2, 3])
@pytest.mark.parametrize("written", [False, True])
@pytest.mark.parametrize("budget", [12, 8])
def test_the_played_note_comes_back_on_the_restore_call(multiplier, written,
                                                        budget):
    """Through the gplay.c transcription: the fixed note is current on every
    call from the attack's first to `restore_call - 1`, and the played note
    (`.sng` `$00`) on `restore_call` itself -- spelled out where the budget
    allows and folded into delays where it does not."""
    fixed = 0xBF
    plain = _two_stage_entries(0x41, 0x21, 1, multiplier, attack_note=fixed,
                               budget=budget, written=written)
    plain_end = len(_notes_by_call(*plain)) - _notes_by_call(
        *plain)[::-1].index(fixed)               # last call on the fixed note
    held = folded = 0
    for restore in range(2, 40):
        left, right = _two_stage_entries(0x41, 0x21, 1, multiplier,
                                         attack_note=fixed, budget=budget,
                                         written=written,
                                         restore_call=restore)
        assert len(left) <= budget
        if (left, right) == plain:
            # Not held: the attack already reaches the gate, or the hold
            # does not fit beside the lead.
            continue
        assert restore > plain_end + 1, (restore, plain_end)
        held += 1
        folded += any(v <= 0x0F for v in left)
        notes = _notes_by_call(left, right)
        first = notes.index(fixed) + 1           # the call the attack starts
        assert all(n == fixed for n in notes[first - 1:restore - 1]), (
            restore, notes[:restore])
        assert notes[restore - 1] == 0x00, (restore, notes[:restore + 1])
    assert held, "no restore_call produced a held block"
    if budget == 8 and multiplier == 1:
        assert folded, "the small budget never folded the hold into a delay"


def test_unchanged_where_the_attack_already_reaches_the_gate():
    """A restore call inside the attack stage -- I_Ball record 13's six
    frames against gate 4 -- leaves the block as it was."""
    plain = _two_stage_entries(0x41, 0x81, 6, 1, attack_note=0xC5)
    for restore in range(0, 9):
        assert _two_stage_entries(0x41, 0x81, 6, 1, attack_note=0xC5,
                                  restore_call=restore) == plain
    assert _two_stage_entries(0x41, 0x81, 6, 1, attack_note=0xC5,
                              restore_call=None) == plain


def test_no_fixed_pitch_no_hold():
    """Without `attack_note` (a `$80` record, or no `$40`) the restore call
    has nothing to hold."""
    plain = _two_stage_entries(0x41, 0x21, 1, 1)
    assert _two_stage_entries(0x41, 0x21, 1, 1, restore_call=9) == plain


@needs_corpus
@pytest.mark.parametrize("name, record, written, want", [
    ("Nemesis_the_Warlock", 0, False, 4),   # gate 3, test-bit firstwave
    ("Wiz", 8, True, 4),                    # gate 4, no_test_restart
    ("Wiz", 9, True, None),                 # vibrato byte 0: LDA note,X
    ("Sanxion", 13, False, None),           # duration gate, not a counter
])
def test_restore_call_read_from_the_player(name, record, written, want):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    det = detect(sid, lambda _m: None)
    assert _counter_gate_restore_call(sid, det, record, 1, written) == want


@needs_corpus
@pytest.mark.parametrize("name, ins_name, block, restore", [
    ("Nemesis_the_Warlock", "02:23-90-44",
     [(0x41, 0x00), (0x21, 0xBF), (0x41, 0xBF), (0x41, 0x00), (0xFF, 0x00)],
     4),
    ("Wiz", "0A:23-40-44",
     [(0x81, 0xC5), (0x41, 0xC5), (0x41, 0xC5), (0x41, 0x00), (0xFF, 0x00)],
     4),
])
def test_converted_block_under_presets(name, ins_name, block, restore):
    """The emitted program under presets, and the vibrato it carries cannot
    start before the played note is back: `vibdelay` is spent against the
    effect calls of this very block (`_classic_gate_refine`), so its first
    vibrato call is after `restore` even with no tick 0 withheld."""
    import fidelity
    import songview as SV
    from h2g.convert import convert

    doc = json.loads((REPO_ROOT / "presets.json").read_text())
    opts = dict(fidelity._preset_opts(doc, f"{name}.sid"),
                drop_unnamed_instruments=False)
    song = SV.parse_sng(convert(str(CORPUS / f"{name}.sid"),
                                log=lambda _m: None, **opts))
    wtbl = song.tables["WTBL"]
    (ins,) = [i for i in song.instruments if i.name == ins_name]
    assert wtbl[ins.wave_ptr - 1:ins.wave_ptr - 1 + len(block)] == block
    assert ins.vib_delay >= 1
    calls = _effect_call_list(wtbl, ins.wave_ptr, 32)
    assert calls[ins.vib_delay - 1] > restore


@needs_corpus
def test_no_hold_where_the_handler_does_not_yield_to_the_vibrato():
    """The hold is the `LDA field,Y / BNE out` branch's consequence; where
    that branch was not read against the vibrato byte, the note comes back
    as before. No corpus counter-gate file reads it differently (all 28
    read +5 = the vibrato byte), so the reading is withheld here: without
    the handler's operand `_fixed_pitch_yield_field` reads nothing."""
    import dataclasses

    sid = load_sid(str(CORPUS / "Wiz.sid"))
    det = detect(sid, lambda _m: None)
    assert _counter_gate_restore_call(sid, det, 8, 1, True) == 4
    blind = dataclasses.replace(det, fixed_pitch_index=-1)
    assert _counter_gate_restore_call(sid, blind, 8, 1, True) is None
