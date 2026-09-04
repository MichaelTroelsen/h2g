"""Reading a player's own sequencer period out of its cycle count.

`--pace` can only say our row disagrees with the original's; it needs a
conversion, and it needs the two sides to share enough notes to align. This
reads the original alone: siddump -z prints the cycles the play routine burned
each frame (siddump.c:470-478), a Hubbard player does markedly more work on
the frame its sequencer steps, and the gaps between those frames are the row
period.

Two things that made the first version of this wrong are pinned here, because
both produced confident wrong numbers rather than failures:

* a **global** threshold splits the tune into sections rather than frames --
  Deep_Strike runs near 700 cycles a frame early and near 1300 later, and Otsu
  over the whole series called 328 consecutive frames busy;
* the **mean** gap is not the period when a tick is occasionally missed --
  Tarzan's gaps are 3 (x89) and 6 (x37), mean 3.88, period 3.0.
"""
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fidelity import (TICK_MIN_REGULAR, local_ratio, otsu,          # noqa: E402
                      tick_period)
from h2g import detect as D                                          # noqa: E402
from h2g import goatwriter as G                                      # noqa: E402


def series(pattern, n, base=700, spike=950):
    """`n` frames where every frame in `pattern` (mod its length) is busy."""
    return [spike if i % len(pattern) in pattern else base for i in range(n)]


def ticks_at(gaps, n, base=700, spike=950, drift=0):
    """A series whose busy frames sit at the given cumulative gaps."""
    out, at, k = [], 0, 0
    busy = set()
    while at < n:
        busy.add(at)
        at += gaps[k % len(gaps)]
        k += 1
    return [(spike if i in busy else base) + (i * drift) for i in range(n)]


def test_otsu_splits_a_clean_two_level_series():
    assert 700 <= otsu([700] * 20 + [950] * 10) < 950


def test_otsu_on_one_level_returns_it():
    assert otsu([700] * 20) == 700


def test_local_ratio_removes_a_drifting_baseline():
    """The Deep_Strike failure, in the form it actually took."""
    drifting = [700 + 2 * i for i in range(200)]
    r = local_ratio(drifting)
    assert max(r[20:-20]) - min(r[20:-20]) < 0.02


def test_a_flat_period_is_read_exactly():
    got = tick_period(ticks_at([3], 300), skip=0)
    assert got["modal"] == 3
    assert got["period"] == pytest.approx(3.0, abs=0.05)
    assert got["regular"] == pytest.approx(1.0)


def test_a_missed_tick_does_not_lengthen_the_period():
    """Tarzan's shape: gaps of 3 and 6, period 3.

    The mean gap here is 4.0 and the period is 3.0. Reporting the mean was
    the first version's error and it read 3.88 against a true 3.00.
    """
    got = tick_period(ticks_at([3, 3, 6], 400), skip=0)
    assert got["modal"] == 3
    assert got["period"] == pytest.approx(3.0, abs=0.08)


def test_an_alternating_player_is_refused_rather_than_averaged():
    """Deep_Strike's shape: 3, 3, 2, a genuine 2.67 frames a row.

    This is the cost of the regularity guard, and it falls on exactly the
    files §7b of whats-next.md is about -- the ones whose row is not an
    integer number of frames. The guard cannot tell an alternating sequencer
    from spikes that are not the sequencer at all, so it refuses both. It
    refuses *with a reason*, which is the difference between a gap in the
    tool and a wrong number; `--pace` still measures these, at the cost of
    needing a conversion to compare against.
    """
    got = tick_period(ticks_at([3, 3, 2], 400), skip=0)
    assert "period" not in got
    assert got["regular"] < TICK_MIN_REGULAR


def test_a_drifting_baseline_does_not_defeat_it():
    got = tick_period(ticks_at([3], 400, drift=3), skip=0)
    assert got["period"] == pytest.approx(3.0, abs=0.08)


def test_a_player_doing_equal_work_every_frame_is_refused():
    got = tick_period([700] * 300, skip=0)
    assert "period" not in got and got["why"]


def test_a_barely_raised_frame_is_refused():
    got = tick_period(ticks_at([3], 300, base=1000, spike=1010), skip=0)
    assert "period" not in got


def test_too_few_frames_is_refused():
    assert "period" not in tick_period([700, 950] * 8, skip=0)


def test_too_few_busy_frames_is_refused():
    body = [700] * 300
    for i in (10, 40, 70, 100):
        body[i] = 950
    assert "period" not in tick_period(body, skip=0)


def test_a_period_of_one_frame_is_refused():
    """Adjacent busy frames are not a tick rate; this read as 1.00 on 8 files.

    Kept below the every-frame-is-busy guard on purpose, so it is the modal
    check that has to catch it: busy frames in pairs give a quiet class and a
    modal gap of 1.
    """
    body = [950 if i % 5 in (0, 1) else 700 for i in range(300)]
    got = tick_period(body, skip=0)
    assert "period" not in got
    assert "no period visible" in got["why"] and got["modal"] == 1


def test_regularity_counts_exact_multiples_only():
    """A near-multiple tolerance would accept almost everything.

    Gaps of 3 and 6 against a modal of 3 are one period with a missed tick,
    and count. Gaps of 4 and 5 are not, and under the +-1 frame tolerance this
    first shipped with they counted too -- which is why the field read 1.00 on
    files whose busy frames had no single period, and why the corpus check
    below came out at 53% rather than 100%.
    """
    assert tick_period(ticks_at([3, 3, 6], 400), skip=0)["regular"] == 1.0
    off = tick_period(ticks_at([3, 4, 3, 5], 400), skip=0)
    assert off["regular"] < 0.9
    assert "period" not in off


def test_the_guard_is_what_makes_it_an_instrument():
    """Calibrated against --pace over the corpus, not chosen.

    Ungated, this agreed with --pace on 53% of the files both can measure --
    it produced periods of 1.00, 12.97 and 28.00 with no sign they were
    wrong. Gated on `modal >= 2 and regular >= TICK_MIN_REGULAR` it speaks on
    31 of 95 files and agrees on 18 of the 18 that --pace can check, while
    refusing the other 64 with a stated reason. A tool that is right when it
    speaks and says so when it cannot is worth more here than one that always
    answers.
    """
    assert TICK_MIN_REGULAR == 0.90
    good = tick_period(ticks_at([3], 300), skip=0)
    assert good["regular"] >= TICK_MIN_REGULAR and good["period"]


# ---------------------------------------------------------------------------
# The OTHER tick: the bit-$80 drum's noise hit, whose pitch is fixed.
#
# These live here rather than beside the sfx-drum's other tests because
# `test_ticks.py` is the file the task that measured them was allowed to
# write; the natural homes (`test_noise_tick.py`, `test_phantom_subtunes_sfx.py`)
# were not declared, and an undeclared path is a stop.
# ---------------------------------------------------------------------------

CORPUS_DRUM_PITCHES = (0x38, 0x48)   # Trans-Atlantic Balloon; the other six


def _drum_block(freq_reg, ctrl_reg, period=6):
    """An image carrying the sfx-drum block with those two store targets."""
    body = bytes([0xC9, period, 0xD0, 0x02,          # CMP #period / BNE +2
                  0xA9, 0x48, 0x8D, freq_reg, 0xD4,  # LDA #$48 / STA $D4xx
                  0xA9, 0x81, 0x8D, ctrl_reg, 0xD4])  # LDA #$81 / STA $D4xx
    return SimpleNamespace(data=bytes(64) + body + bytes(64))


def test_the_drum_hit_carries_an_absolute_note_and_never_the_played_one():
    """The hit is a fixed pitch, in BOTH branches of `_sfx_drum_entries`.

    Refuted three ways at 64c795b (see the function's own docstring): the
    player's block has no store to the frequency LOW byte, so its only
    note-dependence is the retained low byte -- 181-242 units of span over
    1116-1423 measured drum frames a file, under 23 cents -- while emitting
    `WAVE_NOTE_BASE` here would move the hit by a median +34 to +56 semitones
    on the instruments that carry it, and costs melody or sequence on three
    of the seven files at both -t 60 and -t 180 while gaining on none.

    So this asserts the *absence* of the obvious repair, which is the thing a
    reader is otherwise likely to try.
    """
    noise = G.WAVE_NOISE_GATEOFF | 0x01
    for pitch_hi in CORPUS_DRUM_PITCHES:
        note = G._sfx_note_byte(pitch_hi)
        assert note > G.WAVE_NOTE_ABS, "an absolute note, not a relative one"
        assert note != G.WAVE_NOTE_BASE and note != G.WAVE_NOTE_KEEP

        left, right, loop = G._sfx_drum_entries(0x41, pitch_hi, 6)
        hits = [i for i, v in enumerate(left) if v == noise]
        assert hits and loop in hits, "the loop re-enters on the hit"
        assert all(right[i] == note for i in hits)

        # ...and with bit $40's own second pitch, which is a different fixed
        # note and must not be mistaken for the played one either.
        second = 0x9F
        left, right, loop = G._sfx_drum_entries(0x41, pitch_hi, 6, 1, second)
        hits = [i for i, v in enumerate(left) if v == noise]
        assert hits and loop in hits
        assert set(right[i] for i in hits) == {note, second}
        assert G.WAVE_NOTE_BASE not in [right[i] for i in hits]


def test_the_drum_block_writes_the_frequency_high_byte_only():
    """A store to the frequency LOW register is not this block.

    This is what makes "the player tracks the note" false rather than merely
    unhelpful: `_find_sfx_drum` accepts the shape only when its two stores are
    the frequency-HIGH and control registers of one voice, so a match is
    positive evidence that the low byte is never written.
    """
    # $D40F / $D412 -- voice 3's frequency high byte and control register.
    assert D._find_sfx_drum(_drum_block(0x0F, 0x12), None) == (0x48, 2, 6)
    # $D40E is that voice's frequency LOW byte, and is refused.
    assert D._find_sfx_drum(_drum_block(0x0E, 0x12), None) == (-1, -1, -1)
    # ...as is a control register belonging to another voice.
    assert D._find_sfx_drum(_drum_block(0x0F, 0x04), None) == (-1, -1, -1)
