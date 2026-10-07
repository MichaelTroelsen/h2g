"""Why the drum records do not get Goattracker's hard restart back above -S1.

A measurement shipped as a keyed table (see `_drum_tick_noise`'s docstring),
the sequel to `test_drum_tick_adsr_delay.py`. The original writes ADSR $0000
before every gate rise, which drops the release period to 9 cycles, so the
rate counter has wrapped long before the drum's gate rises. The targeted form
tried here was Goattracker's own hard restart on the drum records only (their
gatetimer without bit $80): it writes `adparam` $0F00 (R=0) on the fetch call,
`gatetimer & $3F` calls before the note.

It cannot do what the original does, in either regime. VICE, 60 s under
presets, drum voice swapped onto voice 3, rise -> first ENV3 increase:

* Window SHORTER than the 520-line wrap: Rasputin (-S2) holds the $0F00 for
  309 lines (2 calls). Its attack starts a median 209 lines after the rise
  (max 215), against 504 without it and 1 in the original. 309 + 209 is the
  wrap: the hard restart starts the wrap and the rise inherits what is left.
* Window LONGER than the wrap: Formula_1_Simulator (-S2, 620 lines),
  Warhawk and Proteus (-S7, 622/621) finish the wrap before the rise, and
  the delay is still the whole wrap, median 519-520 lines. Goattracker's
  note init writes the record's SR 1-2 lines BEFORE the gate rises
  (`player.s` mt_newnoteinit, then the gate in mt_loadregs): the release
  period goes back up while the gate is still off, the counter climbs past
  the attack's 9, and the rise waits for a fresh wrap. The original holds
  $0000 until the rise itself.
"""
import json
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter.hard_restart import _hard_restart_ticks  # noqa: E402

CYCLES_PER_LINE = 63                 # PAL
LINES_PER_FRAME = 312
WRAP_LINES = 0x8000 / CYCLES_PER_LINE    # 520.1

# Rasputin, -S2, VICE at v0.5.513 + the uncommitted cycle-3 merge.
RASPUTIN_MULTIPLIER = 2
RASPUTIN_ROW_CALLS = 4               # its drum records' gatetimer is 2 (and 3)
MEASURED_HR_WINDOW_LINES = 309       # $0F00 held before the rise, median
MEASURED_HR_DELAY_LINES = (209, 215)  # rise -> first ENV3 increase, median, max


# Window LONGER than the wrap: (multiplier, a row length giving the gatetimer
# the conversions carry -- 4 calls on Formula_1_Simulator's drum records, 14
# on Warhawk's and Proteus' -- measured window lines, measured delay median,
# lines from the record's SR landing to the rise, most common).
LONG_WINDOW = {
    "Formula_1_Simulator": (2, 8, 620, 520, 1),
    "Warhawk": (7, 28, 622, 519, 1),
    "Proteus": (7, 28, 621, 519, 1),
}


def test_the_window_is_the_gatetimer_in_lines():
    ticks = _hard_restart_ticks(RASPUTIN_MULTIPLIER, RASPUTIN_ROW_CALLS)
    lines = ticks * LINES_PER_FRAME / RASPUTIN_MULTIPLIER
    assert ticks == 2
    assert abs(lines - MEASURED_HR_WINDOW_LINES) <= 4


def test_the_window_is_shorter_than_the_wrap():
    assert MEASURED_HR_WINDOW_LINES < WRAP_LINES


def test_the_delay_left_is_the_wrap_less_the_window():
    median, worst = MEASURED_HR_DELAY_LINES
    assert abs(WRAP_LINES - MEASURED_HR_WINDOW_LINES - median) <= 3
    assert worst <= WRAP_LINES - MEASURED_HR_WINDOW_LINES + 6


@pytest.mark.parametrize("name", sorted(LONG_WINDOW))
def test_a_window_past_the_wrap_still_leaves_the_whole_wrap(name):
    m, row, window, delay, sr_lead = LONG_WINDOW[name]
    ticks = _hard_restart_ticks(m, row)
    assert abs(ticks * LINES_PER_FRAME / m - window) <= 5
    assert window > WRAP_LINES
    # The SR lands more than the attack period's 9 cycles before the rise,
    # so the counter is past 9 when the gate rises: a whole wrap again.
    assert sr_lead * CYCLES_PER_LINE > 9
    assert delay >= WRAP_LINES - 2


@needs_corpus
def test_rasputins_drum_records_keep_no_hard_restart():
    """The decision itself: every record, drums included, keeps bit $80."""
    import fidelity as F
    import songview as V
    from h2g.convert import convert
    root = Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = F._preset_opts(doc, "Rasputin.sid")
    assert opts.get("no_hard_restart") is True
    assert F._preset_multiplier(doc, "Rasputin.sid") == RASPUTIN_MULTIPLIER
    song = V.parse_sng(convert(str(next(CORPUS.rglob("Rasputin.sid"))),
                               log=lambda *a, **k: None, **opts))
    hr = [n + 1 for n, ins in enumerate(song.instruments)
          if not ins.gatetimer & 0x80]
    assert hr == [], f"instruments with the hard restart on: {hr}"
