"""`first_rows`: the rows before a JMP-form gate's first underflow keep the
lengths the original gives them.

A `jmp_gate` player (Star_Paws `$B053`, Knucklebusters `$0462`) is run by three
bytes the file holds at start. The outer cell counts down from its image byte,
so until its first underflow the rows are not the cycle's rows. Star_Paws (cell
$06, reload 127): its third row is 3 frames where every other row is 2, and
its voice 1 attacks at 1, 10, 18, 26 against ours 1, 9, 17, 25 once the
packed player's lead is taken out. Knucklebusters subtune 0 (cell $03, reload
1): fetches on 1, 6, 12, 18 -- its first row is 5 frames where the rest are 6.
`startup_lag` reads the lead off the FIRST attack, so both songs were scored a
frame off their own steady lag. Read off the original with `siddump -w` (the
three cells) at 10 s: Star_Paws $B712 reads 6 5 4 3 2 1 0 7F ..., Knucklebusters
$0981 reads 3 2 1 0 1 0 1 ...
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO                      # noqa: E402
from h2g.goatwriter import call_phase                        # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,  # noqa: E402
                          first_rows_tempos)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pattern(rows, cmd_at=None):
    p = [0x60, 1, CMD_SETTEMPO, 4]
    for r in range(1, rows):
        p += [0x60 + r, 1, 0, 0]
    p += [GT_END_PATTERN, 0, 0, 0]
    if cmd_at is not None:
        p[cmd_at * 4 + 2], p[cmd_at * 4 + 3] = 1, 0x20     # a portamento cell
    return p


def _tempos(pattern):
    return {r: pattern[r * 4 + 3] for r in range(len(pattern) // 4)
            if pattern[r * 4 + 2] == CMD_SETTEMPO}


def test_a_lengthened_row_gets_a_restore_in_a_clone_of_the_first_play():
    patterns = [_pattern(8)]
    tracks = [[0, 0, GT_ORDER_RESTART, 0], [], []]
    assert first_rows_tempos(patterns, tracks, 0, 4, {2: 2}) == 2
    # the first play is the clone; the second keeps the steady rows
    assert tracks[0][:2] == [1, 0] and len(patterns) == 2
    assert _tempos(patterns[1]) == {0: 4, 2: 6, 3: 4}
    assert _tempos(patterns[0]) == {0: 4}


def test_a_shortened_row_zero_rewrites_its_own_tempo():
    patterns = [_pattern(8)]
    tracks = [[0, GT_ORDER_RESTART, 0], [], []]
    assert first_rows_tempos(patterns, tracks, 0, 18, {0: -3}) == 2
    assert _tempos(patterns[1]) == {0: 15, 1: 18}


def test_an_occupied_command_column_declines_the_whole_correction():
    patterns = [_pattern(8, cmd_at=3)]
    tracks = [[0, GT_ORDER_RESTART, 0], [], []]
    before = [list(p) for p in patterns]
    assert first_rows_tempos(patterns, tracks, 0, 4, {2: 2}) == 0
    assert patterns == before and tracks[0] == [0, GT_ORDER_RESTART, 0]


def test_a_repeated_first_pattern_is_declined():
    patterns = [_pattern(8)]
    tracks = [[GT_REPEAT + 1, 0, GT_ORDER_RESTART, 0], [], []]
    assert first_rows_tempos(patterns, tracks, 0, 4, {2: 2}) == 0
    assert len(patterns) == 1


@needs_corpus
def test_the_gate_phase_names_star_paws_third_row_and_knucklebusters_first():
    sp = load_sid(str(CORPUS / "Star_Paws.sid"))
    assert call_phase.first_row_deltas(sp, 0, 2, 4, rate_paid=True) == {2: 2}
    # a rounded row (508 calls for 512) with no regrid to pay the fraction
    assert call_phase.first_row_deltas(sp, 0, 2, 4) == {}
    kb = load_sid(str(CORPUS / "Knucklebusters.sid"))
    assert call_phase.first_row_deltas(kb, 0, 3, 18) == {0: -3}
    # subtune 2: a 6-call row for the gate's 6.375, no regrid -- the first row
    # would be put right in front of a 6% drift
    assert call_phase.first_row_deltas(kb, 2, 3, 6) == {}
    # a row length that is not the modal interval times the multiplier is not
    # a row this correction can express
    assert call_phase.first_row_deltas(sp, 0, 2, 5) == {}
    # a player without the JMP-form gate has no such phase
    assert call_phase.first_row_deltas(
        load_sid(str(REPO_ROOT / "Commando.sid")), 0, 2, 6) == {}


def _convert(name, first_rows):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    opts["first_rows"] = first_rows
    return songview.parse_sng(convert(str(CORPUS / name),
                                      log=lambda m: None, **opts))


def _first_play(sng, voice=0, subtune=0):
    return sng.patterns[sng.tracks[3 * subtune + voice][
        next(i for i, b in enumerate(sng.tracks[3 * subtune + voice])
             if b < 0xD0)]]


@needs_corpus
def test_star_paws_third_row_is_three_frames_with_the_option_only():
    on = _tempos(_first_play(_convert("Star_Paws.sid", True)))
    off = _tempos(_first_play(_convert("Star_Paws.sid", False)))
    assert on[0] == off[0] == 4 and on[2] == 6 and on[3] == 4
    assert 2 not in off


@needs_corpus
def test_knucklebusters_subtune_zero_opens_on_a_five_frame_row():
    on = _tempos(_first_play(_convert("Knucklebusters.sid", True)))
    off = _tempos(_first_play(_convert("Knucklebusters.sid", False)))
    assert off[0] == 18 and on[0] == 15 and on[1] == 18
