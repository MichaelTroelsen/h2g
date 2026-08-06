"""The bit-6-first status byte read (`BIT status / BVS`).

Commando $50C2 (and Last V8 $80CF, byte for byte the same shape):

    50C2  B1 5F     LDA ($5F),Y       ; the status byte
    50C7  8D 02 55  STA $5502
    50CA  29 1F     AND #$1F
    50CC  9D F2 54  STA $54F2,X       ; the wait counter is kept...
    50CF  2C 02 55  BIT $5502         ; V := bit 6
    50D2  70 44     BVS $5118         ; ...but bit 6 skips BOTH reads below
    50DC  C8 B1 5F  INY / LDA ($5F),Y ; the operand (bit 7 set)
    50ED  C8 B1 5F  INY / LDA ($5F),Y ; the note

The BVS lands past both INY/LDA pairs whatever bit 7 says, so a status byte
of $C0-$FE consumes nothing but itself -- where the bit-7-first reading
consumes an operand and a note the player never reads, and desynchronises
the rest of the pattern.

Gated on detection finding that shape (61 of 95 corpus files), off by
default: the byte-exact Commando fixture encodes the old reading -- and, as
pinned below, Commando's own played patterns contain no $C0-$FE byte, so
even the flag leaves the fixture untouched.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import convert
from h2g.detect import STATUS_BIT6_SHAPE, detect
from h2g.patterns import GT_NO_NOTE, _build_raw_pattern
from h2g.search import search_file
from h2g.sidfile import load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# One $C3 status byte (bit 7: operand follows, bit 6: no note, wait 3),
# then $00 $00, then the terminator -- laid out so the two readings tell
# themselves apart on the first row alone.
VECTOR = bytes([0x00, 0x00, 0xC3, 0x00, 0x00, 0xFF])


def _rows(events):
    return [tuple(events[k:k + 4]) for k in range(0, len(events), 4)]


def test_without_the_flag_c0_fe_consumes_an_operand_and_a_note():
    # The old reading, pinned because it is still the default: $C3 reads $00
    # as its operand (instrument 0 -> GT instrument 2) and $00 as its note.
    rows = _rows(_build_raw_pattern(VECTOR, 2))
    assert rows[0] == (0x60, 2, 0, 0)
    assert len(rows) == 1 + 3 + 1          # event, wait 3, ENDPATT


def test_with_the_flag_c0_fe_consumes_only_itself():
    rows = _rows(_build_raw_pattern(VECTOR, 2, status_bit6=True))
    # $C3 is a bare hold: no operand, no note, no instrument...
    assert rows[0] == (GT_NO_NOTE, 0, 0, 0)
    # ...and the two $00 bytes it no longer swallows become the next event:
    # status $00, note $00.
    assert rows[4] == (0x60, 0, 0, 0)
    assert len(rows) == 1 + 3 + 1 + 1      # hold, wait 3, next event, ENDPATT


def test_wait_bits_still_count_on_the_skip_path():
    # The player stores AND #$1F *before* the BVS, so a skipped event still
    # holds its wait+1 rows.
    rows = _rows(_build_raw_pattern(bytes([0, 0, 0xDF, 0xFF]), 2,
                                    status_bit6=True))
    assert len(rows) == 1 + 0x1F + 1


def test_commando_has_the_shape():
    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    assert search_file(sid.data, STATUS_BIT6_SHAPE) >= 1
    det = detect(sid, lambda m: None)
    assert det.status_bit6


def test_commando_fixture_survives_the_flag():
    # Commando has the BIT/BVS shape but its played patterns hold no $C0-$FE
    # status byte, so honouring the skip changes nothing -- the fixture is
    # byte-exact even with the flag on. If this ever fails, the flag has
    # started reaching data it did not reach before; find out why before
    # touching the fixture.
    fixture = (REPO_ROOT / "Commando.sng").read_bytes()
    out = convert(str(REPO_ROOT / "Commando.sid"), log=lambda m: None,
                  status_bit6=True)
    assert out == fixture
