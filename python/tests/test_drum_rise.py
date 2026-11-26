"""A drum record that also rises keeps the rise where the arpeggio overwrites
the sweep (task listen-sub99-kentilla).

Kentilla `$04` (`+7 = $07`: drum `$01` + rise `$02` + arpeggio `$04`, nibble 0,
ADSR `$340B`) is played by voice 1 on 48 notes in 180 s. The player runs the
drum block, the rise block (`INC note,X` once in four working frames) and the
arpeggio block, whose zero-nibble write takes the frequency from the note
index the rise has just raised, so the note climbs a semitone at a time,
`G-6 G#6 A-6 ... E-7`, 9 steps in 38 frames. `_wavetable_entries` took the
drum-only shape for it (the sweep is overwritten, the rise had no slots) and
the climb never sounded: 99,408 units of voice-1 travel against the
original's 1,021,013, `travel` 0.27x on the file.

The climb is emitted as note entries, one `+k` semitone step each, because a
looped `CMD_PORTAUP` glide has the right travel but siddump prints each of its
calls as a `(+ xxxx)` bend where the original's steps are ties (`bend` read
0.96x -> 3.76x on the same file). Figures are historical (v0.5.674 + this
change, -t 180 under presets); the assertions are the mechanism.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter import FORMAT_GTS5                          # noqa: E402
from h2g.goatwriter import wavetable                            # noqa: E402
from h2g.goatwriter.wavetable import (_drum_entries,            # noqa: E402
                                      _drum_rise_step_calls)

# Kentilla at -S10: a 12-row note of 33-call rows, outer gate reload 10.
STEPS = _drum_rise_step_calls(10, 10, 12 * 33)


def _entries(rise_calls, budget=118):
    return _drum_entries(0x15, FORMAT_GTS5, [], 10, 12, sustain=0,
                         budget=budget, tick_frames=2, note_rows=12,
                         row_calls=33, gate_skip=10, sweep=False,
                         rise_calls=rise_calls)


def _walk(left, right):
    """{call: right byte} for each note entry the program reaches, calls
    counted from the note's first. A delay entry (1..15) holds for value + 1
    calls; the waveform and note entries take one; $FF with right 0 stops."""
    out, call = {}, 0
    for l, r in zip(left, right):
        if l == 0xFF:
            break
        if 0 < l <= 15:
            call += l + 1
            continue
        if r != 0x80:
            out[call] = r
        call += 1
    return out


def test_the_steps_follow_the_players_cadence():
    """One step in four working frames, 4 * (O + 1) / O = 4.4 frames at O 10,
    from the mode of Kentilla's 48 notes (frames 2 7 11 15 20 24 29 33 37)."""
    assert STEPS == [f * 10 for f in (2, 7, 11, 15, 20, 24, 29, 33, 37)]


def test_no_note_length_no_steps():
    assert _drum_rise_step_calls(10, 10, None) is None
    assert _drum_rise_step_calls(10, 10, 0) is None


def test_a_note_too_short_for_the_first_step_has_none():
    assert _drum_rise_step_calls(10, 10, 20) is None


def test_every_step_lands_on_its_call_with_its_semitone():
    left, right = _entries(STEPS)
    notes = {c: r for c, r in _walk(left, right).items() if r}
    # The first step's frame is 2, but the noise tick and the gate-off entry
    # hold the first 28 calls (10 + 17 + 1), so it goes on the next call, still
    # inside frame 2 (calls 20-29); the rest are exact.
    (first, one), *rest = notes.items()
    assert one == 1 and 20 <= first < 30
    assert dict(rest) == {c: k for k, c in enumerate(STEPS, start=1)
                          if k > 1}


def test_the_program_stops_after_the_last_step_and_fits_its_budget():
    left, right = _entries(STEPS)
    assert left[-1] == 0xFF or 0xFF in left
    assert left.index(0xFF) <= 118


def test_a_small_budget_drops_the_late_steps_not_the_early_ones():
    left, right = _entries(STEPS, budget=20)
    got = [r for r in _walk(left, right).values() if r]
    assert got == list(range(1, len(got) + 1)) and 0 < len(got) < len(STEPS)
    assert left.index(0xFF) <= 20


def test_without_rise_calls_the_shape_is_the_flat_drum():
    flat_l, flat_r = _entries(None)
    assert not [r for r in _walk(flat_l, flat_r).values() if r]
    base = _drum_entries(0x15, FORMAT_GTS5, [], 10, 12, sustain=0, budget=118,
                         tick_frames=2, note_rows=12, row_calls=33,
                         gate_skip=10, sweep=False)
    assert (flat_l, flat_r) == base


def _converted(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng[0] if isinstance(sng, tuple) else sng


def _program(song, ad, sr):
    ins = [i for i in song.instruments
           if (i.ad, i.sr) == (ad, sr) and not i.gatetimer & 0x40]
    assert len(ins) == 1, [(i.number, i.adsr) for i in song.instruments]
    wt = song.tables["WTBL"]
    k = ins[0].wave_ptr - 1
    left, right = [], []
    while wt[k][0] != 0xFF:
        left.append(wt[k][0])
        right.append(wt[k][1])
        k += 1
    return left + [0xFF], right + [0x00]


@needs_corpus
def test_kentilla_record_4_climbs_nine_semitones():
    sys.path.insert(0, str(PYTHON_ROOT))
    import songview
    left, right = _program(songview.parse_sng(_converted("Kentilla")),
                           0x34, 0x0B)
    steps = {c: r for c, r in _walk(left, right).items() if r}
    assert list(steps.values()) == list(range(1, 10)), (left, right)


@needs_corpus
def test_the_seam_restores_the_flat_drum(monkeypatch):
    sys.path.insert(0, str(PYTHON_ROOT))
    import songview
    monkeypatch.setattr(wavetable, "_DRUM_RISE", False)
    left, right = _program(songview.parse_sng(_converted("Kentilla")),
                           0x34, 0x0B)
    assert not [r for r in _walk(left, right).values() if r], (left, right)


@needs_corpus
def test_the_record_is_what_the_docstring_says():
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / "Kentilla.sid"))
    det = detect(sid, lambda m: None)
    assert det.effect_drum and det.effect_rise and det.effect_arp
    assert not det.arp_fixed_up
    rec = bytes(sid.data[det.instr_start + 4 * det.instr_stride:
                         det.instr_start + 5 * det.instr_stride])
    assert (rec[3], rec[4], rec[7]) == (0x34, 0x0B, 0x07), rec
