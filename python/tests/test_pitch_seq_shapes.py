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
    The rotation putting the zero step first is keyed on calls per step, so
    it applies at -S1 too once the divider makes a step four calls long --
    see `test_a_divided_step_at_s1_opens_on_the_zero_step` for why.
    """
    from h2g import goatwriter as G
    sid, det = _detect_tables(load_sid(str(CORPUS / "Food_Feud.sid")),
                              lambda *a, **k: None)
    wave = sid.data[det.instr_start + 2 * det.instr_stride + 2]
    assert wave == 0x11
    left, right = G._pitch_seq_entries(sid, det, 2, wave, 1)
    assert left == [0x11] * 8 and right == [0] * 4 + [124] * 4
    left, right = G._pitch_seq_entries(sid, det, 2, wave, 3)
    assert left == [0x11] * 24 and right == [0] * 12 + [124] * 12


def _pair_record(pair, frames_per_step):
    """A synthetic pair-form bit-$10 record: base byte 0, then `pair`."""
    STRIDE, INSTR, IDX, PAIRS, BASE = 8, 0x40, 0x100, 0x110, 0x120
    data = bytearray(0x200)
    data[INSTR + 2] = 0x11
    data[INSTR + 7] = 0x10
    data[IDX] = 0
    data[PAIRS:PAIRS + 2] = bytes(pair)
    data[BASE] = 0
    sid = SidFile(path="fake.sid", data=bytes(data), name="n", author="a",
                  released="r", load_addr=0x1000, subtunes=1)
    det = Detection(instr_start=INSTR, instr_used=1, instr_stride=STRIDE,
                    track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                    pattern_used=0, read_track_version=0)
    det.pitch_seq = D.PitchSeq(index=IDX, pairs=PAIRS, base=BASE, steps=3,
                               frames_per_step=frames_per_step)
    return sid, det


def test_a_divided_step_at_s1_opens_on_the_zero_step():
    """The rotation is keyed on CALLS PER STEP, not on the multiplier alone.

    No corpus file has a divider at -S1 (Food_Feud packs at -S3), so this is
    the synthetic record the decision was traced on: sequence (0, 12, 24),
    `frames_per_step=4`, one C-4 every 96 calls, packed by gt2reloc and traced
    per call in VICE (C:/t/pitch-seq-divider-s1-rotation/synth/report.txt).
    At -S1 the note's first call writes only the `$09` firstwave; entry 0
    lands on call 1, and that is the frame siddump names the attack from
    (siddump.c:436, `$09` is below `$10`). Keyed on the multiplier alone the
    table opened `24 x4` and siddump named every attack C-6; keyed on calls
    per step it opens `0 x4` and names them C-4, as the same record does at
    -S3. With no divider at -S1 a step is one call, and entry 0 is rotated
    to the zero step on its own rule -- see
    `test_at_s1_every_record_opens_on_the_zero_step`.
    """
    from h2g import goatwriter as G
    rel = [_arp_relative(1, s) for s in (0, 12, 24)]
    sid, det = _pair_record((12, 24), 4)
    left, right = G._pitch_seq_entries(sid, det, 0, 0x11, 1)
    assert left == [0x11] * 12
    assert right == [rel[0]] * 4 + [rel[1]] * 4 + [rel[2]] * 4, right
    # -S3: the rotation it always had, twelve calls a step
    left, right = G._pitch_seq_entries(sid, det, 0, 0x11, 3)
    assert right == [rel[0]] * 12 + [rel[1]] * 12 + [rel[2]] * 12, right
    # -S1 without a divider: one call a step, and still opening on the zero
    # step. `_pitch_seq_notes` alone gives `24, 0, 12`, which siddump read as
    # C-6 on every C-4 attack (C:/t/pitch-seq-divider-s1-rotation/synth/
    # siddump_S1_fps1.txt).
    sid, det = _pair_record((12, 24), 1)
    assert G._pitch_seq_notes(sid, det, 0) == [rel[2], rel[0], rel[1]]
    assert (G._pitch_seq_entries(sid, det, 0, 0x11, 1)[1]
            == [rel[0], rel[1], rel[2]])


# Nineteen's -S1 bit-$10 records, as `_pitch_seq_entries` emits them: rotated
# from `_pitch_seq_notes`' `(12, 0, 7)`, `(9, 0, 4)`, `(8, 0, 5)` to open on the
# zero step; records 3 and 14 already opened on it and keep their bytes.
# Records 14 and 15 reach the function called alone but not in Nineteen's
# shipped conversion (a spy on it there saw only 1, 3, 9 and 10), which is
# why 15's `(-6, 0, 0)` rotating here moves none of the file's bytes.
_NINETEEN_S1 = {1: [0x00, 0x07, 0x0C], 3: [0x00, 0x00, 0x18],
                9: [0x00, 0x04, 0x09], 10: [0x00, 0x05, 0x08],
                14: [0x00, 0x00, 0x05], 15: [0x00, 0x00, 0x7A]}


@needs_corpus
def test_at_s1_every_record_opens_on_the_zero_step():
    """With no divider at -S1, entry 0 is the frame siddump names the attack
    from, so it must be the step that leaves the note alone.

    The firstwave call is `$09`, below `$10` (siddump.c:436), so siddump
    names the note from call 1 -- wavetable entry 0 -- and the old rotation
    (the modal step at index 1) put a transposing step there on every -S1
    record whose sequence is `(0, a, b)`. A/B at -t 180, melody before ->
    after: Nineteen (shipped) 97.28 -> 98.05, and forced Bangkok_Knights
    83.73 -> 96.88, IK_plus 88.06 -> 99.89, I_Ball 93.38 -> 96.45,
    Mega_Apocalypse 88.83 -> 93.28, Pygmies_Revenge 89.93 -> 91.74
    (C:/t/pitch-seq-s1-entry0/ab_table.txt, arms A and Cc).

    Corpus-wide over every record the standalone emitter reaches at -S1 on a
    file whose phase steps once a frame, then pinned on the one shipped file.
    """
    from h2g import goatwriter as G
    opened_off_zero = []
    reached = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        if det is None or det.pitch_seq is None:
            continue
        if det.pitch_seq.frames_per_step != 1:
            continue
        for i in range(det.instr_used):
            rec = det.instr_start + i * det.instr_stride
            if rec + 7 >= len(sid.data):
                continue
            got = G._pitch_seq_entries(sid, det, i, sid.data[rec + 2], 1)
            if got is None:
                continue
            reached += 1
            right = got[1]
            if right[0] != 0x00 and 0x00 in right:
                opened_off_zero.append((path.stem, i, right))
    assert reached >= 40, f"the walk reached only {reached} records"
    assert opened_off_zero == []
    sid, det = _detect_tables(load_sid(str(CORPUS / "Nineteen.sid")),
                              lambda *a, **k: None)
    got = {}
    for i in range(det.instr_used):
        rec = det.instr_start + i * det.instr_stride
        out = G._pitch_seq_entries(sid, det, i, sid.data[rec + 2], 1)
        if out is not None:
            assert out[0] == [sid.data[rec + 2]] * 3
            got[i] = out[1]
    assert got == _NINETEEN_S1, got


# ---------------------------------------------------------------------------
# The divided phase is GLOBAL, and `pitch_seq_phases` carries it per
# instrument (task pitch-seq-global-phase-per-instrument). Food_Feud's cell
# never restarts at a note: with the divider honoured a per-note wavetable
# opening on the zero step first moved at attack + 5, while the original
# moves at + 1 (393 of the 466 voice-2 notes under ADSR $29F9 in 180 s) or
# + 3 (73). The 3-frame note at frames 1512-1515 reads 2 ties in the original
# and read 0 in ours. Measured on the clock simulation below, then on the
# conversion (C:/t/pitch-seq-phase/by_instr.py, -t 180, `pitch_seq` forced):
# the 29F9 notes' attack-relative pitch agreement 55.8% -> 64.3%, voice 2's
# ties 3907 -> 5239 against the original's 5139.
# ---------------------------------------------------------------------------
import subprocess                                              # noqa: E402

import pytest                                                  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import fidelity                                                # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")


@needs_corpus
def test_the_divided_clock_is_read_on_food_feud_and_nowhere_else():
    """Every cell's initial byte and both reloads, from the bytes; None on
    every other corpus file, because no other player has a divider and a
    clock assumed rather than read would put a wrong phase on every note."""
    from h2g import goatwriter as G
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        if det is None:
            continue
        clock = G._pitch_seq_clock(sid, det)
        if clock is not None:
            got[path.stem] = clock
    assert got == {"Food_Feud": G.PitchSeqClock(
        divider=1, divider_reload=3, phase=1, phase_reload=1,
        outer=1, inner=1)}, got


@needs_corpus
@needs_siddump
def test_the_simulated_clock_is_re_measured_against_the_original():
    """`siddump -w955d,955e` samples Food_Feud's phase and divider cells after
    every call. The simulation must equal them on every frame, and every
    attack the original plays (all three voices) must land on a call the
    simulated row clock fetches on -- 60 s here, 180 s when it was written
    (C:/t/pitch-seq-phase/model_probe.py: all 8999 frames, 1227 attacks)."""
    from h2g import goatwriter as G
    path = CORPUS / "Food_Feud.sid"
    sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
    clock = G._pitch_seq_clock(sid, det)
    speeds = G.find_song_speeds(sid, det)
    out = subprocess.run([str(fidelity.SIDDUMP), str(path), "-a0", "-t60",
                          f"-v{fidelity.PAL_FLAG}", "-w955d,955e"],
                         capture_output=True, text=True, timeout=180,
                         stdin=subprocess.DEVNULL).stdout
    cells = {}
    for line in out.splitlines():
        c = line.split("|")
        if len(c) >= 8:
            try:
                f = int(c[1])
            except ValueError:
                continue
            phase, div = c[6].split()
            cells[f] = (int(div, 16), int(phase, 16))
    assert len(cells) == 3000
    trace = fidelity.parse_dump(out)
    calls = G._pitch_seq_calls(clock, speeds.frames_for(0), speeds.skip_for(0))
    fetches = set()
    for frame in range(1, 3000):
        _seen, fetched, after = next(calls)
        assert after == cells[frame], frame
        if fetched:
            fetches.add(frame)
    attacks = set()
    for v in trace:
        attacks |= set(v.attack_frames)
    assert len(attacks) > 300
    assert attacks <= fetches, sorted(attacks - fetches)[:10]


def test_the_standalone_phased_block_spells_frame_0_then_the_period():
    """`_pitch_seq_phased_entries`: entry `e` is frame `(e + 1) // m`, so
    `m - 1` entries of the attack frame's own note -- never fewer than one,
    because at -S1 entry 0 is the attack's named frame (task
    mega-0a06-frame-2-pitch-move) -- then the counter's whole period one
    frame per `m` entries, looped onto the period's first entry. Food_Feud's
    two clocked records both carry bit $04 and take the two-stage block;
    Mega_Apocalypse's four `$0A06` records reach this path at -S1
    (tests/test_pitch_seq_flat_clock.py)."""
    from h2g import goatwriter as G
    notes, phases = [0x00, 124], (1, 0, 0, 0, 0, 1, 1, 1)
    left, right = G._pitch_seq_phased_entries(notes, phases, 0x11, 3,
                                              start=5, budget=200)
    assert left == [0x11] * 26 + [0xFF]
    assert right == [0, 0] + [124] * 3 + [0] * 12 + [124] * 9 + [5 + 2]
    left, right = G._pitch_seq_phased_entries(notes, phases, 0x11, 1,
                                              start=5, budget=200)
    assert right == [0, 124, 0, 0, 0, 0, 124, 124, 124, 5 + 1]
    # a cell value with no step behind it declines rather than guessing
    assert G._pitch_seq_phased_entries(notes, (2,) * 8, 0x11, 1, 5, 200) is None
    # and a block that does not fit its budget declines
    assert G._pitch_seq_phased_entries(notes, phases, 0x11, 3, 5, 26) is None
