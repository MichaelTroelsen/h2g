"""A drum record the start subtune never plays is sized by the gate of the
subtunes that do (Commando_2's `$046F`).

One wavetable serves every subtune, and `_noise_tick_frames` read the START
subtune's speed gate for all of it. Commando starts on subtune 0 (gate 3, noise
2 frames); instrument 10 (ADSR `$046F`, effect `$05`) is played only in subtune 1,
whose gate is 4. The player's drum block holds the noise for the unit's
`gate - 1` frames: 3 on 564 of 564 of that record's notes in a 180 s trace,
against the 2 this wrote, so heard `instr` read 54% on the listening page
Commando_2 (wave 564 of 1232 notes) and 100% with the gate read per record.
Figures are historical (v0.5.674 renders, -t 180).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import h2g.goatwriter as G                                   # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import Detection                             # noqa: E402
from h2g.goatwriter import SongSpeeds, _noise_tick_frames    # noqa: E402
from h2g.tracks import instrument_row_calls                  # noqa: E402
from songview import parse_sng                               # noqa: E402

COMMANDO = CORPUS / "Commando.sid"
PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
needs_presets = pytest.mark.skipif(not PRESETS.exists(),
                                   reason="presets.json absent")
# Commando's own gates: four songs and fourteen one-frame sound effects.
COMMANDO_GATES = (3, 4, 3, 3, 1, None) + (1,) * 13


class _Sid:
    def __init__(self, start_song: int = 1):
        self.data = bytes(16)
        self.start_song = start_song
        self.subtunes = 1


def _det():
    return Detection(instr_start=8, instr_stride=8, effect_drum=True)


def _speeds(frames, monkeypatch):
    monkeypatch.setattr(
        G.tempo, "find_song_speeds",
        lambda sid, det: SongSpeeds(frames=tuple(frames), reload_addr=0,
                                    table_addr=None))


def test_a_record_only_a_slower_subtune_plays_takes_that_gate(monkeypatch):
    _speeds(COMMANDO_GATES, monkeypatch)
    assert _noise_tick_frames(_Sid(), _det()) == 2                 # the tune
    assert _noise_tick_frames(_Sid(), _det(), frozenset({1})) == 3  # gate 4
    # gate 1: a one-frame effect subtune's record keeps one frame of noise
    assert _noise_tick_frames(_Sid(), _det(), frozenset({4, 6})) == 1


def test_a_record_the_start_subtune_plays_keeps_the_start_gate(monkeypatch):
    _speeds(COMMANDO_GATES, monkeypatch)
    assert _noise_tick_frames(_Sid(), _det(), frozenset({0, 1})) == 2
    assert _noise_tick_frames(_Sid(), _det(), frozenset({0})) == 2


def test_subtunes_that_disagree_or_cannot_be_read_keep_the_start_gate(
        monkeypatch):
    _speeds(COMMANDO_GATES, monkeypatch)
    assert _noise_tick_frames(_Sid(), _det(), frozenset({1, 4})) == 2   # 4 vs 1
    assert _noise_tick_frames(_Sid(), _det(), frozenset({5})) == 2      # None
    assert _noise_tick_frames(_Sid(), _det(), frozenset({40})) == 2     # absent
    assert _noise_tick_frames(_Sid(), _det(), frozenset()) == 2


def test_instrument_row_calls_names_the_groups_that_play_each_record():
    # Two subtunes; instrument 2 only in the second, 3 in both. Row layout is
    # (note, instrument, command, data) per row, `$FF` ends a pattern.
    end = [0xFF, 0, 0, 0]
    patterns = [[0x30, 3, 0, 0] + end, [0x30, 3, 0, 0, 0x32, 2, 0, 0] + end]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0],
              [1, 0xFF, 0], [1, 0xFF, 0], [1, 0xFF, 0]]
    got = instrument_row_calls(tracks, patterns, [6, 8]).play_groups
    assert got[3] == frozenset({0, 1})
    assert got[2] == frozenset({1})


@needs_corpus
@needs_presets
def test_commando_instrument_10_holds_three_frames_of_noise():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, COMMANDO.name)
    song = parse_sng(convert(str(COMMANDO), log=lambda m: None, **opts))
    wtbl = song.tables["WTBL"]

    def noise_calls(adsr):
        ins = next(i for i in song.instruments if i.adsr == adsr)
        rows = wtbl[ins.wave_ptr - 1:]
        # the first row is the record's own attack; count noise rows after it
        n = 0
        for left, _ in rows[1:]:
            if left & 0xF0 == 0x80 and not left & 0x0F:
                n += 1
            else:
                break
        return n

    # `$064B` is played by the start subtune (gate 3): two frames of noise.
    assert noise_calls("$064B") == 2
    # `$046F` only by subtune 1 (gate 4): three. Each noise row is one call,
    # the arpeggio's octave alternating on the right-hand column.
    assert noise_calls("$046F") == 3
