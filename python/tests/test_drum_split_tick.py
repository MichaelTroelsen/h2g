"""The split tick: a ticked nibble-arpeggio record's noise frames after the first.

The player's drum block writes its noise as `LDA #$80 / STA $D404,Y`, gate
clear on every tick frame: Bump_Set_Spike's original reads `41 80 80 40` from
each `$090A` onset. Above -S1 the conversion writes the whole tick gated
(`_drum_tick_noise`), because a gate-off first frame releases the voice before
the SID's ADSR delay has let the attack start (loud_ratio 1.009 -> .804 on
Bump_Set_Spike). The converter keeps the first tick frame gated -- which
carries the gate past 520 lines at every -S >= 2 -- and writes the noise runs
that start at call `multiplier` or later gate-off, without adding an entry.

Unconditional since task decide-thrust-unconditional-split-tick; the
`drum_split_tick` option is inert. Measured at v0.5.674 (task
listen-sub99-bump-set-spike, -t 180 --presets --sound, option forced on): Bump_Set_Spike gate .728 -> .767, heard instr
.390 -> .613, International_Karate gate .897 -> .928, Thrust .869 -> .879,
Kentilla unmoved; no printed column falls on any of the four.
"""
import contextlib
import io
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.goatwriter import _first_frame_lead
from h2g.goatwriter.arpeggio import ticked_nibble_arp_entries
from h2g.goatwriter.constants import WAVE_NOISE_GATEOFF

REPO = Path(__file__).resolve().parents[2]
WAVE, NOISE, ALT = 0x41, 0x81, 0x74


def _entries(m, tick, half, up, first_calls, multiplier=None):
    frame0, frame0_r = _first_frame_lead(WAVE, m, force=True)
    return ticked_nibble_arp_entries(
        frame0, frame0_r, tick, NOISE, WAVE, ALT, half, up, first_calls, 6,
        255, multiplier=m if multiplier is None else multiplier)


def test_at_one_call_a_frame_nothing_is_gate_off():
    """SABOTAGE TARGET: dropping the `multiplier > 1` guard writes -S1 tick
    frames gate-off."""
    left, _ = _entries(1, 2, 2, False, 2)
    assert WAVE_NOISE_GATEOFF not in left


@pytest.mark.parametrize("m, half", [(3, 3), (2, 2), (10, 10), (7, 7)])
def test_the_second_tick_frame_loses_the_gate_and_the_first_keeps_it(m, half):
    """Per call: the first `m` noise calls are `$81`, the rest of the tick
    `$80`. SABOTAGE TARGET: dropping the `lo >= multiplier` bound writes the
    first frame gate-off too (the arm that costs Bump_Set_Spike .20 of
    loud_ratio), and dropping `wave == noise` would rewrite the tail."""
    from test_call_rate import wave_timeline
    tick = 2 * m
    left, right = _entries(m, tick, half, False, half)
    plain_l, plain_r = _entries(m, tick, half, False, half, multiplier=1)
    assert len(left) == len(plain_l), "no entry may be added"
    assert right == plain_r
    calls = wave_timeline(left, right, first=6, calls=m + tick + 4 * half)
    waves = [w for _, w, _ in calls]
    assert waves[:m] == [WAVE] * m                      # the lead
    assert waves[m:2 * m][0] == NOISE                   # first tick frame: gated
    assert all(w & 1 for w in waves[m:m + min(m, half)])
    assert set(waves[2 * m:m + tick]) <= {WAVE_NOISE_GATEOFF}
    assert set(waves[m + tick:]) == {WAVE}              # the tail is untouched


def test_the_tail_that_shares_a_run_with_the_tick_is_not_rewritten():
    """A tick that ends inside a run leaves the run's rest on the record's own
    waveform. SABOTAGE TARGET: dropping `wave == noise` writes it gate-off."""
    from test_call_rate import wave_timeline
    m, tick, half = 3, 4, 3
    left, right = _entries(m, tick, half, False, half)
    waves = [w for _, w, _ in wave_timeline(left, right, first=6,
                                            calls=m + tick + 2 * half)]
    assert waves[m:2 * m] == [NOISE] * m, waves
    assert waves[2 * m:m + tick] == [WAVE_NOISE_GATEOFF] * (tick - m), waves
    assert set(waves[m + tick:]) == {WAVE}, waves


def test_a_run_straddling_the_frame_boundary_stays_gated():
    """A first run longer than a frame starts at call 0 < `multiplier`, so it
    is one noise row and keeps the gate for all of it (a split would need an
    extra entry, which the split does not spend)."""
    from test_call_rate import wave_timeline
    m, half = 7, 8
    left, right = _entries(m, 2 * m, half, False, half)
    calls = wave_timeline(left, right, first=6, calls=m + 2 * m)
    waves = [w for _, w, _ in calls]
    assert waves[m:m + half] == [NOISE] * half, waves
    assert set(waves[m + half:m + 2 * m]) == {WAVE_NOISE_GATEOFF}, waves


def test_a_one_frame_tick_has_nothing_to_split():
    """The tick of Game_Killer, Warhawk and Proteus is one frame: the whole
    tick is the frame that must stay gated, so the split leaves it alone."""
    for m in (3, 7):
        left, _ = _entries(m, m, m, False, m)
        assert WAVE_NOISE_GATEOFF not in left


def _song(stem, **over):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), **over)
    with contextlib.redirect_stdout(io.StringIO()):
        return parse_sng(convert(str(CORPUS / f"{stem}.sid"),
                                 log=lambda m: None, **opts))


def _program(song, ad, sr, nth=0):
    ins = [i for i in song.instruments if (i.ad, i.sr) == (ad, sr)]
    assert len(ins) > nth, f"no instrument {ad:02X}{sr:02X}: the test is blind"
    rows, p = [], ins[nth].wave_ptr - 1
    while song.tables["WTBL"][p][0] != 0xFF:
        rows.append(tuple(song.tables["WTBL"][p]))
        p += 1
    return rows


def _lefts(song, ad, sr):
    return [l for l, _ in _program(song, ad, sr)]


@needs_corpus
def test_bump_set_spike_090a_writes_noise_gated_then_gate_off():
    """Instrument 2 (`$090A`, effect `$C5`) is the record behind 498 of the
    original's 499 voice-1 `$090A` notes: the first noise frame stays `$81`,
    the second is `$80`, also with the (inert) preset key forced False.
    SABOTAGE TARGET: dropping `multiplier=multiplier` at the wavetable call
    site leaves both `$81`."""
    for over in ({}, {"drum_split_tick": False}):
        lefts = _lefts(_song("Bump_Set_Spike", **over), 0x09, 0x0A)[:6]
        assert lefts.count(NOISE) == 1, lefts
        assert lefts.count(WAVE_NOISE_GATEOFF) == 1, lefts


@needs_corpus
def test_thrust_0f0a_writes_noise_gated_then_gate_off():
    """Thrust has no preset key for the split and still gets it: instrument
    `$0F0A` (the voice-0 drum) reads `129 129 128` in the original."""
    lefts = _lefts(_song("Thrust"), 0x0F, 0x0A)
    assert lefts[:6] == [0x81, 0x01, 0x81, 0x01, WAVE_NOISE_GATEOFF, 0x01], lefts
