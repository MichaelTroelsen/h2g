"""`vibrato_round_up`: Delta's classic vibrato gives back swing for rate
(task listen-sub99-delta).

Delta subtune 11 read bend 0.65x, travel 0.74x, depth 0.76x (listening index
of 2026-11-21, v0.5.674). All of it is voice 0's three vibrato records
(`$09AB`, `$0C99`: byte $23, bound 4 shift 3; `$3D00`: byte $12, bound 2
shift 2), and the player's code is

    C034  LDA $BDDE,X / LSR / TAY / DEY / BMI    freq -= depth, bound/2 times
    C055  LDY $BDDB,X / DEY / BMI                freq += depth, ctr times

so the swing is `bound` depths of `(f(n) - f(n-1)) >> shift`, one update a
frame. At -S2 over 5-call rows the packed player skips the effects on tick 0
(`REALTIMEOPTIMIZATION`), so the entry's half-period is `bound * 2 * 4/5` =
6.4 active calls, which `round` takes to 6; the swing is `(cmp + 2) * speed`
and `speed` is a whole shift, so the 0.4 call comes off the swing and nothing
can pay it back (traced at call resolution: 6 steps of $2C up, hold, 6 down,
against the original's 4 steps of $53 a frame). Rounding the half-period up
takes the swing from 6 to 7 steps and the rate from 1.07x to 0.91x.
"""
import inspect
import json
import pathlib
import sys

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter.vibrato import _classic_vibrato_entry    # noqa: E402
import presets                                               # noqa: E402

DELTA = CORPUS / "Delta.sid"
COMMANDO = PYTHON_ROOT.parent / "Commando.sid"
PRESETS = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())


def _active_calls(entry):
    """Goattracker's half-period in calls: cmp + 2 (VIBRATO_CMP_BIAS)."""
    return (entry[0] & 0x7F) + 2


def test_a_fractional_half_period_rounds_up_not_to_nearest():
    # Delta's `$23` (bound 4) and `$12` (bound 2) at -S2, 5-call rows:
    # half = 6.4 and 3.2.
    assert _active_calls(_classic_vibrato_entry(0x23, 2, 5)) == 6
    assert _active_calls(_classic_vibrato_entry(0x23, 2, 5,
                                                round_up=True)) == 7
    assert _active_calls(_classic_vibrato_entry(0x12, 2, 5)) == 3
    assert _active_calls(_classic_vibrato_entry(0x12, 2, 5,
                                                round_up=True)) == 4


def test_round_up_changes_the_cmp_only_not_the_shift():
    plain = _classic_vibrato_entry(0x23, 2, 5)
    up = _classic_vibrato_entry(0x23, 2, 5, round_up=True)
    assert plain == (0x84, 4) and up == (0x85, 4)


def test_a_whole_or_high_fraction_half_period_is_unchanged():
    # bound 4 at -S1, no row compensation: half 4.0. bound 3 at -S2 over
    # 5-call rows: 4.8, which `round` already takes up.
    for byte, mult, rows in ((0x23, 1, 0), (0x1B, 2, 5), (0x23, 2, 0)):
        assert (_classic_vibrato_entry(byte, mult, rows)
                == _classic_vibrato_entry(byte, mult, rows, round_up=True))


def test_the_option_is_off_by_default_and_listed_per_song():
    assert "vibrato_round_up" in presets.EXCLUDED_FROM_ALWAYS


def test_round_up_leaves_commando_alone():
    assert (convert(str(COMMANDO), log=lambda m: None, vibrato_round_up=True)
            == convert(str(COMMANDO), log=lambda m: None))


def _delta(**over):
    opts = fidelity._preset_opts(PRESETS, DELTA.name)
    sig = inspect.signature(convert).parameters
    kw = {k: v for k, v in opts.items() if k in sig}
    kw.update(over)
    return convert(str(DELTA), log=lambda m: None, **kw)


@needs_corpus
def test_delta_ships_the_longer_entries_and_off_differs():
    # Adopted on Delta only (user decision, task adopt-delta-vibrato-round-up):
    # the shipped entry sets it, and the same song with it off differs.
    assert PRESETS["songs"]["Delta.sid"]["vibrato_round_up"] is True
    shipped = _delta()
    assert _delta(vibrato_round_up=True) == shipped
    assert _delta(vibrato_round_up=False) != shipped
