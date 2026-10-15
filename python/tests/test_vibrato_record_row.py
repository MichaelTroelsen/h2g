"""The global-triangle vibrato is sized by the row the START subtune plays.

`tracks.instrument_row_calls` is a MINIMUM over the subtunes that play a
record -- the right bound for the gatetimer, where a value too large stops the
song, and the wrong row for the vibrato's tick-0 correction
(`vibrato._triangle_vibrato_entry`), which is a function of the row and not a
bound. A record played at 2-call rows in a funk subtune and 4-call rows in the
tune was given the 2-call entry (`cmp` 0) for both, which ran the tune's
oscillator too fast (Human_Race subtune 0 `vib` 0.868 -> 1.251 under the
correction, figures historical).

`InstrumentRowCalls.start_rows` already carries "the row the start subtune
plays each record at" for the drum sweep; `_record_row_calls` is the one
reader of it, now shared (`goatwriter.primitives`). What is pinned:

  1. the helper's order -- start subtune, else the shortest, else the file's --
     and that the drum sweep and the vibrato read the same function;
  2. `_vibrato_layout` hands a triangle record its START row where the start
     subtune plays it, its shortest row where it does not, the file's where
     the record is not attributed, and ignores `start_rows` of a plain dict;
  3. through `build_sng` on Human_Race: the record both its subtunes share
     (instrument 1, 4-call rows in subtune 0 and 2-call in subtune 4) is asked
     for at 4, and a record only the 2-call subtune plays is still asked at 2.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.detect import detect  # noqa: E402
from h2g.goatwriter import _triangle_vibrato_entry  # noqa: E402
from h2g.goatwriter import primitives, wavetable  # noqa: E402
from h2g.goatwriter.constants import FORMAT_GTS5  # noqa: E402
from h2g.goatwriter.vibrato import _vibrato_layout  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import InstrumentRowCalls  # noqa: E402


def _rows(shortest, start):
    out = InstrumentRowCalls(shortest)
    out.start_rows = dict(start)
    return out


def test_one_helper_serves_the_drum_sweep_and_the_vibrato():
    assert wavetable._record_row_calls is primitives._record_row_calls
    both = _rows({3: 2, 4: 3}, {3: 4})
    assert primitives._record_row_calls(both, 3, 99) == 4    # start subtune
    assert primitives._record_row_calls(both, 4, 99) == 3    # else shortest
    assert primitives._record_row_calls(both, 5, 99) == 99   # else the file's
    assert primitives._record_row_calls({3: 2}, 3, 99) == 2  # plain dict


@needs_corpus
def test_the_layout_takes_the_start_subtunes_row_where_it_plays_the_record():
    sid = load_sid(str(CORPUS / "Gerry_the_Germ.sid"))
    det = detect(sid, log=lambda m: None)
    assert det.triangle_vibrato is not None
    n, lead, data = 30, 1, sid.data
    live = [i for i in range(n - 1)
            if det.instr_start + i * det.instr_stride < len(data)
            and _triangle_vibrato_entry(
                data[det.instr_start + i * det.instr_stride
                     + det.triangle_vibrato], 1) is not None]
    assert len(live) >= 6
    third = len(live) // 3
    started, shortest_only = live[:third], live[third:2 * third]
    # Every record's shortest row is 2; the start subtune plays the first
    # third of them at 4, the second third not at all, and the last third are
    # not attributed (the file's row, 3, stands).
    shortest = {i + lead + 1: 2 for i in started + shortest_only}
    start = {i + lead + 1: 4 for i in started}
    want = {}
    for i in live:
        byte = data[det.instr_start + i * det.instr_stride
                    + det.triangle_vibrato]
        row = (4 if i in started else 2 if i in shortest_only else 3)
        want[i] = _triangle_vibrato_entry(byte, 1, row)
    table: list = []
    got = _vibrato_layout(sid, det, n, True, FORMAT_GTS5, 1, table,
                          lead=lead, row_calls=3,
                          instr_row_calls=_rows(shortest, start))
    assert set(got) == set(live)
    for i in live:
        assert table[got[i][0] - 1] == want[i], i
    # A plain dict has no start rows: the shortest row for everything it
    # holds, which is what the layout read before.
    table2: list = []
    plain_got = _vibrato_layout(sid, det, n, True, FORMAT_GTS5, 1, table2,
                                lead=lead, row_calls=3,
                                instr_row_calls=dict(shortest))
    for i in started:
        byte = data[det.instr_start + i * det.instr_stride
                    + det.triangle_vibrato]
        assert table2[plain_got[i][0] - 1] == _triangle_vibrato_entry(
            byte, 1, 2), i
    assert table2[plain_got[started[0]][0] - 1] != table[got[started[0]][0] - 1]


def _asked(monkeypatch, name):
    """{(byte, row): entry} for every triangle entry asked while `name`
    converts under presets."""
    import fidelity as F
    from h2g.convert import convert
    import h2g.goatwriter.vibrato as V
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text())
    seen = []
    real = V._triangle_vibrato_entry

    def spy(byte, mult, rc=0):
        out = real(byte, mult, rc)
        seen.append((byte, mult, rc, out))
        return out
    monkeypatch.setattr(V, "_triangle_vibrato_entry", spy)
    convert(str(CORPUS / name), log=lambda m: None,
            **F._preset_opts(doc, name))
    return [s for s in seen if s[3] is not None]


@needs_corpus
def test_human_race_shared_record_is_asked_at_the_tunes_row(monkeypatch):
    """Instrument 1 is every voice's start instrument, so subtune 4's 2-call
    rows play it too; subtune 0 (the tune, 4-call rows) is the start. The
    other vibrato records are each played in one subtune only: 4-call
    records at 4 and subtune 4's (2-call) at 2."""
    sid = load_sid(str(CORPUS / "Human_Race.sid"))
    det = detect(sid, log=lambda m: None)
    first = sid.data[det.instr_start + det.triangle_vibrato]
    asked = _asked(monkeypatch, "Human_Race.sid")
    rows = {rc for _, _, rc, _ in asked}
    assert rows == {2, 3, 4}
    assert (first, 1, 4, _triangle_vibrato_entry(first, 1, 4)) in asked
    assert (first, 1, 2, _triangle_vibrato_entry(first, 1, 2)) not in asked
    # Records only the funk subtune plays are still the 2-call entry.
    assert any(rc == 2 for _, _, rc, _ in asked)
