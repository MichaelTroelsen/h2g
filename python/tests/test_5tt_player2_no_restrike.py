"""5_Title_Tunes player 2 (subtune 2), voices 0 and 1: no extra note at attack index 19.

Task `five-title-tunes-player2-extra-note`. The record that opened it
(triangle-sim-model-fails-on-rasputin-and-one-man, at 3b1c66d) said both voices
play one note the original does not, at attack index 19, and that it was the
only miss there (19/20). MEASURED 2026-10-05 at 8586101 (historical): the note
is the one `one-man-restrike-at-attack-856` removed at v0.5.510 -- a slide event
after a bit-5 (tied) note, which `_build_raw_pattern` used to hand the command
column and so re-struck. Frames, packed at -S1 and traced 180 s, original (o)
against ours (c):

    voice 0, index 19 C-5:   o 660                 c 668 and again at 692
    voice 1, index 19 E-4:   o 660                 c 668 and again at 692

The original strikes once and slides; the pre-fix converter struck twice, 24
frames apart. The whole subtune went 1639 attacks against the original's 1627
(sequence 0.9963) to 1627 against 1627 (sequence 1.0). The same row repeats
(ours indices 66/136/182/252/299, voice 0 B-4 and C-5), six extra strikes a
voice in 180 s.

The test is the converter-level property, not the trace (no siddump needed): the
walk's note list for that player. Switching the tied-slide branch off puts 116
notes in it, with C-5/C-5 and E-4/E-4 at indices 19-20.
"""
import json
import sys
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_ROOT.parent
NAME = "5_Title_Tunes.sid"
NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-"]
PLAYER = 2          # walk call index == subtune of the appended player


def _player_notes():
    """(planned-or-not) note names the walk sees, per voice, for player 2."""
    sys.path.insert(0, str(PYTHON_ROOT))
    import fidelity
    from h2g import convert as C, patterns as P
    presets = REPO_ROOT / "presets.json"
    if not presets.exists():
        pytest.skip("presets.json not available here")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    kwargs = fidelity._preset_opts(doc, NAME)
    kwargs["pulse_phase"] = True
    calls: list = []
    real = C.collect_pulse_phases

    def spy(pats, tracks, *a, **kw):
        r = real(pats, tracks, *a, **kw)
        calls.append((pats, [list(t) for t in tracks], r))
        return r
    C.collect_pulse_phases = spy
    try:
        C.convert(str(CORPUS / NAME), log=lambda m: None, **kwargs)
    finally:
        C.collect_pulse_phases = real
    assert len(calls) > PLAYER, "the walk was not entered once per player"
    pats, tracks, plan = calls[PLAYER]
    assert plan, "player 2 has no pulse plan"
    out = []
    for v in range(3):
        notes, live = [], 0
        for b in tracks[v]:
            if b == P.GT_ORDER_RESTART:
                break
            if b >= P.MAX_PATTERNS or b >= len(pats):
                continue
            for r, kind, instr in P._phase_note_rows(pats[b], live, {}):
                if instr:
                    live = instr
                if kind != "note" or pats[b][4 * r + 2] == P.CMD_TONEPORTA:
                    continue
                nn = pats[b][4 * r] - P.GT_FIRSTNOTE
                notes.append(f"{NAMES[nn % 12]}{nn // 12}")
        out.append(notes)
    return out


@needs_corpus
def test_player_2_voices_0_and_1_strike_the_slid_note_once():
    v0, v1, _ = _player_notes()
    # Original attack sequence of subtune 2, siddump 180 s (frames 624/636/660/
    # 768/804): ... B-4 B-4 C-5 G-4 F-4 ... and ... F-4 F-4 E-4 F-4 D-4 ...
    assert v0[17:23] == ["B-4", "B-4", "C-5", "G-4", "F-4", "A-4"]
    assert v1[17:23] == ["F-4", "F-4", "E-4", "F-4", "D-4", "G-4"]
    assert len(v0) == len(v1) == 114      # 116 with the tied-slide branch off
