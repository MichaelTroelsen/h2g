"""Food Feud's instrument-indexed note transpose.

Food Feud's voice 0 played two regions an octave low, and the mechanism is
neither an orderlist transpose (the voice's orderlist has no byte >= $80 at
all) nor anything in the pattern's note bytes. It is a static 14-byte table
at $956D, one byte per instrument (`00` x11, `0C`, `0C`, `00`), read at $90FF
`LDA $956D,X` with X = the pattern's instrument operand into a per-voice cell
`$9544,X`, which $9114 `ADC $9544,X` adds to EVERY note byte before the
frequency lookup. Instruments 11 and 12 therefore sound an octave above what
their note bytes say, from the instrument change until the next one -- 116
notes in the tune, 72 on instrument 12 and 44 on 11, the second block sitting
past 180 s of trace and so invisible to the routine artefact.

The conversion applies the offset at the same seam the player does, when a
note byte becomes a Goattracker note (`patterns._build_raw_pattern`,
`instr_transpose`), and `tracks.instrument_transposes` walks the orderlists
for the one thing a pattern cannot know alone: the cell's value when it
starts, for a pattern that sounds notes before naming an instrument.

Measured on the corpus at v0.5.486: the byte-hash moves Food_Feud alone, and
its melody / seq / pitch at -t 260 go 97 / 97 / 90% -> 100 / 100 / 100%.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.detect import (Detection, INSTR_TRANSPOSE_SHAPE,  # noqa: E402
                        _find_instr_transpose, detect, instr_transpose_table)
from h2g.patterns import (GT_END_PATTERN, _build_raw_pattern,  # noqa: E402
                          convert_patterns, decode_entry)
from h2g.sidfile import HLEN, SidFile, load_sid  # noqa: E402
from h2g.tracks import convert_tracks, instrument_transposes  # noqa: E402

FOOD_FEUD = CORPUS / "Food_Feud.sid"
TABLE_OFFSET = 0x5EB
TABLE = bytes([0] * 11 + [12, 12, 0])


def _quiet(*_a, **_k):
    return None


# --- the note seam, on bytes ------------------------------------------------

# One byte per instrument: record 1 transposes +12, record 2 +7, others 0.
SYNTH_TABLE = bytes([0, 12, 7, 0])


def _decode(pattern: list[int], entry: int = 0, table=SYNTH_TABLE):
    data = bytes([0, 0]) + bytes(pattern)
    out: list = []
    events = _build_raw_pattern(data, 2, instr_transpose=table,
                                entry_transpose=entry, transpose_exit=out)
    notes = [events[k] for k in range(0, len(events), 4)
             if events[k] != GT_END_PATTERN]
    return notes, out[0]


def test_an_instrument_byte_transposes_every_note_after_it():
    # $80 nn: operand follows; nn < $80 is an instrument. Then the note.
    notes, (before, exit_cell) = _decode([0x80, 0x01, 0x10, 0x00, 0x12, 0xFF])
    assert notes == [0x10 + 12 + 0x60, 0x12 + 12 + 0x60]
    assert (before, exit_cell) == (0, 12)


def test_a_later_instrument_replaces_the_offset_rather_than_adding_to_it():
    notes, (_, exit_cell) = _decode([0x80, 0x01, 0x10,
                                     0x80, 0x02, 0x10,
                                     0x80, 0x00, 0x10, 0xFF])
    assert notes == [0x10 + 12 + 0x60, 0x10 + 7 + 0x60, 0x10 + 0x60]
    assert exit_cell == 0


def test_notes_before_the_first_instrument_use_the_entry_value():
    notes, (before, exit_cell) = _decode([0x00, 0x10, 0x00, 0x11,
                                          0x80, 0x00, 0x10, 0xFF], entry=12)
    assert notes == [0x10 + 12 + 0x60, 0x11 + 12 + 0x60, 0x10 + 0x60]
    assert (before, exit_cell) == (2, 0)


def test_a_pattern_naming_no_instrument_carries_the_entry_through():
    notes, (before, exit_cell) = _decode([0x00, 0x10, 0xFF], entry=12)
    assert notes == [0x10 + 12 + 0x60]
    # None: the cell leaves exactly as it entered, whatever that was.
    assert (before, exit_cell) == (1, None)


def test_the_sum_wraps_like_the_players_eight_bit_add_and_shift():
    # $78 + 12 = $84; `ASL / TAY` loses bit 7, so the entry read is 4.
    notes, _ = _decode([0x80, 0x01, 0x78, 0xFF])
    assert notes == [0x04 + 0x60]


def test_without_a_table_the_entry_value_is_ignored():
    data = bytes([0, 0, 0x00, 0x10, 0xFF])
    events = _build_raw_pattern(data, 2, entry_transpose=12)
    assert events[0] == 0x10 + 0x60


def test_an_operand_past_the_table_reads_as_zero():
    notes, _ = _decode([0x80, 0x01, 0x10, 0x80, 0x09, 0x10, 0xFF])
    assert notes == [0x10 + 12 + 0x60, 0x10 + 0x60]


# --- the orderlist walk, on a synthetic file --------------------------------

LOAD = 0x1000
TRACK_LO, TRACK_HI = 10, 13
PATT_LO, PATT_HI = 16, 20
VOICE_AT = (40, 52, 56)
PATT_AT = (100, 110, 120, 130)
SYNTH_TABLE_AT = 80
# P0 names instrument 1 (+12) and sounds two notes.
# P1 sounds one note BEFORE naming instrument 0 (+0), then one after.
# P2 names nothing: it plays whatever the voice arrived with.
# P3 names instrument 2 (+7) first, so its entry value cannot matter.
PATTERNS = ([0x80, 0x01, 0x10, 0x00, 0x12, 0xFF],
            [0x00, 0x10, 0x80, 0x00, 0x10, 0xFF],
            [0x00, 0x10, 0xFF],
            [0x80, 0x02, 0x10, 0xFF])


def _addr_of(offset: int) -> int:
    return LOAD + offset - (HLEN - 1)


def _sid(voice0: list[int]) -> SidFile:
    data = bytearray(160)
    for v, off in enumerate(VOICE_AT):
        addr = _addr_of(off)
        data[TRACK_LO + v] = addr & 0xFF
        data[TRACK_HI + v] = addr >> 8
    for i, off in enumerate(PATT_AT):
        addr = _addr_of(off)
        data[PATT_LO + i] = addr & 0xFF
        data[PATT_HI + i] = addr >> 8
    data[VOICE_AT[0]:VOICE_AT[0] + len(voice0)] = bytes(voice0)
    for off in VOICE_AT[1:]:
        data[off:off + 2] = bytes([0x02, 0xFF])
    for off, p in zip(PATT_AT, PATTERNS):
        data[off:off + len(p)] = bytes(p)
    data[SYNTH_TABLE_AT:SYNTH_TABLE_AT + 4] = SYNTH_TABLE
    return SidFile(path="synthetic", data=bytes(data), name="", author="",
                   released="", load_addr=LOAD, subtunes=1)


def _det(table: bool = True) -> Detection:
    return Detection(track_lo=TRACK_LO, track_hi=TRACK_HI,
                     pattern_lo=PATT_LO, pattern_hi=PATT_HI, pattern_used=3,
                     read_track_version=2, track_voices=3,
                     instr_transpose=SYNTH_TABLE_AT if table else -1,
                     instr_start=SYNTH_TABLE_AT + 4, instr_used=4)


def _walk(voice0: list[int], table: bool = True):
    sid, det = _sid(voice0), _det(table)
    lines: list = []
    tracks = convert_tracks(sid, det, lines.append)
    return sid, det, tracks, lines


def test_the_table_is_read_one_byte_per_instrument_and_no_further():
    sid, det = _sid([0x00, 0xFF]), _det()
    assert instr_transpose_table(sid.data, det) == SYNTH_TABLE
    det.instr_used = 40                     # over-counted, as before bounding
    assert instr_transpose_table(sid.data, det) == SYNTH_TABLE
    assert instr_transpose_table(sid.data, _det(table=False)) == b""


def test_the_entry_value_is_carried_from_the_previous_pattern():
    # P0 leaves +12; P1's first note sounds under it; P1 leaves 0; then P0
    # again, and P2 -- which names nothing -- plays under +12.
    _, det, _, lines = _walk([0x00, 0x01, 0x00, 0x02, 0xFF])
    assert det.instr_entry_transposes == {1: 12, 2: 12}
    assert any("2 pattern(s) enter under" in s for s in lines), lines


def test_a_pattern_that_names_an_instrument_first_needs_no_entry():
    _, det, _, _ = _walk([0x00, 0x03, 0xFF])
    assert det.instr_entry_transposes == {}


def test_the_loop_carries_the_cell_back_to_the_restart():
    # P2 is the FIRST pattern, entered at 0 on the first pass -- and at +12
    # when the orderlist loops back after P0. The first value in play order
    # is kept (0, so no entry) and the conflict is said, not averaged.
    _, det, _, lines = _walk([0x02, 0x00, 0xFF])
    assert det.instr_entry_transposes == {}
    assert any("UNDER TWO VALUES" in s and "$2:[0, 12]" in s for s in lines), lines


def test_a_conflict_within_one_pass_is_reported_too():
    _, det, _, lines = _walk([0x01, 0x00, 0x01, 0xFF])
    assert det.instr_entry_transposes == {}
    assert any("UNDER TWO VALUES" in s and "$1:[0, 12]" in s for s in lines), lines


def test_without_the_table_convert_tracks_leaves_the_map_alone():
    _, det, _, lines = _walk([0x00, 0x01, 0xFF], table=False)
    assert det.instr_entry_transposes == {}
    assert not any("Instrument transpose" in s for s in lines)


def test_decode_entry_applies_the_walks_answer():
    sid, det, tracks, _ = _walk([0x00, 0x01, 0x00, 0x02, 0xFF])
    p1 = decode_entry(sid, det, 1)
    assert [p1[0], p1[4]] == [0x10 + 12 + 0x60, 0x10 + 0x60]
    assert decode_entry(sid, det, 2)[0] == 0x10 + 12 + 0x60
    assert decode_entry(sid, det, 3)[0] == 0x10 + 7 + 0x60
    # ...and through convert_patterns, which is what the file is built from.
    patterns, _ = convert_patterns(sid, det, _quiet)
    assert patterns[2][0] == 0x10 + 12 + 0x60


def test_the_walk_is_a_pure_function_of_the_orderlists():
    sid, det = _sid([0x00, 0x01, 0x00, 0x02, 0xFF]), _det()
    tracks = convert_tracks(sid, det, _quiet)
    assert instrument_transposes(sid, det, tracks) == {1: 12, 2: 12}


# --- the detector, on bytes -------------------------------------------------

def _player(with_adc: bool, prefix: bool = True) -> bytes:
    """Food Feud's $90F9-$9116 with the table at the address `_addr_of(60)`
    resolves to, so the found offset is 60."""
    tbl = _addr_of(60)
    code = bytes([0xB1, 0xFA, 0x9D, 0x26, 0x95]) if prefix else bytes(5)
    code += bytes([0xAA, 0xBD, tbl & 0xFF, tbl >> 8,
                   0xAE, 0x2E, 0x95, 0x9D, 0x44, 0x95,
                   0xFE, 0x17, 0x95, 0xC8, 0xB1, 0xFA, 0x8D, 0x4C, 0x95,
                   0x29, 0x7F, 0x18])
    code += bytes([0x7D, 0x44, 0x95]) if with_adc else bytes([0x7D, 0x45, 0x95])
    data = bytearray(160)
    data[10:10 + len(code)] = code
    data[60:64] = SYNTH_TABLE
    return bytes(data)


def _sid_of(data: bytes) -> SidFile:
    return SidFile(path="synthetic", data=data, name="", author="",
                   released="", load_addr=LOAD, subtunes=1)


def test_the_shape_names_the_table_the_player_reads():
    det = Detection(instr_used=4, instr_start=64)
    assert _find_instr_transpose(_sid_of(_player(True)), det) == 60


def test_a_register_the_note_fetch_never_adds_is_not_a_transpose():
    # Same four opcodes, but the cell the STA writes is not the one the
    # note fetch ADCs -- the loose shape's two other corpus matches.
    det = Detection(instr_used=4, instr_start=64)
    assert _find_instr_transpose(_sid_of(_player(False)), det) == -1


def test_without_the_instrument_fetch_in_front_the_shape_is_not_matched():
    det = Detection(instr_used=4, instr_start=64)
    assert _find_instr_transpose(_sid_of(_player(True, prefix=False)), det) == -1


def test_the_shape_anchors_on_the_instrument_fetch_and_the_table_load():
    assert INSTR_TRANSPOSE_SHAPE.split()[:3] == ["B1", "??", "9D"]
    assert INSTR_TRANSPOSE_SHAPE.split()[5:7] == ["AA", "BD"]


# --- Food Feud itself -------------------------------------------------------

@needs_corpus
def test_food_feud_carries_the_table_at_956d():
    sid = load_sid(str(FOOD_FEUD))
    det = detect(sid, log=_quiet)
    assert det.instr_transpose == TABLE_OFFSET
    assert sid.to_address(det.instr_transpose) == 0x956D
    assert det.instr_used == 14
    assert instr_transpose_table(sid.data, det) == TABLE


@needs_corpus
def test_food_feud_is_the_only_corpus_file_with_the_table():
    found = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            det = detect(load_sid(str(path)), log=_quiet)
        except Exception:                              # noqa: BLE001
            continue
        if det.instr_transpose >= 0:
            found.add(path.name)
    assert found == {"Food_Feud.sid"}


@needs_corpus
def test_food_feud_enters_patterns_23_and_28_under_an_octave():
    """Four instrument changes move the cell; three sit at a pattern start
    and one mid-pattern. Patterns $17 and $1C name no instrument and follow
    the ones that select 12 and 11, so they are the two the walk must
    answer for -- and no pattern is reached under two values."""
    sid = load_sid(str(FOOD_FEUD))
    det = detect(sid, log=_quiet)
    lines: list = []
    convert_tracks(sid, det, lines.append)
    assert det.instr_entry_transposes == {23: 12, 28: 12}
    assert not any("UNDER TWO VALUES" in s for s in lines), lines
    assert not any("DEPENDS ON" in s for s in lines), lines


def _notes_in_play_order(blob: bytes):
    """(voice, pattern, row, note, instrument) for every note row, orderlists
    expanded, on the finished .sng. songview's patterns are flat byte lists."""
    import songview
    song = songview.parse_sng(blob)
    out = []
    for v, track in enumerate(song.tracks):
        for b in track:
            if b == 0xFF:
                break
            if b >= 0xD0:
                continue
            pat = song.patterns[b]
            for k in range(0, len(pat), 4):
                if pat[k] == 0xFF:
                    break
                out.append((v, b, k // 4, pat[k], pat[k + 1]))
    return out


@needs_corpus
def test_exactly_116_notes_rise_an_octave_and_nothing_else_moves(monkeypatch):
    """The A/B the change was adopted on, pinned: with the table found, the
    conversion differs from one that does not find it in exactly the 116
    note cells the player transposes -- 72 under instrument 12 and 44 under
    11, all on voice 0, every one of them +12 -- and in no other byte of any
    row."""
    import h2g.detect as D
    from h2g.convert import convert

    with_table = convert(str(FOOD_FEUD), log=_quiet)
    monkeypatch.setattr(D, "_find_instr_transpose", lambda sid, det: -1)
    without = convert(str(FOOD_FEUD), log=_quiet)
    assert with_table != without

    a, b = _notes_in_play_order(without), _notes_in_play_order(with_table)
    assert len(a) == len(b)
    moved = []
    current: dict = {}          # the instrument in force, per voice
    for (va, pa, ra, na, ia), (vb, pb, rb, nb, ib) in zip(a, b):
        assert (va, pa, ra, ia) == (vb, pb, rb, ib)
        if ib:
            current[vb] = ib
        if na != nb:
            moved.append((va, nb - na, current.get(vb, 0)))
    assert len(moved) == 116
    assert {v for v, _, _ in moved} == {0}
    assert {d for _, d, _ in moved} == {12}
    # Goattracker numbers instruments from 1 and the default base is 2, so
    # the player's records 11 and 12 are the .sng's 13 and 14 here.
    by_instr: dict = {}
    for _, _, i in moved:
        by_instr[i] = by_instr.get(i, 0) + 1
    assert by_instr == {14: 72, 13: 44}
