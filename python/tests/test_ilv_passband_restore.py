"""ILV filter routing's "restore" spelling: the majority passband's programs
open at CUTOFF, and a CMD_SETFILTERPTR puts the passband back.

goatwriter.ilv_filter_routing_plan. Where a file's programs need different
passbands, "shared" (one passband block per subtune) is unavailable, and
"params" -- every program opening with its params row -- lets that row
overwrite the `B` on its note's own row one call later (player.s runs
`mt_filtstep` before the channels), so a note opening on another union lags.
Sun_Never_Shines lagged 130 rows that way. "restore" drops the params row
from the majority passband's programs and, where a majority note finds a
passband it did not set, writes an `A` on that note's own command column to
a copy of its program opening [PARAMS majority, union]. The `A` runs after
the note's own pointer load (player.s "Execute tick 0 FX after newnote
init"; gplay.c:388 before :459), so the copy is what runs.
"""
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus  # noqa: F401
from h2g.convert import convert
from h2g.goatwriter import (CMD_SETFILTERCTRL, CMD_SETFILTERPTR,
                            FILT_SET_CUTOFF, FILT_SET_PARAMS, FILT_STOP,
                            _ilv_routing_walk, _ilv_voice_rows, pattern_rows)

REPO = Path(__file__).resolve().parents[2]

_REST = (0xBD, 0, 0, 0)
# instr_base 1: GT instrument 1 is record 0 (routed, majority passband $10),
# 2 is record 1 (routed, minority passband $20), 3 is record 2 (unrouted).
_MAJ, _MIN, _PLAIN = 1, 2, 3
_PROGRAMS = {0: (0x10, 0x40, 0x80, 0), 1: (0x20, 0x40, 0x90, 0)}
_BASE = 7       # 1-based index the first restore block takes


def _pattern(rows, length=8):
    rows = dict(rows)
    out = []
    for r in range(length):
        out += list(rows.get(r, _REST))
    return out + [0xFF, 0, 0, 0]


def _groups(patterns, tracks, horizon=None):
    first = [_ilv_voice_rows(t, patterns) for t in tracks]
    horizon = horizon or max(len(f) for f in first)
    return [(horizon, [_ilv_voice_rows(t, patterns, horizon) for t in tracks])]


def _restore():
    return {"pb": 0x10, "majority": frozenset({0}), "next": _BASE,
            "len": {0: 3}, "blocks": {}}


def _walk(patterns, groups, mode, restore=None):
    return _ilv_routing_walk(groups, patterns, 1, {0, 1}, _PROGRAMS, mode,
                             {0: 0x41, 1: 0x41}, {}, restore)


def _song():
    """Voice 0: majority note, minority note, majority note. Voice 2 joins on
    a majority note at row 6, while the passband is already the majority's,
    so its union ($45) must be written by a `B` on its own row."""
    patterns = [_pattern({1: (0x90, _MAJ, 0, 0), 3: (0x90, _MIN, 0, 0),
                          5: (0x90, _MAJ, 0, 0)}),
                _pattern({}),
                _pattern({6: (0x90, _MAJ, 0, 0)})]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    return patterns, _groups(patterns, tracks)


def test_a_majority_note_after_a_minority_one_restores_its_passband():
    """SABOTAGE TARGET: with no restore placed, the passband stays $00 at
    power-on and $20 after row 3, and `passband_late` counts every row.

    Row 1 finds the power-on passband 0 and row 5 the minority's $20; both
    take an `A` on their own column to the ONE copy of record 0's program for
    union $41. Row 6's majority note finds $10 standing and gets a plain `B`
    on its own row -- never overwritten, because the program it loads opens
    at CUTOFF."""
    patterns, groups = _song()
    restore = _restore()
    plan, stats = _walk(patterns, groups, "restore", restore)
    assert plan == {(0, 0): {1: (CMD_SETFILTERPTR, _BASE),
                             5: (CMD_SETFILTERPTR, _BASE)},
                    (2, 0): {6: (CMD_SETFILTERCTRL, 0x45)}}, plan
    assert restore["blocks"] == {(0, 0x41): _BASE}
    assert (stats["restores"], stats["lagged"], stats["late_rows"],
            stats["passband_late"]) == (2, 0, 0, 0), stats


def test_the_params_spelling_lags_the_same_song():
    """The contrast: "params" opens record 0's program on its params row
    ($41), which overwrites the `B` voice 2's row-6 note wants -- one lag,
    written a row late, on the first free column (no voice notes on row 7)."""
    patterns, groups = _song()
    plan, stats = _walk(patterns, groups, "params")
    assert plan == {(0, 0): {7: (CMD_SETFILTERCTRL, 0x45)}}, plan
    assert (stats["lagged"], stats["late_rows"], stats["passband_late"]) \
        == (1, 1, 0), stats


def test_a_restore_whose_own_column_is_taken_runs_on_the_next_free_row():
    """SABOTAGE TARGET: drop the late fallback and the passband stays 0 until
    the next majority note.

    Row 0 is the subtune's clock (CLAUDE.md), so a majority note there takes
    its copy from the first free column after it, and the row it spent on the
    wrong passband is counted."""
    patterns = [_pattern({0: (0x90, _MAJ, 0, 0)}), _pattern({}), _pattern({})]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    plan, stats = _walk(patterns, _groups(patterns, tracks), "restore",
                        _restore())
    assert plan == {(0, 0): {1: (CMD_SETFILTERPTR, _BASE)}}, plan
    assert (stats["restore_unplaceable"], stats["late_restores"],
            stats["passband_late"]) == (1, 1, 1), stats


def test_a_replayed_restore_puts_the_passband_back_without_a_second_copy():
    """SABOTAGE TARGET: treat a replayed `A` as the shared init (params $00,
    passband untouched) and the second play's majority note sits on $20.

    `REPEAT` $D1 plays pattern 0 twice: the second play's row-1 note runs the
    `A` its first play placed, which the walk must model as the restore."""
    patterns = [_pattern({1: (0x90, _MAJ, 0, 0), 3: (0x90, _MIN, 0, 0)}),
                _pattern({}, 16), _pattern({}, 16)]
    tracks = [[0xD1, 0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    plan, stats = _walk(patterns, _groups(patterns, tracks, 16), "restore",
                        _restore())
    assert plan == {(0, 1): {1: (CMD_SETFILTERPTR, _BASE)}}, plan
    assert (stats["restores"], stats["passband_late"], stats["late_rows"]) \
        == (1, 0, 0), stats


# --- Sun_Never_Shines, the file the spelling exists for ----------------------

def _sun():
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = F._preset_opts(doc, "Sun_Never_Shines.sid")
    assert opts.get("ilv_filter_routing"), opts
    lines = []
    blob = convert(str(CORPUS / "Sun_Never_Shines.sid"), log=lines.append,
                   **opts)
    line = next(m for m in lines if m.startswith("ILV filter routing"))
    return parse_sng(blob), line


@needs_corpus
def test_sun_takes_the_restore_spelling_and_stops_lagging():
    """Figures at the staged base of the cycle this was written in: "params",
    130 lagged, 130 rows late. Now: 0 lagged, 10 rows late (the changes with
    no free column), one restore placed a row after the song's first note
    (row 0, which also carries the tempo), one row on the wrong passband."""
    _song_, line = _sun()
    assert line.startswith("ILV filter routing......: restore,"), line
    assert " 0 lagged," in line and " 10 row(s) late," in line, line
    assert "1 passband restore(s), 1 late," in line, line
    assert "1 row(s) on the wrong passband" in line, line


@needs_corpus
def test_sun_majority_programs_open_at_cutoff_and_every_a_restores_the_passband():
    """SABOTAGE TARGET: keep the params row on the majority's programs, or
    drop it from the restore copy, and one of the two halves fails.

    Every instrument pointer into the filter table lands on a CUTOFF row
    unless it is the minority program ($20, which keeps its params row); every
    `A` in the patterns lands on [PARAMS $30, union][CUTOFF] -- the majority
    passband with a routed union, never $00."""
    song, _ = _sun()
    ftbl = song.tables["FTBL"]
    pointers = {ins.filt_ptr for ins in song.instruments} - {0}
    opens = sorted({ftbl[p - 1][0] for p in pointers})
    # Record 12 (the minority, never played in the walk) may have no
    # instrument of its own here; the majority ones must all open at CUTOFF.
    assert FILT_SET_CUTOFF in opens, opens
    assert set(opens) <= {FILT_SET_CUTOFF, FILT_SET_PARAMS | 0x20}, opens
    targets = {dat for p in song.patterns
               for _n, _i, cmd, dat in pattern_rows(p)
               if cmd == CMD_SETFILTERPTR}
    assert targets, "no restore written"
    for t in targets:
        left, right = ftbl[t - 1]
        assert left == FILT_SET_PARAMS | 0x30 and right & 0x0F, (t, ftbl[t - 1])
        assert ftbl[t][0] == FILT_SET_CUTOFF, ftbl[t]
        assert any(ftbl[k][0] == FILT_STOP for k in range(t, len(ftbl)))


@pytest.mark.parametrize("stem,mode", [("Radio_ACE", "params"),
                                       ("Lion_Heart", "params"),
                                       ("Pacific_Coast", "params"),
                                       ("Go_Go_Dash", "shared")])
@needs_corpus
def test_one_passband_files_keep_their_spelling(stem, mode):
    """"restore" is walked only where the programs' passbands differ."""
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    lines = []
    convert(str(CORPUS / f"{stem}.sid"), log=lines.append,
            **F._preset_opts(doc, f"{stem}.sid"))
    line = next(m for m in lines if m.startswith("ILV filter routing"))
    assert line.startswith(f"ILV filter routing......: {mode},"), line
    assert "passband restore" not in line, line
