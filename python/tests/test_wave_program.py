"""The byte-code wave program: 29 of 95 files, and nothing emits it.

A listener reported Trans-Atlantic's snare missing. It is GT 3, and its program
begins `81 30` -- the interpreter writes an opcode >= $80 straight to $D404 and
the next byte to $D401, so that is literally "noise at $30xx", which is the 43
onsets the trace shows on voice 2.

Two of these files were already known (ACE II and Auf Wiedersehen Monty, as
`effect_bit80 == "program"`). The other 27 were not, which makes this the most
widespread instrument mechanism the project has found unemitted -- and the first
census of it was wrong by a factor of 29, because the signature was written from
one file's exact operands rather than from the shape.

The gating bit reads too, once anchored on the pointer load rather than scanned
for loosely: $01 in 22 files, $08 in three, $20 in one, $80 in two (by sign,
`BPL`), and one shape unrecognised. In 18 of the 29 the cell the branch tests is
also independently known to be the effect byte, which is what makes this the
instrument's own flag rather than some other state; the other 11 are files whose
effect cell detection cannot locate at all. In these players effect bit $01 selects a wave program where in Warhawk's
dialect it means a drum -- and no file does both, so nothing `--effects` reads
collides with it.
"""
import pathlib

from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402

from h2g.convert import _detect_tables
from h2g.detect import (WAVE_PROGRAM_HOLD, decode_wave_program,
                        find_wave_program)
from h2g.sidfile import load_sid

CORPUS = _CORPUS


def _prog(name, instr):
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                              lambda *a, **k: None)
    base = det.wave_program
    off = base + instr * det.instr_stride
    at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
    return decode_wave_program(sid.data, at)


# --- the decoder, on synthetic programs ------------------------------------

def test_an_opcode_above_the_hold_is_a_waveform_and_an_absolute_pitch():
    """Both bytes go straight to the chip -- $D404 and $D401 -- so the pitch is
    the player's own and has nothing to do with the note being played."""
    assert decode_wave_program(bytes([0x81, 0x30, 0x85]), 0) == [
        ("set", 0x81, 0x30), ("hold", 0, 0)]


def test_an_opcode_below_the_hold_is_a_waveform_and_a_16_bit_step_down():
    got = decode_wave_program(bytes([0x10, 0x00, 0x02, 0x85]), 0)
    assert got == [("slide", 0x10, 0x0200), ("hold", 0, 0)]


def test_a_step_is_subtracted_so_a_large_one_slides_upward():
    """`SEC / LDA lo,X / SBC (ptr),Y` -- $FC00 taken away is $0400 added. The
    decoder reports the operand as written; reading it as unsigned "down" only
    would invert three of Trans-Atlantic's GT 13 steps."""
    got = decode_wave_program(bytes([0x50, 0x00, 0xFC, 0x85]), 0)
    assert got[0] == ("slide", 0x50, 0xFC00)
    assert (0x10000 - got[0][2]) == 0x0400


def test_the_hold_ends_the_program():
    assert WAVE_PROGRAM_HOLD == 0x85
    got = decode_wave_program(bytes([0x85, 0x81, 0x30]), 0)
    assert got == [("hold", 0, 0)]


def test_a_truncated_program_is_cut_rather_than_read_past_the_end():
    """Programs are not length-prefixed, so the only alternative to stopping is
    trusting a byte count nothing states."""
    assert decode_wave_program(bytes([0x81]), 0) == []
    assert decode_wave_program(bytes([0x10, 0x00]), 0) == []


def test_the_step_limit_is_honoured():
    assert len(decode_wave_program(bytes([0x81, 0x30] * 50), 0, limit=6)) == 6


# --- against the real players ----------------------------------------------

@needs_corpus
def test_the_interpreter_is_found_across_the_corpus():
    """29 files, and the first census said one. The signature that found one was
    written from Trans-Atlantic's exact operands; this one is written from the
    fetch-and-hold shape, which is what the players actually share.

    All 29 yield a pointer array. Only 27 also yield a plausible gating bit,
    which is why the gate is not part of the reading at all -- see the comment
    above WAVE_PROGRAM_FETCH."""
    sids = sorted(CORPUS.glob("*.sid"))
    if not sids:
        return
    found = 0
    for path in sids:
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        if find_wave_program(sid)[0] >= 0:
            found += 1
    assert found == 29, f"{found} -- the interpreter's reach changed"


@needs_corpus
def test_the_missing_snare_decodes_to_noise_at_a_fixed_pitch():
    if not CORPUS.is_dir():
        return
    steps = _prog("Trans-Atlantic_Balloon_Challenge", 2)
    assert steps[0] == ("set", 0x81, 0x30), steps[:3]
    # ...then two slides under a released waveform, then more noise pitches
    assert [s[0] for s in steps[:6]] == [
        "set", "slide", "slide", "set", "set", "set"], steps[:6]


@needs_corpus
def test_every_located_program_decodes_to_something():
    """A pointer array that resolves but decodes to nothing would mean the
    array was misidentified."""
    if not CORPUS.is_dir():
        return
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.wave_program < 0 or det.instr_used <= 0:
            continue
        nonempty = 0
        for i in range(det.instr_used):
            off = det.wave_program + i * det.instr_stride
            if off + 1 >= len(sid.data):
                break
            at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
            if at >= 0 and decode_wave_program(sid.data, at, 4):
                nonempty += 1
        assert nonempty, path.name
        checked += 1
    assert checked >= 20, checked


@needs_corpus
def test_the_gate_reads_and_never_guesses():
    """Anchored on the pointer load, not scanned for. The first attempt swept 40
    bytes back from the fetch and returned $01 for 21 files, which looked like
    the drum bit and was dismissed as a mismatch -- it was under-anchored, and
    $01 really is the gate in 13 of them.

    v0.5.227: the walk tries both widths of the `STX save` between the branch
    and the load. Mega Apocalypse stores to zero page where the other 28 store
    absolute, and one byte out it read no gate at all -- the last unread gate
    in the corpus. There are now none, so this test's `seen[0]` is 0 and the
    "reported as unread" path is exercised by the synthetic case below rather
    than by a corpus file.
    """
    if not CORPUS.is_dir():
        return
    from collections import Counter
    seen = Counter()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        at, gate = find_wave_program(sid)
        if at >= 0:
            seen[gate] += 1
    assert sum(seen.values()) == 29
    assert seen[0x01] == 23, dict(seen)
    assert seen[0x08] == 3, dict(seen)
    assert seen[0x20] == 1, dict(seen)
    assert seen[0x80] == 2, dict(seen)
    # ...and no file left with an unread gate.
    assert seen[0] == 0, dict(seen)


@needs_corpus
def test_the_zero_page_store_reads_the_same_gate():
    """Mega Apocalypse, the file the fixed-width step missed.

    `LDA $EC / AND #$01 / BEQ / STX $E4 / LDA $54A3,Y` -- two bytes shorter
    than the absolute form, so the old walk looked for the branch opcode
    inside the `AND`'s operand. Pinned by the bytes rather than by the answer,
    so a future change to the walk that happens to return $01 for the wrong
    reason still fails here.
    """
    if not CORPUS.is_dir():
        return
    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    at, gate = find_wave_program(sid)
    assert gate == 0x01
    # the five instructions above, verbatim, ending at the pointer load
    site = sid.data.index(bytes.fromhex("A5EC2901F04686E4B9"))
    assert site > 0


@needs_corpus
def test_the_gate_never_collides_with_a_bit_effects_already_reads():
    """Bit $01 is a drum in Warhawk's dialect and a wave program here. If one
    file did both, `--effects` would fabricate a drum where the player runs a
    program."""
    if not CORPUS.is_dir():
        return
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.wave_program < 0 or not det.wave_program_gate:
            continue
        if det.wave_program_gate == 0x01:
            assert not det.effect_drum, path.name
        if det.wave_program_gate == 0x04:
            assert not det.effect_arp, path.name


# --- the encoding ----------------------------------------------------------
#
# This test used to assert that goatwriter mentioned none of it, because the
# gating bit was unread. v0.5.186 read the gate and v0.5.187 emits the program.

def test_a_set_opcode_becomes_one_entry_at_an_absolute_note():
    """The player writes $D401 directly and a wavetable names notes, so the
    pitch quantises to a semitone -- inaudible for the noise these opcodes
    mostly carry."""
    from h2g.goatwriter import _wave_byte, _sfx_note_byte
    assert _wave_byte(0x81) == 0x81
    assert 0x81 <= _sfx_note_byte(0x30) <= 0xDF


def test_a_waveform_below_ten_uses_the_inaudible_range():
    """$01-$0F are *delays* in a wavetable. $E0-$EF sets the waveform to $00-$0F
    instead (readme.txt:3.4.1, gplay.c:527), which is the only way to express
    `slide $01` -- and GT 11's program is three of them in a row."""
    from h2g.goatwriter import WAVE_SILENT_BASE, _wave_byte
    assert _wave_byte(0x01) == WAVE_SILENT_BASE | 0x01
    assert _wave_byte(0x10) == 0x10, "a real waveform is written literally"


def test_the_one_value_that_range_cannot_carry_is_zero():
    """`$E0` is the exception, and it is a fact about the *packed* player.

    gt2reloc rewrites the range on the way out (greloc.c:1270-1271): it takes
    the low nibble, then adds `$10` back only if the song uses a wavetable
    delay at all. A song without one therefore ships `$E0` as a literal `$00`,
    which player.s:944 reads as *no wave change* -- the entry writes nothing
    and the previous waveform keeps sounding. Traced: Skate or Die intro's
    GT 7 ends its program on `slide $00`, its packed table carries `00`, and
    its trace holds the `$80` before it for the rest of the note.

    `$18` is the way out: triangle with the **test bit**, which holds the
    oscillator at zero, so it is written by both players and sounds nothing.
    Every other value in the range survives, which is why only the zero one
    moves here -- Nineteen's `$E1` reaches the packed file as `$11` and writes
    the `$01` it means.
    """
    from h2g.goatwriter import (WAVE_SILENT_BASE, WAVE_SILENT_TESTBIT,
                                _wave_byte)
    assert _wave_byte(0x00) == WAVE_SILENT_TESTBIT
    assert _wave_byte(0xF0) == WAVE_SILENT_TESTBIT
    assert not WAVE_SILENT_TESTBIT & 0x01, "the gate stays closed"
    assert WAVE_SILENT_TESTBIT & 0xF0, "...and it is written, not a delay"
    for low in range(1, 0x10):
        assert _wave_byte(low) == WAVE_SILENT_BASE | low


def test_a_speed_entry_is_reused_rather_than_duplicated():
    from h2g.goatwriter import _speed_index
    table = []
    assert _speed_index(table, (0x02, 0x00)) == 1
    assert _speed_index(table, (0x03, 0xC0)) == 2
    assert _speed_index(table, (0x02, 0x00)) == 1
    assert len(table) == 2


@needs_corpus
def test_the_snare_is_emitted_and_lands_on_noise():
    """GT 3's program opens `81 30`, and the emitted block opens on a noise
    waveform with an absolute note near $30xx. Before this, all 43 of its notes
    sounded a triangle."""
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _note_freq, _wavetable_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    speed = []
    left, right = _wavetable_entries(sid, det, 2, True, "gts5", speed, 1,
                                     start=1, budget=30, wave_program=True)
    # Entry 0 is the record's own `+2` -- the note's first frame, which the
    # player writes before it reaches the interpreter at all (v0.5.217, see
    # `_first_frame_entry`). The program itself starts at entry 1.
    assert left[0] == sid.data[det.instr_start + 2 * det.instr_stride + 2]
    assert left[1] == 0x81, "the snare must open on noise"
    assert abs(_note_freq(right[1] - 0x80) - 0x3000) < 0x0300
    assert left[-1] == 0xFF
    # v0.5.203: a slide is one entry, not a waveform plus a portamento command.
    # The two-entry form made the program 2 frames longer than the player's and
    # truncated the closing noise burst from 8 frames to 6 -- see
    # test_a_slide_opcode_costs_one_entry_so_the_program_keeps_its_length. The
    # frame count is what a percussion transient is; 2 frames of pitch movement
    # under a released waveform is not.
    assert 0xF2 not in left and 0xF1 not in left
    assert not speed, "a slide no longer allocates a speed-table entry"


def test_it_is_off_by_default_and_selected_per_song():
    from h2g.convert import convert
    import presets
    assert len(convert(str(pathlib.Path(__file__).resolve().parents[2]
                           / "Commando.sid"), log=lambda m: None)) == 15193
    assert "wave_program" in presets.EXCLUDED_FROM_ALWAYS
    assert "wave_program" in presets.FIDELITY_TOGGLES


def test_a_multispeed_file_holds_each_opcode_for_a_whole_frame():
    """One opcode is one of the player's frames, and a frame is `multiplier`
    play calls (v0.5.234). Refusing the file instead is what kept the largest
    group of the onset census unrendered: 7 of the 9 files whose `$01` records
    open on noise in the original and flat here carry a wave program and pack
    above -S1, so the option was selectable, measured, and inert."""
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wave_program_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    one = _wave_program_entries(sid, det, 2, [], "gts5", 1, 60)
    two = _wave_program_entries(sid, det, 2, [], "gts5", 2, 60)
    three = _wave_program_entries(sid, det, 2, [], "gts5", 3, 60)
    assert one is not None and two is not None and three is not None
    # Every entry but the closing stop gains one call's worth of hold, so the
    # program lasts the same number of *frames* at every -S.
    assert len(two[0]) == len(three[0]) == 2 * len(one[0]) - 2
    # -S2 has no delay value for a single extra call, so the waveform is
    # written again; -S3 spends a delay of m - 2, current for m - 1 calls.
    assert two[0][2:4] == [one[0][1], one[0][1]]
    assert three[0][3] == 1
    assert _wave_program_entries(sid, det, 2, [], "gts2", 1, 60) is None


def test_a_hold_does_not_rewrite_the_pitch_the_opcode_just_set():
    """`$80` on the right is what leaves the opcode's pitch standing.

    The obvious reading is the other way round and it is wrong, because it
    describes the byte AFTER the packer has touched it. `greloc.c:1340-1341`
    does `insertbyte(rtable[c][d] ^ 0x80)` -- "For normal notes, reverse all
    right side high bits" -- so the `.sng` byte and the byte `player.s` tests
    are bit-7 inverses:

        .sng $80 -> packed $00 -> the `bne` at player.s:977 fails -> no write
        .sng $00 -> packed $80 -> `bmi` at mt_wavefreq (player.s:1054-1058)
                                 -> `adc mt_chnnote,x / and #$7f`
                                 -> writes the pattern's own note

    So writing `$00` here re-asserted the pattern's note over a `>= $80`
    opcode's absolute pitch. At `-S2` an opcode is entry+hold, so the pitch
    landed on the frame's first call and was overwritten on its second, and
    siddump -- one sample a frame -- read a flat pitch. Confirmed on bytes
    rather than argued: Ricochet's `.sng` right column and the same run in its
    packed `.sid` differ by exactly bit 7 ($00<->$80, $C2->$42).
    """
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wave_program_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    left, right = _wave_program_entries(sid, det, 2, [], "gts5", 3, 60)
    # The entry after the opcode must be a HOLD, not a command: `$F0`-`$FF` on
    # the left is a jump or a stop, and its right byte is the jump target, not
    # a note. The last opcode in this record is followed by the table's own
    # `$FF` terminator, and counting that as a hold is what the first version
    # of this assertion did.
    absolute = [k for k, (l, r) in enumerate(zip(left, right))
                if l >= 0x10 and r >= 0x80 and k + 1 < len(left)
                and left[k + 1] < 0xF0]
    assert absolute, "no absolute-pitch opcode in this record"
    assert all(right[k + 1] == 0x80 for k in absolute)


def test_the_multiplier_one_encoding_is_unchanged():
    """The lead now comes from `_first_frame_lead` rather than being written
    out here; at -S1 that has to be the same byte pair it always was, or this
    is not a multispeed fix but a rewrite of every wave-program file."""
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wave_program_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    left, right = _wave_program_entries(sid, det, 2, [], "gts5", 1, 60)
    assert (left[0], right[0]) == (0x11, 0x00)
    assert len(left) == 14


# --- v0.5.203: the overshoot ------------------------------------------------

@needs_corpus
def test_a_slide_opcode_costs_one_entry_so_the_program_keeps_its_length():
    """The player runs one opcode per frame. A portamento needs a command entry
    of its own and a wavetable spends a call on it, so a two-entry slide made
    the program longer than the player's and ran everything after it late: on
    the snare, the closing noise burst came out 6 frames instead of 8.
    """
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wavetable_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    speed: list = []
    left, _right = _wavetable_entries(sid, det, 2, True, "gts5", speed, 1,
                                      start=1, budget=30, wave_program=True)
    steps = _prog("Trans-Atlantic_Balloon_Challenge", 2)
    opcodes = len([s for s in steps if s[0] != "hold"])
    # one entry per opcode, plus the note's own first frame ahead of the
    # program (v0.5.217), the waveform restore, and the stop
    assert len(left) == opcodes + 3, (len(left), opcodes)
    assert not speed, "a slide no longer allocates a speed-table entry"


@needs_corpus
def test_the_stored_waveform_is_restored_before_the_program_stops():
    """The program's end restores the cell the `< $80` opcodes own.

    `$85` does not freeze the last waveform. The two opcode kinds write
    different cells -- IK+ `$E348`: `>= $80` stores to `$E5E7,X`, the one the
    per-frame writer copies to `$D404`, and `< $80` stores to `$E58F,X`, the
    voice's *stored* waveform -- and the hold jumps to `$E44C`, which is
    `LDA $E58F,X / AND gate,X / STA $E5E7,X`. So the voice reverts to the last
    `< $80` opcode's waveform, not to the record's `+2`.

    Holding the program's last value instead let Trans-Atlantic's snare run
    30, 54 and 78 frames where the original's runs are 8 (v0.5.203, and that
    much was right); restoring `+2` was the wrong value for it, worth `wave`
    on 16 files at a mean +1.2pp once corrected.
    """
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wavetable_entries, _wave_byte
    from h2g.detect import decode_wave_program
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    left, _r = _wavetable_entries(sid, det, 2, True, "gts5", [], 1,
                                  start=1, budget=30, wave_program=True)
    rec = det.instr_start + 2 * det.instr_stride
    off = det.wave_program + 2 * det.instr_stride
    at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
    stored = sid.data[rec + 2]
    for kind, wave, _arg in decode_wave_program(sid.data, at):
        if kind == "hold":
            break
        if kind != "set":
            stored = wave
    assert left[-1] == 0xFF
    assert left[-2] == _wave_byte(stored & 0xFE), [hex(x) for x in left[-3:]]
    assert not left[-2] & 0x80, "the restore must not itself be noise"
    assert left[-3] & 0x80, "...and it must follow the program's noise"


@needs_corpus
def test_ik_plus_restores_the_opcode_that_stored_the_cell():
    """The file that separates the two readings, because its program never
    ends on a `< $80` opcode: `81 11 40 80 80 80 80 80`. The stored cell is
    the `$40` opcode 2 left there, and the original plays three frames of it
    before the note ends -- `11 81 11 40 80 80 80 80 80 40 40 40`.
    """
    from h2g.goatwriter import _wavetable_entries
    sid, det = _detect_tables(load_sid(str(CORPUS / "IK_plus.sid")),
                              lambda *a, **k: None)
    left, _r = _wavetable_entries(sid, det, 6, True, "gts5", [], 1,
                                  start=1, budget=30, wave_program=True,
                                  lead=0)
    rec = det.instr_start + 6 * det.instr_stride
    assert sid.data[rec + 2] == 0x11, "the record's own waveform is triangle"
    assert left[-2] == 0x40, [hex(x) for x in left]


@needs_corpus
def test_a_program_ending_on_no_waveform_ends_silent():
    """Skate or Die intro's GT 7 and Arcade Classics' GT 3 both end on
    `slide $00`, and the original is silent from that frame to the end of the
    note. Both the opcode and the restore have to say so, and `$E0` does not
    reach the packed player -- see the zero-value test above."""
    from h2g.goatwriter import WAVE_SILENT_TESTBIT, _wavetable_entries
    for name, rec_i in (("Skate_or_Die_intro", 6), ("Arcade_Classics", 2)):
        sid, det = _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                                  lambda *a, **k: None)
        left, _r = _wavetable_entries(sid, det, rec_i, True, "gts5", [], 1,
                                      start=1, budget=30, wave_program=True,
                                      lead=0)
        assert left[-1] == 0xFF
        assert left[-2] == WAVE_SILENT_TESTBIT, (name, [hex(x) for x in left])
        assert left[-3] == WAVE_SILENT_TESTBIT, (name, [hex(x) for x in left])


def test_the_listening_confirmation_is_recorded_with_its_reason():
    """`fidelity_better` scores the fixed program as worse, structurally: its
    `finds_noise` test requires the reference to have no audible noise, and this
    file has plenty from another instrument -- a per-file test for a per-
    instrument defect. The mirror of FIDELITY_VETOED records the listening
    verdict instead of hand-editing generated presets.json."""
    import presets
    confirmed = presets.FIDELITY_CONFIRMED[
        "Trans-Atlantic_Balloon_Challenge.sid"]
    assert "wave_program" in confirmed
    # v0.5.208: the sfx_drum veto is retired -- the listener reported no audible
    # difference once the snare existed and the burst had its two pitches, and
    # the oscillation scorer selects the setting on its own.
    #
    # v0.5.209: the corpus --fidelity run confirms sfx_drum and pitch_seq are
    # now selected independently, so both are trimmed from here -- only
    # wave_program still needs the hand-recorded measurement.
    assert "sfx_drum" not in confirmed
    assert "pitch_seq" not in confirmed
    assert confirmed == {"wave_program"}
    # FIDELITY_VETOED is no longer required to be empty: the same run found
    # Dragons_Lair_Part_II's subtune-correspondence bug (its init routine
    # remaps subtune 0 to our subtune 9) had invalidated its pitch_seq
    # measurement, an unrelated veto reason from the retired listening one.
    assert presets.FIDELITY_VETOED == {
        "Dragons_Lair_Part_II.sid": {"pitch_seq"}}


def test_the_budget_counts_the_hold_entry_too():
    """A program that fills the table must not overrun its budget by the hold
    entries: the caller reserves five entries for every *later* record, and
    that reservation is the only thing making the variable-length layout safe.
    The guard counted one entry per opcode when an opcode now costs two."""
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import _wave_program_entries
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a, **k: None)
    for budget in range(5, 30):
        for mult in (1, 2, 3, 5):
            got = _wave_program_entries(sid, det, 2, [], "gts5", mult, budget)
            if got is not None:
                assert len(got[0]) <= budget, (budget, mult, len(got[0]))
