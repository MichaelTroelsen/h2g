"""Effect bit $10's block has four spellings, and two of them were unread.

`PITCH_SEQ_SHAPE` was one fixed byte string, so it matched 34 of the 95 corpus
files and reported the mechanism *absent* in two more that carry it complete.
Both misses are instruction **lengths**, the `SPEED_GATE_IMM` class:

    Mega_Apocalypse $4E0D   LDA $B9,X          zero page, two bytes, where 33
                            files spell it     LDA $abs,X, three
    Food_Feud       $9382   SEC / SBC #$30     the player's own note-table
                            between the ADC and the ASL/TAY

A length difference moves the `BEQ` offset in front of it and every operand
behind it at once, so a shape matching neither is indistinguishable from the
player not having the feature.

What this file also pins is the **boundary**: three more files have an
`AND #$10 / BEQ` block that is deliberately *not* matched, and two named in the
task have no `AND #$10` at all. Recording those keeps the next reader from
widening the shape until it swallows a different mechanism.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                        # noqa: E402

from h2g import detect as D                                    # noqa: E402
from h2g.convert import _detect_tables                         # noqa: E402
from h2g.detect import Detection                              # noqa: E402
from h2g.goatwriter import _arp_relative, _pitch_seq_notes    # noqa: E402
from h2g.sidfile import SidFile, load_sid                      # noqa: E402


def _seq(name):
    return D._find_pitch_seq(load_sid(str(CORPUS / f"{name}.sid")))


def _addr(sid, off):
    """File offset back to the C64 address, the inverse of `to_offset`."""
    return sid.load_addr + (off - sid.to_offset(sid.load_addr))


def test_the_canonical_spelling_is_unchanged():
    """The widening must not move a file that already reads correctly.

    Composing the shape from parts is only safe if part one still spells the
    string 34 files match today, and if it stays *first* in the search order --
    `_find_pitch_seq` returns on the first hit.
    """
    assert D.PITCH_SEQ_SHAPE == (
        "29 10 F0 ?? B9 ?? ?? 0A A8 B9 ?? ?? 8D ?? ?? B9 ?? ?? "
        "8D ?? ?? AC ?? ?? 18 BD ?? ?? 79 ?? ?? 0A A8")
    assert D.PITCH_SEQ_SHAPES[0] == (D.PITCH_SEQ_SHAPE, 29)
    assert D.PITCH_SEQ_AT_BASE == 29


def test_every_spelling_puts_the_operands_where_the_reader_looks():
    """The three head operands are fixed; only the ADC's offset moves.

    `base` is derived from the note load's length rather than counted by hand,
    which is the whole point of composing the shapes -- so assert the derivation
    against the byte strings themselves, not against the same arithmetic.
    """
    assert len(D.PITCH_SEQ_SHAPES) == 4
    for shape, at_base in D.PITCH_SEQ_SHAPES:
        toks = shape.split()
        assert toks[D.PITCH_SEQ_AT_INDEX - 1] == "B9", shape   # LDA index,Y
        assert toks[D.PITCH_SEQ_AT_PAIRS - 1] == "B9", shape   # LDA pairs,Y
        assert toks[D.PITCH_SEQ_AT_PHASE - 1] == "AC", shape   # LDY phase
        assert toks[at_base - 1] == "79", shape                # ADC base,Y
        # the head is shared verbatim by all four
        assert shape.startswith(D.PITCH_SEQ_HEAD), shape


@needs_corpus
def test_mega_apocalypse_keeps_the_played_note_in_zero_page():
    """`LDA $B9,X` at $4E0D -- two bytes where the other files use three.

    Everything else is the canonical block: the index array, both pair copies,
    the global phase, the base add. Addresses are read off the disassembly, so
    a shape that matched by luck somewhere else in the file would fail here.
    """
    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    seq = D._find_pitch_seq(sid)
    assert seq is not None
    assert (_addr(sid, seq.index), _addr(sid, seq.pairs),
            _addr(sid, seq.base)) == (0x54A3, 0x5392, 0x524D)
    # `DEC $51BF / BPL +5 / LDA #$02 / STA $51BF` at $4E7E -- a three-step cycle
    assert seq.steps == 3


@needs_corpus
def test_food_feud_subtracts_its_note_table_origin_before_the_lookup():
    """`SEC / SBC #$30` at $9382, between the ADC and the ASL/TAY."""
    sid = load_sid(str(CORPUS / "Food_Feud.sid"))
    seq = D._find_pitch_seq(sid)
    assert seq is not None
    assert (_addr(sid, seq.index), _addr(sid, seq.pairs),
            _addr(sid, seq.base)) == (0x95EB, 0x9565, 0x955F)
    # `DEC $955D / BPL +5 / LDA #$01 / STA $955D` at $9405 -- two steps, not the
    # three of the constant, and read from the player rather than assumed.
    assert seq.steps == 2


@needs_corpus
def test_the_two_new_files_decode_to_real_arpeggios():
    """A shape can match and still name the wrong bytes.

    Mega Apocalypse's four bit-$10 records give thirds over fifths/sixths;
    Food Feud's two give a small drop and back. Both are intervals a tune could
    contain, which a mis-anchored pairs table would not be.
    """
    from h2g import goatwriter as G
    want = {
        "Mega_Apocalypse": {4: [8, 0, 5], 5: [8, 0, 3],
                            7: [9, 0, 5], 8: [9, 0, 4]},
        "Food_Feud": {2: [124, 0], 3: [125, 0]},
    }
    for name, records in want.items():
        sid, det = _detect_tables(
            load_sid(str(CORPUS / f"{name}.sid")), lambda *a, **k: None)
        got = {}
        for i in range(16):
            rec = det.instr_start + i * det.instr_stride
            if rec + 7 >= len(sid.data):
                break
            if sid.data[rec + 7] & 0x10:
                got[i] = G._pitch_seq_notes(sid, det, i)
        assert got == records, name


@needs_corpus
def test_only_the_two_intended_files_gain_the_block():
    """The corpus difference is exactly {Food_Feud, Mega_Apocalypse}.

    Pinned as a set rather than a count: a later widening that finds one more
    file and loses one would keep the count and change the answer.
    """
    found = {p.stem for p in sorted(CORPUS.glob("*.sid"))
             if D._find_pitch_seq(load_sid(str(p))) is not None}
    assert "Food_Feud" in found and "Mega_Apocalypse" in found
    assert len(found) == 36


@needs_corpus
def test_the_blocks_that_are_deliberately_not_matched():
    """Three files have an `AND #$10 / BEQ` block that this cannot represent.

    - Kings_of_the_Beach_intro $1011 loads the phase and adds the base, but has
      **no index array and no pair copy**: `$126B` holds a static `00 0C 18` and
      nothing in the file writes `$126C`/`$126D`. `PitchSeq` addresses its steps
      as `pairs + 2 * index`, so saying "the same three steps for every record"
      needs a writer change as well as a shape.
    - ACE_II $E3F7 and Ricochet $9421 copy **one** pair byte and never load the
      phase, so their `ADC base,Y` runs with `Y = 2 * index` -- a constant
      transpose per record. Neither is in `VIBRATO.md`'s `pitchseq` rows.
    """
    for name, at, note in (
            ("Kings_of_the_Beach_intro", 0x1011, "static table, no index"),
            ("ACE_II", 0xE3F7, "no phase load"),
            ("Ricochet", 0x9421, "no phase load")):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        off = sid.to_offset(at)
        assert sid.data[off:off + 2] == b"\x29\x10", (name, "gate moved")
        assert D._find_pitch_seq(sid) is None, (name, note)


@needs_corpus
def test_the_ik_dialect_never_tests_bit_10_at_all():
    """`$55` in these two files is "arpeggio, depth 5" -- not five flags.

    `VIBRATO.md` files International_Karate's `$090A`/`$0A0A` and
    Formula_1_Simulator's `$0A0A` under `pitchseq` because
    `fidelity.py`'s cause map sets `out[0x10] = "pitchseq"` unconditionally and
    `VIB_CAUSE_ORDER` puts `$10` ahead of `$04`. Their players contain no
    `AND #$10` anywhere: the effect cell is tested against single bits up to
    `$08` and then shifted right four times, so bit 4 is the low bit of bit
    $04's interval. Widening the shape can never reach them.
    """
    for name, cell in (("International_Karate", 0xB2F7),
                       ("Formula_1_Simulator", 0xC4F7)):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        data = sid.data
        assert not any(data[i] == 0x29 and data[i + 1] == 0x10
                       for i in range(len(data) - 1)), name
        assert D._find_pitch_seq(sid) is None, name
        # the cell is real and is read -- the bit simply is not a flag here
        assert 0x10 not in D._effect_cells(data).get(cell, set()), name
        lo, hi = cell & 0xFF, cell >> 8
        assert any(data[i] == 0xAD and data[i + 1] == lo and data[i + 2] == hi
                   and data[i + 3:i + 7] == b"\x4a\x4a\x4a\x4a"
                   for i in range(len(data) - 7)), (name, "no LSR x4")

# --- the static global table: a writer, not a spelling ----------------------

def _rotations(steps):
    enc = [_arp_relative(1, s) for s in steps]
    return [enc[k:] + enc[:k] for k in range(len(enc))]


def _static(base, steps):
    """The interim static form `_pitch_seq_notes` reads: `pairs < 0` says the
    table is global at `base`; `steps` is its length, negative where the
    phase counter counts down."""
    return D.PitchSeq(index=-1, pairs=-1, base=base, steps=steps)


def test_the_static_form_reads_kings_of_the_beach_intros_table_in_play_order():
    """Its bit-$10 handler ($100E) adds a GLOBAL table ($126B: 00 0C 18) to
    the note under a phase counter that counts DOWN ($107F: DEC / BPL / LDA
    #2), so the player's order is 24, 12, 0 -- siddump reads 559 frames of
    -12 and 292 of +24 on voice 1 in 60 s and never the rising cycle. Nothing
    in detect.py emits this form yet; this pins what the writer does with it.
    """
    if not CORPUS.is_dir():
        return
    sid = load_sid(str(CORPUS / "Kings_of_the_Beach_intro.sid"))
    sid, det = _detect_tables(sid, lambda *a, **k: None)
    assert det.pitch_seq is None, "detection does not read the static form yet"
    base = sid.to_offset(0x126B)
    assert sid.data[base:base + 3] == b"\x00\x0c\x18"
    det.pitch_seq = _static(base, -3)
    notes = _pitch_seq_notes(sid, det, 4)            # record 4 carries bit $10
    assert notes in _rotations((24, 12, 0)), notes
    assert notes not in _rotations((0, 12, 24)), "direction is the mechanism"
    assert notes[1] == _arp_relative(1, 0), "the played note follows the attack"
    assert _pitch_seq_notes(sid, det, 0) is None, "no bit $10, no sequence"


def _fake(table, effect=0x10):
    STRIDE, INSTR, TABLE = 8, 0x40, 0x100
    data = bytearray(0x200)
    data[INSTR + 2] = 0x41
    data[INSTR + 7] = effect
    data[TABLE:TABLE + len(table)] = bytes(table)
    sid = SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                  released="r", load_addr=0x1000, subtunes=1)
    det = Detection(instr_start=INSTR, instr_used=1, instr_stride=STRIDE,
                    track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                    pattern_used=0, read_track_version=0)
    return sid, det, TABLE


def test_the_static_forms_sign_is_the_phase_counters_direction():
    sid, det, table = _fake((0, 12, 24))
    det.pitch_seq = _static(table, 3)
    assert _pitch_seq_notes(sid, det, 0) in _rotations((0, 12, 24))
    det.pitch_seq = _static(table, -3)
    assert _pitch_seq_notes(sid, det, 0) in _rotations((24, 12, 0))


def test_a_static_table_with_no_zero_step_still_opens_on_the_played_note():
    """(24, 12, 0) has no modal step. `most_common` broke the tie by insertion
    order and led with 24, which at -S5 put two octaves on every attack frame:
    melody 99.5% -> 91.7%, pitch 100% -> 69% in the A/B. The tie now goes to
    the zero step, and a pair-form sequence -- whose 0 is inserted first --
    rotates exactly as it did before."""
    sid, det, table = _fake((24, 12, 0))
    det.pitch_seq = _static(table, 3)
    assert _pitch_seq_notes(sid, det, 0)[1] == _arp_relative(1, 0)
    sid, det, table = _fake((0, 12, 24))
    det.pitch_seq = _static(table, 3)
    assert _pitch_seq_notes(sid, det, 0) == [_arp_relative(1, s) for s in (24, 0, 12)]


def test_the_static_form_declines_a_table_it_cannot_read():
    sid, det, table = _fake((0, 12, 24))
    det.pitch_seq = _static(len(sid.data) - 1, 3)      # runs off the data
    assert _pitch_seq_notes(sid, det, 0) is None
    det.pitch_seq = _static(table, 1)                   # one step is no cycle
    assert _pitch_seq_notes(sid, det, 0) is None
    sid, det, table = _fake((0, 0, 0))
    det.pitch_seq = _static(table, 3)                   # all zero: no arpeggio
    assert _pitch_seq_notes(sid, det, 0) is None

