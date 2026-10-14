"""Does the orderlist's restart loop play any note row in a state the first pass
never put it in?

`past_table_wave._walk` / `_contexts` read each track once, from position 0 to
its `$FF`, and stop; the byte after `$FF` (the restart position) is never
followed. Goattracker does follow it (`gplay.c:966`), and the voice's
transpose, latched instrument and latched note are NOT reset by the loop
(`gplay.c:222` clears `trans` only on song start): a looped tail can run under
the transpose the list ended on, so a row that reads past the note table there
could be missed.

`past-table-walk-ignores-orderlist-restart-transpose` measured it (95 corpus
files under presets, 89 converted, 122 views, before and after the pass):
no loop visit differs from the first pass anywhere. The converter opens every
track's list with a transpose entry (`$F0`/`$FE`), and a restart that is not
position 0 lands at a point whose state the first pass already visited. So the
single-pass walk is exact on this corpus and was left alone; this file pins
the property it relies on and shows the measure has power.

* `_loop_only_visits` follows the restart, carrying (trans, instr, note), until
  the state at loop entry repeats, and returns the (pattern, row, wave start,
  note, instr) visits the loop makes that no first-pass visit of that row made;
* the corpus test asserts it is empty for every file in `_CHECKED`;
* the power tests make it non-empty: on a hand-built song, and on a real
  converted song with its leading transpose entry turned into a no-op.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W                       # noqa: E402
from h2g.goatwriter.appending import _parse_song           # noqa: E402
from test_past_table_split import _corpus_convert          # noqa: E402

# The 11 files with a (note row, visit) that reads past the table before the
# pass, plus every converting file whose first pass ends under a non-zero
# transpose (the case the loop could carry).
_MIXED = ["5_Title_Tunes.sid", "Crazy_Comets.sid", "International_Karate.sid",
          "Master_of_Magic.sid", "Nineteen.sid", "Rock_Tells_the_Tale.sid",
          "Saboteur_II.sid", "Star_Paws.sid", "Thing_on_a_Spring.sid",
          "Trans-Atlantic_Balloon_Challenge.sid", "Wiz.sid"]
_CARRYING = ["Powerplay_Hockey_USA_vs_USSR.sid", "Mr_Meaner.sid",
             "Shockway_Rider.sid", "Thundercats.sid", "Off_the_Cuff.sid",
             "One_on_One_Jordan_vs_Bird.sid", "Kings_of_the_Beach_intro.sid",
             "Deep_Strike.sid", "Chicken_Song.sid", "I_Ball.sid",
             "Auf_Wiedersehen_Monty.sid"]
_CHECKED = _MIXED + _CARRYING


def _passes(song, top=None):
    """(track, orderlist position, pattern, [(row offset, wave start, note,
    instr), ...], pass number) for every visit, the restart followed."""
    count = len(song.instruments)
    for ti, track in enumerate(song.tracks):
        end = next((i for i in range(len(track) - 1) if track[i] == 0xFF), None)
        if end is None:
            continue
        restart = track[-1]
        trans, instr, note = 0, 1, None
        seen, pos, passno = set(), 0, 0
        while True:
            for p in range(pos, end):
                b = track[p]
                if 0xE0 <= b < 0xFF:
                    trans = b - 0xF0
                    continue
                if 0xD0 <= b < 0xE0 or b >= len(song.patterns):
                    continue
                pat = song.patterns[b]
                deltas = W._row_deltas(top, pat)
                rows = []
                for k in range(0, len(pat) - 3, 4):
                    nt, ins, cmd, data = pat[k:k + 4]
                    if ins:
                        instr = ins
                    start = None
                    delta = 0
                    if W._FIRST_NOTE <= nt <= W._LAST_NOTE:
                        note = nt - W._FIRST_NOTE + trans
                        delta = deltas.get(k, 0)
                        if 0 < instr <= count and song.instruments[instr - 1][2]:
                            start = song.instruments[instr - 1][2]
                    if (cmd & 0x0F) == W._CMD_SETWAVEPTR and data \
                            and note is not None:
                        start = data
                    if start is not None and note is not None:
                        rows.append((k, start, note + delta, instr))
                yield ti, p, b, rows, passno
            state = (trans, instr, note, restart)
            if restart >= end or state in seen or passno > 20:
                break
            seen.add(state)
            pos, passno = restart, passno + 1


def _loop_only_visits(song, top=None):
    first, later = {}, {}
    for _ti, _p, b, rows, passno in _passes(song, top):
        for k, start, note, instr in rows:
            (first if passno == 0 else later).setdefault((b, k), set()).add(
                (start, note, instr))
    return sorted((b, k, v) for (b, k), vs in later.items()
                  for v in vs if v not in first.get((b, k), ()))


def _top(det):
    return W.top_rows_of(getattr(det, "top_cols", None))


@pytest.mark.parametrize("name", _CHECKED)
def test_the_restart_loop_plays_no_row_in_a_state_the_first_pass_did_not(name):
    _out, seen = _corpus_convert(name)
    assert seen
    for before, after, _sid, det in seen:
        for blob in (before, after):
            assert _loop_only_visits(_parse_song(blob), _top(det)) == []


def _toy(tracks):
    # one instrument (wave start 1); pattern 0: a note row at note 12;
    # pattern 1: no notes
    return SimpleNamespace(
        instruments=[bytearray([0, 0, 1, 0, 0, 0, 0, 0, 0])],
        patterns=[bytearray([W._FIRST_NOTE + 12, 1, 0, 0] + [0] * 4),
                  bytearray([0] * 8)],
        tracks=tracks)


def test_the_measure_sees_a_loop_that_carries_a_transpose():
    # list: pattern 0 at +0, then transpose +2 and an empty pattern, restart
    # at 0. The restart lands before any transpose entry, so the second pass
    # runs pattern 0 under +2 (the transpose the list ended on).
    song = _toy([bytes([0, 0xF2, 1, 0xFF, 0])])
    assert _loop_only_visits(song) == [(0, 0, (1, 14, 1))]


def test_the_measure_is_quiet_when_the_restart_lands_on_a_transpose_entry():
    song = _toy([bytes([0xF0, 0, 0xF2, 1, 0xFF, 0])])
    assert _loop_only_visits(song) == []


def test_the_measure_sees_a_real_song_whose_leading_transpose_is_removed():
    """Powerplay_Hockey opens each list with `$F0` and ends on `$F2`/`$F5`: the
    loop is harmless only because of that entry. Turn it into a repeat marker
    (the walk skips both) and the loop carries the end transpose."""
    _out, seen = _corpus_convert("Powerplay_Hockey_USA_vs_USSR.sid")
    before, _after, _sid, det = seen[0]
    song = _parse_song(before)
    assert _loop_only_visits(song, _top(det)) == []
    tracks = []
    for t in song.tracks:
        assert t[0] == 0xF0
        tracks.append(bytes([0xD0]) + t[1:])
    song.tracks = tracks
    assert _loop_only_visits(song, _top(det)) != []
