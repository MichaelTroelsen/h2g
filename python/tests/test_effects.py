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
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import (Detection, _effect_byte_address,
                        _find_effect_routines)
from h2g.goatwriter import (DRUM_SPEED, FORMAT_GTS2, FORMAT_GTS5, RISE_SHIFT,
                            SPEED_NOTE_RELATIVE, WAVE_NOISE_GATEOFF,
                            WAVECMD_PORTADOWN, WAVECMD_PORTAUP,
                            _wavetable_entries)
from h2g.sidfile import load_sid

CORPUS = pathlib.Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")

RISE = 0x02
ARP = 0x04
DRUM = 0x01


class _FakeSid:
    """Just enough of SidFile for _wavetable_entries: one instrument record."""

    def __init__(self, effect_byte, wave=0x41):
        record = bytes([0x00, 0x00, wave, 0x00, 0x00, 0x00, 0x00, effect_byte])
        self.data = bytes(8) + record


def _entries(effect_byte, *, effects=False, rise=False, arp=False, drum=False,
             fmt=FORMAT_GTS5, speed_table=None, wave=0x41):
    det = Detection(instr_start=8, instr_stride=8,
                    effect_rise=rise, effect_arp=arp, effect_drum=drum)
    return _wavetable_entries(_FakeSid(effect_byte, wave), det, 0, effects,
                              fmt, speed_table if speed_table is not None
                              else [])


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
    assert left[1] == 0x40, "the voice's own waveform, gate released"
    assert (left[2], right[2]) == (WAVECMD_PORTADOWN, 1)
    assert table == [DRUM_SPEED], "256 units per frame == one $D401 step"
    assert left[3] == 0xFF and right[3] == 0x00, "and then stop"


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


def test_the_drum_no_longer_leads_with_a_noise_tick():
    # The inherited shape is one noise tick and then the waveform. There is no
    # such tick in the player, and on the corpus it lands on a noise frame
    # about as often as noise occurs -- chance, not information.
    assert _entries(DRUM)[0][1] == WAVE_NOISE_GATEOFF, "the original's tick"
    for on in (_entries(DRUM, effects=True, drum=True),
               _entries(DRUM, effects=True, drum=False),
               _entries(DRUM | ARP | 0x30, effects=True, drum=True, arp=True)):
        assert on[0][1] != WAVE_NOISE_GATEOFF


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
    assert left[1] == 0x40 and left[2] == 0xFF


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
    assert _detect_effects("Warhawk") == (True, True, True, True)


def test_the_players_that_read_plus_seven_differently_are_rejected():
    if not CORPUS.is_dir():
        return
    # Mega Apocalypse tests the whole byte with LDA/BEQ; Chicken Song does have
    # an AND #$02 on it, but the block swaps in noise rather than raising the
    # note, so the rise probe's `AND #$03 / BNE / INC` tail rejects it.
    assert _detect_effects("Mega_Apocalypse") == (False, False, False, False)
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
    assert _detect_effects("Mega_Apocalypse") == (False, False, False, False)
