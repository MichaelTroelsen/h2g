"""A record two tempo classes share is bounded for the SHORTER class alone.

`tracks.instrument_row_calls` charges an instrument the minimum row over the
subtunes it is played in, which is the safety bound (gplay.c:334 stops the song
when the gatetimer reaches the channel's tick). Human_Race's instrument `$0A00`
is played by the 3-call subtune 2 and by the 4-call subtunes 0 and 1, so it
carried the 3-call bound (2 ticks) in all three, and 318 notes of the default
subtune's voice 0 held the gate one frame past the original's (gate-on 5 frames
of 8 against 4; `heard.py` `instr` 0.726, `gate` 0.931, `adsrnf` 0.971). The
funk pass only treated the 2-call row as the short class.
`funk_gatetimers.split_funk_gatetimers` repeats the funk pass for every row between the
funk row and the file's longest.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from test_funk_gatetimers import END, gt, named, record, sng  # noqa: E402

from h2g.funk_gatetimers import (_split_class,  # noqa: E402
                                 split_funk_gatetimers)
from h2g.goatwriter.appending import _parse_song  # noqa: E402
from monty_fixture import pinned_preset_opts  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def ticks_for(row):
    """The `max_hard_restart` shape: the row less one, floored at 1."""
    return max(1, row - 1)


def three_classes():
    """subtune 0 (4 calls) plays records 2 and 3; subtune 1 (3 calls) plays 2
    and 4; subtune 2 (2 calls, funk) plays 5. Each record carries the gatetimer
    of the shortest row that plays it."""
    p0 = [[0x60, 2, 0, 0], [0x60, 3, 0, 0]]
    p1 = [[0x60, 2, 0, 0], [0x60, 4, 0, 0]]
    p2 = [[0x60, 5, 0, 0]]
    orders = [[0] + END, [3] + END, [3] + END,
              [1] + END, [3] + END, [3] + END,
              [2] + END, [3] + END, [3] + END]
    filler = [[0x60, 0, 0, 0]]
    recs = [record(1), record(2), record(2), record(2), record(1)]
    return sng(orders, [p0, p1, p2, filler], recs)


ROWS = [4, 3, 2]


def test_a_record_a_shorter_class_shares_is_split_and_the_longer_one_raised():
    out = split_funk_gatetimers(three_classes(), ROWS, ticks_for)
    song, cols = named(out)
    # 2: played in the 4-call and the 3-call subtunes -> the original keeps its
    # number and rises to the 4-call bound; the clone keeps the 3-call one.
    assert gt(out, 2) == 3
    clone = [r for r in cols[1] if r not in (0, 4)]
    assert len(clone) == 1 and clone[0] > 5 and gt(out, clone[0]) == 2
    # 3: only the 4-call subtune plays it -> raised.
    assert gt(out, 3) == 3
    # 4: only the 3-call subtune plays it -> stays.  5: the funk row's own.
    assert (gt(out, 4), gt(out, 5)) == (2, 1)
    assert len(song.instruments) == 6
    # The 4-call subtune still names the original.
    assert cols[0] == [2, 3]


def test_the_funk_pass_alone_leaves_the_3_vs_4_split_undone():
    """Short-circuiting the new passes gives the old behaviour: record 2 stays
    at the 3-call bound in the 4-call subtune."""
    out = _split_class(three_classes(), ROWS, ticks_for)
    assert gt(out, 2) == 2 and gt(out, 3) == 2


def test_a_record_a_shorter_subtune_plays_is_never_raised():
    """Record 5 is played by the funk subtune AND a 4-call one, and it keeps
    the funk gatetimer in the funk pass (split) -- the 3-call pass must not
    raise whatever the funk side still names to the 4-call bound."""
    p0 = [[0x60, 2, 0, 0]]
    p1 = [[0x60, 2, 0, 0]]
    p2 = [[0x60, 0, 0, 0]]                  # funk voice opens on instrument 1
    filler = [[0x60, 0, 0, 0]]
    orders = [[0] + END, [3] + END, [3] + END,
              [1] + END, [3] + END, [3] + END,
              [2] + END, [3] + END, [3] + END]
    blob = sng(orders, [p0, p1, p2, filler], [record(1), record(2)])
    out = split_funk_gatetimers(blob, ROWS, ticks_for)
    # Instrument 1 is opened on by the funk voice: it never leaves its bound.
    assert gt(out, 1) == 1


@pytest.mark.parametrize("rows", [[4, 4, 4], [3, 3], [4], [2, 2]])
def test_one_row_class_changes_nothing(rows):
    blob = three_classes()
    assert split_funk_gatetimers(blob, rows, ticks_for) == blob


def test_the_pass_declines_when_the_records_do_not_fit():
    from h2g.goatwriter import GT_TEMPO_INSTRUMENT
    p0 = [[0x60, 2, 0, 0]]
    p1 = [[0x60, 2, 0, 0]]
    filler = [[0x60, 3, 0, 0]]
    recs = [record(1), record(2)] + [record(2)] * (GT_TEMPO_INSTRUMENT - 3)
    orders = [[0] + END, [2] + END, [2] + END,
              [1] + END, [2] + END, [2] + END]
    blob = sng(orders, [p0, p1, filler], recs)
    lines = []
    out = split_funk_gatetimers(blob, [4, 3], ticks_for, lines.append)
    assert any("declined" in m for m in lines)
    assert len(_parse_song(out).instruments) == GT_TEMPO_INSTRUMENT - 1


def _shared_pattern_song(fillers):
    """subtunes 0 (4 calls) and 1 (3 calls) both play pattern 0, which names
    record 2: splitting the record COPIES that pattern, one slot more than
    `fillers` + 1 patterns already hold."""
    shared = [[0x60, 2, 0, 0]]
    filler = [[0x60, 3, 0, 0]]
    recs = [record(1), record(2), record(2)]
    orders = [[0] + END, [1] + END, [1] + END,
              [0] + END, [1] + END, [1] + END]
    return sng(orders, [shared] + [filler] * fillers, recs)


def test_a_longer_row_pass_that_copies_past_the_pattern_reserve_is_declined_whole():
    """Rasputin: 190 patterns became 195 for a gate gain of +.007, past the
    16 slots the passes after this one need; the pass is all or nothing."""
    from h2g.patterns import MAX_PATTERNS
    full = _shared_pattern_song(MAX_PATTERNS - 16 - 1)     # 192 patterns
    lines = []
    assert split_funk_gatetimers(full, [4, 3], ticks_for, lines.append) == full
    assert any("declined" in m for m in lines)
    roomy = _shared_pattern_song(20)
    out = split_funk_gatetimers(roomy, [4, 3], ticks_for)
    assert out != roomy and gt(out, 2) == 3


# ---- the corpus -----------------------------------------------------------

@needs_corpus
def test_human_race_default_subtune_voice_0_lead_gets_the_4_call_bound():
    """The record $0A00 (AD/SR) the 318 mismatched notes play is shared by the
    4-call subtunes 0 and 1 and the 3-call subtune 2. After the pass the
    subtune 0 / 1 record carries the 4-call bound (3) and subtune 2 a clone
    with the 3-call one (2)."""
    import fidelity as F
    from h2g.convert import convert
    from h2g.patterns import GT_ORDER_RESTART, MAX_PATTERNS
    doc = json.loads((ROOT / "presets.json").read_text())
    lines = []
    name = "Human_Race.sid"
    opts = pinned_preset_opts(doc, name)
    blob = convert(str(CORPUS / name), log=lines.append, **opts)
    assert any(m.startswith("Row gatetimers")
               and "3-call subtune and a longer one" in m for m in lines), lines
    song = _parse_song(blob)
    users = {}
    for ti, track in enumerate(song.tracks):
        operand = False
        for b in track:
            if operand:
                operand = False
            elif b == GT_ORDER_RESTART:
                operand = True
            elif b < MAX_PATTERNS:
                pat = song.patterns[b]
                for r in range(1, len(pat), 4):
                    if pat[r]:
                        users.setdefault(pat[r], set()).add(ti // 3)
    lead = [k for k, ss in users.items()
            if (song.instruments[k - 1][0], song.instruments[k - 1][1]) == (0x0A, 0x00)]
    by_subtunes = {k: sorted(users[k]) for k in lead}
    # The 4-call subtunes (0, 1) name a record at 3 ticks; the 3-call subtune
    # (2) never does.
    for k, ss in by_subtunes.items():
        ticks = song.instruments[k - 1][7] & 0x3F
        if 2 in ss:
            assert ticks <= 2, (k, ss, ticks)
        if 0 in ss:
            assert ticks == 3 and 2 not in ss, (k, ss, ticks)
    assert any(0 in ss for ss in by_subtunes.values())
