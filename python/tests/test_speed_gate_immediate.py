"""The speed gate's second spelling: an immediate reload.

`SPEED_GATE` matches `DEC ctr / BPL +6 / LDA reload / STA ctr` -- the reload
read from a *cell*, which is what lets a per-subtune table drive it. Two
corpus players spell the same gate with an immediate instead:

    C83D  DEC $CC46 / BPL +5 / LDA #$02 / STA $CC46        (Ninja)
    C84E  LDA $CC46 / CMP #$02 / BNE skip   ; work on the reload frame

`BPL +5` rather than `+6` because `LDA #imm` is two bytes where `LDA abs` is
three -- one byte, and it cost Ninja every tempo-derived number it had. With
no gate found the tempo falls back to a constant of 3 calls a row where the
truth is 4 frames, so the tune ran exactly 4/3 too fast: `--pace` measured
`0.750` with an interquartile range of `0.750-0.750` over 858 gaps, which is
what a wrong constant looks like as against irregular pacing.

**A fallback, not a competitor.** 35 corpus files carry this shape and 33 of
them already read a gate through the absolute spelling; what the counter does
in those 33 is not established, and `find_song_speeds` has no way to choose
between two candidates it cannot tell apart. So it is consulted only where the
absolute form matched nothing -- the same rule `find_relocation` and
`INSTRUMENT_INDEX_SHAPE` follow.
"""
import pathlib
import re
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables  # noqa: E402
from h2g.goatwriter import (SPEED_GATE, SPEED_GATE_IMM,  # noqa: E402
                            _gate_hits, effective_frames, find_song_speeds,
                            outer_gate_skip, tempo_command_value)
from h2g.sidfile import load_sid  # noqa: E402


def _det(name):
    return _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                          lambda *a, **k: None)


def test_the_two_spellings_differ_by_the_branch_offset():
    """`LDA #imm` is two bytes and `LDA abs` is three, so `BPL +5` vs `+6`."""
    absolute = bytes([0xCE, 0x46, 0xCC, 0x10, 0x06, 0xAD, 0x3B, 0xC5,
                      0x8D, 0x46, 0xCC])
    immediate = bytes([0xCE, 0x46, 0xCC, 0x10, 0x05, 0xA9, 0x02,
                       0x8D, 0x46, 0xCC])
    assert SPEED_GATE.search(absolute) and not SPEED_GATE_IMM.search(absolute)
    assert SPEED_GATE_IMM.search(immediate) and not SPEED_GATE.search(immediate)


def test_a_gate_that_reloads_a_different_cell_is_not_a_gate():
    """The counter and the store must name the same address."""
    other = bytes([0xCE, 0x46, 0xCC, 0x10, 0x05, 0xA9, 0x02,
                   0x8D, 0x99, 0xCC])
    m = SPEED_GATE_IMM.search(other)
    assert m and m.group(1) != m.group(3)


@needs_corpus
def test_ninja_reads_its_gate_and_lands_on_a_whole_row():
    sid, det = _det("Ninja")
    speeds = find_song_speeds(sid, det)
    assert speeds is not None
    assert speeds.frames_for(0) == 3          # reload $02, so three calls
    assert speeds.skip_for(0) == 3            # and the outer counter above it
    # 3 * 4/3 -- the one case where the corrected row is exact.
    assert speeds.exact_row(0) == 4
    assert effective_frames(speeds, 0, skip_gate=True) == 4
    assert tempo_command_value(sid, 0, speeds, 1, skip_gate=True) == 4


@needs_corpus
def test_it_is_consulted_only_where_the_absolute_form_found_nothing():
    """33 of the 35 files carrying it already read a gate the other way."""
    both, rescued = 0, []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if not any(m.group(1) == m.group(3)
                   for m in SPEED_GATE_IMM.finditer(sid.data)):
            continue
        absolute = [m for m in SPEED_GATE.finditer(sid.data)
                    if m.group(1) == m.group(3)]
        if absolute:
            both += 1
            # The hits it returns are the absolute ones and nothing else.
            hits = _gate_hits(sid)
            assert len(hits) == len(absolute), path.name
        else:
            rescued.append(path.name)
    assert both >= 30
    assert sorted(rescued) == ["Mega_Apocalypse.sid", "Ninja.sid"]


@needs_corpus
def test_mega_apocalypse_is_rescued_onto_the_value_it_was_guessing():
    """A reading that confirms the old constant is still worth having."""
    sid, det = _det("Mega_Apocalypse")
    speeds = find_song_speeds(sid, det)
    assert speeds is not None
    assert speeds.frames_for(0) == 3
    assert speeds.skip_for(0) is None          # no outer counter in this one
    # Which is the fallback constant, so its bytes do not move -- the value is
    # now measured rather than assumed.
    assert tempo_command_value(sid, 0, speeds, 1, skip_gate=True) == 3


@needs_corpus
def test_no_other_corpus_file_changes_its_mind():
    """The rescue must not move a file that already read a gate."""
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        absolute = [m for m in SPEED_GATE.finditer(sid.data)
                    if m.group(1) == m.group(3)]
        if not absolute:
            continue
        for pos, _ in _gate_hits(sid):
            assert any(m.start() == pos for m in absolute), path.name
