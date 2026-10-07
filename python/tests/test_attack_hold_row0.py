"""The held-attack pointer reaches a short note on pattern row 0.

`goatwriter._attack_hold_pass` refused a note whose row before carried a
command (a running portamento, it said, would carry past `CMD_SETWAVEPTR`).
Through v0.5.496 it also refused every note on row 0 outright, because row 0 has no
row before it IN THE PATTERN -- and so four of Sanxion's short instrument-14
notes (voice 1 at 4040/4046/4232/4238, voice 3 at 4040/4046 of the packed
trace) kept the restore program and stepped C#6 -> the played note on N+2,
where the original holds C#6 to the next attack. Row 0's row before is the
last row of each pattern the orderlists play ahead of it
(`_predecessor_tails`, `_successor_heads` turned round); the pass now reads
it there (C:/t/attack-hold-row0-placement, 2026-10-03: 51 -> 55 placed, the
4 "column in use" gone, v1 C#6 held to the next attack 60 -> 64 of 64 and
v3 21 -> 23 against the original's 64 and 23; corpus byte-hash under the
presets: 95 compared, 6 refused on both sides, 1 moved, Sanxion).

After v0.5.513 the row-before guard itself went: new-note init resets the
effect on every note (test_attack_hold_row_before.py), so nothing carries,
row 0 is placed like any other row and `_predecessor_tails` is gone. The
tests below that pinned a refusal now pin the placement.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus
from h2g.goatwriter import CMD_SETWAVEPTR, GT_REST, _attack_hold_pass

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

C4, D4 = 0x90, 0x92
EMPTY = [GT_REST, 0, 0, 0]
HELD = 0x10


def _short_head() -> list:
    """Row 0: a two-row note of instrument 1, then a new attack (row 2) that
    is too long to be a target itself."""
    return [C4, 1, 0, 0] + EMPTY + [D4, 0, 0, 0] + EMPTY * 5 + [0xFF]


def _rests(last: list) -> list:
    return EMPTY * 7 + last + [0xFF]


def _pass(patterns, track):
    log = []
    out = _attack_hold_pass(patterns, {1: HELD}, 3, [track], log.append)
    return out, log


def test_row_0_takes_the_pointer_when_every_row_before_is_free():
    a = _short_head()
    out, log = _pass([a, _rests(EMPTY)], [1, 0, 0xFF, 0])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD], out[0][:8]
    assert a[2:4] == [0, 0], "changed patterns are copies"
    assert "column in use" not in log[0], log
    # Song start.
    out, _ = _pass([a, _rests(EMPTY)], [0, 0xFF, 0])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD]


def test_row_0_takes_the_pointer_after_a_command_or_an_unknown_row():
    """The row before is not read, so neither a command there nor an
    unknown one (a restart operand on no pattern, a pattern no orderlist
    plays) refuses row 0 any more."""
    a = _short_head()
    out, log = _pass([a, _rests([GT_REST, 0, 1, 0x20])], [1, 0, 0xFF, 0])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD]
    assert "column in use" not in log[0], log
    out, _ = _pass([a, _rests(EMPTY)], [1, 0, 0xFF, 7])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD]
    out, _ = _pass([a, _rests(EMPTY)], [1, 0xFF, 0])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD]


def test_a_command_the_pass_itself_wrote_on_the_row_before_is_no_bar():
    """A short note on the last row of the pattern before gets the pointer,
    and row 0 after it gets one too."""
    a = _short_head()
    b = EMPTY * 7 + [C4, 1, 0, 0] + [0xFF]
    out, _ = _pass([a, b], [1, 0, 0xFF, 0])
    assert out[1][-5:-1] == [C4, 1, CMD_SETWAVEPTR, HELD], out[1]
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD]


def test_a_one_row_pattern_takes_the_pointer():
    """Refused while row 0 was read against the tails, because its row 0
    is the tail its successors read; with no tail read it is a row like
    any other."""
    one = [C4, 1, 0, 0, 0xFF]
    nxt = [D4, 0, 0, 0] + EMPTY * 5 + [0xFF]
    out, log = _pass([one, nxt], [0, 1, 0xFF, 0])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD]
    assert "column in use" not in log[0], log


@needs_corpus
def test_sanxions_row_0_short_notes_hold_c_sharp_6():
    """End to end under the shipped presets: no short instrument-14 note is
    refused for its column, and at least one row-0 note points at the held
    block (four at v0.5.496: patterns $21, $22, $26, $27)."""
    import json

    import fidelity
    import songview as SV
    from h2g.convert import convert

    doc = json.loads((REPO_ROOT / "presets.json").read_text())
    opts = dict(fidelity._preset_opts(doc, "Sanxion.sid"),
                drop_unnamed_instruments=False)
    log = []
    blob = convert(str(CORPUS / "Sanxion.sid"), log=log.append, **opts)
    line = [m for m in log if m.startswith("Attack pitch held")]
    assert len(line) == 1, log
    assert "column in use" not in line[0], line
    song = SV.parse_sng(blob)
    row0 = [n for n, pat in enumerate(song.patterns)
            if 0x60 <= pat[0] <= 0xBC and pat[2] == CMD_SETWAVEPTR]
    assert row0, line
