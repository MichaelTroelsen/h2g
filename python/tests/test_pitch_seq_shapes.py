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
    contain, which a mis-anchored pairs table would not be. Mega Apocalypse's
    are in PLAY order -- its phase counts down, so (0, 5, 8) plays 0, 8, 5
    and rotates to [5, 0, 8] (was pinned [8, 0, 5], the table's order).
    """
    from h2g import goatwriter as G
    want = {
        "Mega_Apocalypse": {4: [5, 0, 8], 5: [3, 0, 8],
                            7: [5, 0, 9], 8: [4, 0, 9]},
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
    """The corpus difference is exactly {Food_Feud, Mega_Apocalypse} -- and
    the static form, a separate fallback, adds exactly Kings_of_the_Beach_intro.

    Pinned as a set rather than a count: a later widening that finds one more
    file and loses one would keep the count and change the answer.
    """
    seqs = {p.stem: D._find_pitch_seq(load_sid(str(p)))
            for p in sorted(CORPUS.glob("*.sid"))}
    found = {k for k, s in seqs.items() if s is not None}
    assert "Food_Feud" in found and "Mega_Apocalypse" in found
    assert {k for k in found if seqs[k].static} == {"Kings_of_the_Beach_intro"}
    assert len(found) == 37


@needs_corpus
def test_the_static_shape_needs_its_gate():
    """Without `AND #$10 / BEQ` in front, the static block's tail -- `LDY abs /
    CLC / LDA abs,X / ADC abs,Y / ASL / TAY / LDA abs,Y` -- is also the tail of
    every pair-form block (After_8 $13F2, Zoolook $43A1, ...). With the gate it
    is one file. The fallback order would keep a pair-form file on its own
    reading either way; the gate is what makes the shape mean bit $10."""
    hits = {p.stem for p in sorted(CORPUS.glob("*.sid"))
            if D.search_file(load_sid(str(p)).data,
                             D.PITCH_SEQ_STATIC_SHAPE) >= 1}
    assert hits == {"Kings_of_the_Beach_intro"}


@needs_corpus
def test_kings_of_the_beach_intro_is_read_as_the_static_form():
    """$1011: `AND #$10 / BEQ / LDY $126E / CLC / LDA $122B,X / ADC $126B,Y /
    ASL / TAY / LDA $1152,Y` -- no index array, no pair copy. The table is the
    ADC's operand ($126B: 00 0C 18), and its length and direction come from
    the phase's update at $107F, `DEC $126E / BPL / LDA #$02 / STA $126E`:
    three steps, counting down."""
    sid = load_sid(str(CORPUS / "Kings_of_the_Beach_intro.sid"))
    assert sid.data[sid.to_offset(0x107F):sid.to_offset(0x107F) + 10] == \
        bytes.fromhex("CE 6E 12 10 05 A9 02 8D 6E 12")
    seq = D._find_pitch_seq(sid)
    assert seq is not None and seq.static and seq.descending
    assert (seq.index, seq.pairs) == (-1, -1)
    assert _addr(sid, seq.base) == 0x126B
    assert sid.data[seq.base:seq.base + 3] == b"\x00\x0c\x18"
    assert seq.steps == 3 and seq.frames_per_step == 1


def test_the_static_form_declines_without_the_phase_update():
    """A static table has no pair to bound it: without the `DEC` reload
    nothing says how long it is, or which way it plays, so it is declined."""
    block = bytes.fromhex("29 10 F0 1B AC 6E 12 18 BD 2B 12 79 6B 12 0A A8 "
                          "B9 52 11")
    reload = bytes.fromhex("CE 6E 12 10 05 A9 02 8D 6E 12")
    load = 0x1000

    def sid_of(image):
        return SidFile(path="fake.sid", data=bytes(image), name="n",
                       author="a", released="r", load_addr=load, subtunes=1)

    image = bytearray(0x400)
    at = sid_of(image).to_offset          # addresses as the player reads them
    image[at(0x1011):at(0x1011) + len(block)] = block
    image[at(0x126B):at(0x126B) + 3] = b"\x00\x0c\x18"
    assert D._find_pitch_seq(sid_of(image)) is None
    image[at(0x107F):at(0x107F) + len(reload)] = reload
    seq = D._find_pitch_seq(sid_of(image))
    assert seq is not None and seq.static and seq.descending
    assert (seq.base, seq.steps) == (at(0x126B), 3)


@needs_corpus
def test_the_blocks_that_are_deliberately_not_matched():
    """Two files have an `AND #$10 / BEQ` block that this cannot represent.

    - ACE_II $E3F7 and Ricochet $9421 copy **one** pair byte and never load the
      phase, so their `ADC base,Y` runs with `Y = 2 * index` -- a constant
      transpose per record. Neither is in `VIBRATO.md`'s `pitchseq` rows.

    Kings_of_the_Beach_intro $1011 was the third -- a static table with no
    index -- and is now read as the static form; see
    `test_kings_of_the_beach_intro_is_read_as_the_static_form`.
    """
    for name, at, note in (
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


def _static(base, steps, descending=False):
    """The static form `_pitch_seq_notes` reads: `static` says the table is
    global at `base`, `steps` long; `descending` that the phase counter
    counts down."""
    return D.PitchSeq(index=-1, pairs=-1, base=base, steps=steps,
                      static=True, descending=descending)


@needs_corpus
def test_the_static_form_reads_kings_of_the_beach_intros_table_in_play_order():
    """Its bit-$10 handler ($1011) adds a GLOBAL table ($126B: 00 0C 18) to
    the note under a phase counter that counts DOWN ($107F: DEC / BPL / LDA
    #2), so the player's order is 24, 12, 0 -- siddump reads 559 frames of
    -12 and 292 of +24 on voice 1 in 60 s and never the rising cycle
    (re-read at v0.5.497: 559 / 292, +12 on 15). Detection fills the form
    now; this pins what the writer does with what detection hands it.
    """
    sid = load_sid(str(CORPUS / "Kings_of_the_Beach_intro.sid"))
    sid, det = _detect_tables(sid, lambda *a, **k: None)
    base = sid.to_offset(0x126B)
    assert sid.data[base:base + 3] == b"\x00\x0c\x18"
    assert det.pitch_seq == _static(base, 3, descending=True)
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


def test_the_static_forms_direction_is_the_phase_counters():
    sid, det, table = _fake((0, 12, 24))
    det.pitch_seq = _static(table, 3)
    assert _pitch_seq_notes(sid, det, 0) in _rotations((0, 12, 24))
    det.pitch_seq = _static(table, 3, descending=True)
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



# --- the frames-per-step divider: Food_Feud's $955E --------------------------

def _hex(*parts):
    return bytes.fromhex(" ".join(parts))


# Food_Feud $9405: `DEC $955D / BPL +5 / LDA #$01 / STA $955D`, the phase reload
# the existing scan already finds.
_PHASE_RELOAD = "CE 5D 95 10 05 A9 01 8D 5D 95"


def test_the_divider_is_read_in_both_spellings():
    """`DEC cell / BPL / LDA #n / STA cell` in front of the phase reload.

    Absolute (Food_Feud $93FB, ten bytes) and zero-page (eight bytes) are two
    instruction lengths, so each has its own start relative to the reload. A
    block whose store names a *different* cell is some other countdown and
    reads 1, as does the `DEX / BMI / JMP` the other 35 corpus files carry.
    """
    cases = (
        ("CE 5E 95 10 0F A9 03 8D 5E 95", 4),    # Food_Feud, verbatim
        ("C6 5E 10 0D A9 03 85 5E", 4),          # the same in zero page
        ("CE 5E 95 10 0F A9 07 8D 5E 95", 8),    # the reload is read, not assumed
        ("CE 5E 95 10 0F A9 03 8D 5F 95", 1),    # store names another cell
        ("C6 5E 10 0D A9 03 85 5F", 1),
        ("CA 30 03 4C 76 90", 1),                # the voice loop's exit
    )
    for before, want in cases:
        data = _hex("EA EA", before, _PHASE_RELOAD, "60")
        at = 2 + len(_hex(before))
        assert data[at] == 0xCE
        assert D._pitch_seq_divider(data, at) == want, before
    # a reload with nothing in front of it reads 1, not an index error
    assert D._pitch_seq_divider(_hex(_PHASE_RELOAD), 0) == 1


@needs_corpus
def test_food_feud_steps_its_phase_once_every_four_frames():
    """$93FB: `DEC $955E / BPL / LDA #$03 / STA $955E` gates the phase `DEC`."""
    sid = load_sid(str(CORPUS / "Food_Feud.sid"))
    off = sid.to_offset(0x93FB)
    assert sid.data[off:off + 10] == _hex("CE 5E 95 10 0F A9 03 8D 5E 95")
    assert sid.data[off + 10:off + 20] == _hex(_PHASE_RELOAD)
    seq = D._find_pitch_seq(sid)
    assert seq is not None and seq.frames_per_step == 4
    # ...and a file with the plain per-frame phase reads 1
    assert _seq("Mega_Apocalypse").frames_per_step == 1
    assert _seq("Trans-Atlantic_Balloon_Challenge").frames_per_step == 1


@needs_corpus
def test_food_feud_is_the_only_corpus_file_with_a_divider():
    """Pinned as the set: exactly {Food_Feud} of the 36 detected files."""
    slow = {p.stem: seq.frames_per_step for p in sorted(CORPUS.glob("*.sid"))
            if (seq := D._find_pitch_seq(load_sid(str(p)))) is not None
            and seq.frames_per_step != 1}
    assert slow == {"Food_Feud": 4}


@needs_corpus
def test_the_standalone_emitter_holds_each_step_frames_per_step_frames():
    """Food_Feud record 2 (`$34`, notes [124, 0]) through `_pitch_seq_entries`.

    A step is `frames_per_step * multiplier` calls: 4 at -S1, 12 at -S3.
    Held one frame it arpeggiated four times too fast -- voice 2 read 7837
    ties against the original's 5139 with `pitch_seq` forced, 3907 with the
    divider honoured (C:/t/pitch-seq-divider/ab_food_feud.txt, v0.5.491).
    The rotation putting the zero step first is keyed on the CALLS a step
    holds, so it applies at -S1 too: entry 0 is the note's first frequency
    write (the new-note call ends `jmp mt_loadregswaveonly`, player.s), and
    keyed on the multiplier alone the -4 step was what every attack read --
    Food_Feud forced to -S1, melody 81.52% against 93.87% calls-keyed and
    93.87% with the option off (C:/t/pitch-seq-s1-rotation/sd_result.txt).
    """
    from h2g import goatwriter as G
    sid, det = _detect_tables(load_sid(str(CORPUS / "Food_Feud.sid")),
                              lambda *a, **k: None)
    wave = sid.data[det.instr_start + 2 * det.instr_stride + 2]
    assert wave == 0x11
    left, right = G._pitch_seq_entries(sid, det, 2, wave, 1)
    assert left == [0x11] * 8 and right == [0] * 4 + [124] * 4


@needs_corpus
def test_the_rotation_is_keyed_on_calls_per_step_not_on_the_multiplier():
    """One call a step is the only unrotated case, whichever factor makes it.

    The same record with its divider taken away: at -S1 a step is one call
    and the modal step stays at index 1 (unchanged for the 35 divider-less
    files); at -S2 it is two calls and rotates, as a divider of 2 at -S1
    does -- the two are one quantity (C:/t/pitch-seq-s1-rotation).
    """
    import dataclasses as dc
    from h2g import goatwriter as G
    sid, det = _detect_tables(load_sid(str(CORPUS / "Food_Feud.sid")),
                              lambda *a, **k: None)
    wave = sid.data[det.instr_start + 2 * det.instr_stride + 2]

    def with_divider(n):
        return dc.replace(det, pitch_seq=dc.replace(det.pitch_seq,
                                                    frames_per_step=n))
    assert G._pitch_seq_entries(sid, with_divider(1), 2, wave, 1)[1] == [124, 0]
    assert G._pitch_seq_entries(sid, with_divider(1), 2, wave, 2)[1] == \
        [0, 0, 124, 124]
    assert G._pitch_seq_entries(sid, with_divider(2), 2, wave, 1)[1] == \
        [0, 0, 124, 124]
    left, right = G._pitch_seq_entries(sid, det, 2, wave, 3)
    assert left == [0x11] * 24 and right == [0] * 12 + [124] * 12


# --- the global phase, carried per instrument (goatwriter.pitch_seq_phases) --
#
# The bit-$10 cell is ONE counter stepped at the end of every play call and
# never restarted at a note, so a note's arpeggio is fixed by its attack's
# call number modulo the cycle. These pin the three readers the per-
# instrument majority is built from -- the cycle, the row clock and the walk
# -- and re-measure the first two against a trace of the original.

import dataclasses                                             # noqa: E402

import pytest                                                  # noqa: E402

from h2g import goatwriter as G                                # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                                # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")

# $93FB-$940E: the divider `$955E` reloads 3, the phase `$955D` reloads 1,
# and both hold 1 in the image -- so the cell reads 1 on calls 0 and 1,
# then 0 for four calls, then 1 for four, and repeats every 8.
FOOD_FEUD_CYCLE = [1, 1, 0, 0, 0, 0, 1, 1]


def _food_feud():
    return _detect_tables(load_sid(str(CORPUS / "Food_Feud.sid")),
                          lambda *a, **k: None)


def _with_byte(sid, addr, value):
    data = bytearray(sid.data)
    data[sid.to_offset(addr)] = value
    return dataclasses.replace(sid, data=bytes(data))


@needs_corpus
def test_food_feud_phase_cycle_is_simulated_from_the_image():
    """The cycle is the two cells' image bytes run through their reloads."""
    sid, det = _food_feud()
    assert G._pitch_seq_phase_cell(sid) == 0x955D
    assert (sid.data[sid.to_offset(0x955D)],
            sid.data[sid.to_offset(0x955E)]) == (1, 1)
    assert G.pitch_seq_phase_cycle(sid, det) == FOOD_FEUD_CYCLE
    # it is the image that sets the phase: move either byte and the cycle
    # turns by exactly that many calls
    assert G.pitch_seq_phase_cycle(_with_byte(sid, 0x955E, 3), det) == \
        FOOD_FEUD_CYCLE[-2:] + FOOD_FEUD_CYCLE[:-2]
    assert G.pitch_seq_phase_cycle(_with_byte(sid, 0x955D, 0), det) == \
        FOOD_FEUD_CYCLE[4:] + FOOD_FEUD_CYCLE[:4]
    # a byte outside its reload's range is not the repeating cycle: declined
    assert G.pitch_seq_phase_cycle(_with_byte(sid, 0x955E, 4), det) is None
    assert G.pitch_seq_phase_cycle(_with_byte(sid, 0x955D, 2), det) is None


@needs_corpus
def test_food_feud_frame_notes_are_the_cycle_read_from_the_residue():
    """Record 2's steps are (0, $7C): the cell's 1 is the pair's first byte."""
    sid, det = _food_feud()
    assert G._pitch_seq_steps(sid, det, 2)[0] == 0
    step = G._pitch_seq_byte(G._pitch_seq_steps(sid, det, 2)[1])
    assert step == 124
    for r in range(8):
        want = [step if FOOD_FEUD_CYCLE[(r + m) % 8] else 0 for m in range(8)]
        assert G.pitch_seq_frame_notes(sid, det, 2, r) == want, r
    # a record without bit $10 has no frame notes
    assert G.pitch_seq_frame_notes(sid, det, 0, 0) is None


def _fetch_calls_by_voice(sid, det, tracks, patterns):
    out = []
    for track in tracks:
        rows = list(G._note_rows(track, patterns))
        calls = G.pitch_seq_fetch_calls(sid, det, 0, rows[-1][0] + 1)
        out.append([(calls[row], instr) for row, instr in rows])
    return out


def _food_feud_walk():
    """(sid, det, tracks, patterns) as build_sng receives them, preset +
    pitch_seq -- the walk reads the FINISHED orderlists."""
    import json
    import h2g.convert as cv
    presets = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = dict(fidelity._preset_opts(presets, "Food_Feud.sid"))
    opts["pitch_seq"] = True
    got = {}
    real = cv.build_sng

    def spy(sid, det, tracks, patterns, *a, **k):
        got.update(sid=sid, det=det, tracks=[list(t) for t in tracks],
                   patterns=[list(p) for p in patterns])
        return real(sid, det, tracks, patterns, *a, **k)

    cv.build_sng = spy
    try:
        cv.convert(CORPUS / "Food_Feud.sid", log=lambda *a, **k: None, **opts)
    finally:
        cv.build_sng = real
    return got["sid"], got["det"], got["tracks"], got["patterns"]


@needs_corpus
def test_food_feuds_rows_land_on_calls_0_3_and_6_and_the_majority_follows():
    """Three 8/3-frame rows are one cycle, so every instrument's attacks
    split near-evenly over residues 0, 3 and 6 -- the majority is right on
    about a third of them, and it names a residue attacks actually land on
    (v0.5.492, 247 s: GT 3 88/80/78 -> 0, GT 4 183/187/189 -> 6)."""
    sid, det, tracks, patterns = _food_feud_walk()
    ticks = G.pitch_seq_fetch_calls(sid, det, 0, 6)
    assert ticks == [3, 6, 8, 11, 14, 16]
    walk = _fetch_calls_by_voice(sid, det, tracks, patterns)
    residues = {c % 8 for voice in walk for c, _ in voice}
    assert residues == {0, 3, 6}
    phases = G.pitch_seq_phases(sid, det, tracks, patterns)
    assert phases[3] == 0 and phases[4] == 6
    # GT 3 and 4 are records 2 and 3, the two `$34` records (lead 0)
    for gt, rec in ((3, 2), (4, 3)):
        assert sid.data[det.instr_start + rec * det.instr_stride + 7] == 0x34


@needs_corpus
def test_food_feud_is_still_the_only_divider_file():
    """`frames_per_step > 1` was the old gate on the walk; it is Food_Feud
    alone, and the walk no longer asks it (see the reader below)."""
    asked = set()
    for p in sorted(CORPUS.glob("*.sid")):
        seq = D._find_pitch_seq(load_sid(str(p)))
        if seq is not None and seq.frames_per_step > 1:
            asked.add(p.stem)
    assert asked == {"Food_Feud"}


# --- where the row clock starts: read from the init, then re-measured -------
#
# `PITCH_SEQ_CLOCK` reads on 43 files; what differs between them is how many
# play calls the init lets pass before the gate first steps.
# `pitch_seq_new_song_calls` reads that count only where the init returns
# straight after `LDA #$4x / STA flag` on every path and calls nothing, the
# new-song path jumps into the phase step, and the PSID play address enters
# the player once per call. These are the 13 files it reads (v0.5.494).

NEW_SONG_READS = {
    "Bangkok_Knights", "Chain_Reaction", "Flash_Gordon", "Food_Feud",
    "Lightforce", "Nineteen", "Pandora", "Shockway_Rider", "Star_Paws",
    "Trans-Atlantic_Balloon_Challenge", "W_A_R", "W_A_R_Preview", "Zoolook",
}
# Where the row ticks from call 1 carry attacks a trace does not put on a
# tick: one instrument each, a late gate or a drum retriggering inside its
# row (voice 2 GT 9 / voice 2 GT 5 / voice 1 GT 4 at subtune 0).
NEW_SONG_REMAINDER = {"Bangkok_Knights", "Nineteen",
                      "Trans-Atlantic_Balloon_Challenge"}


def test_opcode_lengths_are_dis6502s():
    """The reader's instruction lengths are the disassembler's 151 opcodes."""
    import dis6502
    for op in range(256):
        want = (1 + dis6502.MODES[dis6502.OPCODES[op][1]]
                if op in dis6502.OPCODES else 0)
        assert int(G._OPCODE_LENGTHS[op]) == want, hex(op)


def _clock_files():
    for p in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(p))
        if G.PITCH_SEQ_CLOCK.search(sid.data) is not None:
            yield p, _detect_tables(sid, lambda *a, **k: None)


@needs_corpus
def test_the_new_song_count_is_read_on_exactly_these_inits():
    """Read on 13 of the clock files, and each reading is the constant.
    Delta_Mix-E-Load_loader's init calls the player itself (`JSR $C012`),
    and Mr_Meaner's arms a CIA 2 NMI before its `RTS`: both decline."""
    got = {}
    for p, (sid, det) in _clock_files():
        k = G.pitch_seq_new_song_calls(sid)
        if k is not None:
            got[p.stem] = k
    assert set(got) == NEW_SONG_READS
    assert set(got.values()) == {G.PITCH_SEQ_NEW_SONG_CALLS}


def _patched(sid, patches, **fields):
    data = bytearray(sid.data)
    for addr, raw in patches:
        o = sid.to_offset(addr)
        data[o:o + len(raw)] = raw
    return dataclasses.replace(sid, data=bytes(data), **fields)


@needs_corpus
def test_the_reader_declines_an_init_or_play_it_cannot_count():
    """On Food_Feud's own image, one edit at a time: an init that calls the
    player before arming the flag has spent the new-song call itself
    (Delta_Mix-E-Load_loader's shape), and a play wrapper entering the
    player twice, or behind a branch, is not one call per call. The nine
    zero bytes at $9000 hold the wrappers; `JMP $9CEE` at $9009 is the
    PSID init, `LDA #$00 / STA $D417 / LDA #$40 / STA $953D / RTS` there."""
    sid, _ = _food_feud()
    assert G.pitch_seq_new_song_calls(sid) == 1
    jsr_play = bytes.fromhex("200F90" "A9408D3D95" "60")
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [(0x9CEE, jsr_play)])) is None
    once, twice = bytes.fromhex("201490" "60"), bytes.fromhex("201490201490" "60")
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [(0x9000, once)], play_addr=0x9000)) == 1
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [(0x9000, twice)], play_addr=0x9000)) is None
    branch = bytes.fromhex("D001" "60" "201490" "60")
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [(0x9000, branch)], play_addr=0x9000)) is None
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [], play_addr=0)) is None
    # an init leaving the stop bit set, or returning before the flag
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [(0x9CF4, b"\xc0")])) is None
    assert G.pitch_seq_new_song_calls(
        _patched(sid, [(0x9CEE, b"\x60")])) is None


def _attack_misses(sid, det, trace, n, k):
    ticks = set(G.pitch_seq_fetch_calls(sid, det, 0, n, new_song_calls=k))
    return sum(1 for v in trace for a in v.attack_frames
               if a < n and a not in ticks)


@needs_corpus
@needs_siddump
def test_the_new_song_count_is_re_measured_against_each_original():
    """20 s of subtune 0 of every file the reader reads: the row ticks
    started `PITCH_SEQ_NEW_SONG_CALLS` in carry every attack, or -- on the
    three `NEW_SONG_REMAINDER` files -- strictly more attacks than a start
    one call either side. And the declined Delta_Mix-E-Load_loader really
    measures 0: the reader's refusal is not caution about nothing."""
    seconds = 20
    n = seconds * 50
    k = G.PITCH_SEQ_NEW_SONG_CALLS
    for p, (sid, det) in _clock_files():
        if p.stem not in NEW_SONG_READS | {"Delta_Mix-E-Load_loader"}:
            continue
        trace = fidelity.run_siddump(p, seconds, 0, fidelity.SIDDUMP)
        assert sum(len(v.attack_frames) for v in trace) > 10, p.stem
        miss = {j: _attack_misses(sid, det, trace, n, j)
                for j in (k - 1, k, k + 1)}
        if p.stem == "Delta_Mix-E-Load_loader":
            assert miss[k - 1] == 0 < miss[k], miss
        elif p.stem in NEW_SONG_REMAINDER:
            assert 0 < miss[k] < min(miss[k - 1], miss[k + 1]), (p.stem, miss)
        else:
            assert miss[k] == 0 < min(miss[k - 1], miss[k + 1]), (p.stem, miss)


def _walk(name, subtune=0):
    """(sid, det, tracks, patterns, lead) as build_sng receives them."""
    import json
    import h2g.convert as cv
    presets = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = dict(fidelity._preset_opts(presets, f"{name}.sid"))
    opts["pitch_seq"] = True
    got = {}
    real_b, real_l = cv.build_sng, G._wavetable_layout

    def spy(sid, det, tracks, patterns, *a, **k):
        got.update(sid=sid, det=det, tracks=[list(t) for t in tracks],
                   patterns=[list(q) for q in patterns])
        return real_b(sid, det, tracks, patterns, *a, **k)

    def spy_layout(*a, **k):
        got["lead"] = a[8]
        return real_l(*a, **k)
    cv.build_sng, G._wavetable_layout = spy, spy_layout
    try:
        cv.convert(CORPUS / f"{name}.sid", log=lambda *a, **k: None, **opts)
    finally:
        cv.build_sng, G._wavetable_layout = real_b, real_l
    return got


# (file, subtune): every file the widened walk moves, at a subtune whose
# first 60 s play a bit-$10 note (W_A_R's first five do not).
PHASE_RETRACED = [("Flash_Gordon", 0), ("Trans-Atlantic_Balloon_Challenge", 0),
                  ("W_A_R_Preview", 0), ("W_A_R", 5)]


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name,subtune", PHASE_RETRACED)
def test_the_widened_files_phase_is_re_measured_against_the_original(
        name, subtune):
    """On every in-note frame of a bit-$10 record's note that the walk and
    the trace both attack on, the semitone offset from the attack frame is
    the step the cycle names for that call -- at shift 0 on every frame,
    and on under half of them at either other shift. Fetch frames are left
    out, as on Food_Feud: the fetch path skips the effect block."""
    import math
    g = _walk(name)
    sid, det = g["sid"], g["det"]
    cycle = G.pitch_seq_phase_cycle(sid, det)
    period = len(cycle)
    seconds = 60
    n = seconds * 50
    trace = fidelity.run_siddump(CORPUS / f"{name}.sid", seconds, subtune,
                                 fidelity.SIDDUMP)
    ticks = set(G.pitch_seq_fetch_calls(sid, det, subtune, n))
    agree, total = [0] * period, 0
    for v in range(3):
        rows = list(G._note_rows(g["tracks"][3 * subtune + v], g["patterns"]))
        if not rows:
            continue
        calls = G.pitch_seq_fetch_calls(sid, det, subtune, rows[-1][0] + 1)
        named = {calls[r]: ins for r, ins in rows if calls[r] < n}
        attacks = set(trace[v].attack_frames)
        freq, cur, k = [], None, 0
        ev = sorted(trace[v].freq_events)
        for f in range(n):
            while k < len(ev) and ev[k][0] <= f:
                cur = ev[k][1]
                k += 1
            freq.append(cur)
        at = sorted(named)
        for i, a in enumerate(at[:-1]):
            steps = G._pitch_seq_steps(sid, det, named[a] - g["lead"] - 1)
            if steps is None or a not in attacks or not freq[a]:
                continue
            for f in range(a + 1, at[i + 1]):
                if f in ticks or not freq[f]:
                    continue
                off = round(12 * math.log2(freq[f] / freq[a]))
                total += 1
                for s in range(period):
                    b = steps[cycle[(f + s) % period]]
                    agree[s] += off == (b - 0x100 if b >= 0x80 else b)
    assert total >= 40, (name, total)
    assert agree[0] == total, (name, agree, total)
    assert all(2 * x < total for x in agree[1:]), (name, agree, total)


@needs_corpus
def test_build_sng_asks_for_phases_where_the_count_is_read():
    """Preset + pitch_seq over the files the reader reads: frame notes are
    asked on exactly these -- the others phase no two-stage bit-$10 record.
    Nineteen's residue 2 builds the block its rotation already did, so its
    bytes do not move; the corpus byte-hash moves the other four new ones."""
    import json
    from h2g.convert import convert
    presets = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    real = G.pitch_seq_frame_notes
    asked = set()
    try:
        for name in sorted(NEW_SONG_READS):
            def spy(sid, det, i, residue, name=name):
                asked.add(name)
                return real(sid, det, i, residue)
            G.pitch_seq_frame_notes = spy
            opts = dict(fidelity._preset_opts(presets, f"{name}.sid"))
            convert(CORPUS / f"{name}.sid", log=lambda *a, **k: None,
                    **{**opts, "pitch_seq": True})
    finally:
        G.pitch_seq_frame_notes = real
    assert asked == {"Food_Feud", "Flash_Gordon", "Nineteen",
                     "Trans-Atlantic_Balloon_Challenge", "W_A_R",
                     "W_A_R_Preview"}


@needs_corpus
@needs_siddump
def test_the_clock_and_the_cycle_are_re_measured_against_the_original():
    """Two endpoints, from a siddump of the ORIGINAL (15 s):

    * every attack of every voice falls on a call the walk names;
    * on every in-note frame of the two `$34` instruments the pitch sits off
      the attack's exactly where the cycle reads 1 (the attack frame itself
      always sounds the pattern note) -- except on a fetch frame, below.
    """
    import math
    sid, det, tracks, patterns = _food_feud_walk()
    seconds = 15
    cal, _ = fidelity.table_calibration(CORPUS / "Food_Feud.sid", {})
    trace = fidelity.run_siddump(CORPUS / "Food_Feud.sid", seconds, 0,
                                 fidelity.SIDDUMP, calibrate=cal)
    n = seconds * 50
    walk = _fetch_calls_by_voice(sid, det, tracks, patterns)
    ticks = set(G.pitch_seq_fetch_calls(sid, det, 0, n))
    checked, missed = 0, []
    for v, voice in enumerate(trace):
        named = {c: instr for c, instr in walk[v] if c < n}
        # a subset, not equal: a tied row (no gate retrigger) is walked
        # but siddump prints it as a tie, not an attack
        assert set(voice.attack_frames) <= set(named), v
        assert len(voice.attack_frames) > 0.9 * len(named), v
        freq, cur, k = [], None, 0
        ev = sorted(voice.freq_events)
        for f in range(n):
            while k < len(ev) and ev[k][0] <= f:
                cur = ev[k][1]
                k += 1
            freq.append(cur)
        rows = sorted(named)
        for i, a in enumerate(rows[:-1]):
            if named[a] not in (3, 4) or a not in voice.attack_frames:
                continue
            for f in range(a + 1, rows[i + 1]):
                off = round(12 * math.log2(freq[f] / freq[a])) != 0
                checked += 1
                if off != (FOOD_FEUD_CYCLE[f % 8] == 1):
                    missed.append((v, a, f))
    # The fetch path skips the effect block ($9195 `JMP $93DA`), so a row
    # with no note -- a rest inside the held note -- holds the pitch for
    # its one fetch frame: voice 2's 302 in the note from 296. Every miss
    # must be such a frame, and they are rare.
    assert all(f in ticks for _, _, f in missed), missed
    assert checked > 200 and len(missed) * 100 <= checked, (checked, missed)


# --- the pair form's play order: the phase counts DOWN ----------------------
#
# `DEC phase / BPL / LDA #2 / STA phase` gives the cell 2, 1, 0, 2, ..., so
# `ADC base,Y` adds b, a, 0: the cycle is 0, b, a, not the table's 0, a, b.
# Only a record with distinct nonzero a and b can tell the two apart.

def _fake_pair(a, b, dec=True):
    """A pair-form player: the canonical shape at $1010, phase cell $1100,
    index $1180, pairs $1190, base $11A0 (holding 0), one bit-$10 record at
    $1140 whose index is 0 and pair is (a, b). `dec` adds the phase's
    `DEC / BPL / LDA #2 / STA` reload; without it nothing writes the cell."""
    data = bytearray(0x200)
    shape = _hex("29 10 F0 20 B9 80 11 0A A8 B9 90 11 8D A1 11",
                 "B9 91 11 8D A2 11 AC 00 11 18 BD 00 10 79 A0 11 0A A8")
    data[0x10:0x10 + len(shape)] = shape      # search_file reads 0 as a miss
    if dec:
        data[0x60:0x6A] = _hex("CE 00 11 10 05 A9 02 8D 00 11")
    data[0x140 + 2] = 0x41
    data[0x140 + 7] = 0x10
    data[0x180] = 0
    data[0x190:0x192] = bytes((a, b))
    sid = SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                  released="r", load_addr=0x1000, subtunes=1)
    det = Detection(instr_start=0x140, instr_used=1, instr_stride=8,
                    track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                    pattern_used=0, read_track_version=0)
    det.pitch_seq = D.PitchSeq(index=0x180, pairs=0x190, base=0x1A0, steps=3)
    return sid, det


def test_the_pair_forms_play_order_is_the_table_read_downwards():
    sid, det = _fake_pair(4, 7)
    assert G._pitch_seq_phase_cell(sid) == 0x1100
    assert G._pitch_seq_phase_step(sid) == 0x60
    notes = _pitch_seq_notes(sid, det, 0)
    assert notes in _rotations((0, 7, 4)), notes
    assert notes not in _rotations((0, 4, 7)), "direction is the mechanism"
    assert notes == [_arp_relative(1, s) for s in (4, 0, 7)]
    # the same order `pitch_seq_frame_notes` reads off the simulated cell
    cycle = [G._pitch_seq_steps(sid, det, 0)[p] for p in (2, 1, 0)]
    assert [_arp_relative(1, s) for s in cycle] in _rotations((0, 7, 4))


def test_a_phase_nothing_steps_keeps_the_table_order():
    """No `DEC` reload: the direction is unread, so nothing is reversed."""
    sid, det = _fake_pair(4, 7, dec=False)
    assert G._pitch_seq_phase_step(sid) is None
    assert _pitch_seq_notes(sid, det, 0) in _rotations((0, 4, 7))


def test_orders_only_distinct_nonzero_pairs_can_tell_apart_are_unchanged():
    """(0,x,x) and (0,x,0) read the same either way: one rotation apart,
    and the modal rotation lands them on the same bytes."""
    for a, b in ((12, 12), (24, 0), (0, 5)):
        got = _pitch_seq_notes(*_fake_pair(a, b), 0)
        assert got == _pitch_seq_notes(*_fake_pair(a, b, dec=False), 0), (a, b)


@needs_corpus
@needs_siddump
def test_after_8s_arpeggio_plays_zero_b_a_in_the_original():
    """After_8 record 0 is (0, 5, 9). A siddump of the original (30 s) shows
    3-frame cycles of three distinct notes a fifth-plus-fourth apart, and
    every one runs lowest, +9, +5 -- never +5, +9. The emitter's play order
    must be the same cycle."""
    import collections
    import math
    path = CORPUS / "After_8.sid"
    sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
    assert G._pitch_seq_steps(sid, det, 0) == [0, 5, 9]
    assert _pitch_seq_notes(sid, det, 0) in _rotations((0, 9, 5))
    seconds = 30
    trace = fidelity.run_siddump(path, seconds, 0, fidelity.SIDDUMP)
    seen = collections.Counter()
    for voice in trace:
        ev, cur, k, freq = sorted(voice.freq_events), None, 0, []
        for f in range(seconds * 50):
            while k < len(ev) and ev[k][0] <= f:
                cur = ev[k][1]
                k += 1
            freq.append(cur)
        f = 0
        while f + 9 <= len(freq):
            w = freq[f:f + 9]
            if (all(w) and len(set(w[:3])) == 3
                    and all(w[j] == w[j + 3] for j in range(6))):
                lo = w.index(min(w[:3]))
                r = w[lo:lo + 3]
                seen[tuple(round(12 * math.log2(x / r[0])) for x in r[1:])] += 1
                f += 9
            else:
                f += 1
    assert seen[(9, 5)] >= 50, seen
    assert seen[(5, 9)] == 0, seen


# --- the per-note split on bit $10's clock (goatwriter.pitch_seq_splits) ----
#
# The majority residue is right on about a third of Food_Feud's `$34` notes,
# because three 8/3-frame rows are one cycle and the attacks land on 0, 3
# and 6 in near-equal thirds. The split gives each `$34` record a copy per
# minority residue -- the fixed arp's per-note machinery on this clock -- and
# renames every note to the copy its own row's residue selects. These pin it
# on the finished `.sng`, read back through the independent parser.

def _food_feud_split_song():
    """(sid, det, song): Food_Feud converted on its preset + pitch_seq, the
    detection build_sng was handed, and the .sng read back by songview."""
    import json
    import songview
    import h2g.convert as cv
    presets = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = dict(fidelity._preset_opts(presets, "Food_Feud.sid"))
    opts["pitch_seq"] = True
    got = {}
    real = cv.build_sng

    def spy(sid, det, *a, **k):
        got.update(sid=sid, det=det)
        return real(sid, det, *a, **k)

    cv.build_sng = spy
    try:
        sng = cv.convert(CORPUS / "Food_Feud.sid", log=lambda *a, **k: None,
                         **opts)
    finally:
        cv.build_sng = real
    return got["sid"], got["det"], songview.parse_sng(sng)


def _wave_program(table, start, calls):
    """The right column a wavetable program writes on each of `calls`
    calls from 1-based row `start`: a `$FF` row jumps (to its right side)
    in the same call, every other row is one call. Food_Feud's `$34`
    blocks spell every call out, so no delay row is modelled -- one is
    refused rather than misread."""
    out, p = [], start
    while len(out) < calls:
        left, right = table[p - 1]
        if left == 0xFF:
            assert right, "a wave program stopped inside a held note"
            p = right
            continue
        assert not 0x01 <= left <= 0x0F, f"delay row {p}"
        out.append(right)
        p += 1
    return out


def _residue_program(sid, det, rec, residue, calls, multiplier=3):
    """What the original sounds, as right-column bytes, on each call of a
    note of record `rec` attacking on `residue`: the pattern's note on
    frame 0 (the fetch skips the effect), the phase's step after."""
    notes = G.pitch_seq_frame_notes(sid, det, rec, residue)
    return [0 if c // multiplier == 0 else notes[(c // multiplier) % len(notes)]
            for c in range(calls)]


@needs_corpus
def test_food_feud_split_copies_each_34_record_per_minority_residue():
    """GT 3 (votes 88/80/78 on 0/3/6, its own 0) and GT 4 (183/187/189, its
    own 6) each get the other two residues -- and only they: every other
    instrument is a candidate, but its block does not depend on the phase,
    so `_arp_variant_blocks` makes it no copy. Four copies, $F-$12, each the
    source's 25-byte record with only the wave pointer changed."""
    sid, det, tracks, patterns = _food_feud_walk()
    phases = G.pitch_seq_phases(sid, det, tracks, patterns)
    splits, clock, residue_of = G.pitch_seq_splits(sid, det, tracks,
                                                   patterns, phases)
    assert sorted(splits[3]) == [3, 6] and sorted(splits[4]) == [0, 3]
    assert clock[3] == len(FOOD_FEUD_CYCLE)
    _, _, song = _food_feud_split_song()
    assert len(song.instruments) == 18                   # 14 + 4 copies
    fields = ("ad", "sr", "pulse_ptr", "filt_ptr", "vib_ptr", "vib_delay",
              "gatetimer", "firstwave")
    sources = []
    for copy in song.instruments[14:]:
        src = [ins for ins in song.instruments[2:4]
               if all(getattr(ins, f) == getattr(copy, f) for f in fields)]
        assert src and copy.wave_ptr != src[0].wave_ptr, copy.number
        sources.append(src[0].number)
    assert sorted(sources) == [3, 3, 4, 4]


@needs_corpus
def test_food_feud_split_copy_costs_its_attack_rows_and_one_jump():
    """The budget: a copy's loop is the record's own cycle rotated by its
    residue, so it jumps into that loop (`_share_loop_tail(rotate=True)`)
    -- nine attack-side rows and the jump, where a spelled-out block is 34.
    141 -> 181 of the wavetable's 255 rows; four copies of 34 would not
    fit at all."""
    _, _, song = _food_feud_split_song()
    table = song.tables["WTBL"]
    assert len(table) == 141 + 4 * 10
    for copy in song.instruments[14:]:
        rows = table[copy.wave_ptr - 1:copy.wave_ptr - 1 + 10]
        assert [l for l, _ in rows].index(0xFF) == 9, copy.number
        target = rows[9][1]
        assert not copy.wave_ptr <= target < copy.wave_ptr + 10


@needs_corpus
def test_food_feud_every_34_note_plays_its_own_residue():
    """The claim itself, per NOTE: walk the finished orderlists, name each
    note's residue off the row clock (`pitch_seq_fetch_calls`), and run the
    wavetable program of the instrument the note names -- three full
    cycles of it, past every jump -- against what the original sounds for
    that residue. Every non-tie note of the two `$34` families matches; the
    majority alone matched about a third (78.3% of in-note frames at 247 s,
    99.98% with the split -- C:/t/pitch-seq-row-split)."""
    sid, det, song = _food_feud_split_song()
    table = song.tables["WTBL"]
    family = {}                     # GT number -> source record
    for ins in song.instruments:
        rec = (2 if ins.number == 3 else 3 if ins.number == 4 else None)
        if rec is None and ins.number > 14:
            rec = 2 if ins.pulse_ptr == song.instruments[2].pulse_ptr else 3
        if rec is not None:
            family[ins.number] = rec
    period = len(FOOD_FEUD_CYCLE)
    calls = 3 * period * 3
    checked = wrong = 0
    by_residue = {}
    for track in song.tracks:
        rows = list(G._note_rows(track, song.patterns, commands=True))
        clock = G.pitch_seq_fetch_calls(sid, det, 0, rows[-1][0] + 1)
        for row, gt, command in rows:
            if gt not in family or command == G.CMD_TONEPORTA:
                continue
            residue = clock[row] % period
            got = _wave_program(table, song.instruments[gt - 1].wave_ptr,
                                calls)
            want = _residue_program(sid, det, family[gt], residue, calls)
            checked += 1
            wrong += got != want
            by_residue.setdefault(residue, set()).add(gt)
    assert checked > 500 and wrong == 0, (checked, wrong)
    # each residue is played by a different instrument of each family
    assert sorted(by_residue) == [0, 3, 6]
    assert all(len(v) == 2 for v in by_residue.values()), by_residue


def test_a_rotated_loop_is_shared_only_when_asked():
    """`_share_loop_tail(rotate=True)` jumps `k` rows into a closed loop
    that is the block's own rotated by `k`; without `rotate` -- the fixed
    arp split's call, whose bytes must not move -- only an identical loop
    serves, exactly as before."""
    loop = [(0x11, 0), (0x11, 0), (0x11, 124), (0x11, 124)]
    entries = [(0x41, 0)] + loop + [(0xFF, 2)]           # loop rows 2-5
    rotated = loop[1:] + loop[:1]
    block = ([0x41] + [l for l, _ in rotated] + [0xFF],
             [0] + [r for _, r in rotated] + [11])       # laid at row 10
    assert G._share_loop_tail(block, 10, entries) == block
    left, right = G._share_loop_tail(block, 10, entries, rotate=True)
    assert left == [0x41, 0xFF] and right == [0, 3]
    # and the jump plays the rotation: the program from row 10 of the joint
    # table is the block's own
    joint = entries + [(0, 0)] * (9 - len(entries)) + list(zip(left, right))
    alone = entries + [(0, 0)] * (9 - len(entries)) + list(zip(*block))
    assert _wave_program(joint, 10, 13) == _wave_program(alone, 10, 13)


def test_the_lap_walk_on_a_row_clock_returns_it_to_its_first_residue():
    """A loop of two rows on a clock of three residues a cycle of rows
    meets the clock on another residue every lap, so it is walked three
    laps -- `period` bounds the search, and a clock the loop never returns
    to is walked once."""
    two = [0x30, 1, 0, 0, 0x30, 1, 0, 0, 0xFF, 0, 0, 0]
    walk = G._arp_lap_walk([0, 0xFF, 0], [two], None, 8,
                           residue=lambda row: row % 3)
    assert [lap for _, lap, _, _ in walk] == [0, 1, 2]
    walk = G._arp_lap_walk([0, 0xFF, 0], [two], None, 8,
                           residue=lambda row: row % 2)
    assert [lap for _, lap, _, _ in walk] == [0]
    walk = G._arp_lap_walk([0, 0xFF, 0], [two], None, 8,
                           residue=lambda row: row // 2)
    assert [lap for _, lap, _, _ in walk] == [0]


@needs_corpus
def test_the_split_is_a_population_filter_on_the_divider():
    """`PITCH_SEQ_SPLIT_MIN_FRAMES_PER_STEP` keeps it to Food_Feud, the one
    file whose walk is checked note by note. Trans-Atlantic and Nineteen,
    both `--pitch-seq` in their presets, have a readable clock, majority
    phases and minority residues -- and no split."""
    import json
    import h2g.convert as cv
    presets = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    for name in ("Trans-Atlantic_Balloon_Challenge", "Nineteen"):
        opts = dict(fidelity._preset_opts(presets, f"{name}.sid"))
        assert opts.get("pitch_seq"), name
        got = {}
        real = cv.build_sng

        def spy(sid, det, tracks, patterns, *a, **k):
            got.update(sid=sid, det=det, tracks=tracks, patterns=patterns)
            return real(sid, det, tracks, patterns, *a, **k)

        cv.build_sng = spy
        logs = []
        try:
            cv.convert(CORPUS / f"{name}.sid", log=lambda *a, **k:
                       logs.append(" ".join(map(str, a))), **opts)
        finally:
            cv.build_sng = real
        sid, det = got["sid"], got["det"]
        assert det.pitch_seq.frames_per_step == 1
        phases = G.pitch_seq_phases(sid, det, got["tracks"], got["patterns"])
        assert phases, name
        assert G.pitch_seq_splits(sid, det, got["tracks"], got["patterns"],
                                  phases) == ({}, None, None)
        assert not any("pitch-seq split" in line for line in logs), name
