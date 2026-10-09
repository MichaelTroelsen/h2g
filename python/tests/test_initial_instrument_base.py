"""The initial-instrument index is a 0-based record number, and the instrument
`--initial-instrument` writes is that record under every numbering the writer
can produce.

Gremlins is the file that raised the question. `Detection.initial_instruments`
reads `$15 $15 $03` and the original, traced with `siddump -a3`, plays D-3 on
voice 0 at ADSR `$0800` -- which is record `$15` of the table at `$1784`
(`$182C: 16 04 41 08 00 ...`), not record `$16`. A census taken on the shipped
output read the 21-instrument table as "index + 1 = 22 does not even exist",
and concluded the image value was not the played record. It is: the player
stores a pattern's instrument byte raw into the array
(`$10DD STA $16D6,X`) and indexes the table with `ASL A x3` (`$1114`), so the
array is a 0-based record number exactly like the pattern byte `decode_entry`
applies `instr_base` to. What moves the number is `drop_unnamed_instruments`,
which renumbers the finished file, so "Goattracker instrument k + base" is true
before the drop and not after it. These tests compare the ADSR of the
instrument that ended up in the pattern with the ADSR of record k in the file
image, which is true at every base and survives the drop.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus import CORPUS                              # noqa: E402
from h2g.convert import convert                        # noqa: E402
from h2g.detect import detect                          # noqa: E402
from h2g.sidfile import load_sid                       # noqa: E402
from songview import parse_sng                         # noqa: E402

NUL = lambda *a, **k: None                             # noqa: E731
GREMLINS = os.path.join(CORPUS, "Gremlins.sid")
SUBTUNE, VOICE = 3, 0        # the one orderlist that starts on a bare note


def _gremlins():
    if not os.path.exists(GREMLINS):
        pytest.skip("corpus file not present: Gremlins.sid")
    return GREMLINS


def _first_row_instrument(blob):
    """The (instrument number, ADSR) the subtune-3 voice-0 orderlist's first
    pattern names on its first row, or (0, None) when it names none."""
    song = parse_sng(blob)
    track = song.tracks[SUBTUNE * 3 + VOICE]
    pattern = song.patterns[track[0]]
    note, instr = pattern[0], pattern[1]
    assert note < 0xBD, "row 0 must be a note for this test to mean anything"
    if not instr:
        return 0, None
    return instr, song.instruments[instr - 1].adsr


def _record_adsr(sid, det, k):
    base = det.instr_start + k * det.instr_stride
    return "$%02X%02X" % (sid.data[base + 3], sid.data[base + 4])


def test_the_image_array_and_the_original_agree_on_record_21():
    sid = load_sid(_gremlins())
    det = detect(sid, NUL)
    assert det.initial_instruments[0] == 0x15
    # siddump -a3 shows voice 0 starting D-3 / WF 41 / ADSR 0800.
    assert _record_adsr(sid, det, 0x15) == "$0800"
    # ... and not the next record up, which is what a 1-based reading names.
    assert _record_adsr(sid, det, 0x16) != "$0800"


@pytest.mark.parametrize("compact,drop", [(False, False), (True, False),
                                          (True, True)])
def test_initial_instrument_is_record_k_at_every_numbering(compact, drop):
    path = _gremlins()
    sid = load_sid(path)
    det = detect(sid, NUL)
    want = _record_adsr(sid, det, det.initial_instruments[VOICE])

    off = convert(path, log=NUL, compact_instruments=compact,
                  drop_unnamed_instruments=drop)
    assert _first_row_instrument(off)[0] == 0   # the defect: a bare note

    on = convert(path, log=NUL, compact_instruments=compact,
                 drop_unnamed_instruments=drop, initial_instrument=True)
    number, adsr = _first_row_instrument(on)
    assert number, "the flag wrote no instrument column"
    assert adsr == want


def test_only_the_bare_orderlist_moves():
    """Gremlins has seven subtunes and one voice that starts on a bare note;
    the flag must repoint that one orderlist and no other."""
    path = _gremlins()
    kw = dict(compact_instruments=True, drop_unnamed_instruments=True)
    a = parse_sng(convert(path, log=NUL, **kw))
    b = parse_sng(convert(path, log=NUL, initial_instrument=True, **kw))
    moved = [i for i, (x, y) in enumerate(zip(a.tracks, b.tracks)) if x != y]
    assert moved == [SUBTUNE * 3 + VOICE]
    assert len(b.patterns) == len(a.patterns) + 1
