"""Battle_of_Britain's tied rests ring out; the other note-rise files keep theirs.

Voices 2 and 3 of the intro end a sweep with the gate off and no `$0000`
envelope write: the original's R=$F tail sounds for up to 190 frames
(siddump -v1, voice 2: gate off at frame 704, the envelope cut only at 894).
`cut_release` zeroes the instrument's release, so with the ring-out `chains`
off the tail is silent in ours -- per-voice solo renders at 12-21 s read the
original 30+ dB louder, and `aud` dips to .60 at seconds 14 and 16.
"""
import pathlib
import sys

import pytest

from corpus import needs_corpus
from test_note_rise import _converted

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import h2g.goatwriter.rest_ring as RR                        # noqa: E402

CHAIN_LINE = "tied rest chain(s) ring uncut to the next note"


def _ring_line(name, **extra):
    _sng, lines, _ = _converted(name, **extra)
    return [m for m in lines if m.startswith("Rest ring-out")]


def test_the_keyed_set_names_exactly_battle_of_britain():
    assert RR.CHAINS_WITH_NOTE_RISE == frozenset({"Battle of Britain"})


@needs_corpus
def test_battle_of_britains_tied_rests_ring_uncut_to_the_next_note():
    got = _ring_line("Battle_of_Britain")
    assert len(got) == 1 and CHAIN_LINE in got[0], got


@needs_corpus
def test_the_chain_ring_is_what_the_keyed_set_switches(monkeypatch):
    monkeypatch.setattr(RR, "CHAINS_WITH_NOTE_RISE", frozenset())
    got = _ring_line("Battle_of_Britain")
    assert not any(CHAIN_LINE in m for m in got), got


@needs_corpus
@pytest.mark.parametrize("name", ["Chimera", "Crazy_Comets", "Game_Killer",
                                  "Human_Race"])
def test_the_other_note_rise_files_keep_the_chains_off(name):
    assert not any(CHAIN_LINE in m for m in _ring_line(name)), name
