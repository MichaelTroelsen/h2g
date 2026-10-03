"""The triangle pulse sweep's GT speed is divided by our calls per ORIGINAL
TICK, not by the multiplier alone (`goatwriter._tri_speed`).

The player steps its triangle once per tick -- a play call that passes its
outer gate -- and an outer counter of reload O skips one frame in O + 1. The
GT pulse table steps once per call, `multiplier` calls a frame, so a call per
tick is `multiplier * (O + 1) / O`. The multiplier-only division rested on
convert.py's v0.5.460 "THE SWEEP STEPS PER FRAME" bullet; it is right where
the player has no outer gate and ~11% fast on Game_Killer (-S9, O=9).

Measured on the packed output (see `_tri_speed`'s docstring for the table):
Game_Killer original 200.3 width/frame inside a leg, /9 225.0, /10 198.0.
The control with no gate, One_Man_and_his_Droid, is unchanged by this.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import (GT_MAX_PULSE_SPEED, _phase_sweep_params,  # noqa: E402
                            _pulse_tri_program, _tri_speed,
                            _tri_step_delay, outer_gate_skip)
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent


def _quiet(*_a, **_k):
    pass


# --- the formula --------------------------------------------------------------

def test_the_speed_divides_by_calls_per_tick_where_there_is_an_outer_gate():
    # Game_Killer: $E0 a tick, -S9, O=9 -> 10 calls a tick -> 22 (not 25).
    assert _tri_speed(224, 1, 9, 9) == 22
    # Ninja: $80 a tick, -S1, O=3 -> 4/3 calls a tick -> 96 (not 127).
    assert _tri_speed(128, 1, 1, 3) == 96
    # Samantha_Fox: $20 a tick, -S4, O=4 -> 5 calls a tick -> 6 (not 8).
    assert _tri_speed(32, 1, 4, 4) == 6
    # Spellbound: $60 a tick, -S5, O=10 -> 5.5 calls a tick -> 17 (not 19).
    assert _tri_speed(96, 1, 5, 10) == 17
    # The delay still divides on top of the clock.
    assert _tri_speed(224, 2, 9, 9) == 11


def test_without_an_outer_gate_the_speed_is_the_multiplier_division():
    """The ungated branch is the formula every ungated file shipped with, so
    no ungated carrier (Commando, One_Man_and_his_Droid, ...) moves."""
    for step in range(16, 256, 16):
        for delay in (1, 2, 5, 9, 17, 32):
            for mult in range(1, 10):
                want = min(GT_MAX_PULSE_SPEED,
                           max(1, round(step / (delay * mult))))
                assert _tri_speed(step, delay, mult, None) == want
                assert _tri_speed(step, delay, mult, 0) == want


# --- the seams, on the corpus -------------------------------------------------

# (file, multiplier under presets.json, outer gate reload, record, speed)
_SEAMS = (
    ("Game_Killer.sid", 9, 9, 2, 22),
    ("Ninja.sid", 1, 3, 6, 96),
    ("Samantha_Fox_Strip_Poker.sid", 4, 4, 1, 6),
    ("One_Man_and_his_Droid.sid", 2, None, 14, 112),
)


def _ascending_speed(entries) -> int:
    """The speed byte of the program's first modulation step (an entry whose
    left byte is a tick count, not a set ($80+) or a jump ($FF))."""
    for left, right in entries[1:]:
        if left < 0x80:
            return right if right < 0x80 else 0x100 - right
    raise AssertionError(f"no modulation step in {entries}")


@needs_corpus
def test_the_program_and_the_phase_table_read_the_gate():
    for name, mult, gate, rec, speed in _SEAMS:
        sid = load_sid(str(CORPUS / name))
        det = detect(sid, _quiet)
        assert det.pulse_tri_hi >= 0, name
        assert outer_gate_skip(sid) == gate, (name, outer_gate_skip(sid))
        entries, _ = _pulse_tri_program(sid, det, rec, mult)
        assert _ascending_speed(entries) == speed, (name, entries[:3])
        # The phase table promises the same speed the static program emits.
        assert _phase_sweep_params(sid, det, rec, mult)[1] == speed, name


@needs_corpus
def test_the_gate_reaches_exactly_its_measured_carriers():
    """Every preset song whose triangle speed the gate changes, by name: a
    gate read on a fifth file moves its bytes on no measurement."""
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    moved = set()
    for name, song in doc["songs"].items():
        sid = load_sid(str(CORPUS / name))
        gate = outer_gate_skip(sid)
        if not gate:
            continue
        det = detect(sid, _quiet)
        if det.pulse_tri_hi < 0:
            continue
        mult = song.get("multiplier", 1)
        for i in range(det.instr_used):
            at = det.instr_start + i * det.instr_stride + 6
            if at >= len(sid.data):
                break
            step, delay = _tri_step_delay(det, sid.data[at])
            if step and (_tri_speed(step, delay, mult, gate)
                         != _tri_speed(step, delay, mult, None)):
                moved.add(name)
    assert moved == {"Game_Killer.sid", "Ninja.sid",
                     "Samantha_Fox_Strip_Poker.sid", "Spellbound.sid"}


# --- the measurement ----------------------------------------------------------

_GK = "Game_Killer.sid"
_SECONDS = 120


def _ramp_rate(trace, nframes: int, band: tuple) -> float:
    """Voice 0's width travel per frame inside a sweep leg: between two
    attacks (the attack frame and the next skipped), every frame inside the
    triangle's band and crossing three high nibbles (the accumulate engine
    stays in one), split at direction turns, the turn frames dropped. A hold
    inside a leg counts as a frame of it, so the original's gate-skipped
    frames lower its rate exactly as they do on hardware."""
    import fidelity as F
    t = F.register_timeline(trace[0].pulse_events, nframes)
    atk = sorted({a for a in trace[0].attack_frames if a < nframes}) + [nframes - 1]
    moved = frames = 0
    for a, b in zip(atk, atk[1:]):
        lo = a + 2
        if b - lo < 6 or not all(band[0] <= t[f] < band[1] for f in range(lo, b)):
            continue
        if len({t[f] >> 8 for f in range(lo, b)}) < 3:
            continue
        seg = [t[f + 1] - t[f] for f in range(lo, b - 1)]
        turns, last = [], 0
        for i, x in enumerate(seg):
            if x:
                sign = 1 if x > 0 else -1
                if last and sign != last:
                    turns.append(i)
                last = sign
        for t0, t1 in zip(turns, turns[1:]):
            inner = seg[t0:t1][1:-1]
            moved += sum(abs(x) for x in inner)
            frames += len(inner)
    assert frames > 100, f"only {frames} sweep frames measured"
    return moved / frames


@needs_corpus
def test_game_killers_packed_sweep_travels_at_the_originals_rate():
    """Forced A/B taken at this change: original 200.3, multiplier-only 225.0
    (+12%), calls-per-tick 198.0 (-1%), 120 s. This re-takes our side and
    the original over 120 s and holds the shipped one within 4%."""
    import fidelity as F
    from h2g import convert as C
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    sid_path = CORPUS / _GK
    if not Path(F.SIDDUMP).exists() or not Path(F.GT2RELOC).exists():
        import pytest
        pytest.skip("siddump or gt2reloc not available here")
    opts = F._preset_opts(doc, _GK)
    mult = doc["songs"][_GK]["multiplier"]
    det = detect(load_sid(str(sid_path)), _quiet)
    band = (det.pulse_tri_lo << 8, (det.pulse_tri_hi + 1) << 8)
    nframes = _SECONDS * 50
    wd = Path(tempfile.mkdtemp(prefix="tri_gate_clock_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(sid_path, local)
        cal, _ = F.table_calibration(sid_path, opts)
        sub = F.resolve_subtune(sid_path, "auto")
        orig = F.run_siddump(local, _SECONDS, sub, F.SIDDUMP, cal)
        sng = C.convert(str(sid_path), log=_quiet, **opts)
        blob, _ = F.legalise_restarts(sng)
        packed = F.pack_sid(blob, wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        ours = F.run_siddump(packed, _SECONDS, sub, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    r_orig = _ramp_rate(orig, nframes, band)
    r_ours = _ramp_rate(ours, nframes, band)
    assert 190 <= r_orig <= 210, ("the original's own rate moved", r_orig)
    ratio = r_ours / r_orig
    assert 0.96 <= ratio <= 1.04, (
        f"packed sweep {r_ours:.1f}/frame against the original's "
        f"{r_orig:.1f} ({ratio:.3f}); the multiplier-only clock reads 1.12")
