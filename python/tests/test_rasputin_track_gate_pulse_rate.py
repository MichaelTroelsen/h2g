"""A triangle sweep under an outer gate the TRACK reloads (Rasputin's `$FE nn`)
takes the clock its record sounds at (`pulse.track_set_tick_ratios`).

`outer_gate_skip` returns None for Rasputin -- R is 2, 3, 5, 10, 60, 120, 6, 2
along subtune 0 -- so `_tri_speed` divided its sweep by `multiplier` alone:
128 width a frame against an original that runs 128 * R / (R + 1). Measured
at 0d18fce, 310 s, voice 0, all sweep frames with holds counted, per section:
85.3, 96.0, 105.1, 114.6, 125.7, 127.5 for R 2, 3, 5, 10, 60, 120. Record 0
sounds 3.1, 2.8, 12.3, 10.6, 14.0 and 58.1 s under those R, which weighs the
original to 121.0 a frame; the shipped packed ramp was 128.0, this change's
is 122.0. One speed per record cannot follow R, so the per-section error
stays (+43% at R = 2, -4% at R = 120).
"""
import json
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import (pulse as pulse_mod,              # noqa: E402
                            _pulse_tri_program, _tri_speed,
                            track_set_tick_ratios)
from h2g.goatwriter.constants import CMD_SETTEMPO            # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent
_RAS = "Rasputin.sid"
_SECONDS = 180


def _quiet(*_a, **_k):
    pass


def _ras():
    sid = load_sid(str(CORPUS / _RAS))
    return sid, detect(sid, _quiet)


# --- the formula --------------------------------------------------------------

def test_a_tick_ratio_scales_the_calls_a_tick_and_a_gate_wins_over_it():
    # Rasputin record 0: step 128 every tick, -S2
    assert _tri_speed(128, 1, 2, None) == 64
    assert _tri_speed(128, 1, 2, None, Fraction(1057, 1000)) == 61
    assert _tri_speed(224, 1, 2, None, Fraction(1008, 1000)) == 111
    # an immediate-reload gate (Game_Killer, -S9, O = 9) is read as before
    assert _tri_speed(224, 1, 9, 9, Fraction(2)) == _tri_speed(224, 1, 9, 9) == 22


def test_a_ratio_of_one_is_the_old_division():
    for step in (32, 64, 96, 128, 224):
        for delay in (1, 2, 5, 22):
            for mult in (1, 2, 3, 4, 9):
                assert (_tri_speed(step, delay, mult, None, Fraction(1))
                        == _tri_speed(step, delay, mult, None)), (step, delay, mult)


# --- the walk ------------------------------------------------------------------

def _pat(rows):
    """rows: [(note, instrument, command, data)], closed by the end marker."""
    out = []
    for r in rows:
        out += list(r)
    return out + [0xFF, 0, 0, 0]


REST = (0xBD, 0, 0, 0)


def _note(instr, cmd=0, data=0):
    return (0x60, instr, cmd, data)


@needs_corpus
def test_the_ratio_is_calls_over_ticks_summed_through_every_tempo_command():
    """Pattern 0 plays T = 6 for two rows then T = 4 for two (the second set
    mid-pattern, where `_compensate_fractional_rows` writes its remainders);
    pattern 1 plays T = 4 throughout. Eight rows, one note on each pattern's
    row 0 (held four rows): 12 + 8 + 16 = 36 calls for 8 rows."""
    sid, det = _ras()
    from h2g.goatwriter import find_song_speeds
    frames = find_song_speeds(sid, det).frames_for(0)
    p0 = _pat([_note(1, CMD_SETTEMPO, 6), REST, (0xBD, 0, CMD_SETTEMPO, 4), REST])
    p1 = _pat([_note(1, CMD_SETTEMPO, 4), REST, REST, REST])
    p2 = _pat([REST, REST, REST, REST, REST, REST, REST, REST])
    tracks = [[0, 1, 0xFF, 0], [2, 2, 0xFF, 0], [2, 2, 0xFF, 0]]
    got = track_set_tick_ratios(sid, det, tracks, [p0, p1, p2], 0, 2)
    assert set(got) == {0}
    assert got[0] == Fraction(36, 8 * frames * 2)


@needs_corpus
def test_a_clock_faster_than_the_gates_own_is_clamped_to_one():
    """Never a ratio under 1: a tick cannot take fewer calls than a row's
    `frames * multiplier`, and the tempo floor (3) can push a command under
    that only by clamping."""
    sid, det = _ras()
    from h2g.goatwriter import find_song_speeds
    frames = find_song_speeds(sid, det).frames_for(0)
    assert frames * 2 > 3, "the probe needs a row clock above the tempo floor"
    p = _pat([_note(1, CMD_SETTEMPO, 3), REST])
    q = _pat([REST, REST])
    got = track_set_tick_ratios(sid, det, [[0, 0xFF, 0], [1, 0xFF, 0], [1, 0xFF, 0]],
                                [p, q], 0, 2)
    assert got == {0: Fraction(1)}


@needs_corpus
def test_it_declines_where_the_outer_gate_is_not_the_tracks():
    p = _pat([_note(1, CMD_SETTEMPO, 9), REST])
    q = _pat([REST, REST])
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [1, 0xFF, 0]]
    # Game_Killer: an immediate reload (`outer_gate_skip` = 9), no `$FE nn`
    gk = load_sid(str(CORPUS / "Game_Killer.sid"))
    assert track_set_tick_ratios(gk, detect(gk, _quiet), tracks, [p, q], 0, 9) == {}
    # Commando: no outer gate at all
    c = load_sid(str(CORPUS / "Commando.sid"))
    assert track_set_tick_ratios(c, detect(c, _quiet), tracks, [p, q], 0, 1) == {}


@needs_corpus
def test_only_rasputin_reads_a_track_set_gate():
    """The corpus population this reaches, by name: a gate read on another
    file moves its bytes on no measurement."""
    from h2g.goatwriter import outer_gate_skip
    reached = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = detect(sid, _quiet)
        except Exception:
            continue
        if det.track_fe_command and outer_gate_skip(sid) is None:
            reached.append(path.name)
    assert reached == [_RAS]


# --- the converter ---------------------------------------------------------------

def _convert_ras(monkeypatch):
    from h2g import convert as C
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, _RAS)
    seen = {}
    real = pulse_mod.track_set_tick_ratios

    def spy(*a, **k):
        seen["ratios"] = real(*a, **k)
        return seen["ratios"]
    monkeypatch.setattr(pulse_mod, "track_set_tick_ratios", spy)
    lines = []
    sng = C.convert(str(CORPUS / _RAS), log=lines.append, **opts)
    return sng, seen["ratios"], lines, doc


@needs_corpus
def test_rasputins_sweeping_records_get_the_clock_they_sound_at(monkeypatch):
    """Record 0 (step 128, sounds mostly under R = 120) 1.057, record 11
    (step 224, only under R = 120) 1.008; the program's speed follows."""
    _sng, ratios, lines, _doc = _convert_ras(monkeypatch)
    assert Fraction(103, 100) < ratios[0] < Fraction(108, 100), ratios[0]
    assert Fraction(1) <= ratios[11] < Fraction(102, 100), ratios[11]
    assert any(l.startswith("Pulse sweep clock") for l in lines)
    sid, det = _ras()
    for rec, want in ((0, 61), (11, 111)):
        entries, loop = _pulse_tri_program(sid, det, rec, 2, tick_ratio=ratios[rec])
        speeds = {s for t, s in entries[loop:] if s < 0x80 and t < 0x80}
        assert want in speeds, (rec, want, entries)
    # and not without it: the shipped division
    entries, loop = _pulse_tri_program(sid, det, 0, 2)
    assert 64 in {s for t, s in entries[loop:] if s < 0x80}


# --- the measurement ----------------------------------------------------------

def _ramp_rate(trace, nframes: int, band: tuple):
    """Voice 0's width travel per frame inside a sweep leg (see
    test_pulse_tri_gate_clock._ramp_rate): the turn frames dropped, holds
    counted; returns (rate, legs)."""
    import fidelity as F
    t = F.register_timeline(trace[0].pulse_events, nframes)
    atk = sorted({a for a in trace[0].attack_frames if a < nframes}) + [nframes - 1]
    moved = frames = legs = 0
    for a, b in zip(atk, atk[1:]):
        lo = a + 2
        if b - lo < 6 or not all(band[0] <= t[f] < band[1] for f in range(lo, b)):
            continue
        if len({t[f] >> 8 for f in range(lo, b)}) < 3:
            continue
        seg = [t[f + 1] - t[f] for f in range(lo, b - 1)]
        nz = [x for x in seg if x]
        if len(nz) < len(seg) / 2 or max(abs(x) for x in nz) > 0x400:
            continue
        turns, last = [], 0
        for i, x in enumerate(seg):
            if x:
                sign = 1 if x > 0 else -1
                if last and sign != last:
                    turns.append(i)
                last = sign
        for t0, t1 in zip(turns, turns[1:]):
            inner = seg[t0:t1][1:-1]
            if inner:
                moved += sum(abs(x) for x in inner)
                frames += len(inner)
                legs += 1
    assert legs >= 6, f"only {legs} legs measured"
    return moved / frames, legs


@needs_corpus
def test_rasputins_packed_sweep_travels_at_the_originals_weighted_rate(monkeypatch):
    """Our side re-taken over 180 s: the complete legs' ramp is the emitted
    speed times the multiplier exactly (turn frames excluded), 122.0 where the
    shipped division read 128.0. The target is the original's per-section
    rates weighed by the time record 0 sounds in each (see the module
    docstring): 121.0. Held within 3%, which 128.0 (+5.8%) is not."""
    import fidelity as F
    sng, _ratios, _lines, doc = _convert_ras(monkeypatch)
    if not Path(F.SIDDUMP).exists() or not Path(F.GT2RELOC).exists():
        pytest.skip("siddump or gt2reloc not available here")
    mult = doc["songs"][_RAS]["multiplier"]
    sid, det = _ras()
    band = (det.pulse_tri_lo << 8, (det.pulse_tri_hi + 1) << 8)
    wd = Path(tempfile.mkdtemp(prefix="ras_track_gate_"))
    try:
        blob, _ = F.legalise_restarts(sng)
        packed = F.pack_sid(blob, wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        sub = F.resolve_subtune(CORPUS / _RAS, "auto")
        ours = F.run_siddump(packed, _SECONDS, sub, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    rate, _legs = _ramp_rate(ours, _SECONDS * 50, band)
    assert 121.0 * 0.97 <= rate <= 121.0 * 1.03, (
        f"packed sweep {rate:.1f}/frame; the original's weighted rate is 121.0 "
        f"and the multiplier-only division read 128.0")
