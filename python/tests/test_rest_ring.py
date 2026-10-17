"""A bit-6 rest rings out at the instrument's release and is cut on its last
tick (task las-vegas-voice1-delayed-cut-release).

`--cut-release` zeroes the release nibble in the instrument of a player that
ends a note by writing `$0000` to the envelope pair. A REST drops its gate on
its first tick with the instrument's AD/SR re-written, and the same cut lands
on its last tick -- unless the note before it was tied (status bit 5), in which
case the gate was still open when the rest began and the release is heard. See
`goatwriter/rest_ring.py` for the routine and the trace.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g.goatwriter.rest_ring import rest_ring_pass
from h2g.patterns import (CMD_SETSR, CMD_TONEPORTA, GT_KEYOFF, GT_NO_NOTE,
                          _build_raw_pattern)

REST, KEYOFF, END = GT_NO_NOTE, GT_KEYOFF, 0xFF
SETSR = CMD_SETSR
NOTE = 0x70           # an arbitrary note in the C-0..G#7 range

# Instrument 1: AD $0A, SR $0C with the release in the record; cut_release
# zeroes the release nibble, so the emitted SR is $00.
RING = {1: (0x0A, 0x0C)}
CUT = {1: (0x0A, 0x00)}


def _rows(flat):
    return [tuple(flat[k:k + 4]) for k in range(0, len(flat), 4)]


def _flat(rows):
    return [v for r in rows for v in r]


# --- the decoder: where the marker goes -------------------------------------

def _decode(status_bytes, **kw):
    data = bytes([0x00, 0x00]) + bytes(status_bytes) + bytes([0xFF])
    kw.setdefault("rest_keyoff", True)
    kw.setdefault("rest_ring", True)
    kw.setdefault("tie", True)
    return _rows(_build_raw_pattern(data, 2, status_bit6=True, **kw))


TIED_NOTE = [0xA1, 0x00, 0x10]      # bit 7, bit 5 (tie), wait 1, instr 0
PLAIN_NOTE = [0x81, 0x00, 0x10]     # the same without bit 5


def test_a_rest_after_a_tied_note_is_cut_on_its_last_hold_row():
    """$43: bit 6, wait 3 -- the KEYOFF row and three hold rows. The counter is
    set to 3 at the fetch and reaches 0 three ticks later, on the LAST row."""
    rows = _decode(TIED_NOTE + [0x43])
    rest = rows[2:6]
    assert rest[0][0] == GT_KEYOFF
    assert rest[1] == (REST, 0, 0, 0)
    assert rest[2] == (REST, 0, 0, 0)
    assert rest[3] == (REST, 0, SETSR, 0), "the cut is the LAST hold row"


def test_a_rest_after_an_untied_note_gets_no_marker():
    """The note's own end cut the gate and zeroed the pair, so the rest that
    follows re-writes the instrument's SR into a gate that is already shut and
    an envelope that is already at zero: nothing rings (Las Vegas voice 1,
    frame 241 -> 252)."""
    rows = _decode(PLAIN_NOTE + [0x43])
    assert all(r[2] != SETSR for r in rows), rows


def test_a_rest_that_opens_the_pattern_carries_the_question():
    """Whether the previous pattern left the gate open is not known here: the
    marker is written and the pass answers from the orderlists."""
    rows = _decode([0x43])
    assert rows[3] == (REST, 0, SETSR, 0)


def test_a_rest_with_status_bit_5_is_never_cut():
    """`$20` skips the cut at the rest's end (`$518E AND #$20 / BNE`)."""
    rows = _decode([0x63])
    assert all(r[2] != SETSR for r in rows), rows


def test_a_zero_wait_rest_is_never_cut():
    """The counter is set to 0 by the fetch and decremented to $FF by the
    next one: `counter == 0` is never read after a decrement."""
    rows = _decode([0x40])
    assert all(r[2] != SETSR for r in rows), rows


def test_it_is_off_unless_asked():
    rows = _decode(TIED_NOTE + [0x43], rest_ring=False)
    assert all(r[2] != SETSR for r in rows), rows


def test_it_needs_the_keyoff():
    rows = _decode(TIED_NOTE + [0x43], rest_keyoff=False)
    assert all(r[2] != SETSR for r in rows), rows


def test_a_pattern_ending_on_a_tied_note_marks_its_last_row():
    """The gate is still open when whatever plays next begins; the last row is
    where a following rest's ring is written."""
    rows = _decode(TIED_NOTE)
    assert rows[-2] == (REST, 0, SETSR, 0), rows
    assert rows[-1][0] == END


def test_a_pattern_ending_on_an_untied_note_is_unmarked():
    rows = _decode(PLAIN_NOTE)
    assert all(r[2] != SETSR for r in rows), rows


# --- the pass: where the ring goes ------------------------------------------

def _pass(patterns, tracks, ring=RING, cut=CUT):
    out, new_tracks = rest_ring_pass([_flat(p) for p in patterns], ring, cut,
                                     tracks)
    return [_rows(p) for p in out], new_tracks


def _own_rest():
    """A pattern with the whole sequence inside it: a note naming instrument 1,
    a hold row, the rest's KEYOFF (after a tie) and its cut marker."""
    return [(NOTE, 1, 0, 0), (REST, 0, 0, 0),
            (KEYOFF, 0, CMD_TONEPORTA, 0), (REST, 0, 0, 0),
            (REST, 0, SETSR, 0), (END, 0, 0, 0)]


def test_the_ring_goes_on_the_row_before_the_keyoff():
    """A KEYOFF takes effect `gatetimer` calls early and its command at the
    row's own tick 0: an SR on the KEYOFF row lands after the gate has dropped
    on release 0 (Las Vegas: gate off at 302, `0A0C` at 306)."""
    (p,), _ = _pass([_own_rest()], [[0, 0xFF, 0]])
    assert p[1] == (REST, 0, SETSR, 0x0C), "the ring, a row early"
    assert p[2] == (KEYOFF, 0, CMD_TONEPORTA, 0), "the KEYOFF row is untouched"
    assert p[4] == (REST, 0, SETSR, 0), "the cut stays on the last hold row"


def test_a_ring_with_no_free_row_before_it_is_dropped_with_its_cut():
    rows = _own_rest()
    rows[1] = (REST, 0, 4, 0x37)            # a vibrato command already there
    (p,), _ = _pass([rows], [[0, 0xFF, 0]])
    assert p[1] == (REST, 0, 4, 0x37)
    assert all(r[2] != SETSR for r in p), p


def test_a_rest_opening_a_pattern_rings_on_its_predecessors_last_row():
    before = [(NOTE, 1, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)]  # exit
    rest = [(KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (REST, 0, SETSR, 0),
            (END, 0, 0, 0)]
    (a, b), _ = _pass([before, rest], [[0, 1, 0xFF, 0]])
    assert a[1] == (REST, 0, SETSR, 0x0C)
    assert b[2] == (REST, 0, SETSR, 0), "and the cut"


def test_no_ring_after_an_untied_exit():
    """The predecessor's last row carries no exit marker: its last event closed
    the gate, so the rest that follows is silent in the original too."""
    before = [(NOTE, 1, 0, 0), (REST, 0, 0, 0), (END, 0, 0, 0)]
    rest = [(KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (REST, 0, SETSR, 0),
            (END, 0, 0, 0)]
    (a, b), _ = _pass([before, rest], [[0, 1, 0xFF, 0]])
    assert a[1] == (REST, 0, 0, 0)
    assert all(r[2] != SETSR for r in b), b


def test_a_predecessor_shared_with_a_tie_is_copied_not_edited():
    """Pattern 0 leads to a rest at one orderlist position and to a tie into a
    new instrument at another. A ring left on it would reach the tie, which
    loads nothing (TONEPORTA) and would carry the release into the tied note's
    own end. Only the position that wants it is repointed."""
    before = [(NOTE, 1, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    rest = [(KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (REST, 0, SETSR, 0),
            (END, 0, 0, 0)]
    tie = [(NOTE, 2, CMD_TONEPORTA, 0), (REST, 0, 0, 0), (END, 0, 0, 0)]
    tracks = [[0, 1, 0, 2, 0xFF, 0]]
    (a, b, c, copy), new = _pass([before, rest, tie], tracks)
    assert new[0][0] == 3, "the position before the rest plays the copy"
    assert new[0][2] == 0, "the position before the tie plays the original"
    assert copy[1] == (REST, 0, SETSR, 0x0C)
    assert all(r[2] != SETSR for r in a), "the original carries no ring"
    assert tracks == [[0, 1, 0, 2, 0xFF, 0]], "the caller's list is not edited"


def test_a_repeated_pattern_is_its_own_successor():
    """`$D1 0` plays pattern 0 twice, so its first play is followed by pattern
    0 itself: a ring left on its last row reaches that row 0, and a tie there
    loads nothing to overwrite it. The first row decides."""
    rest = [(KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (REST, 0, SETSR, 0),
            (END, 0, 0, 0)]

    def run(first):
        before = [first, (REST, 0, SETSR, 0), (END, 0, 0, 0)]
        return _pass([before, rest], [[0xD1, 0, 1, 0xFF, 0]])[0]

    assert run((NOTE, 1, 0, 0))[0][1] == (REST, 0, SETSR, 0x0C)
    assert all(r[2] != SETSR for r in run((NOTE, 1, CMD_TONEPORTA, 0))[0])


def test_an_unsettled_instrument_takes_the_marker_out():
    """Two ways into the pattern holding different envelopes: no ring is
    better than the wrong one."""
    ring = {1: (0x0A, 0x0C), 2: (0x0A, 0x09)}
    cut = {1: (0x0A, 0x00), 2: (0x0A, 0x00)}
    a = [(NOTE, 1, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    b = [(NOTE, 2, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    rest = [(KEYOFF, 0, 0, 0), (REST, 0, 0, 0),
            (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    out, _ = _pass([a, b, rest], [[0, 2, 0xFF, 0], [1, 2, 0xFF, 0]], ring, cut)
    assert all(r[2] != SETSR for r in out[2]), out[2]
    assert all(r[2] != SETSR for r in out[0] + out[1]), "and no ring before it"


def test_an_instrument_whose_release_is_not_cut_is_left_alone():
    """An effect-bit-0 record keeps its release in the instrument
    (`EFFECT_PER_FRAME`), so the ring and the cut value are the same SR and
    writing it spends a command for nothing -- or, worse, cuts a note the
    effect routine keeps sounding."""
    (p,), _ = _pass([_own_rest()], [[0, 0xFF, 0]], RING, RING)
    assert all(r[2] != SETSR for r in p), p


def test_envelopes_that_agree_settle_an_instrument_that_does_not():
    """Two instruments entering the pattern with the same pair are as good as
    one."""
    ring = {1: (0x0A, 0x0C), 2: (0x0A, 0x0C)}
    cut = {1: (0x0A, 0x00), 2: (0x0A, 0x00)}
    a = [(NOTE, 1, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    b = [(NOTE, 2, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)]
    rest = [(KEYOFF, 0, 0, 0), (REST, 0, 0, 0), (REST, 0, SETSR, 0),
            (END, 0, 0, 0)]
    out, _ = _pass([a, b, rest], [[0, 2, 0xFF, 0], [1, 2, 0xFF, 0]], ring, cut)
    assert out[0][1] == (REST, 0, SETSR, 0x0C)
    assert out[1][1] == (REST, 0, SETSR, 0x0C)


def test_a_pattern_pushed_past_the_packed_limit_is_put_back():
    """A command column costs packed bytes (greloc.c packpattern) and a
    pattern over 256 does not pack at all. The ring and the cut are the first
    thing to go, and the pattern is the one it always was."""
    from h2g.goatwriter.constants import PACKED_PATTERN_LIMIT
    from h2g.goatwriter.pulse import packed_pattern_size, pattern_rows

    def build(n, ring):
        rows = [(NOTE, 1, 0, 0)]
        rows += [(NOTE + i % 12, 1, 4, (i * 7) % 250 + 1) for i in range(n)]
        rows += [(REST, 0, SETSR, 0x0C) if ring else (REST, 0, 0, 0),
                 (KEYOFF, 0, CMD_TONEPORTA, 0), (REST, 0, 0, 0),
                 (REST, 0, SETSR, 0) if ring else (REST, 0, 0, 0),
                 (END, 0, 0, 0)]
        return rows

    def size(rows):
        return packed_pattern_size(pattern_rows(_flat(rows)))

    # The largest n at which the bare pattern still packs.
    n = max(i for i in range(1, 200) if size(build(i, False))
            <= PACKED_PATTERN_LIMIT)
    assert size(build(n, False)) <= PACKED_PATTERN_LIMIT
    assert size(build(n, True)) > PACKED_PATTERN_LIMIT, "the fixture must tip it"
    marked = build(n, False)
    marked[-2] = (REST, 0, SETSR, 0)            # the decoder's marker
    log = []
    patterns, _tracks = rest_ring_pass([_flat(marked)], RING, CUT,
                                       [[0, 0xFF, 0]], log.append)
    out = _rows(patterns[0])
    assert [r for r in out if r[2] == SETSR] == [], "put back"
    assert size(out) <= PACKED_PATTERN_LIMIT
    assert any("put back" in m for m in log), log


def test_a_stray_marker_is_removed():
    """A cut marker with no KEYOFF before it (a slice boundary fell between
    them) says nothing and costs a command byte."""
    p = [(NOTE, 1, 0, 0), (REST, 0, SETSR, 0), (REST, 0, 0, 0), (END, 0, 0, 0)]
    (out,), _ = _pass([p], [[0, 0xFF, 0]])
    assert out[1] == (REST, 0, 0, 0)


# --- dedup: the markers must not change which patterns are one ---------------

def test_patterns_that_differ_only_in_a_marker_have_one_key():
    """Two sources that decode to the same rows have always been one pattern
    under `dedup`. A marker that un-merged them would grow a file by a pattern
    (Action_Biker +13 bytes, nothing ringing) for no sound at all."""
    from h2g.patterns import _ring_key
    a = _flat([(NOTE, 1, 0, 0), (REST, 0, SETSR, 0), (END, 0, 0, 0)])
    b = _flat([(NOTE, 1, 0, 0), (REST, 0, 0, 0), (END, 0, 0, 0)])
    assert _ring_key(a) == _ring_key(b)
    c = _flat([(NOTE, 1, 0, 0), (REST, 0, SETSR, 0x0C), (END, 0, 0, 0)])
    assert _ring_key(c) != _ring_key(b), "a real SR write is not a marker"


def test_a_merged_marker_survives_only_where_every_source_has_it():
    """The gate state a marker asks about is a property of the source."""
    from h2g.patterns import _merge_ring_markers
    kept = _flat([(KEYOFF, 0, 0, 0), (REST, 0, SETSR, 0), (REST, 0, SETSR, 0)])
    other = _flat([(KEYOFF, 0, 0, 0), (REST, 0, SETSR, 0), (REST, 0, 0, 0)])
    _merge_ring_markers(kept, other)
    assert _rows(kept) == [(KEYOFF, 0, 0, 0), (REST, 0, SETSR, 0),
                           (REST, 0, 0, 0)]


# --- the corpus -------------------------------------------------------------

def _convert(name, **over):
    from fidelity import _preset_opts
    import json
    from pathlib import Path
    from h2g.convert import convert
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    opts = _preset_opts(doc, name)
    opts.update(over)
    log = []
    blob = convert(str(CORPUS / name), log=log.append, **opts)
    return blob, log


@needs_corpus
def test_las_vegas_voice_1_rings_through_its_rest():
    """The default subtune opens voice 1's patterns on a rest after a tied
    note: gate off at 301, SR `$0C` held until 312. Its pattern `$06` row 0 is
    the rest, and the pattern that leads there ends on the ring."""
    from songview import parse_sng
    blob, log = _convert("Las_Vegas_Video_Poker.sid")
    assert any("Rest ring-out" in m for m in log), log
    song = parse_sng(blob)
    rings = cuts = 0
    for pat in song.patterns:
        for r in _rows(pat):
            if r[0] == END:
                break
            if r[0] == REST and r[1] == 0 and r[2] == SETSR:
                if r[3]:
                    rings += 1
                else:
                    cuts += 1
    assert rings >= 10 and cuts >= 10, (rings, cuts)
    # With the option off the same file carries none: the ring is the only
    # thing writing a release to an instrument-less hold row in this player.
    off, _ = _convert("Las_Vegas_Video_Poker.sid", cut_release=False)
    assert not any(r[0] == REST and r[1] == 0 and r[2] == SETSR
                   for pat in parse_sng(off).patterns for r in _rows(pat)
                   if r[0] != END)


@needs_corpus
@pytest.mark.parametrize("name,asked", [("Kentilla.sid", True),
                                        ("Master_of_Magic.sid", False),
                                        ("Las_Vegas_Video_Poker.sid", True)])
def test_the_decoder_is_asked_only_for_a_player_with_the_bit_6_test(
        name, asked, monkeypatch):
    """Master of Magic cuts at a note end but has no BIT/BVS status test: its
    rests are not events, so nothing here may reach it. RETRACTED: "Kentilla
    and Master of Magic ... have no BIT/BVS status test" -- Kentilla has it,
    with the wait stored twice before the BIT (`STATUS_BIT6_TWICE_SHAPE`,
    `$ABC3-$ABD6`), and its rest is Las Vegas's (`DEC $AFC8` into the shared
    tail), so it is asked like Las Vegas (task kentilla-close-the-gaps).
    The mutation that drops the gate is invisible in the output bytes (the
    dedup key and the pass's cleanup absorb the markers it would write), so
    the gate is pinned where it acts -- on the request the decoder receives."""
    import h2g.patterns as P
    seen = []
    real = P._build_raw_pattern

    def spy(*a, **kw):
        seen.append(bool(kw.get("rest_ring")))
        return real(*a, **kw)

    monkeypatch.setattr(P, "_build_raw_pattern", spy)
    _convert(name)
    assert seen, "the decoder was never reached"
    assert any(seen) == asked, (name, set(seen))
