"""A stored-wave note sounds what the OTHER voices hold at the fetch, so two
orderlist positions naming one pattern can sound it differently -- and one
note per pattern is a compromise there. `stored_wave.stored_wave_copies`
gives every orderlist position whose own plays agree on a different note map
its own pattern copy, numbered after `fold_transposes`' variants, and
`patterns.convert_patterns` decodes each copy from its source with that map.

Re-measured on this tree (2026-10-04, `C:/t/stored-wave-per-state-variants/
probe.py`): Crazy_Comets' pattern $18 is played 12 times, 6 under a triangle
on voice 1 (C-4, positions 14/31/32) and 6 under a pulse (B-5, positions
42/43/44) -- the majority kept C-4 for all 12; Gremlins' pattern $4F is
played 64 times (event 0 at subtune 4's position 1 sounds B-4 twice, every
other play of it B-5). After the copies, no play of either disagrees with
the note its own position emits.
"""
import copy
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import patterns, stored_wave  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.patterns import command_floor  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

# Table entries (C-0 = 0).
B_4, C_4, B_5 = 59, 48, 71


def _setup(name):
    """The orderlists and the walk's votes as convert() sees them under the
    shipped presets for these files (`slides` and `status_bit6` on)."""
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda m: None)
    tracks = convert_tracks(sid, det, lambda m: None)
    floor = command_floor(det.read_track_version, det.track_fd_transpose)
    landings = stored_wave.stored_wave_landings(sid, det)
    votes = stored_wave._walk(sid, det, tracks, landings, True, True)
    return sid, det, tracks, floor, votes


def _copies(sid, det, tracks, first, limit, log=None):
    rewritten = copy.deepcopy(tracks)
    out, cps = stored_wave.stored_wave_copies(
        sid, det, rewritten, first, limit, log, slides=True, status_bit6=True)
    return rewritten, out, cps


def _changed(before, after):
    return [(t, p, a, b) for t, (x, y) in enumerate(zip(before, after))
            for p, (a, b) in enumerate(zip(x, y)) if a != b]


@needs_corpus
def test_crazy_comets_pulse_positions_get_their_own_b5_copy():
    sid, det, tracks, floor, _ = _setup("Crazy_Comets.sid")
    first = det.pattern_used + 1
    rewritten, out, cps = _copies(sid, det, tracks, first, floor)
    # The triangle positions (6 plays, first reached) keep the pattern and
    # its C-4; the pulse positions get one copy, B-5.
    assert out == {0x18: {0: C_4}}
    assert cps == [(0x18, {0: B_5})]
    assert _changed(tracks, rewritten) == [
        (0, 42, 0x18, first), (0, 43, 0x18, first), (0, 44, 0x18, first)]


@needs_corpus
def test_gremlins_one_position_gets_its_own_b4_copy():
    sid, det, tracks, floor, _ = _setup("Gremlins.sid")
    first = det.pattern_used + 1
    rewritten, out, cps = _copies(sid, det, tracks, first, floor)
    assert out == {0x4F: {0: B_5, 1: B_5, 2: B_5, 3: B_5}}
    assert cps == [(0x4F, {0: B_4, 1: B_5, 2: B_5, 3: B_5})]
    # Subtune 4's voice 1, its first play of the pattern.
    assert _changed(tracks, rewritten) == [(13, 1, 0x4F, first)]


@needs_corpus
@pytest.mark.parametrize("name,before", [("Crazy_Comets.sid", 6),
                                         ("Gremlins.sid", 2)])
def test_every_play_hears_its_own_waveform_state(name, before):
    """The property the copies exist for: each vote the walk casts -- the
    pitch the original sounds at that fetch -- equals the note the pattern
    its orderlist position NOW names gives that event."""
    sid, det, tracks, floor, votes = _setup(name)
    notes = stored_wave.stored_wave_notes(sid, det, tracks, slides=True,
                                          status_bit6=True)
    assert sum(1 for (_g, _v, _t, _p, e, o, _f, d) in votes
               if notes[e][o] != d) == before
    first = det.pattern_used + 1
    rewritten, out, cps = _copies(sid, det, tracks, first, floor)
    by_number = {first + j: m for j, (_src, m) in enumerate(cps)}
    wrong = [(g, v, p, e, o, d) for (g, v, _t, p, e, o, _f, d) in votes
             if by_number.get(rewritten[3 * g + v][p], out.get(e))[o] != d]
    assert wrong == []


@needs_corpus
def test_no_copy_at_or_past_the_command_floor():
    """An orderlist byte at the floor is a command, not a pattern: a copy
    that would be numbered there is refused, and its positions keep the
    pattern's majority -- the pre-copy output."""
    sid, det, tracks, floor, _ = _setup("Crazy_Comets.sid")
    lines = []
    rewritten, out, cps = _copies(sid, det, tracks, floor, floor, lines.append)
    assert cps == [] and rewritten == tracks
    assert out == {0x18: {0: C_4}}
    assert any("3 position(s) kept the majority" in m for m in lines)


def _decode_with_copies(sid, det, wave_notes, cps):
    lines = []
    new_patterns, ti = patterns.convert_patterns(
        sid, det, lines.append, slides=True, status_bit6=True,
        wave_notes=wave_notes, wave_copies=cps)
    return new_patterns, ti, lines


@needs_corpus
def test_copy_is_its_source_with_only_the_landing_note_moved():
    sid, det, tracks, floor, _ = _setup("Crazy_Comets.sid")
    first = det.pattern_used + 1
    _, out, cps = _copies(sid, det, tracks, first, floor)
    pats, ti, _ = _decode_with_copies(sid, det, out, cps)
    assert len(ti) == first + 1
    src, cpy = ti[0x18], ti[first]
    assert len(src) == len(cpy) == 1
    a, b = pats[src[0]], pats[cpy[0]]
    assert a[0] == patterns.GT_FIRSTNOTE + C_4 + det.note_base
    assert b[0] == patterns.GT_FIRSTNOTE + B_5 + det.note_base
    assert [i for i in range(max(len(a), len(b)))
            if a[i:i + 1] != b[i:i + 1]] == [0]


@needs_corpus
def test_a_copy_that_would_reach_max_patterns_is_dropped(monkeypatch):
    """Copies are appended last, so the cap is checked BEFORE a copy's
    slices are appended: one that would bring the output to MAX_PATTERNS is
    dropped and its positions play the source (the majority note) instead
    of the whole conversion aborting."""
    sid, det, tracks, floor, _ = _setup("Crazy_Comets.sid")
    first = det.pattern_used + 1
    _, out, cps = _copies(sid, det, tracks, first, floor)
    plain, _, _ = _decode_with_copies(sid, det, out, [])
    n0 = len(plain)

    # Exactly room for it: the copy's one slice brings the count to n0 + 1,
    # still below a cap of n0 + 2.
    monkeypatch.setattr(patterns, "MAX_PATTERNS", n0 + 2)
    pats, ti, lines = _decode_with_copies(sid, det, out, cps)
    assert len(pats) == n0 + 1 and ti[first] == [n0]
    assert not any("DROPPED" in m for m in lines)

    # One fewer: the copy would reach the cap, so it is dropped.
    monkeypatch.setattr(patterns, "MAX_PATTERNS", n0 + 1)
    pats, ti, lines = _decode_with_copies(sid, det, out, cps)
    assert len(pats) == n0
    assert ti[first] == ti[0x18]
    assert any("1 WAVEFORM-STATE PATTERN COP(IES) DROPPED" in m for m in lines)


def test_commando_is_held_so_no_copy_is_made():
    sid = load_sid(str(pathlib.Path(__file__).resolve().parents[2]
                       / "Commando.sid"))
    sid, det = _detect_tables(sid, lambda m: None)
    tracks = convert_tracks(sid, det, lambda m: None)
    floor = command_floor(det.read_track_version, det.track_fd_transpose)
    rewritten, out, cps = _copies(sid, det, tracks, det.pattern_used + 1, floor)
    assert (out, cps) == ({}, []) and rewritten == tracks


@needs_corpus
def test_copies_follow_the_octave_variants_in_numbering():
    """`convert` numbers copy j `pattern_used + 1 + len(variants) + j`, and
    convert_patterns must append them in that order. No corpus file has both
    (Crazy_Comets and Gremlins fold no transpose), so a synthetic variant
    pins the order: the variant is entry `first`, the copy `first + 1`."""
    sid, det, tracks, floor, _ = _setup("Crazy_Comets.sid")
    first = det.pattern_used + 1
    _, out, cps = _copies(sid, det, tracks, first + 1, floor)
    pats, ti = patterns.convert_patterns(
        sid, det, lambda m: None, slides=True, status_bit6=True,
        wave_notes=out, wave_copies=cps, variants=[(0x18, 1)])
    variant, cpy = pats[ti[first][0]], pats[ti[first + 1][0]]
    base = patterns.GT_FIRSTNOTE + det.note_base
    assert variant[0] == base + C_4 + 12
    assert cpy[0] == base + B_5


@needs_corpus
@pytest.mark.parametrize("name,line", [
    ("Crazy_Comets.sid", "1 waveform-state cop(ies) for 3 orderlist position(s)"),
    ("Gremlins.sid", "1 waveform-state cop(ies) for 1 orderlist position(s)")])
def test_convert_wires_the_copies_through(name, line, monkeypatch):
    """Under the shipped presets, the copies reach convert_patterns."""
    import json
    import warnings
    import fidelity as F
    from h2g import convert as C
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    seen = {}
    real = C.convert_patterns

    def spy(*a, **k):
        seen["copies"] = k.get("wave_copies")
        return real(*a, **k)

    monkeypatch.setattr(C, "convert_patterns", spy)
    lines = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        C.convert(str(CORPUS / name), log=lines.append,
                  **F._preset_opts(doc, name))
    assert len(seen["copies"]) == 1
    assert any(line in m for m in lines)
