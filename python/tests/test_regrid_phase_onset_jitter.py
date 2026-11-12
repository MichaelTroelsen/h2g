"""`regrid_phase` on the onset-jitter songs: rows start on the original's frame.

todo.md "Wave: our attacks sit 1-4 frames off the original's on 11 songs."
Bangkok_Knights, Sigma_Seven, Nemesis_the_Warlock and Trans-Atlantic_Balloon_
Challenge run the sequencer gate `goatwriter.step_durations` reads (an outer
counter that stalls the row counter's reload call once per 127 calls, so a row
of 3 calls lasts 4 whenever a stall falls inside it; Nemesis' rows are 4 or 5).
Read against a 180 s siddump of the original that schedule lands on EVERY
attack of voices 0 and 1 (Bangkok 364/364, 765/765; Sigma 81/81, 87/87;
Nemesis 209/209, 227/227, 254/254; Trans-Atlantic 256/256, 708/708 on voices
0 and 2). `regrid` pays the same debt as evenly spread pairs per PATTERN, so
the converted rows scatter: measured at 64c8265, rows start on the schedule's
frame 11.3% / 18.1% / 17.7% / 24.6% of the time, up to 17 frames off. With
`regrid_phase` 99.8% / 99.5% / 99.6% / 72.8%.

Measured at 64c8265 (`C:/t/wave-attacks-1-4-frames-off/finding.md`).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest                                                # noqa: E402

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO, step_durations      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,  # noqa: E402
                          GT_TRANSPOSE_DOWN, MAX_PATTERNS)
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# name -> (exact share with the option at least, exact share without it at most)
SONGS = {
    "Bangkok_Knights": (0.99, 0.30),
    "Sigma_Seven": (0.99, 0.30),
    "Nemesis_the_Warlock": (0.99, 0.30),
    "Trans-Atlantic_Balloon_Challenge": (0.70, 0.30),
}


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
@pytest.mark.parametrize("name", sorted(SONGS))
def test_rows_start_on_the_originals_frame_with_regrid_phase(name):
    want, _ = SONGS[name]
    sng, logs = _convert(name, regrid_phase=True)
    assert any(m.startswith("Re-grid (phase)") and "compensating" in m
               and " 0 compensating" not in m for m in logs), logs
    share, worst = _exact_share(name, _row_starts(sng))
    assert share >= want, (name, share, worst)


@needs_corpus
@pytest.mark.parametrize("name", sorted(SONGS))
def test_rows_scatter_without_regrid_phase(name):
    _, ceiling = SONGS[name]
    share, worst = _exact_share(
        name, _row_starts(_convert(name, regrid_phase=False)[0]))
    assert share <= ceiling and worst >= 3, (name, share, worst)


@needs_corpus
def test_presets_ship_regrid_phase_with_regrid():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    for name in SONGS:
        entry = doc["songs"][name + ".sid"]
        assert entry.get("regrid_phase") is True, name
        assert entry.get("regrid") is True, name
