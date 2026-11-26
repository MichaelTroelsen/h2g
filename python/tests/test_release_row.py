"""A gate lead longer than one row: KEYOFF on the rest row before a note
(goatwriter.release_row).

W_A_R's player clears the gate on the last tick of every note, 12 calls (3
frames at -S4) before the next note. Its rows are 9 calls, so the gatetimer
stops at 8 (`gplay.c:334`) and ours cleared it 2 frames before: `gate` 77%.
A KEYOFF on the rest row before the note is fetched `gatetimer` calls before
THAT row, which is `row + gatetimer` before the note: 9 + 3 = 12.

The synthetic songs below are one record whose gatetimer is `lead - row` = 3,
rows of 9 calls, lead 12.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import HEADER_LEN                        # noqa: E402
from h2g.goatwriter import release_row as rr                 # noqa: E402

import songview                                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
C4 = 0x60 + 12 * 4
REST, KEYOFF, END = 0xBD, 0xBE, 0xFF
TONEPORTA = 3
LEAD, ROW = 12, 9


def record(gatetimer):
    r = bytearray(25)
    r[2] = 1
    r[7] = gatetimer
    return bytes(r)


def song(patterns, orders, gatetimers=(0x83,)):
    """A GTS5 song: `gatetimers` records, voice 0 plays `orders[0]` (pattern
    numbers) and restarts at 0; voices 1 and 2 play `orders[1:]` if given."""
    out = bytearray(b"GTS5" + bytes(HEADER_LEN - 4))
    out.append(1)
    tracks = [list(o) + [0xFF, 0x00] for o in orders]
    tracks += [[0xFF, 0x00]] * (3 - len(tracks))
    for track in tracks:
        out.append(len(track) - 1)
        out += bytes(track)
    out.append(len(gatetimers))
    for g in gatetimers:
        out += record(g)
    wtbl = [(0x41, 0x00), (0xFF, 0x00)]
    out.append(len(wtbl))
    out += bytes(left for left, _ in wtbl) + bytes(right for _, right in wtbl)
    for _ in range(3):                       # pulse, filter, speed tables
        out.append(0)
    out.append(len(patterns))
    for rows in patterns:
        out.append(len(rows) + 1)
        for row in rows:
            out += bytes(row)
        out += bytes([END, 0, 0, 0])
    return bytes(out)


NOTE = (C4, 1, 0, 0)
HOLD = (REST, 0, 0, 0)
TIE = (C4 + 2, 0, TONEPORTA, 0)
FOUR_ROWS = [NOTE, HOLD, HOLD, HOLD, NOTE, HOLD, HOLD, HOLD]


def run(blob, calls=(ROW,)):
    return rr.release_row_keyoffs(blob, list(calls), LEAD)


def notes(blob, pattern=0):
    p = songview.parse_sng(blob).patterns[pattern]
    return [p[4 * r] for r in range(len(p) // 4)]


def test_release_ticks_is_the_lead_beyond_the_row():
    assert rr.release_ticks(12, 9) == 3
    assert rr.release_ticks(12, 7) == 5
    # Not between one row and two: the ordinary gatetimer reaches it, or
    # nothing does.
    assert rr.release_ticks(12, 12) == 0
    assert rr.release_ticks(12, 13) == 0
    assert rr.release_ticks(12, 6) == 0
    assert rr.release_ticks(8, 9) == 0
    assert rr.release_ticks(12, 1) == 0


def test_release_calls_is_frames_times_multiplier():
    assert rr.release_calls(4, 3) == 12
    assert rr.release_calls(1, None) == 2
    assert rr.release_calls(4, False) == 8        # `_preset_opts` absent key


def test_the_rest_row_before_a_note_becomes_a_keyoff():
    got = notes(run(song([FOUR_ROWS], [[0]])))
    # Row 3 precedes the note on row 4. Row 7 is the pattern's last row and
    # the position repeats into a note (restart 0): the boundary case.
    assert got[3] == KEYOFF
    assert got[7] == KEYOFF
    assert got[:3] == [C4, REST, REST] and got[4] == C4


def test_nothing_changes_for_an_instrument_that_is_not_released_this_way():
    blob = song([FOUR_ROWS], [[0]], gatetimers=(0x88,))
    assert run(blob) == blob


def test_nothing_changes_where_the_track_is_at_another_row_length():
    # The instrument's gatetimer (3) is for 9-call rows; this subtune's are 16
    # calls: lead 12 is below the row, the ordinary gatetimer's business.
    blob = song([FOUR_ROWS], [[0]])
    assert run(blob, calls=(16,)) == blob
    # And a 10-call row wants 2, not 3.
    assert run(blob, calls=(10,)) == blob


def test_a_tied_note_is_not_preceded_by_a_keyoff():
    # CMD_TONEPORTA reads as "no gate-off" (gplay.c:925): a KEYOFF before it
    # would shut a gate the tie means to keep.
    rows = [NOTE, HOLD, HOLD, TIE, HOLD, HOLD, HOLD, HOLD]
    got = notes(run(song([rows], [[0]])))
    assert got[2] == REST


def test_a_single_row_note_has_no_rest_row_to_carry_one():
    rows = [NOTE, NOTE, NOTE, HOLD, HOLD]
    got = notes(run(song([rows], [[0]])))
    assert got[:3] == [C4, C4, C4]
    assert KEYOFF not in got[:3]


def test_a_row_carrying_an_instrument_or_a_note_is_kept():
    rows = [NOTE, HOLD, (REST, 2, 0, 0), NOTE, HOLD, HOLD]
    got = notes(run(song([rows], [[0]], gatetimers=(0x83, 0x83))))
    assert got[2] == REST


def test_a_command_column_on_the_rest_row_survives():
    rows = [NOTE, HOLD, (REST, 0, 9, 0x40), NOTE, HOLD, HOLD]
    sng = songview.parse_sng(run(song([rows], [[0]])))
    p = sng.patterns[0]
    assert p[4 * 2:4 * 2 + 4] == [KEYOFF, 0, 9, 0x40]


def test_visits_that_disagree_get_a_copy():
    """Pattern 0 is played by voice 0 holding the released record and by
    voice 1 holding one that is not: one pattern, two wants."""
    patterns = [[(C4, 1, 0, 0), HOLD, HOLD, NOTE, HOLD, HOLD],
                [(C4, 2, 0, 0), HOLD, HOLD, NOTE, HOLD, HOLD]]
    # Voice 0 plays pattern 0 (record 1, released); voice 1 plays pattern 1,
    # which names record 2 (gatetimer 8, not released) -- a different
    # pattern, so no copy is needed and neither is touched wrongly.
    blob = song(patterns, [[0], [1]], gatetimers=(0x83, 0x88))
    got = run(blob)
    assert notes(got, 0)[2] == KEYOFF
    assert notes(got, 1)[2] == REST
    # The same pattern under both instruments: voice 1 enters it holding
    # record 2, which an earlier pattern names; voice 0 holds record 1.
    bare = (C4, 0, 0, 0)
    shared = [bare, HOLD, HOLD, bare, HOLD, HOLD]
    entry = [(REST, 2, 0, 0), HOLD]
    blob = song([shared, entry], [[0], [1, 0]], gatetimers=(0x83, 0x88))
    got = run(blob)
    parsed = songview.parse_sng(got)
    assert len(parsed.patterns) == 3, "a copy for the released position"
    assert notes(got, 0)[2] == REST         # voice 1 keeps the plain rows
    assert notes(got, 2)[2] == KEYOFF       # voice 0: the released record
    assert parsed.tracks[0][0] == 2 and parsed.tracks[3 * 0 + 1][1] == 0


def test_the_seam_turns_the_pass_off():
    blob = song([FOUR_ROWS], [[0]])
    rr.ENABLED = False
    try:
        assert run(blob) == blob
    finally:
        rr.ENABLED = True
    assert run(blob) != blob


@needs_corpus
def test_w_a_r_is_released_a_row_early_under_the_option():
    """W_A_R at its preset plus `release_row` and a 3-frame lead: the hat and
    melody records carry gatetimer 3, a 9-call row plus 3 is the original's 12
    calls, and the rest row before each note is a KEYOFF. Without the option
    the song is unchanged."""
    doc = json.loads((REPO_ROOT / "presets.json").read_text())
    shipped = fidelity._preset_opts(doc, "W_A_R.sid")
    # W_A_R ships with the option on: the shipped row must say so, and "off"
    # is the same row with the two keys withdrawn.
    assert shipped["release_row"] is True
    assert shipped["hard_restart_frames"] == 3
    base = {k: v for k, v in shipped.items()
            if k not in ("release_row", "hard_restart_frames")}
    path = str(CORPUS / "W_A_R.sid")
    plain = fidelity.convert(path, log=lambda *_: None, **base)
    opts = dict(base, release_row=True, hard_restart_frames=3)
    lines = []
    got = fidelity.convert(path, log=lines.append, **opts)
    assert any(l.startswith("Release row") for l in lines)
    before, after = songview.parse_sng(plain), songview.parse_sng(got)
    released = [i.number for i in after.instruments if i.gatetimer & 0x3F == 3]
    assert len(released) >= 15
    assert not any(i.gatetimer & 0x3F == 3 for i in before.instruments)

    def keyoffs(sng):
        return sum(p[4 * r] == KEYOFF for p in sng.patterns
                   for r in range(len(p) // 4))
    assert keyoffs(after) > keyoffs(before) + 500

    # The same options with the pass short-circuited: gatetimers move, rows
    # do not.
    rr.ENABLED = False
    try:
        off = songview.parse_sng(
            fidelity.convert(path, log=lambda *_: None, **opts))
    finally:
        rr.ENABLED = True
    assert keyoffs(off) == keyoffs(before)
    assert fidelity.convert(path, log=lambda *_: None, **dict(
        base, release_row=False)) == plain
