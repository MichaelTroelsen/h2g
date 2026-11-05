"""A tied rest chain sliced at the pattern end is still cut where it ends
(task kentilla-aud-dip-151).

Kentilla's record 0 is a tied note followed by three bit-5-less rests: the
gate shuts at the first rest, the instrument's SR $5F rings (release F, 24 s),
and the player zeroes the AD/SR pair on the last tick of the last rest
(siddump -v1, voice 3: gate off 7368, `0000` at 7602, `0D5F` back at 7606).
`patterns` slices at 94 rows, which put that last rest in the NEXT pattern:
the first pattern rang uncut (`test_kentilla_gaps`) and the cut marker in the
second was taken out as an orphan, so the voice rang on at release F to its
next attack 25 s later -- 10x the original's level over seconds 152-159 of
the render, the `aud` dip QUEUE calls dip-kentilla-151.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g.goatwriter import rest_ring
from h2g.goatwriter.rest_ring import rest_ring_pass
from h2g.patterns import (CMD_SETSR, CMD_TONEPORTA, GT_KEYOFF, GT_NO_NOTE)

REST, KEYOFF, END = GT_NO_NOTE, GT_KEYOFF, 0xFF
NOTE = 0x70
RING = {1: (0x0D, 0x5F)}
CUT = {1: (0x0D, 0x00)}

CHAIN = [(NOTE, 1, 0, 0), (REST, 0, 0, 0),
         (KEYOFF, 0, CMD_TONEPORTA, 0), (REST, 0, 0, 0),
         (KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (END, 0, 0, 0)]
TAIL = [(REST, 0, 0, 0), (REST, 0, 0, 0), (REST, 0, CMD_SETSR, 0),
        (END, 0, 0, 0)]


def _rows(flat):
    return [tuple(flat[k:k + 4]) for k in range(0, len(flat), 4)]


def _flat(rows):
    return [v for r in rows for v in r]


def _pass(patterns, tracks, **kw):
    out, new_tracks = rest_ring_pass([_flat(p) for p in patterns], RING, CUT,
                                     tracks, **kw)
    return [_rows(p) for p in out], new_tracks


def test_the_cut_in_the_next_slice_is_kept():
    (a, b), _ = _pass([CHAIN, TAIL], [[0, 1, 0xFF, 0]])
    assert a[1] == (REST, 0, CMD_SETSR, 0x5F), "the ring, as before"
    assert b[2] == (REST, 0, CMD_SETSR, 0), "and the cut in the next slice"


def test_a_cut_mid_pattern_is_kept_too():
    tail = [(REST, 0, 0, 0), (REST, 0, CMD_SETSR, 0), (NOTE, 1, 0, 0),
            (END, 0, 0, 0)]
    (a, b), _ = _pass([CHAIN, tail], [[0, 1, 0xFF, 0]])
    assert b[1] == (REST, 0, CMD_SETSR, 0)


def test_a_next_pattern_reached_from_elsewhere_is_left_alone():
    """The marker would cut a rest that is not ringing (or a held note) on
    the other path."""
    out, _ = _pass([CHAIN, TAIL], [[0, 1, 0xFF, 0], [1, 0xFF, 0]])
    assert all(r[2] != CMD_SETSR for r in out[1]), out[1]
    out, _ = _pass([CHAIN, TAIL, CHAIN],
                   [[0, 1, 0xFF, 0], [2, 1, 0xFF, 0]])
    assert all(r[2] != CMD_SETSR for r in out[1]), "two openers: left alone"


def test_a_next_pattern_that_opens_on_a_note_has_no_chain_to_cut():
    tail = [(NOTE, 1, 0, 0), (REST, 0, 0, 0), (REST, 0, CMD_SETSR, 0),
            (END, 0, 0, 0)]
    (a, b), _ = _pass([CHAIN, tail], [[0, 1, 0xFF, 0]])
    assert all(r[2] != CMD_SETSR for r in b), b


def test_without_chains_nothing_is_carried():
    (a, b), _ = _pass([CHAIN, TAIL], [[0, 1, 0xFF, 0]], chains=False)
    assert all(r[2] != CMD_SETSR for r in a + b), (a, b)


def test_the_seam_is_the_behaviour(monkeypatch):
    """With the carry off the marker is the orphan it was."""
    monkeypatch.setattr(rest_ring, "_CARRY_OPEN_CUT", False)
    (a, b), _ = _pass([CHAIN, TAIL], [[0, 1, 0xFF, 0]])
    assert all(r[2] != CMD_SETSR for r in b), b


@needs_corpus
def test_kentilla_cuts_its_record_0_chain():
    import json
    from pathlib import Path
    from fidelity import _preset_opts
    from h2g.convert import convert
    from songview import parse_sng
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    log = []
    blob = convert(str(CORPUS / "Kentilla.sid"), log=log.append,
                   **_preset_opts(doc, "Kentilla.sid"))
    ring = [m for m in log if m.startswith("Rest ring-out")]
    assert ring and "1 of them cut where the slicing moved" in ring[0], ring
    song = parse_sng(blob)
    cuts = [(n, r) for n, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4)
            if tuple(pat[r * 4:r * 4 + 4]) == (REST, 0, CMD_SETSR, 0)]
    assert cuts, "the cut rows reach the song"
