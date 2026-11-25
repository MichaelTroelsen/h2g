"""`ilv_filter_resume` holds the sweep where the interleaved player's does, and
starts a `$87` note at its own cutoff (h2g.goatwriter.filters / ilv_filter_resume).

Radio_ACE's one filter record sweeps `$0295` a frame down from `$AD18`, and the
player does not step on a frame a note starts (`$13CA JMP $17B7` skips the block
holding `$15F9-$1661`): five frames stepping, one holding, with the note
period 6 frames. 164 of its filtered notes follow a `$84` and so keep a running
sweep instead of restarting it (`ilv_filter_resume`); without the hold those
164 notes overshoot a step in six. 10 notes follow a `$87 nn mm`, which writes
the cutoff cell and sets `$1A63` (`$1335 LDA $1A63 / BNE $1346`), so they load
the record's program but start it at `nn`.

Measured at a3792d2 + the `$84` change of listen-sub99-lion-heart + this one,
`-t 180`, shipped presets plus `ilv_filter_resume` on Radio_ACE alone: `cfrm`
.177 -> .967, `cut` 1.133 -> 1.01 (with the `$84` clones alone: .418 and 1.285),
every other printed column identical (`aud`/`loud` within 2e-4).

SABOTAGE TARGETS: `filters.ILV_HOLD_ENABLED = False` removes the period and with
it the hold rows and the `$87` blocks (their anchors are the hold sweep's):
`test_the_period_is_what_moves_radio_ace`,
`test_radio_aces_table_holds_and_has_a_block_per_start_value` and
`test_the_start_clones_are_radio_aces_alone` fail.
`ilv_filter_resume.START_CLONES_ENABLED = False` removes the `$87` clones alone:
`test_a_started_note_gets_a_block_of_its_own`,
`test_values_the_table_has_no_room_for_take_the_nearest_blocks` and
`test_radio_aces_table_holds_and_has_a_block_per_start_value` fail.
"""
import json
import pathlib

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g import patterns as P  # noqa: E402
from h2g.convert import convert  # noqa: E402
from h2g.goatwriter import build as B  # noqa: E402
from h2g.goatwriter import filters as G  # noqa: E402
from h2g.goatwriter import ilv_filter_resume as R  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]

# Radio_ACE's program (`+0` start hi/lo, `+2` step, `+4` upper, `+5` lower,
# `+6` direction/passband, `+7` resonance): `$AD18`, `$0295`, `$65`, `$08`, down.
PROG = bytes.fromhex("ad18 0295 6508 0140")


# --- the decoder -------------------------------------------------------------

def _rows(*b):
    sk: list = []
    ev = P._build_raw_pattern_ilv(bytes([0, 0, 0x80, 0x05, *b, P.ILV_END]), 2,
                                  skip_rows=sk)
    return [ev[i:i + 4] for i in range(0, len(ev), 4)], sk


def test_a_dollar_87_note_is_flagged_with_its_start_cutoff():
    rows, sk = _rows(0xC1, 0x30, 0x87, 0x6A, 0x0D, 0xC1, 0x31, 0xC1, 0x32)
    notes = [i for i, r in enumerate(rows)
             if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    assert len(notes) == 3 and sk == [(notes[1], 0x6A)]


def test_the_dollar_87_flag_is_cleared_by_a_rest_and_yields_to_a_dollar_84():
    _rows_, sk = _rows(0x87, 0x6A, 0x0D, 0xC1, P.ILV_REST, 0xC1, 0x30)
    assert sk == []
    _rows_, sk = _rows(0x87, 0x6A, 0x0D, 0x84, 0xC1, 0x30)
    assert sk == [0]


def test_slices_rebase_a_start_row_with_its_value():
    got = P._rebase_skip([3, (5, 0x6A), (9, 0x7D), 12], 4, 6)
    assert got == frozenset({(1, 0x6A), (5, 0x7D)})
    assert P._rebase_skip([3, (5, 0x6A), 7], 0, 8) == frozenset(
        {3, (5, 0x6A), 7})


# --- the sweep ----------------------------------------------------------------

def test_the_trajectory_holds_on_every_period_frame():
    his = G._hi_trajectory(PROG, 0xAD, 30, 6)
    for f in range(6, 31, 6):
        assert his[f] == his[f - 1], f
    assert all(his[f] < his[f - 1] for f in (1, 2, 3, 4, 5, 7))


def test_the_trajectory_turns_at_its_limit():
    his = G._hi_trajectory(PROG, 0x10, 40, 6)
    assert min(his) == 0x08 and his[-1] > 0x08


def test_the_hold_sweep_steps_five_calls_and_holds_one():
    rows, anchors = G._ilv_hold_sweep(PROG, 6, 1, 0xAD)
    assert rows[-1] == (G.FILT_STOP, 0x00)
    body = rows[:-1]
    assert [r[0] for r in body[0::2]] == [5] * len(body[0::2])
    assert set(body[1::2]) == {(1, 0)}
    # one anchor per period, at the start of its stepping row
    assert [a[0] for a in anchors] == list(range(0, len(body), 2))
    assert anchors[0][1] == 0xAD
    assert all(b[1] < a[1] for a, b in zip(anchors, anchors[1:]))


def test_the_hold_sweep_tracks_the_players_high_byte():
    rows, anchors = G._ilv_hold_sweep(PROG, 6, 1, 0xAD)
    his = G._hi_trajectory(PROG, 0xAD, 6 * len(anchors), 6)
    for u, (_off, hi) in enumerate(anchors):
        assert abs(hi - his[6 * u]) <= 3, (u, hi, his[6 * u])
    # it ends where the player's first leg does: at the lower limit
    last = anchors[-1][1] + 5 * (rows[-3][1] - 256)
    assert abs(last - 0x08) <= 8


def test_a_multiplier_spends_calls_not_frames():
    rows, _ = G._ilv_hold_sweep(PROG, 12, 2, 0xAD)     # 6 frames at -S2
    assert rows[0][0] == 10 and rows[1] == (2, 0)


def test_a_sweep_the_shape_cannot_say_is_none():
    assert G._ilv_hold_sweep(PROG, 6, 4, 0xAD) is None         # 6 % 4
    assert G._ilv_hold_sweep(PROG[:2] + bytes(2) + PROG[4:], 6, 1, 0xAD) is None
    assert G._ilv_hold_sweep(PROG, 6, 1, 0x08) is None         # at its limit
    assert G._ilv_hold_sweep(PROG, 1, 1, 0xAD) is None         # no stepping
    slow = PROG[:2] + bytes([0x00, 0x10]) + PROG[4:]
    assert G._ilv_hold_sweep(slow, 6, 1, 0xAD) is None         # > ILV_HOLD_ROWS


# --- the clones ----------------------------------------------------------------

def _instruments(filter_ptrs):
    out = bytearray([len(filter_ptrs)])
    for g, f in enumerate(filter_ptrs, 1):
        rec = bytearray(25)
        rec[0], rec[1], rec[2], rec[3], rec[4] = 9, 7, g + 10, g + 20, f
        rec[5] = 3
        out += rec
    return out


def _pattern(*rows):
    out = []
    for note, ins, cmd, dat in rows:
        out += [note, ins, cmd, dat]
    return out + [0xFF, 0, 0, 0]


NOTE = 0x70


def _table():
    return [(0x90, 0x44), (0x00, 0xAD), (5, 0xFD), (1, 0), (5, 0xFD), (1, 0),
            (G.FILT_STOP, 0)]


LADDER = {1: [(0, 0xAD), (2, 0xA0)]}


def test_a_started_note_gets_a_block_of_its_own():
    out = _instruments([1])
    entries = _table()
    pats = [_pattern((NOTE, 1, 0, 0), (NOTE, 1, 0, 0), (NOTE, 1, 0, 0))]
    known = {0: frozenset({(1, 0xA2), 2})}
    got, written, clones = R.resume_plan(pats, known, 1, (), out, 0, 1,
                                         filter_entries=entries,
                                         anchors=LADDER)
    assert clones == [(1, 2), (1, 3)] and written == 3
    # row 2 is a `$84` note: a clone with no pointer; row 1 starts at 0xA2
    assert [got[0][4 * r + 1] for r in range(3)] == [1, 3, 2]
    assert out[1 + 1 * 25 + 4] == 0 and out[1 + 2 * 25 + 4] == 8
    # the new block: the record's params row, set cutoff, a jump into the
    # sweep at the period whose cutoff is nearest (0xA0, row offset 2)
    assert entries[7:] == [(0x90, 0x44), (0x00, 0xA2),
                           (G.FILT_STOP, 1 + 2 + 2)]


def test_a_started_note_on_no_anchored_record_keeps_restarting():
    out = _instruments([1])
    entries = _table()
    pats = [_pattern((NOTE, 1, 0, 0), (NOTE, 1, 0, 0))]
    got, written, clones = R.resume_plan(pats, {0: frozenset({(1, 0xA2)})}, 1,
                                         (), out, 0, 1,
                                         filter_entries=entries, anchors={})
    assert clones == [] and written == 1 and got[0][5] == 1
    assert len(entries) == 7


def test_values_the_table_has_no_room_for_take_the_nearest_blocks():
    out = _instruments([1])
    entries = _table() + [(0x00, 0)] * (G.GT_MAX_FILT - 7 - 6)
    pats = [_pattern(*[(NOTE, 1, 0, 0)] * 4)]
    known = {0: frozenset({(0, 0x40), (1, 0x40), (2, 0xA0), (3, 0xA1)})}
    got, written, clones = R.resume_plan(pats, known, 1, (), out, 0, 1,
                                         filter_entries=entries,
                                         anchors=LADDER)
    # room for two blocks: 0x40 (two notes) and the lower of the tied 0xA0/0xA1
    assert len(clones) == 2 and len(entries) == G.GT_MAX_FILT
    names = [got[0][4 * r + 1] for r in range(4)]
    assert names[0] == names[1] and names[2] == names[3] != names[0]


def test_the_start_switch_short_circuits_the_clones(monkeypatch):
    out = _instruments([1])
    entries = _table()
    pats = [_pattern((NOTE, 1, 0, 0), (NOTE, 1, 0, 0))]
    monkeypatch.setattr(R, "START_CLONES_ENABLED", False)
    _p, written, clones = R.resume_plan(pats, {0: frozenset({(1, 0xA2)})}, 1,
                                        (), out, 0, 1,
                                        filter_entries=entries,
                                        anchors=LADDER)
    assert clones == [] and written == 1 and len(entries) == 7


# --- the corpus -------------------------------------------------------------------

def _song(stem, capture=None, **extra):
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), **extra)
    lines: list = []
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lines.append, **opts)
    return blob, lines


def _filter_table(stem, **extra):
    seen: list = []
    real = B._write_filtertable
    B._write_filtertable = lambda out, entries: (seen.append(list(entries)),
                                                 real(out, entries))[1]
    try:
        _song(stem, **extra)
    finally:
        B._write_filtertable = real
    return seen[-1]


@needs_corpus
def test_the_period_is_what_moves_radio_ace(monkeypatch):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / "Radio_ACE.sid"))
    det = detect(sid, lambda m: None)
    assert G.ilv_hold_period(sid, det, 1) == 6
    assert G.ilv_hold_period(sid, det, 2) == 12
    on, _ = _song("Radio_ACE", ilv_filter_resume=True)
    monkeypatch.setattr(G, "ILV_HOLD_ENABLED", False)
    assert G.ilv_hold_period(sid, det, 1) is None
    off, _ = _song("Radio_ACE", ilv_filter_resume=True)
    assert on != off


@needs_corpus
def test_radio_aces_table_holds_and_has_a_block_per_start_value():
    table = _filter_table("Radio_ACE", ilv_filter_resume=True)
    assert len(table) <= G.GT_MAX_FILT
    # the record's block: params, set cutoff, then (5, step) / (1, 0) pairs
    assert table[0][0] == 0x90 and table[1] == (G.FILT_SET_CUTOFF, 0xAD)
    pairs = table[2:2 + 26]
    assert [p[0] for p in pairs] == [5, 1] * 13
    assert table[28] == (G.FILT_STOP, 0)
    # one three-row block per `$87` value, each jumping into that sweep
    blocks = [(table[i + 1][1], table[i + 2][1]) for i in range(29, len(table), 3)
              if table[i][0] == 0x90]
    assert sorted(v for v, _t in blocks) == [0x6A, 0x7D, 0x84, 0x9A, 0xA4,
                                            0xC6, 0xD6]
    assert all(3 <= t <= 28 and t % 2 == 1 for _v, t in blocks)


@needs_corpus
def test_the_hold_does_not_reach_a_ping_pong_sweep(monkeypatch):
    """Lion_Heart's sweep is the bounded ping-pong, which the hold does not
    model: its bytes are the `$84` change's whatever the period says."""
    on, _ = _song("Lion_Heart", ilv_filter_resume=True)
    monkeypatch.setattr(G, "ILV_HOLD_ENABLED", False)
    off, _ = _song("Lion_Heart", ilv_filter_resume=True)
    assert on == off


@needs_corpus
def test_the_start_clones_are_radio_aces_alone():
    moved = []
    for stem in ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                 "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines"):
        hold_on, _ = _song(stem, ilv_filter_resume=True)
        R.START_CLONES_ENABLED = False
        try:
            hold_off, _ = _song(stem, ilv_filter_resume=True)
        finally:
            R.START_CLONES_ENABLED = True
        if hold_on != hold_off:
            moved.append(stem)
    assert moved == ["Radio_ACE"], moved
