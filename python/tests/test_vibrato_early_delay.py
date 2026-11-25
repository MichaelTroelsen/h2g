"""`vibrato_early_delay`: a classic vibrato's `vibdelay` floor loses the one
effect call tick 0 does not run (task listen-sub99-sigma-seven).

Sigma_Seven's original moves a vibrato note's pitch on frame 1 (109 of 140
notes) or 2 (31); ours first moved on frame 6 (111 of 140), five frames into
notes that are 12 frames long. The packed player runs no effect on tick 0
(`REALTIMEOPTIMIZATION`, player.s:982-987), so effect call `k` of a row is play
call `k`, and the floor `multiplier + 1` starts the oscillator one effect call
after the first call of frame 1. The option takes the floor to `multiplier`
where rows are 2 calls or longer. Forced on, Sigma_Seven -t 180 (v0.5.676,
historical): tiefr .584 -> .595, bend .607 -> .648, travel .643 -> .677,
reversals .877 -> .920, cents .969 -> .972, melody and gate unmoved.
"""
import inspect
import json
import pathlib
import sys

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
import presets                                               # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import _vibrato_delay                    # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from songview import parse_sng                               # noqa: E402

SIGMA = CORPUS / "Sigma_Seven.sid"
COMMANDO = PYTHON_ROOT.parent / "Commando.sid"
PRESETS = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())


def _sigma(**over):
    opts = fidelity._preset_opts(PRESETS, SIGMA.name)
    sig = inspect.signature(convert).parameters
    kw = {k: v for k, v in opts.items() if k in sig}
    kw.update(over)
    return convert(str(SIGMA), log=lambda m: None, **kw)


def _delays(blob):
    """vibdelay of every instrument that carries a vibrato entry."""
    return sorted({i.vib_delay for i in parse_sng(blob).instruments
                   if i.vib_ptr})


@needs_corpus
def test_the_floor_loses_one_effect_call_only_where_tick_0_skips_one():
    sid = load_sid(str(SIGMA))
    det = detect(sid, lambda m: None)
    # No gate delay in this player, so the floor is the delay.
    assert _vibrato_delay(det, 1, row_calls=3) == 2
    assert _vibrato_delay(det, 1, row_calls=3, early=True) == 1
    assert _vibrato_delay(det, 3, row_calls=8) == 4
    assert _vibrato_delay(det, 3, row_calls=8, early=True) == 3
    # No tick-0 skip (rows of 0 or 1 call): nothing to take off.
    for rows in (0, 1):
        assert (_vibrato_delay(det, 1, row_calls=rows, early=True)
                == _vibrato_delay(det, 1, row_calls=rows) == 2)


@needs_corpus
def test_sigma_seven_starts_its_oscillator_one_effect_call_earlier():
    # Sigma_Seven's preset sets the option (adopted v0.5.678), so the
    # shipped file is the early one and "base" is the option off.
    base = _sigma(vibrato_early_delay=False)
    early = _sigma(vibrato_early_delay=True)
    assert _sigma() == early
    assert early != base
    assert _delays(base) == [2]
    assert _delays(early) == [1]


def test_the_option_is_off_by_default_and_listed_per_song():
    assert "vibrato_early_delay" in presets.EXCLUDED_FROM_ALWAYS
    assert not inspect.signature(convert).parameters[
        "vibrato_early_delay"].default


def test_early_delay_leaves_commando_alone():
    assert (convert(str(COMMANDO), log=lambda m: None,
                    vibrato_early_delay=True)
            == convert(str(COMMANDO), log=lambda m: None))
