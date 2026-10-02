"""Effect bit $40's fixed attack pitch is read from the handler's own operand.

`detect._find_fixed_pitch_index` reads the `LDA idx,Y` inside the bit-$40
handler (`BIT effect / BVC / LDA counter,X / BEQ / DEC counter,X / LDA idx,Y
/ JMP fetch`) and `goatwriter._fixed_attack_note` decodes the record's byte
in that array through the player's note table. Through v0.5.486 the note
index was taken from `det.wave_program` instead -- an array 16 corpus files
with `$40` records do not have, so none of them sounded the pitch (Food
Feud's voice 3: 36 ties against the original's 1396) -- and one After 8
reads four bytes away from the handler's. The pins below are the four
readings the reach was measured on: Food Feud (no wave program at all),
Trans-Atlantic (the file the old reading was derived on, where both agree),
After 8 (where they disagree and the trace sounds the handler's byte) and
Powerplay Hockey (two players in one file; the anchored scan resolves the
operand against the selected copy's own records).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import dataclasses

from corpus import CORPUS, needs_corpus
from h2g.detect import detect, find_wave_program
from h2g.goatwriter import WAVE_NOTE_ABS, _fixed_attack_note
from h2g.sidfile import find_freq_table, load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-",
              "A#", "B-"]


def _name(note_byte: int) -> str:
    n = note_byte - WAVE_NOTE_ABS
    return f"{NOTE_NAMES[n % 12]}{n // 12}"


def _load(name: str, engine: int = 0):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    det = detect(sid, lambda _m: None, engine=engine)
    return sid, det


def _index_byte(sid, det, i: int) -> int:
    return sid.data[det.fixed_pitch_index + i * det.instr_stride]


@needs_corpus
def test_food_feud_reads_95eb_and_record_0_is_d_sharp_5():
    """The file the defect was found on. `LDA $95EB,Y` at $93BD; record 0's
    byte there is $3F = 63, and `freqtable[63]` is $295E -- the frequency the
    original writes on the noise frame of every voice-3 hit. It has no
    byte-code wave program, so the old reading returned None on every record.
    """
    sid, det = _load("Food_Feud")
    assert det.effect_bit40
    assert det.wave_program < 0
    assert sid.to_address(det.fixed_pitch_index) == 0x95EB
    assert _index_byte(sid, det, 0) == 63
    table = find_freq_table(sid)
    at = sid.to_offset(table.addr) + 2 * 63
    assert sid.data[at] | sid.data[at + 1] << 8 == 0x295E
    note = _fixed_attack_note(sid, det, 0)
    assert note == WAVE_NOTE_ABS + 63
    assert _name(note) == "D#5"


@needs_corpus
def test_food_feud_two_stage_drum_gets_g_sharp_4():
    """Record 8 (instrument 9 in the editor): effect $65, no $80. Its second
    stage sounds G#4 in the original -- 648 of voice 0's 758 missing ties --
    and the byte at $95EB + 8 * 8 is 56.
    """
    sid, det = _load("Food_Feud")
    rec7 = det.instr_start + 8 * det.instr_stride + 7
    assert sid.data[rec7] == 0x65
    assert _index_byte(sid, det, 8) == 56
    assert _name(_fixed_attack_note(sid, det, 8)) == "G#4"


@needs_corpus
def test_food_feud_records_without_the_bit_get_nothing():
    """Per record, not per file -- the Thundercats rule."""
    sid, det = _load("Food_Feud")
    with_bit = {i for i in range(det.instr_used)
                if sid.data[det.instr_start + i * det.instr_stride + 7] & 0x40}
    assert with_bit == {0, 8, 9, 10}
    for i in range(det.instr_used):
        got = _fixed_attack_note(sid, det, i)
        assert (got is not None) == (i in with_bit), i


@needs_corpus
def test_trans_atlantic_agrees_with_the_wave_program_array():
    """The file the old reading was derived on: `$116B,Y`, record 1's byte
    $34 = 52, `freqtable[52]` = $15EB on 226 of 226 frames. The handler
    operand and `wave_program` name the same array here, so the reading
    this file pinned is unchanged.
    """
    sid, det = _load("Trans-Atlantic_Balloon_Challenge")
    assert sid.to_address(det.fixed_pitch_index) == 0x116B
    assert det.fixed_pitch_index == det.wave_program
    assert _index_byte(sid, det, 1) == 52
    assert _fixed_attack_note(sid, det, 1) == WAVE_NOTE_ABS + 52


@needs_corpus
def test_after_8_prefers_the_handler_operand_over_wave_program():
    """`LDA $1704,Y` -- record +12 -- where `wave_program` is $1700, +8. The
    +12 byte is 60 on all four `$40` records and the original sounds note 60
    (C-5, $22A0) 914 times in 180 s; the +8 bytes (0, 0, 1, 2) never sound.
    """
    sid, det = _load("After_8")
    assert sid.to_address(det.fixed_pitch_index) == 0x1704
    assert sid.to_address(det.wave_program) == 0x1700
    assert det.fixed_pitch_index == det.instr_start + 12
    assert det.fixed_pitch_index != det.wave_program
    for i in (0, 12, 13, 14):
        assert _index_byte(sid, det, i) == 60
        assert _name(_fixed_attack_note(sid, det, i)) == "C-5"


@needs_corpus
def test_powerplay_hockey_resolves_against_the_selected_player():
    """Two copies of the player in one file. The bit-$40 handler is at $477D
    and tests the $4998 cell -- the effect byte of the instrument table at
    $4A00 that detection selects (engine 0, the presets' engine) -- and
    reads `$4A08,Y`, that table's +8. Through v0.5.486 `wave_program` was
    read file-wide and returned $3C00, the array of the OTHER copy at $3BA0
    (its fetch at $3975 comes first in the file); record 3's byte there
    (141) is past the note table, so the old reading emitted nothing. The
    handler's byte is 65, and the engine-scoped `find_wave_program` now
    names the same $4A08 array -- the two readings agree on this file too.
    """
    sid, det = _load("Powerplay_Hockey_USA_vs_USSR", engine=0)
    assert sid.to_address(det.instr_start) == 0x4A00
    assert sid.to_address(det.fixed_pitch_index) == 0x4A08
    assert det.fixed_pitch_index == det.instr_start + 8
    assert sid.to_address(det.wave_program) == 0x4A08
    assert det.wave_program == det.fixed_pitch_index
    assert _index_byte(sid, det, 3) == 65
    # Index 65 of a table 0.70 semitones flat ($2CC0) rounds to Goattracker's
    # E-5 ($2BF0), not F-5 ($2E8D): the nearest-note rule of
    # `_freq_table_note`, not a reading of the wrong byte.
    assert _name(_fixed_attack_note(sid, det, 3)) == "E-5"


@needs_corpus
def test_powerplay_hockeys_other_player_is_declined_not_guessed():
    """Anchored on the selected copy's effect cell, the scan finds no handler
    for the $3BA0 copy (the file holds one `BIT/BVC` handler and it tests
    the $4A00 copy's cell), so engine 1 gets -1 rather than the other
    engine's array. Its wave program, though, is its own: the $3975 fetch
    names $3C00, one row past the $3BA0 table's 12 eight-byte records.
    """
    sid, det = _load("Powerplay_Hockey_USA_vs_USSR", engine=1)
    assert sid.to_address(det.instr_start) == 0x3BA0
    assert det.fixed_pitch_index == -1
    assert sid.to_address(det.wave_program) == 0x3C00
    assert det.wave_program == det.instr_start + 12 * det.instr_stride


@needs_corpus
def test_powerplay_hockeys_wave_program_is_scoped_to_the_selected_player():
    """`find_wave_program` picks, among a file's `WAVE_PROGRAM_FETCH` sites,
    the one whose gate block names the selected table's effect cell
    (`_wave_program_fetch_site`). Powerplay has two: $3975 (cue engine,
    `LDA $3B51 / AND #$01 / BEQ`, array $3C00) and $471D (tune engine,
    `LDA $4998 / AND #$01 / BEQ`, array $4A08). Without a detection the
    reading is file-wide and returns the first, which is what it always
    did; with one it returns the selected engine's, and both gates read
    $01.
    """
    sid, det0 = _load("Powerplay_Hockey_USA_vs_USSR", engine=0)
    _, det1 = _load("Powerplay_Hockey_USA_vs_USSR", engine=1)
    assert find_wave_program(sid) == (sid.to_offset(0x3C00), 0x01)
    assert find_wave_program(sid, det1) == (sid.to_offset(0x3C00), 0x01)
    assert find_wave_program(sid, det0) == (sid.to_offset(0x4A08), 0x01)
    # What the scoping changes in the output: nothing, on this file. None
    # of the tune engine's 20 records carries the $01 gate, so
    # `_wave_program_entries` emits no program under engine 0 whichever
    # array it is handed; the cue engine's records 2 and 6 do, and their
    # pointers ($3B74, $3B8D) name programs inside the file. The fix is to
    # the reading, so that the record is right before a consumer is.
    gated = [i for i in range(det0.instr_used)
             if sid.data[det0.instr_start + i * det0.instr_stride + 7]
             & det0.wave_program_gate]
    assert gated == []
    gated = [i for i in range(det1.instr_used)
             if sid.data[det1.instr_start + i * det1.instr_stride + 7]
             & det1.wave_program_gate]
    assert gated == [2, 6]
    for i in gated:
        off = det1.wave_program + i * det1.instr_stride
        ptr = sid.data[off] | sid.data[off + 1] << 8
        assert ptr in (0x3B74, 0x3B8D)
        assert 0 <= sid.to_offset(ptr) < len(sid.data)


@needs_corpus
def test_wave_program_is_the_fallback_when_the_handler_was_not_read():
    """A Detection with `fixed_pitch_index` unset still reads `wave_program`,
    and one with neither reads nothing.
    """
    sid, det = _load("Trans-Atlantic_Balloon_Challenge")
    want = _fixed_attack_note(sid, det, 1)
    assert want is not None
    only_wp = dataclasses.replace(det, fixed_pitch_index=-1)
    assert _fixed_attack_note(sid, only_wp, 1) == want
    neither = dataclasses.replace(det, fixed_pitch_index=-1, wave_program=-1)
    assert _fixed_attack_note(sid, neither, 1) is None


@needs_corpus
def test_the_handler_operand_is_preferred_when_the_two_disagree():
    """The After 8 decision, stated as a rule: where both arrays exist the
    handler's wins, so pointing `fixed_pitch_index` at `wave_program` on
    After 8 changes the emitted note.
    """
    sid, det = _load("After_8")
    handler = _fixed_attack_note(sid, det, 0)
    wp = dataclasses.replace(det, fixed_pitch_index=det.wave_program)
    assert _fixed_attack_note(sid, wp, 0) != handler
    assert _fixed_attack_note(sid, wp, 0) == WAVE_NOTE_ABS + 0


@needs_corpus
def test_the_index_array_lies_inside_the_records_span_in_every_file():
    """`+8` in the 8-byte-record dialect is the next record's first byte --
    the array is interleaved with the records, one byte per stride -- so it
    must lie within instr_start .. instr_start + used * stride in every file
    it is read from, and past the file in none.
    """
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, lambda _m: None)
        except Exception:                                  # noqa: BLE001
            continue
        if det.fixed_pitch_index < 0:
            continue
        assert det.effect_bit40, path.name
        last = det.fixed_pitch_index + (det.instr_used - 1) * det.instr_stride
        assert 0 <= det.fixed_pitch_index < len(sid.data), path.name
        assert last < len(sid.data), path.name


def test_a_long_fixed_pitch_attack_folds_into_the_budget():
    """Reaching sixteen more files reached attacks the spelled-out form
    cannot afford: Delta Mix-E-Load's ten-call attack wanted 12 entries of
    a five-entry budget (`tests/test_instrument_bound.py`). Over budget the
    calls fold into one delay carrying the fixed note, and the timeline the
    packed player would see still holds that pitch on every call of the
    attack -- entry 0 writes it, the delay writes nothing until its final
    call, and that call writes the same byte.
    """
    from h2g.goatwriter import _two_stage_entries
    from test_call_rate import wave_timeline

    note = WAVE_NOTE_ABS + 63
    spelled = _two_stage_entries(0x41, 0x81, 10, 1, attack_note=note,
                                 budget=64)
    folded = _two_stage_entries(0x41, 0x81, 10, 1, attack_note=note,
                                budget=5)
    assert len(spelled[0]) == 13           # the frame-0 lead, ten calls, tail
    assert len(folded[0]) <= 5
    for left, right in (spelled, folded):
        seen = wave_timeline(left, right, calls=11)
        assert seen[0][1] == 0x41            # frame 0: the record's own +2
        assert all(w == 0x81 and n == note for _, w, n in seen[1:11]), (
            left, right)
    # Wherever the budget allows it, the spelled-out form is unchanged.
    assert _two_stage_entries(0x41, 0x81, 10, 1, attack_note=note,
                              budget=13) == spelled


def test_the_fixture_has_no_such_handler():
    """Commando does not test bit $40, so nothing here can reach it -- which
    is what keeps the byte-exact fixture byte-exact.
    """
    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    det = detect(sid, lambda _m: None)
    assert not det.effect_bit40
    assert det.fixed_pitch_index == -1
    assert all(_fixed_attack_note(sid, det, i) is None
               for i in range(max(det.instr_used, 0)))


@needs_corpus
def test_detects_own_freq_table_call_is_anchored_on_the_selected_engine():
    """`detect()`'s own `det.freq_table = find_freq_table(sid)` used to call
    with no `near`, unlike `fidelity.engine_freq_table`'s re-derivation of
    the same table, which anchors on `(det.pattern_lo, det.instr_start)`.
    Blind, both engines land on the longest run -- Powerplay Hockey's tune
    table at $4895 (run 96) -- even for engine 1, whose own player is the
    OTHER table, at $3A36 (run 95, one entry short of winning the blind
    tie-break). Anchored the way `engine_freq_table` already is, engine 0's
    own pattern pointers sit near $4895 and engine 1's near $3A36, so the two
    engines now read two different tables -- the property a synthetic
    two-table file would exist to prove, except Powerplay already is one.
    """
    sid, det0 = _load("Powerplay_Hockey_USA_vs_USSR", engine=0)
    _, det1 = _load("Powerplay_Hockey_USA_vs_USSR", engine=1)
    assert det0.freq_table.addr == 0x4895
    assert det1.freq_table.addr == 0x3A36
    assert det0.freq_table.addr != det1.freq_table.addr
    # Neither table carries a shift, so this file's own conversion bytes do
    # not move -- the corpus byte-hash covers every other file.
    assert det0.note_base == 0 and det1.note_base == 0


# --- The fixed pitch is HELD where the player's vibrato never writes ---------
#
# Sanxion's handler past the countdown, `$B40B`: `LDA $B571,Y / BNE $B421`,
# record +5 -- the vibrato byte -- so a record carrying vibrato gets no
# `LDA note,X` restore, and only the vibrato writes the frequency after the
# attack. Its vibrato is duration-gated (`$B257 ... CMP #$03 / BCC`), so a
# note shorter than three rows is never written again: the original holds
# C#6 ($49B8) from N+1 to the next attack on 60 of 60 voice-1 and 22 of 22
# voice-3 six-frame notes, where the conversion wrote the note back at N+2.
# Long notes vibrate around the note from N+2, so the instrument keeps the
# restore and the short notes are pointed at a held copy
# (C:/t/sanxion-c-sharp-6-hold, 2026-10-01).

def test_the_held_attack_keeps_the_fixed_pitch_where_the_restore_drops_it():
    """`hold_attack` changes one byte: the second stage's right side, `$00`
    (the played note) -> `$80` (leave the frequency alone). Read through
    gplay's loop, the held program still sounds the fixed note on every call
    after the attack; the restore writes the played note on the third."""
    from h2g.goatwriter import WAVE_NOTE_KEEP, _two_stage_entries
    from test_call_rate import wave_timeline

    c_sharp_6 = WAVE_NOTE_ABS + 73
    restore = _two_stage_entries(0x17, 0x17, 1, 1, attack_note=c_sharp_6)
    held = _two_stage_entries(0x17, 0x17, 1, 1, attack_note=c_sharp_6,
                              hold_attack=True)
    assert restore == ([0x17, 0x17, 0x17, 0xFF], [0x00, c_sharp_6, 0x00, 0x00])
    assert held == ([0x17, 0x17, 0x17, 0xFF],
                    [0x00, c_sharp_6, WAVE_NOTE_KEEP, 0x00])
    notes = [n for _, _, n in wave_timeline(*held, calls=8)]
    assert notes[0] == 0x00 and all(n == c_sharp_6 for n in notes[1:]), notes
    notes = [n for _, _, n in wave_timeline(*restore, calls=8)]
    assert notes[1] == c_sharp_6 and notes[2] == 0x00, notes
    # No fixed pitch, nothing to hold: the flag is inert.
    assert (_two_stage_entries(0x41, 0x81, 2, 1, hold_attack=True)
            == _two_stage_entries(0x41, 0x81, 2, 1))


@needs_corpus
def test_sanxions_handler_yields_to_the_vibrato_byte():
    """The branch is read out of the handler, not assumed: Sanxion's
    `LDA $B571,Y / BNE` at $B40B is record +5, the same offset detection
    found the vibrato at. Go Go Dash's family tests a per-voice cell
    (`LDA abs,X`) there instead, which is not this rule."""
    from h2g.goatwriter import _fixed_pitch_yield_field

    sid, det = _load("Sanxion")
    at = sid.to_offset(0xB40B)
    assert bytes(sid.data[at:at + 4]) == bytes((0xB9, 0x71, 0xB5, 0xD0))
    assert sid.to_address(det.instr_start) == 0xB56C
    assert _fixed_pitch_yield_field(sid, det) == 5 == det.vibrato_offset
    assert det.vibrato_gate.form == "duration" and det.vibrato_gate.gate == 3
    sid, det = _load("Go_Go_Dash")
    assert det.fixed_pitch_index >= 0
    assert _fixed_pitch_yield_field(sid, det) is None


@needs_corpus
def test_sanxions_short_attack_notes_hold_c_sharp_6():
    """End to end, under the shipped presets. Instrument 14 (record 13,
    effect $44, vibrato byte $10) keeps its own note / C#6 / note program --
    the long notes vibrate around the note -- and a second block holds C#6
    on the third step. Every `CMD_SETWAVEPTR` in the song points at that
    block, sits on a note row of instrument 14 no longer than the gate, and
    no longer note of it carries one. Fails if the held step restores the
    note (`$00`) or if the pass stops pointing short notes at it."""
    import json

    import fidelity
    import songview as SV
    from h2g.convert import convert
    from h2g.goatwriter import (CMD_SETWAVEPTR, GT_REST, WAVE_NOTE_KEEP,
                                _entry_instruments)

    doc = json.loads((REPO_ROOT / "presets.json").read_text())
    blob = convert(str(CORPUS / "Sanxion.sid"), log=lambda _m: None,
                   **fidelity._preset_opts(doc, "Sanxion.sid"))
    song = SV.parse_sng(blob)
    wtbl = song.tables["WTBL"]
    ins = song.instruments[13]
    assert ins.name == "0F:10-00-44"
    c_sharp_6 = WAVE_NOTE_ABS + 73
    own = wtbl[ins.wave_ptr - 1:ins.wave_ptr + 3]
    assert own == [(0x17, 0x00), (0x17, c_sharp_6), (0x17, 0x00), (0xFF, 0x00)]

    entry = _entry_instruments(song.tracks, song.patterns)
    pointed, short, long_ = set(), 0, 0
    for number, pat in enumerate(song.patterns):
        held = entry.get(number, set())
        live = next(iter(held)) if len(held) == 1 else 0
        for k in range(0, len(pat) - 3, 4):
            if pat[k + 1]:
                live = pat[k + 1]
            if not 0x60 <= pat[k] <= 0xBC:
                assert pat[k + 2] != CMD_SETWAVEPTR, (number, k)
                continue
            end = k + 4
            while end + 3 < len(pat) and pat[end] == GT_REST and not pat[end + 1]:
                end += 4
            if pat[k + 2] == CMD_SETWAVEPTR:
                assert live == 14, (number, k)
                assert (end - k) // 4 <= 3, (number, k)
                pointed.add(pat[k + 3])
                short += 1
            elif live == 14 and (end - k) // 4 > 3:
                long_ += 1
    assert short > 0 and long_ > 0
    assert len(pointed) == 1
    start = pointed.pop()
    block = wtbl[start - 1:start + 3]
    assert block == [(0x17, 0x00), (0x17, c_sharp_6), (0x17, WAVE_NOTE_KEEP),
                     (0xFF, 0x00)], block


def test_the_fixture_gets_no_held_attack():
    """Commando's player has no bit-$40 handler, so no record qualifies and
    the byte-exact fixture lays out no extra block."""
    from h2g.goatwriter import _attack_hold_records

    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    det = detect(sid, lambda _m: None)
    assert _attack_hold_records(sid, det, max(det.instr_used, 0), 1,
                                True, True) == []
