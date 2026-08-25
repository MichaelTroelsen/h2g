"""What a note's own row is spent on before the note can be heard.

A Goattracker note that is **not** tied costs two things before it sounds:
`gatetimer & $3f` play calls with the gate held off (the hard restart,
gplay.c:905 / player.s `mt_normalnote`), and then one more call on the
instrument's `firstwave`. The default `firstwave` is `$09` -- gate on, **test
bit on** -- which resets the oscillator and outputs nothing, and the packed
player does not execute the wavetable on that call at all (player.s:908-911),
so the first entry that can make a sound lands on the call after it.

The budget is therefore `_hard_restart_ticks(...) + 1` calls, and where that
reaches the row length a one-row note is **inaudible**: every call in its slot
is either gated off or on the test bit, and the next row's first call is the
next note's gate-off. Nineteen's row is 3 calls (`CMD_SETTEMPO [3]`) and its
restart is 2, so its voice 0 traces

    frame 1058 wf=40  1059 wf=40  1060 wf=09      <- one row, silent
    frame 1061 wf=40  1062 wf=40  1063 wf=09      <- the next, silent

against an original that is gated and arpeggiating across the same frames.

This is why a `CMD_TONEPORTA $00` tie can make a file's attack count go **up**.
The tie's spelling is answered by the packed player with "no gateoff"
(player.s:1298-1301, `lda mt_chnnewfx,x / cmp #TONEPORTA / beq mt_rest`), so a
tied row skips the whole budget and becomes audible. On Nineteen five voice-0
rows did exactly that: 69 attacks -> 74 when `gate_hold` landed (v0.5.331),
which reads as a regression on `melody` and is the conversion *recovering*
notes it had been swallowing. Removing the budget instead -- either by
dropping the floor below, or by setting `gatetimer` bit `$40` so no note gates
off -- takes the same voice from 69 to **90** attacks with no tie anywhere,
which is the measurement that says the notes were there all along.

The census below is the other half of the argument: **38 of the 83 convertible
corpus files** carry such a row under their shipped presets, so this is a
property of a 3-call row and not of Nineteen's player. Any rule that switched
`gate_hold` off for Nineteen alone would be hiding that.

These tests pin the arithmetic as it stands; they are a *characterisation* of
a known defect, not an endorsement of it. A change that gives a 3-call row a
call to sound in is expected to break them, and should update the numbers here
in the same commit rather than delete the tests.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402
import h2g.goatwriter as gw  # noqa: E402
from h2g.goatwriter import _hard_restart_ticks  # noqa: E402

# The note's first call goes on `firstwave`, and the packed player jumps
# straight to the register writes after the init rather than falling through
# to the wavetable (player.s:908-911), so nothing an instrument programs can
# reach $D404 on it.
FIRSTWAVE_CALLS = 1


def _budget(multiplier: int, row_calls: int) -> int:
    return _hard_restart_ticks(multiplier, row_calls) + FIRSTWAVE_CALLS


def test_a_three_call_row_has_no_call_left_for_the_note():
    """Nineteen, Commando, Sanxion and thirty more: `CMD_SETTEMPO [3]`."""
    assert _hard_restart_ticks(1, 3) == 2
    assert _budget(1, 3) == 3


def test_the_floor_is_what_spends_the_last_call():
    """`row // 2` would leave one call; `max(ticks, min(2, row - 1))` does not.

    The floor is deliberate -- it is what keeps every `-S1` conversion in the
    corpus byte-identical to the value this writer used for its whole life --
    so naming it is the point: the cost of that compatibility is every
    one-row note on a 3-call row.
    """
    assert 3 // 2 == 1                       # the half-the-row bound
    assert _hard_restart_ticks(1, 3) == 2    # what the floor makes of it


def test_a_longer_row_keeps_calls_for_the_note():
    """Four calls and up have room, which is why this is a short-row defect."""
    for row in range(4, 40):
        assert _budget(1, row) < row


@needs_corpus
def test_the_swallowed_row_is_not_one_file():
    """Hook the writer's own bound while converting the corpus.

    Recomputing the row length here instead would be a second derivation of
    something the converter already knows -- the trap CLAUDE.md records for
    probes -- so this asks the function that decides it.
    """
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    real = gw._hard_restart_ticks
    seen: dict[str, set] = {}
    current = [""]

    def spy(multiplier, row_calls, wide=False, full=False, frames=None):
        # `frames` is the per-song --hard-restart-frames override; the spy has
        # to accept it or every conversion here raises TypeError and the
        # `converted >= 80` guard below correctly refuses to conclude anything.
        ticks = real(multiplier, row_calls, wide, full, frames)
        if row_calls:
            seen.setdefault(current[0], set()).add((row_calls, ticks))
        return ticks

    gw._hard_restart_ticks = spy
    try:
        converted = 0
        for path in sorted(CORPUS.glob("*.sid")):
            current[0] = path.name
            try:
                blob = F.convert(str(path), log=lambda m: None,
                                 **F._preset_opts(doc, path.name))
            except Exception:                          # noqa: BLE001
                continue                               # SURVEY.md's business
            if blob:
                converted += 1
    finally:
        gw._hard_restart_ticks = real

    # A probe whose conversions nearly all failed would agree with anything.
    assert converted >= 80, converted
    swallowed = sorted(name for name, rows in seen.items()
                       if any(t + FIRSTWAVE_CALLS >= rc for rc, t in rows))
    assert "Nineteen.sid" in swallowed
    assert "Commando.sid" in swallowed
    # 38 at v0.5.337. Asserted as a floor rather than an equality so that
    # adding a corpus file does not fail the test that says "not one file".
    assert len(swallowed) >= 30, swallowed
