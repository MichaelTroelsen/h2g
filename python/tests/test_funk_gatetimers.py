"""A 2-call subtune's gatetimer bound belongs to the records that subtune plays.

`tracks.instrument_row_calls` charges an instrument the MINIMUM row over the
subtunes it is played in -- the right safety bound (a gatetimer a 2-call row's
counter never reaches stalls the voice, player.s:1090-1098) and a cost for an
instrument a longer subtune plays too: its gate-off starts a tick early in
every subtune of the file. The clone passes append records after that walk, and
a record it never saw gets the file-wide `short_row_calls`, 2 as soon as one
subtune is a funk subtune. `funk_gatetimers.split_funk_gatetimers` fixes both
on the finished bytes:

  1. a record only longer subtunes play is raised to its own rows' gatetimer;
  2. a record played in both is split -- the original keeps its number and is
     raised, a clone with the low gatetimer takes the funk subtunes' uses;
  3. a pattern a longer subtune plays too is copied, not respelled;
  4. instrument 1 (opened on without a pattern naming it) is never split on
     the funk side; the longer subtunes' named uses of it move instead.

Gerry_the_Germ lost 1.2-3.1 points of `gate` on subtunes 0/1/3/6, Human_Race
1 on subtune 1 and Auf_Wiedersehen_Monty 1.2 on subtune 0 to this, with the
funk subtune's own columns unmoved (base 2b64d25; -t 180 relative A/B, lag 0).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.funk_gatetimers import split_funk_gatetimers  # noqa: E402
from h2g.goatwriter import HEADER_LEN  # noqa: E402
from h2g.goatwriter.appending import _parse_song  # noqa: E402
from h2g.goatwriter.constants import FUNK_ROW_CALLS  # noqa: E402
from h2g.patterns import MAX_PATTERNS  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
END = [0xFF, 0x00]                       # an orderlist's end and its restart


def ticks_for(row):
    return 1 if row <= 2 else 2


def record(gatetimer, name=b"x"):
    return bytes([0, 0, 0, 0, 0, 0, 0, gatetimer, 0]) + name.ljust(16, b"\0")


def sng(orders, patterns, records):
    """A GTS5 .sng with the given orderlists (bytes incl. the end), patterns
    (lists of [note, instrument, cmd, data] rows) and instrument records."""
    b = bytearray(b"GTS5") + bytes(HEADER_LEN - 4)
    b.append(len(orders) // 3)
    for o in orders:
        b.append(len(o) - 1)
        b += bytes(o)
    b.append(len(records))
    for r in records:
        b += r
    for _ in range(4):                   # the four (empty) tables
        b.append(0)
    b.append(len(patterns))
    for p in patterns:
        b.append(len(p))
        for row in p:
            b += bytes(row)
    return bytes(b)


def named(blob):
    song = _parse_song(blob)
    return song, [[p[r + 1] for r in range(0, len(p), 4)]
                  for p in song.patterns]


def gt(blob, k):
    return _parse_song(blob).instruments[k - 1][7] & 0x3F


def two_subtunes(shared=False, p1_rows=None):
    """subtune 0 (3 calls) and subtune 1 (2 calls, funk). Every pattern's
    first row names an instrument, so no voice opens on instrument 1."""
    p0 = [[0x60, 2, 0, 0], [0x60, 3, 0, 0]]
    p1 = p1_rows or [[0x60, 2, 0, 0], [0x60, 4, 0, 0]]
    p2 = [[0x60, 5, 0, 0]]
    p3 = [[0x60, 6, 0, 0]]
    orders = [[0] + END, [2] + END, [2] + END,
              [0 if shared else 1] + END, [3] + END, [3] + END]
    recs = [record(1), record(1), record(1), record(1), record(2), record(1)]
    return sng(orders, [p0, p1, p2, p3], recs)


def test_a_record_played_in_both_is_split_and_only_longer_ones_are_raised():
    out = split_funk_gatetimers(two_subtunes(), [3, FUNK_ROW_CALLS], ticks_for)
    song, cols = named(out)
    assert len(song.instruments) == 7
    # 2: played in both -> the original rises to the 3-call subtune's value,
    # the clone (7) keeps the funk row's.
    assert (gt(out, 2), gt(out, 7)) == (2, 1)
    # 3: only the 3-call subtune plays it (the clone pass's file-wide bound).
    assert gt(out, 3) == 2
    # 4 and 6: funk only. 5: not the funk row's value, so not this pass's.
    assert (gt(out, 4), gt(out, 6), gt(out, 5)) == (1, 1, 2)
    # The funk subtune's pattern names the clone; the 3-call one is untouched.
    assert cols[1] == [7, 4] and cols[0] == [2, 3]
    # The clone is its record's bytes with nothing else changed.
    clone = _parse_song(out).instruments[6]
    assert bytes(clone) == bytes(_parse_song(two_subtunes()).instruments[1])


def test_a_pattern_a_longer_subtune_plays_too_is_copied_not_respelled():
    out = split_funk_gatetimers(two_subtunes(shared=True),
                                [3, FUNK_ROW_CALLS], ticks_for)
    song, cols = named(out)
    assert len(song.patterns) == 5
    assert cols[0] == [2, 3]                        # the shared pattern, as it was
    # Its copy, respelled: both records it names are now played in both.
    assert cols[4] == [7, 8]
    assert (gt(out, 2), gt(out, 3), gt(out, 7), gt(out, 8)) == (2, 2, 1, 1)
    assert song.tracks[0][0] == 0 and song.tracks[3][0] == 4


def test_an_implicit_use_in_a_funk_subtune_keeps_the_record_low_for_it():
    """A voice opening on rests runs under instrument 1 with no pattern naming
    it, so no column can move the FUNK side to a clone. The longer subtunes'
    named uses move instead (tests/test_funk_gatetimers_implicit.py); a record
    beside it that the same subtune names is split as usual."""
    p0 = [[0x60, 1, 0, 0], [0x60, 3, 0, 0]]         # subtune 0 names 1 and 3
    p1 = [[0x60, 0, 0, 0], [0x60, 3, 0, 0]]         # subtune 1 opens on 1
    filler = [[0x60, 4, 0, 0]]
    blob = sng([[0] + END, [2] + END, [2] + END, [1] + END, [2] + END, [2] + END],
               [p0, p1, filler], [record(1)] * 4)
    out = split_funk_gatetimers(blob, [3, FUNK_ROW_CALLS], ticks_for)
    _song, cols = named(out)
    assert gt(out, 1) == 1                          # instrument 1: untouched
    assert cols[1] == [0, 5]                        # row 0 stays, 3 -> clone 5
    assert (gt(out, 3), gt(out, 5)) == (2, 1)
    # ... and the 3-call subtune's own naming of 1 goes to clone 7 (4 is also
    # played in both, so its clone is 6), raised.
    assert cols[0] == [7, 3] and gt(out, 7) == 2


def test_an_implicit_use_in_the_funk_subtune_still_frees_the_longer_naming():
    # Record 1 is named in the 3-call subtune and opened on by the funk one:
    # the funk voice keeps record 1, the 3-call subtune's naming takes clone 3.
    p0 = [[0x60, 1, 0, 0]]
    p1 = [[0x60, 0, 0, 0]]
    blob = sng([[0] + END, [0] + END, [0] + END, [1] + END, [1] + END, [1] + END],
               [p0, p1], [record(1), record(1)])
    out = split_funk_gatetimers(blob, [3, FUNK_ROW_CALLS], ticks_for)
    _song, cols = named(out)
    assert cols == [[3], [0]] and (gt(out, 1), gt(out, 3)) == (1, 2)


@pytest.mark.parametrize("rows", [[3, 3], [2, 2], [3, 3, 2], [3]])
def test_nothing_changes_without_a_funk_subtune_and_a_longer_one(rows):
    blob = two_subtunes()
    assert split_funk_gatetimers(blob, rows, ticks_for) == blob


def test_a_gatetimer_that_is_not_the_funk_rows_is_left_alone():
    # Record 1 is named by both subtunes but carries 3, nobody's funk value.
    p = [[0x60, 1, 0, 0]]
    odd = sng([[0] + END, [0] + END, [0] + END, [1] + END, [1] + END, [1] + END],
              [p, [[0x60, 1, 0, 0]]], [record(3)])
    assert split_funk_gatetimers(odd, [3, FUNK_ROW_CALLS], ticks_for) == odd


def test_a_split_that_does_not_fit_is_declined_but_the_raise_stands():
    lines = []
    p0 = [[0x60, 2, 0, 0], [0x60, 3, 0, 0]]
    p1 = [[0x60, 2, 0, 0]]
    filler = [[0x60, 4, 0, 0]]
    recs = [record(1)] * 4 + [record(2)] * 58       # 62 records: no room
    blob = sng([[0] + END, [2] + END, [2] + END, [1] + END, [2] + END, [2] + END],
               [p0, p1, filler], recs)
    out = split_funk_gatetimers(blob, [3, FUNK_ROW_CALLS], ticks_for,
                                lines.append)
    assert any("declined" in m for m in lines)
    assert len(_parse_song(out).instruments) == 62
    assert gt(out, 2) == 1 and gt(out, 3) == 2      # 2 stays low, 3 is raised
    assert len(_parse_song(out).patterns) == 3


def test_the_pattern_limit_is_respected():
    # 206 patterns already: the funk subtune needs two copies.
    shared = [[0x60, 2, 0, 0]]
    filler = [[0x60, 4, 0, 0]]
    # Both subtunes play both patterns, so both are copied: two more.
    patterns = [shared] + [filler] * (MAX_PATTERNS - 3)
    recs = [record(1)] * 4
    orders = [[0] + END, [1] + END, [1] + END, [0] + END, [1] + END, [1] + END]
    blob = sng(orders, patterns, recs)
    assert len(patterns) == MAX_PATTERNS - 2
    out = split_funk_gatetimers(blob, [3, FUNK_ROW_CALLS], ticks_for)
    assert len(_parse_song(out).patterns) == MAX_PATTERNS
    assert len(_parse_song(out).instruments) == 6
    # One more pattern to copy than there is room for: declined.
    patterns.append(filler)
    out = split_funk_gatetimers(sng(orders, patterns, recs),
                                [3, FUNK_ROW_CALLS], ticks_for)
    assert len(_parse_song(out).patterns) == MAX_PATTERNS - 1
    assert len(_parse_song(out).instruments) == 4


# ---- the corpus -----------------------------------------------------------

# file -> (records split, records only longer subtunes play that were raised,
# subtune rows). Pinned at 2b64d25 under presets.json; a record count moving is
# a mover to be named, not noise.
CORPUS_SPLITS = {
    "Gerry_the_Germ.sid": 2,
    "Human_Race.sid": 2,
    "Auf_Wiedersehen_Monty.sid": 2,
}


@pytest.fixture(scope="module")
def conversions():
    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((ROOT / "presets.json").read_text())
    out = {}
    for name in CORPUS_SPLITS:
        lines = []
        blob = convert(str(CORPUS / name), log=lines.append,
                       **F._preset_opts(doc, name))
        out[name] = (blob, lines)
    return out


@needs_corpus
@pytest.mark.parametrize("name,splits", sorted(CORPUS_SPLITS.items()))
def test_the_corpus_funk_files_split_exactly_these_records(conversions, name,
                                                           splits):
    _blob, lines = conversions[name]
    got = [m for m in lines if m.startswith("Funk gatetimers")]
    assert len(got) == 1 and f"{splits} record(s) played in both" in got[0], got


@needs_corpus
@pytest.mark.parametrize("name", sorted(CORPUS_SPLITS))
def test_no_record_a_longer_subtune_alone_plays_keeps_the_funk_gatetimer(
        conversions, name):
    """The postcondition on the finished bytes, read independently of the
    pass: walk the orderlists, and every record no funk subtune names (or
    opens on) has the gatetimer its own shortest row gives."""
    from h2g.goatwriter.hard_restart import _hard_restart_ticks
    from h2g.patterns import GT_ORDER_RESTART
    blob, _ = conversions[name]
    song = _parse_song(blob)
    # The rows are the converter's own: recover them from the clone-free
    # tempo commands is not possible for a 2-call row, so read the file.
    import h2g.convert as C
    rows = {}
    orig = C.instrument_row_calls

    def spy(tracks, patterns, group_tempos, start_group=None):
        rows["g"] = list(group_tempos)
        return orig(tracks, patterns, group_tempos, start_group=start_group)

    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text())
    opts = F._preset_opts(doc, name)
    C.instrument_row_calls = spy
    try:
        C.convert(str(CORPUS / name), log=lambda m: None, **opts)
    finally:
        C.instrument_row_calls = orig
    g = rows["g"]
    users = {}
    for ti, track in enumerate(song.tracks):
        s = ti // 3
        operand, first = False, True
        for b in track:
            if operand:
                operand = False
            elif b == GT_ORDER_RESTART:
                operand = True
            elif b < MAX_PATTERNS:
                pat = song.patterns[b]
                if first and not pat[1]:
                    users.setdefault(1, set()).add(s)
                first = False
                for r in range(1, len(pat), 4):
                    if pat[r]:
                        users.setdefault(pat[r], set()).add(s)

    def ticks(r):
        return _hard_restart_ticks(1, r, opts.get("wide_hard_restart", False),
                                   opts.get("max_hard_restart", False),
                                   opts.get("hard_restart_frames")) & 0x3F
    checked = 0
    for k, ss in users.items():
        if any(g[s] == FUNK_ROW_CALLS for s in ss):
            continue
        # Legato/tie clones carry flag bits of their own; the ticks are the
        # low six bits whatever else is set.
        want = ticks(min(g[s] for s in ss))
        got = song.instruments[k - 1][7] & 0x3F
        assert got == want, (name, k, got, want, sorted(ss))
        checked += 1
    assert checked
