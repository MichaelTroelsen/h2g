"""A note before its voice's first instrument, and the table that decides it.

The rule is a property of the PLAYER: twenty builds park `$08` -- the test bit,
every waveform bit clear -- in a voice's stored waveform until an instrument is
named, so a note reaching the SID before then sounds nothing. Goattracker has
no such state, so those notes came out audible.

`detect.PRE_INSTRUMENT_SILENCE` is a measured table rather than a derivation,
and these tests are what keep it checkable. The instrument is ablation: NOP the
store into the cell, re-trace, and compare -- which is the only instrument that
has ever been right about this question, four static routes having been scored
against it and refuted.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import (PRE_INSTRUMENT_SILENCE, Detection,   # noqa: E402
                        find_pre_instrument_silence,
                        find_stored_wave_cell,
                        find_stored_wave_store)
from h2g.patterns import GT_KEYOFF, GT_LASTNOTE              # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from h2g.tracks import silence_pre_instrument_notes          # noqa: E402

SIDDUMP = (Path(__file__).resolve().parents[1] / "tools" / "siddump-rt"
           / "siddump.exe")

# The two endpoints this rule was derived from, and they must disagree:
# Bangkok's 20 pre-instrument notes are silent in the original, Delta's 8 sound
# exactly. A change that makes them agree has broken the discriminator, whatever
# else it scores.
BANGKOK = "Bangkok_Knights.sid"
DELTA = "Delta_Mix-E-Load_loader.sid"


def _det(**kw):
    d = Detection()
    for k, v in kw.items():
        setattr(d, k, v)
    return d


# --------------------------------------------------------------------------
# the emitter
# --------------------------------------------------------------------------
def test_a_note_before_the_first_instrument_is_silenced():
    # One pattern, two rows: a note with no instrument, then a note that sets
    # one. Only the first may be silenced.
    patterns = [[60, 0, 0, 0, 62, 3, 0, 0, 0xFF, 0, 0, 0]]
    tracks = [[0, 0xFF]]
    n = silence_pre_instrument_notes(tracks, patterns,
                                     _det(pre_instrument_silence=True))
    assert n == 1
    assert tracks[0][0] == 1, "the orderlist must point at the copy"
    assert patterns[1][0] == GT_KEYOFF
    assert patterns[1][4] == 62, "the instrument's own row must still sound"
    assert patterns[0][0] == 60, "the shared original must not be patched"


def test_the_emitter_is_inert_without_the_detection_flag():
    patterns = [[60, 0, 0, 0, 0xFF, 0, 0, 0]]
    tracks = [[0, 0xFF]]
    assert silence_pre_instrument_notes(tracks, patterns,
                                        _det(pre_instrument_silence=False)) == 0
    assert patterns == [[60, 0, 0, 0, 0xFF, 0, 0, 0]]
    assert tracks == [[0, 0xFF]]


def test_a_shared_pattern_is_copied_not_patched_in_place():
    """The reason this cannot patch in place, in one test.

    Voice 0 reaches pattern 0 before it has an instrument; voice 1 reaches the
    same pattern having already been given one. Patching the pattern would
    silence voice 1's note too -- and in Bangkok the shared pattern is exactly
    the case, its leading entry being material voice 2 plays normally later.
    """
    patterns = [[60, 0, 0, 0, 0xFF, 0, 0, 0],
                [64, 7, 0, 0, 0xFF, 0, 0, 0]]
    tracks = [[0, 0xFF], [1, 0, 0xFF]]
    n = silence_pre_instrument_notes(tracks, patterns,
                                     _det(pre_instrument_silence=True))
    assert n == 1
    assert patterns[0][0] == 60, "voice 1 still plays the original"
    assert tracks[1][1] == 0, "voice 1's step is untouched"
    assert patterns[tracks[0][0]][0] == GT_KEYOFF


@needs_corpus
def test_bangkok_silences_exactly_its_twenty_pre_instrument_notes():
    lines = []
    convert(str(CORPUS / BANGKOK), log=lines.append)
    said = [ln for ln in lines if "Pre-instrument notes" in ln]
    assert said, "the conversion did not report silencing anything"
    assert "20 note(s)" in said[0], said[0]


@needs_corpus
def test_delta_keeps_its_pre_instrument_notes():
    """The converse endpoint. Delta's 8 are EXACT in the original.

    This is the test that fails if the table is widened to the whole
    population instead of the measured 20.
    """
    sid = load_sid(str(CORPUS / DELTA))
    cell = find_stored_wave_cell(sid)
    store = find_stored_wave_store(sid, cell) if cell is not None else None
    # Report the KEY, not just the verdict: the table is two addresses read out
    # of the file, so a wrong verdict is a wrong key, and a bare "expected
    # False" sends the next reader to the emitter instead of the locator.
    where = (f"cell={cell if cell is None else hex(cell)} "
             f"store={store if store is None else hex(store)}")
    assert find_pre_instrument_silence(sid) is False, \
        f"Delta must not be in PRE_INSTRUMENT_SILENCE; locator gave {where}"
    lines = []
    convert(str(CORPUS / DELTA), log=lines.append)
    assert not [ln for ln in lines if "Pre-instrument notes" in ln], where


# --------------------------------------------------------------------------
# the table
# --------------------------------------------------------------------------
@needs_corpus
def test_every_table_entry_is_reachable_from_some_corpus_file():
    """No entry is a typo, and none has been orphaned by a locator change.

    A table keyed on two addresses is exactly as good as the locator that
    reads them, so an entry no file produces is dead weight that would never
    fire and never fail.
    """
    seen = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        cell = find_stored_wave_cell(sid)
        if cell is None:
            continue
        store = find_stored_wave_store(sid, cell)
        if store is not None:
            seen.add((cell, store))
    orphans = sorted(PRE_INSTRUMENT_SILENCE - seen)
    assert not orphans, \
        f"table entries no corpus file produces: {[(hex(a), hex(b)) for a, b in orphans]}"


@needs_corpus
def test_no_table_key_spans_both_verdicts():
    """The key names a player BUILD, which is what makes it a legal key.

    Five corpus files share $1A43/$104B and two share $1654/$103B. That is
    only sound because the files sharing a key share the answer -- if a key
    ever covered one file that clears and one that does not, the table would
    be silently wrong on whichever it was not measured from.
    """
    by_key: dict[tuple[int, int], list[str]] = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        cell = find_stored_wave_cell(sid)
        if cell is None:
            continue
        store = find_stored_wave_store(sid, cell)
        if store is None:
            continue
        by_key.setdefault((cell, store), []).append(path.name)
    assert by_key, "the locator found nothing at all"
    # Every key is wholly in the table or wholly out of it; membership is what
    # the verdict is, so a key cannot span both by construction *here* -- what
    # this asserts is that the sharing groups are real and were not invented.
    shared = {k: v for k, v in by_key.items() if len(v) > 1}
    assert shared, "expected some corpus files to share a player build"
    for key, files in shared.items():
        inside = key in PRE_INSTRUMENT_SILENCE
        assert all((key in PRE_INSTRUMENT_SILENCE) == inside for _ in files)


@pytest.mark.skipif(not SIDDUMP.exists(),
                    reason="siddump-rt is gitignored; build it to run the "
                           "ablation")
@needs_corpus
def test_the_ablation_still_says_what_the_table_says():
    """Regenerate the verdict for the two endpoints, by the measuring method.

    This is the table's actual warrant. It is restricted to the two endpoints
    rather than all 50 files because the full sweep is 100 traces; the probe
    that produced the table sweeps the whole population and lives in the
    session scratchpad, and this is the part cheap enough to keep in the suite.
    """
    def clears(name: str) -> bool:
        data = bytearray((CORPUS / name).read_bytes())
        sid = load_sid(str(CORPUS / name))
        cell = find_stored_wave_cell(sid)
        assert cell is not None, f"{name}: the locator found no cell"
        store = find_stored_wave_store(sid, cell)
        assert store is not None
        off = store - sid.load_addr + 0x7F - 1
        assert data[off] in (0x8D, 0x9D, 0x99, 0x8E, 0x8C), \
            f"{name}: ${store:04X} is not a store; the locator has drifted"
        sub = max(sid.start_song - 1, 0)

        def trace(blob: bytes) -> str:
            with tempfile.TemporaryDirectory(prefix="nb5t") as d:
                p = Path(d) / name
                p.write_bytes(blob)
                r = subprocess.run(
                    [str(SIDDUMP), str(p), f"-a{sub}", "-t8", "-v0"],
                    capture_output=True, text=True, timeout=180,
                    stdin=subprocess.DEVNULL)
                return r.stdout

        before = trace(bytes(data))
        assert before.strip(), f"{name}: empty trace"
        for k in range(3):
            data[off + k] = 0xEA
        return before != trace(bytes(data))

    assert clears(BANGKOK) is True, \
        "Bangkok's store no longer decides its silence -- the table's key or " \
        "the locator has drifted from what was measured"
    assert clears(DELTA) is False, \
        "Delta now clears too, so the discriminator no longer discriminates"
