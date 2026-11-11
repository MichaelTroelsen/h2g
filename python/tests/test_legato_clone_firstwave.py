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
from monty_fixture import pinned_preset_opts  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _song(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / name), log=lambda m: None,
                  **pinned_preset_opts(doc, name))
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
        # The testbit, or since v0.5.588 (its preset names 1..62 in
        # `gate_off_firstwave_instruments`) the record's waveform with the
        # gate CLEAR (`instruments.gate_off_firstwave`): either way not a
        # gated waveform a clone could copy.
        assert base.firstwave == G.FIRSTWAVE_TESTBIT or (
            base.firstwave >= 0x10 and not base.firstwave & 0x01), base
        assert _opens_on_a_waveform(song, clone)
        assert clone.firstwave == 0, clone


@needs_corpus
def test_sanxions_zero_record_clone_keeps_the_free_running_byte():
    """Sanxion's second clone is of record 08 (waveform $00), whose first
    wavetable entry was a delay; it keeps the base's gate-ON firstwave byte
    (`firstwave_of` copies any gated byte but the testbit). Since
    `instruments.park_free_running` that block opens on $E0 (silent wave
    $00), a waveform entry like any other, so both clones now OPEN on a
    waveform -- yet the zero record's clone still takes the base's $01, the
    early return, not the wavetable rule. No corpus clone opens on a delay any
    more; the delay branch of `firstwave_of` is not pinned by a corpus file."""
    song = _song("Sanxion.sid")
    pairs = _clones(song)
    assert len(pairs) == 2
    assert all(_opens_on_a_waveform(song, c) for c, _b in pairs)
    # The base is record 08, waveform $00: since
    # sanxion-free-running-first-wave-adoption (2026-11-07) a record with no
    # select bit gets the free-running $01, not the testbit, so its oscillator
    # runs for the ring/sync neighbour as the original's ctrl $00 does.
    zero = [(c, b) for c, b in pairs if b.firstwave == G.FIRSTWAVE_FREERUN]
    assert len(zero) == 1
    clone, base = zero[0]
    assert song.tables["WTBL"][base.wave_ptr - 1][0] == G.WAVE_SILENT_BASE
    assert clone.firstwave == 0x01, clone
    others = [(c, b) for c, b in pairs if (c, b) != (clone, base)]
    assert len(others) == 1 and others[0][0].firstwave == 0


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
