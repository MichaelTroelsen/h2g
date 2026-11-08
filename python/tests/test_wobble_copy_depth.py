"""`wobble_copy_depth`: a waveform-state copy of a `$68` pattern is sized on
its OWN pitch.

Monty_on_the_Run's opening note (record 13, `$68` -> `$4141`, B-5 on voice 1)
shares its pattern with a later B-6 play; the depth (`sweep_depths`) was
sized once, on the B-6 majority (interval 2000), and the B-5 copy took the
same speed-table entry against B-5's interval of 1000: half the swing. The
original steps `$0540` a frame and siddump names every step a note, so it
prints no bend line over 0-10 s bar the last 50 frames; ours printed 70000 of
voice-2 bend from the small steps. The copy now gets its own depth and the
no-note pattern that follows it (shared with the B-6 voice) is cloned so each
side keeps its own carried index.

A per-song `convert()` option, shipped by Monty_on_the_Run alone, with
`drum_long`. `stored_wave.COPY_DEPTH_EXTRA` is a measured constant (user,
2026-11-08); the ladder is in docs/OPTIONS.md.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import patterns                                     # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter.constants import CMD_VIBRATO             # noqa: E402
from songview import parse_sng                                # noqa: E402

MONTY = CORPUS / "Monty_on_the_Run.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _doc() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(**kw):
    opts = fidelity._preset_opts(_doc(), MONTY.name)
    return convert(str(MONTY), log=lambda m: None, **{**opts, **kw})


def _opening(blob):
    """(speed-table entry of voice 1's first note's vibrato, the vibrato
    indices on the no-note pattern that follows it)."""
    song = parse_sng(blob)
    first, second = song.tracks[1][0], song.tracks[1][1]
    pat = song.patterns[first]
    assert pat[2] == CMD_VIBRATO or pat[6] == CMD_VIBRATO
    idx = next(pat[r + 3] for r in range(0, len(pat) - 3, 4)
               if pat[r + 2] == CMD_VIBRATO)
    nxt = song.patterns[second]
    carried = {nxt[r + 3] for r in range(0, len(nxt) - 3, 4)
               if nxt[r + 2] == CMD_VIBRATO}
    return tuple(song.tables["STBL"][idx - 1]), idx, carried


@needs_corpus
def test_off_keeps_the_majority_depth():
    entry, _idx, _carried = _opening(_convert(drum_long=True,
                                              wobble_copy_depth=False))
    assert entry == (0x86, 0x02)


@needs_corpus
def test_b5_copy_is_sized_on_its_own_interval():
    entry, idx, carried = _opening(_convert(drum_long=True,
                                            wobble_copy_depth=True))
    # 12 quarter-octaves: three octaves off the shift (3 -> 0), the clamp.
    assert entry == (0x84, 0x00)
    # The rest pattern after it keeps the same index (the clone), where the
    # B-6 voice's own pattern keeps ITS index.
    assert carried == {idx}


@needs_corpus
def test_short_circuited_depth_restores_the_majority(monkeypatch):
    monkeypatch.setattr(patterns, "_note_wave_depth",
                        lambda sid, det, i, notes:
                        (getattr(det, "stored_wave_depth", None) or {}
                         ).get(i) if notes else None)
    entry, _idx, _carried = _opening(_convert(drum_long=True,
                                              wobble_copy_depth=True))
    assert entry == (0x86, 0x02)


def test_only_monty_ships_the_option():
    doc = _doc()
    on = sorted(name for name in doc["songs"]
                if fidelity._preset_opts(doc, name).get("wobble_copy_depth"))
    assert on == ["Monty_on_the_Run.sid"]
