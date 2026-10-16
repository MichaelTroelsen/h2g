"""Thrust record 18 ($0A0A, -S3): the "dropped" attacks are not dropped.

At one sample per frame (`run_siddump(calls=3)`) voice 2 shows 529 attacks in
ours against 559 in the original, and 30 of the 45 original `$0A0A` notes in
the first 240 s have no attack within the pairing window (the nearest forward
one lags 16 = 3 + 13, the next note's). Read at one sample per PLAY CALL
(`calls=1` on the packed song: every call is a row) ours has all 559.

Cause: `goatwriter.arpeggio.gateoff_nibble_arp_entries` opens the record
with `[attack, tail]`, so the gate is high for ONE play call -- a third of a
frame at -S3 -- where the original's is one frame. siddump reads the SID once
per frame, after the frame's last call, so it sees the pulse only when the
note starts on that call. Thrust's tempo is 10 calls a row and 10 mod 3 = 1,
so the start call rotates with the row: visible exactly for rows = 1 mod 3
(pattern $22 rows 4, 16, 28, 34, 40: ours 3432, 3472, 3512, 3532, 3552).
Kentilla (-S10, tempo a multiple of the frame) is phase-locked and shows
every attack.

The test pins the finding: ours attacks as often as the original when every
call is read, and the frame-rate reading never exceeds it.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from test_arp_octave import (_converted, needs_gt2reloc,    # noqa: E402
                             needs_siddump)

SECONDS = 100          # frame 3416, the first $0A0A note, is at 68 s
VOICE = 2


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_thrust_voice_2_attacks_every_note_when_every_call_is_read(tmp_path):
    presets = PYTHON_ROOT.parent / "presets.json"
    if not presets.exists():
        pytest.skip("presets.json not present")
    doc = json.loads(presets.read_text())
    m = fidelity._preset_multiplier(doc, "Thrust.sid")
    assert m == 3
    sng, _t, _p = _converted("Thrust")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / "Thrust.sid", SECONDS, 0, calls=1)
    per_frame = fidelity.run_siddump(packed, SECONDS, 0, calls=m)
    # calls=1 makes every play call a row: m rows to the original's frame.
    per_call = fidelity.run_siddump(packed, SECONDS * m, 0, calls=1)

    n_orig = sum(1 for f in orig[VOICE].attack_frames if f < SECONDS * 50)
    n_call = sum(1 for f in per_call[VOICE].attack_frames
                 if f < SECONDS * 50 * m)
    n_frame = sum(1 for f in per_frame[VOICE].attack_frames
                  if f < SECONDS * 50)
    assert n_orig > 100, n_orig                      # the window has notes
    assert n_call == n_orig, (n_call, n_orig)        # none are dropped
    assert n_frame <= n_call, (n_frame, n_call)

    # And each lands a few frames after the original's (9-11 calls at 240 s).
    import bisect
    at = per_call[VOICE].attack_frames
    for f in orig[VOICE].attack_frames:
        if f >= SECONDS * 50:
            break
        i = bisect.bisect_left(at, f * m)
        assert i < len(at) and at[i] - f * m < 8 * m, f
