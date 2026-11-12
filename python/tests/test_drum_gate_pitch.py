"""Tarzan's gate-only drum head returns to the played note's pitch.

Records 8, 10 and 11 (effect $45/$65, bit $40) get a gate-off head
(`drum_fall.drum_gate_records`). Their wavetable program clicks at an
absolute pitch (`81` at C-6, `$C8`) for one call and then goes back to the
played note; the head replaces that program from the rest row on, and a head
that KEEPS the frequency (`$80`) leaves the voice on the click's pitch for
the whole release. Subtune 5, voice 2 (the drum voice), original: attack on
the note, one call of `81` at $45A0, then `10` on the note's pitch again.
Measured at cb2d3e3, `fidelity.py -t 180 --presets --sound -a 5`: aud
.7962 with no head, .7876 with the keep-frequency head, .7934 with this one;
subtune 0: aud .9310 -> .9388, tie_ratio .8608 -> .8955.

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
from h2g.goatwriter import drum_fall as DF                   # noqa: E402
from h2g.goatwriter.constants import GT_WAVE_NO_NOTE         # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TARZAN = "Tarzan.sid"
SUBTUNE = 5
SECONDS = 20
CLICK_FREQ = 0x4000          # the $C8 click is C-6, well above the drum notes

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump (tools/siddump-rt) and gt2reloc")


def _opts() -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, TARZAN)


def _clicks(trace, n: int, voice: int = 1) -> list[int]:
    """Frames where the voice switches the noise waveform on at the click
    pitch."""
    v = trace[voice]
    fr = fidelity.register_timeline(v.freq_events, n)
    wf = fidelity.register_timeline(v.wf_events, n)
    return [f for f in range(1, n)
            if wf[f] & 0x80 and not wf[f - 1] & 0x80 and fr[f] >= CLICK_FREQ]


def _back_on_the_note(trace, clicks, lag: int, n: int, voice: int = 1) -> int:
    """Clicks after which the next call's frequency is the pre-click one."""
    fr = fidelity.register_timeline(trace[voice].freq_events, n + 60)
    return sum(abs(fr[c + 1 + lag] - fr[c - 1 + lag]) <= 0x40 for c in clicks)


def _measure(tmp_path: pathlib.Path):
    opts = _opts()
    sid = CORPUS / TARZAN
    local = tmp_path / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = fidelity.table_calibration(sid, opts)
    orig = fidelity.run_siddump(local, SECONDS, SUBTUNE, fidelity.SIDDUMP, cal)
    n = SECONDS * 50
    where = tmp_path / "ours"
    where.mkdir()
    sng, _ = fidelity.legalise_restarts(
        convert(str(sid), log=lambda m: None, **opts))
    packed = fidelity.pack_sid(sng, where, fidelity.GT2RELOC, 1)
    assert packed is not None
    ours = fidelity.run_siddump(packed, SECONDS + 1, SUBTUNE,
                                fidelity.SIDDUMP)
    lag, _ = fidelity.startup_lag(orig, ours)
    oc, uc = _clicks(orig, n), _clicks(ours, n + 60)
    return orig, ours, oc, uc, lag, n


@needs_corpus
@needs_tools
def test_every_click_is_followed_by_the_note_pitch(tmp_path):
    orig, ours, oc, uc, lag, n = _measure(tmp_path)
    assert len(oc) >= 5, oc
    # the original returns to the note on the very next call, always
    assert _back_on_the_note(orig, oc, 0, n) == len(oc)
    # and so is ours, on every click it makes (its clicks need not be the
    # original's: subtune 5's melody is 91%)
    mine = [c - lag for c in uc if 0 < c - lag < n]
    assert len(mine) >= 5, mine
    assert _back_on_the_note(ours, mine, lag, n) == len(mine)


@needs_corpus
@needs_tools
def test_a_keep_frequency_head_leaves_clicks_on_the_click_pitch(
        tmp_path, monkeypatch):
    # the change short-circuited: the head keeps the frequency again
    monkeypatch.setattr(DF, "DRUM_GATE_HEAD_NOTE", GT_WAVE_NO_NOTE)
    _orig, ours, _oc, uc, lag, n = _measure(tmp_path)
    clicks = [c - lag for c in uc if c - lag > 0]
    assert clicks
    assert _back_on_the_note(ours, clicks, lag, n) < len(clicks)
