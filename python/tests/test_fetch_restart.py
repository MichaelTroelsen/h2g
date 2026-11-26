"""The classic filter sweep restarts on every event its voice fetches.

Knucklebusters' start song (records 19/20, `$0562..$0578`): the fetch path
stores `LDA #$00 / STA cutoff,X` before it tests whether the entry is a note,
so a KEYOFF (or a tie) resets the voice's cutoff accumulator and holds the
frame exactly as a note does. Pattern 73 plays note, KEYOFF, note: the
original sweeps `$1C00 .. $FC00`, holds, and sweeps again from `$1C00`, where
ours knew only the note's strike and ran its one program straight through the
8-bit wrap (60 s, lag 5: cfrm .773 -> .833; `cutoff_sweep` 1.053 -> .986).

`fetch_restart.classic_fetch_restarts` writes a `CMD_SETFILTERPTR` to the live
instrument's own block on the event's row, for every voice, on the event's own
row only.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import CMD_SETFILTERPTR, fetch_restart   # noqa: E402
from songview import parse_sng                               # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
REST, KEYOFF = 0xBD, 0xBE
NOTE = 0x90


def _pat(*rows):
    flat = []
    for r in rows:
        flat += list(r)
    return flat + [0xFF, 0, 0, 0]


def _tracks():
    return [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]


def test_a_keyoff_on_any_voice_restarts_its_live_instruments_block():
    """SABOTAGE TARGET: `voice=0` in `classic_fetch_restarts` and only voice
    0's KEYOFFs restart; this song's sweeping voice is voice 1."""
    patterns = [_pat((REST, 0, 0, 0)),
                _pat((NOTE, 4, 0, 0), (REST, 0, 0, 0), (REST, 0, 0, 0),
                     (REST, 0, 0, 0), (KEYOFF, 0, 0, 0), (REST, 0, 0, 0)),
                _pat((REST, 0, 0, 0))]
    out_p, _out_t, written = fetch_restart.classic_fetch_restarts(
        _tracks(), patterns, {4: 19})
    assert written == 1
    assert out_p[1][4 * 4 + 2:4 * 4 + 4] == [CMD_SETFILTERPTR, 19]


def test_the_restart_goes_on_the_events_own_row_only():
    """SABOTAGE TARGET: `back=3` -- the restart then lands up to three rows
    early, three rows of the wrong cutoff, when the event's column is taken."""
    taken = (KEYOFF, 0, 1, 0x20)           # a running slide owns the column
    patterns = [_pat((REST, 0, 0, 0)),
                _pat((NOTE, 4, 0, 0), (REST, 0, 0, 0), (REST, 0, 0, 0), taken),
                _pat((REST, 0, 0, 0))]
    out_p, _out_t, written = fetch_restart.classic_fetch_restarts(
        _tracks(), patterns, {4: 19})
    assert written == 0 and out_p == patterns


def test_an_instrument_with_no_block_restarts_nothing():
    patterns = [_pat((REST, 0, 0, 0)),
                _pat((NOTE, 5, 0, 0), (REST, 0, 0, 0), (KEYOFF, 0, 0, 0)),
                _pat((REST, 0, 0, 0))]
    out_p, _out_t, written = fetch_restart.classic_fetch_restarts(
        _tracks(), patterns, {4: 19})
    assert written == 0 and out_p == patterns


@needs_corpus
def test_knucklebusters_start_song_restarts_on_its_keyoffs(monkeypatch):
    """SABOTAGE TARGET: `fetch_restart.ENABLED = False` (or drop the call in
    build.py) -- the start song then carries no restart pointer."""
    sid = CORPUS / "Knucklebusters.sid"
    doc = json.load(open(REPO / "presets.json"))
    opts = dict(fidelity._preset_opts(doc, sid.name))

    def pointers(enabled):
        monkeypatch.setattr(fetch_restart, "ENABLED", enabled)
        song = parse_sng(convert(str(sid), log=lambda m: None, **opts))
        n = 0
        for pat in song.patterns:
            for r in range(len(pat) // 4):
                note, _ins, cmd, _dat = pat[4 * r:4 * r + 4]
                if note == KEYOFF and cmd == CMD_SETFILTERPTR:
                    n += 1
        return n

    on, off = pointers(True), pointers(False)
    assert off == 0 and on > 0, (on, off)


# --- the slope gate -----------------------------------------------------------

def test_a_restart_is_withheld_from_a_record_whose_rounded_slope_is_wrong():
    """SABOTAGE TARGET: make `slope_true` return True. Dragons_Lair_Part_II's
    record 22 steps 1 a frame; the table steps 1 a CALL, so at -S3 the sweep
    is three times too fast, and its one restart took `cut` 1.44x -> 1.50x."""
    assert not fetch_restart.slope_true(0x01, 3)
    assert not fetch_restart.slope_true(0xFF, 3)         # -1 a frame
    assert fetch_restart.slope_true(0x1C, 3)             # Knucklebusters +28: 27
    assert fetch_restart.slope_true(0xF0, 3)             # -16: -15
    assert fetch_restart.slope_true(0x00, 3)             # a static record
    assert fetch_restart.slope_true(0x05, 1)             # -S1 is exact


@needs_corpus
def test_dragons_lair_takes_no_restart(monkeypatch):
    """The one instrument that would take a restart sweeps 1 a frame."""
    sid = CORPUS / "Dragons_Lair_Part_II.sid"
    doc = json.load(open(REPO / "presets.json"))
    opts = dict(fidelity._preset_opts(doc, sid.name))

    def blob(enabled):
        monkeypatch.setattr(fetch_restart, "ENABLED", enabled)
        return convert(str(sid), log=lambda m: None, **opts)

    assert blob(True) == blob(False)
