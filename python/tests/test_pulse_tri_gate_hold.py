"""Samantha Fox's `pul` count overshoot is the player's OUTER GATE, not a
pulse defect -- pinned against both traces.

The task (`pulse-tri-zp-change-count-overshoot`) read our pulse changes at
~1.25x the original's on every voice (4385 vs 3513) and asked whether the
note-fetch frame the player skips disagreed with the GT program's set
entry. Measured at 81da71d it does not; the whole excess is the gate:

* `$7006 DEC $EA / BPL / LDA #$04 / STA $EA / RTS` returns before the
  player does anything one frame in five (`outer_gate_skip` = 4), so the
  original's width HOLDS on that frame and moves a full step on the other
  four;
* `goatwriter.pulse._tri_speed` spreads the same travel over every call
  (calls a tick `multiplier * (O + 1) / O`), so ours moves on all five.

Hence ours / original = (O + 1) / O = 1.25 with every extra change on one
frame phase mod 5 and none on a fetch frame. See `_tri_speed`'s docstring
for the figures and for why copying the stutter is not worth it.
"""
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402

SAMANTHA = "Samantha_Fox_Strip_Poker.sid"
SECONDS = 30
_CACHE: dict = {}


def _traces():
    """(original, ours, lag, O), Samantha Fox under its shipped preset:
    the original at -m1, ours converted, packed at -S{multiplier} and traced
    at -m{multiplier}, exactly as fidelity.py measures it. Once a session."""
    if _CACHE:
        return _CACHE["v"]
    import json
    import fidelity as F
    from h2g.convert import convert
    from h2g.goatwriter.tempo import outer_gate_skip
    from h2g.sidfile import load_sid
    sid = CORPUS / SAMANTHA
    presets = Path(__file__).resolve().parents[2] / "presets.json"
    if (not sid.exists() or not presets.exists()
            or not Path(F.SIDDUMP).exists() or not Path(F.GT2RELOC).exists()):
        pytest.skip("Samantha Fox, presets.json, siddump or gt2reloc missing")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, SAMANTHA)
    mult = doc["songs"][SAMANTHA].get("multiplier", 1)
    wd = Path(tempfile.mkdtemp(prefix="sf_gate_hold_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(sid, local)
        cal, _ = F.table_calibration(sid, opts)
        sub = F.resolve_subtune(sid, "auto")
        orig = F.run_siddump(local, SECONDS, sub, F.SIDDUMP, cal)
        blob, _ = F.legalise_restarts(convert(str(sid), log=lambda m: None,
                                              **opts))
        packed = F.pack_sid(blob, wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        ours = F.run_siddump(packed, SECONDS, sub, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    lag, _ = F.startup_lag(orig, ours)
    n = SECONDS * 50
    voices = []
    for a, b in zip(orig, ours):
        voices.append((F.register_timeline(a.pulse_events, n),
                       F.register_timeline(b.pulse_events, n),
                       list(zip(a.attack_frames, a.attacks)),
                       list(zip(b.attack_frames, b.attacks))))
    _CACHE["v"] = (voices, lag, outer_gate_skip(load_sid(str(sid))), mult)
    return _CACHE["v"]


def _walk(ta, tb, lag, period):
    """Frames (original's numbering) where exactly one side moves."""
    n = len(ta) - lag
    ours_only = [f for f in range(2, n)
                 if tb[f + lag] != tb[f + lag - 1] and ta[f] == ta[f - 1]]
    orig_only = [f for f in range(2, n)
                 if ta[f] != ta[f - 1] and tb[f + lag] == tb[f + lag - 1]]
    changes = (sum(ta[f] != ta[f - 1] for f in range(2, n)),
               sum(tb[f + lag] != tb[f + lag - 1] for f in range(2, n)))
    return ours_only, orig_only, changes


@needs_corpus
def test_the_gate_is_what_the_count_reads():
    """Every frame where ours moves and the original holds sits on ONE phase
    mod O+1 on all three voices -- the gate's -- the original never moves
    where ours holds, and the excess IS those frames."""
    voices, lag, O, _ = _traces()
    assert O == 4, f"Samantha Fox's outer gate reload read {O}, not 4"
    period = O + 1
    phases, held, excess, orig_total = set(), set(), 0, 0
    for vi, (ta, tb, _, _) in enumerate(voices):
        ours_only, orig_only, (ca, cb) = _walk(ta, tb, lag, period)
        assert ours_only, f"voice {vi}: no gate-held frame in {SECONDS} s"
        assert not orig_only, (vi, orig_only[:8])
        assert cb - ca == len(ours_only), (vi, ca, cb, len(ours_only))
        phases |= {f % period for f in ours_only}
        # the original's own isolated holds inside a sweep: still, between
        # two frames that both moved
        held |= {f % period for f in range(2, len(ta) - 1)
                 if ta[f] == ta[f - 1] != ta[f - 2] and ta[f + 1] != ta[f]}
        excess += cb - ca
        orig_total += ca
    assert len(phases) == 1, f"the extra changes span phases {sorted(phases)}"
    assert held == phases, (sorted(held), sorted(phases))
    assert 1.2 <= (orig_total + excess) / orig_total <= 1.3, (orig_total, excess)


@needs_corpus
def test_the_note_fetch_frame_is_not_part_of_the_excess():
    """The verify's own question. The player opens a note on the record's
    width and steps from the next frame; our set entry plus one call's
    speed lands within a step of it. Both sides change on the fetch frame,
    so no extra change is ever counted there."""
    voices, lag, O, _ = _traces()
    for vi, (ta, tb, aa, ab) in enumerate(voices):
        ours_only, _, _ = _walk(ta, tb, lag, O + 1)
        fetch = {f for f, _ in aa}
        assert not [f for f in ours_only if f in fetch], vi
        # Paired by note: our width on our attack frame is the record's
        # width (the original's, on its own fetch frame) plus at most the
        # one frame of travel the calls after the set entry add.
        pairs = list(zip(aa, ab))
        assert pairs and all(x[1] == y[1] for x, y in pairs), (
            vi, "the two sides' attacks no longer name the same notes")
        off = [(f, g, tb[g] - ta[f], abs(tb[g + 1] - tb[g]))
               for (f, _), (g, _) in pairs if g + 1 < len(tb)]
        bad = [o for o in off if not 0 <= o[2] <= o[3]]
        assert len(bad) <= len(off) // 20, (vi, len(bad), len(off), bad[:6])


@needs_corpus
def test_the_rate_spreads_the_gate_rather_than_ignoring_it():
    """What makes the count overshoot is also what keeps the TRAVEL right:
    ours steps `step / (O+1) * multiplier`-ish every frame where the original
    steps `step` O frames in O+1. A speed that ignored the gate (divided by
    `multiplier` alone) would match the original's per-frame step and run
    (O+1)/O fast -- this ratio would read 1.0."""
    voices, lag, O, _ = _traces()
    for vi, (ta, tb, aa, ab) in enumerate(voices):
        fa, fb = {f for f, _ in aa}, {g for g, _ in ab}
        sa = [abs(ta[f] - ta[f - 1]) for f in range(2, len(ta))
              if f not in fa and ta[f] != ta[f - 1]]
        sb = [abs(tb[f] - tb[f - 1]) for f in range(2, len(tb))
              if f not in fb and tb[f] != tb[f - 1]]
        ratio = statistics.median(sb) / statistics.median(sa)
        # O/(O+1) = 0.8, less GT's integer speed rounding (16 -> 12, 32 -> 24)
        assert 0.7 <= ratio <= 0.86, (vi, statistics.median(sa),
                                      statistics.median(sb))
