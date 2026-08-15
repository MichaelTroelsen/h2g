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
