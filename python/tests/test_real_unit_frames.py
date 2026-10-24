"""`_real_unit_frames`: the drum gate's first unit in REAL frames under `drum_gate_off`.

Deep_Strike's speed gate is 2 working calls and an outer counter (reload 3)
skips the play routine on every fourth call, so a duration unit lasts 3 real
frames on two thirds of notes and 2 on the rest (`SongSpeeds.true_frames`
2.667). The drum block's gate mask closes when the first unit ends, and the
original's voice-2 `$0F07` record reads `11 11 81 10 80` (three frames) on 84
of 126 hits. `_noise_tick_frames` returned the gate less one -- 1 -- so the
conversion gated two frames, `11 11 80`, and `noise_run_agreement` (noise AND
gate) had no run of ours to pair with the original's: .75 -> .50 when
`drum_gate_off` was adopted.

Own file: reads no shared fixture.
"""
import json
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import _noise_tick_frames, _real_unit_frames  # noqa: E402
from h2g.goatwriter.tempo import SongSpeeds                  # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEEP_STRIKE = "Deep_Strike.sid"
SECONDS = 30

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump (tools/siddump-rt) and gt2reloc")


def _speeds(frames, skip):
    return SongSpeeds(frames=(frames,), reload_addr=0, table_addr=None,
                      skip=(skip,))


@pytest.mark.parametrize("frames,skip,want", [
    (2, 3, 3),      # Deep_Strike, Food_Feud, Zoolook: 2.667 -> 3
    (3, 10, 3),     # 3.3 -> 3
    (2, 4, 2),      # 2.5 is an exact tie: keeps the gate's own reading
    (2, 8, 2),      # 2.25
    (4, 10, 4),     # 4.4
    (3, 3, 4),      # 4.0: a whole extra frame
    (2, 2, 3),      # 3.0
    (2, None, 2),   # no outer counter: untouched
    (2, 0, 2),
])
def test_unit_is_the_nearest_whole_frame_ties_down(frames, skip, want):
    assert _real_unit_frames(_speeds(frames, skip), 0, frames) == want


def test_no_speeds_keeps_the_gate():
    assert _real_unit_frames(None, 0, 2) == 2


def test_never_below_the_gate():
    for f in (1, 2, 3, 5):
        for s in (1, 2, 3, 9, 127):
            assert _real_unit_frames(_speeds(f, s), 0, f) >= f


@needs_corpus
def test_deep_strike_tick_reads_three_frames_only_under_the_option():
    sid = load_sid(str(CORPUS / DEEP_STRIKE))
    det = detect(sid, lambda m: None)
    assert det.drum_gate_off is False
    assert _noise_tick_frames(sid, det) == 1
    det.drum_gate_off = True
    assert _noise_tick_frames(sid, det) == 2


@needs_corpus
def test_a_file_without_an_outer_counter_is_unmoved_by_the_option():
    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    det = detect(sid, lambda m: None)
    off = _noise_tick_frames(sid, det)
    det.drum_gate_off = True
    assert _noise_tick_frames(sid, det) == off == 2


def _opts() -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, DEEP_STRIKE)


@needs_corpus
@needs_tools
def test_deep_strike_noise_runs_pair_with_the_original(tmp_path):
    sid = CORPUS / DEEP_STRIKE
    opts = dict(_opts(), drum_gate_off=True)
    sub, our_sub, _ = fidelity.resolve_pair(sid, "auto")
    local = tmp_path / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = fidelity.table_calibration(sid, opts)
    orig = fidelity.run_siddump(local, SECONDS, sub, fidelity.SIDDUMP, cal)
    sng, _ = fidelity.legalise_restarts(
        convert(str(sid), log=lambda m: None, **opts))
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    mult = fidelity._preset_multiplier(doc, DEEP_STRIKE)
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, mult,
                               original=sid)
    assert packed is not None, "gt2reloc wrote no .sid"
    ours = fidelity.run_siddump(packed, SECONDS, our_sub, fidelity.SIDDUMP,
                                calls=mult)
    n = SECONDS * 50
    a, b = fidelity.noise_runs(orig, n), fidelity.noise_runs(ours, n)
    # Both drum records are gated-noise instruments on BOTH sides: before
    # the change ours had no noise-AND-gate run on `$0F07`/`$0F09` at all.
    assert 0x0F07 in a and 0x0F07 in b
    assert 0x0F09 in a and 0x0F09 in b
    res = fidelity.noise_run_agreement(orig, ours, n)
    assert res["noise_run_instruments"] >= 3
    assert res["noise_run_agreement"] >= 0.75
