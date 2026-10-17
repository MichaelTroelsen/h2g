"""A voice parked on the silent pattern stops sweeping its pulse width.

`tracks.SILENT_PATTERN` used to be a bare KEYOFF row. KEYOFF closes the gate
and nothing else: the voice's pulse program (`cptr->ptr[PTBL]`) keeps stepping
(gplay.c runs the pulse step whenever the pointer is non-zero), so after the
tune "ended" every parked voice swept its width on every frame for the rest of
the trace. Kings_of_the_Beach_ingame subtune 4, packed under presets at -S3
and traced for 90 s: 4495 pulse changes per voice against the original's 343.
The original's player halts with the tune -- its last pulse write is the frame
before its final waveform-0 write -- so the sweep stops there.

The row now also carries CMD_SETPULSEPTR 0 (`case CMD_SETPULSEPTR:
cptr->ptr[PTBL] = param`), which switches the pulse step off. Same trace after:
346 pulse changes on each voice against the original's 343 (the command sits
one row after the KEYOFF, so the stop lands one row later).
"""
import json
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import patterns as P                                # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.tracks import SILENT_PATTERN                        # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAME = "Kings_of_the_Beach_ingame.sid"
SUBTUNE = 4
SECONDS = 30
# The original's pulse writes end at frame 343 (waveform 0 at 345); ours runs
# the startup lag (4 frames) later. Anything past this is the parked voice
# still sweeping.
LAST_PULSE_FRAME = 360

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def test_the_silent_pattern_clears_the_pulse_pointer_after_its_keyoff():
    assert SILENT_PATTERN[:4] == [P.GT_KEYOFF, 0, 0, 0], (
        "the KEYOFF row's command column stays free for the filter fetch hold")
    note, instr, cmd, data = SILENT_PATTERN[4:8]
    assert note == P.GT_NO_NOTE and instr == 0, "instr 00 keeps the instrument"
    assert cmd == P.CMD_SETPULSEPTR == 9
    assert data == 0, "pointer 0 is 'no pulse program'"
    assert SILENT_PATTERN[8] == P.GT_END_PATTERN


def test_the_filter_fetch_hold_still_finds_the_keyoff_rows_column():
    """Sigma_Seven voice 0: with CMD_SETPULSEPTR on the KEYOFF row itself the
    hold had 'no free row' (tests/test_free_running_holds.py)."""
    from h2g.goatwriter.filters import _fetch_hold_pattern
    writes, skips, _i, _r = _fetch_hold_pattern(
        list(SILENT_PATTERN), 1, 0, {1: 7}, 4)
    assert writes == frozenset({(0, 7)}) and not skips


def _preset_opts():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, NAME), doc["songs"][NAME].get("multiplier", 1)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_a_parked_voice_makes_no_pulse_change_after_the_tune_ends(tmp_path):
    src = CORPUS / NAME
    if not src.exists():
        pytest.skip("Kings_of_the_Beach_ingame.sid not in the corpus")
    opts, mult = _preset_opts()
    blob, _ = fidelity.legalise_restarts(
        convert(str(src), log=lambda *_: None, **opts))
    packed = fidelity.pack_sid(blob, tmp_path, fidelity.GT2RELOC, mult)
    assert packed is not None
    voices = fidelity.run_siddump(packed, SECONDS, SUBTUNE, fidelity.SIDDUMP,
                                  calls=mult)
    assert len(voices) == 3
    for v, tr in enumerate(voices):
        frames = [f for f, _ in tr.pulse_events]
        assert frames, f"voice {v}: no pulse event at all"
        assert max(frames) <= LAST_PULSE_FRAME, (
            f"voice {v}: pulse still changing at frame {max(frames)}")
        # And it did sweep while the tune played.
        assert len(frames) > 100, (v, len(frames))
