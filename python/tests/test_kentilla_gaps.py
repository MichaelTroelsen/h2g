"""Kentilla's three unread mechanisms (task kentilla-close-the-gaps).

1. **The per-voice pulse triangle, spelled absolute,X** (`PULSE_TRI_ABSX_SHAPE`,
   Kentilla `$AD96`). Samantha Fox's zero-page triangle with `$AFF7,X` /
   `$AFFA,X` cells; the nibble-arpeggio family's eight files carry it and none
   read a sweep before, so record 7's `$080 -> $1E0` per note was frozen at
   `$080` (Kentilla: 116 pulse changes against the original's 6592).
2. **The status-bit-6 test with the wait stored twice**
   (`STATUS_BIT6_TWICE_SHAPE`, `$ABC3-$ABD6`). Undetected, a `$77` rest was
   decoded as a hold: the gate stayed open for the rest's 24 ticks, 1503 frames
   at the end of the window on voice 2 alone.
3. **A rest chain that rings uncut** (`patterns` `ring_chain`,
   `goatwriter.rest_ring`). `37 77 77 57` is a tied note, two bit-5 rests
   that re-write the record's SR $5F with the gate shut and never cut, and a
   last rest that cuts on its final tick. Only the cut-at-the-end rest after a
   tie rang before.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import (PULSE_TRI_ABSX_SHAPE, PULSE_TRI_SHAPE,
                        PULSE_TRI_ZP_SHAPE, STATUS_BIT6_TWICE_SHAPE,
                        _find_pulse_tri_absx, _status_bit6_bvs, detect)
from h2g.goatwriter.rest_ring import rest_ring_pass
from h2g.patterns import (CMD_SETSR, CMD_TONEPORTA, GT_KEYOFF, GT_NO_NOTE,
                          _build_raw_pattern)
from h2g.search import search_file
from h2g.sidfile import load_sid

REST, KEYOFF, END = GT_NO_NOTE, GT_KEYOFF, 0xFF
SETSR = CMD_SETSR
NOTE = 0x70
RING = {1: (0x0A, 0x5F)}
CUT = {1: (0x0A, 0x50)}

ABSX_FILES = {
    "Bump_Set_Spike.sid", "Formula_1_Simulator.sid",
    "International_Karate.sid", "Kentilla.sid", "Las_Vegas_Video_Poker.sid",
    "Proteus.sid", "Thrust.sid", "Warhawk.sid"}


def _quiet(*_a, **_k):
    pass


def _rows(flat):
    return [tuple(flat[k:k + 4]) for k in range(0, len(flat), 4)]


def _flat(rows):
    return [v for r in rows for v in r]


def _decode(status_bytes, **kw):
    data = bytes([0x00, 0x00]) + bytes(status_bytes) + bytes([0xFF])
    kw.setdefault("rest_keyoff", True)
    kw.setdefault("rest_ring", True)
    kw.setdefault("tie", True)
    return _rows(_build_raw_pattern(data, 2, status_bit6=True, **kw))


TIED_NOTE = [0xA1, 0x00, 0x10]
PLAIN_NOTE = [0x81, 0x00, 0x10]


# --- the decoder: a rest entered ringing ------------------------------------

def test_a_rest_after_an_uncut_rest_after_a_tie_is_cut_on_its_last_row():
    """Tied note, `$63` (bit 5: no cut, wait 3), `$43` (wait 3). The first
    rest leaves the release sounding, so the second is entered ringing and
    its cut is marked on ITS last hold row; the first carries none."""
    rows = _decode(TIED_NOTE + [0x63, 0x43])
    first, second = rows[2:6], rows[6:10]
    assert first[0][0] == KEYOFF and second[0][0] == KEYOFF
    assert all(r[2] != SETSR for r in first), first
    assert second[3] == (REST, 0, SETSR, 0), second


def test_a_chain_entered_after_a_cut_note_is_not_marked():
    rows = _decode(PLAIN_NOTE + [0x63, 0x43])
    assert all(r[2] != SETSR for r in rows), rows


def test_a_rest_after_a_rest_that_cut_is_not_marked():
    """`$43` cuts on its last tick, so the `$43` after it enters silence."""
    rows = _decode(TIED_NOTE + [0x43, 0x43])
    marks = [i for i, r in enumerate(rows) if r[2] == SETSR]
    assert marks == [5], rows


def test_a_note_ends_the_chain():
    rows = _decode(TIED_NOTE + [0x63] + PLAIN_NOTE + [0x43])
    assert all(r[2] != SETSR for r in rows), rows


# --- the pass: where the chain rings ----------------------------------------

def _pass(patterns, tracks):
    out, new_tracks = rest_ring_pass([_flat(p) for p in patterns], RING, CUT,
                                     tracks)
    return [_rows(p) for p in out], new_tracks


def test_a_chain_rings_from_its_first_keyoff():
    rows = [(NOTE, 1, 0, 0), (REST, 0, 0, 0),
            (KEYOFF, 0, CMD_TONEPORTA, 0), (REST, 0, 0, 0),
            (KEYOFF, 0, 0, 0), (REST, 0, 0, 0),
            (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    (p,), _ = _pass([rows], [[0, 0xFF, 0]])
    assert p[1] == (REST, 0, SETSR, 0x5F), p
    assert p[3] == (REST, 0, 0, 0), "nothing lands inside the chain"
    assert p[6] == (REST, 0, SETSR, 0), "the cut stays"


def test_a_tied_chain_running_off_the_pattern_rings_uncut():
    """Kentilla pattern 2 sliced at 94 rows: the chain's cut is in the next
    slice, so this one rings to the end of the pattern."""
    rows = [(NOTE, 1, 0, 0), (REST, 0, 0, 0),
            (KEYOFF, 0, CMD_TONEPORTA, 0), (REST, 0, 0, 0),
            (KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (END, 0, 0, 0)]
    (p,), _ = _pass([rows], [[0, 0xFF, 0]])
    assert p[1] == (REST, 0, SETSR, 0x5F), p
    assert all(r[2] != SETSR for r in p[2:]), p


def test_without_chains_the_pass_reads_rests_as_before():
    """`chains=False` (a note-rise file) rings neither a chain from its first
    KEYOFF nor a tied chain running off the pattern: the chain's cut marker
    is an orphan and is taken out."""
    chained = [(NOTE, 1, 0, 0), (REST, 0, 0, 0),
               (KEYOFF, 0, CMD_TONEPORTA, 0), (REST, 0, 0, 0),
               (KEYOFF, 0, 0, 0), (REST, 0, 0, 0),
               (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    off_end = chained[:6] + [(END, 0, 0, 0)]
    out, _ = rest_ring_pass([_flat(chained), _flat(off_end)], RING, CUT,
                            [[0, 1, 0xFF, 0]], chains=False)
    for p in out:
        assert all(r[2] != SETSR for r in _rows(p)), _rows(p)


@needs_corpus
def test_a_note_rise_file_keeps_its_rows():
    """Game_Killer's rise claims the rows through its rests after this pass
    (`goatwriter.note_rise`); the new rings stand aside there."""
    _blob, log = _convert("Game_Killer.sid")
    ring = [m for m in log if m.startswith("Rest ring-out")]
    assert ring and "tied rest chain" not in ring[0], ring


def test_an_untied_keyoff_running_off_the_pattern_does_not_ring():
    rows = [(NOTE, 1, 0, 0), (REST, 0, 0, 0),
            (KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (END, 0, 0, 0)]
    (p,), _ = _pass([rows], [[0, 0xFF, 0]])
    assert all(r[2] != SETSR for r in p), p


# --- detection, on the corpus -----------------------------------------------

@needs_corpus
def test_the_twice_stored_bit6_test_is_kentillas_alone():
    hits = {p.name for p in sorted(CORPUS.glob("*.sid"))
            if search_file(load_sid(str(p)).data,
                           STATUS_BIT6_TWICE_SHAPE) >= 0}
    assert hits == {"Kentilla.sid"}
    sid = load_sid(str(CORPUS / "Kentilla.sid"))
    at = _status_bit6_bvs(sid.data)
    rel = sid.data[at]
    assert sid.to_address(at + 1 + rel) == 0xAC20, "the DEC gatemask branch"
    assert detect(sid, _quiet).status_bit6


@needs_corpus
def test_the_absolute_x_triangle_is_found_on_exactly_its_eight_files():
    found = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, _quiet)
        if search_file(sid.data, PULSE_TRI_ABSX_SHAPE) < 0:
            continue
        # Only where both other spellings read nothing.
        assert search_file(sid.data, PULSE_TRI_SHAPE) < 0, path.name
        assert search_file(sid.data, PULSE_TRI_ZP_SHAPE) < 0, path.name
        assert _find_pulse_tri_absx(sid, det) is not None, path.name
        assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0E), path.name
        assert (det.pulse_tri_step_mask,
                det.pulse_tri_delay_mask) == (0xF0, 0x0F), path.name
        assert det.pulse_tri_gated and det.pulse_tri_per_voice, path.name
        found.add(path.name)
    assert found == ABSX_FILES


@needs_corpus
def test_kentilla_record_7_sweeps():
    """Rate `$20`: a step of $20 every frame, 10 of 11 frames past the outer
    gate, at -S10 -- 3 a call."""
    from h2g.goatwriter import _pulse_program
    sid = load_sid(str(CORPUS / "Kentilla.sid"))
    det = detect(sid, _quiet)
    entries, _loop = _pulse_program(sid, det, 7, True, 10)
    assert entries[0] == (0x80, 0x80), "set to the record's own $080"
    speeds = {e[1] for e in entries if 0 < e[0] < 0x80}
    assert 3 in speeds, entries


def _convert(name):
    import json
    from pathlib import Path
    from fidelity import _preset_opts
    from h2g.convert import convert
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    log = []
    blob = convert(str(CORPUS / name), log=log.append,
                   **_preset_opts(doc, name))
    return blob, log


@needs_corpus
def test_kentilla_rings_its_tied_drone_rests_at_sr_5f():
    from songview import parse_sng
    blob, log = _convert("Kentilla.sid")
    assert any("tied rest chain(s) ring uncut" in m for m in log), log
    song = parse_sng(blob)
    rung = 0
    for pat in song.patterns:
        rows = _rows(pat)
        for i, r in enumerate(rows[:-1]):
            if r[0] == END:
                break
            if (r == (REST, 0, SETSR, 0x5F) and rows[i + 1][0] == KEYOFF):
                rung += 1
    assert rung >= 1, "record 0's $77 chain rings at its own SR"
