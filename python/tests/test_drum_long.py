"""`drum_long`: the bit-$01 drum sweep on notes longer than the record's median.

Monty_on_the_Run record 1 (`00 08 81 02 08 .. .. 01`, a bit-$01 drum) is played
at four rows (G-5, 440 plays) and two (G-6 / G-7, 880 plays). The player's
block (`$82DE`) sweeps the frequency high byte down one a call from the second
unit of a note and not at all on a two-unit note, so the original's G-5 falls
`3426 -> 3326 -> 3226 -> 3126` on frames +3..+5 and its G-6 / G-7 stay put.
`median_played_durations` is 2, `_drum_duration_steps(2, ...)` is 0 and the
record's one wavetable program carries no sweep: the original's ~8K of voice-2
bend per 10 s over 40-60, 70-100, 110-120 and 150-180 s (91136 of 445006 file
bend) never reached the chip.

A per-song `convert()` option, shipped by Monty_on_the_Run and Devils_Galop.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import drum_long                         # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,       # noqa: E402
                                      GT_WAVE_JUMP, WAVECMD_PORTADOWN)
from songview import parse_sng                                # noqa: E402

MONTY = CORPUS / "Monty_on_the_Run.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _doc() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(**kw):
    opts = fidelity._preset_opts(_doc(), MONTY.name)
    return convert(str(MONTY), log=lambda m: None, **{**opts, **kw})


def _heads(blob):
    """(pattern, row) of every row whose SETWAVEPTR names a drum_long head:
    gate-off hold entries, a jump into a PORTADOWN chain ending in a stop."""
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    found = []
    for pi, pat in enumerate(song.patterns):
        for r in range(0, len(pat) - 3, 4):
            if pat[r + 2] != CMD_SETWAVEPTR:
                continue
            at = pat[r + 3]                       # 1-based wavetable row
            holds = 0
            while wave[at - 1 + holds] == (0x80, 0x80):
                holds += 1
            if not holds or wave[at - 1 + holds][0] != GT_WAVE_JUMP:
                continue
            target = wave[at - 1 + holds][1]
            n = 0
            while wave[target - 1 + n][0] == WAVECMD_PORTADOWN:
                n += 1
            if n and wave[target - 1 + n][0] == GT_WAVE_JUMP:
                found.append((pi, r // 4, holds, n))
    return found


@needs_corpus
def test_off_emits_no_head():
    assert _heads(_convert(drum_long=False)) == []


@needs_corpus
def test_long_g5_notes_get_a_six_step_sweep():
    heads = _heads(_convert(drum_long=True))
    # Ten rows in two shared patterns; a four-row note at four calls a row
    # and two a frame sweeps (4 - 2) * 4 - 2 = 6 calls of $0080, after
    # `multiplier + 1` calls holding the gate-off waveform.
    assert len(heads) == 10
    assert {(h, n) for _p, _r, h, n in heads} == {(3, 6)}


@needs_corpus
def test_short_circuited_plan_emits_nothing(monkeypatch):
    monkeypatch.setattr(drum_long, "drum_long_plan", lambda *a, **k: None)
    assert _heads(_convert(drum_long=True)) == []


def test_only_monty_and_devils_galop_ship_the_option():
    doc = _doc()
    on = sorted(name for name in doc["songs"]
                if fidelity._preset_opts(doc, name).get("drum_long"))
    # International_Karate also carries such a record but moved within noise
    # on every column at 1ee1557, so it stays off until measured on its own.
    assert on == ["Devils_Galop.sid", "Monty_on_the_Run.sid"]
