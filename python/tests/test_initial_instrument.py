"""The instrument a voice starts on, and the signature that finds it.

Two separate things share one signature (detect.INSTRUMENT_INDEX_SHAPE), and
they ship on different terms:

  * the instrument *table* address, taken from the same match, is applied
    unconditionally -- but only as the last fallback, after every
    store-shaped signature has failed, so it can rescue a file that finds
    nothing and cannot move one that already reads correctly;
  * the per-voice initial instrument is behind --initial-instrument, because
    the array it reads is mutable player state and its file-image value is
    only the starting value for a rip of a single tune.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from h2g.convert import convert                       # noqa: E402
from h2g.detect import INSTRUMENT_INDEX_SHAPE, Detection, detect  # noqa: E402
from h2g.search import search_file                    # noqa: E402
from h2g.sidfile import load_sid                      # noqa: E402
from h2g.tracks import apply_initial_instruments      # noqa: E402

CORPUS = r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob"
# The repo's own Commando.sid, not the corpus copy -- they are different rips
# (4222 B / 3 subtunes here against 4165 B / 19 there), and only this one is
# the byte-exact fixture.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NUL = lambda *a, **k: None                            # noqa: E731


def _commando():
    return os.path.join(REPO, "Commando.sid")


def corpus(name):
    path = os.path.join(CORPUS, name)
    if not os.path.exists(path):
        pytest.skip(f"corpus file not present: {name}")
    return path


# --- the signature ---------------------------------------------------------

def test_shape_matches_the_load_not_the_store():
    """`LDA idx,X / STX save / ASL*3 / TAX / LDA record+2,X`.

    The three shifts are the multiply by the 8-byte record size, which is
    what makes the trailing operand the record's waveform field rather than
    its base.
    """
    assert INSTRUMENT_INDEX_SHAPE.split() == [
        "BD", "??", "??", "8E", "??", "??",
        "0A", "0A", "0A", "AA", "BD", "??", "??"]


def test_phantoms_instrument_table_found_via_the_index_load():
    """The file this rescued: it writes the SID through JSR trampolines.

    `$E112 LDA $E467,X / JSR $F04E` instead of `STA $D402,Y`, so none of the
    store-shaped signatures match and it converted with zero instruments --
    every note naming an instrument that was not written, which is silence.
    """
    sid = load_sid(corpus("Phantoms_of_the_Asteroid.sid"))
    det = detect(sid, NUL)
    assert det.instr_start == sid.to_offset(0xE467)
    assert det.instr_used == 0x19
    assert det.initial_instruments == (0x00, 0x00, 0x02)


def test_phantoms_writes_the_instruments_its_patterns_name():
    sid = load_sid(corpus("Phantoms_of_the_Asteroid.sid"))
    det = detect(sid, NUL)
    # Its patterns reference up to instrument $19; before the signature
    # existed the file carried none at all.
    assert det.instr_used >= 0x19


def test_index_load_never_overrides_a_store_signature():
    """Corroboration, and the reason the fallback is safe.

    The shape is present in most of the corpus and names the same table the
    store-shaped chain already found. It is consulted last regardless, so a
    file that reads correctly cannot be moved by it -- this pins the
    agreement that makes the address trustworthy where it *is* consulted.
    """
    sid = load_sid(_commando())
    det = detect(sid, NUL)
    i = search_file(sid.data, INSTRUMENT_INDEX_SHAPE)
    if i <= -1:
        pytest.skip("shape absent in this rip of Commando")
    named = (sid.data[i + 12] * 256 + sid.data[i + 11]) - 2
    assert sid.to_offset(named) == det.instr_start


# --- the initial instrument ------------------------------------------------

def test_mix_e_load_initial_array_is_what_the_original_plays():
    """`$C535` reads `03 09 00`, and records 3/9/0 carry the ADSR siddump
    shows on voices 0/1/2. Voice 1 is the control: its pattern selects
    instrument $09 explicitly, and the array agrees.
    """
    sid = load_sid(corpus("Delta_Mix-E-Load_loader.sid"))
    det = detect(sid, NUL)
    assert det.initial_instruments == (0x03, 0x09, 0x00)
    adsr = {}
    for i in (0x00, 0x03, 0x09):
        base = det.instr_start + i * det.instr_stride
        adsr[i] = (sid.data[base + 3], sid.data[base + 4])
    assert adsr[0x03] == (0x3A, 0x98)      # voice 0
    assert adsr[0x09] == (0xBC, 0x5D)      # voice 1
    assert adsr[0x00] == (0x0C, 0xF8)      # voice 2


def test_off_by_default_and_commando_unmoved():
    out = convert(_commando(), log=NUL)
    with open(os.path.join(REPO, "Commando.sng"), "rb") as fh:
        assert out == fh.read()


def test_flag_changes_mix_e_load_and_nothing_in_commando():
    plain = convert(_commando(), log=NUL)
    flagged = convert(_commando(), log=NUL, initial_instrument=True)
    assert plain == flagged          # no voice here starts without one

    a = convert(corpus("Delta_Mix-E-Load_loader.sid"), log=NUL)
    b = convert(corpus("Delta_Mix-E-Load_loader.sid"), log=NUL,
                initial_instrument=True)
    assert a != b


# --- the pass itself -------------------------------------------------------

def _det(initial, instr_used=8):
    det = Detection()
    det.initial_instruments = initial
    det.instr_used = instr_used
    return det


def test_copies_rather_than_patching_a_shared_pattern():
    """The pattern is played again later, where the voice already has an
    instrument -- writing the column into the shared copy would re-select it
    every time round, so the fix must not touch the original.
    """
    patterns = [[0x70, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    tracks = [[0, 0, 0xFF, 0]]
    n = apply_initial_instruments(tracks, patterns, _det((5, 0, 0)))
    assert n == 1
    assert len(patterns) == 2
    assert patterns[0][1] == 0            # original untouched
    assert patterns[1][1] == 5 + 2        # Hubbard 5 -> Goattracker 7
    assert tracks[0] == [1, 0, 0xFF, 0]   # only the first step repointed


def test_a_pattern_that_sets_an_instrument_is_left_alone():
    patterns = [[0x70, 0x04, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    tracks = [[0, 0xFF, 0]]
    assert apply_initial_instruments(tracks, patterns, _det((5, 0, 0))) == 0
    assert len(patterns) == 1


def test_an_instrument_set_before_the_first_note_wins():
    """A row may carry an instrument with no note; gplay.c:914 assigns on any
    non-zero column, so the player has one by the time the note arrives."""
    patterns = [[0xBD, 0x04, 0x00, 0x00, 0x70, 0x00, 0x00, 0x00]]
    tracks = [[0, 0xFF, 0]]
    assert apply_initial_instruments(tracks, patterns, _det((5, 0, 0))) == 0


def test_a_noteless_pattern_defers_to_the_next_in_the_orderlist():
    silent = [0xBD, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]
    sounding = [0x70, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]
    patterns = [list(silent), list(sounding)]
    tracks = [[0, 1, 0xFF, 0]]
    assert apply_initial_instruments(tracks, patterns, _det((5, 0, 0))) == 1
    assert tracks[0][0] == 0              # the silent pattern is not copied
    assert tracks[0][1] == 2              # the sounding one is


def test_voice_index_selects_its_own_entry():
    patterns = [[0x70, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    apply_initial_instruments(tracks, patterns, _det((1, 2, 3)))
    got = [patterns[t[0]][1] for t in tracks]
    assert got == [3, 4, 5]               # each +2, one copy per voice


def test_no_array_is_a_no_op():
    patterns = [[0x70, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    tracks = [[0, 0xFF, 0]]
    assert apply_initial_instruments(tracks, patterns, _det(())) == 0
    assert len(patterns) == 1


def test_an_index_past_the_written_instruments_is_refused():
    """goatwriter drops instruments past its ceiling, so naming one the .sng
    will not contain would trade silence for a dangling reference."""
    patterns = [[0x70, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]]
    tracks = [[0, 0xFF, 0]]
    assert apply_initial_instruments(tracks, patterns,
                                     _det((90, 0, 0), instr_used=8)) == 0
