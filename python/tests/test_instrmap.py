"""The instrument columns appended to siddump's own table.

`annotate_dump` is the join the rest of `instrmap.py` reports as a summary,
applied per frame instead of per song: it labels each voice of the trace --
including the *original's* trace -- with the GT instrument sounding on it.

What is worth pinning is that it stays faithful to the tables it sits under.
The instrument is decided on the frame after the attack and held for the note,
so a hard restart's ADSR on the attack frame cannot relabel it, and a row of
the dump cannot contradict the mapping above it.
"""
import instrmap as M
import fidelity as F

# Real Commando rows: a silent frame, an attack on all three voices, then a
# frame that writes only the gate-off waveform. The third row is what proves
# the carry-forward -- its ADSR field is dots, so a per-frame join would read
# it as ADSR 0 and lose the instrument mid-note.
DUMP = """\
| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | 0116  ... ..  00 0000 0B8 | 0116  ... ..  00 0000 000 | 0000  ... ..  00 0000 068 | 0000 00 Off F |
|     1 | AF58  E-7 D8  15 0DFB 180 | 2141  B-4 BB  43 0FC4 200 | 03A9  A-1 95  41 099F 168 | .... .. ... . |
|     2 | ....  ... ..  80 .... ... | ....  ... ..  80 .... ... | ....  ... ..  80 .... ... | .... .. ... . |
"""

NF = 3
# instrument 8 carries $0DFB and 5 carries $0FC4; $099F is deliberately left
# out, so voice 3 exercises the unmatched-ADSR path
INS = {0x0DFB: [8], 0x0FC4: [5]}


def _rows(text):
    return [l for l in text.splitlines() if l.startswith("|")]


def test_columns_are_appended_and_aligned():
    body, _ = M.annotate_dump(DUMP, F.parse_dump(DUMP), INS, NF)
    lines = body.splitlines()
    assert "Ins1 Ins2 Ins3" in lines[0]
    # the rule row has to grow with the header or the table stops being one
    assert len(set(len(l) for l in lines)) == 1


def test_onset_marked_and_held_for_the_note():
    body, _ = M.annotate_dump(DUMP, F.parse_dump(DUMP), INS, NF)
    r = _rows(body)
    assert r[1].endswith("   .    .    . |")      # frame 0, nothing sounding
    assert r[2].endswith("  *8   *5   *a |")      # frame 1, all three attack
    # frame 2 writes no ADSR at all; the note is still the same instrument
    assert r[3].endswith("   8    5    a |")


def test_unmatched_adsr_is_lettered_and_named():
    _, legend = M.annotate_dump(DUMP, F.parse_dump(DUMP), INS, NF)
    assert legend == ["`$099F` = `a`"]


def test_ambiguous_adsr_names_every_instrument_sharing_it():
    body, _ = M.annotate_dump(DUMP, F.parse_dump(DUMP),
                              {**INS, 0x0DFB: [3, 8]}, NF)
    assert "*3/8" in _rows(body)[2]
