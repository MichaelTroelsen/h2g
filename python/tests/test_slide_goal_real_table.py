"""`_slide_goals` / `_slide_semitones` read Goattracker's real note table.

Opened as listen-sub99-pandora (the listening index's `instr` 39% on Pandora;
re-taken at a3792d2 / v0.5.676 as 59.4%, the stale figure being a heard.json
older than build/listen's staged h2g.sid). 108 of Pandora's 1261 notes are the
`$11 $81 $41 $41 $41 $40` drum (record 6, `set $81 $40 / slide $41 ...`), and
every one differed from the original on frame 4 by exactly one semitone
(heard: relative -18 original, -17 ours): the player's target there is
`$1168 - $0B15 = 1619`, which sits 47 cents above Goattracker's note 30
(`$0628`, 1576) and 53 below note 31 (`$0685`, 1669).

`_slide_goals` took `_note_freq(48)`, the `279 * 2**(n/12)` floor formula, whose
note 48 is 4464 where the table says `$1168` = 4456 (86 of the 96 entries
differ), so its target was 1627 and note 31 won by three cents. The table the
voice is actually played from is `skydive.GT_FREQ_TABLE`, which
`_wave_set_note_byte` and `_wave_tail_wrapped_note_byte` already read.
Heard `instr` 59.4 -> 68.0 on Pandora, `pitch_cents_agreement` .850 -> .857,
`aud` .93639 -> .93646 (`-t 180 --sound`, presets); Pandora is the only one
of the 89 presets conversions whose bytes move.
"""
import pathlib
import sys

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter import wave_program  # noqa: E402
from h2g.goatwriter.primitives import _note_freq  # noqa: E402
from h2g.goatwriter.skydive import GT_FREQ_TABLE  # noqa: E402

NOTE = 48          # GT's note for Pandora's $1168
SUM = 0x0B15       # the program's third running sum on record 6


def test_the_formula_and_the_table_disagree_at_pandoras_note():
    # the premise: the two tables a goal could be read from name different
    # frequencies for the same note
    assert GT_FREQ_TABLE[NOTE] == 0x1168
    assert _note_freq(NOTE) == 4464


def test_the_goal_is_the_players_target_from_the_real_table():
    [(n, plays, goal)] = wave_program._slide_goals({NOTE: 170}, SUM)
    assert (n, plays) == (NOTE, 170)
    assert goal == 0x1168 - SUM == 1619


def test_the_count_is_the_nearest_table_note_to_the_players_pitch():
    k = wave_program._slide_semitones({NOTE: 170}, SUM)
    assert k == -18, k
    here = abs(GT_FREQ_TABLE[NOTE + k] - 1619)
    other = abs(GT_FREQ_TABLE[NOTE + k + 1] - 1619)
    # 1576 is 47 cents below the target, 1669 is 53 above it
    assert GT_FREQ_TABLE[NOTE + k] == 0x0628
    assert GT_FREQ_TABLE[NOTE + k + 1] == 0x0685
    assert here < other, (here, other)
