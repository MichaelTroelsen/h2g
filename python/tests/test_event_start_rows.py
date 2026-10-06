"""The decoder's event-start rows, carried out to the triangle pulse walk.

A Hubbard pattern is a list of EVENTS, each a fetch followed by `wait` hold
rows the player only counts down. A Goattracker row cannot say which it is:
a no-note event that names no instrument decodes to `$BD 00` with the
command its hold rows repeat -- byte for byte a hold row. The triangle
player spends the fetch tick without stepping its sweep, on a note and a
no-note event alike (patterns.collect_pulse_phases), so until this channel
existed the walk stepped the sweep on such a fetch as if it were a hold.

`_build_raw_pattern(event_rows=)` records every event's first row;
`convert_patterns(event_rows=True)` re-bases them per output pattern onto
`TrackIndex.event_rows` (None where a shared pattern's sources disagree --
the dedup key is NOT changed, so the request moves no byte);
`inherit_event_rows` extends them to the later passes' copies by note
column; and the walk reads a pattern by them where it has them.

Measured at 8586101 + this change (presets, `pulse_phase` forced): the
walk receives 75 hidden fetches on 4 files -- Devils_Galop 4,
Master_of_Magic 31, Thing_on_a_Spring 34, Zoids 6 -- and NO row the bytes
called a fetch that the decoder does not.

RETRACTED, on the tree that merges this change with triangle-lockstep-walk
(the lockstep walk, `patterns._walk_triangle_group`, which no longer
declines a record on two voices): "None of them moves a byte: the
Devils_Galop and Thing_on_a_Spring ones are in subtunes the walk declines
(a record on two voices) ... So the corpus byte-hash moves nothing, shipped
or forced". Re-measured there against the same tree with `_triangle_rows`
reading bytes only: shipped presets 89 converted, 0 refused, 89 compared,
0 moved; forced `pulse_phase` 89/0/89, 1 moved -- Thing_on_a_Spring, whose
34 hidden fetches (31 on voice 0, 2 on voice 1, 1 on voice 2) take its
exact widths from v0 144/225, v1 0/25 to 225/225, 25/25
(tests/test_triangle_lockstep.py). The other 41 -- Devils_Galop's 4,
Master_of_Magic's 31, Zoids' 6 -- all fall on rows whose record has no
sim, so they step nothing and their plans are identical (the earlier
reasons for Zoids and Master_of_Magic stand as far as they go; the
uniform one is this). `test_the_walk_receives_the_hidden_fetches` pins
the census and, per file, whether the plan moves (`MOVES`).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent
sys.path.insert(0, str(PYTHON_ROOT))

from h2g import patterns as P  # noqa: E402
from h2g.goatwriter import PulsePhaseSim  # noqa: E402

# A note event (wait 3), a no-note event naming no instrument (wait 3), a
# note event (wait 1), the terminator -- classic grammar.
_STREAM = bytes([0, 0, 0x03, 0x20, 0x43, 0x01, 0x22, 0xFF])


def test_the_decoder_records_every_events_first_row():
    ev: list = []
    events = P._build_raw_pattern(_STREAM, 2, event_rows=ev)
    rows = [events[i:i + 4] for i in range(0, len(events), 4)]
    assert ev == [0, 4, 8]
    # The case the channel exists for: the no-note event's row is byte for
    # byte its neighbours' hold rows.
    assert rows[4] == rows[1] == rows[5] == [P.GT_NO_NOTE, 0, 0, 0]
    # ...and asking for it changes no byte of the stream.
    assert P._build_raw_pattern(_STREAM, 2) == events


def _fake_convert(monkeypatch, streams, **kw):
    """convert_patterns over hand-written entries: `streams[i]` is
    (event stream, event-start rows) for entry i."""
    def decode_entry(sid, det, i, *a, event_rows=None, **k):
        events, starts = streams[i]
        if event_rows is not None:
            event_rows.extend(starts)
        return list(events)
    monkeypatch.setattr(P, "decode_entry", decode_entry)
    det = SimpleNamespace(pattern_used=len(streams) - 1, table_stride=1,
                          pattern_lo=0, pattern_hi=len(streams),
                          pattern_dialect=kw.pop("dialect", "classic"),
                          note_flag=False)
    sid = SimpleNamespace(data=bytes(64))
    return P.convert_patterns(sid, det, lambda *a, **k: None, **kw)


def _rows(*cells):
    out = []
    for c in cells:
        out += c
    return out


NOTE = [P.GT_FIRSTNOTE + 24, 2, 0, 0]
HOLD = [P.GT_NO_NOTE, 0, 0, 0]
END = [0xFF, 0, 0, 0]


def test_convert_patterns_rebases_the_starts_onto_each_slice(monkeypatch):
    # Entry 0: note, hold, no-note event, hold, note, hold -- sliced at 2
    # rows, so the starts {0, 2, 4} land on row 0 of each slice.
    stream = _rows(NOTE, HOLD, HOLD, HOLD, NOTE, HOLD, END)
    pats, ti = _fake_convert(monkeypatch, [(stream, [0, 2, 4])],
                             max_rows=2, event_rows=True)
    assert [ti.event_rows[i] for i in ti[0]][:3] == [frozenset({0})] * 3
    # Off, the channel is empty and the patterns are the same.
    pats_off, ti_off = _fake_convert(monkeypatch, [(stream, [0, 2, 4])],
                                     max_rows=2)
    assert ti_off.event_rows == {} and list(pats_off) == list(pats)


def test_a_shared_pattern_whose_sources_disagree_is_unknown(monkeypatch):
    # Byte-identical streams: entry 0 has a no-note event on row 2, entry 1
    # holds through it. Dedup shares them; the starts cannot both be right.
    stream = _rows(NOTE, HOLD, HOLD, HOLD, END)
    streams = [(stream, [0, 2]), (stream, [0])]
    pats, ti = _fake_convert(monkeypatch, streams, dedup=True,
                             event_rows=True)
    assert ti[0] == ti[1] and ti.event_rows[ti[0][0]] is None
    # The dedup key is not changed for it: one pattern either way.
    pats_off, _ = _fake_convert(monkeypatch, streams, dedup=True)
    assert len(pats) == len(pats_off) == 1
    # Agreeing sources keep their set.
    pats, ti = _fake_convert(monkeypatch, [(stream, [0, 2])] * 2,
                             dedup=True, event_rows=True)
    assert ti.event_rows[ti[0][0]] == frozenset({0, 2})


def test_a_variant_and_a_waveform_copy_carry_their_sources_starts(
        monkeypatch):
    # Entry 1 is an octave variant of entry 0 (shift_notes moves no row),
    # entry 2 a waveform-state copy (decoded again from the same source):
    # both start their events on the source's rows.
    stream = _rows(NOTE, HOLD, HOLD, HOLD, END)
    pats, ti = _fake_convert(monkeypatch, [(stream, [0, 2])],
                             event_rows=True, variants=[(0, 1)],
                             wave_copies=[(0, {})])
    assert len(ti) == 3
    assert pats[ti[1][0]][0] == NOTE[0] + 12
    for entry in (0, 1, 2):
        assert ti.event_rows[ti[entry][0]] == frozenset({0, 2}), entry


def test_a_non_classic_dialect_reads_unknown(monkeypatch):
    stream = _rows(NOTE, HOLD, END)
    _, ti = _fake_convert(monkeypatch, [(stream, [0])], event_rows=True,
                          dialect="ilv")
    assert ti.event_rows[ti[0][0]] is None


def test_a_copy_inherits_by_note_column_only_where_one_set_matches():
    a = _rows(NOTE, HOLD, HOLD, END)
    b = _rows([NOTE[0] + 1, 2, 0, 0], HOLD, HOLD, END)
    c = _rows([NOTE[0] + 2, 2, 0, 0], HOLD, END)
    pats = [a, list(a), b, list(b), c,
            # copies, appended by later passes with a column edited
            [x if i != 2 else 0x0F for i, x in enumerate(a)],
            list(b), list(c), _rows(HOLD, END)]
    known = {0: frozenset({0, 1}), 1: frozenset({0, 1}),
             2: frozenset({0}), 3: frozenset({0, 2}), 4: None}
    out = P.inherit_event_rows(pats, known)
    assert out[5] == frozenset({0, 1})      # one matching set
    assert 6 not in out                     # two sources disagree
    assert 7 not in out                     # its source is unknown
    assert 8 not in out                     # matches nothing
    assert 4 not in out                     # unknown stays unknown


def _walk(event_rows, row2=HOLD):
    """One voice sweeping instrument 2 every tick, 2 ticks a row: a note,
    three rows, a note. Returns the two notes' planned (width, dir)."""
    pattern = _rows(NOTE, HOLD, row2, HOLD, NOTE, HOLD, END)
    tracks = [[0, P.GT_ORDER_RESTART, 0], [0, P.GT_ORDER_RESTART, 0],
              [0, P.GT_ORDER_RESTART, 0]]
    # voices 1 and 2 play the same pattern under an instrument with no sim
    other = _rows([NOTE[0], 3, 0, 0], HOLD, HOLD, HOLD, END)
    patterns = [pattern, other]
    tracks[1][0] = tracks[2][0] = 1
    sims = {2: PulsePhaseSim(0x800, 0x10, 1, 0x2, 0xE)}
    start = [(0, ((2, +1, 0), (3, +1, 0), (3, +1, 0)))]
    phases, writes = P.collect_pulse_phases(
        patterns, tracks, [2], sims, tri_start=start,
        event_rows=event_rows)
    rows = {r: ph for ti, pos, rr in writes if ti == 0
            for r, (_, ph) in rr.items()}
    return rows[0], rows[4]


def test_the_walk_spends_a_tick_on_a_fetch_the_bytes_cannot_see():
    first_hidden, second_hidden = _walk({0: frozenset({0, 2, 4})})
    first_bytes, second_bytes = _walk(None)
    assert first_hidden == first_bytes == (0x800, 1)
    # 4 rows of 2 ticks, the note's fetch tick skipped: 7 steps by the
    # bytes; the no-note event on row 2 is a second fetch, so 6.
    assert second_bytes == (0x800 + 7 * 0x10, 1)
    assert second_hidden == (0x800 + 6 * 0x10, 1)
    # A pattern the channel names is read by it ALONE: a row it calls a
    # hold is one, whatever its bytes would have said. Row 2 carrying an
    # instrument byte reads as a fetch by the bytes...
    named = [P.GT_NO_NOTE, 2, 0, 0]
    assert _walk(None, named)[1] == (0x800 + 6 * 0x10, 1)
    # ...and as the hold the decoder says it is, where the channel has it.
    assert _walk({0: frozenset({0, 4})}, named)[1] == (0x800 + 7 * 0x10, 1)


# Hidden fetches (decoder start, bytes say hold) on played positions of the
# walk's patterns, per file, presets + pulse_phase forced, measured at
# 8586101 + this change. Every other corpus file with the triangle walk has
# none, and no file has a row the bytes call a fetch that is not a start.
HIDDEN = {"Devils_Galop.sid": 4, "Master_of_Magic.sid": 31,
          "Thing_on_a_Spring.sid": 34, "Zoids.sid": 6}
# The files whose first walk plans differently with the event starts than
# by bytes alone (measured on the merged tree; see the module docstring).
MOVES = {"Thing_on_a_Spring.sid"}


@pytest.mark.parametrize("name", sorted(HIDDEN) + ["Game_Killer.sid"])
def test_the_walk_receives_the_hidden_fetches(name):
    presets = REPO_ROOT / "presets.json"
    corpus = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
    if not presets.exists() or not (corpus / name).exists():
        pytest.skip("corpus or presets.json not available here")
    import fidelity
    from h2g import convert as C
    doc = json.loads(presets.read_text(encoding="utf-8"))
    kw = fidelity._preset_opts(doc, name)
    kw["pulse_phase"] = True
    calls = []
    real = C.collect_pulse_phases

    def spy(pats, tracks, *a, **k):
        calls.append((pats, [list(t) for t in tracks], k.get("event_rows"),
                      a, dict(k)))
        return real(pats, tracks, *a, **k)
    C.collect_pulse_phases = spy
    try:
        C.convert(str(corpus / name), log=lambda *a, **k: None, **kw)
    finally:
        C.collect_pulse_phases = real
    assert calls, "the triangle walk did not run"
    pats, tracks, ev, args, kwargs = calls[0]
    assert ev, "the walk received no event starts"
    # Re-walk the captured call twice, with the starts and by bytes alone
    # (the triangle walk clones its records, so the sims can be shared).
    by_bytes = dict(kwargs, event_rows=None)
    plans = [real([list(p) for p in pats], [list(t) for t in tracks],
                  *args, **k) for k in (kwargs, by_bytes)]
    assert (plans[0] != plans[1]) == (name in MOVES), name
    hidden = false = 0
    for t in tracks:
        for b in t:
            if b == P.GT_ORDER_RESTART:
                break
            if b >= P.MAX_PATTERNS or b >= len(pats) or b not in ev:
                continue
            for r, kind, _ in P._phase_note_rows(pats[b], 0, {}):
                if kind == "note":
                    assert r in ev[b], (b, r)
                    continue
                byte = (pats[b][4 * r] == P.GT_KEYOFF
                        or bool(pats[b][4 * r + 1]))
                hidden += r in ev[b] and not byte
                false += byte and r not in ev[b]
    assert (hidden, false) == (HIDDEN.get(name, 0), 0)
