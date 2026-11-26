"""`pulse_phase` leaves row 0 of a `$68` sweep note to its wide CMD_VIBRATO.

The decoder marks a `$68` note's FIRST HOLD row with
`CMD_VIBRATO, STORED_DEPTH_MARK + quarter-octaves`; `_vibrato_command_pass`
turns the mark into the note's wide speed-table index and writes it on every
FREE row of the note's block. `apply_pulse_phase` runs first, so a
CMD_SETPULSEPTR on the note's row 0 took the column and the sweep's first row
ran at the instrument's own depth. Devils_Galop's opening note on voice 1 under
forced `pulse_phase` was the case: its row 0 read `09 xx` where
`tests/test_stored_wave_sweep_depth.py` expects `04 04`.

Measured (-t 180 --sound, forced pulse_phase on Devils_Galop, 2026-11-23,
a3792d2 + this change): pphase .625 -> .958, poff .796 -> .961, pspan .973 ->
1.000, aud .9329 -> .9460, loud .9727 -> .9832; the displaced build read aud
.9461, i.e. the restored vibrato is inside the noise.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fidelity import _preset_opts  # noqa: E402
from h2g.convert import convert  # noqa: E402
from h2g.patterns import (CMD_SETPULSEPTR, STORED_DEPTH_MARK,  # noqa: E402
                          apply_pulse_phase)
from songview import parse_sng  # noqa: E402

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
CMD_VIBRATO = 4
GT_FIRST_NOTE = 0x60


def test_the_marked_notes_row_0_keeps_its_column_free():
    # row 0: a note whose first hold row holds the depth mark;
    # row 2: a plain note with a free column.
    patterns = [[0x80, 5, 0, 0,
                 0xBD, 0, CMD_VIBRATO, STORED_DEPTH_MARK + 4,
                 0x82, 5, 0, 0,
                 0xFF, 0, 0, 0]]
    tracks = [[0, 0xFF, 0x00]]
    writes = [(0, 0, {0: (5, (0x900, 1)), 2: (5, (0xA00, 1))})]
    index = {(5, 0x900, 1): 40, (5, 0xA00, 1): 43}
    n = apply_pulse_phase(patterns, tracks, writes, index)
    clone = patterns[tracks[0][0]]
    assert n == 1, "only the unmarked note takes a phase"
    assert (clone[2], clone[3]) == (0, 0), "row 0 is left to the wide vibrato"
    assert (clone[6], clone[7]) == (CMD_VIBRATO, STORED_DEPTH_MARK + 4)
    assert (clone[10], clone[11]) == (CMD_SETPULSEPTR, 43)


def test_an_ordinary_hold_command_does_not_hold_the_phase_back():
    # a real vibrato index on the hold row is below the mark
    patterns = [[0x80, 5, 0, 0, 0xBD, 0, CMD_VIBRATO, 3, 0xFF, 0, 0, 0]]
    tracks = [[0, 0xFF, 0x00]]
    writes = [(0, 0, {0: (5, (0x900, 1))})]
    n = apply_pulse_phase(patterns, tracks, writes, {(5, 0x900, 1): 40})
    clone = patterns[tracks[0][0]]
    assert n == 1 and (clone[2], clone[3]) == (CMD_SETPULSEPTR, 40)


@needs_corpus
def test_devils_galop_forced_pulse_phase_keeps_the_wide_entry_on_row_0():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, "Devils_Galop.sid")
    opts["pulse_phase"] = True
    song = parse_sng(convert(str(CORPUS / "Devils_Galop.sid"),
                             log=lambda m: None, **opts))
    stbl = song.tables["STBL"]
    wide = stbl.index((0x80 | 6, 2)) + 1
    pat = song.patterns[song.tracks[1][0]]
    assert pat[0] == GT_FIRST_NOTE + 71 + 1
    assert (pat[2], pat[3]) == (CMD_VIBRATO, wide)
    # the option still ran: other notes carry their phase
    assert any(p[r + 2] == CMD_SETPULSEPTR
               for p in song.patterns for r in range(0, len(p) - 3, 4))
