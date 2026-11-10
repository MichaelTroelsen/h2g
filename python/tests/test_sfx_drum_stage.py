"""The sfx drum's burst on a record that also sets bit $04 (the attack waveform).

IK+'s pulse+drum records (`+2 = $41`, `+7 = $A4`, stage waveform `$81` for 2
frames) read `41 81 81 40` in the original's trace: the hit on frame 1 and the
stage's second frame on frame 2, at the played note, before the record's own
waveform returns. 1274 of its 1487 voice-2 noise runs are 2 frames long; the
program that wrote `41 81 41 40` had every run 1 frame and `nrun` fell
100% -> 75% (`C:/t/ik-plus-sub99-priority/ab_ph_vs_base.txt`).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter.drums import _sfx_drum_entries           # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_stage_frames_follow_the_hit_in_the_prologue_the_loop_skips():
    left, right, loop = _sfx_drum_entries(0x41, 0x48, 6, stage_wave=0x81,
                                          stage_frames=2)
    # frame 0 the record's own wave; frame 1 the hit; frame 2 the stage at the
    # played note; then the rest of the period held
    assert left[:3] == [0x41, 0x81, 0x81] and right[1] != 0 and right[2] == 0
    # the loop starts on the next hit and does not repeat the stage
    assert left[loop] == 0x81 and right[loop] == right[1]
    assert left[loop + 1] != 0x81


def test_without_a_stage_the_hit_is_one_frame_as_before():
    plain = _sfx_drum_entries(0x41, 0x48, 6)
    assert plain == _sfx_drum_entries(0x41, 0x48, 6, stage_wave=None,
                                      stage_frames=0)
    assert plain == _sfx_drum_entries(0x41, 0x48, 6, stage_wave=0x81,
                                      stage_frames=1)
    assert plain[0][:3] == [0x41, 0x81, 0x41]


def _a4_programs(stage):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "IK_plus.sid")
    opts["sfx_drum"] = True
    opts["sfx_drum_stage"] = stage
    sng = songview.parse_sng(convert(str(CORPUS / "IK_plus.sid"),
                                     log=lambda m: None, **opts))
    wtbl = sng.tables["WTBL"]
    return {ins.name: [l for l, _r in wtbl[ins.wave_ptr - 1:ins.wave_ptr + 2]]
            for ins in sng.instruments
            if ins.name.endswith("-A4") and ins.wave_ptr}


@needs_corpus
def test_ik_plus_pulse_and_drum_alone_records_hold_noise_two_frames():
    firsts = _a4_programs(True)
    # records 1 (pulse+drum) and 8 (drum alone, test-bit wave): `wave, noise, noise`
    assert len(firsts) == 2, firsts
    for name, seq in firsts.items():
        assert seq[1:] == [0x81, 0x81], (name, seq)


@needs_corpus
def test_without_sfx_drum_stage_the_same_records_hold_noise_one_frame():
    firsts = _a4_programs(False)
    assert len(firsts) == 2, firsts
    for name, seq in firsts.items():
        assert seq[1] == 0x81 and seq[2] != 0x81, (name, seq)
