"""ilv_start_cutoff: a `$87` start cutoff rides on the note's own row.

Sun_Never_Shines' voice-0 filter record (record 8, program `24 91 00 AE 4F 06
03 80`) starts EVERY note on a `$87 nn mm`: 621 notes in 180 s, 71 distinct
start values, 83% of them far from the record's own `$24`. A table row is one
value per instrument, so the file's `cfrm` read 25% (`cutoff_frame` .2527 at
v0.5.676). Under the option the value rides on the note as a
`CMD_SETFILTERCUTOFF`, the record's table drops its cutoff row (which would
overwrite the command a tick later), and its first leg runs at the player's
fractional step (`$00AE` = 0.68 a frame) instead of the rounded 1.

The cutoff is written LAST (`filters.finalize_start_cutoffs`): every pass that
wants the command column displaces it, the routing's `CMD_SETFILTERCTRL`
included -- which moves the cutoff to the note's first hold row when that is
free. The first version wrote it at decode time and the routing then moved
594 `B` rows onto voice 1's hold rows, where a command silences the
instrument vibrato (travel .983 -> .970, route .988 -> .984).
"""
import io
import json
import contextlib
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.goatwriter import filters as GF
from h2g.goatwriter.constants import (CMD_SETFILTERCTRL, CMD_SETFILTERCUTOFF,
                                      FILT_SET_CUTOFF, FILT_STOP)

REPO = Path(__file__).resolve().parents[2]
SUN = "Sun_Never_Shines"
PROG8 = bytes.fromhex("24 91 00 AE 4F 06 03 80")


def _song(stem=SUN, **over):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    # The option is named explicitly: Sun ships with it on, and these tests
    # compare the option on against the option off.
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), pack=False,
                ilv_start_cutoff=False)
    opts.update(over)
    with contextlib.redirect_stdout(io.StringIO()):
        return parse_sng(convert(str(CORPUS / f"{stem}.sid"),
                                 log=lambda m: None, **opts))


def _rows(song):
    for p in song.patterns:
        for k in range(0, len(p) - 3, 4):
            if p[k] != 0xFF:
                yield tuple(p[k:k + 4])


def _sid_det(stem):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda m: None)


def test_the_fractional_first_leg_is_two_calls_in_three_and_loops():
    """0.68 of a high-byte step a frame: the cycle (-1, -1, 0) = 0.667."""
    rows = GF._ilv_first_leg_fractional(PROG8, 1)
    assert rows == ((2, 0xFF), (1, 0x00), ("jump", 0)), rows
    # up-going, and per CALL at -S2 (the step is per frame)
    up = bytes.fromhex("24 91 00 AE 4F 06 83 80")
    assert GF._ilv_first_leg_fractional(up, 1)[0] == (2, 0x01)
    assert GF._ilv_first_leg_fractional(PROG8, 2)[-1] == ("jump", 0)


def test_a_whole_number_rate_keeps_the_one_row_leg():
    prog = bytes.fromhex("50 00 02 00 70 10 03 30")        # exactly -2 a frame
    assert (GF._ilv_first_leg_fractional(prog, 1)
            == GF._ilv_first_leg(prog, 1))


def test_the_cycle_travels_the_players_distance():
    """Over 60 frames the player's `$00AE` moves 60 * 174 / 256 = 40.8 high
    steps; the cycle moves 40."""
    rows = GF._ilv_first_leg_fractional(PROG8, 1)
    moved = 0
    for call in range(60):
        n = call % 3
        moved += 1 if n < 2 else 0
    assert abs(moved - 60 * 0xAE / 256) < 1.5
    assert rows[0][0] + rows[1][0] == 3


def test_the_marker_helpers_round_trip():
    note = 0x70
    pat = [note, 9, 0, 166, 0xBD, 0, 0, 0, 0xFF, 0, 0, 0]
    assert GF.strip_start_cutoff_markers([pat])[0][3] == 0
    out = GF.finalize_start_cutoffs([pat])[0]
    assert out[2:4] == [CMD_SETFILTERCUTOFF, 166]
    # a row another pass took keeps its command; the stray data byte is the
    # pass's own and is not touched
    taken = [note, 9, CMD_SETFILTERCTRL, 133, 0xFF, 0, 0, 0]
    assert GF.finalize_start_cutoffs([taken])[0] == taken


@needs_corpus
def test_the_record_every_note_of_which_takes_87_is_exactly_sun_8():
    """Read through `convert`, which hands the reading the patterns an
    orderlist reaches: Sun's 79 `$84` notes sit in patterns 19, 20 and 26 that
    nothing plays and must not disqualify record 8.
    SABOTAGE TARGET: `START_CUTOFF_ENABLED = False` (or dropping `played`)
    empties this."""
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    got = {}
    for name in ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                 "Pacific_Coast", "Radio_ACE", SUN):
        opts = dict(F._preset_opts(doc, f"{name}.sid"), pack=False,
                    ilv_start_cutoff=True)
        logs = []
        with contextlib.redirect_stdout(io.StringIO()):
            convert(str(CORPUS / f"{name}.sid"), log=logs.append, **opts)
        got[name] = [l for l in logs if l.startswith("ILV start cutoffs")]
    assert {n: bool(v) for n, v in got.items()} == {
        "Go_Go_Dash": False, "Lakers_vs_Celtics": False, "Lion_Heart": False,
        "Pacific_Coast": False, "Radio_ACE": False, SUN: True}, got
    assert "[8]" in got[SUN][0], got[SUN]


@needs_corpus
def test_off_by_default_writes_no_cutoff_command_or_marker():
    song = _song()
    rows = list(_rows(song))
    assert not any(r[2] == CMD_SETFILTERCUTOFF for r in rows)
    assert not any(r[2] == 0 and r[3] for r in rows)


@needs_corpus
def test_on_writes_one_command_per_free_note_and_none_beside_a_B():
    off, on = _song(), _song(ilv_start_cutoff=True)
    cut = [r for r in _rows(on) if r[2] == CMD_SETFILTERCUTOFF]
    # 71 distinct values over the rows the patterns share
    assert len(cut) > 150, len(cut)
    assert len({r[3] for r in cut}) > 40, len({r[3] for r in cut})
    # routing untouched: the same CMD_SETFILTERCTRL rows with the same values
    def b_rows(song):
        return sorted(r[3] for r in _rows(song) if r[2] == CMD_SETFILTERCTRL)
    assert b_rows(on) == b_rows(off)
    assert not any(r[2] == 0 and r[3] for r in _rows(on)), "a marker leaked"


@needs_corpus
def test_the_record_table_drops_its_cutoff_row_and_loops_the_leg():
    """The commanded record's block is `modulate, modulate, jump` -- no
    `00 xx` row, which would overwrite the command a tick later -- and the
    record that reloads its own start keeps its cutoff row and ping-pong."""
    song = _song(ilv_start_cutoff=True)
    ftbl = [tuple(r) for r in song.tables["FTBL"]]
    ptrs = sorted({i.filt_ptr for i in song.instruments if i.filt_ptr})
    blocks = {}
    for p in ptrs:
        rows = []
        for r in ftbl[p - 1:]:
            rows.append(r)
            if r[0] == FILT_STOP:
                break
        blocks[p] = rows
    loops = {p: b for p, b in blocks.items() if b[0] == (2, 0xFF)}
    assert loops, blocks
    for p, b in loops.items():
        assert b == [(2, 0xFF), (1, 0x00), (FILT_STOP, p)], (p, b)
    assert any(b[0][0] == FILT_SET_CUTOFF for p, b in blocks.items()
               if p not in loops), "the other record lost its cutoff row"


@needs_corpus
def test_the_switch_short_circuits_the_option(monkeypatch):
    """SABOTAGE TARGET, from the other side: with the reading off the option
    changes nothing and the file converts as it does without it."""
    base = _song()
    monkeypatch.setattr(GF, "START_CUTOFF_ENABLED", False)
    off = _song(ilv_start_cutoff=True)
    assert off.patterns == base.patterns and off.tables == base.tables


@needs_corpus
def test_option_off_leaves_a_file_without_the_record_untouched():
    for name in ("Radio_ACE", "Lion_Heart"):
        a, b = _song(name), _song(name, ilv_start_cutoff=True)
        assert a.patterns == b.patterns and a.tables == b.tables, name
