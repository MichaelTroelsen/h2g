"""Food_Feud voice 2's tie deficit is a startup-row phase, not a rounded tempo.

Under `pitch_seq` forced, voice 2's ties were 3562 against the original's 3696
(parse_dump, 180 s, 82d60ac: 133 of the 3695 in the paired notes). The windows
between attacks were one frame SHORT on 339 notes and one frame LONG on 339 (the
attack offset ours - original was 3 on 693 notes, 4 on 348): gt2reloc's 18-call
startup row at -S3 puts a third of our rows a frame after the original's, and
the short windows lose the tie their last frame carried. The rate is exact, so
the error is a constant phase and no tempo rounding is in it.

`call_phase.startup_phase` (jmp-form-outer-gate-clock, v0.5.519) now writes a
17-call row for Food_Feud, and every window is the original's length: 3626 ties,
a residual 69 that is NOT the grid -- on 67 11-frame notes (and 2 22-frame
ones) the tie on the window's last frame is the next note's tick-0 init call
(firstwave `$09`, AD/SR `29F9`), the last call of that frame at -S3, which the
original runs in the attack frame itself (the init-visible-at-phase-m-1 effect
of tests/test_gate_off_firstwave_call_phase.py).

Measured 2026-10-09 on 9d1ff22: C:/t/food-feud-voice2-row-grid-tie-deficit/.
"""
import json
import pathlib
import sys
from collections import Counter

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import h2g.convert as convert_module                         # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAME = "Food_Feud.sid"
SECONDS = 60
VOICE = 1

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _voice2(tmp_path, startup: bool, monkeypatch):
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    mult = fidelity._preset_multiplier(doc, NAME)
    opts = dict(fidelity._preset_opts(doc, NAME), pitch_seq=True)
    if not startup:
        monkeypatch.setattr(convert_module, "startup_phase",
                            lambda *a, **k: None)
    sng = convert_module.convert(str(CORPUS / NAME), log=lambda m: None,
                                 **opts)
    sng, _ = fidelity.legalise_restarts(sng)
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=mult)
    assert packed is not None and packed.exists()
    return fidelity.run_siddump(packed, SECONDS, 0, calls=mult)[VOICE]


def _windows(orig, ours):
    oa, ua = orig.attack_frames, ours.attack_frames
    ot, ut = set(orig.tie_frames), set(ours.tie_frames)
    n = min(len(oa), len(ua)) - 1
    assert n > 200
    for k in range(n):
        yield (oa[k + 1] - oa[k], ua[k + 1] - ua[k], ua[k] - oa[k],
               [t - oa[k] for t in range(oa[k], oa[k + 1]) if t in ot],
               [t - ua[k] for t in range(ua[k], ua[k + 1]) if t in ut])


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_voice_2_windows_are_the_originals_and_the_tie_loss_is_the_last_frame(
        tmp_path, monkeypatch):
    orig = fidelity.run_siddump(CORPUS / NAME, SECONDS, 0)[VOICE]
    ours = _voice2(tmp_path, True, monkeypatch)
    rows = list(_windows(orig, ours))
    assert Counter(lu - lo for lo, lu, *_ in rows) == {0: len(rows)}
    assert len({lag for _, _, lag, *_ in rows}) == 1
    differing = [(lo, so, su) for lo, _, _, so, su in rows if so != su]
    at_end = [d for d in differing
              if set(d[1]) - set(d[2]) == {d[0] - 1} and set(d[2]) <= set(d[1])]
    assert len(at_end) > 10
    # One 27-frame note moves a tie by a frame (7 -> 6): not the grid either.
    assert len(differing) - len(at_end) <= 1, differing


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_without_the_startup_row_a_third_of_the_windows_are_a_frame_off(
        tmp_path, monkeypatch):
    orig = fidelity.run_siddump(CORPUS / NAME, SECONDS, 0)[VOICE]
    ours = _voice2(tmp_path, False, monkeypatch)
    rows = list(_windows(orig, ours))
    delta = Counter(lu - lo for lo, lu, *_ in rows)
    assert set(delta) == {-1, 0, 1}, delta
    assert delta[-1] == delta[1] > len(rows) // 5   # rate exact, phase off
    short = [(lo, so, su) for lo, lu, _, so, su in rows if lu < lo]
    assert any(len(su) < len(so) for _, so, su in short)
