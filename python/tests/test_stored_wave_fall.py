"""Chicken Song's bit $01 -- a stored-waveform frequency fall, not a drum.

`$133B` lowers the voice's frequency high byte `$0100` a call from call 3 of
the note and writes the record's stored waveform to `$D404`. The Warhawk drum
guards match it, which is why `detect._find_effect_routines` demands `LDA
#$80` in the block; `_find_stored_wave_fall` is the block read for what it is.
"""
from pathlib import Path

import pytest

from h2g.detect import detect
from h2g.goatwriter import _wave_alternate_entries
from h2g.goatwriter.stored_fall import stored_fall_offsets
from h2g.sidfile import load_sid

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
CHICKEN = CORPUS / "Chicken_Song.sid"

# The original's own siddump note column for voice 2, calls 4-11 of an A#3
# (`0E82 (A-3 AD)` ... `0782 (A-2 A1)`), as semitones below the note AE.
SIDDUMP_DOWN = (1, 2, 4, 5, 7, 8, 10, 13)


@pytest.fixture(scope="module")
def chicken():
    if not CHICKEN.exists():
        pytest.skip("corpus not present")
    sid = load_sid(str(CHICKEN))
    return sid, detect(sid, log=lambda m: None)


def test_the_block_is_read_and_is_not_a_drum(chicken):
    _sid, det = chicken
    assert det.stored_wave_fall is not None
    assert det.stored_wave_fall.first_call == 3     # SBC #$03 at $1350
    assert not det.effect_drum and det.drum_fall_step == 0


def test_the_fall_follows_the_originals_note_column(chicken):
    sid, det = chicken
    got = stored_fall_offsets(sid, det, 3, 0x03, {46: 160, 47: 8, 44: 8},
                              12, 1)
    assert got == {4 + m: (0x80 - d) & 0x7F
                   for m, d in enumerate(SIDDUMP_DOWN)}
    assert max(got) == 11, "the 12th call is the last the note has"


@pytest.mark.parametrize("what,args", [
    ("multiplier above 1", dict(multiplier=2)),
    ("no played pitches", dict(pitches=None)),
    ("no typical note length", dict(calls=None)),
    ("a bit besides $01 and $02", dict(effect=0x07)),
    ("no bit $01", dict(effect=0x02)),
    ("no modal pitch", dict(pitches={46: 10, 47: 10, 44: 10})),
])
def test_it_declines_what_it_cannot_say(chicken, what, args):
    sid, det = chicken
    kw = dict(effect=0x03, pitches={46: 160}, calls=12, multiplier=1)
    kw.update(args)
    assert stored_fall_offsets(sid, det, 3, kw["effect"], kw["pitches"],
                               kw["calls"], kw["multiplier"]) is None, what


def test_a_note_too_short_to_fall_has_no_fall(chicken):
    sid, det = chicken
    # The first write is the note's own high byte: calls 3 only, no step.
    assert stored_fall_offsets(sid, det, 3, 0x03, {46: 1}, 4, 1) is None


def test_the_fall_rides_the_alternation_rows():
    # lead (call 0), then the pair in its own phase with the fall's right
    # sides from call 4, held on the pair that loops.
    fall = {4: 0x7F, 5: 0x7E}
    left, right = _wave_alternate_entries(0x41, 0x81, 1, start=16, budget=20,
                                          alt_first=True, fall=fall)
    assert left == [0x41, 0x81, 0x41, 0x81, 0x41, 0x81, 0x41, 0x81, 0xFF]
    assert right == [0, 0, 0, 0, 0x7F, 0x7E, 0x7E, 0x7E, 16 + 6]
    # ...and a program that does not fit keeps the plain pair.
    plain = _wave_alternate_entries(0x41, 0x81, 1, start=16, budget=20,
                                    alt_first=True)
    tight = _wave_alternate_entries(0x41, 0x81, 1, start=16, budget=4,
                                    alt_first=True, fall=fall)
    assert tight == plain == ([0x41, 0x81, 0x41, 0xFF], [0, 0, 0, 17])
    # A multispeed frame is not a call: no fall.
    assert (_wave_alternate_entries(0x41, 0x81, 2, start=16, budget=20,
                                    alt_first=True, fall=fall)
            == _wave_alternate_entries(0x41, 0x81, 2, start=16, budget=20,
                                       alt_first=True))


def test_only_chicken_song_carries_the_block():
    if not CORPUS.is_dir():
        pytest.skip("corpus not present")
    found = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            det = detect(load_sid(str(path)), log=lambda m: None)
        except Exception:                      # noqa: BLE001 -- refused files
            continue
        if det.stored_wave_fall is not None:
            assert not det.effect_drum, path.name
            found.append(path.name)
    assert found == ["Chicken_Song.sid"]


def test_chicken_song_record_3_carries_the_fall_and_its_chords_do_not():
    """Under the shipped presets (which carry `wave_alternate`), record 3's
    own program holds the fall's relative notes -- and the chord blocks
    derived from that program still read the program WITHOUT it, as shipped
    (`11 11 11 41 41 41`), since a chorded note's pitch is the chord's."""
    import json
    import sys

    import fidelity
    import songview
    from h2g.convert import convert
    from h2g.goatwriter.constants import CMD_SETWAVEPTR
    if not CHICKEN.exists():
        pytest.skip("corpus not present")
    presets = Path(__file__).resolve().parents[2] / "presets.json"
    doc = json.loads(presets.read_text(encoding="utf-8"))
    song = songview.parse_sng(convert(
        str(CHICKEN), log=lambda m: None,
        **fidelity._preset_opts(doc, "Chicken_Song.sid")))
    record_3 = next(i for i in song.instruments if i.name.startswith("05:"))
    wt = song.tables["WTBL"]
    rows = wt[record_3.wave_ptr - 1:record_3.wave_ptr - 1 + 14]
    assert [l for l, _r in rows[:4]] == [0x41, 0x81, 0x41, 0x81]
    assert [r for _l, r in rows[4:12]] == [(0x80 - d) & 0x7F
                                          for d in SIDDUMP_DOWN]
    chorded = {p[r + 3] for p in song.patterns for r in range(0, len(p) - 3, 4)
               if p[r + 2] == CMD_SETWAVEPTR}
    blocks = [[l for l, _r in wt[row - 1:row + 5]] for row in chorded
              if wt[row - 1][0] == 0x11]
    assert blocks and all(b == [0x11, 0x11, 0x11, 0x41, 0x41, 0x41]
                          for b in blocks)
