"""The instrument effect byte (+7), and the fact that it is not a format.

H2G has always read +7 as a bit-field -- bit $01 a drum, bit $04 an arpeggio
whose interval is the high nibble -- and built a wavetable from it for every
file it converts. That reading is *Warhawk's*. Reading the byte's own consumers
out of four other players shows four different treatments:

    Warhawk               $15BD   AND #$08 / #$01 / #$02 / #$04, LSR x4
    Mega Apocalypse       $4F60   LDA / BEQ -- the whole byte, zero or not
    W.A.R. Preview        $0CF8   LDA / BEQ, then CLC / ADC
    One Man and his Droid $1501   LDA / BEQ, then AND #$E0
    Chicken Song          $15C1   AND #$02, but the block ORAs #$80 into the
                                  waveform at $D404 -- a noise swap, not pitch

Applying Warhawk's reading corpus-wide was measured, not guessed, to invent
effects: 287 frames of pitch movement in W.A.R. Preview and 256 in Mega
Apocalypse, whose originals have none at all in the traced window. So the two
bits this module adds are gated on finding the routine that reads them, bound
to the address the instrument-load routine stores +7 to.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


from h2g.detect import (Detection, _effect_byte_address,
                        _find_effect_routines)
from h2g.goatwriter import (DRUM_SPEED, FORMAT_GTS2, FORMAT_GTS5, RISE_SHIFT,
                            SPEED_NOTE_RELATIVE, WAVE_NOISE_GATEOFF,
                            WAVECMD_PORTADOWN, WAVECMD_PORTAUP,
                            _drum_steps_safe, _note_freq, _wavetable_entries)
from h2g.patterns import min_played_notes
from h2g.sidfile import load_sid

CORPUS = _CORPUS

RISE = 0x02
ARP = 0x04
DRUM = 0x01


class _FakeSid:
    """Just enough of SidFile for _wavetable_entries: one instrument record."""

    def __init__(self, effect_byte, wave=0x41):
        record = bytes([0x00, 0x00, wave, 0x00, 0x00, 0x00, 0x00, effect_byte])
        self.data = bytes(8) + record


def _entries(effect_byte, *, effects=False, rise=False, arp=False, drum=False,
             fmt=FORMAT_GTS5, speed_table=None, wave=0x41, multiplier=1,
             min_notes=None, budget=None):
    det = Detection(instr_start=8, instr_stride=8,
                    effect_rise=rise, effect_arp=arp, effect_drum=drum)
    kw = {} if budget is None else {"budget": budget}
    return _wavetable_entries(_FakeSid(effect_byte, wave), det, 0, effects,
                              fmt, speed_table if speed_table is not None
                              else [], multiplier, min_notes, **kw)


# --- the fabricated octave arpeggio ----------------------------------------

def test_a_zero_nibble_arpeggio_is_silent_in_the_player():
    # $13DB stores the high nibble into the operand of the SBC at $13F4, so a
    # nibble of zero subtracts zero: both halves of the alternation play the
    # same note. The original substituted $74 -- a +12 relative note -- for a
    # zero nibble, inventing an octave arpeggio for half of every arpeggio
    # instrument in the corpus (315 of 660 records).
    off = _entries(ARP)                                  # inherited behaviour
    on = _entries(ARP, effects=True, arp=True)
    assert off[1][3] == 0x0C, "the original's +12 relative note"
    assert on[1][3] == 0x00, "no second arpeggio step"
    assert on[1][4] == 0x00, "and no loop back to it"


def test_a_real_interval_is_kept_and_is_a_negative_relative_note():
    # readme.txt:795 -- right side $60-$7F is a negative relative note, so a
    # nibble of 4 is $80-4 == $7C, four semitones down, matching SBC #$04.
    for nibble in (1, 4, 0x0C, 0x0F):
        on = _entries(ARP | (nibble << 4), effects=True, arp=True)
        # Entry 2, not 3, since v0.5.197: the player's alternation lands on the
        # note's *third* call (`1D46 1D46 3A8C 1D46 3A8C`), and carrying it on
        # entry 3 delayed the first swing by one, which measured as an onset at
        # frame 3+ against the player's 1-2 on 15 of 24 corpus files.
        assert on[1][2] == (0x80 - nibble) & 0xFF
        assert on[1][3] != 0x00, "and it still loops"
        assert on[0][3] == 0xFF, "...from a jump, one entry earlier than before"


def test_the_arpeggio_is_dropped_where_the_player_has_no_such_routine():
    # det.effect_arp false: we do not know what +7 means in that player, so
    # nothing is synthesized from it. 544 of the 683 corpus records that set
    # the bit are in such a file, and the inherited reading arpeggiates all of
    # them -- the larger half of this function's error.
    on = _entries(ARP | 0x30, effects=True, arp=False)
    assert on == _entries(0x00), "the same as a record with no bits set"
    assert on[0][3] == 0xFF and on[1][4] == 0x00, "no loop back"


# --- the chromatic rise -----------------------------------------------------

def test_the_rise_becomes_a_looping_note_relative_portamento():
    table = []
    left, right = _entries(RISE, effects=True, rise=True, speed_table=table)
    assert left[2] == WAVECMD_PORTAUP
    assert right[2] == 1, "1-based speed table index"
    assert table == [(SPEED_NOTE_RELATIVE, RISE_SHIFT)]
    # Entry 4 jumps back to entry 3 -- instrument 0's entries are 1-based
    # 6..10, so its third is 8 -- making the portamento repeat every frame.
    assert left[3] == 0xFF and right[3] == 8


def test_one_speed_table_entry_serves_every_rising_instrument():
    table = []
    for _ in range(4):
        _entries(RISE, effects=True, rise=True, speed_table=table)
    assert table == [(SPEED_NOTE_RELATIVE, RISE_SHIFT)]


def test_the_rise_needs_gts5_because_gts2_stores_no_speed_table():
    # A GTS2 loader builds its speed table from instrument vibrato bytes and
    # pattern command columns only (gsong.c:285, :311-321) and reads the
    # wavetable verbatim, so an index written here would name whatever entry
    # happened to land at that position.
    table = []
    left, _ = _entries(RISE, effects=True, rise=True, fmt=FORMAT_GTS2,
                       speed_table=table)
    assert left[2] != WAVECMD_PORTAUP
    assert table == []


def test_the_rise_is_not_emitted_where_the_player_has_no_such_routine():
    assert _entries(RISE, effects=True, rise=False) == _entries(RISE)


def test_an_arpeggio_wins_over_a_rise_on_the_same_instrument():
    # Both bits set: the player runs the rise and then the arpeggio overwrites
    # the frequency, so the arpeggio is what is heard. One wavetable stream
    # cannot carry both -- a note-setting entry ends the portamento.
    left, _ = _entries(RISE | ARP | 0x30, effects=True, rise=True, arp=True)
    assert left[2] != WAVECMD_PORTAUP


def test_effects_off_changes_nothing_at_all():
    # The gate is --effects, not detection: with the option off, a file whose
    # player has every routine still gets the VB6 shape byte for byte. That is
    # what keeps the Commando fixture exact.
    for byte in (0x00, DRUM, RISE, ARP, DRUM | RISE | ARP, 0xC4, 0x3F):
        assert _entries(byte, rise=True, arp=True, drum=True) == \
            _entries(byte)


# --- the drum ---------------------------------------------------------------

def test_the_drum_is_dropped_where_the_player_has_no_such_routine():
    # 159 of the 450 corpus records that set the bit are in a file with no
    # drum routine, and each got a fabricated noise tick and a released gate.
    assert _entries(DRUM, effects=True, drum=False) == _entries(0x00)


def test_the_drum_is_a_gate_off_waveform_and_a_downward_sweep():
    # $1390 `LDA $157C,X / AND #$FE` -- the voice's own waveform with the gate
    # released -- and $1387 `LDA counter / DEC counter / STA $D401,Y`, the
    # frequency high byte falling one step per frame.
    # budget 8: the tick's four entries plus a stop fill the old fixed five
    # exactly, so a sweep needs the room the variable-length layout supplies.
    table = []
    left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                           speed_table=table, budget=8)
    # Entry 0 is the note's own waveform, 1-2 the noise tick, 3 the gate-off
    # waveform, and the sweep starts at 4.
    assert left[1] == 0x81, "the tick, keeping the gate bit"
    assert left[3] == 0x40, "the voice's own waveform, gate released"
    assert (left[4], right[4]) == (WAVECMD_PORTADOWN, 1)
    assert table == [DRUM_SPEED], "256 units per frame == one $D401 step"
    assert 0xFF in left[5:], "and then stop"


def test_the_noise_ending_is_measured_and_rejected():
    """The one part of the drum block that is not written.

    $139D does end the drum on `LDA #$80 / STA $D404,Y`, but Goattracker
    latches the last waveform of a gated-off voice until the next note, so a
    noise entry at the end of the table stands for the whole rest of the note
    while the player stops writing $D404 when its counter runs out. Emitting
    it costs 2.4 points of corpus wave agreement and overshoots the original's
    noise frames. Ours ends on the sweep instead.
    """
    left, _ = _entries(DRUM, effects=True, drum=True, wave=0x41)
    assert WAVE_NOISE_GATEOFF not in left[2:]


def test_the_drum_leads_with_a_two_frame_noise_tick():
    """The tick is in the player, and this test used to assert it was not.

    It was removed on the reading that "there is no such tick", judged by the
    corpus `wave` metric landing on a noise frame about as often as noise
    occurs. Both the disassembly and the trace say otherwise: Warhawk $1385's
    `BCC` reaches the noise store while the remaining-duration counter is
    still large -- the START of the note, a direction section 7.ii corrected
    in v0.5.90 -- and measuring the noise run at each onset of Commando's
    original splits into 11 frames for one record (a real noise instrument)
    and exactly 2 frames for five others, over 349 onsets. See instrmap.py.
    """
    left, _ = _entries(DRUM, effects=True, drum=True, wave=0x41)
    # Entry 0 is the note's OWN waveform: the player reaches the drum block's
    # noise only on the note's second frame, which the published siddump shows
    # as `15 80 80 14 14`. This test asserted noise at entry 0 until the trace
    # said otherwise.
    assert left[0] == 0x41, "the note's own waveform first"
    assert left[1] == 0x81, "then noise, keeping the record's gate bit"
    assert left[2] == 0x81, "for a second frame at -S1"
    assert left[3] == 0x40, "and then the waveform with the gate released"


def test_the_tick_is_two_frames_at_every_call_rate():
    """Two *frames*, not two calls -- the standing per-frame/per-call rule.

    At -S{m} a frame is m calls, so the tick needs 2m of them. One delay entry
    covers the remainder, and a delay is current for `value + 1` calls
    (_wave_hold_byte), so the value is 2m - 2.
    """
    for m, want in ((1, 0x81), (2, 2), (4, 6)):
        left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                               multiplier=m)
        assert left[1] == 0x81, "the tick starts at entry 1"
        assert left[2] == want, f"-S{m}"
        if m > 1:
            assert right[2] == 0x80,                 "a delay's right side is read on its final call"


def test_a_waveform_of_zero_is_noise_for_the_whole_drum():
    # $1390 `LDA $157C,X / AND #$FE / BNE` falls through to the noise store
    # when the masked waveform is zero.
    left, _ = _entries(DRUM, effects=True, drum=True, wave=0x01)
    assert left[3] == WAVE_NOISE_GATEOFF,         "wave $01 masks to 0, so the gate-off entry falls back to noise"


def test_the_sweep_needs_gts5_and_a_gts2_drum_is_just_the_gate_off():
    table = []
    left, _ = _entries(DRUM, effects=True, drum=True, fmt=FORMAT_GTS2,
                       speed_table=table)
    assert table == [], "a GTS2 file stores no speed table"
    assert left[3] == 0x40 and left[4] == 0xFF,         "the tick still leads, but nothing sweeps"


# --- the sweep's depth ------------------------------------------------------
#
# The player sweeps for `W - 1` frames (section 7.ii); a wavetable command entry
# fires exactly once and cannot be held or repeated (gplay.c:715-724), so depth
# costs entries. The drum shape has room for two, and the second is written only
# where it provably cannot wrap.

def test_a_second_sweep_step_is_written_when_the_lowest_note_allows_it():
    # Record 0 is Goattracker instrument 2. Note index 12 is 558 units, which
    # clears two 256-unit steps with room to spare.
    # The noise tick costs two entries, so at the old fixed budget of five
    # only one sweep step fits -- the variable-length layout is what supplies
    # room for more, and it passes the real budget in.
    table = []
    left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                           speed_table=table, min_notes={2: 12}, budget=8)
    assert (left[4], right[4]) == (WAVECMD_PORTADOWN, 1)
    assert (left[5], right[5]) == (WAVECMD_PORTADOWN, 1), "the second step"
    assert 0xFF in left[6:], "and then stop"

    tight = _entries(DRUM, effects=True, drum=True, wave=0x41,
                     speed_table=[], min_notes={2: 12}, budget=5)[0]
    assert tight[4] == 0xFF,         "five entries hold the tick and the stop, and no sweep at all"
    assert table == [DRUM_SPEED], "both steps share the one speed entry"


def test_the_second_step_is_refused_when_the_note_could_underflow():
    """CMD_PORTADOWN has no floor, so depth is only safe where it is provable.

    Section 7.oo reverted an unbounded loop for exactly this: gplay.c:557-572
    is `cptr->freq -= speed` on an unsigned 16-bit value, and Commando's own
    content wrapped it. Note 11 is 526 units -- one step clears, two do not.
    """
    left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                           min_notes={2: 11}, budget=8)
    assert (left[4], right[4]) == (WAVECMD_PORTADOWN, 1), "one step still"
    assert left[5] == 0xFF and right[5] == 0x00, "and then stop"


def test_an_unknown_lowest_note_keeps_the_shipped_single_step():
    # No bound is not a high bound: an instrument no orderlist-reachable
    # pattern plays has no entry in min_played_notes, and a caller that passes
    # nothing at all must get exactly the bytes that shipped before deepening.
    for bound in (None, {}, {3: 60}):      # {3: ...} is a different instrument
        left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                               min_notes=bound, budget=8)
        assert left[5] == 0xFF and right[5] == 0x00


def test_the_bound_is_read_against_the_scaled_step_not_the_constant():
    """A rate is per frame; the table applies it per call (section 7.bb).

    _drum_speed divides the 256-unit step by the multiplier, so at -S2 two
    steps travel 256 units, not 512 -- and a note that cannot take two steps at
    -S1 can take them at -S2. Reading the bound against the constant would
    refuse the multispeed file that is in fact safe.
    """
    assert not _drum_steps_safe(2, 11, 1)
    assert _drum_steps_safe(2, 11, 2)


def test_note_freq_floors_so_the_bound_errs_safe():
    # Goattracker's table rounds where this floors, so _note_freq is never above
    # the real value -- the safe direction for a no-underflow test.
    assert _note_freq(0) == 0x0117, "GT_FREQ0, the lowest note"
    assert _note_freq(12) == 558, "one octave up, floored"
    assert _note_freq(-4) == 0, "a transpose can take a note below the table"


def test_min_played_notes_follows_a_sticky_instrument_column():
    """A quarter of the corpus's note rows name no instrument.

    They inherit whichever one a previous row last named, possibly in a previous
    pattern, so a row before the first naming row in a pattern cannot be
    attributed and must lower the bound for *every* instrument. Reading it onto
    whatever the pattern names first is how a drum's own low note gets filed
    elsewhere and the sweep deepened past what it can take.
    """
    N = 0x60
    pat = [N + 3, 0, 0, 0] + [N + 40, 2, 0, 0]
    tracks = [[0, 0xFF, 0x00]]
    assert min_played_notes(tracks, [pat])[2] == 3, \
        "the unattributable row lowers instrument 2's bound"

    pat3 = [N + 30, 2, 0, 0] + [N + 40, 3, 0, 0]
    assert min_played_notes(tracks, [pat3]) == {2: 30, 3: 40}, \
        "each instrument keeps its own lowest note"


def test_min_played_notes_applies_the_lowest_orderlist_transpose():
    """gplay.c:977-981 sets cptr->trans; :927 adds it to every note.

    A pattern played once at +0 and once at -12 sounds an octave lower the
    second time, and the bound has to be the lower of the two or the sweep is
    sized for a pitch the tune never plays that note at.
    """
    N = 0x60
    pat = [N + 30, 2, 0, 0]
    assert min_played_notes([[0, 0xFF, 0x00]], [pat])[2] == 30
    # 0xE4 - TRANSUP($F0) == -12
    assert min_played_notes([[0xE4, 0, 0xFF, 0x00]], [pat])[2] == 18
    assert min_played_notes([[0, 0xE4, 0, 0xFF, 0x00]], [pat])[2] == 18, \
        "the lowest transpose wins, not the last one"


def test_min_played_notes_ignores_a_pattern_no_orderlist_reaches():
    # An unreferenced pattern cannot lower a bound, because it never plays.
    N = 0x60
    got = min_played_notes([[0, 0xFF, 0x00]],
                           [[N + 40, 2, 0, 0], [N + 1, 2, 0, 0]])
    assert got[2] == 40


def test_min_played_notes_reads_a_restart_operand_as_a_position():
    # $FF's operand is a restart *position*, not a pattern number -- counting it
    # as one would attribute another pattern's notes to this instrument.
    N = 0x60
    got = min_played_notes([[0, 0xFF, 0x01]],
                           [[N + 40, 2, 0, 0], [N + 1, 2, 0, 0]])
    assert got[2] == 40, "the restart position is not a reference to pattern 1"


def test_an_arpeggio_keeps_the_pair_it_needs_over_the_deep_drum():
    # Both bits set: the player runs both blocks and the arpeggio's frequency
    # write ($13F4) lands after the drum's. Five entries cannot hold both, so
    # such a record stays on the original's shape -- 62 of the 291 drum
    # records this gate keeps.
    left, right = _entries(DRUM | ARP | 0x30, effects=True, drum=True,
                           arp=True, wave=0x41)
    # The loop target moved one entry earlier with the phase fix (v0.5.197), so
    # it is right[3] rather than right[4] and names entry 1 rather than entry 2.
    assert right[3] == 7, "the arpeggio keeps its loop"
    assert left[1] == 0x40, "and the drum says only where it starts"


# --- detection --------------------------------------------------------------

def _detect_effects(name):
    from h2g.detect import detect
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _find_effect_routines(sid, detect(sid, log=lambda m: None))


def test_warhawk_has_all_four_routines():
    if not CORPUS.is_dir():
        return
    # Warhawk is the player the +7 bit-field reading was taken from, so it is
    # the one file that must answer yes to every probe: rise, arp, drum, pulse.
    # The fifth element is the fixed arpeggio interval, 0 here: Warhawk is the
    # nibble dialect, which takes its interval from the record.
    assert _detect_effects("Warhawk") == (True, True, True, True, 0)


def test_the_players_that_read_plus_seven_differently_are_rejected():
    if not CORPUS.is_dir():
        return
    # Mega Apocalypse tests the whole byte with LDA/BEQ; Chicken Song does have
    # an AND #$02 on it, but the block swaps in noise rather than raising the
    # note, so the rise probe's `AND #$03 / BNE / INC` tail rejects it.
    assert _detect_effects("Mega_Apocalypse") == (False, False, False, False, 0)
    assert _detect_effects("Chicken_Song")[0] is False


def test_a_bit_can_be_tested_without_the_block_being_warhawks():
    """The distinction the probes exist to draw.

    Mega Apocalypse ANDs $01, $02 and $04 against its own effect byte and
    matches none of the four blocks -- so "the player tests this bit" and
    "the player means what Warhawk means by it" are different questions, and
    only the second one licenses fabricating an effect.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect
    from h2g.search import search_file
    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    det = detect(sid, log=lambda m: None)
    addr, zp = _effect_byte_address(sid, det)
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    tested = [b for b in (0x01, 0x02, 0x04, 0x08)
              if search_file(sid.data, f"{load} 29 {b:02X}") >= 1]
    assert tested == [0x01, 0x02, 0x04]
    assert _detect_effects("Mega_Apocalypse") == (False, False, False, False, 0)


def test_the_noise_tick_length_is_derived_but_not_yet_wired():
    """v0.5.191. `run = gate - 1` is the mechanism behind the hardcoded 2: the
    drum's "first vbl" test compares against a length that decrements once per
    duration *unit*, and the note's own first frame is spent by the init path.
    Exact on 22 of the 25 corpus files with a drum and a pitched record.

    It is read and not wired, because wiring it measured flat -- 26 of 29 drum
    instruments match the original's run either way. The sweep was the first
    suspect and is exonerated: both tick settings at budget 5 and again at
    budget 8 gave identical counts. What the derived tick does is move the noise
    a frame earlier relative to siddump's gate-edge attack, so the two settings
    are measured on different populations. This test pins the reading and the
    fact that nothing consumes it, so the next attempt starts from there rather
    than from the wrong suspect.
    """
    from h2g.convert import _detect_tables
    from h2g.goatwriter import _drum_entries, _noise_tick_frames
    from h2g.sidfile import load_sid
    import pathlib
    fixture = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"
    sid, det = _detect_tables(load_sid(str(fixture)), lambda *a, **k: None)
    # Commando's gate is 3, so the derived value equals the constant -- which is
    # why the fixture and the drum a listener validated by ear are unaffected.
    assert _noise_tick_frames(sid, det) == 2
    # ...and a 1-frame tick emits one noise entry, not zero.
    left, _ = _drum_entries(0x41, "gts5", [], 1, min_note=40, sustain=0,
                            budget=5, tick_frames=1)
    assert left[:3] == [0x41, 0x81, 0x40]


# --- v0.5.200: the release the player destroys -------------------------------

def test_the_cut_routine_is_read_and_not_assumed():
    """Gate-clear *then* zero both envelope registers. The bare
    `LDA #$00 / STA $D405 / STA $D406` also matches an init routine clearing
    the chip at startup, which says nothing about how notes end -- it appears
    in 9 further files this deliberately does not claim.
    """
    from h2g.detect import ENVELOPE_CUT_SHAPES, find_envelope_cut

    class _S:
        def __init__(self, data):
            self.data = data
    body = bytes.fromhex("29FE9904D4A9009905D49906D4")
    assert find_envelope_cut(_S(b"\x00" + body))
    assert not find_envelope_cut(_S(b"\x00" + bytes.fromhex(
        "A9009905D49906D4"))), "the gate-clear is part of the shape"
    assert len(ENVELOPE_CUT_SHAPES) == 2, "Y- and X-indexed"


def _sr(sid, det, **kw):
    """The emitted sustain/release byte of the one real record.

    Located by its attack/decay byte rather than by a fixed offset -- the
    Clear Voice slot's name field is 16 bytes, and an arithmetic guess at it
    read the name instead and reported no change at all.
    """
    from h2g.goatwriter import _write_instruments
    out = bytearray()
    _write_instruments(out, sid, det, 2, {}, False, False, {}, {}, lead=1, **kw)
    at = out.index(0x29, 10)
    return out[at + 1]


def test_the_release_nibble_is_dropped_and_the_sustain_is_not():
    """The cut destroys the envelope at the note's end; it says nothing about
    the level the note holds at while it plays."""
    from h2g.detect import Detection
    from h2g.goatwriter import _write_instruments

    class _S:
        data = bytes([0x00, 0x00, 0x41, 0x29, 0x5F, 0x00, 0x00, 0x00])
    det = Detection(instr_start=0, instr_stride=8, envelope_cut=True)
    assert _sr(_S(), det, cut_release=True) == 0x50
    assert _sr(_S(), det, cut_release=False) == 0x5F, "off by default"


def test_a_player_without_the_routine_keeps_its_release():
    from h2g.detect import Detection
    from h2g.goatwriter import _write_instruments

    class _S:
        data = bytes([0x00, 0x00, 0x41, 0x29, 0x5F, 0x00, 0x00, 0x00])
    det = Detection(instr_start=0, instr_stride=8, envelope_cut=False)
    assert _sr(_S(), det, cut_release=True) == 0x5F,         "62 corpus files have no cut routine"


def test_an_instrument_whose_effect_runs_every_frame_keeps_its_release():
    """v0.5.201. The cut is one write on the note's last row; an effect routine
    that runs every frame overwrites it, so that instrument's release survives
    and is audible. v0.5.200 zeroed every record of a cut-routine file and
    destroyed Commando's drums -- reported by ear, and in the trace all along:
    records 1, 7 and 12 hold their envelope across the whole gap.
    """
    from h2g.detect import Detection
    from h2g.goatwriter import EFFECT_PER_FRAME

    class _S:
        def __init__(self, eff):
            self.data = bytes([0x00, 0x00, 0x41, 0x29, 0x5F, 0x00, 0x00, eff])
    det = Detection(instr_start=0, instr_stride=8, envelope_cut=True)
    assert EFFECT_PER_FRAME == 0x01
    assert _sr(_S(0x00), det, cut_release=True) == 0x50, "no effect -> cut"
    assert _sr(_S(0x08), det, cut_release=True) == 0x50, "$08 is not per-frame"
    assert _sr(_S(0x01), det, cut_release=True) == 0x5F, "the drum keeps it"
    assert _sr(_S(0x05), det, cut_release=True) == 0x5F, "drum + arp"


# --- v0.5.202: the tie flag -------------------------------------------------

def _decoded(status_bytes, tie):
    """Decode a synthetic classic pattern: (status, operand?, note) events."""
    from h2g.patterns import _build_raw_pattern
    # addr must exceed 1: the decoder rejects `addr + i2 <= 1` outright.
    data = bytes([0x00, 0x00]) + bytes(status_bytes) + bytes([0xFF])
    return _build_raw_pattern(data, 2, tie=tie)


def test_the_note_after_a_tied_event_becomes_a_toneporta_with_no_speed():
    """Status bit 5 means the player never closes the gate at that note's end
    (Commando $517F), so the next note arrives with the gate open and only
    changes frequency. `CMD_TONEPORTA` with parameter 0 is exactly that:
    gplay.c:811 assigns `freq = targetfreq` in one call, :930 skips the
    hard-restart gate-off *because* the command is TONEPORTA, and :355 skips the
    firstwave testbit for the same reason.
    """
    # a tied event (bit 5, wait 1, no operand), then a plain note
    ev = _decoded([0x21, 0x30, 0x01, 0x34], tie=True)
    rows = [ev[i:i + 4] for i in range(0, len(ev), 4)]
    assert rows[0][2] == 0, "the tied event itself is not the landing"
    landing = rows[2]
    assert landing[2] == 3 and landing[3] == 0, rows
    # ...and the toneporta is not repeated on the landing note's hold rows
    assert rows[3][2] == 0, rows


def test_it_is_the_following_note_and_not_the_tied_event_itself():
    """The original attacks *on* the slide event and glides; it is the landing
    that must not re-attack. Placing the command on the tied row instead would
    remove the attack that is really there."""
    ev = _decoded([0x21, 0x30, 0x01, 0x34], tie=True)
    assert [ev[i + 2] for i in range(0, len(ev), 4)][:3] == [0, 0, 3]


def test_a_second_note_after_the_landing_is_untouched():
    ev = _decoded([0x21, 0x30, 0x01, 0x34, 0x01, 0x38], tie=True)
    cmds = [ev[i + 2] for i in range(0, len(ev), 4)]
    assert cmds.count(3) == 1, cmds
    assert cmds[2] == 3, cmds


def test_off_by_default_so_the_fixture_is_untouched():
    ev = _decoded([0x21, 0x30, 0x01, 0x34], tie=False)
    assert all(ev[i + 2] != 3 for i in range(0, len(ev), 4))
    from h2g.convert import convert
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    assert convert(str(root / "Commando.sid"), log=lambda m: None) == \
        (root / "Commando.sng").read_bytes()


# --- v0.5.207: effect bit $10, the pitch sequence ---------------------------

@needs_corpus
def test_the_pitch_sequence_reads_three_tables_and_a_global_phase():
    """`note = played note + seq[phase]`, in 34 of 95 files. seq[0] is a byte
    nothing writes (0 everywhere checked) and seq[1..2] are the instrument's own
    pair; the phase is a global counter, not per note.
    """
    from corpus import CORPUS
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    if not CORPUS.is_dir():
        return
    sid, det = _detect_tables(
        load_sid(str(CORPUS / "Trans-Atlantic_Balloon_Challenge.sid")),
        lambda *a: None)
    seq = det.pitch_seq
    assert seq is not None and seq.steps == 3
    # the index array is `wave_program` again -- a pointer low byte under $08, a
    # note index under $40, a sequence index under $10. One cell, three meanings.
    assert seq.index == det.wave_program
    idx = sid.data[seq.index + 0 * det.instr_stride]
    assert [sid.data[seq.base], sid.data[seq.pairs + 2 * idx],
            sid.data[seq.pairs + 2 * idx + 1]] == [0, 24, 0]


def test_an_all_zero_sequence_emits_nothing():
    """Three identical entries are not an arpeggio, they are the note."""
    from h2g.detect import Detection, PitchSeq
    from h2g.goatwriter import _pitch_seq_entries

    class _S:
        data = bytes([0, 0, 0x41, 0x0A, 0x99, 0, 0, 0x10]) + bytes(16)
    det = Detection(instr_start=0, instr_stride=8,
                    pitch_seq=PitchSeq(index=8, pairs=10, base=9))
    assert _pitch_seq_entries(_S(), det, 0, 0x41) is None


def test_it_is_gated_on_the_record_and_on_having_a_waveform():
    from h2g.detect import Detection, PitchSeq
    from h2g.goatwriter import _pitch_seq_entries

    class _S:
        def __init__(self, eff):
            self.data = (bytes([0, 0, 0x41, 0x0A, 0x99, 0, 0, eff])
                         + bytes([0, 0, 24, 0]) + bytes(12))
    det = Detection(instr_start=0, instr_stride=8,
                    pitch_seq=PitchSeq(index=8, pairs=10, base=9))
    assert _pitch_seq_entries(_S(0x10), det, 0, 0x41) is not None
    assert _pitch_seq_entries(_S(0x00), det, 0, 0x41) is None, "$10 clear"
    assert _pitch_seq_entries(_S(0x10), det, 0, 0x00) is None, "no waveform"


def test_the_modal_step_follows_the_attack_frame():
    """The player's phase is global, so which step a note opens on is unknowable
    and a wavetable always starts at entry 0. Entry 0 sounds the pattern's note
    and the modal step goes on the frame after it -- the likeliest value under a
    uniform unknown phase. Emitting `(0, 24, 0)` as written put the two-octave
    jump one frame into every note and cost 4.2 points of mean melody.
    """
    from h2g.detect import Detection, PitchSeq
    from h2g.goatwriter import _pitch_seq_entries

    class _S:
        data = (bytes([0, 0, 0x41, 0x0A, 0x99, 0, 0, 0x10])
                + bytes([0, 0, 24, 0]) + bytes(12))
    det = Detection(instr_start=0, instr_stride=8,
                    pitch_seq=PitchSeq(index=8, pairs=10, base=9))
    _left, right = _pitch_seq_entries(_S(), det, 0, 0x41)
    assert right[0] == 0x00, "the attack sounds the pattern's note"
    assert right[1] == 0x00, "...and the modal step follows it"
    assert 0x18 in right, "the sequence's own step is still emitted"


def test_off_by_default_and_searched_per_song():
    """v0.5.208 gave `fidelity_better` an oscillation term, which is the only
    criterion that can see this setting: it strikes no new notes and sounds no
    new register. Never in `always` -- the global phase makes it a per-song
    trade, right on the balloon song and wrong on seven others."""
    import presets
    from h2g.convert import convert
    assert "pitch_seq" in presets.EXCLUDED_FROM_ALWAYS
    assert "pitch_seq" in presets.FIDELITY_TOGGLES
    root = pathlib.Path(__file__).resolve().parents[2]
    assert convert(str(root / "Commando.sid"), log=lambda m: None) == \
        (root / "Commando.sng").read_bytes()
