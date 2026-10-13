"""An UNTIED landing on a gate-clear record closes its gate one tick late.

The `$40` legato bit on a gate-clear record's instrument
(`instruments._write_instruments(gate_clear_firstwave=)`) is exact for the
landings Chimera has -- every one follows a wait-0 event, so the player has not
closed the gate and the record's own fetch does. It is a property of the
RECORD, so a landing that follows a note with `wait > 0` gets it too, and
there the original has ALREADY shut the gate on the predecessor's hold path
(`LDA counter,X / BNE` -> `AND #$FE / STA $D404`), one Hubbard tick (3 frames
at Chimera's speed) before the record's fetch.

This file measures that on a SYNTHETIC untied landing, both sides through
siddump (`tests/test_gate_clear_record.py` holds the tied reading it
leaves alone). Chimera's pattern `$19` is

    80 07 3d | 00 40 | 00 41 | 00 43 | 00 45 | 80 08 49 | ff
    rec 7 attack, four wait-0 ties, then the record-8 landing

(file offset `$3052`). Rewritten in place as

    80 07 3d | 00 40 | 00 41 | 81 0a 43 | 80 08 49 | ff | ff

the same 6 ticks long, the record-8 landing now follows a wait-1 note on
record 10 (waveform `$11`, effect `$02`: no drum, which a wait > 0 note on
record 7 would run and which would shut the gate with `$80`, not `$10`).

The measurement: for every write of record 8's envelope (`$BF05`, the fetch),
how many frames the gate had already been clear -- the LEAD.

| landing                   | original | shipped (legato) | without the bit |
|---------------------------|----------|------------------|-----------------|
| tied (wait-0 predecessor) | 0        | 0                | 2 (early)       |
| untied (wait-1 predecessor) | 3      | 0 (3 frames late)| 2 (1 frame late)|

Measured 2026-10-13 at 8618f82, presets, 180 s, subtune 0, voice 1, 26
occurrences of each landing. The "without the bit" column comes from deleting
`gatetimer |= GATETIMER_LEGATO` in a scratch copy; it is why the bit stays
(the tied landings are the whole corpus) and why a per-landing choice would
win only 2 of the 3 frames. NOTHING IN THE CORPUS HAS AN UNTIED LANDING
(Chimera's four record-8 events all follow a wait-0 event; no other file
decodes a pattern event on a gate-clear instrument record), so this is a
declined limitation, not a defect with a file behind it. The first test pins
the lag so that a fix has to change it on purpose: when untied landings
are split off (a per-landing clone, the `tie_restart` machinery), change the
expected `ours` to equal `orig`.
"""

import json
import pathlib
import sys
from collections import Counter

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

PATTERN_AT = 0x3059
BEFORE = bytes.fromhex("00 43 00 45 80 08 49 ff")
# Event 3 becomes record 10 with wait 1; the terminator moves up one byte.
AFTER = bytes.fromhex("81 0a 43 80 08 49 ff ff")

RECORD_8_ENVELOPE = 0xBF05
SECONDS, FRAMES = 180, 180 * 50


def _chimera(path, patched):
    raw = bytearray((CORPUS / "Chimera.sid").read_bytes())
    if patched:
        assert bytes(raw[PATTERN_AT:PATTERN_AT + len(BEFORE)]) == BEFORE
        raw[PATTERN_AT:PATTERN_AT + len(AFTER)] = AFTER
    path.write_bytes(bytes(raw))
    return path


def _leads(voice):
    """Frames the gate had been clear at each write of record 8's envelope."""
    wf = fidelity.register_timeline(voice.wf_events, FRAMES)
    out = []
    for frame, value in voice.adsr_events:
        if value != RECORD_8_ENVELOPE or frame >= FRAMES:
            continue
        assert not wf[frame] & 1, (frame, wf[frame])
        start = frame
        while start > 0 and not wf[start - 1] & 1:
            start -= 1
        out.append(frame - start)
    return Counter(out)


def _both_sides(tmp_path, patched):
    import h2g.convert as C
    sid = _chimera(tmp_path / ("untied.sid" if patched else "tied.sid"),
                   patched)
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Chimera.sid")
    orig = fidelity.run_siddump(sid, SECONDS, 0, calls=1)
    packed = fidelity.pack_sid(
        C.convert(str(sid), log=lambda m: None, **opts), tmp_path)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, SECONDS, 0, calls=1)
    return _leads(orig[1]), _leads(ours[1])


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_control_tied_landings_close_on_the_fetch_in_both(tmp_path):
    orig, ours = _both_sides(tmp_path, patched=False)
    assert sum(orig.values()) >= 40, orig
    assert orig == {0: sum(orig.values())}
    assert ours == orig


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_an_untied_landing_closes_one_tick_after_the_original(tmp_path):
    orig, ours = _both_sides(tmp_path, patched=True)
    n = orig[3]
    assert n >= 20, orig
    # Half the landings are the patched pattern's (untied: the original
    # closed three frames before the fetch), half the unpatched pattern's
    # (still tied: closed by the fetch itself).
    assert orig == {3: n, 0: n}, orig
    # Ours closes on the fetch for BOTH: the untied half is three frames
    # late. A fix changes this line to `ours == orig`.
    assert ours == {0: 2 * n}, ours
