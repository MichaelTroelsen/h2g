"""Presets adopted by ear (user, 2026-10-31), each on the song heard with it.

Proteus takes drum_gate_off + drum_sustain_gate_off (gate 68% -> 91%,
melody/aud/loud flat); Lion_Heart takes wave_program (onset 85% -> 100% at
melody 95% -> 92%). Both pairs were staged from the presets they now carry.
"""
import io
import json
import hashlib
import contextlib
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert

REPO = Path(__file__).resolve().parents[2]

HEARD = {
    "Proteus.sid": ("drum_gate_off", "drum_sustain_gate_off"),
    "Lion_Heart.sid": ("wave_program",),
}


def _opts(name):
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    return F._preset_opts(doc, name)


def _sha(name, **over):
    with contextlib.redirect_stdout(io.StringIO()):
        blob = convert(str(CORPUS / name), log=lambda m: None,
                       **dict(_opts(name), **over))
    return hashlib.sha1(blob).hexdigest()


@needs_corpus
@pytest.mark.parametrize("name", sorted(HEARD))
def test_the_heard_song_carries_its_options(name):
    opts = _opts(name)
    assert all(opts.get(k) for k in HEARD[name]), (name, HEARD[name])


@needs_corpus
@pytest.mark.parametrize("name", sorted(HEARD))
def test_the_options_change_what_the_heard_song_emits(name):
    """The adoption is not inert: without its options the bytes differ."""
    off = {k: False for k in HEARD[name]}
    assert _sha(name) != _sha(name, **off)


@needs_corpus
def test_proteus_takes_the_drum_shape_without_keep_hard_restart():
    assert not _opts("Proteus.sid").get("keep_hard_restart")
