"""Four pulse-engine spellings detect.py did not read.

Each of Mozart, Commodore_64_Music_Examples, Mega_Apocalypse and Chicken_Song
carries a pulse engine the converter already reads elsewhere, in a spelling
its signature did not match, so `_pulse_program` fell to the static width and
the file's pulse changes sat at 1-5% of the original's:

* Mozart $0A79 -- PULSE_TRI_SHAPE's routine with the masks `AND #$0F` /
  `AND #$F0` instead of `$1F` / `$E0` (PULSE_TRI_MASKS_SHAPE);
* Commodore_64_Music_Examples $12CC -- the same with an extra
  `STA scratch` between the delay mask and `DEC counter,X`
  (PULSE_TRI_STA_SHAPE), which moves every operand after it by three;
* Mega_Apocalypse $4CD1 -- PULSE_PROG_SHAPE with `DEC/LDY/STA` spelled
  zero-page (PULSE_PROG_ZP_SHAPE);
* Chicken_Song $12A3 -- PULSE_TRI_CMD_SHAPE whose per-voice turnaround cells
  disagree (voices 1-2 turn between nibbles 8 and F, voice 3 between 1 and
  4): the record's bounds are chosen by the voice that sounds it.

Every new spelling is a fallback: it is consulted only where the older shapes
matched nothing, and the corpus census below pins the exact files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import (PULSE_PROG_SHAPE, PULSE_PROG_ZP_SHAPE,  # noqa: E402
                        PULSE_TRI_CMD_SHAPE, PULSE_TRI_MASKS_SHAPE,
                        PULSE_TRI_SHAPE, PULSE_TRI_STA_SHAPE,
                        _find_pulse_tri_cmd, _find_pulse_tri_cmd_voices,
                        _find_pulse_tri_variant, detect, pulse_tri_offset,
                        pulse_tri_shift)
from h2g.goatwriter import _pulse_tri_program, triangle_start  # noqa: E402
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

MOZART = "Mozart.sid"
COMMODORE = "Commodore_64_Music_Examples.sid"
MEGA = "Mega_Apocalypse.sid"
CHICKEN = "Chicken_Song.sid"


def _quiet(*_a, **_k):
    pass


def _multiplier(name):
    import json
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    return doc["songs"][name].get("multiplier", 1)


def _read(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, _quiet)


# --- detection, on the corpus -------------------------------------------------

@needs_corpus
def test_mozart_reads_the_triangle_under_its_own_masks():
    sid, det = _read(MOZART)
    assert search_file(sid.data, PULSE_TRI_SHAPE) < 0
    assert search_file(sid.data, PULSE_TRI_MASKS_SHAPE) >= 0
    assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0E)
    assert (det.pulse_tri_step_mask, det.pulse_tri_delay_mask) == (0xF0, 0x0F)
    assert det.pulse_tri_gated and not det.pulse_tri_per_voice
    assert det.pulse_tri_step_shift == 0
    # A Mozart sweeping record: instrument 0, rate $80 -> step $80 a call.
    program = _pulse_tri_program(sid, det, 0, _multiplier(MOZART))
    assert program is not None


@needs_corpus
def test_commodore_reads_the_triangle_across_its_extra_store():
    sid, det = _read(COMMODORE)
    assert search_file(sid.data, PULSE_TRI_SHAPE) < 0
    assert search_file(sid.data, PULSE_TRI_MASKS_SHAPE) < 0
    assert search_file(sid.data, PULSE_TRI_STA_SHAPE) >= 0
    assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0E)
    assert (det.pulse_tri_step_mask, det.pulse_tri_delay_mask) == (0xE0, 0x1F)
    assert not det.pulse_tri_gated and not det.pulse_tri_per_voice


@needs_corpus
def test_the_extra_store_moves_the_phase_offsets_and_they_follow():
    """`pulse_tri_shift` is 3 across the extra `STA`, 0 elsewhere, and
    `triangle_start` -- which reads the counter and direction cells by
    `_TRI_COUNTER` / `_TRI_DIR` + the shift -- finds Commodore's start state
    ($1425 is the scratch cell, $142D the counter): without the shift it
    would read the `DEC`'s own bytes and decline."""
    sid, det = _read(COMMODORE)
    off = pulse_tri_offset(sid, det)
    assert off >= 0 and pulse_tri_shift(sid, off) == 3
    d = sid.data
    # DEC counter,X is three bytes above the AND, and its operand is $142D.
    assert d[off + 5] == 0xDE and d[off + 6:off + 8] == bytes([0x2D, 0x14])
    start = triangle_start(sid, det, lead=0)
    assert start is not None
    assert start.cells == ((1, 0), (1, 0), (-1, 0))
    assert start.instruments == (1, 8, 6)
    # The other two: no shift.
    for name in (MOZART, "Commando.sid"):
        s, dt = _read(name)
        o = pulse_tri_offset(s, dt)
        assert o >= 0 and pulse_tri_shift(s, o) == 0, name


@needs_corpus
def test_mega_apocalypse_reads_the_zero_page_pulse_program():
    sid, det = _read(MEGA)
    assert search_file(sid.data, PULSE_PROG_SHAPE) < 0
    assert search_file(sid.data, PULSE_PROG_ZP_SHAPE) >= 0
    assert det.pulse_prog_count == 14
    assert sid.to_address(det.pulse_prog_table) == 0x5250
    assert det.pulse_tri_hi < 0 and det.pulse_bounds < 0


@needs_corpus
def test_chicken_song_keeps_per_voice_bounds_and_the_uniform_reading_declines():
    sid, det = _read(CHICKEN)
    assert search_file(sid.data, PULSE_TRI_CMD_SHAPE) >= 0
    # The uniform reading still declines (voice 3's cells hold $01/$04) ...
    assert _find_pulse_tri_cmd(sid, det) is None
    # ... and the per-voice one reads them.
    read = _find_pulse_tri_cmd_voices(sid, det)
    assert read is not None
    assert read[1] == ((8, 15), (8, 15), (1, 4))
    assert det.pulse_tri_voice_bounds == ((8, 15), (8, 15), (1, 4))
    assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 15)
    assert det.pulse_tri_per_voice and det.pulse_tri_step_shift == 1


# --- fallback discipline, on the whole corpus ---------------------------------

@needs_corpus
def test_each_fallback_reads_exactly_its_files_and_never_a_literal_match():
    tri_variant, prog_zp, voices = set(), set(), set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, _quiet)
        literal = search_file(sid.data, PULSE_TRI_SHAPE) >= 0
        if literal:
            # A rescue never disturbs a file the primary shape reads.
            assert _find_pulse_tri_variant(sid, det) is None, path.name
        elif _find_pulse_tri_variant(sid, det) is not None:
            tri_variant.add(path.name)
        if search_file(sid.data, PULSE_PROG_SHAPE) >= 0:
            assert search_file(sid.data, PULSE_PROG_ZP_SHAPE) < 0, path.name
        elif det.pulse_prog_table >= 0:
            prog_zp.add(path.name)
        if det.pulse_tri_voice_bounds:
            voices.add(path.name)
    assert tri_variant == {MOZART, COMMODORE}
    assert prog_zp == {MEGA}
    assert voices == {CHICKEN}


# --- Chicken_Song's per-voice bound choice ------------------------------------

def _det(voice_bounds, lo=8, hi=15):
    from h2g.detect import Detection
    det = Detection()
    det.pulse_tri_lo, det.pulse_tri_hi = lo, hi
    det.pulse_tri_voice_bounds = voice_bounds
    return det


def _pattern(instr):
    """One note row on instrument byte `instr`, then the end marker."""
    return [0x60, instr, 0, 0, 0xFF, 0, 0, 0]


NOTE_FIRST, NOTE_LAST = 0x60, 0xBC


def test_a_record_turns_where_the_voice_that_sounds_it_does():
    """Three voices, lead 0 (instrument byte = record + 1): record 0 on
    voices 0 and 1, record 1 on voice 2 only, record 2 on voices 0 and 2 with
    more rows on voice 2."""
    voice_bounds = ((8, 15), (8, 15), (1, 4))
    patterns = [_pattern(1), _pattern(2), _pattern(3)]
    # One orderlist per voice: pattern numbers.
    tracks = [[0, 2], [0], [1, 2, 2]]
    det = _det(voice_bounds)
    det.set_tri_record_bounds(tracks, patterns, 0, NOTE_FIRST, NOTE_LAST)
    # record 1 (voice 2 only) turns at 1..4; record 0 (voices 0, 1) is the
    # engine's own pair and is not entered; record 2 is sounded once by
    # voice 0 and twice by voice 2.
    assert det.pulse_tri_record_bounds == {1: (1, 4), 2: (1, 4)}
    assert det.tri_bounds(0) == (8, 15)
    assert det.tri_bounds(1) == (1, 4)
    assert det.tri_bounds(7) == (8, 15)


def test_a_tie_between_voices_goes_to_the_lowest_voice():
    voice_bounds = ((8, 15), (8, 15), (1, 4))
    patterns = [_pattern(1)]
    det = _det(voice_bounds)
    det.set_tri_record_bounds([[0], [], [0]], patterns, 0, NOTE_FIRST,
                              NOTE_LAST)
    assert det.pulse_tri_record_bounds == {}


def test_a_uniform_engine_sets_no_record_bounds_and_the_map_is_cleared():
    det = _det(())
    det.pulse_tri_record_bounds = {3: (1, 4)}
    det.set_tri_record_bounds([[0], [0], [0]], [_pattern(1)], 0, NOTE_FIRST,
                              NOTE_LAST)
    assert det.pulse_tri_record_bounds == {}


@needs_corpus
def test_the_record_bounds_reach_the_program_the_record_is_laid_out_with():
    """A voice-3 record sweeps between nibbles 1 and 4, not 8 and F."""
    sid, det = _read(CHICKEN)
    base = _pulse_tri_program(sid, det, 2, 1)
    assert base is not None
    det.pulse_tri_record_bounds = {2: (1, 4)}
    voice3 = _pulse_tri_program(sid, det, 2, 1)
    assert voice3 is not None
    assert voice3 != base
    assert voice3[0] != base[0]


@needs_corpus
def test_convert_chicken_song_applies_the_voice_bounds():
    """End to end: with the per-voice bounds blanked the conversion differs
    from the shipped one, so `build_sng` does hand the patterns over."""
    import json
    import fidelity
    import h2g.convert as convert_mod
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, CHICKEN)
    shipped = convert_mod.convert(str(CORPUS / CHICKEN), log=_quiet, **opts)

    real = convert_mod.detect

    def blanked(sid, log, engine=0):
        d = real(sid, log, engine)
        d.pulse_tri_voice_bounds = ()
        return d
    convert_mod.detect = blanked
    try:
        flat = convert_mod.convert(str(CORPUS / CHICKEN), log=_quiet, **opts)
    finally:
        convert_mod.detect = real
    assert shipped != flat
