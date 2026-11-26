"""Bangkok_Knights carries `tie_late_pitch` in its presets entry.

Voice 0's one-row note tied into the next (A-3 then A#3, a semitone, at a 3-call
row) steps the pitch at attack+3 in the original and attack+2 in ours without
the option (the same mechanism as Gremlins, `tests/test_tie_late_pitch.py`).
`fidelity.within_note_travel` skips a step within two frames of a gate rise, so
ours read 0 against the original's 2153 (travel 0.00x). With the option the
four audible steps (964 units) land on the original's frame: our travel 966.
Task listen-sub99-bangkok-knights, -t 180, v0.5.674.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus import CORPUS                              # noqa: E402
from fidelity import _preset_opts                      # noqa: E402
from h2g.convert import convert                        # noqa: E402

NUL = lambda *a, **k: None                             # noqa: E731
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"
NAME = "Bangkok_Knights.sid"
KEEP = 0x80                                            # "no note change"


def _doc():
    return json.loads(PRESETS.read_text())


def test_the_presets_entry_sets_tie_late_pitch():
    assert _doc()["songs"][NAME].get("tie_late_pitch") is True


def test_the_option_moves_only_the_keep_bytes_of_the_plain_records():
    sid = os.path.join(CORPUS, NAME)
    if not os.path.exists(sid):
        pytest.skip(f"corpus file not present: {NAME}")
    opts = _preset_opts(_doc(), NAME)
    assert opts["tie_late_pitch"] is True
    on = convert(sid, log=NUL, **opts)
    off = convert(sid, log=NUL, **{**opts, "tie_late_pitch": False})
    assert len(on) == len(off)
    moved = [(a, b) for a, b in zip(off, on) if a != b]
    assert moved, "tie_late_pitch changed no byte: the entry is inert"
    assert all(a == 0 and b == KEEP for a, b in moved), moved
    assert len(moved) == 3, len(moved)
