"""Where the drum's noise lands on Warhawk and Proteus, and why it cannot be exact.

Warhawk `$0F0A` and Proteus `$090A` are drum-only records on a player with an
outer gate of reload 7 (`tempo.outer_gate_skip`): the whole play routine is
skipped on one call in 8, and it is the SAME frame residue for the whole tune.
Traced at -m1 over 180 s the original's drum is one of three shapes from the
gate rise `s` (waveform bytes from frame `s`):

    41 80 40 40   the noise is the frame after the attack      46/62 and 43/62
    41 41 80 40   the skipped frame falls on s+1: the noise is  8/62 and  9/62
                  a frame later
    41 80 80 40   the skipped frame falls on s+2: the noise     8/62 and 10/62
                  holds a second frame

Which one a note gets is a function of `s mod 8` alone -- not of the record, the
voice or the pattern -- so no per-instrument wavetable can say it (the same
finding as Rasputin's, METHOD section 7.ooooooo). The conversion plays the
first shape on every note and so lands on the original's frame on three in
four; the other quarter is the original's outer gate.

The task `warhawk-proteus-drum-wave-frame-late` opened on 6 of 40 and 41 notes
reading `09 41 81` -- the testbit firstwave frame visible before the attack,
a frame late (8 of 62 each at 81a766c) -- which `gate_off_firstwave` removed
(`call_phase.GATE_OFF_FIRSTWAVE`; turning it off brings them back).

The gate bit of the noise (`81` against the original's `80`) is
`_drum_tick_noise`'s measured, deliberate difference and is masked out here.
"""
import json
import pathlib
import sys
from collections import Counter

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from h2g.goatwriter import tempo                             # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

SECONDS = 120
FRAMES = SECONDS * 50
RECORDS = [("Warhawk", 0x0F0A), ("Proteus", 0x090A)]
PLAIN = (0x80, 0x40, 0x40)           # the frame after the attack is the noise
LATE = (0x41, 0x80, 0x40)            # skipped frame at s+1: pitched, then noise
HELD = (0x80, 0x80, 0x40)            # skipped frame at s+2: noise twice


def _timeline(events):
    out = [None] * FRAMES
    cur, it = None, iter(sorted(events))
    nxt = next(it, None)
    for f in range(FRAMES):
        while nxt is not None and nxt[0] <= f:
            cur = nxt[1]
            nxt = next(it, None)
        out[f] = cur
    return out


def _drum_notes(trace, adsr):
    """(s, waveform bytes from frame s+1, three frames) per gate rise of the record."""
    notes = []
    for voice in trace:
        wf = _timeline(voice.wf_events)
        ad = _timeline(voice.adsr_events)
        for s in range(1, FRAMES - 4):
            if (wf[s] is not None and wf[s] & 1 and not (wf[s - 1] or 0) & 1
                    and (ad[s] or 0) == adsr):
                notes.append((s, tuple(x or 0 for x in wf[s + 1:s + 4]),
                              tuple(x or 0 for x in wf[s - 1:s + 1])))
    return notes


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name, adsr", RECORDS)
def test_original_noise_frame_is_the_outer_gate_residue(name, adsr):
    path = CORPUS / f"{name}.sid"
    mod = tempo.outer_gate_skip(load_sid(str(path)), 0) + 1
    assert mod == 8
    trace = fidelity.run_siddump(path, SECONDS, 0, calls=1)
    notes = _drum_notes(trace, adsr)
    assert len(notes) >= 30, len(notes)
    shapes = Counter(n[1] for n in notes)
    # The three shapes the docstring names, and nothing else.
    assert set(shapes) == {PLAIN, LATE, HELD}, shapes
    # Where the skipped frame falls is fixed by the late shape's own notes...
    skip = {(s + 1) % mod for s, shape, _ in notes if shape == LATE}
    assert len(skip) == 1, skip
    k = skip.pop()
    # ... and then predicts every other note: s+1 -> late, s+2 -> held.
    for s, shape, _ in notes:
        want = LATE if (s + 1) % mod == k else HELD if (s + 2) % mod == k \
            else PLAIN
        assert shape == want, (s, shape, want, k)
    # The residue really is the skipped call: across the three voices the
    # frame residue `k` carries (almost) no register change at all, where every
    # other residue carries thousands (Warhawk 0 and Proteus 9 of ~3300).
    events = Counter(f % mod for voice in trace
                     for attr in ("freq_events", "wf_events", "adsr_events")
                     for f, _ in getattr(voice, attr))
    others = sorted(n for r, n in events.items() if r != k)
    assert events[k] * 100 < others[0], (k, dict(events))
    # The plain shape is the majority, which is the one we emit.
    assert shapes[PLAIN] > shapes[LATE] + shapes[HELD]


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name, adsr", RECORDS)
def test_conversion_lands_the_noise_on_the_majority_frame(name, adsr, tmp_path):
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sng = convert(str(CORPUS / f"{name}.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, f"{name}.sid"))
    sng = sng[0] if isinstance(sng, tuple) else sng
    m = fidelity._preset_multiplier(doc, f"{name}.sid")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    trace = fidelity.run_siddump(packed, SECONDS, 0, calls=m)
    notes = _drum_notes(trace, adsr)
    assert len(notes) >= 30, len(notes)
    # The testbit firstwave frame ($09) before the attack is the defect the
    # task opened on: the frame before the gate rise is the note's own, ungated.
    for s, shape, around in notes:
        assert around[0] & 1 == 0 and around[1] & 0xFE == 0x40, (s, around)
        assert tuple(x & 0xFE for x in shape) == PLAIN, (s, shape)
