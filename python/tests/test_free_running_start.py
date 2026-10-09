"""A free-running filter sweep starts at the file's byte, not Goattracker's 0.

Sigma_Seven's per-voice cutoff accumulator (`$84A1,X`) is initialised only by
the file ($08) and its sweep is the only writer (`FilterInfo.free_running`).
The block we emit has no set-cutoff row (it would reset the sweep on every
note), so Goattracker's `filtercutoff` powered on at 0: the original's first
write is $0A (-t 180, presets), ours was $02, and the cutoff ran 8 behind.
`free_running_start` writes `CMD_SETFILTERCUTOFF $08` once, on row 0 of the
subtune's entry pattern.

Per-voice occupancy of the filter-enabling records in the converted file
(rows, orderlists unrolled; measured 2026-10-09): voice 0 1192 of 1192, voice 1
26 of 1192, voice 2 0 of 1215. The cutoff is voice 0's accumulator ($D416 is
written by the voices in X = 2, 1, 0 order, so voice 0 writes last), and
voice 0 never plays an unfiltered record, so there is no "sweeps while an
unfiltered record plays" error to emit a pause for on this file.
"""
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.goatwriter import (CMD_SETFILTERCUTOFF, FILT_SET_PARAMS,
                            _free_running_block, free_running_start)

REPO = Path(__file__).resolve().parents[2]
FREE = ("Sigma_Seven", "After_8", "Mr_Meaner", "Rikky")


def _pat(rows=4, cmd=0, data=0):
    p = [0xBD, 0, 0, 0] * rows
    p[2], p[3] = cmd, data
    return p


def test_the_command_value_is_gcommon_c():
    assert CMD_SETFILTERCUTOFF == 0x0C


def test_row_zero_of_the_entry_pattern_gets_the_start():
    pats, tracks, placed, skipped = free_running_start(
        [[0, 1, 2], [3, 4, 5], [6, 7, 8]], [_pat(), _pat(), _pat()], 0x08)
    assert (placed, skipped) == (1, 0)
    assert pats[0][2:4] == [CMD_SETFILTERCUTOFF, 0x08]
    assert all(p[2] == 0 for p in pats[1:])


def test_an_occupied_command_column_is_never_overwritten():
    """SABOTAGE TARGET: drop the `patterns[number][2] != 0` guard and the
    subtune's tempo (row 0 of voice 0) is replaced."""
    tempo = _pat(cmd=0x0F, data=0x06)
    pats, _t, placed, _s = free_running_start(
        [[0], [1], [2]], [tempo, _pat(), _pat()], 0x08)
    assert pats[0][2:4] == [0x0F, 0x06]
    assert pats[1][2:4] == [CMD_SETFILTERCUTOFF, 0x08] and placed == 1


def test_no_free_column_leaves_the_subtune_unseeded():
    pats, _t, placed, skipped = free_running_start(
        [[0], [1], [2]], [_pat(cmd=0x0F, data=1)] * 3, 0x08)
    assert (placed, skipped) == (0, 1)
    assert all(p[2] == 0x0F for p in pats)


def test_a_pattern_entered_elsewhere_is_cloned_not_edited():
    """SABOTAGE TARGET: write into the shared pattern and the command fires
    again mid-song, resetting the sweep."""
    base = [_pat(), _pat(), _pat()]
    pats, tracks, placed, _s = free_running_start(
        [[1, 0], [1], [2]], base, 0x08)
    assert placed == 1 and len(pats) == 4
    assert all(p[2] == 0 for p in pats[:3])             # originals untouched
    assert pats[3][2:4] == [CMD_SETFILTERCUTOFF, 0x08]
    assert tracks[0] == [3, 0]                          # entry repointed


def test_a_repeat_prefix_is_not_an_entry():
    pats, _t, placed, skipped = free_running_start(
        [[0xD1, 0], [0xD1, 1], [0xD1, 2]], [_pat()] * 3, 0x08)
    assert (placed, skipped) == (0, 1)


def test_the_first_sweep_write_is_start_plus_step():
    """The next call after the command: the table's params row (no step),
    then `start + step` on every call, as in the original (0x08 + 2 = 0x0A)."""
    from test_filter_absent_four import gt_filter_calls
    block = _free_running_block(0x10, 0xF4, 2, 1)
    assert block[0][0] == FILT_SET_PARAMS | 0x10
    got = gt_filter_calls(block, 1, 4, cutoff=0x08)
    assert got == [0x08, 0x0A, 0x0C, 0x0E]


def _converted(stem):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                   **F._preset_opts(doc, f"{stem}.sid"))
    return parse_sng(blob)


def _cutoff_commands(song):
    return [(p, r, pat[4 * r + 3]) for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4)
            if pat[4 * r + 2] == CMD_SETFILTERCUTOFF]


@needs_corpus
def test_sigma_seven_carries_one_start_command_on_an_entry_row_zero():
    """SABOTAGE TARGET: gate `free_running_start` off in build.py and this
    finds no command."""
    song = _converted("Sigma_Seven")
    cmds = _cutoff_commands(song)
    assert [c[2] for c in cmds] == [0x08], cmds
    p, r, _ = cmds[0]
    assert r == 0
    assert p in [t[0] for t in song.tracks[:3] if t and t[0] < 0xD0]


@needs_corpus
@pytest.mark.parametrize("stem", [s for s in FREE if s != "Sigma_Seven"])
def test_a_free_running_file_starting_at_zero_gets_no_command(stem):
    """After_8, Mr_Meaner and Rikky read start 0 and Goattracker already
    powers on there: nothing to seed."""
    assert _cutoff_commands(_converted(stem)) == []
