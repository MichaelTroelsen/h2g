"""The gate-off firstwave shows its waveform SELECT on the init frame, one frame
before the pitch frame; the original keeps the previous note's waveform there.

`gate_off_firstwave` spends the note-init call on the record's own waveform with
the gate CLEAR (`waveform & $FE`); the wavetable's first step then writes the
gated waveform on the pitch frame. Tarzan voice 3 alternates two instruments,
`$40`-select and `$10`-select, and the original never writes a waveform on its
init frame (it holds the previous note's, `$40` or `$10`, gate clear). Ours
changes the select there exactly when the previous note's select differs from
the new record's -- 146 of 536 paired attacks at -t 180 (60 of 176 at 60 s),
and none where they agree.

That is inherent to a per-instrument firstwave byte, not a defect of this one.
Every other byte was measured on Tarzan and is worse on voices 2 and 3 as well as
the 60: `$FF` (gate on, waveform latched; gplay.c:355-358) opens the gate on the
stale pitch (the `no_test_restart` defect, the program starts a frame before
the pitch on 435 of 436 voice-2 attacks); `$FE` never opens the gate at all (0
attacks: the wavetable's `$11` is masked by the latched gate `$FE`); `$08` and
`$18` change the select on the init frame on every attack of voices 2 and 3. Only
a byte that depended on the previous note's last waveform would latch, and the
firstwave byte is part of the instrument record.

Historical figures (Tarzan, lag 6, b23f86b); the tests assert the property, not
the counts. Every arm forces its options explicitly so a later `presets.json`
decision for Tarzan cannot make them a tautology.
"""
import json
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAME = "Tarzan.sid"
SECONDS = 30
EVERY = tuple(range(1, 64))

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def pitch_frame(freq, f):
    """The frame an attack's PITCH lands on (f+1 when the rise at f carries the
    previous frame's frequency)."""
    if f >= 1 and freq[f] == freq[f - 1] and freq[f + 1] != freq[f]:
        return f + 1
    return f


def _program_start(wf, h):
    """Offset from `h` of the first waveform change in [h-2, h+3], else None."""
    for k in range(h - 2, h + 4):
        if wf[k] != wf[k - 1]:
            return k - h
    return None


def _measure(firstwave_byte=None):
    """(orig voices, our voices, lag) for Tarzan with the gate-off firstwave on
    every instrument and `no_test_restart` off; `firstwave_byte` replaces
    `gate_off_firstwave` by a constant for the contrast arms."""
    from h2g.convert import convert
    from h2g.goatwriter import instruments
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = dict(fidelity._preset_opts(doc, NAME), no_test_restart=False,
                real_firstwave_instruments=(),
                gate_off_firstwave_instruments=EVERY)
    assert doc["songs"][NAME].get("multiplier", 1) == 1
    real = instruments.gate_off_firstwave
    if firstwave_byte is not None:
        instruments.gate_off_firstwave = lambda w: firstwave_byte
    try:
        sng, _ = fidelity.legalise_restarts(
            convert(str(CORPUS / NAME), log=lambda m: None, **opts))
    finally:
        instruments.gate_off_firstwave = real
    with tempfile.TemporaryDirectory() as work:
        packed = fidelity.pack_sid(sng, pathlib.Path(work))
        assert packed is not None and packed.exists()
        sub, our_sub, _ = fidelity.resolve_pair(CORPUS / NAME, "auto")
        orig = fidelity.run_siddump(CORPUS / NAME, SECONDS, sub)
        ours = fidelity.run_siddump(packed, SECONDS, our_sub)
    return orig, ours, fidelity.startup_lag(orig, ours)[0]


def _paired(orig, ours, lag):
    """Per paired attack of one voice: (our timeline, f, original timeline, g)
    with `f` the attack moved to its pitch frame."""
    n = max([e[0] for e in orig.wf_events + ours.wf_events] + [0]) + 30
    wa = fidelity.register_timeline(orig.wf_events, n)
    wb = fidelity.register_timeline(ours.wf_events, n)
    fb = fidelity.register_timeline(ours.freq_events, n)
    oa = set(orig.attack_frames)
    for f in ours.attack_frames:
        p = pitch_frame(fb, f)
        if p - lag in oa and p >= 3:
            yield wb, p, wa, p - lag


@pytest.fixture(scope="module")
def gate_off():
    return _measure()


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_init_frame_select_is_the_records_waveform_gate_clear(gate_off):
    """Voice 3: the frame before the pitch frame carries the new note's select
    with the gate clear on EVERY paired attack (it is `waveform & $FE`, the
    pitch frame's `waveform` minus its gate bit), and it is the original who
    holds the previous note's waveform there -- on every attack."""
    orig, ours, lag = gate_off
    rows = list(_paired(orig[2], ours[2], lag))
    assert len(rows) > 50, len(rows)
    for wb, f, wa, g in rows:
        assert wb[f - 1] == wb[f] & 0xFE, (f, wb[f - 1:f + 1])
        assert wa[g - 1] == wa[g - 2], (g, wa[g - 2:g + 1])


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_select_shows_early_exactly_when_the_previous_select_differs(
        gate_off):
    """Voice 3: our select changes on the init frame iff the previous note's
    last waveform is not the new record's -- so the early frames exist, are a
    minority, and no per-instrument byte can remove them."""
    orig, ours, lag = gate_off
    changed = unchanged = 0
    for wb, f, wa, g in _paired(orig[2], ours[2], lag):
        if wb[f - 2] == wb[f] & 0xFE:
            assert wb[f - 1] == wb[f - 2], (f, wb[f - 2:f + 1])
            unchanged += 1
        else:
            assert wb[f - 1] != wb[f - 2], (f, wb[f - 2:f + 1])
            changed += 1
    assert changed > 0 and unchanged > changed, (changed, unchanged)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_gate_on_latching_byte_opens_the_gate_on_the_stale_pitch():
    """`$FF` latches the waveform but opens the gate on the frequency the voice
    still holds: voice 2's program starts a frame before the pitch frame on
    almost every attack, the `no_test_restart` defect."""
    orig, ours, lag = _measure(0xFF)
    early = total = 0
    for wb, f, wa, g in _paired(orig[1], ours[1], lag):
        total += 1
        early += _program_start(wb, f) == -1
    assert total > 50 and early >= 0.8 * total, (early, total)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_gate_off_latching_byte_never_opens_the_gate():
    """`$FE` latches the waveform with the gate off, and the wavetable's gated
    waveform is masked by it: no attack at all."""
    orig, ours, lag = _measure(0xFE)
    assert sum(len(v.attack_frames) for v in ours) == 0
    assert all(len(v.attack_frames) > 20 for v in orig)


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("byte", [0x08, 0x18])
def test_a_fixed_testbit_byte_moves_the_select_on_every_voice(byte):
    """`$08` / `$18` are silent, gate clear, and a single constant: the select
    moves on the init frame on (nearly) every attack of voices 2 and 3, where
    the record's own byte moves it on none of voice 2's."""
    orig, ours, lag = _measure(byte)
    for v in (1, 2):
        moved = total = 0
        for wb, f, wa, g in _paired(orig[v], ours[v], lag):
            total += 1
            moved += wb[f - 1] != wb[f - 2]
        assert total > 50 and moved >= 0.9 * total, (v, moved, total)
