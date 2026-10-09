"""The global-triangle vibrato's shift rounds the WHOLE ratio, once.

Opened by global-triangle-vibrato-tick0 (head 6e467ff): Game_Killer (`-S9`)
read depth 0.785 under the harness while `_triangle_vibrato_entry`'s own model
predicted 1.5x. Diagnosed by game-killer-triangle-depth (2026-10-09; figures
historical, `C:/t/game-killer-triangle-depth/runs/`):

* The model was right and the harness was the blind party. `fidelity.py --vice`
  (a per-call trace) read Game_Killer's one pure-triangle vibrato record
  (`$19BA`, vibrato byte 2) at 0.03232 of the pitch against the original's
  0.02166, 1.49x; the siddump column keeps one call in nine at `-S9` and read
  1.27x for the same record.
* The defect was a dropped factor. The derivation in `_triangle_vibrato_entry`
  is `rshift = byte + 1 + log2(multiplier) + log2((PERIOD / 2) / PEAK)`, with
  the last term `log2(4/3) = 0.415` "absorbed" because `round(k + 0.415) == k`
  for an INTEGER k. `log2(multiplier)` is an integer only at 1, 2, 4, 8, so
  the code rounded `log2(9) = 3.17` to 3 (a division by 8 where 12 is wanted)
  and swung 4.5 depths against the player's 3. Rounding the sum, `round(3.585)
  = 4`, swings 2.25 (0.75x). Of the 25 triangle files only Game_Killer has a
  multiplier (9) on which the two roundings differ.

The swing is checked through a transcription of gplay.c:795-801, as
`test_classic_vibrato_swing.py` does for the classic mapping.
"""
import math
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
from h2g.detect import (TRIANGLE_VIBRATO_PEAK,                # noqa: E402
                        TRIANGLE_VIBRATO_PERIOD)
from h2g.goatwriter import (_rate_shift, _triangle_rate_shift,           # noqa: E402
                           _triangle_vibrato_entry)

HALF = TRIANGLE_VIBRATO_PERIOD // 2


def _gt_swing(entry, interval):
    """Peak-to-peak and period (calls) of gplay.c:795-801 over many periods."""
    cmp_value, rshift = entry
    assert cmp_value & 0x80                                  # note-relative
    cmp_value &= 0x7F
    speed = interval >> rshift
    vibtime, freq, seen = 0, 0, [0]
    for _ in range(8 * (cmp_value + 2)):
        if vibtime < 0x80 and vibtime > cmp_value:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        freq += -speed if vibtime & 1 else speed
        seen.append(freq)
    return max(seen) - min(seen), 2 * cmp_value + 4


def test_the_shift_is_the_rounded_ratio_not_the_rounded_multiplier():
    for m in range(1, 33):
        want = max(0, round(math.log2(m * HALF / TRIANGLE_VIBRATO_PEAK)))
        assert _triangle_rate_shift(m) == want, m


def test_it_agrees_with_the_plain_rate_shift_except_at_5_9_10_11():
    """Every corpus multiplier but Game_Killer's 9 is 1 or 2, where the two
    roundings coincide, so the change moves one file."""
    differ = [m for m in range(1, 17)
              if _triangle_rate_shift(m) != _rate_shift(m)]
    assert differ == [5, 9, 10, 11]


@pytest.mark.parametrize("multiplier", range(1, 17))
@pytest.mark.parametrize("byte", [1, 2, 3])
def test_the_emitted_swing_is_within_half_an_octave_of_the_players(
        multiplier, byte):
    """The player swings `PEAK * (interval >> (byte + 1))`; the entry's swing,
    run through Goattracker's loop, is never further than 2**0.5 from it, in
    either direction. (The old shift was 2**0.585 too deep at `-S9`.)"""
    interval = 1 << 16
    entry = _triangle_vibrato_entry(byte, multiplier)
    p2p, period = _gt_swing(entry, interval)
    player = TRIANGLE_VIBRATO_PEAK * (interval >> (byte + 1))
    assert abs(math.log2(p2p / player)) <= 0.5 + 1e-9
    # The period is the player's, in calls: 8 frames of `multiplier` calls.
    assert period == TRIANGLE_VIBRATO_PERIOD * multiplier


def test_game_killer_s9_swings_three_quarters_of_the_player_not_one_and_a_half():
    interval = 1 << 16
    for byte in (1, 2):
        entry = _triangle_vibrato_entry(byte, 9)
        assert entry == (0x80 | (HALF * 9 - 2), byte + 1 + 4)
        p2p, period = _gt_swing(entry, interval)
        player = TRIANGLE_VIBRATO_PEAK * (interval >> (byte + 1))
        assert p2p / player == 0.75
        assert period == 72


@needs_corpus
def test_only_game_killer_moves_among_the_triangle_files_under_presets():
    import json
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    songs = json.load(open(PYTHON_ROOT.parent / "presets.json"))["songs"]
    moved = []
    for name, cfg in sorted(songs.items()):
        path = CORPUS / name
        if not path.exists():
            continue
        det = detect(load_sid(str(path)), lambda *a, **k: None)
        if det.triangle_vibrato is None:
            continue
        m = cfg.get("multiplier", 1)
        if _triangle_rate_shift(m) != _rate_shift(m):
            moved.append(name)
    assert moved == ["Game_Killer.sid"]
