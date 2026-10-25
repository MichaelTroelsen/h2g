"""master_volume: one `D0v` per subtune for originals that hold $D418 below $F.

Design: docs/superpowers/plans/2026-10-24-master-volume-design.md. The level is
READ from the play routine's immediate (`detect.find_master_volume`), never
traced; the table below is the census's trace of $D418 (fbs-vol-column run), so
a detector that read the wrong nibble fails against the player itself.

Held DIGI files appear here only as a READ of the detector. Nothing converts
one, and the option is off by default.
"""
import io
import json
import contextlib
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.detect import detect
from h2g.patterns import CMD_SETMASTERVOL, _entry_reference
from h2g.goatwriter import CMD_SETTEMPO
from h2g.sidfile import load_sid

REPO = Path(__file__).resolve().parents[2]

# Traced constant $D418 low nibble of every corpus file whose play entry matches
# FILTER_MODE_ENTRY_SHAPE and whose level is below $F (census at 2043c3b).
# Mr_Meaner's immediate is $18: the passband nibble is not part of the level.
TRACED = {
    "Mega_Apocalypse": 8, "Pygmies_Revenge": 8,
    # held: read only, never converted or adopted
    "Arcade_Classics": 8, "Kings_of_the_Beach_intro": 8, "Mr_Meaner": 8,
    "Off_the_Cuff": 8, "One_on_One_Jordan_vs_Bird": 8,
    "Powerplay_Hockey_USA_vs_USSR": 8, "Rock_Tells_the_Tale": 8,
    "BMX_Kidz": 10, "Ricochet": 10, "Skate_or_Die_intro": 10,
}
WORKED = ("Mega_Apocalypse", "Pygmies_Revenge")


def _det(stem):
    with contextlib.redirect_stdout(io.StringIO()):
        return detect(load_sid(str(CORPUS / f"{stem}.sid")), lambda m: None)


def _both(stem):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    # the shipped presets now adopt master_volume for both; "off" must be off
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), master_volume=False)
    off = parse_sng(convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                            **opts))
    lines = []
    on = parse_sng(convert(str(CORPUS / f"{stem}.sid"), log=lines.append,
                           **dict(opts, master_volume=True)))
    return off, on, lines


def _cells(song, cmd):
    """{(pattern, row): param} for every cell carrying `cmd`."""
    return {(p, r): pat[4 * r + 3]
            for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4) if pat[4 * r + 2] == cmd}


def _entry(song, k, v):
    track = song.tracks[3 * k + v]
    at = _entry_reference(track)
    return None if at is None else track[at]


@needs_corpus
@pytest.mark.parametrize("stem", sorted(TRACED))
def test_the_level_equals_the_traced_constant(stem):
    """SABOTAGE TARGET: dropping `& 0x0F` in find_master_volume reads Mr_Meaner
    (immediate $18) as 24."""
    assert _det(stem).master_volume == TRACED[stem]


@needs_corpus
def test_every_other_corpus_file_reads_none():
    got = {p.stem: _det(p.stem).master_volume
           for p in sorted(CORPUS.glob("*.sid")) if p.stem not in TRACED}
    assert {k: v for k, v in got.items() if v is not None} == {}


@needs_corpus
@pytest.mark.parametrize("stem", WORKED)
def test_the_option_leaves_every_tempo_where_it_was(stem):
    """SABOTAGE TARGET: writing the D on voice 0 row 0 overwrites the entry's
    CMD_SETTEMPO, so this fails."""
    off, on, _ = _both(stem)
    assert _cells(off, CMD_SETTEMPO), "no tempo to protect: the test is blind"
    assert _cells(on, CMD_SETTEMPO) == _cells(off, CMD_SETTEMPO)
    assert on.tracks == off.tracks


@needs_corpus
@pytest.mark.parametrize("stem", WORKED)
def test_no_master_volume_on_a_voice_zero_entry_row_zero(stem):
    off, on, _ = _both(stem)
    for k in range(on.subtunes):
        p = _entry(on, k, 0)
        assert on.patterns[p][2] != CMD_SETMASTERVOL


@needs_corpus
@pytest.mark.parametrize("stem", WORKED)
def test_one_d0v_per_subtune(stem):
    off, on, lines = _both(stem)
    assert _cells(off, CMD_SETMASTERVOL) == {}
    level = TRACED[stem]
    assert on.subtunes >= 1
    for k in range(on.subtunes):
        entries = {_entry(on, k, v) for v in range(3)} - {None}
        hits = [(p, r) for (p, r), v in _cells(on, CMD_SETMASTERVOL).items()
                if p in entries]
        assert len(hits) == 1, (k, hits)
        assert _cells(on, CMD_SETMASTERVOL)[hits[0]] == level
        assert hits[0][1] == 0 and hits[0][0] != _entry(on, k, 0)
