"""The held-attack pointer does not read the row before its note.

Through v0.5.513 `goatwriter._attack_hold_pass` refused a short note whose
row before carried any command, on the grounds that `CMD_SETWAVEPTR` does not
reset the running effect and so a portamento there would carry into the
note. It does not carry: new-note init zeroes the effect on every note that
is not a toneportamento -- gplay.c `cptr->command = 0` (with `cmddata` back to
the instrument's vibrato) ahead of the tick-0 switch, and player.s
`mt_newnoteinit`, `sta mt_chnfx,x ;Reset effect` and `mt_chnparam` from
`mt_insvibparam`, both before the `TONEPORTA` skip. That is exactly the state
`CMD_DONOTHING` (`mt_tick0_0`) leaves, so on a note row the pointer changes
the wave pointer and nothing else. Row 0 needed the orderlist walk
(`_predecessor_tails`) only to answer that question, so it went with it.

Corpus byte-hash under the presets, defaults, the always block alone and the
presets with `drop_unnamed_instruments=False`: 0 moved in each (89/86/86/89
compared) -- the guard refused no note in the corpus
(C:/t/attack-hold-row-before-guard-refuted, 2026-10-07). These tests pin the
rule on synthetic patterns, where it does bite.
"""
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import CMD_SETWAVEPTR, GT_REST, _attack_hold_pass

C4, D4 = 0x90, 0x92
EMPTY = [GT_REST, 0, 0, 0]
HELD = 0x10
CMD_PORTAUP = 1

PLAYER_S = pathlib.Path(
    r"C:/Users/mit/Downloads/GoatTracker_2.77/src/player.s")


def _pass(patterns, tracks):
    log = []
    out = _attack_hold_pass(patterns, {1: HELD}, 3, tracks, log.append)
    return out, log


def test_a_portamento_on_the_row_before_does_not_refuse_the_note():
    # A long note, a portamento on its last row, then a short target note
    # and the long attack that ends it.
    pat = ([C4, 1, 0, 0] + EMPTY * 4 + [GT_REST, 0, CMD_PORTAUP, 0x01]
           + [D4, 0, 0, 0] + EMPTY + [C4, 0, 0, 0] + EMPTY * 5 + [0xFF])
    out, log = _pass([pat], [[0, 0xFF, 0]])
    row = 6 * 4
    assert out[0][row:row + 4] == [D4, 0, CMD_SETWAVEPTR, HELD], out[0]
    # Nothing else moved: the note row's command column is the only change.
    diff = [k for k, (a, b) in enumerate(zip(pat, out[0])) if a != b]
    assert diff == [row + 2, row + 3], diff
    assert "column in use" not in log[0], log


def test_consecutive_short_notes_both_take_the_pointer():
    """The pass's own pointer on the note before is a row-before command
    too; it no longer refuses the second note (rows 0 and 1)."""
    pat = ([C4, 1, 0, 0] + [D4, 0, 0, 0] + EMPTY
           + [C4, 0, 0, 0] + EMPTY * 5 + [0xFF])
    out, _ = _pass([pat], [[0, 0xFF, 0]])
    assert out[0][2:4] == [CMD_SETWAVEPTR, HELD], out[0]
    assert out[0][6:8] == [CMD_SETWAVEPTR, HELD], out[0]


def test_the_note_rows_own_column_still_refuses():
    pat = ([C4, 1, 0, 0] + EMPTY + [D4, 0, 0, 0] + EMPTY * 5 + [0xFF])
    pat[2:4] = [CMD_PORTAUP, 0x01]
    out, log = _pass([pat], [[0, 0xFF, 0]])
    assert out[0][2:4] == [CMD_PORTAUP, 0x01]
    assert "1 with the column in use" in log[0], log


@pytest.mark.skipif(not PLAYER_S.is_file(), reason=f"{PLAYER_S} not found")
def test_the_packed_player_resets_the_effect_on_every_new_note():
    """The premise, read off player.s: `mt_newnoteinit` stores 0 to
    `mt_chnfx` before the toneportamento skip, and `mt_tick0_8` does not
    touch `mt_chnfx`."""
    src = PLAYER_S.read_text(errors="replace")
    init = src[src.index("mt_newnoteinit:"):]
    init = init[:init.index("mt_nonewnoteinit:")]
    reset = re.search(r"lda #\$00\s*\n(?:\s*\.IF[^\n]*\n)*\s*sta mt_chnfx,x",
                      init)
    assert reset, init[:400]
    assert reset.start() < init.index("cmp #TONEPORTA")
    tick8 = src[src.index("mt_tick0_8:"):]
    tick8 = tick8[:tick8.index("rts")]
    assert "mt_chnfx" not in tick8, tick8
