"""`--regrid` pays a row that `tempo_command_value` FLOORS, not only one it declined.

Knucklebusters.sid packs at `-S3`, the factor its START subtune wants (7/3
frames). Subtune 2 runs the same player with an outer counter of 16: its row is
2 * 17/16 = 17/8 frames, an exact fraction with a denominator `effective_frames`
accepts (<= MAX_ROW_DENOMINATOR) -- so it did not decline, and `regrid_deficits`
(which paid only DECLINED rows, where `eff * multiplier == tempo`) wrote 0.
But 17/8 frames is 6.375 calls at `-S3`, and `tempo_command_value` floors that
to 6: a row of exactly 2.0 frames against the original's 2.125. Ticks of the
original over 2720 frames (a 6502 emulation of the file): 1280, gaps 2 x 1119
and 3 x 160. Ours: 1360. `drift` -58.82 per 1000 (exactly -1/17), `len` -3.1 s,
`gate` .49, every edge 160 frames early at the end.

`regrid_floored` (per song, off by default) makes `regrid_deficits` also owe the
fraction of a call a floored exact row drops. It is an option and not the
default because the same arithmetic moves four shipped `regrid` files
(Auf_Wiedersehen_Monty, Delta, Star_Paws, Wiz) whose other subtunes were never
measured under it: Star_Paws subtune 1 melody -3.5pp, Wiz subtune 2 drift
unchanged at -110.8 per 1000.
"""
import json
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert, regrid_deficits             # noqa: E402
from h2g.goatwriter.tempo import SongSpeeds, effective_frames  # noqa: E402

KNUCKLEBUSTERS = CORPUS / "Knucklebusters.sid"


def _speeds(frames, skip):
    return SongSpeeds(tuple(frames), 0, None, skip=tuple(skip))


def test_a_floored_exact_row_owes_the_dropped_fraction_of_a_call_in_frames():
    """Knucklebusters subtune 2, synthetically: 2 frames, outer 16, -S3."""
    sp = _speeds([2], [16])
    assert sp.exact_row(0) == Fraction(17, 8)
    assert effective_frames(sp, 0, True) == Fraction(17, 8)   # not declined
    # tempo_command_value: int(17/8 * 3) = 6 calls
    got = regrid_deficits(sp, [6], True, 3, floored=True)
    assert got == pytest.approx([(6.375 - 6) / 3])            # 1/8 of a frame


def test_without_the_option_a_floored_row_owes_nothing_as_before():
    """Every shipped `regrid` song's bytes depend on this: the default call."""
    sp = _speeds([2], [16])
    assert regrid_deficits(sp, [6], True, 3) == [0.0]
    assert regrid_deficits(sp, [6], True, 3, floored=False) == [0.0]


def test_a_row_the_multiplier_carries_exactly_still_owes_nothing():
    """Knucklebusters subtune 1: 7/3 frames is tempo 7 at -S3, exactly."""
    sp = _speeds([2], [6])
    assert effective_frames(sp, 0, True) == Fraction(7, 3)
    assert regrid_deficits(sp, [7], True, 3, floored=True) == [0.0]


def test_a_tempo_that_is_not_the_floored_row_owes_nothing():
    """`values` overwritten by an opening `$FE` or a split is another clock."""
    sp = _speeds([2], [16])
    for tempo in (7, 5, 2):                       # 2: the funktempo floor
        assert regrid_deficits(sp, [tempo], True, 3, floored=True) == [0.0]


@needs_corpus
def test_regrid_floored_reaches_knucklebusters_subtune_2_and_nothing_else_does():
    """End to end. `regrid` alone leaves Knucklebusters' bytes exactly as they
    are with `regrid` off (every deficit reads 0); `regrid_floored` rewrites
    subtune 2's clock. The shipped preset sets both (adopted v0.5.662)."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import fidelity
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Knucklebusters.sid")
    assert fidelity._preset_multiplier(doc, "Knucklebusters.sid") == 3
    assert opts["regrid"] and opts["regrid_floored"], "the adoption left presets.json"
    opts["regrid"] = opts["regrid_floored"] = False
    off = convert(str(KNUCKLEBUSTERS), log=lambda m: None, **opts)
    opts["regrid"] = True
    plain = convert(str(KNUCKLEBUSTERS), log=lambda m: None, **opts)
    assert plain == off, "regrid alone must not move a floored row"
    lines = []
    opts["regrid_floored"] = True
    on = convert(str(KNUCKLEBUSTERS), log=lines.append, **opts)
    rg = [ln for ln in lines if ln.startswith("Re-grid")]
    assert rg, "regrid_tempos was never called: every deficit read 0"
    assert int(rg[0].split(":")[1].split()[0]) > 0, rg[0]
    assert on != off
