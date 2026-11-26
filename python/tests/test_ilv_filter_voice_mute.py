"""A `$89` naming a voice that never loads a filter program mutes the filter.

The interleaved player's flush reads cutoff, resonance and passband from the
ONE voice the global `$1A66` names (pattern command `$89 nn`). Pacific_Coast's
single `$89 00` names voice 0, while its one filtered record plays on voice 1,
so the original routes voice 1 for 6 frames (7629-7634 at -t 180) with
passband 0, resonance 0 and no cutoff write. The converter used to emit the
record's own program there -- passband 3, resonance $F, a 17,664-step cutoff
sweep -- and `band` read 0 of 6 union frames. See
`goatwriter.filters.ilv_filter_voice_mute`.
"""
import json
import pathlib

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import FILT_SET_CUTOFF, FILT_SET_PARAMS, FILT_STOP
from h2g.goatwriter.filters import _ilv_programs, ilv_filter_voices

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
ILV = ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart", "Pacific_Coast",
       "Radio_ACE", "Sun_Never_Shines")


def _sid_det(name):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda m: None)


@needs_corpus
def test_each_interleaved_file_names_one_filter_voice():
    """Radio_ACE, Lion_Heart, Go_Go_Dash 02, Sun_Never_Shines 00 (a voice that
    filters); Pacific_Coast 00 (a voice that does not); Lakers has none."""
    got = {n: set(ilv_filter_voices(*_sid_det(n))) for n in ILV}
    assert got == {"Go_Go_Dash": {2}, "Lakers_vs_Celtics": set(),
                   "Lion_Heart": {2}, "Pacific_Coast": {0},
                   "Radio_ACE": {2}, "Sun_Never_Shines": {0}}, got


@needs_corpus
def test_muted_programs_are_a_params_row_with_no_passband_and_no_sweep():
    """SABOTAGE TARGET: ignore `mute` in `_ilv_programs` and Pacific_Coast's
    record keeps passband $30 and its sweep."""
    sid, det = _sid_det("Pacific_Coast")
    real = _ilv_programs(sid, det, det.instr_used, 1)
    muted = _ilv_programs(sid, det, det.instr_used, 1, mute=True)
    assert real and set(muted) == set(real)
    assert all(p[0] == 0x30 for p in real.values())
    assert all(m == (0, 0, 0, ((FILT_STOP, 0x00),)) for m in muted.values())


@needs_corpus
@pytest.mark.skipif(not (PYTHON_ROOT.parent / "presets.json").exists(),
                    reason="presets.json absent")
def test_pacific_coast_filter_table_carries_no_passband_or_sweep():
    """End to end under the shipped presets: every filter row is passband 0
    (`FILT_SET_PARAMS | 0`), a zero cutoff or the stop; the routing nibble
    survives so voice 1 is still routed (`$02`, as the original writes).
    SABOTAGE TARGET: pass `mute=False` at both call sites in
    goatwriter/build.py and the table is `$B0 $02, cutoff, modulate...`."""
    import fidelity as F
    import songview
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    name = "Pacific_Coast.sid"
    blob = convert(str(CORPUS / name), lambda m: None,
                   **F._preset_opts(doc, name))
    rows = songview.parse_sng(bytes(blob)).tables["FTBL"]
    assert rows, "the file lost its filter table"
    for left, right in rows:
        assert (left, right) in {(FILT_SET_PARAMS, 0x02), (FILT_SET_PARAMS, 0),
                                 (FILT_SET_CUTOFF, 0), (FILT_STOP, 0)}, rows
    assert any(left == FILT_SET_PARAMS and right & 0x07 for left, right in rows)
