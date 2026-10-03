"""`goatwriter._entry_instruments` follows the orderlist restart for one lap.

The loop (gplay.c:966-968: `songptr = songorder[..][songptr+1]`) leaves the
channel's `instr` alone -- only song init sets it to 1 (gplay.c:62/:223) --
so a pattern the restart re-enters is entered holding whatever the previous
lap ended on. Walked once, such a pattern came out SETTLED on the first lap's
instrument, and the passes that trust a settled entry
(`_tied_instrument_envelopes`, `_vibrato_command_pass`, `_attack_hold_pass`,
`legato_tie_clones`) wrote against an instrument the loop does not hold.

Under presets the lap moved no corpus byte at v0.5.496's dirty tree (95
files, 6 refused, 0 sha changes), although it widened entry sets in 71 files
-- every one of them on a pattern whose first note row names its own
instrument. These pins are synthetic for that reason.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import (_entry_instruments,  # noqa: E402
                            _tied_instrument_envelopes, legato_tie_clones)
from h2g.patterns import (CMD_TONEPORTA, GT_END_PATTERN,  # noqa: E402
                          GT_NO_NOTE)

NOTE = 0x60 + 0x30
REST = [GT_NO_NOTE, 0, 0, 0]
END = [GT_END_PATTERN, 0, 0, 0]
NAMES_5 = [NOTE, 5, 0, 0] + END          # a pattern that leaves instrument 5
SILENT = REST + END                      # a pattern naming nothing
ENVELOPES = {5: (0x22, 0x44), 6: (0x0F, 0x90)}


def test_a_pattern_the_restart_re_enters_sees_the_instrument_the_lap_ended_on():
    # Pattern 1 first, then pattern 0 naming 5, restart to position 0: the
    # second time round pattern 1 is entered holding 5, not 1.
    tracks = [[1, 0, 0xFF, 0x00]]
    assert _entry_instruments(tracks, [NAMES_5, SILENT]) == {1: {1, 5},
                                                             0: {1, 5}}


def test_a_restart_past_the_end_adds_no_lap():
    # gplay.c:969: a restart >= songlen stops the song -- nothing re-enters.
    assert _entry_instruments([[1, 0, 0xFF, 0x02]],
                              [NAMES_5, SILENT]) == {1: {1}, 0: {1}}


def test_the_lap_starts_at_the_restart_and_is_taken_once():
    # Restart to position 1: pattern 1 (position 0) is only ever entered from
    # song init. A lap from position 0 -- or a second, lapped-twice walk --
    # would hand it 5 as well.
    tracks = [[1, 0, 2, 0xFF, 0x01]]
    patterns = [NAMES_5, SILENT, SILENT]
    assert _entry_instruments(tracks, patterns) == {1: {1}, 0: {1, 5}, 2: {5}}
    # legato_tie_clones walks the same entry: a tie on pattern 1's row 0
    # with an empty column plays instrument 1, settled, so it is cloned.
    tie = [NOTE, 0, CMD_TONEPORTA, 0] + REST + END
    out, clones, declined = legato_tie_clones(
        [NAMES_5, tie, SILENT], {(1, 0)}, tracks, cloneable={1, 5},
        first_number=20)
    assert declined == set()
    assert clones == [(1, 20)]
    assert out[1][0:4] == [NOTE, 20, 0, 0]


def test_a_tie_the_loop_makes_ambiguous_is_left_alone():
    # Pattern 1 ties into instrument 6 on row 1, before any row names one.
    # The first lap enters it on 1, the loop on 5: the held instrument is
    # not settled, so `_tied_instrument_envelopes` writes nothing. Walked
    # once, it read 1 and wrote 6's pair against it.
    tied = REST + [NOTE, 6, CMD_TONEPORTA, 0] + REST + END
    patterns = [NAMES_5, tied]
    tracks = [[1, 0, 0xFF, 0x00]]
    assert _entry_instruments(tracks, patterns)[1] == {1, 5}
    logged = []
    out = _tied_instrument_envelopes(patterns, ENVELOPES, tracks,
                                     log=logged.append)
    assert out[1] == tied
    # Without the restart the entry IS settled on 1 and the pair is written:
    # the test above is about the lap, not about a pass that never writes.
    once = _tied_instrument_envelopes(patterns, ENVELOPES,
                                      [[1, 0, 0xFF, 0x03]])
    assert once[1] != tied
