"""The ticked nibble record's noise tick is two WHOLE frames of calls at -S10.

`tl` (`[noise, delay]`) holds the tick in one delay entry, and a delay spends
at most `WAVE_MAX_DELAY + 1` = 16 calls, so the tick length read off it was 17
calls at -S10 where two frames are 20. `ticked_nibble_arp_entries` unrolls the
tick into runs with no such cap, so it takes the real length.

International_Karate (-S10): its row clock puts a note's first call at call
phase 0, 2, 4, 6 or 8 of a frame, and a 17-call noise starting at the call 11
after that reaches the SECOND frame's end only from phase 2 on. At phase 0 the
sampled register reads the noise once: 112 of its 378 plain unit-3 drum notes
read one noise frame where the original (traced at -m1) has two on all 445.
Two frames of calls (20) cover exactly two frame ends from every phase.

Measured at 3503f19 (task listen-r2-international-karate, -t 180, presets,
--sound): International_Karate wave .9910 -> .9959, heard wave-mismatching
notes 151 -> 24, instr .755 -> .854; the corpus byte-hash moves
International_Karate and Kentilla only, and Kentilla's printed columns do not
move.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import wavetable                         # noqa: E402
from songview import parse_sng                                # noqa: E402
from test_drum_held_gate3 import _run                         # noqa: E402

KARATE = CORPUS / "International_Karate.sid"
PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
needs_presets = pytest.mark.skipif(not PRESETS.exists(),
                                   reason="presets.json absent")
FRAME = 10


def _program():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, KARATE.name)
    sng = convert(str(KARATE), log=lambda m: None, **opts)
    song = parse_sng(sng[0] if isinstance(sng, tuple) else sng)
    # Instrument 1 (`02:00-20-55`): a drum + nibble-arpeggio record.
    return list(song.tables["WTBL"]), song.instruments[0].wave_ptr - 1


def _noise_calls(rows, at):
    regs = [r for r, _ in _run(rows, 6 * FRAME, at=at)]
    start = next(i for i, r in enumerate(regs) if r & 0x80)
    end = next(i for i in range(start, len(regs)) if not regs[i] & 0x80)
    assert not any(r & 0x80 for r in regs[end:end + 12])
    return start, end


def _frames_read(start, end, phase):
    """Frame ends (the last call of a frame, where siddump samples) inside the
    noise window, for a note whose first call is call `phase` of its frame."""
    return sum(1 for c in range(start, end) if (phase + c) % FRAME == FRAME - 1)


@needs_corpus
@needs_presets
def test_the_tick_is_two_whole_frames_of_calls_and_reads_two_at_every_phase():
    """SABOTAGE TARGET: `wavetable._TICK_UNCAP_NIBBLE = False` (the tick length
    back to what one delay entry holds) leaves 17 calls and one frame read
    from phase 0."""
    rows, at = _program()
    start, end = _noise_calls(rows, at)
    assert end - start == 2 * FRAME
    for phase in range(FRAME):
        assert _frames_read(start, end, phase) == 2, phase


@needs_corpus
@needs_presets
def test_the_capped_tick_read_one_frame_from_the_phase_the_clock_gives(monkeypatch):
    monkeypatch.setattr(wavetable, "_TICK_UNCAP_NIBBLE", False)
    rows, at = _program()
    start, end = _noise_calls(rows, at)
    assert end - start == 17
    assert [_frames_read(start, end, p) for p in range(0, FRAME, 2)] == \
        [1, 2, 2, 2, 2]
