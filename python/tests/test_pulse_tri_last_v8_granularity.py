"""Last_V8's voice-0 `pul` count (ours 4718, original 3515, pulse_phase forced)
is a CHANGE-COUNT granularity difference, not a sweep-rate error -- pinned
against both traces.

The task (`last-v8-voice0-pulse-changes-surplus`) asked whether instrument 7's
sweep steps per CALL rather than per FRAME at `-S2`. Measured at 2b64d25
(180 s, pulse_phase forced; `fidelity.py`'s traces of both sides, voice 0, notes
grouped by the ORIGINAL's modal change gap and step):

    class (gap frames, step)   notes   changes orig / ours   travel orig / ours
    (2, 224)  record 7           48    1457 / 2842  (x1.95)  326368 / 315616 (x0.97)
    (2, 64)   record 6          148     841 / 1657  (x1.97)   53824 /  50672 (x0.94)
    (1, 8)    pulse-lo engine   112    1040 /    0           23930 /      0

* The RATE is right. Record 7's rate byte is $E1: step $E0, delay 2 frames,
  so the original moves 224 every second frame = 112 a frame. `_tri_speed`
  gives 56 a call; at `-S2` that is 112 a frame. Record 6 ($41: 64 / 2) is
  32 a frame on both sides.
* The COUNT doubles because the original HOLDS the width for the delay's
  second frame and ours moves on every call. A Goattracker pulse row is
  `(time, speed)` stepping EVERY call (`gplay.c:884-897`); the only hold is a
  speed-0 row. Reproducing the original's cadence at `-S2` is a (1 call, +224)
  row and a (3 calls, 0) row per step, i.e. 7 steps x 2 rows a leg for record
  7 and 21 x 2 for record 6, against 1 row a leg now: ~150 rows for records
  6-8 against a 255-row table the forced Last_V8 build already fills to 223.
  It is the same by-construction excess `_tri_speed`'s docstring records for
  the outer gate ("read `pspan` and the per-frame travel instead").
* The 1.34x total understates it: the third class, 112 notes whose width the
  original moves +8 a frame, was missing from ours entirely, which hid 1040 of
  the 2201 surplus changes. It sweeps since the folded accumulate spelling
  was read (`test_the_pulse_lo_notes_sweep_on_both_sides`).
"""
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402

LAST_V8 = ("Last_V8.sid", "Last_V8_C128_version.sid")
SECONDS = 60
_CACHE: dict = {}


def _sweep_record(name, i):
    from h2g import detect
    from h2g.goatwriter import pulse as P
    from h2g.goatwriter.tempo import outer_gate_skip
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / name))
    det = detect.detect(sid, lambda m: None)
    rec = det.instr_start + i * det.instr_stride
    step, delay = P._tri_step_delay(det, sid.data[rec + 6])
    return sid, det, P, step, delay, outer_gate_skip(sid)


@needs_corpus
@pytest.mark.parametrize("name", LAST_V8)
@pytest.mark.parametrize("record,step,delay", [(6, 64, 2), (7, 224, 2), (8, 128, 2)])
def test_the_speed_per_call_is_the_originals_travel_per_frame(name, record, step, delay):
    """`-S2`: GT speed a call x 2 calls a frame == step / delay a frame."""
    sid, det, P, st, dl, gate = _sweep_record(name, record)
    assert (st, dl) == (step, delay), f"{name} record {record} rate byte moved"
    assert gate is None, "an outer gate would change the clock"
    mult = 2
    speed = P._tri_speed(st, dl, mult, gate)
    assert speed * mult * dl == st, (speed, mult, dl, st)
    program, _ = P._pulse_tri_program(sid, det, record, mult)
    # the shipped program carries that speed on both legs (up: +speed, down:
    # 256 - speed), and no speed-0 hold row anywhere
    ups = [s for t, s in program if t < 0x80]
    assert speed in ups and (256 - speed) in ups and 0 not in ups, program


def _traces(name, pulse_phase):
    key = (name, pulse_phase)
    if key in _CACHE:
        return _CACHE[key]
    import fidelity as F
    from h2g.convert import convert
    presets = Path(__file__).resolve().parents[2] / "presets.json"
    if (not presets.exists() or not Path(F.SIDDUMP).exists()
            or not Path(F.GT2RELOC).exists()):
        pytest.skip("presets.json, siddump or gt2reloc missing")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, name)
    if pulse_phase:
        opts = dict(opts, pulse_phase=True)
    mult = doc["songs"][name].get("multiplier", 1)
    assert mult == 2
    sid = CORPUS / name
    wd = Path(tempfile.mkdtemp(prefix="lv8_gran_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(sid, local)
        cal, _ = F.table_calibration(sid, opts)
        sub = F.resolve_subtune(sid, "auto")
        orig = F.run_siddump(local, SECONDS, sub, F.SIDDUMP, cal)
        blob, _ = F.legalise_restarts(convert(str(sid), log=lambda m: None,
                                              **opts))
        packed = F.pack_sid(blob, wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        ours = F.run_siddump(packed, SECONDS, sub, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    _CACHE[key] = (F, orig, ours)
    return _CACHE[key]


def _classes(F, orig, ours):
    """{(modal gap, modal step) of the ORIGINAL's note: [notes, orig changes,
    ours changes, orig travel, ours travel]} for voice 0, notes paired by
    index (the two sides' attacks name the same notes)."""
    n = SECONDS * 50
    a, b = orig[0], ours[0]
    ta = F.register_timeline(a.pulse_events, n)
    tb = F.register_timeline(b.pulse_events, n)
    fa = [f for f in a.attack_frames if f < n]
    fb = [f for f in b.attack_frames if f < n]
    assert list(a.attacks[:len(fa) - 1]) == list(b.attacks[:len(fa) - 1])
    out: dict = {}
    for i in range(min(len(fa), len(fb)) - 1):          # last note is cut
        ea, eb = fa[i + 1], fb[i + 1]
        ca = [k for k in range(fa[i] + 1, ea) if ta[k] != ta[k - 1]]
        cb = [k for k in range(fb[i] + 1, eb) if tb[k] != tb[k - 1]]
        if len(ca) >= 3:
            gap = Counter(ca[j + 1] - ca[j]
                          for j in range(len(ca) - 1)).most_common(1)[0][0]
            step = Counter(abs(ta[k] - ta[k - 1])
                           for k in ca).most_common(1)[0][0]
            key = (gap, step)
        else:
            key = ("few", 0)
        c = out.setdefault(key, [0, 0, 0, 0, 0])
        c[0] += 1
        c[1] += len(ca)
        c[2] += len(cb)
        c[3] += sum(abs(ta[k] - ta[k - 1]) for k in ca)
        c[4] += sum(abs(tb[k] - tb[k - 1]) for k in cb)
    return out


@needs_corpus
@pytest.mark.parametrize("name", LAST_V8)
@pytest.mark.parametrize("pulse_phase", [False, True])
def test_the_count_doubles_while_the_travel_matches(name, pulse_phase):
    """Every note the original sweeps every SECOND frame is changed on every
    frame by ours (ratio ~2), over the same travel (ratio ~1): the rate is
    right and the cadence is the Goattracker row's. Measured at 2b64d25,
    60 s, both modes: 1.95-1.97 and 0.94-0.97 (180 s)."""
    F, orig, ours = _traces(name, pulse_phase)
    classes = _classes(F, orig, ours)
    for key in ((2, 224), (2, 64)):
        assert key in classes, (key, sorted(classes, key=str))
        notes, co, cb, to, tb = classes[key]
        assert notes >= 10, (key, notes)
        assert 1.8 <= cb / co <= 2.1, (key, "changes", co, cb)
        assert 0.85 <= tb / to <= 1.1, (key, "travel", to, tb)


@needs_corpus
@pytest.mark.parametrize("name", LAST_V8)
@pytest.mark.parametrize("pulse_phase", [False, True])
def test_the_pulse_lo_notes_sweep_on_both_sides(name, pulse_phase):
    """The (1, 8) class: records 2 and 5 carry effect bit $08 (record +6 = 8),
    the accumulate engine, and the original moves their width +8 a frame
    (with `ORA #$40` folded in: $AD33 `AND #$08 / BEQ / LDY / LDA instr,Y /
    ADC rate / ORA #$40 / STA instr,Y / LDY / STA $D402,Y`). RETRACTED: "Ours
    holds the seed: 0 changes" -- true until `detect.PULSE_LO_ORA_SHAPES` read
    the folded spelling (task frozen-pulse-phantoms-ninja-pygmies-nineteen).
    Re-pinned at e0b17bd + that change, 90 s window of `_traces`: 32 notes,
    328 changes on both sides, travel 7498 (C128: 7496) against ours 6608 --
    every frame the original moves ours moves; the travel is short because
    our sweep restarts at the record's width with each note, where the
    player's runs on in the record."""
    F, orig, ours = _traces(name, pulse_phase)
    classes = _classes(F, orig, ours)
    assert (1, 8) in classes, sorted(classes, key=str)
    notes, co, cb, to, tb = classes[(1, 8)]
    assert notes >= 10 and co > 100, (notes, co)
    assert cb == co, (co, cb)
    assert 0.8 <= tb / to <= 1.0, (to, tb)
