"""Task `auf-wiedersehen-voice2-interval`: a planned-note reader applies the
orderlist's transpose state before it compares names with an original.

The walk-same-note-pair census (runs.jsonl, 6e467ff) listed Auf_Wiedersehen_Monty
subtune 0 voice 2 and subtune 6 voice 2 as "a transposed voice": name alignment
against the original's attacks failed while 849 of 855 pitch INTERVALS matched.
Nothing was wrong with the playback. The reader took each pattern's note byte
as the pitch, and Goattracker's orderlist transposes ($E0-$FE) on top of it, so
a voice under a changing transpose came out a changing interval from what the
original sounds.

Measured at 8618f82 (shipped presets, `pulse_phase` forced so the walk runs,
the walk's own patterns and tracks, original traced with siddump at -t 180):

    subtune 0 voice 2   planned 1802 notes, original 856 attacks
        pattern bytes alone  625 / 856 names equal   (transposes seen
                             +0 x1284, +2 x225, +9 x144, +6 x86, +8 x39, +10 x24)
        transpose applied    856 / 856
    subtune 6 voice 2   planned 54, original 54
        pattern bytes alone    6 / 54
        transpose applied     54 / 54

`songview.planned_notes` is the reader. The corpus test is the one that fails
if the transpose application is reverted; the synthetic ones pin the mechanism
without the corpus.
"""
import json
import sys
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity as F  # noqa: E402
import songview  # noqa: E402
from h2g import convert as C  # noqa: E402
from h2g.patterns import (CMD_TONEPORTA, GT_END_PATTERN,  # noqa: E402
                          GT_FIRSTNOTE, GT_ORDER_RESTART, GT_REPEAT,
                          GT_TRANSPOSE_UP)

AUF = "Auf_Wiedersehen_Monty.sid"


def _pat(*notes, cmds=None):
    """One pattern, instrument 1 on the first row, ended by GT_END_PATTERN."""
    rows = []
    for i, n in enumerate(notes):
        rows += [GT_FIRSTNOTE + n, 1 if i == 0 else 0,
                 (cmds or {}).get(i, 0), 0]
    return rows + [GT_END_PATTERN, 0, 0, 0]


def _names(notes):
    return [n[3] for n in notes]


def test_transpose_is_added_to_every_following_pattern():
    pats = [_pat(12, 14)]                     # C-1 D-1
    track = [0, GT_TRANSPOSE_UP + 2, 0, GT_TRANSPOSE_UP - 12, 0,
             GT_TRANSPOSE_UP, 0, GT_ORDER_RESTART, 0]
    assert _names(songview.planned_notes(pats, track)) == [
        "C-1", "D-1",                         # no transpose yet
        "D-1", "E-1",                         # +2
        "C-0", "D-0",                         # -12 replaces +2, it does not stack
        "C-1", "D-1"]                         # back to +0


def test_untransposed_reading_keeps_the_pattern_names():
    pats = [_pat(0, 2)]
    track = [GT_TRANSPOSE_UP + 2, 0, GT_ORDER_RESTART, 0]
    assert _names(songview.planned_notes(pats, track, transpose=False)) == ["C-0", "D-0"]
    assert _names(songview.planned_notes(pats, track)) == ["D-0", "E-0"]


def test_transpose_crosses_an_octave():
    pats = [_pat(10)]                         # A#0
    track = [GT_TRANSPOSE_UP + 3, 0, GT_ORDER_RESTART, 0]
    assert _names(songview.planned_notes(pats, track)) == ["C#1"]


def test_repeat_plays_the_pattern_again_under_the_same_transpose():
    pats = [_pat(0)]
    track = [GT_TRANSPOSE_UP + 1, GT_REPEAT + 1, 0, 0, GT_ORDER_RESTART, 0]
    assert _names(songview.planned_notes(pats, track)) == ["C#0", "C#0", "C#0"]


def test_toneporta_rows_are_not_strikes():
    pats = [_pat(0, 2, 4, cmds={1: CMD_TONEPORTA})]
    track = [0, GT_ORDER_RESTART, 0]
    assert _names(songview.planned_notes(pats, track)) == ["C-0", "E-0"]
    assert _names(songview.planned_notes(pats, track, skip_toneporta=False)) == [
        "C-0", "D-0", "E-0"]


def _walk_capture(name):
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    kw = F._preset_opts(doc, name)
    kw["pulse_phase"] = True
    calls = []
    real = C.collect_pulse_phases

    def spy(pats, tracks, *a, **k):
        r = real(pats, tracks, *a, **k)
        calls.append((pats, [list(t) for t in tracks]))
        return r

    C.collect_pulse_phases = spy
    try:
        C.convert(str(CORPUS / name), log=lambda *a, **k: None, **kw)
    finally:
        C.collect_pulse_phases = real
    assert calls, "the pulse walk never ran for " + name
    return doc, calls[0]


@needs_corpus
@pytest.mark.skipif(not Path(F.SIDDUMP).exists(), reason="siddump.exe not built")
@pytest.mark.parametrize("group, voice, count", [(0, 2, 856), (6, 2, 54)])
def test_auf_wiedersehen_voice_2_names_equal_the_originals_attacks(
        tmp_path, group, voice, count):
    doc, (pats, tracks) = _walk_capture(AUF)
    seconds = 180
    local = tmp_path / AUF
    local.write_bytes((CORPUS / AUF).read_bytes())
    cal, _ = F.table_calibration(CORPUS / AUF, F._preset_opts(doc, AUF))
    tr = F.run_siddump(local, seconds, group, F.SIDDUMP, cal)
    nf = seconds * 50
    orig = [tr[voice].attacks[k] for k, f in enumerate(tr[voice].attack_frames)
            if f + 1 < nf]
    assert len(orig) == count, "the trace length moved; re-measure"
    track = tracks[3 * group + voice]
    plan = _names(songview.planned_notes(pats, track))[:len(orig)]
    assert len(plan) == len(orig)
    assert plan == orig
    # and the old reading really is a different list on this voice
    raw = _names(songview.planned_notes(pats, track, transpose=False))[:len(orig)]
    assert sum(a == b for a, b in zip(raw, orig)) < len(orig)
