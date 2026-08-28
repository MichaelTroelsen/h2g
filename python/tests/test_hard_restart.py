"""How long the gate is closed before a note, and why it is bounded twice.

Goattracker fetches the next note `gatetimer & $3f` calls early and holds the
gate off for them (gplay.c:905). That is this writer's *only* release between
two adjacent notes, and it was 2 **calls** for the project's whole life --
2 frames at `-S1` and two thirds of one at `-S3`, against the players' own
releases, which the gate census measures at 3.3 frames.

Measured in frames instead, and bounded twice:

* **gplay.c:334 stops the song outright** when the value exceeds the
  channel's tick. Swept past it, Commando drops from 716 attacks to 3 and
  Sanxion from 956 to 1 -- total, not graceful.
* **Half the row**, which is a claim about music rather than the player.
  Bounded only by the player's own limit, Saboteur II gets 6 calls of an
  8-call row and melody falls 98% -> 62%; every other file that moved gained.

Corpus at v0.5.275: melody +33pp on 5 files (Off the Cuff 51 -> 95%, Kings of
the Beach intro 67 -> 100%), `gate` +12pp on 15, `retrig` toward 1.0 on all
five movers, and **no file worse by half a point on any dimension**.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import (HARD_RESTART_FRAMES,  # noqa: E402
                            _hard_restart_ticks)


def test_it_is_measured_in_frames_not_calls():
    """A frame is `multiplier` calls, the conversion every rate here makes."""
    assert _hard_restart_ticks(1, 99) == HARD_RESTART_FRAMES
    assert _hard_restart_ticks(3, 99) == HARD_RESTART_FRAMES * 3


def test_it_never_reaches_the_row_length():
    """gplay.c:334 stops the song, so this is a correctness bound."""
    for row in range(2, 40):
        for mult in (1, 2, 3, 5):
            assert _hard_restart_ticks(mult, row) < row


def test_it_takes_at_most_half_the_row():
    """A note that spends more of its slot released is not the note."""
    # Saboteur II: -S3, an 8-call row. `want` is 6 and the answer is 4.
    assert _hard_restart_ticks(3, 8) == 4
    # Off the Cuff: -S5, 12 calls. `want` is 10.
    assert _hard_restart_ticks(5, 12) == 6


def test_wide_takes_two_thirds_of_the_row():
    """`--wide-hard-restart` raises the ceiling from `row // 2` to
    `2 * row // 3` -- worth 1.6pp of mean gate over the corpus in v0.5.276's
    sweep, and the value at which Saboteur II's melody falls 98% -> 67%, which
    is why it is searched per song rather than made the constant."""
    # Saboteur II: -S3, an 8-call row. Half is 4; two thirds is 5.
    assert _hard_restart_ticks(3, 8) == 4
    assert _hard_restart_ticks(3, 8, wide=True) == 5
    # Off the Cuff: -S5, 12 calls. `want` is 10, so the bound decides both.
    assert _hard_restart_ticks(5, 12) == 6
    assert _hard_restart_ticks(5, 12, wide=True) == 8


def test_wide_still_never_reaches_the_row():
    """gplay.c:334 stops the song outright above the channel's tick, so the
    wider bound must stay under the row for every rate the corpus packs at."""
    for row in range(2, 40):
        for mult in (1, 2, 3, 5):
            assert _hard_restart_ticks(mult, row, wide=True) < row
            assert _hard_restart_ticks(mult, row, wide=True) >= 1


def test_wide_is_never_shorter_than_the_default():
    """A wider ceiling can only raise the value it bounds, never lower it --
    otherwise the option would be a different setting rather than a wider one,
    and `fidelity_better` would be choosing between two unrelated things."""
    for row in range(0, 40):
        for mult in (1, 2, 3, 5):
            assert (_hard_restart_ticks(mult, row, wide=True)
                    >= _hard_restart_ticks(mult, row))


def test_full_takes_the_player_s_own_limit():
    """`--max-hard-restart` is `row - 1`, the value above which gplay.c:334
    stops the song. 3.3pp of mean gate in v0.5.276's sweep against `wide`'s
    1.6, and 98% -> 62% on Saboteur II against 67%."""
    # Saboteur II: -S3, an 8-call row. `want` is 6, so it caps below the bound.
    assert _hard_restart_ticks(3, 8, full=True) == 6
    # Off the Cuff: -S5, 12 calls. Half is 6, two thirds 8, the limit 11,
    # and `want` is 10 -- so this is the one file shape where `want` decides.
    assert _hard_restart_ticks(5, 12, full=True) == 10
    # A long row at -S2: `want` is 4 and every bound is above it.
    assert _hard_restart_ticks(2, 30, full=True) == 4


def test_full_outranks_wide_where_both_are_given():
    """The search tries every combination of its toggles, so the two arrive
    together on 1 candidate in 4. The wider must win rather than whichever is
    tested last -- otherwise the pair means something different from either
    flag alone and `fidelity_better` is choosing between three things while
    seeing two."""
    for row in range(2, 40):
        for mult in (1, 2, 3, 5):
            both = _hard_restart_ticks(mult, row, wide=True, full=True)
            assert both == _hard_restart_ticks(mult, row, full=True)


def test_full_still_never_reaches_the_row():
    """The bound is the player's limit, so this is the test that matters most:
    one call further and the song stops dead (Commando 716 attacks -> 3)."""
    for row in range(2, 40):
        for mult in (1, 2, 3, 5):
            assert _hard_restart_ticks(mult, row, full=True) < row
            assert _hard_restart_ticks(mult, row, full=True) >= 1


def test_the_three_bounds_are_ordered():
    """half <= wide <= full, for every rate and row the corpus packs at. If
    that ever fails the options are not three settings of one knob."""
    for row in range(0, 40):
        for mult in (1, 2, 3, 5):
            half = _hard_restart_ticks(mult, row)
            wide = _hard_restart_ticks(mult, row, wide=True)
            full = _hard_restart_ticks(mult, row, full=True)
            assert half <= wide <= full


def test_a_single_speed_file_keeps_the_historical_two():
    """Commando's row is 3 calls; half of it is 1, and 1 would move every
    `-S1` conversion in the corpus to fix a multispeed defect."""
    assert _hard_restart_ticks(1, 3) == 2
    assert _hard_restart_ticks(1, 4) == 2
    assert _hard_restart_ticks(1, 12) == 2


def test_the_floor_still_yields_to_the_row():
    """A two-call row cannot carry a two-call gate-off."""
    assert _hard_restart_ticks(1, 2) == 1
    assert _hard_restart_ticks(4, 2) == 1


def test_no_tempo_pass_keeps_the_old_constant():
    """A caller that built instruments without resolving a tempo."""
    assert _hard_restart_ticks(1, 0) == 2
    assert _hard_restart_ticks(5, 0) == 2


def test_it_is_never_zero():
    """Zero would be no gate-off at all, and no retrigger with it."""
    for row in range(0, 40):
        for mult in (1, 2, 3, 5, 8):
            assert _hard_restart_ticks(mult, row) >= 1


def test_the_two_bounds_decide_almost_everywhere():
    """Why the frame count barely matters, at the level of the rule.

    On the bytes, raising `HARD_RESTART_FRAMES` from 2 to 3 changes 3 of the
    83 corpus files and moves no dimension of the report; 4 and 6 change the
    same three. Lowering it to 1 changes 15 and costs 1.2pp of mean `gate`.
    The reason is here: over the (multiplier, row) pairs this corpus spans,
    one of the two bounds is binding almost every time, and `want` reaches
    the answer only where the row is long relative to the multiplier.

    A corpus version of this test measured the wrong row twice -- the
    header's subtune count instead of the emitted one, then a log line whose
    "in N pattern(s)" digits joined the tempo values -- and reported first 0
    responding files and then 2, against the true 3. The rule is testable
    without either.
    """
    import h2g.goatwriter as G

    binding = {"floor": 0, "row": 0, "want": 0}
    for mult in (1, 2, 3, 5):
        for row in range(2, 14):
            want = G.HARD_RESTART_FRAMES * mult
            got = _hard_restart_ticks(mult, row)
            if got == 2 and want != 2 and row // 2 != 2:
                binding["floor"] += 1
            elif got == want:
                binding["want"] += 1
            else:
                binding["row"] += 1
    assert binding["row"] > binding["want"], binding


def test_it_fits_the_six_bits_it_is_written_into():
    """Bit 7 of gatetimer is the no-hard-restart flag (gsong.c:381)."""
    for row in (2, 3, 8, 40, 127):
        for mult in (1, 3, 8):
            assert _hard_restart_ticks(mult, row) <= 0x3F


# --- wide/full are inert at multiplier 1 -------------------------------------
#
# `_hard_restart_ticks` computes `ticks = min(want, bound)`, and `want` is
# `HARD_RESTART_FRAMES * multiplier`. `wide` and `full` raise the BOUND only, so
# at multiplier 1 (want = 2) neither can lift the result above 2 however long the
# row is. The docstring used to say `full` "goes to row_calls - 1", which is true
# only once the multiplier has already pushed `want` past the bound.
#
# This is not a defect to fix here -- raising `want` needs a convert() option --
# but it is why 17 corpus songs carry `max_hard_restart` and none of them is
# multiplier 1: on a single-speed file the toggle changes no byte, so the preset
# search can never select it. Pinned so the inertness is a stated property rather
# than a surprise the next reader re-derives.

def test_full_and_wide_are_inert_at_multiplier_one():
    from h2g import goatwriter as G
    for row_calls in (4, 6, 8, 12, 16):
        plain = G._hard_restart_ticks(1, row_calls)
        assert G._hard_restart_ticks(1, row_calls, wide=True) == plain
        assert G._hard_restart_ticks(1, row_calls, full=True) == plain
        assert plain == 2, (row_calls, plain)


def test_full_does_reach_its_bound_once_want_exceeds_it():
    # The other half of the same statement: the bound is real, it just needs a
    # `want` big enough to reach it, which only a multiplier supplies today.
    from h2g import goatwriter as G
    assert G._hard_restart_ticks(4, 8, full=True) == 7      # row_calls - 1
    assert G._hard_restart_ticks(4, 8) == 4                 # row_calls // 2
    assert G._hard_restart_ticks(2, 4, full=True) == 3      # row_calls - 1


def test_the_constant_cannot_move_a_four_call_row():
    # 5_Title_Tunes' shape: multiplier 1, row_calls 4. `bound = 4 // 2` = 2 caps
    # the result before `want` is consulted, which is why converting that file at
    # HARD_RESTART_FRAMES 2, 3, 4 and 5 produces a byte-identical .sng.
    from h2g import goatwriter as G
    old = G.HARD_RESTART_FRAMES
    try:
        for n in (2, 3, 4, 5, 8):
            G.HARD_RESTART_FRAMES = n
            assert G._hard_restart_ticks(1, 4) == 2, n
    finally:
        G.HARD_RESTART_FRAMES = old

def test_the_gate_bound_is_per_instrument_over_the_subtunes_it_plays_in():
    """The minimum, never the median -- too large stops the song outright."""
    from h2g.tracks import instrument_row_calls

    # Two subtunes, one voice each shown: subtune 0 plays pattern 0 at 3
    # calls a row, subtune 1 plays pattern 1 at 5.
    tracks = [[0], [], [], [1], [], []]
    patterns = [
        [0, 7, 0, 0],          # pattern 0 sets instrument 7
        [0, 9, 0, 0],          # pattern 1 sets instrument 9
    ]
    got = instrument_row_calls(tracks, patterns, [3, 5])
    assert got == {7: 3, 9: 5}, got


def test_an_instrument_shared_between_two_tempos_takes_the_shorter_row():
    """gplay.c:334 stops the song when the gatetimer reaches the tick, so a
    pattern played in the fast subtune is played at the fast tempo."""
    from h2g.tracks import instrument_row_calls

    tracks = [[0], [], [], [0], [], []]   # both subtunes play pattern 0
    patterns = [[0, 7, 0, 0]]
    assert instrument_row_calls(tracks, patterns, [3, 5]) == {7: 3}


def test_it_refuses_rather_than_guessing_when_the_numbering_does_not_line_up():
    """A wrong attribution here is a stopped song, so {} -- and the caller
    then keeps the file-wide bound, which is the old behaviour."""
    from h2g.tracks import instrument_row_calls

    tracks = [[0], [], [], [0], [], []]        # two subtunes
    patterns = [[0, 7, 0, 0]]
    assert instrument_row_calls(tracks, patterns, [3]) == {}   # one tempo only
    assert instrument_row_calls(tracks, patterns, []) == {}


def test_a_single_tempo_file_is_unchanged_by_the_per_instrument_bound():
    """Commando has one tempo, so every instrument's bound equals the
    file-wide one and the byte-exact fixture cannot move."""
    from h2g.convert import convert

    root = pathlib.Path(__file__).resolve().parents[2]
    ref = (root / "Commando.sng").read_bytes()
    assert convert(str(root / "Commando.sid")) == ref
