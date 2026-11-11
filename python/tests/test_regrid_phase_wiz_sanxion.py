"""`regrid_phase` on Wiz and Sanxion: rows start on the original's frame.

Both run the player `goatwriter.step_durations` reads (an outer counter that
stalls the row counter's reload call, 127 calls on Wiz and Sanxion alike, so a
row of 3 calls lasts 4 whenever a stall falls inside it). Read against a 180 s
siddump of the original, the schedule lands on every attack of every voice:
Wiz 673/673, 559/559, 420/420 (all at row-start + 2), Sanxion 442/442,
827/827, 1238/1238 (row-start + 3). `regrid` pays the same debt as evenly
spread pairs per PATTERN and Wiz's patterns are shared and replayed, so its
rows land -11..+3 frames from the original's (19.1% exact) and Sanxion's
-35..0 (0.9% exact).

The convert.py gate used to read `len(values) == 1`, which kept Wiz (three
subtunes, the traced one is subtune 0) out: `schedule_of` now answers for
subtune 0 whatever the subtune count, and None for the others.

Measured at 64c8265 (`C:/t/attack-scatter-phase-drift-wiz-worst/finding.md`).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO, step_durations      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,  # noqa: E402
                          GT_TRANSPOSE_DOWN, MAX_PATTERNS)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _convert(name, **force):
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name + ".sid")
    opts.update(force)
    logs = []
    sng = convert(str(CORPUS / (name + ".sid")), log=logs.append, **opts)
    return sng, logs


def _row_starts(sng_bytes):
    sng = songview.parse_sng(sng_bytes)
    plays, rep = [], 1
    for b in sng.tracks[0]:
        if b == GT_ORDER_RESTART:
            break
        if GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
            rep = b - GT_REPEAT + 1
        elif b < MAX_PATTERNS:
            plays += [b] * rep
            rep = 1
    starts, frame, tempo = [], 0, None
    for p in plays:
        pat = sng.patterns[p]
        for r in range(len(pat) // 4):
            note, _ins, cmd, dat = pat[r * 4:r * 4 + 4]
            if note == GT_END_PATTERN:
                break
            if cmd == CMD_SETTEMPO and dat < 0x80:
                tempo = dat
            starts.append(frame)
            frame += tempo or 6
    return starts


def _exact_share(name, starts):
    dur = step_durations(load_sid(str(CORPUS / (name + ".sid"))), len(starts))
    ideal = [0]
    for d in dur:
        ideal.append(ideal[-1] + d)
    n = min(len(starts), len(ideal))
    off = [starts[i] - ideal[i] for i in range(n)]
    return sum(1 for x in off if x == 0) / n, max(abs(x) for x in off)


@needs_corpus
def test_wiz_with_three_subtunes_reads_a_schedule_and_clones_for_it():
    sng, logs = _convert("Wiz", regrid_phase=True)
    line = next((m for m in logs if m.startswith("Re-grid (phase)")
                 and "compensating" in m), "")
    assert "compensating row(s) in" in line and " 0 compensating" not in line, logs
    share, worst = _exact_share("Wiz", _row_starts(sng))
    assert share > 0.99 and worst <= 1, (share, worst)


@needs_corpus
def test_wiz_without_it_scatters_over_a_dozen_frames():
    share, worst = _exact_share("Wiz", _row_starts(_convert("Wiz", regrid_phase=False)[0]))
    assert share < 0.3 and worst >= 8, (share, worst)


@needs_corpus
def test_sanxion_rows_start_on_the_originals_frame_with_regrid_phase():
    share, worst = _exact_share("Sanxion", _row_starts(_convert("Sanxion", regrid_phase=True)[0]))
    assert share > 0.99 and worst <= 1, (share, worst)


@needs_corpus
def test_sanxion_without_it_drifts_tens_of_frames():
    share, worst = _exact_share("Sanxion", _row_starts(_convert("Sanxion", regrid_phase=False)[0]))
    assert share < 0.05 and worst > 20, (share, worst)


@needs_corpus
def test_presets_ship_regrid_phase_for_both():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    for name in ("Wiz.sid", "Sanxion.sid"):
        assert doc["songs"][name].get("regrid_phase") is True, name
        assert doc["songs"][name].get("regrid") is True, name
