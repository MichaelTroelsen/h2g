"""Thrust's opening: one 8-second note on all three voices, vibrato counters
at three different phases in the original (dip-thrust-0, aud .71-.74 over
seconds 0-7 against .93 after).

Traced (siddump-rt -a0 -v1, PAL), voice 1 / 2 / 3 at frames 5-11:

    original  v1 3DD6 4120 446A 4120 3DD6 3A8C 3742
              v2 3742 33F8 30AE 33F8 3742 3A8C 3DD6
              v3 3742 3A8C 3DD6 4120 446A 4120 3DD6
    ours      v1 = v2 = v3 on every frame, and at call 338 (the KEYOFF row's
              `CMD_TONEPORTA 00` one row on) all three re-centred to 3A8D.

Two causes, each alone worth nothing (aud .9136 -> .9134 and .9128), both
together .9136 -> .9213 (scoped, confuzion-keyoff-untie-scope): the offset between the voices
(`unison_vibrato.MEASURED_START`) and the retie on the rest that follows
(`rest_ring_pass(untie_instruments=)`, classic engine, held instrument with a vibrato).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import unison_vibrato as uv                         # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
THRUST = "Thrust.sid"
GT_KEYOFF, CMD_TONEPORTA = 190, 3


def _opts(on):
    doc = json.loads(PRESETS.read_text())
    return dict(fidelity._preset_opts(doc, THRUST), unison_vibrato_phase=on)


def _sid():
    sid = load_sid(str(CORPUS / THRUST))
    return sid, detect(sid, lambda m: None)


@needs_corpus
def test_the_three_voices_are_offset_by_the_measured_start():
    sid, det = _sid()
    blob = convert(str(CORPUS / THRUST), log=lambda m: None, **_opts(False))
    # Voice 1 leads; voice 2 starts 6 updates behind it (half of the
    # 12-update period), voice 3 two behind (traced shifts 7 and 2 frames).
    assert uv.doubled_note_delays(blob, sid, det) == {
        (1, 0, 0, 0): (27, 6), (2, 0, 0, 0): (27, 2)}


@needs_corpus
def test_the_table_is_what_declines_without_it(monkeypatch):
    sid, det = _sid()
    blob = convert(str(CORPUS / THRUST), log=lambda m: None, **_opts(False))
    monkeypatch.setattr(uv, "MEASURED_START", {})
    assert uv.doubled_note_delays(blob, sid, det) == {}


@needs_corpus
def test_the_rest_after_the_opening_note_is_not_retied():
    blob = convert(str(CORPUS / THRUST), log=lambda m: None, **_opts(True))
    s = songview.parse_sng(blob)
    seen = 0
    for track in s.tracks:
        p = s.patterns[track[0]]
        for i in range(0, len(p), 4):
            if p[i] == GT_KEYOFF:
                seen += 1
                assert p[i + 2] != CMD_TONEPORTA, (track[0], i // 4)
    assert seen >= 3


CMD_SETSR = 6
CONFUZION = "Confuzion.sid"


@needs_corpus
def test_the_triangle_engine_keeps_its_keyoff_tie():
    """Confuzion (triangle vibrato) keeps the `CMD_TONEPORTA 00` on the KEYOFF
    that ends a ringing rest. Its original stops the vibrato at the gate-off
    (B-4 at calls 3158-3176: centre, then static for 12 frames) and the tie's
    `vibtime` restart is the nearest thing ours has to that; untying it left
    the vibrato running through the rest, aud .9569 -> .9538 and loud .9628 ->
    .9589 (confuzion-keyoff-untie-scope). Pattern $0D row 60 is that KEYOFF."""
    doc = json.loads(PRESETS.read_text())
    blob = convert(str(CORPUS / CONFUZION), log=lambda m: None,
                   **fidelity._preset_opts(doc, CONFUZION))
    s = songview.parse_sng(blob)
    kept = 0
    for p in s.patterns:
        for i in range(4, len(p), 4):
            if (p[i] == GT_KEYOFF and p[i + 2] == CMD_TONEPORTA
                    and p[i - 2] == CMD_SETSR):
                kept += 1
    assert kept >= 2
    assert tuple(s.patterns[0x0D][60 * 4:60 * 4 + 4]) == (
        GT_KEYOFF, 0, CMD_TONEPORTA, 0)
