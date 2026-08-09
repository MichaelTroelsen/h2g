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
        assert on[1][3] == (0x80 - nibble) & 0xFF
        assert on[1][4] != 0x00, "and it still loops"


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
    table = []
    left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                           speed_table=table)
    # Entries 0-1 are the two-frame noise tick, so the voice's own waveform is
    # entry 2 and the sweep starts at 3.
    assert left[0] == WAVE_NOISE_GATEOFF, "the note opens on noise"
    assert left[2] == 0x40, "the voice's own waveform, gate released"
    assert (left[3], right[3]) == (WAVECMD_PORTADOWN, 1)
    assert table == [DRUM_SPEED], "256 units per frame == one $D401 step"
    assert 0xFF in left[4:], "and then stop"


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
    assert left[0] == WAVE_NOISE_GATEOFF, "the note opens on noise"
    assert left[1] == WAVE_NOISE_GATEOFF, "for a second frame at -S1"
    assert left[2] == 0x40, "and then the voice's own waveform"


def test_the_tick_is_two_frames_at_every_call_rate():
    """Two *frames*, not two calls -- the standing per-frame/per-call rule.

    At -S{m} a frame is m calls, so the tick needs 2m of them. One delay entry
    covers the remainder, and a delay is current for `value + 1` calls
    (_wave_hold_byte), so the value is 2m - 2.
    """
    for m, want in ((1, WAVE_NOISE_GATEOFF), (2, 2), (4, 6)):
        left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                               multiplier=m)
        assert left[0] == WAVE_NOISE_GATEOFF
        assert left[1] == want, f"-S{m}"
        if m > 1:
            assert right[1] == 0x80,                 "a delay's right side is read on its final call"


def test_a_waveform_of_zero_is_noise_for_the_whole_drum():
    # $1390 `LDA $157C,X / AND #$FE / BNE` falls through to the noise store
    # when the masked waveform is zero.
    left, _ = _entries(DRUM, effects=True, drum=True, wave=0x01)
    assert left[1] == WAVE_NOISE_GATEOFF


def test_the_sweep_needs_gts5_and_a_gts2_drum_is_just_the_gate_off():
    table = []
    left, _ = _entries(DRUM, effects=True, drum=True, fmt=FORMAT_GTS2,
                       speed_table=table)
    assert table == [], "a GTS2 file stores no speed table"
    assert left[2] == 0x40 and left[3] == 0xFF,         "the tick still leads, but nothing sweeps"


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
    assert (left[3], right[3]) == (WAVECMD_PORTADOWN, 1)
    assert (left[4], right[4]) == (WAVECMD_PORTADOWN, 1), "the second step"
    assert 0xFF in left[5:], "and then stop"

    tight = _entries(DRUM, effects=True, drum=True, wave=0x41,
                     speed_table=[], min_notes={2: 12}, budget=5)[0]
    assert tight[3] == WAVECMD_PORTADOWN and tight[4] == 0xFF,         "one step is all five entries hold once the tick is there"
    assert table == [DRUM_SPEED], "both steps share the one speed entry"


def test_the_second_step_is_refused_when_the_note_could_underflow():
    """CMD_PORTADOWN has no floor, so depth is only safe where it is provable.

    Section 7.oo reverted an unbounded loop for exactly this: gplay.c:557-572
    is `cptr->freq -= speed` on an unsigned 16-bit value, and Commando's own
    content wrapped it. Note 11 is 526 units -- one step clears, two do not.
    """
    left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                           min_notes={2: 11})
    assert (left[3], right[3]) == (WAVECMD_PORTADOWN, 1), "one step still"
    assert left[4] == 0xFF and right[4] == 0x00, "and then stop"


def test_an_unknown_lowest_note_keeps_the_shipped_single_step():
    # No bound is not a high bound: an instrument no orderlist-reachable
    # pattern plays has no entry in min_played_notes, and a caller that passes
    # nothing at all must get exactly the bytes that shipped before deepening.
    for bound in (None, {}, {3: 60}):      # {3: ...} is a different instrument
        left, right = _entries(DRUM, effects=True, drum=True, wave=0x41,
                               min_notes=bound)
        assert left[4] == 0xFF and right[4] == 0x00


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
    assert right[4] == 8, "the arpeggio keeps its loop"
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
