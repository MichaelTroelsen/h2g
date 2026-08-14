"""`$FE nn`: the one dialect whose orderlist changes tempo mid-song.

§ 7.vvvv decoded the command and did not emit it, on the grounds that
Goattracker would need a tempo command in the pattern. It does, and that is
what `patterns._apply_orderlist_tempos` writes -- into a *copy* of the
pattern, because the same pattern is played at other tempos elsewhere.

Two things these tests pin that the report cannot see:

* the operand is the **outer** counter's reload, so a row lasts
  `frames * (R + 1) / R` and not `R + 1` frames. Read the other way round,
  Rasputin's `$FE 78` is 121 frames a row against its neighbours' 3.
* the substitution happens before `pack_repeats`, so a tempo change inside a
  run of one repeated pattern survives packing.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.goatwriter import (CMD_SETTEMPO, derived_group_tempos,  # noqa: E402
                            orderlist_tempo_values)
from h2g.patterns import (MAX_PATTERNS, _apply_orderlist_tempos,  # noqa: E402
                          pack_repeats, reindex_tracks)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import _build_track, convert_tracks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _rasputin():
    sid = load_sid(str(CORPUS / "Rasputin.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


# --- reading the command ---------------------------------------------------

def test_the_operand_is_recorded_at_the_position_it_takes_effect():
    # $FE occupies no orderlist step, so its operand belongs to the entry
    # that follows: here, the third.
    data = bytes([0x01, 0x02, 0xFE, 0x07, 0x03, 0xFF])
    tempos = {}
    track = _build_track(data, 0, 0, None, fe_command=True, tempos=tempos)
    assert track[:3] == [0x01, 0x02, 0x03]
    assert tempos == {2: 0x07}


def test_nothing_is_recorded_where_the_player_has_no_such_command():
    data = bytes([0x01, 0xFE, 0x07, 0x03, 0xFF])
    tempos = {}
    _build_track(data, 0, 0, None, fe_command=False, tempos=tempos)
    assert tempos == {}


# --- turning it into a tempo ----------------------------------------------

@needs_corpus
def test_rasputin_is_the_only_file_that_carries_it():
    found = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.track_fe_command:
            continue
        raw: list = []
        convert_tracks(sid, det, lambda *a, **k: None, None, raw)
        if any(raw):
            found.append(path.name)
    assert found == ["Rasputin.sid"]


@needs_corpus
def test_the_value_is_the_row_length_times_the_outer_ratio():
    sid, det = _rasputin()
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    values = orderlist_tempo_values(sid, det, raw, "auto", True)
    # Subtune 0's inner gate reads 2 frames a row, the file packs at -S2, and
    # the operands are the outer counter's reload: 2 * (R+1)/R * 2 calls.
    assert raw[2] == {0: 2, 14: 3, 24: 5, 62: 10, 78: 60, 132: 120,
                      206: 6, 223: 2}
    assert values[2] == {0: 6, 14: 5, 24: 5, 62: 4, 78: 4, 132: 4,
                         206: 5, 223: 6}
    # Read as a row length instead, $FE 78 would be 121 frames -- 60x its
    # neighbours, on patterns the same list plays at speed.
    assert values[2][132] < values[2][0]


@needs_corpus
def test_the_multiplier_agrees_with_the_one_the_subtunes_are_packed_at():
    """These values are derived before reindexing and that one after."""
    sid, det = _rasputin()
    raw: list = []
    tracks = convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    _, mult, _ = derived_group_tempos(sid, det, len(tracks) // 3, True)
    values = orderlist_tempo_values(sid, det, raw, "auto", True)
    # 2 frames * 3/2 * mult for the opening command. `mult` comes from the
    # function that runs after reindexing; if the two ever disagreed, the
    # tempo written into a pattern would be on a different timebase from the
    # tempo written beside it.
    assert mult > 1
    assert values[2][0] == 2 * 3 // 2 * mult


@needs_corpus
def test_an_explicit_tempo_leaves_the_multiplier_at_one():
    """`--tempo N` packs at 1x, so a mid-song change must not be scaled."""
    sid, det = _rasputin()
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    values = orderlist_tempo_values(sid, det, raw, 6, True)
    assert values[2][0] == 3          # 2 frames * 3/2, unscaled


# --- writing it into a pattern --------------------------------------------

def test_the_tempo_goes_into_a_copy_and_not_the_shared_pattern():
    patterns = [[0x60, 1, 0, 0], [0x61, 1, 0, 0]]
    track = [0, 1, 0]
    moved = {0: 0, 1: 1, 2: 2}
    copies: dict = {}
    n = _apply_orderlist_tempos(track, moved, {0: 6, 2: 9}, patterns, copies)
    assert n == 2
    assert patterns[0] == [0x60, 1, 0, 0]          # untouched
    assert track[1] == 1                            # not asked for
    assert track[0] != 0 and track[2] != 0
    assert patterns[track[0]][2:4] == [CMD_SETTEMPO, 6]
    assert patterns[track[2]][2:4] == [CMD_SETTEMPO, 9]


def test_one_copy_serves_every_step_asking_for_the_same_tempo():
    patterns = [[0x60, 1, 0, 0]]
    track = [0, 0, 0]
    n = _apply_orderlist_tempos(track, {0: 0, 1: 1, 2: 2},
                                {0: 6, 2: 6}, patterns, {})
    assert n == 2
    assert len(patterns) == 2
    assert track == [1, 0, 1]


def test_a_row_whose_command_column_is_taken_is_left_alone():
    """A portamento this converter emitted keeps its column."""
    patterns = [[0x60, 1, 0x04, 0x10]]
    track = [0]
    logged: list = []
    n = _apply_orderlist_tempos(track, {0: 0}, {0: 6}, patterns, {},
                                logged.append)
    assert n == 0 and len(patterns) == 1 and track == [0]
    assert logged and "COMMAND COLUMN IS TAKEN" in logged[0]


def test_a_pattern_that_already_says_it_is_not_copied():
    patterns = [[0x60, 1, CMD_SETTEMPO, 6]]
    track = [0]
    assert _apply_orderlist_tempos(track, {0: 0}, {0: 6}, patterns, {}) == 1
    assert len(patterns) == 1 and track == [0]


def test_the_copy_survives_packing():
    """The substitution runs before pack_repeats, which is the point of it.

    A tempo change in the middle of a run of one pattern is a boundary; a
    pass after packing would have to break a repeat to say anything.
    """
    tracks = [[0, 0, 0, 0, 0xFF, 0]]
    patterns = [[0x60, 1, 0, 0]]
    out = reindex_tracks(tracks, [[0]], pack=True, patterns=patterns,
                         tempos=[{2: 6}])
    # Without the tempo the whole run packs to one repeat; with it the run
    # is split around the copy, which is a different pattern number.
    assert len(patterns) == 2
    assert patterns[1][2:4] == [CMD_SETTEMPO, 6]
    assert 1 in out[0]
    plain = reindex_tracks([[0, 0, 0, 0, 0xFF, 0]], [[0]], pack=True,
                           patterns=[[0x60, 1, 0, 0]])
    assert 1 not in plain[0]                 # nothing to split the run
    assert plain[0][:len(pack_repeats([0, 0, 0, 0]))] == pack_repeats([0, 0, 0, 0])


def test_the_pass_stops_at_goattrackers_pattern_ceiling():
    patterns = [[0x60, 1, 0, 0] for _ in range(MAX_PATTERNS)]
    track = [0]
    logged: list = []
    assert _apply_orderlist_tempos(track, {0: 0}, {0: 6}, patterns, {},
                                   logged.append) == 0
    assert len(patterns) == MAX_PATTERNS
    assert logged and "NO ROOM" in logged[0]


# --- end to end ------------------------------------------------------------

@needs_corpus
def test_only_rasputin_s_bytes_move():
    presets = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    always = {k: v for k, v in presets["always"].items()
              if k in ("effects", "slides", "status_bit6", "skip_gate")}
    for name in ("Commando.sid", "Knucklebusters.sid", "Tarzan.sid"):
        path = CORPUS / name
        if not path.exists():
            continue
        sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        raw: list = []
        convert_tracks(sid, det, lambda *a, **k: None, None, raw)
        assert not any(raw), name       # they read $FD, not $FE nn


@needs_corpus
def test_the_opening_tempo_is_the_same_number_from_both_writers():
    """Both land on row 0 of the song; disagreeing would be a channel race."""
    import songview
    blob = convert(str(CORPUS / "Rasputin.sid"), log=lambda *a, **k: None,
                   effects=True, slides=True, status_bit6=True,
                   skip_gate=True, compact_instruments=True,
                   legal_restart=True, fmt="gts5", tempo="auto")
    song = songview.parse_sng(blob)
    opening = []
    for voice in range(3):
        track = song.tracks[voice]
        first = next((b for b in track if b < MAX_PATTERNS), None)
        if first is None or first >= len(song.patterns):
            continue
        rows = song.patterns[first]
        if len(rows) >= 4 and rows[2] == CMD_SETTEMPO:
            opening.append(rows[3])
    assert opening and len(set(opening)) == 1, opening
