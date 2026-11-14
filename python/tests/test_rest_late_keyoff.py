"""A ringing rest's KEYOFF one row later (h2g.rest_late_keyoff).

Las_Vegas_Video_Poker voice 1 plays 36 notes with status bit 5 (no cut of
their own) before a bit-6 rest: the original's gate drops on the rest's first
tick, 15 frames in. Ours sounded 11 -- Goattracker fetches the KEYOFF row
`gatetimer` calls before its own tick 0 and drops the gate AT THE FETCH, and
this song's records carry 14 of a 15-call row, so the gate fell 14 calls (3.5
frames at -S4) early. One row later the fetch lands on the call after the
rest's tick 0.

The synthetic song below is one record (gatetimer 14), rows of 15 calls at
multiplier 4: a note, three holds the last of which carries the ring
(`CMD_SETSR $0C`), the KEYOFF, three rests. Only a rest that is RINGING moves.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import rest_late_keyoff as rlk                      # noqa: E402
from h2g.goatwriter import HEADER_LEN                        # noqa: E402

import songview                                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
C4 = 0x60 + 12 * 4
REST, KEYOFF, END = 0xBD, 0xBE, 0xFF
SETSR, TONEPORTA, SETPULSEPTR = 6, 3, 9

needs_siddump = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and fidelity.supports_calls_per_frame(fidelity.SIDDUMP)),
    reason="no -m siddump on this machine (tools/siddump-rt, see its README): "
           "Las_Vegas runs at -S4")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def record(gatetimer):
    r = bytearray(25)
    r[2] = 1
    r[7] = gatetimer
    return bytes(r)


def song(patterns, order, gatetimer=0x8E):
    """A GTS5 song: one record, voice 0 plays `order` (pattern numbers) and
    restarts at position 0; voices 1 and 2 are empty."""
    out = bytearray(b"GTS5" + bytes(HEADER_LEN - 4))
    out.append(1)
    for track in (list(order) + [0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]):
        out.append(len(track) - 1)
        out += bytes(track)
    out.append(1)
    out += record(gatetimer)
    wtbl = [(0x41, 0x00), (0xFF, 0x00)]
    out.append(len(wtbl))
    out += bytes(left for left, _ in wtbl) + bytes(right for _, right in wtbl)
    for _ in range(3):                       # pulse, filter, speed tables
        out.append(0)
    out.append(len(patterns))
    for rows in patterns:
        out.append(len(rows) + 1)
        for row in rows:
            out += bytes(row)
        out += bytes([END, 0, 0, 0])
    return bytes(out)


RING = (REST, 0, SETSR, 0x0C)
CUT = (REST, 0, SETSR, 0x00)
HOLD = (REST, 0, 0, 0)
RINGING = [(C4, 1, 0, 0), HOLD, HOLD, RING, (KEYOFF, 0, 0, 0), HOLD, HOLD, CUT]


def run(blob, calls=(15,), multiplier=4):
    return rlk.rest_late_keyoff(blob, list(calls) if calls else None,
                                multiplier)


def notes(sng, pattern=0):
    p = sng.patterns[pattern]
    return [p[4 * r] for r in range(len(p) // 4)]


def parsed(blob):
    return songview.parse_sng(blob)


def test_a_ringing_rest_keyoff_moves_one_row_later():
    got = parsed(run(song([RINGING], [0])))
    assert notes(got)[:8] == [C4, REST, REST, REST, REST, KEYOFF, REST, REST]
    # The ring and the cut stay on their rows: only the note column moved.
    p = got.patterns[0]
    assert (p[4 * 3 + 2], p[4 * 3 + 3]) == (SETSR, 0x0C)
    assert (p[4 * 7 + 2], p[4 * 7 + 3]) == (SETSR, 0x00)


def test_the_row_stays_a_bare_rest_with_its_own_command():
    rows = list(RINGING)
    rows[4] = (KEYOFF, 0, SETPULSEPTR, 0x3F)
    got = parsed(run(song([rows], [0])))
    p = got.patterns[0]
    assert p[4 * 4] == REST and (p[4 * 4 + 2], p[4 * 4 + 3]) == (SETPULSEPTR, 0x3F)
    assert p[4 * 5] == KEYOFF


def test_a_rest_that_does_not_ring_keeps_its_row():
    rows = list(RINGING)
    rows[3] = HOLD
    blob = song([rows], [0])
    assert run(blob) == blob


def test_a_short_gatetimer_keeps_its_row():
    # g = 2 of a 15-call row: the fetch is already within 2 calls of the row,
    # and a row later would be 13 calls LATE.
    blob = song([RINGING], [0], gatetimer=0x82)
    assert run(blob) == blob


def test_a_tied_rests_toneporta_moves_with_it_unless_the_seam_says_not(
        monkeypatch):
    rows = list(RINGING)
    rows[4] = (KEYOFF, 0, TONEPORTA, 0)
    blob = song([rows], [0])
    p = parsed(run(blob)).patterns[0]
    assert (p[4 * 4], p[4 * 4 + 2]) == (REST, TONEPORTA)
    assert p[4 * 5] == KEYOFF
    monkeypatch.setattr(rlk, "ALLOW_TONEPORTA", False)
    assert run(blob) == blob


def test_a_one_row_rest_has_no_row_to_move_to():
    rows = [(C4, 1, 0, 0), HOLD, HOLD, RING, (KEYOFF, 0, 0, 0), (C4, 1, 0, 0)]
    blob = song([rows], [0])
    assert run(blob) == blob


def test_without_the_subtune_clock_nothing_changes():
    blob = song([RINGING], [0])
    assert run(blob, calls=None) == blob


def test_a_rest_that_opens_a_pattern_is_moved_where_the_ring_precedes_it():
    first = [(C4, 1, 0, 0), HOLD, HOLD, RING]
    opener = [(KEYOFF, 0, 0, 0), HOLD, HOLD, CUT]
    got = parsed(run(song([first, opener], [0, 1])))
    assert notes(got, 1)[:4] == [REST, KEYOFF, REST, REST]
    assert len(got.patterns) == 2           # edited in place, nothing copied


def test_an_opener_entered_ringing_from_one_place_only_is_copied_for_it():
    ring = [(C4, 1, 0, 0), HOLD, HOLD, RING]
    plain = [(C4, 1, 0, 0), HOLD, HOLD, HOLD]
    opener = [(KEYOFF, 0, 0, 0), HOLD, HOLD, CUT]
    got = parsed(run(song([ring, plain, opener], [0, 2, 1, 2])))
    order = got.tracks[0]
    # Position 1 (after the ring) plays the copy, position 3 the original.
    assert order[1] != 2 and order[3] == 2
    assert notes(got, order[1])[:4] == [REST, KEYOFF, REST, REST]
    assert notes(got, 2)[:4] == [KEYOFF, REST, REST, REST]


def test_the_seam_turns_it_off(monkeypatch):
    blob = song([RINGING], [0])
    assert run(blob) != blob
    monkeypatch.setattr(rlk, "ENABLED", False)
    assert run(blob) == blob


def test_convert_default_is_byte_identical():
    import inspect
    from h2g.convert import convert
    assert inspect.signature(convert).parameters[
        "rest_late_keyoff"].default is False


def _row(tmp_path, name, late, seconds=20):
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    doc["songs"]["Las_Vegas_Video_Poker.sid"]["rest_late_keyoff"] = late
    presets = tmp_path / f"presets_{name}.json"
    presets.write_text(json.dumps(doc), encoding="utf-8")
    sid = tmp_path / name / "Las_Vegas_Video_Poker.sid"
    sid.parent.mkdir()
    sid.write_bytes((CORPUS / "Las_Vegas_Video_Poker.sid").read_bytes())
    out = tmp_path / f"{name}.json"
    fidelity.main([str(sid), "-t", str(seconds), "--presets", str(presets),
                   "--json", str(out), "--workdir", str(tmp_path / f"w_{name}"),
                   "--label", "test"])
    return json.loads(out.read_text(encoding="utf-8"))[0]


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_las_vegas_notes_before_a_ringing_rest_hold_the_gate_to_the_rests_frame(
        tmp_path):
    """Voice 1's first notes before a ringing rest (original frames 286,
    346, 406, ...): the shipped build drops the gate 4 frames early on every
    one of them, the moved KEYOFF on none."""
    shipped = _row(tmp_path, "shipped", False)
    moved = _row(tmp_path, "moved", True)
    assert shipped["gate_ours_silent"] >= 8, shipped["gate_ours_silent"]
    assert moved["gate_ours_silent"] == 0, moved["gate_ours_silent"]
    assert moved["gate"] > shipped["gate"]
    assert moved["melody"] == shipped["melody"]
    assert moved["retrigger_ratio"] == shipped["retrigger_ratio"]
