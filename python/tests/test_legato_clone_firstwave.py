"""A `note_flag` legato clone does not write its waveform on the init call.

`goatwriter.build_sng`'s `clone_firstwave`: a tied note's legato clone of a
record that starts on the test bit (firstwave `$09`) used to take the record's
waveform with the gate (`waveform | 1`). Goattracker's init call writes only
that byte -- the pitch arrives with the first wavetable call, one call later
(player.s `mt_loadregswaveonly`) -- so a held voice whose waveform register
the previous note's effect had moved (a drum's `$11 -> $81`, a gate an effect
had closed) took the record's waveform and gate on the OLD pitch one frame
before the original does, which writes waveform and pitch on the one fetch.
Where the clone's wavetable opens with a waveform entry, the clone now takes
firstwave 0 ("no change", gplay.c:355) and that entry writes the waveform,
the gate and the pitch together -- the rule the classic restart family has
had since `tie_restart` (tests/test_tie_restart.py).

Trace that found it (Trans-Atlantic_Balloon_Challenge, sub 0, voice 2, packed
with gt2reloc and traced with siddump-rt, presets, 180 s, HISTORICAL --
2026-10-12 at 6f346b6): the old clone had the register go `$11 -> $41` at
frames 6494, 6592, 6883 and 6981 while the pitch still read `$7C10`; the
original moves waveform and pitch in one frame, and so does the new clone.
On the 17 movers the `wave` column moves by at most 4e-4 either way.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.convert import convert
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _song(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / name), log=lambda m: None,
                  **fidelity._preset_opts(doc, name))
    return parse_sng(sng)


def _clones(song):
    """(clone, base) for every legato clone that has a record to be a clone
    of: same name and wavetable pointer, the legato bit on top."""
    plain = [i for i in song.instruments if not i.gatetimer & G.GATETIMER_LEGATO]
    out = []
    for c in song.instruments:
        if not c.gatetimer & G.GATETIMER_LEGATO:
            continue
        for b in plain:
            if (b.name == c.name and b.wave_ptr == c.wave_ptr
                    and c.gatetimer == b.gatetimer | G.GATETIMER_LEGATO):
                out.append((c, b))
                break
    return out


def _opens_on_a_waveform(song, ins):
    first = song.tables["WTBL"][ins.wave_ptr - 1][0]
    return G.GT_WAVE_LAST_DELAY < first < G.GT_WAVE_FIRST_CMD


@needs_corpus
def test_trans_atlantic_clones_leave_the_waveform_to_the_wavetable():
    song = _song("Trans-Atlantic_Balloon_Challenge.sid")
    pairs = _clones(song)
    # 6 until v0.5.550, whose room-aware pitch-seq phase clones add two more
    # legato clones (Trans-Atlantic gets 5 phase clones there); every one of
    # the 8 still leaves its waveform to the wavetable.
    assert len(pairs) == 8
    for clone, base in pairs:
        assert base.firstwave == G.FIRSTWAVE_TESTBIT
        assert _opens_on_a_waveform(song, clone)
        assert clone.firstwave == 0, clone


@needs_corpus
def test_a_clone_whose_wavetable_opens_on_a_delay_keeps_the_waveform_byte():
    """Sanxion's second clone is of a record whose first wavetable entry is a
    delay: firstwave 0 would leave the whole first call unwritten, so it keeps
    the record's own waveform byte with the gate (the old rule)."""
    song = _song("Sanxion.sid")
    pairs = _clones(song)
    assert len(pairs) == 2
    delays = [(c, b) for c, b in pairs if not _opens_on_a_waveform(song, c)]
    assert len(delays) == 1
    clone, base = delays[0]
    assert base.firstwave == G.FIRSTWAVE_TESTBIT
    assert clone.firstwave == 0x01
    waves = [(c, b) for c, b in pairs if _opens_on_a_waveform(song, c)]
    assert len(waves) == 1 and waves[0][0].firstwave == 0


@needs_corpus
def test_a_record_with_a_real_firstwave_keeps_it_on_its_clone():
    """Monty's preset writes real firstwaves, so its clones are untouched --
    they copy the base record's byte."""
    song = _song("Auf_Wiedersehen_Monty.sid")
    pairs = _clones(song)
    assert pairs
    for clone, base in pairs:
        assert base.firstwave != G.FIRSTWAVE_TESTBIT
        assert clone.firstwave == base.firstwave


@needs_corpus
def test_commando_is_not_a_legato_family_player_and_does_not_move():
    ref = (REPO_ROOT / "Commando.sng").read_bytes()
    assert convert(str(REPO_ROOT / "Commando.sid"),
                   log=lambda m: None) == ref
