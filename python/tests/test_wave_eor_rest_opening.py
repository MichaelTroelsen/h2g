"""A ring note a sliced pattern carries into the next pattern's rest rows.

`--max-rows` slices a long pattern, so a note can run on past the slice's end
into the successor's leading rest rows. Its last tick is the last of those
rows, so `eor_stop_pass` puts the pointer there -- in the successor, edited in
place, which is only right when EVERY way into the successor is such a tail.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import wave_eor as W  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETTEMPO, CMD_SETWAVEPTR,  # noqa: E402
                                      CMD_TONEPORTA, CMD_VIBRATO, GT_KEYOFF,
                                      GT_REST)

N = 0x60
STOP = 9
RING = frozenset({3})
REST = [GT_REST, 0, 0, 0]
PTR = (CMD_SETWAVEPTR, STOP)


def _pat(*rows):
    out = []
    for r in rows:
        out += r
    return out + [0xFF, 0, 0, 0]


def _cmds(pat):
    return [(pat[4 * k + 2], pat[4 * k + 3]) for k in range(len(pat) // 4)
            if pat[4 * k] != 0xFF]


def _run(pats, tracks):
    return W.eor_stop_pass(pats, tracks, RING, STOP)


CUT = _pat([N, 3, 0, 0], REST, REST)                    # ring note, sliced
OTHER = _pat([N, 4, 0, 0], REST, REST)                  # not a ring
TAIL = _pat(REST, REST, [N + 1, 5, 0, 0], REST)         # two rests, a note


def test_the_pointer_goes_on_the_last_leading_rest_row():
    got = _run([CUT, TAIL], [[0, 1, 0xFF, 0]])
    assert _cmds(got[0]) == [(0, 0)] * 3                 # the slice's end
    assert _cmds(got[1]) == [(0, 0), PTR, (0, 0), (0, 0)]


def test_the_opening_is_counted_in_the_log():
    log = []
    W.eor_stop_pass([CUT, TAIL], [[0, 1, 0xFF, 0]], RING, STOP, log.append)
    assert log and "1 note(s) stop their toggle" in log[0]
    assert "not followed" not in log[0]


def test_two_ring_tails_into_one_opening_both_take_it():
    cut2 = _pat([N + 2, 3, 0, 0], REST, REST)
    got = _run([CUT, cut2, TAIL], [[0, 2, 1, 2, 0xFF, 0]])
    assert _cmds(got[2]) == [(0, 0), PTR, (0, 0), (0, 0)]


def test_an_opening_a_non_ring_note_also_enters_is_declined():
    """Its pointer would hijack the other note's wavetable."""
    got = _run([CUT, OTHER, TAIL], [[0, 2, 1, 2, 0xFF, 0]])
    assert got[2] == TAIL and got[0] == CUT


def test_an_opening_entered_from_outside_is_declined():
    """A track that starts on it, or restarts to it, has no tail before it."""
    assert _run([CUT, TAIL], [[0, 1, 0xFF, 0], [1, 0xFF, 0]])[1] == TAIL
    assert _run([CUT, TAIL], [[0, 1, 0xFF, 1]])[1] == TAIL


def test_an_opening_that_is_a_successors_among_others_is_declined_whole():
    """A note whose successors are not ALL rest openings keeps its ring."""
    plain = _pat([N + 3, 5, 0, 0])
    got = _run([CUT, TAIL, plain], [[0, 1, 0xFF, 0], [0, 2, 0xFF, 0]])
    assert got[0] == CUT and got[1] == TAIL


def test_a_tie_after_the_rests_keeps_the_ring():
    tie = [N + 2, 3, CMD_TONEPORTA, 0]
    tail = _pat(REST, REST, tie)
    got = _run([CUT, tail], [[0, 1, 0xFF, 0]])
    assert got[1] == tail


def test_a_key_off_or_instrument_in_the_rests_is_not_an_opening():
    off = _pat(REST, [GT_KEYOFF, 0, 0, 0], [N + 1, 5, 0, 0])
    named = _pat(REST, [GT_REST, 5, 0, 0], [N + 1, 5, 0, 0])
    assert _run([CUT, off], [[0, 1, 0xFF, 0]])[1] == off
    assert _run([CUT, named], [[0, 1, 0xFF, 0]])[1] == named


def test_a_busy_last_rest_column_is_kept():
    tail = _pat(REST, [GT_REST, 0, CMD_SETTEMPO, 4], [N + 1, 5, 0, 0])
    assert _run([CUT, tail], [[0, 1, 0xFF, 0]])[1] == tail


def test_a_running_vibrato_into_the_rests_is_not_ended():
    vib = [CMD_VIBRATO, 0x24]
    cut = _pat([N, 3] + vib, [GT_REST, 0] + vib)
    # still running when the opening starts, and its own row 0 keeps it
    tail = _pat([GT_REST, 0] + vib, REST, [N + 1, 5, 0, 0])
    assert _run([cut, tail], [[0, 1, 0xFF, 0]])[1] == tail
    # an empty column in the opening's first row has ended it by the pointer
    tail = _pat(REST, REST, [N + 1, 5, 0, 0])
    assert _cmds(_run([cut, tail], [[0, 1, 0xFF, 0]])[1])[1] == PTR


def test_patterns_are_copied_not_edited_in_place():
    before = list(TAIL)
    _run([CUT, TAIL], [[0, 1, 0xFF, 0]])
    assert TAIL == before


RASPUTIN = CORPUS / "Rasputin.sid"

# the pattern whose leading rests the twelve tails run into
OPENINGS = (8, 28, 29, 167, 178, 179, 180, 181, 182, 183)


@needs_corpus
def test_rasputin_covers_all_twelve_sliced_ring_notes():
    import json

    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, "Rasputin.sid")
    log, seen = [], {}
    real = W.eor_stop_pass

    def spy(patterns, tracks, rings, stop, log=None):
        seen["before"], seen["stop"] = patterns, stop
        seen["after"] = real(patterns, tracks, rings, stop, log)
        return seen["after"]
    W.eor_stop_pass = spy
    try:
        convert(str(RASPUTIN), log=log.append, **opts)
    finally:
        W.eor_stop_pass = real
    line = next(l for l in log if l.startswith("EOR last tick"))
    assert "not followed" not in line
    stop = seen["stop"]
    for n in OPENINGS:
        pb, pa = seen["before"][n], seen["after"][n]
        rows = [r for r in range(len(pb) // 4)
                if pb[4 * r + 2:4 * r + 4] != pa[4 * r + 2:4 * r + 4]]
        lead = 0
        while pb[4 * lead] == GT_REST and not pb[4 * lead + 1]:
            lead += 1
        assert (lead - 1) in rows
        assert tuple(pa[4 * (lead - 1) + 2:4 * (lead - 1) + 4]) == (
            CMD_SETWAVEPTR, stop)
