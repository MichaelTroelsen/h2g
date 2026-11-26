"""The sfx drum's one-frame bandpass on the SHADOW-form player (IK+).

IK_plus' drum fire block (`$E436`) is the documented block with its two noise
stores aimed at a RAM image of the SID (`8D F2 E5` / `8D F5 E5`) and then the
chip stores `$60 -> $D416`, `$2F -> $D418` ten bytes behind the pair, exactly
where the direct form has them. `find_sfx_drum_bandpass` anchored on the direct
form only, so `--sfx-drum-bandpass` was inert on IK_plus while the original's
1487 bandpass frames (`bnote` 0.000, `band` .83) went unemitted.

Reading the tail is half of it. The other half is the cutoff: IK+'s drum notes
hold ONE hit (1077 of 1231 hits are the only hit of their note, `-t 180`) and
the player restarts the note's filter accumulator at every note, so the
original reads `$60 $28 $1C $10 $04` from the hit frame on, every hit. The
loop the direct-form files get cannot write the `$60` (the value after it
differs per hit of a long note) and, shifted by its two non-modulating calls,
took `cfrm` .768 -> .446. The first hit is written out instead
(`find_sfx_drum_shadow_spike`).

Measured at `-t 180 --sound` on IK_plus under presets + `sfx_drum_bandpass`
(historical; v0.5.674): band .835 -> 1.000, bnote 0.000 -> .999, cfrm .768 ->
.890, cut .581 -> .902, aud .9073 -> .9260, loud .935 -> .960, loud_ratio .814
-> .956; no printed column falls.
"""
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from test_sfx_drum_bandpass import (BP, LP, RES, _on_ftbl,   # noqa: E402
                                    _sid, block, needs_presets, run_filter)
from h2g.detect import (find_sfx_drum_bandpass,              # noqa: E402
                        find_sfx_drum_shadow_spike)
from h2g.goatwriter import (FILT_SET_CUTOFF, FILT_SET_PARAMS,  # noqa: E402
                            _sfx_bandpass_block)

SHADOW = "A9 48 8D F2 E5 A9 81 8D F5 E5 A9 60 8D 16 D4"
DIRECT = "A9 48 8D 0F D4 A9 81 8D 12 D4 A9 60 8D 16 D4"
MODE = "A9 2F 8D 18 D4"


def test_the_tail_behind_the_shadow_pair_is_read():
    """SABOTAGE TARGET: the `SFX_DRUM_SHADOW_SHAPE` fallback in
    `find_sfx_drum_bandpass`; without it this reads (-1, -1)."""
    assert find_sfx_drum_bandpass(_sid(SHADOW, MODE)) == (BP, 0x60)


def test_the_shadow_form_still_needs_the_mode_write_behind_it():
    assert find_sfx_drum_bandpass(_sid(SHADOW)) == (-1, -1)
    assert find_sfx_drum_bandpass(_sid(SHADOW, "EA", MODE)) == (-1, -1)


def test_only_the_shadow_form_carries_a_spike():
    """SABOTAGE TARGET: `find_sfx_drum_shadow_spike`. The direct-form files
    keep the unspiked loop their measurements were taken with."""
    assert find_sfx_drum_shadow_spike(_sid(SHADOW, MODE)) == 0x60
    assert find_sfx_drum_shadow_spike(_sid(DIRECT, MODE)) == -1
    assert find_sfx_drum_shadow_spike(_sid("EA EA")) == -1


def _spiked(step=0xF4):
    return _sfx_bandpass_block(LP, BP, RES, 0x40, step, 1, 6, 1, 1, spike=0x60)


def test_the_first_hit_reads_the_players_cutoffs_frame_for_frame():
    """The original's IK_plus trace after a drum note's strike frame:
    `$60 $28 $1C $10 $04` (D416) with the bandpass on the first only."""
    run = run_filter(_spiked(), 1, 6)
    assert [(t, c) for t, c, _ in run[1:6]] == [
        (BP, 0x60), (LP, 0x28), (LP, 0x1C), (LP, 0x10), (LP, 0x04)], run
    assert run[0] == (LP, 0, RES)           # the strike frame writes nothing


def test_the_spiked_head_keeps_the_period_and_loops_on_the_blip():
    """SABOTAGE TARGET: the `n_tail` count of the spiked head. The next hit
    must land `period` calls after the first, on the loop's blip row."""
    rows = _spiked()
    run = run_filter(rows, 1, 1 + 6 * 4)
    bp = [i for i, (t, _, _) in enumerate(run) if t == BP]
    assert bp == [1, 7, 13, 19], bp
    left, right = rows[-1]
    assert left == 0xFF and rows[right - 1] == (FILT_SET_PARAMS | BP, RES)


def test_without_a_spike_the_block_is_the_one_every_other_file_has():
    assert _sfx_bandpass_block(LP, BP, RES, 0x40, 0xF4, 1, 6, 1, 1) == block(0xF4)


def test_a_multispeed_player_keeps_the_plain_loop():
    """The spiked head is written for `-S1` with the hit on the first call."""
    assert _sfx_bandpass_block(LP, BP, RES, 0x40, 0xF4, 2, 6, 2, 1,
                               spike=0x60) == block(0xF4, 2, 6)


@needs_corpus
@needs_presets
def test_ik_plus_forced_on_writes_the_spike_row():
    """SABOTAGE TARGET: the `find_sfx_drum_shadow_spike` argument at the
    `_filter_entries` call site. IK_plus' drum records (2, 8, 9, 15 -- the
    ones that route a voice) each carry `[BP params][cutoff $60]`."""
    rows = _on_ftbl("IK_plus")
    spikes = [i for i in range(len(rows) - 1)
              if rows[i][0] == FILT_SET_PARAMS | BP
              and rows[i + 1] == (FILT_SET_CUTOFF, 0x60)]
    assert spikes, rows
    at = spikes[0]
    assert rows[at + 1] == (FILT_SET_CUTOFF, 0x60)
    assert rows[at + 3] == (FILT_SET_CUTOFF, 0x28)
