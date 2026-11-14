"""A wavetable gate pulse (a drum strike) must survive the hard-restart mask.

The fetch of the next note sets `gate = $FE` `gatetimer` calls before the note
ends (gplay.c:905-940), so a row that raises the gate on call `c` of a note of
`L` calls reaches the chip only when `c < L - gatetimer`. Sun_Never_Shines'
drum record `80 CD / 81 CD / 40 77` raises the gate on call 6 of a ten-call
note (two 5-call rows) and its preset's window of 4 masks it: 150 of voice 0's
921 attacks vanish (melody 91%). `hard_restart.strike_safe_ticks` lowers that
one record's window to 3. At the v0.5.660 tree no other converted corpus file
has a masked pulse (89 converted, 1 moved).
"""
import hashlib
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
import h2g.goatwriter.hard_restart as HR  # noqa: E402

# Sun's record 3, rows 21-31 of its wavetable (wave, note); ptr is 1-based.
SUN_DRUM = [(0x11, 0), (0x81, 0xC2), (0x41, 0x7E), (0x41, 0x7A),
            (0x80, 0xCD), (0x81, 0xCD), (0x40, 0x77), (0x80, 0xC2),
            (0x80, 0xBB), (0x80, 0xBE), (0xFF, 8)]


def test_the_window_is_lowered_below_the_strike():
    # rise on call 6 (row 6 of the program), 10-call note: window <= 3
    assert HR.strike_safe_ticks(SUN_DRUM, 1, 5, 4) == 3


def test_a_window_that_already_clears_the_strike_is_unchanged():
    assert HR.strike_safe_ticks(SUN_DRUM, 1, 5, 3) == 3
    assert HR.strike_safe_ticks(SUN_DRUM, 1, 5, 2) == 2


def test_a_held_gate_is_not_a_strike():
    held = [(0x41, 0), (0x41, 0), (0x41, 0), (0x41, 0), (0x41, 0),
            (0x41, 0), (0x41, 0), (0xFF, 1)]
    assert HR.strike_safe_ticks(held, 1, 5, 4) == 4


def test_a_strike_that_needs_a_window_below_the_floor_is_left_alone():
    # rise on call 8 of a 10-call note would need a window of 1
    prog = [(0x80, 0)] * 7 + [(0x81, 0), (0x80, 0), (0xFF, 1)]
    assert HR.strike_safe_ticks(prog, 1, 5, 4) == 4


def _sun_gatetimers():
    import fidelity as F
    from h2g.convert import convert
    from songview import parse_sng
    presets = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    doc = json.loads(presets.read_text(encoding="utf-8"))
    name = "Sun_Never_Shines.sid"
    # Without prev_class_firstwave (in the preset since v0.5.668): its clones
    # of the drum record carry the drum's lowered window after the records.
    blob = convert(str(CORPUS / name), log=lambda *a, **k: None,
                   **dict(F._preset_opts(doc, name),
                          prev_class_firstwave=False))
    song = parse_sng(blob)
    return [ins.gatetimer & 0x3F for ins in song.instruments], blob


@needs_corpus
def test_sun_never_shines_drum_record_takes_the_lowered_window(monkeypatch):
    got, blob = _sun_gatetimers()
    assert got[2] == 3                       # record 3, the drum
    assert set(got[:2] + got[3:]) == {4}     # every other record keeps 4
    # short-circuited: the old window, and different bytes
    monkeypatch.setattr(HR, "strike_safe_ticks", lambda e, p, r, t: t)
    old, oldblob = _sun_gatetimers()
    assert old[2] == 4
    assert hashlib.sha1(oldblob).digest() != hashlib.sha1(blob).digest()
