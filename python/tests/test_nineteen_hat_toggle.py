"""Nineteen's hi-hat toggle: band-pass for one frame on every hit, low-pass between.

Nineteen `$9512`: each hit of the sfx drum writes `$60 -> $D416`, `$2F -> $D418`
and the next frame's `LDY #$1F / STY $D418` takes the mode back (66 Bnd/Low pairs
per 400 frames in the sparse passage at 117-124 s, 1367 Bnd frames in 180 s).
Without the toggle the conversion never leaves low-pass, and where voice 0 rests
(seconds ~106-128) the original's band-pass ghost is most of what the mix has
(RMS .0354 of .056 in 119-125 s, ours .0002).

`sfx_drum_bandpass` is the emitter (`goatwriter.sfx_bandpass_plan`); this file
pins that Nineteen's SHIPPED preset turns it on, that the filter program it
writes fires the band-pass row once a `period` on the drum lattice, and that the
packed player puts it on the original's hat frames.

Measured at v0.5.655 (-t 180 --presets --sound, historical): `aud` .9082 ->
.9168, 117-124 s .8512 -> .8587; `band` 84% -> 86%, `bnote` 0% -> 99%, `cut`
.43 -> .44, `loud` 95% -> 96%; no printed column falls. Not carried: the drum's
own `$60` cutoff (`test_sfx_drum_bandpass.test_the_unrolled_cutoff_restore_
does_not_fit`).
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import FILT_SET_PARAMS, build            # noqa: E402
from songview import parse_sng                               # noqa: E402
from test_sfx_drum_bandpass import (BP, LP, PRESETS, _bp_frames, _trace,  # noqa: E402
                                    needs_gt2reloc, needs_presets,
                                    needs_siddump, run_filter)

STEM = "Nineteen"


def _shipped():
    doc = json.loads(PRESETS.read_text("utf-8"))
    return fidelity._preset_opts(doc, f"{STEM}.sid")


def _ftbl(opts):
    sng = convert(str(CORPUS / f"{STEM}.sid"), log=lambda m: None, **opts)
    return parse_sng(sng).tables["FTBL"]


@needs_presets
def test_the_shipped_preset_turns_the_toggle_on():
    """SABOTAGE TARGET: `presets.json`'s Nineteen entry (and the per-song search,
    which re-derives `sfx_drum_bandpass` after the walk: `presets.py
    --fidelity` on Nineteen alone chose it at v0.5.655)."""
    opts = _shipped()
    assert opts["sfx_drum"] and opts["sfx_drum_bandpass"] is True


@needs_corpus
@needs_presets
def test_the_shipped_conversion_carries_a_bandpass_row_in_the_drum_programs():
    """SABOTAGE TARGET: `sfx_bandpass_plan` (short-circuit it to `{}` and the
    table has no band-pass row). Two drum records filter in Nineteen, each a
    loop [set][blip][restore][sweep][jump]."""
    rows = _ftbl(_shipped())
    blips = [i for i, (l, _r) in enumerate(rows)
             if l == FILT_SET_PARAMS | BP]
    assert len(blips) == 2, rows
    for i in blips:
        assert rows[i - 1][0] != FILT_SET_PARAMS | BP
        assert rows[i + 1][0] == FILT_SET_PARAMS | LP      # restored next call
    assert len(rows) <= 64


@needs_corpus
@needs_presets
def test_the_emitter_is_what_puts_the_row_there(monkeypatch):
    """Control for the test above: with the plan emptied the same options write
    no band-pass row at all, so the row is the emitter's and not the table's."""
    monkeypatch.setattr(build, "sfx_bandpass_plan", lambda *a, **k: {})
    rows = _ftbl(_shipped())
    assert not [1 for l, _r in rows if l == FILT_SET_PARAMS | BP]


@needs_corpus
@needs_presets
def test_the_program_is_bandpass_once_a_period_and_lowpass_between():
    """Goattracker's own step (`run_filter`, gplay.c:253-300) over the shipped
    table, from each blip's loop: band-pass on exactly one call in `period`
    (6 at `-S1`), low-pass on all the others."""
    rows = _ftbl(_shipped())
    checked = 0
    for i, (l, _r) in enumerate(rows):
        if l != FILT_SET_PARAMS | BP:
            continue
        checked += 1
        seen = run_filter(rows, i + 1, 6 * 12)
        modes = [t for t, _c, _k in seen]
        assert modes.count(BP) == 12, modes
        assert [k for k, m in enumerate(modes) if m == BP] == list(range(0, 72, 6))
    assert checked == 2


@needs_corpus
@needs_presets
@needs_siddump
@needs_gt2reloc
def test_the_packed_player_toggles_on_the_originals_hat_frames(tmp_path):
    """SABOTAGE TARGET: the lattice's first-hit call. In the first 40 s the
    original has 233 band-pass frames and the packed conversion 234; 230 of the
    original's (98.7%) have one of ours 5-7 frames later, the aligner's
    startup lag (6) and the 1-frame ledger residual either side of it."""
    orig, ours = _trace(STEM, True, tmp_path)
    bo, bb = _bp_frames(orig), set(_bp_frames(ours))
    assert len(bo) > 150
    assert abs(len(bb) - len(bo)) <= len(bo) // 10, (len(bb), len(bo))
    near = sum(1 for f in bo if any(f + d in bb for d in (5, 6, 7)))
    assert near >= 0.95 * len(bo), (near, len(bo))
